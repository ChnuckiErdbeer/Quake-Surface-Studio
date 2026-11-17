"""Map Quake first-person movement settings to Blender Walk Navigation preferences."""

from math import isfinite


def quake_walk_preferences(unit_scale, speed_quake, fast_factor):
    """Return safe Blender Walk Navigation preference values for a Quake map.

    Quake BSP units are converted into Blender metres/second using the map's
    imported unit scale. Blender's own speed limits are applied here so this
    calculation can be tested without importing bpy.
    """
    scale = float(unit_scale)
    speed = float(speed_quake)
    factor = float(fast_factor)

    if not all(isfinite(value) for value in (scale, speed, factor)):
        raise ValueError("Quake Walk settings must be finite numbers.")
    if scale <= 0.0:
        raise ValueError("Quake unit scale must be greater than zero.")

    return {
        "walk_speed": min(100.0, max(0.01, speed * scale)),
        "walk_speed_factor": min(10.0, max(1.0, factor)),
        "view_height": min(1000.0, max(0.0, 22.0 * scale)),
        "use_gravity": False,
    }
