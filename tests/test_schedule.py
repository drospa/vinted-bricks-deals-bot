"""Madrid-time slot guard. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import daily_deals as dd  # noqa: E402


def at(h, m):
    return datetime(2026, 10, 15, h, m)


class TestSlots(unittest.TestCase):
    def test_slot_per_time(self):
        self.assertIsNone(dd.schedule_slot({}, at(8, 0)))
        self.assertEqual(dd.schedule_slot({}, at(9, 30)), "2026-10-15-am")
        self.assertEqual(dd.schedule_slot({}, at(14, 7)), "2026-10-15-pm")
        self.assertEqual(dd.schedule_slot({}, at(19, 0)), "2026-10-15-eve")
        self.assertEqual(dd.schedule_slot({}, at(23, 50)), "2026-10-15-eve")

    def test_evening_runs_after_afternoon_done(self):
        self.assertEqual(dd.schedule_slot({"last_slot": "2026-10-15-pm"}, at(19, 0)), "2026-10-15-eve")

    def test_backup_cron_skips_done_slot(self):
        self.assertIsNone(dd.schedule_slot({"last_slot": "2026-10-15-eve"}, at(19, 7)))


if __name__ == "__main__":
    unittest.main()
