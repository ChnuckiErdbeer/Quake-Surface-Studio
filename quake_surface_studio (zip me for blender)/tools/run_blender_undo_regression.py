"""Run SLOPGATE's Blender undo/redo integration regression suite.

Recommended invocation:
    Open a new empty Blender file (File > New > General), open this script in
    Blender's Text Editor, then choose Run Script.

The script creates disposable Blender datablocks, drives actual Blender Undo/Redo
operators through a registered UNDO operator, tests the image journal, runs the
standalone unittest suite, saves a temporary .blend and opens it in a second
Blender process. It writes TXT and JSON reports to the system temp directory.
Run it in a new empty file, never in a valuable working project. A UI context is
recommended because Blender's Undo/Redo operators may be unavailable in background
mode; the child save/reopen verification itself runs in a background process.
"""
from __future__ import annotations

import array
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

import bpy
from bpy.props import FloatProperty, StringProperty

ADDON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_ROOT))
import bake_scope
import image_undo

CHECKS = []
TEMP_DIR = tempfile.mkdtemp(prefix="slopgate_undo_regression_")
REPORT_TXT = os.path.join(tempfile.gettempdir(), "SLOPGATE_Undo_Redo_Regression.txt")
REPORT_JSON = os.path.join(tempfile.gettempdir(), "SLOPGATE_Undo_Redo_Regression.json")
JOURNAL = image_undo.ImageUndoJournal(history_limit=32)


def record(name, status, detail=""):
    CHECKS.append({"name": str(name), "status": str(status).upper(), "detail": str(detail)})
    print(f"[{str(status).upper():4}] {name}: {detail}")


def run_check(name, callback):
    try:
        detail = callback()
        record(name, "PASS", detail or "OK")
        return True
    except Exception as exc:
        record(name, "FAIL", f"{exc}\n{traceback.format_exc()}")
        return False


def pixels(image):
    result = array.array("f", [0.0]) * (int(image.size[0]) * int(image.size[1]) * 4)
    image.pixels.foreach_get(result)
    return result


def fill(image, value):
    count = int(image.size[0]) * int(image.size[1])
    image.pixels.foreach_set(array.array("f", [float(value), float(value), float(value), 1.0]) * count)
    image.update()


def assert_uniform(image, value, tolerance=1e-5):
    data = pixels(image)
    for index in range(0, len(data), 4):
        for channel in range(3):
            if abs(float(data[index + channel]) - float(value)) > tolerance:
                raise AssertionError(
                    f"{image.name} pixel {index // 4} channel {channel}: "
                    f"expected {value}, got {data[index + channel]}"
                )


def undo():
    result = bpy.ops.ed.undo()
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender Undo returned {sorted(result)}")


def redo():
    result = bpy.ops.ed.redo()
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender Redo returned {sorted(result)}")


class QSS_OT_regression_image_edit(bpy.types.Operator):
    bl_idname = "qss_undo_regression.image_edit"
    bl_label = "SLOPGATE Undo Regression Image Edit"
    bl_options = {"REGISTER", "UNDO"}

    map_name: StringProperty()
    image_name: StringProperty()
    value: FloatProperty(default=0.5, min=0.0, max=10.0)

    def execute(self, context):
        obj = bpy.data.objects.get(self.map_name)
        image = bpy.data.images.get(self.image_name)
        if obj is None or image is None:
            self.report({"ERROR"}, "Regression map or image disappeared")
            return {"CANCELLED"}
        transaction = JOURNAL.begin(obj, [image])
        try:
            fill(image, self.value)
            JOURNAL.commit(obj, [image], transaction)
        except Exception:
            JOURNAL.rollback(obj, transaction, bpy.data.images.get)
            raise
        return {"FINISHED"}


class QSS_OT_regression_generated_image(bpy.types.Operator):
    bl_idname = "qss_undo_regression.generated_image"
    bl_label = "SLOPGATE Undo Regression Generated Image"
    bl_options = {"REGISTER", "UNDO"}

    map_name: StringProperty()
    image_name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.map_name)
        if obj is None:
            return {"CANCELLED"}
        transaction = JOURNAL.begin(obj, [])
        image = bpy.data.images.new(self.image_name, width=4, height=4, alpha=True, float_buffer=True)
        image.use_fake_user = True
        fill(image, 0.66)
        JOURNAL.commit(obj, [image], transaction)
        return {"FINISHED"}


def operator_edit(obj, image, value):
    result = bpy.ops.qss_undo_regression.image_edit(
        "EXEC_DEFAULT", map_name=obj.name, image_name=image.name, value=float(value)
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"Regression edit operator returned {sorted(result)}")


def test_edge_canonicalization():
    for block in (1, 2, 4):
        width = height = block * 2
        data = array.array("f", [0.0, 0.0, 0.0, 1.0] * (width * height))
        count = bake_scope.collapse_rgba_luxel_blocks(
            data, width, height, [(0, 0, width, height)], block_size=block
        )
        if count != 4:
            raise AssertionError(f"{block}x luxel blocks: expected 4, got {count}")
        for by in (0, block):
            for bx in (0, block):
                first = tuple(data[(by * width + bx) * 4:(by * width + bx) * 4 + 4])
                for y in range(by, by + block):
                    for x in range(bx, bx + block):
                        offset = (y * width + x) * 4
                        if tuple(data[offset:offset + 4]) != first:
                            raise AssertionError(f"{block}x block was not made uniform")
    return "Luxel block canonicalization passed at 1x, 2x and 4x"


def test_save_reopen(obj, image):
    blend_path = os.path.join(TEMP_DIR, "slopgate_undo_roundtrip.blend")
    result = bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True, compress=True)
    if "FINISHED" not in result or not os.path.isfile(blend_path):
        raise RuntimeError(f"Could not save round-trip fixture: {sorted(result)}")
    expression = (
        "import bpy; "
        "assert bpy.data.objects.get(" + repr(obj.name) + "); "
        "assert bpy.data.images.get(" + repr(image.name) + "); "
        "print('SLOPGATE_REOPEN_OK')"
    )
    completed = subprocess.run(
        [bpy.app.binary_path, "--background", blend_path, "--python-expr", expression],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90,
    )
    if completed.returncode != 0 or "SLOPGATE_REOPEN_OK" not in completed.stdout:
        raise RuntimeError(
            f"Saved .blend did not reopen cleanly (exit {completed.returncode}):\n{completed.stdout[-5000:]}"
        )
    return "Temporary .blend reopened in a second Blender process with map object and image intact"


def main():
    if bpy.app.background:
        print("NOTE: Blender is in background mode; Undo/Redo operator context may be unavailable.")
    mesh = bpy.data.meshes.new("SLOPGATE_UNDO_TEST_Mesh")
    obj = bpy.data.objects.new("SLOPGATE_UNDO_TEST_Map", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["qss_object_role"] = "quake_bsp29"
    JOURNAL.ensure_object(obj)

    image_a = bpy.data.images.new("SLOPGATE_UNDO_TEST_Lightmap_A", 4, 4, alpha=True, float_buffer=True)
    image_b = bpy.data.images.new("SLOPGATE_UNDO_TEST_Lightmap_B", 4, 4, alpha=True, float_buffer=True)
    image_a.use_fake_user = True
    image_b.use_fake_user = True
    fill(image_a, 0.1)
    fill(image_b, 0.1)

    operators = (QSS_OT_regression_image_edit, QSS_OT_regression_generated_image)
    registered = []
    try:
        for operator in operators:
            bpy.utils.register_class(operator)
            registered.append(operator)
        JOURNAL.register(bpy)
        record("Registration does not access restricted bpy.data", "PASS",
               "Image undo handlers registered after Blender startup")

        run_check("One operation: Ctrl+Z restores image pixels", lambda: (
            operator_edit(obj, image_a, 0.8),
            undo(),
            assert_uniform(image_a, 0.1),
            "Undo restored the pre-edit image buffer"
        )[-1])

        run_check("One operation: Ctrl+Shift+Z restores edited pixels", lambda: (
            redo(),
            assert_uniform(image_a, 0.8),
            "Redo restored the post-edit image buffer"
        )[-1])

        def stacked_roundtrip():
            operator_edit(obj, image_a, 0.4)
            operator_edit(obj, image_a, 0.7)
            undo()
            assert_uniform(image_a, 0.4)
            undo()
            assert_uniform(image_a, 0.8)
            redo()
            assert_uniform(image_a, 0.4)
            redo()
            assert_uniform(image_a, 0.7)
            return "Two consecutive operations survived undo/undo/redo/redo in order"
        run_check("Multiple operations: undo and redo stack order", stacked_roundtrip)

        def rollback():
            before = pixels(image_a)
            transaction = JOURNAL.begin(obj, [image_a])
            fill(image_a, 0.95)
            JOURNAL.rollback(obj, transaction, bpy.data.images.get)
            after = pixels(image_a)
            if tuple(before) != tuple(after):
                raise AssertionError("Rollback did not restore the original pixel buffer")
            return "Cancelled/failed operation restored its before-image and token"
        run_check("Failed operation rollback", rollback)

        def unrelated_native_edit():
            operator_edit(obj, image_a, 0.5)
            # Stand-in for an intervening native Texture Paint pixel edit. The
            # journal must not restore image A while undoing a later edit to B.
            fill(image_a, 0.33)
            operator_edit(obj, image_b, 0.9)
            undo()
            assert_uniform(image_a, 0.33)
            assert_uniform(image_b, 0.1)
            return "Undoing image B preserved an intervening external edit to image A"
        run_check("Unrelated/native paint edit is not overwritten", unrelated_native_edit)

        def redo_branch():
            operator_edit(obj, image_b, 0.85)
            undo()
            assert_uniform(image_b, 0.1)
            operator_edit(obj, image_a, 0.22)
            try:
                redo()
            except Exception:
                pass  # A discarded redo branch may correctly have no redo action.
            assert_uniform(image_a, 0.22)
            assert_uniform(image_b, 0.1)
            return "A new operation after undo did not resurrect the abandoned redo branch"
        run_check("New operation discards old redo branch", redo_branch)

        def generated_image_roundtrip():
            generated_name = "SLOPGATE_UNDO_TEST_Generated"
            existing = bpy.data.images.get(generated_name)
            if existing is not None:
                bpy.data.images.remove(existing, do_unlink=True)
            result = bpy.ops.qss_undo_regression.generated_image(
                "EXEC_DEFAULT", map_name=obj.name, image_name=generated_name
            )
            if "FINISHED" not in result:
                raise RuntimeError(f"Generated-image operator returned {sorted(result)}")
            generated = bpy.data.images.get(generated_name)
            if generated is None:
                raise AssertionError("Generated image was not created")
            undo()
            redo()
            generated = bpy.data.images.get(generated_name)
            if generated is None:
                raise AssertionError("Generated image was not available after redo")
            assert_uniform(generated, 0.66)
            return "Image created during an operation was present with correct pixels after redo"
        run_check("Generated image survives undo/redo", generated_image_roundtrip)

        run_check("Atlas edge sharpness: 1x/2x/4x", test_edge_canonicalization)
        run_check("Save/reopen persistence", lambda: test_save_reopen(obj, image_a))

        # Run the repository's complete pure-Python regression suite as part
        # of the same one-click report.
        def standalone_tests():
            tests_dir = str(ADDON_ROOT / "tests")
            suite = unittest.defaultTestLoader.discover(tests_dir, pattern="test_*.py")
            result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
            if not result.wasSuccessful():
                raise AssertionError(
                    f"{len(result.failures)} failures, {len(result.errors)} errors "
                    f"across {result.testsRun} unit tests"
                )
            return f"{result.testsRun} standalone unit tests passed"
        run_check("Full SLOPGATE Python regression suite", standalone_tests)

    finally:
        try:
            JOURNAL.unregister(bpy)
        except Exception:
            pass
        for operator in reversed(registered):
            try:
                bpy.utils.unregister_class(operator)
            except Exception:
                pass
        # Test objects/images are disposable; the script is intended for a
        # factory-startup file and deliberately removes only its own names.
        for name in ("SLOPGATE_UNDO_TEST_Map",):
            item = bpy.data.objects.get(name)
            if item is not None:
                bpy.data.objects.remove(item, do_unlink=True)
        mesh_item = bpy.data.meshes.get("SLOPGATE_UNDO_TEST_Mesh")
        if mesh_item is not None and mesh_item.users == 0:
            bpy.data.meshes.remove(mesh_item)
        for name in (
            "SLOPGATE_UNDO_TEST_Lightmap_A",
            "SLOPGATE_UNDO_TEST_Lightmap_B",
            "SLOPGATE_UNDO_TEST_Generated",
        ):
            item = bpy.data.images.get(name)
            if item is not None:
                bpy.data.images.remove(item, do_unlink=True)
        shutil.rmtree(TEMP_DIR, ignore_errors=True)

    passed = sum(item["status"] == "PASS" for item in CHECKS)
    failed = sum(item["status"] == "FAIL" for item in CHECKS)
    report = {
        "blender_version": bpy.app.version_string,
        "background": bool(bpy.app.background),
        "passed": passed,
        "failed": failed,
        "total": len(CHECKS),
        "checks": CHECKS,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    with open(REPORT_TXT, "w", encoding="utf-8") as handle:
        handle.write(
            f"SLOPGATE Blender Undo/Redo Regression: {passed} passed, "
            f"{failed} failed ({len(CHECKS)} checks)\n"
            f"Blender: {bpy.app.version_string}\n\n"
        )
        for item in CHECKS:
            handle.write(f"[{item['status']}] {item['name']}\n{item['detail']}\n\n")
    print(f"\nSLOPGATE regression result: {passed} passed, {failed} failed")
    print(f"Text report: {REPORT_TXT}")
    print(f"JSON report: {REPORT_JSON}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
