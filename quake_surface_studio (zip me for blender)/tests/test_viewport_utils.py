import unittest

import viewport_utils


class ViewportUtilsTests(unittest.TestCase):
    def test_computes_world_bounds_center_and_diagonal(self):
        bounds = viewport_utils.bounds_from_points([
            (0.0, 0.0, 0.0),
            (2.0, 4.0, 6.0),
        ])
        self.assertEqual(bounds["minimum"], (0.0, 0.0, 0.0))
        self.assertEqual(bounds["maximum"], (2.0, 4.0, 6.0))
        self.assertEqual(bounds["center"], (1.0, 2.0, 3.0))
        self.assertAlmostEqual(bounds["diagonal"], (56.0) ** 0.5)

    def test_view_distance_has_minimum_and_scale(self):
        bounds = viewport_utils.bounds_from_points([
            (0, 0, 0), (2, 0, 0),
        ])
        self.assertEqual(viewport_utils.view_distance_from_bounds(bounds), 3.0)
        point_bounds = viewport_utils.bounds_from_points([(0, 0, 0)])
        self.assertEqual(viewport_utils.view_distance_from_bounds(point_bounds), 0.05)

    def test_invalid_points_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty selection"):
            viewport_utils.bounds_from_points([])
        with self.assertRaisesRegex(ValueError, "three coordinates"):
            viewport_utils.bounds_from_points([(0, 1)])
        with self.assertRaisesRegex(ValueError, "finite"):
            viewport_utils.bounds_from_points([(float("nan"), 0, 0)])


if __name__ == "__main__":
    unittest.main()
