# Eevee lightmap capture spike

This is an isolated experiment. It does not change the production Cycles baker or add an Eevee option to the UI.

## Goal

Determine whether Blender 5.3 Eevee can provide a fast, stable source of direct-light + shadow samples that can be written into SLOPGATE's existing world-aligned lightmap charts and then passed through the existing BSP29 export path.

## Important distinction

Eevee irradiance volumes are not UV lightmap atlases. This spike tests a different strategy: render chart-aligned orthographic views and sample the render into chart luxels. Reflection probes are not involved.

## Stage 0: renderer/camera feasibility

### Run from Blender's UI (recommended)

1. Check out the `experiment/eevee-lightmap-capture-spike` branch, or obtain `manual_eevee_lightmap_probe.py` from that branch.
2. In Blender 5.3, open the **Scripting** workspace.
3. In the Text Editor, choose **Open** and select `manual_eevee_lightmap_probe.py`.
4. Press **Run Script**.

The probe creates a separate temporary scene, renders it with Eevee Next, checks the rendered pixels, loads the PNG into Blender, then removes only the temporary scene and its datablocks. Your current scene, objects, lights, and render settings are left unchanged. When launched from the Text Editor or Python Console, the editor area switches to an Image Editor showing the result.

The default output is `qss_eevee_probe.png` in Blender's temporary directory. The system console / Blender console prints a line beginning with `QSS_EEVEE_PROBE` containing Blender version, render duration, sampled-pixel statistics, and output path.

### Optional: run in background mode

```sh
blender --background --python tests/manual_eevee_lightmap_probe.py -- --output /tmp/qss_eevee_probe.png
```

This creates a lit receiver plane, an occluding cube, an orthographic camera aligned to the receiver plane, and renders with Eevee Next.

This verifies the Blender 5.3 Eevee render API, orthographic chart projection, pixel readback, and shadow rendering. It does **not** yet prove per-face isolation or match Cycles output.

## Stage 1: target-face isolation (blocking question)

A chart render must include the target face's illumination while excluding unrelated camera-visible surfaces, without removing those surfaces as shadow casters. The imported BSP is a single combined mesh, so object-level visibility is insufficient.

Prototype candidate: render the complete scene and use a per-face mask/ID pass to retain only pixels belonging to the chart's receiver faces. Validate material-index or attribute-based masking on a combined mesh in Eevee 5.3. Do not assume Cycles-only ray visibility controls work in Eevee.

If a reliable per-face mask cannot be extracted without changing the lighting/shadow solution, stop and revise the architecture rather than shipping a bake that silently loses occlusion.

## Stage 2: atlas integration

Only after Stage 1 succeeds:
- Render at the chart's exact luxel resolution (or a controlled supersampling factor).
- Derive camera orientation and pixel centres from the chart's world-plane basis, not from a guessed global axis.
- Preserve the chart's model ownership and resolved style grouping.
- Sample linear lighting values; do not bake albedo into the lightmap.
- Populate only valid chart texels, then use the existing chart gutter dilation.
- Keep decoupled BSPX faces on their existing path until separately supported.
- Preserve the existing source atlas and image-undo transaction; write to a disposable float target and commit only after all charts succeed.

## Stage 3: quality and performance comparison

Use the same map, lights, light energies, world, resolution, and bounce policy where possible. Compare:
- Eevee direct-only versus Cycles direct-only.
- Eevee shadow edges and source radius behavior.
- RGB/color management and linear-to-byte conversion.
- Per-face visibility, nodraw/blocklight and inline-model shadow rules.
- Atlas seams and exported BSP in the target engine.
- Wall time, including scene preparation, chart renders, pixel readback and atlas assembly.

Indirect diffuse lighting is a separate milestone. Do not imply irradiance volumes are interchangeable with classic BSP luxels.

## Safety constraints

- Never change the production bake engine by default.
- Do not alter Cycles samples, bounce counts, light settings, or the user's active render engine permanently.
- Do not write into the original lightmap image until the complete experiment succeeds.
- Do not claim Blender runtime validation from Python unit tests or source inspection.
