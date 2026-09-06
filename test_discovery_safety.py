"""Offline regressions for discovery, account isolation, and safe diagnostics."""
import io
import json
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cloud_check as check
from test_check_outcomes import ACTIVE, COOKIE, GPS, ROOT, SIGNED, config, response


class DiscoverySafetyTests(unittest.TestCase):
    def assert_not_submitted(self, html):
        with patch("cloud_check.requests.get", return_value=response(html)), patch("cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')) as post, redirect_stdout(io.StringIO()):
            try:
                check.check_all_cookies(config())
            except RuntimeError:
                pass
        post.assert_not_called()

    def test_foreign_course_link_is_not_rewritten_into_a_local_task(self):
        self.assert_not_submitted(ACTIVE.replace('<a>', '<a href="/student/punchscan/course/999/321">'))

    def test_foreign_origin_link_is_not_rewritten_into_a_local_task(self):
        self.assert_not_submitted(ACTIVE.replace('<a>', '<a href="https://example.org/student/punchscan/course/96755/321">'))

    def test_ended_card_is_not_submitted(self):
        self.assert_not_submitted('<div class="punch-card" data-punch-id="321">二维码签到 已结束</div>')

    def test_scan_route_is_discovered_without_a_legacy_button_id(self):
        html = ACTIVE.replace('<a>', '<a href="/student/punchscan/course/96755/321">')
        with patch("cloud_check.requests.get", return_value=response(html)), patch("cloud_check.requests.post") as post, redirect_stdout(io.StringIO()):
            try:
                found = check.check_one_cookie(config(autosubmit=False), COOKIE)
            except RuntimeError as exc:
                self.fail("A valid scan submission URL must be discovered: " + str(exc))
        self.assertEqual(found, 1)
        post.assert_not_called()

    def test_explicit_punch_attribute_is_recognized(self):
        html = ACTIVE.replace('punch-card--primary"', 'punch-card--primary" data-punch-id="321"')
        gps, scan = check.extract_punch_ids(html)
        self.assertIn("321", gps + scan)

    def test_hidden_punch_id_is_recognized_but_generic_id_is_not(self):
        html = '<form method="post"><input name="punch_id" value="321"><input name="student_id" value="999"></form>'
        gps, scan = check.extract_punch_ids(html)
        self.assertEqual(gps + scan, ["321"])

    def test_escaped_json_submission_url_is_recognized(self):
        html = r'<script>{"url":"https:\/\/k8n.cn\/student\/punchscan\/course\/96755\/321?token=abc"}</script>'
        self.assertEqual(check.extract_submit_urls(html, "96755").get("321"),
                         "https://k8n.cn/student/punchscan/course/96755/321?token=abc")

    def test_html_entities_do_not_corrupt_submission_query(self):
        html = '<a href="/student/punchw/course/96755/321?sid=12345&amp;token=abc">签到</a>'
        self.assertEqual(check.extract_submit_urls(html, "96755")["321"],
                         "https://k8n.cn/student/punchw/course/96755/321?sid=12345&token=abc")

    def test_diagnostics_prioritize_action_over_outer_wrappers(self):
        html = '<div class="wrapper">' * 20 + '<a data-punch-id="321">点此去完成签到</a>' + '</div>' * 20
        hints = check.get_active_structure_hints(html)
        self.assertTrue(any(hint["tag"] == "a" for hint in hints))

    def test_diagnostics_never_include_arbitrary_attribute_values(self):
        html = '<a data-punch-id="321" data-token="tiny-secret" onclick="go(\'inline-secret\')">点此去完成签到</a>'
        self.assertNotIn("tiny-secret", json.dumps(check.get_active_structure_hints(html)))
        self.assertNotIn("inline-secret", json.dumps(check.get_active_structure_hints(html)))

    def test_missing_id_records_account_scoped_page_evidence(self):
        output = io.StringIO()
        with patch("cloud_check.requests.get", return_value=response(ACTIVE)), redirect_stdout(output):
            with self.assertRaises(RuntimeError):
                check.check_all_cookies(config())
        events = [json.loads(line[11:]) for line in output.getvalue().splitlines() if line.startswith("BJMF_AUDIT ")]
        pages = [event for event in events if event["event"] == "page_observed"]
        self.assertTrue(pages, "Missing a durable record of the page that could not be parsed")
        self.assertTrue(all(event["student_id"] == "12345" for event in pages))
        self.assertRegex(pages[0]["html_sha256"], r"^[0-9a-f]{64}$")

    def test_unparsed_qr_task_keeps_a_cross_account_time_reference(self):
        html = ACTIVE.replace('<span>', '<div>2026-09-03 09:25:41 开始</div><span>')
        output = io.StringIO()
        with redirect_stdout(output):
            check.print_page_diagnostics("list", response(html), "96755", config())
        events = [json.loads(line[11:]) for line in output.getvalue().splitlines() if line.startswith("BJMF_AUDIT ")]
        self.assertIn("tasks", events[0])
        self.assertEqual(events[0]["tasks"][0]["times"], ["2026-09-03 09:25:41"])
        self.assertEqual(events[0]["tasks"][0]["kind"], "qr")

    def test_already_signed_post_response_is_not_a_precheck_result(self):
        with patch("cloud_check.requests.get", side_effect=[response(GPS), response('<form method="post"></form>', "/student/punchw/course/96755/123"), response(SIGNED), response(SIGNED)]), patch("cloud_check.requests.post", return_value=response('<div id="title">已经签到</div>')), patch("cloud_check.write_account_summary") as summary, redirect_stdout(io.StringIO()):
            check.check_all_cookies(config())
        row = summary.call_args.args[0][0]
        self.assertEqual(row["outcome"], "server_already_signed")
        self.assertEqual(row["post_attempts"], 1)

    def test_cooldown_is_distinct_from_cookie_expiry(self):
        with patch("cloud_check.requests.get", return_value=response('<p>账号冷却，请等待</p>')) as get, redirect_stdout(io.StringIO()), patch("cloud_check.write_account_summary") as summary:
            with self.assertRaises(RuntimeError):
                check.check_all_cookies(config())
        self.assertEqual(get.call_count, 1)
        self.assertEqual(summary.call_args.args[0][0]["outcome"], "cooldown")

    def test_login_redirect_is_classified_without_following_it(self):
        page = response('', status=302)
        page.headers["Location"] = "https://open.weixin.qq.com/connect/oauth2/authorize?token=private"
        with patch("cloud_check.requests.get", return_value=page) as get, redirect_stdout(io.StringIO()), patch("cloud_check.write_account_summary") as summary:
            with self.assertRaises(RuntimeError):
                check.check_all_cookies(config())
        self.assertFalse(get.call_args.kwargs.get("allow_redirects", True))
        self.assertEqual(summary.call_args.args[0][0]["outcome"], "login_required")

    def test_blank_page_is_not_reported_as_no_task(self):
        with patch("cloud_check.requests.get", return_value=response('')), redirect_stdout(io.StringIO()), patch("cloud_check.write_account_summary") as summary:
            try:
                check.check_all_cookies(config())
            except RuntimeError:
                pass
        self.assertEqual(summary.call_args.args[0][0]["outcome"], "unrecognized_page")

    def test_valid_task_is_not_blocked_by_an_unrelated_unparsed_card(self):
        def get_page(url, **kwargs):
            return response(ACTIVE + GPS) if "/student/course/" in url else response('<form method="post"></form>', "/student/punchw/course/96755/123")
        with patch("cloud_check.requests.get", side_effect=get_page), patch("cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')) as post, patch("cloud_check.write_account_summary") as summary, redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                check.check_all_cookies(config())
        self.assertEqual([call.kwargs["data"]["id"] for call in post.call_args_list], ["123"])
        self.assertEqual(summary.call_args.args[0][0]["outcome"], "partial_failure")
        self.assertEqual(summary.call_args.args[0][0]["confirmed"], 1)

    def test_form_cannot_switch_the_task_id(self):
        form = response('<form method="post" action="/student/punchw/course/96755/456"></form>', "/student/punchw/course/96755/123")
        with patch("cloud_check.requests.get", return_value=form), patch("cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')) as post, redirect_stdout(io.StringIO()):
            try:
                check.post_punch(config(), check.get_headers("96755", COOKIE), "123", form.url)
            except RuntimeError:
                pass
        post.assert_not_called()

    def test_post_cannot_bypass_read_only_mode(self):
        with patch("cloud_check.requests.get", return_value=response('<form method="post"></form>', "/student/punchw/course/96755/123")), patch("cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')) as post, redirect_stdout(io.StringIO()):
            try:
                check.post_punch(config(autosubmit=False), check.get_headers("96755", COOKIE), "123", "https://k8n.cn/student/punchw/course/96755/123")
            except RuntimeError:
                pass
        post.assert_not_called()

    def test_server_error_after_post_is_unknown_not_no_submission(self):
        with patch("cloud_check.requests.get", side_effect=[response(GPS), response('<form method="post"></form>', "/student/punchw/course/96755/123")]), patch("cloud_check.requests.post", return_value=response('server error', status=500)), patch("cloud_check.write_account_summary") as summary, redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                check.check_all_cookies(config())
        self.assertEqual(summary.call_args.args[0][0]["outcome"], "submission_unknown")

    def test_uncertain_post_can_be_confirmed_by_exact_task_without_resending(self):
        import requests
        signed = response('<div class="punch-card punch-card--success" data-punch-id="123">已签到</div>')
        for result in (response('', status=302), requests.Timeout('response lost')):
            with self.subTest(result=type(result).__name__), patch("cloud_check.requests.get", side_effect=[response(GPS), response('<form method="post"></form>', "/student/punchw/course/96755/123"), signed]), patch("cloud_check.requests.post", side_effect=[result]) as post, patch("cloud_check.write_account_summary") as summary, redirect_stdout(io.StringIO()):
                try:
                    check.check_all_cookies(config())
                except RuntimeError as exc:
                    self.fail("Exact task verification should resolve an uncertain POST: " + str(exc))
                self.assertEqual(post.call_count, 1)
                self.assertEqual(summary.call_args.args[0][0]["outcome"], "submitted_confirmed")

    def test_both_workflows_share_a_lock_and_offer_read_only_checks(self):
        workflows = [(ROOT / ".github/workflows" / name).read_text(encoding="utf-8") for name in ("AutoCheckBJMF.yml", "BJMFManualForceCheck.yml")]
        groups = [re.search(r"(?m)^  group: (.+)$", text).group(1) for text in workflows]
        self.assertEqual(groups[0], groups[1])
        for text in workflows:
            self.assertIn("dry_run:", text)
            self.assertRegex(text, r"BJMF_AUTOSUBMIT:.*dry_run")


if __name__ == "__main__":
    unittest.main()
