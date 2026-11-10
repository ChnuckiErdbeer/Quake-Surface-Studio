import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import xml.etree.ElementTree as ET
from io import BytesIO

from PIL import Image

from ora_preview import read_ora_layers, load_ora_layer


def png_bytes(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class OraPreviewTests(unittest.TestCase):
    def make_ora(self, directory):
        path = Path(directory) / "sample.ora"
        root = ET.Element("image", {"version": "0.0.1", "w": "4", "h": "3"})
        stack = ET.SubElement(root, "stack")
        ET.SubElement(stack, "layer", {
            "name": "Visible red", "src": "data/layer0.png",
            "opacity": "1.0", "visibility": "visible", "x": "1", "y": "1",
        })
        ET.SubElement(stack, "layer", {
            "name": "Hidden blue", "src": "data/layer1.png",
            "opacity": "1.0", "visibility": "hidden", "x": "0", "y": "0",
        })
        with ZipFile(path, "w") as archive:
            archive.writestr("mimetype", "image/openraster", compress_type=ZIP_STORED)
            archive.writestr("stack.xml", ET.tostring(root), compress_type=ZIP_DEFLATED)
            archive.writestr("data/layer0.png", png_bytes(Image.new("RGBA", (2, 1), (255, 0, 0, 255))))
            archive.writestr("data/layer1.png", png_bytes(Image.new("RGBA", (1, 1), (0, 0, 255, 255))))
        return path

    def test_reads_layer_metadata_in_stack_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_ora(temp)
            width, height, layers = read_ora_layers(path)
            self.assertEqual((width, height), (4, 3))
            self.assertEqual([x["name"] for x in layers], ["Visible red", "Hidden blue"])
            self.assertTrue(layers[0]["visible"])
            self.assertFalse(layers[1]["visible"])
            self.assertEqual((layers[0]["x"], layers[0]["y"]), (1, 1))

    def test_renders_layer_at_its_canvas_offset(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_ora(temp)
            _w, _h, layers = read_ora_layers(path)
            preview = load_ora_layer(path, layers[0], checker_size=1)
            self.assertEqual(preview.size, (4, 3))
            self.assertEqual(preview.getpixel((1, 1)), (255, 0, 0))
            self.assertNotEqual(preview.getpixel((0, 0)), (255, 0, 0))

    def test_rejects_missing_stack_xml(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.ora"
            with ZipFile(path, "w") as archive:
                archive.writestr("mimetype", "image/openraster")
            with self.assertRaises(ValueError):
                read_ora_layers(path)


if __name__ == "__main__":
    unittest.main()
