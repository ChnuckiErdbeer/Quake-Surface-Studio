"""Static contracts for SLOPGATE's Blender global-undo boundaries.

These tests run without Blender. Runtime undo behavior still needs Blender 5.3
integration tests because Blender's image-paint undo is not available in CI.
"""
import ast
import os
import unittest


ADDON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "addon.py")
)


def _operator_flags(source, class_name):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    if any(
                        isinstance(target, ast.Name) and target.id == "bl_options"
                        for target in statement.targets
                    ):
                        return ast.literal_eval(statement.value)
            return {"REGISTER"}
    raise AssertionError(f"Operator class {class_name} was not found")


class UndoContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ADDON_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_mesh_and_material_toggle_operations_are_undoable(self):
        for class_name in (
            "QSS_OT_detach_faces",
            "QSS_OT_toggle_textures",
            "QSS_OT_toggle_source_lightmaps",
            "QSS_OT_toggle_painted_textures",
            "QSS_OT_toggle_painted_lightmaps",
            "QSS_OT_isolate_faces",
            "QSS_OT_close_active_map",
        ):
            with self.subTest(operator=class_name):
                self.assertIn("UNDO", _operator_flags(self.source, class_name))

    def test_image_pixel_and_paint_mode_operations_do_not_push_global_undo(self):
        # Direct Python image.pixels.foreach_set() writes and paint-mode
        # transitions need explicit image snapshots/native paint undo instead.
        for class_name in (
            "QSS_OT_quake_direct_bake",
            "QSS_OT_bake_scene_lights",
            "QSS_OT_activate_lightmap_paint",
            "QSS_OT_activate_paint",
            "QSS_OT_undo_last_bake",
            "QSS_OT_restore_original_lightmap",
        ):
            with self.subTest(operator=class_name):
                self.assertNotIn("UNDO", _operator_flags(self.source, class_name))


if __name__ == "__main__":
    unittest.main()
