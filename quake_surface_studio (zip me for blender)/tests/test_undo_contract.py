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

    def test_image_mutation_operators_use_coherent_global_undo(self):
        for class_name in (
            "QSS_OT_quake_direct_bake",
            "QSS_OT_bake_scene_lights",
            "QSS_OT_undo_last_bake",
            "QSS_OT_restore_original_lightmap",
            "QSS_OT_change_lightmap_resolution",
        ):
            with self.subTest(operator=class_name):
                self.assertIn("UNDO", _operator_flags(self.source, class_name))

    def test_paint_mode_transitions_stay_out_of_the_global_undo_stack(self):
        for class_name in (
            "QSS_OT_activate_lightmap_paint",
            "QSS_OT_activate_paint",
        ):
            with self.subTest(operator=class_name):
                self.assertNotIn("UNDO", _operator_flags(self.source, class_name))

    def test_image_undo_handlers_are_registered_and_removed(self):
        self.assertIn("image_undo.register(bpy)", self.source)
        self.assertIn("image_undo.unregister(bpy)", self.source)


if __name__ == "__main__":
    unittest.main()
