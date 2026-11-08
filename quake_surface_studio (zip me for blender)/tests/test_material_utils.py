import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import material_utils


class FakeIDMaterials:
    """Minimal stand-in for Blender IDMaterials' keyword-only pop API."""

    def __init__(self, values):
        self.values = list(values)

    def __len__(self):
        return len(self.values)

    def pop(self, *, index=-1):
        return self.values.pop(index)


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
