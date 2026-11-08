import os
import sys
import unittest
import math

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

    def test_mouse_right_turns_view_right_without_pitch_change(self):
        yaw_delta, pitch_delta = navigation_utils.mouse_look_deltas(10, 0, 0.0, sensitivity=0.01)
        self.assertAlmostEqual(yaw_delta, -0.1)
        self.assertAlmostEqual(pitch_delta, 0.0)

    def test_mouse_up_raises_view(self):
        yaw_delta, pitch_delta = navigation_utils.mouse_look_deltas(0, -10, 0.0, sensitivity=0.01)
        self.assertAlmostEqual(yaw_delta, 0.0)
        self.assertAlmostEqual(pitch_delta, 0.1)

    def test_pitch_clamps_at_both_extrema_without_wraparound(self):
        limit = math.radians(89.0)
        _yaw, pitch_delta = navigation_utils.mouse_look_deltas(
            0, -1000, math.radians(88.0), sensitivity=0.01, pitch_limit=limit
        )
        self.assertAlmostEqual(pitch_delta, limit - math.radians(88.0))
        _yaw, pitch_delta = navigation_utils.mouse_look_deltas(
            0, 1000, math.radians(-88.0), sensitivity=0.01, pitch_limit=limit
        )
        self.assertAlmostEqual(pitch_delta, -limit + math.radians(88.0))

    def test_viewport_center_uses_window_relative_region_origin(self):
        center = navigation_utils.viewport_region_center(120, 80, 900, 700)
        self.assertEqual(center, (570, 430))

    def test_mouse_delta_is_measured_from_center(self):
        dx, dy = navigation_utils.mouse_delta_from_center(582, 421, 570, 430)
        self.assertEqual((dx, dy), (12, -9))

    def test_center_warp_feedback_has_zero_mouse_delta(self):
        center = navigation_utils.viewport_region_center(120, 80, 900, 700)
        self.assertEqual(
            navigation_utils.mouse_delta_from_center(center[0], center[1], *center),
            (0, 0),
        )

    def test_center_is_recalculated_after_region_resize(self):
        first = navigation_utils.viewport_region_center(120, 80, 900, 700)
        second = navigation_utils.viewport_region_center(120, 80, 1000, 700)
        self.assertEqual(first, (570, 430))
        self.assertEqual(second, (620, 430))


if __name__ == "__main__":
    unittest.main(verbosity=2)
