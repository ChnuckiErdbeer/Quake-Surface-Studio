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


def add_half_luxel_edge_padding(record: Mapping[str, Any],
                                 max_dimension: int = MAX_SURFACE_LUXELS) -> tuple[dict[str, Any], bool]:
    """Add a half-luxel support rim for linear filtering at a face boundary.

    The output grid is one sample wider and taller. New output sample (x, y)
    resamples the original grid at (x - 0.5, y - 0.5), clamped to the face
    bounds. The projection origin is shifted by +0.5 luxel on both axes, so a
    face edge maps between the rim sample and the first interior sample.

    Returns (record, padded). Oversized faces are returned unchanged with
    padded=False rather than exceeding the per-surface dimension limit.
    """
    if not isinstance(record, Mapping):
        raise ValueError("Lightmap face record must be a mapping")
    width = int(record.get("width", 0))
    height = int(record.get("height", 0))
    rgb = bytes(record.get("rgb", b""))
    if width < 1 or height < 1:
        raise ValueError("Lightmap face dimensions must be positive")
    if len(rgb) != width * height * 3:
        raise ValueError(
            f"RGB data has {len(rgb)} bytes but the {width}x{height} face grid needs {width * height * 3}"
        )
    max_dimension = int(max_dimension)
    if max_dimension < 1:
        raise ValueError("Maximum lightmap dimension must be positive")
    if width + 1 > max_dimension or height + 1 > max_dimension:
        return dict(record), False

    if "lmvecs" in record:
        lmvecs = tuple(float(value) for value in record["lmvecs"])
        if len(lmvecs) != 8 or not all(math.isfinite(value) for value in lmvecs):
            raise ValueError("Decoupled lightmap vectors must contain eight finite values")
        shifted = list(lmvecs)
        shifted[3] += 0.5
        shifted[7] += 0.5
    else:
        try:
            shift = int(record["shift"])
            s_min = float(record["s_min"])
            t_min = float(record["t_min"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Classic lightmap record needs shift, s_min and t_min") from exc
        if shift < 0 or shift > 4:
            raise ValueError(f"Invalid lightmap shift for edge padding: {shift}")
        if not math.isfinite(s_min) or not math.isfinite(t_min):
            raise ValueError("Lightmap grid origins must be finite")
        half_spacing = (1 << shift) * 0.5
        shifted = None
        shifted_s_min = s_min - half_spacing
        shifted_t_min = t_min - half_spacing

    padded = bytearray((width + 1) * (height + 1) * 3)
    out_width = width + 1
    out_height = height + 1
    for out_y in range(out_height):
        source_y = min(max(out_y - 0.5, 0.0), float(height - 1))
        y0 = int(math.floor(source_y))
        y1 = min(y0 + 1, height - 1)
        fy = source_y - y0
        for out_x in range(out_width):
            source_x = min(max(out_x - 0.5, 0.0), float(width - 1))
            x0 = int(math.floor(source_x))
            x1 = min(x0 + 1, width - 1)
            fx = source_x - x0
            indices = (
                (y0 * width + x0) * 3,
                (y0 * width + x1) * 3,
                (y1 * width + x0) * 3,
                (y1 * width + x1) * 3,
            )
            dst = (out_y * out_width + out_x) * 3
            for channel in range(3):
                top = rgb[indices[0] + channel] * (1.0 - fx) + rgb[indices[1] + channel] * fx
                bottom = rgb[indices[2] + channel] * (1.0 - fx) + rgb[indices[3] + channel] * fx
                value = top * (1.0 - fy) + bottom * fy
                padded[dst + channel] = max(0, min(255, int(math.floor(value + 0.5))))

    result = dict(record)
    result["width"] = out_width
    result["height"] = out_height
    result["rgb"] = bytes(padded)
    if shifted is not None:
        result["lmvecs"] = tuple(shifted)
    else:
        result["s_min"] = shifted_s_min
        result["t_min"] = shifted_t_min
    return result, True

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


def stitch_coplanar_edge_samples(
    faces,
    texinfos,
    vertices,
    edges,
    surfedges,
    planes,
    face_model_ids,
    lighting,
    lit_rgb,
    *,
    sample_spacing: int = 16,
    plane_tolerance: float = 1e-4,
    edge_tolerance: float = 0.05,
    grid_tolerance: float = 1e-4,
    endpoint_tolerance: float = 1e-5,
):
    """Reconcile matching classic luxels on shared, coplanar BSP face edges.

    This is deliberately not a blur. It touches only pairs of samples that
    occupy the same 3D point on an edge used by exactly two lightmapped faces.
    Both faces must belong to the same BSP model, have the same oriented plane
    and identical light-style bytes, and their 16-unit sample grids must
    actually intersect the shared edge at matching positions. Corners,
    non-coplanar edges, differently styled faces and unaligned grids are left
    unchanged.

    lighting and lit_rgb are mutable BSP29 mono and QLIT sample buffers.
    The RGB average is written to both faces; the mono fallback is rebuilt
    from that averaged RGB value. Returns counts useful for diagnostics/tests.
    """
    spacing = int(sample_spacing)
    if spacing <= 0:
        raise ValueError("Classic lightmap sample spacing must be positive.")
    if len(face_model_ids) != len(faces):
        raise ValueError("Face model IDs must contain one entry per BSP face.")
    if len(lit_rgb) < len(lighting) * 3:
        raise ValueError("RGB lightmap buffer is shorter than the classic lighting buffer.")

    def _oriented_plane(face):
        plane_id = int(face[0])
        if plane_id < 0 or plane_id >= len(planes):
            return None
        plane = planes[plane_id]
        if len(plane) < 4:
            return None
        sign = -1.0 if int(face[1]) else 1.0
        normal = [float(plane[i]) * sign for i in range(3)]
        distance = float(plane[3]) * sign
        length = math.sqrt(sum(value * value for value in normal))
        if not math.isfinite(length) or length <= 1e-12:
            return None
        return tuple(value / length for value in normal), distance / length

    def _project(point, axis):
        return (
            float(point[0]) * float(axis[0])
            + float(point[1]) * float(axis[1])
            + float(point[2]) * float(axis[2])
            + float(axis[3])
        )

    grids = {}
    edge_users = {}
    for face_id, face in enumerate(faces):
        light_offset = int(face[9])
        styles = tuple(int(value) for value in face[5:9])
        active_styles = tuple(value for value in styles if value != 255)
        texinfo_id = int(face[4])
        if light_offset < 0 or not active_styles:
            continue
        if texinfo_id < 0 or texinfo_id >= len(texinfos):
            continue
        if len(texinfos[texinfo_id]) < 8:
            continue
        first_edge, edge_count = int(face[2]), int(face[3])
        if (
            first_edge < 0 or edge_count < 3
            or first_edge + edge_count > len(surfedges)
        ):
            continue
        edge_ids = []
        points = []
        valid = True
        for signed_edge in surfedges[first_edge:first_edge + edge_count]:
            edge_id = abs(int(signed_edge))
            if edge_id >= len(edges):
                valid = False
                break
            edge = edges[edge_id]
            vertex_id = int(edge[0] if signed_edge >= 0 else edge[1])
            if vertex_id < 0 or vertex_id >= len(vertices):
                valid = False
                break
            edge_ids.append(edge_id)
            points.append(vertices[vertex_id])
        if not valid or len(points) < 3:
            continue
        texinfo = texinfos[texinfo_id]
        s_values = [_project(point, texinfo[0:4]) for point in points]
        t_values = [_project(point, texinfo[4:8]) for point in points]
        if not all(math.isfinite(value) for value in (*s_values, *t_values)):
            continue
        s_min = math.floor(min(s_values) / spacing + 1e-7) * spacing
        t_min = math.floor(min(t_values) / spacing + 1e-7) * spacing
        s_max = math.ceil(max(s_values) / spacing - 1e-7) * spacing
        t_max = math.ceil(max(t_values) / spacing - 1e-7) * spacing
        width = (s_max - s_min) // spacing + 1
        height = (t_max - t_min) // spacing + 1
        if width < 1 or height < 1:
            continue
        block_size = width * height
        if light_offset + block_size * len(active_styles) > min(
            len(lighting), len(lit_rgb) // 3
        ):
            continue
        plane = _oriented_plane(face)
        if plane is None:
            continue
        grid = {
            "face_id": face_id,
            "styles": styles,
            "active_styles": active_styles,
            "light_offset": light_offset,
            "width": width,
            "height": height,
            "s_min": float(s_min),
            "t_min": float(t_min),
            "texinfo": texinfo,
            "plane": plane,
            "model_id": int(face_model_ids[face_id]),
            "edges": set(edge_ids),
        }
        grids[face_id] = grid
        for edge_id in grid["edges"]:
            edge_users.setdefault(edge_id, []).append(face_id)

    considered = 0
    matched = 0
    changed = 0
    for edge_id, face_ids in edge_users.items():
        if len(face_ids) != 2:
            continue
        grid_a, grid_b = (grids[face_id] for face_id in face_ids)
        if grid_a["model_id"] != grid_b["model_id"]:
            continue
        if grid_a["styles"] != grid_b["styles"]:
            continue
        normal_a, distance_a = grid_a["plane"]
        normal_b, distance_b = grid_b["plane"]
        if (
            max(abs(normal_a[i] - normal_b[i]) for i in range(3)) > plane_tolerance
            or abs(distance_a - distance_b) > plane_tolerance
        ):
            continue

        considered += 1
        edge = edges[edge_id]
        vertex_a, vertex_b = int(edge[0]), int(edge[1])
        if (
            vertex_a < 0 or vertex_a >= len(vertices)
            or vertex_b < 0 or vertex_b >= len(vertices)
        ):
            continue
        point_a = tuple(float(value) for value in vertices[vertex_a])
        point_b = tuple(float(value) for value in vertices[vertex_b])
        direction = tuple(point_b[i] - point_a[i] for i in range(3))
        length_squared = sum(value * value for value in direction)
        if length_squared <= 1e-12:
            continue
        edge_length = math.sqrt(length_squared)

        def _edge_luxels(grid):
            texinfo = grid["texinfo"]
            s0, s1 = _project(point_a, texinfo[0:4]), _project(point_b, texinfo[0:4])
            t0, t1 = _project(point_a, texinfo[4:8]), _project(point_b, texinfo[4:8])
            ds, dt = s1 - s0, t1 - t0
            found = []
            width, height = grid["width"], grid["height"]
            if abs(ds) >= abs(dt) and abs(ds) > 1e-10:
                lower = max(0, int(math.ceil(
                    (min(s0, s1) - grid["s_min"]) / spacing - grid_tolerance
                )))
                upper = min(width - 1, int(math.floor(
                    (max(s0, s1) - grid["s_min"]) / spacing + grid_tolerance
                )))
                for x in range(lower, upper + 1):
                    u = (grid["s_min"] + x * spacing - s0) / ds
                    if u <= endpoint_tolerance or u >= 1.0 - endpoint_tolerance:
                        continue
                    t = t0 + u * dt
                    y_float = (t - grid["t_min"]) / spacing
                    y = int(round(y_float))
                    if 0 <= y < height and abs(y_float - y) <= grid_tolerance:
                        found.append((u, y * width + x))
            elif abs(dt) > 1e-10:
                lower = max(0, int(math.ceil(
                    (min(t0, t1) - grid["t_min"]) / spacing - grid_tolerance
                )))
                upper = min(height - 1, int(math.floor(
                    (max(t0, t1) - grid["t_min"]) / spacing + grid_tolerance
                )))
                for y in range(lower, upper + 1):
                    u = (grid["t_min"] + y * spacing - t0) / dt
                    if u <= endpoint_tolerance or u >= 1.0 - endpoint_tolerance:
                        continue
                    s = s0 + u * ds
                    x_float = (s - grid["s_min"]) / spacing
                    x = int(round(x_float))
                    if 0 <= x < width and abs(x_float - x) <= grid_tolerance:
                        found.append((u, y * width + x))
            return sorted(found)

        samples_a = _edge_luxels(grid_a)
        samples_b = _edge_luxels(grid_b)
        if not samples_a or not samples_b:
            continue
        used_b = set()
        for u_a, index_a in samples_a:
            best_index = None
            best_delta = float("inf")
            for u_b, index_b in samples_b:
                if index_b in used_b:
                    continue
                delta = abs(u_a - u_b) * edge_length
                if delta < best_delta:
                    best_delta = delta
                    best_index = index_b
            if best_index is None or best_delta > edge_tolerance:
                continue
            used_b.add(best_index)
            matched += 1
            offset_a = grid_a["light_offset"] + index_a
            offset_b = grid_b["light_offset"] + best_index
            rgb_a = offset_a * 3
            rgb_b = offset_b * 3
            average = tuple(
                max(0, min(255, int(round(
                    (int(lit_rgb[rgb_a + channel]) + int(lit_rgb[rgb_b + channel])) * 0.5
                ))))
                for channel in range(3)
            )
            if (
                tuple(lit_rgb[rgb_a:rgb_a + 3]) == average
                and tuple(lit_rgb[rgb_b:rgb_b + 3]) == average
            ):
                continue
            lit_rgb[rgb_a:rgb_a + 3] = bytes(average)
            lit_rgb[rgb_b:rgb_b + 3] = bytes(average)
            luminance = max(0, min(255, int(round(
                0.2126 * average[0] + 0.7152 * average[1] + 0.0722 * average[2]
            ))))
            lighting[offset_a] = luminance
            lighting[offset_b] = luminance
            changed += 1

    return {
        "shared_coplanar_edges": considered,
        "matched_sample_pairs": matched,
        "changed_sample_pairs": changed,
    }


def world_plane_frame(plane, side: int = 0):
    """Return a deterministic world-anchored 2D basis for a BSP plane."""
    if len(plane) < 4:
        raise ValueError("A BSP plane requires a normal and distance.")
    sign = -1.0 if int(side) else 1.0
    normal = [float(plane[i]) * sign for i in range(3)]
    distance = float(plane[3]) * sign
    length = math.sqrt(sum(value * value for value in normal))
    if not math.isfinite(length) or length <= 1e-12 or not math.isfinite(distance):
        raise ValueError("BSP plane normal and distance must be finite and non-zero.")
    normal = [value / length for value in normal]
    distance /= length
    major = max(range(3), key=lambda index: (abs(normal[index]), -index))
    if normal[major] < 0.0:
        normal = [-value for value in normal]
        distance = -distance
    reference_axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    projected = []
    for axis_index, reference in enumerate(reference_axes):
        dot = sum(normal[i] * reference[i] for i in range(3))
        tangent = tuple(reference[i] - normal[i] * dot for i in range(3))
        projected.append((sum(value * value for value in tangent), -axis_index, tangent))
    tangent_length_sq, _order, tangent = max(projected, key=lambda item: (item[0], item[1]))
    if tangent_length_sq <= 1e-12:
        raise ValueError("Could not construct a stable tangent basis for the BSP plane.")
    inverse_length = 1.0 / math.sqrt(tangent_length_sq)
    axis_s = tuple(value * inverse_length for value in tangent)
    axis_t = (
        normal[1] * axis_s[2] - normal[2] * axis_s[1],
        normal[2] * axis_s[0] - normal[0] * axis_s[2],
        normal[0] * axis_s[1] - normal[1] * axis_s[0],
    )
    return {
        "normal": tuple(normal), "distance": distance,
        "axis_s": axis_s, "axis_t": axis_t,
    }


def build_coplanar_face_charts(
    face_records, faces, planes, edges, surfedges, face_model_ids,
    *, sample_spacing: int = 16, plane_tolerance: float = 1e-4,
):
    """Group adjacent classic lightmapped faces into shared world-space charts.

    face_records must provide face_id and polygon positions. Components join
    only across a shared BSP edge when model ownership, oriented plane and all
    four classic style bytes match. Chart origins are snapped to one global
    world-space sample lattice instead of each face's texinfo origin.
    """
    spacing = int(sample_spacing)
    if spacing <= 0:
        raise ValueError("World chart sample spacing must be positive.")
    if len(face_model_ids) != len(faces):
        raise ValueError("Face model IDs must contain one entry per BSP face.")
    records_by_face, keys, frames, edge_users = {}, {}, {}, {}
    for record in face_records:
        face_id = int(record.get("face_id", -1))
        if face_id < 0 or face_id >= len(faces):
            continue
        face = faces[face_id]
        first_edge, edge_count = int(face[2]), int(face[3])
        plane_id = int(face[0])
        if (first_edge < 0 or edge_count < 3 or first_edge + edge_count > len(surfedges)
                or plane_id < 0 or plane_id >= len(planes)):
            continue
        try:
            frame = world_plane_frame(planes[plane_id], int(face[1]))
        except ValueError:
            continue
        plane_key = tuple(round(value / plane_tolerance) for value in (
            *frame["normal"], frame["distance"]
        ))
        keys[face_id] = (
            int(face_model_ids[face_id]), tuple(int(value) for value in face[5:9]), plane_key
        )
        positions = tuple(tuple(float(value) for value in point) for point in record.get("positions", ()))
        if len(positions) < 3:
            continue
        edge_ids, valid = set(), True
        for signed_edge in surfedges[first_edge:first_edge + edge_count]:
            edge_id = abs(int(signed_edge))
            if edge_id >= len(edges):
                valid = False
                break
            edge_ids.add(edge_id)
        if not valid:
            keys.pop(face_id, None)
            continue
        records_by_face[face_id] = dict(record)
        records_by_face[face_id]["positions"] = positions
        frames[face_id] = frame
        for edge_id in edge_ids:
            edge_users.setdefault(edge_id, []).append(face_id)

    parent = {face_id: face_id for face_id in records_by_face}

    def find(face_id):
        while parent[face_id] != face_id:
            parent[face_id] = parent[parent[face_id]]
            face_id = parent[face_id]
        return face_id

    for users in edge_users.values():
        if len(users) == 2 and keys[users[0]] == keys[users[1]]:
            root_a, root_b = find(users[0]), find(users[1])
            if root_a != root_b:
                parent[max(root_a, root_b)] = min(root_a, root_b)

    components = {}
    for face_id in records_by_face:
        components.setdefault(find(face_id), []).append(face_id)

    charts, face_to_chart = [], {}
    for chart_index, root in enumerate(sorted(components)):
        face_ids = sorted(components[root])
        frame = frames[face_ids[0]]
        projected = [
            (sum(point[i] * frame["axis_s"][i] for i in range(3)),
             sum(point[i] * frame["axis_t"][i] for i in range(3)))
            for face_id in face_ids for point in records_by_face[face_id]["positions"]
        ]
        s_min = math.floor(min(point[0] for point in projected) / spacing + 1e-7) * spacing
        t_min = math.floor(min(point[1] for point in projected) / spacing + 1e-7) * spacing
        s_max = math.ceil(max(point[0] for point in projected) / spacing - 1e-7) * spacing
        t_max = math.ceil(max(point[1] for point in projected) / spacing - 1e-7) * spacing
        chart_id = len(faces) + chart_index
        chart = {
            "chart_id": chart_id, "face_ids": tuple(face_ids),
            "model_id": int(face_model_ids[face_ids[0]]),
            "styles": tuple(int(value) for value in faces[face_ids[0]][5:9]),
            "normal": frame["normal"], "distance": frame["distance"],
            "axis_s": frame["axis_s"], "axis_t": frame["axis_t"],
            "s_min": float(s_min), "t_min": float(t_min),
            "width": int((s_max - s_min) // spacing + 1),
            "height": int((t_max - t_min) // spacing + 1),
        }
        charts.append(chart)
        for face_id in face_ids:
            face_to_chart[face_id] = chart_id
    return charts, face_to_chart, records_by_face


def point_in_polygon_2d(point, polygon, tolerance: float = 1e-7) -> bool:
    """Return True for points inside or on the boundary of a 2D polygon."""
    px, py = float(point[0]), float(point[1])
    vertices = tuple((float(p[0]), float(p[1])) for p in polygon)
    if len(vertices) < 3:
        return False
    inside = False
    for index, first in enumerate(vertices):
        second = vertices[(index + 1) % len(vertices)]
        dx, dy = second[0] - first[0], second[1] - first[1]
        length_sq = dx * dx + dy * dy
        if length_sq > 1e-20:
            projection = max(0.0, min(1.0, ((px - first[0]) * dx + (py - first[1]) * dy) / length_sq))
            nearest_x = first[0] + projection * dx
            nearest_y = first[1] + projection * dy
            if math.hypot(px - nearest_x, py - nearest_y) <= tolerance:
                return True
        if (first[1] > py) != (second[1] > py):
            crossing_x = first[0] + (py - first[1]) * dx / (second[1] - first[1])
            if px < crossing_x:
                inside = not inside
    return inside


def bilinear_sample_rgb_grid(samples, width: int, height: int, x: float, y: float):
    """Bilinearly sample a row-major RGB luxel grid, clamping to its edge."""
    w, h = int(width), int(height)
    if w <= 0 or h <= 0 or len(samples) != w * h:
        raise ValueError("RGB luxel grid dimensions do not match its samples.")
    if not math.isfinite(float(x)) or not math.isfinite(float(y)):
        raise ValueError("RGB luxel grid coordinates must be finite.")
    x = min(max(float(x), 0.0), w - 1.0)
    y = min(max(float(y), 0.0), h - 1.0)
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    x1, y1 = min(w - 1, x0 + 1), min(h - 1, y0 + 1)
    fx, fy = x - x0, y - y0
    corners = (
        samples[y0 * w + x0], samples[y0 * w + x1],
        samples[y1 * w + x0], samples[y1 * w + x1],
    )
    return tuple(max(0, min(255, int(round(
        (float(corners[0][c]) * (1.0 - fx) + float(corners[1][c]) * fx) * (1.0 - fy)
        + (float(corners[2][c]) * (1.0 - fx) + float(corners[3][c]) * fx) * fy
    )))) for c in range(3))


def resample_coplanar_chart_sources(chart, face_records, *, sample_spacing: int = 16):
    """Resample per-face source lightmaps onto a shared world-space chart.

    Matching samples on a shared geometric edge contribute to one chart luxel;
    their RGB values are averaged. Empty cells are marked invalid and left to
    the caller's atlas background/gutter.
    """
    spacing = int(sample_spacing)
    width, height = int(chart["width"]), int(chart["height"])
    if spacing <= 0 or width <= 0 or height <= 0:
        raise ValueError("World chart dimensions and sample spacing must be positive.")
    count = width * height
    accum, weights = [0.0] * (count * 3), [0] * count
    axis_s, axis_t = chart["axis_s"], chart["axis_t"]
    normal, distance = chart["normal"], float(chart["distance"])
    s_min, t_min = float(chart["s_min"]), float(chart["t_min"])

    for face_id in chart["face_ids"]:
        record = face_records[face_id]
        polygon = [
            (sum(point[i] * axis_s[i] for i in range(3)),
             sum(point[i] * axis_t[i] for i in range(3)))
            for point in record["positions"]
        ]
        min_x = max(0, int(math.floor((min(p[0] for p in polygon) - s_min) / spacing)) - 1)
        max_x = min(width - 1, int(math.ceil((max(p[0] for p in polygon) - s_min) / spacing)) + 1)
        min_y = max(0, int(math.floor((min(p[1] for p in polygon) - t_min) / spacing)) - 1)
        max_y = min(height - 1, int(math.ceil((max(p[1] for p in polygon) - t_min) / spacing)) + 1)
        texinfo = record["texinfo"]
        for gy in range(min_y, max_y + 1):
            world_t = t_min + gy * spacing
            for gx in range(min_x, max_x + 1):
                world_s = s_min + gx * spacing
                if not point_in_polygon_2d((world_s, world_t), polygon):
                    continue
                point = tuple(
                    axis_s[i] * world_s + axis_t[i] * world_t + normal[i] * distance
                    for i in range(3)
                )
                source_s = sum(point[i] * texinfo[i] for i in range(3)) + float(texinfo[3])
                source_t = sum(point[i] * texinfo[i + 4] for i in range(3)) + float(texinfo[7])
                source_x = (source_s - float(record["s_min"])) / spacing
                source_y = (source_t - float(record["t_min"])) / spacing
                rgb = bilinear_sample_rgb_grid(
                    record["samples_rgb"], record["width"], record["height"],
                    source_x, source_y,
                )
                offset = (gy * width + gx) * 3
                accum[offset] += rgb[0]
                accum[offset + 1] += rgb[1]
                accum[offset + 2] += rgb[2]
                weights[gy * width + gx] += 1
    output, valid = [], bytearray(count)
    for index, weight in enumerate(weights):
        if weight:
            valid[index] = 1
            output.append(tuple(max(0, min(255, int(round(
                accum[index * 3 + channel] / weight
            )))) for channel in range(3)))
        else:
            output.append((0, 0, 0))
    return output, bytes(valid)


def world_chart_pixel_coordinates(
    world_s, world_t, atlas_x, atlas_y, chart_s_min, chart_t_min,
    gutter, lightmap_scale, resolution, image_size,
):
    """Map world-plane coordinates to the bottom-up image pixel centre."""
    block = max(1, int(lightmap_scale)) * max(1, int(resolution))
    origin_x = (int(atlas_x) + int(gutter)) * max(1, int(resolution))
    origin_y = (int(atlas_y) + int(gutter)) * max(1, int(resolution))
    luxel_s = (float(world_s) - float(chart_s_min)) / 16.0
    luxel_t = (float(world_t) - float(chart_t_min)) / 16.0
    pixel_x = origin_x + (luxel_s + 0.5) * block - 0.5
    pixel_top_y = origin_y + (luxel_t + 0.5) * block - 0.5
    return pixel_x, int(image_size) - 1.0 - pixel_top_y


def sample_rgb_from_world_chart_positions(
    pixels, image_size: int, working_resolution: int,
    atlas_x: int, atlas_y: int, gutter: int, pixels_per_luxel: int,
    positions, axis_s, axis_t, chart_s_min: float, chart_t_min: float,
) -> bytes:
    """Sample chart pixels at arbitrary Quake world positions.

    The caller supplies points already solved on the BSP face plane. They are
    projected into the chart's deterministic world-plane basis, then sampled
    at the corresponding pixel centres. This is used to write classic BSP29
    face-local luxel grids from a world-aligned Cycles chart without changing
    the face's texinfo or lightmap dimensions.
    """
    if int(image_size) <= 0 or int(working_resolution) not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Invalid image size or working resolution.")
    if min(int(atlas_x), int(atlas_y), int(gutter)) < 0 or int(pixels_per_luxel) <= 0:
        raise ValueError("Invalid world-chart atlas rectangle.")
    if len(pixels) != int(image_size) * int(image_size) * 4:
        raise ValueError("World-chart RGBA buffer dimensions do not match pixel data.")
    if len(axis_s) != 3 or len(axis_t) != 3:
        raise ValueError("World-chart basis axes must have three components.")
    coordinates = (
        float(chart_s_min), float(chart_t_min),
        *(float(value) for value in axis_s),
        *(float(value) for value in axis_t),
    )
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("World-chart projection must contain finite values.")
    output = bytearray()
    for point in positions:
        if len(point) < 3 or not all(math.isfinite(float(value)) for value in point[:3]):
            raise ValueError("World-chart sample points must be finite XYZ coordinates.")
        world_s = sum(float(point[i]) * float(axis_s[i]) for i in range(3))
        world_t = sum(float(point[i]) * float(axis_t[i]) for i in range(3))
        pixel_x, pixel_y = world_chart_pixel_coordinates(
            world_s, world_t, atlas_x, atlas_y,
            chart_s_min, chart_t_min, gutter,
            pixels_per_luxel, working_resolution, image_size,
        )
        red, green, blue, _alpha = bilinear_sample_rgba(
            pixels, int(image_size), int(image_size), pixel_x, pixel_y
        )
        output.extend(
            max(0, min(255, int(round(channel * 255.0))))
            for channel in (red, green, blue)
        )
    return bytes(output)


def world_chart_grid_positions(
    texinfo, plane_normal, plane_distance, s_coordinates, t_coordinates,
):
    """Solve a rectangular classic S/T grid into XYZ positions on a BSP face."""
    if len(texinfo) < 8:
        raise ValueError("A face texinfo requires two four-component projection axes.")
    result = []
    for t_value in t_coordinates:
        for s_value in s_coordinates:
            point = _solve_projection_plane(
                texinfo[0:3], texinfo[4:7], plane_normal,
                float(s_value) - float(texinfo[3]),
                float(t_value) - float(texinfo[7]),
                float(plane_distance),
            )
            if point is None:
                raise ValueError("Face texinfo projection is singular on its BSP plane.")
            result.append(point)
    return result


def _solve_projection_plane(s_axis, t_axis, plane_normal, s_value, t_value, plane_distance):
    """Pure-Python solve for two projection equations plus a plane equation."""
    a = tuple(float(value) for value in s_axis[:3])
    b = tuple(float(value) for value in t_axis[:3])
    c = tuple(float(value) for value in plane_normal[:3])
    cross_bc = (
        b[1] * c[2] - b[2] * c[1],
        b[2] * c[0] - b[0] * c[2],
        b[0] * c[1] - b[1] * c[0],
    )
    cross_ca = (
        c[1] * a[2] - c[2] * a[1],
        c[2] * a[0] - c[0] * a[2],
        c[0] * a[1] - c[1] * a[0],
    )
    cross_ab = (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
    determinant = sum(a[i] * cross_bc[i] for i in range(3))
    if abs(determinant) < 1e-10:
        return None
    inverse = 1.0 / determinant
    return tuple(
        (float(s_value) * cross_bc[i]
         + float(t_value) * cross_ca[i]
         + float(plane_distance) * cross_ab[i]) * inverse
        for i in range(3)
    )
