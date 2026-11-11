# SLOPGATE — AI Project Handoff

**Last reviewed:** 2026-11-11  
**Purpose:** A compact, maintained project and collaboration brief for future assistant sessions. This is an editorial summary, not a verbatim record.

## Read this first

At the start of a new project session, read this file first. Then consult the main conversation archive, ai chat history/Slipgate_Chat_History_Clean.md, whenever a detail needs context, dialogue-level confirmation, technical evidence, or fact-checking.

This brief deliberately compresses the archive. It can become stale. The live repository, current branch, test output and the main archive outrank assumptions in this summary. Always inspect the current branch head and relevant source before modifying code.

The archive filename and some historic headings contain the old spelling “Slipgate”. That is historical. The current product name is **SLOPGATE**. Do not rename or rewrite historic transcript material merely to normalize the old spelling.

## Project identity and purpose

- Product: **SLOPGATE**, a Blender add-on and workflow for Quake BSP map import, texture editing/painting, lighting, map inspection and export.
- Repository: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio
- Active branch in the last inspected source state: fix/v0.11.1-metadata-style-order-test
- Target interactive environment: Blender 5.2 on Linux.
- Target map format: Quake 1 BSP29. Target engine includes Ironwail 0.8.2.
- The add-on's package folder and internal identifiers still use quake_surface_studio / QSS for compatibility. Do not perform a partial global rename. New user-visible branding, log entries and new code labels should use SLOPGATE.
- The scope may grow beyond surface painting; preserve the existing BSP, texture, lighting and export workflows.

## How to work with the user

1. **Do not remove existing functionality, controls, operators, settings or workflows without explicit permission.** If a change might retire or replace a feature, ask first. The user has explicitly allowed changing or rolling back the recent experimental Cycles attenuation work, but that permission is limited to that lighting experiment.
2. Work incrementally and keep changes organized. The user prefers one coherent task at a time and values accuracy over speculative conclusions.
3. Do not ask again for information already present in the conversation archive or current project context.
4. Be direct about what is known, inferred, or unverified. Distinguish source inspection, automated tests, user-reported results and actual interactive verification.
5. Never claim Blender GUI/runtime testing, a Cycles/Eevee render or bake, QBSP compilation, or Ironwail launching succeeded unless that was actually performed. CI and pure-Python tests are not substitutes for those tests.
6. Preserve original dialogue in the main archive. Append new sessions; do not rewrite the historic transcript. Keep this concise handoff updated when decisions or source state materially change.
7. The user wants an **installable Blender ZIP for every new add-on version/build**. For each such build:
   - build from the exact source commit being reported;
   - verify the artifact exists and its package layout contains the installable quake_surface_studio/__init__.py;
   - provide a direct download link;
   - report exact version, source commit, artifact identity/checksum when available, and test status;
   - if CI fails or the artifact cannot be verified, state that plainly and do not offer an unverified archive.
8. Do not promise background work or results later. Complete the task in the current session or state what could not be completed.

## Current source/build baseline — checked 2026-11-11

- Repository: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio
- Active branch: fix/v0.11.1-metadata-style-order-test
- Current add-on version: **0.21.0**.
- Exact source commit for the final 0.21.0 package build: 87a1cee7dfc007b177c4b9923e7c2874777e773d (the code implementation commit is 1bd489a941996b1e6951e5e80bcb29ad55717738).
- Successful final QSS Python workflow: run 43006568762; compileall, standalone suite, package assembly and artifact upload passed.
- Install artifact: Quake-Surface-Studio-v0.21.0-Blender-Install, artifact ID 13847848551, 250,878 bytes, 41 ZIP entries.
- SHA-256: 65e6bef6f391d2216ebb9c67fd8ace8e6920499161acce08c12b194b2b9f57c7. ZIP integrity and installable package root verified; expiry 2027-02-09.
- GitHub artifact page: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43006568762/artifacts/13847848551
- Runtime validation outstanding: no Blender 5.2 GUI, actual QBSP/VIS, Cycles/Eevee render/bake, or Ironwail run.
- Previous 0.20.9 artifact details are historical.
- Main add-on source: quake_surface_studio (zip me for blender)/addon.py; MAP text-preserving parser/synchronizer: map_sync.py; focused tests: tests/test_map_sync.py. Direct MAP-via-QBSP import was superseded and removed in 0.21.0.
- Successful QSS Python workflow push run: 42997883763. Python compilation, the standalone unit suite, package assembly and artifact upload passed.
- Successful PR-triggered QSS Python run: 42997891885.
- Successful companion converter GUI workflow run: 42997891883.
- Install artifact: Quake-Surface-Studio-v0.20.9-Blender-Install, artifact ID 13844916535, 243,699 bytes.
- Artifact SHA-256: 9876a4092af7f7334e62ec9c7acd351fc09b1780fb4470e801258f724f1f0a60. Artifact expires 2027-02-09.
- Downloaded ZIP was verified: 39 entries, no corrupt member, and the installable package root contains quake_surface_studio/__init__.py.
- **Runtime validation outstanding:** no interactive Blender 5.2 import test, no actual run against the user's ericw QBSP installation, no Cycles/Eevee viewport or bake test, no VIS or Ironwail launch. 0.20.9 is an experimental implementation build, not an official release.
- Version 0.20.8 and its artifact details are historical; 0.20.9 supersedes that baseline.

### Official-release direction

The user wants the currently discussed main features implemented before a cleanup/polish phase and a first official SLOPGATE release. Build coherent features and preserve compatibility now; do not prematurely label experimental builds as official. Once the main features are in place, reserve a dedicated stabilization phase for cleanup, tests, UX/documentation, migration/backward compatibility, and target-environment validation.

## Existing add-on architecture and status

### BSP, textures and painting

- Main add-on source is quake_surface_studio (zip me for blender)/addon.py.
- BSP parsing and geometry/material workflows are split into supporting modules, including bsp.py, lighting.py, color.py and related helpers.
- Imported mesh faces retain their source miptex index as qss_bsp_miptex_id; materials retain source texture names in qss_texture_name. These properties support correct texture export and future per-face classification/filtering.
- Texture painting uses the imported faces/materials and existing UV/image workflows. Preserve per-face mapping, source texture identity and the current export path.
- The user confirmed in Blender that version 0.20.6 baked without visible seams, texture painting worked well, Quick Actions worked, the second-map grey/white tint regression was fixed, the viewport floor grid was hidden, and lighting modes could be switched in Edit Mode but not Texture Paint. These are user-reported checks on 0.20.6, not a blanket validation of 0.20.8.
- The 0.20.7 import-folder and Quake-palette-popup changes had not yet received explicit user confirmation in the last handoff.

### Lighting paths already present

- The “Bake Imported Lights to Lightmap” path is a native Cycles diffuse bake with direct and indirect contributions.
- Preview modes include Cycles-rendered lighting and Live Lights (native Blender lamps / Eevee Next preview).
- The existing **Quake Direct** path is a separate CPU solver that evaluates Quake/ericw-style light contributions. It is not the same thing as the native Blender lamp preview or the recent Cycles light-node experiment. Do not delete or replace Quake Direct as part of simplifying native lamp falloff.
- Imported Quake light parsing is in addon.py, notably _import_bsp_entities(), _entity_spot_direction(), _parse_light_value() and _parse_quake_light_color().
- The current entity importer creates POINT or SPOT Blender lights. It already understands target, mangle and angle for direction; spotlight cone width uses angle (default 40 degrees), with _cone as a fallback, and _softangle for the inner cone transition.
- The importer reads the standard light, _color, delay, wait, _falloff, target, mangle, angle, and _softangle fields. The worldspawn import currently reads _dist, _range, _gamma, _anglescale / _anglesense, _bounce, _bouncescale, _bouncecolorscale and other existing values. Inspect the live parser before relying on this list as exhaustive.
- lighting.py contains the exact Quake/ericw attenuation helpers used by the CPU direct solver, plus blender_live_light_preview_parameters() for a calibrated **native-light approximation**. Keep those paths conceptually separate.

### Experimental Cycles attenuation code to simplify

The most recent lighting experiment added:

- lighting.ericw_cycles_light_falloff_correction() and its tests for delay 0 and delay 5.
- In addon.py: _qss_make_cycles_math_node(), _qss_cycles_falloff_tree_is_owned(), _qss_build_cycles_delay_falloff_nodes() and _qss_update_cycles_delay_falloff().
- The node graph uses a Cycles Light Falloff node and custom math to reproduce the ericw delay-0 and delay-5 radial curves. Eevee ignores this custom light shader graph.
- The native preview helper still exists and returns Blender energy, cutoff-distance and emitter-softness approximations. The custom Cycles graph is layered on top of that path.

The user has now explicitly changed the objective: **do not try to perfectly imitate ericw's render with native Blender lamps for now.** A reasonable next implementation is to remove only the recent native-light Cycles correction graph and its dedicated helper/tests, while retaining the standard native-light approximation and the separate Quake Direct CPU solver. Make that change as a small isolated patch, review all call sites, and do not remove any unrelated lighting/bake features. Do not make that code change until the new entity-key plan is settled.

## Current lighting and MAP workflow design — 2026-11-11 (planned, not implemented)

The latest user clarification supersedes the earlier per-light delay-2 / _sl_type proposal. **Do not add _sl_type.** Existing Quake/ericw entity classnames and keys identify light behavior. A worldspawn key selects the lighting workflow for the whole map.

### Worldspawn lighting mode

Use the exact worldspawn key proposed by the user:

    "_sl_SLOPGATE_lighting" "1"

- Value 1: SLOPGATE-native lighting intended for Cycles.
- Value 2: SLOPGATE-native lighting intended for Eevee.
- Missing, 0, or any other value: rough ericw-light approximation for every light.

Treat 1 or 2 as the map's preferred render engine. Select it as the initial preview/bake engine on import, but do not hard-lock the user out of switching. In native modes, Blender light properties and SLOPGATE keys control the result; per-light delay does not select an ericw attenuation profile. In fallback mode, established ericw keys (delay, wait, light, _falloff, etc.) guide a practical native Blender approximation. Nearby walls/receivers are the priority, not pixel-identical ericw output.

Ignore SLOPGATE-only per-light overrides when the worldspawn mode is absent or not 1/2, so old maps do not accidentally adopt new semantics.

### Reuse existing entity conventions — no type key

- Point: ordinary Quake light entity. ericw accepts entity classnames whose first five letters are "light".
- Spot: an ordinary light entity with target or mangle; reuse angle and _softangle for cone width/transition. targetname retains its established role for switchable lights.
- Sun: a light entity with _sun set to 1, with mangle or target controlling direction. Also support ericw's worldspawn _sunlight / _sun_mangle family for global sunlight where applicable. Do not create duplicate Blender Suns for sky faces.
- Surface / Area: a light entity with _surface naming the texture whose faces emit light. Reuse related existing keys such as _surface_offset, _surface_spotlight and _surflight_group where supported. This is a face-linked emitter template, not an ordinary point light with a new type key.
- Keep _color, light and existing Quake direction/cone keys unchanged for compatibility.

A Blender Sun is a directional object, whereas ericw sunlight is emitted by sky-content faces. Keep sky background and direct sunlight separate. Exclude sky faces from inappropriate lightmap receiving; decide and test separately whether they should cast shadows. Represent the Sun once as a directional source, not duplicated over sky polygons.

### Blender-specific keys

The SLOPGATE namespace is still proposed as _sl_ (single leading underscore, lowercase for per-light keys). The worldspawn selector above retains the exact capitalization proposed by the user. Do not create the FGD yet.

Initial user-proposed keys:
- _sl_temperature: valid range 800–20000 K; when set, enable temperature color.
- _sl_tint: optional tint multiplier for temperature color; neutral white when absent.
- _sl_power: explicit Blender energy override; negative means unset; zero is a valid explicit override.
- _sl_exposure: Blender exposure in EV; neutral default 0.
- _sl_normalize: explicit boolean override; negative means inherit Blender default.
- _sl_radius: negative means inherit; maps to a type-specific source-size property.
- _sl_soft_falloff: explicit boolean override where supported; negative means inherit.

The user wants keys for the other relevant Blender light parameters too. Design a type-aware property registry based on Blender 5.2 POINT, SUN, SPOT and AREA data APIs. Unset keys must leave Blender defaults intact. Distinguish shared settings from subtype-only settings. Preserve light → automatic Blender energy conversion using the existing scene multiplier as the first choice; _sl_power bypasses that automatic conversion. A separate area/surface-emitter multiplier may be added after calibration. Calibrate each type separately because their energy semantics/units differ.

### MAP files become a first-class workflow

All MAP-related operations are gated behind a validated ericw-tools path. Do not disable ordinary BSP import, painting or existing workflows merely because no compiler path is configured. Validate the executable needed for each operation:
- qbsp: compile MAP to BSP, including temporary BSPs for MAP import.
- vis: generate PVS after a full geometry compile when a game-ready BSP is wanted.
- light: optional ericw lightmap compile only; do not run it in the SLOPGATE-native default export because it overwrites BSP lighting data.
- bsputil: BSP decompile and optional texture/entity utilities, depending on the exact installed binary's supported options.

#### Historical MAP-first import proposal — superseded by the BSP-first companion workflow

Superseded: the user chose BSP import with silent same-basename MAP discovery instead. Do not invoke QBSP or search for WADs during MAP association. The companion MAP is only used for preserving brush source and synchronizing supported light properties.

Use the source MAP's WAD references and configured search paths when invoking QBSP. Keep compiler working/output directories isolated from the original map.

#### Existing BSP import and automatic MAP recovery

- If a user imports a BSP and a plausible matching MAP exists, offer/link it as the editable source.
- If there is no matching MAP, offer bsputil --decompile. ericw bsputil can reconstruct a .decompile.map; this is a recovered approximation, not the original TrenchBroom project. Never overwrite the BSP or imply editor groups/comments/hidden state can be recovered byte-for-byte.
- Preserve the original BSP and create the recovered MAP as a separate file.

#### Blender-to-MAP light synchronization

The linked MAP is the source of brush geometry. In the first implementation, SLOPGATE writes light/entity changes back to MAP; it does not reverse-engineer edited Blender triangle meshes into TrenchBroom brush planes.

- Existing imported lights retain their source entity association and original key/value data.
- Changing a supported Blender light property updates the corresponding MAP key.
- Moving a light updates origin; changing spot/sun direction updates mangle or preserves/updates target according to the source convention.
- Deleting a linked light removes its corresponding light entity on export; adding a Blender light creates a valid Quake/ericw light entity using established class/key conventions.
- Preserve every unrelated entity and unknown key. Preserve brush blocks, texture axes, comments and unrelated source text; do not regenerate the whole MAP from a lossy generic representation.
- Detect source-MAP changes made externally in TrenchBroom and warn/offer reload or merge rather than silently overwriting them.
- Export to a separate updated MAP by default, or make in-place overwrite explicit with a backup.

A per-map SLOPGATE manifest under the output folder can hold source hashes and Blender-object/entity associations without injecting editor-only IDs into every MAP entity. Settle the exact mapping format during parser design.

### Compiler/export stages

Keep the stages distinct and selectable. Do not make every export a full QBSP/VIS/light rebuild.

Full geometry build:
- Run QBSP from the linked MAP to a new working BSP.
- Run VIS optionally when a game-ready PVS is wanted. It is not needed for Blender geometry import.
- Import the result and perform/redo the SLOPGATE bake after geometry changes. A full QBSP rebuild creates a new BSP and invalidates the previous BSP lightmap result.
- Do not run ericw light unless the user explicitly chooses the ericw lighting path; it overwrites BSP lighting data.

Entities-only update:
- If brush geometry is unchanged, write the edited MAP entity data and run qbsp -onlyents against the existing BSP. ericw documents this as updating MAP entities only; it avoids rebuilding geometry.
- VIS is not needed when geometry/PVS topology is unchanged.
- If switchable lights using targetname are present, ericw documents a follow-up light -onlyents after qbsp -onlyents to assign style numbers. This is not a full light calculation.
- Re-bake SLOPGATE lighting after entity light changes if the lightmap should reflect those changes.

Skip compiler stages:
- Allow a true skip when the BSP already contains the intended geometry and entity data. Make clear that MAP and BSP may then be out of sync.
- Keep skip, entities-only and full-geometry choices distinct.

### Painted textures and WAD export

- Export painted Quake textures into a WAD in a dedicated per-map output folder, provisionally <game-or-project>/##SLOPGATE/<mapname>/.
- Add/update the MAP worldspawn wad reference while preserving existing WAD references. Use paths QBSP/TrenchBroom can resolve in the configured game/mod search path; avoid absolute machine-specific paths.
- Quake MAP's worldspawn wad key identifies source WADs; QBSP embeds the referenced textures used by the map into the BSP.
- If only existing texture pixels change and dimensions stay the same, bsputil --replace-textures may update BSP textures without a full geometry rebuild. ericw's changelog records this feature, but the exact alpha11 binary/package variant must be capability-checked because not every packaged build/manpage exposes the option consistently. If unavailable, use a full QBSP and reapply/rebake SLOPGATE lightmaps.
- New texture names may require full QBSP to be embedded. Changed dimensions need UV/texture-scale validation. The texture-replacement documentation warns about dimension mismatches.
- Texture updates after baking must not silently discard SLOPGATE lightmaps. If full QBSP is necessary after painting, apply the bake again to the rebuilt BSP.

### Suggested authoring workflow

1. Create/edit geometry in TrenchBroom and save MAP.
2. Open MAP in SLOPGATE; internally run QBSP to a working BSP and import it.
3. Adjust lights in Blender and use native Cycles/Eevee previews. Export/sync light changes to MAP as needed.
4. Once geometry is final, perform a full QBSP build and optional VIS; reload/associate the final BSP if necessary.
5. Finalize Blender lights and bake SLOPGATE lightmaps to that BSP.
6. Paint textures. Export painted textures to the per-map ##SLOPGATE WAD and update the MAP WAD reference. Use in-place BSP texture replacement only if the configured tool supports it safely; otherwise rebuild and reapply the bake.
7. Final export can select skip, entities-only or full geometry. Geometry changes require full QBSP and a new bake; light/entity-only changes generally do not require VIS.

This keeps TrenchBroom authoritative for brush geometry, SLOPGATE authoritative for Blender-authored lighting and paint, and MAP authoritative for entity data that must remain editable in TrenchBroom.

### Delivered implementation: version 0.20.9 — first MAP import milestone

- Added QSS_OT_import_map and an **Import MAP via QBSP** control in the Project panel. The control is enabled only when a valid active game directory and configured ericw-tools qbsp executable are available.
- MAP files are compiled with QBSP into a dedicated persistent Blender user-data cache under qss/map_imports. QBSP output never targets the source MAP or an existing game BSP.
- The command builder uses explicit source and destination paths plus configured -basedir, -gamedir, -wadpath and -path search paths. It launches without a shell. The command and QBSP output are saved to a per-import log.
- SLOPGATE validates that QBSP produced a file and parses it with the existing bsp.BSP29 reader before handing it to the existing BSP importer. This intentionally reuses the established BSP geometry/material/entity import pipeline; the initial importer remains BSP29-only.
- The imported map object stores source MAP path and SHA-256 as qss_source_map_path and qss_source_map_sha256, and is tagged qss_map_imported_via_qbsp for later entity-sync work.
- The normal Add/Replace import confirmation also forwards the source MAP association.
- The operation runs QBSP only. It deliberately does **not** run VIS or ericw light: VIS is not necessary for Blender geometry import, and ericw light would produce/overwrite lighting outside the SLOPGATE bake workflow.
- Existing Import BSP, Export BSP, painting, preview, Quake Direct and bake workflows remain in place.

### Automated validation for version 0.20.9

- Added three QBSP command-builder tests covering source/destination separation, repeated search paths, missing/invalid paths and expected output argument ordering.
- Successful QSS workflow run 42997883763: compileall, the standalone test suite, package assembly and artifact upload passed.
- Successful PR workflow run 42997891885 passed; converter GUI run 42997891883 also passed.
- Install ZIP SHA-256 and package layout were verified after download (details above).
- No actual QBSP executable was run against the user's Quake installation. No Blender 5.2 runtime/UI import was performed. The user still needs to test the new Import MAP button using their configured QBSP and game/WAD paths.


### Delivered implementation: version 0.21.0 — companion MAP workflow (automated tests passed)

- Current user scope: import BSP as before; if a same-basename MAP exists beside it, discover and associate it silently. No direct MAP import, QBSP invocation, WAD discovery, or WAD resolution.
- Added map_sync.py, a source-span MAP parser/patcher. It indexes top-level entity key/value pairs while treating nested brush blocks as opaque. Patches preserve brush planes, texture axes, comments, unknown keys, WAD references, and unrelated source text.
- BSP import associates compiled BSP light entities with MAP light entities by classname and origin. Malformed/unreadable companions do not block ordinary BSP import.
- BSP export prepares a separate companion MAP beside the exported BSP. It refuses to overwrite the source MAP, refuses an unrelated existing output MAP, and checks the source MAP hash to detect external TrenchBroom edits.
- Current supported MAP edits: linked light origin, RGB color, light magnitude, spotlight cone angle, and deletion of a linked imported light. Creating new light entities and spot direction/mangle synchronization are not yet implemented; original target and mangle keys are preserved. Painted texture pixels continue through the existing BSP texture export path. MAP WAD paths and texture references are not rewritten.
- No geometry synchronization, QBSP rebuild, VIS, ericw light, WAD generation, or WAD search is performed. The source MAP remains unchanged.
- The old direct Import MAP via QBSP operator and sidebar control were removed as explicitly superseded by the BSP-first companion workflow.
- Version 0.21.0. Final QSS Python workflow 43006568762 passed compileall, standalone tests (including MAP preservation/byte-write and light-deletion tests), package assembly and artifact upload. The installable ZIP was downloaded and verified (41 entries, correct package root, no corrupt members; SHA-256 65e6bef6f391d2216ebb9c67fd8ace8e6920499161acce08c12b194b2b9f57c7). Blender 5.2 GUI/runtime and Quake toolchain validation remain outstanding.

### Remaining MAP implementation boundary

The MAP parser, source-preserving patch mechanism, same-basename companion discovery, and safe companion export are implemented in 0.21.0. Current synchronization is deliberately limited to existing linked light origin, color, magnitude and spot cone values, plus deletion of linked imported lights. Remaining work:
1. Spot direction/mangle, target-linked lights, worldspawn sunlight, creation of new light entities, and additional point entities.
2. Worldspawn _sl_SLOPGATE_lighting mode and full point/spot/sun/surface entity classification.
3. Full / entities-only / skip export workflow and qbsp -onlyents handling.
4. WAD export and safe BSP texture replacement/deployment. Painted pixels still use the existing BSP texture export path; SLOPGATE does not generate or search for WADs.
5. Optional BSP-to-MAP recovery through bsputil --decompile.
6. Blender light-property key registry and, after it stabilizes, the official rerelease-based FGD.

Keep the first MAP round-trip strictly limited to lights and textures; never regenerate brush geometry from the Blender mesh. Preserve existing BSP import/export, Quake Direct, Cycles bake, Live Lights, texture painting, and user data.

### Source references checked for this plan

- ericw light entities, spot/sun/surface conventions: https://ericw-tools.readthedocs.io/en/latest/light.html
- ericw QBSP and -onlyents, WAD path/search behavior: https://ericw-tools.readthedocs.io/en/latest/qbsp.html
- ericw VIS and PVS: https://ericw-tools.readthedocs.io/en/latest/vis.html
- ericw light full compile overwrites BSP lighting; light -onlyents assigns switchable style numbers: https://ericw-tools.readthedocs.io/en/latest/light.html
- ericw bsputil decompile and texture operations: https://ericw-tools.readthedocs.io/en/latest/bsputil.html
- ericw changelog notes when bsputil --replace-textures was added: https://ericw-tools.readthedocs.io/en/latest/changelog.html
- Blender 5.2 Light API: https://docs.blender.org/api/5.2/bpy.types.Light.html
- TrenchBroom manual: https://trenchbroom.github.io/manual/latest/

## Other still-relevant ideas and work

- A TrenchBroom-inspired View Options popup was proposed, separate from the narrow sidebar. First candidates are editor/tool/non-rendered surfaces such as trigger, clip, origin, hint, hintskip and skip. Sky, liquids and fences must not be hidden by default because they are actual game-visible features. Implement only as reversible face visibility, never destructive geometry/material deletion; test Object Mode, Edit Mode, Texture Paint, bake and export before adopting. A read-only texture classifier/diagnostic list should precede the filter UI. This is not implemented.
- Meta Quest 3 / Linux PCVR painting was explored. The feasible direction was a controller raycast onto an imported BSP face, conversion to the existing face-local UV/image paint path, and stamping the current brush while a trigger is held. Blender VR Scene Inspection alone does not provide controller texture painting. No VR code is implemented.
- The repository history also contains a separate Quake texture-converter tool/workflow. Treat it as a companion utility; do not conflate its GUI/CI with SLOPGATE's Blender add-on or its validation.
- The 18-light delay-calibration map lives under lighttest/. Its matrix is six delay groups × three brightness values (50, 300, 900). Static-light IDs must not use targetname, because ericw uses that for switchable lights; the earlier harness uses _qss_test_id. The calibration harness was synthetically checked but the compiler and real BSP sampler were not run in the assistant environment. Use its raw compiler outputs/CSV if the user supplies a real run.

## Test and delivery discipline

- Run focused unit tests for every lighting/parser change and the existing full standalone Python suite.
- Test Blender API integration in the target Blender 5.2 environment. At minimum check import, POINT/SPOT/SUN/AREA creation, light values, preview switch, Cycles bake, Eevee preview, sky exclusions, and save/reopen behavior.
- Use the 18-light test map for legacy delay approximation; use a dedicated SLOPGATE-authored map for the new key schema and all four light types.
- Validate area/surface emitters separately; test a large face, multiple matched faces, different normals, and no-match texture behavior.
- Only after the schema and behavior settle, prepare the official-rerelease-based FGD.
- For every new installable build, produce and verify the Blender ZIP and provide it with the exact source commit and test status.

## Source references

- ericw-tools light entity keys: https://ericw-tools.readthedocs.io/en/latest/light.html
- Blender 5.2 Light API: https://docs.blender.org/api/5.2/bpy.types.Light.html
- Blender 5.2 PointLight API: https://docs.blender.org/api/5.2/bpy.types.PointLight.html
- TrenchBroom manual: https://trenchbroom.github.io/manual/latest/
- FGD property conventions reference: https://book.leveldesignbook.com/appendix/resources/formats/fgd
