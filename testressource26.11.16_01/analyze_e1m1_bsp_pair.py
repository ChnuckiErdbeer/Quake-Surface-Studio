#!/usr/bin/env python3
"""Read-only comparison of the original Nightdive E1M1 BSP and the ericw rebuild."""
from __future__ import annotations
import hashlib
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

def closest_point_segment(p, a, b):
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom <= 1e-20:
        return a
    t = max(0.0, min(1.0, dot(sub(p, a), ab)/denom))
    return add(a, mul(ab, t))

def closest_point_triangle(p, a, b, c):
    # Ericson's closest-point-on-triangle algorithm, with a degenerate fallback.
    ab, ac = sub(b, a), sub(c, a)
    if length(cross(ab, ac)) <= 1e-12:
        candidates = (closest_point_segment(p, a, b),
                      closest_point_segment(p, b, c),
                      closest_point_segment(p, c, a))
        return min(candidates, key=lambda q: length(sub(p, q)))
    ap = sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0: return a
    bp = sub(p, b); d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3: return b
    vc = d1*d4 - d3*d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        denom = d1-d3
        return add(a, mul(ab, d1/denom if abs(denom) > 1e-20 else 0.0))
    cp = sub(p, c); d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6: return c
    vb = d5*d2 - d1*d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        denom = d2-d6
        return add(a, mul(ac, d2/denom if abs(denom) > 1e-20 else 0.0))
    va = d3*d6 - d5*d4
    if va <= 0 and (d4-d3) >= 0 and (d5-d6) >= 0:
        denom = (d4-d3)+(d5-d6)
        return add(b, mul(sub(c, b), (d4-d3)/denom if abs(denom) > 1e-20 else 0.0))
    denom = va+vb+vc
    if abs(denom) <= 1e-20:
        candidates = (closest_point_segment(p, a, b),
                      closest_point_segment(p, b, c),
                      closest_point_segment(p, c, a))
        return min(candidates, key=lambda q: length(sub(p, q)))
    inv_denom = 1.0/denom
    return add(a, add(mul(ab, vb*inv_denom), mul(ac, vc*inv_denom)))

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

def parse_texture_metadata(data):
    if len(data) < 4: return []
    count = struct.unpack_from("<i", data, 0)[0]
    if count < 0 or count > 100000 or 4 + 4*count > len(data): return []
    result = []
    for i in range(count):
        mip_off = struct.unpack_from("<i", data, 4 + 4*i)[0]
        if mip_off < 0 or mip_off + 40 > len(data):
            result.append({"name": "", "width": 0, "height": 0, "sha256": None})
            continue
        name_raw, width, height, *mip_offsets = struct.unpack_from("<16s6I", data, mip_off)
        name = name_raw.split(b"\\0", 1)[0].decode("latin1", errors="replace")
        chunks = []
        valid = True
        for level, rel_off in enumerate(mip_offsets):
            if rel_off == 0: continue
            w, h = max(1, width >> level), max(1, height >> level)
            length = w*h
            start = mip_off + rel_off
            if start < mip_off or start + length > len(data):
                valid = False
                break
            chunks.append(data[start:start+length])
        digest = hashlib.sha256(b"".join(chunks)).hexdigest() if valid and chunks else None
        result.append({"name": name, "width": width, "height": height,
                       "sha256": digest, "mip_offsets": mip_offsets, "valid": valid})
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

def polygon_topology_metrics(polygon, normal):
    if len(polygon) < 3:
        return {"concave": False, "concave_turns": 0, "collinear_turns": 0,
                "self_intersections": 0, "repeated_vertices": 0, "winding_dot": 0.0}
    axis = max(range(3), key=lambda i: abs(normal[i]))
    axes = [i for i in range(3) if i != axis]
    points = [(float(p[axes[0]]), float(p[axes[1]])) for p in polygon]
    n = len(points)
    cross_values = []
    eps = 1e-6
    for i in range(n):
        a, b, c = points[i-1], points[i], points[(i+1) % n]
        cross_values.append((b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]))
    positive = sum(1 for value in cross_values if value > eps)
    negative = sum(1 for value in cross_values if value < -eps)
    collinear = sum(1 for value in cross_values if abs(value) <= eps)
    concave_turns = min(positive, negative) if positive and negative else 0

    def orient(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    def on_segment(a, b, p):
        return (min(a[0], b[0])-eps <= p[0] <= max(a[0], b[0])+eps
                and min(a[1], b[1])-eps <= p[1] <= max(a[1], b[1])+eps)
    def intersects(a, b, c, d):
        o1, o2, o3, o4 = orient(a,b,c), orient(a,b,d), orient(c,d,a), orient(c,d,b)
        if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
            return True
        return ((abs(o1) <= eps and on_segment(a,b,c))
                or (abs(o2) <= eps and on_segment(a,b,d))
                or (abs(o3) <= eps and on_segment(c,d,a))
                or (abs(o4) <= eps and on_segment(c,d,b)))
    crossings = 0
    for i in range(n):
        a, b = points[i], points[(i+1)%n]
        for j in range(i+1, n):
            if j == i or j == (i+1)%n or (j+1)%n == i:
                continue
            c, d = points[j], points[(j+1)%n]
            if intersects(a,b,c,d):
                crossings += 1

    repeated = 0
    for i in range(n):
        for j in range(i+1, n):
            if math.hypot(points[i][0]-points[j][0], points[i][1]-points[j][1]) <= eps:
                repeated += 1

    area_vec = (0.0, 0.0, 0.0)
    for i, vertex in enumerate(polygon):
        area_vec = add(area_vec, cross(vertex, polygon[(i+1)%n]))
    winding_dot = dot(area_vec, normal)
    return {
        "concave": bool(concave_turns),
        "concave_turns": int(concave_turns),
        "collinear_turns": int(collinear),
        "self_intersections": int(crossings),
        "repeated_vertices": int(repeated),
        "winding_dot": float(winding_dot),
    }

def world_plane_frame(plane_normal, plane_distance, side=0):
    sign = -1.0 if int(side) else 1.0
    normal = [float(value)*sign for value in plane_normal]
    distance = float(plane_distance)*sign
    nlen = length(normal)
    if not math.isfinite(nlen) or nlen <= 1e-12 or not math.isfinite(distance):
        raise ValueError("Invalid plane")
    normal = [value/nlen for value in normal]
    distance /= nlen
    major = max(range(3), key=lambda index: (abs(normal[index]), -index))
    if normal[major] < 0:
        normal = [-value for value in normal]
        distance = -distance
    axes = ((1.0,0.0,0.0),(0.0,1.0,0.0),(0.0,0.0,1.0))
    projected = []
    for axis_index, reference in enumerate(axes):
        d = dot(normal, reference)
        tangent = tuple(reference[i]-normal[i]*d for i in range(3))
        projected.append((dot(tangent,tangent),-axis_index,tangent))
    tangent_len_sq, _order, tangent = max(projected,key=lambda item:(item[0],item[1]))
    if tangent_len_sq <= 1e-12:
        raise ValueError("No stable plane tangent")
    axis_s = mul(tangent,1.0/math.sqrt(tangent_len_sq))
    axis_t = cross(normal,axis_s)
    return {"normal":tuple(normal),"distance":distance,"axis_s":axis_s,"axis_t":axis_t}

def build_current_qss_world_charts(faces, planes, edges, surfedges, models):
    # Port of lightmap_export.py::build_coplanar_face_charts from the 0.21.21 branch.
    face_model_ids = [None]*len(faces)
    for model_id, model in enumerate(models):
        first, count = int(model[14]), int(model[15])
        for face_id in range(max(0,first), min(len(faces),first+count)):
            face_model_ids[face_id] = model_id
    face_model_ids = [0 if value is None else int(value) for value in face_model_ids]
    records, keys, frames, edge_users = {}, {}, {}, {}
    skip_stats = {
        "input_faces": len(faces), "negative_lightofs": 0, "empty_styles": 0,
        "empty_polygons": 0, "bad_surface_ranges": 0, "bad_plane_indices": 0,
        "plane_frame_errors": {}, "bad_edge_indices": 0, "accepted_faces": 0,
    }
    for face in faces:
        face_id = face["index"]
        if face["lightofs"] < 0:
            skip_stats["negative_lightofs"] += 1
            continue
        if not face["styles"]:
            skip_stats["empty_styles"] += 1
            continue
        if not face["polygon"]:
            skip_stats["empty_polygons"] += 1
            continue
        firstedge, edge_count = face["firstedge"], face["numedges"]
        plane_id = face["plane_index"]
        if firstedge < 0 or edge_count < 3 or firstedge+edge_count > len(surfedges):
            skip_stats["bad_surface_ranges"] += 1
            continue
        if plane_id < 0 or plane_id >= len(planes):
            skip_stats["bad_plane_indices"] += 1
            continue
        try:
            plane = planes[plane_id]
            frame = world_plane_frame(plane[:3],plane[3],face["side"])
        except Exception as exc:
            label = f"{type(exc).__name__}: {exc}"
            skip_stats["plane_frame_errors"][label] = skip_stats["plane_frame_errors"].get(label, 0) + 1
            continue
        plane_key = tuple(round(value/1e-4) for value in (*frame["normal"],frame["distance"]))
        keys[face_id] = (face_model_ids[face_id],tuple(int(v) for v in face["styles"]),plane_key)
        edge_ids, valid = set(), True
        for se in surfedges[firstedge:firstedge+edge_count]:
            edge_id = abs(int(se))
            if edge_id >= len(edges):
                valid=False
                break
            edge_ids.add(edge_id)
        if not valid:
            skip_stats["bad_edge_indices"] += 1
            keys.pop(face_id,None)
            continue
        records[face_id] = face
        skip_stats["accepted_faces"] += 1
        frames[face_id] = frame
        for edge_id in edge_ids:
            edge_users.setdefault(edge_id,[]).append(face_id)
    parent={face_id:face_id for face_id in records}
    def find(face_id):
        while parent[face_id] != face_id:
            parent[face_id]=parent[parent[face_id]]
            face_id=parent[face_id]
        return face_id
    shared_join_edges=0
    for users in edge_users.values():
        if len(users)==2 and keys[users[0]]==keys[users[1]]:
            a,b=find(users[0]),find(users[1])
            if a!=b:
                parent[max(a,b)]=min(a,b)
                shared_join_edges+=1
    components={}
    for face_id in records:
        components.setdefault(find(face_id),[]).append(face_id)
    charts=[]
    face_to_chart={}
    for chart_index,root in enumerate(sorted(components)):
        members=sorted(components[root])
        frame=frames[members[0]]
        projected=[
            (dot(point,frame["axis_s"]),dot(point,frame["axis_t"]))
            for face_id in members for point in records[face_id]["polygon"]
        ]
        s_min=math.floor(min(p[0] for p in projected)/16.0+1e-7)*16
        t_min=math.floor(min(p[1] for p in projected)/16.0+1e-7)*16
        s_max=math.ceil(max(p[0] for p in projected)/16.0-1e-7)*16
        t_max=math.ceil(max(p[1] for p in projected)/16.0-1e-7)*16
        chart_id=len(faces)+chart_index
        chart={"chart_id":chart_id,"face_ids":members,"model_id":face_model_ids[members[0]],
               "styles":records[members[0]]["styles"],"normal":frame["normal"],
               "distance":frame["distance"],"axis_s":frame["axis_s"],"axis_t":frame["axis_t"],
               "s_min":float(s_min),"t_min":float(t_min),"s_max":float(s_max),"t_max":float(t_max),
               "width":int((s_max-s_min)//16+1),"height":int((t_max-t_min)//16+1)}
        charts.append(chart)
        for face_id in members:
            face_to_chart[face_id]=chart_id
    return charts,face_to_chart,shared_join_edges,skip_stats

def pack_current_qss_charts(charts, gutter=2, atlas_sizes=(512,1024,2048)):
    ordered=sorted(charts,key=lambda r:(-r["height"],-r["width"],r["chart_id"]))
    for scale in (2,1):
        for size in atlas_sizes:
            x=y=row_h=0
            placements={}
            failed=False
            for rec in ordered:
                rw=rec["width"]*scale+2*gutter
                rh=rec["height"]*scale+2*gutter
                if rw>size or rh>size:
                    failed=True
                    break
                if x+rw>size:
                    x=0
                    y+=row_h
                    row_h=0
                if y+rh>size:
                    failed=True
                    break
                placements[rec["chart_id"]]=(x,y,rw,rh)
                x+=rw
                row_h=max(row_h,rh)
            if not failed:
                return {"atlas_size":size,"luxel_scale":scale,"gutter":gutter,"placements":placements}
    return {"error":"Atlas pack failed"}

def current_qss_world_chart_report(parsed, target_face_id):
    charts,face_to_chart,shared_edges,skip_stats=build_current_qss_world_charts(
        parsed["_all_faces"],parsed["_planes"],parsed["_edges"],parsed["_surfedges"],parsed["_models"])
    pack=pack_current_qss_charts(charts)
    chart_id=face_to_chart.get(int(target_face_id))
    if chart_id is None:
        return {"target_face":target_face_id,"error":"Target face has no classic world chart",
                "chart_count":len(charts),"shared_coplanar_join_edges":shared_edges,
                "chart_build_skip_stats":skip_stats}
    chart=next(item for item in charts if item["chart_id"]==chart_id)
    rect=pack.get("placements",{}).get(chart_id)
    target=parsed["_all_faces"][int(target_face_id)]
    sx,sy=9,3
    n=target["normal"]
    ti=target["texinfo_vectors"]
    point=None
    if ti is not None and target["extents"]:
        p1,p2=ti
        a,b,c=p1[0],p1[1],p1[2]
        d,e,f=p2[0],p2[1],p2[2]
        g,h,i=n
        det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
        s_value=target["extents"]["s"][0]+sx*16-p1[3]
        t_value=target["extents"]["t"][0]+sy*16-p2[3]
        if abs(det)>1e-12:
            point=[
                (s_value*(e*i-f*h)-b*(t_value*i-f*target["plane_dist"])+c*(t_value*h-e*target["plane_dist"]))/det,
                (a*(t_value*i-f*target["plane_dist"])-s_value*(d*i-f*g)+c*(d*target["plane_dist"]-t_value*g))/det,
                (a*(e*target["plane_dist"]-t_value*h)-b*(d*target["plane_dist"]-t_value*g)+s_value*(d*h-e*g))/det,
            ]
    pixel=None
    if rect and point is not None:
        ws,wt=dot(point,chart["axis_s"]),dot(point,chart["axis_t"])
        px=rect[0]+pack["gutter"]+(((ws-chart["s_min"])/16)+0.5)*pack["luxel_scale"]-0.5
        py=pack["atlas_size"]-1-(rect[1]+pack["gutter"]+(((wt-chart["t_min"])/16)+0.5)*pack["luxel_scale"]-0.5)
        pixel=[px,py]
    member_summary = []
    for member_id in chart["face_ids"]:
        face = parsed["_all_faces"][int(member_id)]
        polygon_chart = [
            [dot(point,chart["axis_s"]),dot(point,chart["axis_t"])]
            for point in face["polygon"]
        ]
        member_summary.append({
            "face":int(member_id),"texture":face["texture"],"numedges":face["numedges"],
            "area":face["area"],"styles":face["styles"],"lightofs":face["lightofs"],
            "extents":face["extents"],"texinfo_vectors":face["texinfo_vectors"],
            "polygon_world":face["polygon"],"polygon_chart":polygon_chart,
            "topology":face["topology"],
            "chart_bbox":[
                min(p[0] for p in polygon_chart),max(p[0] for p in polygon_chart),
                min(p[1] for p in polygon_chart),max(p[1] for p in polygon_chart),
            ] if polygon_chart else None,
        })
    return {
        "target_face":int(target_face_id),"chart_id":chart_id,"chart_face_count":len(chart["face_ids"]),
        "chart_face_ids":chart["face_ids"],"chart_members":member_summary,
        "chart_model_id":chart["model_id"],"chart_styles":chart["styles"],
        "chart_plane_normal":chart["normal"],"chart_plane_distance":chart["distance"],
        "chart_axis_s":chart["axis_s"],"chart_axis_t":chart["axis_t"],
        "chart_world_extents":[chart["s_min"],chart["s_max"],chart["t_min"],chart["t_max"]],
        "chart_luxel_dimensions":[chart["width"],chart["height"]],
        "atlas_size":pack.get("atlas_size"),"luxel_scale":pack.get("luxel_scale"),
        "chart_build_skip_stats":skip_stats,
        "atlas_rectangle":list(rect) if rect else None,"luxel_9_3_world_point":point,
        "luxel_9_3_predicted_pixel":pixel,"shared_coplanar_join_edges":shared_edges,
    }

def simulate_qss_atlas(faces, target_face=TARGET_FACE, atlas_sizes=(512, 1024, 2048), gutter=2):
    # Mirrors addon.py::_pack_lightmap_rectangles ordering and scale fallback.
    records = []
    for face in faces:
        if face["lightofs"] < 0 or not face["styles"] or not face["extents"]:
            continue
        width, height = face["extents"]["luxel_dimensions"]
        records.append({"face_id": face["index"], "width": width, "height": height})
    ordered = sorted(records, key=lambda r: (-r["height"], -r["width"], r["face_id"]))
    for scale in (2, 1):
        for atlas_size in atlas_sizes:
            x = y = row_h = 0
            placements = {}
            failed = False
            for rec in ordered:
                rw = rec["width"] * scale + 2*gutter
                rh = rec["height"] * scale + 2*gutter
                if rw > atlas_size or rh > atlas_size:
                    failed = True
                    break
                if x + rw > atlas_size:
                    x = 0
                    y += row_h
                    row_h = 0
                if y + rh > atlas_size:
                    failed = True
                    break
                placements[rec["face_id"]] = (x, y, rw, rh)
                x += rw
                row_h = max(row_h, rh)
            if not failed:
                target = placements.get(int(target_face))
                near = []
                if target:
                    tx, ty, tw, th = target
                    for face_id, (px, py, pw, ph) in placements.items():
                        if face_id == TARGET_FACE:
                            continue
                        dx = max(0, max(px-(tx+tw), tx-(px+pw)))
                        dy = max(0, max(py-(ty+th), ty-(py+ph)))
                        dist = math.hypot(dx, dy)
                        if dist <= 8:
                            near.append({"face": face_id, "gap_px": dist,
                                         "rect": [px, py, pw, ph]})
                    near.sort(key=lambda item: item["gap_px"])
                return {
                    "atlas_size": atlas_size, "luxel_scale": scale, "gutter": gutter,
                    "lightmapped_face_count": len(placements),
                    "target_face": int(target_face),
                    "target_rect": list(target) if target else None,
                    "target_chart_nearby_rectangles": near[:20],
                    "target_right_margin": atlas_size-(target[0]+target[2]) if target else None,
                    "target_top_margin": atlas_size-(target[1]+target[3]) if target else None,
                }
    return {"error": "QSS packer failed all configured atlas sizes",
            "lightmapped_face_count": len(records)}

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
    texture_metadata = parse_texture_metadata(lumps["textures"])
    model_data = lumps["models"]
    models = [struct.unpack_from("<9f7i", model_data, i)
              for i in range(0, len(model_data)-63, 64)]

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
        topology = polygon_topology_metrics(polygon, pnormal)
        area_vec = (0.0, 0.0, 0.0)
        if len(polygon) >= 3:
            for j, v in enumerate(polygon):
                area_vec = add(area_vec, cross(v, polygon[(j+1)%len(polygon)]))
        area = 0.5 * abs(dot(normalize(pnormal), area_vec)) if length(pnormal) > 0 else 0.0
        centroid = tuple(sum(v[k] for v in polygon)/len(polygon) for k in range(3)) if polygon else (0,0,0)
        texname = ""
        extents = None
        texture_vectors = None
        texture_flags = None
        texture_digest = None
        if 0 <= texnum < len(texinfos):
            ti = texinfos[texnum]
            texture_vectors = [list(ti[0:4]), list(ti[4:8])]
            texture_flags = ti[9]
            mip_index = ti[8]
            texname = texture_names[mip_index] if 0 <= mip_index < len(texture_names) else ""
            if 0 <= mip_index < len(texture_metadata):
                texture_digest = texture_metadata[mip_index].get("sha256")
        if 0 <= texnum < len(texinfos) and polygon:
            ti = texinfos[texnum]
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
            "texinfo_vectors": texture_vectors, "texinfo_flags": texture_flags,
            "texture_digest": texture_digest,
            "model_indices": [mi for mi, model in enumerate(models)
                              if model[14] <= fi < model[14] + model[15]],
            "styles": styles, "lightofs": lightofs, "sample_count_estimate": sample_count,
            "light_range_ok": light_range_ok, "extents": extents,
            "polygon": polygon, "centroid": centroid, "area": area,
            "bbox": [[min(v[k] for v in polygon), max(v[k] for v in polygon)] for k in range(3)] if polygon else [],
            "min_edge": min(edge_lengths, default=0.0), "zero_edges": repeats,
            "max_plane_error": max_plane_error,
            "topology": topology,
            "target_plane_distance": abs(dot(pnormal, TARGET)-pdist) if finite_vec(pnormal) else float("inf"),
            "target_polygon_distance": polygon_distance(TARGET, polygon),
        }
        faces.append(face)
        if polygon and (len(polygon) < 3 or repeats or area < 1e-8 or max_plane_error > 0.05 or not light_range_ok):
            bad_poly_faces.append({"face": fi, "numedges": numedges, "zero_edges": repeats,
                                   "area": area, "max_plane_error": max_plane_error,
                                   "lightofs": lightofs, "sample_count": sample_count,
                                   "light_range_ok": light_range_ok, "texture": texname})
    entity_text = lumps["entities"].split(b"\0", 1)[0].decode("latin1", errors="replace")
    entity_blocks = re.findall(r"\{([^{}]*)\}", entity_text, re.S)
    worldspawn_raw = entity_blocks[0][:3000] if entity_blocks else ""
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
            "models": len(models),
            "lights": len(lights), "entities": len(entity_list),
            "nonfinite_vertices": sum(1 for v in vertices if not finite_vec(v)),
            "bad_face_references": len(bad_face_refs), "bad_light_ranges": len(bad_lighting),
            "degenerate_or_suspicious_faces": len(bad_poly_faces),
        },
        "face_5828": faces[TARGET_FACE] if len(faces) > TARGET_FACE else None,
        "nearest_faces_to_failure_position": target_faces,
        "nearest_lights": lights[:12],
        "blue_spotlights": [x for x in lights if x["mangle"] and x["color"] and ("181 238 255" in x["color"] or "0.7098" in x["color"])],
        "worldspawn_raw_first_entity": worldspawn_raw,
        "worldspawn_parsed": entity_list[0] if entity_list else None,
        "model0": {
            "firstface": models[0][14], "numfaces": models[0][15],
            "headnodes": list(models[0][9:13]), "visleafs": models[0][13],
        } if models else None,
        "bad_face_references_sample": bad_face_refs[:20],
        "nonfinite_faces_sample": nonfinite_faces[:30],
        "suspicious_faces_sample": bad_poly_faces[:30],
        "topology_quality": {
            "concave_faces": sum(1 for face in faces if face["topology"]["concave"]),
            "self_intersecting_faces": sum(1 for face in faces if face["topology"]["self_intersections"]),
            "repeated_vertex_faces": sum(1 for face in faces if face["topology"]["repeated_vertices"]),
            "collinear_vertex_faces": sum(1 for face in faces if face["topology"]["collinear_turns"]),
            "winding_opposed_faces": sum(1 for face in faces if face["polygon"] and face["topology"]["winding_dot"] < -1e-6),
            "concave_face_sample": [face["index"] for face in faces if face["topology"]["concave"]][:50],
            "self_intersection_sample": [face["index"] for face in faces if face["topology"]["self_intersections"]][:50],
            "winding_opposed_sample": [face["index"] for face in faces if face["polygon"] and face["topology"]["winding_dot"] < -1e-6][:50],
        },
    }
    result["_atlas_layout"] = simulate_qss_atlas(faces, target_face=TARGET_FACE)
    result["_all_faces"] = faces
    result["_planes"] = planes
    result["_edges"] = edges
    result["_surfedges"] = surfedges
    result["_models"] = models
    result["_entities"] = entity_list
    result["_worldspawn_raw"] = worldspawn_raw
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
        candidates.append({
            "face": f["index"], "texture": f["texture"], "normal_alignment_abs": n_dot,
            "centroid_distance": length(sub(src_centroid, f["centroid"])),
            "source_centroid_to_candidate_polygon": poly_dist,
            "plane_delta_at_candidate_centroid": plane_delta,
            "target_polygon_distance": f["target_polygon_distance"],
            "numedges": f["numedges"], "area": f["area"],
            "plane_index": f["plane_index"], "side": f["side"],
            "normal": f["normal"], "plane_dist": f["plane_dist"],
            "texinfo": f["texinfo"], "texinfo_vectors": f["texinfo_vectors"],
            "texinfo_flags": f["texinfo_flags"], "texture_digest": f["texture_digest"],
            "styles": f["styles"], "lightofs": f["lightofs"],
            "sample_count_estimate": f["sample_count_estimate"],
            "extents": f["extents"], "model_indices": f["model_indices"],
            "polygon": f["polygon"],
            "same_vertex_set": sorted(tuple(v) for v in src["polygon"]) == sorted(tuple(v) for v in f["polygon"]),
            "same_texinfo_vectors": src["texinfo_vectors"] == f["texinfo_vectors"],
            "same_texinfo_flags": src["texinfo_flags"] == f["texinfo_flags"],
            "same_texture_digest": src["texture_digest"] == f["texture_digest"],
            "same_extents": src["extents"] == f["extents"],
        })
    candidates.sort(key=lambda x: (x["source_centroid_to_candidate_polygon"], x["centroid_distance"]))
    return candidates[:12]

def compare_neighborhood(original, rebuilt, radius=128.0):
    source_faces = [f for f in original["_all_faces"]
                    if f["polygon"] and f["target_polygon_distance"] <= radius]
    target_results = []
    for src in sorted(source_faces, key=lambda f: f["target_polygon_distance"]):
        src_n = normalize(src["normal"])
        candidates = []
        for dst in rebuilt["_all_faces"]:
            if not dst["polygon"] or dst["numedges"] < 3:
                continue
            alignment = abs(dot(src_n, normalize(dst["normal"])))
            if alignment < 0.999:
                continue
            plane_delta = min(
                abs(dot(src_n, dst["centroid"])-src["plane_dist"]),
                abs(dot(src_n, dst["centroid"])+src["plane_dist"]),
            )
            if plane_delta > 0.05:
                continue
            centroid_distance = length(sub(src["centroid"], dst["centroid"]))
            polygon_distance_value = polygon_distance(src["centroid"], dst["polygon"])
            same_vertices = sorted(tuple(v) for v in src["polygon"]) == sorted(tuple(v) for v in dst["polygon"])
            candidates.append({
                "face": dst["index"], "texture": dst["texture"],
                "polygon_distance_from_source_centroid": polygon_distance_value,
                "centroid_distance": centroid_distance, "same_vertex_set": same_vertices,
                "same_texinfo_vectors": src["texinfo_vectors"] == dst["texinfo_vectors"],
                "same_texture_digest": src["texture_digest"] == dst["texture_digest"],
                "source_plane_delta": plane_delta,
                "numedges": dst["numedges"], "area": dst["area"],
                "texinfo_vectors": dst["texinfo_vectors"],
                "polygon": dst["polygon"],
            })
        candidates.sort(key=lambda x: (not x["same_vertex_set"],
                                       x["polygon_distance_from_source_centroid"],
                                       x["centroid_distance"]))
        target_results.append({
            "original_face": src["index"], "texture": src["texture"],
            "distance_to_failure_position": src["target_polygon_distance"],
            "centroid": src["centroid"], "normal": src["normal"],
            "numedges": src["numedges"], "area": src["area"],
            "texinfo_vectors": src["texinfo_vectors"], "polygon": src["polygon"],
            "best_rebuild_matches": candidates[:3],
        })
    return target_results[:80]

def spotlight_geometry_paths(parsed, sample=TARGET):
    faces = parsed["_all_faces"]
    results = []
    for light in parsed["_entities"]:
        if not str(light.get("classname", "")).lower().startswith("light"):
            continue
        raw_origin = light.get("origin", "")
        try:
            origin = tuple(float(value) for value in raw_origin.split()[:3])
            if len(origin) != 3:
                continue
        except (TypeError, ValueError):
            continue
        color = light.get("_color", light.get("color", ""))
        mangle = light.get("mangle", "")
        delta = sub(origin, sample)
        segment_length = length(delta)
        if segment_length <= 1e-8:
            continue
        nearest = []
        intersections = []
        for face in faces:
            polygon = face["polygon"]
            if not polygon or len(polygon) < 3:
                continue
            distance_to_light = polygon_distance(origin, polygon)
            if distance_to_light <= 192.0:
                nearest.append({
                    "face": face["index"], "texture": face["texture"],
                    "distance": distance_to_light,
                    "normal": face["normal"], "plane_dist": face["plane_dist"],
                    "model_indices": face["model_indices"],
                    "polygon": polygon,
                })
            normal = normalize(face["normal"])
            denom = dot(normal, delta)
            if abs(denom) <= 1e-10:
                continue
            t = (face["plane_dist"] - dot(normal, sample))/denom
            if 1e-6 < t < 1.0-1e-6:
                hit_point = add(sample, mul(delta, t))
                polygon_dist = polygon_distance(hit_point, polygon)
                if polygon_dist <= 0.05:
                    intersections.append({
                        "face": face["index"], "texture": face["texture"],
                        "segment_t": t, "distance_from_sample": t*segment_length,
                        "distance_to_light": (1.0-t)*segment_length,
                        "hit_point": hit_point, "polygon_distance": polygon_dist,
                        "normal": face["normal"], "model_indices": face["model_indices"],
                    })
        nearest.sort(key=lambda item: item["distance"])
        intersections.sort(key=lambda item: item["segment_t"])
        results.append({
            "origin": origin, "distance_from_sample": segment_length,
            "light": light.get("light"), "color": color, "mangle": mangle,
            "delay": light.get("delay", ""), "nearest_surfaces": nearest[:8],
            "segment_surface_intersections": intersections[:20],
        })
    results.sort(key=lambda item: item["distance_from_sample"])
    return results[:20]

def compare_entities(original, rebuilt):
    left, right = original["_entities"], rebuilt["_entities"]
    changes = []
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else {}
        b = right[i] if i < len(right) else {}
        keys = sorted(set(a) | set(b))
        delta = {k: {"original": a.get(k), "rebuilt": b.get(k)}
                 for k in keys if a.get(k) != b.get(k)}
        if delta:
            changes.append({"entity_index": i, "original_class": a.get("classname"),
                            "rebuilt_class": b.get("classname"),
                            "original_origin": a.get("origin"), "rebuilt_origin": b.get("origin"),
                            "changes": delta})
    return {"original_count": len(left), "rebuilt_count": len(right),
            "exact_entity_dicts_match_in_order": not changes, "differences": changes[:100],
            "original_worldspawn": original["_entities"][0] if left else None,
            "rebuilt_worldspawn": rebuilt["_entities"][0] if right else None,
            "original_worldspawn_raw": original["_worldspawn_raw"],
            "rebuilt_worldspawn_raw": rebuilt["_worldspawn_raw"]}

def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def _world_plane_frame_legacy(plane, side=0):
    """Match lightmap_export.world_plane_frame for a classic Quake BSP plane."""
    sign = -1.0 if int(side) else 1.0
    normal = [float(plane[i]) * sign for i in range(3)]
    distance = float(plane[3]) * sign
    magnitude = math.sqrt(sum(value * value for value in normal))
    if not math.isfinite(magnitude) or magnitude <= 1e-12 or not math.isfinite(distance):
        raise ValueError("BSP plane normal and distance must be finite and non-zero")
    normal = [value / magnitude for value in normal]
    distance /= magnitude
    major = max(range(3), key=lambda index: (abs(normal[index]), -index))
    if normal[major] < 0.0:
        normal = [-value for value in normal]
        distance = -distance
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    projected = []
    for axis_index, reference in enumerate(axes):
        projection = sum(normal[i] * reference[i] for i in range(3))
        tangent = tuple(reference[i] - normal[i] * projection for i in range(3))
        projected.append((sum(value * value for value in tangent), -axis_index, tangent))
    tangent_sq, _order, tangent = max(projected, key=lambda value: (value[0], value[1]))
    if tangent_sq <= 1e-12:
        raise ValueError("Could not construct a stable plane tangent")
    inv_length = 1.0 / math.sqrt(tangent_sq)
    axis_s = tuple(value * inv_length for value in tangent)
    axis_t = (
        normal[1] * axis_s[2] - normal[2] * axis_s[1],
        normal[2] * axis_s[0] - normal[0] * axis_s[2],
        normal[0] * axis_s[1] - normal[1] * axis_s[0],
    )
    return {"normal": tuple(normal), "distance": distance,
            "axis_s": axis_s, "axis_t": axis_t}


def world_chart_diagnostic(parsed, target_face_id, target_position=TARGET,
                            gutter=2, max_atlas_size=2048):
    """Mirror the current QSS coplanar-chart grouping and rectangle packer."""
    faces = parsed["_all_faces"]
    planes = parsed["_planes"]
    surfedges = parsed["_surfedges"]
    records_by_face, keys, frames, edge_users = {}, {}, {}, {}
    face_model_ids = []
    for face in faces:
        models = face.get("model_indices") or []
        face_model_ids.append(int(models[0]) if models else -1)

    for face in faces:
        face_id = int(face["index"])
        first_edge, edge_count = int(face["firstedge"]), int(face["numedges"])
        plane_id = int(face["plane_index"])
        if (face["lightofs"] < 0 or not face["styles"] or not face["extents"]
                or first_edge < 0 or edge_count < 3
                or first_edge + edge_count > len(surfedges)
                or plane_id < 0 or plane_id >= len(planes)
                or len(face["polygon"]) < 3):
            continue
        try:
            frame = _world_plane_frame_legacy(planes[plane_id], int(face["side"]))
        except ValueError:
            continue
        plane_key = tuple(round(value / 1e-4) for value in (
            *frame["normal"], frame["distance"]
        ))
        keys[face_id] = (
            face_model_ids[face_id],
            tuple(int(value) for value in face["styles"]),
            plane_key,
        )
        records_by_face[face_id] = face
        frames[face_id] = frame
        for signed_edge in surfedges[first_edge:first_edge + edge_count]:
            edge_id = abs(int(signed_edge))
            edge_users.setdefault(edge_id, []).append(face_id)

    parent = {face_id: face_id for face_id in records_by_face}

    def find(face_id):
        while parent[face_id] != face_id:
            parent[face_id] = parent[parent[face_id]]
            face_id = parent[face_id]
        return face_id

    for users in edge_users.values():
        if len(users) == 2 and keys[users[0]] == keys[users[1]]:
            root_a, root_b = find(users[0]), find(users[1])
            if root_a != root_b:
                parent[max(root_a, root_b)] = min(root_a, root_b)

    components = {}
    for face_id in records_by_face:
        components.setdefault(find(face_id), []).append(face_id)

    charts, face_to_chart = [], {}
    for chart_index, root in enumerate(sorted(components)):
        member_ids = sorted(components[root])
        frame = frames[member_ids[0]]
        projected = [
            (dot(point, frame["axis_s"]), dot(point, frame["axis_t"]))
            for face_id in member_ids for point in records_by_face[face_id]["polygon"]
        ]
        s_min = math.floor(min(point[0] for point in projected) / 16.0 + 1e-7) * 16.0
        t_min = math.floor(min(point[1] for point in projected) / 16.0 + 1e-7) * 16.0
        s_max = math.ceil(max(point[0] for point in projected) / 16.0 - 1e-7) * 16.0
        t_max = math.ceil(max(point[1] for point in projected) / 16.0 - 1e-7) * 16.0
        chart_id = len(faces) + chart_index
        chart = {
            "chart_id": chart_id, "face_ids": tuple(member_ids),
            "model_id": face_model_ids[member_ids[0]],
            "styles": tuple(int(value) for value in records_by_face[member_ids[0]]["styles"]),
            "normal": frame["normal"], "distance": frame["distance"],
            "axis_s": frame["axis_s"], "axis_t": frame["axis_t"],
            "s_min": float(s_min), "t_min": float(t_min),
            "width": int((s_max - s_min) // 16 + 1),
            "height": int((t_max - t_min) // 16 + 1),
        }
        charts.append(chart)
        for face_id in member_ids:
            face_to_chart[face_id] = chart_id

    chart_records = [
        {"face_id": chart["chart_id"], "width": chart["width"], "height": chart["height"]}
        for chart in charts
    ]
    ordered = sorted(chart_records, key=lambda item: (-item["height"], -item["width"], item["face_id"]))
    packed_result = None
    for scale in (2, 1):
        for atlas_size in (512, 1024, 2048):
            if atlas_size > int(max_atlas_size):
                continue
            x = y = row_h = 0
            placements = {}
            failed = False
            for rec in ordered:
                rw = rec["width"] * scale + 2 * gutter
                rh = rec["height"] * scale + 2 * gutter
                if rw > atlas_size or rh > atlas_size:
                    failed = True
                    break
                if x + rw > atlas_size:
                    x = 0
                    y += row_h
                    row_h = 0
                if y + rh > atlas_size:
                    failed = True
                    break
                placements[rec["face_id"]] = (x, y, rw, rh)
                x += rw
                row_h = max(row_h, rh)
            if not failed:
                packed_result = (atlas_size, scale, placements)
                break
        if packed_result is not None:
            break
    if packed_result is None:
        return {"error": "QSS world-chart packer failed"}

    if target_face_id not in face_to_chart:
        return {"error": "target face is not in a classic lightmapped chart",
                "target_face": target_face_id,
                "chart_count": len(charts),
                "lightmapped_face_count": len(records_by_face)}
    chart_id = face_to_chart[target_face_id]
    chart = next(item for item in charts if item["chart_id"] == chart_id)
    atlas_size, scale, placements = packed_result
    ax, ay, rw, rh = placements[chart_id]
    position = tuple(float(value) for value in target_position)
    world_s, world_t = dot(position, chart["axis_s"]), dot(position, chart["axis_t"])
    luxel_s = (world_s - chart["s_min"]) / 16.0
    luxel_t = (world_t - chart["t_min"]) / 16.0
    origin_x, origin_y = ax + gutter, ay + gutter
    pixel_x = origin_x + (luxel_s + 0.5) * scale - 0.5
    pixel_top_y = origin_y + (luxel_t + 0.5) * scale - 0.5
    pixel_y_bottom_up = atlas_size - 1.0 - pixel_top_y

    target_face = records_by_face[target_face_id]
    texinfo = target_face["texinfo_vectors"]
    source_s = dot(position, texinfo[0][:3]) + texinfo[0][3]
    source_t = dot(position, texinfo[1][:3]) + texinfo[1][3]
    classic_luxel_s = (source_s - target_face["extents"]["s"][0]) / 16.0
    classic_luxel_t = (source_t - target_face["extents"]["t"][0]) / 16.0

    contributors = []
    for face_id in chart["face_ids"]:
        face = records_by_face[face_id]
        tex = face["texinfo_vectors"]
        src_s = dot(position, tex[0][:3]) + tex[0][3]
        src_t = dot(position, tex[1][:3]) + tex[1][3]
        src_x = (src_s - face["extents"]["s"][0]) / 16.0
        src_y = (src_t - face["extents"]["t"][0]) / 16.0
        width, height = face["extents"]["luxel_dimensions"]
        if (-1e-6 <= src_x <= width - 1 + 1e-6
                and -1e-6 <= src_y <= height - 1 + 1e-6):
            contributors.append({
                "face": face_id, "texture": face["texture"],
                "source_luxel": [src_x, src_y],
                "grid_dimensions": [width, height],
                "polygon_distance": face["target_polygon_distance"],
            })

    member_preview = []
    for face_id in chart["face_ids"][:100]:
        face = records_by_face[face_id]
        member_preview.append({
            "face": face_id, "texture": face["texture"],
            "dimensions": face["extents"]["luxel_dimensions"],
            "polygon_distance_to_target": face["target_polygon_distance"],
        })
    return {
        "target_face": target_face_id,
        "chart_id": chart_id,
        "chart_face_count": len(chart["face_ids"]),
        "chart_face_ids_truncated": len(chart["face_ids"]) > len(member_preview),
        "chart_face_ids_preview": member_preview,
        "chart_dimensions": [chart["width"], chart["height"]],
        "chart_bounds_st": [chart["s_min"], chart["s_min"] + 16 * (chart["width"] - 1),
                            chart["t_min"], chart["t_min"] + 16 * (chart["height"] - 1)],
        "chart_basis": {"normal": chart["normal"], "distance": chart["distance"],
                        "axis_s": chart["axis_s"], "axis_t": chart["axis_t"]},
        "atlas_size": atlas_size, "luxel_scale": scale, "gutter": gutter,
        "atlas_rectangle_with_gutter": [ax, ay, rw, rh],
        "sample_world": list(position),
        "sample_world_chart_st": [world_s, world_t],
        "sample_chart_luxel": [luxel_s, luxel_t],
        "sample_original_face_luxel": [classic_luxel_s, classic_luxel_t],
        "sample_atlas_pixel_center_bottom_up": [pixel_x, pixel_y_bottom_up],
        "sample_atlas_pixels_floor": [math.floor(pixel_x), math.floor(pixel_y_bottom_up)],
        "sample_contribution_count": len(contributors),
        "sample_contributors": contributors[:20],
        "chart_count": len(charts),
        "lightmapped_face_count": len(records_by_face),
    }


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: analyze_e1m1_bsp_pair.py ORIGINAL.bsp ORIGINAL.lit REBUILT.bsp REBUILT.lit")
    original = parse_bsp(sys.argv[1])
    rebuilt = parse_bsp(sys.argv[3])
    face_matches = compare_faces(original, rebuilt)
    rebuilt_target_face = (
        int(face_matches[0]["face"])
        if face_matches and face_matches[0].get("same_vertex_set")
        and face_matches[0].get("source_centroid_to_candidate_polygon", 1.0) <= 1e-4
        else None
    )
    original_atlas_layout = current_qss_world_chart_report(original,TARGET_FACE)
    rebuilt_atlas_layout = (
        current_qss_world_chart_report(rebuilt,rebuilt_target_face)
        if rebuilt_target_face is not None else {"error":"No exact counterpart face was identified"}
    )
    report = {
        "target_world_quake": TARGET,
        "original": {k: v for k, v in original.items() if k not in ("_all_faces", "_entities", "_worldspawn_raw", "_atlas_layout")},
        "original_lit": lit_summary(sys.argv[2], original),
        "rebuilt": {k: v for k, v in rebuilt.items() if k not in ("_all_faces", "_entities", "_planes", "_edges", "_surfedges")},
        "rebuilt_lit": lit_summary(sys.argv[4], rebuilt),
        "original_face_5828_matches_in_rebuild": face_matches,
        "entity_comparison": compare_entities(original, rebuilt),
        "local_face_neighborhood_comparison": compare_neighborhood(original, rebuilt),
        "original_atlas_layout": original_atlas_layout,
        "rebuilt_atlas_layout": rebuilt_atlas_layout,
        "rebuilt_counterpart_face_id": rebuilt_target_face,
        "original_spotlight_geometry_paths": spotlight_geometry_paths(original),
        "rebuilt_spotlight_geometry_paths": spotlight_geometry_paths(rebuilt),
    }
    out = json.dumps(json_safe(report), indent=2, allow_nan=False)
    Path("e1m1-bsp-comparison.json").write_text(out, encoding="utf-8")
    print(out)

if __name__ == "__main__":
    main()
