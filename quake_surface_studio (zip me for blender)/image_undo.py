"""Session-local image snapshots synchronized with Blender's global undo/redo.

Blender restores mesh/material/object datablocks through its normal undo stack,
but Python writes to Image.pixels.foreach_set() are not reliably included.
Each SLOPGATE operation therefore records before/after snapshots only for the
images that operation actually changes. undo_post restores the operation's
before state; redo_post restores its after state. Unrelated Texture Paint
strokes remain under Blender's native stroke undo.

Snapshots are compressed to a temporary session directory rather than kept in
RAM or embedded in the .blend file. Blender's undo stack is session-local, so
the files are deleted when the add-on is unregistered or a .blend is loaded.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict
import os
import shutil
import tempfile
import uuid
import zlib


_HISTORY_LIMIT = 96


def _pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)


def _capture_image(image, storage_dir):
    width, height = (int(image.size[0]), int(image.size[1]))
    if width <= 0 or height <= 0:
        raise ValueError(f"Image {getattr(image, 'name', '<unnamed>')} has invalid dimensions.")
    pixels = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    if pixels.itemsize != 4:
        raise RuntimeError("SLOPGATE image history requires 32-bit float pixel buffers.")
    compressed = zlib.compress(pixels.tobytes(), level=1)
    path = os.path.join(storage_dir, uuid.uuid4().hex + ".z")
    with open(path, "wb") as handle:
        handle.write(compressed)
    return {
        "name": str(image.name),
        "width": width,
        "height": height,
        "path": path,
    }


def _restore_image(snapshot, image_lookup):
    image = image_lookup(snapshot["name"])
    if image is None:
        return False
    width, height = int(snapshot["width"]), int(snapshot["height"])
    if tuple(int(value) for value in image.size[:2]) != (width, height):
        return False
    try:
        with open(snapshot["path"], "rb") as handle:
            raw = zlib.decompress(handle.read())
    except FileNotFoundError:
        return False
    pixels = array("f")
    pixels.frombytes(raw)
    if len(pixels) != width * height * 4:
        raise ValueError(f"Stored image history for {snapshot['name']} has an invalid pixel count.")
    image.pixels.foreach_set(pixels)
    image.update()
    return True


class ImageUndoJournal:
    """Store operation deltas keyed by the state token on a Quake map object."""

    def __init__(self, history_limit=_HISTORY_LIMIT):
        self.history_limit = max(4, int(history_limit))
        self._transitions = {}
        self._order = {}
        self._owners = {}
        self._last_seen = {}
        self._bpy = None
        self._handlers = {}
        self._storage_dir = None

    def _ensure_storage(self):
        if self._storage_dir is None or not os.path.isdir(self._storage_dir):
            self._storage_dir = tempfile.mkdtemp(prefix="slopgate_undo_")
        return self._storage_dir

    def ensure_object(self, obj):
        pointer = _pointer(obj)
        uid = str(obj.get("qss_undo_uid", "") or "")
        if not uid:
            uid = uuid.uuid4().hex
            obj["qss_undo_uid"] = uid
        if "qss_undo_token" not in obj:
            obj["qss_undo_token"] = ""
        token = str(obj.get("qss_undo_token", "") or "")
        self._owners[pointer] = uid
        self._last_seen.setdefault(uid, token)
        return uid

    @staticmethod
    def _unique_images(images):
        result = {}
        for image in images or ():
            if image is None:
                continue
            name = str(getattr(image, "name", "") or "")
            if name:
                result[name] = image
        return result

    def _capture_images(self, images):
        storage_dir = self._ensure_storage()
        return {
            name: _capture_image(image, storage_dir)
            for name, image in self._unique_images(images).items()
        }

    def _delete_unreferenced_files(self):
        if not self._storage_dir or not os.path.isdir(self._storage_dir):
            return
        referenced = set()
        for transitions in self._transitions.values():
            for transition in transitions.values():
                for side in ("before", "after"):
                    referenced.update(
                        snapshot["path"] for snapshot in transition[side].values()
                    )
        for filename in os.listdir(self._storage_dir):
            path = os.path.join(self._storage_dir, filename)
            if path not in referenced:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _truncate_redo_branch(self, uid, current_token):
        order = self._order.setdefault(uid, [])
        if current_token in order:
            keep = order.index(current_token) + 1
        elif not current_token:
            keep = 0
        elif not order:
            keep = 0
        else:
            # An unknown token means the saved state predates this in-memory
            # journal; do not retain an unreachable redo branch.
            keep = 0
        removed = order[keep:]
        transitions = self._transitions.setdefault(uid, OrderedDict())
        for token in removed:
            transitions.pop(token, None)
        self._order[uid] = order[:keep]
        self._delete_unreferenced_files()

    def _trim(self, uid):
        order = self._order.setdefault(uid, [])
        transitions = self._transitions.setdefault(uid, OrderedDict())
        while len(order) > self.history_limit:
            expired = order.pop(0)
            transitions.pop(expired, None)

    def begin(self, obj, images):
        """Capture pre-edit pixels for the images this operation will modify."""
        uid = self.ensure_object(obj)
        before_token = str(obj.get("qss_undo_token", "") or "")
        self._truncate_redo_branch(uid, before_token)
        return {
            "uid": uid,
            "before_token": before_token,
            "before": self._capture_images(images),
            "finished": False,
        }

    def commit(self, obj, images, transaction):
        """Capture post-edit pixels and advance the map's undo token."""
        if transaction is None or transaction.get("finished"):
            raise ValueError("The SLOPGATE image transaction is missing or already finished.")
        uid = transaction["uid"]
        new_token = uuid.uuid4().hex
        transition = {
            "before_token": transaction["before_token"],
            "before": transaction["before"],
            "after": self._capture_images(images),
        }
        transitions = self._transitions.setdefault(uid, OrderedDict())
        transitions[new_token] = transition
        self._order.setdefault(uid, []).append(new_token)
        self._trim(uid)
        obj["qss_undo_token"] = new_token
        self._owners[_pointer(obj)] = uid
        self._last_seen[uid] = new_token
        transaction["finished"] = True
        self._delete_unreferenced_files()
        return new_token

    def rollback(self, obj, transaction, image_lookup):
        """Restore pre-edit pixels when an operation fails or is cancelled."""
        if transaction is None or transaction.get("finished"):
            return
        for snapshot in transaction["before"].values():
            _restore_image(snapshot, image_lookup)
        obj["qss_undo_token"] = transaction["before_token"]
        self._owners[_pointer(obj)] = transaction["uid"]
        self._last_seen[transaction["uid"]] = transaction["before_token"]
        transaction["finished"] = True
        self._delete_unreferenced_files()

    def _restore_transition_side(self, transition, side, image_lookup):
        for snapshot in transition[side].values():
            _restore_image(snapshot, image_lookup)

    def _reconcile(self, objects, image_lookup, *, redo):
        for obj in objects:
            try:
                if str(obj.get("qss_object_role", "")) != "quake_bsp29":
                    continue
                pointer = _pointer(obj)
                uid = self._owners.get(pointer) or str(obj.get("qss_undo_uid", "") or "")
                if not uid:
                    continue
                token = str(obj.get("qss_undo_token", "") or "")
                previous = self._last_seen.get(uid, token)
                if token == previous:
                    continue
                transitions = self._transitions.get(uid, {})
                if redo:
                    # Redo moves from the parent token to the operation token.
                    transition = transitions.get(token)
                    if transition and transition["before_token"] == previous:
                        self._restore_transition_side(transition, "after", image_lookup)
                else:
                    # Undo moves from the operation token back to its parent.
                    transition = transitions.get(previous)
                    if transition and transition["before_token"] == token:
                        self._restore_transition_side(transition, "before", image_lookup)
                self._last_seen[uid] = token
                self._owners[pointer] = uid
            except Exception as exc:
                # Never break Blender's undo/redo because an orphan image or a
                # stale generated atlas was removed by another operation.
                print(f"[SLOPGATE] image undo reconciliation warning: {exc}")
        self._delete_unreferenced_files()

    def undo(self, objects, image_lookup):
        self._reconcile(objects, image_lookup, redo=False)

    def redo(self, objects, image_lookup):
        self._reconcile(objects, image_lookup, redo=True)

    def clear(self):
        self._transitions.clear()
        self._order.clear()
        self._owners.clear()
        self._last_seen.clear()
        if self._storage_dir and os.path.isdir(self._storage_dir):
            shutil.rmtree(self._storage_dir, ignore_errors=True)
        self._storage_dir = None

    def register(self, bpy_module):
        self.unregister(bpy_module)
        self._bpy = bpy_module
        try:
            undo_steps = int(bpy_module.context.preferences.edit.undo_steps)
            self.history_limit = max(8, min(128, undo_steps + 4))
        except Exception:
            pass

        def undo_handler(*_args):
            self.undo(bpy_module.data.objects, bpy_module.data.images.get)

        def redo_handler(*_args):
            self.redo(bpy_module.data.objects, bpy_module.data.images.get)

        def reset_after_load(*_args):
            self.clear()
            for obj in bpy_module.data.objects:
                try:
                    if str(obj.get("qss_object_role", "")) == "quake_bsp29":
                        self.ensure_object(obj)
                except Exception:
                    pass

        persistent = getattr(bpy_module.app.handlers, "persistent", lambda callback: callback)
        handlers = {
            "undo_post": persistent(undo_handler),
            "redo_post": persistent(redo_handler),
            "load_post": persistent(reset_after_load),
        }
        for name, callback in handlers.items():
            handler_list = getattr(bpy_module.app.handlers, name, None)
            if handler_list is not None and callback not in handler_list:
                handler_list.append(callback)
        self._handlers = handlers
        # Do not enumerate bpy.data.objects during add-on registration. Blender
        # exposes a restricted _RestrictData proxy in this phase; object access
        # is safe from load_post and from normal operator/undo callbacks.

    def unregister(self, bpy_module=None):
        target = bpy_module or self._bpy
        if target is not None:
            for name, callback in tuple(self._handlers.items()):
                handler_list = getattr(target.app.handlers, name, None)
                if handler_list is not None and callback in handler_list:
                    handler_list.remove(callback)
        self._handlers.clear()
        self._bpy = None
        self.clear()


_JOURNAL = ImageUndoJournal()


def ensure_object(obj):
    return _JOURNAL.ensure_object(obj)


def begin(obj, images):
    return _JOURNAL.begin(obj, images)


def commit(obj, images, transaction):
    return _JOURNAL.commit(obj, images, transaction)


def rollback(obj, transaction, image_lookup):
    return _JOURNAL.rollback(obj, transaction, image_lookup)


def register(bpy_module):
    return _JOURNAL.register(bpy_module)


def unregister(bpy_module=None):
    return _JOURNAL.unregister(bpy_module)


__all__ = [
    "ImageUndoJournal",
    "begin",
    "commit",
    "ensure_object",
    "register",
    "rollback",
    "unregister",
]
