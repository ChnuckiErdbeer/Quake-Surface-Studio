# SLOPGATE 0.21.1

## 0.21.1 — Mod palette fallback and bake workflow improvements

- Palette lookup now searches the selected mod first and then the sibling base-game \`id1\` directory. Within a game directory, loose palette files take precedence over PAK contents, and higher-numbered PAK archives take precedence over lower-numbered archives.
- The Cycles \`Bake Lightmap\` action can be started from Mesh Edit Mode. SLOPGATE temporarily switches to Object Mode for the full-map bake and restores the previous edit-object selection afterwards. The bake still covers the entire map; it is not limited to selected faces.
- The existing archive-aware game-map picker is now exposed in the main SLOPGATE panel as \`Browse Maps\`. It lists loose BSPs and BSPs inside Quake PAK archives and extracts an archived BSP to the user-data cache before import.
- The standard Blender file selector is not yet a virtual PAK filesystem. PAK entries are accessible through SLOPGATE's map picker, but the archive's internal folders are not mounted as native file-browser folders.
- BSP2 and 2PSB parsing/export, preview-brightness calibration, and lightmap edge-padding/bleed improvements remain unimplemented. The parser still accepts classic BSP29 only.
- Automated tests and package assembly must pass before this development build is distributed. No interactive Blender 5.2, Cycles/Eevee runtime, or Ironwail test is implied by Python CI.

---

## 0.21.0 — Companion MAP synchronization

- BSP import quietly discovers a same-basename `.map` beside the selected `.bsp`. No direct MAP import, QBSP invocation, WAD search, or texture-path resolution is involved.
- The companion MAP is associated with imported BSP light entities using classname and origin matching. The original MAP path and SHA-256 are retained.
- BSP export creates a separate companion `.map` beside the exported BSP. It never overwrites the source MAP. Existing output companions are overwritten only when their contents match the hash of the previous SLOPGATE export.
- MAP synchronization updates supported existing light properties: origin, RGB color, light magnitude, and spotlight cone angle. Deleting a linked imported Blender light removes its corresponding MAP light entity. Spot direction/mangle synchronization and creating new light entities are not yet implemented; original target and mangle keys are preserved.
- The MAP parser edits only top-level entity key/value spans. Brush blocks, plane geometry, texture axes, comments, WAD references, unknown keys, and unrelated source text are preserved rather than regenerated.
- Painted texture pixels continue through the existing BSP texture export path. This feature does not create WAD files, search for WADs, change MAP texture references, rebuild BSP geometry, run QBSP, VIS, or ericw light.
- If the source MAP changed externally since import, or an unrelated file already occupies the companion output path, export stops rather than overwriting it.
- The former Import MAP via QBSP workflow is removed; BSP is the import entry point and the adjacent MAP is an optional companion source.
- Added focused tests for MAP tokenization, brush/comment preservation, entity matching, safe patching, and same-directory companion discovery. CI and Blender 5.2 runtime validation are pending.

---

# SLOPGATE 0.20.7

## 0.20.7 — Faster BSP import entry and cursor palette

- The Import BSP file selector now starts in the active game's `maps` directory, falling back to the game directory when no `maps` folder exists.
- Removed the Browse Game Maps button from the sidebar to avoid the slow archive-scanning workflow in the main UI. The existing archive-aware operator remains registered and available through Blender's operator search for compatibility.
- The Quake palette operator now opens as a cursor-positioned popup when invoked from the paint-mode context menu.
- Retains Blender's native `template_palette` widget, which adapts its columns to the available layout width and uses square swatches. No custom button colors or custom swatch grid have been introduced.
- No other controls, panels or workflows are removed.

### Validation notes

- QSS Python CI run 627 is pending at the time of this note.
- Import dialog initial-directory behavior and cursor-positioned palette popup require interactive Blender 5.2 verification.
- Blender's standard theme UI does not expose arbitrary per-button background colors through ordinary `UILayout.operator` controls; semantic states (enabled/depressed/alert) and native theme colors remain available.

---




## 0.20.2 — Material-zone BSP texture export and lighting safeguards

### BSP texture export
- Edited and newly detached textures are now quantized with SLOPGATE's integrated material-zone algorithm during BSP export, not the older per-pixel nearest-colour lookup.
- The same five-candidate-ramp material-zone conversion is applied independently to all four mip levels.
- `{` texture alpha is encoded as Quake index 255; ordinary textures do not become transparent because of incidental Blender alpha.
- Fullbright masks are recovered from the original indexed miptex when the image dimensions match, or from a sibling `*_fullbrights.png` mask for loose source images.
- The standard Lighting panel no longer shows a separate **Convert Image to Quake Palette** button. Normal BSP export performs palette conversion automatically; the standalone image-conversion operator remains available as an optional advanced utility.

### Lightmap paint warning
- The first lightmap-paint pass still accounts for the shared atlas and its working copy, but the confirmation threshold is now 256 MiB or 10% of detected available memory.
- The confirmation message explains the shared-atlas allocation and uses singular/plural wording correctly.

### Cycles bake safeguards
- A Cycles bake with no nonzero BSP luxel samples is now rejected even if the source BSP lightmap mean is also zero.
- The failed bake is discarded and the source atlas and light calibration are restored. Energy, source mean, sampled-luxel count and whole-atlas pixel statistics remain available for the Lighting Diagnostics report.
- A zero bake-output scale is rejected before starting.

### Validation and user testing
- GitHub Actions passed the standalone Python suite and converter GUI workflow for the 0.20.2 implementation commit.
- The user reports that 0.20.1 enables in Blender 5.2, removes the Edit Mode grey hue, and successfully paints/exports the previously failing wall.
- QBSP compilation and Ironwail acceptance have not yet been reported for the current implementation. A real Blender Cycles bake is also still required to identify the root cause of the user's all-black result; this release adds a hard failure and diagnostics rather than claiming the root cause is fixed.

## 0.20.0 — Quake brush palette, in-process conversion and viewport controls

### FOV and face focus
- Adds **Viewport FOV** to QSS Settings. The default is 90° horizontal FOV; the setting is stored in QSS's user `config.json` and applied to open 3D Views.
- **Focus on Face** uses the same configured FOV when calculating a face-fit distance, accounting for viewport aspect ratio.

### Quake palette painting
- Fixes Quake palette creation by importing the missing hashing module and using Blender 5.2's native palette selector and swatch template.
- The Standard / Quake brush-color switch is now part of the existing **LIGHTING** panel rather than a separate sidebar section.
- Adds **Quake Palette Colors…** to the paint-mode brush/property right-click menus. It opens a palette dialog populated from the active map's actual 256-entry Quake palette.
- Native UI calls use Blender's `template_ID(settings, "palette")` and `template_palette(settings, "palette")` pattern; the previous unsupported palette-template argument is removed.

### Material-zone conversion inside Blender
- The **Convert Image to Quake Palette…** action is now inside the existing Lighting panel. It runs directly in Blender's Python process using QSS's standard-library implementation in `palette_utils.py`; it does not launch an external program and does not require NumPy, Pillow, SciPy or scikit-image.
- Retains OKLab color analysis, SLIC-style superpixels, adjacency-based material-zone merging, the curated 14 palette ramps, five candidate ramps per zone, alpha transparency at index 255, and optional sibling `*_fullbrights.png` masks.
- The generated PNG is indexed and uses the active map's exact Quake palette. QSS loads and packs the output as a new Blender image; the source is not overwritten.
- Render Result is saved through Blender's render I/O before conversion, so the scene's view transform is included in the pixels being converted.
- The shader suggestion is not used as the converter itself: a shader can map individual pixels to palette colors, but this converter also needs whole-image superpixels, connected material-zone merging and per-zone ramp fitting. Those image-wide operations belong in a Python image-processing pass.

### Paint preparation and Edit Mode appearance
- Removes the arbitrary 64-face threshold. QSS estimates face-image/atlas buffers from selected face UV footprints and adds a conservative 3× working-buffer reserve for temporary sampling and packing arrays. A confirmation appears at 32 MiB estimated preparation memory or 5% of available system/cgroup memory.
- Warning text now explains in plain language what QSS is about to allocate, why the estimate may be low, the risk of Blender running out of memory, and that painting smaller batches is the safest choice.
- Lightmap Paint warnings use the current atlas size and available memory rather than a fixed face-count threshold. These warnings remain estimates, not a guarantee that Blender cannot run out of memory.
- In Edit Mode, QSS temporarily disables Blender's face-fill selection overlay for imported QSS maps, while retaining selection outlines. It restores the previous overlay setting outside Edit Mode. This specifically targets the grey Edit Mode face-fill tint reported in Material Preview/Eevee/Cycles; the actual Blender 5.2 GUI behavior still needs local verification.

### Validation
- The converter now runs without any external converter runtime or third-party package installation.
- The standalone suite includes tests for five candidate ramps, indexed PNG chunks/palette transparency, fullbright handling, and in-process RGBA-to-index conversion.
- Interactive Blender 5.2 verification is still required for the brush/right-click palette picker, large image conversion performance, FOV in newly opened views, the Edit Mode overlay appearance, and the paint confirmation behavior.


## 0.19.0 — Quake palette painting, conversion and safer map workflow

### Quake palette brush picker
- Adds a switch between Blender's **Standard** brush color picker and **Quake** palette mode in the new **QUAKE PALETTE** sidebar panel.
- The Quake picker is populated from the active map's actual 256-entry palette (the resolved game `gfx/palette.lmp` or explicitly imported palette), not from a hard-coded approximation.
- The selected palette is synchronized when changing the active loaded map. Quake entries 0–223 are ordinary colors, 224–254 are the palette's fullbright range, and 255 is the conventional transparent index; transparency itself is handled by the texture format, not as a brush alpha mode.

### Integrated Quake texture converter
- Bundles the existing `conv_layers.py` material-zone converter and its settings as part of QSS. The algorithm is preserved: OKLab analysis, detail enhancement, SLIC superpixels, adjacency-based hierarchical material-zone merging, all 14 palette ramps, multiple candidate ramps per zone, independent alpha/transparency and optional fullbright masks.
- Sets `ramp_candidates_per_zone = 5` as the default, matching the successful setting confirmed in Blender texture tests.
- Converts the active Texture Paint canvas, an Image Editor image, or the current Render Result to an indexed Quake-palette PNG. Optionally creates the converter's layered OpenRaster (`.ora`) diagnostic project.
- Uses the active map's exact palette file when constructing the JASC-PAL input. The converted PNG is loaded and packed into the Blender file as a new image; the source image is not overwritten.
- **Historical v0.19.0 implementation:** this first version launched the converter in a separate Python environment. That external runtime was removed in **v0.20.0**; current conversion runs inside Blender and needs no third-party Python packages.

### Paint preparation and map workflow
- Large paint selections now show a **confirmation dialog**, not a hard rejection. The dialog estimates peak face-image and atlas pixel-buffer allocation, reports existing QSS image-buffer memory, and compares the estimate with available host/cgroup memory when the platform exposes it.
- Memory estimates cover CPU image pixel buffers only. They cannot predict Blender undo history, GPU copies, material datablocks, allocator fragmentation, or memory consumed by other processes, so they are guidance rather than an out-of-memory guarantee.
- Focus-on-face temporary near/far clipping now runs in **Edit Mode as well as Texture Paint**, and restores the previous clipping when leaving the mode or moving the view.
- Adds **Close** beside the Loaded Map selector. It asks for confirmation before removing that map's imported objects and map-specific data. Closing the final QSS map restores the scene objects that QSS hid during map isolation. The original BSP on disk is not changed.
- Removes the separate **Last Export** Ironwail button; **Test in Ironwail** is the single in-panel launch workflow.

### Viewport shading clarification
- Blender's Solid/Flat and Material Preview are viewport shading modes, not separate Object Mode and Edit Mode color spaces. QSS now displays a hint and a **Material Preview** shortcut when the active viewport is in Solid shading. Material Preview is the mode that evaluates the imported QSS image/material nodes and lightmap preview. Each 3D View stores its own shading mode.

### Validation
- The standalone test suite now includes a converter smoke test: it runs the bundled converter against a generated 256-entry JASC-PAL and a small synthetic texture, and verifies that it produces a same-size indexed PNG.
- GitHub Actions installs the converter's Python dependencies, compiles the add-on and converter, runs the full standalone suite, checks the metadata version, and assembles the Blender package.
- Interactive Blender 5.2 checks are still required for palette UI behavior, image/render conversion, memory confirmation, and the close-map dialog.


## 0.18.4 — Safer painting, aligned layers and smoother camera travel

- **Focus on Face** flips the selected face normal toward the side occupied by the current view, avoiding a focus move through a wall to the back side. Framing adds more breathing room around the projected face bounds.
- **Player Start** uses the shared 0.5-second eased camera-transition operator. The same operator is available to future QSS camera-positioning actions.
- The **Painted / Source** matrix uses fixed, matching column widths. Source-layer controls work in Object Mode and Edit Mode; Painted Textures safely commits to Object Mode for its face-material/UV update and then restores Edit Mode.
- Entering Texture Paint or Lightmap Paint is stopped with a warning when more than **64 faces** are selected. Split large selections into smaller batches to avoid Blender memory spikes or crashes.
- Adds **Test in Ironwail**, available without a previous export. It writes a temporary Classic/Enhanced BSP copy under `maps/qss_preview`, launches Ironwail, and removes the BSP and optional .lit sidecar when the launched process exits. **Last Export** remains available separately.
- The temporary test uses the regular BSP assembly/export path at click time; geometry, material state and atlases remain in memory until that operation. Export is not a preassembled BSP snapshot.

## 0.18.3 — Face paint correction and smoother focus

- Import still enters **Edit Mode / Face Select**, but now clears all face, edge and vertex selection so the first view is not covered by the orange selection overlay.
- Fixes **Paint Texture** detachment with the actual 10-field BSP29 texinfo record (8 projection floats plus miptex/flags metadata).
- **Focus on Face** now fits the selected polygon's projected bounds to the viewport with breathing room and eases the camera over 0.5 seconds.
- Repeated clicks on Focus cycle through selected faces. While the pointer is over Focus, mouse-wheel up/down cycles forward/backward; scrolling elsewhere remains normal viewport navigation.
- Edit Mode shading note: QSS requests Material Preview for the Original/Baked preview and does not override the scene view transform. Blender Solid/Flat shading is a separate viewport mode and does not calculate lighting.

## 0.18.2 — Quick Actions, face focus and lightmap layer controls

- After importing a BSP, QSS enters **Edit Mode with Face Select active**, ready for selecting surfaces.
- Renames NAVIGATION to **QUICK ACTIONS** and arranges WASD, Player Start, Isolate Selection and Focus on Face in one compact horizontal icon row.
- Restores reversible face isolation and makes it available from both Edit Mode and Texture Paint face-mask mode. The original hidden-face and selection snapshot is retained.
- **Focus on Face** aims the viewport along the selected polygon's world-space normal and frames it closely. While in Texture Paint, a temporary near/far clipping slab suppresses geometry in front of and behind the focused surface. QSS restores the previous clipping range when painting ends, the view is moved, or another face is focused.
- Replaces the loose texture/lightmap switches with a two-row **Textures / Lightmaps** matrix and **Painted / Source** columns. Source Textures controls the diffuse/albedo contribution; Source Lightmaps controls the active unpainted Original/Baked lightmap contribution.
- Preserves original texel density when creating face-local paint images: Quake-valid multiple-of-eight padding stays outside the face UV footprint, and only faces exceeding the 512-pixel miptexture limit are resampled.
- Tightens Cycles bake visibility: only lights belonging to the active map are included, active-map lights and geometry are temporarily made visible to the bake, and their previous viewport/render visibility is restored afterward. Failed-bake diagnostics now also record the active mesh/map-collection visibility state.

**UI note:** Blender's standard Python panel API does not expose arbitrary per-operator background colors. Quick Actions uses distinct icons and the normal pressed/active state rather than unsupported custom button tints.

## 0.18.1 — Painting and viewport corrections

- Recognizes Blender's Texture Paint context mode correctly, so the Paint Texture and Paint Lightmap buttons remain active while painting.
- The paint buttons now act as toggles: clicking the active paint button exits to the previous Object/Edit mode; clicking the other button switches paint targets without losing the original return mode.
- Fixes painted-texture disable: detached faces are reprojected from their original BSP texinfo before restoring their source material, preventing face-local paint UVs from leaking into the original texture mapping.
- Adds a **Diffuse Textures** toggle that removes albedo while preserving the currently selected original or generated lightmap. Its state is reapplied when changing lighting presets.
- Removes a stale undefined light-restoration call that interrupted Original/Baked lightmap preview and painted-lightmap switching.
- Refreshes affected 3D View areas after applying a lighting preset.

## 0.18.0 — Sidebar-first project workflow

This release implements the agreed NAVIGATION / MAIN / LIGHTING / STATS layout in the existing **View3D → Sidebar → Quake** tab. The dedicated workspace, toolbar, viewport-header and context-menu interfaces remain removed.

### Sidebar

- **NAVIGATION:** native Blender Walk Navigation in Quake noclip mode and Move to Player Start.
- **MAIN:** Game / Mod selector, immediate map browser import, BSP import/export, active map selector, Open Last Export in Ironwail, lightmap resolution controls, and Settings.
- **LIGHTING:** Original, Eevee Material Preview, Cycles Rendered and Baked presets; selected-face Texture/Lightmap Paint; independent painted texture/lightmap overrides; Cycles lightmap bake.
- **STATS:** collapsed by default; active-map geometry, entity, texture, lightmap, export and diagnostic information.

### Multi-map workflow

- Every imported BSP receives a uniquely named `QSS_Map_*` root collection. Its mesh and entity collection live below that root.
- Importing another map follows `import_behavior` in `CONFIG/qss/config.json`: `ASK` (default), `ADD`, or `REPLACE`. The Ask dialog defaults to Add. Replace deletes only the previously active QSS map collection, and only after the new import succeeds.
- A newly imported map becomes active, is isolated in the viewport, and frames `info_player_start` when available. Switching Loaded Map changes the active object and hides the other scene content without deleting it.
- Each map stores its own lighting preview mode and painted-lightmap state. Only the active map's QSS lights are enabled for its live-light preview and Cycles bake.

### Lighting and painting

- Original and Baked use Material Preview with scene lighting disabled; Eevee uses Material Preview with scene lights/world enabled; Cycles uses Rendered shading with Cycles.
- Painted textures are reversible per-face material overrides. The original material assignments are retained.
- Original and Baked lightmap painting each use a separate image override. Painted Lightmaps is available only in those two modes.
- The Cycles bake is the supported artist-bake path. Existing bake data prompts for confirmation before replacement. A new bake invalidates the painted Baked override but never overwrites the immutable original BSP snapshot.
- Export follows the selected lightmap layer: Original exports the original/painted-original layer, Baked exports the generated/painted-baked layer, and live-lighting previews fall back to Original.
- EEVEE lightmap baking is not implemented as a separate backend in this release. The Bake button remains available from Eevee preview but uses the existing Cycles bake path; this is disclosed in the panel and is a low-priority future experiment.

### Import, export and settings

- The BSP file browser no longer exposes QSS-specific import settings. It uses the active Game / Mod, configured unit scale and configured working-atlas resolution.
- Export format choices are Automatic, Classic, Enhanced and Both. Automatic chooses Enhanced for upscaled working atlases or source maps carrying DECOUPLED_LM; otherwise it chooses Classic. Both writes `_c.bsp` and `_e.bsp`.
- Open Last Export in Ironwail prefers the Enhanced file after Both by default. The preference is configurable. The exported BSP must be inside the active Game / Mod directory for Quake's virtual map lookup.
- The Settings popup edits the Quake installation root and Ironwail executable as well as common defaults: import behaviour (`ASK`), export format (`AUTO`), preferred Both-export launch variant, default working-atlas resolution, re-bake policy (`ASK`) and lighting-mode memory (`PER_MAP` or `GLOBAL`). The adjacent Text Editor action opens the actual `config.json` in a separate Blender window for advanced editing.
- Per-map lighting memory is the default. Global mode memory is optional and stores one shared Original/Eevee/Cycles/Baked choice. A map without a generated bake safely falls back to Original when global Baked mode is selected.
- Re-baking asks before replacing an existing generated lightmap by default; the setting can be changed to overwrite directly.
- Changing working lightmap resolution rebuilds the atlas from the original BSP. The dialog warns that generated and painted lightmaps are discarded; painted textures and mesh geometry are retained.

### Validation status

Python compilation, standalone regression tests and package assembly are run by GitHub Actions. Blender 5.2 GUI registration, visual layout, multi-map interaction, painting and render-mode switching still require interactive verification; CI cannot replace that test.

## 0.17.9 changes

- Returns to the original single **3D View > Sidebar > Quake** workflow. Dedicated workspace creation, workspace toolbar tools, viewport header menus, and context-menu additions have been removed.
- Restores the original project-first sidebar home panel and the existing collapsible Project, Navigation, Texture, Lighting, Diagnostics, and Export sections.
- Retains the later BSP/lightmap, face-isolation, focus, and native Quake Walk implementation; no core editing or navigation operators are intentionally reverted.


## 0.17.8 changes

- Consolidates the 3D View sidebar into one **Quake Studio** tab. The old parallel **Quake** and **Quake Studio** tabs are retired; the workspace home is the single starting point.
- Replaces the duplicated dashboard with a focused home panel: current map summary, mode-aware quick actions, Ironwail launch, and a simple import-first welcome state.
- Adds a compact **Quake** menu to the 3D View header for import, focus, noclip Walk, face isolation/reveal, paint setup, export, and workspace access.
- Adds Quake face-editing actions to the Edit Mesh context menu so focus, isolate/reveal, and paint setup are available where face selection happens.
- Keeps the left toolbar intentionally limited to persistent Paint Texture and Paint Lightmap tools. One-shot commands remain menus/buttons and do not hijack viewport clicks.
- Preserves the working native Blender Walk Navigation implementation, including mouse-look, WASD/QE free flight, Shift acceleration, LMB exit, and Esc/RMB cancel.
- Moves lighting and advanced diagnostics into the same Quake Studio sidebar hierarchy. Existing operator implementations and BSP workflows are unchanged.

## 0.17.7 changes (navigation)

- Replaces QSS's custom timer-driven WASD overlay with Blender 5.2's native **Walk Navigation** operator. QSS no longer maintains a competing camera-navigation modal loop.
- Provides genuine first-person mouse-look and free-flight movement: **W/A/S/D** move, **Q/E** move vertically, and **Shift** temporarily accelerates. Free flight is enabled to match Quake noclip rather than gravity-based walking.
- Makes exit behaviour explicit and reliable: **LMB confirms and exits**; **Esc or RMB cancels and restores the starting view**. There is no persistent QSS navigation session or separate stop toggle to get stuck in.
- Maps the QSS Quake-units/second speed and fast multiplier into Blender's native Walk Navigation preferences using the imported BSP's unit scale.
- Leaves Blender's ordinary viewport navigation and MMB orbit untouched outside the native Walk session. FPS navigation is a direct sidebar action, not a persistent toolbar tool, so exiting returns to the previously selected viewport tool and ordinary clicks cannot relaunch Walk accidentally.
- Adds standalone tests for Quake-to-Blender navigation speed conversion and preference bounds.

## 0.17.6 changes

- Replaces context-sensitive `view3d.view_selected` calls with direct world-space bounds framing. Focus now frames the actual selected BSP faces in Edit Mode, or the BSP object bounds in Object Mode, in the active 3D View.
- Makes **Isolate Selected Faces** a reversible toggle. QSS records the face visibility and selection state before isolation; pressing the same button again restores the previous hidden faces and selected faces instead of blindly revealing everything.
- The isolation snapshot is stored on the BSP object and survives saving/reopening the .blend file. If the mesh topology changes while isolation is active, QSS refuses an unsafe restore and explains how to recover with Blender's Reveal Hidden (Alt+H).
- Removes the redundant QSS Reveal button from the main workflow. Blender's native Reveal Hidden remains available for geometry hidden by other operations.
- Moves one-shot Player Start, Focus, and Toggle Isolation commands to direct sidebar Quick Actions. They no longer require selecting a left-toolbar tool and clicking an arbitrary point in the viewport.
- Keeps FPS Navigation, Paint Texture, and Paint Lightmap in the left toolbar; their sidebar actions remain direct command buttons.
- Adds standalone regression tests for saved/restored visibility snapshots, topology mismatch handling, and world-space focus bounds.

## 0.17.5 changes


- Fixes the 0.17.4 toolbar regression: Blender 5.2 `ToolDef` entries are namedtuples, not ordinary tool groups. The sanitizer now recognizes the actual Blender type before inspecting tuple groups.
- Preserves Blender's built-in Object, Edit, Texture Paint, Vertex Paint, Weight Paint, Sculpt, and other mode tool definitions without rebuilding or flattening untouched groups.
- Preserves the top-level dynamic tool generators used by built-in context-sensitive tools, including Texture Paint selection tools.
- Repairs only stale QSS entries and genuinely malformed/nested data; valid native ToolDef groups and dynamic generators keep their original structure and order.
- Registers QSS tools through Blender's `register_tool` / `unregister_tool` lifecycle. Refresh removes previous QSS tool definitions and generated keymaps before registering them once.
- Adds one-click **Quick Actions** to the Quake Studio sidebar for commands such as Player Start, Focus, Isolate, Reveal, FPS Navigation, Paint Texture, and Paint Lightmap. The left toolbar remains a tool selector: select a QSS tool there, then click in the 3D View to run it.
- Makes Isolate and Reveal work from either the viewport toolbar or the sidebar by explicitly invoking their mesh operators in the 3D View window region.
- Detects when a running Blender session has already lost its built-in toolbar definitions and displays a restart warning.
- Adds regression tests for Blender's namedtuple ToolDef behavior, unchanged built-in groups, dynamic tool generators, stale QSS tools, malformed entries, and safe iteration.

**Upgrade note:** v0.17.4 could already have damaged the in-memory built-in toolbar lists. A full Blender restart after installing v0.17.5 is required to reload Blender's original tool definitions; disabling/re-enabling the add-on alone cannot reconstruct deleted built-in tools.

## 0.17.4 changes


- Hardens the Blender 5.2 viewport toolbar repair: only valid ToolDef-like objects with a non-empty string `idname` are retained.
- Removes stray strings and arbitrary unsupported values from top-level and nested toolbar groups, while preserving valid Blender tools and separators.
- Handles nested tuple and list groups, removes stale QSS entries, and normalizes separators across every 3D View mode list.
- Adds standalone regression tests for invalid entries, nested groups, stale QSS ToolDefs, and safe toolbar iteration.

## 0.17.3 changes

- Fixes the Blender 5.2 toolbar crash reported in v0.17.2: earlier QSS registrations could create nested ToolDef tuples, causing Blender's toolbar drawing code to fail when reading tool identifiers.
- Repairs existing VIEW_3D tool lists by flattening legacy nested groups and removing stale QSS entries from every mode list.
- Registers the QSS actions as individual ToolDefs appended to the Object Mode and Edit Mesh tool lists. The implementation no longer uses nested groups or the fragile after= insertion path.
- Reports the registered count across all 3D View mode lists and keeps the manual Refresh control.



## 0.17.2 changes

- Moves QSS viewport actions into Blender 5.2's shared 3D View toolbar tool list so they are available in Object, Edit and Paint modes.
- Removes stale QSS toolbar definitions from previous add-on module instances and migrates tools left in old mode-specific lists by earlier 0.17.x builds.
- Displays a toolbar registration count in the Quake Studio panel to distinguish registration failures from viewport display issues.
- Keeps mode safety in the underlying QSS operators; actions that require Edit Mode or an imported BSP still validate those requirements.



## 0.17.1 changes

- Fixes the Quake Studio viewport toolbar presentation: QSS actions are now separate, individually visible buttons instead of being nested into a single drag-expand group.
- Registers Object Mode and Edit Mode actions against their own valid selection-tool anchors.
- Uses Blender's simple WorkSpaceTool left-click keymap format for consistent toolbar invocation.



## 0.17.0 changes

- Adds a dedicated **Quake Studio** workspace, created by duplicating the current workspace so the user's existing Layout and editor arrangements remain untouched.
- Adds a Quake Studio sidebar with level import, game/mod selection, map browsing, BSP export, Ironwail launch, installation/tool paths, navigation speed, decoupled lightmap density and lighting workflows.
- Separates **Visual lightmap resolution** (working paint-atlas scale) from **Target world units per luxel** (compiler-generated lightmap density); the latter explains the build-time, file-size and detail trade-off.
- Adds viewport toolbar tools for Player Start, focus selection, FPS navigation, isolate/reveal faces, Paint Texture and Paint Lightmap.
- Paint Texture now has a dedicated action that detaches the selected faces before entering Texture Paint. The previous Quake sidebar remains available as a compatibility fallback.
- Moves map audits, diagnostics and recovery actions into a collapsed **Advanced / Debug** section.

## Opening Quake Studio

Enable QSS, then use **Open Quake Studio Workspace** from the existing Quake sidebar. QSS duplicates the currently active workspace and names the copy **Quake Studio**; your original Blender workspace is preserved. The new workspace exposes the Quake Studio sidebar and QSS viewport tools.

The **Visual lightmap resolution** setting controls the working paint atlas only. **Target world units per luxel** controls the density requested from ericw-tools when generating a decoupled-lightmap BSP: lower values increase detail, build time and output size.



## 0.16.1 changes

- Adds a Blender UI action to generate real `DECOUPLED_LM` test BSPs with the configured ericw-tools `light` executable. The operation relights a separate copy, verifies the 40-byte-per-face BSPX records, and preserves the original BSP.

## 0.16.0 changes

## 0.16.0 changes

- Imports BSPX `DECOUPLED_LM` face records as authoritative lightmap metadata: per-face sample width/height, sample offset, and two independent world-to-luxel projection vectors.
- Reconstructs each face's lightmap UV island from its own decoupled axes, independently of the texture texinfo projection. `LMSTYLE` is honoured as the per-face style override.
- Enhanced export rebases imported decoupled layouts into a fresh `DECOUPLED_LM` table, appends rebuilt monochrome/RGB samples, and writes a flattened `LMSTYLE` table. The legacy `LMSHIFT`/`LMOFFSET` arrays are no longer emitted.
- Classic export builds a vanilla BSP29 fallback lightmap for each decoupled face with an editable atlas island, using the output texture projection, while preserving the original decoupled BSPX records and source sample offsets for BSPX-aware engines.
- Detached texture projections remain independent from decoupled lightmap axes. The classic fallback is resampled through the final exported texinfo, while the enhanced payload retains the face-local lightmap projection.
- The export integrity validator checks decoupled record size, per-face styles and sample bounds, contiguous rebuilt sample ranges, and every face vertex against its declared luxel grid. The direct Quake lightmap baker also solves sample positions from the decoupled axes.
- `LMSTYLE16` and legacy `LMSHIFT`/`LMOFFSET` layouts without `DECOUPLED_LM` remain explicitly unsupported; those layouts are rejected with a descriptive message rather than being treated as classic BSP29.



## 0.15.5 changes

- Removes QSS mouse-look completely. Blender's native MMB viewport navigation, mouse movement, cursor state and event handling are left untouched while FPS / Walk Navigation is active.
- QSS now acts only as a keyboard-movement overlay: WASD moves along the current horizontal viewport heading, Q/E moves vertically, and Shift accelerates.
- Movement reads the live viewport quaternion every update, so native Blender orbit immediately changes the direction of WASD movement.
- Keeps the corrected Z-up right-hand basis: D moves to the camera's right and A to its left. No custom yaw, pitch, cursor hiding or cursor warping remains.

## 0.15.4 changes (superseded)

- Attempted to derive custom MMB-look from Blender mouse-event deltas. The custom mouse-look path is removed in v0.15.5 in favour of native Blender navigation.

## 0.15.3 changes (superseded)

- Attempted to centre-lock the pointer during MMB-look. This custom mouse-look path is removed in v0.15.5.

## 0.15.2 changes

- Changes the install artifact to a single Blender-ready package archive: the downloaded GitHub artifact contains the `quake_surface_studio/` add-on folder directly, with no nested ZIP.
- Makes FPS MMB-look and WASD/QE movement run in the same QSS modal session, so movement continues while looking.
- Replaces the previous independent yaw/pitch camera reconstruction with incremental quaternion yaw/pitch, keeping the view orientation stable and clamping only the vertical pitch.
- Corrects the horizontal right vector so W follows the view heading and D moves to the view's right.

## 0.15.1 changes

- Changes FPS / Walk Navigation into a keyboard-movement overlay: WASD follows the live viewport heading, Q/E moves vertically, and Shift accelerates. QSS no longer captures MMB or mouse movement, so Blender's regular viewport orbit remains in control.
- Removes the legacy QSS MMB-to-FPS keymap from both add-on and user keyconfigs during registration cleanup.
- Fixes movement to translate the current viewport while preserving its existing aim, projection mode and orbit distance.

## 0.15.0 changes

- Added a persistent ericw-tools directory, Ironwail executable path and optional demo path to `CONFIG/qss/config.json`.
- Added an Ironwail launcher in Project & Source. It launches the active imported game map or a selected `.dem`, enables developer mode, uses `-condebug`, and records process output in QSS user data.
- Added **Run Full Map Audit**. It discovers every effective loose/PAK map in the selected game folder and processes them one at a time, continuing after individual map failures.
- Each map receives BSP structural/reference/lightmap validation, a real QSS import, face/material/UV metadata checks, Original/Working/Live preview checks, immutable source-atlas verification, lightmap-link repair, viewport selection/hide/reveal tests, texture detach and paint-mode tests on a disposable duplicate, and Classic BSP export plus source-to-export integrity validation.
- Optional audit stages include the full Quake direct CPU lightmap bake with restore, the experimental Cycles PBR bake with exact undo verification, Enhanced BSPX export, ericw `bspinfo`, verbose disposable-BSP `light` runs, and a `.map` → `qbsp` → `vis` → `light` compile pipeline when a sibling MAP source exists.
- Audit reports are written after every map to a checkpoint JSON file and, at completion, to `report.json`, `report.txt`, plus Blender Text datablocks `QSS_Map_Audit_Report` and `QSS_Map_Audit_JSON`. External tool output is stored in per-map log files.
- Destructive operations use a duplicate mesh/object and disposable export/compiler inputs; original game BSP files are not passed to ericw `light` because that tool overwrites its input.
- Optional CPU lighting bakes and compiler runs are disabled by default. Viewport tests require a running Blender UI with a VIEW_3D area; unavailable viewport tests are reported as SKIP.

# Quake Surface Studio 0.14.1

## 0.14.1 changes

- Fixed Blender 5.2 registration of the dynamic Game / Mod enum. During RNA registration Blender can evaluate enum items without a Scene context; QSS now resolves the item list from its saved installation configuration in that case.
- Validates the saved game identifier against discovered game folders before assigning the enum default.
- Hardened add-on cleanup after interrupted or failed registration so stale operator classes are unregistered before a retry.

## Automated game-map audit and external tools (0.15.0)

In **N → Quake → 01 · Project & Source**, configure:

- **ericw-tools folder**: the directory containing \`qbsp\`, \`vis\`, \`light\`, and optionally \`bspinfo\`.
- **Ironwail executable**: the full path to \`ironwail.exe\` or the Ironwail binary.
- **Demo (.dem)**: optional. Select a demo and use **Launch Ironwail…**; leave it empty to launch the active imported map. Ironwail starts with \`developer 1\` and \`-condebug\`. Each launch gets a separate directory under Blender user data \`qss/ironwail_logs/\`, containing \`qconsole.log\` and \`process_output.log\`.

Use **Run Full Game Map Audit** to process every effective map in the selected game/mod directory. The button is available even when no BSP is currently imported. The audit runs the standalone Python suite once, then imports and checks maps sequentially. It can be stopped with Esc after the current map completes.

The optional tests are disabled by default:

- **ericw light on disposable BSP copy** runs verbose relighting on a temporary copy. ericw \`light\` overwrites its BSP input, so QSS never gives it the original game file.
- **Compile sibling MAP files** runs \`qbsp\`, \`vis\`, and \`light\` only when a loose sibling \`.map\` file exists. Maps stored only in PAK archives have no extracted source MAP and are skipped.
- **Quake direct lightmap bake** runs the QSS CPU ray-traced solver and restores the imported lightmap.
- **Cycles PBR bake** runs on a duplicate object and verifies that Undo restores the exact pre-bake atlas.
- **Enhanced BSPX export** attempts per-face DECOUPLED_LM output; unsupported legacy layouts are reported as skipped.

The report directory is under Blender user data \`qss/audits/Map_Audit_<timestamp>/\`. It contains a checkpoint \`progress.json\`, aggregate \`report.json\` and \`report.txt\`, exported BSPs and external-tool logs. The same report is embedded in Blender Text datablocks \`QSS_Map_Audit_Report\` and \`QSS_Map_Audit_JSON\`. A map failure does not stop the remaining maps. The audit removes its temporary Blender objects and restores the original active object and interaction mode.

Viewport-specific checks require a normal Blender UI session with a 3D View area. If run in background mode or without a 3D View, those checks are explicitly marked SKIP; structural parsing, external compiler checks, and file export/validation can still run.

## 0.14.0 changes

- Added a persistent Quake installation setting stored in Blender's user configuration at \`CONFIG/qss/config.json\`. Choose the folder containing \`id1\`; QSS normalizes an \`id1\` selection to its parent and remembers the active game folder across Blender sessions.
- Added an active **Game / Mod** selector that discovers \`id1\` and immediate mod folders containing \`maps/\` or \`pak*.pak\`.
- Added a PAK-aware game map browser. It indexes loose BSP files and \`maps/*.bsp\` entries in Quake PACK archives, applies loose-file and higher-numbered-PAK override precedence, and extracts archived maps into a QSS cache before import.
- Added **Validate Exported BSP** inside Blender. Select the exported BSP and the original/source BSP in the file browser; a sibling \`.lit\` file is auto-detected, or an explicit sidecar can be supplied. The integrity report is written to \`QSS_Export_Validation\`.
- Added **Validate Maps in Active Game** to parse and validate each discovered BSP29 map, including face references and classic/enhanced lightmap bounds. Results are written to \`QSS_Game_Map_Validation\`.
- Added **Run QSS Python Test Suite** inside Blender. The add-on install ZIP now includes its standalone \`tests/\` folder so the same pure-Python test suite can run from Blender; results are written to \`QSS_Python_Test_Report\`.
- Quake materials now explicitly set Principled BSDF Roughness to \`1.0\` when created or reconnected, rather than inheriting Blender's default \`0.5\`.

## 0.13.0 changes

- Added a standalone **BSP export integrity checker**: `qss_export_check.py source.bsp exported.bsp`. It compares the source and exported files, checks that topology-related standard lumps and unknown BSPX payloads survive, validates face/texture/texinfo references and classic lightmap sample bounds, and verifies a sibling QLIT v1 `.lit` sidecar.
- Added an opt-in **Enhanced BSPX (DECOUPLED_LM)** lightmap export mode alongside the unchanged default **Classic BSP29** mode.
- Enhanced export keeps the classic LIGHTING fallback region at the front, then appends per-face higher-density monochrome and RGB samples. Each 40-byte `DECOUPLED_LM` record stores dimensions, a sample offset, and two independent world-to-luxel vectors; `LMSTYLE` declares the flattened static style 0. BSPX `RGBLIGHTING` and QLIT v1 `.lit` contain matching sample counts.
- The enhanced sampling pitch follows the imported working atlas: 1× = 16-unit luxels, 2× = 8, 4× = 4, and 8× = 2. Oversized faces are coarsened to stay within the 256×256 per-surface limit. Samples are bilinearly sampled from the working atlas; Classic BSP29 remains the broad-compatibility fallback.
- Enhanced output targets engines implementing the FTE/QuakeSpasm-Spiked `DECOUPLED_LM` and `LMSTYLE` BSPX extensions. QSS imports and rebases existing `DECOUPLED_LM` records and keeps lightmap axes independent from detached face-local texture projections. BSPX extensions are not universal; use Classic BSP29 when broad compatibility matters.
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
- **Quake Walk / Noclip Navigation** uses Blender's native first-person Walk Navigation with mouse-look, WASD/QE free flight, Quake-scaled speed, LMB exit, and Esc/RMB cancel. It does not collide with BSP walls, matching noclip movement.
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
- BSPX directory and unknown payloads are preserved. `RGBLIGHTING` and `DECOUPLED_LM` are interpreted. `LMSTYLE` is honoured. `LMSTYLE16` and legacy `LMSHIFT`/`LMOFFSET` data without `DECOUPLED_LM` are not supported yet.
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
2. Enable **SLOPGATE**.
3. In a 3D View, press `N` and open the **SLOPGATE** sidebar tab.
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

`qss_export_check.py` compares an exported BSP against the exact original file used for import. It checks face/geometry identity, retained source lumps and unknown BSPX data, texture/texinfo references, classic lightmap bounds, optional enhanced BSPX DECOUPLED_LM records, and the sibling QLIT v1 `.lit` file. A sibling `.lit` file is detected automatically; use `--lit path/to/file.lit` to select another one. This validator is read-only and does not replace loading the output in the target engine.

The inspector reports standard lump counts, BSPX extension names, RGBLIGHTING sample counts, optional QLIT validity, and face/texinfo/miptex references. It is a structural check, not a replacement for testing in the engine.

## Technical notes

Classic BSP29 has a 124-byte header and 15 standard lumps. Each face references a 40-byte texinfo record with two projection vectors and a miptex index. `RGBLIGHTING` is a BSPX extension that stores one RGB triplet per classic lighting byte/sample; the add-on writes the same payload (without the QLIT header) into BSPX and wraps it in QLIT v1 for the sibling `.lit` file.

- `bsp.py`: BSP29/BSPX reader-writer, miptex/texinfo helpers, WAD2, palette/PAK, entities, QLIT and RGBLIGHTING helpers.
- `addon.py`: Blender geometry import, entity light import, painting UI, Quake direct-light solver integration, experimental Cycles bake and BSP export.
- `color.py`: Quake palette / Blender colour-space conversion.
- `qss_inspect.py`: standalone BSP29 and BSPX inspection tool, including per-face RGB luxel/style inspection.
- `qss_export_check.py` and `export_validation.py`: standalone source-to-export integrity checks, classic sample bounds, optional enhanced BSPX lightmap checks and QLIT sidecar validation.
- `lightmap_export.py`: Blender-independent higher-density per-face lightmap sampling, DECOUPLED_LM parsing and BSPX payload helpers.
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
