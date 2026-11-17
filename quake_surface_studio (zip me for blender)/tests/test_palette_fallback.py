import os
import struct
import tempfile
import unittest

import bsp


def write_palette(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = bytes([int(value) & 255]) * 768
    with open(path, "wb") as handle:
        handle.write(data)
    return data


def write_pak(path, entries):
    """Create a minimal PACK archive from {virtual_path: bytes} entries."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = bytearray(b"PACK" + struct.pack("<ii", 0, 0))
    records = []
    for name, data in entries.items():
        raw_name = str(name).replace("\\", "/").encode("latin1")
        if len(raw_name) > 55:
            raise ValueError("PACK entry path is too long")
        offset = len(payload)
        blob = bytes(data)
        payload.extend(blob)
        records.append(
            raw_name.ljust(56, b"\0") + struct.pack("<ii", offset, len(blob))
        )
    directory_offset = len(payload)
    directory = b"".join(records)
    payload.extend(directory)
    struct.pack_into("<ii", payload, 4, directory_offset, len(directory))
    with open(path, "wb") as handle:
        handle.write(payload)


class QuakePaletteFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.id1 = os.path.join(self.root, "id1")
        self.mod = os.path.join(self.root, "ad")
        os.makedirs(self.id1)
        os.makedirs(self.mod)

    def tearDown(self):
        self.temp.cleanup()

    def test_mod_without_palette_falls_back_to_sibling_id1(self):
        expected = write_palette(
            os.path.join(self.id1, "gfx", "palette.lmp"), 41
        )
        palette, origin = bsp.find_quake_palette(self.mod)
        self.assertEqual(palette, expected)
        self.assertEqual(origin, os.path.join(self.id1, "gfx", "palette.lmp"))

    def test_mod_loose_palette_overrides_base_game_palette(self):
        write_palette(os.path.join(self.id1, "gfx", "palette.lmp"), 41)
        expected = write_palette(
            os.path.join(self.mod, "gfx", "palette.lmp"), 82
        )
        palette, origin = bsp.find_quake_palette(self.mod)
        self.assertEqual(palette, expected)
        self.assertEqual(origin, os.path.join(self.mod, "gfx", "palette.lmp"))

    def test_mod_pak_palette_precedes_base_game_loose_palette(self):
        write_palette(os.path.join(self.id1, "gfx", "palette.lmp"), 41)
        expected = bytes([93]) * 768
        write_pak(os.path.join(self.mod, "pak0.pak"), {
            "gfx/palette.lmp": expected,
        })
        palette, origin = bsp.find_quake_palette(self.mod)
        self.assertEqual(palette, expected)
        self.assertTrue(origin.endswith("pak0.pak!gfx/palette.lmp"))

    def test_mod_loose_palette_overrides_palette_in_mod_pak(self):
        packaged = bytes([93]) * 768
        write_pak(os.path.join(self.mod, "pak0.pak"), {
            "gfx/palette.lmp": packaged,
        })
        expected = write_palette(
            os.path.join(self.mod, "gfx", "palette.lmp"), 82
        )
        palette, origin = bsp.find_quake_palette(self.mod)
        self.assertEqual(palette, expected)
        self.assertEqual(origin, os.path.join(self.mod, "gfx", "palette.lmp"))

    def test_higher_numbered_pak_overrides_lower_numbered_pak(self):
        lower = bytes([31]) * 768
        higher = bytes([73]) * 768
        write_pak(os.path.join(self.mod, "pak0.pak"), {
            "gfx/palette.lmp": lower,
        })
        write_pak(os.path.join(self.mod, "pak2.pak"), {
            "gfx/palette.lmp": higher,
        })
        palette, origin = bsp.find_quake_palette(self.mod)
        self.assertEqual(palette, higher)
        self.assertTrue(origin.endswith("pak2.pak!gfx/palette.lmp"))

    def test_installation_root_prefers_id1_palette(self):
        expected = write_palette(
            os.path.join(self.id1, "gfx", "palette.lmp"), 52
        )
        write_palette(os.path.join(self.mod, "gfx", "palette.lmp"), 84)
        palette, origin = bsp.find_quake_palette(self.root)
        self.assertEqual(palette, expected)
        self.assertEqual(origin, os.path.join(self.id1, "gfx", "palette.lmp"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
