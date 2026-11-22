"""Static contracts for BSP export paths that do not require Blender's bpy module."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon.py"
ADDON_SOURCE = ADDON_PATH.read_text(encoding="utf-8")
ADDON_TREE = ast.parse(ADDON_SOURCE)


def _find_function(container, name):
    for node in ast.walk(container):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} was not found in addon.py")


def _source_for(node):
    return ast.get_source_segment(ADDON_SOURCE, node) or ""


class EnhancedBSPExportContractTests(unittest.TestCase):
    def test_world_chart_face_context_is_defined_before_it_is_used(self):
        function = _find_function(ADDON_TREE, "_build_enhanced_lightmap_payload")
        context = _source_for(function)
        face_info_loads = [
            node.lineno for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and node.id == "face_info"
            and isinstance(node.ctx, ast.Load)
        ]
        face_info_stores = [
            node.lineno for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and node.id == "face_info"
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ]

        self.assertTrue(face_info_stores, "Enhanced export must construct face_info locally.")
        self.assertTrue(face_info_loads, "Enhanced export must use its face-specific context.")
        self.assertLess(min(face_info_stores), min(face_info_loads))
        self.assertIn('face_attrs["qss_lm_world_chart"]', context)
        self.assertIn('face_attrs["qss_lm_chart_axis_s"]', context)
        self.assertIn('face_attrs["qss_lm_chart_axis_t"]', context)
        self.assertIn("world_chart_grid_positions(", context)
        self.assertIn("sample_rgb_from_world_chart_positions(", context)

    def test_missing_companion_map_link_is_not_resolved_to_blender_working_directory(self):
        function = _find_function(ADDON_TREE, "_qss_prepare_companion_map_export")
        context = _source_for(function)

        raw_check = 'source_map_raw = str(obj.get("qss_source_map_path", "") or "").strip()'
        empty_return = 'if not source_map_raw:\\n        return None'
        self.assertIn(raw_check, context)
        self.assertIn(empty_return, repr(context))
        self.assertLess(context.index("if not source_map_raw:"), context.index("os.path.abspath(source_map_raw)"))
        self.assertNotIn('os.path.abspath(str(obj.get("qss_source_map_path", "") or ""))', context)

    def test_non_map_directory_metadata_is_ignored_as_no_companion(self):
        function = _find_function(ADDON_TREE, "_qss_prepare_companion_map_export")
        context = _source_for(function)
        extension_guard = 'os.path.splitext(source_map_raw)[1].lower() != ".map"'
        self.assertIn(extension_guard, context)
        guard = context.index(extension_guard)
        self.assertLess(guard, context.index("source_map = os.path.abspath(source_map_raw)"))
        self.assertIn('obj["qss_map_sync_status"] = "NO_COMPANION"', context[guard:])
        self.assertIn('obj.pop("qss_source_map_path", None)', context[guard:])
        self.assertIn('raise map_sync.MapSyncError(f"Linked companion MAP is missing: {source_map}")', context)

    def test_companion_map_preparation_and_write_errors_do_not_abort_bsp_export(self):
        operator_class = next(
            node for node in ADDON_TREE.body
            if isinstance(node, ast.ClassDef) and node.name == "QSS_OT_export_bsp"
        )
        execute = _find_function(operator_class, "execute")
        context = _source_for(execute)

        expected_handler = "except (map_sync.MapSyncError, OSError, UnicodeError) as map_exc:"
        self.assertGreaterEqual(context.count(expected_handler), 2)
        self.assertIn("_qss_prepare_companion_map_export(context, obj, output)", context)
        self.assertIn("_qss_commit_companion_map_export(obj, prepared_map)", context)
        self.assertIn("Companion MAP was not updated (BSP export succeeded)", context)
        self.assertIn('return {"FINISHED"}', context)


if __name__ == "__main__":
    unittest.main()
