import unittest

from cloud_check import extract_punch_ids


class CloudCheckParsingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
