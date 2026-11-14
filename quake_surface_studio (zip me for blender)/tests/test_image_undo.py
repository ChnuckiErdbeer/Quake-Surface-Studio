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
