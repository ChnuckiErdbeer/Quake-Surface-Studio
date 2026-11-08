"""Blender-independent navigation event helpers."""

from math import hypot


def is_active_timer_event(event_type, event_timer, active_timer):
    """Recognize the modal operator's timer event across Blender API variants.

    Blender 5.2 may deliver a TIMER event without exposing Event.timer. In
    that case the modal handler is the only timer consumer in this interaction
    and should process the event rather than crashing or stalling.
    """
    if event_type != "TIMER":
        return False
    if event_timer is None:
        return True
    return event_timer == active_timer


def horizontal_movement_axes(forward_x, forward_y, right_x, right_y, epsilon=1e-8):
    """Return normalized world-XY forward/right axes for viewport-relative movement.

    The projected view-forward vector determines heading. If the view points
    almost exactly vertically, the projected camera-right vector supplies a
    stable horizontal heading instead of producing a zero vector.
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
            fx = float(right_y) / right_length
            fy = -float(right_x) / right_length
    return (fx, fy), (-fy, fx)
