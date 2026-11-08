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

    def test_horizontal_forward_and_right_match_z_up_view_basis(self):
        forward, right = navigation_utils.horizontal_movement_axes(0.0, 1.0, 1.0, 0.0)
        self.assertAlmostEqual(forward[0], 0.0)
        self.assertAlmostEqual(forward[1], 1.0)
        self.assertAlmostEqual(right[0], 1.0)
        self.assertAlmostEqual(right[1], 0.0)

    def test_arbitrary_horizontal_forward_has_correct_right_hand_side(self):
        forward, right = navigation_utils.horizontal_movement_axes(3.0, 4.0, -4.0, 3.0)
        self.assertAlmostEqual(forward[0], 0.6)
        self.assertAlmostEqual(forward[1], 0.8)
        self.assertAlmostEqual(right[0], 0.8)
        self.assertAlmostEqual(right[1], -0.6)

    def test_vertical_view_uses_camera_right_as_heading_fallback(self):
        forward, right = navigation_utils.horizontal_movement_axes(0.0, 0.0, 1.0, 0.0)
        self.assertEqual(forward, (0.0, 1.0))
        self.assertEqual(right, (1.0, -0.0))

    def test_degenerate_view_axes_use_stable_world_fallback(self):
        forward, right = navigation_utils.horizontal_movement_axes(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(forward, (1.0, 0.0))
        self.assertEqual(right, (0.0, -1.0))

if __name__ == "__main__":
    unittest.main(verbosity=2)
