import io
import inspect
import ast
import json
import os
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import cloud_check as check


COOKIE = "remember_student_test=12345%7Cprivate-test-secret%7C"
ROOT = Path(__file__).resolve().parent


def response(html, path="/student/course/96755/punchs?op=ing", status=200):
    result = requests.Response()
    result.status_code = status
    result._content = html.encode("utf-8")
    result.encoding = "utf-8"
    result.url = "https://k8n.cn" + path
    return result


def config(**extra):
    return dict({"class": "96755", "cookie": [COOKIE], "lat": "23.185647",
                 "lng": "113.33389", "acc": "30", "autosubmit": True}, **extra)


SIGNED = '<div class="punch-card punch-card--success">已签到</div>'
ACTIVE = '<div class="punch-card punch-card--primary"><span>二维码签到</span><a>点此去完成签到</a></div>'
GPS = '<div class="punch-card punch-card--primary"><a id="gps_btn_123" href="/student/punchw/course/96755/123">点此去完成签到</a></div>'


class OutcomeTests(unittest.TestCase):
    def test_only_pending_task_ids_are_submitted(self):
        old = '<div class="punch-card punch-card--success"><a id="gps_btn_456">已签到</a></div>'
        output = io.StringIO()
        def get_page(url, **kwargs):
            return response(old + GPS) if "/student/course/" in url else response('<form method="post"></form>', "/student/punchw/course/96755/123")
        with patch("cloud_check.requests.get", side_effect=get_page), patch(
            "cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')
        ) as post, redirect_stdout(output):
            try:
                check.check_all_cookies(config())
            except RuntimeError:
                pass
        self.assertEqual([call.kwargs["data"]["id"] for call in post.call_args_list], ["123"])

    def test_direct_link_cannot_send_another_accounts_sid(self):
        with patch("cloud_check.requests.get", return_value=response(SIGNED, "/student/punchw/course/96755/123")) as get, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "account"):
                check.check_one_cookie(config(direct_punch_url="/student/punchw/course/96755/123?sid=67890"), COOKIE)
        get.assert_not_called()

    def test_form_cannot_forward_cookie_to_another_host(self):
        with patch("cloud_check.requests.get", side_effect=[response(GPS), response('<form method="post" action="https://example.org/collect"></form>')]), patch(
            "cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')
        ) as post, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                check.check_all_cookies(config())
        post.assert_not_called()

    def test_not_signed_is_not_signed(self):
        self.assertFalse(check.has_signed_status("<p>not signed</p>"))

    def test_cloud_source_has_no_overridden_top_level_functions(self):
        tree = ast.parse((ROOT / "cloud_check.py").read_text(encoding="utf-8"))
        names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(len(names), len(set(names)))

    def test_unsigned_text_is_not_signed(self):
        self.assertFalse(check.has_signed_status("<p>unsigned</p>"))

    def test_old_signed_card_does_not_hide_unparsed_current_task(self):
        with self.assertRaisesRegex(RuntimeError, "punch id"):
            check.raise_if_unparsed_active_task(SIGNED + ACTIVE, [], [])

    def test_verification_cannot_use_another_tasks_history(self):
        self.assertIn("punch_id", inspect.signature(check.verify_signed).parameters)
        page = response('<div class="punch-card punch-card--success" data-punch-id="456">已签到</div>')
        with patch("cloud_check.requests.get", return_value=page):
            self.assertFalse(check.verify_signed("96755", {}, punch_id="123"))

    def test_server_confirmed_success_survives_followup_timeout(self):
        pages = [response(GPS), response('<form method="post"></form>', "/student/punchw/course/96755/123")]
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch("cloud_check.requests.get", side_effect=pages + [requests.Timeout()]), patch(
            "cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')
        ), redirect_stdout(output):
            audit_path = Path(tmp) / "audit.jsonl"
            try:
                check.check_all_cookies(config(audit_log_path=str(audit_path)))
            except RuntimeError as exc:
                self.fail("Server confirmed success must not become attendance failure: " + str(exc))
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        finished = next(event for event in events if event["event"] == "account_check_finished")
        self.assertEqual(finished.get("outcome"), "submitted_confirmed")
        self.assertTrue(any(event["event"] == "verification_unavailable" for event in events))

    def test_server_rejection_is_not_overridden_by_signed_history(self):
        with patch("cloud_check.requests.get", side_effect=[response(GPS), response('<form method="post"></form>', "/student/punchw/course/96755/123"), response(SIGNED)]), patch(
            "cloud_check.requests.post", return_value=response('<div id="title">签到失败：已结束</div>')
        ), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                check.check_all_cookies(config())

    def test_mixed_accounts_have_separate_outcomes_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            env = {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_ACTIONS": "true"}
            with patch.dict(os.environ, env), patch("cloud_check.requests.get", side_effect=[response(SIGNED), response(ACTIVE), response(ACTIVE)]), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "1 of 2"):
                    check.check_all_cookies(config(cookie=[COOKIE, "remember_student_second=67890%7Csecond-secret%7C"]))
            self.assertTrue(summary.exists(), "Missing per-account GitHub summary")
            content = summary.read_text(encoding="utf-8")
        self.assertIn("already_signed", content)
        self.assertIn("needs_punch_url", content)
        self.assertIn("12345", content)
        self.assertIn("67890", content)
        self.assertNotIn("private-test-secret", content)
        self.assertNotIn("second-secret", content)

    def test_already_signed_direct_link_does_not_post_again(self):
        with patch("cloud_check.requests.get", return_value=response(SIGNED, "/student/punchw/course/96755/123")), patch(
            "cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')
        ) as post, redirect_stdout(io.StringIO()):
            check.check_one_cookie(config(direct_punch_url="/student/punchw/course/96755/123"), COOKIE)
        post.assert_not_called()

    def test_diagnostics_redact_query_secrets(self):
        output = io.StringIO()
        page = response(GPS, "/student/course/96755/punchs?token=secret-short")
        with redirect_stdout(output):
            check.print_page_diagnostics("list", page, "96755")
        self.assertNotIn("secret-short", output.getvalue())

    def test_run_has_traceable_source_and_attempt(self):
        output = io.StringIO()
        cfg = config(github_run_id="999", github_run_attempt="2", github_sha="a" * 40)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), redirect_stdout(output):
            check.write_audit_event(cfg, "run_started")
        event = json.loads(output.getvalue().split("BJMF_AUDIT ", 1)[1])
        self.assertEqual(event.get("source"), "github_actions")
        self.assertEqual(event.get("run_attempt"), "2")
        self.assertEqual(event.get("revision"), "a" * 40)
        self.assertIsInstance(event.get("pid"), int)


class LocalOutcomeTests(unittest.TestCase):
    def run_local(self, html, post_html=None):
        with tempfile.TemporaryDirectory() as tmp:
            settings = dict(config(), configLock=True, debug=False, scheduletime="", pushplus="", poll={"enabled": False})
            (Path(tmp) / "config.json").write_text(json.dumps(settings), encoding="utf-8")
            output = io.StringIO()
            with patch("os.getcwd", return_value=tmp), patch("builtins.input", return_value=""), patch("time.sleep"), patch(
                "requests.get", return_value=response(html)
            ), patch("requests.post", return_value=response(post_html or "")), redirect_stdout(output):
                runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
            path = Path(tmp) / "bjmf-audit-local.jsonl"
            self.assertTrue(path.exists(), "Local run must persist source and result with debug disabled")
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            return output.getvalue(), events

    def test_local_no_task_is_not_claimed_as_attendance_success(self):
        output, events = self.run_local("<title>用户中心</title><p>暂无签到</p>")
        self.assertNotIn("本次签到圆满成功", output)
        self.assertTrue(any(event.get("outcome") == "no_task" for event in events))
        self.assertTrue(all(event["source"] == "local_main" for event in events))

    def test_local_submission_logs_actual_server_result_without_secret(self):
        output, events = self.run_local('<title>用户中心</title><button id="punchcard_123">扫码签到</button>', '<div id="title">签到成功</div>')
        self.assertTrue(any(event["event"] == "post_attempt" for event in events))
        self.assertTrue(any(event.get("outcome") == "submitted_confirmed" for event in events))
        self.assertNotIn("private-test-secret", output + json.dumps(events))

    def test_local_rejected_submission_is_not_success_and_is_not_resent(self):
        output, events = self.run_local('<title>用户中心</title><button id="punchcard_123">扫码签到</button>', '<div id="title">签到失败：已结束</div>')
        self.assertEqual(sum(event["event"] == "post_attempt" for event in events), 1)
        self.assertTrue(any(event.get("outcome") == "submission_rejected" for event in events))
        self.assertNotIn("本次签到圆满成功", output)


if __name__ == "__main__":
    unittest.main()
