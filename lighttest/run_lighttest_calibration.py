#!/usr/bin/env python3
"""Build clean, reproducible ericw-tools reference lightmaps for Slipgate.

Place this script in the repository's lighttest/ directory and run:
    python3 run_lighttest_calibration.py --compile

The source MAP/BSP are never modified. Two output variants are built:
  * attenuation-only: per-light _anglescale 0, isolating radial attenuation
  * angle-default:    per-light _anglescale 0.5, measuring the default incidence term

Both variants remove targetname from the test lights. In ericw-tools,
light.targetname means "switchable light", not a harmless label. The old map
used it as an ID for 15 lights, which explains the 15 switchable light styles
in the committed light.log. We preserve the ID in the inert _qss_test_id key.

Compiler settings for the clean baseline:
    qbsp -splitturb <variant.map>
    vis <variant>
    light -verbose -nocolor -bounce 0 -dirt -1 <variant>

The previously committed compile used -extra4 -soft 2 -dirt 1 -bounce 1
-surflight_subdivide 64 -surflightscale 0.7 -phong. Those are useful production
settings, but they confound a pure direct-attenuation calibration.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MAP = SCRIPT_DIR / "lighttest01-compile.map"
DEFAULT_TOOLS_DIR = Path(
    "/mnt/sde1/FPS/IdTech2/QuakeDev/##tools/ericw-tools-2.0.0-alpha11-Linux"
)
QSS_SOURCE_DIR = SCRIPT_DIR.parent / "quake_surface_studio (zip me for blender)"
RADII = (0, 16, 32, 64, 128, 192, 256, 384, 448)
DIRECTIONS = (
    ("center", 0, 0),
    ("east", 1, 0),
    ("west", -1, 0),
    ("north", 0, 1),
    ("south", 0, -1),
)
LUMP_COUNT = 15
HEADER_SIZE = 4 + LUMP_COUNT * 8
LUMP_PLANES = 1
LUMP_VERTEXES = 3
LUMP_LIGHTING = 8
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_FACES = 7
LUMP_TEXINFO = 6


@dataclass
class Entity:
    start: int
    end: int
    values: dict[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_map_entities(text: str) -> list[Entity]:
    """Read top-level entity key/value pairs from a standard .map file."""
    lines = text.splitlines()
    entities: list[Entity] = []
    depth = 0
    start = -1
    current: dict[str, str] | None = None
    key_pattern = re.compile(r'^\s*"((?:\\.|[^"])*)"\s+"((?:\\.|[^"])*)"\s*$')
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "{":
            depth += 1
            if depth == 1:
                start = index
                current = {}
            continue
        if stripped == "}":
            if depth == 1 and current is not None:
                entities.append(Entity(start, index, current))
                current = None
            depth = max(0, depth - 1)
            continue
        if depth == 1 and current is not None:
            match = key_pattern.match(line)
            if match:
                current[match.group(1)] = match.group(2)
    if depth != 0:
        raise ValueError("Unbalanced braces in MAP file.")
    return entities


def light_test_id(entity: dict[str, str]) -> str:
    delay = int(float(entity.get("delay", "0") or 0))
    value = float(entity.get("light", "300") or 300)
    value_text = str(int(value)) if value.is_integer() else str(value).replace(".", "p")
    return f"d{delay}_{value_text}"


def inspect_map(map_path: Path) -> tuple[str, list[dict[str, Any]]]:
    text = map_path.read_text(encoding="utf-8", errors="replace")
    entities = parse_map_entities(text)
    lights: list[dict[str, Any]] = []
    for entity in entities:
        classname = entity.values.get("classname", "")
        if not classname.startswith("light"):
            continue
        try:
            origin = tuple(float(part) for part in entity.values.get("origin", "0 0 0").split())
            if len(origin) != 3:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"Invalid origin on light entity at MAP line {entity.start + 1}.") from exc
        light_value = float(entity.values.get("light", "300") or 300)
        delay = int(float(entity.values.get("delay", "0") or 0))
        color = tuple(float(part) for part in entity.values.get("_color", "255 255 255").split())
        lights.append({
            "id": light_test_id(entity.values),
            "classname": classname,
            "origin": origin,
            "delay": delay,
            "light": light_value,
            "wait": float(entity.values.get("wait", "1") or 1),
            "color": color,
            "targetname": entity.values.get("targetname", ""),
            "anglescale": entity.values.get("_anglescale", "(default 0.5)"),
            "start": entity.start,
            "end": entity.end,
        })
    return text, lights


def validate_light_matrix(lights: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    expected = {(delay, value) for delay in range(6) for value in (50.0, 300.0, 900.0)}
    actual = [(item["delay"], item["light"]) for item in lights]
    missing = sorted(expected - set(actual))
    duplicate = sorted(pair for pair in set(actual) if actual.count(pair) > 1)
    unexpected = sorted(set(actual) - expected)
    if len(lights) != 18:
        warnings.append(f"Expected 18 point lights; found {len(lights)}.")
    if missing:
        warnings.append(f"Missing delay/value pairs: {missing}.")
    if duplicate:
        warnings.append(f"Duplicate delay/value pairs: {duplicate}.")
    if unexpected:
        warnings.append(f"Unexpected delay/value pairs: {unexpected}.")
    if any(len(item["origin"]) != 3 for item in lights):
        warnings.append("One or more light entities has an invalid origin.")
    if any(len(item["color"]) != 3 for item in lights):
        warnings.append("One or more light entities has an invalid _color.")
    waits = sorted({item["wait"] for item in lights})
    colors = sorted({tuple(item["color"]) for item in lights})
    if waits != [1.0]:
        warnings.append(f"Expected wait=1 for all lights; found {waits}.")
    if colors != [(255.0, 255.0, 255.0)]:
        warnings.append(f"Expected white 255 255 255 lights; found {colors}.")
    named = [item["id"] for item in lights if item["targetname"]]
    if named:
        warnings.append(
            f"{len(named)} lights have targetname. ericw-tools interprets this as a switchable-light key, "
            "not a label. The compile copy will replace it with _qss_test_id."
        )
    return warnings


def write_variant_map(
    original_text: str,
    lights: list[dict[str, Any]],
    destination: Path,
    anglescale: float,
) -> int:
    """Remove switchable-light targetnames and make light IDs inert metadata."""
    lines = original_text.splitlines()
    removed = 0
    # Use line spans from the entity parser; process in reverse so line numbers stay valid.
    for item in sorted(lights, key=lambda value: value["start"], reverse=True):
        start, end = int(item["start"]), int(item["end"])
        entity_lines = lines[start + 1:end]
        rewritten: list[str] = []
        indent = ""
        for line in entity_lines:
            match = re.match(r'^(\s*)"targetname"\s+"(?:\\.|[^"])*"\s*$', line)
            if match:
                indent = match.group(1)
                removed += 1
                continue
            if re.match(r'^\s*"_qss_test_id"\s+', line):
                continue
            if re.match(r'^\s*"_anglescale"\s+', line):
                continue
            rewritten.append(line)
        if not indent:
            indent = "\t"
        rewritten.append(f'{indent}"_qss_test_id" "{item["id"]}"')
        rewritten.append(f'{indent}"_anglescale" "{anglescale:.6g}"')
        lines[start + 1:end] = rewritten
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return removed


def run_command(command: list[str], cwd: Path, label: str) -> str:
    print(f"\n[{label}] {' '.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    output = completed.stdout or ""
    (cwd / f"{label}.stdout.txt").write_text(output, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        tail = "\n".join(output.splitlines()[-35:])
        raise RuntimeError(f"{label} exited with code {completed.returncode}.\n{tail}")
    print("  PASS", flush=True)
    return output


def parse_bsp_lumps(path: Path) -> list[bytes]:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE or struct.unpack_from("<i", data, 0)[0] != 29:
        raise ValueError(f"{path} is not a classic BSP29 file.")
    lumps: list[bytes] = []
    for index in range(LUMP_COUNT):
        offset, length = struct.unpack_from("<ii", data, 4 + index * 8)
        if offset < 0 or length < 0 or offset + length > len(data):
            raise ValueError(f"Invalid BSP lump {index} bounds.")
        lumps.append(data[offset:offset + length] if length else b"")
    return lumps


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        # Include points lying on an edge (within a small numeric tolerance).
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        dot = (x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)
        length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if length_sq > 0 and abs(cross) <= 1e-6 and -1e-6 <= dot <= length_sq + 1e-6:
            return True
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing_x:
                inside = not inside
    return inside


def _bilinear(data: bytes, offset: int, width: int, height: int, x: float, y: float) -> float:
    x = max(0.0, min(float(width - 1), x))
    y = max(0.0, min(float(height - 1), y))
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    x1, y1 = min(width - 1, x0 + 1), min(height - 1, y0 + 1)
    tx, ty = x - x0, y - y0
    p00 = data[offset + y0 * width + x0]
    p10 = data[offset + y0 * width + x1]
    p01 = data[offset + y1 * width + x0]
    p11 = data[offset + y1 * width + x1]
    top = p00 * (1.0 - tx) + p10 * tx
    bottom = p01 * (1.0 - tx) + p11 * tx
    return top * (1.0 - ty) + bottom * ty


def build_face_records(lumps: list[bytes]) -> list[dict[str, Any]]:
    planes = [struct.unpack_from("<4fi", lumps[LUMP_PLANES], i)
              for i in range(0, len(lumps[LUMP_PLANES]), 20)]
    vertices = [struct.unpack_from("<3f", lumps[LUMP_VERTEXES], i)
                for i in range(0, len(lumps[LUMP_VERTEXES]), 12)]
    edges = [struct.unpack_from("<2H", lumps[LUMP_EDGES], i)
             for i in range(0, len(lumps[LUMP_EDGES]), 4)]
    surfedges = [item[0] for item in struct.iter_unpack("<i", lumps[LUMP_SURFEDGES])]
    texinfos = [struct.unpack_from("<8fii", lumps[LUMP_TEXINFO], i)
                for i in range(0, len(lumps[LUMP_TEXINFO]), 40)]
    faces = [struct.unpack_from("<Hhihh4Bi", lumps[LUMP_FACES], i)
             for i in range(0, len(lumps[LUMP_FACES]), 20)]
    result = []
    for index, face in enumerate(faces):
        planenum, side, firstedge, numedges, texinfo_index = face[:5]
        styles = tuple(face[5:9])
        lightofs = face[9]
        if planenum >= len(planes) or texinfo_index < 0 or texinfo_index >= len(texinfos):
            continue
        if firstedge < 0 or numedges < 3 or firstedge + numedges > len(surfedges):
            continue
        vertex_ids = []
        valid = True
        for signed_edge in surfedges[firstedge:firstedge + numedges]:
            edge_index = abs(signed_edge)
            if edge_index >= len(edges):
                valid = False
                break
            v0, v1 = edges[edge_index]
            vertex_ids.append(v0 if signed_edge >= 0 else v1)
        if not valid or any(vertex_id >= len(vertices) for vertex_id in vertex_ids):
            continue
        plane = planes[planenum]
        plane_sign = -1.0 if side else 1.0
        normal = tuple(float(value) * plane_sign for value in plane[:3])
        # BSP face side reverses the complete plane equation, not just its normal.
        distance = float(plane[3]) * plane_sign
        tex = texinfos[texinfo_index]
        s_axis, t_axis = tex[:4], tex[4:8]
        polygon_world = [vertices[vertex_id] for vertex_id in vertex_ids]
        polygon_st = [
            (sum(p[k] * s_axis[k] for k in range(3)) + s_axis[3],
             sum(p[k] * t_axis[k] for k in range(3)) + t_axis[3])
            for p in polygon_world
        ]
        min_s = math.floor(min(p[0] for p in polygon_st) / 16.0 + 1e-6)
        max_s = math.ceil(max(p[0] for p in polygon_st) / 16.0 - 1e-6)
        min_t = math.floor(min(p[1] for p in polygon_st) / 16.0 + 1e-6)
        max_t = math.ceil(max(p[1] for p in polygon_st) / 16.0 - 1e-6)
        width, height = max_s - min_s + 1, max_t - min_t + 1
        if width < 1 or height < 1 or width > 65536 or height > 65536:
            continue
        style_ids = [value for value in styles if value != 255]
        result.append({
            "index": index,
            "normal": normal,
            "plane_distance": distance,
            "polygon_st": polygon_st,
            "s_axis": s_axis,
            "t_axis": t_axis,
            "min_s": min_s,
            "min_t": min_t,
            "width": width,
            "height": height,
            "styles": styles,
            "style_ids": style_ids,
            "lightofs": lightofs,
        })
    return result


def sample_floor_luxel(lumps: list[bytes], face_records: list[dict[str, Any]],
                       point: tuple[float, float, float], source: tuple[float, float, float]
                       ) -> tuple[float | None, dict[str, Any] | None]:
    """Find the actual upward-facing floor under x/y, then read its lightmap.

    Do not assume the floor is exactly eight units below the light. The MAP's
    brush geometry determines the floor height; read that from the compiled BSP.
    """
    lightdata = lumps[LUMP_LIGHTING]
    x, y = point[0], point[1]
    candidates = []
    for face in face_records:
        nx, ny, nz = face["normal"]
        if nz < 0.9:
            continue
        floor_z = (face["plane_distance"] - nx * x - ny * y) / nz
        if floor_z >= source[2] - 0.5:
            continue
        s_axis, t_axis = face["s_axis"], face["t_axis"]
        s_value = x * s_axis[0] + y * s_axis[1] + floor_z * s_axis[2] + s_axis[3]
        t_value = x * t_axis[0] + y * t_axis[1] + floor_z * t_axis[2] + t_axis[3]
        if not _point_in_polygon(s_value, t_value, face["polygon_st"]):
            continue
        sx = (s_value - face["min_s"] * 16.0) / 16.0
        ty = (t_value - face["min_t"] * 16.0) / 16.0
        if (sx < -1e-4 or ty < -1e-4 or
                sx > face["width"] - 1 + 1e-4 or
                ty > face["height"] - 1 + 1e-4):
            continue
        candidates.append((floor_z, face, sx, ty))
    if not candidates:
        return None, None

    floor_z, face, sx, ty = max(candidates, key=lambda item: item[0])
    direction = (source[0] - x, source[1] - y, source[2] - floor_z)
    length = math.sqrt(sum(value * value for value in direction)) or 1.0
    dot = (face["normal"][0] * direction[0] +
           face["normal"][1] * direction[1] +
           face["normal"][2] * direction[2]) / length

    if face["lightofs"] < 0 or not face["style_ids"]:
        return None, {"face": face["index"], "styles": face["styles"],
                      "normal_dot": dot, "sample_z": floor_z}
    sample_count = face["width"] * face["height"]
    style_index = face["styles"].index(0) if 0 in face["styles"] else 0
    offset = face["lightofs"] + style_index * sample_count
    if offset + sample_count > len(lightdata):
        return None, {"face": face["index"], "styles": face["styles"],
                      "error": "lightdata bounds", "sample_z": floor_z}
    value = _bilinear(lightdata, offset, face["width"], face["height"], sx, ty)
    return value, {
        "face": face["index"],
        "styles": ",".join(str(v) for v in face["style_ids"]),
        "normal_dot": dot,
        "lightmap_width": face["width"],
        "lightmap_height": face["height"],
        "sample_z": floor_z,
    }

def sample_compiled_bsp(bsp_path: Path, lights: list[dict[str, Any]], variant: str,
                        output_dir: Path) -> dict[str, int]:
    lumps = parse_bsp_lumps(bsp_path)
    faces = build_face_records(lumps)
    # QSS lighting.py is deliberately imported dynamically; it has no bpy dependency.
    sys.path.insert(0, str(QSS_SOURCE_DIR))
    try:
        import lighting  # type: ignore
    except Exception:
        lighting = None
    csv_path = output_dir / "luxel_samples.csv"
    missing = 0
    written = 0
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "test_id", "delay", "light", "radius", "direction", "distance",
            "x", "y", "z", "sample_z", "luxel", "ericw_attenuation", "surface_factor",
            "ericw_with_surface_angle", "normal_dot", "face", "styles",
            "lightmap_width", "lightmap_height", "status",
        ))
        writer.writeheader()
        for light in lights:
            ox, oy, oz = light["origin"]
            floor_z = oz - 8.0
            for radius in RADII:
                directions = DIRECTIONS[:1] if radius == 0 else DIRECTIONS[1:]
                for direction_name, dx, dy in directions:
                    x = ox + dx * radius
                    y = oy + dy * radius
                    point = (x, y, floor_z)
                    value, meta = sample_floor_luxel(lumps, faces, point, light["origin"])
                    actual_z = meta.get("sample_z", floor_z) if meta else floor_z
                    distance = math.sqrt((x - ox) ** 2 + (y - oy) ** 2 + (oz - actual_z) ** 2)
                    status = "OK" if value is not None else "NO_FLOOR_LUXEL"
                    if value is None:
                        missing += 1
                    predicted = ""
                    surface_factor: float | str = ""
                    predicted_with_angle: float | str = ""
                    if lighting is not None:
                        try:
                            predicted = lighting.ericw_light_value(
                                light["light"], light["delay"], distance, wait=light["wait"]
                            )
                            if meta and "normal_dot" in meta:
                                angle_scale = 0.0 if variant == "attenuation_only" else 0.5
                                surface_factor = lighting.ericw_surface_angle(
                                    meta["normal_dot"], anglescale=angle_scale
                                )
                                predicted_with_angle = predicted * surface_factor
                        except Exception:
                            predicted = ""
                            surface_factor = ""
                            predicted_with_angle = ""
                    writer.writerow({
                        "test_id": light["id"],
                        "delay": light["delay"],
                        "light": light["light"],
                        "radius": radius,
                        "direction": direction_name,
                        "distance": f"{distance:.6f}",
                        "x": f"{x:.3f}", "y": f"{y:.3f}", "z": f"{actual_z:.3f}",
                        "sample_z": "" if not meta else f"{meta.get('sample_z', '')}",
                        "luxel": "" if value is None else f"{value:.4f}",
                        "ericw_attenuation": "" if predicted == "" else f"{predicted:.6f}",
                        "surface_factor": "" if surface_factor == "" else f"{surface_factor:.6f}",
                        "ericw_with_surface_angle": "" if predicted_with_angle == "" else f"{predicted_with_angle:.6f}",
                        "normal_dot": "" if not meta else f"{meta.get('normal_dot', '')}",
                        "face": "" if not meta else meta.get("face", ""),
                        "styles": "" if not meta else meta.get("styles", ""),
                        "lightmap_width": "" if not meta else meta.get("lightmap_width", ""),
                        "lightmap_height": "" if not meta else meta.get("lightmap_height", ""),
                        "status": status,
                    })
                    written += 1
    return {"samples_written": written, "missing_samples": missing, "csv": str(csv_path)}


def compile_variant(
    tools: dict[str, Path], source_map: Path, original_text: str,
    lights: list[dict[str, Any]], root_output: Path, variant: str, anglescale: float,
    do_sample: bool = True,
) -> dict[str, Any]:
    variant_dir = root_output / variant
    variant_dir.mkdir(parents=True, exist_ok=True)
    stem = f"lighttest01_{variant}"
    map_path = variant_dir / f"{stem}.map"
    removed_targetnames = write_variant_map(original_text, lights, map_path, anglescale)
    for suffix in (".content.json", ".texinfo.json"):
        sidecar = source_map.with_name(source_map.stem + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, variant_dir / f"{stem}{suffix}")

    qbsp_output = run_command([str(tools["qbsp"]), "-splitturb", map_path.name], variant_dir, "qbsp")
    bsp_path = variant_dir / f"{stem}.bsp"
    if not bsp_path.is_file():
        raise RuntimeError("qbsp returned success but did not create the expected BSP.")
    run_command([str(tools["vis"]), stem], variant_dir, "vis")
    light_args = [
        str(tools["light"]), "-verbose", "-nocolor", "-bounce", "0", "-dirt", "-1", stem,
    ]
    light_output = run_command(light_args, variant_dir, "light")
    light_log = variant_dir / f"{stem}-light.log"
    switchable_styles = None
    if light_log.exists():
        log_text = light_log.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(\d+) switchable light styles", log_text)
        if match:
            switchable_styles = int(match.group(1))
        log_source = str(light_log)
    else:
        match = re.search(r"(\d+) switchable light styles", light_output)
        if match:
            switchable_styles = int(match.group(1))
        log_source = str(variant_dir / "light.stdout.txt")
    if do_sample:
        try:
            sample_result = sample_compiled_bsp(bsp_path, lights, variant, variant_dir)
        except Exception as exc:
            sample_result = {"error": str(exc), "samples_written": 0, "missing_samples": 0}
            print(f"  WARNING: BSP luxel sampler could not finish: {exc}", flush=True)
    else:
        sample_result = {"skipped": True}
    report = {
        "variant": variant,
        "map": str(map_path),
        "bsp": str(bsp_path),
        "anglescale": anglescale,
        "removed_switchable_targetnames": removed_targetnames,
        "switchable_light_styles": switchable_styles,
        "compile_commands": {
            "qbsp": [str(tools["qbsp"]), "-splitturb", map_path.name],
            "vis": [str(tools["vis"]), stem],
            "light": light_args,
        },
        "sample_results": sample_result,
        "notes": [
            "Source MAP/BSP files were not modified.",
            "targetname was replaced with inert _qss_test_id because targetname makes ericw-tools lights switchable.",
            "Bounce and dirtmapping were disabled to isolate direct light attenuation.",
            "extra4, soft, phong and surface-light options from the original production compile were omitted.",
        ],
        "qbsp_log": str(variant_dir / "qbsp.stdout.txt"),
        "vis_log": str(variant_dir / "vis.stdout.txt"),
        "light_log": log_source,
        "qbsp_stdout_tail": qbsp_output.splitlines()[-8:],
    }
    (variant_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP, help="Source MAP file (default: lighttest01-compile.map beside this script)")
    parser.add_argument("--tools-dir", type=Path, default=DEFAULT_TOOLS_DIR, help="Folder containing qbsp, vis and light")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory (default: lighttest/results_<timestamp>)")
    parser.add_argument("--compile", action="store_true", help="Build clean attenuation-only and default-angle references")
    parser.add_argument("--no-sample", action="store_true", help="Skip floor-luxel CSV sampling after compilation")
    args = parser.parse_args()

    map_path = args.map.expanduser().resolve()
    if not map_path.is_file():
        print(f"ERROR: MAP file not found: {map_path}", file=sys.stderr)
        return 2
    try:
        original_text, lights = inspect_map(map_path)
        warnings = validate_light_matrix(lights)
    except Exception as exc:
        print(f"ERROR: Could not inspect MAP: {exc}", file=sys.stderr)
        return 2

    print(f"Calibration source: {map_path}")
    print(f"Lights: {len(lights)}")
    for delay in range(6):
        row = sorted((item for item in lights if item["delay"] == delay), key=lambda item: item["light"])
        print(f"  delay {delay}: " + ", ".join(f'{item["light"]:g} ({item["id"]})' for item in row))
    named = sum(bool(item["targetname"]) for item in lights)
    print(f"Lights with targetname (switchable): {named}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if not args.compile:
        print("\nInspection only. Run with --compile to build two non-destructive reference BSPs.")
        return 0

    tools_dir = args.tools_dir.expanduser().resolve()
    suffix = ".exe" if os.name == "nt" else ""
    tools = {name: tools_dir / f"{name}{suffix}" for name in ("qbsp", "vis", "light")}
    missing = [str(path) for path in tools.values() if not path.is_file()]
    if missing:
        print("ERROR: Could not find compiler executable(s):", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print("Pass --tools-dir with the folder that contains qbsp, vis and light.", file=sys.stderr)
        return 2
    if not args.output_dir:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_root = SCRIPT_DIR / f"results_{stamp}"
    else:
        output_root = args.output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    try:
        reports = []
        for variant, angle in (("attenuation_only", 0.0), ("angle_default", 0.5)):
            print(f"\n=== Building {variant} (_anglescale={angle:g}) ===")
            # Sampling can be disabled for the rare case that a custom BSP geometry
            # cannot be matched to the expected floor plane.
            report = compile_variant(
                tools, map_path, original_text, lights, output_root,
                variant, angle, do_sample=not args.no_sample,
            )
            reports.append(report)
        summary = {
            "source_map": str(map_path),
            "source_sha256": sha256_file(map_path),
            "tools_dir": str(tools_dir),
            "lights": lights,
            "warnings": warnings,
            "variants": reports,
        }
        (output_root / "calibration_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nDone. Results: {output_root}")
        for report in reports:
            sample = report["sample_results"]
            print(
                f"  {report['variant']}: switchable styles={report['switchable_light_styles']}; "
                f"samples={sample.get('samples_written', 0)}; missing={sample.get('missing_samples', 0)}; "
                f"BSP={report['bsp']}"
            )
        print("Import the two BSPs in Slipgate and compare them with the original compiled lighttest BSP.")
        print("The attenuation_only variant isolates radial falloff. angle_default retains ericw's default _anglescale=0.5.")
        return 0
    except Exception as exc:
        print(f"ERROR: Calibration build failed: {exc}", file=sys.stderr)
        print(f"Partial outputs were kept in: {output_root}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
