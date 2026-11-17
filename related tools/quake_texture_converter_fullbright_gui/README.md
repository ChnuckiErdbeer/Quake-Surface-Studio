# Quake Palette Texture Converter

A Python command-line tool for converting source textures to an indexed PNG using a 256-colour Quake-style palette. It can also process a folder of images and export an editable OpenRaster (`.ora`) project for each conversion. The converter creates SLIC superpixels and merges adjacent superpixels into larger material zones. Ramp fitting evaluates the distribution of actual pixel colours in a zone rather than only its average. Each zone receives a primary ramp plus a small set of best-fit candidate ramps; pixel matching can use those candidates to preserve multiple painted hues within the same material zone. The merge logic deliberately down-weights luminance because these inputs are already-authored game textures with painted highlights, baked shadows and limited apparent depth; tonal variation should not automatically become a separate material.

## Files

Keep these files together:

- `conv_layers.py` — the converter.
- `conv_settings.ini` — default conversion settings.
- `quake.pal` — the 256-colour JASC-PAL palette file. The palette is not bundled with the script; supply your own compatible palette.

The script expects a **256-entry JASC-PAL** palette. By default it looks for `quake.pal` in the current working directory. You can change the `palette` setting in `conv_settings.ini` to an absolute path, or pass `--palette` on the command line.

## Requirements

- Python 3.9 or newer is recommended.
- Pillow
- NumPy
- SciPy
- scikit-image

On Pop!_OS / Ubuntu, create a virtual environment and install the dependencies from the directory containing the script:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install Pillow numpy scipy scikit-image
```

If virtual-environment creation reports that `venv` is unavailable, install the distribution package `python3-venv` first.

## Basic use

### Convert one image

Provide the input image and the output PNG filename:

```bash
.venv/bin/python conv_layers.py input.tga output.png
```

### Convert one image and create an editable project

Add `--layers` to create an OpenRaster project beside the PNG. The ORA file has the same base name:

```bash
.venv/bin/python conv_layers.py input.tga output.png --layers
```

You can choose a specific ORA filename in single-image mode:

```bash
.venv/bin/python conv_layers.py input.tga output.png --layers my_project.ora
```

Open the `.ora` file in an application that supports OpenRaster, such as GIMP or Krita. The **Final texture** layer is visible by default. The **Original source** layer is included unchanged but hidden by default. Ramp-contribution and diagnostic layers are also included and hidden; toggle them in the layer panel as needed. The diagnostics now include both **SLIC superpixels** (the initial small regions) and **material zones** (the merged areas that actually receive palette ramps).

The indexed PNG is the game-ready palette-indexed output. OpenRaster layers are ordinary RGBA layers and are intended for inspection and editing, not as a replacement for the indexed PNG.

### Convert a whole folder

Pass a folder instead of a filename. By default, output goes into a `converted` subfolder inside the input folder:

```bash
.venv/bin/python conv_layers.py tga
```

Create both PNG and ORA files for every supported image:

```bash
.venv/bin/python conv_layers.py tga --layers
```

Choose a different output folder:

```bash
.venv/bin/python conv_layers.py tga converted --layers
```

Batch mode scans only the specified folder (not its subfolders). Supported extensions are `.tga`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.pcx`, and `.webp`. Each output uses the source filename with a `.png` extension; when `--layers` is enabled, a matching `.ora` is also written.

## Settings

The script reads `conv_settings.ini` from the same directory as `conv_layers.py` by default. Edit the values under `[conversion]`, save the file, and run the converter again. Command-line options override the corresponding INI values.

Current defaults:

```ini
[conversion]
palette = quake.pal
ramps = neutral,dark_earth,blue_grey,olive_dark,red,ochre,warm_earth,tan,purple_dark,purple_warm,stone,green_grey,yellow_ochre,blue
fullbright_start = 224
segments = 180
compactness = 10.0
detail = 0.35
detail_radius = 1.2
coherence = 0.025
material_merge_threshold = 0.055
material_luminance_weight = 0.20
material_chroma_limit = 0.075
ramp_candidates_per_zone = 3
```

Parameter guide:

| Setting | Meaning |
|---|---|
| `palette` | Path to the 256-entry JASC-PAL palette. Relative paths are resolved from the directory where the command is run. |
| `ramps` | Comma-separated palette ramp families used for normal colour matching. All fourteen non-fullbright ramp families are enabled by default to avoid losing source hues. |
| `fullbright_start` | First fullbright palette index. With the default `224`, indices 224–255 are excluded from normal matching; the full 256-entry palette is still written to the PNG. |
| `segments` | Approximate initial SLIC superpixel count. These are subsequently merged into material zones; lower values start with larger building blocks. |
| `compactness` | SLIC shape regularity. Higher values favour more compact, regular regions. |
| `detail` | Strength of subtle local-contrast enhancement. `0` disables it. |
| `detail_radius` | Spatial scale used for local-detail enhancement. Larger values affect broader variations. |
| `coherence` | Encourages neighbouring material zones to use consistent palette ramps. Higher values increase ramp sharing. |
| `material_merge_threshold` | How readily adjacent superpixels merge into one material zone. Higher values create fewer, larger zones; lower values preserve more separate zones. |
| `material_luminance_weight` | How much light/dark differences affect material identity. Lower values help keep painted shadows and highlights in the same material zone. This is intentionally low for existing game textures. |
| `material_chroma_limit` | Maximum chroma difference allowed for a merge. Lower values protect boundaries between differently coloured materials. |
| `ramp_candidates_per_zone` | Number of best-fit ramps available to pixels within a material zone. Higher values preserve more hue variation; lower values enforce a more uniform ramp. |

The default values are the established baseline. Change one parameter at a time when tuning results so the visual effect is easier to assess.

## Command-line options

```text
--settings FILE          Use a different INI settings file
--layers [FILE.ora]      Also export an OpenRaster project
--palette FILE           Override the palette path
--ramps LIST             Override the comma-separated ramp list
--fullbright-start N     Override the first fullbright index
--segments N             Override the SLIC region count
--compactness FLOAT      Override SLIC compactness
--detail FLOAT           Override detail enhancement amount
--detail-radius FLOAT    Override detail enhancement radius
--coherence FLOAT        Override neighbouring-ramp coherence
--material-merge-threshold FLOAT  Control how readily adjacent regions merge
--material-luminance-weight FLOAT Control the influence of light/dark differences
--material-chroma-limit FLOAT     Maximum chroma difference allowed for merging
--ramp-candidates-per-zone N       Candidate palette ramps available per zone
```

Example using a different segment count without editing the INI file:

```bash
.venv/bin/python conv_layers.py input.tga output.png --layers --segments 220
```

To use a different settings file:

```bash
.venv/bin/python conv_layers.py --settings another_settings.ini tga --layers
```

## Notes

- Normal colour matching excludes the fullbright range beginning at `fullbright_start`; it does not delete those entries from the output palette.
- The converter does not apply dithering.
- Material merging is adjacency-only: distant areas are not joined simply because they have similar colours.
- Luminance is deliberately down-weighted during material-zone merging because these inputs are already-authored game textures, not photographs. Strongly different chroma still helps preserve material boundaries.
- For more consistent, larger material zones, raise `material_merge_threshold` slightly. If different materials start merging together, lower it or lower `material_chroma_limit`. If painted shadows are still split into separate zones, lower `material_luminance_weight`. Change one setting at a time and inspect the **Diagnostic - material zones** layer.
- The script writes PNG output in indexed (`P`) mode with the complete 256-colour palette.
- All fourteen non-fullbright ramp families are enabled by default. The zone ramp scorer evaluates a sample of actual zone pixels (not just the average colour), and the default three candidate ramps allow genuine colour variation within a painted material to survive quantization.
- In batch mode, use `--layers` without an explicit ORA filename. Each input gets its own ORA file. An explicit ORA filename is supported only for single-image mode.
- If a batch contains a failed image, the script reports the failure and continues processing the remaining images; its final exit status indicates whether any failed.


## Transparency

Transparent pixels are written as Quake palette index 255, with the PNG transparency
entry set accordingly. This index is reserved for transparency in the output and is
never selected by normal colour matching.

- Sources with an alpha channel (including indexed PNG palette transparency) use alpha
  automatically. Alpha values below `alpha_threshold` (default 128) become transparent;
  other pixels are opaque.
- Sources without alpha can use an optional RGB colour key: `--color-key FF00FF`.
  Matching is exact by default. `--color-key-tolerance 8` allows up to 8 levels of
  difference in each RGB channel.
- When both alpha and a colour key are available, alpha takes precedence.
- Indexed source images are analysed by counting actually used palette entries; unused
  palette entries do not influence conversion.

Examples:

```bash
# Alpha is detected automatically
.venv/bin/python conv_layers.py input.tga output.png

# Treat magenta as transparent in a source without alpha
.venv/bin/python conv_layers.py input.bmp output.png --color-key FF00FF

# Allow slight variation around the colour key
.venv/bin/python conv_layers.py input.png output.png --color-key FF00FF --color-key-tolerance 8
```

The alpha threshold and colour-key tolerance can also be set in `conv_settings.ini`.

## Desktop GUI (Pop!_OS / Linux)

The GUI is `conv_gui.py`. Launch it with the same Python environment that has Pillow, NumPy, SciPy and scikit-image installed:

```bash
.venv/bin/python conv_gui.py
```

The GUI provides side-by-side source and converted-image previews. The zoom slider magnifies the centre of each preview while keeping both preview panes at a fixed size; this is useful for small game textures. The palette-ramp families are selectable as individual checkboxes and each has a short illustrative gradient swatch. The checked ramp list is written to the settings file and used for subsequent conversions. In folder mode, previews update only after a file has finished converting. Enable **Convert subfolders recursively** to include nested directories; the output directory mirrors the input directory structure, with each converted image written as a PNG. The output directory is excluded from input scanning when it is inside the source tree.

The GUI starts the converter with `sys.executable`, so it uses the same Python interpreter and virtual environment as the GUI itself.

## Recursive command-line batch conversion

To include subfolders and preserve their relative paths in the output directory:

```bash
.venv/bin/python conv_layers.py source_folder output_folder --recursive
```

For example, `source_folder/doors/metal.tga` becomes `output_folder/doors/metal.png`.

## GUI preview and batch review controls

The GUI's preview is updated only after a source file has completed conversion. It keeps the last completed input/output pair visible while the next file is being processed. Uncheck **Display previews** to skip image loading/display work during a batch.

**Pause after current file** lets the current conversion finish, then pauses before starting the next file. While paused, settings can be edited; clicking **Resume conversion** saves the current settings and applies them to files that have not started yet. Use **Previous** and **Next** to browse completed source/output pairs. **Reconvert selected** runs the selected source again to its previous output path using the current settings; it does not silently rewrite other completed files.

When an ORA project exists for the selected image, the GUI lists its layers in stack order and displays the selected layer over a checkerboard transparency background. Use the layer selector or arrow buttons to inspect the diagnostic layers. If a separate ORA destination is selected, recursive batches preserve the same relative subfolder structure there.


## Fullbright mask support

For a source texture named `metal_panel.tga`, place a mask named `metal_panel_fullbrights.png` in the **same directory**. It must have exactly the same dimensions. White (grayscale value >= 128) marks fullbright texels; black leaves the source texel on the normal conversion path.

The converter automatically detects these masks by default. Disable detection with `--no-fullbright-masks`. Fullbright texels are matched only against palette indices `fullbright_start` through `254`; index `255` remains reserved for transparency. Source transparency takes precedence over the fullbright mask. ORA exports include a fullbright-mask diagnostic layer and a fullbright-pixel contribution layer.

The GUI also has an optional separate ORA destination directory. The stop control finishes the current file and then stops the batch.

Launch on Linux with `./launch_converter.sh` (make executable first with `chmod +x launch_converter.sh`) or double-click the included desktop launcher after allowing it to launch as a program.
