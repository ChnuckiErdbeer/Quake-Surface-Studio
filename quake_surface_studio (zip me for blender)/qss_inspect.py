#!/usr/bin/env python3
"""Inspect and validate a classic Quake BSP29, BSPX RGBLIGHTING and optional QLIT sidecar.

Usage:
    python qss_inspect.py path/to/map.bsp
    python qss_inspect.py path/to/map.bsp --lit path/to/map.lit
"""
from __future__ import annotations

import argparse
import os
import sys

import bsp
import lighting


def _face_luxel_samples(parsed, face, rgb_data):
    """Extract summed RGB luxels for one classic BSP29 face."""
    vertices = parsed.vertices()
    edges = parsed.edges()
    surfedges = parsed.surfedges()
    texinfos = parsed.texinfos()
    texinfo_id = int(face[4])
    if texinfo_id < 0 or texinfo_id >= len(texinfos):
        return [], []
    lightofs = int(face[9])
    styles = [int(value) for value in face[5:9] if int(value) != 255]
    if lightofs < 0 or not styles:
        return styles, []
    vertex_ids = parsed.face_vertex_indices(face, edges, surfedges)
    positions = [vertices[index] for index in vertex_ids]
    texinfo = texinfos[texinfo_id]
    s_values = [p[0]*texinfo[0] + p[1]*texinfo[1] + p[2]*texinfo[2] + texinfo[3] for p in positions]
    t_values = [p[0]*texinfo[4] + p[1]*texinfo[5] + p[2]*texinfo[6] + texinfo[7] for p in positions]
    import math
    s_min = math.floor(min(s_values) / 16.0 + 1e-7) * 16
    t_min = math.floor(min(t_values) / 16.0 + 1e-7) * 16
    s_max = math.ceil(max(s_values) / 16.0 - 1e-7) * 16
    t_max = math.ceil(max(t_values) / 16.0 - 1e-7) * 16
    width = ((s_max - s_min) >> 4) + 1
    height = ((t_max - t_min) >> 4) + 1
    count = width * height
    mono = parsed.lumps[bsp.LUMP_LIGHTING]
    return styles, lighting.combine_style_samples(mono, rgb_data, lightofs, count, styles)


def face_lighting_report(parsed, rgb_data):
    faces = parsed.faces()
    rows = []
    chromatic_faces = 0
    gradient_faces = 0
    for face_id, face in enumerate(faces):
        styles, samples = _face_luxel_samples(parsed, face, rgb_data)
        if not samples:
            continue
        chroma = max((max(sample) - min(sample) for sample in samples), default=0)
        luminances = [0.2126*r + 0.7152*g + 0.0722*b for r, g, b in samples]
        gradient = max(luminances) - min(luminances) if luminances else 0.0
        is_chromatic = chroma >= 12
        is_gradient = gradient >= 3
        chromatic_faces += int(is_chromatic)
        gradient_faces += int(is_gradient)
        mean = tuple(sum(sample[channel] for sample in samples) / len(samples) for channel in range(3))
        rows.append((face_id, styles, int(face[9]), len(samples), is_chromatic, is_gradient,
                     mean, chroma, gradient))
    return rows, chromatic_faces, gradient_faces


def inspect(path: str, lit_path: str | None = None, face_lighting: bool = False) -> int:
    parsed = bsp.BSP29.from_file(path)
    vertices = parsed.vertices()
    edges = parsed.edges()
    surfedges = parsed.surfedges()
    texinfos = parsed.texinfos()
    faces = parsed.faces()
    textures = parsed.miptextures()

    problems: list[str] = []
    lightmapped = 0
    style_faces = [0, 0, 0, 0]
    for face_id, face in enumerate(faces):
        texinfo_id = face[4]
        if texinfo_id < 0 or texinfo_id >= len(texinfos):
            problems.append(f"face {face_id}: texinfo index {texinfo_id} is out of range")
            continue
        miptex_id = texinfos[texinfo_id][8]
        if miptex_id < -1 or miptex_id >= len(textures):
            problems.append(f"face {face_id}: miptex index {miptex_id} is out of range")
        try:
            indices = parsed.face_vertex_indices(face, edges, surfedges)
            if any(i >= len(vertices) for i in indices):
                problems.append(f"face {face_id}: vertex index is out of range")
        except bsp.BSPError as exc:
            problems.append(f"face {face_id}: {exc}")
        styles = face[5:9]
        if face[9] >= 0 and styles[0] != 255:
            lightmapped += 1
            for style_index, style in enumerate(styles):
                if style != 255:
                    style_faces[style_index] += 1

    print(f"File:       {os.path.abspath(path)}")
    print(f"Format:     Quake BSP{bsp.BSP_VERSION}")
    print(f"Size:       {os.path.getsize(path):,} bytes")
    print(f"Vertices:   {len(vertices):,}")
    print(f"Edges:      {len(edges):,}")
    print(f"Surfedges:  {len(surfedges):,}")
    print(f"Faces:      {len(faces):,}")
    print(f"Texinfos:   {len(texinfos):,}")
    print(f"Miptexes:   {len(textures):,} ({sum(t.blob is not None for t in textures):,} embedded)")
    print(f"Lighting:   {len(parsed.lumps[bsp.LUMP_LIGHTING]):,} bytes")
    print(f"BSPX:       {', '.join(sorted(parsed.bspx_lumps)) if parsed.bspx_lumps else 'none'}")
    rgb = parsed.bspx_lumps.get("RGBLIGHTING")
    rgb_valid = False
    if rgb is not None:
        rgb_valid = (len(rgb) % 3 == 0 and
                     (not parsed.lumps[bsp.LUMP_LIGHTING] or len(rgb) == 3 * len(parsed.lumps[bsp.LUMP_LIGHTING])))
        if rgb_valid:
            print(f"RGB light:  BSPX RGBLIGHTING valid ({len(rgb) // 3:,} samples)")
        else:
            problems.append("BSPX RGBLIGHTING has an invalid or size-mismatched sample count")
            print(f"RGB light:  INVALID ({len(rgb):,} bytes)")
    print(f"Lightmapped faces: {lightmapped:,}; faces by style slot: {style_faces}")

    if lit_path is None:
        lit_path = os.path.splitext(path)[0] + ".lit"
    if rgb_valid:
        print("QLIT:       BSPX RGBLIGHTING is the active in-BSP RGB source")
    elif os.path.isfile(lit_path):
        sidecar_rgb = bsp.load_lit_file(lit_path, len(parsed.lumps[bsp.LUMP_LIGHTING]))
        if sidecar_rgb is None:
            problems.append(f"invalid or size-mismatched QLIT v1 sidecar: {lit_path}")
            print(f"QLIT:       INVALID ({lit_path})")
        else:
            print(f"QLIT:       valid v1 ({len(sidecar_rgb) // 3:,} RGB samples) — {lit_path}")
    else:
        print("QLIT:       no sidecar or BSPX RGBLIGHTING found")

    rgb_data, rgb_source = bsp.resolve_rgb_lighting(parsed.bspx_lumps,
                                                     parsed.lumps[bsp.LUMP_LIGHTING],
                                                     lit_path)
    if face_lighting and rgb_data is not None:
        rows, chromatic_count, gradient_count = face_lighting_report(parsed, rgb_data)
        print(f"\nRGB luxel coverage ({rgb_source}): {len(rows)} faces with samples; "
              f"{gradient_count} brightness-gradient; {chromatic_count} chromatic")
        for face_id, styles, lightofs, samples, chromatic, gradient, mean, chroma, grad in rows:
            print("  face {:3d}: styles={} lightofs={} luxels={} chromatic={} gradient={} "
                  "mean=({:.1f},{:.1f},{:.1f}) max_channel_spread={:.1f} luma_range={:.1f}".format(
                      face_id, styles, lightofs, samples, int(chromatic), int(gradient),
                      *mean, chroma, grad))

    entities = bsp.parse_entities_lump(parsed.lumps[bsp.LUMP_ENTITIES])
    worldspawn = next((entity for entity in entities if entity.get('classname', '').lower() == 'worldspawn'), {})
    print("\nWorld lighting settings:")
    for key, default in (('_bounce', '0 (off)'), ('_bouncescale', '1'),
                         ('_bouncecolorscale', '0'), ('_gamma', '1'),
                         ('_minlight', '0'), ('_dist', '1'), ('_range', '1')):
        print(f"  {key}: {worldspawn.get(key, default)}")

    print("\nLight entities:")
    malformed_style_entities = []
    for entity_id, entity in enumerate(entities):
        classname = entity.get('classname', '').lower()
        if not classname.startswith('light'):
            continue
        origin = entity.get('origin', '?')
        style, inferred = lighting.infer_entity_style(entity)
        raw_light = entity.get('light', '300 (default)')
        raw_color = entity.get('_color', '') or '(white/default)'
        delay = entity.get('delay', '0 (linear/default)')
        wait = entity.get('wait', '1 (default)')
        print(f"  entity {entity_id}: {classname} origin={origin} light={raw_light} color={raw_color} style={style}"
              f"{' [inferred from empty key]' if inferred else ''} delay={delay} wait={wait}")
        if '' in entity and 'style' not in entity:
            malformed_style_entities.append((entity_id, origin, entity.get(''))
            )
    if malformed_style_entities:
        print("\nMalformed light style key(s):")
        for entity_id, origin, value in malformed_style_entities:
            print(f"  entity {entity_id} at {origin}: empty key has value {value!r}; MAP should use \"style\" \"{value}\"")

    if problems:
        print(f"\nValidation: {len(problems)} problem(s)")
        for problem in problems[:100]:
            print(f"  - {problem}")
        if len(problems) > 100:
            print(f"  ... and {len(problems) - 100} more")
        return 1
    print("\nValidation: no structural reference problems found")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bsp_file", help="classic Quake BSP29 file")
    parser.add_argument("--lit", dest="lit_file", help="optional QLIT v1 sidecar (default: sibling .lit)")
    parser.add_argument("--face-lighting", action="store_true",
                        help="print per-face RGB luxel/style coverage for diagnosing lightmaps")
    args = parser.parse_args()
    try:
        return inspect(args.bsp_file, args.lit_file, args.face_lighting)
    except (OSError, bsp.BSPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
