# SLOPGATE — AI Project Handoff

**Last reviewed:** 2026-11-13  
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


## Current source and install baseline — 2026-11-14 (SLOPGATE 0.21.3)

### User's Blender 5.3 feedback on 0.21.2

- User upgraded to Blender 5.3; SLOPGATE 0.21.2 loads without errors.
- Mesh Edit Mode **Select Affecting Lights** context action works as intended (takes a few seconds).
- Object Mode **Select Affected Faces** entry was missing.
- Cycles Bake failed with \`NameError: name 'scope_label' is not defined\` in the execute wrapper.
- User confirmed mod palette fallback works.
- Nodraw handling was not integrated before this version; only the standalone classifier existed.
- Live Eevee/Cycles previews remain too bright, but the user agrees this is not caused by the Emission socket. Source shows live modes already use diffuse Base Color and disconnect emission. Brightness calibration remains open.

### Implemented in 0.21.3

- Fixed undefined bake \`scope_label\`: it is now computed from the Only Selected Faces checkbox after resolving selection and before entering the Object Mode bake path.
- Fixed Object Mode **Select Affected Faces** context menu and operator. Selected SLOPGATE lights are resolved to their owning imported BSP by membership in its map collection hierarchy; the BSP itself no longer needs to be selected. The operation switches to the resolved map and selects affected faces in Edit Mode.
- Integrated \`surface_policy.py\` into material factory, Original/Baked preview, live Eevee/Cycles preview, Cycles bake material override, and Quake Direct bake.
- Compiler-only nodraw surfaces (trigger, clip/playerclip/monsterclip, origin, hint, skip/hintskip, null, nodraw, bevel, areaportal and supported name variants) are rendered transparent in Blender.
- Nodraw surfaces do not receive lightmaps and do not block Quake Direct visibility rays.
- \`blocklight\` is deliberately special: it is transparent to the camera and does not receive a lightmap, but remains opaque in Cycles bake and stays in the Quake Direct BVH as a light blocker.
- For the Cycles bake, non-blocking nodraw materials temporarily use Transparent BSDF. Blocklight uses opaque diffuse during the bake while its lightmap UVs are placed outside the bake target; full BSP geometry remains available as an occluder.
- Selected-face bake input is checked for receiver policy. Selecting only nodraw/blocklight faces is rejected with an explanatory message.
- Added \`tests/test_surface_policy.py\` with four tests for compiler-only names, blocklight semantics, safe non-matches and policy behavior.
- User-facing preview distinction unchanged: Original/Baked use albedo × lightmap into Emission to show Quake lightmaps without extra Blender lighting. Live modes use diffuse. Do not alter the Original/Baked path to diffuse as that can double-light it.

### Latest verified installer

- Branch: \`fix/v0.11.1-metadata-style-order-test\`
- Version: \`0.21.3\`
- Source + README commit packaged: \`214f63b0d24ae5da113f58d872770ca40d35d08d\`
- QSS Python push workflow run: \`43569530862\`, job \`132370658801\`, success. Python compilation, 236 standalone tests, package assembly and artifact upload passed.
- QSS PR workflow run \`43569522588\` and converter GUI PR run \`43569534704\` also passed; converter workflow is companion-tool validation, not Blender GUI validation.
- Artifact ID: \`14103795855\`, \`Quake-Surface-Studio-v0.21.3-Blender-Install\`, 267,737 bytes, 46 ZIP entries, expires 2027-02-12.
- SHA-256: \`c13f6308ea2d30e01c238dde330dadc8a332b51d122efb5e56753ab436c2e966\`.
- Artifact page: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43569530862/artifacts/14103795855
- Downloaded ZIP: \`/mnt/data/SLOPGATE-v0.21.3-Blender-Install.zip\`. ZIP integrity passed; package root is \`quake_surface_studio/\`; required modules and the new classifier tests are present.
- Installer link must be given whenever sending a build: \`sandbox:/mnt/data/SLOPGATE-v0.21.3-Blender-Install.zip\`.

### Runtime validation still needed

- User should verify 0.21.3 in Blender 5.3: right-click a selected imported light in Object Mode without selecting the BSP; **Select Affected Faces** should now appear and switch to Edit Mode.
- Retry Cycles bake in 5.3; the undefined-name crash is fixed in source. Test full bake and Only Selected Faces, including a selection that includes nodraw faces.
- Test trigger/clip/etc. as invisible in Eevee Material Preview, Cycles and render; confirm these faces do not receive light or cast shadows.
- Test blocklight is invisible and receives no lightmap, but still blocks light.
- No interactive Blender runtime tests of 0.21.3 have been performed by the assistant. Automated CI does not prove menu display, shader transparency, bake success or renderer output.
- Selected-face bake still does not use a receiver-only temporary mesh; it preserves the remaining atlas but Cycles still evaluates the complete BSP mesh. The user previously observed no substantial bake time reduction. Do not claim faster baking.
- Live-preview brightness calibration remains unresolved. The live preview path is already diffuse; Quake-to-Blender energy conversion needs a calibrated separate adjustment.
- Keep BSP2/2PSB, lightmap edge bleed and true receiver-only bake performance as separate future milestones.
- Always deliver a verified ZIP link for every updated installable build, stating version, exact commit, automated test status and artifact digest.


## User feedback and source update — 2026-11-14 (0.21.4 timing)

### Runtime feedback on 0.21.3 in Blender 5.3

- User confirms **Select Affected Faces** now works.
- User confirms Cycles bake is back and working, but subjectively feels slower. No measured before/after duration is available yet.
- User confirms trigger and clip faces are no longer visible.
- The user asked whether blocklight is a Quake feature. It is not in the classic Quake 1 / ericw-tools QBSP special-texture list checked for this handoff. The existing SLOPGATE `blocklight` policy is a compatibility/custom texture-name classification, not standard Quake semantics. Do not describe it as a required Quake feature. Do not silently remove its existing behavior without deciding whether compatibility should be preserved or the classification should be disabled.
- User reports doors, elevators and other moving brush objects render incorrectly in the imported map. The importer currently flattens every BSP face into one static mesh and does not map BSP29 `models` lump face ranges to entity `model "*n"` references. This is a real architecture gap, not just a question of showing a mover's animated position.

### Bake timing added in 0.21.4

- Added pure formatter `bake_stats.py` and unit tests `tests/test_bake_stats.py`.
- Cycles bake records both total operation duration (setup, bake, atlas processing and scene restoration) and time inside Blender's `bpy.ops.object.bake(type='DIFFUSE')`.
- Timings are included in the completion report and `Save Lighting Diagnostics`; failed attempts retain separate attempt timing fields.
- Rebuilding the lightmap atlas clears the old timing fields.
- No bake settings, samples, bounce counts, receiver geometry or Cycles shader behavior were changed.
- Automated tests and ZIP packaging must be verified for the final commit. No interactive Blender bake timing measurement is available in the assistant environment yet.

### Moving brush entity diagnosis — next implementation milestone

- Quake BSP29 separates brush models in its `models` lump using `firstface` and `numfaces`; brush entities refer to inline models with entity key `model "*n"`.
- SLOPGATE currently imports all face ranges into one static map mesh and ignores those entity-to-model associations.
- For entities compiled with an `origin` brush, QBSP rebases the brush geometry around the model origin and writes the previous center into the entity's `origin` key. A display/importer that ignores that transform can place a door, platform or rotating brush at the wrong location.
- The correct model is to preserve worldspawn geometry as the static world and import each inline brush model as a separate child object with its entity origin and initial orientation applied. Retain source BSP face IDs, texinfo/miptex metadata and original local coordinates so texture projection, lightmap sampling and export remain correct. Do not apply mover travel distance or guess a later animation position; the imported placement should be its compiled initial/entity placement.
- Implement and test this against maps containing `func_door`, `func_plat` / lifts, `func_train` and rotating brush entities. Until then, avoid a broad transform patch to the flattened mesh because it could break direct-light BVHs, face selection, map sync, UV/lightmap rebuild and export.
- Keep this as a separate feature milestone from bake timing. The user's comment about initial positions is plausible for origin-brush models, but it is not a generic rule that all movers start elsewhere.



### Latest verified installer — 0.21.4 bake timing telemetry

- Latest handoff/documentation branch head: `a0508d30927d902f6186649f79e66f3458644eef`.
- Exact source + README commit packaged: `8de54e1e942839d1e09c203281e7ca56477dd680` (the final timing clean-up code is in parent `b2d001aba990c95f0b3d80370a3558ed8e931af5`; version tuple is `0.21.4`).
- QSS Python push workflow run: `43576192956`, job `132390846731`, success. Python compilation passed; **239 standalone tests passed**; package assembly and artifact upload passed.
- QSS PR workflow on the latest handoff commit `a0508d3`: run `43576198933`, success. Companion converter GUI PR workflow also passed; it validates the separate converter tool, not Blender runtime behavior.
- Installer: `Quake-Surface-Studio-v0.21.4-Blender-Install`, artifact ID `14106388181`, 269,450 bytes, 48 ZIP entries, expires 2027-02-12.
- SHA-256: `54b68d04cc522203e43f77a1d511b14704c8e893078db37c98509c6ee71f5698`.
- Downloaded ZIP was tested: no corrupt member; correct `quake_surface_studio/__init__.py` package root; `bake_stats.py` and `tests/test_bake_stats.py` are present.
- GitHub artifact page: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43576192956/artifacts/14106388181
- Blender 5.3 runtime retest of the new timing display is still user-side. The reported 0.21.3 Bake/selection/nodraw runtime feedback remains as recorded above.


## User feedback and next milestone — 2026-11-14

- User confirms the last E1M1 Cycles bake took roughly 5–7 minutes; an older build reportedly baked E1M1 in about 90 seconds. These are user-observed approximate times, not controlled benchmarks.
- User could not find the new duration statistic. Root cause: 0.21.4 added timings to the completion report and Save Lighting Diagnostics text, but not the persistent STATS panel. Corrected in 0.21.5: Lighting > STATS now shows last successful total duration and Cycles operator duration directly after baking.
- User's next main priority is BSP inline brush-model support. Bake optimization is welcome if a concrete bottleneck is identified, but must not reduce bake quality/settings or risk the inline-model milestone.
- 0.21.5 parses BSP29 `dmodel_t` (64-byte) records, validates face ownership ranges, maps each face to a model ID, and resolves entity `model "*n"` references.
- Inline-model face geometry is transformed by the referenced entity's compiled `origin` and explicit three-component `angles` for display. A combined map mesh is retained to minimize disruption to current editing, lighting and export paths. Original model-local coordinates remain used for texture UVs/lightmap atlas creation; model metadata is stored so lightmap resolution rebuild can invert the entity transform.
- Important Quake distinction: `angle` (singular) on movers commonly specifies travel direction, not initial model orientation. Do not apply it as a brush geometry rotation. Only explicit three-component `angles` is applied as initial orientation.
- Current scope corrects initial placement/rotation for imported inline-model faces, but does not yet split each inline model into a separately selectable Blender object, simulate mover travel, or implement full entity-specific animation. Validate against real `func_door`, `func_plat`, `func_train`, and rotating-brush BSP samples, including maps with and without origin brushes.
- Bake timing now appears persistently in the Lighting section of STATS; users should capture total and Cycles durations on E1M1 for future comparison. No bake settings or quality were changed.


### SLOPGATE 0.21.5 verified build

- Implementation commit: `8666f7bdec483fc5aa5815f1d201ebcb31672a83`.
- QSS Python workflow: run `43579048637`, success. Python compilation passed, **246 standalone tests passed**, package folder assembled, installer artifact uploaded.
- Installer artifact: `Quake-Surface-Studio-v0.21.5-Blender-Install`, artifact ID `14107855128`, 272,694 bytes, SHA-256 `c21addb5b7045efcb2cff0210be507f98bfa4cf9b151be0628761bb349d22184`, expires 2027-02-12.
- Downloaded archive was checked with `unzip -t`; no corrupt members.
- No Blender 5.3 interactive runtime verification has been performed for the new inline-model placement or visible timing panel. User validation remains required, especially for maps containing origin-brush doors/platforms, rotated brush models, and lightmap-resolution rebuilds.
- Next work should add targeted fixture/sample-map validation for `func_door`, `func_plat`, `func_train`, and `func_rotating`; then consider separating inline models into independently selectable objects only if the combined-mesh workflow proves insufficient.


### 0.21.6 — bake timing visibility correction

- The user could not find the 0.21.5 timing display because it was placed in the default-collapsed STATS panel. Moved it directly below **Bake Lightmap** in the always-visible Lighting panel, where it shows total and Cycles duration.
- No bake behavior or quality settings changed. 0.21.6 supersedes the 0.21.5 installer for testing.


### SLOPGATE 0.21.6 verified installer

- Source/version commit: `20f1ecc368a7ef3a5a1e21826a35a0d48c60734a` (add-on version 0.21.6).
- QSS Python workflow run: `43579167842`, job `132399985935`, success. Python compilation passed; **246 standalone tests passed**; package assembly and artifact upload passed.
- Final user-facing installer: `Quake-Surface-Studio-v0.21.6-Blender-Install`, artifact ID `14107519044`, 272,682 bytes, SHA-256 `2624bdfa340ddb4f77c364c307978f57e10e0110964a34b9f465b079c4c58da4`, expires 2027-02-12.
- Downloaded archive passed `unzip -t` with no corrupt members.
- Timing display is now directly below the Bake Lightmap button in the Lighting panel, not in the collapsed STATS accordion.
- The inline brush-model geometry placement pass is included in 0.21.6. It retains one combined map mesh; this does not yet provide independently selectable animated mover objects. User runtime validation in Blender 5.3 is required before treating placement as fully verified.


### 0.21.7 — bake workload telemetry

- Adds effective Cycles sample count, device, diffuse bounce count, lightmap atlas size, and receiver-face count to the visible last-bake box and diagnostics report.
- Records both successful and attempted bake workload where possible. This is intended to distinguish a Cycles-time regression from a change in workload or SLOPGATE setup overhead.
- No sample count, bounce, device, or other bake quality/performance setting is changed by this telemetry.
- Source-level observation: the current bake path enforces a minimum of 96 Cycles samples (`scene.cycles.samples = max(96, old_cycles['samples'])`). This could be relevant to the reported time difference if older builds used fewer samples, but there is no verified historical settings comparison. Do not lower it without a quality comparison and user approval.


### SLOPGATE 0.21.7 verified installer — current recommended test build

- Source/version commit: `6010fc0c93a6077f51f3c7a9ae36f01b9eed8970` (version 0.21.7).
- QSS Python workflow: run `43579307417`, job `132400401974`, success. Python compilation passed; **246 standalone tests passed**; package assembly and artifact upload passed.
- Installer artifact: `Quake-Surface-Studio-v0.21.7-Blender-Install`, artifact ID `14107189855`, 273,039 bytes, SHA-256 `229ce48691919e3c5004c2b239460961a7c60f32b499fb2b85ec9653bc037dd3`, expires 2027-02-12.
- Downloaded archive passed `unzip -t`; source checks confirm version 0.21.7, visible LAST BAKE panel, workload telemetry, BSP face-model metadata, inline transforms, and inverse lightmap rebuild transform are included.
- User should use 0.21.7 rather than 0.21.5/0.21.6 for the next Blender 5.3 test.


### User feedback and 0.21.8 implementation — 2026-11-14

- User confirms bake timing is now visible, but requests it be placed inside the existing STATS panel rather than in a separate box. 0.21.8 removes the standalone LAST BAKE box and adds last total, Cycles operator duration and workload summary under TEXTURES & LIGHTING in STATS.
- User asks why statistics cannot be selected/copied. Added **Copy Stats to Clipboard** under EXPORT & DIAGNOSTICS. It copies the same full plain-text report built for Save Lighting Diagnostics, including bake timing, workload, map metadata and diagnostics. Save Lighting Diagnostics already also copies the report to Blender's clipboard, creates a Text datablock and saves a .txt file.
- User's measured latest bake: total 3m 23.6s; Cycles operator 3m 19.5s. Therefore SLOPGATE overhead outside the Cycles operator was about 4.1 seconds.
- User compared Cycles output with original ericw lighting and identified moving brush entities (doors/platforms/etc.) incorrectly occluding light. 0.21.8 introduces per-material shader variants for inline brush faces belonging to selected moving/illusionary entity classes. A Light Path node routes shadow rays to Transparent BSDF while camera/diffuse rays retain the original material shader. This is intended to stop moving brushes blocking static-world light while keeping their own visible surface shader. It does not hide geometry or disable diffuse reception.
- Entity classes currently exempt from shadow casting: func_door, func_door_rotating, func_plat, func_train, func_rotating, func_button, func_bobbing, func_pendulum, func_water, func_illusionary. Confirm this policy against Quake/ericw semantics and representative maps; do not expand it blindly.
- Imported material variants are assigned only to faces with those inline model IDs, so worldspawn geometry retains normal shadow behavior. Stats and diagnostics report the exempt face count/classes.
- Important validation still required in Blender 5.3: verify Cycles Bake honors Is Shadow Ray on the shader path; compare door/platform shadows and static receiver lightmaps with ericw output; verify mover surfaces still receive expected lighting and display normally; test shared material reuse and export behavior. If Cycles bake treats Light Path differently than expected, use object-level Cycles visibility or a bake-only scene proxy approach.
- Current build's bake timing from user: total 203.6s; Cycles 199.5s; non-Cycles overhead ~4.1s. No bake quality settings changed.


### SLOPGATE 0.21.8 verified build

- Source/version commit: `79aceaed83135a771d7690970ff66be61aa71f09`; documentation/handoff commit: `20bdd20abe6794a8db02639845d92d339587c0ab`.
- QSS Python workflow run: `43581227689`, job `132406179325`, success. Python compilation passed; **246 standalone tests passed**; add-on package assembled and installer artifact uploaded.
- Installer: `Quake-Surface-Studio-v0.21.8-Blender-Install`, artifact ID `14107953631`, 274,236 bytes, SHA-256 `72a15281c51a8bdb98bba18990f0b54b9f05d0afd42cee91b1dc10244ad6fc5c`, expires 2027-02-12. Downloaded ZIP passed `unzip -t`.
- UI changes: bake timing/workload moved to STATS; standalone LAST BAKE box removed. Copy Stats to Clipboard added in EXPORT & DIAGNOSTICS, copying the full text diagnostic report.
- Shadow policy change is source/CI verified only; Blender 5.3 runtime bake behavior has not been exercised in this environment. User must validate against a map with doors/platforms before treating the lighting correction as confirmed.


### SLOPGATE 0.21.9 — bake-time mover shadow correction

- User tested 0.21.8 and confirmed moving brush objects still block light. Reported bake: total 3m 33.2s; Cycles 3m 29s (about 4.2s overhead).
- Root cause in source: the bake operator temporarily replaces every material Surface with a plain Diffuse BSDF. This bypasses the persistent inline mover material's Light Path -> Mix Shader -> Transparent shadow-ray branch. Thus 0.21.8's display material graph could not affect the actual bake.
- 0.21.9 updates the temporary bake material override. For materials tagged `qss_inline_model_no_shadow`, the temporary bake surface is now a Mix Shader: Light Path Is Shadow Ray selects Transparent BSDF; all other rays use the temporary white Diffuse BSDF. This keeps the mover's own surface available to receive diffuse lighting while preventing it from occluding shadow rays during the bake.
- Nodraw remains fully transparent under the existing policy; blocklight/NODRAW_BLOCKER behavior remains opaque; normal world materials continue using the standard diffuse bake override.
- Temporary Light Path, Transparent, Mix and Diffuse nodes are tracked per material and removed in the bake `finally` cleanup; the original Surface links are restored.
- Records count of mover-tagged materials that received the bake-time shadow override in object stats/diagnostics.
- Blender documentation confirms Light Path exposes Is Shadow Ray in Cycles; transparent shader pass-through is a supported shader behavior. References: Blender 5.3 Light Path manual and Cycles baking manual. Runtime verification in Blender 5.3 remains necessary.
- Next user validation: bake a map with func_door/func_plat/func_train entities and compare static world light behind them to ericw. Confirm movers themselves still receive light and their display materials are restored after bake.


### SLOPGATE 0.21.9 verified installer

- Source/version commit: `30fb6629ef83093cb9d9d6db1cd0d3de879a9d73`; 0.21.9 add-on version and README documented.
- QSS Python workflow run `43582521377`, job `132410082968`: success. Python compilation passed; **246 standalone tests passed**; package assembled and artifact uploaded.
- Installer: `Quake-Surface-Studio-v0.21.9-Blender-Install`, artifact ID `14109270675`, 274,686 bytes, SHA-256 `2c360b775700d67536b317def32c06d62185c9ea28675b4f91372cf308c7f1a2`, expires 2027-02-12. Downloaded ZIP passed `unzip -t`.
- Runtime Cycles Bake behavior is not verifiable in CI; user's Blender 5.3 test remains the acceptance criterion.


### User runtime confirmation — mover lighting fixed (2026-11-14)

- User tested SLOPGATE 0.21.9 in Blender 5.3 and confirms: **lighting on movable objects now works**. This validates the bake-time Light Path / Transparent shadow-ray override for the tested map.
- Latest bake: total **3m 34.0s**; Cycles **3m 30.0s**; non-Cycles overhead approximately **4.0s**. Compared with prior 0.21.9 test (3m 33.2s / 3m 30s), bake time is effectively unchanged. No evidence of a new performance regression from the shader correction.
- Treat mover lighting as user-verified for the tested case, not as universal coverage of every Quake mover classname or map setup.
- Next release-readiness work should prioritize: (1) inline-model/entity fixture coverage and independent object semantics/transform edge cases; (2) audit shadow-casting policy by classname and compare representative maps to ericw; (3) BSP2/2PSB support if included in 1.0 scope; (4) lighting-fidelity gap documentation/tests (radiosity/bounce, dirt, surface emitters, sky/sun, deviance/area sampling, lightstyles); (5) lightmap edge bleed and receiver-only bake efficiency; (6) clean install/upgrade, supported Blender-version matrix, and regression suite on representative maps. Do not make all compiler-fidelity features a hard 1.0 blocker unless the project explicitly promises ericw parity.


---

## 1.0 release-candidate scope and priorities — confirmed 2026-11-14

### Release scope

- User confirms **classic Quake 1 BSP29 only** for SLOPGATE 1.0 / 1.0 RC.
- BSP2 and 2PSB, plus broader engine/BSP variants, are a core post-1.0 expansion track. Do not hold 1.0 RC for those formats.
- The user considers lighting fidelity, workflow/usability, and reliable undo/redo important RC concerns; these must not be demoted to vague future polish.
- Full bit-identical ericw feature parity is not promised for 1.0 unless the scope is explicitly changed. Core results must nevertheless be visually dependable and known limitations documented.

### User-confirmed runtime status

- Blender 5.3: affected-face selection works; Cycles bake works; trigger/clip faces are no longer visible in the intended workflow.
- SLOPGATE 0.21.9: movable-object lighting now works for tested doors/platforms. User confirms the fix.
- Secret doors still do not get the same behavior. The user confirms inline model placement/entity handling works for ordinary doors/platforms; do not misrepresent this as a general failure of inline model placement. Treat secret doors as the remaining entity-policy coverage issue.
- Latest bake timings reported by the user: total 3m 34s; Cycles 3m 30s. Prior measurements are roughly the same; non-Cycles overhead is about 4 seconds. The main speed opportunity is inside Cycles, not Python setup.
- User reports preview modes are still too bright compared with the reasonably accurate bake.
- User reports blur/visible edge artifacts between some lightmapped faces.
- Reliable undo and redo across editing workflows is a major usability priority.
- The user asked whether Texture Paint has layers; clarify native Blender capability and SLOPGATE's current source/painted behavior (see below).

### Important ericw-tools discovery: brush-model shadow rules are entity-key based, not classname based

This supersedes the earlier SLOPGATE plan to keep growing a hard-coded list of exempt classnames.

- ericw 'light' reads the entity definitions contained in the compiled BSP and computes light/shadow information from them. It does not consult an FGD at lighting time.
- The relevant keys apply to **any entity with a brush model**:
  - '_shadow': when 1, the bmodel casts shadows on other models and itself.
  - '_shadowself' / '_selfshadow': self-shadow only.
  - '_shadowworldonly': shadow the world only, not other bmodels.
  - '_switchableshadow': dynamic/switchable shadow behavior with assigned lightstyle metadata.
  - The documented default for these keys is 0.
- ericw source confirms the actual rule: the world model is always included as an occluder; an inline model is only added to the solid/filter shadow geometry if one of 'shadow', 'shadowself', 'shadowworldonly', or 'switchableshadow' is enabled. The ray filter further distinguishes world-only and self-only blocking. Default inline bmodels therefore receive light but do not block other lighting rays.
- This is why a custom mod classname needs no special compiler registration. If QBSP emits a proper inline model (model "*n") and its entity lump contains '_shadow' keys, ericw reads the key generically. An FGD can expose/document the property to TrenchBroom or another editor, but the FGD is not the mechanism the light compiler uses.
- SLOPGATE 0.21.9 currently selects non-shadow material variants using a classname whitelist (func_door, func_plat, etc.). The missing secret-door class is a likely reason that the secret door is still an occluder. Do not add one classname as another special case.
- Next implementation: resolve the face's inline-model ID to its BSP entity and apply a generic, key-driven shadow policy. Default brush models should not cast shadows; '_shadow' enables all-model blocking; '_shadowself', '_shadowworldonly', and '_switchableshadow' need their documented relationship/style semantics. 'func_detail'/'func_group' compiler merging and texture-level no-shadow flags need separate handling where applicable.
- Caution: the current single combined Blender mesh plus per-face material shader cannot fully express all ericw source-vs-hit model distinctions ('_shadowself' and '_shadowworldonly', in particular). Evaluate separate model objects or bake-only ray-visibility proxies for exact behavior. Preserve the current working behavior while introducing this policy; compare against ericw's own test maps.
- Source references:
  - ericw light model entity keys: https://ericw-tools.readthedocs.io/en/latest/light.html#model-entity-keys
  - ericw QBSP compiler-internal bmodels: https://ericw-tools.readthedocs.io/en/latest/qbsp.html
  - ericw shadow model setup: https://github.com/ericwa/ericw-tools/blob/master/include/light/light.hh#L203-L260
  - ericw per-model occluder construction and ray filtering: https://github.com/ericwa/ericw-tools/blob/master/light/trace_embree.cc#L304-L350 and https://github.com/ericwa/ericw-tools/blob/master/light/trace_embree.cc#L597-L692
  - ericw regression map with '_shadow', '_shadowself' and '_shadowworldonly': https://github.com/ericwa/ericw-tools/blob/master/testmaps/deprecated/shadowself_shadow.map

### 1.0 RC work packages, in implementation order

1. **Generic inline-bmodel shadow policy (highest priority).** Remove classname-only behavior in favor of ericw-compatible entity model keys. Verify ordinary doors/platforms, secret doors, a custom mod-defined brush entity, 'func_wall' with '_shadow 1', self-only/world-only shadows, and switchable-shadow behavior or a documented limitation.
2. **Lighting preview fidelity.** Preview modes currently use separate paths: Original/Baked material preview multiplies albedo by a lightmap through a Principled emission input; Eevee/Cycles Live previews use native Blender lights with converted energy/falloff approximations. The latter is intentionally not the same solver as the bake. Measure each path separately against the same BSP faces and bake; fix brightness/color-space/energy calibration without changing the accurate bake.
3. **Lightmap seam/edge quality.** Investigate the reported blur and visible face boundaries. Audit atlas packing, gutter width, bake margin dilation, UV texel-center alignment, image interpolation, and resampling. Add a representative multi-face test map; verify after import, bake, painting, save/reopen, and BSP export. Keep atlas islands isolated and prevent black/neighbor-face bleed.
4. **Reliable undo/redo.** Define a project-level edit transaction/history for destructive or stateful SLOPGATE operations (face detach/paint prep, image/UV/material changes, light edits/sync, bake/restore, resolution changes and export-side state). Ensure Ctrl+Z/Ctrl+Shift+Z or explicit SLOPGATE actions restore image pixels, UVs, material slots, metadata, source snapshots and light/scene state coherently. Existing **Undo Last Bake** is only a one-step bake snapshot, not comprehensive project undo. Preserve recoverability after failed operations and test save/reopen.
5. **Bake performance.** Continue profiling because Cycles is ~98% of measured wall time. Benchmark fixed maps and workloads (samples, device, atlas size, receiver faces/material count/lights) and optimize a demonstrated bottleneck. Do not silently lower samples, bounce counts or image quality to meet a speed target. Compare visual error against the same ericw reference.
6. **Release hardening.** Keep BSP29 as the only 1.0 target; exercise representative maps and mod content; test import/export round trips, texture/WAD workflow, lightmaps, custom entity keys, installation/upgrades and save/reopen in Blender 5.3; document unsupported ericw features; then freeze features and build the 1.0 RC package.

Post-1.0: BSP2/2PSB support, expanded BSP dialect compatibility and any format-specific conversion/recovery work.

### Blender Texture Paint layers — current understanding

- Blender 5.3's built-in Texture Paint is image-based. A UV texture is an image; each UV texture has one image. A mesh may have multiple UV texture maps/images, but that is not a Photoshop-style non-destructive layer stack.
- Blender 5.3 release notes mention improved Texture Paint Undo/Redo performance for high-resolution images and UDIMs; ordinary paint strokes should use Blender's native undo/redo.
- SLOPGATE currently provides source-vs-painted toggles rather than a stack of named, independently blendable paint layers:
  - Texture painting detaches selected BSP faces into face-local paint images/materials and preserves original material/UV data for toggling.
  - Original and Baked lightmaps use separate painted image copies as overrides.
  - These are reversible source/painted states, not multiple paint layers with opacity/blend modes and per-layer visibility.
- A future SLOPGATE layer stack would require explicit image layers and a compositor/material-node composite, with a deterministic merged result for BSP/WAD export. Treat this as a distinct feature request; do not confuse multiple UV maps or paint slots with a true layer stack.
- Blender 5.3 references:
  - Texture Paint introduction: https://docs.blender.org/manual/en/5.3/sculpt_paint/texture_paint/introduction.html
  - Blender 5.3 Texture Paint Undo/Redo release note: https://developer.blender.org/docs/release_notes/5.3/sculpt/


---

## SLOPGATE 0.21.10 implementation pass — 2026-11-14

### Changes made on the active development branch

- Bumped add-on version to 0.21.10.
- Replaced the importer's classname-only inline brush shadow exemption with bsp.inline_model_shadow_policy(entity), resolved from each compiled BSP entity's model "*n" reference. All inline brush models now default to non-shadow-casting regardless of classname; _shadow 1 opts into full shadow casting and _shadow -1 disables it. This should cover custom secret-door classnames.
- _shadowself, _shadowworldonly, and _switchableshadow are detected and reported as special policy values, but currently fall back conservatively to no shadow. Exact semantics need source-model/hit-model-aware ray filtering and are not claimed as implemented.
- Fixed inverse inline-model transforms so a scalar angle is ignored as initial rotation, matching the forward transform and Quake's meaning of scalar angle as mover travel direction. Three-component angles still controls initial rotation.
- Undo boundary audit found a likely contributor to the user's erratic Ctrl+Z: QSS_OT_quake_direct_bake had UNDO while it writes pixels directly with image.pixels.foreach_set(). Blender's global operator undo does not reliably snapshot such Python image-buffer mutations. Removed global UNDO from that operation; keep explicit pre-bake image snapshots/Undo Last Bake as the image recovery mechanism.
- Also removed global UNDO from QSS_OT_activate_lightmap_paint: it is a mode/paint-target transition and should not create an unrelated global undo step that competes with Texture Paint's native stroke history.
- Added Blender global undo to reversible scene/material/mesh toggles (toggle_textures, toggle_source_lightmaps, toggle_painted_textures, toggle_painted_lightmaps) and confirmed map close, which changes scene datablocks/visibility.
- Added static undo-contract tests plus BSP unit tests for custom classname default shadow policy, _shadow 1/-1, special shadow keys and scalar angle semantics.
- README and version updated to 0.21.10.

### Build verification

- GitHub Actions QSS Python tests run: 43587762733, commit b9986cdcc8b088bf75de4b3e1c176af546843874; success.
- Test count: **253 passed** in 2.739 seconds.
- Installer artifact: Quake-Surface-Studio-v0.21.10-Blender-Install, artifact ID 14110794745, 277,401 bytes, SHA-256 67b55f9d86d618014ed8140dbba5e7ae6b005d0b0e444902da0b290e36a55aba; ZIP integrity checked successfully. Runtime Blender behavior is not covered by CI.

### 1.0 RC work estimates (engineering time, not elapsed calendar time)

1. **Ctrl+Z/redo consistency — 5–10 engineering days for audit + first complete pass; 2–4 weeks if image/paint operations need a true transaction/snapshot architecture.** Current 0.21.10 patch removes two unsafe undo pushes and adds undo to reversible scene toggles. Still need Blender 5.3 interaction tests for: face detach, entering/exiting both paint modes, texture paint strokes, lightmap paint strokes, undo/redo after a stroke, bake/Undo Last Bake, restore source lightmap, toggles, map close/reopen and save/reopen. Define which operations are true edits versus mode/context transitions. Never add UNDO indiscriminately to direct pixel-buffer writers.
2. **Preview brightness calibration — 3–6 days.** Source/Baked preview is a material emission multiplication of albedo and lightmap; Eevee/Cycles live preview uses separate approximate scene lights. Capture matched material/light samples from one test map, separate color-management vs light-energy causes, calibrate each preview path independently, and add regression measurements. User needs to validate the result visually.
3. **Lightmap seam/blur defect — 4–8 days for diagnosis and likely fix, potentially 2 weeks if UV/atlas/export assumptions are involved.** Existing atlas uses 2-pixel gutters, closest interpolation, centered luxel UVs and Cycles EXTEND margin. Do not increase blur/margin blindly. Reproduce with a map showing adjacent face edges; inspect UVs, atlas pixels and exported per-face samples at 1x/2x/4x resolution. Test import, bake, paint, save/reopen and BSP export.
4. **Cycles bake performance — 3–5 days profiling, then 5–10 days for a demonstrated optimization.** Cycles is about 98% of reported time (3m30 of 3m34). Benchmark controlled map/device/sample/atlas/material/lights cases, measure bake stage and GPU/CPU utilization. Current bake enforces at least 96 samples and 2 default diffuse bounces. Do not reduce quality silently; expose any speed/quality tradeoff.
5. **Generic brush shadow policy — 2–4 days to finish default and _shadow 1/-1 behavior plus map validation; another 5–10 days for exact _shadowself, _shadowworldonly, _switchableshadow.** 0.21.10 now handles any inline model classname for the common default and full-shadow cases. Special modes require model-aware ray filters or bake-only visibility proxies; switchable shadows also require style/channel semantics.
6. **Lighting fidelity gap audit — 5–10 days to inventory/compare and document; feature additions depend on chosen scope.** Build controlled ericw reference maps for direct falloff, sky/sun, colored light, light styles, minlight, dirt, bounce, surface emitters, two-sided surfaces and texture policies. Prioritize issues that materially change ordinary BSP29 maps. Full ericw parity is not a 1.0 promise.
7. **Regression map suite and release hardening — 5–8 days.** Maintain a small deterministic BSP29 fixture plus representative real maps, verify import/export round trips, texture/WAD behavior, face metadata, inline entities, lightmap preservation, clean install/upgrade and Blender 5.3 save/reopen. Prepare known-limitations docs, release notes and rollback package.

### Recommended critical path

- First user test of 0.21.10: secret door default shadow behavior, explicit _shadow 1, ordinary doors/platforms, and Ctrl+Z/redo sequences involving paint-mode entry, painting strokes, detaching faces and toggles.
- Then fix any reproduced undo inconsistency before broadening other work.
- In parallel, reproduce the preview brightness and seam issues with a shared test map and exact screenshots/diagnostics.
- Profile Cycles only after a repeatable baseline and quality metric exist.
- Complete special shadow modes only to the degree required for real BSP29 mod compatibility; document any unsupported special keys.
- 1.0 RC remains classic Quake 1 BSP29 only. BSP2/2PSB and other dialects remain post-1.0.
