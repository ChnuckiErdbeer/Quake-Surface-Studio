import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import palette_utils


class QuakePaletteUtilityTests(unittest.TestCase):
    def test_quake_binary_palette_is_serialized_as_jasc_pal(self):
        palette = bytes((value % 256 for value in range(768)))
        text = palette_utils.palette_to_jasc_text(palette)
        lines = text.splitlines()
        self.assertEqual(lines[:3], ["JASC-PAL", "0100", "256"])
        self.assertEqual(len(lines), 259)
        self.assertEqual(lines[3], "0 1 2")
        self.assertEqual(lines[-1], "253 254 255")

    def test_invalid_palette_sizes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "768"):
            palette_utils.palette_to_jasc_text(b"short")

    def test_material_zone_converter_builds_all_four_mip_levels(self):
        palette = bytes(channel for value in range(256) for channel in (value, value, value))
        rgba = bytes((120, 120, 120, 255)) * (16 * 16)
        levels, stats = palette_utils.convert_rgba8_mip_chain(
            16, 16, rgba, palette,
            settings={"segments": 4, "ramp_candidates_per_zone": 5},
        )
        self.assertEqual([len(level) for level in levels], [256, 64, 16, 4])
        self.assertEqual(len(stats), 4)
        self.assertTrue(all(len(set(level)) >= 1 for level in levels))
        self.assertTrue(all(0 <= index < 224 for level in levels for index in level))

    def test_non_brace_mip_chain_ignores_source_alpha_at_every_level(self):
        palette = bytes(channel for value in range(256) for channel in (value, value, value))
        opaque = bytearray()
        varied_alpha = bytearray()
        for y in range(16):
            for x in range(16):
                pixel = (x * 13 + y * 7) % 256
                opaque.extend((pixel, pixel, pixel, 255))
                varied_alpha.extend((pixel, pixel, pixel, 0 if (x + y) % 2 else 255))
        settings = {"segments": 4, "ramp_candidates_per_zone": 5}
        expected, _ = palette_utils.convert_rgba8_mip_chain(
            16, 16, opaque, palette, settings=settings, transparent=False
        )
        actual, _ = palette_utils.convert_rgba8_mip_chain(
            16, 16, varied_alpha, palette, settings=settings, transparent=False
        )
        self.assertEqual(actual, expected)

    def test_material_zone_mip_chain_preserves_brace_transparency(self):
        palette = bytes(channel for value in range(256) for channel in (value, value, value))
        rgba = bytearray(bytes((120, 120, 120, 255)) * (16 * 16))
        for y in range(2):
            for x in range(2):
                rgba[(y * 16 + x) * 4 + 3] = 0
        levels, stats = palette_utils.convert_rgba8_mip_chain(
            16, 16, rgba, palette,
            settings={"segments": 4, "ramp_candidates_per_zone": 5},
            transparent=True,
        )
        self.assertEqual(levels[0][0], 255)
        self.assertGreater(stats[0]["transparent_pixels"], 0)
        self.assertEqual(len(levels), 4)

    def test_material_zone_mip_chain_keeps_fullbright_mask(self):
        palette = bytes(channel for value in range(256) for channel in (value, value, value))
        rgba = bytes((120, 120, 120, 255)) * (16 * 16)
        mask = bytearray(16 * 16)
        mask[0] = 1
        levels, stats = palette_utils.convert_rgba8_mip_chain(
            16, 16, rgba, palette,
            settings={"segments": 4, "ramp_candidates_per_zone": 5},
            fullbright_mask=mask,
        )
        self.assertGreaterEqual(levels[0][0], 224)
        self.assertEqual(stats[0]["fullbright_pixels"], 1)

    def test_face_memory_estimate_includes_peak_atlas_allocation(self):
        result = palette_utils.estimate_face_local_paint_bytes(
            [(16, 16), (65, 33)], bytes_per_face_pixel=4
        )
        self.assertEqual(result["face_count"], 2)
        self.assertEqual(result["face_image_bytes"], 16 * 16 * 4 + 72 * 40 * 4)
        self.assertEqual(result["atlas_bytes"], 512 * 512 * 16)
        self.assertEqual(result["peak_pixel_bytes"],
                         result["face_image_bytes"] + result["atlas_bytes"])

    def test_single_face_does_not_include_shared_atlas(self):
        result = palette_utils.estimate_face_local_paint_bytes([(520, 2)])
        self.assertEqual(result["face_image_bytes"], 512 * 8 * 4)
        self.assertEqual(result["atlas_bytes"], 0)

    def test_float_face_buffers_are_accounted_for(self):
        result = palette_utils.estimate_face_local_paint_bytes(
            [(8, 8)], bytes_per_face_pixel=16
        )
        self.assertEqual(result["peak_pixel_bytes"], 8 * 8 * 16)

    def test_mib_formatting(self):
        self.assertEqual(palette_utils.format_mib(1024 * 1024), "1.0 MiB")


if __name__ == "__main__":
    unittest.main()
