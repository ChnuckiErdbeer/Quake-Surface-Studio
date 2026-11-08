import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import external_tools


class ExternalToolsTests(unittest.TestCase):
    def test_resolves_windows_and_unix_binary_names_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "QBSP.EXE" if os.name == "nt" else "qbsp")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("placeholder")
            self.assertEqual(external_tools.resolve_tool(temp, "qbsp"), path)
            self.assertEqual(external_tools.discover_tools(temp)["qbsp"], path)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ValueError):
            external_tools.resolve_tool(".", "not-a-real-tool")

    def test_missing_tool_directory_returns_empty_paths(self):
        self.assertEqual(external_tools.discover_tools("/does/not/exist")["light"], "")

    def test_builds_ironwail_map_command_with_mod_and_developer_mode(self):
        with tempfile.TemporaryDirectory() as root:
            game = os.path.join(root, "hipnotic")
            os.makedirs(game)
            command = external_tools.build_ironwail_command(
                "/tools/ironwail", root, game, map_path="maps/hip1m1.bsp"
            )
            self.assertEqual(command[:5], [
                "/tools/ironwail", "-basedir", root, "-game", "hipnotic"
            ])
            self.assertEqual(command[-4:], ["+developer", "1", "+map", "hip1m1"])

    def test_game_directory_itself_can_be_the_engine_base_directory(self):
        with tempfile.TemporaryDirectory() as game:
            os.makedirs(os.path.join(game, "maps"))
            command = external_tools.build_ironwail_command(
                "/tools/ironwail", game, game, map_path="maps/custom.bsp"
            )
            self.assertEqual(command[:3], ["/tools/ironwail", "-basedir", game])
            self.assertEqual(command[-4:], ["+developer", "1", "+map", "custom"])

    def test_builds_ironwail_demo_command(self):
        with tempfile.TemporaryDirectory() as root:
            game = os.path.join(root, "id1")
            os.makedirs(os.path.join(game, "demos"))
            demo = os.path.join(game, "demos", "demo1.dem")
            with open(demo, "wb") as handle:
                handle.write(b"")
            command = external_tools.build_ironwail_command(
                "/tools/ironwail", root, game, demo_file=demo, timedemo=True
            )
            self.assertEqual(command[-4:], ["+developer", "1", "+timedemo", "demos/demo1"])

    def test_rejects_demo_outside_game_directory(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            game = os.path.join(root, "id1")
            os.makedirs(game)
            demo = os.path.join(outside, "demo.dem")
            with open(demo, "wb") as handle:
                handle.write(b"")
            with self.assertRaises(ValueError):
                external_tools.build_ironwail_command(
                    "/tools/ironwail", root, game, demo_file=demo
                )

    def test_rejects_ambiguous_target(self):
        with self.assertRaises(ValueError):
            external_tools.build_ironwail_command(
                "/tools/ironwail", "", "", map_path="e1m1", demo_file="demo.dem"
            )

    def test_external_command_captures_output_and_return_code(self):
        result = external_tools.run_command(
            sys.executable, ["-c", "print('qss-external-ok')"], timeout=10
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("qss-external-ok", result["stdout"])

    def test_external_command_timeout_is_reported(self):
        result = external_tools.run_command(
            sys.executable, ["-c", "import time; time.sleep(2)"], timeout=1
        )
        self.assertEqual(result["status"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
