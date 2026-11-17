import unittest

import surface_policy


class SurfacePolicyTests(unittest.TestCase):
    def test_compiler_only_surfaces_are_invisible_and_do_not_occlude(self):
        for name in (
            "trigger",
            "trigger_multiple",
            "clip",
            "clip_player",
            "playerclip",
            "monsterclip",
            "origin",
            "hint",
            "skip",
            "hintskip",
            "null",
            "nodraw",
            "bevel",
            "areaportal",
            "*trigger",
            "textures/clip",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    surface_policy.classify_texture(name),
                    surface_policy.POLICY_NODRAW,
                )
                self.assertFalse(surface_policy.receives_light(name))
                self.assertFalse(surface_policy.casts_light_shadow(name))

    def test_blocklight_is_invisible_and_blocks_light(self):
        self.assertEqual(
            surface_policy.classify_texture("blocklight"),
            surface_policy.POLICY_NODRAW_BLOCKER,
        )
        self.assertFalse(surface_policy.receives_light("blocklight"))
        self.assertTrue(surface_policy.casts_light_shadow("blocklight"))
        self.assertTrue(surface_policy.is_nodraw_policy(
            surface_policy.classify_texture("blocklight")
        ))

    def test_ordinary_and_special_visible_textures_remain_rendered(self):
        for name in ("brick01", "stone_wall", "triggered", "clipboard", "sky", "{water"):
            with self.subTest(name=name):
                self.assertEqual(
                    surface_policy.classify_texture(name),
                    surface_policy.POLICY_RENDER,
                )
                self.assertTrue(surface_policy.receives_light(name))
                self.assertTrue(surface_policy.casts_light_shadow(name))

    def test_unknown_policy_is_not_silently_treated_as_nodraw(self):
        self.assertFalse(surface_policy.is_nodraw_policy("UNKNOWN"))
        self.assertFalse(surface_policy.policy_receives_light("UNKNOWN"))
        self.assertFalse(surface_policy.policy_casts_light_shadow("UNKNOWN"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
