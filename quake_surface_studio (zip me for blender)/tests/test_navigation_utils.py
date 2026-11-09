import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import navigation_utils


class QuakeWalkPreferenceTests(unittest.TestCase):
    def test_default_quake_speed_converts_to_blender_metres_per_second(self):
        settings = navigation_utils.quake_walk_preferences(0.0254, 640.0, 4.0)
        self.assertAlmostEqual(settings["walk_speed"], 16.256)
        self.assertEqual(settings["walk_speed_factor"], 4.0)
        self.assertAlmostEqual(settings["view_height"], 0.5588)
        self.assertFalse(settings["use_gravity"])

    def test_movement_speed_tracks_imported_map_scale(self):
        inches = navigation_utils.quake_walk_preferences(0.0254, 320.0, 3.0)
        half_scale = navigation_utils.quake_walk_preferences(0.0127, 320.0, 3.0)
        self.assertAlmostEqual(inches["walk_speed"], half_scale["walk_speed"] * 2.0)

    def test_speed_and_fast_factor_respect_blender_preference_limits(self):
        settings = navigation_utils.quake_walk_preferences(10.0, 4000.0, 99.0)
        self.assertEqual(settings["walk_speed"], 100.0)
        self.assertEqual(settings["walk_speed_factor"], 10.0)
        self.assertEqual(settings["view_height"], 220.0)

        slow = navigation_utils.quake_walk_preferences(0.0254, 0.0, 0.0)
        self.assertEqual(slow["walk_speed"], 0.01)
        self.assertEqual(slow["walk_speed_factor"], 1.0)

    def test_rejects_zero_or_negative_map_scale(self):
        for scale in (0.0, -0.0254):
            with self.subTest(scale=scale):
                with self.assertRaises(ValueError):
                    navigation_utils.quake_walk_preferences(scale, 640.0, 4.0)

    def test_rejects_non_finite_settings(self):
        for values in ((float("nan"), 640.0, 4.0),
                       (0.0254, float("inf"), 4.0),
                       (0.0254, 640.0, float("-inf"))):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    navigation_utils.quake_walk_preferences(*values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
