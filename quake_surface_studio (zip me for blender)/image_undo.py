"""In-memory image-pixel journal synchronized with Blender's global undo/redo.

Blender's operator undo stores mesh/material/object state, but Python writes to
Image.pixels.foreach_set() are not consistently part of that state. SLOPGATE
operators register the pixel state before and after a single logical edit.
Blender's undo_post/redo_post handlers restore the matching image state when
the object's journal token changes. Texture Paint strokes remain native
Blender operations and do not change the token.

The journal is session-local by design: Blender's undo stack itself is not
persisted across file reloads.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict
import uuid
import zlib


_HISTORY_LIMIT = 96


def _pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)


def _capture_image(image):
    width, height = (int(image.size[0]), int(image.size[1]))
    if width <= 0 or height <= 0:
        raise ValueError(f"Image {getattr(image, 'name', '<unnamed>')} has invalid dimensions.")
    pixels = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    if pixels.itemsize != 4:
        raise RuntimeError("SLOPGATE image history requires 32-bit float pixel buffers.")
    return {
        "name": str(image.name),
        "width": width,
        "height": height,
        "pixels": zlib.compress(pixels.tobytes(), level=1),
    }


def _restore_image(snapshot, image_lookup):
    image = image_lookup(snapshot["name"])
    if image is None:
        return False
    width, height = int(snapshot["width"]), int(snapshot["height"])
    if tuple(int(value) for value in image.size[:2]) != (width, height):
        return False
    raw = zlib.decompress(snapshot["pixels"])
    pixels = array("f")
    pixels.frombytes(raw)
    if len(pixels) != width * height * 4:
        raise ValueError(f"Stored image history for {snapshot['name']} has an invalid pixel count.")
    image.pixels.foreach_set(pixels)
    image.update()
    return True


class ImageUndoJournal:
    """Keep bounded image snapshots keyed by a Blender-undoable object token."""

    def __init__(self, history_limit=_HISTORY_LIMIT):
        self.history_limit = max(4, int(history_limit))
        self._states = {}
        self._owners = {}
        self._last_seen = {}
        self._image_refs = {}
        self._bpy = None
        self._handlers = {}

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
        result = {}
        for name, image in self._unique_images(images).items():
            result[name] = _capture_image(image)
            self._image_refs[name] = image
        return result

    def _resolve_image(self, name):
        if self._bpy is not None:
            try:
                image = self._bpy.data.images.get(name)
                if image is not None:
                    self._image_refs[name] = image
                    return image
            except Exception:
                pass
        return self._image_refs.get(name)

    def _truncate_redo_branch(self, states, current_token):
        keys = list(states.keys())
        if current_token in keys:
            index = keys.index(current_token)
            for token in keys[index + 1:]:
                states.pop(token, None)

    def _trim(self, states):
        while len(states) > self.history_limit:
            states.popitem(last=False)

    def begin(self, obj, images):
        """Capture pre-edit pixels and return a transaction handle."""
        uid = self.ensure_object(obj)
        token = str(obj.get("qss_undo_token", "") or "")
        before = self._capture_images(images)
        states = self._states.setdefault(uid, OrderedDict())
        self._truncate_redo_branch(states, token)
        # Native Texture Paint can change an image without changing the
        # SLOPGATE token. Refresh every image already tracked at this state
        # before adding the current operation's own images, so a later undo
        # never rewinds unrelated paint strokes on another atlas/image.
        merged = dict(states.get(token, {}))
        for image_name in tuple(merged):
            image = self._resolve_image(image_name)
            if image is not None:
                try:
                    merged[image_name] = _capture_image(image)
                except Exception as exc:
                    print(f"[SLOPGATE] could not refresh undo image {image_name}: {exc}")
        merged.update(before)
        states[token] = merged
        states.move_to_end(token)
        self._last_seen[uid] = token
        return {
            "uid": uid,
            "before_token": token,
            "before": before,
            "finished": False,
        }

    def commit(self, obj, images, transaction):
        """Record post-edit pixels and advance the undoable state token."""
        if transaction is None or transaction.get("finished"):
            raise ValueError("The SLOPGATE image transaction is missing or already finished.")
        uid = transaction["uid"]
        before_token = transaction["before_token"]
        states = self._states.setdefault(uid, OrderedDict())
        state = dict(states.get(before_token, {}))
        state.update(self._capture_images(images))
        new_token = uuid.uuid4().hex
        states[new_token] = state
        self._trim(states)
        obj["qss_undo_token"] = new_token
        self._owners[_pointer(obj)] = uid
        self._last_seen[uid] = new_token
        transaction["finished"] = True
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

    def reconcile(self, objects, image_lookup):
        """Apply snapshots only when a global undo/redo changed a map token."""
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
                state = self._states.get(uid, {}).get(token)
                if state:
                    for snapshot in state.values():
                        _restore_image(snapshot, image_lookup)
                self._last_seen[uid] = token
                self._owners[pointer] = uid
            except Exception as exc:
                # Never break Blender's undo/redo because an orphan image was
                # removed or a generated atlas changed size in another edit.
                print(f"[SLOPGATE] image undo reconciliation warning: {exc}")

    def clear(self):
        self._states.clear()
        self._owners.clear()
        self._last_seen.clear()
        self._image_refs.clear()

    def register(self, bpy_module):
        self.unregister(bpy_module)
        self._bpy = bpy_module

        def reconcile(*_args):
            self.reconcile(bpy_module.data.objects, bpy_module.data.images.get)

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
            "undo_post": persistent(reconcile),
            "redo_post": persistent(reconcile),
            "load_post": persistent(reset_after_load),
        }
        for name, callback in handlers.items():
            handler_list = getattr(bpy_module.app.handlers, name, None)
            if handler_list is not None and callback not in handler_list:
                handler_list.append(callback)
        self._handlers = handlers
        for obj in bpy_module.data.objects:
            try:
                if str(obj.get("qss_object_role", "")) == "quake_bsp29":
                    self.ensure_object(obj)
            except Exception:
                pass

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
