"""Small pure geometry helpers used by QSS viewport framing."""
from __future__ import annotations

import math


def bounds_from_points(points):
    """Return axis-aligned bounds and diagonal for an iterable of 3D points."""
    coordinates = []
    for point in points:
        if len(point) != 3:
            raise ValueError("Viewport points must have exactly three coordinates.")
        values = tuple(float(value) for value in point)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Viewport points must contain finite coordinates.")
        coordinates.append(values)
    if not coordinates:
        raise ValueError("Cannot frame an empty selection.")

    minimum = tuple(min(point[i] for point in coordinates) for i in range(3))
    maximum = tuple(max(point[i] for point in coordinates) for i in range(3))
    center = tuple((minimum[i] + maximum[i]) * 0.5 for i in range(3))
    diagonal = math.sqrt(sum((maximum[i] - minimum[i]) ** 2 for i in range(3)))
    return {
        "minimum": minimum,
        "maximum": maximum,
        "center": center,
        "diagonal": diagonal,
    }


def view_distance_from_bounds(bounds, scale=1.5, minimum=0.05):
    """Calculate a stable orbit distance for the selected bounds."""
    scale = float(scale)
    minimum = float(minimum)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("View-distance scale must be a positive finite number.")
    if not math.isfinite(minimum) or minimum <= 0.0:
        raise ValueError("Minimum view distance must be a positive finite number.")
    diagonal = float(bounds["diagonal"])
    if not math.isfinite(diagonal) or diagonal < 0.0:
        raise ValueError("Bounds diagonal must be a non-negative finite number.")
    return max(minimum, diagonal * scale)
