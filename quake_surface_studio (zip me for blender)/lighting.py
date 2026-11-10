"""Small, Blender-independent helpers for Quake light sample handling."""
from __future__ import annotations


def scaled_quake_light_energy(quake_value: float, energy_scale: float) -> float:
    """Map a Quake light magnitude to an approximate Blender watt value.

    Quake light values are compiler-space artistic intensities, not physical
    watts. The scale is deliberately an exposed multiplier rather than a claim
    of physically exact conversion.
    """
    try:
        magnitude = abs(float(quake_value))
        scale = max(0.0, float(energy_scale))
    except (TypeError, ValueError):
        return 0.0
    return magnitude * scale


def extract_rgb_samples(rgb_lighting: bytes, sample_offset: int, sample_count: int) -> list[tuple[int, int, int]]:
    """Extract RGB luxels at a BSP LIGHTING-byte offset.

    QLIT v1 / BSPX RGBLIGHTING stores one RGB triplet for each byte/sample in
    the classic LIGHTING lump. `sample_offset` is therefore a sample index,
    not a byte offset into the RGB payload.
    """
    start_sample = int(sample_offset)
    count = int(sample_count)
    if start_sample < 0 or count < 0:
        raise ValueError("RGB sample offset and count must be non-negative")
    start = start_sample * 3
    end = (start_sample + count) * 3
    if end > len(rgb_lighting):
        raise ValueError(
            f"RGB lightmap sample range [{start_sample}, {start_sample + count}) "
            f"exceeds {len(rgb_lighting) // 3} available samples"
        )
    return [tuple(rgb_lighting[i:i + 3]) for i in range(start, end, 3)]


def face_has_chromatic_lighting(samples, threshold: int = 12) -> bool:
    """True when any luxel has meaningful RGB channel separation.

    A face can have a bright/dark gradient while remaining neutral grey. This
    predicate distinguishes actual coloured-light contribution from intensity
    variation, which is useful when diagnosing QLIT/BSPX data.
    """
    limit = max(0, int(threshold))
    return any(len(sample) >= 3 and (max(sample[:3]) - min(sample[:3])) >= limit
               for sample in samples)



def bounce_enabled(worldspawn: dict) -> bool:
    """Return whether ericw-tools bounce is enabled in a parsed worldspawn."""
    try:
        return float(worldspawn.get('_bounce', 0.0)) > 0.0
    except (TypeError, ValueError):
        return False


def normalize_light_move(keys, yaw: float):
    """Return a normalized horizontal WASD vector as (x, y), or (0, 0)."""
    import math
    x = y = 0.0
    fx, fy = math.cos(yaw), math.sin(yaw)
    rx, ry = -math.sin(yaw), math.cos(yaw)
    if 'W' in keys: x += fx; y += fy
    if 'S' in keys: x -= fx; y -= fy
    if 'D' in keys: x += rx; y += ry
    if 'A' in keys: x -= rx; y -= ry
    length = math.hypot(x, y)
    if length > 1e-12:
        x /= length; y /= length
    return x, y


def combine_style_samples(mono_lighting: bytes, rgb_lighting: bytes | None,
                          sample_offset: int, sample_count: int,
                          styles, style_weights: dict[int, float] | None = None):
    """Sum all active Quake face light-style planes into one static RGB plane.

    Quake stores one contiguous luxel block per non-255 style in the face's
    styles[0..3] array.  The corresponding QLIT v1 payload has the same sample
    order, with three bytes per monochrome LIGHTING byte.  Static Studio mode
    defaults every active style to weight 1.0; callers may override weights.
    """
    offset = int(sample_offset)
    count = int(sample_count)
    if offset < 0 or count < 0:
        raise ValueError("Sample offset and count must be non-negative")
    active_styles = [int(style) for style in styles if int(style) != 255]
    if not active_styles:
        return [(0, 0, 0)] * count
    weights = style_weights or {}
    accumulated = [[0.0, 0.0, 0.0] for _ in range(count)]
    for layer_index, style_id in enumerate(active_styles):
        layer_offset = offset + layer_index * count
        weight = max(0.0, float(weights.get(style_id, 1.0)))
        if weight == 0.0:
            continue
        if rgb_lighting is not None:
            plane = extract_rgb_samples(rgb_lighting, layer_offset, count)
        else:
            start, end = layer_offset, layer_offset + count
            if end > len(mono_lighting):
                raise ValueError(
                    f"Light-style sample range [{start}, {end}) exceeds "
                    f"{len(mono_lighting)} monochrome samples"
                )
            plane = [(value, value, value) for value in mono_lighting[start:end]]
        for i, sample in enumerate(plane):
            for channel in range(3):
                accumulated[i][channel] += sample[channel] * weight
    return [tuple(max(0, min(255, int(round(channel)))) for channel in sample)
            for sample in accumulated]


def infer_entity_style(entity: dict) -> tuple[int, bool]:
    """Read a light style, tolerating a legacy empty-key value when present.

    A valid map should use `"style" "N"`.  The empty-key fallback is included
    for the malformed entity shown in some editor/compiler logs; callers should
    still report that the value was inferred rather than silently rewriting it.
    """
    raw = entity.get('style')
    inferred = False
    if raw is None and '' in entity:
        raw = entity.get('')
        inferred = raw is not None
    try:
        value = int(float(raw)) if raw is not None else 0
    except (TypeError, ValueError):
        value = 0
        inferred = False
    return max(0, min(255, value)), inferred


def calibration_factor(source_luminance, baked_luminance, current_scale: float) -> float:
    """Multiplier making a current linear bake's mean match the source mean."""
    source = max(0.0, float(source_luminance))
    baked = max(0.0, float(baked_luminance))
    scale = max(0.0, float(current_scale))
    if source <= 1e-8 or baked <= 1e-8 or scale <= 0.0:
        raise ValueError("Source, bake and current energy scale must all be non-zero")
    return min(100000.0, max(1e-6, scale * source / baked))


def bake_atlas_match_scale(source_luminance, baked_luminance) -> float:
    """Scale the current baked atlas to the source mean, independent of lamp slider.

    The Cycles bake already contains the currently selected lamp energy scale.
    Applying that scale again when normalizing the atlas would double-count it.
    """
    source = max(0.0, float(source_luminance))
    baked = max(0.0, float(baked_luminance))
    if source <= 1e-8 or baked <= 1e-8:
        raise ValueError("Source and baked luminance must both be non-zero")
    return min(100000.0, max(1e-6, source / baked))

# ericw-tools light attenuation. LF_SCALE is defined in ericw-tools' light
# headers as 128; these helpers mirror GetLightValue() for static point lights.
ERICW_LIGHT_SCALE = 128.0


def ericw_light_value(light_value: float, delay: int, distance: float,
                      wait: float = 1.0, world_dist: float = 1.0,
                      falloff: float = 0.0) -> float:
    """Return ericw-tools point-light intensity at a luxel (before color/range).

    delay 0: linear, delay 1: inverse, delay 2: inverse-square,
    delay 3: infinite, delay 4: local-minlight ceiling, delay 5: softened
    inverse-square. For delay 4 the returned value is a clamp threshold; the
    caller must apply it with max(current, threshold), not addition.
    """
    import math
    light = float(light_value)
    dist = max(0.1, float(distance))
    attenuation = max(1e-6, float(wait)) * max(1e-6, float(world_dist))
    formula = int(delay)
    if formula == 0:
        if float(falloff) > 0.0:
            # Worldspawn _dist scales the fade distance globally. In _falloff
            # mode the entity's wait key is ignored, but the world distance
            # multiplier still applies to the map-space cutoff radius.
            radius = float(falloff) * max(1e-6, float(world_dist))
            return light * max(0.0, 1.0 - dist / radius) if dist < radius else 0.0
        value = attenuation * dist
        if light >= 0.0:
            return max(0.0, light - value)
        return min(0.0, light + value)
    value = attenuation * dist
    if formula == 1:
        return light / max(1e-12, value / ERICW_LIGHT_SCALE)
    if formula == 2:
        return light / max(1e-12, (value * value) / (ERICW_LIGHT_SCALE ** 2))
    if formula in (3, 4):
        return light
    if formula == 5:
        shifted = value + ERICW_LIGHT_SCALE
        return light / max(1e-12, (shifted * shifted) / (ERICW_LIGHT_SCALE ** 2))
    # ericw treats unknown delay values as the default linear formula.
    value = attenuation * dist
    if light >= 0.0:
        return max(0.0, light - value)
    return min(0.0, light + value)


def ericw_surface_angle(normal_dot_to_light: float, anglescale: float = 0.5,
                        bleed: bool = False) -> float:
    """Lambert/incidence factor used by ericw-tools for a receiving surface."""
    dot = float(normal_dot_to_light)
    if bleed:
        dot = abs(dot)
    elif dot < 0.0:
        return 0.0
    scale = max(0.0, min(1.0, float(anglescale)))
    return max(0.0, (1.0 - scale) + scale * dot)


def ericw_spot_factor(dot_light_to_sample: float, outer_angle: float = 40.0,
                      inner_angle: float = 0.0) -> float:
    """Return ericw-style hard/soft spotlight cone factor from source direction."""
    import math
    outer = max(0.1, min(179.9, float(outer_angle)))
    inner = max(0.0, min(outer, float(inner_angle)))
    outer_cos = math.cos(math.radians(outer * 0.5))
    inner_cos = math.cos(math.radians(inner * 0.5)) if inner > 0.0 else outer_cos
    value = float(dot_light_to_sample)
    if value < outer_cos:
        return 0.0
    if inner <= 0.0 or value >= inner_cos:
        return 1.0
    span = max(1e-12, inner_cos - outer_cos)
    return max(0.0, min(1.0, (value - outer_cos) / span))


def solve_texinfo_plane(s_axis, t_axis, plane_normal, s_value: float,
                        t_value: float, plane_distance: float):
    """Solve S/T texinfo projections plus a plane equation for a world point.

    s_axis/t_axis are three-component projection vectors. The S/T offsets are
    subtracted from s_value/t_value by the caller. Returns None if singular.
    """
    import math
    a = tuple(float(v) for v in s_axis[:3])
    b = tuple(float(v) for v in t_axis[:3])
    c = tuple(float(v) for v in plane_normal[:3])
    cross_bc = (b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0])
    cross_ca = (c[1]*a[2]-c[2]*a[1], c[2]*a[0]-c[0]*a[2], c[0]*a[1]-c[1]*a[0])
    cross_ab = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    determinant = a[0]*cross_bc[0] + a[1]*cross_bc[1] + a[2]*cross_bc[2]
    if abs(determinant) < 1e-10:
        return None
    inv = 1.0 / determinant
    return tuple((float(s_value)*cross_bc[i] + float(t_value)*cross_ca[i] +
                  float(plane_distance)*cross_ab[i]) * inv for i in range(3))


def ericw_postprocess_rgb(rgb, range_scale: float = 0.5, gamma: float = 1.0, maxlight: float = 255.0):
    """Apply ericw-style global range, gamma and max-channel scaling to RGB values.

    Input/output are in Quake 0..255 lightmap intensity units. The maximum
    channel is scaled uniformly (preserving hue) when it exceeds maxlight.
    """
    import math
    values = [max(0.0, float(c)) * max(0.0, float(range_scale)) for c in rgb[:3]]
    g = max(1e-6, float(gamma))
    values = [255.0 * ((v / 255.0) ** (1.0 / g)) if v > 0.0 else 0.0 for v in values]
    limit = max(1e-6, float(maxlight))
    peak = max(values, default=0.0)
    if peak > limit:
        factor = limit / peak
        values = [v * factor for v in values]
    return tuple(max(0.0, min(1.0, v / 255.0)) for v in values)


def evaluate_quake_luxel(sample_position, surface_normal, lights, active_styles,
                          world_dist: float = 1.0, world_range: float = 0.5,
                          world_gamma: float = 1.0, energy_scale: float = 1.0,
                          visible=None, maxlight: float = 255.0,
                          contribution_gate: float = 0.001):
    """Evaluate static direct ericw-style lighting for one BSP luxel.

    `sample_position`, `surface_normal`, light origins and spot directions use
    raw Quake map units / Quake Z-up coordinates. Each light is a mapping with
    origin, value, color, style, delay, wait, falloff, anglescale, direction,
    outer_angle, inner_angle and nostaticlight keys.

    This implements point/spot direct lighting only. `delay=4` contributes a
    channel-wise local-minlight clamp, not additive energy. `visible(light,
    sample_position, surface_normal)` may be supplied by a geometry ray caster.
    The function is Blender-independent so its attenuation and style behavior
    can be regression-tested without Blender.
    """
    import math

    sample = tuple(float(v) for v in sample_position[:3])
    normal = tuple(float(v) for v in surface_normal[:3])
    nlen = math.sqrt(sum(v * v for v in normal))
    if nlen <= 1e-12:
        normal = (0.0, 0.0, 1.0)
    else:
        normal = tuple(v / nlen for v in normal)

    style_set = {int(v) for v in active_styles if int(v) != 255}
    gate = max(0.0, float(contribution_gate))
    if not style_set or float(energy_scale) <= 0.0:
        return (0.0, 0.0, 0.0)

    additive = {style: [0.0, 0.0, 0.0] for style in style_set}
    local_min = {style: [0.0, 0.0, 0.0] for style in style_set}
    for light in lights:
        if bool(light.get('nostaticlight', False)):
            continue
        style = int(light.get('style', 0))
        if style not in style_set:
            continue
        origin = tuple(float(v) for v in light.get('origin', (0.0, 0.0, 0.0))[:3])
        delta = tuple(origin[i] - sample[i] for i in range(3))
        distance = math.sqrt(sum(v * v for v in delta))
        if distance <= 1e-8:
            direction_to_light = (0.0, 0.0, 1.0)
        else:
            direction_to_light = tuple(v / distance for v in delta)

        incidence = sum(normal[i] * direction_to_light[i] for i in range(3))
        bleed = bool(light.get('bleed', False))
        angle_factor = ericw_surface_angle(
            incidence, float(light.get('anglescale', 0.5)), bleed=bleed
        )
        if angle_factor <= 0.0:
            continue
        if visible is not None and not visible(light, sample, normal):
            continue

        if bool(light.get('is_spot', False)):
            spot_dir = tuple(float(v) for v in light.get('direction', (0.0, 0.0, -1.0))[:3])
            spot_len = math.sqrt(sum(v * v for v in spot_dir))
            if spot_len <= 1e-12:
                continue
            spot_dir = tuple(v / spot_len for v in spot_dir)
            # Direction from the source toward the luxel.
            from_light = tuple(-v for v in direction_to_light)
            spot_dot = sum(spot_dir[i] * from_light[i] for i in range(3))
            cone_factor = ericw_spot_factor(
                spot_dot, float(light.get('outer_angle', 40.0)),
                float(light.get('inner_angle', 0.0))
            )
            if cone_factor <= 0.0:
                continue
        else:
            cone_factor = 1.0

        intensity = float(light.get('value', 300.0)) * max(0.0, float(energy_scale))
        falloff = float(light.get('falloff', 0.0))
        wait = float(light.get('wait', 1.0))
        amount = ericw_light_value(
            intensity, int(light.get('delay', 0)), distance, wait,
            float(world_dist), falloff
        ) * angle_factor * cone_factor
        if abs(amount) < gate or abs(amount) <= 0.0:
            continue
        colour = tuple(max(0.0, float(v)) for v in light.get('color', (1.0, 1.0, 1.0))[:3])
        target = local_min[style] if int(light.get('delay', 0)) == 4 else additive[style]
        for channel in range(3):
            value = amount * (colour[channel] if channel < len(colour) else 1.0)
            if int(light.get('delay', 0)) == 4:
                # ericw delay 4 is a local minlight cap. Keep the largest cap
                # per channel; it does not add to the regular light sum.
                target[channel] = max(target[channel], value)
            else:
                target[channel] += value

    total = [0.0, 0.0, 0.0]
    for style in style_set:
        values = [max(additive[style][c], local_min[style][c]) for c in range(3)]
        for channel in range(3):
            total[channel] += values[channel]
    return ericw_postprocess_rgb(
        total, range_scale=float(world_range), gamma=float(world_gamma),
        maxlight=float(maxlight)
    )


def lightmap_bake_margin_pixels(gutter: int = 2, resolution: int = 1) -> int:
    """Return the safe Cycles edge-extension margin for a packed atlas island.

    Atlas gutters are stored in source-luxel units and scaled with the working
    lightmap resolution. Using the full one-sided gutter prevents unfilled bake
    edge pixels while keeping extensions inside the reserved inter-island gap.
    """
    gutter = int(gutter)
    resolution = int(resolution)
    if gutter < 0:
        raise ValueError("Lightmap gutter cannot be negative")
    if resolution < 1:
        raise ValueError("Lightmap resolution must be at least one")
    return gutter * resolution


def blender_live_light_preview_parameters(
    effective_light_value: float,
    raw_light_value: float,
    delay: int,
    wait: float = 1.0,
    world_dist: float = 1.0,
    falloff: float = 0.0,
    unit_scale: float = 0.0254,
):
    """Return a delay-aware native Blender lamp approximation.

    Blender's standard point/spot lights use inverse-square attenuation. Quake
    delay 2 is therefore representable by the same curve after converting the
    Quake 128-unit reference distance to Blender units. Other profiles are
    calibrated at a documented reference point and/or softened/cut off; delays
    3 and 4 remain explicit native-light fallbacks because a constant point
    field and a local-minlight max-clamp are not expressible by a standard lamp.

    Returned profile labels are intended for diagnostics, not as claims of
    pixel-identical ericw-tools output. Quake's exact equations remain in the
    Quake Direct CPU solver.
    """
    import math

    def finite(value, default):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return float(default)
        return result if math.isfinite(result) else float(default)

    intensity = abs(finite(effective_light_value, 0.0))
    raw_intensity = abs(finite(raw_light_value, intensity))
    wait_value = max(1e-6, finite(wait, 1.0))
    dist_scale = max(1e-6, finite(world_dist, 1.0))
    scale = max(1e-9, abs(finite(unit_scale, 0.0254)))
    falloff_value = max(0.0, finite(falloff, 0.0))
    mode = int(delay)
    attenuation = wait_value * dist_scale
    reference_qu = ERICW_LIGHT_SCALE / attenuation
    reference_blender = reference_qu * scale
    min_cutoff = 32.0 * scale

    if mode == 0:
        radius_qu = (falloff_value * dist_scale) if falloff_value > 0.0 else raw_intensity * attenuation
        radius_blender = max(min_cutoff, radius_qu * scale)
        # Match the linear Quake profile at half its radius: QSS receives half
        # the source intensity there, as does an inverse-square lamp at this
        # calibrated energy/radius pair.
        energy = intensity * (radius_blender ** 2) / 8.0
        cutoff = max(min_cutoff, radius_blender)
        soft_size = max(2.0 * scale, radius_blender * 0.02)
        profile = "delay0_linear_midpoint_approximation"
    elif mode == 1:
        energy = intensity * (reference_blender ** 2)
        cutoff = max(min_cutoff, reference_blender * 16.0)
        soft_size = max(scale, reference_blender * 0.01)
        profile = "delay1_inverse_reference_calibration"
    elif mode == 2:
        # Exact radial curve match: E / d_blender^2 equals
        # I * (128 / (wait * world_dist * d_quake))^2.
        energy = intensity * (reference_blender ** 2)
        cutoff = max(min_cutoff, reference_blender * 16.0)
        soft_size = max(scale * 0.5, reference_blender * 0.002)
        profile = "delay2_inverse_square_exact"
    elif mode == 5:
        # The ericw soft inverse-square reaches one quarter of source value at
        # 128/(wait*world_dist) Quake units. Match there and use the same scale
        # as a native spherical emitter to soften the near-source transition.
        energy = intensity * (reference_blender ** 2) / 4.0
        cutoff = max(min_cutoff, reference_blender * 16.0)
        soft_size = max(scale, reference_blender)
        profile = "delay5_soft_inverse_square_approximation"
    else:
        # Native point lights cannot express constant delay 3 or delay 4's
        # per-channel local-minlight clamp. Preserve the familiar prior energy
        # and conservative range rather than inventing false equivalence.
        legacy_radius = max(min_cutoff, raw_intensity * attenuation * scale)
        energy = intensity
        cutoff = legacy_radius
        soft_size = 0.0
        profile = (
            "delay3_native_inverse_square_fallback" if mode == 3 else
            "delay4_native_local_minlight_fallback" if mode == 4 else
            "unknown_delay_native_fallback"
        )

    return {
        "energy": max(0.0, min(1e12, float(energy))),
        "cutoff_distance": max(min_cutoff, min(1e9, float(cutoff))),
        "shadow_soft_size": max(0.0, min(1e6, float(soft_size))),
        "profile": profile,
        "reference_distance": reference_blender,
    }

