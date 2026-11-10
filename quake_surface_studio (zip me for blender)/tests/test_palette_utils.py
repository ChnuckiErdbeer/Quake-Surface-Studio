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

    def test_face_memory_estimate_includes_peak_atlas_allocation(self):
        result = palette_utils.estimate_face_local_paint_bytes(
            [(16, 16), (65, 33)], bytes_per_face_pixel=4
        )
        self.assertEqual(result["face_count"], 2)
        self.assertEqual(result["face_image_bytes"], 24 * 24 * 4 + 72 * 40 * 4)
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
