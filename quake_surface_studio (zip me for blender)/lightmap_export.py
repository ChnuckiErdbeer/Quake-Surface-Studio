"""Pure helpers for importing and exporting Quake BSPX lightmap layouts.

DECOUPLED_LM stores one explicit sample grid and two independent world-to-luxel
vectors per face. Enhanced QSS output retains classic LIGHTING samples at the
front of the standard lump and appends the rebuilt per-face samples so engines
that ignore BSPX can use the vanilla BSP29 face lightofs fallback.
"""
from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from typing import Any

SUPPORTED_RESOLUTIONS = (1, 2, 4, 8)
MAX_SURFACE_LUXELS = 256
NO_LIGHT_OFFSET = 0xFFFFFFFF


def choose_luxel_grid(
    s_values: Sequence[float],
    t_values: Sequence[float],
    working_resolution: int,
    max_luxels: int = MAX_SURFACE_LUXELS,
) -> tuple[int, int, int, int, int]:
    """Choose the finest power-of-two luxel spacing supported by the atlas.

    Returns (lmshift, s_min, t_min, width, height). A 1x working atlas uses
    the classic 16-unit spacing (shift 4); 2x/4x/8x request progressively
    denser 8/4/2-unit spacing. Oversized faces are conservatively coarsened.
    """
    if working_resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError(f"Unsupported working lightmap resolution: {working_resolution}")
    if not s_values or not t_values or len(s_values) != len(t_values):
        raise ValueError("S/T projection coordinate arrays must be non-empty and equal length")
    if max_luxels < 2:
        raise ValueError("Maximum per-face luxel dimension must be at least 2")
    values = tuple(float(v) for v in (*s_values, *t_values))
    if not all(math.isfinite(v) for v in values):
        raise ValueError("S/T projection coordinates must be finite")

    target_shift = 4 - int(math.log2(working_resolution))
    epsilon = 1e-7
    for shift in range(target_shift, 5):
        spacing = 1 << shift
        s_min = math.floor(min(s_values) / spacing + epsilon) * spacing
        s_max = math.ceil(max(s_values) / spacing - epsilon) * spacing
        t_min = math.floor(min(t_values) / spacing + epsilon) * spacing
        t_max = math.ceil(max(t_values) / spacing - epsilon) * spacing
        width = (s_max - s_min) // spacing + 1
        height = (t_max - t_min) // spacing + 1
        if 1 <= width <= max_luxels and 1 <= height <= max_luxels:
            return shift, int(s_min), int(t_min), int(width), int(height)
    raise ValueError(
        f"Face exceeds the {max_luxels}x{max_luxels} BSPX lightmap limit, even at 16 units per luxel"
    )


def bilinear_sample_rgba(
    pixels: Sequence[float], width: int, height: int, x: float, y: float
) -> tuple[float, float, float, float]:
    """Bilinearly sample a bottom-up RGBA float buffer in pixel-index space."""
    if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
        raise ValueError("RGBA buffer dimensions do not match its pixel data")
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("Pixel coordinates must be finite")
    if x < -1e-6 or y < -1e-6 or x > width - 1 + 1e-6 or y > height - 1 + 1e-6:
        raise ValueError("Pixel sample lies outside the atlas image")
    x = min(max(x, 0.0), width - 1.0)
    y = min(max(y, 0.0), height - 1.0)
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    x1, y1 = min(width - 1, x0 + 1), min(height - 1, y0 + 1)
    fx, fy = x - x0, y - y0

    def rgba_at(px: int, py: int) -> tuple[float, float, float, float]:
        offset = (py * width + px) * 4
        return tuple(float(pixels[offset + channel]) for channel in range(4))

    a = rgba_at(x0, y0)
    b = rgba_at(x1, y0)
    c = rgba_at(x0, y1)
    d = rgba_at(x1, y1)
    return tuple(
        (a[i] * (1.0 - fx) + b[i] * fx) * (1.0 - fy)
        + (c[i] * (1.0 - fx) + d[i] * fx) * fy
        for i in range(4)
    )


def sample_face_rgb_from_atlas(
    pixels: Sequence[float],
    image_size: int,
    working_resolution: int,
    atlas_x: int,
    atlas_y: int,
    gutter: int,
    pixels_per_luxel: int,
    base_s_min: int,
    base_t_min: int,
    s_min: int,
    t_min: int,
    sample_width: int,
    sample_height: int,
    spacing: int,
) -> bytes:
    """Sample a face's luxel grid from the shared, bottom-up RGBA atlas.

    atlas_x/y, gutter and pixels_per_luxel are in base-atlas pixels.
    s_min/t_min and spacing describe the requested output luxel grid;
    base_s_min/t_min describe the original 16-unit grid used by atlas UVs.
    """
    if image_size <= 0 or working_resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Invalid image size or working resolution")
    if min(atlas_x, atlas_y, gutter) < 0 or pixels_per_luxel <= 0:
        raise ValueError("Invalid atlas rectangle metadata")
    if sample_width <= 0 or sample_height <= 0 or spacing <= 0:
        raise ValueError("Invalid output luxel grid")
    if len(pixels) != image_size * image_size * 4:
        raise ValueError("RGBA buffer dimensions do not match the atlas image")

    pixel_block = pixels_per_luxel * working_resolution
    origin_x = (atlas_x + gutter) * working_resolution
    origin_y = (atlas_y + gutter) * working_resolution
    output = bytearray()
    for sy in range(sample_height):
        t = t_min + sy * spacing
        luxel_t = (t - base_t_min) / 16.0
        center_y_from_top = origin_y + (luxel_t + 0.5) * pixel_block
        pixel_y = image_size - center_y_from_top - 0.5
        for sx in range(sample_width):
            s = s_min + sx * spacing
            luxel_s = (s - base_s_min) / 16.0
            center_x = origin_x + (luxel_s + 0.5) * pixel_block
            pixel_x = center_x - 0.5
            red, green, blue, _alpha = bilinear_sample_rgba(
                pixels, image_size, image_size, pixel_x, pixel_y
            )
            output.extend(
                max(0, min(255, int(round(channel * 255.0))))
                for channel in (red, green, blue)
            )
    return bytes(output)



def sample_face_rgb_at_coordinates(
    pixels: Sequence[float],
    image_size: int,
    working_resolution: int,
    atlas_x: int,
    atlas_y: int,
    gutter: int,
    pixels_per_luxel: int,
    base_s_min: int,
    base_t_min: int,
    s_coordinates: Sequence[float],
    t_coordinates: Sequence[float],
) -> bytes:
    """Sample arbitrary S/T luxel coordinates from a face's shared atlas island.

    Coordinates use the source face's original Quake texinfo projection and
    the original 16-unit luxel grid. This is used when a detached face gets a
    new texinfo projection and therefore needs a reprojected classic lightmap.
    """
    if image_size <= 0 or working_resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Invalid image size or working-resolution multiplier")
    if min(atlas_x, atlas_y, gutter) < 0 or pixels_per_luxel <= 0:
        raise ValueError("Invalid atlas rectangle metadata")
    if not s_coordinates or not t_coordinates:
        raise ValueError("S/T sample coordinates must be non-empty")
    if len(pixels) != image_size * image_size * 4:
        raise ValueError("RGBA buffer dimensions do not match the atlas image")
    coordinates = tuple(float(v) for v in (*s_coordinates, *t_coordinates))
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("S/T sample coordinates must be finite")

    pixel_block = int(pixels_per_luxel) * int(working_resolution)
    origin_x = (int(atlas_x) + int(gutter)) * int(working_resolution)
    origin_y = (int(atlas_y) + int(gutter)) * int(working_resolution)
    output = bytearray()
    for t in t_coordinates:
        luxel_t = (float(t) - float(base_t_min)) / 16.0
        center_y_from_top = origin_y + (luxel_t + 0.5) * pixel_block
        pixel_y = image_size - center_y_from_top - 0.5
        for s in s_coordinates:
            luxel_s = (float(s) - float(base_s_min)) / 16.0
            center_x = origin_x + (luxel_s + 0.5) * pixel_block
            pixel_x = center_x - 0.5
            red, green, blue, _alpha = bilinear_sample_rgba(
                pixels, image_size, image_size, pixel_x, pixel_y
            )
            output.extend(
                max(0, min(255, int(round(channel * 255.0))))
                for channel in (red, green, blue)
            )
    return bytes(output)




def parse_decoupled_lightmap_data(payload: bytes, face_count: int):
    """Parse the BSPX DECOUPLED_LM table (one 40-byte record per BSP face).

    A zero-sized record with offset 0xffffffff marks an unlightmapped face.
    All other records contain explicit dimensions, a sample offset and two
    independent world-to-luxel projection vectors.
    """
    raw = bytes(payload)
    count = int(face_count)
    if count < 0 or len(raw) != count * 40:
        raise ValueError(
            f"DECOUPLED_LM must contain exactly {count * 40} bytes "
            f"({count} records of 40 bytes); found {len(raw)}"
        )
    records = []
    for face_id in range(count):
        width, height, offset, *vectors = struct.unpack_from("<HHI8f", raw, face_id * 40)
        if width == 0 and height == 0 and offset == NO_LIGHT_OFFSET:
            records.append(None)
            continue
        if width == 0 or height == 0:
            raise ValueError(
                f"DECOUPLED_LM face {face_id} has inconsistent dimensions {width}x{height}"
            )
        if offset == NO_LIGHT_OFFSET:
            raise ValueError(f"DECOUPLED_LM face {face_id} has dimensions but no light offset")
        if not all(math.isfinite(value) for value in vectors):
            raise ValueError(f"DECOUPLED_LM face {face_id} has non-finite projection vectors")
        records.append({
            "width": int(width),
            "height": int(height),
            "offset": int(offset),
            "lmvecs": tuple(float(value) for value in vectors),
        })
    return tuple(records)



def sample_face_rgb_at_lm_coordinate_pairs(
    pixels: Sequence[float],
    image_size: int,
    working_resolution: int,
    atlas_x: int,
    atlas_y: int,
    gutter: int,
    pixels_per_luxel: int,
    coordinates: Sequence[Sequence[float]],
) -> bytes:
    """Sample arbitrary (S,T) positions from one atlas island.

    Unlike a separable S/T grid, this accepts a different S and T coordinate
    for every output pixel. It is required when the imported decoupled axes are
    rotated or otherwise couple the two texture-space directions.
    """
    if image_size <= 0 or working_resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Invalid image size or working lightmap resolution")
    if min(atlas_x, atlas_y, gutter) < 0 or pixels_per_luxel <= 0:
        raise ValueError("Invalid atlas rectangle metadata")
    if len(pixels) != image_size * image_size * 4:
        raise ValueError("RGBA buffer dimensions do not match the atlas image")
    if not coordinates:
        raise ValueError("At least one arbitrary lightmap coordinate is required")
    normalized = []
    for coordinate in coordinates:
        if len(coordinate) != 2:
            raise ValueError("Each arbitrary lightmap coordinate must contain S and T")
        s, t = float(coordinate[0]), float(coordinate[1])
        if not math.isfinite(s) or not math.isfinite(t):
            raise ValueError("Arbitrary lightmap coordinates must be finite")
        normalized.append((s, t))

    pixel_block = int(pixels_per_luxel) * int(working_resolution)
    origin_x = (int(atlas_x) + int(gutter)) * int(working_resolution)
    origin_y = (int(atlas_y) + int(gutter)) * int(working_resolution)
    output = bytearray()
    for s, t in normalized:
        pixel_x = origin_x + (s + 0.5) * pixel_block - 0.5
        pixel_y = image_size - origin_y - (t + 0.5) * pixel_block - 0.5
        red, green, blue, _alpha = bilinear_sample_rgba(
            pixels, image_size, image_size, pixel_x, pixel_y
        )
        output.extend(
            max(0, min(255, int(round(channel * 255.0))))
            for channel in (red, green, blue)
        )
    return bytes(output)

def sample_face_rgb_at_lm_coordinates(
    pixels: Sequence[float],
    image_size: int,
    working_resolution: int,
    atlas_x: int,
    atlas_y: int,
    gutter: int,
    pixels_per_luxel: int,
    s_coordinates: Sequence[float],
    t_coordinates: Sequence[float],
) -> bytes:
    """Sample an atlas island at arbitrary DECOUPLED_LM luxel coordinates.

    Coordinates are already in sample-space units produced by the face's
    lmvecs; unlike classic texinfo coordinates, they must not be divided by 16.
    """
    if image_size <= 0 or working_resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Invalid image size or working lightmap resolution")
    if min(atlas_x, atlas_y, gutter) < 0 or pixels_per_luxel <= 0:
        raise ValueError("Invalid atlas rectangle metadata")
    if not s_coordinates or not t_coordinates:
        raise ValueError("S/T sample coordinates must be non-empty")
    if len(pixels) != image_size * image_size * 4:
        raise ValueError("RGBA buffer dimensions do not match the atlas image")
    coordinates = tuple(float(value) for value in (*s_coordinates, *t_coordinates))
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("Luxel coordinates must be finite")

    pixel_block = int(pixels_per_luxel) * int(working_resolution)
    origin_x = (int(atlas_x) + int(gutter)) * int(working_resolution)
    origin_y = (int(atlas_y) + int(gutter)) * int(working_resolution)
    output = bytearray()
    for t in t_coordinates:
        pixel_y = image_size - origin_y - (float(t) + 0.5) * pixel_block - 0.5
        for s in s_coordinates:
            pixel_x = origin_x + (float(s) + 0.5) * pixel_block - 0.5
            red, green, blue, _alpha = bilinear_sample_rgba(
                pixels, image_size, image_size, pixel_x, pixel_y
            )
            output.extend(
                max(0, min(255, int(round(channel * 255.0))))
                for channel in (red, green, blue)
            )
    return bytes(output)

def build_decoupled_lightmap_data(faces, texinfos, face_records, face_offsets):
    """Serialize BSPX DECOUPLED_LM records (40 bytes per BSP face).

    Lightmap axes are reconstructed from the source texinfo, independently of
    any face-local texture projection used by the exported texture.
    """
    faces = list(faces)
    texinfos = list(texinfos)
    offsets = bytes(face_offsets)
    if len(offsets) != len(faces) * 4:
        raise ValueError("DECOUPLED_LM requires one uint32 sample offset per face")
    output = bytearray()
    for face_id, face in enumerate(faces):
        record = face_records.get(face_id)
        offset = struct.unpack_from("<I", offsets, face_id * 4)[0]
        if record is None or offset == NO_LIGHT_OFFSET:
            output.extend(struct.pack("<HHI8f", 0, 0, NO_LIGHT_OFFSET, *([0.0] * 8)))
            continue
        width = int(record.get("width", 0))
        height = int(record.get("height", 0))
        if not (1 <= width <= 65535 and 1 <= height <= 65535):
            raise ValueError(f"Face {face_id} has invalid decoupled lightmap dimensions {width}x{height}")
        provided_vectors = record.get("lmvecs")
        if provided_vectors is not None:
            if len(provided_vectors) != 8:
                raise ValueError(f"Face {face_id} DECOUPLED_LM vectors must contain eight floats")
            vectors = tuple(float(value) for value in provided_vectors)
            if not all(math.isfinite(value) for value in vectors):
                raise ValueError(f"Face {face_id} has non-finite decoupled lightmap axes")
        else:
            shift = int(record.get("shift", -1))
            s_min = float(record.get("s_min", float("nan")))
            t_min = float(record.get("t_min", float("nan")))
            if shift < 0 or shift > 4:
                raise ValueError(f"Face {face_id} has invalid decoupled lightmap shift {shift}")
            if face[4] < 0 or face[4] >= len(texinfos):
                raise ValueError(f"Face {face_id} has an invalid source texinfo index")
            texinfo = texinfos[face[4]]
            spacing = float(1 << shift)
            vectors = (
                float(texinfo[0]) / spacing, float(texinfo[1]) / spacing,
                float(texinfo[2]) / spacing, (float(texinfo[3]) - s_min) / spacing,
                float(texinfo[4]) / spacing, float(texinfo[5]) / spacing,
                float(texinfo[6]) / spacing, (float(texinfo[7]) - t_min) / spacing,
            )
            if not all(math.isfinite(value) for value in vectors):
                raise ValueError(f"Face {face_id} has non-finite decoupled lightmap axes")
        output.extend(struct.pack("<HHI8f", width, height, offset, *vectors))
    return bytes(output)


def build_lightmap_extension_data(
    face_count: int,
    face_records: Mapping[int, Mapping[str, Any]],
    base_sample_count: int,
) -> dict[str, bytes | int]:
    """Build per-face offsets/styles and appended mono/RGB sample payloads.

    face_records maps original BSP face ID to {shift, width, height, rgb}.
    RGB is exactly width*height triplets in row-major face sample order.
    LMOFFSET is retained as an internal offset table for DECOUPLED_LM writing;
    QSS no longer emits LMSHIFT/LMOFFSET in its enhanced output.
    Unlit faces receive style=255 and offset=0xffffffff.
    """
    if face_count < 0:
        raise ValueError("Face count cannot be negative")
    if base_sample_count < 0 or base_sample_count > NO_LIGHT_OFFSET:
        raise ValueError("Classic lightmap sample count is outside uint32 range")

    shifts = bytearray([4]) * face_count
    offsets = bytearray()
    styles = bytearray([255]) * face_count
    appended_rgb = bytearray()
    appended_mono = bytearray()
    sample_offset = base_sample_count

    for face_id in range(face_count):
        record = face_records.get(face_id)
        if record is None:
            offset = NO_LIGHT_OFFSET
        else:
            shift = int(record.get("shift", -1))
            width = int(record.get("width", 0))
            height = int(record.get("height", 0))
            rgb = bytes(record.get("rgb", b""))
            if shift < 0 or shift > 4:
                raise ValueError(f"Face {face_id} has invalid LMSHIFT value {shift}")
            if width < 1 or height < 1 or width > MAX_SURFACE_LUXELS or height > MAX_SURFACE_LUXELS:
                raise ValueError(f"Face {face_id} has invalid {width}x{height} lightmap dimensions")
            if len(rgb) != width * height * 3:
                raise ValueError(f"Face {face_id} RGB data does not match its {width}x{height} grid")
            if sample_offset + width * height > NO_LIGHT_OFFSET:
                raise ValueError("Enhanced RGBLIGHTING exceeds the uint32 sample-offset limit")
            shifts[face_id] = shift
            styles[face_id] = 0
            offset = sample_offset
            appended_rgb.extend(rgb)
            for index in range(0, len(rgb), 3):
                red, green, blue = rgb[index:index + 3]
                appended_mono.append(max(0, min(255, int(round(
                    0.2126 * red + 0.7152 * green + 0.0722 * blue
                )))))
            sample_offset += width * height
        offsets.extend(struct.pack("<I", offset))

    return {
        "LMSHIFT": bytes(shifts),
        "LMOFFSET": bytes(offsets),
        "LMSTYLE": bytes(styles),
        "RGBLIGHTING_APPEND": bytes(appended_rgb),
        "LIGHTING_APPEND": bytes(appended_mono),
        "enhanced_sample_count": sample_offset - base_sample_count,
    }
