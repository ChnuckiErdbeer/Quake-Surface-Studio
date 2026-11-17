#!/usr/bin/env python3
"""Read-only comparison of the original Nightdive E1M1 BSP and the ericw rebuild."""
from __future__ import annotations
import json
import math
import re
import struct
import sys
from pathlib import Path

TARGET = (-80.0, 640.0, 96.0)
TARGET_FACE = 5828

LUMP_NAMES = [
    "entities", "planes", "textures", "vertices", "visibility", "nodes",
    "texinfo", "faces", "lighting", "clipnodes", "leaves", "marksurfaces",
    "edges", "surfedges", "models",
]

def add(a, b): return tuple(x + y for x, y in zip(a, b))
def sub(a, b): return tuple(x - y for x, y in zip(a, b))
def mul(a, s): return tuple(x * s for x in a)
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def length(a): return math.sqrt(dot(a, a))
def normalize(a):
    n = length(a)
    return mul(a, 1.0/n) if n > 1e-20 else (0.0, 0.0, 0.0)
def finite_vec(v): return all(math.isfinite(x) for x in v)

def closest_point_triangle(p, a, b, c):
    # Ericson's closest-point-on-triangle algorithm.
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0: return a
    bp = sub(p, b); d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3: return b
    vc = d1*d4 - d3*d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return add(a, mul(ab, d1/(d1-d3)))
    cp = sub(p, c); d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6: return c
    vb = d5*d2 - d1*d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return add(a, mul(ac, d2/(d2-d6)))
    va = d3*d6 - d5*d4
    if va <= 0 and (d4-d3) >= 0 and (d5-d6) >= 0:
        return add(b, mul(sub(c, b), (d4-d3)/((d4-d3)+(d5-d6))))
    denom = 1.0/(va+vb+vc)
    return add(a, add(mul(ab, vb*denom), mul(ac, vc*denom)))

def polygon_distance(p, verts):
    if len(verts) < 3: return float("inf")
    return min(length(sub(p, closest_point_triangle(p, verts[0], verts[i], verts[i+1])))
               for i in range(1, len(verts)-1))

def parse_entities(data):
    text = data.split(b"\0", 1)[0].decode("latin1", errors="replace")
    result = []
    for block in re.findall(r"\{([^{}]*)\}", text, re.S):
        kv = dict(re.findall(r'"([^"]+)"\s+"([^"]*)"', block))
        if kv: result.append(kv)
    return result

def parse_textures(data):
    if len(data) < 4: return []
    count = struct.unpack_from("<i", data, 0)[0]
    if count < 0 or count > 100000 or 4 + 4*count > len(data): return []
    names = []
    for i in range(count):
        off = struct.unpack_from("<i", data, 4 + 4*i)[0]
        if off < 0 or off + 40 > len(data):
            names.append("")
            continue
        raw = data[off:off+16].split(b"\0", 1)[0]
        names.append(raw.decode("latin1", errors="replace"))
    return names

def parse_bsp(path):
    data = Path(path).read_bytes()
    if len(data) < 124: raise ValueError(f"{path}: BSP header truncated ({len(data)} bytes)")
    version = struct.unpack_from("<i", data, 0)[0]
    lumps = {}
    lump_summary = {}
    for i, name in enumerate(LUMP_NAMES):
        off, size = struct.unpack_from("<ii", data, 4 + i*8)
        if off < 0 or size < 0 or off + size > len(data):
            raise ValueError(f"{path}: invalid {name} lump range {off}+{size}, file size {len(data)}")
        lumps[name] = data[off:off+size]
        lump_summary[name] = {"offset": off, "bytes": size}
    if version != 29:
        raise ValueError(f"{path}: expected Quake BSP29, found version {version}")

    plane_data = lumps["planes"]
    planes = [struct.unpack_from("<4fi", plane_data, i)
              for i in range(0, len(plane_data)-19, 20)]
    vertex_data = lumps["vertices"]
    vertices = [struct.unpack_from("<3f", vertex_data, i)
                for i in range(0, len(vertex_data)-11, 12)]
    edge_data = lumps["edges"]
    edges = [struct.unpack_from("<2H", edge_data, i)
             for i in range(0, len(edge_data)-3, 4)]
    surfedge_data = lumps["surfedges"]
    surfedges = [x[0] for x in struct.iter_unpack("<i", surfedge_data[:len(surfedge_data)//4*4])]
    texinfo_data = lumps["texinfo"]
    texinfos = [struct.unpack_from("<8fii", texinfo_data, i)
                for i in range(0, len(texinfo_data)-39, 40)]
    texture_names = parse_textures(lumps["textures"])

    faces = []
    face_data = lumps["faces"]
    bad_face_refs = []
    bad_poly_faces = []
    nonfinite_faces = []
    for fi, off in enumerate(range(0, len(face_data)-19, 20)):
        planenum, side, firstedge, numedges, texnum, styles0, styles1, styles2, styles3, lightofs = struct.unpack_from("<Hhihh4Bi", face_data, off)
        style_bytes = (styles0, styles1, styles2, styles3)
        styles = []
        for s in style_bytes:
            if s == 255: break
            styles.append(s)
        problems = []
        if planenum >= len(planes): problems.append("plane_index")
        if texnum < 0 or texnum >= len(texinfos): problems.append("texinfo_index")
        if firstedge < 0 or numedges < 0 or firstedge + numedges > len(surfedges): problems.append("surfedge_range")
        polygon = []
        if not problems:
            for se in surfedges[firstedge:firstedge+numedges]:
                ei = abs(se)
                if ei >= len(edges):
                    problems.append("edge_index")
                    break
                edge = edges[ei]
                vi = edge[0] if se >= 0 else edge[1]
                if vi >= len(vertices):
                    problems.append("vertex_index")
                    break
                polygon.append(tuple(float(x) for x in vertices[vi]))
        if problems:
            bad_face_refs.append({"face": fi, "problems": problems})
        pnormal, pdist = (tuple(planes[planenum][:3]), float(planes[planenum][3])) if planenum < len(planes) else ((0,0,0), 0.0)
        if side:
            pnormal, pdist = mul(pnormal, -1.0), -pdist
        if polygon and (not all(finite_vec(v) for v in polygon) or not finite_vec(pnormal) or not math.isfinite(pdist)):
            nonfinite_faces.append(fi)
        edge_lengths = [length(sub(polygon[(j+1)%len(polygon)], polygon[j])) for j in range(len(polygon))] if polygon else []
        repeats = sum(1 for x in edge_lengths if x < 1e-6)
        plane_errors = [abs(dot(pnormal, v)-pdist) for v in polygon] if polygon else []
        max_plane_error = max(plane_errors, default=0.0)
        area_vec = (0.0, 0.0, 0.0)
        if len(polygon) >= 3:
            for j, v in enumerate(polygon):
                area_vec = add(area_vec, cross(v, polygon[(j+1)%len(polygon)]))
        area = 0.5 * abs(dot(normalize(pnormal), area_vec)) if length(pnormal) > 0 else 0.0
        centroid = tuple(sum(v[k] for v in polygon)/len(polygon) for k in range(3)) if polygon else (0,0,0)
        texname = ""
        extents = None
        if 0 <= texnum < len(texinfos) and polygon:
            ti = texinfos[texnum]
            texname = texture_names[ti[8]] if 0 <= ti[8] < len(texture_names) else ""
            st = [(dot(tuple(ti[0:3]), v)+ti[3], dot(tuple(ti[4:7]), v)+ti[7]) for v in polygon]
            smin, smax = min(p[0] for p in st), max(p[0] for p in st)
            tmin, tmax = min(p[1] for p in st), max(p[1] for p in st)
            s0, s1 = math.floor(smin/16)*16, math.ceil(smax/16)*16
            t0, t1 = math.floor(tmin/16)*16, math.ceil(tmax/16)*16
            sw, th = int(round((s1-s0)/16))+1, int(round((t1-t0)/16))+1
            extents = {"s": [round(s0,4), round(s1,4)], "t": [round(t0,4), round(t1,4)],
                       "luxel_dimensions": [sw, th], "luxel_count_per_style": sw*th}
        sample_count = (extents["luxel_count_per_style"]*len(styles)) if extents else 0
        lighting_len = len(lumps["lighting"])
        light_range_ok = (lightofs < 0) or (lightofs + sample_count <= lighting_len)
        face = {
            "index": fi, "plane_index": planenum, "side": side,
            "normal": pnormal, "plane_dist": pdist, "firstedge": firstedge,
            "numedges": numedges, "texinfo": texnum, "texture": texname,
            "styles": styles, "lightofs": lightofs, "sample_count_estimate": sample_count,
            "light_range_ok": light_range_ok, "extents": extents,
            "polygon": polygon, "centroid": centroid, "area": area,
            "bbox": [[min(v[k] for v in polygon), max(v[k] for v in polygon)] for k in range(3)] if polygon else [],
            "min_edge": min(edge_lengths, default=0.0), "zero_edges": repeats,
            "max_plane_error": max_plane_error,
            "target_plane_distance": abs(dot(pnormal, TARGET)-pdist) if finite_vec(pnormal) else float("inf"),
            "target_polygon_distance": polygon_distance(TARGET, polygon),
        }
        faces.append(face)
        if polygon and (len(polygon) < 3 or repeats or area < 1e-8 or max_plane_error > 0.05 or not light_range_ok):
            bad_poly_faces.append({"face": fi, "numedges": numedges, "zero_edges": repeats,
                                   "area": area, "max_plane_error": max_plane_error,
                                   "lightofs": lightofs, "sample_count": sample_count,
                                   "light_range_ok": light_range_ok, "texture": texname})
    entity_list = parse_entities(lumps["entities"])
    lights = []
    for i, ent in enumerate(entity_list):
        if ent.get("classname", "").startswith("light"):
            origin = tuple(float(x) for x in ent.get("origin", "0 0 0").split()[:3]) if ent.get("origin") else None
            d = length(sub(origin, TARGET)) if origin and len(origin)==3 else None
            lights.append({
                "entity_index": i, "classname": ent.get("classname"), "origin": ent.get("origin"),
                "light": ent.get("light"), "delay": ent.get("delay"), "wait": ent.get("wait"),
                "color": ent.get("_color", ent.get("color")), "mangle": ent.get("mangle"),
                "target": ent.get("target"), "angle": ent.get("angle"), "distance_to_sample": d,
            })
    lights.sort(key=lambda x: x["distance_to_sample"] if x["distance_to_sample"] is not None else 1e30)
    target_faces = sorted(faces, key=lambda f: (f["target_polygon_distance"], f["target_plane_distance"]))[:12]
    bad_lighting = [f for f in faces if f["lightofs"] >= 0 and not f["light_range_ok"]]
    result = {
        "path": str(path), "file_bytes": len(data), "version": version,
        "lumps": lump_summary,
        "counts": {
            "planes": len(planes), "vertices": len(vertices), "edges": len(edges),
            "surfedges": len(surfedges), "texinfo": len(texinfos), "faces": len(faces),
            "lights": len(lights), "entities": len(entity_list),
            "nonfinite_vertices": sum(1 for v in vertices if not finite_vec(v)),
            "bad_face_references": len(bad_face_refs), "bad_light_ranges": len(bad_lighting),
            "degenerate_or_suspicious_faces": len(bad_poly_faces),
        },
        "face_5828": faces[TARGET_FACE] if len(faces) > TARGET_FACE else None,
        "nearest_faces_to_failure_position": target_faces,
        "nearest_lights": lights[:12],
        "blue_spotlights": [x for x in lights if x["mangle"] and x["color"] and ("181 238 255" in x["color"] or "0.7098" in x["color"])],
        "bad_face_references_sample": bad_face_refs[:20],
        "nonfinite_faces_sample": nonfinite_faces[:30],
        "suspicious_faces_sample": bad_poly_faces[:30],
    }
    result["_all_faces"] = faces
    return result

def lit_summary(path, bsp):
    data = Path(path).read_bytes()
    if len(data) < 8:
        return {"path": str(path), "bytes": len(data), "error": "short QLIT file"}
    magic, version = data[:4], struct.unpack_from("<i", data, 4)[0]
    rgb_bytes = len(data)-8
    light_bytes = bsp["lumps"]["lighting"]["bytes"]
    return {"path": str(path), "bytes": len(data), "magic": magic.decode("latin1"),
            "version": version, "rgb_payload_bytes": rgb_bytes,
            "bsp_lightdata_bytes": light_bytes,
            "rgb_triplets_match_bsp_lightdata": rgb_bytes == light_bytes*3}

def clean_face(face):
    if face is None: return None
    return {k: v for k, v in face.items() if k != "polygon"}

def compare_faces(original, rebuilt):
    src = original["face_5828"]
    if not src: return {"error": "original does not contain face 5828"}
    src_centroid = src["centroid"]
    candidates = []
    for f in rebuilt["_all_faces"]:
        if not f["polygon"] or f["numedges"] < 3: continue
        n_dot = abs(dot(normalize(src["normal"]), normalize(f["normal"])))
        if n_dot < 0.95: continue
        plane_delta = min(abs(dot(normalize(src["normal"]), f["centroid"])-src["plane_dist"]),
                          abs(dot(normalize(src["normal"]), f["centroid"])+src["plane_dist"]))
        poly_dist = polygon_distance(src_centroid, f["polygon"])
        candidates.append({"face": f["index"], "texture": f["texture"], "normal_alignment_abs": n_dot,
                           "centroid_distance": length(sub(src_centroid, f["centroid"])),
                           "source_centroid_to_candidate_polygon": poly_dist,
                           "plane_delta_at_candidate_centroid": plane_delta,
                           "target_polygon_distance": f["target_polygon_distance"],
                           "numedges": f["numedges"], "area": f["area"]})
    candidates.sort(key=lambda x: (x["source_centroid_to_candidate_polygon"], x["centroid_distance"]))
    return candidates[:12]

def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value

def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: analyze_e1m1_bsp_pair.py ORIGINAL.bsp ORIGINAL.lit REBUILT.bsp REBUILT.lit")
    original = parse_bsp(sys.argv[1])
    rebuilt = parse_bsp(sys.argv[3])
    face_matches = compare_faces(original, rebuilt)
    report = {
        "target_world_quake": TARGET,
        "original": {k: v for k, v in original.items() if k != "_all_faces"},
        "original_lit": lit_summary(sys.argv[2], original),
        "rebuilt": {k: v for k, v in rebuilt.items() if k != "_all_faces"},
        "rebuilt_lit": lit_summary(sys.argv[4], rebuilt),
        "original_face_5828_matches_in_rebuild": face_matches,
    }
    out = json.dumps(json_safe(report), indent=2, allow_nan=False)
    Path("e1m1-bsp-comparison.json").write_text(out, encoding="utf-8")
    print(out)

if __name__ == "__main__":
    main()
