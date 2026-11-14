# Quake-Surface-Studio
blender add on for importing, manipulating and exporting quake bsp files.

## Current development build

SLOPGATE **0.21.13** — BSP29-only development build. The undo regression runner
is now non-invasive and global Ctrl+Z testing is parked while feature testing
continues.

Enhanced BSPX export adds a half-luxel support rim to eligible per-face
`DECOUPLED_LM` lightmaps and writes the `SLPG_LMPAD` marker to prevent the rim
from being added again after re-import. This is an experimental edge-filtering
mitigation, not a proven renderer fix. It does **not** change the classic BSP29
fallback: renderers that ignore `DECOUPLED_LM` (including the inspected
Ironwail classic path) will not benefit from this rim. Runtime support for this
extension in the Quake rerelease has not yet been verified.

Python tests and the install package are checked in GitHub Actions. Blender
GUI baking and in-engine lightmap comparisons still require manual validation.
