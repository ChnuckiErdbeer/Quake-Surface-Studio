"""Blender-independent navigation event helpers."""


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
