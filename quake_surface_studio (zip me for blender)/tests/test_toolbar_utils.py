import unittest
from collections import namedtuple

import toolbar_utils


# Match Blender's key distinction: ToolDef is itself a namedtuple, while
# click-drag groups are ordinary tuple instances containing ToolDef objects.
ToolDef = namedtuple(
    "ToolDef",
    (
        "idname", "label", "description", "icon", "cursor",
        "widget_properties", "widget", "keymap", "brush_type",
        "data_block", "operator", "draw_settings", "draw_cursor", "options",
    ),
)


def tool(identifier):
    return ToolDef(
        identifier, identifier, None, None, None, None, None, None,
        None, None, None, None, None, None,
    )


def dynamic_tools(_context):
    return ()


class ToolbarUtilsTests(unittest.TestCase):
    def test_preserves_builtin_tooldefs_groups_and_dynamic_generators(self):
        select = tool("builtin.select")
        circle = tool("builtin.select_circle")
        lasso = tool("builtin.select_lasso")
        move = tool("builtin.move")
        original_group = (circle, lasso)
        original = [select, original_group, None, dynamic_tools, move]

        normalized, discarded = toolbar_utils.normalize_tool_entries(original, ToolDef)

        self.assertEqual(normalized, original)
        self.assertIs(normalized[0], select)
        self.assertIs(normalized[1], original_group)
        self.assertIs(normalized[3], dynamic_tools)
        self.assertEqual(discarded, [])

    def test_removes_qss_tools_and_flattens_only_the_tainted_nested_group(self):
        select = tool("builtin.select")
        qss = tool("qss.old_tool")
        move = tool("builtin.move")
        scale = tool("builtin.scale")
        untouched = tool("builtin.cursor")
        original_group = (untouched, move)

        normalized, discarded = toolbar_utils.normalize_tool_entries(
            [select, original_group, ((qss, (move, scale)), None)],
            ToolDef,
        )

        self.assertEqual(normalized, [select, original_group, (move, scale)])
        self.assertIs(normalized[1], original_group)
        self.assertEqual(discarded, [])

    def test_discards_stray_strings_without_shredding_tooldef_fields(self):
        select = tool("builtin.select")
        move = tool("builtin.move")

        normalized, discarded = toolbar_utils.normalize_tool_entries(
            ["builtin.select", select, "not-a-tool", move],
            ToolDef,
        )

        self.assertEqual(normalized, [select, move])
        self.assertEqual(discarded, ["builtin.select", "not-a-tool"])

    def test_preserves_dynamic_generators_when_removing_stale_qss_tool(self):
        select = tool("builtin.select")
        qss = tool("qss.old_tool")

        normalized, discarded = toolbar_utils.normalize_tool_entries(
            [select, qss, dynamic_tools, None],
            ToolDef,
        )

        self.assertEqual(normalized, [select, dynamic_tools])
        self.assertEqual(discarded, [])

    def test_removes_invalid_members_from_a_malformed_group(self):
        select = tool("builtin.select")
        move = tool("builtin.move")

        normalized, discarded = toolbar_utils.normalize_tool_entries(
            [(select, ("bad-string", move))],
            ToolDef,
        )

        self.assertEqual(normalized, [(select, move)])
        self.assertEqual(discarded, ["bad-string"])

    def test_iter_tooldefs_does_not_iterate_namedtuple_fields(self):
        select = tool("builtin.select")
        qss = tool("qss.paint_texture")
        move = tool("builtin.move")

        found = list(toolbar_utils.iter_tooldefs(
            [None, select, (qss, move), "stray", dynamic_tools],
            ToolDef,
        ))

        self.assertEqual(found, [select, qss, move])
        self.assertTrue(all(type(item) is ToolDef for item in found))


if __name__ == "__main__":
    unittest.main()
