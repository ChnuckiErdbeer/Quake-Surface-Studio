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



def next_selected_face_index(selected_indices, active_index=None, previous_index=None, direction=1):
    """Choose the active/first selected face, then cycle deterministically."""
    indices = tuple(sorted({int(index) for index in selected_indices}))
    if not indices:
        raise ValueError("At least one selected face is required.")
    if previous_index in indices:
        position = indices.index(int(previous_index))
        step = 1 if int(direction) >= 0 else -1
        return indices[(position + step) % len(indices)]
    if active_index in indices:
        return int(active_index)
    return indices[0]


def face_focus_distance(half_width, half_height, aspect, radius, unit_scale,
                        fov_degrees=45.0, margin=1.4):
    """Fit a face's projected bounding box in a perspective viewport with margin."""
    values = tuple(float(value) for value in (
        half_width, half_height, aspect, radius, unit_scale, fov_degrees, margin
    ))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Face-focus dimensions must be finite.")
    half_width, half_height, aspect, radius, unit_scale, fov_degrees, margin = values
    if half_width < 0.0 or half_height < 0.0 or radius < 0.0:
        raise ValueError("Face-focus extents and radius cannot be negative.")
    if aspect <= 0.0 or unit_scale <= 0.0:
        raise ValueError("Viewport aspect and Quake unit scale must be positive.")
    if not 10.0 <= fov_degrees <= 100.0 or margin < 1.0:
        raise ValueError("Face-focus FOV must be 10–100 degrees and margin at least 1.")
    tangent = math.tan(math.radians(fov_degrees) * 0.5)
    fit_height = half_height / tangent
    fit_width = half_width / (tangent * aspect)
    return max(0.25, unit_scale * 4.0, radius * 2.9,
               max(fit_height, fit_width) * margin)



def face_normal_toward_view(normal, camera_side):
    """Orient a face normal toward the side occupied by the current viewport."""
    normal = tuple(float(value) for value in normal)
    camera_side = tuple(float(value) for value in camera_side)
    if len(normal) != 3 or len(camera_side) != 3:
        raise ValueError("Face normal and camera side must be three-dimensional.")
    if not all(math.isfinite(value) for value in normal + camera_side):
        raise ValueError("Face normal and camera side must be finite.")
    dot = sum(a * b for a, b in zip(normal, camera_side))
    return tuple(-value for value in normal) if dot < 0.0 else normal


def viewport_lens_from_fov(fov_degrees, sensor_width=32.0):
    """Convert horizontal viewport FOV to Blender's SpaceView3D focal length."""
    fov = float(fov_degrees)
    sensor = float(sensor_width)
    if not math.isfinite(fov) or not 10.0 <= fov <= 150.0:
        raise ValueError("Viewport FOV must be between 10 and 150 degrees.")
    if not math.isfinite(sensor) or sensor <= 0.0:
        raise ValueError("Viewport sensor width must be a positive finite number.")
    return sensor / (2.0 * math.tan(math.radians(fov) * 0.5))
