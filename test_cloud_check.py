import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cloud_check import extract_form_submit_url
from cloud_check import extract_punch_id_from_url
from cloud_check import extract_gps_submit_urls
from cloud_check import extract_punch_ids
from cloud_check import extract_submit_urls
from cloud_check import find_remember_cookie
from cloud_check import get_active_structure_hints
from cloud_check import has_active_task_marker
from cloud_check import has_cooldown_marker
from cloud_check import has_signed_status
from cloud_check import parse_notice_end_time
from cloud_check import raise_if_cooldown_page
from cloud_check import raise_if_unparsed_active_task
from cloud_check import raise_if_login_abnormal
from cloud_check import should_run_for_notice
from cloud_check import check_all_cookies
from cloud_check import check_one_cookie
from cloud_config import CHINA_TZ


class CloudCheckParsingTests(unittest.TestCase):
    def test_cookie_batch_writes_account_audit_without_exposing_tokens(self):
        cookies = [
            "remember_student_first=3170461%7Cfirst-secret-token-value",
            "remember_student_second=2955801%7Csecond-secret-token-value",
        ]
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            audit_path = Path(temp_dir) / "audit.jsonl"
            config = {"cookie": cookies, "audit_log_path": str(audit_path)}
            with redirect_stdout(output):
                found = check_all_cookies(config, checker=lambda _config, _cookie: 0)

            self.assertTrue(audit_path.exists(), "account audit file was not created")
            records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(found, 0)
        self.assertEqual(
            [(record["event"], record["account"], record["student_id"]) for record in records],
            [
                ("account_check_started", 1, "3170461"),
                ("account_check_finished", 1, "3170461"),
                ("account_check_started", 2, "2955801"),
                ("account_check_finished", 2, "2955801"),
            ],
        )
        combined_output = output.getvalue() + "\n" + "\n".join(json.dumps(record) for record in records)
        self.assertNotIn("first-secret-token-value", combined_output)
        self.assertNotIn("second-secret-token-value", combined_output)

    def test_submission_writes_post_attempt_response_and_verification_audit(self):
        page = SimpleNamespace(
            text=(
                '<a id="gps_btn_5228732" '
                'href="/student/punchw/course/96755/5228732">点此去完成签到</a>'
            ),
            url="https://k8n.cn/student/course/96755/punchs?op=ing",
            status_code=200,
            raise_for_status=lambda: None,
        )
        post_response = SimpleNamespace(
            text='<div id="title">签到成功</div>',
            status_code=200,
            raise_for_status=lambda: None,
        )
        config = {
            "class": "96755",
            "lat": "23.185647",
            "lng": "113.33389",
            "acc": "30",
            "autosubmit": True,
            "audit_log_path": "",
            "_audit_account_number": 2,
            "_audit_student_id": "2955801",
        }
        output = io.StringIO()

        with patch("cloud_check.requests.get", return_value=page), patch(
            "cloud_check.resolve_submit_url",
            return_value="https://k8n.cn/student/punchw/course/96755/5228732",
        ), patch("cloud_check.requests.post", return_value=post_response), patch(
            "cloud_check.verify_signed", return_value=True
        ), redirect_stdout(output):
            found = check_one_cookie(
                config,
                "remember_student_second=2955801%7Csecond-secret-token-value",
            )

        audit_records = [
            json.loads(line.removeprefix("BJMF_AUDIT "))
            for line in output.getvalue().splitlines()
            if line.startswith("BJMF_AUDIT ")
        ]
        self.assertEqual(found, 1)
        self.assertEqual(
            [record["event"] for record in audit_records],
            ["post_attempt", "post_response", "signed_verification"],
        )
        self.assertEqual(audit_records[0]["punch_id"], "5228732")
        self.assertEqual(audit_records[1]["http_status"], 200)
        self.assertEqual(audit_records[1]["server_result"], "签到成功")
        self.assertTrue(audit_records[2]["signed"])
        self.assertNotIn("second-secret-token-value", output.getvalue())

    def test_cookie_batch_continues_after_one_account_fails(self):
        checked = []

        def checker(config, cookie):
            checked.append(cookie)
            if cookie == "expired-cookie":
                raise RuntimeError("expired")
            return 2

        config = {"cookie": ["expired-cookie", "working-cookie"]}

        with self.assertRaisesRegex(RuntimeError, "1 of 2 cookie account checks failed"):
            check_all_cookies(config, checker=checker)

        self.assertEqual(checked, ["expired-cookie", "working-cookie"])

    def test_detects_url_encoded_wechat_oauth_login_redirect(self):
        response = SimpleNamespace(
            text="<html></html>",
            url=(
                "https://open.weixin.qq.com/connect/oauth2/authorize?"
                "redirect_uri=https%3A%2F%2Fk8n.cn%2Flogin%2Fweixin%2Flogin%2Fstudent%2F2"
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "login/OAuth"):
            raise_if_login_abnormal(response)

    def test_accepts_any_remember_student_cookie_name(self):
        cookie = "s=ignored; remember_student_abc123=student%7Ctoken; other=x"

        self.assertEqual(find_remember_cookie(cookie), "remember_student_abc123=student%7Ctoken")

    def test_extracts_punch_id_from_direct_url(self):
        url = "https://k8n.cn/student/punchw/course/96755/5228732?sid=3170461"

        self.assertEqual(extract_punch_id_from_url(url), "5228732")

    def test_parses_wechat_notice_end_time(self):
        notice = "GPS考勤考勤2026-05-28 08:24:53结束，我还未签"

        end_time = parse_notice_end_time(notice)

        self.assertEqual(end_time, datetime(2026, 5, 28, 8, 24, 53, tzinfo=CHINA_TZ))

    def test_skips_expired_notice_window(self):
        config = {"notice_text": "GPS考勤考勤2026-05-28 08:24:53结束，我还未签"}
        now_china = datetime(2026, 5, 28, 8, 30, tzinfo=CHINA_TZ)

        self.assertFalse(should_run_for_notice(config, now_china))

    def test_extracts_new_gps_launch_path_punch_id(self):
        html = '''
            <wx-open-launch-weapp
                path="pages/punchs/gps?course_id=96755&punch_id=5228732">
            </wx-open-launch-weapp>
            <a id="gps_btn_5228732"
               href="/student/punchw/course/96755/5228732?sid=3170461">
               点此去完成签到
            </a>
        '''

        gps_ids, scan_ids = extract_punch_ids(html)

        self.assertEqual(gps_ids, ["5228732"])
        self.assertEqual(scan_ids, [])

    def test_keeps_legacy_patterns(self):
        html = "onclick=\"punch_gps(111)\" id=\"punchcard_222\""

        gps_ids, scan_ids = extract_punch_ids(html)

        self.assertEqual(gps_ids, ["111"])
        self.assertEqual(scan_ids, ["222"])

    def test_extracts_dynamic_scan_id_variants(self):
        html = '''
            <button id="punchcard-301">扫码签到</button>
            <button data-scan-id="302">扫码签到</button>
            <script>
                punchcard(303);
                window.config = {"punchcard_id": "304"};
            </script>
        '''

        gps_ids, scan_ids = extract_punch_ids(html)

        self.assertEqual(gps_ids, [])
        self.assertEqual(scan_ids, ["301", "303", "302", "304"])

    def test_extracts_dynamic_scan_submit_routes(self):
        html = '''
            <a href="/student/punchcard/course/96755/401?token=short">scan</a>
            <form action="/student/punchscan/course/96755/402"></form>
        '''

        urls = extract_submit_urls(html, "96755")

        self.assertEqual(
            urls,
            {
                "401": "https://k8n.cn/student/punchcard/course/96755/401?token=short",
                "402": "https://k8n.cn/student/punchscan/course/96755/402",
            },
        )

    def test_extracts_new_gps_submit_url(self):
        html = '''
            <a id="gps_btn_5228732"
               href="/student/punchw/course/96755/5228732?sid=3170461">
               点此去完成签到
            </a>
        '''

        urls = extract_gps_submit_urls(html, "96755")

        self.assertEqual(
            urls,
            {
                "5228732": "https://k8n.cn/student/punchw/course/96755/5228732?sid=3170461",
            },
        )

    def test_extracts_submit_url_from_href_action_and_raw_markup(self):
        html = '''
            <form method="post" action="/student/punchw/course/96755/333?sid=abc"></form>
            <a href="https://k8n.cn/student/punchs/course/96755/444">legacy</a>
            <script>var next="/student/punchw/course/96755/555?sid=xyz";</script>
        '''

        urls = extract_submit_urls(html, "96755")

        self.assertEqual(
            urls,
            {
                "333": "https://k8n.cn/student/punchw/course/96755/333?sid=abc",
                "444": "https://k8n.cn/student/punchs/course/96755/444",
                "555": "https://k8n.cn/student/punchw/course/96755/555?sid=xyz",
            },
        )

    def test_uses_current_detail_page_when_post_form_has_no_action(self):
        html = '<form method="post"><input name="lat"></form>'

        url = extract_form_submit_url(
            html,
            "https://k8n.cn/student/punchw/course/96755/5228732?sid=3170461",
        )

        self.assertEqual(url, "https://k8n.cn/student/punchw/course/96755/5228732?sid=3170461")

    def test_detects_signed_status(self):
        html = "<div>GPS</div><div>14:29 signed</div><div>已签到</div>"

        self.assertTrue(has_signed_status(html))

    def test_detects_cooldown_page(self):
        html = "<body>4168分钟完全后再访问该页面，冷却前访问一次会增加1分钟等待时间</body>"

        self.assertTrue(has_cooldown_marker(html))

    def test_cooldown_page_cannot_be_reported_as_no_task(self):
        html = "<body>4168分钟完全后再访问该页面，冷却前访问一次会增加1分钟等待时间</body>"

        with self.assertRaisesRegex(RuntimeError, "cooldown.*not retry"):
            raise_if_cooldown_page(html)

    def test_raises_when_active_punch_button_is_visible_but_unparsed(self):
        html = "<div>正在进行</div><a>点此去完成签到</a>"

        with self.assertRaisesRegex(RuntimeError, "could not parse"):
            raise_if_unparsed_active_task(html, [], [])

    def test_static_qr_without_id_requests_the_scanned_url(self):
        html = '''
            <div class="card punch-card punch-card--primary">
                <div class="card-body">
                    <div class="punch-status">正在进行</div>
                    <div class="punch-meta"><span>二维码签到</span></div>
                    <a>点此去完成签到</a>
                </div>
            </div>
        '''

        with self.assertRaisesRegex(RuntimeError, "static QR.*direct_punch_url"):
            raise_if_unparsed_active_task(html, [], [])

    def test_static_qr_without_id_falls_back_to_legacy_list_page(self):
        current_page = SimpleNamespace(
            text='''
                <div class="card punch-card punch-card--primary">
                    <div class="punch-status">正在进行</div>
                    <div class="punch-meta"><span>二维码签到</span></div>
                    <a>点此去完成签到</a>
                </div>
            ''',
            url="https://k8n.cn/student/course/96755/punchs?op=ing",
            status_code=200,
            raise_for_status=lambda: None,
        )
        legacy_page = SimpleNamespace(
            text='<button id="punchcard_812345">扫码签到</button>',
            url="https://k8n.cn/student/course/96755/punchs",
            status_code=200,
            raise_for_status=lambda: None,
        )
        config = {
            "class": "96755",
            "lat": "23.185647",
            "lng": "113.33389",
            "acc": "30",
            "autosubmit": False,
        }

        with patch("cloud_check.requests.get", side_effect=[current_page, legacy_page]) as get:
            found = check_one_cookie(config, "remember_student_test=student%7Ctoken")

        self.assertEqual(found, 1)
        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            [
                "https://k8n.cn/student/course/96755/punchs?op=ing",
                "https://k8n.cn/student/course/96755/punchs",
            ],
        )

    def test_structure_hints_redact_dynamic_values(self):
        html = (
            '<a class="scan-entry" data-session="abcdefghijklmnopqrstuvwxyz123456" '
            'href="/student/punchcard/course/96755/987654?token=secret-value">'
            '点此去完成签到</a>'
        )

        hints = get_active_structure_hints(html)
        serialized = repr(hints)

        self.assertIn("scan-entry", serialized)
        self.assertIn("<n>", serialized)
        self.assertIn("<value>", serialized)
        self.assertNotIn("987654", serialized)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", serialized)

    def test_click_to_complete_text_still_counts_as_active_punch(self):
        html = "<div>\u70b9\u6b64\u53bb\u5b8c\u6210\u7b7e\u5230</div>"

        self.assertTrue(has_active_task_marker(html))
        with self.assertRaisesRegex(RuntimeError, "could not parse"):
            raise_if_unparsed_active_task(html, [], [])

    def test_generic_page_words_do_not_count_as_active_punch(self):
        html = "<div>\u6b63\u5728\u8fdb\u884c</div><button>\u786e\u5b9a</button>"

        self.assertFalse(has_active_task_marker(html))
        raise_if_unparsed_active_task(html, [], [])


if __name__ == "__main__":
    unittest.main()
