"""Blender-independent material-slot rollback and paint-setting helpers."""


def configure_texture_paint_visibility(image_paint):
    """Use QSS-safe visibility settings for BSP surface painting.

    Keep occlusion enabled so geometry still blocks brush projections, but
    disable backface culling. Imported BSP face winding/normals are not
    guaranteed to agree with Blender's paint projection culling convention;
    enabling it can suppress strokes on otherwise visible surfaces.
    """
    image_paint.use_occlude = True
    image_paint.use_backface_culling = False


def filter_lightmapped_face_indices(selected_indices, lightmap_flags):
    """Keep unique, in-range selected faces that have imported lightmap samples.

    The order of the user's selection is preserved so the active face can be
    retained by the caller. Invalid indices are ignored defensively.
    """
    flags = tuple(bool(value) for value in lightmap_flags)
    result = []
    seen = set()
    for raw_index in selected_indices:
        index = int(raw_index)
        if index in seen or index < 0 or index >= len(flags):
            continue
        seen.add(index)
        if flags[index]:
            result.append(index)
    return result


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



def find_image_slot_index(paint_images, image):
    """Return Blender's material paint-slot index for an exact image datablock.

    Do not infer this index from node-tree order: Blender builds and orders
    paint slots independently. Pointer identity is preferred because RNA
    wrappers for the same datablock need not be the same Python object.
    """
    if image is None:
        return -1
    target_pointer = None
    try:
        target_pointer = image.as_pointer()
    except Exception:
        pass
    for index, candidate in enumerate(paint_images):
        if candidate is image:
            return index
        try:
            if candidate == image:
                return index
        except Exception:
            pass
        if target_pointer is not None:
            try:
                if candidate.as_pointer() == target_pointer:
                    return index
            except Exception:
                pass
    return -1
