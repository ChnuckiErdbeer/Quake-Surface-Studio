# SLOPGATE

## Current development build

SLOPGATE **0.21.19** — BSP29-only development build.

This candidate changes how Cycles handles Quake delay-0 lights. The experimental custom falloff used by the previous build is disabled for these lights; Cycles now uses Blender's regular point-light falloff with SLOPGATE's existing energy calibration. This is a deliberate reliability-first approximation, not an attempt to reproduce ericw lighting exactly. The delay-5 correction remains unchanged.

This change targets the single non-finite luxel reported during the e1m1 bake. It must still be tested in Blender 5.3 against e1m1 and the one-light spottest before the lighting issue can be considered resolved. The failed-bake rollback and face/light diagnostics remain enabled.

The world-aligned coplanar lightmap charts, detached-face local-texture export correction, classic BSP29 seam handling and large-map sampling improvements are retained. Automated tests and package assembly run in GitHub Actions; CI does not replace Blender GUI bake or Ironwail runtime validation.
