"""Blender-independent FPS navigation math and event helpers."""

import math
from math import hypot


def is_active_timer_event(event_type, event_timer, active_timer):
    """Recognize the modal operator's timer event across Blender API variants.

    Blender 5.2 may deliver a TIMER event without exposing Event.timer. In
    that case the modal handler should process the event rather than crashing.
    """
    if event_type != "TIMER":
        return False
    if event_timer is None:
        return True
    return event_timer == active_timer


def horizontal_movement_axes(forward_x, forward_y, right_x, right_y, epsilon=1e-8):
    """Return normalized world-XY forward/right axes for viewport-relative movement.

    The horizontal right vector is forward crossed with world-up. In a
    right-handed Z-up world this is (forward_y, -forward_x), not its inverse.
    When looking almost vertically, projected camera-right supplies a stable
    heading fallback.
    """
    forward_length = hypot(float(forward_x), float(forward_y))
    if forward_length > epsilon:
        fx = float(forward_x) / forward_length
        fy = float(forward_y) / forward_length
    else:
        right_length = hypot(float(right_x), float(right_y))
        if right_length <= epsilon:
            fx, fy = 1.0, 0.0
        else:
            # Invert the screen-right vector to recover a consistent forward.
            fx = -float(right_y) / right_length
            fy = float(right_x) / right_length
    return (fx, fy), (fy, -fx)


def mouse_look_deltas(dx, dy, current_pitch, sensitivity=0.0022, pitch_limit=math.radians(89.0)):
    """Convert mouse deltas to incremental yaw/pitch, clamping only vertical pitch.

    Mouse-right turns the view to the right (negative world-Z yaw); mouse-up
    raises the view. Quaternion composition is performed by the Blender layer.
    """
    yaw_delta = -float(dx) * float(sensitivity)
    target_pitch = max(
        -float(pitch_limit),
        min(float(pitch_limit), float(current_pitch) - float(dy) * float(sensitivity)),
    )
    return yaw_delta, target_pitch - float(current_pitch)
