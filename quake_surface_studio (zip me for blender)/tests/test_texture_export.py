import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import texture_export


class TextureExportHelperTests(unittest.TestCase):
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
