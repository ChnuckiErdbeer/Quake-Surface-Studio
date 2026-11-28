"""Manual Blender 5.3 Eevee render probe for SLOPGATE's chart-capture experiment.

UI use (recommended):
    1. Open this file in Blender's Scripting workspace.
    2. Press "Run Script" in the Text Editor.

The probe creates a separate temporary scene, renders it with Eevee Next,
loads the PNG into Blender, then removes the temporary scene. It does not
delete or modify objects, render settings, or lights in the user's scene.

Background use:
    blender --background --python manual_eevee_lightmap_probe.py -- \
        --output /tmp/qss_eevee_probe.png

This is a disposable scene-level API probe, not a production lightmap baker.
"""

import argparse
import math
import os
import sys
import tempfile
import time

import bpy
from mathutils import Vector


DEFAULT_RESOLUTION = 256
DEFAULT_OUTPUT = os.path.join(
    bpy.app.tempdir or tempfile.gettempdir(),
    "qss_eevee_probe.png",
)
RESULT_IMAGE_NAME = "QSS Eevee Probe Result"


def arguments():
    """Read optional command-line overrides; Text Editor runs use defaults."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--resolution", type=int, default=DEFAULT_RESOLUTION)
    return parser.parse_args(argv)


def make_material(name, color):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        raise RuntimeError("Could not find the Principled BSDF node.")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    return material


def make_mesh_object(scene, name, vertices, faces, material):
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj, mesh


def remove_if_unused(collection, datablock):
    if datablock is not None and datablock.users == 0:
        collection.remove(datablock)


def cleanup_probe_scene(scene, meshes, materials, lights, cameras, world):
    """Remove only datablocks created by this probe."""
    if scene is not None and scene.name in bpy.data.scenes:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

        for mesh in meshes:
            remove_if_unused(bpy.data.meshes, mesh)
        for material in materials:
            remove_if_unused(bpy.data.materials, material)
        for light in lights:
            remove_if_unused(bpy.data.lights, light)
        for camera in cameras:
            remove_if_unused(bpy.data.cameras, camera)
        remove_if_unused(bpy.data.worlds, world)

        bpy.data.scenes.remove(scene)


def configure_scene(scene, resolution, output_path):
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.filepath = output_path


def build_probe_scene(resolution, output_path):
    """Build the test scene exclusively through Blender's data API."""
    scene = bpy.data.scenes.new("QSS Eevee Probe [Temporary]")
    meshes = []
    materials = []
    lights = []
    cameras = []
    world = None

    try:
        configure_scene(scene, resolution, output_path)

        world = bpy.data.worlds.new("QSS Eevee Probe World")
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background is None:
            raise RuntimeError("Could not find the World Background node.")
        background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs["Strength"].default_value = 0.0
        scene.world = world

        receiver_mat = make_material(
            "QSS Probe Receiver Material", (0.8, 0.8, 0.8)
        )
        blocker_mat = make_material(
            "QSS Probe Blocker Material", (0.5, 0.5, 0.5)
        )
        materials.extend((receiver_mat, blocker_mat))

        receiver_vertices = [
            (-4.0, -4.0, 0.0),
            (4.0, -4.0, 0.0),
            (4.0, 4.0, 0.0),
            (-4.0, 4.0, 0.0),
        ]
        receiver, receiver_mesh = make_mesh_object(
            scene,
            "QSS Probe Receiver",
            receiver_vertices,
            [(0, 1, 2, 3)],
            receiver_mat,
        )
        meshes.append(receiver_mesh)

        half = 0.75
        z_bottom, z_top = 1.2 - half, 1.2 + half
        blocker_vertices = [
            (-half, -half, z_bottom),
            (half, -half, z_bottom),
            (half, half, z_bottom),
            (-half, half, z_bottom),
            (-half, -half, z_top),
            (half, -half, z_top),
            (half, half, z_top),
            (-half, half, z_top),
        ]
        blocker_faces = [
            (0, 3, 2, 1),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (1, 2, 6, 5),
            (2, 3, 7, 6),
            (3, 0, 4, 7),
        ]
        blocker, blocker_mesh = make_mesh_object(
            scene,
            "QSS Probe Shadow Caster",
            blocker_vertices,
            blocker_faces,
            blocker_mat,
        )
        meshes.append(blocker_mesh)

        light_data = bpy.data.lights.new("QSS Probe Area Light", type="AREA")
        lights.append(light_data)
        light_data.energy = 1800.0
        light_data.shape = "DISK"
        light_data.size = 1.0
        light_obj = bpy.data.objects.new("QSS Probe Area Light", light_data)
        scene.collection.objects.link(light_obj)
        light_obj.location = (-2.5, -2.0, 4.0)
        direction = Vector((0.0, 0.0, 0.0)) - light_obj.location
        light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

        camera_data = bpy.data.cameras.new("QSS Chart Camera")
        cameras.append(camera_data)
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = 8.0
        camera = bpy.data.objects.new("QSS Chart Camera", camera_data)
        scene.collection.objects.link(camera)
        camera.location = (0.0, 0.0, 10.0)
        camera.rotation_euler = (0.0, 0.0, 0.0)
        scene.camera = camera

        return scene, meshes, materials, lights, cameras, world

    except Exception:
        cleanup_probe_scene(scene, meshes, materials, lights, cameras, world)
        raise


def inspect_render(image):
    """Sample enough pixels to confirm a non-empty image without huge copies."""
    width, height = image.size
    pixel_count = width * height
    stride = max(1, math.ceil(pixel_count / 8192))
    samples = []

    for pixel_index in range(0, pixel_count, stride):
        offset = pixel_index * 4
        red = float(image.pixels[offset])
        green = float(image.pixels[offset + 1])
        blue = float(image.pixels[offset + 2])
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        samples.append(luminance)

    if not samples or max(samples) <= 0.02:
        raise RuntimeError("Eevee render readback appears empty.")

    lit_samples = sum(value > 0.02 for value in samples)
    return {
        "sample_count": len(samples),
        "lit_samples": lit_samples,
        "max_luminance": max(samples),
        "mean_luminance": sum(samples) / len(samples),
    }


def main():
    args = arguments()
    if bpy.app.version < (5, 3, 0):
        raise RuntimeError(
            "This probe targets Blender 5.3 or newer; found "
            + bpy.app.version_string
        )
    if args.resolution < 32 or args.resolution > 4096:
        raise ValueError("Resolution must be between 32 and 4096.")

    output_path = os.path.abspath(os.path.expanduser(args.output))
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    original_area = bpy.context.area
    probe_scene = None
    meshes = []
    materials = []
    lights = []
    cameras = []
    world = None
    image = None

    try:
        (
            probe_scene,
            meshes,
            materials,
            lights,
            cameras,
            world,
        ) = build_probe_scene(args.resolution, output_path)

        started = time.perf_counter()
        bpy.ops.render.render(write_still=True, scene=probe_scene.name)
        elapsed = time.perf_counter() - started

        old_image = bpy.data.images.get(RESULT_IMAGE_NAME)
        if old_image is not None:
            bpy.data.images.remove(old_image, do_unlink=True)

        image = bpy.data.images.load(output_path, check_existing=False)
        image.name = RESULT_IMAGE_NAME
        metrics = inspect_render(image)

        print(
            "QSS_EEVEE_PROBE "
            f"blender={bpy.app.version_string} "
            f"engine=BLENDER_EEVEE_NEXT "
            f"resolution={args.resolution}x{args.resolution} "
            f"render_seconds={elapsed:.4f} "
            f"sampled_pixels={metrics['sample_count']} "
            f"lit_samples={metrics['lit_samples']} "
            f"max_luminance={metrics['max_luminance']:.5f} "
            f"mean_luminance={metrics['mean_luminance']:.5f} "
            f"output={output_path}"
        )

    finally:
        if probe_scene is not None:
            cleanup_probe_scene(
                probe_scene, meshes, materials, lights, cameras, world
            )

    # When run from the Text Editor or Python Console, show the PNG in-place.
    # Other editor areas are left alone.
    if image is not None and original_area is not None:
        if original_area.type in {"TEXT_EDITOR", "CONSOLE"}:
            original_area.type = "IMAGE_EDITOR"
            original_area.spaces.active.image = image
        elif original_area.type == "IMAGE_EDITOR":
            original_area.spaces.active.image = image


if __name__ == "__main__":
    main()
