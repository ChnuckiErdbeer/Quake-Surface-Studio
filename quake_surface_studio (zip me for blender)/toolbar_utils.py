"""Defensive normalization for Blender's VIEW_3D toolbar definitions.

Blender expects each toolbar entry to be a ToolDef, None separator, or a
one-level tuple of ToolDefs. This module deliberately has no bpy dependency so
the repair logic can be unit-tested outside Blender.
"""


def tooldef_idname(item):
    """Return a valid ToolDef identifier, or None for unsupported values."""
    if item is None:
        return None
    try:
        identifier = getattr(item, "idname", None)
    except Exception:
        return None
    return identifier if isinstance(identifier, str) and identifier else None


def _collect_tooldefs(item, output, discarded, qss_prefix):
    """Recursively collect valid non-QSS ToolDefs from possibly malformed data."""
    if item is None:
        return
    if isinstance(item, (tuple, list)):
        for child in item:
            _collect_tooldefs(child, output, discarded, qss_prefix)
        return

    identifier = tooldef_idname(item)
    if identifier is None:
        discarded.append(item)
    elif not identifier.startswith(qss_prefix):
        output.append(item)


def normalize_tool_entries(entries, qss_prefix="qss."):
    """Return (normalized_entries, discarded_values).

    Nested tuple/list groups are flattened to Blender's supported single group
    level. Invalid leaves (including strings) and stale QSS ToolDefs are
    removed. Top-level None separators are retained, de-duplicated and trimmed.
    """
    normalized = []
    discarded = []

    for item in entries:
        if item is None:
            normalized.append(None)
            continue

        members = []
        _collect_tooldefs(item, members, discarded, qss_prefix)
        if len(members) == 1:
            normalized.append(members[0])
        elif len(members) > 1:
            normalized.append(tuple(members))

    result = []
    for item in normalized:
        if item is None and (not result or result[-1] is None):
            continue
        result.append(item)
    while result and result[0] is None:
        result.pop(0)
    while result and result[-1] is None:
        result.pop()

    return result, discarded


def iter_tooldefs(entries):
    """Yield only valid ToolDef-like objects from arbitrary toolbar data."""
    if entries is None:
        return
    if isinstance(entries, (tuple, list)):
        for item in entries:
            yield from iter_tooldefs(item)
        return
    if tooldef_idname(entries) is not None:
        yield entries
