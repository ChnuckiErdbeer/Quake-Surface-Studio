import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import light_node_utils


class LightNodeTreeClassificationTests(unittest.TestCase):
    def _default_tree(self):
        emission = SimpleNamespace(
            bl_idname="ShaderNodeEmission",
            inputs={
                "Color": SimpleNamespace(default_value=(1.0, 1.0, 1.0, 1.0)),
                "Strength": SimpleNamespace(default_value=1.0),
            },
            mute=False,
        )
        output = SimpleNamespace(
            bl_idname="ShaderNodeOutputLight",
            target="ALL",
            mute=False,
        )
        emission_socket = SimpleNamespace(name="Emission")
        surface_socket = SimpleNamespace(name="Surface")
        link = SimpleNamespace(
            from_node=emission,
            to_node=output,
            from_socket=emission_socket,
            to_socket=surface_socket,
        )
        tree = SimpleNamespace(nodes=[emission, output], links=[link])
        return SimpleNamespace(node_tree=tree), tree, emission, output

    def test_missing_tree_is_safe_to_replace(self):
        self.assertTrue(light_node_utils.is_default_light_node_tree(
            SimpleNamespace(node_tree=None)
        ))

    def test_empty_tree_is_safe_to_replace(self):
        self.assertTrue(light_node_utils.is_default_light_node_tree(
            SimpleNamespace(node_tree=SimpleNamespace(nodes=[], links=[]))
        ))

    def test_untouched_blender_emission_tree_is_safe_to_replace(self):
        light, _tree, _emission, _output = self._default_tree()
        self.assertTrue(light_node_utils.is_default_light_node_tree(light))

    def test_custom_emission_strength_is_preserved(self):
        light, _tree, emission, _output = self._default_tree()
        emission.inputs["Strength"].default_value = 2.0
        self.assertFalse(light_node_utils.is_default_light_node_tree(light))

    def test_custom_emission_color_is_preserved(self):
        light, _tree, emission, _output = self._default_tree()
        emission.inputs["Color"].default_value = (0.2, 0.4, 0.8, 1.0)
        self.assertFalse(light_node_utils.is_default_light_node_tree(light))

    def test_extra_node_is_preserved(self):
        light, tree, _emission, _output = self._default_tree()
        tree.nodes.append(SimpleNamespace(bl_idname="ShaderNodeMath"))
        self.assertFalse(light_node_utils.is_default_light_node_tree(light))

    def test_non_default_link_is_preserved(self):
        light, tree, _emission, _output = self._default_tree()
        tree.links[0].to_socket.name = "Volume"
        self.assertFalse(light_node_utils.is_default_light_node_tree(light))


if __name__ == "__main__":
    unittest.main()
