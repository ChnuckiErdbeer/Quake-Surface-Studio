# Quake-Surface-Studio

## Current development build

SLOPGATE **0.21.18** — BSP29-only development build.

The 0.21.17 world-aligned coplanar chart implementation is retained. This build removes repeated full-BSP face/style reconstruction from per-face sampling in post-Cycles diagnostics and the Quake direct-light bake, reusing one parsed metadata cache per pass. Classic face-grid sampling from a shared chart now uses an affine fast path that avoids constructing an XYZ tuple for each luxel. GitHub Actions compiles the add-on, runs the standalone suite, and assembles the Blender ZIP. Blender 5.3 and Ironwail runtime validation remain outstanding; the residual edge artefact is not yet claimed fixed.

The detached-face local-texture export correction from 0.21.15 is retained. The earlier 0.21.13 half-luxel rim remains limited to Enhanced BSPX DECOUPLED_LM; it does not change the classic BSP29 fallback.

Python tests and package assembly are checked in GitHub Actions. Blender 5.3 export/bake and Ironwail/Quake rerelease comparisons are not claimed as runtime-tested until performed.
