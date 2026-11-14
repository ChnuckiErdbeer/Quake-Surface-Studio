"""Pure helpers for partial SLOPGATE lightmap bakes.

This module deliberately has no Blender dependency so face filtering and
atlas-region updates can be covered by the standalone Python test suite.
"""

from __future__ import annotations


def resolve_target_faces(
    face_count: int,
    selected_faces=None,
    directly_lit_faces=None,
    *,
    use_selected_faces: bool = False,
    use_selected_lights: bool = False,
) -> list[int]:
    """Return stable mesh-polygon indices after applying active bake filters."""
    count = max(0, int(face_count))
    valid = set(range(count))
    targets = valid
    if use_selected_faces:
        targets &= {int(i) for i in (selected_faces or ()) if 0 <= int(i) < count}
    if use_selected_lights:
        targets &= {int(i) for i in (directly_lit_faces or ()) if 0 <= int(i) < count}
    return sorted(targets)


def face_luxel_rectangles(
    face_indices,
    atlas_x,
    atlas_y,
    sample_width,
    sample_height,
    *,
    image_width: int,
    image_height: int,
    resolution: int = 1,
    lightmap_scale: int = 1,
    gutter: int = 0,
    padding: int = 0,
):
    """Return clipped atlas pixel rectangles for selected face luxel regions.

    Coordinates use Blender image pixel orientation (UV origin at bottom-left).
    Rectangles include the reserved gutter/padding so bake edge extension can
    update the selected face's own atlas allocation without touching other faces.
    """
    width = max(0, int(image_width))
    height = max(0, int(image_height))
    resolution = max(1, int(resolution))
    scale = max(1, int(lightmap_scale)) * resolution
    gutter = max(0, int(gutter))
    padding = max(0, int(padding))
    if len(atlas_x) != len(atlas_y) or len(atlas_x) != len(sample_width) or len(atlas_x) != len(sample_height):
        raise ValueError("Face atlas attribute arrays must have matching lengths.")

    rectangles = []
    for raw_index in face_indices:
        index = int(raw_index)
        if index < 0 or index >= len(atlas_x):
            continue
        sample_w = max(0, int(sample_width[index]))
        sample_h = max(0, int(sample_height[index]))
        if sample_w <= 0 or sample_h <= 0:
            continue
        x0 = int(atlas_x[index]) * resolution + gutter - padding
        x1 = int(atlas_x[index]) * resolution + gutter + sample_w * scale + padding
        top_y0 = int(atlas_y[index]) * resolution + gutter
        top_y1 = top_y0 + sample_h * scale
        # BSP atlas attributes use top-left rows; Blender image pixels use
        # bottom-left rows. Convert before touching pixel buffers.
        y0 = height - (top_y1 + padding)
        y1 = height - top_y0 + padding
        x0 = max(0, min(width, x0))
        y0 = max(0, min(height, y0))
        x1 = max(0, min(width, x1))
        y1 = max(0, min(height, y1))
        if x1 > x0 and y1 > y0:
            rectangles.append((x0, y0, x1, y1))
    return rectangles


def _merged_row_intervals(rectangles, image_width: int, image_height: int):
    """Yield row intervals with overlaps merged."""
    rows = {}
    for rect in rectangles:
        x0, y0, x1, y1 = (int(value) for value in rect)
        x0 = max(0, min(int(image_width), x0))
        x1 = max(0, min(int(image_width), x1))
        y0 = max(0, min(int(image_height), y0))
        y1 = max(0, min(int(image_height), y1))
        if x1 <= x0 or y1 <= y0:
            continue
        for y in range(y0, y1):
            rows.setdefault(y, []).append((x0, x1))

    for y in sorted(rows):
        intervals = sorted(rows[y])
        if not intervals:
            continue
        start, end = intervals[0]
        for next_start, next_end in intervals[1:]:
            if next_start <= end:
                end = max(end, next_end)
            else:
                yield y, start, end
                start, end = next_start, next_end
        yield y, start, end



def merge_rgba_regions(
    destination,
    source,
    image_width: int,
    image_height: int,
    rectangles,
    factor: float = 1.0,
):
    """Copy and scale source RGBA pixels only inside selected rectangles.

    Pixels outside the requested regions are never modified, so a partial bake
    preserves the rest of the existing lightmap. Overlapping rectangles are
    merged to prevent a pixel being scaled more than once.
    """
    width = int(image_width)
    height = int(image_height)
    expected = width * height * 4
    if width < 0 or height < 0 or len(destination) != expected or len(source) != expected:
        raise ValueError("RGBA pixel buffers do not match the supplied image dimensions.")
    scale = max(0.0, float(factor))
    changed = 0
    for y, x0, x1 in _merged_row_intervals(rectangles, width, height):
        offset = (y * width + x0) * 4
        for _x in range(x0, x1):
            destination[offset] = max(0.0, float(source[offset]) * scale)
            destination[offset + 1] = max(0.0, float(source[offset + 1]) * scale)
            destination[offset + 2] = max(0.0, float(source[offset + 2]) * scale)
            destination[offset + 3] = 1.0
            offset += 4
            changed += 1
    return changed

def dilate_rgba_gutters(pixels, image_width: int, image_height: int, core_rectangles, padding: int = 0):
    """Extend each face's own edge texels into its reserved atlas gutter.

    Coordinates are bottom-up pixel rectangles (x0, y0, x1, y1), with the
    upper bounds exclusive. Padding is in working-image pixels. Core texels
    are never changed, and gutter pixels copy the nearest texel inside the
    same face rectangle; adjacent islands are never blended.
    """
    width, height = int(image_width), int(image_height)
    expected = width * height * 4
    if width <= 0 or height <= 0 or len(pixels) != expected:
        raise ValueError("RGBA pixel buffer does not match the supplied image dimensions.")
    pad = int(padding)
    if pad < 0:
        raise ValueError("Gutter padding cannot be negative.")
    if pad == 0:
        return 0

    regions = []
    for rectangle in core_rectangles:
        if len(rectangle) != 4:
            raise ValueError("Each face core rectangle must contain four coordinates.")
        x0, y0, x1, y1 = (int(value) for value in rectangle)
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        expanded = (
            max(0, x0 - pad), max(0, y0 - pad),
            min(width, x1 + pad), min(height, y1 + pad),
        )
        regions.append(((x0, y0, x1, y1), expanded))

    # A packed layout must reserve enough space for both one-sided gutters.
    # Fail closed rather than allowing one face to overwrite another.
    for index, (_core_a, rect_a) in enumerate(regions):
        ax0, ay0, ax1, ay1 = rect_a
        for _core_b, rect_b in regions[index + 1:]:
            bx0, by0, bx1, by1 = rect_b
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                raise ValueError("Expanded lightmap face gutters overlap; atlas packing needs more padding.")

    changed = 0
    for (x0, y0, x1, y1), (ex0, ey0, ex1, ey1) in regions:
        for y in range(ey0, ey1):
            source_y = min(y1 - 1, max(y0, y))
            for x in range(ex0, ex1):
                if x0 <= x < x1 and y0 <= y < y1:
                    continue
                source_x = min(x1 - 1, max(x0, x))
                source_offset = (source_y * width + source_x) * 4
                target_offset = (y * width + x) * 4
                pixels[target_offset] = pixels[source_offset]
                pixels[target_offset + 1] = pixels[source_offset + 1]
                pixels[target_offset + 2] = pixels[source_offset + 2]
                pixels[target_offset + 3] = pixels[source_offset + 3]
                changed += 1
    return changed



def collapse_rgba_luxel_blocks(
    pixels,
    image_width: int,
    image_height: int,
    core_rectangles,
    block_size: int,
):
    """Make every supersampled Quake luxel block hold one centre-sampled value.

    Cycles renders into a higher-resolution working atlas. A Quake lightmap,
    however, stores one value per luxel. Retaining small per-pixel variations
    inside a luxel block makes the Blender preview look softer than the data
    that will be written back to BSP. This reduces each block at its geometric
    centre (bilinear 2x2 centre for even-sized blocks) and replicates that
    value across the block.

    Rectangles are bottom-up core pixel bounds with exclusive upper limits.
    Gutters and pixels outside the supplied face cores are never modified.
    Returns the number of luxel blocks processed.
    """
    width, height = int(image_width), int(image_height)
    block = int(block_size)
    expected = width * height * 4
    if width <= 0 or height <= 0 or len(pixels) != expected:
        raise ValueError("RGBA pixel buffer does not match the supplied image dimensions.")
    if block < 1:
        raise ValueError("Luxel block size must be at least one pixel.")

    regions = []
    for rectangle in core_rectangles:
        if len(rectangle) != 4:
            raise ValueError("Each face core rectangle must contain four coordinates.")
        x0, y0, x1, y1 = (int(value) for value in rectangle)
        if x0 < 0 or y0 < 0 or x1 > width or y1 > height or x1 <= x0 or y1 <= y0:
            raise ValueError("A face core rectangle lies outside the image or is empty.")
        if (x1 - x0) % block or (y1 - y0) % block:
            raise ValueError("Face core dimensions must be exact multiples of the luxel block size.")
        regions.append((x0, y0, x1, y1))

    for index, rect_a in enumerate(regions):
        ax0, ay0, ax1, ay1 = rect_a
        for rect_b in regions[index + 1:]:
            bx0, by0, bx1, by1 = rect_b
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                raise ValueError("Face core rectangles overlap; atlas metadata is inconsistent.")

    centre = ((block - 1) // 2, block // 2)
    processed = 0
    for x0, y0, x1, y1 in regions:
        for by in range(y0, y1, block):
            for bx in range(x0, x1, block):
                # An even-sized block has its exact centre between four pixels.
                # Averaging those four is a bilinear point sample at that centre;
                # it is deliberately not an average of the whole block.
                sample = [0.0, 0.0, 0.0, 0.0]
                sample_count = 0
                for sy in set(centre):
                    for sx in set(centre):
                        offset = ((by + sy) * width + bx + sx) * 4
                        for channel in range(4):
                            sample[channel] += float(pixels[offset + channel])
                        sample_count += 1
                inverse_count = 1.0 / sample_count
                sample = [value * inverse_count for value in sample]
                for py in range(by, by + block):
                    offset = (py * width + bx) * 4
                    for _px in range(bx, bx + block):
                        pixels[offset] = sample[0]
                        pixels[offset + 1] = sample[1]
                        pixels[offset + 2] = sample[2]
                        pixels[offset + 3] = sample[3]
                        offset += 4
                processed += 1
    return processed


def scale_rgba_regions(pixels, image_width: int, image_height: int, rectangles, factor: float):
    """Scale RGB only within selected atlas rectangles; leave other pixels intact.

    pixels is a mutable flat RGBA sequence (for example array('f')). Returns
    the number of pixels modified. Alpha is kept at 1.0 for touched lightmap
    pixels, matching the full-atlas SLOPGATE bake path.
    """
    width = int(image_width)
    height = int(image_height)
    expected = width * height * 4
    if width < 0 or height < 0 or len(pixels) != expected:
        raise ValueError("RGBA pixel buffer does not match the supplied image dimensions.")
    scale = max(0.0, float(factor))
    changed = 0
    for y, x0, x1 in _merged_row_intervals(rectangles, width, height):
        index = (y * width + x0) * 4
        for _x in range(x0, x1):
            pixels[index] = max(0.0, float(pixels[index]) * scale)
            pixels[index + 1] = max(0.0, float(pixels[index + 1]) * scale)
            pixels[index + 2] = max(0.0, float(pixels[index + 2]) * scale)
            pixels[index + 3] = 1.0
            index += 4
            changed += 1
    return changed


__all__ = [
    "resolve_target_faces",
    "face_luxel_rectangles",
    "scale_rgba_regions",
    "merge_rgba_regions",
    "dilate_rgba_gutters",
    "collapse_rgba_luxel_blocks",
]
