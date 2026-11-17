
#!/usr/bin/env python3

import argparse
import sys
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

from scipy.ndimage import gaussian_filter, distance_transform_edt
from skimage.segmentation import slic
from skimage.filters import sobel


# ============================================================
# QUAKE PALETTE RAMPS
# ============================================================

RAMPS = {
    "neutral":       list(range(0, 16)),
    "dark_earth":    list(range(16, 32)),
    "blue_grey":     list(range(32, 48)),
    "olive_dark":    list(range(48, 64)),
    "red":           list(range(64, 80)),
    "ochre":         list(range(80, 96)),
    "warm_earth":    list(range(96, 112)),
    "tan":           list(range(112, 128)),
    "purple_dark":   list(range(128, 144)),
    "purple_warm":   list(range(144, 160)),
    "stone":         list(range(160, 176)),
    "green_grey":    list(range(176, 192)),
    "yellow_ochre":  list(range(192, 208)),
    "blue":          list(range(208, 224)),
}

# Use every non-fullbright palette ramp by default. Restricting the converter
# to a small subset causes unrelated hues to collapse into the nearest earthy
# family, which is especially visible in already-painted game textures.
DEFAULT_RAMPS = list(RAMPS.keys())


# ============================================================
# PALETTE LOADING
# ============================================================

def load_palette(filename):
    path = Path(filename)

    with path.open("r", encoding="ascii") as f:
        lines = [line.strip() for line in f if line.strip()]

    if len(lines) < 3 or lines[0] != "JASC-PAL":
        raise ValueError("Not a valid JASC-PAL palette")

    count = int(lines[2])
    colors = []

    for line in lines[3:3 + count]:
        rgb = [int(x) for x in line.split()]
        if len(rgb) != 3:
            raise ValueError("Invalid palette entry")
        colors.append(rgb)

    if len(colors) != count:
        raise ValueError("Palette entry count mismatch")

    return np.asarray(colors, dtype=np.uint8)


# ============================================================
# COLOR SPACE: sRGB -> OKLab
# ============================================================

def srgb_to_linear(rgb):
    rgb = np.asarray(rgb, dtype=np.float32) / 255.0

    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4
    )


def to_oklab(rgb):
    rgb = srgb_to_linear(rgb)

    l = (
        0.4122214708 * rgb[..., 0]
        + 0.5363325363 * rgb[..., 1]
        + 0.0514459929 * rgb[..., 2]
    )

    m = (
        0.2119034982 * rgb[..., 0]
        + 0.6806995451 * rgb[..., 1]
        + 0.1073969566 * rgb[..., 2]
    )

    s = (
        0.0883024619 * rgb[..., 0]
        + 0.2817188376 * rgb[..., 1]
        + 0.6299787005 * rgb[..., 2]
    )

    l = np.cbrt(l)
    m = np.cbrt(m)
    s = np.cbrt(s)

    return np.stack([
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    ], axis=-1)


# ============================================================
# LOCAL CONTRAST AND DETAIL PRESERVATION
# ============================================================

def enhance_detail(image, amount=0.35, radius=1.2):
    """
    Enhance low-contrast luminance detail.

    No denoising or general-purpose blur is applied.
    The high-frequency luminance component is restored
    to the source before palette quantization.
    """

    if amount <= 0:
        return image.astype(np.float32)

    lab = to_oklab(image)

    luminance = lab[..., 0]

    base = gaussian_filter(
        luminance,
        sigma=radius,
        mode="nearest"
    )

    detail = luminance - base

    # Restrict enhancement to subtle variations.
    # This avoids excessively amplifying strong edges.
    detail = np.clip(detail, -0.12, 0.12)

    lab[..., 0] += amount * detail

    # Convert adjusted OKLab back to approximate RGB.
    L = lab[..., 0]
    a = lab[..., 1]
    b = lab[..., 2]

    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l = l_ ** 3
    m = m_ ** 3
    s = s_ ** 3

    rgb_linear = np.stack([
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ], axis=-1)

    rgb = np.where(
        rgb_linear <= 0.0031308,
        rgb_linear * 12.92,
        1.055 * np.maximum(rgb_linear, 0) ** (1 / 2.4) - 0.055
    )

    return np.clip(rgb * 255.0, 0, 255).astype(np.float32)


# ============================================================
# EDGE DETECTION
# ============================================================

def detect_edges(image):
    """
    Calculate an edge-strength map.

    Used to protect structural detail during region
    analysis and ramp assignment.
    """

    gray = (
        0.299 * image[..., 0]
        + 0.587 * image[..., 1]
        + 0.114 * image[..., 2]
    ) / 255.0

    edges = sobel(gray)

    return edges.astype(np.float32)


# ============================================================
# SLIC SUPERPIXEL SEGMENTATION
# ============================================================

def segment_image(image, segments=180, compactness=10):
    """
    Divide the texture into coherent visual regions.

    Segmentation guides ramp selection but does not
    force pixels within a region to share one color.
    """

    labels = slic(
        image.astype(np.uint8),
        n_segments=segments,
        compactness=compactness,
        sigma=0,
        convert2lab=True,
        enforce_connectivity=True,
        start_label=0,
        channel_axis=-1
    )

    return labels.astype(np.int32)


# ============================================================
# HIERARCHICAL MATERIAL-ZONE MERGING
# ============================================================

def merge_material_zones(
    image, labels, merge_threshold=0.055, luminance_weight=0.20,
    chroma_limit=0.075
):
    """Merge adjacent SLIC superpixels likely to be the same material.

    Game textures commonly contain painted lighting, baked shadows and
    hand-painted value variation. Therefore luminance contributes only a
    small part of material similarity; chroma and local boundary colour
    differences carry more weight. This deliberately avoids treating every
    light/dark patch as a separate material.

    This is a conservative, adjacency-only merge: disconnected areas are
    never joined merely because they have similar colours.
    """
    labels = np.asarray(labels, dtype=np.int32)
    lab = to_oklab(image)
    count = int(labels.max()) + 1

    # Robust region descriptors: medians are less sensitive to painted
    # highlights, scratches and isolated noisy pixels than means.
    descriptors = np.zeros((count, 3), dtype=np.float32)
    for region in range(count):
        pixels = lab[labels == region]
        if len(pixels):
            descriptors[region] = np.median(pixels, axis=0)

    # Collect boundary colour differences for every adjacent pair. The
    # chroma difference is measured independently from luminance so that
    # a shadow boundary alone is not treated as a material boundary.
    boundary_samples = {}
    for a, b in ((labels[:, :-1], labels[:, 1:]),
                 (labels[:-1, :], labels[1:, :])):
        mask = a != b
        if not np.any(mask):
            continue
        aa = a[mask].astype(np.int32)
        bb = b[mask].astype(np.int32)
        # Compare the actual pixels on either side of each superpixel edge.
        if a.shape == labels[:, :-1].shape:
            left = lab[:, :-1][mask]
            right = lab[:, 1:][mask]
        else:
            left = lab[:-1, :][mask]
            right = lab[1:, :][mask]
        for x, y, c1, c2 in zip(aa, bb, left, right):
            key = (min(int(x), int(y)), max(int(x), int(y)))
            delta = c1 - c2
            item = boundary_samples.setdefault(key, [0.0, 0.0, 0])
            item[0] += float(np.linalg.norm(delta[1:]))
            item[1] += float(abs(delta[0]))
            item[2] += 1

    parent = np.arange(count, dtype=np.int32)
    size = np.bincount(labels.ravel(), minlength=count).astype(np.int64)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = int(parent[x])
        return x

    # Sort by the strongest evidence of material continuity. Unioning only
    # neighbouring regions prevents unrelated, distant surfaces merging.
    candidates = []
    for (a, b), (chroma_sum, light_sum, n) in boundary_samples.items():
        if not n:
            continue
        boundary_chroma = chroma_sum / n
        boundary_light = light_sum / n
        da = descriptors[a] - descriptors[b]
        region_chroma = float(np.linalg.norm(da[1:]))
        region_light = float(abs(da[0]))
        # Blend robust region appearance with the actual shared boundary.
        chroma_score = 0.65 * region_chroma + 0.35 * boundary_chroma
        light_score = 0.65 * region_light + 0.35 * boundary_light
        score = float(np.hypot(chroma_score, luminance_weight * light_score))
        if chroma_score <= chroma_limit and score <= merge_threshold:
            candidates.append((score, a, b))

    candidates.sort(key=lambda item: item[0])
    for _score, a, b in candidates:
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        # Union by size. The initial pair test is conservative; no global
        # colour-only clustering is performed.
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]

    roots = np.asarray([find(i) for i in range(count)], dtype=np.int32)
    _unique, compact = np.unique(roots[labels], return_inverse=True)
    return compact.reshape(labels.shape).astype(np.int32)


# ============================================================
# SUPERPIXEL NEIGHBORHOOD GRAPH
# ============================================================

def build_adjacency(labels):
    adjacency = set()

    for a, b in [
        (labels[:, :-1], labels[:, 1:]),
        (labels[:-1, :], labels[1:, :])
    ]:
        mask = a != b

        pairs = np.stack([a[mask], b[mask]], axis=1)

        for x, y in pairs:
            adjacency.add((min(int(x), int(y)),
                           max(int(x), int(y))))

    return list(adjacency)


# ============================================================
# RAMP PREPARATION
# ============================================================

def get_ramps(palette, names, fullbright_start):
    result = {}

    for name in names:
        if name not in RAMPS:
            raise ValueError(f"Unknown ramp: {name}")

        indices = [
            i for i in RAMPS[name]
            if i < fullbright_start and i < len(palette)
        ]

        if indices:
            result[name] = np.asarray(indices, dtype=np.int32)

    if not result:
        raise ValueError("No usable palette ramps")

    return result


# ============================================================
# REGION COLOR ANALYSIS
# ============================================================

def region_statistics(image, labels, edges):
    count = int(labels.max()) + 1

    means = np.zeros((count, 3), dtype=np.float32)
    edge_means = np.zeros(count, dtype=np.float32)
    sizes = np.zeros(count, dtype=np.float32)

    for region in range(count):
        mask = labels == region

        pixels = image[mask]

        if len(pixels) == 0:
            continue

        means[region] = np.mean(pixels, axis=0)
        edge_means[region] = np.mean(edges[mask])
        sizes[region] = len(pixels)

    return means, edge_means, sizes


# ============================================================
# CHOOSE A RAMP FOR EACH REGION
# ============================================================

def assign_region_ramps(
    image,
    labels,
    edges,
    palette,
    ramps,
    coherence=0.025,
    candidates_per_zone=3
):
    """Choose a primary ramp and a small candidate set for each material zone.

    Ramp scoring uses the distribution of actual pixel colours in a zone,
    rather than its average colour. This matters for painted game textures:
    highlights, baked shadows and differently coloured brushwork can coexist
    inside one material zone, and an average can be a colour that is barely
    present in the source at all.

    The primary ramp is used for the zone diagnostic/coherence. Pixel
    quantization may also use the next-best candidate ramps, preventing a
    single ramp from turning a multi-hued zone muddy or brownish.
    """
    names = list(ramps.keys())
    means, edge_means, sizes = region_statistics(image, labels, edges)
    region_lab = to_oklab(means)
    ramp_labs = {name: to_oklab(palette[indices]) for name, indices in ramps.items()}

    region_count = len(means)
    costs = np.zeros((region_count, len(names)), dtype=np.float32)

    # Evaluate the colour distribution of each zone. Deterministic sampling
    # caps work on large textures without making results vary between runs.
    max_samples = 768
    for region in range(region_count):
        pixels = image[labels == region].astype(np.float32)
        if len(pixels) == 0:
            continue
        if len(pixels) > max_samples:
            sample_ids = np.linspace(0, len(pixels) - 1, max_samples, dtype=np.int32)
            pixels = pixels[sample_ids]
        pixels_lab = to_oklab(pixels)
        for j, name in enumerate(names):
            candidates = ramp_labs[name]
            delta = pixels_lab[:, None, :] - candidates[None, :, :]
            distance = np.sum(delta * delta, axis=2)
            # Mean nearest-colour error evaluates the whole colour population.
            # A small upper-tail term discourages ramps that fit only the
            # dominant colour while badly missing the zone's other hues.
            nearest = np.min(distance, axis=1)
            costs[region, j] = float(
                0.85 * np.mean(nearest) + 0.15 * np.percentile(nearest, 85)
            )

    adjacency = build_adjacency(labels)
    assignments = np.argmin(costs, axis=1)

    # Neighborhood coherence remains a gentle prior, not a force that can
    # override a clearly better colour-family match.
    neighbors = [[] for _ in range(region_count)]
    for a, b in adjacency:
        neighbors[a].append(b)
        neighbors[b].append(a)

    for _ in range(5):
        changed = False
        for region in range(region_count):
            scores = costs[region].copy()
            for neighbor in neighbors[region]:
                difference = np.linalg.norm(region_lab[region] - region_lab[neighbor])
                edge_strength = max(edge_means[region], edge_means[neighbor])
                penalty = coherence * np.exp(-difference * 5.0)
                penalty *= max(0.0, 1.0 - edge_strength * 3.0)
                for j in range(len(names)):
                    if j != assignments[neighbor]:
                        scores[j] += penalty
            best = int(np.argmin(scores))
            if best != assignments[region]:
                assignments[region] = best
                changed = True
        if not changed:
            break

    candidate_count = max(1, min(int(candidates_per_zone), len(names)))
    candidate_assignments = np.argsort(costs, axis=1)[:, :candidate_count]
    # Ensure the coherent primary choice is included, even if coherence
    # moved it just outside the purely colour-ranked candidate set.
    for region in range(region_count):
        if assignments[region] not in candidate_assignments[region]:
            candidate_assignments[region, -1] = assignments[region]

    return assignments, names, candidate_assignments


# ============================================================
# PIXEL-LEVEL QUANTIZATION
# ============================================================

def quantize_pixels(
    image,
    labels,
    assignments,
    names,
    ramps,
    palette,
    fullbright_start,
    edge_map,
    candidate_assignments=None
):
    """Quantize pixels using a zone's best few palette ramps.

    Each material zone has a coherent primary ramp, but pixels can select
    from a small set of distribution-matched candidate ramps. This retains
    genuine hue variation within painted surfaces without allowing every
    superpixel to independently choose an unrelated ramp.
    """
    height, width = image.shape[:2]
    output = np.zeros((height, width), dtype=np.uint8)

    ramp_data = {}
    for name, indices in ramps.items():
        colors = palette[indices]
        ramp_data[name] = (indices, to_oklab(colors))

    for region in range(int(labels.max()) + 1):
        mask = labels == region
        if not np.any(mask):
            continue

        if candidate_assignments is None:
            candidate_ids = [int(assignments[region])]
        else:
            candidate_ids = [int(x) for x in candidate_assignments[region]]
        # Keep primary ramp first for deterministic tie-breaking.
        primary = int(assignments[region])
        candidate_ids = [primary] + [x for x in candidate_ids if x != primary]

        all_indices = []
        all_labs = []
        for candidate_id in candidate_ids:
            name = names[candidate_id]
            indices, colors_lab = ramp_data[name]
            all_indices.append(indices)
            all_labs.append(colors_lab)
        palette_indices = np.concatenate(all_indices)
        palette_labs = np.concatenate(all_labs, axis=0)

        pixels_lab = to_oklab(image[mask].astype(np.float32))
        delta = pixels_lab[:, None, :] - palette_labs[None, :, :]
        distance = np.sum(delta * delta, axis=2)
        light_delta = pixels_lab[:, None, 0] - palette_labs[None, :, 0]
        distance += 0.08 * light_delta * light_delta
        best = np.argmin(distance, axis=1)
        output[mask] = palette_indices[best]

    return output


# ============================================================
# SAVE INDEXED PNG
# ============================================================

def save_png(indices, palette, filename):
    image = Image.fromarray(indices.astype(np.uint8), mode="P")

    table = palette.flatten().tolist()
    table += [0] * (768 - len(table))

    image.putpalette(table[:768])
    image.save(filename, optimize=False, transparency=255)



# ============================================================
# OPENRASTER (.ORA) LAYER EXPORT
# ============================================================

def rgba_layer(rgb, mask=None):
    """Create an RGBA layer; pixels outside mask are transparent."""
    rgb = np.asarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = rgb
    if mask is None:
        rgba[..., 3] = 255
    else:
        rgba[..., 3] = np.asarray(mask, dtype=np.uint8) * 255
    return rgba


def png_bytes(image):
    """Encode a PIL-compatible image as PNG bytes."""
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def diagnostic_region_colors(labels):
    """Give each SLIC region a stable, visually distinct diagnostic color."""
    count = int(labels.max()) + 1
    # Golden-ratio hue stepping avoids adjacent regions receiving similar colors.
    hues = (np.arange(count, dtype=np.float32) * 0.61803398875) % 1.0
    colors = np.zeros((count, 3), dtype=np.uint8)
    for i, hue in enumerate(hues):
        rgb = np.asarray(Image.new("RGB", (1, 1), (0, 0, 0)))
        # HSV conversion is implemented here to avoid another dependency.
        h6 = hue * 6.0
        sector = int(h6) % 6
        f = h6 - int(h6)
        v, s = 0.92, 0.78
        p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
        choices = [
            (v, t, p), (q, v, p), (p, v, t),
            (p, q, v), (t, p, v), (v, p, q)
        ]
        colors[i] = np.clip(np.asarray(choices[sector]) * 255, 0, 255)
    return colors[labels]


def save_ora(
    filename,
    result_indices,
    palette,
    superpixel_labels,
    zone_labels,
    assignments,
    names,
    ramps,
    edges,
    detail_source,
    original_source,
    opaque_mask=None,
    fullbright_mask=None
):
    """
    Write a standards-compliant OpenRaster document.

    The visible top layer is the finished texture. Ramp and diagnostic
    layers are included underneath and start hidden, so opening the ORA
    shows the same result as the indexed PNG.
    """
    height, width = result_indices.shape
    rgb_result = palette[result_indices]

    # The indexed PNG is preserved separately; ORA layers are RGB/RGBA.
    layers = []

    # Top visible merged result.
    layers.append(("Final texture", rgba_layer(rgb_result, opaque_mask), True))

    # Keep the untouched source image in the project for comparison/editing.
    # It starts hidden so the converted result remains the initial appearance.
    layers.append(("Original source", rgba_layer(original_source, opaque_mask), False))
    if opaque_mask is not None and not np.all(opaque_mask):
        layers.append(("Diagnostic - transparency mask", rgba_layer(
            np.repeat((~opaque_mask).astype(np.uint8)[..., None] * 255, 3, axis=2)
        ), False))

    if fullbright_mask is not None and np.any(fullbright_mask):
        fb_rgb = np.repeat(fullbright_mask.astype(np.uint8)[..., None] * 255, 3, axis=2)
        layers.append(("Diagnostic - fullbright mask", rgba_layer(fb_rgb), False))
        fb_used = fullbright_mask & (result_indices != 255)
        layers.append(("Fullbright pixels", rgba_layer(rgb_result, fb_used), False))

    # One transparent contribution layer per palette ramp.
    for ramp_name in names:
        mask = np.isin(result_indices, ramps[ramp_name])
        contribution = rgba_layer(rgb_result, mask)
        layers.append((f"Ramp - {ramp_name}", contribution, False))

    # Show both the initial SLIC segmentation and the merged material zones.
    superpixel_rgb = diagnostic_region_colors(superpixel_labels)
    layers.append(("Diagnostic - SLIC superpixels", rgba_layer(superpixel_rgb), False))
    zone_rgb = diagnostic_region_colors(zone_labels)
    layers.append(("Diagnostic - material zones", rgba_layer(zone_rgb), False))

    # Ramp assignment diagnostic: flat color per selected ramp family.
    ramp_display = np.zeros((height, width, 3), dtype=np.uint8)
    for name in names:
        # Show the ramp actually used by each output pixel, including
        # secondary candidate ramps within a material zone.
        indices = ramps[name]
        mask = np.isin(result_indices, indices)
        ramp_display[mask] = palette[indices[len(indices) // 2]]
    layers.append(("Diagnostic - ramp assignments", rgba_layer(ramp_display), False))

    # Edge map.
    edge_gray = np.clip(edges * 255.0 * 2.5, 0, 255).astype(np.uint8)
    edge_rgb = np.repeat(edge_gray[..., None], 3, axis=2)
    layers.append(("Diagnostic - edges", rgba_layer(edge_rgb), False))

    # Detail map: absolute local luminance detail, normalized for visibility.
    lab_l = to_oklab(detail_source)[..., 0]
    local_base = gaussian_filter(lab_l, sigma=1.2, mode="nearest")
    detail = np.abs(lab_l - local_base)
    scale = np.percentile(detail, 99.0) if np.any(detail) else 1.0
    detail_gray = np.clip(detail / max(float(scale), 1e-6) * 255.0, 0, 255).astype(np.uint8)
    detail_rgb = np.repeat(detail_gray[..., None], 3, axis=2)
    layers.append(("Diagnostic - fine detail", rgba_layer(detail_rgb), False))

    # OpenRaster requires mimetype first and uncompressed.
    root = ET.Element("image", {
        "version": "0.0.1",
        "w": str(width),
        "h": str(height),
        "name": Path(filename).stem
    })
    stack = ET.SubElement(root, "stack")

    # stack.xml lists topmost layer first, matching the layer list above.
    for index, (name, _rgba, visible) in enumerate(layers):
        ET.SubElement(stack, "layer", {
            "name": name,
            "src": f"data/layer{index:03d}.png",
            "opacity": "1.0",
            "visibility": "visible" if visible else "hidden",
            "composite-op": "svg:src-over",
            "x": "0",
            "y": "0"
        })

    stack_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    with zipfile.ZipFile(filename, "w") as archive:
        archive.writestr("mimetype", "image/openraster",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("stack.xml", stack_xml,
                         compress_type=zipfile.ZIP_DEFLATED)
        for index, (_name, rgba, _visible) in enumerate(layers):
            archive.writestr(
                f"data/layer{index:03d}.png",
                png_bytes(rgba),
                compress_type=zipfile.ZIP_DEFLATED
            )
        archive.writestr(
            "mergedimage.png",
            png_bytes(rgb_result),
            compress_type=zipfile.ZIP_DEFLATED
        )


# ============================================================
# SETTINGS AND CONVERSION
# ============================================================


def read_settings(filename):
    """Read simple key=value settings; command-line flags override these."""
    import configparser

    config = configparser.ConfigParser()
    path = Path(filename)
    if path.exists():
        config.read(path, encoding="utf-8")
    values = config["conversion"] if config.has_section("conversion") else {}

    def get(key, fallback, cast):
        try:
            return cast(values.get(key, fallback))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid '{key}' value in {path}: {values.get(key)!r}") from exc

    return {
        "palette": get("palette", "quake.pal", str),
        "ramps": get("ramps", ",".join(DEFAULT_RAMPS), str),
        "fullbright_start": get("fullbright_start", "224", int),
        "segments": get("segments", "180", int),
        "compactness": get("compactness", "10.0", float),
        "detail": get("detail", "0.35", float),
        "detail_radius": get("detail_radius", "1.2", float),
        "coherence": get("coherence", "0.025", float),
        "material_merge_threshold": get("material_merge_threshold", "0.055", float),
        "material_luminance_weight": get("material_luminance_weight", "0.20", float),
        "material_chroma_limit": get("material_chroma_limit", "0.075", float),
        "ramp_candidates_per_zone": get("ramp_candidates_per_zone", "3", int),
        "alpha_threshold": get("alpha_threshold", "128", int),
        "color_key_tolerance": get("color_key_tolerance", "0", int),
        "fullbright_masks": get("fullbright_masks", "true", lambda x: str(x).lower() in ("1", "true", "yes", "on")),
    }


def decode_source_image(input_path, color_key=None, color_key_tolerance=0, alpha_threshold=128):
    """Decode RGB and transparency independently; return RGB, opaque mask, palette stats."""
    with Image.open(input_path) as source:
        source.load()
        indexed_stats = None
        if source.mode == "P":
            source_indices = np.asarray(source, dtype=np.uint8)
            counts = np.bincount(source_indices.ravel(), minlength=256)
            used = np.flatnonzero(counts)
            indexed_stats = (len(used), int(counts.sum()))

        has_alpha = "A" in source.getbands() or "transparency" in source.info
        rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8)
        rgb = rgba[..., :3].copy()

        if has_alpha:
            opaque = rgba[..., 3] >= int(alpha_threshold)
            transparency_source = "alpha channel / palette transparency"
        elif color_key is not None:
            key = np.asarray([int(color_key[i:i+2], 16) for i in (0, 2, 4)], dtype=np.int16)
            delta = np.abs(rgb.astype(np.int16) - key)
            opaque = np.max(delta, axis=2) > int(color_key_tolerance)
            transparency_source = f"colour key #{color_key.upper()} (tolerance {color_key_tolerance})"
        else:
            opaque = np.ones(rgb.shape[:2], dtype=bool)
            transparency_source = "none"

    if not np.any(opaque):
        raise ValueError("Source image is entirely transparent")
    if not np.all(opaque):
        # Prevent hidden RGB under transparent pixels from contaminating segmentation.
        nearest = distance_transform_edt(~opaque, return_distances=False, return_indices=True)
        rgb[~opaque] = rgb[tuple(axis[~opaque] for axis in nearest)]
    return rgb.astype(np.float32), opaque, indexed_stats, transparency_source


def load_fullbright_mask(input_path, enabled=True):
    """Load sibling <stem>_fullbrights.png; white means fullbright, black means normal."""
    if not enabled:
        return None, None
    source = Path(input_path)
    mask_path = source.with_name(source.stem + "_fullbrights.png")
    if not mask_path.is_file():
        return None, None
    with Image.open(mask_path) as mask_image:
        mask_image.load()
        if mask_image.size != Image.open(source).size:
            raise ValueError(f"Fullbright mask dimensions do not match source: {mask_path}")
        # Treat any non-black pixel with luminance >= 128 as white/fullbright.
        gray = np.asarray(mask_image.convert("L"), dtype=np.uint8)
    return gray >= 128, mask_path


def convert_one(input_path, output_path, args, palette):
    """Convert one image and optionally write its layered ORA project."""
    original, opaque_mask, indexed_stats, transparency_source = decode_source_image(
        input_path, color_key=args.color_key,
        color_key_tolerance=args.color_key_tolerance,
        alpha_threshold=args.alpha_threshold
    )

    print(f"\nProcessing: {input_path}")
    print(f"  Transparency: {transparency_source}; transparent pixels: {int((~opaque_mask).sum())}")
    if indexed_stats is not None:
        print(f"  Indexed source palette: {indexed_stats[0]} used entries across {indexed_stats[1]} pixels")
    fullbright_mask, fullbright_path = load_fullbright_mask(
        input_path, enabled=getattr(args, "fullbright_masks", True)
    )
    if fullbright_mask is not None:
        print(f"  Fullbright mask: {fullbright_path}; marked pixels: {int(fullbright_mask.sum())}")
        if fullbright_mask.shape != opaque_mask.shape:
            raise ValueError(f"Fullbright mask dimensions do not match source: {fullbright_path}")
        # Source transparency always wins over the emissive mask.
        fullbright_mask &= opaque_mask

    image = enhance_detail(
        original,
        amount=args.detail,
        radius=args.detail_radius
    )

    print("  Detecting edges...")
    edges = detect_edges(image)

    print("  Detecting initial superpixels...")
    superpixel_labels = segment_image(
        image,
        segments=args.segments,
        compactness=args.compactness
    )

    print("  Merging superpixels into material zones...")
    zone_labels = merge_material_zones(
        image, superpixel_labels,
        merge_threshold=args.material_merge_threshold,
        luminance_weight=args.material_luminance_weight,
        chroma_limit=args.material_chroma_limit
    )

    ramp_names = [x.strip() for x in args.ramps.split(",") if x.strip()]
    ramps = get_ramps(palette, ramp_names, args.fullbright_start)

    print("  Assigning palette ramps per material zone...")
    assignments, names, candidate_assignments = assign_region_ramps(
        image, zone_labels, edges, palette, ramps,
        coherence=args.coherence,
        candidates_per_zone=args.ramp_candidates_per_zone
    )

    print("  Quantizing pixels...")
    result = quantize_pixels(
        image, zone_labels, assignments, names, ramps,
        palette, args.fullbright_start, edges,
        candidate_assignments=candidate_assignments
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fullbright_mask is not None and np.any(fullbright_mask):
        # Fullbright entries are selected only from [fullbright_start, 254].
        # Index 255 is reserved for Quake transparency and is never a colour candidate.
        fb_indices = np.arange(args.fullbright_start, 255, dtype=np.int32)
        if len(fb_indices) == 0:
            raise ValueError("No fullbright palette entries available before transparent index 255")
        fb_lab = to_oklab(palette[fb_indices])
        fb_pixels = to_oklab(image[fullbright_mask].astype(np.float32))
        delta = fb_pixels[:, None, :] - fb_lab[None, :, :]
        distances = np.sum(delta * delta, axis=2)
        result[fullbright_mask] = fb_indices[np.argmin(distances, axis=1)]
    result[~opaque_mask] = 255
    save_png(result, palette, output_path)

    if args.layers is not None:
        ora_dir = getattr(args, "ora_dir", None)
        ora_path = (Path(ora_dir) / output_path.with_suffix(".ora").name) if ora_dir else output_path.with_suffix(".ora")
        ora_path.parent.mkdir(parents=True, exist_ok=True)
        save_ora(
            ora_path, result, palette, superpixel_labels, zone_labels,
            assignments, names, ramps, edges, image, original.astype(np.uint8), opaque_mask, fullbright_mask
        )
        print(f"  Layered project: {ora_path}")

    used = np.unique(result)
    print(f"  Saved: {output_path}")
    print(
        f"  Superpixels: {int(superpixel_labels.max()) + 1} | "
        f"Material zones: {int(zone_labels.max()) + 1} | Colors used: {len(used)}"
    )


def main():
    script_settings = Path(__file__).with_name("conv_settings.ini")
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--settings", default=str(script_settings))
    known, _ = preliminary.parse_known_args()

    try:
        defaults = read_settings(known.settings)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(
        description="Convert one image or a whole folder to the Quake 256-color palette."
    )
    parser.add_argument("input", help="Input image, or folder containing images")
    parser.add_argument(
        "output", nargs="?",
        help="Output PNG filename (single image), or output folder (batch). "
             "For batch mode the default is INPUT/converted/"
    )
    parser.add_argument(
        "--settings", default=str(script_settings),
        help="Settings file to use (default: conv_settings.ini next to this script)"
    )
    parser.add_argument("--recursive", action="store_true",
                        help="In folder mode, include subfolders and preserve their relative structure")
    parser.add_argument(
        "--layers", nargs="?", const="auto", default=None,
        metavar="FILE.ora",
        help="Also export layered OpenRaster file(s). In batch mode, use --layers without a filename."
    )

    parser.add_argument("--palette", default=defaults["palette"], help="JASC palette file")
    parser.add_argument("--ramps", default=defaults["ramps"], help="Comma-separated palette ramp names")
    parser.add_argument("--fullbright-start", type=int, default=defaults["fullbright_start"],
                        help="First fullbright palette index; these colors are excluded from matching")
    parser.add_argument("--segments", type=int, default=defaults["segments"],
                        help="SLIC region count: lower = larger regions; higher = smaller regions")
    parser.add_argument("--compactness", type=float, default=defaults["compactness"],
                        help="SLIC shape regularity: higher = more compact, grid-like regions")
    parser.add_argument("--detail", type=float, default=defaults["detail"],
                        help="Fine surface contrast: 0 disables enhancement; higher preserves more subtle detail")
    parser.add_argument("--detail-radius", type=float, default=defaults["detail_radius"],
                        help="Scale of detail enhancement; larger values affect broader variations")
    parser.add_argument("--coherence", type=float, default=defaults["coherence"],
                        help="Ramp consistency between neighboring regions: higher = more sharing")
    parser.add_argument("--material-merge-threshold", type=float,
                        default=defaults["material_merge_threshold"],
                        help="How readily adjacent superpixels merge into one material zone")
    parser.add_argument("--material-luminance-weight", type=float,
                        default=defaults["material_luminance_weight"],
                        help="Influence of light/dark differences on material identity; lower ignores painted lighting more")
    parser.add_argument("--material-chroma-limit", type=float,
                        default=defaults["material_chroma_limit"],
                        help="Maximum chroma difference allowed when merging material zones")
    parser.add_argument("--ramp-candidates-per-zone", type=int,
                        default=defaults["ramp_candidates_per_zone"],
                        help="Number of best-fit palette ramps available to pixels inside each material zone")
    parser.add_argument("--alpha-threshold", type=int, default=defaults["alpha_threshold"],
                        help="Alpha values below this are transparent (0..255; default 128)")
    parser.add_argument("--color-key", metavar="RRGGBB",
                        help="Treat this RGB colour as transparent when source has no alpha")
    parser.add_argument("--color-key-tolerance", type=int, default=defaults["color_key_tolerance"],
                        help="Per-channel RGB tolerance for --color-key (default 0 = exact)")
    parser.add_argument("--ora-dir", default=None, help="Optional directory for ORA diagnostic projects")
    parser.add_argument("--no-fullbright-masks", dest="fullbright_masks", action="store_false",
                        default=defaults["fullbright_masks"], help="Disable sibling *_fullbrights.png mask detection")

    args = parser.parse_args()

    try:
        palette = load_palette(args.palette)
        if len(palette) != 256:
            raise ValueError("Expected a 256-entry palette")
        if not 1 <= args.fullbright_start <= 256:
            raise ValueError("--fullbright-start must be 1..256")
        if args.segments < 1:
            raise ValueError("--segments must be positive")
        if args.compactness <= 0:
            raise ValueError("--compactness must be greater than zero")
        if args.detail_radius <= 0:
            raise ValueError("--detail-radius must be greater than zero")
        if args.detail < 0 or args.coherence < 0:
            raise ValueError("--detail and --coherence cannot be negative")
        if args.material_merge_threshold < 0 or args.material_luminance_weight < 0 or args.material_chroma_limit < 0:
            raise ValueError("Material-zone thresholds and weights cannot be negative")
        if args.ramp_candidates_per_zone < 1:
            raise ValueError("--ramp-candidates-per-zone must be at least 1")
        if not 0 <= args.alpha_threshold <= 255:
            raise ValueError("--alpha-threshold must be 0..255")
        if not 0 <= args.color_key_tolerance <= 255:
            raise ValueError("--color-key-tolerance must be 0..255")
        if args.color_key is not None:
            args.color_key = args.color_key.lstrip("#")
            if len(args.color_key) != 6 or any(c not in "0123456789abcdefABCDEF" for c in args.color_key):
                raise ValueError("--color-key must be a six-digit RGB value, e.g. FF00FF")

        input_path = Path(args.input)
        if not input_path.exists():
            raise FileNotFoundError(f"Input does not exist: {input_path}")

        if input_path.is_dir():
            output_dir = Path(args.output) if args.output else input_path / "converted"
            output_dir.mkdir(parents=True, exist_ok=True)
            supported = {".tga", ".png", ".jpg", ".jpeg", ".bmp", ".pcx", ".webp"}
            iterator = input_path.rglob("*") if args.recursive else input_path.iterdir()
            files = sorted(
                p for p in iterator
                if p.is_file() and p.suffix.lower() in supported
                and output_dir not in p.parents
            )
            if not files:
                raise ValueError(f"No supported images found in {input_path}")
            if args.layers not in (None, "auto"):
                raise ValueError("In batch mode, use --layers without a filename; each image gets its own .ora")

            print(f"Batch: {len(files)} image(s)")
            print(f"Output folder: {output_dir}")
            failures = []
            for image_path in files:
                relative = image_path.relative_to(input_path) if args.recursive else Path(image_path.name)
                out_png = (output_dir / relative).with_suffix(".png")
                try:
                    convert_one(image_path, out_png, args, palette)
                except Exception as exc:
                    failures.append((image_path, exc))
                    print(f"  FAILED: {image_path.name}: {exc}", file=sys.stderr)
            print(f"\nBatch finished: {len(files) - len(failures)} succeeded, {len(failures)} failed.")
            if failures:
                return 1
        else:
            if not args.output:
                raise ValueError("For a single image, provide an output PNG filename")
            if args.layers not in (None, "auto"):
                # Retain the convenient explicit ORA filename option for single-image mode.
                requested_ora = Path(args.layers)
            else:
                requested_ora = None
            convert_one(input_path, args.output, args, palette)
            if requested_ora is not None:
                default_ora = Path(args.output).with_suffix(".ora")
                generated_ora = default_ora
                if requested_ora != generated_ora:
                    generated_ora.replace(requested_ora)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
