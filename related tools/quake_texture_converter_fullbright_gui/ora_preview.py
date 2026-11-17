"""Small OpenRaster reader used by the texture-converter GUI.

The converter writes flat, full-canvas ORA layers. This reader also honours
layer offsets and opacity so the GUI can inspect each layer independently.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_ora_layers(filename):
    """Return (canvas_width, canvas_height, layer_records) for an ORA file."""
    path = Path(filename)
    with ZipFile(path, "r") as archive:
        try:
            root = ET.fromstring(archive.read("stack.xml"))
        except KeyError as exc:
            raise ValueError(f"{path} is missing stack.xml") from exc

    if _local_name(root.tag) != "image":
        raise ValueError(f"{path} does not contain a valid OpenRaster image")

    try:
        width = int(root.attrib["w"])
        height = int(root.attrib["h"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{path} has invalid canvas dimensions") from exc

    if width < 1 or height < 1:
        raise ValueError(f"{path} has invalid canvas dimensions")

    layers = []

    def visit_stack(stack):
        for child in list(stack):
            kind = _local_name(child.tag)
            if kind == "layer":
                src = child.attrib.get("src", "")
                if not src:
                    continue
                try:
                    opacity = float(child.attrib.get("opacity", "1"))
                except ValueError:
                    opacity = 1.0
                layers.append({
                    "name": child.attrib.get("name") or Path(src).name,
                    "src": src,
                    "x": int(child.attrib.get("x", "0")),
                    "y": int(child.attrib.get("y", "0")),
                    "opacity": max(0.0, min(1.0, opacity)),
                    "visible": child.attrib.get("visibility", "visible") == "visible",
                })
            elif kind == "stack":
                visit_stack(child)

    for child in list(root):
        if _local_name(child.tag) == "stack":
            visit_stack(child)

    return width, height, layers


def load_ora_layer(filename, layer_record, checker_size=12):
    """Load one ORA layer into a checkerboard-backed RGB image for preview."""
    path = Path(filename)
    width, height, _layers = read_ora_layers(path)
    src = layer_record["src"]

    with ZipFile(path, "r") as archive:
        try:
            payload = archive.read(src)
        except KeyError as exc:
            raise ValueError(f"ORA layer image is missing: {src}") from exc

    with Image.open(BytesIO(payload)) as source:
        source.load()
        layer = source.convert("RGBA")

    opacity = float(layer_record.get("opacity", 1.0))
    if opacity < 1.0:
        alpha = layer.getchannel("A").point(lambda value: round(value * opacity))
        layer.putalpha(alpha)

    # Composite onto the ORA canvas, clipping layers whose offsets extend
    # outside its bounds.
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    x = int(layer_record.get("x", 0))
    y = int(layer_record.get("y", 0))
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + layer.width)
    bottom = min(height, y + layer.height)
    if right > left and bottom > top:
        crop = layer.crop((left - x, top - y, right - x, bottom - y))
        canvas.alpha_composite(crop, (left, top))

    # A checkerboard makes transparent areas visible without changing the
    # layer pixels stored in the ORA document.
    background = Image.new("RGB", (width, height), (86, 86, 86))
    draw = ImageDraw.Draw(background)
    tile = max(4, int(checker_size))
    for row in range(0, height, tile):
        for col in range(0, width, tile):
            if (row // tile + col // tile) % 2:
                draw.rectangle(
                    (col, row, min(width - 1, col + tile - 1),
                     min(height - 1, row + tile - 1)),
                    fill=(122, 122, 122),
                )
    background.paste(canvas, (0, 0), canvas.getchannel("A"))
    return background
