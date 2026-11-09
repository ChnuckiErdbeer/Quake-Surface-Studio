import unittest

import toolbar_utils


class FakeTool:
    def __init__(self, idname):
        self.idname = idname


class ToolbarUtilsTests(unittest.TestCase):
    def test_removes_strings_and_flattens_nested_groups(self):
        select = FakeTool("builtin.select")
        move = FakeTool("builtin.move")
        scale = FakeTool("builtin.scale")

        normalized, discarded = toolbar_utils.normalize_tool_entries([
            None,
            ((select, ("unexpected-string", move)), [scale]),
            None,
        ])

        self.assertEqual(normalized, [(select, move, scale)])
        self.assertEqual(discarded, ["unexpected-string"])
        self.assertTrue(all(
            isinstance(item, tuple) or toolbar_utils.tooldef_idname(item)
            for item in normalized
        ))

    def test_removes_stale_qss_tools_from_all_group_levels(self):
        select = FakeTool("builtin.select")
        stale = FakeTool("qss.focus_selected_face")
        move = FakeTool("builtin.move")

        normalized, discarded = toolbar_utils.normalize_tool_entries([
            select,
            (stale, move),
            stale,
        ])

        self.assertEqual(normalized, [select, move])
        self.assertEqual(discarded, [])

    def test_drops_values_without_a_valid_string_idname(self):
        good = FakeTool("builtin.select")
        invalid_id = FakeTool(123)
        empty_id = FakeTool("")

        normalized, discarded = toolbar_utils.normalize_tool_entries([
            "builtin.select",
            invalid_id,
            empty_id,
            good,
        ])

        self.assertEqual(normalized, [good])
        self.assertEqual(discarded, ["builtin.select", invalid_id, empty_id])

    def test_iter_tooldefs_skips_strings_and_separators(self):
        good = FakeTool("builtin.select")
        invalid = FakeTool(None)

        self.assertEqual(
            list(toolbar_utils.iter_tooldefs([None, "bad", (good, [invalid])])),
            [good],
        )


if __name__ == "__main__":
    unittest.main()
