"""Manual Blender 5.3 Eevee render probe for SLOPGATE's chart-capture experiment.

Run:
    blender --background --python tests/manual_eevee_lightmap_probe.py -- --output /tmp/qss_eevee_probe.png

This is a disposable scene-level API probe, not a production lightmap baker.
"""
import argparse
import os
import sys
import time

import bpy


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/qss_eevee_probe.png")
    parser.add_argument("--resolution", type=int, default=256)
    return parser.parse_args(argv)


def main():
    args = arguments()
    if bpy.app.version < (5, 3, 0):
        raise RuntimeError(
            "This probe targets Blender 5.3 or newer; found "
            + bpy.app.version_string
        )
    if args.resolution < 32 or args.resolution > 4096:
        raise ValueError("Resolution must be between 32 and 4096.")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        # Orphaned datablocks are harmless; do not remove linked data.
        pass

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    world = bpy.data.worlds.new("QSS Eevee Probe World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.0, 0.0, 0.0, 1.0
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = world

    receiver_mat = bpy.data.materials.new("QSS Probe Receiver")
    receiver_mat.diffuse_color = (0.8, 0.8, 0.8, 1.0)
    receiver_mat.use_nodes = True
    receiver_bsdf = receiver_mat.node_tree.nodes.get("Principled BSDF")
    receiver_bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1.0)
    receiver_bsdf.inputs["Roughness"].default_value = 1.0

    blocker_mat = bpy.data.materials.new("QSS Probe Blocker")
    blocker_mat.diffuse_color = (0.5, 0.5, 0.5, 1.0)
    blocker_mat.use_nodes = True
    blocker_bsdf = blocker_mat.node_tree.nodes.get("Principled BSDF")
    blocker_bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    blocker_bsdf.inputs["Roughness"].default_value = 1.0

    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, 0.0))
    receiver = bpy.context.object
    receiver.name = "QSS Probe Receiver"
    receiver.data.materials.append(receiver_mat)

    bpy.ops.mesh.primitive_cube_add(size=1.5, location=(0.0, 0.0, 1.2))
    blocker = bpy.context.object
    blocker.name = "QSS Probe Shadow Caster"
    blocker.data.materials.append(blocker_mat)

    light_data = bpy.data.lights.new("QSS Probe Area", type="AREA")
    light_data.energy = 1800.0
    light_data.shape = "DISK"
    light_data.size = 1.0
    light_obj = bpy.data.objects.new("QSS Probe Area", light_data)
    scene.collection.objects.link(light_obj)
    light_obj.location = (-2.5, -2.0, 4.0)
    direction = (0.0, 0.0, 0.0) - light_obj.location
    light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    camera_data = bpy.data.cameras.new("QSS Chart Camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 8.0
    camera = bpy.data.objects.new("QSS Chart Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, 0.0, 10.0)
    camera.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = camera

    scene.render.filepath = os.path.abspath(args.output)
    bpy.context.view_layer.update()
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - started

    image = bpy.data.images.load(os.path.abspath(args.output), check_existing=False)
    pixels = list(image.pixels[:])
    if not pixels or not any(value > 0.02 for value in pixels[0::4]):
        raise RuntimeError("Eevee render readback appears empty.")
    print(
        "QSS_EEVEE_PROBE "
        f"blender={bpy.app.version_string} "
        f"engine={scene.render.engine} "
        f"resolution={args.resolution}x{args.resolution} "
        f"render_seconds={elapsed:.4f} "
        f"pixels={len(pixels) // 4} "
        f"output={os.path.abspath(args.output)}"
    )


if __name__ == "__main__":
    main()
