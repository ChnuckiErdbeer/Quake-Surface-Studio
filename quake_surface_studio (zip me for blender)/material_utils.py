"""Blender-independent material-slot rollback helpers."""


def trim_appended_material_slots(materials, original_count):
    """Remove material slots appended after a transaction snapshot.

    Blender's IDMaterials collection exposes pop(index=...). Keeping this
    operation independent of bpy makes the rollback contract unit-testable.
    Returns the removed material references, in removal order.
    """
    target = int(original_count)
    if target < 0:
        raise ValueError("Original material-slot count cannot be negative.")

    current = len(materials)
    if current < target:
        raise ValueError(
            f"Material slots shrank from the original {target} to {current}; "
            "refusing to guess how to reconstruct removed slots."
        )

    removed = []
    while len(materials) > target:
        removed.append(materials.pop(index=len(materials) - 1))
    return removed
