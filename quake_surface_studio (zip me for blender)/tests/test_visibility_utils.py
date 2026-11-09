import unittest

import visibility_utils


class VisibilityUtilsTests(unittest.TestCase):
    def test_round_trip_preserves_hidden_and_selected_faces(self):
        encoded = visibility_utils.encode_face_visibility_snapshot(
            12, 20, 9, [0, 2, 8], [4, 5]
        )
        hidden, selected = visibility_utils.decode_face_visibility_snapshot(
            encoded, 12, 20, 9
        )
        self.assertEqual(hidden, frozenset({0, 2, 8}))
        self.assertEqual(selected, frozenset({4, 5}))
        self.assertTrue(visibility_utils.snapshot_is_active(encoded))

    def test_topology_change_is_rejected_safely(self):
        encoded = visibility_utils.encode_face_visibility_snapshot(
            12, 20, 9, [], [4]
        )
        with self.assertRaisesRegex(ValueError, "topology changed"):
            visibility_utils.decode_face_visibility_snapshot(
                encoded, 12, 21, 9
            )

    def test_empty_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Select at least one"):
            visibility_utils.encode_face_visibility_snapshot(
                4, 4, 1, [], []
            )

    def test_hidden_and_selected_faces_must_be_disjoint(self):
        with self.assertRaisesRegex(ValueError, "both hidden and selected"):
            visibility_utils.encode_face_visibility_snapshot(
                4, 4, 2, [0], [0]
            )

    def test_out_of_range_indices_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            visibility_utils.encode_face_visibility_snapshot(
                4, 4, 2, [3], [0]
            )

    def test_corrupt_or_unsupported_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            visibility_utils.decode_face_visibility_snapshot(
                "{", 4, 4, 2
            )
        with self.assertRaisesRegex(ValueError, "unsupported version"):
            visibility_utils.decode_face_visibility_snapshot(
                '{"version":2}', 4, 4, 2
            )


if __name__ == "__main__":
    unittest.main()
