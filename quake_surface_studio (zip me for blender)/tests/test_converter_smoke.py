import configparser
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as exc:
    raise unittest.SkipTest(f"Converter test dependencies are not installed: {exc}")


PACKAGE_DIR = Path(__file__).resolve().parents[1]
CONVERTER = PACKAGE_DIR / "quake_texture_converter.py"
SETTINGS = PACKAGE_DIR / "quake_texture_converter.ini"


class QuakeTextureConverterSmokeTests(unittest.TestCase):
    def test_default_zone_ramp_candidates_match_tested_value(self):
        config = configparser.ConfigParser()
        self.assertTrue(config.read(SETTINGS))
        self.assertEqual(config.getint("conversion", "ramp_candidates_per_zone"), 5)

    def test_converter_writes_an_indexed_png_using_the_supplied_palette(self):
        with tempfile.TemporaryDirectory(prefix="qss_converter_smoke_") as temp:
            root = Path(temp)
            source = root / "source.png"
            output = root / "converted.png"
            palette_path = root / "quake.pal"

            palette_lines = ["JASC-PAL", "0100", "256"]
            palette_lines.extend(
                f"{index} {(index * 3) % 256} {(index * 7) % 256}"
                for index in range(256)
            )
            palette_path.write_text("\n".join(palette_lines) + "\n", encoding="ascii")

            pixels = np.zeros((32, 32, 3), dtype=np.uint8)
            pixels[:, :16] = (92, 67, 44)
            pixels[:, 16:] = (51, 91, 142)
            pixels[::4, ::4] = (180, 132, 72)
            Image.fromarray(pixels, mode="RGB").save(source)

            command = [
                sys.executable,
                str(CONVERTER),
                str(source),
                str(output),
                "--palette", str(palette_path),
                "--settings", str(SETTINGS),
                "--segments", "8",
                "--detail", "0",
            ]
            completed = subprocess.run(
                command,
                cwd=str(PACKAGE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"Converter command failed:\n{completed.stdout}",
            )
            self.assertTrue(output.is_file(), msg=completed.stdout)
            with Image.open(output) as converted:
                self.assertEqual(converted.mode, "P")
                self.assertEqual(converted.size, (32, 32))
                self.assertEqual(len(converted.getpalette() or []), 768)


if __name__ == "__main__":
    unittest.main()
