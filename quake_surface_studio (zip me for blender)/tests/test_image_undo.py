"""Tests for the image-state journal used by Blender Ctrl+Z/redo hooks."""

import array
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import image_undo


class FakePixels:
    def __init__(self, values):
        self.values = array.array("f", values)

    def foreach_get(self, target):
        target[:] = self.values

    def foreach_set(self, values):
        self.values = array.array("f", values)


class FakeImage:
    def __init__(self, name, values, width=2, height=2):
        self.name = name
        self.size = (width, height)
        self.pixels = FakePixels(values)
        self.update_count = 0

    def update(self):
        self.update_count += 1


class FakeObject(dict):
    def as_pointer(self):
        return id(self)


class ImageUndoJournalTests(unittest.TestCase):
    def setUp(self):
        self.journal = image_undo.ImageUndoJournal(history_limit=8)
        self.obj = FakeObject(qss_object_role="quake_bsp29")
        self.image = FakeImage("QSS_Lightmap_Test", [0.1, 0.2, 0.3, 1.0] * 4)
        self.images = {self.image.name: self.image}

    def lookup(self, name):
        return self.images.get(name)

    def values(self):
        return tuple(self.image.pixels.values)

    def test_undo_and_redo_restore_image_pixels_for_the_matching_token(self):
        original = self.values()
        transaction = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.8, 0.7, 0.6, 1.0] * 4)
        self.journal.commit(self.obj, [self.image], transaction)
        baked = self.values()
        baked_token = self.obj["qss_undo_token"]

        self.obj["qss_undo_token"] = ""
        self.journal.reconcile([self.obj], self.lookup)
        self.assertEqual(self.values(), original)

        self.obj["qss_undo_token"] = baked_token
        self.journal.reconcile([self.obj], self.lookup)
        self.assertEqual(self.values(), baked)

    def test_rollback_restores_pixels_and_keeps_the_pre_edit_token(self):
        before = self.values()
        transaction = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.9, 0.9, 0.9, 1.0] * 4)
        self.journal.rollback(self.obj, transaction, self.lookup)
        self.assertEqual(self.values(), before)
        self.assertEqual(self.obj["qss_undo_token"], "")

    def test_native_undo_without_a_token_change_does_not_rewrite_paint_strokes(self):
        transaction = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.5, 0.5, 0.5, 1.0] * 4)
        self.journal.commit(self.obj, [self.image], transaction)
        self.journal.reconcile([self.obj], self.lookup)
        painted_stroke = [0.2, 0.4, 0.6, 1.0] * 4
        self.image.pixels.foreach_set(painted_stroke)
        self.journal.reconcile([self.obj], self.lookup)
        self.assertEqual(len(self.values()), len(painted_stroke))
        for actual, expected in zip(self.values(), painted_stroke):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_new_operation_after_undo_discards_the_old_redo_branch(self):
        first = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.3, 0.3, 0.3, 1.0] * 4)
        self.journal.commit(self.obj, [self.image], first)
        old_redo_token = self.obj["qss_undo_token"]
        self.obj["qss_undo_token"] = ""
        self.journal.reconcile([self.obj], self.lookup)

        second = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.9, 0.1, 0.1, 1.0] * 4)
        self.journal.commit(self.obj, [self.image], second)
        states = self.journal._states[self.obj["qss_undo_uid"]]
        self.assertNotIn(old_redo_token, states)

    def test_native_paint_between_operations_survives_undo_of_unrelated_image_edit(self):
        image_b = FakeImage("QSS_Painted_Texture_B", [0.1, 0.2, 0.3, 1.0] * 4)
        first = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.7, 0.7, 0.7, 1.0] * 4)
        self.journal.commit(self.obj, [self.image], first)
        first_token = self.obj["qss_undo_token"]

        # Native Texture Paint changes image A without changing SLOPGATE's token.
        painted = [0.25, 0.35, 0.45, 1.0] * 4
        self.image.pixels.foreach_set(painted)

        # A second SLOPGATE operation edits image B. Its pre-state must refresh
        # image A too, otherwise undoing this unrelated operation would erase
        # the intervening user paint stroke on A.
        second = self.journal.begin(self.obj, [image_b])
        image_b.pixels.foreach_set([0.9, 0.8, 0.7, 1.0] * 4)
        self.journal.commit(self.obj, [image_b], second)
        self.obj["qss_undo_token"] = first_token
        self.journal.reconcile([self.obj], self.lookup)
        for actual, expected in zip(self.values(), painted):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertEqual(tuple(image_b.pixels.values), (0.1, 0.2, 0.3, 1.0) * 4)

    def test_images_created_inside_an_operation_are_restored_on_redo(self):
        transaction = self.journal.begin(self.obj, [])
        created_pixels = [0.35, 0.45, 0.55, 1.0] * 4
        self.image.pixels.foreach_set(created_pixels)
        self.journal.commit(self.obj, [self.image], transaction)
        created_token = self.obj["qss_undo_token"]

        # Model Blender undo removing or clearing an image datablock created by
        # the operation, then redo restoring the operator's token and image ID.
        self.image.pixels.foreach_set([0.0, 0.0, 0.0, 1.0] * 4)
        self.obj["qss_undo_token"] = ""
        self.journal.reconcile([self.obj], self.lookup)
        self.obj["qss_undo_token"] = created_token
        self.journal.reconcile([self.obj], self.lookup)
        for actual, expected in zip(self.values(), created_pixels):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_missing_images_are_ignored_during_reconciliation(self):
        transaction = self.journal.begin(self.obj, [self.image])
        self.image.pixels.foreach_set([0.6, 0.6, 0.6, 1.0] * 4)
        self.journal.commit(self.obj, [self.image], transaction)
        token = self.obj["qss_undo_token"]
        self.images.clear()
        self.obj["qss_undo_token"] = ""
        self.journal.reconcile([self.obj], self.lookup)
        self.obj["qss_undo_token"] = token
        self.journal.reconcile([self.obj], self.lookup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
