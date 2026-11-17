# SLOPGATE

## Current development build

SLOPGATE **0.21.20** — BSP29-only diagnostic development build.

This candidate temporarily uses Blender's native Cycles falloff for **all** imported Quake lights, including delay-5 lights. The goal is to isolate the one repeatable non-finite luxel still seen in e1m1 after delay-0 lights were switched to native falloff in 0.21.19. It is a diagnostic lighting approximation, not the intended final Quake light model. Quake Direct remains a separate path.

The Save Lighting Diagnostics report now records, for the nearest lights around a bad luxel and for all active-map lights, the selected falloff mode, whether custom light nodes are active, and spotlight size/blend. This verifies that the test setting was actually applied.

If e1m1 bakes successfully with 0.21.20, the remaining custom delay-5 Cycles shader is the next place to investigate. If the same luxel still fails, custom Quake falloff shaders can be ruled out and the next investigation should focus on the affected face, its material/UVs, or Cycles' treatment of that sample.

The world-aligned coplanar lightmap charts, detached-face local-texture export correction, classic BSP29 seam handling and large-map sampling improvements are retained. Automated tests and package assembly run in GitHub Actions; CI does not replace Blender 5.3 bake or Ironwail runtime testing.
