"""Static contracts for SLOPGATE's Ctrl+Z / Ctrl+Shift+Z integration.

Blender runtime tests are still required for image datablock undo and native
Texture Paint stroke history; these tests protect the operator/data contract.
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


def _class_source(source, class_name):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"Operator class {class_name} was not found")


class UndoContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ADDON_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_image_datablock_edits_use_global_undo(self):
        for class_name in (
            "QSS_OT_quake_direct_bake",
            "QSS_OT_bake_scene_lights",
            "QSS_OT_undo_last_bake",
            "QSS_OT_restore_original_lightmap",
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

    def test_paint_mode_entry_does_not_insert_global_undo_steps(self):
        for class_name in ("QSS_OT_activate_lightmap_paint", "QSS_OT_activate_paint"):
            with self.subTest(operator=class_name):
                self.assertNotIn("UNDO", _operator_flags(self.source, class_name))

    def test_bake_undo_and_restore_use_image_id_swaps(self):
        undo_source = _class_source(self.source, "QSS_OT_undo_last_bake")
        restore_source = _class_source(self.source, "QSS_OT_restore_original_lightmap")
        self.assertIn("_qss_set_current_lightmap_image", undo_source)
        self.assertIn("_qss_set_current_lightmap_image", restore_source)
        self.assertNotIn("_copy_image_pixels", undo_source)
        self.assertNotIn("_copy_image_pixels", restore_source)

    def test_quake_direct_bake_creates_a_new_image_datablock(self):
        tree = ast.parse(self.source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_qss_run_ericw_direct_bake"
        )
        code = ast.get_source_segment(self.source, function)
        self.assertIn("image.copy()", code)
        self.assertIn("_qss_set_current_lightmap_image", code)
        self.assertNotIn("image.pixels.foreach_set(pixels)", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
