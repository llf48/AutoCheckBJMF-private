"""Offline regressions for status evidence and cross-run account backoff."""
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

OTHER_COOKIE = "remember_student_other=54321%7Cother-test-secret%7C"


class SignedEvidenceTests(unittest.TestCase):
    def test_signed_counters_are_not_personal_status(self):
        for marker in ("已签到人数：0", "已签到人数：12", "已签到率：100%", "尚未签到", "签到成功后请离开"):
            with self.subTest(marker=marker):
                self.assertFalse(check.has_signed_status("<p>" + marker + "</p>"))

    def test_hidden_labels_are_not_status(self):
        for attrs in ('hidden', 'style="display: none !important"', 'style="visibility:hidden"', 'aria-hidden="true"'):
            with self.subTest(attrs=attrs):
                self.assertFalse(check.has_signed_status(f'<div {attrs}><span>已签到</span></div>'))
        self.assertFalse(check.has_signed_status('<template><div class="punch-card--success">已签到</div></template>'))

    def test_counter_split_across_tags_is_not_personal_status(self):
        self.assertFalse(check.has_signed_status('<div><span>已签到</span><span>人数：0</span></div>'))

    def test_counter_does_not_discard_a_valid_task(self):
        html = GPS.replace("</div>", "<span>已签到人数：0</span></div>")
        self.assertEqual(check.extract_punch_ids(check.pending_task_html(html), "96755"), (["123"], []))

    def test_hidden_label_does_not_discard_a_valid_task(self):
        html = GPS.replace("</div>", '<span hidden>已签到</span></div>')
        self.assertEqual(check.extract_punch_ids(check.pending_task_html(html), "96755"), (["123"], []))

    def test_counter_does_not_hide_missing_static_qr_id(self):
        html = ACTIVE.replace("</div>", "<span>已签到人数：0</span></div>")
        with self.assertRaises(check.MissingPunchIdError):
            check.raise_if_unparsed_active_task(html, [], [], "96755")

    def test_real_success_card_is_positive_evidence_without_keyword(self):
        self.assertTrue(check.has_signed_status('<div class="punch-card punch-card--success"><div class="punch-success-info">09:30</div></div>'))

    def test_legacy_personal_status_remains_recognized(self):
        for label in ("已签到", "已经签到", "签到成功", "您已签到", "14:29 signed"):
            with self.subTest(label=label):
                self.assertTrue(check.has_signed_status("<div>" + label + "</div>"))

    def test_exact_task_verification_rejects_a_counter(self):
        html = '<div class="punch-card" data-punch-id="123">已签到人数：0</div>'
        with patch("cloud_check.requests.get", return_value=response(html)):
            self.assertFalse(check.verify_signed("96755", {}, punch_id="123"))


class PersistentCooldownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cooldowns.json"

    def settings(self, **extra):
        return config(cooldown_state_path=str(self.path), cooldown_backoff_minutes=30, **extra)

    def run_batch(self, settings, pages):
        output = io.StringIO()
        with patch("cloud_check.requests.get", side_effect=pages) as get, patch("cloud_check.requests.post") as post, patch("cloud_check.write_account_summary") as summary, redirect_stdout(output):
            try:
                check.check_all_cookies(settings)
            except RuntimeError:
                pass
        return get, post, summary.call_args.args[0] if summary.called else [], output.getvalue()

    def test_new_run_skips_cooled_account_without_blocking_other_account(self):
        self.run_batch(self.settings(), [response("<p>账号冷却，请等待</p>")])
        get, post, rows, output = self.run_batch(self.settings(cookie=[OTHER_COOKIE, COOKIE]), [response(SIGNED), response(SIGNED)])
        self.assertEqual(get.call_count, 1, "Only the unaffected account may contact BJMF")
        self.assertEqual([r["outcome"] for r in rows], ["already_signed", "cooldown_wait"])
        self.assertIn("cooldown_until_china", output)
        post.assert_not_called()

    def test_waiting_does_not_extend_the_deadline_or_store_credentials(self):
        self.run_batch(self.settings(), [response("<p>账号冷却，请等待</p>")])
        self.assertTrue(self.path.exists(), "Cooldown must survive a fresh process")
        before = self.path.read_text(encoding="utf-8")
        self.run_batch(self.settings(), [response(SIGNED)])
        self.assertEqual(before, self.path.read_text(encoding="utf-8"))
        self.assertNotIn("12345", before)
        self.assertNotIn("private-test-secret", before)

    def test_known_wait_duration_is_honored(self):
        with patch("time.time", return_value=1000000):
            self.run_batch(self.settings(), [response("4168分钟完全后再访问该页面，冷却前访问一次会增加1分钟等待时间")])
        self.assertTrue(self.path.exists())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(next(iter(data["accounts"].values()))["until"], 1000000 + 4168 * 60)

    def test_http_error_cooldown_page_is_still_persisted(self):
        self.run_batch(self.settings(), [response("<p>账号冷却，请等待</p>", status=429)])
        get, _, rows, _ = self.run_batch(self.settings(), [response(SIGNED)])
        self.assertEqual(get.call_count, 0)
        self.assertEqual(rows[0]["outcome"], "cooldown_wait")

    def test_cookie_renewal_does_not_bypass_same_student_cooldown(self):
        self.run_batch(self.settings(), [response("<p>账号冷却，请等待</p>")])
        renewed = "remember_student_new=12345%7Crenewed-fake-token%7C"
        get, _, rows, _ = self.run_batch(self.settings(cookie=[renewed]), [response(SIGNED)])
        self.assertEqual(get.call_count, 0)
        self.assertEqual(rows[0]["outcome"], "cooldown_wait")

    def test_broken_state_schema_is_not_treated_as_no_cooldown(self):
        for data in ({"version": 1, "accounts": []}, {"version": 1, "accounts": {"a" * 64: {"until": "tomorrow"}}}):
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                get, _, _, output = self.run_batch(self.settings(), [response(SIGNED)])
                self.assertEqual(get.call_count, 0)
                self.assertIn("cooldown_state_error", output)

    def test_state_write_error_is_reported_and_other_account_still_runs(self):
        with patch("cooldown_state.os.replace", side_effect=OSError("synthetic disk failure")):
            get, _, rows, output = self.run_batch(self.settings(cookie=[COOKIE, OTHER_COOKIE]), [response("<p>账号冷却，请等待</p>"), response(SIGNED)])
        self.assertEqual(get.call_count, 2)
        self.assertEqual([r["outcome"] for r in rows], ["cooldown_state_error", "already_signed"])
        self.assertIn("persist_failed", output)

    def test_expired_cooldown_allows_check_and_clears_account(self):
        with patch("time.time", return_value=1000000):
            self.run_batch(self.settings(), [response("<p>账号冷却，请等待</p>")])
        with patch("time.time", return_value=1000000 + 1801):
            get, _, rows, _ = self.run_batch(self.settings(), [response(SIGNED)])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(rows[0]["outcome"], "already_signed")
        self.assertTrue(self.path.exists())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["accounts"], {})

    def test_force_and_direct_url_do_not_bypass_account_cooldown(self):
        self.run_batch(self.settings(), [response("<p>账号冷却，请等待</p>")])
        get, post, rows, _ = self.run_batch(self.settings(force_check=True, direct_punch_url="/student/punchw/course/96755/123"), [response(SIGNED)])
        self.assertEqual(get.call_count, 0)
        post.assert_not_called()
        self.assertEqual(rows[0]["outcome"], "cooldown_wait")

    def test_bad_state_file_stops_before_network(self):
        self.path.write_text("not valid json", encoding="utf-8")
        get, post, _, output = self.run_batch(self.settings(), [response(SIGNED)])
        self.assertEqual(get.call_count, 0)
        post.assert_not_called()
        self.assertIn("cooldown_state_error", output)

    def test_cooldown_during_verification_is_saved_without_erasing_confirmed_post(self):
        pages = [response(GPS), response('<form method="post"></form>', "/student/punchw/course/96755/123"), response("<p>账号冷却，请等待</p>")]
        with patch("cloud_check.requests.get", side_effect=pages), patch("cloud_check.requests.post", return_value=response('<div id="title">签到成功</div>')), patch("cloud_check.write_account_summary") as summary, redirect_stdout(io.StringIO()):
            check.check_all_cookies(self.settings())
        self.assertEqual(summary.call_args.args[0][0]["outcome"], "submitted_confirmed")
        self.assertTrue(self.path.exists())
        get, _, rows, _ = self.run_batch(self.settings(), [response(SIGNED)])
        self.assertEqual(get.call_count, 0)
        self.assertEqual(rows[0]["outcome"], "cooldown_wait")

    def test_config_loads_persistent_state_and_positive_backoff(self):
        env = {"BJMF_CLASS_ID": "96755", "BJMF_LAT": "23", "BJMF_LNG": "113", "BJMF_ACC": "30", "BJMF_COOKIE": COOKIE,
               "BJMF_COOLDOWN_STATE": str(self.path), "BJMF_COOLDOWN_BACKOFF_MINUTES": "45"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_cloud_config()
        self.assertEqual(cfg.get("cooldown_state_path"), str(self.path))
        self.assertEqual(cfg.get("cooldown_backoff_minutes"), 45)

    def test_both_workflows_restore_and_save_shared_state_even_on_failure(self):
        for name in ("AutoCheckBJMF.yml", "BJMFManualForceCheck.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertIn("uses: actions/cache/restore@v5", text)
                self.assertIn("uses: actions/cache/save@v5", text)
                self.assertIn("bjmf-cooldown-v1-${{ github.ref_name }}-", text)
                self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', text)
                self.assertIn('BJMF_COOLDOWN_STATE: "bjmf-cooldowns.json"', text)
                save = text.split("- name: Save account cooldown state", 1)[1].split("- name:", 1)[0]
                self.assertIn("always()", save)


if __name__ == "__main__":
    unittest.main()
