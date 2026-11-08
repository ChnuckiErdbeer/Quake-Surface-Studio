import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import quake_paths


def write_pak(path, entries):
    payload = bytearray()
    records = []
    for name, data in entries:
        offset = 12 + len(payload)
        payload.extend(data)
        records.append((name, offset, len(data)))
    directory_offset = 12 + len(payload)
    directory = bytearray()
    for name, offset, length in records:
        encoded = name.encode("latin1")[:55].ljust(56, b"\0")
        directory.extend(struct.pack("<56sii", encoded, offset, length))
    with open(path, "wb") as handle:
        handle.write(struct.pack("<4sii", b"PACK", directory_offset, len(directory)))
        handle.write(payload)
        handle.write(directory)


class QuakePathsTests(unittest.TestCase):
    def test_id1_path_normalizes_to_install_root(self):
        with tempfile.TemporaryDirectory() as temp:
            id1 = os.path.join(temp, "id1")
            os.makedirs(id1)
            self.assertEqual(quake_paths.normalize_quake_root(id1), temp)

    def test_discovers_id1_and_mod_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            os.makedirs(os.path.join(temp, "id1", "maps"))
            os.makedirs(os.path.join(temp, "hipnotic", "maps"))
            os.makedirs(os.path.join(temp, "unrelated"))
            items = quake_paths.discover_game_dirs(temp)
            self.assertEqual([item["id"] for item in items], ["id1", "hipnotic"])
            self.assertEqual(quake_paths.resolve_game_dir(temp, "hipnotic"),
                             os.path.join(temp, "hipnotic"))

    def test_discovers_mod_with_pak_even_without_loose_maps(self):
        with tempfile.TemporaryDirectory() as temp:
            os.makedirs(os.path.join(temp, "id1"))
            mod = os.path.join(temp, "custommod")
            os.makedirs(mod)
            write_pak(os.path.join(mod, "pak0.pak"), [("maps/test.bsp", b"map")])
            self.assertIn("custommod", [item["id"] for item in quake_paths.discover_game_dirs(temp)])

    def test_loose_maps_override_pak_and_higher_pak_overrides_lower_pak(self):
        with tempfile.TemporaryDirectory() as temp:
            os.makedirs(os.path.join(temp, "maps"))
            write_pak(os.path.join(temp, "pak0.pak"), [
                ("maps/e1m1.bsp", b"pak0"),
                ("maps/e1m2.bsp", b"pak0-two"),
            ])
            write_pak(os.path.join(temp, "pak1.pak"), [
                ("maps/e1m1.bsp", b"pak1"),
                ("maps/e1m2.bsp", b"pak1-two"),
            ])
            with open(os.path.join(temp, "maps", "e1m1.bsp"), "wb") as handle:
                handle.write(b"loose")
            found = {item["path"]: item for item in quake_paths.discover_maps(temp)}
            self.assertEqual(set(found), {"maps/e1m1.bsp", "maps/e1m2.bsp"})
            self.assertEqual(found["maps/e1m1.bsp"]["kind"], "loose")
            self.assertEqual(found["maps/e1m2.bsp"]["source_label"], "pak1.pak")
            self.assertEqual(quake_paths.read_map_entry(found["maps/e1m2.bsp"]), b"pak1-two")

    def test_extracts_pak_map_to_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            write_pak(os.path.join(temp, "pak0.pak"), [("maps/e1m1.bsp", b"original-bsp")])
            entry = quake_paths.discover_maps(temp)[0]
            cache = os.path.join(temp, "cache")
            path = quake_paths.extract_map(entry, cache)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), b"original-bsp")
            self.assertEqual(quake_paths.extract_map(entry, cache), path)

    def test_pak_directory_rejects_traversal_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            pak = os.path.join(temp, "pak0.pak")
            write_pak(pak, [("../outside.bsp", b"unsafe"), ("maps/ok.bsp", b"ok")])
            self.assertEqual([item["path"] for item in quake_paths.read_pak_directory(pak)],
                             ["maps/ok.bsp"])

    def test_config_file_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "qss", "config.json")
            expected = {"quake_root": temp, "active_game_dir": os.path.join(temp, "id1")}
            quake_paths.save_config(expected, path)
            loaded = quake_paths.load_config(path)
            self.assertEqual(loaded["quake_root"], expected["quake_root"])
            self.assertEqual(loaded["active_game_dir"], expected["active_game_dir"])
            self.assertEqual(loaded["config_version"], quake_paths.CONFIG_VERSION)

    def test_missing_or_invalid_config_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "missing.json")
            self.assertEqual(quake_paths.load_config(path), {})
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{ broken")
            self.assertEqual(quake_paths.load_config(path), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
