# Quake-Surface-Studio

## Current development build

SLOPGATE **0.21.15** — BSP29-only development build.

The detached-face paint atlas remains shared inside Blender, but each edited face is now exported as its own face-local miptexture. The classic BSP29 texinfo therefore retains its face-local projection rather than inheriting the atlas tile's compressed scale and offset. This keeps neighboring coplanar faces' classic lightmap sample grids aligned at shared edges. Export still enforces the conservative 512 classic miptexture limit.

The 0.21.13 half-luxel rim remains limited to the Enhanced BSPX `DECOUPLED_LM` payload; it does not change the classic BSP29 fallback read by Ironwail's classic path.

Automated Python tests and package assembly are intended to run in GitHub Actions. Blender 5.3 export/bake and Ironwail/Quake rerelease comparisons are not claimed as runtime-tested until performed.
