import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import navigation_utils


class NavigationEventTests(unittest.TestCase):
    def test_accepts_timer_event_without_timer_attribute(self):
        self.assertTrue(navigation_utils.is_active_timer_event("TIMER", None, object()))

    def test_accepts_matching_timer(self):
        timer = object()
        self.assertTrue(navigation_utils.is_active_timer_event("TIMER", timer, timer))

    def test_ignores_other_timer(self):
        self.assertFalse(
            navigation_utils.is_active_timer_event("TIMER", object(), object())
        )

    def test_ignores_non_timer_events(self):
        self.assertFalse(navigation_utils.is_active_timer_event("MOUSEMOVE", None, object()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
