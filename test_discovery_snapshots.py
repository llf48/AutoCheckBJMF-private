"""Offline tests: sample only existing failed responses, never fetch or submit."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cloud_check as check
from cloud_config import load_cloud_config
from test_check_outcomes import ACTIVE, COOKIE, GPS, ROOT, SIGNED, config, response


class DiscoverySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "snapshots"

    def run_pages(self, pages, **extra):
        cfg = config(discovery_snapshot_dir=str(self.directory), **extra)
        output = io.StringIO()
        with patch("cloud_check.requests.get", side_effect=pages) as get, patch("cloud_check.requests.post") as post, patch("cloud_check.write_account_summary") as summary, redirect_stdout(output):
            try:
                check.check_all_cookies(cfg)
            except RuntimeError:
                pass
        rows = summary.call_args.args[0] if summary.called else []
        return get, post, rows, output.getvalue()

    def files(self):
        return sorted(self.directory.glob("*.json"))

    def test_missing_id_captures_existing_primary_and_fallback_without_requests(self):
        get, post, rows, output = self.run_pages([response(ACTIVE), response(ACTIVE)])
        self.assertEqual(get.call_count, 2)
        post.assert_not_called()
        self.assertEqual(rows[0]["outcome"], "needs_punch_url")
        self.assertEqual(len(self.files()), 2, "Both already-fetched failure pages must be retained")
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in self.files()]
        self.assertEqual({d["page"] for d in docs}, {"active_list", "fallback_list"})
        self.assertTrue(all(d["account"] == 1 and d["reason"] == "missing_punch_id" for d in docs))
        self.assertIn("discovery_snapshot_saved", output)

    def test_keep_structure_not_private_values_or_executable_html(self):
        html = ACTIVE.replace("<a>", '''<a onclick="beginJoin(987654, {attendanceId: 987654, csrf: 'tiny-secret'})" data-attendance='{"attendanceId":987654,"owner":"AlicePrivate","token":"short-secret"}'>''')
        html += '''<form><input type="hidden" name="attendanceKey" value="hidden-secret"></form>
        <p>AlicePrivate 13800138000 alice-private@example.test</p>
        <script>var token = unquotedSecret; wx.scanQRCode({success: function(res) { beginJoin(res.resultStr); }});
        var settings = {"attendanceId":987654,"url":"/student/attendance/start?token=tiny-secret&sid=12345"};
        </script><script src="https://assets.example.test/js/punch.js?token=asset-secret"></script>'''
        self.run_pages([response(html), response(html)])
        self.assertEqual(len(self.files()), 2)
        text = self.files()[0].read_text(encoding="utf-8")
        for private in ("tiny-secret", "short-secret", "hidden-secret", "asset-secret", "unquotedSecret", "AlicePrivate", "13800138000", "alice-private@example.test", "987654", "12345", COOKIE, "<script", "assets.example.test"):
            with self.subTest(private=private):
                self.assertNotIn(private, text)
        for structural in ("attendanceId", "attendanceKey", "beginJoin", "wx.scanQRCode", "hidden", "query_keys"):
            with self.subTest(structural=structural):
                self.assertIn(structural, text)

    def test_only_failing_account_is_sampled(self):
        other = "remember_student_other=54321%7Cother-fake-token%7C"
        get, post, rows, _ = self.run_pages([response(SIGNED), response(ACTIVE), response(ACTIVE)], cookie=[COOKIE, other])
        self.assertEqual(get.call_count, 3)
        post.assert_not_called()
        self.assertEqual([r["outcome"] for r in rows], ["already_signed", "needs_punch_url"])
        self.assertEqual(len(self.files()), 2)
        self.assertTrue(all(json.loads(p.read_text(encoding="utf-8"))["account"] == 2 for p in self.files()))

    def test_no_sampling_on_signed_no_task_cooldown_or_valid_read_only_task(self):
        for html in (SIGNED, "<p>暂无签到</p>", "<p>账号冷却，请等待</p>", GPS):
            with self.subTest(html=html):
                get, post, _, _ = self.run_pages([response(html)], autosubmit=False)
                self.assertEqual(get.call_count, 1)
                post.assert_not_called()
                self.assertFalse(self.files())

    def test_snapshot_failure_does_not_replace_original_error_or_block_next_account(self):
        self.directory.write_text("not a directory", encoding="utf-8")
        other = "remember_student_other=54321%7Cother-fake-token%7C"
        get, post, rows, output = self.run_pages([response(ACTIVE), response(ACTIVE), response(SIGNED)], cookie=[COOKIE, other])
        self.assertEqual(get.call_count, 3)
        post.assert_not_called()
        self.assertEqual([r["outcome"] for r in rows], ["needs_punch_url", "already_signed"])
        self.assertIn("discovery_snapshot_error", output)
        self.assertNotIn("not a directory", output)

    def test_existing_successful_fallback_does_not_generate_failure_sample(self):
        get, post, rows, _ = self.run_pages([response(ACTIVE), response(GPS)], autosubmit=False)
        self.assertEqual(get.call_count, 2)
        post.assert_not_called()
        self.assertEqual(rows[0]["outcome"], "dry_run")
        self.assertFalse(self.files())

    def test_keep_failed_primary_if_fallback_enters_cooldown(self):
        get, post, rows, _ = self.run_pages([response(ACTIVE), response("<p>账号冷却，请等待</p>")])
        self.assertEqual(get.call_count, 2)
        post.assert_not_called()
        self.assertEqual(rows[0]["outcome"], "cooldown")
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(json.loads(self.files()[0].read_text(encoding="utf-8"))["page"], "active_list")

    def test_sample_count_and_size_are_bounded(self):
        html = ACTIVE + '<input name="attendanceKey" value="big-private-value">' * 1200
        self.run_pages([response(html), response(html)])
        self.run_pages([response(html), response(html)])
        self.assertEqual(len(self.files()), 2)
        for path in self.files():
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertLessEqual(path.stat().st_size, 262144)
            self.assertTrue(doc["truncated"])
            self.assertLessEqual(len(doc["nodes"]), 160)
            self.assertNotIn("big-private-value", path.read_text(encoding="utf-8"))

    def test_comment_and_template_strings_do_not_leak_private_literals(self):
        html = ACTIVE + r'''<script>// beginJoin('comment-secret')
        /* hiddenKey: 'block-secret' */
        var cfg = `template-secret ${123456}`;
        beginJoin({attendanceId: 987654, payload: 'escaped\'secret'});
        </script>'''
        self.run_pages([response(html), response(html)])
        self.assertEqual(len(self.files()), 2)
        text = self.files()[0].read_text(encoding="utf-8")
        for private in ("comment-secret", "block-secret", "template-secret", "123456", "987654", "escaped"):
            self.assertNotIn(private, text)

    def test_json_wrapped_in_script_string_keeps_keys_but_not_values(self):
        payload = json.dumps({"attendanceId": 987654, "token": "embedded-secret"})
        html = ACTIVE + '<script>window.state = JSON.parse(' + json.dumps(payload) + ');</script>'
        self.run_pages([response(html), response(html)])
        self.assertEqual(len(self.files()), 2)
        text = self.files()[0].read_text(encoding="utf-8")
        self.assertIn("attendanceId", text)
        self.assertIn("embedded_data", text)
        self.assertNotIn("embedded-secret", text)
        self.assertNotIn("987654", text)

    def test_config_enables_snapshot_directory_only_when_set(self):
        env = {"BJMF_CLASS_ID": "96755", "BJMF_LAT": "23", "BJMF_LNG": "113", "BJMF_ACC": "30", "BJMF_COOKIE": COOKIE,
               "BJMF_DISCOVERY_DIR": str(self.directory)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_cloud_config().get("discovery_snapshot_dir"), str(self.directory))
        env.pop("BJMF_DISCOVERY_DIR")
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_cloud_config().get("discovery_snapshot_dir"), "")

    def test_both_workflows_upload_json_samples_even_when_check_fails(self):
        for name in ("AutoCheckBJMF.yml", "BJMFManualForceCheck.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertIn('BJMF_DISCOVERY_DIR: "bjmf-discovery"', text)
                self.assertIn("name: bjmf-discovery-${{ github.run_id }}-${{ github.run_attempt }}", text)
                block = text.split("- name: Upload sanitized discovery snapshots", 1)[1]
                self.assertIn("if: always()", block)
                self.assertIn("path: bjmf-discovery/*.json", block)
                self.assertIn("retention-days: 7", block)


if __name__ == "__main__":
    unittest.main()
