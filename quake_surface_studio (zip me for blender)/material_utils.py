"""Blender-independent material, image and lightmap helpers."""

import array


LIGHTMAP_RESOLUTIONS = (1, 2, 4, 8)
MAX_LIGHTMAP_IMAGE_SIZE = 2048


def validate_lightmap_resolution(value):
    """Return a supported integer lightmap working-resolution multiplier."""
    try:
        resolution = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Lightmap resolution must be one of 1, 2, 4 or 8.") from exc
    if resolution not in LIGHTMAP_RESOLUTIONS:
        raise ValueError("Lightmap resolution must be one of 1, 2, 4 or 8.")
    return resolution


def lightmap_resolution_dimensions(base_size, resolution, max_dimension=MAX_LIGHTMAP_IMAGE_SIZE):
    """Return the square working-atlas dimension, enforcing the memory guard."""
    base = int(base_size)
    factor = validate_lightmap_resolution(resolution)
    limit = int(max_dimension)
    if base <= 0:
        raise ValueError("Base lightmap atlas size must be positive.")
    if limit <= 0:
        raise ValueError("Maximum lightmap dimension must be positive.")
    size = base * factor
    if size > limit:
        raise ValueError(
            f"{factor}x would create a {size}x{size} float atlas; "
            f"the safe QSS limit is {limit}x{limit}. Choose a lower resolution."
        )
    return size


def lightmap_resolution_ratio(base_size, image_size):
    """Resolve an atlas image's integer working scale relative to its base layout."""
    base = int(base_size)
    current = int(image_size)
    if base <= 0 or current <= 0 or current % base:
        raise ValueError("Lightmap image dimensions do not match the stored base atlas size.")
    ratio = current // base
    if ratio not in LIGHTMAP_RESOLUTIONS:
        raise ValueError("Lightmap image has an unsupported working-resolution multiplier.")
    return ratio


def lightmap_sample_region(atlas_x, atlas_y, gutter, sample_scale, resolution):
    """Return (pixel_x, pixel_y, pixel_scale) for one face's working luxel region."""
    x = int(atlas_x)
    y = int(atlas_y)
    pad = int(gutter)
    base_scale = int(sample_scale)
    factor = validate_lightmap_resolution(resolution)
    if x < 0 or y < 0 or pad < 0 or base_scale <= 0:
        raise ValueError("Lightmap rectangle coordinates, gutter and sample scale must be valid.")
    return ((x + pad) * factor, (y + pad) * factor, base_scale * factor)


def resample_rgba_pixels(pixels, source_width, source_height, target_width, target_height):
    """Resample bottom-up RGBA float pixels using exact replication or box averaging.

    Integer upscales replicate source luxels without changing their value, so a
    classic BSP export can average each enlarged luxel back to its exact source
    value when the image has not been painted. Integer downscales use a box
    average, retaining the mean contribution of high-resolution brush strokes.
    """
    sw, sh = int(source_width), int(source_height)
    tw, th = int(target_width), int(target_height)
    if min(sw, sh, tw, th) <= 0:
        raise ValueError("Image dimensions must be positive.")
    source = array.array('f', pixels)
    if len(source) != sw * sh * 4:
        raise ValueError("RGBA pixel buffer length does not match the source dimensions.")
    if (sw, sh) == (tw, th):
        return source

    if tw % sw == 0 and th % sh == 0 and tw // sw == th // sh:
        factor = tw // sw
        if factor not in LIGHTMAP_RESOLUTIONS:
            raise ValueError("Only 1x, 2x, 4x and 8x integer resampling is supported.")
        output = array.array('f')
        for sy in range(sh):
            row = array.array('f')
            for sx in range(sw):
                offset = (sy * sw + sx) * 4
                row.extend(source[offset:offset + 4] * factor)
            output.extend(row * factor)
        return output

    if sw % tw == 0 and sh % th == 0 and sw // tw == sh // th:
        factor = sw // tw
        if factor not in LIGHTMAP_RESOLUTIONS:
            raise ValueError("Only 1x, 2x, 4x and 8x integer resampling is supported.")
        output = array.array('f', [0.0]) * (tw * th * 4)
        divisor = float(factor * factor)
        for dy in range(th):
            for dx in range(tw):
                totals = [0.0, 0.0, 0.0, 0.0]
                for oy in range(factor):
                    for ox in range(factor):
                        offset = (((dy * factor + oy) * sw) + dx * factor + ox) * 4
                        for channel in range(4):
                            totals[channel] += source[offset + channel]
                destination = (dy * tw + dx) * 4
                for channel in range(4):
                    output[destination + channel] = totals[channel] / divisor
        return output

    raise ValueError("Source and target dimensions must differ by a supported uniform integer scale.")


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
