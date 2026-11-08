import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import lighting


class LightingHelpersTests(unittest.TestCase):
    def test_energy_scale_is_applied_as_a_live_multiplier(self):
        self.assertAlmostEqual(lighting.scaled_quake_light_energy(300, 0.01), 3.0)
        self.assertAlmostEqual(lighting.scaled_quake_light_energy(300, 1.0), 300.0)
        self.assertAlmostEqual(lighting.scaled_quake_light_energy(-300, 2.0), 600.0)

    def test_invalid_energy_inputs_fall_back_to_zero(self):
        self.assertEqual(lighting.scaled_quake_light_energy('bad', 2), 0.0)
        self.assertEqual(lighting.scaled_quake_light_energy(20, 'bad'), 0.0)
        self.assertEqual(lighting.scaled_quake_light_energy(20, -1), 0.0)

    def test_rgb_samples_respect_nonzero_face_offsets(self):
        payload = bytes((10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120))
        self.assertEqual(lighting.extract_rgb_samples(payload, 0, 2), [(10, 20, 30), (40, 50, 60)])
        self.assertEqual(lighting.extract_rgb_samples(payload, 2, 2), [(70, 80, 90), (100, 110, 120)])

    def test_chromatic_lighting_distinguishes_colour_from_grey_gradient(self):
        self.assertFalse(lighting.face_has_chromatic_lighting([(10, 10, 10), (240, 240, 240)]))
        self.assertTrue(lighting.face_has_chromatic_lighting([(10, 10, 10), (240, 100, 20)]))
        self.assertFalse(lighting.face_has_chromatic_lighting([(10, 10, 10), (20, 20, 20)]))

    def test_bounce_setting_defaults_off_and_reads_worldspawn(self):
        self.assertFalse(lighting.bounce_enabled({}))
        self.assertFalse(lighting.bounce_enabled({'_bounce': '0'}))
        self.assertTrue(lighting.bounce_enabled({'_bounce': '1'}))
        self.assertTrue(lighting.bounce_enabled({'_bounce': '2'}))

    def test_wasd_navigation_does_not_move_without_pressed_keys(self):
        self.assertEqual(lighting.normalize_light_move(set(), 0.0), (0.0, 0.0))

    def test_wasd_forward_moves_only_when_w_is_held(self):
        x, y = lighting.normalize_light_move({'W'}, 0.0)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 0.0)

    def test_wasd_diagonal_is_normalized(self):
        x, y = lighting.normalize_light_move({'W', 'D'}, 0.0)
        self.assertAlmostEqual(x, 2 ** -0.5)
        self.assertAlmostEqual(y, 2 ** -0.5)

    def test_combine_style_samples_sums_all_face_style_planes(self):
        # Two luxels in style 0 followed immediately by two luxels in style 2.
        mono = bytes((10, 20, 30, 40))
        rgb = bytes((10, 0, 0, 20, 0, 0, 0, 0, 30, 0, 0, 40))
        combined = lighting.combine_style_samples(mono, rgb, 0, 2, [0, 2, 255])
        self.assertEqual(combined, [(10, 0, 30), (20, 0, 40)])

    def test_combine_style_samples_respects_face_style_slot_order(self):
        # For a face with styles [2, 0], the first sample plane is style 2,
        # even though style 0 is numerically lower. Weights expose slot swaps.
        mono = bytes((0, 0, 0, 0))
        rgb = bytes((10, 0, 0, 20, 0, 0, 0, 0, 30, 0, 0, 40))
        combined = lighting.combine_style_samples(
            mono, rgb, 0, 2, [2, 0, 255, 255], {2: 0.5, 0: 1.0}
        )
        self.assertEqual(combined, [(5, 0, 30), (10, 0, 40)])

    def test_combine_style_samples_weights_and_clamps(self):
        rgb = bytes((200, 10, 10, 100, 20, 20))
        combined = lighting.combine_style_samples(b'\x00\x00', rgb, 0, 1, [0, 2], {0: 1.0, 2: 0.5})
        self.assertEqual(combined, [(250, 20, 20)])
        clamped = lighting.combine_style_samples(b'\x00\x00', bytes((240, 0, 0, 80, 0, 0)), 0, 1, [0, 2])
        self.assertEqual(clamped, [(255, 0, 0)])

    def test_empty_key_style_is_recovered_but_marked_inferred(self):
        self.assertEqual(lighting.infer_entity_style({'style': '2'}), (2, False))
        self.assertEqual(lighting.infer_entity_style({'': '2'}), (2, True))
        self.assertEqual(lighting.infer_entity_style({}), (0, False))

    def test_calibration_matches_source_mean(self):
        self.assertAlmostEqual(lighting.calibration_factor(0.4, 0.1, 1.0), 4.0)
        with self.assertRaises(ValueError):
            lighting.calibration_factor(0.4, 0.0, 1.0)

    def test_bake_atlas_normalization_is_independent_of_energy_slider(self):
        # The bake already includes the energy slider. Do not apply it twice
        # when normalizing the bake image to the source lightmap mean.
        self.assertAlmostEqual(lighting.bake_atlas_match_scale(0.4, 0.1), 4.0)
        self.assertAlmostEqual(lighting.calibration_factor(0.4, 0.1, 10.0), 40.0)
        with self.assertRaises(ValueError):
            lighting.bake_atlas_match_scale(0.4, 0.0)

    def test_rgb_sample_bounds_are_checked(self):
        with self.assertRaises(ValueError):
            lighting.extract_rgb_samples(bytes(6), 1, 2)
        with self.assertRaises(ValueError):
            lighting.extract_rgb_samples(bytes(6), -1, 1)


if __name__ == '__main__':
    unittest.main()

class EricwAttenuationTests(unittest.TestCase):
    def test_delay_zero_linear(self):
        self.assertAlmostEqual(lighting.ericw_light_value(300, 0, 100), 200)
        self.assertEqual(lighting.ericw_light_value(300, 0, 400), 0)

    def test_delay_zero_falloff_overrides_wait(self):
        self.assertAlmostEqual(lighting.ericw_light_value(300, 0, 50, wait=9, falloff=100), 150)
        self.assertEqual(lighting.ericw_light_value(300, 0, 100, falloff=100), 0)

    def test_delay_one_inverse(self):
        self.assertAlmostEqual(lighting.ericw_light_value(300, 1, 128), 300)
        self.assertAlmostEqual(lighting.ericw_light_value(300, 1, 256), 150)

    def test_delay_two_inverse_square(self):
        self.assertAlmostEqual(lighting.ericw_light_value(300, 2, 128), 300)
        self.assertAlmostEqual(lighting.ericw_light_value(300, 2, 256), 75)

    def test_delay_three_constant(self):
        self.assertEqual(lighting.ericw_light_value(300, 3, 1), 300)
        self.assertEqual(lighting.ericw_light_value(300, 3, 10000), 300)

    def test_delay_four_returns_local_minlight_threshold(self):
        self.assertEqual(lighting.ericw_light_value(300, 4, 10000), 300)
        # The solver must apply this as max(current, threshold), not add it.

    def test_delay_five_soft_inverse_square(self):
        self.assertAlmostEqual(lighting.ericw_light_value(300, 5, 128), 75)
        self.assertLess(lighting.ericw_light_value(300, 5, 32),
                        lighting.ericw_light_value(300, 2, 32))

    def test_wait_and_world_dist_scale_distance(self):
        self.assertAlmostEqual(lighting.ericw_light_value(300, 0, 100, wait=2), 100)
        self.assertAlmostEqual(lighting.ericw_light_value(300, 0, 100, world_dist=2), 100)

    def test_surface_angle_scale(self):
        self.assertEqual(lighting.ericw_surface_angle(0.0, 0.0), 1.0)
        self.assertEqual(lighting.ericw_surface_angle(0.0, 1.0), 0.0)
        self.assertAlmostEqual(lighting.ericw_surface_angle(0.5, 0.5), 0.75)
        self.assertEqual(lighting.ericw_surface_angle(-1.0, 0.5), 0.0)

    def test_spot_cone(self):
        self.assertEqual(lighting.ericw_spot_factor(0.0, 40, 20), 0.0)
        self.assertEqual(lighting.ericw_spot_factor(1.0, 40, 20), 1.0)
        self.assertTrue(0.0 < lighting.ericw_spot_factor(0.95, 90, 30) < 1.0)

    def test_texinfo_plane_solver(self):
        # S=x, T=y, plane z=10 -> unique point (4,5,10).
        self.assertEqual(
            lighting.solve_texinfo_plane((1,0,0,0), (0,1,0,0), (0,0,1), 4, 5, 10),
            (4.0, 5.0, 10.0)
        )
        self.assertIsNone(
            lighting.solve_texinfo_plane((1,0,0,0), (2,0,0,0), (0,0,1), 4, 5, 10)
        )

    def test_ericw_postprocess_uses_default_half_range(self):
        out = lighting.ericw_postprocess_rgb((200, 100, 50))
        self.assertAlmostEqual(out[0], 100 / 255.0)
        self.assertAlmostEqual(out[1], 50 / 255.0)
        self.assertAlmostEqual(out[2], 25 / 255.0)

    def test_ericw_postprocess_gamma_brightens_and_preserves_hue(self):
        out = lighting.ericw_postprocess_rgb((64, 16, 0), range_scale=1.0, gamma=2.0)
        self.assertAlmostEqual(out[0], (64.0 / 255.0) ** 0.5, places=5)
        self.assertAlmostEqual(out[1], (16.0 / 255.0) ** 0.5, places=5)
        self.assertEqual(out[2], 0.0)

    def test_ericw_postprocess_maxlight_scales_channels_uniformly(self):
        out = lighting.ericw_postprocess_rgb((300, 150, 75), range_scale=1, gamma=1, maxlight=255)
        self.assertAlmostEqual(out[0], 1.0)
        self.assertAlmostEqual(out[1], 0.5)
        self.assertAlmostEqual(out[2], 0.25)

class EricwLuxelEvaluationTests(unittest.TestCase):
    def _light(self, **changes):
        light = {
            'origin': (0, 0, 128), 'value': 300, 'color': (1, 1, 1),
            'style': 0, 'delay': 0, 'wait': 1, 'falloff': 0,
            'anglescale': 0, 'nostaticlight': False,
        }
        light.update(changes)
        return light

    def test_delay_zero_channel_color_and_world_range(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1),
            [self._light(color=(1, 0, 0))], [0], world_range=0.5,
            energy_scale=1
        )
        self.assertGreater(result[0], 0)
        self.assertEqual(result[1], 0)
        self.assertEqual(result[2], 0)

    def test_style_filter_does_not_leak_between_styles(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1),
            [self._light(style=2, color=(0, 0, 1))], [0], world_range=1
        )
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_two_styles_accumulate(self):
        lights = [self._light(style=0, color=(1, 0, 0)),
                  self._light(style=2, color=(0, 0, 1))]
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), lights, [0, 2], world_range=1
        )
        self.assertGreater(result[0], 0)
        self.assertGreater(result[2], 0)

    def test_backside_surface_receives_no_direct_light(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, -1), [self._light()], [0]
        )
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_visibility_callback_blocks_light(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [self._light()], [0],
            visible=lambda *_args: False
        )
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_energy_scale_zero_is_black(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [self._light()], [0], energy_scale=0
        )
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_local_minlight_is_a_clamp_not_addition(self):
        red = self._light(delay=4, color=(1, 0, 0), value=100)
        additive = self._light(color=(1, 0, 0), value=300)
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [red, additive], [0], world_range=1
        )
        baseline = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [additive], [0], world_range=1
        )
        # The larger additive contribution wins; the local-minlight does not add.
        self.assertAlmostEqual(result[0], baseline[0])

    def test_spotlight_cone_rejects_sample_behind_cone(self):
        spot = self._light(is_spot=True, direction=(0, 0, -1), outer_angle=40)
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [spot], [0], world_range=1
        )
        self.assertGreater(result[0], 0)
        spot['direction'] = (0, 0, 1)
        result2 = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [spot], [0], world_range=1
        )
        self.assertEqual(result2, (0.0, 0.0, 0.0))

class EricwContributionGateTests(unittest.TestCase):
    def _light(self, **changes):
        light = {
            'origin': (0, 0, 128), 'value': 300, 'color': (1, 1, 1),
            'style': 0, 'delay': 0, 'wait': 1, 'falloff': 0,
            'anglescale': 0, 'nostaticlight': False,
        }
        light.update(changes)
        return light

    def test_contribution_gate_discards_subthreshold_sample(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [self._light(value=0.0005)], [0],
            world_range=1.0, contribution_gate=0.001,
        )
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_contribution_gate_can_be_disabled(self):
        result = lighting.evaluate_quake_luxel(
            (0, 0, 0), (0, 0, 1), [self._light(value=0.0005, delay=3)], [0],
            world_range=1.0, contribution_gate=0.0,
        )
        self.assertGreater(result[0], 0.0)

    def test_world_dist_scales_explicit_falloff_radius(self):
        self.assertAlmostEqual(
            lighting.ericw_light_value(300, 0, 100, wait=99, world_dist=2, falloff=100),
            150.0,
        )
        self.assertEqual(
            lighting.ericw_light_value(300, 0, 200, world_dist=2, falloff=100),
            0.0,
        )
