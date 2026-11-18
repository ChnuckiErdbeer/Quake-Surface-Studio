# SLOPGATE

## Current development build

SLOPGATE **0.21.21** — BSP29 lighting investigation build.

This candidate fixes Blender 5.3 light-node handling. Blender creates a default light-node setup automatically, and SLOPGATE previously treated that untouched setup as if the user had customized it. It therefore skipped installing the Quake-style Cycles falloff correction, leaving delay-0 and delay-5 lights much brighter near their sources than ericw's intended curves.

SLOPGATE now recognizes only Blender's untouched default light graph as safe to replace. It installs the Quake delay-0 linear and delay-5 soft inverse-square corrections, while preserving genuinely customized light-node graphs. The distance calculation also uses a guarded reciprocal and bounded values to avoid invalid math at extreme distances.

The e1m1 one-luxel bake failure is **not yet confirmed fixed**. This candidate is the first one intended to exercise the actual Quake Cycles falloff graphs on Blender 5.3; the earlier 0.21.20 native-falloff test did not isolate the graph behavior for already-imported lights. We still need a Blender 5.3 runtime bake to confirm the result.

The world-aligned coplanar lightmap charts, detached-face local-texture export correction, classic BSP29 seam handling, HDR calibration and large-map sampling improvements are retained. Automated tests and package assembly run in GitHub Actions; CI does not replace Blender 5.3 bake or Ironwail runtime testing.
