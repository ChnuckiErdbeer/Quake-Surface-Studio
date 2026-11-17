import array
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import material_utils


class LightmapResolutionTests(unittest.TestCase):
    def test_supported_resolution_dimensions(self):
        self.assertEqual(material_utils.lightmap_resolution_dimensions(512, 1), 512)
        self.assertEqual(material_utils.lightmap_resolution_dimensions(512, 2), 1024)
        self.assertEqual(material_utils.lightmap_resolution_dimensions(512, 4), 2048)
        self.assertEqual(material_utils.lightmap_resolution_dimensions(256, 8), 2048)

    def test_resolution_guard_rejects_excessive_images(self):
        with self.assertRaises(ValueError):
            material_utils.lightmap_resolution_dimensions(1024, 8)

    def test_only_supported_resolution_factors_are_accepted(self):
        for value in (0, 3, 16, 'high'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                material_utils.validate_lightmap_resolution(value)

    def test_working_scale_is_resolved_from_image_dimensions(self):
        self.assertEqual(material_utils.lightmap_resolution_ratio(512, 2048), 4)
        with self.assertRaises(ValueError):
            material_utils.lightmap_resolution_ratio(512, 1536)

    def test_face_rectangle_is_scaled_without_changing_uvs(self):
        self.assertEqual(material_utils.lightmap_sample_region(10, 20, 2, 2, 4), (48, 88, 8))

    def test_upscale_replicates_source_luxels_exactly(self):
        source = array.array('f', [1, 0, 0, 1, 0, 1, 0, 1,
                                   0, 0, 1, 1, 1, 1, 1, 1])
        result = material_utils.resample_rgba_pixels(source, 2, 2, 4, 4)
        self.assertEqual(len(result), 4 * 4 * 4)
        self.assertEqual(tuple(result[0:4]), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(tuple(result[(1 * 4 + 1) * 4:(1 * 4 + 1) * 4 + 4]), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(tuple(result[(3 * 4 + 3) * 4:(3 * 4 + 3) * 4 + 4]), (1.0, 1.0, 1.0, 1.0))

    def test_downscale_box_averages_high_resolution_pixels(self):
        source = array.array('f', [0, 0, 0, 1] * 3 + [1, 1, 1, 1])
        result = material_utils.resample_rgba_pixels(source, 2, 2, 1, 1)
        self.assertEqual(tuple(round(value, 4) for value in result), (0.25, 0.25, 0.25, 1.0))

    def test_resampling_rejects_incompatible_dimensions_and_buffers(self):
        with self.assertRaises(ValueError):
            material_utils.resample_rgba_pixels([0.0] * 4, 2, 2, 4, 4)
        with self.assertRaises(ValueError):
            material_utils.resample_rgba_pixels([0.0] * 16, 2, 2, 3, 3)


class FakeIDMaterials:
    """Minimal stand-in for Blender IDMaterials' keyword-only pop API."""

    def __init__(self, values):
        self.values = list(values)

    def __len__(self):
        return len(self.values)

    def pop(self, *, index=-1):
        return self.values.pop(index)


class FakeImagePaintSettings:
    def __init__(self):
        self.use_occlude = False
        self.use_backface_culling = True


class MaterialSlotRollbackTests(unittest.TestCase):
    def test_removes_only_slots_appended_after_snapshot(self):
        slots = FakeIDMaterials(["source-a", "source-b", "detached-a", "detached-b"])
        removed = material_utils.trim_appended_material_slots(slots, 2)
        self.assertEqual(slots.values, ["source-a", "source-b"])
        self.assertEqual(removed, ["detached-b", "detached-a"])

    def test_zero_original_slots_are_supported(self):
        slots = FakeIDMaterials(["temporary"])
        removed = material_utils.trim_appended_material_slots(slots, 0)
        self.assertEqual(slots.values, [])
        self.assertEqual(removed, ["temporary"])

    def test_unchanged_collection_is_left_untouched(self):
        slots = FakeIDMaterials(["source"])
        self.assertEqual(material_utils.trim_appended_material_slots(slots, 1), [])
        self.assertEqual(slots.values, ["source"])

    def test_refuses_to_mask_slots_removed_by_another_operation(self):
        slots = FakeIDMaterials(["remaining"])
        with self.assertRaises(ValueError):
            material_utils.trim_appended_material_slots(slots, 2)

    def test_negative_snapshot_count_is_rejected(self):
        slots = FakeIDMaterials([])
        with self.assertRaises(ValueError):
            material_utils.trim_appended_material_slots(slots, -1)

    def test_configures_safe_texture_paint_visibility(self):
        settings = FakeImagePaintSettings()
        material_utils.configure_texture_paint_visibility(settings)
        self.assertTrue(settings.use_occlude)
        self.assertFalse(settings.use_backface_culling)

    def test_finds_image_by_datablock_identity_not_node_position(self):
        image_a = object()
        image_b = object()
        self.assertEqual(
            material_utils.find_image_slot_index([image_a, image_b], image_b), 1
        )

    def test_missing_image_is_not_guessed(self):
        self.assertEqual(
            material_utils.find_image_slot_index([object()], object()), -1
        )

    def test_none_image_is_rejected(self):
        self.assertEqual(material_utils.find_image_slot_index([], None), -1)


    def test_filters_selection_to_faces_with_lightmap_samples(self):
        self.assertEqual(
            material_utils.filter_lightmapped_face_indices(
                [0, 1, 2, 3], [True, False, True, True]
            ),
            [0, 2, 3],
        )

    def test_preserves_order_and_removes_duplicate_face_indices(self):
        self.assertEqual(
            material_utils.filter_lightmapped_face_indices(
                [3, 1, 3, 0, 1], [True, True, False, True]
            ),
            [3, 1, 0],
        )

    def test_ignores_negative_and_out_of_range_face_indices(self):
        self.assertEqual(
            material_utils.filter_lightmapped_face_indices(
                [-1, 0, 4, 1], [True, True]
            ),
            [0, 1],
        )

    def test_returns_empty_when_selected_faces_have_no_lightmap_samples(self):
        self.assertEqual(
            material_utils.filter_lightmapped_face_indices(
                [0, 1], [False, False]
            ),
            [],
        )

if __name__ == '__main__':
    unittest.main(verbosity=2)
