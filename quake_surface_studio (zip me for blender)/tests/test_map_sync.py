import os
import tempfile
import unittest

import map_sync


class MapSyncTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            "// TrenchBroom source comment\n"
            "{\n"
            '    "classname" "worldspawn"\n'
            '    "wad" "custom/not-found.wad"\n'
            "    {\n"
            "        ( 0 0 0 ) ( 64 0 0 ) ( 64 64 0 ) stone 0 0 0 1 1\n"
            "    }\n"
            "}\n"
            "{\n"
            '    "classname" "light"\n'
            '    "origin" "16 32 48"\n'
            '    "light" "300"\n'
            '    "_color" "1 0.5 0.25"\n'
            '    "_unknown_key" "keep me"\n'
            "}\n"
            "{\n"
            '    "classname" "info_player_start"\n'
            '    "origin" "8 8 8"\n'
            "}\n"
        )

    def test_parser_ignores_brush_contents_and_retains_entity_values(self):
        entities = map_sync.parse_map_entities(self.source)
        self.assertEqual(len(entities), 3)
        self.assertEqual(entities[0]["values"]["wad"], "custom/not-found.wad")
        self.assertEqual(entities[1]["values"]["classname"], "light")
        self.assertEqual(entities[1]["values"]["_unknown_key"], "keep me")

    def test_light_patch_preserves_brushes_comments_and_unknown_keys(self):
        result = map_sync.apply_entity_changes(
            self.source, {1: {"origin": "20 32 48", "_color": "0.2 0.4 1.0", "delay": "2"}}
        )
        output = result["text"]
        self.assertIn("// TrenchBroom source comment", output)
        self.assertIn("( 0 0 0 ) ( 64 0 0 ) ( 64 64 0 ) stone 0 0 0 1 1", output)
        self.assertIn('"wad" "custom/not-found.wad"', output)
        self.assertIn('"_unknown_key" "keep me"', output)
        self.assertIn('"origin" "20 32 48"', output)
        self.assertIn('"delay" "2"', output)
        self.assertEqual(len(map_sync.parse_map_entities(output)), 3)

    def test_remove_and_append_update_entity_indices(self):
        result = map_sync.apply_entity_changes(
            self.source,
            remove_entities={1},
            append_entities=[{"classname": "light", "origin": "1 2 3", "light": "100"}],
        )
        self.assertEqual(result["old_to_new"], {0: 0, 2: 1})
        self.assertEqual(result["appended_indices"], [2])
        entities = map_sync.parse_map_entities(result["text"])
        self.assertEqual(len(entities), 3)
        self.assertEqual(entities[1]["values"]["classname"], "info_player_start")
        self.assertEqual(entities[2]["values"]["origin"], "1 2 3")

    def test_entity_matching_uses_classname_and_origin(self):
        map_entities = map_sync.parse_map_entities(self.source)
        bsp_entities = [
            {"classname": "worldspawn"},
            {"classname": "light", "origin": "16.0 32 48"},
            {"classname": "info_player_start", "origin": "8 8 8"},
        ]
        self.assertEqual(
            map_sync.match_bsp_entities_to_map_entities(bsp_entities, map_entities),
            {0: 0, 1: 1},
        )

    def test_malformed_map_is_rejected_before_editing(self):
        with self.assertRaises(map_sync.MapSyncError):
            map_sync.parse_map_entities('{ "classname" "light" ')

    def test_companion_discovery_is_same_directory_and_basename_only(self):
        with tempfile.TemporaryDirectory() as directory:
            bsp_path = os.path.join(directory, "arena.bsp")
            map_path = os.path.join(directory, "arena.map")
            with open(bsp_path, "wb") as handle:
                handle.write(b"bsp")
            with open(map_path, "w", encoding="utf-8") as handle:
                handle.write(self.source)
            self.assertEqual(map_sync.find_companion_map(bsp_path), map_path)
            self.assertEqual(map_sync.find_companion_map(os.path.join(directory, "other.bsp")), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
