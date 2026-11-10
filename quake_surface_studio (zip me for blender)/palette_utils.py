"""Pure helpers for the Quake palette paint and conversion workflows."""
from __future__ import annotations

import math
from typing import Iterable


def palette_to_jasc_text(palette: bytes | bytearray | memoryview) -> str:
    """Serialize the 768-byte Quake RGB palette as a strict 256-entry JASC-PAL."""
    raw = bytes(palette)
    if len(raw) != 256 * 3:
        raise ValueError(f"Quake palette must contain 768 RGB bytes; received {len(raw)}.")
    lines = ["JASC-PAL", "0100", "256"]
    lines.extend(
        f"{raw[index]:d} {raw[index + 1]:d} {raw[index + 2]:d}"
        for index in range(0, len(raw), 3)
    )
    return "\n".join(lines) + "\n"


def quake_dimension(span: float, maximum: int = 512) -> int:
    """Return the smallest multiple-of-eight texture dimension covering span."""
    value = float(span)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Texture span must be finite and nonnegative.")
    upper = max(8, (int(maximum) // 8) * 8)
    requested = max(8, int(math.ceil(max(1.0, value))))
    return min(upper, ((requested + 7) // 8) * 8)


def estimate_face_local_paint_bytes(
    spans: Iterable[tuple[float, float]],
    *,
    bytes_per_face_pixel: int = 4,
    atlas_size: int = 512,
    bytes_per_atlas_pixel: int = 16,
) -> dict[str, int]:
    """Estimate peak pixel-buffer allocation while detaching selected faces.

    This includes all temporary face-local image buffers plus the shared
    512-style float atlas allocated for multi-face paint. It deliberately does
    not pretend to estimate Blender's material datablocks, undo history,
    GPU copies, or other process overhead.
    """
    span_list = [(float(width), float(height)) for width, height in spans]
    if bytes_per_face_pixel not in (4, 16):
        raise ValueError("Face image buffer size must be 4 (byte) or 16 (float) bytes per pixel.")
    if int(atlas_size) < 8 or int(bytes_per_atlas_pixel) not in (4, 16):
        raise ValueError("Invalid detached-atlas dimensions or pixel size.")
    face_bytes = 0
    for width_span, height_span in span_list:
        width = quake_dimension(width_span)
        height = quake_dimension(height_span)
        face_bytes += width * height * int(bytes_per_face_pixel)
    atlas_bytes = (
        int(atlas_size) * int(atlas_size) * int(bytes_per_atlas_pixel)
        if len(span_list) > 1 else 0
    )
    return {
        "face_count": len(span_list),
        "face_image_bytes": face_bytes,
        "atlas_bytes": atlas_bytes,
        "peak_pixel_bytes": face_bytes + atlas_bytes,
    }


def format_mib(byte_count: int) -> str:
    """Format a nonnegative byte count as MiB with one decimal place."""
    return f"{max(0, int(byte_count)) / (1024.0 * 1024.0):.1f} MiB"


# --- Blender-native Quake material-zone conversion (stdlib only) ---
import configparser
import math
import struct
import zlib
from array import array
from collections import deque
from pathlib import Path

# Blender-native, standard-library implementation of the material-zone converter.
import configparser
import struct
import zlib
from array import array
from collections import deque
from pathlib import Path
from typing import Sequence


RAMPS = {
    "neutral": list(range(0, 16)),
    "dark_earth": list(range(16, 32)),
    "blue_grey": list(range(32, 48)),
    "olive_dark": list(range(48, 64)),
    "red": list(range(64, 80)),
    "ochre": list(range(80, 96)),
    "warm_earth": list(range(96, 112)),
    "tan": list(range(112, 128)),
    "purple_dark": list(range(128, 144)),
    "purple_warm": list(range(144, 160)),
    "stone": list(range(160, 176)),
    "green_grey": list(range(176, 192)),
    "yellow_ochre": list(range(192, 208)),
    "blue": list(range(208, 224)),
}
DEFAULT_SETTINGS = {
    "ramps": ",".join(RAMPS),
    "fullbright_start": 224,
    "segments": 180,
    "compactness": 10.0,
    "detail": 0.35,
    "detail_radius": 1.2,
    "coherence": 0.025,
    "material_merge_threshold": 0.055,
    "material_luminance_weight": 0.20,
    "material_chroma_limit": 0.075,
    "ramp_candidates_per_zone": 5,
    "alpha_threshold": 128,
}


def load_settings(path: str | Path | None = None) -> dict:
    """Load converter parameters from the bundled INI, retaining tested defaults."""
    values = dict(DEFAULT_SETTINGS)
    if path is None:
        return values
    config = configparser.ConfigParser()
    try:
        if not config.read(str(path), encoding="utf-8"):
            return values
    except (OSError, configparser.Error):
        return values
    section = config["conversion"] if config.has_section("conversion") else {}
    casts = {
        "fullbright_start": int,
        "segments": int,
        "compactness": float,
        "detail": float,
        "detail_radius": float,
        "coherence": float,
        "material_merge_threshold": float,
        "material_luminance_weight": float,
        "material_chroma_limit": float,
        "ramp_candidates_per_zone": int,
        "alpha_threshold": int,
    }
    for key, cast in casts.items():
        try:
            values[key] = cast(section.get(key, values[key]))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid Quake palette converter setting '{key}'.")
    values["ramps"] = str(section.get("ramps", values["ramps"]))
    return values


def validate_palette(palette: bytes | bytearray | memoryview) -> bytes:
    raw = bytes(palette)
    if len(raw) != 768:
        raise ValueError(f"Quake palette must contain 768 RGB bytes; received {len(raw)}.")
    return raw


def _srgb_to_linear(value: float) -> float:
    value = max(0.0, float(value)) / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value: float) -> float:
    value = max(0.0, float(value))
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1.0 / 2.4)) - 0.055


def _rgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    r = _srgb_to_linear(r)
    g = _srgb_to_linear(g)
    b = _srgb_to_linear(b)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1.0 / 3.0)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073961526 * b) ** (1.0 / 3.0)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1.0 / 3.0)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def _oklab_to_rgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    blue = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return tuple(max(0.0, min(255.0, _linear_to_srgb(v) * 255.0)) for v in (r, g, blue))


def _rgb_to_cielab(r: float, g: float, b: float) -> tuple[float, float, float]:
    """D65 CIE Lab used by SLIC's convert-to-Lab segmentation stage."""
    r, g, b = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b)
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    delta = 6.0 / 29.0
    delta3 = delta ** 3

    def f(value: float) -> float:
        if value > delta3:
            return value ** (1.0 / 3.0)
        return value / (3.0 * delta * delta) + 4.0 / 29.0

    fx, fy, fz = f(x), f(y), f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def _to_oklab(rgb: array) -> array:
    count = len(rgb) // 3
    out = array("f", [0.0]) * (count * 3)
    for i in range(count):
        j = i * 3
        L, a, b = _rgb_to_oklab(rgb[j], rgb[j + 1], rgb[j + 2])
        out[j], out[j + 1], out[j + 2] = L, a, b
    return out


def _gaussian_kernel(sigma: float) -> list[float]:
    radius = max(1, int(math.ceil(3.0 * sigma)))
    weights = [math.exp(-(i * i) / (2.0 * sigma * sigma)) for i in range(-radius, radius + 1)]
    total = sum(weights)
    return [value / total for value in weights]


def _gaussian_blur(plane: array, width: int, height: int, sigma: float) -> array:
    if sigma <= 0.0:
        return array("f", plane)
    kernel = _gaussian_kernel(sigma)
    radius = len(kernel) // 2
    temp = array("f", [0.0]) * (width * height)
    out = array("f", [0.0]) * (width * height)
    for y in range(height):
        row = y * width
        for x in range(width):
            value = 0.0
            for k, weight in enumerate(kernel):
                sx = min(width - 1, max(0, x + k - radius))
                value += plane[row + sx] * weight
            temp[row + x] = value
    for y in range(height):
        for x in range(width):
            value = 0.0
            for k, weight in enumerate(kernel):
                sy = min(height - 1, max(0, y + k - radius))
                value += temp[sy * width + x] * weight
            out[y * width + x] = value
    return out


def _enhance_detail(rgb: array, width: int, height: int, amount: float, radius: float) -> array:
    if amount <= 0.0:
        return array("f", rgb)
    lab = _to_oklab(rgb)
    count = width * height
    luminance = array("f", (lab[i * 3] for i in range(count)))
    base = _gaussian_blur(luminance, width, height, max(0.01, radius))
    out = array("f", [0.0]) * (count * 3)
    for i in range(count):
        p = i * 3
        detail = max(-0.12, min(0.12, luminance[i] - base[i]))
        L = lab[p] + amount * detail
        r, g, b = _oklab_to_rgb(L, lab[p + 1], lab[p + 2])
        out[p], out[p + 1], out[p + 2] = r, g, b
    return out


def _detect_edges(rgb: array, width: int, height: int) -> array:
    gray = array("f", [0.0]) * (width * height)
    for i in range(width * height):
        p = i * 3
        gray[i] = (0.299 * rgb[p] + 0.587 * rgb[p + 1] + 0.114 * rgb[p + 2]) / 255.0
    edges = array("f", [0.0]) * (width * height)
    for y in range(height):
        ym, yp = max(0, y - 1), min(height - 1, y + 1)
        for x in range(width):
            xm, xp = max(0, x - 1), min(width - 1, x + 1)
            a = gray[ym * width + xm]
            b = gray[ym * width + x]
            c = gray[ym * width + xp]
            d = gray[y * width + xm]
            f = gray[y * width + xp]
            g = gray[yp * width + xm]
            h = gray[yp * width + x]
            i = gray[yp * width + xp]
            gx = (c + 2.0 * f + i) - (a + 2.0 * d + g)
            gy = (g + 2.0 * h + i) - (a + 2.0 * b + c)
            edges[y * width + x] = min(1.0, math.sqrt(gx * gx + gy * gy) / 4.0)
    return edges


def _compact_labels(labels: array) -> tuple[array, int]:
    mapping: dict[int, int] = {}
    result = array("i", [0]) * len(labels)
    for index, label in enumerate(labels):
        new = mapping.get(label)
        if new is None:
            new = len(mapping)
            mapping[label] = new
        result[index] = new
    return result, len(mapping)


def _segment_image(rgb: array, edges: array, width: int, height: int,
                   segments: int = 180, compactness: float = 10.0) -> tuple[array, int]:
    """SLIC-style local clustering with Lab colour distance and connectivity."""
    total = width * height
    target = max(1, min(total, int(segments)))
    step = max(1.0, math.sqrt(total / target))
    nx = max(1, int(round(width / step)))
    ny = max(1, int(round(height / step)))
    step_x, step_y = width / nx, height / ny
    centers: list[list[float]] = []
    for gy in range(ny):
        for gx in range(nx):
            cx = min(width - 1.0, (gx + 0.5) * step_x)
            cy = min(height - 1.0, (gy + 0.5) * step_y)
            best_x, best_y, best_edge = int(round(cx)), int(round(cy)), float("inf")
            for yy in range(max(0, int(cy) - 1), min(height, int(cy) + 2)):
                for xx in range(max(0, int(cx) - 1), min(width, int(cx) + 2)):
                    e = edges[yy * width + xx]
                    if e < best_edge:
                        best_x, best_y, best_edge = xx, yy, e
            index = best_y * width + best_x
            centers.append([
                _rgb_to_cielab(rgb[index * 3], rgb[index * 3 + 1], rgb[index * 3 + 2])[0],
                _rgb_to_cielab(rgb[index * 3], rgb[index * 3 + 1], rgb[index * 3 + 2])[1],
                _rgb_to_cielab(rgb[index * 3], rgb[index * 3 + 1], rgb[index * 3 + 2])[2],
                float(best_x), float(best_y),
            ])

    lab = array("f", [0.0]) * (total * 3)
    for p in range(total):
        j = p * 3
        L, a, b = _rgb_to_cielab(rgb[j], rgb[j + 1], rgb[j + 2])
        lab[j], lab[j + 1], lab[j + 2] = L, a, b

    labels = array("i", [-1]) * total
    spatial_weight = (float(compactness) / max(1.0, step)) ** 2
    for _iteration in range(8):
        distances = array("f", [float("inf")]) * total
        for label, center in enumerate(centers):
            cL, ca, cb, cx, cy = center
            x0 = max(0, int(cx - 2.0 * step_x))
            x1 = min(width, int(cx + 2.0 * step_x) + 1)
            y0 = max(0, int(cy - 2.0 * step_y))
            y1 = min(height, int(cy + 2.0 * step_y) + 1)
            for y in range(y0, y1):
                row = y * width
                dy2 = (y - cy) ** 2
                for x in range(x0, x1):
                    pixel = row + x
                    j = pixel * 3
                    dL = lab[j] - cL
                    da = lab[j + 1] - ca
                    db = lab[j + 2] - cb
                    distance = dL * dL + da * da + db * db + spatial_weight * ((x - cx) ** 2 + dy2)
                    if distance < distances[pixel]:
                        distances[pixel] = distance
                        labels[pixel] = label

        sums = [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in centers]
        counts = [0] * len(centers)
        for pixel, label in enumerate(labels):
            if label < 0:
                continue
            j = pixel * 3
            x, y = pixel % width, pixel // width
            item = sums[label]
            item[0] += lab[j]
            item[1] += lab[j + 1]
            item[2] += lab[j + 2]
            item[3] += x
            item[4] += y
            counts[label] += 1
        for label, count in enumerate(counts):
            if count:
                centers[label] = [value / count for value in sums[label]]

    # SLIC's connectivity pass: absorb tiny disconnected components into the
    # neighboring component with which they share the longest boundary.
    average = total / max(1, len(centers))
    minimum_component = max(1, int(average * 0.25))
    visited = bytearray(total)
    for start in range(total):
        if visited[start]:
            continue
        source_label = labels[start]
        queue = [start]
        visited[start] = 1
        component = []
        neighbor_counts: dict[int, int] = {}
        head = 0
        while head < len(queue):
            pixel = queue[head]
            head += 1
            component.append(pixel)
            x, y = pixel % width, pixel // width
            for neighbor in (
                pixel - 1 if x > 0 else -1,
                pixel + 1 if x + 1 < width else -1,
                pixel - width if y > 0 else -1,
                pixel + width if y + 1 < height else -1,
            ):
                if neighbor < 0:
                    continue
                other = labels[neighbor]
                if other == source_label and not visited[neighbor]:
                    visited[neighbor] = 1
                    queue.append(neighbor)
                elif other != source_label:
                    neighbor_counts[other] = neighbor_counts.get(other, 0) + 1
        if len(component) < minimum_component and neighbor_counts:
            target_label = max(neighbor_counts.items(), key=lambda item: item[1])[0]
            for pixel in component:
                labels[pixel] = target_label
    return _compact_labels(labels)


def _median(values: list[float]) -> float:
    values.sort()
    n = len(values)
    if not n:
        return 0.0
    middle = n // 2
    if n & 1:
        return values[middle]
    return (values[middle - 1] + values[middle]) * 0.5


def _merge_material_zones(lab: array, labels: array, count: int, width: int, height: int,
                          merge_threshold: float, luminance_weight: float,
                          chroma_limit: float) -> tuple[array, int]:
    samples: list[list[tuple[float, float, float]]] = [[] for _ in range(count)]
    for pixel, region in enumerate(labels):
        j = pixel * 3
        samples[region].append((lab[j], lab[j + 1], lab[j + 2]))
    descriptors = []
    for region_samples in samples:
        descriptors.append((
            _median([p[0] for p in region_samples]),
            _median([p[1] for p in region_samples]),
            _median([p[2] for p in region_samples]),
        ))

    boundary: dict[tuple[int, int], list[float]] = {}
    for y in range(height):
        row = y * width
        for x in range(width):
            pixel = row + x
            a = labels[pixel]
            if x + 1 < width:
                b = labels[pixel + 1]
                if a != b:
                    _accumulate_boundary(boundary, a, b, lab, pixel, pixel + 1)
            if y + 1 < height:
                b = labels[pixel + width]
                if a != b:
                    _accumulate_boundary(boundary, a, b, lab, pixel, pixel + width)

    parent = list(range(count))
    size = [len(items) for items in samples]

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    candidates = []
    for (a, b), values in boundary.items():
        n = values[2]
        boundary_chroma = values[0] / n
        boundary_light = values[1] / n
        da = descriptors[a][0] - descriptors[b][0]
        db = math.hypot(descriptors[a][1] - descriptors[b][1],
                        descriptors[a][2] - descriptors[b][2])
        chroma_score = 0.65 * db + 0.35 * boundary_chroma
        light_score = 0.65 * abs(da) + 0.35 * boundary_light
        score = math.hypot(chroma_score, luminance_weight * light_score)
        if chroma_score <= chroma_limit and score <= merge_threshold:
            candidates.append((score, a, b))
    candidates.sort(key=lambda item: item[0])
    for _score, a, b in candidates:
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]
    roots = [find(label) for label in labels]
    return _compact_labels(array("i", roots))


def _accumulate_boundary(boundary, a, b, lab, pixel_a, pixel_b):
    key = (min(a, b), max(a, b))
    item = boundary.setdefault(key, [0.0, 0.0, 0])
    ja, jb = pixel_a * 3, pixel_b * 3
    item[0] += math.hypot(lab[ja + 1] - lab[jb + 1],
                          lab[ja + 2] - lab[jb + 2])
    item[1] += abs(lab[ja] - lab[jb])
    item[2] += 1


def _build_adjacency(labels, width: int, height: int) -> list[tuple[int, int]]:
    adjacency = set()
    for y in range(height):
        row = y * width
        for x in range(width):
            pixel = row + x
            a = labels[pixel]
            if x + 1 < width:
                b = labels[pixel + 1]
                if a != b:
                    adjacency.add((min(a, b), max(a, b)))
            if y + 1 < height:
                b = labels[pixel + width]
                if a != b:
                    adjacency.add((min(a, b), max(a, b)))
    return list(adjacency)


def _nearest_palette_distance(pixel, palette_labs, indices):
    best_distance = float("inf")
    for palette_index in indices:
        j = palette_index * 3
        dL = pixel[0] - palette_labs[j]
        da = pixel[1] - palette_labs[j + 1]
        db = pixel[2] - palette_labs[j + 2]
        distance = dL * dL + da * da + db * db
        if distance < best_distance:
            best_distance = distance
    return best_distance


def _assign_region_ramps(rgb: array, lab: array, edges: array, labels: array,
                         region_count: int, palette_labs: array, ramps: dict,
                         width: int, height: int, coherence: float,
                         candidates_per_zone: int):
    names = list(ramps)
    pixel_ids: list[list[int]] = [[] for _ in range(region_count)]
    edge_sums = [0.0] * region_count
    rgb_sums = [[0.0, 0.0, 0.0] for _ in range(region_count)]
    for pixel, region in enumerate(labels):
        pixel_ids[region].append(pixel)
        edge_sums[region] += edges[pixel]
        j = pixel * 3
        sums = rgb_sums[region]
        sums[0] += rgb[j]
        sums[1] += rgb[j + 1]
        sums[2] += rgb[j + 2]
    means = []
    edge_means = []
    for region, pixels in enumerate(pixel_ids):
        count = max(1, len(pixels))
        means.append(tuple(v / count for v in rgb_sums[region]))
        edge_means.append(edge_sums[region] / count)

    mean_labs = [_rgb_to_oklab(*mean) for mean in means]
    ramp_labs = {}
    for name, indices in ramps.items():
        flat = array("f", [0.0]) * (len(indices) * 3)
        for position, index in enumerate(indices):
            j, p = index * 3, position * 3
            flat[p:p + 3] = palette_labs[j:j + 3]
        ramp_labs[name] = flat

    costs = [[0.0] * len(names) for _ in range(region_count)]
    for region, pixels in enumerate(pixel_ids):
        if len(pixels) > 768:
            stride = (len(pixels) - 1) / 767.0
            sample = [pixels[int(round(i * stride))] for i in range(768)]
        else:
            sample = pixels
        sample_labs = []
        for pixel in sample:
            j = pixel * 3
            sample_labs.append((lab[j], lab[j + 1], lab[j + 2]))
        for name_index, name in enumerate(names):
            indices = ramps[name]
            distances = [
                _nearest_palette_distance(color, palette_labs, indices)
                for color in sample_labs
            ]
            distances.sort()
            mean = sum(distances) / max(1, len(distances))
            percentile_index = min(len(distances) - 1, int(0.85 * max(0, len(distances) - 1)))
            costs[region][name_index] = 0.85 * mean + 0.15 * distances[percentile_index]

    adjacency = _build_adjacency(labels, width, height)
    neighbors = [[] for _ in range(region_count)]
    for a, b in adjacency:
        neighbors[a].append(b)
        neighbors[b].append(a)
    assignments = [min(range(len(names)), key=lambda j: costs[r][j]) for r in range(region_count)]
    for _iteration in range(5):
        changed = False
        for region in range(region_count):
            scores = list(costs[region])
            for neighbor in neighbors[region]:
                current = mean_labs[region]
                other = mean_labs[neighbor]
                difference = math.sqrt(sum((a - b) ** 2 for a, b in zip(current, other)))
                edge_strength = max(edge_means[region], edge_means[neighbor])
                penalty = coherence * math.exp(-difference * 5.0)
                penalty *= max(0.0, 1.0 - edge_strength * 3.0)
                neighbor_assignment = assignments[neighbor]
                for j in range(len(names)):
                    if j != neighbor_assignment:
                        scores[j] += penalty
            best = min(range(len(names)), key=lambda j: scores[j])
            if best != assignments[region]:
                assignments[region] = best
                changed = True
        if not changed:
            break

    candidate_count = max(1, min(int(candidates_per_zone), len(names)))
    candidates = []
    for region in range(region_count):
        ranked = sorted(range(len(names)), key=lambda j: costs[region][j])
        selected = ranked[:candidate_count]
        if assignments[region] not in selected:
            selected[-1] = assignments[region]
        candidates.append(selected)
    return assignments, names, candidates


def _quantize_pixels(lab: array, labels: array, assignments: list[int],
                     names: list[str], candidates: list[list[int]],
                     ramps: dict, palette_labs: array) -> bytes:
    """Quantize each zone only against its own candidate palette ramps."""
    output = bytearray(len(labels))
    pixel_ids: list[list[int]] = [[] for _ in assignments]
    for pixel, region in enumerate(labels):
        pixel_ids[region].append(pixel)
    ramp_color_cache = {}
    for region, primary in enumerate(assignments):
        candidate_ids = [primary] + [value for value in candidates[region] if value != primary]
        palette_indices = []
        for candidate in candidate_ids:
            ramp_name = names[candidate]
            if ramp_name not in ramp_color_cache:
                ramp_color_cache[ramp_name] = [
                    (index, tuple(palette_labs[index * 3:index * 3 + 3]))
                    for index in ramps[ramp_name]
                ]
            palette_indices.extend(ramp_color_cache[ramp_name])
        for pixel in pixel_ids[region]:
            j = pixel * 3
            pL, pa, pb = lab[j], lab[j + 1], lab[j + 2]
            best_distance = float("inf")
            best_index = 0
            for index, color in palette_indices:
                dL = pL - color[0]
                da = pa - color[1]
                db = pb - color[2]
                distance = dL * dL + da * da + db * db + 0.08 * dL * dL
                if distance < best_distance:
                    best_distance = distance
                    best_index = index
            output[pixel] = best_index
    return bytes(output)


def _fill_transparent_rgb_nearest(rgb: array, opaque: bytearray, width: int, height: int) -> None:
    """Propagate nearest opaque RGB into transparent texels before segmentation."""
    count = width * height
    if all(opaque):
        return
    queue = deque(index for index, visible in enumerate(opaque) if visible)
    owner = array("i", (index if opaque[index] else -1 for index in range(count)))
    while queue:
        pixel = queue.popleft()
        x, y = pixel % width, pixel // width
        for neighbor in (
            pixel - 1 if x > 0 else -1,
            pixel + 1 if x + 1 < width else -1,
            pixel - width if y > 0 else -1,
            pixel + width if y + 1 < height else -1,
        ):
            if neighbor < 0 or owner[neighbor] != -1:
                continue
            owner[neighbor] = owner[pixel]
            queue.append(neighbor)
    for pixel in range(count):
        if opaque[pixel]:
            continue
        source = owner[pixel]
        if source < 0:
            continue
        rgb[pixel * 3:pixel * 3 + 3] = rgb[source * 3:source * 3 + 3]


def convert_rgba8(width: int, height: int, rgba: bytes | bytearray | memoryview,
                  palette: bytes | bytearray | memoryview,
                  settings: dict | None = None,
                  fullbright_mask: Sequence[bool] | bytes | bytearray | None = None
                  ) -> tuple[bytes, dict]:
    """Convert a top-down RGBA8 image to Quake palette indices (255 transparent)."""
    width, height = int(width), int(height)
    if width < 1 or height < 1 or width * height > 16_777_216:
        raise ValueError("Image dimensions are empty or exceed the safe 16-megapixel conversion limit.")
    raw = bytes(rgba)
    if len(raw) != width * height * 4:
        raise ValueError("RGBA input size does not match the supplied dimensions.")
    palette = validate_palette(palette)
    params = dict(DEFAULT_SETTINGS)
    if settings:
        params.update(settings)
    threshold = int(params["alpha_threshold"])
    if not 0 <= threshold <= 255:
        raise ValueError("Alpha threshold must be between 0 and 255.")
    fullbright_start = int(params["fullbright_start"])
    if not 1 <= fullbright_start <= 255:
        raise ValueError("Fullbright start must be between 1 and 255.")
    segments = max(1, int(params["segments"]))
    compactness = float(params["compactness"])
    if compactness <= 0.0:
        raise ValueError("SLIC compactness must be greater than zero.")

    count = width * height
    rgb = array("f", [0.0]) * (count * 3)
    opaque = bytearray(count)
    for pixel in range(count):
        source, target = pixel * 4, pixel * 3
        rgb[target] = raw[source]
        rgb[target + 1] = raw[source + 1]
        rgb[target + 2] = raw[source + 2]
        opaque[pixel] = 1 if raw[source + 3] >= threshold else 0
    if not any(opaque):
        raise ValueError("The source image is completely transparent.")
    _fill_transparent_rgb_nearest(rgb, opaque, width, height)

    enhanced = _enhance_detail(
        rgb, width, height, float(params["detail"]), float(params["detail_radius"])
    )
    edges = _detect_edges(enhanced, width, height)
    labels, region_count = _segment_image(
        enhanced, edges, width, height, segments=segments, compactness=compactness
    )
    lab = _to_oklab(enhanced)
    labels, region_count = _merge_material_zones(
        lab, labels, region_count, width, height,
        float(params["material_merge_threshold"]),
        float(params["material_luminance_weight"]),
        float(params["material_chroma_limit"]),
    )
    palette_labs = _to_oklab(array("f", (
        palette[index] for index in range(768)
    )))
    ramps = {
        name.strip(): indices
        for name in str(params["ramps"]).split(",")
        if name.strip() in RAMPS
        for indices in [RAMPS[name.strip()]]
    }
    if not ramps:
        ramps = dict(RAMPS)
    assignments, names, candidates = _assign_region_ramps(
        enhanced, lab, edges, labels, region_count, palette_labs, ramps,
        width, height, float(params["coherence"]),
        int(params["ramp_candidates_per_zone"]),
    )
    indices = bytearray(_quantize_pixels(lab, labels, assignments, names, candidates, ramps, palette_labs))

    fb_pixels = 0
    if fullbright_mask is not None:
        mask = fullbright_mask
        if len(mask) != count:
            raise ValueError("Fullbright mask dimensions do not match the source texture.")
        fb_indices = list(range(fullbright_start, 255))
        fb_palette_labs = _to_oklab(array("f", (
            palette[index] for index in range(768)
        )))
        for pixel, selected in enumerate(mask):
            if not selected or not opaque[pixel]:
                continue
            j = pixel * 3
            color = (lab[j], lab[j + 1], lab[j + 2])
            best_index = min(
                fb_indices,
                key=lambda index: _palette_distance(color, fb_palette_labs, index),
            )
            indices[pixel] = best_index
            fb_pixels += 1

    transparent_count = 0
    for pixel, visible in enumerate(opaque):
        if not visible:
            indices[pixel] = 255
            transparent_count += 1
    stats = {
        "pixels": count,
        "regions": region_count,
        "colors_used": len(set(indices)),
        "transparent_pixels": transparent_count,
        "fullbright_pixels": fb_pixels,
    }
    return bytes(indices), stats



def _downsample_rgba8(width: int, height: int, rgba: bytes) -> tuple[int, int, bytes]:
    """Downsample straight-alpha RGBA8 while avoiding colour fringes."""
    out_width, out_height = max(1, width // 2), max(1, height // 2)
    output = bytearray(out_width * out_height * 4)
    for y in range(out_height):
        for x in range(out_width):
            rgb_sums = [0, 0, 0]
            alpha_sum = 0
            samples = 0
            for dy in range(2):
                for dx in range(2):
                    sx, sy = min(width - 1, x * 2 + dx), min(height - 1, y * 2 + dy)
                    offset = (sy * width + sx) * 4
                    alpha = int(rgba[offset + 3])
                    alpha_sum += alpha
                    for channel in range(3):
                        rgb_sums[channel] += int(rgba[offset + channel]) * alpha
                    samples += 1
            target = (y * out_width + x) * 4
            if alpha_sum:
                for channel in range(3):
                    output[target + channel] = max(
                        0, min(255, int(round(rgb_sums[channel] / alpha_sum)))
                    )
            output[target + 3] = max(
                0, min(255, int(round(alpha_sum / max(1, samples))))
            )
    return out_width, out_height, bytes(output)


def _downsample_fullbright_mask(
    width: int, height: int, mask: Sequence[bool] | bytes | bytearray
) -> bytearray:
    """Keep a lower-mip texel fullbright if any covered source texel was fullbright."""
    out_width, out_height = max(1, width // 2), max(1, height // 2)
    output = bytearray(out_width * out_height)
    for y in range(out_height):
        for x in range(out_width):
            selected = False
            for dy in range(2):
                for dx in range(2):
                    sx, sy = min(width - 1, x * 2 + dx), min(height - 1, y * 2 + dy)
                    if mask[sy * width + sx]:
                        selected = True
                        break
                if selected:
                    break
            output[y * out_width + x] = 1 if selected else 0
    return output


def convert_rgba8_mip_chain(
    width: int,
    height: int,
    rgba: bytes | bytearray | memoryview,
    palette: bytes | bytearray | memoryview,
    settings: dict | None = None,
    *,
    transparent: bool = False,
    fullbright_mask: Sequence[bool] | bytes | bytearray | None = None,
) -> tuple[list[bytes], list[dict]]:
    """Convert a texture and its three Quake mip levels with the material-zone algorithm.

    Every mip is segmented and quantized against the same ramp configuration.
    Non-transparent miptexes ignore the source image alpha channel. For brace
    textures, palette index 255 is reserved for texels below alpha_threshold.
    """
    width, height = int(width), int(height)
    raw = bytes(rgba)
    if width < 1 or height < 1 or width * height > 16_777_216:
        raise ValueError("Image dimensions are empty or exceed the safe 16-megapixel conversion limit.")
    if len(raw) != width * height * 4:
        raise ValueError("RGBA input size does not match the supplied dimensions.")
    palette = validate_palette(palette)
    params = dict(DEFAULT_SETTINGS)
    if settings:
        params.update(settings)
    alpha_threshold = int(params["alpha_threshold"])
    if not 0 <= alpha_threshold <= 255:
        raise ValueError("Alpha threshold must be between 0 and 255.")
    current_mask = None if fullbright_mask is None else bytearray(
        1 if value else 0 for value in fullbright_mask
    )
    if current_mask is not None and len(current_mask) != width * height:
        raise ValueError("Fullbright mask dimensions do not match the source texture.")

    current_width, current_height = width, height
    current_rgba = raw
    mip_levels: list[bytes] = []
    mip_stats: list[dict] = []
    for level in range(4):
        conversion_rgba = bytearray(current_rgba)
        if not transparent:
            for offset in range(3, len(conversion_rgba), 4):
                conversion_rgba[offset] = 255

        opaque_count = sum(
            1 for offset in range(3, len(conversion_rgba), 4)
            if conversion_rgba[offset] >= alpha_threshold
        )
        if transparent and opaque_count == 0:
            indices = bytes([255]) * (current_width * current_height)
            stats = {
                "pixels": current_width * current_height,
                "regions": 0,
                "colors_used": 1,
                "transparent_pixels": current_width * current_height,
                "fullbright_pixels": 0,
            }
        else:
            indices, stats = convert_rgba8(
                current_width, current_height, conversion_rgba, palette,
                settings=params, fullbright_mask=current_mask,
            )
        mip_levels.append(indices)
        mip_stats.append(stats)

        if level < 3:
            next_width, next_height, current_rgba = _downsample_rgba8(
                current_width, current_height, current_rgba
            )
            if current_mask is not None:
                current_mask = _downsample_fullbright_mask(
                    current_width, current_height, current_mask
                )
            current_width, current_height = next_width, next_height

    return mip_levels, mip_stats


def _palette_distance(color, palette_labs: array, index: int) -> float:
    j = index * 3
    dL = color[0] - palette_labs[j]
    da = color[1] - palette_labs[j + 1]
    db = color[2] - palette_labs[j + 2]
    return dL * dL + da * da + db * db


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def save_indexed_png(path: str | Path, width: int, height: int,
                     indices: bytes | bytearray | memoryview,
                     palette: bytes | bytearray | memoryview) -> None:
    """Write an 8-bit indexed PNG with the exact 256-color Quake PLTE."""
    width, height = int(width), int(height)
    raw_indices = bytes(indices)
    palette = validate_palette(palette)
    if len(raw_indices) != width * height:
        raise ValueError("Indexed image size does not match the requested PNG dimensions.")
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)  # PNG filter type None.
        start = y * width
        scanlines.extend(raw_indices[start:start + width])
    header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    transparency = bytes([255] * 255 + [0])
    data = bytearray(b"\x89PNG\r\n\x1a\n")
    data.extend(_png_chunk(b"IHDR", header))
    data.extend(_png_chunk(b"PLTE", palette))
    data.extend(_png_chunk(b"tRNS", transparency))
    data.extend(_png_chunk(b"IDAT", zlib.compress(bytes(scanlines), level=6)))
    data.extend(_png_chunk(b"IEND", b""))
    Path(path).write_bytes(data)
