import unittest
from datetime import datetime

from polling import get_next_poll_delay


class PollingWindowTests(unittest.TestCase):
    def test_waits_until_start_before_window(self):
        now = datetime(2026, 5, 14, 7, 45, 0)

        delay = get_next_poll_delay(now, "07:50", "18:00", 5)

        self.assertEqual(delay, 300)

    def test_uses_interval_inside_window(self):
        now = datetime(2026, 5, 14, 8, 10, 0)

        delay = get_next_poll_delay(now, "07:50", "18:00", 5)

        self.assertEqual(delay, 300)

    def test_stops_after_end_time(self):
        now = datetime(2026, 5, 14, 18, 0, 1)

        delay = get_next_poll_delay(now, "07:50", "18:00", 5)

        self.assertIsNone(delay)


if __name__ == "__main__":
    unittest.main()
