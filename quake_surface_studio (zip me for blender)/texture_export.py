"""Blender-independent helpers for detached-face texture atlases and BSP texture indexing."""
from __future__ import annotations

import math
from typing import Sequence


def quake_texture_dimension(value: float, maximum: int = 512) -> int:
    """Round up to a Quake miptexture dimension (multiple of eight)."""
    limit = max(8, int(maximum) // 8 * 8)
    parsed = max(8, int(math.ceil(float(value))))
    return max(8, min(limit, int(math.ceil(parsed / 8.0)) * 8))


def pack_face_rectangles(
    sizes: Sequence[tuple[int, int]],
    atlas_size: int = 512,
    padding: int = 2,
    min_scale: float = 0.25,
) -> dict:
    """Pack face-local images into one square atlas using deterministic shelf packing.

    Returned tile coordinates are bottom-left based and exclude the duplicated
    edge padding. If the full-size images do not fit, all tiles are uniformly
    reduced until they fit, preserving each face's aspect ratio.
    """
    limit = int(atlas_size)
    pad = int(padding)
    if limit <= 0 or pad < 0 or not sizes:
        raise ValueError("Atlas size, padding and source rectangles must be valid.")
    parsed = []
    for index, size in enumerate(sizes):
        if len(size) != 2:
            raise ValueError(f"Image {index} must have width and height.")
        width, height = (int(size[0]), int(size[1]))
        if width <= 0 or height <= 0:
            raise ValueError(f"Image {index} has invalid dimensions {width}x{height}.")
        parsed.append((index, width, height))

    scale = 1.0
    while scale + 1e-9 >= float(min_scale):
        rectangles = []
        for index, width, height in parsed:
            scaled_w = max(8, min(limit - 2 * pad, int(round(width * scale))))
            scaled_h = max(8, min(limit - 2 * pad, int(round(height * scale))))
            rectangles.append((index, scaled_w + 2 * pad, scaled_h + 2 * pad,
                               scaled_w, scaled_h))
        rectangles.sort(key=lambda item: (-item[2], -item[1], item[0]))

        tiles = [None] * len(parsed)
        x = y = shelf_height = 0
        failed = False
        for index, outer_w, outer_h, content_w, content_h in rectangles:
            if outer_w > limit or outer_h > limit:
                failed = True
                break
            if x + outer_w > limit:
                y += shelf_height
                x = 0
                shelf_height = 0
            if y + outer_h > limit:
                failed = True
                break
            tiles[index] = {
                "x": x + pad, "y": y + pad,
                "width": content_w, "height": content_h,
            }
            x += outer_w
            shelf_height = max(shelf_height, outer_h)
        if not failed and all(tile is not None for tile in tiles):
            return {"atlas_size": limit, "scale": scale, "padding": pad, "tiles": tiles}
        scale = round(scale - 0.025, 3)

    raise ValueError(
        f"{len(parsed)} detached face textures do not fit in a {limit}x{limit} paint atlas "
        f"at the minimum {min_scale:.0%} scale. Detach fewer faces at once."
    )


def remap_uvs_to_atlas(uvs, tile: dict, atlas_size: int = 512):
    """Map a face's 0..1 UVs into its atlas tile, keeping bottom-left UV origin."""
    size = float(atlas_size)
    x, y = float(tile["x"]), float(tile["y"])
    width, height = float(tile["width"]), float(tile["height"])
    return [
        ((x + float(u) * width) / size, (y + float(v) * height) / size)
        for u, v in uvs
    ]


def projection_for_atlas_tile(
    projection: Sequence[float],
    source_size: tuple[int, int],
    tile: dict,
    atlas_size: int = 512,
) -> tuple[float, ...]:
    """Transform face-local Quake S/T axes into the packed atlas texel space."""
    if len(projection) != 8:
        raise ValueError("A detached projection must contain eight values.")
    source_w, source_h = int(source_size[0]), int(source_size[1])
    if source_w <= 0 or source_h <= 0 or atlas_size <= 0:
        raise ValueError("Source image and atlas dimensions must be positive.")
    sx = float(tile["width"]) / source_w
    sy = float(tile["height"]) / source_h
    x = float(tile["x"])
    # Quake T grows downwards while atlas UV V grows from the bottom upwards.
    t_offset = float(atlas_size - int(tile["y"]) - int(tile["height"]))
    return (
        float(projection[0]) * sx,
        float(projection[1]) * sx,
        float(projection[2]) * sx,
        float(projection[3]) * sx + x,
        float(projection[4]) * sy,
        float(projection[5]) * sy,
        float(projection[6]) * sy,
        float(projection[7]) * sy + t_offset,
    )


def allocate_image_texture_index(entries: list, indices_by_image: dict, image_key, entry) -> int:
    """Append one miptex per distinct image identity and return its contiguous index."""
    if image_key in indices_by_image:
        return int(indices_by_image[image_key])
    index = len(entries)
    entries.append(entry)
    indices_by_image[image_key] = index
    return index


def resample_rgba_nearest(pixels, source_width, source_height, target_width, target_height):
    """Nearest-neighbour resample of a bottom-up RGBA float image."""
    sw, sh = int(source_width), int(source_height)
    tw, th = int(target_width), int(target_height)
    if min(sw, sh, tw, th) <= 0 or len(pixels) != sw * sh * 4:
        raise ValueError("RGBA source buffer or image dimensions are invalid.")
    if (sw, sh) == (tw, th):
        return [float(value) for value in pixels]
    output = [0.0] * (tw * th * 4)
    for y in range(th):
        sy = min(sh - 1, int((y + 0.5) * sh / th))
        for x in range(tw):
            sx = min(sw - 1, int((x + 0.5) * sw / tw))
            source = (sy * sw + sx) * 4
            target = (y * tw + x) * 4
            output[target:target + 4] = pixels[source:source + 4]
    return output


def inverse_project_axis_coordinates(old_axis, new_axis, coordinates):
    """Map coordinates from a scaled/offset new texinfo axis back to the old axis."""
    old = tuple(float(value) for value in old_axis)
    new = tuple(float(value) for value in new_axis)
    if len(old) != 4 or len(new) != 4:
        raise ValueError("Texinfo axes must contain xyz and offset values.")
    magnitude = sum(value * value for value in old[:3])
    if magnitude <= 1e-20:
        raise ValueError("The source texinfo axis has zero length.")
    scale = sum(old[i] * new[i] for i in range(3)) / magnitude
    residual = math.sqrt(sum((new[i] - scale * old[i]) ** 2 for i in range(3)))
    tolerance = max(1e-6, math.sqrt(magnitude) * 1e-5)
    if not math.isfinite(scale) or abs(scale) <= 1e-12 or residual > tolerance:
        raise ValueError("The detached projection is not a scaled copy of the source texinfo axis.")
    old_offset, new_offset = old[3], new[3]
    return tuple((float(value) - new_offset) / scale + old_offset for value in coordinates)
