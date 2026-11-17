import ast
import os
import unittest


ADDON_PATH = os.path.join(os.path.dirname(__file__), "..", "addon.py")


class AddonRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ADDON_PATH, "r", encoding="utf-8") as source_file:
            cls.tree = ast.parse(source_file.read(), filename=ADDON_PATH)
        cls.classes = {node.name: node for node in cls.tree.body if isinstance(node, ast.ClassDef)}
        cls.registered = next(node.value for node in cls.tree.body
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "CLASSES" for target in node.targets))

    def test_every_registered_class_is_defined(self):
        names = [item.id for item in self.registered.elts if isinstance(item, ast.Name)]
        self.assertEqual(len(names), len(set(names)), "CLASSES contains duplicate entries")
        missing = sorted(set(names) - set(self.classes))
        self.assertEqual(missing, [], f"CLASSES references undefined classes: {missing}")

    def test_every_panel_parent_is_registered(self):
        registered = {item.id for item in self.registered.elts if isinstance(item, ast.Name)}
        panel_ids = {}
        for name, node in self.classes.items():
            if not any(isinstance(base, ast.Name) and base.id == "Panel" for base in node.bases): continue
            value = next((a.value.value for a in node.body if isinstance(a, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "bl_idname" for t in a.targets)
                and isinstance(a.value, ast.Constant) and isinstance(a.value.value, str)), None)
            if value: panel_ids[value] = name
        for name, node in self.classes.items():
            if not any(isinstance(base, ast.Name) and base.id == "Panel" for base in node.bases): continue
            parent = next((a.value.value for a in node.body if isinstance(a, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "bl_parent_id" for t in a.targets)
                and isinstance(a.value, ast.Constant) and isinstance(a.value.value, str)), None)
            if parent:
                self.assertIn(parent, panel_ids, f"{name} references missing panel parent {parent}")
                self.assertIn(panel_ids[parent], registered, f"Parent panel {panel_ids[parent]} is not registered")


if __name__ == "__main__": unittest.main(verbosity=2)
