# Quake-Surface-Studio

## Current development build

SLOPGATE **0.21.16** — BSP29-only development build.

Classic BSP29 export now reconciles matching lightmap samples only along shared coplanar BSP edges, and only when both faces belong to the same model, use identical light styles, and their classic 16-unit luxel grids intersect at the same world-space positions. Non-coplanar joins, differently styled surfaces, unaligned grids, corners and face interiors are left unchanged. Both RGB QLIT and monochrome classic fallback samples are updated.

The detached-face local-texture export correction from 0.21.15 is retained. The earlier 0.21.13 half-luxel rim remains limited to Enhanced BSPX DECOUPLED_LM; it does not change the classic BSP29 fallback.

Python tests and package assembly are checked in GitHub Actions. Blender 5.3 export/bake and Ironwail/Quake rerelease comparisons are not claimed as runtime-tested until performed.
