# Quake Surface Studio 0.13.0

## 0.13.0 changes

- Added a standalone **BSP export integrity checker**: `qss_export_check.py source.bsp exported.bsp`. It compares the source and exported files, checks that topology-related standard lumps and unknown BSPX payloads survive, validates face/texture/texinfo references and classic lightmap sample bounds, and verifies a sibling QLIT v1 `.lit` sidecar.
- Added an opt-in **Enhanced BSPX (LMSHIFT)** lightmap export mode alongside the unchanged default **Classic BSP29** mode.
- Enhanced export retains the original classic LIGHTING samples at the front of the standard lump, then appends per-face higher-density monochrome and RGB samples. `LMOFFSET` points into the appended region; `LMSHIFT` selects per-face luxel spacing; `LMSTYLE` declares the flattened static style 0. The resulting BSPX `RGBLIGHTING` and QLIT v1 `.lit` contain matching sample counts.
- The enhanced sampling pitch follows the imported working atlas: 1× = 16-unit luxels, 2× = 8, 4× = 4, and 8× = 2. Oversized faces are coarsened to stay within the 256×256 per-surface limit. The high-density samples are bilinearly sampled from the working atlas; Classic BSP29 remains the broad-compatibility option and keeps original luxel dimensions.
- Enhanced output targets engines implementing the QuakeSpasm-Spiked/FTE `LMSHIFT`, `LMOFFSET` and `LMSTYLE` BSPX extensions. BSPX extensions are not universal. QSS currently refuses enhanced export when the source already contains lightmap override extensions or when detached face-local texinfo projections are active; it does not yet import/rebase those layouts or emit `DECOUPLED_LM`.
- Object Mode is required for export so the mesh face attributes and polygons are synchronized before the exporter checks face identity.

## 0.12.0 changes

## 0.12.0 changes

- Added an import-time **working lightmap resolution** option: 1×, 2×, 4× or 8×.
- Higher-resolution atlases replicate each original BSP luxel into a larger pixel block. The normalized `Quake_Lightmap_UV` layout remains unchanged, so all material links and face masks continue to use the same UV mapping.
- The original imported BSP lightmap is retained as an independent packed snapshot at the selected working resolution. Restore Original and Undo Bake therefore remain dimension-compatible.
- Classic BSP29 export samples/averages each high-resolution luxel block back into the original BSP lighting lump and QLIT RGB sidecar. The exported BSP retains its original lightmap sample dimensions; high-resolution brush detail is necessarily reduced during this classic export.
- Atlas packing is constrained to a maximum 2048×2048 working image. At 8×, the base atlas is limited to 256×256; if the map cannot fit, import reports that rather than allocating an oversized image.
- Direct lightmap baking, Cycles luxel sampling, export, and diagnostics now resolve the working pixel scale from the stored base atlas size and actual image dimensions.
- Added standalone tests for resolution validation, image limits, coordinate scaling, and exact up/downsampling behavior.

# Quake Surface Studio 0.11.6

## 0.11.6 changes

- Added a visible **Enter Lightmap Paint** control to the Lighting Studio panel.
- Lightmap painting can be started from Edit Mode after selecting one or more faces. QSS captures the selection, filters out faces without lightmap samples, and applies a Texture Paint face mask so brush strokes cannot spill onto unselected BSP surfaces.
- The lightmap paint operator rebuilds the material-to-atlas hookups, explicitly activates the working atlas and `Quake_Lightmap_UV`, and validates the canvas, UV map, and mask after entering Texture Paint.
- Added standalone tests for filtering selected faces against lightmap coverage.
- CI derives the install ZIP and artifact version from `bl_info`, avoiding stale package names after future version bumps.

## 0.11.5 changes

- CI validates the v0.11.5 package and publishes a matching install ZIP.

- Texture Paint explicitly keeps **Occlude enabled** and **Backface Culling disabled**. In Blender 5.2 testing, enabling Backface Culling prevented visible BSP faces from receiving brush strokes; disabling it restored painting while keeping occlusion enabled.

## 0.11.3 changes

## 0.11.3 changes

- Detached face texture painting now uses Blender's Material paint mode, not the object-wide Single Image override.
- The active detached material's Image Texture node and `paint_active_slot` are explicitly selected. This prevents unrelated BSP faces with overlapping UV coordinates from displaying or receiving strokes from the detached face canvas.
- The shared lightmap atlas remains in Single Image mode because its UVs are packed as one object-wide atlas.

## 0.11.2 changes

- Texture Paint now sets Blender 5.2's explicit paint canvas source and canvas image, as well as the legacy image-paint canvas pointer. This keeps the 3D viewport paint display and the image receiving strokes synchronized.
- Face-local texture painting explicitly activates the `Quake_Texture_UV` map; lightmap painting explicitly activates `Quake_Lightmap_UV`.
- CI now builds and uploads a versioned, directly installable Blender add-on ZIP for each tested push.


## 0.11.2 changes

- Texture Paint now sets Blender 5.2's explicit paint canvas source and canvas image, as well as the legacy image-paint canvas pointer. This keeps the 3D viewport paint display and the image receiving strokes synchronized.
- Face-local texture painting explicitly activates the `Quake_Texture_UV` map; lightmap painting explicitly activates `Quake_Lightmap_UV`.
- CI now builds and uploads a versioned, directly installable Blender add-on ZIP for each tested push.

## 0.11.1 changes

- Correct add-on version metadata to 0.11.1 and display the version in the Quake sidebar.
- Add a regression test for BSP face light-style sample ordering when the face style slots are not numerically sorted.
- Make failed face detachment transactional, including material-slot, UV, active-slot, and Edit Mode selection rollback.


## Changes

- Live-light material roughness changed from 0.9 to 1.0.
- Explicitly force Cycles bake target to Image Textures and restore the previous setting afterward.
- Record actual bake-time engine, target, type, and UV layer in diagnostics.

# Quake Surface Studio — prototype 0.10.1

A Blender add-on for importing classic Quake 1 **BSP29** maps, painting embedded or external textures, detaching individual faces into their own paintable texture, and editing lightmaps through a Blender atlas. It imports Quake point/spot lights and includes a Quake-space RGB luxel solver for the documented ericw-tools direct-light attenuation modes. A separate experimental Cycles PBR bake remains available for physically based lighting experiments.

The importer/exporter is deliberately conservative: geometry, visibility, nodes, clipnodes, leaves, collision structures and entity data are not rebuilt. Texture/texinfo/face/light data are changed while unrelated standard BSP lumps and unknown BSPX payloads are preserved.

## 0.6.0 changes (historical)

- Reads ericw-tools/FTE-style **BSPX `RGBLIGHTING`**. This is important for maps compiled with `-bspxlit`, where coloured luxels are stored inside the BSP rather than in a sibling `.lit` file.
- Prefers valid in-BSPX RGBLIGHTING over a QLIT v1 `.lit` sidecar; falls back to the sidecar if BSPX RGB data is absent or invalid.
- Writes RGB samples back to BSPX `RGBLIGHTING` and also writes a QLIT v1 `.lit` sidecar for ports that use the external format.
- If RGBLIGHTING exists without the classic monochrome LIGHTING lump, synthesizes a luminance LIGHTING lump as a compatibility fallback while keeping the original RGB samples intact.
- The inspector reports BSPX lump names and validates RGBLIGHTING sample counts.
- Cycles bake now temporarily hides unrelated Blender light objects. Only lights imported from this BSP's entity lump are enabled during the Quake-light replacement bake.
- Default navigation speed is 640 Quake units/second (with a 4× fast multiplier). Speed remains adjustable in the sidebar.

## Version 0.7.0 changes (historical)

- Base Quake textures and lightmaps now use **Closest / nearest-neighbour** image interpolation by default, matching the original pixel-art look.
- Base texture nodes explicitly use `Quake_Texture_UV`; lightmap nodes explicitly use `Quake_Lightmap_UV`. The lightmap UV channel is marked as the render UV channel, while the base texture has its own explicit UV link.
- Lightmap UVs are assigned using each polygon's actual Blender loop indices rather than a reconstructed running cursor. This is a defensive fix for faces whose RGB gradients appeared on only one surface.
- RGB face samples are extracted through a bounds-checked helper using each BSP face's own `lightofs` sample offset. A regression test confirms that nonzero face offsets read their own RGB block rather than reusing the first face's samples.
- The **Quake light energy scale** is now a live multiplier: changing it updates all imported Quake point/spot lights and world sunlight immediately, and the bake reapplies it before rendering. The default changed from `0.01` to `1.0` (100× the previous default); values are approximate Blender watts, not a physical conversion. Existing `.blend` files may retain their saved slider value, so set it to `1.0` or higher to try the new default level.


## Version 0.8.0 changes

- **RGB preview diagnostics:** distinguishes faces with any brightness gradient from faces with genuinely chromatic RGB luxels. The old `38/38 gradient faces` statistic could count neutral grey gradients as coloured-light coverage.
- **Lightmap preview repair:** rebuilds the atlas image hookup on every material slot, explicitly points each material at `Quake_Lightmap_UV`, uses nearest-neighbour sampling, and uses `EXTEND` rather than clipping out-of-range UV samples to black.
- **Lightmap UV validation:** reports how many face UV islands are in-range and non-degenerate, separately from the number of faces with lightmap samples.
- **Cycles illumination bake:** uses a temporary neutral-white diffuse surface, includes diffuse/direct/indirect illumination and excludes the source material's diffuse-color contribution. This produces an illumination-only RGB lightmap without multiplying base albedo into the result a second time.
- **Recoverable bake:** creates a pre-bake image snapshot. `Undo Last Bake` restores the immediately previous atlas, while `Restore Imported BSP Lightmaps` restores the immutable atlas captured at import. This is explicit because Blender's Undo stack does not reliably revert `Image.pixels` changes.
- **Energy scale diagnostics:** adds an explicit `Apply Light Energy Scale` operation and reports imported light count and maximum energy so it is possible to verify that the slider really changed the lamps. The value remains an approximate Blender calibration multiplier, not a physically exact Quake-to-watt conversion.
- **Optional MMB FPS shortcut:** enable `MMB starts FPS / WASD` in the navigation panel to hold middle mouse for QSS's modal FPS navigation. This replaces the ordinary MMB orbit shortcut while enabled; turn it off to restore Blender's default orbit behaviour.

## Features

### Geometry and navigation

- Reads classic Quake BSP version 29; BSP2 and 2PSB/RMQ are explicitly rejected.
- Imports polygon faces and stores stable original BSP face IDs as mesh attributes.
- Converts map units to Blender metres using a default scale of **0.0254 m per Quake unit** (a common inch-based convention, not a universal physical law). The scale is adjustable on import.
- Quake and Blender are both Z-up. The **Invert Z axis** import option is only for non-standard maps produced by a converter that uses Z-down coordinates. Leave it disabled for normal Quake maps.
- Reads `info_player_start` from the compiled BSP entity lump and starts the viewport there, with the entity yaw and an approximate eye height.
- Imports explicit `light*` entities and worldspawn `_sunlight` into a collection named `QSS_<map>_Entities`.
- **FPS / Walk Navigation** uses Blender's native Walk Navigation, fitted clipping, and the configurable Quake-unit speed. It is free-fly navigation, not a collision-aware Quake player controller.
- **Focus Selected Face(s)**, **Isolate Selected Faces**, **Reveal Hidden Faces**, and **Optimize View Clipping** are available in the Quake sidebar.

### Textures

- Imports embedded miptex textures using `gfx/palette.lmp`, found loose or inside an uncompressed PAK.
- Resolves uncompressed WAD2 miptex references from the worldspawn `wad` key.
- Searches loose replacement files under `textures/<mapname>/` and `textures/` in the BSP/game folders. Supported file types: TGA, PNG, JPEG, BMP and EXR.
- Keeps missing textures visible with a white fallback and reports unresolved names.
- Reconstructs original Quake texinfo projection and UV coordinates. Base textures use nearest-neighbour sampling by default.
- **Detach Selected Faces** creates a face-local 0–1 texture, baking the visible repeated Quake texture region into a private image. This makes an individual face paintable without changing other surfaces that share the original miptex.
- Shared-material painting changes every face using that material.
- Texture paint uses sRGB byte images without applying a second gamma conversion. Export converts float-buffer images from linear to sRGB before Quake-palette quantization.
- Edited/new images are quantized to the Quake palette and rebuilt with four mip levels.

### Lightmaps and colored light

- Builds a Blender atlas from classic BSP face lightmap extents (one sample per 16 Quake units).
- Reads RGB luxels from, in priority order, BSPX `RGBLIGHTING` then a valid sibling QLIT v1 `.lit` sidecar. With neither source, the atlas starts from monochrome BSP lighting.
- Every luxel's RGB triplet is copied into its atlas position. The RGB gradient is not reduced to one average face colour.
- Shows the source type, brightness-gradient faces, genuinely chromatic faces, UV-valid faces and material atlas hookups in the Quake sidebar.
- Previews base texture × lightmap through Principled **Emission** so ordinary Blender scene lights do not relight the baked Quake preview. Lightmap atlas sampling also uses nearest-neighbour by default.
- **Enter Lightmap Paint** activates the RGB atlas and its UV layer. At export, painted pixels are sampled back into the original per-face lightmap regions.
- **Bake Imported Lights to Lightmap** uses Cycles diffuse baking with Color, Direct and Indirect contributions enabled and a neutral-white temporary diffuse shader. It replaces the existing atlas using only imported Quake entity lights; unrelated Blender lights are temporarily hidden and restored. Pre-bake snapshots allow `Undo Last Bake` and restoring the original imported lightmaps.
- Point/spot lights, `_color`, `light` intensity, `_falloff`, `wait`, target/mangle direction, and worldspawn sunlight are imported where present. Blender attenuation is an approximation; Quake's `delay` falloff models are not identical to Blender's inverse-square lights.
- Emissive texture/surface lights generated by compiler-specific material rules are not reconstructed yet. The current light import is based on explicit BSP light entities and worldspawn sunlight.
- Export writes the monochrome LIGHTING fallback, BSPX `RGBLIGHTING`, and a QLIT v1 `.lit` sidecar when RGB lightmap data is available. BSPX RGB payload is the QLIT RGB data without its 8-byte header.
- Static preview combines all active light-style layers on each face at full weight. Export flattens the composite into style 0 and clears the additional planes; animated/flickering style playback is not implemented.

## Compatibility and limits

- **BSP geometry input: classic BSP29 only.** BSP2 and 2PSB/RMQ need a different record parser.
- BSPX directory and payloads are preserved. `RGBLIGHTING` is interpreted; unknown BSPX lumps are preserved as opaque bytes. BSPX extensions that change lightmap layout (for example decoupled lightmap metadata) are not interpreted and may need a future dedicated importer.
- `LIGHTING_E5BGR9` is not supported yet; this build targets RGBLIGHTING.
- WAD lookup supports uncompressed WAD2 MIPTEX lumps only. LZSS-compressed WAD2 lumps, WAD3/GoldSrc archives and other variants are not decoded.
- Quake rerelease content may contain engine-specific extensions; this prototype does not claim universal rerelease BSP compatibility. Test on copies in Ironwail and the rerelease separately.
- QLIT `.lit` output is intended for Ironwail and other QLIT v1-compatible ports. BSPX `RGBLIGHTING` is used by ports that implement that extension; do not assume every port consumes it.
- Face topology, geometry, entities, vis, nodes, clipnodes, leaves, model bounds and collision data cannot be edited/rebuilt. Keep original face IDs and mesh topology intact.
- New/repainted miptex images must be 16–512 pixels per dimension and power-of-two. Non-power-of-two resizing is not automatic.
- Quake textures are indexed 8-bit and quantized to the selected palette; gradients may band. For `{` textures, alpha below 0.5 maps to palette index 255.
- Conservative limits: 512 miptex entries and 4096 texinfo records.
- If the atlas would exceed 2048×2048 even at one pixel per sample, it is skipped.
- The exporter reloads the original BSP from its import path. Keep that exact source file available and do not replace/recompile it between import and export.

**Always test on copies.** A successful export means the file was structurally written; engine acceptance must still be confirmed in the target port.

## Planned dedicated workspace

The longer-term direction is a dedicated **Quake Studio** workspace with a large FPS level viewport, synchronized image editor, surface/material inspector and lightmap editor. Version 0.7.0 still uses the Quake sidebar inside Blender's existing workspace. A later version can add a custom workspace and collision-aware Quake movement after the import/export and lightmap workflow has been validated.

## Install

1. Install `quake_surface_studio_0.10.0.zip` through Blender **Edit → Preferences → Add-ons / Get Extensions → Install from Disk** (wording varies by Blender version).
2. Enable **Quake Surface Studio**.
3. In a 3D View, press `N` and open the **Quake** sidebar tab.
4. Set the Quake game directory (the folder containing `id1`, or `id1` itself) and import a `.bsp` file.
5. For a normal Quake BSP leave **Invert Z axis** unchecked. The default scale is 0.0254 metres per Quake unit.

## First test procedure

1. Use a copy of a small conventional BSP29 map.
2. Import it and check the viewport orientation, `info_player_start` spawn and light-entity count.
3. Check the reported BSPX names. If the map was compiled with ericw-tools `-bspxlit`, it should report `RGBLIGHTING` as the colour source.
4. In the Lighting Studio panel, check **RGB gradient faces**. A non-zero value indicates the source contains intra-face RGB variation; a zero may mean there is no RGB data, a flat-light sample field, or very small faces with too few luxels to show a measurable gradient.
5. Press **Enter Lightmap Paint** to inspect the source RGB atlas. Look for a gradient across a large surface lit from one side.
6. To replace compiler lighting with Quake-like direct lighting, open **04 · Lighting Studio → C · Quake Direct Lightmap Solver** and click **Bake Quake Direct Lighting**. This evaluates each BSP luxel in map space and supports documented `delay` 0–5 attenuation for imported point/spot lights. The experimental Cycles PBR bake is a separate physically based option and does not reproduce ericw `delay` formulas.
7. Select a face in Edit Mode and use **Detach Selected Faces** → **Enter Texture Paint** to paint a private texture.
8. Export to a new BSP path. The exporter writes BSPX RGBLIGHTING and a `.lit` sidecar when RGB data is present.
9. Test the output in Ironwail first, then the rerelease independently.

### Lighting diagnostics

- Click **Save Lighting Diagnostics…** in the Lighting Studio panel. A file browser opens so you choose exactly where `QSS_<map>_diagnostics.txt` is saved. QSS also creates a Blender Text datablock with the report and copies it to the clipboard. The report includes per-face atlas RGB samples, BSP face style IDs/light offsets, material-to-atlas links, viewport render-light flags, imported lamp RGB colours/wattage, and failed-bake telemetry.
- For an independent compiler-side comparison, run ericw-tools `bspinfo map.bsp`. It writes `map.bsp.geometry.obj` with lightmap UVs and `map.bsp.lm_0.png`, `map.bsp.lm_2.png`, etc. as separate atlases for each used style. Compare these with QSS's per-face diagnostics.
- The standalone inspector can summarize source RGB luxels per BSP face: `python qss_inspect.py map.bsp --face-lighting`. It runs in a normal system terminal, **not inside Blender**. Extract the add-on ZIP, open a terminal in the extracted `quake_surface_studio` folder (the one containing `qss_inspect.py`, `bsp.py` and `lighting.py`), then run:

  ```bash
  python3 qss_inspect.py '/path/to/test01_compile.bsp' --face-lighting
  ```

  The sibling `test01_compile.lit` is detected automatically. Requires Python 3.10+. The same command can be run from Blender's Python Console only if that folder is first added to `sys.path`; the system terminal is simpler.

## Standalone tests and inspector

Requires Python 3.10+; these tests do not require Blender:

```bash
cd quake_surface_studio
python -m unittest discover -s tests -v
python qss_inspect.py path/to/map.bsp
python qss_inspect.py path/to/map.bsp --lit path/to/map.lit
python qss_export_check.py path/to/original.bsp path/to/exported.bsp
```

`qss_export_check.py` also accepts `--lit path/to/file.lit` when the QLIT v1 sidecar does not share the exported BSP's basename. It is read-only and works with ordinary Python; it does not require Blender.

`qss_export_check.py` compares an exported BSP against the exact original file used for import. It checks face/geometry identity, retained source lumps and unknown BSPX data, texture/texinfo references, classic lightmap bounds, optional enhanced BSPX lightmap offsets, and the sibling QLIT v1 `.lit` file. A sibling `.lit` file is detected automatically; use `--lit path/to/file.lit` to select another one. This validator is read-only and does not replace loading the output in the target engine.

The inspector reports standard lump counts, BSPX extension names, RGBLIGHTING sample counts, optional QLIT validity, and face/texinfo/miptex references. It is a structural check, not a replacement for testing in the engine.

## Technical notes

Classic BSP29 has a 124-byte header and 15 standard lumps. Each face references a 40-byte texinfo record with two projection vectors and a miptex index. `RGBLIGHTING` is a BSPX extension that stores one RGB triplet per classic lighting byte/sample; the add-on writes the same payload (without the QLIT header) into BSPX and wraps it in QLIT v1 for the sibling `.lit` file.

- `bsp.py`: BSP29/BSPX reader-writer, miptex/texinfo helpers, WAD2, palette/PAK, entities, QLIT and RGBLIGHTING helpers.
- `addon.py`: Blender geometry import, entity light import, painting UI, Quake direct-light solver integration, experimental Cycles bake and BSP export.
- `color.py`: Quake palette / Blender colour-space conversion.
- `qss_inspect.py`: standalone BSP29 and BSPX inspection tool, including per-face RGB luxel/style inspection.
- `qss_export_check.py` and `export_validation.py`: standalone source-to-export integrity checks, classic sample bounds, optional enhanced BSPX lightmap checks and QLIT sidecar validation.
- `lightmap_export.py`: Blender-independent higher-density per-face lightmap sampling and BSPX payload helpers.
- `tests/`: standalone parser, RGB lighting and colour-conversion regression tests.


## Version 0.10.1 changes

- **Rendered viewport flags:** Live Lights explicitly enables Blender 5.2 `use_scene_lights_render` and `use_scene_world_render` (in addition to Material Preview flags). These are separate switches. Live preview uses a black world and a diffuse base-texture material with emission disconnected, so slider 0 should be black and imported Quake lamps are the only illumination.
- **Correct bake normalization:** live lamp calibration and baked-atlas normalization are separate. The atlas is normalized using `source_mean / raw_bake_mean`; this avoids applying the energy slider twice. Matching is a global mean-luminance target, not a pixel-for-pixel match.
- **Transactional bake rollback:** exceptions restore pre-bake pixels, object/light calibration values, lamp energy, non-QSS light visibility and the preview mode that was active before baking.
- **Expanded diagnostics:** the sidebar report includes per-face atlas RGB statistics, BSP `styles[0..3]` and `lightofs`, material image/UV hookups, viewport render-light flags, imported lamp colors and lamp wattage.
- **Standalone per-face inspection:** `qss_inspect.py --face-lighting` reports source RGB luxel coverage, per-face style IDs, offsets, luxel count, chroma and luminance range.
- **Float atlas:** the editable atlas is 32-bit float / Non-Color to preserve low-energy and HDR bake values. Re-import the BSP after upgrading; images already created by older builds in saved `.blend` files are not converted in-place.
- **Three explicit lighting states:** Original BSP Lightmap previews the immutable source snapshot; Live Lights previews diffuse textures under imported Quake lamps; Baked previews the editable atlas produced by the most recent successful bake. Painting always targets the editable working atlas, never the immutable source snapshot.
- **Expanded bake report:** the diagnostic text includes the last raw bake mean, source mean, final atlas mean/max, normalization multiplier, Cycles sample/bounce settings and bake pass flags.
- **Findable diagnostics:** Save Lighting Diagnostics opens a file browser instead of silently writing to Blender's temporary folder. It also creates/updates a Blender Text datablock and copies the report to the clipboard.
- **Failed-bake telemetry:** a failed Cycles bake records the active energy scale, imported lamp wattages/visibility, operator result, sampled luxel mean/count and whole-target image statistics. The failure message distinguishes a zero energy scale, a cancelled bake and a bake that completed but wrote no measurable pixels.

## Version 0.9.0 changes (historical)

- Replaced Blender's auto-starting Walk Navigation with an optional hold-MMB modal first-person navigation operator. WASD movement occurs only while keys are pressed; releasing MMB exits navigation. A simple eye-level raycast collision/slide approximation is used, not a full Quake player capsule. The current version leaves this navigation behaviour unchanged.

## Recommended lighting test with ericw-tools

The supplied compile log confirms that `light` wrote a QLIT v1 `.lit` sidecar and detected colored lighting. It reports four explicit lights and zero emitted surface-light points (this is the emissive-surface-light count, not a statement about point-light bounce). It does not show whether worldspawn `_bounce` was set. In ericw-tools, bounce is disabled by default; set worldspawn `"_bounce" "1"` (or run `light -bounce 1`) to test colored indirect bounce. `_bouncecolorscale` controls how strongly texture colour participates in bounce; this is separate from the RGB colour of the light entities. See the ericw-tools `light` documentation.

The supplied MAP text identifies the intended value: the entity at `(504 -344 56)` has `"" "2"`, an empty key with value `2`. QSS can recover that value as an inferred light style for preview, but the compile log confirms that ericw-tools sees an empty key. Correct the MAP entity to `"style" "2"` before recompiling. The other light at `(376 -392 8)` already has a valid `"style" "2"` key.

The original compile log says `map uses color: true` and writes `<map>.lit`; this is the expected QLIT v1 source for the current importer. To embed RGB data into BSPX, use `light -bspxlit` on the **light** command, not as a `qbsp` flag.

The MAP worldspawn does not set `_bounce`, so ericw-tools uses its default of no bounce lighting. To test colored indirect bounce at compile time, try `"_bounce" "2"`, `"_bouncescale" "1"`, and (if texture colors should tint the bounced light) `"_bouncecolorscale" "1"`. These settings alter the compiler-generated lightmap and are distinct from Blender's artist bake. In ericw-tools, `_bounce` is the maximum number of bounces and `_bouncecolorscale` weights the map texture color used in bounce. See the [ericw-tools light documentation](https://ericw-tools.readthedocs.io/en/latest/light.html).

## Lighting preview workflow

1. Click **1 · Original BSP Lightmap** to display the immutable imported compiler atlas through Emission. This is the reference and is never overwritten by a bake.
2. Click **2 · Live Lights**. The material becomes diffuse and imported map lights illuminate it in Eevee Rendered viewport mode. QSS enables Rendered-mode scene-light and scene-world switches explicitly. At energy scale 0 the surface should be black; higher values add imported light. Live preview is direct Eevee lighting; it does not reproduce Quake's compiler visibility or diffuse bounce exactly.
3. Click **Auto-calibrate Live Scale to Source** once. This performs a temporary Cycles bake, compares average RGB-luxel luminance with the original atlas, updates lamp calibration, restores the original atlas and returns to Live Lights at scale 1. This matches global mean brightness, not spatial falloff pixel-for-pixel.
4. Click **Bake Imported Lights to Lightmap** to bake the Blender approximation. With source matching enabled, the output atlas is normalized by source mean / raw bake mean. It then switches to **3 · Baked** so the generated atlas is visible. The bake uses the current light scale and diffuse bounce setting.
5. Click **Undo Last Bake** to restore the previous working atlas, or **Restore Imported BSP Lightmaps** to copy the original snapshot back into the editable atlas. The **Original BSP Lightmap** preview always remains available independently.

The Blender light model remains an approximation of ericw-tools. ericw-tools `delay 0` is linear attenuation (the default), while Blender point/spot lights use physically based inverse-square falloff. A global brightness calibration can match the average source luxel value, but not every per-face light gradient. Other compiler semantics (visibility/occlusion, `_anglescale`, `_dist`, `_range`, `_falloff`, `_deviance`, surface lights and special minlight behaviour) are not all reproduced yet. The Live preview is an editable lighting base, not bit-identical compiler output.


## Upgrade note for Blender 5.2 (0.9.1)

Version 0.9.1 makes registration/unregistration idempotent and cleans up stale
QSS operator/panel classes and keymap entries during re-enable or upgrade. It
also rolls back partial registration if Blender reports an error. If Blender
currently has a failed 0.9.0 registration in memory, restart Blender once, then
install 0.9.1. You should not need to manually remove classes in the Python
console.


## Version 0.10.1 notes

- The diagnostics command now opens a Save As browser rather than writing silently to Blender's temporary directory. It also embeds the same report in a Blender Text datablock and copies it to the clipboard.
- Failed bake reports now preserve the energy slider value, lamp wattages and visibility, Cycles operator result, number and mean of sampled luxels, and whole-target nonzero-pixel/max-channel statistics.
- A zero energy scale is rejected before Cycles starts, with an explicit instruction to set the scale above zero and apply it. A successful Cycles operator that produces an empty atlas is reported separately from a cancelled operator or an atlas-sampling mismatch.


## Version 0.11.0 changes

- **Ordered sidebar:** numbered, collapsible sections (`01 Project`, `02 Navigation`, `03 Texture`, `04 Lighting`, `05 Diagnostics`, `06 Export`) with nested lighting workflows and stronger visual grouping. Blender's Python Panel API does not provide arbitrary per-panel header colours; QSS uses semantic icons, labelled section boxes, spacing and alert styling instead.
- **Collection safety:** face-local texture extraction validates UV-layer sizes and loop bounds before reading. Texture Paint activation no longer assumes that `uv_layers[0]` exists. Lightmap sampling, direct-bake metadata access and diagnostic face reads use guarded collection access. Stale Edit Mode CustomData now produces a descriptive QSS error instead of a raw `bpy_prop_collection[index]` traceback where possible.
- **Full delay benchmark:** the Blender self-test now runs seven full luxel passes (the map's actual light settings plus all imported lights overridden to `delay` 0 through 5), reports attenuation values at fixed distances, and displays Blender progress. It is a dry run: it does not change the BSP or lightmap atlas. `MAX_BENCHMARK_LUXELS = 0` means all luxels; set a positive value near the top of `qss_blender_diagnostics.py` to cap very large maps.
- **Delay modes:** the Quake-space direct-light evaluator supports the documented six static point/spot attenuation modes: linear, inverse distance, inverse square, constant, local-minlight clamp and softened inverse square. It also uses per-light `wait`, delay-0 `_falloff`, world `_dist`/`_range`/`_gamma`/`_maxlight`, per-light `_anglescale`, point/spot colour and cone, style filtering and hard line-of-sight visibility. This is a documented-behaviour implementation, not a bit-identical port of all ericw-tools compiler internals.
- **Explicit limitation:** this direct pass does not yet reproduce radiosity/bounce, dirtmapping, deviance/area samples, surface emitters, sunlight/sky sampling, projected texture lights, compiler visibility approximations or animated lightstyle time curves. The Live Lights viewport still uses Blender's own lamp falloff; use the Quake Direct Lightmap Solver when you need Quake `delay` attenuation.

### Running the full Blender diagnostics

1. Select the imported BSP mesh and switch to **Object Mode**.
2. Open `N` → **Quake** → **05 · Diagnostics & Recovery**.
3. Click **Run Full Self-Test + Delay Benchmark**.
4. Blender runs an isolated Cycles image-bake sanity check and then evaluates all valid luxels for the actual light settings and six `delay` overrides. A progress indicator is shown.
5. The report is saved as `~/Desktop/QSS_Blender_SelfTest.txt` (or the home folder if Desktop does not exist) and embedded in a Blender Text datablock named `QSS_Blender_SelfTest`.

The benchmark is deliberately read-only. It does not bake into or modify the working lightmap atlas. On large maps it can take a while because ray-traced visibility is evaluated for each candidate light at each luxel. The current test map's roughly 3,782 luxels is a small workload.
