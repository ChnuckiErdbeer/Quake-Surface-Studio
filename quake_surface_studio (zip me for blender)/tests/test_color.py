import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import color


class ColorEncodingTests(unittest.TestCase):
    def test_quake_palette_byte_is_preserved_for_srgb_byte_image(self):
        source = 128
        actual = color.quake_byte_to_srgb_code(source)
        self.assertAlmostEqual(actual, 128 / 255.0, places=7)
        # The old importer incorrectly stored the linearized value in an sRGB
        # byte buffer, which caused Blender to linearize the channel again.
        self.assertGreater(actual, 0.49)

    def test_byte_image_pixel_is_not_srgb_encoded_twice_on_export(self):
        encoded = 128 / 255.0
        actual = color.blender_pixel_to_quake_code(encoded, is_float_buffer=False)
        self.assertAlmostEqual(actual, encoded, places=7)

    def test_float_image_pixel_is_encoded_from_scene_linear_on_export(self):
        # sRGB 128/255 corresponds to approximately 0.216 scene-linear.
        encoded = color.blender_pixel_to_quake_code(0.2158605, is_float_buffer=True)
        self.assertAlmostEqual(encoded, 128 / 255.0, places=4)

    def test_palette_channels_are_clamped(self):
        self.assertEqual(color.quake_byte_to_srgb_code(-1), 0.0)
        self.assertEqual(color.quake_byte_to_srgb_code(300), 1.0)


if __name__ == '__main__':
    unittest.main()
