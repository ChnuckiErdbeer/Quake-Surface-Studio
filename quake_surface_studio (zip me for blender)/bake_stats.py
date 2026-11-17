"""Small pure-Python helpers for presenting SLOPGATE bake timings."""

from __future__ import annotations

import math


def format_duration(seconds):
    """Format a non-negative duration for diagnostics and operator reports."""
    if seconds is None:
        return "not recorded"
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "not recorded"
    if not math.isfinite(value) or value < 0.0:
        return "not recorded"
    if value < 1.0:
        return f"{value * 1000.0:.0f} ms"
    if value < 60.0:
        return f"{value:.2f} s"
    minutes, remainder = divmod(value, 60.0)
    if minutes < 60.0:
        return f"{int(minutes)} min {remainder:.1f} s"
    hours, remainder_minutes = divmod(minutes, 60.0)
    return f"{int(hours)} h {int(remainder_minutes)} min {remainder:.1f} s"


__all__ = ["format_duration"]
