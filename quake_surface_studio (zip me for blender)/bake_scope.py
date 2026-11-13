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
        y0 = int(atlas_y[index]) * resolution + gutter - padding
        x1 = int(atlas_x[index]) * resolution + gutter + sample_w * scale + padding
        y1 = int(atlas_y[index]) * resolution + gutter + sample_h * scale + padding
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
]
