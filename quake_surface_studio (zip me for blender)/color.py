"""Colour conversions at the Quake/Blender image-buffer boundary.

Blender byte image buffers store values encoded in their assigned colour space
(e.g. sRGB). Float image buffers store scene-linear values. Quake miptex texels
are palette/display-encoded 8-bit RGB values.
"""
from __future__ import annotations


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def quake_byte_to_srgb_code(value: int) -> float:
    """Return the stored sRGB code for one Quake palette byte.

    Do not linearize this value before writing it into a Blender 8-bit image
    whose colorspace is set to sRGB: Blender's image sampling performs that
    conversion. Pre-linearizing here would double-apply the transfer function.
    """
    return max(0, min(255, int(value))) / 255.0


def linear_to_srgb(value: float) -> float:
    """Encode a scene-linear channel as an sRGB code value."""
    value = max(0.0, float(value))
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1.0 / 2.4)) - 0.055


def blender_pixel_to_quake_code(value: float, is_float_buffer: bool) -> float:
    """Convert a Blender image pixel channel to normalized Quake sRGB code.

    Byte images already contain values encoded in their image colour space;
    for normal colour textures this is sRGB and must be preserved directly.
    Float buffers contain scene-linear values and need sRGB encoding.
    """
    value = clamp01(value)
    if is_float_buffer:
        return clamp01(linear_to_srgb(value))
    return value
