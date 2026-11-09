"""Safe normalization helpers for Blender VIEW_3D tool definitions.

Blender 5.2's ToolDef is a namedtuple. It must be recognized *before* normal
tuples are treated as click-drag tool groups. Tool lists also contain callable
context-dependent generators; those must be preserved as top-level entries.
This module has no bpy dependency so the rules can be unit-tested separately.
"""


def tooldef_idname(item, tooldef_type):
    """Return the identifier only when item is exactly Blender's ToolDef type."""
    if type(item) is not tooldef_type:
        return None
    identifier = getattr(item, "idname", None)
    return identifier if isinstance(identifier, str) and identifier else None


def _clean_group(group, tooldef_type, qss_prefix, discarded):
    """Clean one possibly malformed group, leaving valid groups untouched."""
    changed = False
    members = []
    dynamic_items = []

    def visit(item):
        nonlocal changed

        if item is None:
            members.append(None)
            return

        identifier = tooldef_idname(item, tooldef_type)
        if identifier is not None:
            if identifier.startswith(qss_prefix):
                changed = True
            else:
                members.append(item)
            return

        # ToolDef is a namedtuple (and therefore also a tuple), so it is tested
        # above. Only ordinary tuples/lists are group containers here.
        if isinstance(item, (tuple, list)):
            changed = True
            for child in item:
                visit(child)
            return

        if callable(item):
            # Context-dependent generators belong at the top level, not inside
            # a ToolDef group. Preserve them as adjacent top-level entries.
            changed = True
            dynamic_items.append(item)
            return

        changed = True
        discarded.append(item)

    for child in group:
        visit(child)

    if not changed:
        return group, [], False

    # Remove only separators made redundant by deleting malformed/QSS members.
    cleaned_members = []
    for item in members:
        if item is None and (not cleaned_members or cleaned_members[-1] is None):
            continue
        cleaned_members.append(item)
    while cleaned_members and cleaned_members[0] is None:
        cleaned_members.pop(0)
    while cleaned_members and cleaned_members[-1] is None:
        cleaned_members.pop()

    if not cleaned_members:
        normalized_group = None
    elif len(cleaned_members) == 1:
        normalized_group = cleaned_members[0]
    else:
        normalized_group = tuple(cleaned_members)

    return normalized_group, dynamic_items, True


def normalize_tool_entries(entries, tooldef_type, qss_prefix="qss."):
    """Return (normalized_entries, discarded_values).

    Valid ToolDef instances, valid one-level ToolDef groups, None separators,
    and top-level callable generators retain their original identity and order.
    Only stale QSS tools, nested/malformed groups, and unsupported values are
    repaired. The ToolDef type is supplied by Blender at runtime.
    """
    normalized = []
    discarded = []
    changed = False

    for item in entries:
        if item is None:
            normalized.append(None)
            continue

        identifier = tooldef_idname(item, tooldef_type)
        if identifier is not None:
            if identifier.startswith(qss_prefix):
                changed = True
            else:
                normalized.append(item)
            continue

        # Keep Blender's dynamic tool-list generators intact.
        if callable(item):
            normalized.append(item)
            continue

        if isinstance(item, (tuple, list)):
            group, dynamic_items, group_changed = _clean_group(
                item, tooldef_type, qss_prefix, discarded
            )
            if group_changed:
                changed = True
                if group is not None:
                    normalized.append(group)
                normalized.extend(dynamic_items)
            else:
                normalized.append(group)
            continue

        # In a Blender toolbar list, a raw string is never a valid entry.
        discarded.append(item)
        changed = True

    if not changed:
        # Return the original sequence contents exactly; do not normalize or
        # reorder built-in definitions just because the add-on is refreshing.
        return list(entries), discarded

    # Removing a stale entry may create adjacent or edge separators. Clean
    # those at the top level without touching valid tool groups or callables.
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


def iter_tooldefs(entries, tooldef_type):
    """Yield actual ToolDef objects, never the fields of the namedtuple."""
    identifier = tooldef_idname(entries, tooldef_type)
    if identifier is not None:
        yield entries
        return
    if isinstance(entries, (tuple, list)):
        for item in entries:
            yield from iter_tooldefs(item, tooldef_type)
