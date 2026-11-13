import array
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bake_scope


class SelectiveBakeScopeTests(unittest.TestCase):
    def test_full_scope_targets_every_face(self):
        self.assertEqual(
            bake_scope.resolve_target_faces(5),
            [0, 1, 2, 3, 4],
        )

    def test_selected_faces_scope_filters_invalid_indices(self):
        self.assertEqual(
            bake_scope.resolve_target_faces(
                5, [0, 2, 2, 99, -1], use_selected_faces=True
            ),
            [0, 2],
        )

    def test_selected_lights_scope_uses_directly_lit_faces(self):
        self.assertEqual(
            bake_scope.resolve_target_faces(
                5, directly_lit_faces=[1, 3, 4, 7],
                use_selected_lights=True,
            ),
            [1, 3, 4],
        )

    def test_combined_scope_intersects_face_and_light_masks(self):
        self.assertEqual(
            bake_scope.resolve_target_faces(
                6, [0, 1, 2, 4], [1, 2, 3],
                use_selected_faces=True, use_selected_lights=True,
            ),
            [1, 2],
        )

    def test_empty_selection_yields_no_targets(self):
        self.assertEqual(
            bake_scope.resolve_target_faces(
                4, [], [0, 1], use_selected_faces=True
            ),
            [],
        )

    def test_face_rectangles_convert_top_origin_to_blender_pixels(self):
        rects = bake_scope.face_luxel_rectangles(
            [0],
            [10], [20], [4], [3],
            image_width=128, image_height=128,
            resolution=2, lightmap_scale=1, gutter=2, padding=1,
        )
        self.assertEqual(rects, [(21, 79, 31, 87)])

    def test_region_merge_preserves_pixels_outside_target(self):
        original = array.array("f", [0.1, 0.2, 0.3, 1.0] * 16)
        baked = array.array("f", [2.0, 3.0, 4.0, 1.0] * 16)
        changed = bake_scope.merge_rgba_regions(
            original, baked, 4, 4, [(1, 1, 3, 3)], factor=0.5
        )
        self.assertEqual(changed, 4)
        for y in range(4):
            for x in range(4):
                offset = (y * 4 + x) * 4
                inside = 1 <= x < 3 and 1 <= y < 3
                if inside:
                    self.assertEqual(list(original[offset:offset + 4]), [1.0, 1.5, 2.0, 1.0])
                else:
                    self.assertAlmostEqual(original[offset], 0.1, places=6)
                    self.assertAlmostEqual(original[offset + 1], 0.2, places=6)
                    self.assertAlmostEqual(original[offset + 2], 0.3, places=6)
                    self.assertEqual(original[offset + 3], 1.0)

    def test_overlapping_rectangles_are_merged_without_double_scaling(self):
        pixels = array.array("f", [1.0, 1.0, 1.0, 1.0] * 9)
        changed = bake_scope.scale_rgba_regions(
            pixels, 3, 3, [(0, 0, 2, 2), (1, 1, 3, 3)], 2.0
        )
        self.assertEqual(changed, 7)
        self.assertEqual(pixels[(1 * 3 + 1) * 4], 2.0)

    def test_invalid_buffer_length_is_rejected(self):
        with self.assertRaises(ValueError):
            bake_scope.merge_rgba_regions([0.0], [0.0], 2, 2, [(0, 0, 1, 1)], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
