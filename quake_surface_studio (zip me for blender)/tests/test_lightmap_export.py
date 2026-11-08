import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import lightmap_export


class LightmapExportTests(unittest.TestCase):
    def test_resolution_selects_expected_lmshift(self):
        expected = {1: 4, 2: 3, 4: 2, 8: 1}
        for resolution, shift in expected.items():
            with self.subTest(resolution=resolution):
                result = lightmap_export.choose_luxel_grid(
                    [0, 64], [0, 64], resolution
                )
                self.assertEqual(result[0], shift)
                self.assertEqual(result[3:], (64 // (1 << shift) + 1,) * 2)

    def test_oversized_face_coarsens_to_engine_limit(self):
        shift, s_min, t_min, width, height = lightmap_export.choose_luxel_grid(
            [0, 2048], [0, 1024], 8
        )
        self.assertGreaterEqual(shift, 4)
        self.assertLessEqual(width, 256)
        self.assertLessEqual(height, 256)

    def test_fails_when_face_exceeds_limit_even_at_classic_spacing(self):
        with self.assertRaisesRegex(ValueError, 'even at 16 units per luxel'):
            lightmap_export.choose_luxel_grid([0, 8192], [0, 8192], 8)

    def test_bilinear_sampler_interpolates_four_pixels(self):
        pixels = (
            0.0, 0.0, 0.0, 1.0,
            1.0, 0.0, 0.0, 1.0,
            0.0, 1.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        )
        sampled = lightmap_export.bilinear_sample_rgba(pixels, 2, 2, 0.5, 0.5)
        self.assertEqual(sampled, (0.5, 0.5, 0.25, 1.0))

    def test_face_atlas_sampling_converts_linear_rgb_to_bytes(self):
        pixels = (0.5, 0.25, 1.0, 1.0) * 16
        sampled = lightmap_export.sample_face_rgb_from_atlas(
            pixels, image_size=4, working_resolution=1,
            atlas_x=0, atlas_y=0, gutter=0, pixels_per_luxel=1,
            base_s_min=0, base_t_min=0, s_min=0, t_min=0,
            sample_width=1, sample_height=1, spacing=16,
        )
        self.assertEqual(sampled, bytes((128, 64, 255)))

    def test_builds_face_ordered_extension_with_classic_prefix_offsets(self):
        records = {
            0: {"shift": 3, "width": 2, "height": 1, "rgb": bytes((255, 0, 0, 0, 255, 0))},
            2: {"shift": 2, "width": 1, "height": 2, "rgb": bytes((0, 0, 255, 255, 255, 255))},
        }
        result = lightmap_export.build_lightmap_extension_data(3, records, base_sample_count=10)
        self.assertEqual(result["LMSHIFT"], bytes((3, 4, 2)))
        self.assertEqual(result["LMSTYLE"], bytes((0, 255, 0)))
        self.assertEqual(
            result["LMOFFSET"],
            b"".join((int(10).to_bytes(4, "little"), int(0xFFFFFFFF).to_bytes(4, "little"),
                      int(12).to_bytes(4, "little")))
        )
        self.assertEqual(result["RGBLIGHTING_APPEND"], records[0]["rgb"] + records[2]["rgb"])
        self.assertEqual(result["LIGHTING_APPEND"], bytes((54, 182, 18, 255)))
        self.assertEqual(result["enhanced_sample_count"], 4)


    def test_arbitrary_coordinate_sampler_matches_classic_grid_centres(self):
        pixels = []
        for y in range(4):
            for x in range(4):
                pixels.extend((x / 3.0, y / 3.0, 0.5, 1.0))
        sampled = lightmap_export.sample_face_rgb_at_coordinates(
            pixels, image_size=4, working_resolution=1,
            atlas_x=0, atlas_y=0, gutter=0, pixels_per_luxel=1,
            base_s_min=0, base_t_min=0,
            s_coordinates=(0, 16), t_coordinates=(0, 16),
        )
        self.assertEqual(len(sampled), 12)
        self.assertEqual(sampled[0:3], bytes((43, 213, 128)))
        self.assertEqual(sampled[9:12], bytes((213, 43, 128)))

    def test_arbitrary_coordinate_sampler_rejects_non_finite_coordinates(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            lightmap_export.sample_face_rgb_at_coordinates(
                [0.0, 0.0, 0.0, 1.0] * 4, 2, 1, 0, 0, 0, 1,
                0, 0, (float("nan"),), (0,),
            )

    def test_rejects_invalid_face_sample_buffer(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            lightmap_export.build_lightmap_extension_data(
                1, {0: {"shift": 3, "width": 2, "height": 2, "rgb": bytes(3)}}, 0
            )

    def test_rejects_invalid_resolution_and_shift(self):
        with self.assertRaises(ValueError):
            lightmap_export.choose_luxel_grid([0, 64], [0, 64], 3)
        with self.assertRaisesRegex(ValueError, 'invalid LMSHIFT'):
            lightmap_export.build_lightmap_extension_data(
                1, {0: {"shift": 5, "width": 1, "height": 1, "rgb": bytes(3)}}, 0
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
