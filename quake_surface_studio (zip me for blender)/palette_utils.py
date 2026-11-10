"""Pure helpers for the Quake palette paint and conversion workflows."""
from __future__ import annotations

import math
from typing import Iterable


def palette_to_jasc_text(palette: bytes | bytearray | memoryview) -> str:
    """Serialize the 768-byte Quake RGB palette as a strict 256-entry JASC-PAL."""
    raw = bytes(palette)
    if len(raw) != 256 * 3:
        raise ValueError(f"Quake palette must contain 768 RGB bytes; received {len(raw)}.")
    lines = ["JASC-PAL", "0100", "256"]
    lines.extend(
        f"{raw[index]:d} {raw[index + 1]:d} {raw[index + 2]:d}"
        for index in range(0, len(raw), 3)
    )
    return "\n".join(lines) + "\n"


def quake_dimension(span: float, maximum: int = 512) -> int:
    """Return the smallest multiple-of-eight texture dimension covering span."""
    value = float(span)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Texture span must be finite and nonnegative.")
    upper = max(8, (int(maximum) // 8) * 8)
    requested = max(8, int(math.ceil(max(1.0, value))))
    return min(upper, ((requested + 7) // 8) * 8)


def estimate_face_local_paint_bytes(
    spans: Iterable[tuple[float, float]],
    *,
    bytes_per_face_pixel: int = 4,
    atlas_size: int = 512,
    bytes_per_atlas_pixel: int = 16,
) -> dict[str, int]:
    """Estimate peak pixel-buffer allocation while detaching selected faces.

    This includes all temporary face-local image buffers plus the shared
    512-style float atlas allocated for multi-face paint. It deliberately does
    not pretend to estimate Blender's material datablocks, undo history,
    GPU copies, or other process overhead.
    """
    span_list = [(float(width), float(height)) for width, height in spans]
    if bytes_per_face_pixel not in (4, 16):
        raise ValueError("Face image buffer size must be 4 (byte) or 16 (float) bytes per pixel.")
    if int(atlas_size) < 8 or int(bytes_per_atlas_pixel) not in (4, 16):
        raise ValueError("Invalid detached-atlas dimensions or pixel size.")
    face_bytes = 0
    for width_span, height_span in span_list:
        width = quake_dimension(width_span)
        height = quake_dimension(height_span)
        face_bytes += width * height * int(bytes_per_face_pixel)
    atlas_bytes = (
        int(atlas_size) * int(atlas_size) * int(bytes_per_atlas_pixel)
        if len(span_list) > 1 else 0
    )
    return {
        "face_count": len(span_list),
        "face_image_bytes": face_bytes,
        "atlas_bytes": atlas_bytes,
        "peak_pixel_bytes": face_bytes + atlas_bytes,
    }


def format_mib(byte_count: int) -> str:
    """Format a nonnegative byte count as MiB with one decimal place."""
    return f"{max(0, int(byte_count)) / (1024.0 * 1024.0):.1f} MiB"
