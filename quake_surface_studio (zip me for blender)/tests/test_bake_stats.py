import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bake_stats


class BakeStatsTests(unittest.TestCase):
    def test_missing_and_invalid_durations(self):
        for value in (None, "not-a-number", float("nan"), float("inf"), -1):
            self.assertEqual(bake_stats.format_duration(value), "not recorded")

    def test_milliseconds_and_seconds(self):
        self.assertEqual(bake_stats.format_duration(0.125), "125 ms")
        self.assertEqual(bake_stats.format_duration(2.5), "2.50 s")

    def test_minutes_and_hours(self):
        self.assertEqual(bake_stats.format_duration(61.25), "1 min 1.2 s")
        self.assertEqual(bake_stats.format_duration(3661.25), "1 h 1 min 1.2 s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
