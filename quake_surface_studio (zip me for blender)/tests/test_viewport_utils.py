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

    def test_selected_face_cycle_uses_active_then_wraps_both_directions(self):
        self.assertEqual(viewport_utils.next_selected_face_index([7, 2, 5], active_index=5), 5)
        self.assertEqual(viewport_utils.next_selected_face_index([7, 2, 5], active_index=5,
                                                                  previous_index=5, direction=1), 7)
        self.assertEqual(viewport_utils.next_selected_face_index([7, 2, 5], active_index=5,
                                                                  previous_index=2, direction=-1), 7)
        self.assertEqual(viewport_utils.next_selected_face_index([7], active_index=7,
                                                                  previous_index=7, direction=1), 7)
        with self.assertRaisesRegex(ValueError, "selected face"):
            viewport_utils.next_selected_face_index([])

    def test_face_focus_distance_fits_aspect_ratio_and_has_safe_margin(self):
        square = viewport_utils.face_focus_distance(1.0, 1.0, 1.0, 1.5, 0.0254)
        narrow = viewport_utils.face_focus_distance(1.0, 1.0, 0.5, 1.5, 0.0254)
        self.assertGreaterEqual(square, 1.5 * 2.9)
        self.assertGreater(narrow, square)
        self.assertGreaterEqual(viewport_utils.face_focus_distance(0, 0, 1, 0, 0.0254), 0.25)
        with self.assertRaisesRegex(ValueError, "aspect"):
            viewport_utils.face_focus_distance(1, 1, 0, 1, 0.0254)

    def test_face_normal_is_flipped_to_viewer_side(self):
        self.assertEqual(viewport_utils.face_normal_toward_view((0, 0, 1), (0, 0, 1)),
                         (0.0, 0.0, 1.0))
        self.assertEqual(viewport_utils.face_normal_toward_view((0, 0, 1), (0, 0, -1)),
                         (0.0, 0.0, -1.0))
        self.assertEqual(viewport_utils.face_normal_toward_view((0, 1, 0), (1, 0, 0)),
                         (0.0, 1.0, 0.0))
        with self.assertRaisesRegex(ValueError, "three-dimensional"):
            viewport_utils.face_normal_toward_view((1, 0), (0, 0, 1))

    def test_invalid_points_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty selection"):
            viewport_utils.bounds_from_points([])
        with self.assertRaisesRegex(ValueError, "three coordinates"):
            viewport_utils.bounds_from_points([(0, 1)])
        with self.assertRaisesRegex(ValueError, "finite"):
            viewport_utils.bounds_from_points([(float("nan"), 0, 0)])


if __name__ == "__main__":
    unittest.main()
