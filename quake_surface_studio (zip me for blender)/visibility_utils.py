"""Pure helpers for reversible Quake BSP face-isolation state.

The serialized snapshot is stored on the imported BSP object so a user's
visibility state survives saving/reopening a .blend file.
"""
from __future__ import annotations

import json


def _indices(values, count, label):
    result = []
    seen = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must contain integer indices.")
        if value < 0 or value >= count:
            raise ValueError(f"{label} index {value} is outside 0..{count - 1}.")
        if value in seen:
            raise ValueError(f"{label} contains duplicate index {value}.")
        seen.add(value)
        result.append(value)
    return sorted(result)


def encode_face_visibility_snapshot(
    vertex_count,
    edge_count,
    face_count,
    hidden_face_indices,
    selected_face_indices,
):
    """Validate and encode the pre-isolation face state as a JSON string."""
    counts = (vertex_count, edge_count, face_count)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in counts):
        raise ValueError("Mesh element counts must be non-negative integers.")

    hidden = _indices(hidden_face_indices, face_count, "Hidden faces")
    selected = _indices(selected_face_indices, face_count, "Selected faces")
    if set(hidden).intersection(selected):
        raise ValueError("A face cannot be both hidden and selected in the snapshot.")
    if not selected:
        raise ValueError("Select at least one visible face before isolating.")

    payload = {
        "version": 1,
        "vertex_count": vertex_count,
        "edge_count": edge_count,
        "face_count": face_count,
        "hidden_faces": hidden,
        "selected_faces": selected,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def decode_face_visibility_snapshot(payload, vertex_count, edge_count, face_count):
    """Decode a snapshot, rejecting corrupt or topology-stale state."""
    if not isinstance(payload, str) or not payload:
        raise ValueError("No QSS face-isolation snapshot is stored.")
    try:
        state = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("The stored QSS face-isolation snapshot is invalid.") from exc
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("The stored QSS face-isolation snapshot has an unsupported version.")

    expected = (vertex_count, edge_count, face_count)
    stored = (
        state.get("vertex_count"),
        state.get("edge_count"),
        state.get("face_count"),
    )
    if stored != expected:
        raise ValueError(
            "The BSP mesh topology changed while faces were isolated "
            f"(stored V/E/F={stored}, current V/E/F={expected})."
        )

    hidden = _indices(state.get("hidden_faces", ()), face_count, "Hidden faces")
    selected = _indices(state.get("selected_faces", ()), face_count, "Selected faces")
    if set(hidden).intersection(selected):
        raise ValueError("The stored isolation state marks a face as both hidden and selected.")
    if not selected:
        raise ValueError("The stored isolation state contains no selected faces.")
    return frozenset(hidden), frozenset(selected)


def snapshot_is_active(payload):
    """Return whether an object currently has a non-empty QSS isolation state."""
    return isinstance(payload, str) and bool(payload)
