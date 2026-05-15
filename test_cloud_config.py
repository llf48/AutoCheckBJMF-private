import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cloud_config import is_inside_china_time_window, load_cloud_config


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
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_cloud_config()

        self.assertEqual(config["watch_minutes"], 40)
        self.assertEqual(config["watch_interval_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
