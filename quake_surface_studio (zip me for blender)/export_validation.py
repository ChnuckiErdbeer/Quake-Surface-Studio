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
    from . import bsp
except ImportError:  # executed as a stand-alone script / unittest module
    import bsp


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


def _validate_enhanced_lightmaps(parsed: bsp.BSP29, classic_required: int, base_sample_count: int) -> Optional[int]:
    extensions = parsed.bspx_lumps
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
        if shift > 4:
            _fail(f"face {face_index} has unsupported LMSHIFT value {shift}")
        offset = struct.unpack_from("<I", offsets, face_index * 4)[0]
        style = int(styles[face_index])
        if offset == _NO_LIGHT_OFFSET or style == 255:
            if offset != _NO_LIGHT_OFFSET or style != 255:
                _fail(f"face {face_index} has inconsistent no-light metadata")
            continue
        if offset < classic_required:
            _fail(
                f"face {face_index} enhanced lightmap offset {offset} overlaps "
                f"the classic sample range ending at {classic_required}"
            )
        width, height = _face_lightmap_dimensions(parsed, face, 1 << shift)
        if width > 256 or height > 256:
            _fail(
                f"face {face_index} enhanced lightmap is {width}x{height}; "
                "BSPX LMSHIFT surfaces are limited to 256 luxels per axis"
            )
        end = offset + width * height
        if end > rgb_samples:
            _fail(
                f"face {face_index} enhanced lightmap ends at sample {end}, "
                f"but RGBLIGHTING contains only {rgb_samples} samples"
            )
        spans.append((offset, end, face_index))

    cursor = base_sample_count
    for start, end, face_index in sorted(spans):
        if start != cursor:
            _fail(
                f"face {face_index} enhanced lightmap starts at sample {start}; "
                f"expected contiguous sample offset {cursor} (overlap or gap)"
            )
        cursor = end
    if cursor != rgb_samples:
        _fail(
            f"enhanced RGBLIGHTING has {rgb_samples} samples but face ranges "
            f"consume {cursor}"
        )
    return rgb_samples - base_sample_count


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
        stable_fields_before = (before[0], before[1], before[2], before[3], before[5:9], before[9])
        stable_fields_after = (after[0], after[1], after[2], after[3], after[5:9], after[9])
        if stable_fields_before != stable_fields_after:
            _fail(f"face {face_index} geometry/light-style offsets changed unexpectedly")

    for name, payload in source.bspx_lumps.items():
        if name in _REWRITABLE_BSPX:
            continue
        if exported.bspx_lumps.get(name) != payload:
            _fail(f"unrelated BSPX lump {name} was not preserved")

    classic_required = _validate_classic_lightmaps(exported, "exported")
    source_rgb = source.bspx_lumps.get('RGBLIGHTING')
    base_sample_count = len(source.lumps[bsp.LUMP_LIGHTING])
    if base_sample_count == 0 and source_rgb is not None and len(source_rgb) % 3 == 0:
        base_sample_count = len(source_rgb) // 3
    enhanced_samples = _validate_enhanced_lightmaps(exported, classic_required, base_sample_count)
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
