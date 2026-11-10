# Slipgate / ericw-tools light calibration run

The repository's `lighttest/` folder already contains the 18-room calibration map:

- 6 attenuation delays (0–5)
- 3 light values per delay (50, 300, 900)
- white `_color` and `wait 1`
- each point light is 8 Quake units above the center of its floor

## Important correction to the current source map

Fifteen light entities currently have `targetname` values such as `d0_50` and `d3_900`. In ericw-tools, `targetname` on a light does not work as an inert label: it makes the light switchable. The committed light log reports exactly 15 switchable light styles and also warns that a face exceeded the four-style limit. The clean test copies created by the script replace these labels with inert `_qss_test_id` keys. The source `.map` and `.bsp` remain untouched.

## Run on Linux

Put `run_lighttest_calibration.py` beside `lighttest01-compile.map` in the repository's `lighttest/` folder, then run:

```bash
cd /path/to/Quake-Surface-Studio/lighttest
python3 run_lighttest_calibration.py --compile
```

The script uses the ericw-tools path recovered from the original compile log by default:

```text
/mnt/sde1/FPS/IdTech2/QuakeDev/##tools/ericw-tools-2.0.0-alpha11-Linux
```

To override it:

```bash
python3 run_lighttest_calibration.py --compile \
  --tools-dir "/mnt/sde1/FPS/IdTech2/QuakeDev/##tools/ericw-tools-2.0.0-alpha11-Linux"
```

## What it creates

A new timestamped folder under `lighttest/`, containing two independent compiler references:

- `attenuation_only/`: `targetname` removed, `_anglescale 0`, bounce and dirt disabled. This isolates radial attenuation.
- `angle_default/`: same clean setup, but `_anglescale 0.5`, so the default surface-incidence term is retained.

For each variant, it runs `qbsp -splitturb`, `vis`, and `light -verbose -nocolor -bounce 0 -dirt -1`. It deliberately omits the production run's `-extra4`, `-soft 2`, `-phong`, `-bounce 1`, `-dirt 1`, and surface-light settings so that bounce, ambient occlusion, oversampling and smoothing do not obscure the direct attenuation comparison.

It saves the compiler logs, a `run_report.json`, and `luxel_samples.csv`. The CSV samples the actual upward-facing floor surface directly below each light and at several radial distances in four directions. It locates that surface from the compiled BSP geometry (rather than assuming a fixed floor height), then reads the corresponding lightmap luxel. It records both the requested sample height and the detected floor height (`sample_z`), the compiled BSP luxel value, the Slipgate ericw attenuation formula, the surface-angle factor, and the combined theoretical value.

All outputs are copies in a new folder. The repository's original MAP/BSP and existing compile logs are not overwritten.

## What to send back

Send the generated timestamped results folder as a ZIP, especially:

- both `luxel_samples.csv` files
- both `run_report.json` files
- both `*-light.log` files

The two generated BSPs can also be imported into Slipgate to compare the clean references visually. This script generates compiler reference data; it does not automatically change or calibrate Blender lamp energies yet.


## Sampling fix (2026-11-10)

The first run successfully compiled both reference BSPs but wrote `NO_FLOOR_LUXEL` for all 594 sample points. The sampler had two assumptions that did not match the compiled geometry: it used a hardcoded floor height, and it reversed a face normal without reversing the plane distance for back-sided BSP faces.

The updated script now:
- applies the BSP face-side sign to both the plane normal and plane distance;
- finds the highest valid upward-facing floor face beneath each sample's XY position;
- projects the sample onto that actual floor and reads its lightmap luxel;
- computes source-to-floor distance using the detected floor height;
- writes the detected height in the new `sample_z` CSV column.

The source MAP/BSP remain untouched. A successful compile alone is not proof that sampling works: check the final summary for `missing=0` (or inspect any remaining non-OK rows) before treating the CSV as calibration data.
