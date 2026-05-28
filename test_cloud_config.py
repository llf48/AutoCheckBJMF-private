import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cloud_config import is_inside_china_time_window, load_cloud_config
from cloud_config import seconds_until_china_time_window_end
from cloud_config import seconds_until_china_time_window_start


class CloudConfigTests(unittest.TestCase):
    def test_loads_required_values_from_environment(self):
        env = {
            "BJMF_CLASS_ID": "96755",
            "BJMF_LAT": "23.185647",
            "BJMF_LNG": "113.33389",
            "BJMF_ACC": "30",
            "BJMF_COOKIE": "remember_student_example=value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertEqual(config["class"], "96755")
        self.assertEqual(config["lat"], "23.185647")
        self.assertEqual(config["lng"], "113.33389")
        self.assertEqual(config["acc"], "30")
        self.assertEqual(config["cookie"], ["remember_student_example=value"])
        self.assertEqual(config["pushplus"], "")

    def test_raises_for_missing_required_secret(self):
        env = {
            "BJMF_CLASS_ID": "96755",
            "BJMF_LAT": "23.185647",
            "BJMF_LNG": "113.33389",
            "BJMF_ACC": "30",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "BJMF_COOKIE"):
                load_cloud_config()

    def test_detects_china_time_window_from_utc_time(self):
        inside = datetime(2026, 5, 13, 23, 50, tzinfo=timezone.utc)
        outside = datetime(2026, 5, 14, 10, 1, tzinfo=timezone.utc)

        self.assertTrue(is_inside_china_time_window(inside))
        self.assertFalse(is_inside_china_time_window(outside))

    def test_loads_watch_mode_settings(self):
        env = {
            "BJMF_CLASS_ID": "96755",
            "BJMF_LAT": "23.185647",
            "BJMF_LNG": "113.33389",
            "BJMF_ACC": "30",
            "BJMF_COOKIE": "remember_student_example=value",
            "BJMF_WATCH_MINUTES": "40",
            "BJMF_WATCH_INTERVAL_SECONDS": "300",
            "BJMF_WATCH_UNTIL_WINDOW_END": "true",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertEqual(config["watch_minutes"], 40)
        self.assertEqual(config["watch_interval_seconds"], 300)
        self.assertTrue(config["watch_until_window_end"])

    def test_autosubmit_watch_mode_clamps_stale_external_trigger_settings(self):
        env = {
            "BJMF_CLASS_ID": "96755",
            "BJMF_LAT": "23.185647",
            "BJMF_LNG": "113.33389",
            "BJMF_ACC": "30",
            "BJMF_COOKIE": "remember_student_example=value",
            "BJMF_AUTOSUBMIT": "true",
            "BJMF_WATCH_MINUTES": "4",
            "BJMF_WATCH_INTERVAL_SECONDS": "60",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertEqual(config["watch_minutes"], 5)
        self.assertEqual(config["watch_interval_seconds"], 30)

    def test_calculates_seconds_until_window_end(self):
        now = datetime(2026, 5, 16, 7, 30, tzinfo=timezone.utc)

        seconds = seconds_until_china_time_window_end(now)

        self.assertEqual(seconds, 9000)

    def test_calculates_seconds_until_window_start(self):
        now = datetime(2026, 5, 24, 23, 30, tzinfo=timezone.utc)

        seconds = seconds_until_china_time_window_start(now)

        self.assertEqual(seconds, 1200)

    def test_window_start_wait_is_zero_after_window_opens(self):
        now = datetime(2026, 5, 24, 23, 50, tzinfo=timezone.utc)

        seconds = seconds_until_china_time_window_start(now)

        self.assertEqual(seconds, 0)

    def test_autosubmit_requires_explicit_opt_in(self):
        env = {
            "BJMF_CLASS_ID": "96755",
            "BJMF_LAT": "23.185647",
            "BJMF_LNG": "113.33389",
            "BJMF_ACC": "30",
            "BJMF_COOKIE": "remember_student_example=value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertFalse(config["autosubmit"])

        env["BJMF_AUTOSUBMIT"] = "true"
        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertTrue(config["autosubmit"])

    def test_loads_pause_and_safe_single_check_flags(self):
        env = {
            "BJMF_CLASS_ID": "96755",
            "BJMF_LAT": "23.185647",
            "BJMF_LNG": "113.33389",
            "BJMF_ACC": "30",
            "BJMF_COOKIE": "remember_student_example=value",
            "BJMF_PAUSED": "true",
            "BJMF_SAFE_SINGLE_CHECK": "false",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertTrue(config["paused"])
        self.assertFalse(config["safe_single_check"])


if __name__ == "__main__":
    unittest.main()
