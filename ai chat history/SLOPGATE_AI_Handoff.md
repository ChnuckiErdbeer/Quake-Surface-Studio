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

## Current source/build baseline

Last inspected source commit before the current documentation-only handoff updates:

- Commit: a5e5be55050ecce6532222aeb0d19eb017cb1254
- Add-on version: **0.20.8**
- Version fields: quake_surface_studio (zip me for blender)/__init__.py and addon.py
- Latest recorded successful CI package run: 42958030442
- Companion converter GUI CI run: 42958030452
- Install artifact: Quake-Surface-Studio-v0.20.8-Blender-Install
- Artifact ID: 13827248365
- Artifact size: 241,052 bytes
- SHA-256: 0798ac71cf207af5c985a94cb2dcf941d6b8907657d96b322a50f40b543df160
- Recorded expiry: 2027-02-09.
- Automated Python tests, converter GUI tests and Python compilation passed for that build.

**Important:** 0.20.8 is an experimental build, not a fully validated release. The assistant has not verified its actual behavior in Blender 5.2. No SLOPGATE Cycles bake, Eevee render, QBSP compile or Ironwail run was performed by the assistant for this baseline. Before more source edits, check the live branch head; documentation-only commits may have advanced it after the source commit above.

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

## New lighting design decision — 2026-11-11 (planned, not implemented)

The main use case is now **new maps authored with SLOPGATE in mind**. Re-rendering existing ericw-targeted maps is an edge case: useful as a rough import/tweak starting point, not a goal of pixel-perfect parity. Performance and reliable native Blender behavior take priority over reproducing ericw's exact attenuation curves.

### Mode selection using the existing delay key

- delay 2 marks a **SLOPGATE-native light**. SLOPGATE creates the specified Blender light type and maps the SLOPGATE-specific keys directly to Blender light properties.
- delay 0, 1, 3, 4 and 5 remain legacy ericw-compatible import modes. Approximate them using ordinary Blender light properties. Prioritize reasonable illumination at nearby walls/receivers; this is a rough starting point for adjustment, not a promise of exact ericw output.
- delay 2 is also ericw's inverse-square point-light mode, so it is a useful compatibility choice for point/spot lights when light is scaled appropriately.

### Light types and existing Quake keys

- Add a type selector, provisionally _sl_type with values point, sun, spot, area; default is point. The user originally wrote _SL_*; lowercase is recommended for consistency with Quake/ericw keys, but the prefix is not yet finalized.
- light remains the base brightness input. Reuse _color unchanged for standard RGB color.
- Reuse existing target / mangle / angle conventions for orientation and spot setup wherever possible. Do not invent duplicate orientation fields before reviewing existing behavior.
- For ericw fallback, use its recognized semantics where appropriate: _sun identifies an entity sun; mangle controls sun direction; _surface selects faces whose texture receives a surface-light template. ericw's _surface template currently copies lights across matched faces at roughly 128-unit spacing and about 2 units above each surface. _suntexture can restrict a sun to a named texture; by default ericw sunlight is emitted from sky-content faces.
- A Blender Sun is a directional light object, not a light emitted from sky-texture polygons. Keep sky visibility/background separate from direct sunlight. The plan must specify that sky-textured faces are excluded from inappropriate lightmap receiving (and decide separately whether they should cast shadows); do not create one duplicate Sun lamp per sky face. A world environment/background may complement the Sun, but is not a substitute for a shadow-casting directional Sun.

### Proposed SLOPGATE light fields

The first fields are the user's proposal; the suffixes for additional Blender properties are a draft schema to review before implementation:

- _sl_temperature: when valid (Blender 5.2 range 800–20000 K), enable temperature mode.
- _sl_tint: optional RGB tint multiplier for the temperature-derived color; default neutral white. Exact combination behavior must be tested in Blender 5.2.
- _sl_power: explicit Blender light energy override. Any negative value means “unset”; zero is a valid explicit value. If unset, derive Blender energy from light and the configured conversion scale.
- _sl_exposure: map to Blender exposure in EV; default 0.
- _sl_normalize: boolean override; any negative value means inherit Blender's default.
- _sl_radius: negative means inherit; map only to the type-appropriate source-size property (do not assume one universal meaning across point, spot, sun and area).
- _sl_soft_falloff: boolean override where Blender supports that property; negative means inherit.
- Other Blender light controls can follow a consistent _sl_ + property-oriented naming scheme, with type applicability documented. Candidate shared controls include shadow enable, diffuse/specular/transmission/volume factors, and custom cutoff distance. Candidate area-specific controls include shape, size X, size Y and spread. Do not add every property blindly; define and test a stable useful subset first.

### Intensity conversion settings

- Reuse the existing scene-level qss_light_energy_scale as the first candidate for the Quake light → Blender energy multiplier rather than adding a duplicate control.
- Add a separate area/surface-light multiplier only if required by calibration, as the user anticipates.
- _sl_power is an explicit native Blender energy override; when set, it should bypass the automatic light conversion multiplier. _sl_exposure remains an independent EV control.
- Blender light types do not all use identical physical energy units (for example point-light energy is documented in W, while Sun energy is W/m²). Verify the visual calibration by type rather than assuming one multiplier produces physically equivalent results.
- Temperature mode is an alternative to _color; when temperature is active, _sl_tint can tint it. When temperature is absent/invalid, _color remains the normal cross-compiler RGB path.
- Preserve delay 2 point-light defaults as an inverse-square native point source; tune the global conversion multiplier so a default light value is close in ericw, Cycles and Eevee. Measure, do not guess.

### Area / surface-light design still needs a focused decision

Recommended direction: retain the standard ericw _surface texture selector for compatibility, and let a SLOPGATE delay 2 template specify how Blender creates the corresponding area emitters on matching BSP faces. Avoid simply copying ericw's dense grid of point lights, which can look spotty. Prototype whether the best Blender representation is one Area light per matched face, a face-derived emitter mesh/material, or a subdivided emitter for large/irregular polygons. A normal standalone _sl_type area light with no _surface key can create one ordinary Blender Area light at origin. This surface-linked emitter strategy is not implemented yet.

### Key naming and editor definitions

- ericw-tools conventionally uses a single leading underscore for compiler/tool-specific keys (_color, _sun, _surface, etc.). FGD references show underscore-prefixed keys are common for compile-time properties. TrenchBroom entity properties are string key/value pairs; the FGD provides editor types, defaults and help text. No reason for a double-underscore prefix was found. Recommend a consistent lowercase namespace such as _sl_ (or a longer _slopgate_ namespace if collision avoidance is preferred); decide once before populating maps/FGD.
- Do **not** create the FGD file yet. Once the schema is stable, base the SLOPGATE definitions on the official rerelease FGD, add the documented SLOPGATE fields with types, defaults, choices and clear help text, and retain the original Quake fields.

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
