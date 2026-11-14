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


def dilate_luxel_islands(
    pixels, image_width: int, image_height: int, islands, *,
    resolution: int = 1, lightmap_scale: int = 1, gutter: int = 0,
) -> int:
    """Pad each face's atlas allocation from its own sampled luxel centres.

    An island is (atlas_x, atlas_y, sample_width, sample_height), with atlas
    coordinates at the top-left of the reserved rectangle in base-atlas pixels.
    Every scaled luxel block and its gutter is filled from the nearest luxel
    centre. This prevents renderer margin dilation from copying adjacent faces.
    """
    import math

    width, height = int(image_width), int(image_height)
    factor, base_scale, base_gutter = int(resolution), int(lightmap_scale), int(gutter)
    if width <= 0 or height <= 0:
        raise ValueError("Atlas dimensions must be positive.")
    if factor < 1 or base_scale < 1 or base_gutter < 0:
        raise ValueError("Resolution and scale must be positive; gutter cannot be negative.")
    if len(pixels) != width * height * 4:
        raise ValueError("RGBA pixel buffer does not match the supplied atlas dimensions.")
    block, pad = base_scale * factor, base_gutter * factor
    centre_offset = (block - 1) * 0.5
    seen, changed = set(), 0

    def sample_bilinear(x, y):
        x = min(max(float(x), 0.0), width - 1.0)
        y = min(max(float(y), 0.0), height - 1.0)
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        x1, y1 = min(width - 1, x0 + 1), min(height - 1, y0 + 1)
        fx, fy = x - x0, y - y0
        values = []
        for channel in range(4):
            a = float(pixels[(y0 * width + x0) * 4 + channel])
            b = float(pixels[(y0 * width + x1) * 4 + channel])
            c = float(pixels[(y1 * width + x0) * 4 + channel])
            d = float(pixels[(y1 * width + x1) * 4 + channel])
            values.append((a * (1-fx) + b * fx) * (1-fy) + (c * (1-fx) + d * fx) * fy)
        return tuple(values)

    for island in islands:
        if len(island) != 4:
            raise ValueError("Each lightmap island must contain x, y, width and height.")
        atlas_x, atlas_y, sample_w, sample_h = (int(v) for v in island)
        if atlas_x < 0 or atlas_y < 0:
            raise ValueError("Lightmap island coordinates cannot be negative.")
        if sample_w <= 0 or sample_h <= 0:
            continue
        identity = (atlas_x, atlas_y, sample_w, sample_h)
        if identity in seen:
            continue
        seen.add(identity)

        tile_x0, tile_y0 = atlas_x * factor, atlas_y * factor
        content_x0, content_y0 = tile_x0 + pad, tile_y0 + pad
        tile_x1 = tile_x0 + sample_w * block + 2 * pad
        tile_y1 = tile_y0 + sample_h * block + 2 * pad
        if tile_x1 > width or tile_y1 > height:
            raise ValueError("Lightmap island allocation lies outside the image.")

        samples = []
        for sy in range(sample_h):
            y_top = content_y0 + sy * block + centre_offset
            y_bottom = height - 1.0 - y_top
            for sx in range(sample_w):
                x = content_x0 + sx * block + centre_offset
                samples.append(sample_bilinear(x, y_bottom))

        for y_top in range(tile_y0, tile_y1):
            sy = int(math.floor((y_top - (content_y0 + centre_offset)) / block + 0.5))
            sy = min(sample_h - 1, max(0, sy))
            y_bottom = height - 1 - y_top
            for x in range(tile_x0, tile_x1):
                sx = int(math.floor((x - (content_x0 + centre_offset)) / block + 0.5))
                sx = min(sample_w - 1, max(0, sx))
                rgba = samples[sy * sample_w + sx]
                offset = (y_bottom * width + x) * 4
                pixels[offset:offset + 4] = rgba
                changed += 1
    return changed


__all__ = [
    "resolve_target_faces",
    "face_luxel_rectangles",
    "scale_rgba_regions",
    "merge_rgba_regions",
    "dilate_luxel_islands",
]
