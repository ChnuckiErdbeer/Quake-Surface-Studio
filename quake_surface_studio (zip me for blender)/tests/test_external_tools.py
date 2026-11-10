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

    def test_builds_decoupled_light_command_without_shell_string(self):
        with tempfile.TemporaryDirectory() as root:
            game = os.path.join(root, "id1")
            os.makedirs(game)
            source = os.path.join(game, "maps", "test.bsp")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"BSP")
            command = external_tools.build_decoupled_light_command(
                os.path.join(root, "light.exe"),
                source,
                world_units_per_luxel=16,
                quake_root=root,
                game_dir=game,
            )
            self.assertEqual(command[1:4], [
                "-verbose", "-world_units_per_luxel", "16"
            ])
            self.assertIn("-basedir", command)
            self.assertIn("-gamedir", command)
            self.assertEqual(command[-1], source)

    def test_rejects_invalid_decoupled_luxel_scale(self):
        for scale in (0, -1, 1024.01, 8192):
            with self.subTest(scale=scale):
                with self.assertRaises(ValueError):
                    external_tools.build_decoupled_light_command(
                        "/tools/light", "/maps/test.bsp", world_units_per_luxel=scale
                    )

    def test_accepts_one_world_unit_per_luxel(self):
        command = external_tools.build_decoupled_light_command(
            "/tools/light", "/maps/test.bsp", world_units_per_luxel=1
        )
        self.assertEqual(command[1:4], [
            "-verbose", "-world_units_per_luxel", "1"
        ])

    def test_launch_process_handle_exposes_process_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            log_path = os.path.join(temp, "launch.log")
            process = external_tools.launch_process_handle(
                [sys.executable, "-c", "print('qss-process-ok')"],
                cwd=temp,
                log_path=log_path,
            )
            self.assertGreater(process.pid, 0)
            self.assertEqual(process.wait(timeout=10), 0)
            with open(log_path, "r", encoding="utf-8") as handle:
                self.assertIn("qss-process-ok", handle.read())

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
