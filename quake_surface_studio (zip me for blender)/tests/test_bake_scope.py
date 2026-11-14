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


class AtlasGutterDilationTests(unittest.TestCase):
    def test_gutter_copies_nearest_edge_texel_including_corners(self):
        pixels = array.array("f", [0.0, 0.0, 0.0, 1.0] * 25)
        width = height = 5
        colors = {
            (1, 1): (1.0, 0.0, 0.0, 1.0),
            (2, 1): (0.0, 1.0, 0.0, 1.0),
            (1, 2): (0.0, 0.0, 1.0, 1.0),
            (2, 2): (1.0, 1.0, 1.0, 1.0),
        }
        for (x, y), color in colors.items():
            offset = (y * width + x) * 4
            pixels[offset:offset + 4] = array.array("f", color)
        changed = bake_scope.dilate_rgba_gutters(
            pixels, width, height, [(1, 1, 3, 3)], padding=1
        )
        self.assertEqual(changed, 12)
        def color_at(x, y):
            offset = (y * width + x) * 4
            return tuple(pixels[offset:offset + 4])
        self.assertEqual(color_at(0, 0), colors[(1, 1)])
        self.assertEqual(color_at(3, 0), colors[(2, 1)])
        self.assertEqual(color_at(0, 3), colors[(1, 2)])
        self.assertEqual(color_at(3, 3), colors[(2, 2)])
        self.assertEqual(color_at(4, 4), (0.0, 0.0, 0.0, 1.0))

    def test_separate_faces_fill_only_their_own_reserved_gutters(self):
        pixels = array.array("f", [0.0, 0.0, 0.0, 1.0] * 40)
        width, height = 8, 5
        for y in range(1, 3):
            for x in range(1, 3):
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = array.array("f", (1.0, 0.0, 0.0, 1.0))
            for x in range(5, 7):
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = array.array("f", (0.0, 0.0, 1.0, 1.0))
        bake_scope.dilate_rgba_gutters(
            pixels, width, height, [(1, 1, 3, 3), (5, 1, 7, 3)], padding=1
        )
        left = pixels[(1 * width + 3) * 4:(1 * width + 3) * 4 + 4]
        right = pixels[(1 * width + 4) * 4:(1 * width + 4) * 4 + 4]
        self.assertEqual(tuple(left), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(tuple(right), (0.0, 0.0, 1.0, 1.0))

    def test_rejects_overlapping_expanded_gutters(self):
        pixels = array.array("f", [0.0, 0.0, 0.0, 1.0] * 49)
        with self.assertRaisesRegex(ValueError, "gutters overlap"):
            bake_scope.dilate_rgba_gutters(
                pixels, 7, 7, [(1, 1, 3, 3), (4, 1, 6, 3)], padding=1
            )

    def test_zero_padding_is_a_no_op(self):
        pixels = array.array("f", [0.25, 0.5, 0.75, 1.0] * 4)
        self.assertEqual(
            bake_scope.dilate_rgba_gutters(pixels, 2, 2, [(0, 0, 2, 2)], padding=0),
            0,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
