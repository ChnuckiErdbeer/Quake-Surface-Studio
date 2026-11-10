"""Standard-library smoke tests for QSS's in-process Quake converter."""
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import palette_utils


def synthetic_palette():
    values = bytearray()
    for index in range(256):
        values.extend((index, (index * 3) % 256, (index * 7) % 256))
    return bytes(values)


class QuakeTextureConverterSmokeTests(unittest.TestCase):
    def test_default_zone_ramp_candidates_match_confirmed_setting(self):
        self.assertEqual(palette_utils.DEFAULT_SETTINGS["ramp_candidates_per_zone"], 5)

    def test_rgba_conversion_returns_indexed_pixels_and_preserves_alpha(self):
        width = height = 16
        rgba = bytearray()
        for y in range(height):
            for x in range(width):
                if x < 2:
                    rgba.extend((0, 0, 0, 0))
                elif x < 8:
                    rgba.extend((106, 73, 43, 255))
                else:
                    rgba.extend((45, 92, 151, 255))
        settings = dict(palette_utils.DEFAULT_SETTINGS)
        settings.update({"segments": 8, "detail": 0.0, "ramp_candidates_per_zone": 5})
        indices, stats = palette_utils.convert_rgba8(
            width, height, rgba, synthetic_palette(), settings
        )
        self.assertEqual(len(indices), width * height)
        self.assertEqual(stats["pixels"], width * height)
        self.assertEqual(stats["transparent_pixels"], height * 2)
        for y in range(height):
            self.assertEqual(indices[y * width], 255)
            self.assertEqual(indices[y * width + 1], 255)
            for x in range(2, width):
                self.assertNotEqual(indices[y * width + x], 255)

    def test_fullbright_mask_uses_only_fullbright_palette_entries(self):
        width = height = 8
        rgba = bytes((220, 180, 100, 255)) * (width * height)
        settings = dict(palette_utils.DEFAULT_SETTINGS)
        settings.update({"segments": 4, "detail": 0.0})
        mask = bytearray([0] * (width * height))
        mask[0] = 1
        indices, stats = palette_utils.convert_rgba8(
            width, height, rgba, synthetic_palette(), settings, mask
        )
        self.assertGreaterEqual(indices[0], 224)
        self.assertLess(indices[0], 255)
        self.assertEqual(stats["fullbright_pixels"], 1)

    def test_indexed_png_writer_emits_palette_transparency_and_valid_chunks(self):
        width, height = 3, 2
        palette = synthetic_palette()
        pixels = bytes((1, 2, 255, 4, 5, 6))
        with tempfile.TemporaryDirectory() as temp:
            output = os.path.join(temp, "indexed.png")
            palette_utils.save_indexed_png(output, width, height, pixels, palette)
            data = open(output, "rb").read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        offset = 8
        chunks = {}
        while offset < len(data):
            size = struct.unpack_from(">I", data, offset)[0]
            kind = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + size]
            expected_crc = struct.unpack_from(">I", data, offset + 8 + size)[0]
            self.assertEqual(
                expected_crc,
                zlib.crc32(kind + payload) & 0xFFFFFFFF,
            )
            chunks[kind] = payload
            offset += size + 12
            if kind == b"IEND":
                break
        self.assertEqual(len(chunks[b"PLTE"]), 768)
        self.assertEqual(len(chunks[b"tRNS"]), 256)
        self.assertEqual(chunks[b"tRNS"][255], 0)
        self.assertEqual(chunks[b"tRNS"][254], 255)
        decoded = zlib.decompress(chunks[b"IDAT"])
        self.assertEqual(decoded, b"\x00" + pixels[:3] + b"\x00" + pixels[3:])

    def test_invalid_palette_and_dimensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "768"):
            palette_utils.convert_rgba8(1, 1, bytes((1, 2, 3, 255)), b"short")
        with self.assertRaisesRegex(ValueError, "16-megapixel"):
            palette_utils.convert_rgba8(5000, 5000, b"", synthetic_palette())


if __name__ == "__main__":
    unittest.main()
