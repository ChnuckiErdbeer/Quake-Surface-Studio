import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import texture_export


class TextureExportHelperTests(unittest.TestCase):
    def test_quake_texture_dimensions_are_power_of_two(self):
        self.assertEqual(texture_export.quake_texture_dimension(65), 128)
        self.assertEqual(texture_export.quake_texture_dimension(80), 128)
        self.assertEqual(texture_export.quake_texture_dimension(128), 128)
        self.assertEqual(texture_export.quake_texture_dimension(129), 256)
        self.assertEqual(texture_export.quake_texture_dimension(520), 512)
        self.assertEqual(texture_export.quake_texture_dimension(2), 16)
        self.assertEqual(texture_export.quake_texture_dimension(0), 16)

    def test_quake_texture_dimension_rejects_invalid_limits_and_non_finite_values(self):
        with self.assertRaises(ValueError):
            texture_export.quake_texture_dimension(64, maximum=8)
        with self.assertRaises(ValueError):
            texture_export.quake_texture_dimension(float("inf"))

    def test_face_local_power_of_two_padding_does_not_stretch_source_texels(self):
        # An 80x65 source span padded to 128x128 keeps the original
        # texinfo axes unchanged; only spans beyond 512 are resampled.
        projection = (2, 0, 0, 16, 0, 4, 0, 8)
        padded = texture_export.face_local_texinfo_projection(
            projection, (10, 5, 80, 65), (128, 128)
        )
        self.assertEqual(padded, (2, 0, 0, 6, 0, 4, 0, 3))
        scaled = texture_export.face_local_texinfo_projection(
            projection, (10, 5, 600, 520), (512, 512)
        )
        self.assertAlmostEqual(scaled[0], 2 * 512 / 600)
        self.assertAlmostEqual(scaled[3], 6 * 512 / 600)
        self.assertAlmostEqual(scaled[5], 4 * 512 / 520)
        self.assertAlmostEqual(scaled[7], 3 * 512 / 520)

    def test_face_local_projection_accepts_full_bsp29_texinfo_record(self):
        # dtexinfo_t has eight projection floats plus miptex and flags.
        record = (2, 0, 0, 16, 0, 4, 0, 8, 12, 3)
        result = texture_export.face_local_texinfo_projection(
            record, (10, 5, 80, 65), (128, 128)
        )
        self.assertEqual(result, (2, 0, 0, 6, 0, 4, 0, 3))

    def test_allocates_contiguous_indices_for_multiple_images(self):
        entries = ["source-a", "source-b"]
        indices = {}
        first = texture_export.allocate_image_texture_index(entries, indices, "img-a", "new-a")
        second = texture_export.allocate_image_texture_index(entries, indices, "img-b", "new-b")
        third = texture_export.allocate_image_texture_index(entries, indices, "img-c", "new-c")
        self.assertEqual((first, second, third), (2, 3, 4))
        self.assertEqual(entries, ["source-a", "source-b", "new-a", "new-b", "new-c"])

    def test_reuses_texture_for_shared_atlas_image(self):
        entries = ["source"]
        indices = {}
        first = texture_export.allocate_image_texture_index(entries, indices, 77, "atlas")
        second = texture_export.allocate_image_texture_index(entries, indices, 77, "ignored")
        self.assertEqual((first, second), (1, 1))
        self.assertEqual(entries, ["source", "atlas"])

    def test_packs_two_faces_and_preserves_individual_tiles(self):
        result = texture_export.pack_face_rectangles([(256, 256), (256, 128)])
        self.assertEqual(result["atlas_size"], 512)
        self.assertEqual(len(result["tiles"]), 2)
        a, b = result["tiles"]
        self.assertLess(a["x"], 512)
        self.assertLess(b["x"], 512)
        self.assertGreaterEqual(a["x"] + a["width"], 0)
        self.assertGreaterEqual(b["y"] + b["height"], 0)
        self.assertFalse(
            a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]
        )

    def test_reduces_large_faces_to_fit_atlas(self):
        result = texture_export.pack_face_rectangles([(512, 512), (512, 512)])
        self.assertLess(result["scale"], 1.0)
        for tile in result["tiles"]:
            self.assertLessEqual(tile["x"] + tile["width"] + result["padding"], 512)
            self.assertLessEqual(tile["y"] + tile["height"] + result["padding"], 512)

    def test_uvs_are_mapped_to_bottom_left_tile(self):
        tile = {"x": 10, "y": 20, "width": 100, "height": 50}
        mapped = texture_export.remap_uvs_to_atlas([(0, 0), (1, 1), (0.5, 0.5)], tile, 512)
        self.assertEqual(mapped[0], (10 / 512, 20 / 512))
        self.assertEqual(mapped[1], (110 / 512, 70 / 512))

    def test_projection_scales_and_offsets_both_axes(self):
        projection = (2, 0, 0, -32, 0, 4, 0, -64)
        tile = {"x": 10, "y": 20, "width": 50, "height": 100}
        mapped = texture_export.projection_for_atlas_tile(projection, (100, 100), tile, 512)
        self.assertEqual(mapped, (1.0, 0.0, 0.0, -6.0, 0.0, 4.0, 0.0, 328.0))

    def test_atlas_tile_crop_restores_local_image_size_and_bottom_left_origin(self):
        # A 2x2 tile at bottom-left-based atlas coordinate (1, 1) contains
        # red, green / blue, white. Surrounding atlas pixels are black.
        pixels = []
        colors = [
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0, 1.0),
            (0.0, 0.0, 1.0, 1.0),
            (1.0, 1.0, 1.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
        ]
        for color in colors:
            pixels.extend(color)
        result = texture_export.extract_atlas_tile_rgba(
            pixels, atlas_size=4,
            tile={"x": 1, "y": 1, "width": 2, "height": 2},
            output_size=(4, 4),
        )
        self.assertEqual(len(result), 4 * 4 * 4)
        self.assertEqual(result[:4], [1.0, 0.0, 0.0, 1.0])
        self.assertEqual(result[4:8], [1.0, 0.0, 0.0, 1.0])
        self.assertEqual(result[8:12], [0.0, 1.0, 0.0, 1.0])
        self.assertEqual(result[-4:], [1.0, 1.0, 1.0, 1.0])

    def test_face_local_projections_keep_adjacent_classic_luxel_phase(self):
        # Original texinfo axes and projected bounds for faces 0 and 1 in
        # the committed spottest01_ericw.bsp fixture. They share y=-208.
        # Face-local projections change only the offset; the shared-edge S
        # coordinates still differ by exactly 7 classic 16-unit luxels.
        face_a = texture_export.face_local_texinfo_projection(
            (0, 1, 0, -32, 0, 0, -1, 0),
            (-352, -256, 112, 240),
            (128, 256),
        )
        face_b = texture_export.face_local_texinfo_projection(
            (0, 1, 0, 0, 0, 0, -1, 0),
            (-208, -256, 192, 240),
            (256, 256),
        )
        edge_s_a = -208 + face_a[3]
        edge_s_b = -208 + face_b[3]
        self.assertEqual(face_a[:3], (0.0, 1.0, 0.0))
        self.assertEqual(face_b[:3], (0.0, 1.0, 0.0))
        self.assertEqual(face_a[4:7], face_b[4:7])
        self.assertAlmostEqual((edge_s_a - edge_s_b) / 16.0, 7.0)
        self.assertAlmostEqual((edge_s_a - edge_s_b) % 16.0, 0.0)

    def test_inverse_projection_maps_back_to_source_axis(self):
        old = (2, 0, 0, 8)
        new = (4, 0, 0, -20)
        coordinates = texture_export.inverse_project_axis_coordinates(old, new, (0, 4, 8))
        self.assertEqual(coordinates, (18.0, 20.0, 22.0))

    def test_resample_nearest_preserves_pixel_values(self):
        pixels = [1, 0, 0, 1, 0, 1, 0, 1]
        resized = texture_export.resample_rgba_nearest(pixels, 2, 1, 4, 1)
        self.assertEqual(resized, [1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
