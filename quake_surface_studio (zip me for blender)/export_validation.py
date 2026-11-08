"""Offline validation for Quake Surface Studio BSP exports.

This module deliberately has no Blender dependency so it can run in ordinary
Python and in CI against files exported by the add-on.
"""
from __future__ import annotations

import math
import os
import struct
from typing import Optional

try:
    from . import bsp, lightmap_export as lightmap_export_utils
except ImportError:  # executed as a stand-alone script / unittest module
    import bsp
    import lightmap_export as lightmap_export_utils


_GEOMETRY_LUMPS = (
    bsp.LUMP_ENTITIES,
    bsp.LUMP_PLANES,
    bsp.LUMP_VERTEXES,
    bsp.LUMP_VISIBILITY,
    bsp.LUMP_NODES,
    bsp.LUMP_CLIPNODES,
    bsp.LUMP_LEAFS,
    bsp.LUMP_MARKSURFACES,
    bsp.LUMP_EDGES,
    bsp.LUMP_SURFEDGES,
    bsp.LUMP_MODELS,
)
_REWRITABLE_BSPX = {
    "RGBLIGHTING", "LMSHIFT", "LMOFFSET", "LMSTYLE", "LMSTYLE16",
    "DECOUPLED_LM",
}
_NO_LIGHT_OFFSET = 0xFFFFFFFF


def _fail(message: str) -> None:
    raise bsp.BSPError("Export validation failed: " + message)


def _face_lightmap_dimensions(parsed: bsp.BSP29, face: tuple, spacing: int) -> tuple[int, int]:
    """Compute per-face luxel dimensions using the engine's current luxel spacing."""
    texinfos = parsed.texinfos()
    texinfo_id = int(face[4])
    if texinfo_id < 0 or texinfo_id >= len(texinfos):
        _fail(f"face references invalid texinfo {texinfo_id}")
    vertex_ids = parsed.face_vertex_indices(face)
    vertices = parsed.vertices()
    if len(vertex_ids) < 3:
        _fail("face has fewer than three edges")
    if any(index < 0 or index >= len(vertices) for index in vertex_ids):
        _fail("face references an invalid vertex")
    texinfo = texinfos[texinfo_id]
    s_values = [
        vertices[index][0] * texinfo[0] + vertices[index][1] * texinfo[1]
        + vertices[index][2] * texinfo[2] + texinfo[3]
        for index in vertex_ids
    ]
    t_values = [
        vertices[index][0] * texinfo[4] + vertices[index][1] * texinfo[5]
        + vertices[index][2] * texinfo[6] + texinfo[7]
        for index in vertex_ids
    ]
    epsilon = 1e-7
    s_min = int(math.floor(min(s_values) / spacing + epsilon))
    s_max = int(math.ceil(max(s_values) / spacing - epsilon))
    t_min = int(math.floor(min(t_values) / spacing + epsilon))
    t_max = int(math.ceil(max(t_values) / spacing - epsilon))
    return s_max - s_min + 1, t_max - t_min + 1


def _validate_face_references(parsed: bsp.BSP29, label: str) -> None:
    planes = parsed.planes()
    texinfos = parsed.texinfos()
    textures = parsed.miptextures()
    for face_index, face in enumerate(parsed.faces()):
        if face[0] < 0 or face[0] >= len(planes):
            _fail(f"{label} face {face_index} references invalid plane {face[0]}")
        texinfo_id = int(face[4])
        if texinfo_id < 0 or texinfo_id >= len(texinfos):
            _fail(f"{label} face {face_index} references invalid texinfo {texinfo_id}")
        texture_id = int(texinfos[texinfo_id][8])
        if texture_id != -1 and not (0 <= texture_id < len(textures)):
            _fail(f"{label} face {face_index} texinfo references invalid texture {texture_id}")
        parsed.face_vertex_indices(face)


def _validate_classic_lightmaps(parsed: bsp.BSP29, label: str) -> int:
    lighting = parsed.lumps[bsp.LUMP_LIGHTING]
    required_samples = 0
    for face_index, face in enumerate(parsed.faces()):
        light_offset = int(face[9])
        styles = tuple(int(value) for value in face[5:9])
        if light_offset < 0 or styles[0] == 255:
            continue
        style_count = 0
        for style in styles:
            if style == 255:
                break
            style_count += 1
        if style_count == 0:
            _fail(f"{label} face {face_index} has a light offset but no active styles")
        width, height = _face_lightmap_dimensions(parsed, face, 16)
        end = light_offset + width * height * style_count
        required_samples = max(required_samples, end)
    if len(lighting) < required_samples:
        _fail(
            f"{label} classic LIGHTING lump has {len(lighting)} bytes, "
            f"but face references require at least {required_samples}"
        )
    return required_samples


def _validate_enhanced_lightmaps(
    parsed: bsp.BSP29,
    classic_required: int,
    base_sample_count: int,
    require_appended: bool = True,
) -> Optional[int]:
    """Validate either classic LMSHIFT arrays or DECOUPLED_LM records."""
    extensions = parsed.bspx_lumps
    if "LMSTYLE16" in extensions:
        _fail("LMSTYLE16 is not supported; its variable-length face-style table is not implemented")
    if "DECOUPLED_LM" in extensions:
        faces = parsed.faces()
        count = len(faces)
        try:
            records = lightmap_export_utils.parse_decoupled_lightmap_data(
                extensions["DECOUPLED_LM"], count
            )
        except ValueError as exc:
            _fail(f"invalid DECOUPLED_LM data: {exc}")
        styles_payload = extensions.get("LMSTYLE")
        if styles_payload is not None and len(styles_payload) != count:
            _fail(f"LMSTYLE must contain exactly one byte for each of {count} faces")
        rgb = extensions.get("RGBLIGHTING")
        if rgb is None or len(rgb) % 3:
            _fail("DECOUPLED_LM requires a valid RGBLIGHTING BSPX lump")
        lighting = parsed.lumps[bsp.LUMP_LIGHTING]
        if len(rgb) != len(lighting) * 3:
            _fail("DECOUPLED_LM RGBLIGHTING must contain exactly three bytes per LIGHTING sample")
        rgb_samples = len(rgb) // 3
        vertices = parsed.vertices()
        spans = []
        total_samples = 0
        for face_index, (face, record) in enumerate(zip(faces, records)):
            style = (
                int(styles_payload[face_index])
                if styles_payload is not None
                else None
            )
            if record is None:
                if style not in (None, 255):
                    _fail(f"DECOUPLED_LM face {face_index} is unlit but LMSTYLE declares style {style}")
                continue
            if style == 255:
                _fail(f"DECOUPLED_LM face {face_index} has samples but LMSTYLE marks it unlit")
            width, height = int(record["width"]), int(record["height"])
            if width < 1 or height < 1:
                _fail(f"DECOUPLED_LM face {face_index} has invalid dimensions")
            active_styles = (
                [style] if style is not None
                else [int(value) for value in face[5:9] if int(value) != 255]
            )
            if not active_styles:
                _fail(f"DECOUPLED_LM face {face_index} has samples but no active face style")
            sample_count = width * height * len(active_styles)
            offset = int(record["offset"])
            finish = offset + sample_count
            if finish > rgb_samples:
                _fail(
                    f"DECOUPLED_LM face {face_index} ends at sample {finish}, "
                    f"but RGBLIGHTING contains only {rgb_samples} samples"
                )
            if finish > len(lighting):
                _fail(
                    f"DECOUPLED_LM face {face_index} ends at sample {finish}, "
                    f"but LIGHTING contains only {len(lighting)} samples"
                )
            plane_id = int(face[0])
            planes = parsed.planes()
            if plane_id < 0 or plane_id >= len(planes):
                _fail(f"DECOUPLED_LM face {face_index} references invalid plane {plane_id}")
            vertex_ids = parsed.face_vertex_indices(face)
            if len(vertex_ids) < 3 or any(index < 0 or index >= len(vertices) for index in vertex_ids):
                _fail(f"DECOUPLED_LM face {face_index} references invalid vertices")
            sign = -1.0 if int(face[1]) else 1.0
            normal = tuple(float(planes[plane_id][i]) * sign for i in range(3))
            distance = float(planes[plane_id][3]) * sign
            lmvecs = record["lmvecs"]
            s_values = [
                vertices[index][0] * lmvecs[0] + vertices[index][1] * lmvecs[1]
                + vertices[index][2] * lmvecs[2] + lmvecs[3]
                for index in vertex_ids
            ]
            t_values = [
                vertices[index][0] * lmvecs[4] + vertices[index][1] * lmvecs[5]
                + vertices[index][2] * lmvecs[6] + lmvecs[7]
                for index in vertex_ids
            ]
            epsilon = 0.01
            if (min(s_values) < -epsilon or min(t_values) < -epsilon
                    or max(s_values) > width - 1 + epsilon
                    or max(t_values) > height - 1 + epsilon):
                _fail(
                    f"DECOUPLED_LM face {face_index} projection falls outside "
                    f"its {width}x{height} sample grid"
                )
            spans.append((offset, finish, face_index))
            total_samples += sample_count

        if require_appended and spans:
            first_offset = min(start for start, _end, _face in spans)
            if first_offset < classic_required:
                _fail(
                    f"DECOUPLED_LM appended samples begin at {first_offset}, "
                    f"before the classic fallback range ending at {classic_required}"
                )
            cursor = first_offset
            for start, finish, face_index in sorted(spans):
                if start != cursor:
                    _fail(
                        f"DECOUPLED_LM face {face_index} starts at sample {start}; "
                        f"expected contiguous sample offset {cursor} (overlap or gap)"
                    )
                cursor = finish
            if cursor != rgb_samples:
                _fail(
                    f"DECOUPLED_LM records consume through sample {cursor}, "
                    f"but RGBLIGHTING contains {rgb_samples} samples"
                )
            return cursor - first_offset
        return total_samples

    if not any(name in extensions for name in ("LMSHIFT", "LMOFFSET", "LMSTYLE")):
        return None

    faces = parsed.faces()
    count = len(faces)
    shifts = extensions.get("LMSHIFT")
    offsets = extensions.get("LMOFFSET")
    styles = extensions.get("LMSTYLE")
    if shifts is None or len(shifts) != count:
        _fail(f"LMSHIFT must contain exactly one byte for each of {count} faces")
    if offsets is None or len(offsets) != count * 4:
        _fail(f"LMOFFSET must contain exactly {count} little-endian uint32 offsets")
    if styles is None or len(styles) != count:
        _fail(f"LMSTYLE must contain exactly one style byte for each of {count} faces")

    rgb = extensions.get("RGBLIGHTING")
    if rgb is None or len(rgb) % 3:
        _fail("enhanced lightmaps require a valid RGBLIGHTING BSPX lump")
    lighting = parsed.lumps[bsp.LUMP_LIGHTING]
    if len(rgb) != len(lighting) * 3:
        _fail(
            "enhanced BSPX RGBLIGHTING must contain exactly three bytes per "
            "standard LIGHTING byte so QSS/FTE readers accept the light data"
        )
    rgb_samples = len(rgb) // 3
    spans = []
    for face_index, face in enumerate(faces):
        shift = int(shifts[face_index])
        offset = struct.unpack_from("<I", offsets, face_index * 4)[0]
        style = int(styles[face_index])
        if shift > 4:
            _fail(f"face {face_index} has unsupported LMSHIFT value {shift}")
        if offset == _NO_LIGHT_OFFSET or style == 255:
            if offset != _NO_LIGHT_OFFSET or style != 255:
                _fail(f"face {face_index} has inconsistent no-light metadata")
            continue
        width, height = _face_lightmap_dimensions(parsed, face, 1 << shift)
        if width > 256 or height > 256:
            _fail(
                f"face {face_index} enhanced lightmap is {width}x{height}; "
                "BSPX LMSHIFT surfaces are limited to 256 luxels per axis"
            )
        finish = offset + width * height
        if finish > rgb_samples:
            _fail(
                f"face {face_index} enhanced lightmap ends at sample {finish}, "
                f"but RGBLIGHTING contains only {rgb_samples} samples"
            )
        spans.append((offset, finish, face_index))

    if require_appended:
        cursor = base_sample_count
        for start, finish, face_index in sorted(spans):
            if start != cursor:
                _fail(
                    f"face {face_index} enhanced lightmap starts at sample {start}; "
                    f"expected contiguous sample offset {cursor} (overlap or gap)"
                )
            cursor = finish
        if cursor != rgb_samples:
            _fail(
                f"enhanced RGBLIGHTING has {rgb_samples} samples but face ranges "
                f"consume {cursor}"
            )
        return rgb_samples - base_sample_count
    return sum(end - start for start, end, _face in spans)


def validate_export_bytes(
    source_data: bytes,
    exported_data: bytes,
    lit_data: Optional[bytes] = None,
) -> dict:
    """Validate an exported BSP against its source; return a concise report."""
    source = bsp.BSP29(source_data)
    exported = bsp.BSP29(exported_data)
    if len(source.faces()) != len(exported.faces()):
        _fail(f"face count changed from {len(source.faces())} to {len(exported.faces())}")

    for lump_id in _GEOMETRY_LUMPS:
        if source.lumps[lump_id] != exported.lumps[lump_id]:
            _fail(f"unrelated geometry/entity lump {lump_id} changed")

    source_texinfos = source.lumps[bsp.LUMP_TEXINFO]
    if exported.lumps[bsp.LUMP_TEXINFO][:len(source_texinfos)] != source_texinfos:
        _fail("original texinfo records were modified instead of appending face-local variants")
    if len(exported.lumps[bsp.LUMP_TEXINFO]) < len(source_texinfos):
        _fail("texinfo lump became shorter")
    source_textures = source.miptextures()
    exported_textures = exported.miptextures()
    if len(exported_textures) < len(source_textures):
        _fail("texture directory lost one or more original entries")

    _validate_face_references(source, "source")
    _validate_face_references(exported, "exported")
    source_faces = source.faces()
    exported_faces = exported.faces()
    for face_index, (before, after) in enumerate(zip(source_faces, exported_faces)):
        stable_geometry_before = (before[0], before[1], before[2], before[3])
        stable_geometry_after = (after[0], after[1], after[2], after[3])
        if stable_geometry_before != stable_geometry_after:
            _fail(f"face {face_index} geometry changed unexpectedly")
        if "DECOUPLED_LM" not in source.bspx_lumps and before[5:9] != after[5:9]:
            _fail(f"face {face_index} classic light-style IDs changed unexpectedly")

    for name, payload in source.bspx_lumps.items():
        if name in _REWRITABLE_BSPX:
            continue
        if exported.bspx_lumps.get(name) != payload:
            _fail(f"unrelated BSPX lump {name} was not preserved")

    classic_required = _validate_classic_lightmaps(exported, "exported")
    source_rgb = source.bspx_lumps.get('RGBLIGHTING')
    base_sample_count = max(
        len(source.lumps[bsp.LUMP_LIGHTING]),
        len(source_rgb) // 3 if source_rgb is not None and len(source_rgb) % 3 == 0 else 0,
    )
    preserved_decoupled = (
        source.bspx_lumps.get("DECOUPLED_LM") is not None
        and exported.bspx_lumps.get("DECOUPLED_LM") == source.bspx_lumps.get("DECOUPLED_LM")
    )
    enhanced_samples = _validate_enhanced_lightmaps(
        exported, classic_required, base_sample_count,
        require_appended=not preserved_decoupled,
    )
    rgb_payload = exported.bspx_lumps.get("RGBLIGHTING")
    if rgb_payload is not None and enhanced_samples is None:
        if len(rgb_payload) % 3:
            _fail("classic BSPX RGBLIGHTING payload is not a complete sequence of RGB samples")
        classic_lighting = exported.lumps[bsp.LUMP_LIGHTING]
        if classic_lighting and len(rgb_payload) != len(classic_lighting) * 3:
            _fail(
                "classic BSPX RGBLIGHTING must contain one RGB triplet per "
                "classic LIGHTING sample"
            )

    if lit_data is not None:
        classic_lighting = exported.lumps[bsp.LUMP_LIGHTING]
        if classic_lighting:
            rgb = bsp.parse_lit_file(lit_data, len(classic_lighting))
            if rgb is None:
                _fail("external .lit sidecar is not valid QLIT v1 data for the classic LIGHTING lump")
        else:
            _fail("external .lit sidecar was supplied but the classic LIGHTING lump is empty")

    return {
        "faces": len(exported_faces),
        "textures": len(exported_textures),
        "texinfos": len(exported.lumps[bsp.LUMP_TEXINFO]) // bsp.SIZE_TEXINFO,
        "classic_lighting_bytes": len(exported.lumps[bsp.LUMP_LIGHTING]),
        "classic_required_samples": classic_required,
        "enhanced_lighting_samples": enhanced_samples,
        "bspx_lumps": tuple(sorted(exported.bspx_lumps)),
        "external_lit": lit_data is not None,
    }


def validate_export_pair(
    source_path: str,
    exported_path: str,
    lit_path: Optional[str] = None,
) -> dict:
    """Read and validate source/export files, auto-detecting a sibling .lit file."""
    with open(source_path, "rb") as handle:
        source_data = handle.read()
    with open(exported_path, "rb") as handle:
        exported_data = handle.read()
    if lit_path is None:
        candidate = os.path.splitext(exported_path)[0] + ".lit"
        if os.path.isfile(candidate):
            lit_path = candidate
    lit_data = None
    if lit_path:
        with open(lit_path, "rb") as handle:
            lit_data = handle.read()
    return validate_export_bytes(source_data, exported_data, lit_data)
