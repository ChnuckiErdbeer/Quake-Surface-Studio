# Quake-Surface-Studio

## Current development build

SLOPGATE **0.21.17** — BSP29-only development build.

Connected coplanar faces with matching model ownership and resolved light styles now share a world-aligned luxel lattice in the Blender atlas. Classic BSP29 export retains each face's original texture projection and sample dimensions, sampling those classic face grids from the shared chart. Quake direct baking, Enhanced BSPX export and partial-bake chart scopes are being integrated against the same metadata. This is a development implementation; no Blender 5.3 or Ironwail runtime validation is claimed yet.

The detached-face local-texture export correction from 0.21.15 is retained. The earlier 0.21.13 half-luxel rim remains limited to Enhanced BSPX DECOUPLED_LM; it does not change the classic BSP29 fallback.

Python tests and package assembly are checked in GitHub Actions. Blender 5.3 export/bake and Ironwail/Quake rerelease comparisons are not claimed as runtime-tested until performed.
