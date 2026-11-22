# SLOPGATE — AI Project Handoff

**Last reviewed:** 2026-11-19  
**Purpose:** A compact, maintained project and collaboration brief for future assistant sessions. This is an editorial summary, not a verbatim record.

## Read this first

At the start of a new project session, read this file first. Then consult the main conversation archive, ai chat history/Slipgate_Chat_History_Clean.md, whenever a detail needs context, dialogue-level confirmation, technical evidence, or fact-checking. The user reconstructed the missing continuation of that archive; it now contains the November 14–16 work through the e1m1 NaN-bake diagnosis and the subsequent bake-sample validation ordering regression/fix.

This brief deliberately compresses the archive. It can become stale. The live repository, current branch, test output and the main archive outrank assumptions in this summary. Always inspect the current branch head and relevant source before modifying code. In particular, distinguish the base development PR from the stacked lightmap work branches and the separate BSP-import diagnostic branch.

The archive filename and some historic headings contain the old spelling “Slipgate”. That is historical. The current product name is **SLOPGATE**. Do not rename or rewrite historic transcript material merely to normalize the old spelling.



# 1.0 MASTER ROADMAP — PROJECT NORTH STAR

**This is the governing development plan. Read this section before starting new feature work.** When an older note, historical transcript, README paragraph or previous experiment conflicts with this roadmap, follow the latest user decision and this section. Keep this roadmap current as priorities are completed or changed.

## Product direction

SLOPGATE is a Blender-based **compiled Quake map surface, texture and lighting editor** for modern Quake mapping. The primary engine targets are **Ironwail** and the **Nightdive rerelease**.

- **Modern core format:** BSP2 is the intended primary import/export target.
- **Legacy core format:** BSP29 remains an optional compatibility import/export path.
- **Extensions:** BSPX lighting and other optional lumps are independent of the core BSP version.
- **Not the product goal:** SLOPGATE is not intended to become a complete brush-based MAP editor or an integrated QBSP/VIS/light compiler for 1.0.

The user has compiled E1M1 with ericw-tools qbsp -bsp2 and confirmed that the Nightdive rerelease loads it. Treat BSP2 core acceptance in that engine as user-verified. Do **not** infer from that test that every BSPX lighting lump works in KEX; verify extensions individually.

## Roadmap — follow this order

### PHASE 1 — Close the current 0.21.24 acceptance loop
**Status: FOLLOW-UP FIX COMMITTED · CI AND BLENDER 5.3 / IRONWAIL ACCEPTANCE PENDING**

Source-side review completed 2026-11-19 against production source HEAD `d27e7be286829a019badb556b6c4c30c0c4c2eb4` (add-on version 0.21.24).

Verified in source:
- `_build_enhanced_lightmap_payload()` constructs `face_info` locally for each face before the world-chart sampling branch reads it. The previous reported `name 'face_info' is not defined` failure has a dedicated AST regression test in `tests/test_export_contracts.py::test_world_chart_face_context_is_defined_before_it_is_used`.
- `_qss_prepare_companion_map_export()` checks the raw linked MAP path before calling `abspath()`. An empty path returns `None`, avoiding the erroneous `/app/blender` resolution. A missing/changed/unwritable linked MAP is caught as a sidecar warning.
- `QSS_OT_export_bsp.execute()` runs BSP export independently of MAP preparation/commit. A companion MAP problem is reported as “BSP export succeeded” rather than aborting the BSP write.
- Enhanced export builds `DECOUPLED_LM`, `LMSTYLE` and `RGBLIGHTING`; retains classic LIGHTING samples for engines that ignore BSPX; the audit path runs `export_validation.validate_export_pair()`.
- `__init__.py` reports version **0.21.24**.

Follow-up investigation after the user clarified that this E1M1 copy never had a companion MAP:

- The exact reported path `/app/blender` is not a MAP filename. The prior empty-string guard did not cover this case because the Blender object contained a non-empty invalid value.
- Import discovery only assigns `qss_source_map_path` when `map_sync.find_companion_map()` finds an actual same-basename MAP, or when the user explicitly supplies a source MAP. Therefore the likely issue is stale/invalid Blender object metadata or an import path that left a non-MAP value behind; it is not evidence that E1M1 needs a MAP file.
- Production fix committed on `fix/0.21.17-world-aligned-lightmap-charts`: `7a5d92a40a19776f8affb4ad44222ed04aa2c381`. Before resolving a linked path, export now checks that it has a `.map` extension. A non-MAP value is cleared from the object (including its stored hash), status becomes `NO_COMPANION`, and BSP export proceeds without a MAP warning. A genuine missing path ending in `.map` still warns, so real stale links are not silently discarded.
- Regression test added: `test_non_map_directory_metadata_is_ignored_as_no_companion`; test commit `037fb6277598e0ecbbf2b73c962ef0214e2a0c25`.
- CI for these new commits has not yet been confirmed. The combined commit status endpoint returned no checks; do not infer a pass.
- The earlier 0.21.24 artifact predates this fix. A new installer must be produced from the updated source before the user retests.

Automated evidence:
- GitHub Actions run `44232978822` completed successfully on source HEAD above. All workflow steps passed: Python compilation, standalone unittest discovery, add-on folder assembly and artifact upload.
- Artifact: `Quake-Surface-Studio-v0.21.24-Blender-Install`, ID `14396470461`, SHA-256 `8a4c4dec82249f9382d5dddbc9bbe2b430144f39f2ecd88a80aebdb2bf30ab8b`.
- Important caveat: this is a Python 3.12 CI run. It does not execute Blender's `bpy` export operator, validate Blender 5.3 file-dialog state, or load the result in Ironwail.
- The workflow run's display title is stale and says 0.21.18; the actual checked-out HEAD and `__init__.py` version are the authoritative 0.21.24 values.

**Runtime acceptance still outstanding.** Do not mark Phase 1 complete until the user confirms the following on Blender 5.3 and Ironwail:

1. Install the 0.21.24 artifact above (ensure Blender is not loading an older duplicate add-on copy).
2. Use a fresh import of the original, unrecompiled E1M1 BSP in a test directory. For the no-companion-MAP case, keep the BSP in a directory without a same-basename `.map`; no decompiled MAP is required.
3. Keep the imported BSP object active and in Object Mode. Export explicitly as **Enhanced BSPX** to a new filename, e.g. `e1m1_phase1_enhanced.bsp`. Do not rely on AUTO or the BOTH option for the first test.
4. Expected result: export operator returns FINISHED; no `/app/blender` MAP error; no `face_info` NameError; Enhanced BSP is written. If source RGB lighting is available, expect the corresponding `.lit` sidecar as well.
5. Run **Validate BSP Export** against the original E1M1 BSP and the new Enhanced BSP (select the generated `.lit` if prompted). Require PASS.
6. Load the exact generated Enhanced BSP in Ironwail. Confirm the map opens and inspect the player-start area / lightmap edges. Record the exact filename opened.
7. Repeat with a linked companion MAP only if MAP synchronization itself is being tested; confirm that the output MAP is created/updated safely and that BSP export still succeeds if the MAP is absent or invalid.

Report back with: Blender version; add-on version shown in Blender; export mode; exact operator message; whether BSP and `.lit` exist; validator report; Ironwail version and whether the exact file loads; any traceback. If it fails, preserve the complete traceback and do not overwrite the source BSP.

**Phase 1 exit condition:** explicit Enhanced export passes in Blender 5.3, QSS structural validation passes, and that exact exported file loads in Ironwail. Only then start Phase 2 BSP2 parser/import work. If a step fails, fix that concrete defect first.

### PHASE 2 — BSP2 foundation
**Status: NOT STARTED · largest architectural blocker**

- Design a format-neutral internal BSP representation.
- Separate BSP29 and BSP2 record readers/writers into explicit adapters.
- Implement BSP2 parsing and structural/reference validation first.
- Preserve entities, geometry, visibility, nodes, leaves, clipnodes, models, textures and unknown supported lumps.
- Build fixtures from the user's qbsp -bsp2 E1M1 and at least one larger BSP2 map.
- Test parsing, inspection, round-trip serialization and failure handling before connecting the full Blender UI.
- Do not implement BSP2 by changing only the version field. BSP2 changes record layouts and field widths.
- Do not add 2PSB/RMQ unless a concrete user/engine requirement appears.

### PHASE 3 — BSP2 export and lossless editing
**Status: NOT STARTED · depends on Phase 2**

- Add BSP2-aware export for existing supported edits: texture changes, face material/texinfo references and lightmap data.
- Preserve unchanged source lumps and unknown supported BSPX payloads.
- Validate every rewritten reference, index, offset, length and bounds field.
- Add round-trip and edit/export/re-import tests using real BSP2 fixtures.
- Keep BSP29 behind the same core-format abstraction as an optional legacy path.

### PHASE 4 — BSPX lighting compatibility on both target engines
**Status: NOT STARTED AS A BSP2 WORKFLOW**

Keep two separate questions in code and UI:
1. Which **core BSP format** is being read/written? BSP2 or BSP29.
2. Which **lighting extensions** are included? Standard lightmaps or supported BSPX data.

Build a per-engine test matrix for Ironwail and Nightdive KEX. Verify each required extension independently:
- RGBLIGHTING
- DECOUPLED_LM
- LMSHIFT / LMOFFSET variants
- LMSTYLE and LMSTYLE16
- QLIT v1 .lit sidecar behavior
- SLPG_LMPAD, the SLOPGATE edge-support marker (verify its consumer/semantics; never assume an engine acts on it).

The current parser supports only some layouts. LMSTYLE16, legacy LMSHIFT/LMOFFSET without DECOUPLED_LM, and LIGHTING_E5BGR9 are documented limitations. Decide explicitly what 1.0 supports; unsupported variants must be rejected with an actionable message, not silently misread.

### PHASE 5 — Lighting fidelity and map workflow quality
**Status: PARTIALLY IMPLEMENTED · requires deliberate scope decisions**

- Preserve the original compiler lightmap as a reference and make every export's selected lighting source (source vs baked) explicit and diagnosable.
- Compare local/spatial luxel distributions, not only global averages. E1M1's diagnostic source mean (0.2947401) and final atlas mean (0.2950881) differ by only about 0.12%, while the maximum sampled luxel is 202.4476. A global mean match is not spatial fidelity.
- Keep Original, Quake Direct Solver, Cycles preview and Cycles bake clearly distinguished in UI and docs.
- State which compiler semantics are supported. The direct solver currently supports documented static delay 0–5, but does not reproduce the entire ericw compiler: radiosity/bounce, dirt, deviance/area sampling, surface emitters, sky/sun sampling, projected texture lights, full compiler visibility behavior and animated lightstyle curves/minlight behavior are incomplete or approximated.
- Cycles correction graphs currently cover delay 0 and delay 5; other delays use native fallback. Eevee is an approximation. Do not promise compiler-identical lighting.
- Decide whether 1.0 needs animated style preview/export. Current static handling composites styles at full weight and flattens output to style 0.
- Complete or explicitly scope companion MAP editing. Current sync updates a subset of existing light properties; target/mangle direction and creating new MAP light entities are not implemented.
- Improve true partial-bake performance only when it can be measured. Current face scopes protect atlas pixels but Cycles still evaluates the full BSP; selected-light masks are approximations.

### PHASE 6 — Stabilization, documentation and 1.0 release
**Status: NOT STARTED**

- Declare supported Blender versions and OS combinations.
- Run real Blender tests: install/upgrade/re-enable, multiple maps, save/reopen, texture paint, detachment, palette conversion, lightmap paint, bake, undo/restore, export/cancel/error recovery.
- Run repeatable engine regression maps in both Ironwail and Nightdive KEX, including a larger BSP2 map and each supported BSPX lighting layout.
- Verify no silent data loss in import/edit/export/re-import.
- Update onboarding, format matrix, known limitations, troubleshooting and recovery documentation.
- Synchronize the tested production source into default main (currently still v0.11.0), close/archive obsolete development branches and old PRs, tag the release, and publish one authoritative installer.

## 1.0 definition of done

Do not call SLOPGATE 1.0 until all are true:

1. BSP2 is the primary supported import/export format; BSP29 remains an optional legacy path.
2. Supported BSPX lighting layouts are verified separately in Ironwail and Nightdive KEX; unsupported layouts are clearly rejected/documented.
3. Round-trip tests show no unintended loss of geometry, entities, visibility/collision data, textures, lightmaps or preserved unknown extensions.
4. Texture painting, face detachment, palette conversion, lightmap editing, bake, undo/restore and export pass real Blender acceptance tests.
5. Lighting has a clearly declared fidelity scope; remaining approximations are visible to users and do not masquerade as compiler-equivalent output.
6. Current export regressions (including the 0.21.24 Enhanced and companion-MAP fixes) have passed actual Blender and target-engine tests.
7. No known critical/high-severity defects remain in the supported workflow.
8. Install/upgrade/recovery documentation is complete, and version metadata, default branch, release notes and installer all identify the same 1.0 build.

## Scope guardrails — do not let 1.0 drift

Keep these outside 1.0 unless the user explicitly changes scope:
- Full brush-based MAP editing and BSP geometry/topology rebuilding.
- Running QBSP, VIS or ericw light as an integrated compiler.
- Gameplay simulation, animated mover travel or a complete Quake player collision system.
- Universal support for every historical BSP/BSPX/WAD variant.
- 2PSB/RMQ without a concrete requirement.

Current intentional limitations to carry consciously or resolve:
- Inline movers are in a combined mesh, not independent animated Blender objects.
- WAD support is limited to uncompressed WAD2 miptex data; WAD3 and compressed variants are not implemented.
- Existing Classic-era texture/texinfo and atlas limits must be reviewed during BSP2 work, not blindly inherited.
- Special shadow modes such as _shadowself, _shadowworldonly and _switchableshadow are not fully ericw-equivalent.
- Selected-face/selected-light filtering is not yet true Cycles receiver-only acceleration.

## Immediate next action

**Phase 1 source review is complete; wait for the user's Blender 5.3 / Ironwail acceptance result using the explicit test procedure in Phase 1 above.** Do not begin BSP2 implementation until Enhanced export, structural validation and target-engine loading pass. If any step fails, fix that reproducible defect first.


## Current verified baseline

- Production source: fix/0.21.17-world-aligned-lightmap-charts, commit d27e7be286829a019badb556b6c4c30c0c4c2eb4, add-on version **0.21.24**.
- Latest CI: run 44232978822, success; Python compilation, **317 standalone tests**, package assembly and artifact upload passed. This is not a Blender GUI or engine runtime test.
- Installer artifact: Quake-Surface-Studio-v0.21.24-Blender-Install, artifact 14396470461; SHA-256 8a4c4dec82249f9382d5dddbc9bbe2b430144f39f2ecd88a80aebdb2bf30ab8b.
- Installer: https://github.com/ChnuckiErdBeer/Quake-Surface-Studio/actions/runs/44232978822/artifacts/14396470461
- User reports that qbsp -bsp2 E1M1 loads in the Nightdive rerelease. This verifies the core BSP2 path in that engine, not individual BSPX extensions.
- Fourteen E1M1 comparison JPGs at info_player_start have been reviewed. Broad smooth gradients occur in both EricW and SLOPGATE Ironwail lightmaps; do not call that alone a Phong bug. A local light-distribution mismatch remains.
- Documentation branch: fix/v0.11.1-metadata-style-order-test. Default main remains v0.11.0 and must be synchronized before 1.0.
- No open GitHub issues; five historical PRs remain open and should be audited/closed or archived during release housekeeping.

---

## Project identity and purpose

- Product: **SLOPGATE**, a Blender add-on for compiled Quake map surface, texture, lightmap and lighting editing.
- Repository: https://github.com/ChnuckiErdBeer/Quake-Surface-Studio
- Primary target engines: **Ironwail** and the **Nightdive rerelease**.
- Current primary format strategy: **BSP2 core + independently selected BSPX extensions**. BSP29 remains optional legacy compatibility. 2PSB/RMQ is not in scope without a concrete need.
- User-confirmed engine fact: an E1M1 compiled with ericw-tools qbsp -bsp2 loads in the Nightdive rerelease. This verifies the BSP2 core format for the user's engine build; it does not verify every BSPX extension.
- Target interactive environment: Blender 5.3 on Linux (verify/declare the supported release matrix before 1.0).
- Package folder and internal identifiers still use quake_surface_studio / QSS for compatibility. Do not perform a partial global rename. New user-visible branding and new labels should use SLOPGATE.
- The product is a compiled-map surface/texture/lightmap editor, not a full brush-based MAP editor or integrated QBSP/VIS/light compiler.

## Historical source/build baseline — checked 2026-11-11

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

---

## SLOPGATE 0.21.11 — undo journal and lightmap gutter pass — 2026-11-14

### Implemented in source

- Version metadata synchronized to 0.21.11 in both the add-on module and Blender manifest.
- Added image_undo.py, a session-local image-pixel journal synchronized to Blender's native global undo/redo.
  - Each journaled map edit captures pre-edit and post-edit pixels for the image datablocks it mutates.
  - The map object carries an undo-state token; Blender restores that token with its normal undo state.
  - undo_post and redo_post handlers restore the matching compressed float-image snapshot only when that token changes.
  - Ordinary Texture Paint strokes and paint-mode/target transitions do not change the token, leaving native Texture Paint stroke history alone.
  - The journal is bounded to 96 states per map and cleared on add-on unregister or file load; Blender undo itself is session-local.
- Enabled one native Ctrl+Z/redo entry for Quake Direct bake, Cycles bake, Undo Last Bake, Restore Imported BSP Lightmaps and Change Lightmap Resolution. Direct image-buffer writes are restored by the journal; mesh/material/object state remains handled by Blender.
- Bake/resolution cleanup now retains old generated snapshot image datablocks as fake-user history images rather than deleting IDs that a Blender redo state may need.
- Added explicit per-face atlas gutter dilation:
  - Each lightmapped face core rectangle is identified from atlas metadata.
  - Its reserved gutter is filled from its own nearest edge luxels, including corners.
  - Adjacent face islands are never blended; overlapping expanded gutters fail closed.
  - The pass runs when the imported lightmap atlas is built and after a Cycles bake, including partial bakes.
  - Core luxel samples are unchanged, so BSP export values still come from the face interior.
- Added pure-Python regression tests for the image undo/redo journal and face-gutter dilation.

### Important limitation still under investigation

The gutter pass addresses atlas filtering/bleed inside Blender and makes per-face padding deterministic. It does not yet prove that the separate in-game edge clipping reported for engine-side lightmap blur is solved. Classic BSP29 does not expose a simple per-face padding field; any engine-side fix must preserve the exact texinfo projection and avoid inventing light from an adjacent face with a different normal, light occlusion or material. That part needs a controlled compiled map and Ironwail comparison before changing export samples.

### Verification boundary

- Standalone unit tests and Python syntax checks can verify the journal state machine and pure atlas-dilation logic.
- Actual Ctrl+Z/redo behavior with Blender 5.3 still needs GUI validation for bake, Undo Last Bake, source restore, resolution changes, detach faces, Texture Paint strokes, lightmap paint strokes, map switching and save/reopen.
- The Blender undo_post/redo_post callbacks are implemented but have not been exercised inside a running Blender process in this environment.
- The atlas gutter change needs a visual comparison at 1x, 2x and 4x resolution, plus a compiled Ironwail test for the in-game blur/crop issue.

### 0.21.11 follow-up: generated image datablocks included

- Face detachment now journals the generated face-local paint images (or packed shared atlas) as the post-state of the same Blender undo operation. The generated image datablocks are kept as fake-user images so redo can reattach and restore their contents.
- Lightmap-resolution rebuilds journal the newly generated atlas image and now treat preview-switch failures as warnings after a successful rebuild, preserving a valid undo step.
- Quake Direct bake's previous snapshot is retained, and both Direct and Cycles bake journal their newly created pre-bake snapshot image as well as the edited atlas.
- The journal now supports operations that create images as well as those that modify existing images.

### Undo-journal preservation fix

- Before every journalled operation, refresh all image snapshots already associated with the current undo token, not only the image(s) the new operation will edit. This preserves native Texture Paint changes made between SLOPGATE operations, including when the next operation edits a different image.
- Added a regression test for the sequence: SLOPGATE edit → native paint stroke → unrelated SLOPGATE edit → Ctrl+Z.

### Undo journal storage and transition model

- Image history is now stored as compressed float buffers in a temporary session directory, not retained as large Python byte strings in RAM or embedded in the .blend file.
- The journal stores operation transitions: before/after snapshots only for images changed by that operation. Undo restores the transition's before side; redo restores its after side.
- This deliberately avoids replaying stale snapshots for unrelated images. A Texture Paint stroke on texture A therefore remains intact when a later lighting operation edits image B.
- History length follows Blender's configured undo-step preference (with a safe bound); temporary snapshot files are pruned when branches are discarded, history expires, the add-on is disabled or a .blend is loaded.

## SLOPGATE 0.21.12 — undo regression runner and luxel block edge pass — 2026-11-14

- Added `tools/run_blender_undo_regression.py`, a one-command Blender integration runner. It creates disposable test datablocks and drives a real `REGISTER, UNDO` operator through Blender Undo/Redo; checks stacked operations, rollback, unrelated image edits, redo-branch invalidation, generated images, edge-block canonicalization at 1x/2x/4x, and .blend save/reopen in a child Blender process. It writes TXT and JSON reports to the system temp directory.
- The runner is compiled by CI but has **not** yet been executed inside Blender 5.3 in this development environment. Its simulated unrelated Texture Paint pixel edit checks journal isolation, not an actual mouse-driven native paint stroke.
- Added `collapse_rgba_luxel_blocks` to `bake_scope.py`. For supersampled Cycles lightmaps, each face-local luxel block is now reduced to its geometric centre sample (four-pixel bilinear centre for even block sizes) and made uniform before face-local gutter dilation. This aligns the editable preview block with the one luxel value exported to BSP and removes within-luxel raster softness. Gutter pixels and other face cores are not touched.
- The Cycles bake records the number of canonicalized luxel blocks in `qss_last_bake_luxel_blocks_canonicalized`.
- Pure-Python regression tests cover 1x/2x/4x block consistency, centre sampling, unchanged gutters, and invalid partial blocks.
- Verification: GitHub Actions QSS Python tests passed for final source commit `31e37386b6312945964c3d1bd972fb576c8fc9eb` (compileall, standalone suite, package assembly and upload). Final package artifact `Quake-Surface-Studio-v0.21.12-Blender-Install` SHA-256: `b52070532b8eeec0540dda7a6c617bf07cdbe28ce49d92707d861199a52128ef`. The Blender integration runner itself still requires execution in a real Blender UI session.
- Limitation: this pass targets softness caused by variation inside supersampled luxel blocks in the Blender lightmap atlas. It does not claim to solve engine-side face-edge clipping/bleed; verify a compiled map in Ironwail before calling that separate issue resolved.

## 2026-11-14 — Lightmap face-edge filtering work (SLOPGATE 0.21.13)

The user has paused undo/redo investigation. Do not spend further time on global
undo testing unless the user reports a reproducible issue while testing other
features.

### Findings

- The earlier `collapse_rgba_luxel_blocks` change addresses softness *inside*
  supersampled luxel blocks. It does not solve lightmap filtering at BSP face
  boundaries.
- Atlas gutters are not automatically part of a face's exported BSP lightmap
  sample rectangle.
- The classic BSP29 renderer path derives each face's lightmap extent from its
  texinfo projection. The inspected Ironwail path packs that exact per-face
  extent and has no observed `DECOUPLED_LM` handling. A separate per-face
  border cannot be represented in that classic fallback without changing
  texture mapping or requiring engine support.
- `DECOUPLED_LM` is a BSPX extension with explicit per-face dimensions and
  world-to-lightmap vectors. Engines that implement it can use independently
  expanded sample grids. The inspected ezQuake renderer applies the conventional
  half-texel offset when converting those coordinates to texture UVs.
- Support for `DECOUPLED_LM` in the user's Quake rerelease target is not
  confirmed. Do not claim that this change fixes the rerelease or Ironwail
  until the user tests the Enhanced export in the actual engines.

### 0.21.13 implementation

- Added `lightmap_export.add_half_luxel_edge_padding`. It builds a one-sample
  rim around an eligible face grid by half-luxel resampling with edge clamping,
  increases each dimension by one sample, and shifts the per-face projection origin by
  +0.5 luxel on S and T. For classic-derived records this is represented by
  moving `s_min` and `t_min` outward by half the selected luxel spacing; for
  explicit decoupled records the two vector intercepts are increased by 0.5.
- Integrated this rim only into the Enhanced `DECOUPLED_LM` sample payload.
  The vanilla BSP29 fallback remains unchanged.
- Added the `SLPG_LMPAD` BSPX marker (version byte 1) so importing and
  re-exporting an already padded SLOPGATE BSP does not repeatedly add rims.
- Faces whose width or height would exceed the per-face 256-luxel limit are
  left unchanged. The export log reports padded and skipped counts.
- Added pure-Python tests for sample interpolation, dimensions, classic and
  explicit projection offsets, maximum dimensions and invalid RGB buffers.
- Version metadata and README updated to 0.21.13.

### Required manual validation

1. Export a copy with **Enhanced** mode (not Classic) and inspect the resulting
   BSPX `DECOUPLED_LM` plus `SLPG_LMPAD` entries.
2. Compare the troublesome edge in the Quake rerelease. Confirm whether that
   engine actually consumes `DECOUPLED_LM`; if it ignores the extension, the
   classic fallback is intentionally unchanged.
3. Open the same map in Ironwail. Expect no edge-rim change from this Enhanced
   extension unless a future engine-side/format-specific path is added.
4. Check ordinary face interiors for any visible half-luxel softening and
   verify that no sample-grid overflow occurs on large faces.
5. Blender GUI baking, rerelease runtime, and Ironwail runtime have not been
   tested by the assistant.

### User runtime result — 0.21.13 edge-rim test (2026-11-15)

The user exported with BSPX and tested the map in both the Quake 2021 rerelease
and Ironwail. They reported **no visible difference**; the original face-edge
artifact remains.

Interpretation:
- This confirms the 0.21.13 half-luxel rim is not affecting either of the
  user's tested render paths.
- Ironwail source was inspected: its classic lightmap packing and drawing path
  derives each face rectangle from classic texture extents and has no
  `DECOUPLED_LM` reader. A BSPX rim is therefore ignored by this path.
- Public QuakeSpasm code documents 2021 rerelease/Q64 compatibility, but has no
  `DECOUPLED_LM` reader either. This does not prove the proprietary rerelease
  executable has identical internals; the user's no-change result is the
  direct evidence for that target.
- BSPX's DECOUPLED_LM format is documented and implemented by FTE and ezQuake.
  That offers a separate renderer in which to verify whether the SLOPGATE
  expanded dimensions/projection are read, but it does not solve the user's
  two target engines.

Do not keep adjusting the Enhanced-only border and calling it a fix. The next
candidate must affect classic BSP29 samples consumed by both renderers. Classic
BSP29 couples texture projection and lightmap extents; a data-only extra border
cannot be expressed independently the way DECOUPLED_LM can. A likely
compatibility strategy is to investigate boundary-aware blending of samples
between BSP faces that share an actual geometric edge. This could soften
discontinuities in the classic lightmap data, but risks light leaking across
true lighting/shadow boundaries and needs to be tested against the user's
actual source map before implementation.

Request the original source BSP and the exported BSPX-edited BSP, plus a
screenshot with the offending edge identified, before implementing a
map-specific or global boundary-blending algorithm. No classic-edge fix is
implemented yet.


---

## 2026-11-15 to 2026-11-16 — Reconstructed continuation: lightmap edge work, import diagnostics and 0.21.18 candidate

This section supersedes earlier assumptions that 0.21.14 was the latest work. Read the branch/PR topology carefully: 0.21.15, 0.21.16 and 0.21.18 are real synchronized candidate builds on stacked draft branches; the 0.21.14 label came from inconsistent metadata on the base branch.

### 0.21.14 candidate — four-point sub-luxel quadrature

- The previous 0.21.12 reduction collapsed a supersampled luxel block to one centre sample. That could miss a narrow spotlight when Cycles illuminated the outer quadrants of a block but not its centre.
- The candidate changes collapse_rgba_luxel_blocks() to evaluate four quarter/three-quarter sub-luxel positions, using bilinear interpolation for blocks larger than 2×, and average those values into the single classic Quake luxel. The 2× case samples all four pixels directly.
- A regression test lights only the four corners of a 4× block and expects the canonical RGB value to become 0.25. The change is included in the ancestry of the later 0.21.15–0.21.18 branch chain.
- Version warning: on the PR #1 base after commit c63205d, __init__.py says 0.21.14 but addon.py ADDON_VERSION and README say 0.21.13. The build name therefore did not represent synchronized metadata. Do not call this a clean validated release or independently increment versions.
- CI evidence on the PR #1 code commit c63205d: QSS Python run 43757220942 passed 275 standalone tests, compilation and package assembly. A separate diagnostic-branch run 43767937159 also passed 275 tests and uploaded a package named 0.21.14, artifact 14182513321 (291,988 bytes, SHA-256 9938d87922f560a050548b46d1819cf5ed0d42595c9cde5c90c17f5213dcf4c1). The metadata mismatch remains the reason not to use that as a canonical release.
- No Blender 5.3 or engine runtime validation of the quadrature has been recorded.

### BSP import failure — separate diagnostic PR #2

- User-side import of maps/spottest-compile.bsp produced: can only assign array (not "tuple") to array slice. The failing source line has not yet been identified; do not guess at an array-slice fix.
- PR #2, branch fix/0.21.15-bsp-import-array-trace, adds full traceback recording to both direct BSP import and Browse Maps/game-map import failures. The traceback is written to a Blender Text datablock named SLOPGATE_Last_Import_Traceback and to a user-data diagnostics file; the error report identifies the diagnostic location.
- PR #2 head is 66767f0fe7d34db7a29204af1d13dc383ec300ce, based on c63205dc4974c313103ef9b8b7def5131b8680f1. Its QSS Python run 43767937159 passed 275 standalone tests, Python compilation and package assembly; artifact ID 14182513321. This is diagnostic instrumentation, not a root-cause fix.
- No Blender 5.3 reproduction with the full traceback has been recorded. PR #2 is open/draft and is not included in the PR #3 → #4 → #5 lightmap branch chain. The branch name is not evidence that a 0.21.15 add-on build exists on that branch.

### 0.21.15 — detached-face texture export and classic BSP29 lightmap-grid alignment

- PR #3: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/pull/3
- Branch: fix/0.21.15-classic-face-local-lightmap-alignment
- Head: 5ea9781e71ea64b9adb70e5ecbda7918e5d1fde9; base is the PR #1 development code at c63205d.
- The Blender paint workflow may use a shared atlas, but BSP export now crops each edited face tile back to its own local image dimensions and exports it as a face-local miptexture using the local texinfo projection. This avoids letting shared-atlas packing scale/offset changes alter classic BSP29 lightmap extents or luxel sample phase.
- Added pure-Python tests for tile extraction/orientation and the shared luxel phase using the committed spottest01 fixture.
- QSS Python run 43774091817 / job 132996263641 passed 277 standalone tests, compile and BSP export integrity checks. Artifact 14185488366, Quake-Surface-Studio-v0.21.15-Blender-Install, 293,556 bytes, SHA-256 97ab102d343a42b81c9da8b7e05d4c957a689739702e4f75276368081ec04971.
- PR #3 is open/draft. No Blender 5.3 or Ironwail runtime acceptance is recorded. The first fixture arrangement failed; the corrected branch tip's CI rerun passed.

### 0.21.16 — conservative shared-coplanar-edge luxel reconciliation

- PR #4: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/pull/4
- Branch: fix/0.21.16-coplanar-edge-luxel-stitch
- Head: 15ff4802a32eaa64d83e2c42bcd33761bc124e94; based on PR #3 head 5ea9781e.
- Adds an export-time edge reconciliation pass for lightmap samples occupying the same world-space position on a shared geometric BSP edge.
- Matching is deliberately conservative: exactly two lightmapped face users of the shared edge, same BSP model, same oriented plane, identical four light-style bytes, and aligned classic 16-unit luxel grids. Matched RGB samples are averaged and both QLIT RGB data and classic monochrome fallback values are updated.
- It does not blend corners, face interiors, non-coplanar joins, style boundaries or misaligned grids. Do not broaden the matcher without regression maps because boundary blending can leak light across real shadow/material/orientation changes.
- QSS Python run 43775538317 / job 133000869251 passed 281 standalone tests, compile and BSP export integrity checks. Artifact 14185683175, Quake-Surface-Studio-v0.21.16-Blender-Install, 297,273 bytes, SHA-256 32b6bad1f384f25f228111383dd50d0bb01cf0900fb1cef5fb905500ccb1402e.
- PR #4 is open/draft. The in-game visual effect has not yet been confirmed by the user.

### 0.21.17 — world-aligned coplanar lightmap charts

- The PR #5 branch incorporates the PR #3 and PR #4 ancestry and adds a shared world-space chart representation for connected coplanar BSP faces.
- It builds a deterministic plane frame, groups adjacent lightmapped faces only when they share a BSP edge and agree on model ownership, oriented plane and all four light-style bytes, then snaps chart origins to a common 16-unit world luxel lattice.
- Each face is resampled into its shared chart. This makes matching coplanar edge samples share one chart coordinate/grid rather than relying solely on independent face-local sampling. Model and style boundaries remain chart boundaries.
- A world-chart pixel-coordinate transform and chart-space source sampling are used by the bake diagnostics/coverage path. Do not assume this modifies non-coplanar boundaries or proves all engine filtering artifacts solved.
- Version 0.21.17 is an intermediate development step; the latest candidate is 0.21.18.

### 0.21.18 — outward-rounded luxel coverage and large-map sampling performance

- PR #5: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/pull/5
- Branch: fix/0.21.17-world-aligned-lightmap-charts
- Head: 7f182cf97cc1a3aa35c15408d429a478f87e08c2; base is PR #4 head 15ff4802.
- Edge-sampling correction: classic BSP29 face extents round outward to complete 16-unit luxel boundaries. Therefore a final luxel row/column can have its centre just outside the actual polygon while still belonging to the face's valid classic lightmap rectangle. The earlier chart resampler skipped those samples. The new pass fills them by clamping to that face's own source-grid edge values.
- The resampler now checks each candidate coordinate against the face's own classic sample rectangle before accumulating it. This prevents the polygon search margin from extrapolating one face into a neighbour's area. A regression fixture covers a 20-unit-wide face whose last outward-rounded luxel centre lies beyond its geometric edge.
- Performance correction: per-face processing was repeatedly reconstructing BSP face, plane, texinfo and style metadata during post-Cycles diagnostics and the Quake Direct path. This created near-quadratic work and could make large maps such as e1m1 appear frozen after Cycles had finished.
- The 0.21.18 pass parses/prepares that metadata once per operation and reuses it for diagnostics, face coverage and source-lightmap comparisons. It also applies the cache to Quake Direct baking.
- Classic luxel sampling from world charts uses an affine fast path that solves the face projection once and advances pixel coordinates, avoiding per-luxel XYZ tuple construction.
- QSS Python run 43783467279 / job 133025758521 passed Python compilation, 290 standalone tests, BSP export integrity checks, Blender ZIP assembly and artifact upload.
- Artifact: Quake-Surface-Studio-v0.21.18-Blender-Install, ID 14188889199, 308,296 bytes. GitHub Actions upload log/API digest: 18499457a52b39b232cce6c4f7567be6c7d028ca29fdcdc70de226ee4cf772e8. Artifact/run page: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43783467279/artifacts/14188889199.
- An earlier narrative in the reconstructed chat archive lists SHA-256 5bff80081380ff08ae1c7779f6ad605c058b0d514238d3cbfa37be638b607015 for the same stated 308,296-byte installer. That conflicts with the workflow upload log and GitHub artifact metadata. Prefer the digest from the actual artifact record above unless an independent downloaded-file hash proves otherwise.
- The PR #5 description records the same 290-test pass and confirms that Blender 5.3 and Ironwail runtime validation remain outstanding. This build has not been proven to fix the visible edge artifact or the e1m1 freeze; it is the next candidate to test, not a release.

### Open PR topology as of 2026-11-16

| PR | Branch | Base | Purpose | State |
|---|---|---|---|---|
| #1 | fix/v0.11.1-metadata-style-order-test | main | Long-running development line; documentation updates are maintained on this branch | Open, draft |
| #2 | fix/0.21.15-bsp-import-array-trace | fix/v0.11.1-metadata-style-order-test at c63205d | Capture the unresolved BSP import traceback | Open, draft |
| #3 | fix/0.21.15-classic-face-local-lightmap-alignment | fix/v0.11.1-metadata-style-order-test at c63205d | 0.21.15 detached-face export correction | Open, draft |
| #4 | fix/0.21.16-coplanar-edge-luxel-stitch | PR #3 head 5ea9781e | 0.21.16 conservative shared-edge sample reconciliation | Open, draft |
| #5 | fix/0.21.17-world-aligned-lightmap-charts | PR #4 head 15ff4802 | 0.21.17 charts + 0.21.18 edge/performance, brightness, NaN guard, export timing and NaN face/light attribution diagnostics | Open, draft; head bdae11b8 |

Do not merge these stacked PRs out of order. PR #3 → PR #4 → PR #5 is the lightmap integration sequence. PR #2 is an independent diagnostic branch. PR #3–#5 are based on the c63205d source base rather than the latest PR #1 documentation-only head; account for that when integrating the archive/handoff update.

### Immediate runtime validation and next engineering steps

1. Install the newest 0.21.18 candidate, artifact ID 14282850052, and re-import e1m1 so all Cycles light node trees are rebuilt with the patched falloff shader. Repeat the bake. If a NaN remains, inspect the new attribution block: BSP face ID, Blender polygon, luxel (s,t), atlas centre, Quake-space XYZ, and nearest three active-map lights with delay/value/wait/falloff. The latest candidate has a 296-test CI pass. The one-luxel NaN root cause remains unconfirmed; do not apply a silent clamp.
2. Compare the default `_softangle=0` spotlight edge and brightness with ericw. The earlier HDR source-match and post-luxel-reduction calibration corrections remain in this candidate.
3. Repeat e1m1 in Blender 5.3. Record total bake duration and Cycles operator duration. Previous user report: total 2m57.1s / Cycles 2m48.7s.
4. Use Test in Ironwail and inspect the new `Last BSP export` timings. The user clarified Blender freezes immediately after the button click for ~25 seconds, then unfreezes at the same moment Ironwail opens. Source inspection confirms `_export_object` runs synchronously in the UI operator before launching Ironwail. The new timing splits export into source parse/palette, texture/image processing, face/texinfo remap, lightmap patch, and serialize/write. This is instrumentation only; it does not make export asynchronous or faster.
5. After export timings are captured, optimize only the stage actually shown to dominate. Do not lower bake samples/bounces as a workaround for temporary export latency.
6. Keep the multi-BSP scene clarification: aggregated scene-wide diagnostic counts may legitimately include multiple imported BSPs. Do not treat those totals alone as proof of cross-map contamination. Quake Direct is separately scoped to the active map.
7. If BSP import error recurs, use PR #2 traceback instrumentation. Do not resume broad undo/redo testing without a reproducible user report.
8. Continue to provide an installable ZIP for every candidate build with exact branch/commit, CI status, artifact page and checksum. Keep version declarations synchronized and do not call any 0.21.x candidate an official release.

## Archive and handoff maintenance rule

The user identified that the full chat log and then this handoff had stopped being updated. This is an important process failure to avoid repeating:
- Append the user's original dialogue and the assistant's relevant technical response to Slipgate_Chat_History_Clean.md after each substantive session. Preserve historical text; do not rewrite old dialogue.
- Update SLOPGATE_AI_Handoff.md when a decision, implementation state, branch topology, test result or runtime-validation status changes materially.
- After editing either file, verify the branch, latest commit, blob contents and that the new section is present. Never state that the documentation was updated unless the GitHub write succeeded.
- Use SLOPGATE_AI_Handoff.md as the maintained starting point and the main chat archive for detailed historical confirmation.


## Standing documentation requirement — confirmed 2026-11-16

The user explicitly instructed: **“From now on ALWAYS keep both files up to date.”** Treat this as a required part of every SLOPGATE work session, not optional housekeeping.

1. **Conversation archive:** append the relevant user dialogue and assistant technical response/decisions/results to `Slipgate_Chat_History_Clean.md`. Keep it chronological and append-only; preserve prior entries.
2. **Maintained handoff:** review and update this `SLOPGATE_AI_Handoff.md` in the same work session so the next session starts from the actual current state: implementation baseline, branch/PR topology, design decisions, open defects, tests and their evidence, runtime validation, artefacts/checksums, and next actions.
3. **No-change sessions:** when a SLOPGATE session makes no engineering change, still record the relevant discussion and explicitly state that no source change/test/build/merge occurred where applicable. Do not manufacture progress.
4. **Consistency and verification:** keep the archive and handoff mutually consistent; verify both GitHub writes, the target branch, resulting branch HEAD, and the newly written content before claiming they are current.
5. **Release evidence:** continue distinguishing automated tests from Blender/engine runtime validation and candidate builds from official releases. Keep exact install artefact links and verified checksums with each build update.

The archive entry for this instruction was appended immediately before this handoff update. This session changes documentation/process records only; it does not modify add-on source, change the version, create a build, run tests, or merge a PR.

## Latest investigation — 2026-11-16: severe Cycles lightmap overbrightness

### User test evidence

- Folder: [testressource26.11.16_01](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/tree/fix/v0.11.1-metadata-style-order-test/testressource26.11.16_01), branch fix/v0.11.1-metadata-style-order-test.
- User did not provide the copyrighted Quake Remaster e1m1 MAP/BSP; only screenshots and diagnostics were supplied for that test. The one-light test resources are named spottest02-compile (MAP, BSP, ericw logs, images, original/baked lightmaps and Blender diagnostics), while the message also refers to spottest01.
- MAP has one value-600 spotlight at (392, -128, 264), target info_notnull at (456, -160, 200), default outer angle 40, default _softangle 0. The wall spans the user-described coordinates at x=496.
- Stats: 36 receiver faces, 3,858 luxels, 512px atlas, 4,096 GPU Cycles samples, 2 diffuse bounces. Raw luxel mean 0.1606826660; source mean 0.0237591356; final atlas mean 0.0319509245; old normalization 0.1478637129; whole-atlas max channel 12.57252789. Final mean was ~1.345x the source mean. Old chart sampler clipped HDR above 1.0 before mean measurement; old calibration also measured before luxel reduction.
- ericw compile log says bounce was set to 1 from command line. The SLOPGATE report's worldspawn/compiler bounce field is 0; that field does not include the CLI override.
- User reports e1m1 3m01 total / 2m49 Cycles and a 25-second export/test interval. The latter is not identified in the supplied report.

### Confirmed source defects now patched on PR #5

**Feature branch:** fix/0.21.17-world-aligned-lightmap-charts  
**Current head:** 8ddee09dd7027045360a163aef6c2f08d3de6ec1  
**PR:** #5, open and draft; no merge.  
**Add-on version declarations:** remain synchronized at 0.21.18; this is a candidate build, not an official release.

- World-chart calibration sampling now supports unbounded linear float RGB via `preserve_float=True`. The existing byte-clamped output remains the default for BSP export.
- Cycles bake calibration now takes place after `collapse_rgba_luxel_blocks`, by sampling the same reduced float atlas that is about to be exported. HDR values remain intact until the final BSP byte conversion.
- ericw `_softangle=0` now maps to Blender Spot Blend 0 (hard edge), instead of Blend 1 (maximum softness). Positive inner angles retain proportional conversion.
- Quake Direct's imported-light collector now enumerates only `_qss_active_map_objects(context.scene, obj)`, preventing unrelated maps in the scene from contributing.
- Lighting diagnostics now list only the active BSP collection's imported lights. The old 253 count was a report-scope bug: Cycles baking already restricted/hid other map lights, so the diagnostic count is not evidence that those 253 lights affected the Cycles test bake.

Commits on PR #5:
`87640e1a9197239b17144179315a1ef3394a0016`, `98753c71756fcd7e039578764da56beb2dfbb92d`, `ecda44b5aa6f274428c6b43d399fca2d6ed3c9f5`, `4d5caaeb61c6158d7eff500ee6412d2414331d05`, `fbd760c774464b3567786cf2e42fd9c52ee11430`, `8ddee09dd7027045360a163aef6c2f08d3de6ec1`.

### CI and install artifact

- Run: [43885001364](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43885001364); job 133360636369.
- Passed: Python compilation, 294 standalone tests, BSP export integrity checks, package assembly and artifact upload. Duplicate run 43885021350 also succeeded.
- Installer artifact: [Quake-Surface-Studio-v0.21.18-Blender-Install (14233422720)](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43885001364/artifacts/14233422720).
- Size 309,344 bytes; verified Actions upload SHA-256: `e38fd4cef1288fcaaef7a20e912a2ea1f7be4339910071518fc21204453eb3a2`.
- No Blender 5.3 interactive test, Cycles bake, Ironwail launch or Remaster engine comparison has been run by the assistant. The user must validate the artifact before any claim that brightness is fixed.

### Remaining potential contributor / diagnostic plan

The test Cycles bake used two diffuse bounces; the ericw command-line compile used one. The Quake delay-0 Cycles light uses a custom linear falloff. Blender documents that its Linear/Constant Light Falloff can introduce additional energy with each global-illumination bounce and become extremely bright. This is a credible additional contributor, not yet established as the cause in the supplied bake. No bounce default or policy was changed. Compare 0, 1 and 2 bounces before changing that behaviour.

The user's 25-second interval is not represented in the diagnostic timing fields. Establish whether it refers to SLOPGATE BSP export or Ironwail loading/testing before optimizing that path.

References:
- ericw spot-angle and bounce keys: https://ericw-tools.readthedocs.io/en/latest/light.html
- Blender 5.3 Spot Blend semantics: https://docs.blender.org/manual/en/5.3/render/lights/light_object.html
- Blender Light Falloff bounce warning: https://docs.blender.org/manual/en/4.3/render/shader_nodes/color/light_falloff.html

## 2026-11-16 — User clarification: multi-BSP scene explains aggregate light/bake counts

The user points out that both BSPs were probably imported into the same SLOPGATE/Blender scene. Therefore the reported additional lights (253) and two registered bakes may simply be scene-wide totals spanning both imported maps. The diagnostic fields may not currently discriminate every statistic by active BSP. This is a plausible explanation and supersedes the earlier inference that the count itself demonstrated a diagnostics-scope defect. Do not treat the aggregate light count or bake count as evidence of cross-map Cycles contamination. Verify the actual ownership/scope of each report field before changing or interpreting it. Keep active-map isolation in Quake Direct as a separate code-path question; test with both BSPs present and compare against a clean one-map scene if needed.

## 2026-11-16 — Runtime retest: calibration abort and Ironwail startup delay

**User report**

> [Test in ironwail] even with a freshly imported unbaked e1m1 takes about 25 to 
> start ironwail.
>
> Baking  takes the usuasl time and i hear the gpu fans but in the end it gives 
> an error:
> Cycles bake failed; atlas and light calibration restored: Source and baked 
> luminance must both be non-zero

**Interpretation / status**

- The ~25-second delay is present even when e1m1 has just been imported and not baked. It is therefore not attributable solely to the new Cycles bake/calibration stage. The measured interval still needs to be separated into SLOPGATE export/pre-launch work versus Ironwail process startup/load time; the user phrasing says time to start Ironwail, so do not call it a BSP export regression without timing boundaries.
- Cycles appears to execute (user hears GPU activity) but the bake transaction aborts and restores the atlas/light calibration. The reported exception comes from source/baked luminance calibration requiring both values nonzero. This does not establish that Cycles rendered a black atlas: the zero could be in source luxel sampling, post-reduction baked luxel sampling, or a calibration helper precondition. Capture the diagnostic report before changing the fallback behavior.
- On current PR #5 source at 8ddee09dd7027045360a163aef6c2f08d3de6ec1, the bake path samples source and post-reduction bake values, records source mean/raw bake mean, and invokes `lighting_utils.bake_atlas_match_scale(source_mean, raw_bake_mean)` when source mean is positive. The helper implementation/error source was not located in the single-file addon tree during this inspection; do not patch by guessing.
- User's earlier clarification remains authoritative: both BSPs were likely imported into the same scene, so aggregate light/bake counts may span maps. Do not interpret those totals as proof of cross-map contamination.

**Next diagnostic request**

Ask the user to save and provide the SLOPGATE lighting diagnostics immediately after the failed bake, plus Blender's console traceback if available. Key values: source mean, raw/post-reduction baked mean, sampled luxel count, image max/nonzero pixel stats, active BSP name/face count, and any calibration exception stack. Then determine whether zero originates in source sampler, reduced bake sampler, or calibration helper. Preserve the pre-bake atlas restoration behavior. For the 25-second delay, time separately from clicking export to Ironwail process launch and from process launch to map visible.

No source code change or new installer was made in response to this report. Both project records updated; no runtime fix claimed.

## Latest runtime diagnosis and candidate patch — 2026-11-16

### User's clarification of the 25-second Test in Ironwail delay

The user explicitly clarified: clicking **Test in Ironwail** freezes Blender; ~25 seconds later Blender unfreezes at the same time Ironwail opens. This means the delay occurs before the Ironwail process launch. Source inspection confirmed the operator calls `_export_object(obj, output_path, mode)` synchronously and only then starts Ironwail through `external_tools.launch_process_handle`.

### Uploaded e1m1 lighting report

- User upload: `Pasted text(20261116-155250).txt`.
- Blender 5.3.0, active object e1m1.bsp_QSS, QLIT v1 .lit sidecar, EEVEE restored after bake.
- Failed bake attempt total 2m57.1s; Cycles operator 2m48.7s; GPU; 4,096 samples; 2 diffuse bounces; 2,048px float Non-Color atlas; 6,437 receiver faces.
- Cycles operator result FINISHED. 165,763 sampled luxels, 5,631 faces in the face-coverage sample, 157,564 lit luxels, max face luminance 360.69619245.
- Atlas: 4,194,304 px; 747,740 nonzero pixels; 2,243,220 nonzero RGB values; max channel 404.7032776. But whole-atlas mean_luma and sampled luxel mean are NaN.
- Last successful bake metrics are n/a, indicating the failed transaction restored prior atlas/calibration. This is not evidence of a black bake: many texels are nonzero and maximum values are finite.
- Source-match calibration setting 1.0, light energy scale 1.0, worldspawn/compiler bounce 16; the actual Cycles bake had 2 diffuse bounces. There is no traceback or old-build non-finite channel count/coordinate in the report.

### Code diagnosis

- The generic exception `Source and baked luminance must both be non-zero` was secondary: `bake_atlas_match_scale` clamps input via `max(0.0, float(value))`; NaN is reduced to zero in this call path.
- The Cycles delay-0/delay-5 QSS light graph reconstructed distance with Light Falloff `Linear / Quadratic`. At exactly zero distance, both outputs may be infinite, giving Inf/Inf = NaN. This is a credible specific singularity to fix, but the new branch has not yet been runtime-verified against the user's e1m1 bake.
- The temporary test operator performed export synchronously, explaining the ~25-second Blender UI block. The export stage responsible was unknown before instrumentation.

### Latest PR #5 patch

Feature branch: `fix/0.21.17-world-aligned-lightmap-charts`  
Current head: `a3daef84b1bd12c32f90218d5eabf643439b73e6`  
PR #5 remains open and draft; no merge. Version remains synchronized at 0.21.18.

Changes in this head:
1. Cycles Light Falloff distance now uses `sqrt(Strength / max(Quadratic, 1e-20))` instead of `Linear / Quadratic`. This preserves the same distance calculation away from the origin and avoids the identified Inf/Inf singularity.
2. Whole-atlas diagnostics now count non-finite pixels/channels, calculate finite-only luminance, and record the first 16 bad pixel coordinates.
3. Bake validation counts non-finite source and baked luxel samples and emits an explicit non-finite error before source-match calibration. Atlas rollback remains intact; there is no silent NaN clamp.
4. Lighting diagnostic text now reports non-finite baked/source luxel counts and source mean.
5. `_export_object` now records total time and per-stage durations: source BSP parse/palette, texture/image processing, face/texinfo remap, lightmap patch, serialize/write. Test in Ironwail reports the temporary export duration. This is instrumentation only; the UI remains synchronous, and no optimization or asynchronous export has yet been implemented.

Source commit: `a3daef84b1bd12c32f90218d5eabf643439b73e6`.

### CI and installer

- QSS Python run [43904361797](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43904361797), job 133429096100: passed Python compilation, 294 tests, BSP export-integrity checks, package assembly and artifact upload. Duplicate run 43904348965 also succeeded.
- Installer: [Quake-Surface-Studio-v0.21.18-Blender-Install, artifact 14244660593](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43904361797/artifacts/14244660593).
- Size 310,319 bytes; SHA-256 `632c3d004b13af1b7082d81120122bf6f73bc0d02a335fa8f0f8cec93fac2c26`.
- No Blender 5.3 GUI bake/rebake or Ironwail run by the assistant. Runtime fix is unconfirmed. The next user validation must re-import e1m1 before baking so the updated Cycles light node graphs are reconstructed, then re-run Test in Ironwail to capture per-stage export timings.

## Follow-up regression fix — 2026-11-16: bake_values use before assignment

### User-reported error

`Cycles bake failed; atlas and light calibration restored: cannot access local variable 'bake_values' where it is not associated with a value`

### Root cause and correction

The previous NaN-diagnostics patch read `bake_values` during the source-only validation stage, before the reduced Cycles atlas was sampled into that variable. The correct assignment occurs after the bake is copied to the float buffer, luxel blocks are collapsed, and the reduced atlas is sampled. This caused Python's `UnboundLocalError` to mask the intended NaN/zero validation.

The early block now calculates source-only values and energy metadata; all validation that reads `bake_values` is moved to immediately after the post-reduction sampler assigns it. It then counts non-finite bake/source luxels and performs non-finite and zero-value checks. Rollback remains unchanged.

A static AST regression test was added to `tests/test_bake_scope.py`: it finds the function containing the Cycles bake operator and asserts the unique assignment to `bake_values` occurs before any read.

### Current source and build

- PR #5 branch: `fix/0.21.17-world-aligned-lightmap-charts`.
- Current head: `5c4cd5382534566698f4ae974abce679f00a7020`.
- Fix commit: `b09d3775a92603cf65ede80d102400aae36282ae`.
- Regression test commit: `5c4cd5382534566698f4ae974abce679f00a7020`.
- Add-on remains version 0.21.18 candidate, open draft PR; not an official release and not merged.

### CI and installer

- GitHub Actions run [43964423362](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43964423362), job 133639973941, completed successfully on the exact current head.
- 295 standalone tests passed; Python compilation, BSP export integrity, installer package assembly and artifact upload passed.
- Installer: [Quake-Surface-Studio-v0.21.18-Blender-Install, artifact 14274424187](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43964423362/artifacts/14274424187).
- Size 310,790 bytes; verified SHA-256: `67add3a143f2a4ce6b44168b839139f1dedf7882d78a514fdb0025a3ee43ae8e`.

### Runtime status

No Blender 5.3 interactive test has been run by the assistant. The prior `sqrt(Strength / Quadratic)` NaN correction is still awaiting the user's runtime validation. Re-import the BSP before baking so all light node trees are rebuilt. If another bake fails, expect the intended non-finite or zero-luxel report rather than the `bake_values` local-variable exception. Then use Test in Ironwail and inspect the per-stage export timings from the previous instrumentation patch.

## Latest non-finite bake report — localized to one luxel; attribution diagnostics added (2026-11-16)

### User's latest report

`baked=1/165763, source=0/165763, non-finite atlas RGB values=12, non-finite atlas pixels=4, first atlas pixel coordinates=[(1594, 2000), (1595, 2000), (1594, 2001), (1595, 2001)]`.

This is one failed luxel, with all source luxels finite. The bad atlas pixels form a 2x2 region. This confirms the previous bake_values ordering fix works and that NaN validation now reports the real data issue rather than an UnboundLocalError. Atlas/calibration rollback succeeded. The previous `sqrt(Strength / max(Quadratic, 1e-20))` update did not eliminate all NaN values. A zero-distance Light Falloff singularity remains a hypothesis, not proven.

### New diagnostics on PR #5

Feature branch: `fix/0.21.17-world-aligned-lightmap-charts`  
Current head: `bdae11b81140c9b70a332c3a78a179fe5ebeb22e`  
Version: 0.21.18 candidate; PR #5 open/draft, not merged.

- Added `classic_face_grid_world_chart_pixel_coordinates()` so the precise fast sampler pixel centres can be calculated independently and tested.
- Added a coordinate mapping regression test.
- Added `_qss_describe_nonfinite_luxels()` to map bad atlas pixels back to candidate receiver face, BSP face ID, polygon, (s,t) luxel index, atlas sample centre and Quake-space XYZ; also identifies nearest three active-map lights and reports their origin/delay/value/wait/falloff.
- For non-world-chart maps, the diagnostic helper now loads the source BSP/cache and falls back to face-local atlas sample centres.
- Error and Save Lighting Diagnostics now include this attribution block. No lighting output clamp, forced per-light fallback, or other speculative shader change was made; the cause remains unconfirmed.

Commits:
- `143b25b6a54f4a96080dc3557e5aeac94e06333d`
- `8b8c210a983cc241d8b4d3f32aedc91b887eaecd`
- `77c4e6f38161def61ced62052f0672e72b805f43`
- `bdae11b81140c9b70a332c3a78a179fe5ebeb22e`

### CI and installer

- GitHub Actions run [43977434456](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43977434456), job 133684924995, passed on exact head bdae11b81140c9b70a332c3a78a179fe5ebeb22e.
- **296 tests passed**, including `test_classic_face_grid_pixel_coordinates_match_sampler_centres`; Python compilation, BSP export integrity, package assembly and artifact upload passed.
- Installer: [Quake-Surface-Studio-v0.21.18-Blender-Install, artifact 14282850052](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43977434456/artifacts/14282850052).
- Size 312,385 bytes; SHA-256 `785cc28a2a6cb29e7fe01c5764fcdf8aa8d48b02671b3db2fdcd32598ba729d3`.
- Not an official release. No Blender 5.3 runtime bake was run by the assistant.

### Next test

Install artifact 14282850052 and re-import e1m1. If the NaN persists, the new report should identify the face/luxel/map-space point and nearest lights. Use the returned distances and profiles to determine whether the bad luxel coincides with a source light or whether the issue is elsewhere in the Cycles light shader. Do not clamp or accept the texel until identified; preserve rollback.


## 2026-11-17 — Handoff review and user-facing communication preference

The user asked that explanations be less technical and aimed at **technically enthusiastic level designers**, not computer scientists who happen to enjoy level design. This is a standing communication preference for all future SLOPGATE responses.

User-facing explanations should:
- Start with the practical effect: what changes in the map, lighting, texture, export or Blender workflow.
- Say plainly what works, what does not, what is still uncertain, and what the user should try next.
- Avoid code-level names, long lists of internal functions and programmer jargon unless they are necessary to explain a problem.
- Briefly explain any technical term that cannot be avoided.
- Keep reports compact and useful to a level designer, while retaining exact commits, test counts, source findings and other detailed evidence in this handoff and the full archive.

### Live PR status checked 2026-11-17

- PR #1: open/draft, `fix/v0.11.1-metadata-style-order-test` → `main`; head `d1f1fd29257cf9932121c1ede6555b61242c725c`. This includes the maintained project documents; the underlying add-on source baseline on this line is still `c63205dc4974c313103ef9b8b7def5131b8680f1`.
- PR #2: open/draft, independent BSP import traceback diagnostics; head `66767f0fe7d34db7a29204af1d13dc383ec300ce`.
- PR #3: open/draft, detached-face/classic lightmap alignment; head `5ea9781e71ea64b9adb70e5ecbda7918e5d1fde9`.
- PR #4: open/draft, shared coplanar-edge lightmap seam reconciliation; head `15ff4802a32eaa64d83e2c42bcd33761bc124e94`, based on PR #3.
- PR #5: open/draft, world-aligned lightmap charts and the latest 0.21.18 candidate; head `bdae11b81140c9b70a332c3a78a179fe5ebeb22e`, based on PR #4.
- Keep PR #3 → PR #4 → PR #5 in that order. PR #2 is separate. No PR was merged during this session.

### Current test status carried forward

The latest 0.21.18 candidate has a 296-test CI pass and diagnostics that should identify the face, luxel location, map-space position and nearby lights for the remaining single bad lighting sample. This is diagnostic progress, not a lighting fix. Blender 5.3 runtime validation is still outstanding. The 25-second Test in Ironwail pause was traced to SLOPGATE preparing the temporary BSP before launching Ironwail; the new timings are intended to reveal which export step is taking the time.

This session changed documentation only. No add-on source, installer, automated test result or merge status changed.


## 2026-11-17 — e1m1 still fails on the same single bad luxel

The user re-tested e1m1 and reported the same failure:
`baked=1/165763, source=0/165763, non-finite atlas RGB values=12, non-finite atlas pixels=4`; bad atlas pixels remain `(1594, 2000), (1595, 2000), (1594, 2001), (1595, 2001)`. All 165,763 original source samples are finite and the failed bake restores the previous atlas/calibration.

### Important clarification from live source review

On PR #5 head `bdae11b81140c9b70a332c3a78a179fe5ebeb22e`, the short bake error dialog is deliberately generic. The face/light details are stored on the active BSP object before raising the error:
- `qss_last_bake_attempt_nonfinite_details`
- `qss_last_bake_attempt_lights`

The Save Lighting Diagnostics report includes both values under:
- `Last attempted lamp states`
- `Non-finite luxel face/world/light matches`

Therefore, seeing the same short popup does not establish whether the added attribution worked. The required next step is to save the diagnostic report immediately after the failed e1m1 bake, with the e1m1 BSP object active, and inspect the face/luxel/map-coordinate/nearest-light section. It should list the three closest imported lights. If it instead reports no matching face/luxel or cannot access the source BSP, that identifies a separate problem in the new tracing helper.

Do not clamp/zero the bad luxel or alter all imported lights as a workaround. Keep the rollback behaviour. Only after reading the map position and nearby lights should the relevant Cycles light/shader calculation be changed.

### Current source / PR status

- PR #5 remains open/draft, branch `fix/0.21.17-world-aligned-lightmap-charts`, head `bdae11b81140c9b70a332c3a78a179fe5ebeb22e`, base PR #4.
- Add-on version remains 0.21.18 candidate.
- Latest CI: 296 tests passed; this does not substitute for Blender 5.3 bake validation.
- No new source commit, test run, installer, or PR merge was made for this report.


## 2026-11-17 — e1m1 face 5828 traced; 0.21.19 delay-0 falloff experiment

### User test findings

The user supplied the face/luxel attribution from the latest 0.21.18 candidate:
- One bad sampled luxel out of 165,763; zero bad source luxels.
- Four non-finite atlas pixels: `(1594, 2000)`, `(1595, 2000)`, `(1594, 2001)`, `(1595, 2001)`.
- BSP face 5828, Blender polygon 5828, local luxel (9, 3), atlas sample centre (1594.5, 2000.5).
- Quake world position: `(-80, 640, 96)`.
- Nearest imported lights:
  1. `QSS_light_405`, 64.4981 units away, origin (-120,624,144), delay 0, value 1000, wait 1, falloff 0.
  2. `QSS_light_330`, 77.5629 units, origin (-128,584,72), delay 0, value 200, wait 1, falloff 0.
  3. `QSS_light_404`, 80.399 units, origin (-48,696,144), delay 0, value 1000, wait 1, falloff 0.
- Therefore, the invalid sample is not coincident with a light origin. The previous exact-zero-distance Light Falloff explanation is not supported by the reported world position and nearest-light distances.
- Source luxel sampling remains fully finite; only the baked result is invalid. Atlas rollback is still working.
- The post-failure diagnostics also show zero entries for the mesh face attributes and UV layers. Since the diagnostic helper successfully used those attributes to report face 5828 during the bake failure, the zero-length attributes may be due to bake cleanup/rollback or the diagnostics inspection occurring after they were invalidated. Treat this as a separate post-failure reporting/cleanup issue; do not conclude that the mesh started without attributes.

### Targeted 0.21.19 code experiment

The three nearest lights all use delay 0. The PR #5 custom Cycles shader attempted to bend Blender's normal inverse-square point-light falloff into ericw's linear curve. The prior distance-expression adjustment did not remove the same bad luxel.

Commit `a781e3f43d24e42bb19145cda13da3973d5044cd` on `fix/0.21.17-world-aligned-lightmap-charts` makes a narrow test change:
- Delay-0 lights now use Blender's regular Cycles point-light falloff instead of the experimental custom node graph.
- Existing Quake-to-Blender light energy calibration, cutoff range and global light-energy slider remain.
- Delay-5 custom falloff remains unchanged.
- Separate Quake Direct CPU lighting remains unchanged.
- Only QSS-owned custom node graphs are disabled; user-authored light nodes are preserved.
- Added policy tests and synchronized visible version metadata to 0.21.19 in `__init__.py`, `addon.py` and README.
- Failure detection and atlas/calibration rollback remain in place. No bad luxel is clamped or silently accepted.

This is an isolation experiment, not a proven final lighting fix. It intentionally trades exact ericw delay-0 curve matching in the Cycles bake for the established native Blender approximation. Compare final brightness and falloff in e1m1 and the one-light spottest after the bake test. Do not claim ericw parity.

### CI and installer

- PR #5 is still open/draft; head `a781e3f43d24e42bb19145cda13da3973d5044cd`, based on PR #4. No merge.
- Run [43983168256](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43983168256): succeeded on the exact source head.
- Python compilation and **300 standalone tests** passed; add-on package assembled and uploaded.
- Installer artifact [Quake-Surface-Studio-v0.21.19-Blender-Install, ID 14283692364](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43983168256/artifacts/14283692364).
- Size 312,721 bytes; SHA-256 `4451116ff2fb4af0e3b8ae1955d596249778b4d630afa4f467fe55927543417a`.
- No Blender 5.3 interactive bake or Ironwail comparison by the assistant. The experiment requires the user's runtime test.

### Next validation

1. Install 0.21.19 and re-import e1m1 so all imported light objects are recreated and the native delay-0 falloff path is applied.
2. Bake e1m1. Verify that the previous one-luxel NaN either disappears or is reported at a new location.
3. If successful, compare wall/floor light levels and overall brightness with the original source lightmaps, then inspect the exported BSP in Ironwail.
4. Retest `spottest02` to confirm that its hard-edged value-600 spotlight and coverage remain reasonable under the native delay-0 approximation.
5. If it still fails, inspect the new report and source/luxel attribution; do not clamp the bad sample. Also trace why face attributes are zero in the report after failure.



## 2026-11-17 — Diagnostics mesh-data counts and Edit Mode clarification

The user's post-failure report listed zero entries for all face-domain attributes and both UV layers. Code review shows the bake operator restores the user's original mode before returning. If the user began in Edit Mode, the subsequent Save Lighting Diagnostics operator reads the regular Mesh attribute/UV collections while the object is back in Edit Mode. The zero counts may be caused by that reporting context rather than data loss. The face 5828 diagnostic was successfully generated during the bake itself.

For another report, ask the user to switch the e1m1 object to **Object Mode after the failed bake**, then click Save Lighting Diagnostics. This should allow the report's regular Mesh attribute/UV reads to return valid entry counts. Do not ask the user to re-import solely because of those zero counts until Object Mode diagnostics confirms the data is actually missing.


## 2026-11-17 — 0.21.19 Blender test results: spottest02 passes; e1m1 still fails

The user tested the 0.21.19 installer in Blender 5.3.0:
- e1m1 still produces the same non-finite bake error: 1/165,763 bad baked luxels, 0/165,763 bad source luxels; 12 non-finite RGB channel values across four atlas pixels `(1594,2000)`, `(1595,2000)`, `(1594,2001)`, `(1595,2001)`.
- spottest02 completes successfully.
  - 1 imported delay-0 spotlight (`QSS_light_002`, raw Quake value 300, range 600).
  - GPU, 4096 samples, two diffuse bounces.
  - 2.22 s Cycles, 2.83 s total.
  - 3,858 sampled luxels; 3,845 lit; 36/36 light-receiving faces lit.
  - zero non-finite bake/source luxels and zero non-finite atlas pixels.
  - raw sampled mean 0.4274429424; source mean 0.02375913635; source-match normalization 0.05558434586; final atlas mean 0.02375913636 and max 0.936521.
  - Raw atlas maximum before normalization 16.84865. This illustrates that the source-mean normalization is active and successful in this map.

**Meaning:** the 0.21.19 delay-0 native-falloff path works on spottest02's single delay-0 spotlight, but e1m1 still exposes one map-specific non-finite sample. Do not call the e1m1 problem fixed. Do not assume that the original delay-0 custom shader is the only cause: we need a new e1m1 report after the fallback change.

The spottest02 report again shows zero-length mesh attributes/UV arrays. Earlier source review indicates the bake operator restores the user's original mode before returning, while the report reads regular Mesh collections; an Edit Mode report can therefore show misleading zeros. Tell the user to switch the active BSP mesh to **Object Mode** before generating the next diagnostics report. Do not diagnose metadata loss solely from the Edit Mode report.

### Immediate next information needed

Obtain a fresh full **e1m1** Save Lighting Diagnostics report immediately after its failed 0.21.19 bake, with the e1m1 object selected and in Object Mode. Inspect:
- `Last attempted lamp states`
- `Non-finite luxel face/world/light matches`
- `IMPORTED LIGHTS (active BSP map only)`
- active-map light count and per-light delay/value/range/energy.

Compare with the previous 0.21.18 attribution: face 5828, luxel (9,3), map position (-80,640,96), nearest lights #405 (delay0/value1000), #330 (delay0/value200), #404 (delay0/value1000). Determine whether the same luxel and neighbours persist under 0.21.19 before changing more code.

No further source change, new build, test run, or merge was made in this response. PR #5 remains open/draft at `a781e3f43d24e42bb19145cda13da3973d5044cd`; CI 300 tests succeeded. The 0.21.19 package link/digest are recorded above.


## 2026-11-17 — e1m1 0.21.19 diagnostics and 0.21.20 isolation candidate

The user supplied the full Object Mode report (12,659 lines / 850,149 characters) after the 0.21.19 e1m1 failure.

- Failure remains exactly one bad baked luxel / 165,763, zero bad source luxels, four non-finite atlas pixels (1594,2000), (1595,2000), (1594,2001), (1595,2001), twelve non-finite RGB channel values.
- Face/poly 5828, luxel (9,3), atlas sample (1594.5,2000.5), world position (-80,640,96).
- Nearest lights: #405 spotlight delay 0 raw value 1000 at (-120,624,144); #330 point delay 0 raw value 200 at (-128,584,72); #404 spotlight delay 0 raw value 1000 at (-48,696,144). The imported-light summary lists #405/#404 at 40322.5 W, value 500, and #330 at 322.58 W, value 100. Raw attribution values and summary values come from distinct light properties.
- Active map contains 252 imported lights. GPU bake 4096 samples, two diffuse bounces, 2048px atlas; 6605 mesh faces, 110 materials.
- Object Mode report confirms the face attributes and UV layers exist. Earlier zero counts were an Edit Mode report limitation, not data loss.
- 4,194,300 of 4,194,304 atlas pixels are finite; only the same four pixels are bad. Source mean 0.2898378. Raw bake mean NaN due to the single bad luxel; max finite channel 404.7033.
- Viewport scene lights/world are enabled. Active map is e1m1.
- User confirmed 0.21.19 works on spottest02, a small map with one delay-0 spotlight.

### 0.21.20 diagnostic source commit

Commit `21344ec1cbbe60edf321958b9d358598bcfe01ed` on PR #5 branch `fix/0.21.17-world-aligned-lightmap-charts`. Version synchronized to 0.21.20 in add-on metadata, package metadata and README.

This candidate disables the remaining custom delay-5 Cycles light shader. All Quake lights use Blender-native Cycles falloff for one controlled isolation test. Quake Direct is unchanged. Diagnostics now record each light's Cycles profile, custom-node active state, node usage, spotlight size/blend, and energy, including nearest lights around bad luxels.

Interpretation:
- If e1m1 now bakes, investigate the delay-5 custom Cycles shader as the remaining cause.
- If the same luxel still fails, custom Cycles light falloff graphs are ruled out and the investigation moves to face 5828, its material/UV data, or Cycles sampling.
This is a diagnostic approximation only, not the intended final Quake lighting model.

**Status:** source commit created and verified on PR #5 branch. At handoff time, no CI result, 0.21.20 installer artifact, Blender runtime result, or PR merge has been confirmed. Do not give the user a download link until the package artifact is actually built and verified.


## 2026-11-17 — 0.21.20 CI and installer verified

The 0.21.20 diagnostic source commit `21344ec1cbbe60edf321958b9d358598bcfe01ed` triggered GitHub Actions run `43987390162`. Job `133718958318` completed successfully:
- 300 standalone tests passed.
- Python module compilation passed.
- BSP export integrity checks passed.
- Blender install package assembly and artifact upload passed.
- Artifact: `Quake-Surface-Studio-v0.21.20-Blender-Install`, ID `14286680280`, size 313,031 bytes.
- SHA-256: `a37d55487a010cf76da4d897b7989588dcdfa230997cb8cfd2120f4e88cdee75`.
- Download: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43987390162/artifacts/14286680280
- Workflow: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/43987390162

This confirms automated tests and package creation only. It is not a Blender 5.3 runtime bake test. The user must test e1m1 in Blender. 0.21.20 remains a diagnostic candidate, not an official release.


## 2026-11-17 — 0.21.20 still produces same e1m1 non-finite luxel

The user tested 0.21.20 and reports the identical short error: one bad baked luxel out of 165,763; zero bad source luxels; 12 non-finite RGB channel values across the same four atlas pixels `(1594,2000)`, `(1595,2000)`, `(1594,2001)`, `(1595,2001)`. Same map face/luxel attribution from prior report remains face 5828 at (-80,640,96), unless a newer report proves otherwise.

0.21.20 disables **all** QSS custom Cycles falloff graphs (including delay 5). Thus the custom delay-0/delay-5 shader graphs are not the leading cause. However the generic error dialog does not confirm the actual lamp mode at render time. 0.21.20 added `cycles_profile`, `cycles_custom_active`, `use_light_nodes`, `spot_size`, `spot_blend`, and energy to nearest-light attribution and active-map lamp diagnostics.

### Next step

Do not ask for another bake. Ask the user to run **Save Lighting Diagnostics** now, after the failed 0.21.20 bake, with e1m1 selected and in Object Mode. Ask for only:
- `Last attempted lamp states`
- `Non-finite luxel face/world/light matches`

Those should include the nearest three lights plus `cycles_profile`, custom-active state and light-node state. Expected 0.21.20 values: `cycles_profile=native_fallback_delay0` for delay-0 lights (or `native_fallback` for other delays), `cycles_custom_active=False`, `use_light_nodes=False` for QSS-owned graphs. The key check is that no custom QSS light nodes were active. The old 0.21.19 report cannot verify this.

If diagnostics confirm the native path for all three nearest lights, move investigation away from the custom Quake falloff graphs toward face 5828's material/UV/geometry and/or the GPU Cycles sampling path. Do not keep modifying light falloff or add a clamp that hides non-finite values.

No new source code, tests, artifact or merge occurred after this 0.21.20 user test report. PR #5 stays open/draft at `21344ec1cbbe60edf321958b9d358598bcfe01ed`. CI run `43987390162`, 300 tests, successful package, artifact ID `14286680280`, size 313,031 bytes, SHA-256 `a37d55487a010cf76da4d897b7989588dcdfa230997cb8cfd2120f4e88cdee75`.


## 2026-11-17 — Spotlight 405 and geometric corner at the bad e1m1 luxel

The user identified the wall at Quake position `(-80,640,96)` in Ironwail as visibly lit by spotlight `QSS_light_405`, and pushed the decompiled map to `testressource26.11.16_01/e1m1.decompile.map`.

### Decompiled MAP review
- MAP blob `1cf32f62cb9dc977665e48eecfbcc6c9b5d7f49e`, 1,697,287 bytes, 24,864 lines.
- Entity index 405 is the imported `QSS_light_405`:
  - `classname light`, `light 1000`, `_color 181 238 255`
  - `mangle 0 -30 0`
  - `origin -120 624 144`
  - no explicit `angle` or `_softangle`
- ericw-tools documentation says spotlight angle default is 40° and soft-angle default is 0 (hard cone). The source `light/entities.cc::SetupSpotlights` sets the cutoff to `-cos(angle / 2)`; 40° is therefore a 20° half-angle. QSS import maps that to Blender `spot_size=0.698132` rad (40°) and `spot_blend=0`.
- Other nearby source lights: point `(-128,584,72)`, value 200; spotlight `(-48,696,144)`, value 1000, mangle `270 330 0`.

### Face 5828 sample is at a brush corner
The known bad luxel centre is face 5828, local luxel (9,3), Quake position `(-80,640,96)`. Parsed the decompiled MAP's convex brush side planes and found the sample lies exactly at the intersection of perpendicular planes `x=-80` and `y=640`. Both corresponding surface faces use texture `tech07_2`. Matching brush records occur near MAP lines 20258 and 20325. This is a brush-corner / face-boundary sample, not an interior point on a broad wall.

Vector from light 405 to the sample is `(40,16,-48)`, distance 64.4981. Mangle yaw 0 / pitch -30 gives axis approximately `(0.866,0,-0.5)`; the sample direction is about 24.6° from the axis. With the 40° full cone (20° half-angle), it is roughly 4.6° outside the nominal cone. This does not contradict the user's Ironwail observation that the wall region is illuminated; it means the exact luxel centre is near/outside the hard cutoff and other local contributions may be involved. The other nearby spotlight is similarly near/outside its nominal cone at the exact coordinate.

### 0.21.20 report interpretation
The 0.21.20 report marks the three nearest lights as `cycles_profile=native_fallback_delay0`, `cycles_custom_active=False`, `spot_blend=0`. QSS's custom Cycles falloff is therefore not marked active at the bad sample. The report also says `use_light_nodes=True`; that is a separate Blender flag and does not say which node graph is present. The existing diagnostics do not list the actual node names or links, so do not claim that no Blender light node tree exists based solely on `cycles_custom_active=False`.

### Next source investigation
- Stop changing general light falloff.
- Focus on a single GPU bake luxel at the intersection of two brush faces near the hard edge of spotlight 405.
- Inspect whether face 5828's lightmap UV sample maps exactly onto a polygon boundary and how Cycles GPU handles that sample.
- A controlled test of a tiny spot-edge softness or an inward face-local sample offset may be considered, but preserve ericw/Quake lighting and classic BSP luxel placement in any final fix.
- No new source changes or installer from this MAP inspection. PR #5 remains at 0.21.20 source commit `21344ec1cbbe60edf321958b9d358598bcfe01ed`, CI 300 tests, artifact `14286680280` as above.


## 2026-11-17 — Six pale-blue e1m1 spotlights tie into original edge complaint and bake overbrightness

The user clarified that spotlight 405 is one of the six pale-blue spotlights that originally caused concern. They say the six lights appear as subtle blue shimmers with ericw-tools, but looked far too bright in SLOPGATE's Cycles bake and were involved in the reported lightmap glitch.

### Original complaint context (read from full archive)
The 2026-11-13 report described that game engines blur low-resolution lightmaps; near BSP face boundaries this could produce harsh edges or abruptly cut a light spot off because the blur needs samples outside the face's own lightmap rectangle. This was recorded as **lightmap clipping after engine blur**, not simply a lack of soft luxel values.

Historical edge work:
- 0.21.13: half-luxel support rim for eligible Enhanced BSPX per-face lightmaps. The user reported no visible change in Ironwail or Quake 2021 rerelease; do not repeat/claim that Enhanced-only padding as a fix.
- 0.21.14 candidate: four-point sub-luxel quadrature intended to retain narrow spotlight coverage near luxel-block edges. Runtime confirmation wasn't established in the archive.
- The current classic BSP29 e1m1 problem needs its own investigation; BSPX-specific padding cannot be assumed to affect Ironwail classic output.

### Six spotlight group in decompiled e1m1 MAP
Entities 403–408 are the six pale-blue spotlights:
- all have light=1000, _color=181 238 255, and mangle;
- no explicit angle or _softangle, so ericw defaults: 40-degree outer cone, zero softness (hard edge);
- entity 405 is at (-120,624,144), mangle (0,-30,0), the light the user sees illuminating the current wall;
- others: #403 (80,696,144), #404 (-48,696,144), #406 (-120,504,144), #407 (-216,1688,-16), #408 (472,1688,-16).
One additional similar directed blue 1000-value light exists at entity 427 elsewhere and is outside the 403–408 cluster.

### Do not conflate three observed issues
1. **Engine blur/face-boundary clipping:** the original light spot is abruptly cut at BSP face edges after game lightmap filtering.
2. **Blue-light overbrightness:** these six lights are subtle blue shimmers in ericw, but too bright in SLOPGATE's Cycles bake.
3. **Current NaN:** one invalid Cycles luxel at face 5828 and (-80,640,96), exactly at the intersection of planes x=-80/y=640 on two tech07_2 faces, near the hard cone boundary of #405. 0.21.20 disabling all QSS custom Cycles falloff did not change this failure.

These may interact around the same lights/geometry but the source and acceptance tests differ. A fix to one must not be assumed to fix the others.

### Current investigation constraints
- Stop repeating Enhanced-only edge padding or modifying global light falloff without evidence.
- Inspect the six light entities' effective energy/falloff and compare their baked contributions to ericw. The 0.21.20 report shows the nearest delay-0 lights have cycles_custom_active=False and cycles_profile=native_fallback_delay0, but also says use_light_nodes=True; actual Blender node names/links have not been inspected. Don't claim the light node trees are absent until verified.
- Independently investigate the face-corner luxel / Cycles GPU issue causing the unchanged NaN.
- Any blue brightness correction must be checked with side-by-side lightmap images, not a global brightness slider guess.
- No source, test, installer or merge changes were made for this clarification. Current candidate is still 0.21.20 on open/draft PR #5; see preceding entries for commit, CI and artifact details.


## 2026-11-17 — Current lighting investigation: 0.21.21 fallback correction

- Current candidate source is on PR #5 branch fix/0.21.17-world-aligned-lightmap-charts. Code correction commit: 9d9b650339f3b0be64830290a241126e5c16e4ef. Subsequent test/version/README commits make the current docs branch tip c929614765a5cd299a5a82e01548e9a90763311f before archive/handoff updates.
- Candidate version is 0.21.21. Package bl_info was bumped; package/root README updated. tests/test_lighting.py gained two source-contract checks.
- Important confirmed bug: Blender 5.3's Light.use_nodes is not a reliable on/off switch; it reads True and ignores assignment False. The old 0.21.20 fallback only changed this compatibility property, so custom QSS light shader graphs could remain in the actual node tree. Thus the 0.21.20 all-native-falloff isolation test was inconclusive.
- New fallback explicitly clears the light node tree only if every node carries the QSS ownership marker. Any untagged/user-authored node tree is preserved. Diagnostics now report actual node names/types and whether the graph is QSS-owned, instead of interpreting use_nodes.
- The 0.21.21 candidate has not yet had CI or artifact validation confirmed. Do not send an installer link until the Actions run completes and the ZIP/package is verified.
- User's three acceptance issues remain separate: (1) e1m1 Cycles bake NaN at face 5828 / world (-80,640,96), near light 405 and a perpendicular brush corner; (2) six pale-blue spotlights 403–408 are too bright in SLOPGATE compared with subtle ericw shimmer; (3) original engine blur/face-edge clipping. The new patch primarily makes the light-node fallback test real; it does not claim to fix all three.
- Next: verify CI/artifact; ask user to install 0.21.21, re-import e1m1, bake once, then inspect report fields light_node_tree and light_node_tree_qss_owned for lights 405/404/330. Expected native fallback is an empty node tree (or at least no QSS-owned custom graph). If NaN persists with empty trees, focus on face/corner/GPU bake path. Keep the old atlas rollback.
- No PR merges. No Blender 5.3 runtime validation by assistant.


### 0.21.21 CI and installer verification

- GitHub Actions run 44005218004, job 133778790906, completed successfully on source head c929614765a5cd299a5a82e01548e9a90763311f.
- Python compilation passed; 302 standalone tests passed; Blender add-on package assembly and artifact upload passed.
- Artifact Quake-Surface-Studio-v0.21.21-Blender-Install, ID 14293447941, 313,890 bytes.
- SHA-256: 768aae8f3e6aa04ee34b2390d570f7ba013e844c4844c4fe81fa5301b69c17a8.
- Download: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44005218004/artifacts/14293447941
- Downloaded ZIP was independently checked: 52 entries, ZIP test passed, installable root quake_surface_studio/__init__.py present, local SHA-256 matches GitHub upload digest.
- This verifies CI/package only. No Blender GUI bake or Ironwail runtime test has been performed by the assistant. 0.21.21 remains an experimental candidate on open draft PR #5.


## 2026-11-17 — Latest 0.21.21 build and repeated e1m1 bake result

- User supplied another identical non-finite bake popup: baked=1/165763, source=0/165763, four bad atlas pixels at (1594,2000), (1595,2000), (1594,2001), (1595,2001). This proves the current run still failed, but the popup itself does not identify the installed artifact or show the light-node summary. Do not claim a root cause from this message alone.
- The PR #5 branch has advanced beyond the first 0.21.21 installer. Latest head is 9e72bc5a77b30322ab53b00be0ec139380ae45f4 (commit title: Restore exact Quake Cycles falloff on Blender 5.3 (0.21.21)). This commit was authored by the repository user. Treat the live branch tip as authoritative.
- Why the new commit exists: on Blender 5.3, each fresh light has an untouched default Emission → Light Output node graph. The earlier 0.21.21 build's fallback logic could not distinguish that default graph from a user-authored graph, so it skipped applying QSS's Quake delay-0 / delay-5 Cycles correction. New module light_node_utils.py identifies only the untouched default graph; the QSS falloff graph replaces it, while genuinely edited user nodes are preserved. The distance probe uses guarded reciprocal of the Light Falloff Linear output with distance caps, avoiding the earlier Inf/Inf calculation.
- Latest 0.21.21 CI run 44005701116 / job 133780413705 passed Python compilation, 311 standalone tests and package assembly/upload. Latest artifact ID 14294590886, 316,032 bytes; SHA-256 7bcc940fe7651eaae1a623dcd0cebefc6153c3bf799f63d48f17930561fdf71e. Installer: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44005701116/artifacts/14294590886. ZIP verified locally: 54 entries, clean ZIP test, installable package root present, digest matches GitHub.
- Important: artifact 14293447941 from run 44005218004 is the earlier 0.21.21 revision at c929614 and is superseded. Use artifact 14294590886 for any further test. Same version string, different source revision and ZIP contents.
- The new build restores QSS's intended Quake falloff for delay 0 and 5, so it is also intended to improve the over-bright blue spotlights. It does not claim the one-luxel e1m1 issue is fixed. No Blender runtime or Ironwail test by assistant; PR #5 remains open/draft, no merge.
- If the user's repeated popup was produced by the earlier artifact 14293447941, one controlled retest of latest artifact 14294590886 on a freshly imported e1m1 is worthwhile. If it was already produced by 14294590886, do not request another bake yet.
- After a failure on latest artifact, use Save Lighting Diagnostics without baking again. Request only the Non-finite luxel face/world/light matches section around lights 405/404/330. The decisive fields are light_node_tree and light_node_tree_qss_owned; expected active QSS corrections should show a qss[...] graph and ownership True, with the delay-specific profile active. If those are correct and the same luxel fails, move investigation to BSP face 5828's perpendicular corner and Cycles GPU sample handling rather than changing global light attenuation.
- User-facing explanations should remain in level-designer language. Do not describe this as fixed until a Blender 5.3 runtime bake and an Ironwail lightmap comparison are actually reported.

## 2026-11-17 follow-up — latest 0.21.21 artifact still fails

- User confirmed the repeated one-luxel NaN was produced by the newer artifact 14294590886 (workflow 44005701116; source 9e72bc5...). The earlier 0.21.21 artifact 14293447941 was the previous test. Latest build is not a fix for the NaN.
- Face mapping: BSP face 5828, luxel (9,3), world Quake (-80,640,96). Closest light QSS_light_405 at 64.4981 units; next QSS_light_330 (point) at 77.5629 and QSS_light_404 (spot) at 80.399. Proximity does not conclusively identify the causal lamp.
- The six Nightdive additions QSS_light_403..408 are spotlights with pale-blue color (0.7098,0.9333,1.0), delay 0, raw value 1000/effective display value 500, range 1000, 40-degree cone, no blend. Importer code recognizes mangle/target or spot classname, uses angle/_cone and _softangle, calculates direction and sets Blender object rotation; actual per-light direction is not in the supplied diagnostics.
- Every one of the six is currently user_nodes_preserved_native_fallback, cycles_custom_active=False, light_node_tree_qss_owned=False, and graph summary user-custom[Emission,Light Output]. Importantly, white point light QSS_light_164 is classified the same way, so this is not simply a blue-color exception.
- light_node_utils.is_default_light_node_tree currently expects white Emission Color and Strength 1.0 in addition to strict graph topology/target/mute checks. Diagnostics do not expose actual socket values or link details; exact failed predicate remains unknown.
- Next step: improve node diagnostics and conservatively recognize Blender-generated light graphs matching their Light datablock, without overwriting truly customized graphs. No further bake request until a new build exists. Keep the NaN, six-blue-spotlight brightness/colour fidelity, and BSP lightmap edge clipping as separate acceptance tests.
- No Blender 5.3 runtime validation or Ironwail comparison by assistant; do not mark this fixed. User-facing explanations stay in level-designer terms.


## 2026-11-17 — Original Nightdive e1m1 BSP comparison
- User added the actual failing original files to `testressource26.11.16_01/`: `e1m1_rerel.bsp` and `e1m1_rerel.lit`. The working ericw rebuild is `e1m1_dec01-compile.bsp/.lit`.
- Read-only forensic workflow run: [44097250888](https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44097250888). Analyzer script: `testressource26.11.16_01/analyze_e1m1_bsp_pair.py`; latest analyzer-only commit: `33493c832a63e6e12ad25af6bb5897cba2354d27`. This commit did not alter the production add-on.
- Both BSPs are classic BSP29, each with 428 entities and 252 light entities. Apart from worldspawn, the parsed entity sets match. The six pale-blue Nightdive spotlights retain their entity data in the rebuild; `light405` remains at Quake coordinate `(-120, 624, 144)`. The recompiled worldspawn is malformed/different (ericw log warns about empty key/value pairs), but there is no evidence that this causes the NaN.
- Original face 5828 maps exactly to rebuilt face 7612: same four world vertices, plane, texture `tech07_2`, texinfo mapping, styles, 11x15 luxel grid, and area. The target sample `(-80,640,96)` is inside that face in both BSPs. Both BSPs have valid face/light references and no non-finite vertices. The rebuilt BSP actually has more parser-flagged suspicious/degenerate faces, yet it bakes successfully.
- The current SLOPGATE atlas builder forms a connected coplanar world-aligned chart. Original chart members are faces 5826–5831 (6 faces); rebuilt chart members are 7605–7613 (9 faces). Both chart components have the same plane, world extents `[496,656] x [-256,144]`, dimensions 11x26, atlas size 2048, scale 2, gutter 2. The additional rebuild members only subdivide the low-z part of the plane; only the target face polygon contains sample `(-80,640,96)` in either chart. Thus no adjacent chart face overlaps that sample.
- Absolute atlas placement differs: original chart rectangle `[1574,0,26,56]`, mapping the failed sample to pixel centre `(1594.5,2000.5)`—an exact match for the user's bake diagnostic. Rebuilt chart rectangle `[530,142,26,56]`, mapping the same world sample to `(550.5,1858.5)`. The chart-relative sample coordinate and face-local luxel remain equivalent. This makes atlas-coordinate-dependent Cycles rasterization/UV behaviour a candidate, but does not prove it is the cause; a global BVH/scene-interaction difference also remains possible.
- Recommended discriminating test on the original BSP: use SLOPGATE's existing **Change Lightmap Resolution** operator to rebuild the working atlas at 2x (from the original BSP source) and then bake once. This changes atlas packing/image coordinates without moving lights or editing brushes. It discards generated/painted lightmaps, so preserve a copy of the .blend first if any painted/baked work must be kept. If the NaN disappears, investigate atlas placement/UV sampling; if the same world luxel still fails, shift focus to Cycles shading/geometry-ray interaction. This is a diagnostic test, not a workaround or verified fix.
- No new add-on build/installer was produced, and no Blender runtime test was run by the assistant. Keep the three acceptance tracks separate: face-5828 non-finite luxel; Nightdive spotlight visual fidelity; original engine lightmap edge blur/clipping.


## 2026-11-17 — Session orientation update: current branch tip and E1M1 chart-packing diagnostic

This entry supplements, and where newer supersedes, the earlier November 17 status above. The live refs were checked during the orientation session.

### Live repository / PR state

- Maintained documentation branch `fix/v0.11.1-metadata-style-order-test`: `56628f7585a23e8bc6ca80b9e3bebf91628f99ac` (**Simulate alternate E1M1 chart packing order**, authored 2026-11-17 14:01:24 UTC).
- PR #1 is open/draft, head `56628f7585a23e8bc6ca80b9e3bebf91628f99ac`.
- PR #2 is open/draft, head `66767f0fe7d34db7a29204af1d13dc383ec300ce`, separate import-trace diagnostic.
- PR #3 is open/draft, head `5ea9781e71ea64b9adb70e5ecbda7918e5d1fde9`.
- PR #4 is open/draft, head `15ff4802a32eaa64d83e2c42bcd33761bc124e94`.
- PR #5 is open/draft, head `9e72bc5a77b30322ab53b00be0ec139380ae45f4`, based on PR #4. Keep the #3 → #4 → #5 stack order; PR #2 remains independent.
- No PR was merged during this review. The connector's PR metadata returned `mergeable=false` for #1–#3 and `mergeable=true` for #4–#5 at the time checked; do not treat this metadata as an approval or a merge result.

### New forensic analyzer change on PR #1 documentation branch

Commit `56628f7585a23e8bc6ca80b9e3bebf91628f99ac` changes only `testressource26.11.16_01/analyze_e1m1_bsp_pair.py`:
- Adds an optional reverse-chart-ID ordering to the offline current-QSS chart packing simulation.
- Reports an alternate atlas size, luxel scale, rectangle and predicted pixel coordinate for the known face-5828 sample, alongside the normal predicted coordinate.
- This is a read-only diagnostic simulation. It does not change production add-on code or actual Blender atlas packing.
- No PR-triggered workflow run was returned for this new commit. No result from running the analyzer on the E1M1 resource is recorded here. Do not claim the alternate arrangement eliminates the NaN until the analyzer output is actually inspected, and do not infer a Blender bake result from the simulation.

The preceding commit `778113d9de2c77402926528c09aa9075f65c44d3` archived the original-vs-rebuilt Nightdive BSP forensic comparison. It found that original face 5828 and rebuilt face 7612 are the same world-space wall polygon, with the same texture, texinfo, plane, styles, 11×15 luxel grid and area; the exact failed world sample `(-80,640,96)` is inside both. Their world-aligned chart geometry/extents are equivalent, but the absolute atlas rectangles and resulting sample pixels differ. This makes atlas placement a testable variable, not a proven cause; global scene/BVH interaction remains another possibility.

### Current defect and immediate user-side discriminator

- Latest documented 0.21.21 artifact tested by the user: artifact `14294590886`, source commit `9e72bc5a77b30322ab53b00be0ec139380ae45f4`. The user's Blender 5.3 run still reproduced one non-finite baked luxel out of 165,763, with no bad source luxels. The four invalid atlas pixels map to BSP face 5828, luxel (9,3), Quake position `(-80,640,96)`.
- `spottest02` succeeds on 0.21.19; that small one-light test does not validate the Nightdive E1M1 corner.
- Spotlight 405 is one of six pale-blue Nightdive lights, all with hard 40° outer cones by ericw defaults. Keep three acceptance tracks separate: the face-5828 NaN; six blue spotlights appearing too bright in SLOPGATE compared with ericw; and classic in-game lightmap blur/clipping at face edges.
- Recommended discriminating test remains: save a copy of the .blend; on the original E1M1 BSP, use **Change Lightmap Resolution** to rebuild the atlas at 2×, then bake once without changing map geometry or lights. This rebuild discards generated/painted lightmaps, so the copy is important. If the NaN disappears, investigate atlas UV/layout dependence; if it remains at the same world-space luxel, shift attention toward Cycles face-corner / scene interaction.
- The new reverse-order packing simulation may help choose or interpret an alternate arrangement, but it is not a replacement for this controlled runtime test.

### Work performed in this orientation session

- Read this maintained handoff, the field notes, the archive introduction and latest November 17 archive entries; inspected the live branch head, the two newest relevant commits, current PR metadata, and the new analyzer diff.
- The full archive and 14 supporting workflow PDFs were not exhaustively read in this orientation. Consult them when a specific detail requires deeper source/dialogue verification.
- No add-on source was changed. No tests, builds, installer artifact, Blender bake, Ironwail launch, or PR merge were performed. The archive was appended with this session's orientation findings; this handoff update records the same state.


## 2026-11-17 — Regression investigation requested: original rerelease E1M1 must bake

The user has made the original, unrecompiled official Quake rerelease E1M1 a mandatory acceptance target. They report that older SLOPGATE releases baked it without the current crash, and request a backward investigation of changes made while fixing lightmap edge artefacts. The recompiled BSP is diagnostic evidence only; it is not an acceptable replacement. The user explicitly says the empty `property 1` key in the recompile was user-created and must be ignored as a cause.

### Regression window and certainty

- The earliest documented original E1M1 non-finite bake report in the current archive occurs in the 0.21.18 testing sequence on 2026-11-16.
- 0.21.16 is the last plausible pre-world-chart baseline. The current transcript does **not** yet prove that a named 0.21.16 artifact was the last build on which the original rerelease E1M1 bake completed cleanly. Do not claim this is confirmed.
- Earlier 0.20.2 `Bake complete` log lines are not a clean baseline: the user said the resulting lightmaps looked black. No build ID for a problem-free rerelease E1M1 bake has yet been established.
- The 0.21.13 Enhanced-only half-luxel rim did not visibly improve edge artefacts in Ironwail or the Quake rerelease. It did not alter classic BSP29 fallback data.
- 0.21.14 changed supersampled luxel reduction to four-point quadrature; 0.21.15 fixed detached-face texture export and classic grid alignment; 0.21.16 added conservative shared-coplanar-edge sample reconciliation.
- 0.21.17 introduced shared world-aligned coplanar charts in atlas import/baking and changed classic BSP29 export to sample face-local grids back out of the shared charts. This is the primary regression suspect because it changed atlas layout, UV assignment and the classic export sampling path.
- 0.21.18 added outward-rounded edge luxel filling by sampling the face's own source-grid edge, followed by a guard constraining the extension to the face's classic sample rectangle. This is a secondary suspect to isolate separately.

### Original vs recompiled E1M1 facts

- Original face 5828 and rebuilt face 7612 have the same world-space polygon, vertices, `tech07_2` texture, texinfo, plane, styles, 11×15 sample grid and area. The failed world sample is `(-80,640,96)` in both.
- Both BSPs contain the same 428 entities and 252 lights apart from worldspawn differences; the Nightdive blue spotlights are present with matching light properties. Nearest is light405 at `(-120,624,144)`.
- Their world-aligned chart extents match, but atlas rectangles differ: original `[1574,0,26,56]`, rebuilt `[530,142,26,56]`. The failed world sample maps to `(1594.5,2000.5)` in the original and `(550.5,1858.5)` in the rebuild.
- Original BSP passed the structural checks recorded so far. Rebuild bakes despite more parser-flagged suspicious faces. There is no evidence that the different worldspawn or the intentionally empty `property 1` key explains the success; exclude that key from causal analysis.
- Atlas packing/UV sampling is a testable hypothesis, not yet a proven root cause. Global Cycles scene/BVH interactions and other chart membership/topology differences remain possible.

### Current observed failure

Artifact 0.21.21 ID `14294590886` still reports one non-finite baked luxel out of 165,763, zero non-finite source luxels, and a four-pixel atlas block at `(1594,2000)` through `(1595,2001)`. Attribution: BSP face 5828, luxel (9,3), world `(-80,640,96)`, near light405's hard spotlight cone edge. The pre-bake atlas is restored. `spottest02` passing does not validate original E1M1.

### Next engineering work

1. Find the last user-confirmed good original rerelease E1M1 bake and its exact build/artifact ID from the older transcript and workflow artifacts. Until then, 0.21.16 is a candidate baseline only.
2. Reproduce by bisecting the feature changes against the original BSP. First compare pre-0.21.17 face-local atlas import/export with shared world-aligned charts, changing no light settings. Then isolate 0.21.18 edge-fill and 0.21.14 quadrature separately.
3. Inspect original face 5828's chart membership, UVs, chart attributes, atlas rectangle, sample interpolation neighbours, source samples and write bounds; compare those values to rebuilt face 7612.
4. Keep original unrecompiled E1M1 as the required bake acceptance test. Recompiled E1M1 is a control only.
5. Do not clamp/discard the invalid luxel, adjust spotlight energy to mask it, or blame `property 1`. Track finite original-map bake, spotlight brightness fidelity and in-engine edge filtering as separate acceptance criteria.

No production source changes, new build, Blender bake, Ironwail test or PR merge occurred during this review. This entry records regression archaeology and the next controlled experiments only.



## 2026-11-17 — Confirmed stock E1M1 bake regression depends on six Nightdive spotlights; exact 0.21.18 baseline

### User-confirmed runtime evidence

The user imported original, unrecompiled rerelease E1M1 in the current version, deleted the six Nightdive spotlights in Blender, and the Cycles bake completed. The user identifies **SLOPGATE-0.21.18-Large-Map-Bake-Performance.zip** as the last build that baked the stock/remaster E1M1 successfully.

This is now the last-known-good build by user confirmation. The prior uncertainty about whether 0.21.16 was the baseline is superseded.

### Build identity

- Artifact ID `14188889199`, name `Quake-Surface-Studio-v0.21.18-Blender-Install`.
- Workflow run `43783467279`, successful.
- Exact source `7f182cf97cc1a3aa35c15408d429a478f87e08c2`.
- Size 308,296 bytes; SHA-256 `18499457a52b39b232cce6c4f7567be6c7d028ca29fdcdc70de226ee4cf772e8`.
- Critically, this build already contains the shared world-aligned chart system and 0.21.18 outward-rounded edge-fill correction. Those changes alone are therefore not sufficient to cause the regression.

### Strongest newly identified regression candidate: spotlight edge softness

In known-good 0.21.18, imported spotlight `spot_blend` was assigned by `1 - soft_angle / cone`. With the six Nightdive lights' default `_softangle=0`, Blender received `spot_blend=1.0`.

After the known-good commit:
- `98753c71756fcd7e039578764da56beb2dfbb92d` added a Quake-to-Blender mapping that intentionally maps ericw `_softangle=0` to Blender `spot_blend=0.0` (hard edge).
- `fbd760c774464b3567786cf2e42fd9c52ee11430` applies this helper during BSP light import.
- Test commit `4d5caaeb61c6158d7eff500ee6412d2414331d05` explicitly locks in the 40° / 0° → 0.0 mapping.
- Nightdive entities 403–408 have no explicit `angle` or `_softangle`, so all six changed from Blender's fully softened edge in 0.21.18 to hard edges in the current source.
- The bad face-5828 sample is near the cone edge of spotlight405. This is the clearest spotlight-specific behavioral change after the confirmed good build, and the leading candidate to test.

Do not simply revert this as a final fix yet. The new value is intended to match ericw's hard cone; the real requirement is to make Cycles bake it safely without losing that light shape.

### Other changes after the known-good commit

The 21 commits from `7f182cf` to current `9e72bc5` also include HDR sample preservation, moving calibration after luxel reduction, changes to Cycles falloff distance math, disabling delay-0/all custom falloff for isolation, Blender 5.3 node-tree clearing/classification, and the attempted exact Quake delay-0/5 shader restore. These remain secondary checks. In the diagnostic report from artifact `14294590886`, all six lights were still classified `user_nodes_preserved_native_fallback`, with `cycles_custom_active=False` and `user-custom[Emission, Light Output]` node trees. This means the QSS custom Quake Cycles graph was not active for those lights in that tested build; it weakens that graph as the direct explanation for the result, without excluding other Blender node-tree interactions.

The HDR/calibration changes do not directly alter spotlight geometry. The 0.21.18 chart/export changes were already present in the known-good build.

### Next isolation test

On a fresh import of original stock E1M1:
1. Keep all six Nightdive lights.
2. Change only Blender **Spot Shape → Blend** on lights 403–408 from 0.0 to 1.0, matching the known-good 0.21.18 import values.
3. Bake once, with light energy, directions, atlas resolution and all other settings unchanged.

If the bake succeeds, restore the hard edge one light at a time to isolate which spot(s) trigger the invalid Cycles sample. If it still fails, test the six lights individually / in small groups. Removing all six proves a group dependency, not that every member is independently causal.

No source changes, tests, build, installer, Blender runtime bake, or PR merge were made. This remains an evidence-led isolation step; do not clamp or discard the bad luxel.



## 2026-11-17 — User confirms original rerelease E1M1 bake succeeds with six spotlight Blend values restored

### Confirmed user test

The user retained the original, unrecompiled Quake rerelease E1M1 and all 252 lights, changed only the six Nightdive spotlights' Blender `Spot Blend` values from 0.0 to 1.0, and completed a Full Map Cycles bake.

Exact user report:

```
Bake complete (Full map. ) 252 lights, 110 materials, 5557/5631 faces lit,
157570/165763 raw luxels lit, mean 0.2951, max 30.64, raw mean 3.122,
source mean 0.2947, atlas scale 0.09441, 2 diffuse bounces;
total 3 min 20.9 s (Cycles 3 min 9.2 s).
Switches to Baked Lightmaps preview.
```

This is now a verified-by-user successful bake of the original, unrecompiled rerelease E1M1. It proves the six lights do not need to be deleted; their current hard-edge Blender configuration was the critical variable changed in the successful test.

### Updated root-cause assessment

Known-good SLOPGATE 0.21.18 imported these six lights with `spot_blend=1.0`, because its old formula was `1 - soft_angle / cone` and the Nightdive entities omit `_softangle` (default 0). Later `98753c7` and `fbd760c` changed the mapping so Quake's zero softangle produces Blender `spot_blend=0.0` (hard edge). User's controlled test restored only the six values to 1.0 and the full original map bake succeeded.

This is very strong evidence that the hard-edged spotlight representation introduced after 0.21.18 triggers the non-finite Cycles luxel failure. The previous chart/atlas placement hypothesis is now secondary: the shared world-chart system was already present in the known-good 0.21.18 build and is retained in this successful bake.

### Bake quality evidence

- 252 lights; all six Nightdive spotlights retained.
- 5,557/5,631 faces lit; 157,570/165,763 raw luxels lit.
- mean 0.2951; source mean 0.2947; raw mean 3.122; max 30.64.
- Atlas match scale 0.09441, applied to atlas source matching only.
- 2 diffuse bounces; total 3m20.9s, Cycles 3m9.2s.
- Bake completed and entered Baked Lightmaps preview.

### Required final correction

Do not stop at a manual Blend workaround. Implement a Cycles-safe solution that preserves Quake/ericw's intended hard spotlight cone as closely as possible without producing non-finite luxels. `spot_blend=1.0` is an established successful compatibility reference, but it may make the visible cone edge too soft. Validate both full-map bake success and in-game cone appearance.

The final acceptance test must be a fresh import of the original unrecompiled E1M1 with all six lights, no manual changes to their Blender properties, a successful full-map bake, and a Quake rerelease visual comparison. Keep classic engine face-edge filtering as a separate criterion.

No production code, build or installer changed in this update; only user runtime evidence and the regression assessment were recorded.



## 2026-11-17 — SLOPGATE 0.21.22 candidate: Cycles-safe near-hard spotlight edge

### Source-branch clarification

The current SLOPGATE 0.21.21 source is on `fix/0.21.17-world-aligned-lightmap-charts`, not on this documentation-maintenance branch. This `fix/v0.11.1-metadata-style-order-test` branch has the latest handoff/archive entries but its add-on source snapshot is older. Do not use its add-on folder as the installer source.

### Code change made

- Updated the production source branch to SLOPGATE **0.21.22**, commit `8a138c4d66d6aa16878acd3bde41b9b3578abf29`.
- In `quake_surface_studio (zip me for blender)/lighting.py`, added `CYCLES_MIN_SPOT_BLEND = 0.01`.
- `blender_spot_blend_from_ericw_angles()` now floors any zero-width/invalid blend at 0.01 instead of returning exact zero. Positive `_softangle` values keep their existing proportional mapping, except that values collapsing to zero also receive the finite floor.
- The Quake reference function `ericw_spot_factor()` remains unchanged and still evaluates the exact hard cone. Only Blender's imported Cycles light representation receives the narrow transition.
- Added tests for default zero `_softangle`, positive `_softangle`, zero-width transitions, invalid input, and the unchanged exact Quake reference edge.
- Bumped add-on version to 0.21.22 and added the release note in the source branch README.

### Why 0.01, not 1.0

The user's manual `Spot Blend = 1.0` test proves that a softened Blender spotlight configuration lets the original rerelease E1M1 bake complete, but it is too broad to adopt as the final light shape without visual comparison.

Blender 5.3's Cycles source in `intern/cycles/scene/light.cpp` calculates the spot factor with:

```
spot_smooth = 1.0 / ((1.0 - cos_half_spot_angle) * smooth)
```

Here `smooth` is the spotlight blend value. A zero blend therefore creates an infinite intermediate. The new 0.01 floor keeps the calculation finite while limiting the fade to a very narrow rim, rather than softening the entire cone. The upstream source is available at:
https://github.com/blender/blender/blob/blender-v5.3-release/intern/cycles/scene/light.cpp

This is a mathematically motivated candidate, not yet a user-confirmed bake fix. The unit tests validate the mapping but cannot prove Cycles' actual full-map bake result.

### Validation status and next acceptance test

- Source changes and the version bump are committed; the final 0.21.22 GitHub Actions run is pending at the time of this note.
- No Blender runtime bake or Quake rerelease visual comparison has been performed by the assistant.
- The next test is a **fresh import** of the original, unrecompiled rerelease E1M1 using the 0.21.22 installer, with all 252 lights and no manual property edits. Check that the full-map bake completes with no non-finite luxels.
- Compare the six Nightdive spotlight boundaries against the rerelease/ericw reference. The 0.01 transition is intended to look nearly hard, but this visual check is still required.
- Keep classic in-engine face-edge filtering separate from this Cycles bake acceptance test.

Do not call the regression closed until the fresh-import bake succeeds and the spotlight appearance is acceptable. The earlier user test at Blend=1.0 remains a separate, confirmed workaround result.



### Final CI and installer verification

- Final workflow run: `44180237973`, conclusion **success**.
- Run URL: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44180237973
- Exact source commit tested: `8a138c4d66d6aa16878acd3bde41b9b3578abf29`.
- Python compilation passed.
- Standalone test suite: **312 tests passed** (`Ran 312 tests ... OK`).
- BSP export integrity checks passed.
- Blender-ready install package assembly and artifact upload passed.
- Installer artifact: `Quake-Surface-Studio-v0.21.22-Blender-Install`, artifact ID `14371921535`, size 316,758 bytes.
- Artifact SHA-256: `641b7fe160ee487c87865b076614c5a6a98720730398a8c0695627bc9833c340`.
- Installer page: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44180237973/artifacts/14371921535

These CI results validate the source tests and package, not Blender's actual Cycles runtime. The original rerelease E1M1 full-map bake and six-cone visual comparison remain the decisive user acceptance test.



## 2026-11-17 — User confirms 0.21.22 E1M1 bake completes; residual brightness points to falloff mismatch

### User runtime report

The user reports that the original-map bake now **finishes** using SLOPGATE 0.21.22. This closes the immediate non-finite-luxel bake blocker for their test run. They also report:
- Live preview lights still look very bright.
- Baked lighting is somewhat too bright as well.
- The excess is most noticeable when a light is close to a wall / receiving surface.
- The user suspects the falloff curve differs.

No new bake metrics, screenshots, Blender diagnostic text or in-engine comparison were included in this report. Do not invent a measured brightness ratio.

### Source audit: yes, attenuation mismatch is a strong explanation

The current production source is on `fix/0.21.17-world-aligned-lightmap-charts` at `8a138c4d66d6aa16878acd3bde41b9b3578abf29`. The relevant code is in `lighting.py` and `addon.py`.

ericw-tools documents delay 0 as **linear attenuation**, the default; delay 2 is inverse-square. It also defines `_falloff` as a distance-to-zero setting for delay 0, while worldspawn `_dist` scales fade distance and `_range` scales brightness independently:
- https://ericw-tools.readthedocs.io/en/latest/light.html

SLOPGATE's `blender_live_light_preview_parameters()` explicitly uses native Blender inverse-square lamps as an approximation for delay 0, calibrated to match at the midpoint of the light's radius. Nearer than that reference point, an inverse-square curve rises much faster than Quake's linear curve. This naturally explains why the native live preview looks especially bright near a light and nearby wall. It is not a simple overall brightness multiplier problem.

For Cycles, SLOPGATE has a custom distance correction graph for delays 0 and 5. It reconstructs ericw's linear (delay 0) and soft-inverse-square (delay 5) curves over Blender's inverse-square lamp. Other delay types use a native Blender fallback. The correction graph is only installed when the existing Light node tree is recognized as Blender's untouched default graph; custom/user trees are deliberately preserved.

The previous 0.21.21 diagnostic run for the six Nightdive spotlights recorded:
- `cycles_custom_active=False`
- profile `user_nodes_preserved_native_fallback`
- node summary `user-custom[Emission, Light Output]`

Therefore those lights did not receive the intended exact Cycles falloff correction in that diagnostic run. The 0.21.22 change only altered the non-zero spotlight blend floor; it did not change the light-node classification or Cycles falloff setup. This makes native inverse-square fallback the leading explanation for the residual bright bake, but the same status must be checked in the user's current 0.21.22 file before calling it confirmed.

Blender's Light Falloff node is documented as **Cycles Only**. Eevee ignores light shader node trees, so a Realtime/Eevee live preview cannot use SLOPGATE's exact Cycles node correction and remains an approximation:
- https://docs.blender.org/manual/en/latest/render/shader_nodes/color/light_falloff.html
- https://docs.blender.org/manual/en/5.4/render/cycles/light_settings.html

### Do not "fix" this by lowering global brightness yet

Reducing `_range`, the global light-energy slider or every lamp's energy would lower brightness at all distances. It would not repair the incorrect shape of an inverse-square curve when the intended curve is linear. It could make distant parts of E1M1 too dark while leaving the near-light imbalance in place.

### Next controlled check

On the 0.21.22 imported E1M1, inspect the six Nightdive spotlights (and representative ordinary delay-0 lights) in the current diagnostics:
- `qss_cycles_falloff_active`
- `qss_cycles_falloff_profile`
- `qss_cycles_falloff_error`
- `light_node_tree_qss_owned` / node-tree summary

If the status is still `user_nodes_preserved_native_fallback`, fix the classification/installation path for newly created QSS lights without overwriting genuinely user-authored node trees. Then verify the Cycles graph is active and the brightness-vs-distance curve follows ericw's delay-0 profile. Keep the Eevee/Realtime limitation separate: exact custom light shader graphs are Cycles-only, so Eevee needs either an explicitly labelled approximation or a different preview strategy.

The user should also identify whether the bright live preview was viewed in Realtime/Eevee or Cycles. That affects whether the custom falloff graph can be used at all.

### Status

- **Bake completion:** user-confirmed on 0.21.22.
- **Original E1M1 brightness/falloff fidelity:** still under investigation.
- **0.21.22 automated validation:** 312 tests, Python compilation, BSP export checks and installer packaging passed (workflow `44180237973`, artifact `14371921535`).
- No new source-code change or Blender diagnostic run was performed in this brightness investigation. The two project records were updated with the user's bake success and the falloff analysis.



## 2026-11-17 — E1M1 0.21.22 diagnostics confirm inactive Cycles falloff; 0.21.23 import fix built

### User-provided 0.21.22 diagnostics

The user supplied a full diagnostics report from Blender 5.3.0 for the original E1M1 BSP. Key facts:

- Preview mode: `realtime`; render engine: `BLENDER_EEVEE`.
- RGB source: monochrome BSP lighting; BSPX lumps empty.
- Light energy scale and source-match calibration both 1.0.
- Bake completed: Cycles operator `FINISHED`, 0 non-finite luxels (and 0 non-finite source luxels).
- Last bake mean values: raw mean `3.15409998`; source mean `0.29474011`; final atlas mean `0.29514125`; maximum `33.60558`; normalization `0.09344666`.
- GPU, 4096 samples, 2 diffuse bounces, 2048-pixel atlas, 6,437 receiver faces; successful Cycles bake time 3m02.4s.
- All 252 imported lights were listed. Representative delay-0 and delay-5 lights reported `cycles_profile=user_nodes_preserved_native_fallback`, `cycles_custom_active=False`, and `user-custom[Emission, Light Output]` node trees. The delay-3 entries showed the expected native fallback.
- Last attempted lamp-state block was `n/a`; the imported-light listing above supplies the relevant current node-state evidence.
- The report also showed missing/stale QSS face attributes: 0 entries for 6,605 mesh faces, and 0 entries for 31,052 UV loops. This is separate from the falloff issue. Use a clean fresh import for the next bake test and confirm the face attributes and UV maps are populated before baking/exporting.

### Interpretation

Two separate mismatches explain the reported brightness:

1. The live preview is explicitly Eevee Realtime. Blender ignores light shader node trees in Eevee, so it uses Blender's native point/spot falloff rather than QSS's Cycles correction. This mode is intentionally fast but spatially approximate. Use the QSS **Cycles** preview mode to see the custom delay-0/5 attenuation; it is slower.
2. In the Cycles bake, QSS's intended delay-0 and delay-5 correction graphs were not installed for any of the reported lights. The node classifier rejected Blender's generated starter graph as `user-custom`, and the safety check therefore preserved it instead of replacing it with the QSS graph. The diagnostics' `cycles_custom_active=False` confirms the correction was inactive.

The global source-match pass did its job on the average: final atlas mean 0.295141 is within about 0.14% of source mean 0.294740. However, the raw bake mean was 3.1541 and was multiplied by 0.0934467. A matching average does not guarantee matching local brightness distribution; the maximum luxel remained 33.6056. The uncorrected native inverse-square falloff can create local hot spots near lights/walls even after the global average is normalized. Do not lower global energy/range as a first fix: that changes distant lighting too and does not fix the curve shape.

Blender's 5.3 manual confirms light shader nodes are supported in Cycles and ignored by Eevee:
- https://docs.blender.org/manual/en/5.3/render/cycles/light_settings.html
- https://docs.blender.org/manual/en/latest/render/shader_nodes/output/light.html

### Production source correction: SLOPGATE 0.21.23

Production source branch: `fix/0.21.17-world-aligned-lightmap-charts`.
Final source commit: `8cd21cc144687c0808c8639c8af07962e5351162`.

- Added `light_node_utils.is_safe_to_replace_light_node_tree()` with an explicit one-time permission for a light datablock created by the current QSS import operation.
- The importer now installs the Quake/Cycles correction graph for newly imported delay-0 (linear) and delay-5 (soft inverse-square) lights while it still knows the light datablock was just created by QSS. This safely bypasses the false `user-custom` classification of Blender's starter nodes.
- That permission is not persistent. Later updates still require a fully QSS-owned node tree or a recognized untouched Blender default; user-edited light graphs remain protected.
- Added tests for the explicit first-import permission, protection of an existing custom graph, and the import/update wiring.
- Diagnostics now print `cycles_error` so the next report will reveal why a graph was not installed.
- Lighting-mode descriptions now distinguish fast approximate Eevee Realtime from the slower Cycles preview, which can use the delay-0/5 correction graphs.
- Updated the stale per-light diagnostic note to explain which delay modes are corrected.

### CI and installer

- Workflow run `44192399427`: **success**, exact final source commit `8cd21cc144687c0808c8639c8af07962e5351162`.
- Python compilation passed.
- Standalone suite: **314 tests passed**.
- BSP export integrity checks passed.
- Blender-ready install package assembled and uploaded.
- Artifact: `Quake-Surface-Studio-v0.21.23-Blender-Install`, ID `14377536600`, size 317,905 bytes.
- SHA-256: `3dde455049ce33ebfc8afc5c37205ab9df44ac283100932ef3518896920a5816`.
- Run: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44192399427
- Installer: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44192399427/artifacts/14377536600

### Next acceptance test

This is a source/CI-verified candidate, not yet a user-confirmed runtime fix. The user must:
1. Install 0.21.23 and freshly re-import the original, unrecompiled E1M1 so the new light-node setup and face/UV attributes are rebuilt.
2. Check diagnostics for delay-0/5 lights: `cycles_custom_active=True`, profile `ericw_delay0_linear` or `ericw_delay5_soft_inverse_square`, and empty `cycles_error`. Other delay types continue to use their documented fallback.
3. Switch the QSS lighting mode to **Cycles** to compare the corrected live preview. Eevee Realtime remains an approximation and cannot use the Cycles light-node graph.
4. Run a full-map Cycles bake with all 252 lights. Confirm finite luxels and compare the bright near-wall areas against the original rerelease.

Do not claim that E1M1 brightness fidelity is solved until this fresh-import runtime test passes. The classic engine lightmap edge-filtering artefact remains a separate acceptance criterion.


## 2026-11-18 — E1M1 screenshot/diagnostics review and flat-face edge-fade investigation

User added `screens and diagnostics/v.0.21.21` on the documentation branch (the actual directory name includes the leading dot after `v`). Contents:
- `screenshots_v2.21.21.ora` — 24,305,689 bytes
- `phonglike_lighting_example_ironwail.png` — 234,779 bytes
- `v2.21.12_diagnostics.txt` — 972,623 bytes

The GitHub file connector can read the text diagnostics and the standalone PNG (the PNG was visually inspected), but could not return the 24.3 MB binary OpenRaster file. The ORA was not inspected layer-by-layer in this session. User should attach that ORA directly in chat before any claim is made about comparing all embedded screenshot layers. Do not describe this review as a complete comparison of every screenshot.

### Diagnostic findings

The report is for Blender 5.3.0 and object `e1m1.bsp_QSS`.
- Active preview mode at capture: `source`; render engine: `CYCLES`.
- Source BSPX lump list is empty.
- Light energy scale and source-match calibration are both 1.0.
- Last bake completed: 165,763 sampled luxels; Cycles operator `FINISHED`; zero non-finite baked or source luxels.
- Raw bake mean 0.3433270291; source mean 0.2947401109; final atlas mean 0.2950881173; normalization 0.8584821057; maximum sampled luxel 202.4475658.
- GPU, 4096 samples, 2 diffuse bounces, 2048px atlas, 6,437 receiver faces; bake total 2m19.0s / Cycles operator 2m03.3s.
- Atlas diagnostic max channel 241.6353; face coverage reports 5,531 lit and 100 dark faces out of 5,631 faces in the bake sample set.
- Mesh metadata is healthy in this capture: all 6,605 faces have each QSS face-domain attribute; both texture and lightmap UV maps have 31,052 entries for 31,052 loops.
- Last BSP export took 25.07s, almost all in lightmap patching, but the diagnostic does not record the exact exported path or the export format. It also does not identify whether the exported file was opened by Ironwail.
- Preview mode `source` is significant: `_patch_lightmap_lump()` chooses the original/source lightmap when that mode is active, and the baked atlas only when mode `baked` is active. The diagnostic shows the currently selected mode, not a guaranteed snapshot of the mode at the exact time of the last export. Therefore the Ironwail image might be showing source lighting rather than the Cycles bake; this needs explicit checking.

### Cycles light-node installation status

The diagnostic includes 252 imported light states:
- 232 delay-0 lights use `ericw_delay0_linear`, with `cycles_custom_active=True`, QSS-owned node graphs and empty `cycles_error`.
- 16 delay-5 lights use `ericw_delay5_soft_inverse_square`, also active and QSS-owned with empty `cycles_error`.
- 4 delay-3 lights use `native_fallback`, with correction inactive as expected for the current supported correction set.

This confirms the earlier 0.21.23 fresh-import node-installation defect is not present in this capture. Do not attribute the current differences to missing delay-0/5 correction nodes.

The final mean is within about 0.12% of the source mean, but that is only a global statistic. It does not prove that each face or each local light gradient matches. The high sampled maximum (202.45) and raw atlas maximum (241.64) remain worth inspecting spatially once the screenshot layers are available.

### Visual observation from the accessible PNG

The single standalone Ironwail screenshot (700x500) shows broad, smooth brightness gradients on large grey planar wall faces, with some areas appearing brighter toward the middle and darker toward adjoining vertical boundaries. This is visually reminiscent of Phong shading, but the image alone cannot establish the cause or even prove that the falloff is an unintended edge-only artifact. The other variants are inside the uninspected ORA.

The current importer does not set BSP mesh polygons to smooth shading (no explicit `use_smooth` / `shade_smooth` setup was found in the import path), so this is not presently evidence of Blender smooth vertex normals. Once written to a BSP and displayed by Ironwail, the gradient must be coming from the exported lightmap samples or the engine's lightmap sampling/filtering, not Blender's viewport normal interpolation. Avoid calling it a confirmed Phong/normal bug.

### Source audit relevant to edge fade

Current production source branch: `fix/0.21.17-world-aligned-lightmap-charts`, head at review time: `8cd21cc144687c0808c8639c8af07962e5351162`.

Relevant code:
- `lightmap_export.py`: `world_plane_frame()`, `build_coplanar_face_charts()`, `resample_coplanar_chart_sources()`, `world_chart_pixel_coordinates()`, `sample_rgb_from_world_chart_positions()`, and `sample_classic_face_grid_from_world_chart()`.
- `addon.py`: `_build_lightmap_atlas()` assembles world-aligned coplanar charts, maps the actual BSP face vertices into the lightmap UV atlas, runs the Cycles bake, collapses supersampled blocks, and fills atlas gutters. `_patch_lightmap_lump()` converts atlas pixels back into classic BSP face luxel grids through bilinear sampling.
- Enhanced BSPX export uses `_build_enhanced_lightmap_payload()`, which calls `add_half_luxel_edge_padding()` and writes a `SLPG_LMPAD` marker. This half-luxel rim is not applied to the classic BSP29 fallback branch. The `AUTO` export option chooses Enhanced for upscaled lightmaps, sub-16-unit decoupled luxel spacing, or a source BSP that already contains `DECOUPLED_LM`; otherwise it selects Classic. The diagnostics do not record the final selected export mode, so the engine screenshot's precise path remains unknown.
- Tests in `tests/test_lightmap_export.py` cover bilinear sampling, chart alignment, edge padding values and projection offsets. They are pure helper tests; they do not verify a full Blender Cycles bake of a real BSP followed by a render in Ironwail.

The flat-face edge fade is therefore not yet diagnosed. Plausible areas to isolate are (1) whether the Ironwail export was made from `source` or `baked` preview mode, (2) whether Ironwail received the Classic or Enhanced BSP output, and (3) the atlas/face-boundary sampling and filtering path. The existing half-luxel support code makes the Classic-versus-Enhanced comparison particularly important, but it is not proof that this is the cause.

### Next controlled comparison

1. Attach `screenshots_v2.21.21.ora` directly in chat so each layer can be read and labelled variants can be compared fairly.
2. Confirm the last export was performed while QSS preview mode was explicitly `baked`, not `source`.
3. Export **Both** Classic and Enhanced variants from that same baked atlas; load each exact output file in Ironwail and compare the same player-start view. Keep the filenames distinct and record which one is open.
4. Include a lightmap-only screenshot for each BSP output and a textured screenshot for each. If edge fade appears only in one format, use that to isolate export/engine filtering from the bake.
5. Keep the light-node correction validation separate: this report already confirms the delay-0/5 nodes are installed. Do not change the falloff formulas or add another broad intensity multiplier based on the screenshot alone.

No source code was changed and no new Blender runtime bake or Ironwail runtime test was performed during this review. Treat all edge-fade explanations as hypotheses until the ORA layers and exact exported BSP variants are compared.


## 2026-11-18 — 0.21.24 Enhanced BSPX export repair and optional companion MAP

### User report

The user reported two export failures while exporting E1M1:
- `Linked companion MAP is missing: /app/blender`
- Enhanced BSPX export aborted with `name 'face_info' is not defined`.

The `/app/blender` path came from calling `os.path.abspath("")` when `qss_source_map_path` was empty. That incorrectly converted "no companion MAP is configured" into Blender's working directory and then treated it as a missing .map file.

### Production source changes

Production source branch: `fix/0.21.17-world-aligned-lightmap-charts`.
Final head: `d27e7be286829a019badb556b6c4c30c0c4c2eb4`.
Add-on version: **0.21.24**.

Commit `3fcfd6ac581cde6d910a584e05d2f049d52876b7` — `Fix Enhanced BSPX chart export and decouple MAP sync`:
- In `_build_enhanced_lightmap_payload()`, the world-chart sampling branch used `face_info` without constructing it. It now constructs this per-face context from the validated face-domain mesh attributes and original BSP geometry: world-chart flag, source texinfo, oriented BSP plane normal/distance, shared chart S/T axes and chart S/T origin.
- The sampling path then uses that context to solve the classic face luxel grid onto the shared world chart and sample the correct atlas coordinates.
- Companion MAP preparation failures (missing, stale, ambiguous, unreadable) are now captured as sidecar warnings instead of aborting the BSP export. Existing protections against overwriting a MAP that is not a verified previous SLOPGATE export remain intact. MAP write errors are also reported as warnings after the BSP export.
- Added `tests/test_export_contracts.py`: Enhanced world-chart context is constructed before use, and MAP preparation/commit failures do not abort the BSP export.
- Bumped version to 0.21.24 and documented the change in README.

Commit `d27e7be286829a019badb556b6c4c30c0c4c2eb4` — `Treat absent companion MAP as an unconfigured sidecar`:
- `_qss_prepare_companion_map_export()` now checks the raw linked MAP path before normalizing it. An empty property returns `None` immediately. Only a non-empty path is passed to `os.path.abspath()`.
- Added a regression contract ensuring an empty link is not resolved to the Blender working directory.

### CI and installer

Final workflow run: `44232978822`.
- URL: https://github.com/ChnuckiErdbeer/Quake-Surface-Studio/actions/runs/44232978822
- Exact tested source commit: `d27e7be286829a019badb556b6c4c30c0c4c2eb4`.
- Python module compilation passed.
- **317 tests passed** (`Ran 317 tests in 4.852s; OK`).
- The three new export contracts passed, including:
  - `test_world_chart_face_context_is_defined_before_it_is_used`
  - `test_companion_map_preparation_and_write_errors_do_not_abort_bsp_export`
  - `test_missing_companion_map_link_is_not_resolved_to_blender_working_directory`
- Blender-ready add-on package assembly and artifact upload passed.
- Installer: `Quake-Surface-Studio-v0.21.24-Blender-Install`, artifact ID `14396470461`, size 319,967 bytes.
- SHA-256: `8a4c4dec82249f9382d5dddbc9bbe2b430144f39f2ecd88a80aebdb2bf30ab8b`.
- Installer artifact: https://github.com/ChnuckiErdBeer/Quake-Surface-Studio/actions/runs/44232978822/artifacts/14396470461

CI proves syntax, static export contracts and standalone unit tests; it does not run Blender or Ironwail. A fresh Blender 5.3 Enhanced export and engine load are still required to prove the original E1M1 case is fixed at runtime.

### Extracted ORA review

The user said the ORA had been extracted into the repository. The extracted layer directory was found, but on a separate branch `ChnuckiErdBeer-patch-1` (commit `f78d9e9c6f788bd634a5119c1be2caf0e842e60a`), under `screens and diagnostics/v.0.21.21/screenshots_v2.21.21/data/`. Its `stack.xml` was read and supplies these explicit layer labels:
- layer0: Blender ericw lightmap + texture
- layer1: Blender Eevee preview lightmap + texture
- layer2: Blender Cycles preview lightmap + texture
- layer3: Blender Cycles bake lightmap + texture
- layer4: Ironwail Cycles bake lightmap + textures
- layer5: Ironwail Cycles bake lightmap
- layer6: Ironwail ericw lightmap
- layer7: Ironwail ericw lightmap + textures
- layer8: Ironwail fullbright
- layer9: Blender ericw textures
- layer10: Blender Cycles preview lightmap
- layer11: Blender Eevee preview lightmap
- layer12: Blender ericw lightmap
- layer13: Blender Cycles bake lightmap

The GitHub connector successfully returned/allowed inspection of layer5, layer11, layer12, the small thumbnail and the standalone `phonglike_lighting_example_ironwail.png`. Most other extracted layer images exceed the connector's binary image response limit (about 1 MB raw); their filenames and labels are known from `stack.xml`, but those image pixels were not inspected. Thus this is not a complete pixel-by-pixel comparison of all 14 layers. Ask the user to attach the large extracted PNGs (especially layers 0, 2, 3, 4, 6, 10 and 13) directly in chat if a complete review is required.

Visible images confirm broad continuous brightness variation on some large planar faces. That appearance does not indicate Blender Phong/vertex-normal interpolation by itself: a flat polygon can contain a spatially varying lightmap and the engine interpolates lightmap samples across it. Since the gradient is visible in the lightmap-only Ironwail image, the likely data path is the baked/exported luxel field and/or engine interpolation, not texture shading. This is still a visual interpretation, not a runtime isolation test. The visible Cycles-bake screenshot shows broad light pools and smooth gradients; the visible Blender Eevee and Ericw screenshot variants have noticeably different brightness distributions. Eevee is an approximation, not the correct reference for Quake/Ericw equivalence. The key Blender Cycles-bake and Ironwail Ericw lightmap-only images are among the inaccessible larger files, so their direct comparison remains incomplete.

Do not conflate this visual issue with the Enhanced-export exception: the latter is a confirmed source-level bug and now has a targeted fix, while the precise reason for the flat-face edge fade still needs the Classic-versus-Enhanced controlled export comparison.

### Next user acceptance test

1. Install 0.21.24 from the artifact above.
2. Open the E1M1 Blender file and export Enhanced BSPX directly with no companion MAP linked; it should not mention `/app/blender`. If a linked MAP is missing or stale, the BSP export should still finish and show a MAP sidecar warning.
3. Export Enhanced for a freshly selected `baked` lightmap preview. Confirm the `face_info` traceback is gone and the `.bsp` / `.lit` files are written.
4. Load that exact Enhanced BSP in Ironwail. Also export Classic from the same baked atlas and compare both outputs at the same player-start position. The Enhanced export is the path with half-luxel edge padding; Classic retains the standard BSP29 layout.
5. Report whether the planar edge fade differs between Classic and Enhanced. Do not change light falloff or apply another global brightness adjustment before this comparison.

No Blender runtime export or Ironwail runtime validation was performed by the assistant during this session.


## 2026-11-18 — full cropped JPG comparison at E1M1 info_player_start; branch inventory

User added 14 cropped JPEG files to `screens and diagnostics/v.0.21.21/` on this docs branch. User confirms all screenshots are captured at the E1M1 `info_player_start` viewpoint, corresponding to the first in-game frame. The layer names were matched against the ORA `stack.xml` previously read:
- layer0: Blender EricW/source, textured + lightmap
- layer1: Blender Eevee preview, textured + lightmap
- layer2: Blender Cycles preview, textured + lightmap
- layer3: Blender Cycles bake, textured + lightmap
- layer4: Ironwail Cycles-bake BSP, textured + lightmap
- layer5: Ironwail Cycles-bake BSP, lightmap only
- layer6: Ironwail EricW reference, lightmap only
- layer7: Ironwail EricW reference, textured + lightmap
- layer8: Ironwail fullbright/textures only
- layer9: Blender texture-only
- layer10: Blender Cycles preview, lightmap only
- layer11: Blender Eevee preview, lightmap only
- layer12: Blender EricW/source, lightmap only
- layer13: Blender Cycles bake, lightmap only

All 14 cropped JPGs were successfully opened and visually reviewed. The common player-start location is a strong comparison control; however screenshots from Blender and Ironwail use different application viewports/capture dimensions, so they are compared by corresponding surfaces/landmarks, not exact pixel registration. Their on-screen add-on label reads 0.21.21. Do not treat these images as a test of the later 0.21.24 Enhanced-export repair.

### Visual findings

**Textured views**
- Blender EricW/source (layer0) appears very dark overall in this viewport.
- Eevee preview (layer1) is visibly brighter, particularly around the inner arch and doorway side faces; it spreads a strong light contribution across nearby surfaces. This is consistent with Eevee being an approximation, not a Quake/EricW reference.
- Cycles live preview (layer2) is notably darker than the other rendered views, with localized brightness around the inner arch but much of the corridor nearly black.
- Blender Cycles bake (layer3) shows very bright vertical/angled regions around the inner doorway and comparatively dark foreground/floor and deeper corridor.
- Ironwail Cycles-bake output (layer4) has more readable illumination in the deeper corridor and floor than the Blender baked viewport image. That is a real visual difference worth explaining, but screen/view-transform differences mean it cannot yet be read as a direct raw-value comparison.
- Ironwail EricW (layer7) provides the game-engine reference; compared with layer4, the spatial distribution is not identical. The difference is local, not just a uniform gain change.
- Fullbright (layer8) and Blender texture-only (layer9) are helpful albedo references but are not lighting comparisons.

**Lightmap-only views — primary evidence**
- Ironwail Cycles-bake lightmap (layer5) shows a broad, smoothly filtered light pool on the floor and illuminated inner-arch surfaces. The field falls off over distance; the darkest values remain on surfaces farther from the light sources.
- Ironwail EricW reference lightmap (layer6) also shows broad smooth gradients over the floor and planar surfaces. The bright pool and falloff pattern are similar in broad structure but not identical in extent/intensity. Therefore smooth gradients across flat faces are not unique to SLOPGATE's Cycles bake.
- Blender EricW/source lightmap (layer12) looks much more visibly patchy/blocky than its Ironwail counterpart. The likely explanation is different display/filtering of the low-resolution luxel field, including the engine's interpolation, rather than changed geometry normals.
- Blender Eevee preview lightmap (layer11) is close to washed out in the central lit region and shows different hard/dark transition areas.
- Blender Cycles preview lightmap (layer10) is also very bright/washed out compared with its textured counterpart. Do not assume that untextured white-surface preview values have a one-to-one visual match with the final engine's lightmap display.
- Blender Cycles baked lightmap (layer13) contains large broad brightness regions and visible face/wire overlays. The overlays and viewport representation make it a poor standalone visual substitute for the exported Ironwail lightmap-only view, but the same broad light distribution is evident.

### Updated interpretation of the alleged “Phong-like” edge fade

The cropped JPGs do **not** show a clear, narrow dark halo that consistently tracks every polygon boundary. Instead, the clearest pattern is broad continuous brightness variation tied to the illuminated areas. Importantly, the Ironwail EricW lightmap-only reference (layer6) shows similar smooth gradients on flat surfaces. This means the fade is not, by itself, proof of a SLOPGATE edge bug or Phong/normal interpolation.

A flat BSP face can have changing luxel values and the engine interpolates between them. This creates a smooth light gradient on a planar surface without changing its normal. The EricW layer demonstrates this kind of smooth field exists in the reference too. Current best interpretation: much of the visible effect is expected lightmap spatial variation/filtering, not geometry smoothing. A narrower fade exactly at face perimeters or an obvious dark seam remains worth testing, but it is not established by these screenshots.

### Remaining lighting mismatch

The screenshots suggest:
- Eevee preview is too generous/uneven in the highlighted portal region compared with the EricW reference.
- Cycles live preview and Cycles bake are visibly different from one another.
- Blender baked viewport and Ironwail baked output are also visibly different; engine interpolation/display transform and export sampling remain possible causes.
- Ironwail Cycles bake and EricW have broadly similar light-pool structure, but the local distribution differs. This agrees with diagnostics: source mean 0.2947401109 and final atlas mean 0.2950881173 are within about 0.12%, while max sampled luxel is 202.4476. Global mean calibration does not ensure local spatial match. Raw bake mean was 0.3433270291, atlas-match normalization 0.8584821057, all 165,763 samples finite, 6,437 receiver faces, 4096 samples, GPU, two diffuse bounces and 2048 atlas.
- Source-mesh face attributes and both UV maps were populated in the diagnostic.
- Diagnostic light states: 232 delay-0 lights and 16 delay-5 lights had active QSS Cycles correction profiles; 4 delay-3 lights used native fallback. The report's preview mode says `source`; the screenshots separately show several preview modes. Do not infer that the last export was definitely source or baked solely from that one diagnostic field.

The images do not justify changing the global energy scale or falloff curves. The average already matches closely; any further global multiplier would affect all regions and likely worsen already-bright local areas. 0.21.24 Enhanced export repair has not been runtime-tested yet and concerns export correctness, not this brightness comparison.

### Branch inventory / current working-branch guidance

Repository currently has nine named branches:
- `fix/0.21.17-world-aligned-lightmap-charts`: active production add-on source, currently 0.21.24, head `d27e7be286829a019badb556b6c4c30c0c4c2eb4`. This is the branch to use for the latest add-on work/installer.
- `fix/v0.11.1-metadata-style-order-test`: current handoff/history, diagnostic and new cropped-JPG branch, head at review time `80380186b9046a7bc7f08857d5cb262cfabb284e`.
- `main`: default branch but still add-on version 0.11.0 at review time; it is not the current production source. Do not assume downloading from default `main` gives the newest add-on.
- `ChnuckiErdBeer-patch-1`: contains the original extracted ORA and individual extracted PNG layers.
- `feature/0.21.11-undo-lightmap-edges`, `feature/0.21.12-coplanar-edge-preview-brightness`, `fix/0.21.15-bsp-import-array-trace`, `fix/0.21.15-classic-face-local-lightmap-alignment`, and `fix/0.21.16-coplanar-edge-luxel-stitch`: older development/experiment branches created to isolate specific features or regressions. Several are historical milestones/ancestors of the production source; others have small divergent commits and should be reviewed before deletion. Branches are lightweight reference points, not multiple installed add-ons.

Practical simplification: two branches matter for current work — production source and docs/handoff. Keep historical branches until their unique commits are audited; do not delete or merge them blindly. After the user accepts 0.21.24, consider merging/synchronizing the production source into `main` so the GitHub default branch no longer advertises the old 0.11.0 snapshot.

### Next useful runtime comparison

After the user tests 0.21.24, export Classic and Enhanced from the same explicitly selected Baked preview, load each exact output in Ironwail, and compare with the EricW map at the same info_player_start viewpoint. This isolates the new Enhanced edge-support path from the classic fallback. Do not change light intensity before that controlled comparison.


## 2026-11-18 — BSP2 as the primary target: strategy corrected by user runtime test

User compiled E1M1 with ericw-tools qbsp -bsp2 and loaded the result in the Nightdive rerelease successfully. This directly demonstrates that the user's installed target rerelease accepts the modern BSP2 core format (not merely BSP29). User also reports that the large MachineGames campaign maps are BSP2; record this as user-provided project/engine knowledge, not as a separate file-by-file audit.

This supersedes the earlier handoff assumption that rerelease acceptance of community BSP2 was uncertain. That uncertainty was too conservative once the actual engine test was available.

### Corrected product direction

SLOPGATE should treat modern BSP2 as the primary core map format, with BSP29 retained as an optional legacy compatibility target. The target audience is modern Quake engines, particularly Ironwail and the Nightdive rerelease; original vanilla compatibility should not constrain the main architecture.

ericw-tools documentation says qbsp -bsp2 emits BSP2 for much larger/more complex maps than original BSP29. It separately describes -2psb as an earlier, distinct format. Modern BSP2 and 2PSB/RMQ must not be conflated. Reference: https://ericw-tools.readthedocs.io/en/latest/qbsp.html

### Keep core BSP format and lighting extensions separate

BSP2 and BSPX are not two values in the same format choice:
- BSP29 or BSP2 describes the core BSP header and geometry/lump record layouts.
- BSPX is an optional extension directory carrying extra lumps.

Current SLOPGATE CLASSIC and ENHANCED output modes are not BSP29-versus-BSP2 choices. Both are built around BSP29 serialization. Enhanced writes BSPX data including DECOUPLED_LM, LMSHIFT, LMSTYLE, RGBLIGHTING, and the SLOPGATE SLPG_LMPAD edge-support marker, while preserving a classic fallback lighting sample region. Current bsp.py explicitly rejects BSP2 and 2PSB, and the importer/exporter assumes BSP29 record layouts.

The future UI and internal model should separate:
1. Core BSP format: BSP2 (modern default), BSP29 (optional compatibility).
2. Lighting data: standard face lightmaps or optional BSPX-enhanced/decoupled lightmaps, with RGB data and supported edge-filtering data.
3. Optional compatibility sidecars: e.g. .lit where useful for engines/toolchains that use it.

### Important compatibility qualification

The user's E1M1 test proves Nightdive accepts a BSP2 core map. It does not yet prove that KEX supports every specific BSPX lightmap extension SLOPGATE may attach. Verify individual lump support for the target engines:
- RGBLIGHTING
- DECOUPLED_LM
- LMSHIFT
- LMSTYLE
- SLPG_LMPAD (a SLOPGATE-specific marker; engine behavior must not be assumed)

Ironwail and the rerelease must be tested independently. A valid BSP2 file loading successfully does not by itself validate the optional lighting-lump semantics.

### Recommended implementation plan

1. Refactor BSP parsing/writing around a format-neutral in-memory model and explicit BSP29/BSP2 record adapters. Do not change only the version integer: node/leaf/face/edge/index structures and bounds differ.
2. Add BSP2 import first, with structural/reference validation and round-trip tests against qbsp -bsp2 files, including the user's E1M1 test BSP.
3. Add BSP2 export preserving source geometry/BSP tree and unknown supported extensions, then validate all rewritten offsets and indices.
4. Port standard lightmap and BSPX export to the BSP2 adapter, keeping core format selection orthogonal to lighting extension selection.
5. Run target-engine acceptance tests: BSP2 with standard lighting; BSP2 + RGBLIGHTING; BSP2 + decoupled lightmaps; then each engine separately.
6. Keep BSP29 as an explicit optional export path for people who want vanilla-compatible maps.

Do not start a broad BSP2 conversion in the same change as the current 0.21.24 Enhanced export runtime acceptance test. First collect user feedback on 0.21.24. Then establish a dedicated BSP2 parser/writer feature branch with structural tests before UI changes.

### Current state

Production source is still SLOPGATE 0.21.24 on fix/0.21.17-world-aligned-lightmap-charts; no source code was changed as part of this strategy correction. The existing Enhanced mode is BSP29 + BSPX, not BSP2 + BSPX. The actual rerelease BSP2 acceptance test is user-performed; assistant did not run the engine.


## 2026-11-19 — SLOPGATE 1.0 readiness assessment and roadmap

### Current baseline

Production source branch: `fix/0.21.17-world-aligned-lightmap-charts`.
Current source commit: `d27e7be286829a019badb556b6c4c30c0c4c2eb4`.
Add-on version: **0.21.24**.
Latest CI run: `44232978822`, successful; compilation, add-on packaging and **317 standalone tests** passed. This CI does not run Blender or Ironwail.
Default branch `main` still carries version 0.11.0, not the current production build.
There are no open GitHub issues; five old pull requests remain open from historical development branches. These are repository-maintenance items, not an accurate list of current work.

Assessment: SLOPGATE is a feature-rich pre-1.0 prototype. Its surface-editing workflows and supporting utilities are substantial, but it is not release-ready for the intended modern BSP2 target. The main blockers are BSP2 parser/writer support, runtime validation of current exports, and dependable Quake-style lighting/lightmap behavior.

### Implemented foundations

The current 0.21.24 codebase already includes:
- BSP29 import/export with original geometry/topology retained, and preservation of unrelated standard lumps and unknown BSPX payloads.
- Embedded miptex and external texture import, WAD2 lookup for uncompressed miptex lumps, face detachment, texture painting, Quake-palette quantization/mip rebuilding, transparency and fullbright handling.
- RGB lightmap import from BSPX RGBLIGHTING or QLIT v1 sidecar, editable Blender atlas, original-lightmap snapshot/restore, paint-back and export.
- Quake point/spot/world light import, style metadata, a direct Quake-space luxel solver for the documented static delay 0–5 attenuation modes, and an experimental Cycles diffuse bake.
- Cycles light-node falloff correction for delay 0 (linear) and delay 5 (soft inverse-square). Other delay modes still use native fallback in the Cycles light representation.
- Coplanar world-aligned lightmap charts, classic face-grid resampling, edge reconciliation and Enhanced half-luxel lightmap padding.
- Partial-bake scopes, diagnostics, bake snapshots, map audits, inspector/export validator, navigation/focus/isolate helpers, image undo safeguards and companion MAP light-entity synchronization.
- CI suite of 317 standalone tests and versioned Blender package assembly.

This is meaningful functionality. The 1.0 work is primarily about format modernization, runtime reliability, and finishing the advertised lighting workflow rather than starting from scratch.

### P0 — must be completed before 1.0

**1. Make BSP2 a first-class core format**
- The current `bsp.py` parser explicitly accepts BSP29 only and rejects BSP2 and 2PSB. Current Classic/Enhanced exporters also serialize BSP29.
- Introduce a format-neutral parsed model and explicit BSP29/BSP2 record adapters. BSP2 is not a version-number-only change: nodes, leaves, faces, edges, indices, bounds and other records use different layouts/widths.
- Implement BSP2 import first, then BSP2 export while preserving geometry, visibility/collision lumps, entities and unknown supported BSPX payloads.
- Use the user's `qbsp -bsp2` E1M1 file as a fixture and include at least one larger BSP2 map. Validate round-trip structure and actual loading in Ironwail and the Nightdive rerelease.
- Make BSP2 the modern default. Keep BSP29 as an explicit legacy compatibility option. 2PSB/RMQ should not be included unless a concrete target/user need justifies it.

**2. Separate core format from lighting extensions**
- Replace the current Classic/Enhanced naming as the only format switch. BSP29/BSP2 is the core file layout; BSPX is an independent optional extension set.
- Build a compatibility matrix for Ironwail and KEX/rerelease. Test each extension independently on both engines:
  - RGBLIGHTING
  - DECOUPLED_LM
  - LMSHIFT and LMSHIFT/LMOFFSET variants
  - LMSTYLE and LMSTYLE16
  - QLIT v1 .lit sidecar
  - SLOPGATE's SLPG_LMPAD marker (confirm what it signals and ensure its use never depends on unverified engine-specific behavior)
- Current README says LMSTYLE16, legacy LMSHIFT/LMOFFSET without DECOUPLED_LM, and LIGHTING_E5BGR9 are not implemented. Decide which formats are actually required for 1.0 and reject unsupported variants with clear messages.
- The user's successful qbsp -bsp2 test proves the rerelease accepts the BSP2 core layout; it does not prove every listed BSPX lump is supported. Test them separately.

**3. User-accept and regression-test 0.21.24 export fixes**
- User runtime test still required for the Enhanced `face_info` repair and optional companion MAP behavior.
- Confirm exporting without a linked MAP no longer mentions `/app/blender`; a stale/missing configured MAP must not block BSP output.
- Export from explicitly selected Baked lighting and load the exact resulting BSP in Ironwail. Then run Classic and Enhanced from the same baked atlas and compare lightmap-only output at E1M1 info_player_start.
- Preserve the user's test result, Blender version, source BSP hash, export mode/path and engine build in a reproducible acceptance report.
- Add an actual Blender integration/export test path if feasible; static contracts and pure Python tests cannot expose all bpy context, image, UV, Cycles or serializer integration failures.

**4. Establish lightmap correctness, not just a successful bake**
- Keep the original source lightmap as a deterministic reference and ensure every export records whether the selected layer was source or baked.
- Validate world-chart continuity, face-local classic sampling, supersampling, atlas gutters, edge support and BSP export sampling on actual maps, not just pure helper tests.
- E1M1 screenshots show broad gradients on flat faces in both EricW and SLOPGATE, so smooth fade alone is not proof of Phong shading. The remaining concern is local distribution mismatch and any narrow face-boundary seams.
- Diagnostic source mean 0.2947401 vs final atlas mean 0.2950881 (about 0.12% difference) is a global match only. The sampled maximum 202.4476 shows why local per-face/spatial comparison is essential.
- Do not change global energy or falloff as a substitute for spatially validating the bake.

### P1 — important 1.0 quality and workflow items

**5. Define and improve lighting fidelity**
- Keep three concepts clearly separated in the UI and documentation: live preview, Quake Direct Lightmap Solver, and experimental Cycles artistic/physical bake.
- The Quake direct solver supports documented static point/spot delay 0–5 attenuation, but is not a bit-identical ericw-tools light compiler. It still lacks or approximates radiosity/bounce, dirtmapping, deviance/area sampling, surface emitters, sunlight/sky sampling, projected texture lights, compiler visibility approximations, animated lightstyle time curves and special minlight behavior.
- Cycles currently has explicit correction node graphs only for delay 0 and delay 5. Other delay values fall back to Blender's native lamp model. This distinction needs explicit UI/documentation and targeted test fixtures.
- Live Eevee remains an approximation; Cycles preview and bake do not currently guarantee the same result as ericw-tools.
- Either implement the missing compiler semantics required by the chosen 1.0 fidelity target, or define a smaller, honest supported lighting subset and show warnings when source maps use unsupported features.
- Current static preview combines style samples at full weight; export flattens them into style 0. Animated/flickering lightstyle playback and multi-style preservation need a conscious 1.0 decision.

**6. Finish advertised MAP/light entity editing or narrow its scope**
- MAP sync currently safely updates a subset of existing lights: origin, RGB, intensity and spotlight cone angle.
- Spot direction/target/mangle updates and creating new MAP light entities are not implemented. New lights created in Blender do not yet become new MAP entities.
- Decide whether 1.0 advertises two-way MAP/light editing. If yes, implement and test target/mangle, new/deleted lights and entity key preservation. If no, state clearly that MAP sync is a limited companion update, not a full entity editor.

**7. Document intentional surface-editor boundaries**
- SLOPGATE currently does not rebuild BSP geometry, modify topology, run QBSP/VIS/ericw light, or act as a complete .map/WAD level compiler. The importer/exporter relies on the exact original BSP and preserves geometry rather than rebuilding it. This can remain out of 1.0 scope if SLOPGATE is explicitly a compiled-map surface/texture/lightmap editor.
- Inline movers are represented in a combined mesh, are not independently selectable Blender objects and are not animated.
- Selected-face/selected-light bake scopes protect atlas pixels but do not yet guarantee true Cycles performance acceleration; the full BSP is still evaluated. Selected-light receiver masks are direct-light approximations and may miss indirect-only contribution.
- Only uncompressed WAD2 miptex lookup is supported; compressed WAD2 and WAD3/GoldSrc variants are not.
- Existing conservative Classic-era limits (including 512 miptex entries, 4096 texinfo records and 2048 atlas ceiling) must be revisited as part of BSP2 architecture rather than silently carried into modern output.
- Special shadow modes (_shadowself, _shadowworldonly, _switchableshadow) are not fully ericw-equivalent.

### P2 — polish and release engineering

**8. Release/compatibility matrix**
- Declare and test supported Blender versions and operating systems. CI currently validates standard-Python compilation/tests and packages the add-on; it is not an interactive Blender test.
- Exercise install, upgrade, disable/re-enable, multiple open maps, save/reopen .blend, image-paint undo, bake undo/restore, export cancellation and error recovery in real Blender.
- Maintain a small repeatable engine acceptance suite in Ironwail and KEX: import/export, textures, BSPX RGB lightmaps, decoupled lightmaps, styles, moving models and representative large BSP2 maps.
- Update user documentation around the modern BSP2-first workflow, supported BSPX variants, texture/WAD limits, lighting semantics and recovery.
- Synchronize production source into default `main` (currently 0.11.0) once the branch strategy is agreed, close/archive stale development PRs, create tagged releases, and provide a single authoritative installer/release page.

### Proposed 1.0 definition of done

1. BSP2 is the default supported import/export format and is tested on real medium/large maps. BSP29 remains an optional compatibility output.
2. Supported BSPX lighting extensions work on both Ironwail and the Nightdive rerelease, or are rejected/documented accurately.
3. No data loss in round-trip tests for geometry, entities, visibility/collision lumps, textures, lightmaps and unknown preserved extensions.
4. Texture painting, face detachment, palette conversion, lightmap painting, undo/restore and export all pass real Blender acceptance checks.
5. Lighting behavior has a declared scope and repeatable reference comparisons; known approximations are visible to the user.
6. 0.21.24 export repairs have passed the user's actual Blender and engine tests; no critical export traceback remains.
7. No critical/high-severity known issues in the supported workflow; install/upgrade and recovery procedures are documented.
8. The default branch, version metadata, installer and release notes all identify the same 1.0 release.

### Recommended order

A. First, get the user's 0.21.24 Enhanced export acceptance result and close the immediate E1M1 export/seam question.
B. Then create a dedicated BSP2 parser/import branch with fixtures and structural tests. Do not combine it with lightmap changes.
C. Add BSP2 export and validate all unchanged/preserved lumps.
D. Add BSP2 + BSPX lighting extensions and test each target engine separately.
E. Close the highest-impact lighting gaps and decide what MAP sync/mover capabilities belong in 1.0.
F. Run the Blender/engine regression matrix, update docs and default branch, and tag 1.0.

### Overall assessment

The core surface-editing product is substantial; the main 1.0 risk is not a lack of convenience features. It is the gap between an increasingly capable BSP29 prototype and a reliable BSP2-first tool with predictable Quake lighting and tested engine exports. Do not inflate the 1.0 scope into a full QBSP/VIS/map geometry editor unless that becomes an explicit product goal.
