"""SAFE SLOPGATE regression runner.

This runner deliberately does NOT call bpy.ops.ed.undo/redo, register undo
handlers, create/remove Blender datablocks, or modify the current .blend.
It runs the add-on's isolated Python regression suite and a pure-buffer
luxel canonicalization check. Blender GUI undo integration must be tested
manually in a disposable file; scripting global undo from the Text Editor
proved unsafe on some Blender builds.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

import bpy


def find_addon_root():
    candidates = []
    try:
        script_path = Path(__file__).resolve()
        if len(script_path.parents) > 1:
            candidates.append(script_path.parents[1])
    except (NameError, OSError, RuntimeError):
        pass

    for addon in bpy.context.preferences.addons:
        module = sys.modules.get(addon.module)
        module_file = getattr(module, "__file__", None)
        if module_file:
            module_path = Path(module_file).resolve()
            candidates.extend((module_path.parent, module_path.parent.parent))

    for scripts_dir in bpy.utils.script_paths(subdir="addons"):
        base = Path(scripts_dir)
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if child.is_dir():
                    candidates.extend((child, child / "quake_surface_studio"))
        except OSError:
            pass

    seen = set()
    for candidate in candidates:
        try:
            root = candidate.resolve()
            if root in seen:
                continue
            seen.add(root)
            if (root / "bake_scope.py").is_file() and (root / "image_undo.py").is_file():
                return root
        except (OSError, RuntimeError):
            pass

    raise RuntimeError(
        "Cannot locate SLOPGATE source. Enable the add-on or place this script "
        "inside its tools folder, then run again."
    )


ADDON_ROOT = find_addon_root()
sys.path.insert(0, str(ADDON_ROOT))

import bake_scope


def check_luxel_blocks():
    from array import array
    for block in (1, 2, 4):
        width = height = block * 2
        pixels = array("f", [0.0, 0.0, 0.0, 1.0] * (width * height))
        changed = bake_scope.collapse_rgba_luxel_blocks(
            pixels, width, height, [(0, 0, width, height)], block_size=block
        )
        if changed != 4:
            raise AssertionError(f"{block}x: expected 4 blocks, got {changed}")
        for by in (0, block):
            for bx in (0, block):
                ref = tuple(pixels[(by * width + bx) * 4:(by * width + bx) * 4 + 4])
                for y in range(by, by + block):
                    for x in range(bx, bx + block):
                        i = (y * width + x) * 4
                        if tuple(pixels[i:i + 4]) != ref:
                            raise AssertionError(f"{block}x luxel block is not uniform")
    return "Luxel block buffer test passed at 1x, 2x and 4x"


def main():
    checks = []
    try:
        checks.append({"name": "Luxel block canonicalization", "status": "PASS",
                       "detail": check_luxel_blocks()})
    except Exception as exc:
        checks.append({"name": "Luxel block canonicalization", "status": "FAIL",
                       "detail": traceback.format_exc()})

    try:
        suite = unittest.defaultTestLoader.discover(
            str(ADDON_ROOT / "tests"), pattern="test_*.py"
        )
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
        checks.append({
            "name": "SLOPGATE isolated Python test suite",
            "status": "PASS" if result.wasSuccessful() else "FAIL",
            "detail": f"{result.testsRun} tests; {len(result.failures)} failures; "
                      f"{len(result.errors)} errors",
        })
    except Exception:
        checks.append({"name": "SLOPGATE isolated Python test suite", "status": "FAIL",
                       "detail": traceback.format_exc()})

    passed = sum(c["status"] == "PASS" for c in checks)
    failed = len(checks) - passed
    report = {
        "blender_version": bpy.app.version_string,
        "current_file_modified": False,
        "global_undo_touched": False,
        "passed": passed,
        "failed": failed,
        "checks": checks,
    }
    txt_path = os.path.join(tempfile.gettempdir(), "SLOPGATE_Safe_Regression.txt")
    json_path = os.path.join(tempfile.gettempdir(), "SLOPGATE_Safe_Regression.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(f"SLOPGATE SAFE REGRESSION: {passed} passed, {failed} failed\\n")
        handle.write(f"Blender: {bpy.app.version_string}\\n")
        handle.write("Current .blend modified: NO; global undo touched: NO\\n\\n")
        for item in checks:
            handle.write(f"[{item['status']}] {item['name']}\\n{item['detail']}\\n\\n")

    print(f"\\nSLOPGATE safe regression: {passed} passed, {failed} failed")
    print(f"Text report: {txt_path}")
    print(f"JSON report: {json_path}")
    print("NOTE: This safe runner does not simulate GUI Ctrl+Z/Ctrl+Shift+Z.")
    if failed:
        print("One or more isolated checks failed; see the report.")


if __name__ == "__main__":
    main()
