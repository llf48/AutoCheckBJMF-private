import unittest

from cloud_check import extract_form_submit_url
from cloud_check import extract_gps_submit_urls
from cloud_check import extract_punch_ids
from cloud_check import extract_submit_urls
from cloud_check import find_remember_cookie
from cloud_check import has_cooldown_marker
from cloud_check import has_signed_status
from cloud_check import raise_if_unparsed_active_task


class CloudCheckParsingTests(unittest.TestCase):
    def test_accepts_any_remember_student_cookie_name(self):
        cookie = "s=ignored; remember_student_abc123=student%7Ctoken; other=x"

        self.assertEqual(find_remember_cookie(cookie), "remember_student_abc123=student%7Ctoken")

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

    def test_raises_when_active_punch_button_is_visible_but_unparsed(self):
        html = "<div>正在进行</div><a>点此去完成签到</a>"

        with self.assertRaisesRegex(RuntimeError, "could not parse"):
            raise_if_unparsed_active_task(html, [], [])


if __name__ == "__main__":
    unittest.main()
