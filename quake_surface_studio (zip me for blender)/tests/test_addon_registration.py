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

    def test_cycles_indirect_bounce_control_is_exposed_in_lightmap_panel(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        panel_start = source.index("class QSS_PT_lighting(Panel)")
        panel_end = source.index("\nclass ", panel_start + 5)
        panel = source[panel_start:panel_end]
        self.assertIn('context.scene, "qss_bake_bounces"', panel)
        self.assertIn('text="Indirect Bounces"', panel)
        self.assertIn('name=\'Cycles diffuse bounces\'', source)
        self.assertIn('default=2, min=0, max=12', source)

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


    def test_delay_profiles_update_live_and_cancel_restores_original_values(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        settings_start = source.index("class QSS_OT_settings(Operator):")
        settings_end = source.index("\nclass QSS_OT_open_config_text", settings_start)
        settings = source[settings_start:settings_end]
        self.assertEqual(settings.count("update=_on_native_delay_profile_changed"), 18)
        self.assertIn("def cancel(self, context):", settings)
        self.assertIn("original_profiles", source)
        self.assertIn("delay edits update the viewport live", settings.lower())

    def test_cycles_preview_uses_same_active_map_light_set_as_bake(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("def _qss_set_preview_light_visibility(scene, obj, active_map_objects):", source)
        self.assertIn("def _qss_restore_preview_light_visibility(obj):", source)
        preview_start = source.index("def _set_lighting_preview(context, obj, mode):")
        preview_end = source.index("\ndef ", preview_start + 5)
        preview = source[preview_start:preview_end]
        self.assertIn("_qss_set_preview_light_visibility(", preview)
        self.assertIn("_qss_restore_preview_light_visibility(obj)", preview)
        self.assertIn("light_obj.hide_render = not is_active_qss_light", source)
        self.assertIn("light_obj.hide_set(not is_active_qss_light)", source)

    def test_bake_source_match_is_opt_in_and_visible(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("name='Match source lightmap brightness'", source)
        self.assertIn("default=False", source[source.index("name='Match source lightmap brightness'"):])
        panel_start = source.index("class QSS_PT_lighting(Panel)")
        panel_end = source.index("\nclass QSS_PT_stats", panel_start)
        panel = source[panel_start:panel_end]
        self.assertIn('"qss_bake_match_source"', panel)
        self.assertIn("live Cycles preview will differ", panel)


    def test_settings_exposes_explicit_apply_to_lights_button(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("class QSS_OT_apply_native_delay_profiles(Operator):", source)
        settings_start = source.index("class QSS_OT_settings(Operator):")
        settings_end = source.index("\nclass QSS_OT_open_config_text", settings_start)
        settings = source[settings_start:settings_end]
        self.assertIn("QSS_OT_apply_native_delay_profiles.bl_idname", settings)
        self.assertIn("apply_op.profiles_json = json.dumps(", settings)

    def test_cycles_bake_uses_one_normalized_profile_snapshot(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("class QSS_OT_bake_scene_lights(Operator):")
        end = source.index("class QSS_OT_undo_last_bake(Operator):", start)
        bake = source[start:end]
        self.assertIn("bake_native_profiles = _qss_native_delay_profiles_normalized(", bake)
        self.assertGreaterEqual(
            bake.count("_apply_quake_light_energy_scale(scene, delay_profiles=bake_native_profiles)"),
            2,
        )
        self.assertIn("qss_last_bake_attempt_native_delay_summary", bake)
    def test_apply_and_save_persists_diffuse_profiles_and_applies_light_factor(self):
        addon_path = os.path.join(os.path.dirname(__file__), "..", "addon.py")
        with open(addon_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('bl_label = "Apply & Save"', source)
        self.assertIn('settings["native_delay_profiles"] = profiles', source)
        self.assertIn('light_obj.data.diffuse_factor = multipliers["diffuse"]', source)
        self.assertIn('for field in ("energy", "diffuse", "range", "softness")', source)
        settings_start = source.index("class QSS_OT_settings(Operator):")
        settings_end = source.index("\\nclass QSS_OT_open_config_text", settings_start)
        settings = source[settings_start:settings_end]
        self.assertEqual(settings.count("delay0_diffuse"), 1)
        self.assertIn('header.label(text="Eevee Cutoff ×")', settings)
        self.assertIn('header.label(text="Source Radius ×")', settings)


if __name__ == "__main__": unittest.main(verbosity=2)
