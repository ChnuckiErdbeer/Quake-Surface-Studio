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


def _assigned_value(tree, name):
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Module assignment {name!r} was not found")


INIT_PATH = ADDON_PATH.parent / "__init__.py"
INIT_TREE = ast.parse(INIT_PATH.read_text(encoding="utf-8"))


class EnhancedBSPExportContractTests(unittest.TestCase):
    def test_sidebar_version_matches_installed_addon_version(self):
        sidebar_version = _assigned_value(ADDON_TREE, "ADDON_VERSION")
        package_info = _assigned_value(INIT_TREE, "bl_info")
        self.assertEqual(sidebar_version, package_info["version"])

    def test_bsp_export_validation_is_available_in_main_sidebar_panel(self):
        panel = next(
            node for node in ADDON_TREE.body
            if isinstance(node, ast.ClassDef) and node.name == "QSS_PT_project"
        )
        draw = _find_function(panel, "draw")
        context = _source_for(draw)
        self.assertIn("QSS_OT_validate_bsp_export.bl_idname", context)
        self.assertIn('text="Validate Last Export"', context)
        self.assertIn("_qss_last_export_path(obj)", context)
        self.assertIn("validate_row.enabled = bool(last_export)", context)

    def test_export_validator_uses_recorded_source_and_last_export_without_file_dialog(self):
        operator = next(
            node for node in ADDON_TREE.body
            if isinstance(node, ast.ClassDef) and node.name == "QSS_OT_validate_bsp_export"
        )
        self.assertNotIn("ImportHelper", [ast.unparse(base) for base in operator.bases])
        self.assertFalse(any(
            isinstance(node, ast.FunctionDef) and node.name in {"invoke", "draw"}
            for node in operator.body
        ))
        execute = _find_function(operator, "execute")
        context = _source_for(execute)
        self.assertIn('obj.get("qss_source_path", "")', context)
        self.assertIn("_qss_last_export_path(obj)", context)
        self.assertIn("export_validation.validate_export_pair(source, exported)", context)
        self.assertNotIn("self.filepath", context)
        self.assertNotIn("self.source_bsp", context)
        self.assertNotIn("self.lit_file", context)

    def test_unedited_source_lightmaps_are_passed_through_before_atlas_sampling(self):
        function = _find_function(ADDON_TREE, "_patch_lightmap_lump")
        context = _source_for(function)
        guard = "lightmap_export_utils.should_preserve_source_lightmaps("
        self.assertIn(guard, context)
        self.assertLess(context.index(guard), context.index("image.pixels.foreach_get(px)"))
        passthrough = context[context.index(guard):context.index("if not image_name:")]
        self.assertIn("return (", passthrough)
        self.assertIn("lighting_source,", passthrough)
        self.assertIn("original_lit,", passthrough)
        self.assertIn("output_faces_lump or parsed.lumps[bsp.LUMP_FACES]", passthrough)
        self.assertIn("painted_override_active", passthrough)
        self.assertIn("has_face_local_projection", passthrough)

    def test_enhanced_export_does_not_strip_or_create_bspx_lightmaps_on_passthrough(self):
        function = _find_function(ADDON_TREE, "_export_object")
        context = _source_for(function)
        self.assertIn(
            "if lightmap_export_mode == 'ENHANCED' and 'DECOUPLED_LM' in lightmap_bspx_updates:",
            context,
        )
        self.assertIn("'RGBLIGHTING' in new_bspx_lumps", context)
        self.assertIn("'RGBLIGHTING' in lightmap_bspx_updates", context)


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
