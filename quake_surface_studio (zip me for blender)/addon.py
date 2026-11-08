"""Blender UI and texture-paint workflow for Quake Surface Studio.

Prototype scope: classic Quake BSP29 import, indexed miptex editing/export,
static all-style lightmap reconstruction, QLIT v1 colour sidecars and light baking.
BSP2/2PSB and rerelease-specific BSP extensions are not implemented.
"""
from __future__ import annotations

import array
import hashlib
from functools import lru_cache
import math
import os
import re
import struct
import time
import traceback

import bpy
from bpy.props import StringProperty, FloatProperty, BoolProperty, IntProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import bsp, color, lighting as lighting_utils


ADDON_VERSION = (0, 11, 0)

# Quake mapping convention: one map unit is conventionally treated as one inch.
# Blender scene units are metres, so this keeps movement and light distances intuitive.
DEFAULT_QUAKE_UNIT_SCALE = 0.0254

# Track keymap items created by this add-on. This must exist before register().
_addon_keymaps = []


def _report(op, level, message):
    op.report({level}, message)


def _image_hash(image):
    image.update()
    px = array.array('f', [0.0]) * (image.size[0] * image.size[1] * 4)
    image.pixels.foreach_get(px)
    h = hashlib.sha256()
    h.update(struct.pack('<II', int(image.size[0]), int(image.size[1])))
    h.update(px.tobytes())
    return h.hexdigest()


def _find_image(mat, role="base_texture"):
    if not mat or not mat.use_nodes:
        return None
    nodes = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
    for node in nodes:
        if node.get('qss_role', '') == role:
            return node.image
    if role == "base_texture":
        for node in nodes:
            if node.get('qss_role', '') != 'lightmap':
                return node.image
    return None


def _find_image_node(mat, role="base_texture"):
    if not mat or not mat.use_nodes:
        return None
    nodes = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
    for node in nodes:
        if node.get('qss_role', '') == role:
            return node
    if role == "base_texture":
        for node in nodes:
            if node.get('qss_role', '') != 'lightmap':
                return node
    return None


def _set_material_image(mat, image):
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    tex = _find_image_node(mat, "base_texture")
    if tex is None:
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (-520, 120)
    tex.image = image
    tex['qss_role'] = 'base_texture'
    tex.extension = 'REPEAT'
    tex.interpolation = 'Closest'
    # Explicitly bind the Quake material UV layer. Lightmap UVs are a separate
    # render channel and must never silently replace the base-texture mapping.
    texture_uv_node = next(
        (n for n in nodes if n.type == 'UVMAP' and n.get('qss_role') == 'texture_uv'), None
    )
    if texture_uv_node is None:
        texture_uv_node = nodes.new('ShaderNodeUVMap')
        texture_uv_node.location = (-760, 300)
        texture_uv_node['qss_role'] = 'texture_uv'
    texture_uv_node.uv_map = 'Quake_Texture_UV'
    for link in list(mat.node_tree.links):
        if link.to_socket == tex.inputs['Vector']:
            mat.node_tree.links.remove(link)
    mat.node_tree.links.new(texture_uv_node.outputs['UV'], tex.inputs['Vector'])
    for node in nodes:
        node.select = False
    tex.select = True
    nodes.active = tex
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (0, 80)
    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if output is None:
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (300, 80)
    lightmap_multiply = next(
        (n for n in nodes if n.type == 'MIX_RGB' and n.get('qss_role') == 'lightmap_multiply'), None
    )
    if lightmap_multiply is not None:
        # Keep the albedo feeding the lightmap multiply node, not the shader directly.
        for link in list(mat.node_tree.links):
            if link.to_socket == lightmap_multiply.inputs['Color1']:
                mat.node_tree.links.remove(link)
        mat.node_tree.links.new(tex.outputs['Color'], lightmap_multiply.inputs['Color1'])
    elif not any(link.from_node == tex and link.to_node == bsdf for link in mat.node_tree.links):
        mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    if not any(link.from_node == bsdf and link.to_node == output for link in mat.node_tree.links):
        mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])


def _next_pow2_clamped(value, minimum=16, maximum=512):
    """Choose a supported Quake miptex dimension for a face-local texture."""
    value = max(1, int(math.ceil(float(value))))
    dimension = 1 << (value - 1).bit_length()
    return max(minimum, min(maximum, dimension))


def _bake_face_local_texture(source_image, uv_layer, poly, image_name):
    """Bake the repeated Quake texture under one BSP face into a 0..1 image.

    Quake faces commonly use texture coordinates outside Blender's 0..1 UV
    square because the source miptex repeats. Blender's paint canvas cannot
    reliably paint those repeated tiles. This function crops/resamples the
    actual projected region into a face-local image and returns normalized
    UVs plus the projected texinfo bounds.
    """
    if source_image is None or uv_layer is None:
        raise bsp.BSPError("The selected face has no source image or texture UV layer.")
    width_src, height_src = int(source_image.size[0]), int(source_image.size[1])
    if width_src <= 0 or height_src <= 0:
        raise bsp.BSPError("The source texture image has invalid dimensions.")

    # Blender 5.2 can temporarily expose an empty UV data collection after
    # Edit Mode hide/reveal or stale BMesh CustomData. Never index it blindly.
    try:
        uv_data = uv_layer.data
        loop_start = int(poly.loop_start)
        loop_total = int(poly.loop_total)
        uv_count = len(uv_data)
    except Exception as exc:
        raise bsp.BSPError(
            f"Cannot read UV collection for face {getattr(poly, 'index', '?')}: {exc}. "
            "Return to Object Mode, update the mesh, or re-import the BSP."
        ) from exc
    if loop_start < 0 or loop_total < 3 or loop_start + loop_total > uv_count:
        raise bsp.BSPError(
            f"Face {getattr(poly, 'index', '?')} references UV loops "
            f"[{loop_start}, {loop_start + loop_total}), but the UV collection has "
            f"{uv_count} entries. This usually follows a destructive Edit Mode operation; "
            "switch to Object Mode and re-import the BSP if the mismatch persists."
        )
    uv_values = []
    for i in range(loop_start, loop_start + loop_total):
        try:
            uv_values.append(tuple(uv_data[i].uv))
        except Exception as exc:
            raise bsp.BSPError(f"UV entry {i} became unavailable while reading face {poly.index}: {exc}") from exc
    if len(uv_values) < 3:
        raise bsp.BSPError(f"Face {poly.index} has fewer than three UV coordinates.")

    # UVs were imported as U=S/width and V=1-T/height. Keep the unwrapped
    # projected coordinates here; modulo is applied only while sampling.
    s_values = [uv[0] * width_src for uv in uv_values]
    t_values = [(1.0 - uv[1]) * height_src for uv in uv_values]
    min_s, max_s = min(s_values), max(s_values)
    min_t, max_t = min(t_values), max(t_values)
    span_s = max(max_s - min_s, 1.0)
    span_t = max(max_t - min_t, 1.0)

    width_out = _next_pow2_clamped(span_s)
    height_out = _next_pow2_clamped(span_t)
    source_pixels = array.array('f', [0.0]) * (width_src * height_src * 4)
    source_image.update()
    source_image.pixels.foreach_get(source_pixels)
    output_pixels = array.array('f')

    # Blender image pixel buffers are bottom-up. Sample at texel centres and
    # wrap source coordinates exactly as the Quake material repeats.
    for y in range(height_out):
        t = min_t + (1.0 - (y + 0.5) / height_out) * span_t
        v_src = (1.0 - (t / height_src)) % 1.0
        sy = min(height_src - 1, int(v_src * height_src))
        for x in range(width_out):
            s = min_s + ((x + 0.5) / width_out) * span_s
            u_src = (s / width_src) % 1.0
            sx = min(width_src - 1, int(u_src * width_src))
            offset = (sy * width_src + sx) * 4
            output_pixels.extend(source_pixels[offset:offset + 4])

    image = bpy.data.images.new(
        name=image_name, width=width_out, height=height_out,
        alpha=True, float_buffer=bool(getattr(source_image, 'is_float', False)),
    )
    try:
        image.colorspace_settings.name = source_image.colorspace_settings.name
    except Exception:
        pass
    image.pixels.foreach_set(output_pixels)
    image.update()
    try:
        image.pack()
    except RuntimeError:
        pass
    image['qss_import_hash'] = ''  # Always export the face-local image as a new miptex.
    image['qss_face_local_baked'] = True

    normalized_uvs = [
        ((s - min_s) / span_s, 1.0 - ((t - min_t) / span_t))
        for s, t in zip(s_values, t_values)
    ]
    return image, normalized_uvs, (min_s, min_t, span_s, span_t), (width_out, height_out)


def _face_local_texinfo_projection(source_texinfo, bounds, output_size):
    """Return a texinfo projection matching the baked, face-local texture."""
    min_s, min_t, span_s, span_t = bounds
    width, height = output_size
    scale_s = width / span_s
    scale_t = height / span_t
    s = source_texinfo[0:4]
    t = source_texinfo[4:8]
    return (
        s[0] * scale_s, s[1] * scale_s, s[2] * scale_s, (s[3] - min_s) * scale_s,
        t[0] * scale_t, t[1] * scale_t, t[2] * scale_t, (t[3] - min_t) * scale_t,
    )


def _install_lightmap_nodes(mat, image):
    """Preview albedo x lightmap through Principled emission (unlit in Blender)."""
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (180, 80)
    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if output is None:
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (520, 80)

    base_socket = bsdf.inputs.get('Base Color')
    base_from = None
    if base_socket is not None:
        base_links = [link for link in links if link.to_socket == base_socket]
        if base_links:
            base_from = base_links[0].from_socket
        for link in base_links:
            links.remove(link)
    if base_from is None:
        base_image_node = _find_image_node(mat, 'base_texture')
        if base_image_node is not None:
            base_from = base_image_node.outputs.get('Color')

    uv_node = next((n for n in nodes if n.type == 'UVMAP' and n.get('qss_role') == 'lightmap'), None)
    if uv_node is None:
        uv_node = nodes.new('ShaderNodeUVMap')
        uv_node.location = (-720, -260)
        uv_node['qss_role'] = 'lightmap'
    uv_node.uv_map = 'Quake_Lightmap_UV'

    lm_node = _find_image_node(mat, 'lightmap')
    if lm_node is None:
        lm_node = nodes.new('ShaderNodeTexImage')
        lm_node.location = (-480, -260)
        lm_node['qss_role'] = 'lightmap'
    lm_node.image = image
    lm_node.extension = 'EXTEND'
    lm_node.interpolation = 'Closest'
    for link in list(links):
        if link.to_socket == lm_node.inputs['Vector']:
            links.remove(link)
    links.new(uv_node.outputs['UV'], lm_node.inputs['Vector'])

    multiply = next((n for n in nodes if n.type == 'MIX_RGB' and n.get('qss_role') == 'lightmap_multiply'), None)
    if multiply is None:
        multiply = nodes.new('ShaderNodeMixRGB')
        multiply.location = (-100, 40)
        multiply.blend_type = 'MULTIPLY'
        multiply['qss_role'] = 'lightmap_multiply'
    multiply.blend_type = 'MULTIPLY'
    multiply.inputs['Fac'].default_value = 1.0
    # White is the neutral multiplier. In particular, an empty/missing albedo
    # node must never turn the entire lightmapped surface black.
    if base_from is not None:
        for link in list(links):
            if link.to_socket == multiply.inputs['Color1']:
                links.remove(link)
        links.new(base_from, multiply.inputs['Color1'])
    else:
        multiply.inputs['Color1'].default_value = (1.0, 1.0, 1.0, 1.0)
    for link in list(links):
        if link.to_socket == multiply.inputs['Color2']:
            links.remove(link)
    links.new(lm_node.outputs['Color'], multiply.inputs['Color2'])

    # Use the Principled BSDF's emission input. Set the lit surface's regular
    # BRDF contribution to black so scene lamps/world illumination cannot
    # relight or tint the already-baked Quake lightmap.
    emission_socket = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
    if emission_socket is None:
        raise bsp.BSPError(f"Blender's Principled BSDF has no Emission input (material '{mat.name}').")
    for link in list(links):
        if link.to_socket == emission_socket:
            links.remove(link)
    links.new(multiply.outputs['Color'], emission_socket)
    strength_socket = bsdf.inputs.get('Emission Strength')
    if strength_socket is not None:
        strength_socket.default_value = 1.0
    if base_socket is not None:
        base_socket.default_value = (0.0, 0.0, 0.0, 1.0)
    for socket_name, value in (('Metallic', 0.0), ('Roughness', 1.0), ('Specular IOR Level', 0.0), ('Specular', 0.0)):
        socket = bsdf.inputs.get(socket_name)
        if socket is not None:
            socket.default_value = value
    # Keep one known surface connection.
    if not any(link.from_node == bsdf and link.to_node == output for link in links):
        for link in list(links):
            if link.to_socket == output.inputs['Surface']:
                links.remove(link)
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])


def _rebuild_lightmap_preview(obj, image_override=None):
    """Force every material slot to sample the same atlas with the map's LM UVs.

    image_override is used for the immutable Original BSP Lightmap preview;
    normal painting/export continues to use the editable working atlas.
    """
    image = image_override or bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
    if image is None:
        raise bsp.BSPError('The QSS lightmap atlas image is missing.')
    mesh = obj.data
    uv_layer = mesh.uv_layers.get('Quake_Lightmap_UV')
    if uv_layer is None:
        raise bsp.BSPError('Quake_Lightmap_UV is missing; re-import the BSP.')
    try:
        uv_layer.active_render = True
        mesh.uv_layers.active = uv_layer
    except Exception:
        pass
    hooked = 0
    for mat in mesh.materials:
        if mat is None:
            continue
        _install_lightmap_nodes(mat, image)
        node = _find_image_node(mat, 'lightmap')
        uv = next((n for n in mat.node_tree.nodes
                   if n.type == 'UVMAP' and n.get('qss_role') == 'lightmap'), None)
        if node is not None:
            node.interpolation = 'Closest'
            node.extension = 'EXTEND'
            if uv is not None:
                uv.uv_map = 'Quake_Lightmap_UV'
            hooked += 1
    obj['qss_lightmap_material_hooks'] = hooked
    obj['qss_lightmap_material_slots'] = len(mesh.materials)
    return hooked, len(mesh.materials)



def _install_realtime_light_nodes(mat):
    """Show the original diffuse texture under actual Blender scene lights."""
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    if output is None:
        output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if output is None:
        output = nodes.new('ShaderNodeOutputMaterial')

    base = _find_image_node(mat, 'base_texture')
    base_socket = bsdf.inputs.get('Base Color')
    if base_socket is not None:
        for link in list(links):
            if link.to_socket == base_socket:
                links.remove(link)
        if base is not None:
            links.new(base.outputs['Color'], base_socket)
        else:
            base_socket.default_value = (1.0, 1.0, 1.0, 1.0)

    # The baked-lightmap emission path must be disconnected in this mode.
    emission = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
    if emission is not None:
        for link in list(links):
            if link.to_socket == emission:
                links.remove(link)
        emission.default_value = (0.0, 0.0, 0.0, 1.0)
    strength = bsdf.inputs.get('Emission Strength')
    if strength is not None:
        strength.default_value = 0.0

    for name, value in (('Metallic', 0.0), ('Roughness', 1.0),
                        ('Specular IOR Level', 0.0), ('Specular', 0.0)):
        socket = bsdf.inputs.get(name)
        if socket is not None:
            socket.default_value = value

    for link in list(links):
        if link.to_socket == output.inputs['Surface']:
            links.remove(link)
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])


def _set_black_preview_world(scene, obj):
    """Use a private black world so zero-energy live lights really render black.

    Material Preview otherwise keeps its studio HDRI when use_scene_world is
    false, which makes the mesh appear lit even with every Quake lamp at zero.
    A copied world keeps the user's actual scene world untouched.
    """
    existing_copy = obj.get('qss_preview_world_copy', '')
    if existing_copy and scene.world and scene.world.name == existing_copy:
        return
    original_name = scene.world.name if scene.world else ''
    source_world = scene.world
    preview_world = source_world.copy() if source_world else bpy.data.worlds.new('QSS_LivePreview_BlackWorld')
    preview_world.name = f"QSS_LivePreview_BlackWorld_{obj.name}"
    preview_world.use_nodes = True
    background = next((node for node in preview_world.node_tree.nodes if node.type == 'BACKGROUND'), None)
    if background is None:
        background = preview_world.node_tree.nodes.new('ShaderNodeBackground')
        output = next((node for node in preview_world.node_tree.nodes if node.type == 'OUTPUT_WORLD'), None)
        if output is None:
            output = preview_world.node_tree.nodes.new('ShaderNodeOutputWorld')
        preview_world.node_tree.links.new(background.outputs['Background'], output.inputs['Surface'])
    background.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
    background.inputs['Strength'].default_value = 0.0
    scene.world = preview_world
    obj['qss_preview_world_original'] = original_name
    obj['qss_preview_world_copy'] = preview_world.name


def _restore_preview_world(scene, obj):
    """Restore the user's world after leaving Live Lights or completing a bake."""
    original_name = obj.get('qss_preview_world_original', '')
    preview_name = obj.get('qss_preview_world_copy', '')
    preview_world = bpy.data.worlds.get(preview_name) if preview_name else None
    if preview_name and scene.world and scene.world.name == preview_name:
        scene.world = bpy.data.worlds.get(original_name) if original_name else None
    if preview_world is not None and preview_world.users == 0:
        bpy.data.worlds.remove(preview_world)
    for key in ('qss_preview_world_original', 'qss_preview_world_copy'):
        if key in obj:
            del obj[key]


def _store_and_enter_eevee_live_engine(scene, obj):
    """Remember the render engine and use Eevee for responsive coloured live lights."""
    if not obj.get('qss_preview_original_engine'):
        obj['qss_preview_original_engine'] = scene.render.engine
    # Blender 4.2+ / 5.x Eevee engine identifier. Keep a safe fallback for
    # older builds without silently leaving the user's engine changed.
    try:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        try:
            scene.render.engine = 'BLENDER_EEVEE'
        except Exception:
            pass


def _restore_preview_engine(scene, obj):
    original_engine = obj.get('qss_preview_original_engine', '')
    if original_engine:
        try:
            scene.render.engine = original_engine
        except Exception:
            pass
    if 'qss_preview_original_engine' in obj:
        del obj['qss_preview_original_engine']


def _set_viewport_lighting_mode(context, mode):
    """Use Eevee Rendered mode for live lights; use unlit Material Preview for BSP lightmaps."""
    screen = getattr(context, 'screen', None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type != 'VIEW_3D':
                continue
            shading = space.shading
            if mode == 'realtime':
                shading.type = 'RENDERED'
                # Blender stores separate switches for Material Preview and
                # Rendered viewport mode. The previous build changed only the
                # viewport type, so a saved `use_scene_lights_render=False`
                # could leave the imported Quake lamps invisible: the viewport
                # then looked like an unlit/base-texture preview and the energy
                # slider appeared to do nothing.
                for prop_name in ('use_scene_lights', 'use_scene_world',
                                  'use_scene_lights_render', 'use_scene_world_render'):
                    if hasattr(shading, prop_name):
                        setattr(shading, prop_name, True)
            else:
                shading.type = 'MATERIAL'
                shading.use_scene_lights = False
                shading.use_scene_world = False
                if hasattr(shading, 'use_scene_lights_render'):
                    shading.use_scene_lights_render = False
                if hasattr(shading, 'use_scene_world_render'):
                    shading.use_scene_world_render = False


def _hide_non_quake_lights_for_preview(scene):
    """Ensure Live Lights is illuminated only by lamps imported from this BSP."""
    for light_obj in scene.objects:
        if light_obj.type != 'LIGHT':
            continue
        if light_obj.get('qss_light_role') in {'quake_entity_light', 'quake_world_sunlight'}:
            continue
        if not light_obj.get('qss_hidden_by_live_preview', False):
            light_obj['qss_restore_hide_viewport'] = bool(light_obj.hide_viewport)
            light_obj['qss_restore_hide_render'] = bool(light_obj.hide_render)
            try:
                light_obj['qss_restore_hide_set'] = bool(light_obj.hide_get())
            except Exception:
                light_obj['qss_restore_hide_set'] = False
            light_obj['qss_hidden_by_live_preview'] = True
        light_obj.hide_viewport = True
        light_obj.hide_render = True
        try:
            light_obj.hide_set(True)
        except Exception:
            pass


def _restore_non_quake_lights(scene):
    """Restore non-QSS light visibility exactly as it was before Live Lights."""
    for light_obj in scene.objects:
        if light_obj.type != 'LIGHT' or not light_obj.get('qss_hidden_by_live_preview', False):
            continue
        try:
            light_obj.hide_viewport = bool(light_obj.get('qss_restore_hide_viewport', False))
            light_obj.hide_render = bool(light_obj.get('qss_restore_hide_render', False))
            light_obj.hide_set(bool(light_obj.get('qss_restore_hide_set', False)))
        except Exception:
            pass
        for key in ('qss_restore_hide_viewport', 'qss_restore_hide_render',
                    'qss_restore_hide_set', 'qss_hidden_by_live_preview'):
            if key in light_obj:
                del light_obj[key]


def _set_lighting_preview(context, obj, mode):
    if mode == 'realtime':
        _set_black_preview_world(context.scene, obj)
        _store_and_enter_eevee_live_engine(context.scene, obj)
        _hide_non_quake_lights_for_preview(context.scene)
        for mat in obj.data.materials:
            if mat is not None:
                _install_realtime_light_nodes(mat)
        for light_obj in context.scene.objects:
            if light_obj.type == 'LIGHT' and light_obj.get('qss_light_role') in {
                'quake_entity_light', 'quake_world_sunlight'
            }:
                light_obj.hide_viewport = False
                light_obj.hide_render = False
                try:
                    light_obj.hide_set(False)
                except Exception:
                    pass
        _apply_quake_light_energy_scale(context.scene)
    else:
        _restore_non_quake_lights(context.scene)
        _restore_preview_world(context.scene, obj)
        _restore_preview_engine(context.scene, obj)
        if mode == 'source':
            source = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
            if source is None:
                raise bsp.BSPError('The immutable original BSP lightmap snapshot is missing.')
            _rebuild_lightmap_preview(obj, image_override=source)
        else:
            _rebuild_lightmap_preview(obj)
    obj['qss_preview_mode'] = mode
    _set_viewport_lighting_mode(context, mode)


def _decode_mip0(entry, palette):
    if entry is None or entry.blob is None:
        return None
    name_raw, width, height, o0, o1, o2, o3 = struct.unpack_from('<16s6I', entry.blob, 0)
    if o0 <= 0 or o0 + width * height > len(entry.blob):
        return None
    indices = entry.blob[o0:o0 + width * height]
    name = name_raw.split(b'\0', 1)[0].decode('ascii', 'replace')
    transparent = name.startswith('{')
    # Blender stores image pixels bottom-up. Quake miptex rows are top-down.
    # Reverse rows here and invert the T projection in the UV coordinates.
    pixels = array.array('f')
    for y in range(height - 1, -1, -1):
        row = indices[y * width:(y + 1) * width]
        for index in row:
            base = index * 3
            r, g, b = palette[base], palette[base + 1], palette[base + 2]
            a = 0.0 if transparent and index == 255 else 1.0
            pixels.extend((color.quake_byte_to_srgb_code(r), color.quake_byte_to_srgb_code(g), color.quake_byte_to_srgb_code(b), a))
    return width, height, pixels, name


def _make_image(name, decoded):
    if decoded is None:
        return None
    width, height, pixels, texture_name = decoded
    image = bpy.data.images.new(name=name, width=width, height=height, alpha=True, float_buffer=False)
    image.colorspace_settings.name = 'sRGB'
    image.pixels.foreach_set(pixels)
    image.update()
    try:
        image.pack()
    except RuntimeError:
        # Generated images are stored in the .blend without an external file.
        pass
    image['qss_import_hash'] = _image_hash(image)
    image['qss_source_texture_name'] = texture_name
    return image


def _make_white_image(name, width=16, height=16):
    """Create a packed neutral-white texture so missing inputs never black out a material."""
    width = max(16, min(512, int(width or 16)))
    height = max(16, min(512, int(height or 16)))
    width = 1 << (width - 1).bit_length()
    height = 1 << (height - 1).bit_length()
    image = bpy.data.images.new(name=name, width=width, height=height, alpha=True, float_buffer=False)
    image.colorspace_settings.name = 'sRGB'
    image.pixels.foreach_set(array.array('f', [1.0]) * (width * height * 4))
    image.update()
    try:
        image.pack()
    except RuntimeError:
        pass
    image['qss_import_hash'] = _image_hash(image)
    image['qss_white_fallback'] = True
    return image


def _load_image_from_external_file(name, path):
    try:
        image = bpy.data.images.load(path, check_existing=True)
    except Exception:
        return None
    try:
        image.colorspace_settings.name = 'sRGB'
    except Exception:
        pass
    try:
        image.pack()
    except RuntimeError:
        pass
    image['qss_source_texture_name'] = name
    image['qss_external_texture_path'] = os.path.abspath(path)
    image['qss_import_hash'] = _image_hash(image)
    return image


def _resolve_worldspawn_wads(parsed, source_path, game_dir):
    """Resolve worldspawn WAD paths against the BSP and selected game folders."""
    names = bsp.worldspawn_wad_names(parsed.lumps[bsp.LUMP_ENTITIES])
    if not names:
        return [], []
    source_dir = os.path.dirname(os.path.abspath(source_path))
    roots = []
    for root in (source_dir, game_dir, os.path.join(game_dir, 'id1') if game_dir else ''):
        if root and os.path.isdir(root) and os.path.abspath(root) not in roots:
            roots.append(os.path.abspath(root))
    found = []
    unresolved = []
    for wad_name in names:
        normalized = os.path.expandvars(os.path.expanduser(wad_name.strip().strip('"'))).replace('\\', os.sep)
        basename = os.path.basename(normalized)
        candidates = [normalized]
        for root in roots:
            candidates.extend((os.path.join(root, normalized), os.path.join(root, basename)))
        path = next((os.path.abspath(x) for x in candidates if x and os.path.isfile(x)), None)
        if path is None and basename:
            for root in roots:
                # Bounded search: game root/id1 and the BSP folder, not the whole Steam library.
                for walk_root, dirs, files in os.walk(root):
                    depth = os.path.relpath(walk_root, root).count(os.sep)
                    if depth >= 3:
                        dirs[:] = []
                    match = next((f for f in files if f.lower() == basename.lower()), None)
                    if match:
                        path = os.path.abspath(os.path.join(walk_root, match))
                        break
                if path:
                    break
        if path and path not in found:
            found.append(path)
        elif not path:
            unresolved.append(wad_name)
    return found, unresolved


def _index_external_texture_files(source_path, game_dir):
    """Index conventional loose Quake replacement textures under textures/."""
    roots = []
    for root in (game_dir, os.path.join(game_dir, 'id1') if game_dir else '', os.path.dirname(os.path.abspath(source_path))):
        if root and os.path.isdir(root) and os.path.abspath(root) not in roots:
            roots.append(os.path.abspath(root))
    map_name = os.path.splitext(os.path.basename(source_path))[0].lower()
    extensions = {'.tga', '.png', '.jpg', '.jpeg', '.bmp', '.exr'}
    indexed = {}
    # Map-specific textures take precedence over the generic textures/ directory.
    ordered_dirs = []
    for root in roots:
        textures_root = os.path.join(root, 'textures')
        ordered_dirs.extend((os.path.join(textures_root, map_name), textures_root))
    for folder in ordered_dirs:
        if not os.path.isdir(folder):
            continue
        for walk_root, dirs, files in os.walk(folder):
            depth = os.path.relpath(walk_root, folder).count(os.sep)
            if depth >= 4:
                dirs[:] = []
            for filename in files:
                stem, ext = os.path.splitext(filename)
                if ext.lower() not in extensions:
                    continue
                indexed.setdefault(stem.lower(), os.path.join(walk_root, filename))
    return indexed


def _load_wad_texture_index(wad_paths):
    textures = {}
    loaded_paths = []
    failures = []
    for path in wad_paths:
        try:
            items = bsp.read_wad2_textures(path)
            for name, texture in items.items():
                textures.setdefault(name.lower(), texture)
            loaded_paths.append(path)
        except bsp.BSPError as exc:
            failures.append(f"{os.path.basename(path)}: {exc}")
    return textures, loaded_paths, failures


def _make_material(name, texture_id, texture_name, image):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat['qss_texture_index'] = int(texture_id)
    mat['qss_texture_name'] = texture_name or name
    mat['qss_export_name'] = (texture_name or name)[:15]
    mat['qss_is_new_texture'] = False
    if image:
        _set_material_image(mat, image)
    return mat


def _load_quake_image_and_materials(parsed, palette, wad_textures=None, loose_textures=None):
    entries = parsed.miptextures()
    wad_textures = wad_textures or {}
    loose_textures = loose_textures or {}
    materials = []
    material_by_miptex = {}
    source_counts = {'embedded': 0, 'wad': 0, 'loose': 0, 'white_fallback': 0}
    missing_names = []
    for texture_id, entry in enumerate(entries):
        decoded = _decode_mip0(entry, palette) if entry.blob is not None else None
        source_kind = 'embedded' if decoded is not None else ''
        if decoded is None and entry.name:
            wad_entry = wad_textures.get(entry.name.lower())
            if wad_entry is not None:
                decoded = _decode_mip0(wad_entry, palette)
                if decoded is not None:
                    source_kind = 'wad'
        image_name = f"QSS_TEX_{texture_id:03d}_{entry.name or 'MISSING'}"
        image = _make_image(image_name, decoded) if decoded is not None else None
        if image is None and entry.name:
            texture_path = loose_textures.get(entry.name.lower())
            if texture_path:
                image = _load_image_from_external_file(entry.name, texture_path)
                if image is not None:
                    source_kind = 'loose'
        if image is None and entry.name:
            # A neutral white fallback keeps the lightmap visible instead of
            # multiplying it by Blender's black value for an empty image node.
            image = _make_white_image(image_name + '_WHITE', entry.width or 16, entry.height or 16)
            source_kind = 'white_fallback'
            missing_names.append(entry.name)
        if image is None:
            continue
        mat = _make_material(f"QSS_{texture_id:03d}_{entry.name or 'MISSING'}", texture_id, entry.name, image)
        mat['qss_texture_source'] = source_kind
        if source_kind == 'loose':
            mat['qss_external_texture_path'] = image.get('qss_external_texture_path', '')
        material_by_miptex[texture_id] = mat
        materials.append(mat)
        source_counts[source_kind] = source_counts.get(source_kind, 0) + 1

    missing_image = _make_white_image('QSS_MISSING_TEXTURE_WHITE')
    missing = _make_material("QSS_MISSING_TEXTURE", -2, "missing", missing_image)
    missing['qss_texture_source'] = 'white_fallback'
    materials.append(missing)
    return entries, materials, material_by_miptex, missing, source_counts, sorted(set(missing_names))


def _get_or_make_face_attributes(mesh):
    names = ('qss_bsp_face_id', 'qss_bsp_texinfo_id', 'qss_bsp_miptex_id')
    attrs = {}
    for name in names:
        attr = mesh.attributes.get(name)
        if attr is None:
            attr = mesh.attributes.new(name=name, type='INT', domain='FACE')
        attrs[name] = attr
    return attrs


def _calc_face_lightmap_extents(positions, texinfo):
    svec = texinfo[0:4]
    tvec = texinfo[4:8]
    s_values = [p[0] * svec[0] + p[1] * svec[1] + p[2] * svec[2] + svec[3] for p in positions]
    t_values = [p[0] * tvec[0] + p[1] * tvec[1] + p[2] * tvec[2] + tvec[3] for p in positions]
    # Mirrors Quake's CalcSurfaceExtents: floor(min/16), ceil(max/16).
    s_min = math.floor(min(s_values) / 16.0 + 1e-7) * 16
    t_min = math.floor(min(t_values) / 16.0 + 1e-7) * 16
    s_max = math.ceil(max(s_values) / 16.0 - 1e-7) * 16
    t_max = math.ceil(max(t_values) / 16.0 - 1e-7) * 16
    return s_min, t_min, s_max - s_min, t_max - t_min, svec, tvec


def _pack_lightmap_rectangles(records, gutter=2):
    # Prefer 2x sample blocks for easier painting; fall back to 1:1 if needed.
    ordered = sorted(records, key=lambda r: (-(r['height']), -(r['width']), r['face_id']))
    for scale in (2, 1):
        for atlas_size in (512, 1024, 2048):
            x = y = row_h = 0
            placements = {}
            failed = False
            for rec in ordered:
                rw = rec['width'] * scale + 2 * gutter
                rh = rec['height'] * scale + 2 * gutter
                if rw > atlas_size or rh > atlas_size:
                    failed = True
                    break
                if x + rw > atlas_size:
                    x = 0
                    y += row_h
                    row_h = 0
                if y + rh > atlas_size:
                    failed = True
                    break
                placements[rec['face_id']] = (x, y)
                x += rw
                row_h = max(row_h, rh)
            if not failed:
                return atlas_size, scale, placements, gutter
    return None


def _build_lightmap_atlas(obj, mesh, parsed, face_ids, texinfo_ids, positions_by_face,
                          lit_rgb=None, lighting_data=None):
    faces = parsed.faces()
    texinfos = parsed.texinfos()
    lighting = (parsed.lumps[bsp.LUMP_LIGHTING] if lighting_data is None else lighting_data)
    records = []
    positions_lookup = dict(zip(face_ids, positions_by_face))
    for face_id, texinfo_id in zip(face_ids, texinfo_ids):
        if face_id < 0 or face_id >= len(faces) or texinfo_id < 0 or texinfo_id >= len(texinfos):
            continue
        face = faces[face_id]
        styles = face[5:9]
        light_offset = face[9]
        if light_offset < 0 or styles[0] == 255:
            continue
        ext = _calc_face_lightmap_extents(positions_lookup[face_id], texinfos[texinfo_id])
        s_min, t_min, extent_s, extent_t, svec, tvec = ext
        sample_w = (extent_s >> 4) + 1
        sample_h = (extent_t >> 4) + 1
        active_styles = [int(style) for style in styles if style != 255]
        style_count = len(active_styles)
        block_size = sample_w * sample_h
        if not active_styles or light_offset + block_size * style_count > len(lighting):
            continue
        # Quake stores one luxel block per active style, contiguously from
        # lightofs. The previous importer sampled only styles[0], silently
        # dropping switchable/flickering layers such as style 2.
        combined_rgb = lighting_utils.combine_style_samples(
            lighting, lit_rgb, light_offset, block_size, active_styles
        )
        combined_mono = [max(0, min(255, int(round(
            0.2126 * r + 0.7152 * g + 0.0722 * b
        )))) for r, g, b in combined_rgb]
        records.append({
            'face_id': face_id,
            'texinfo_id': texinfo_id,
            'width': sample_w,
            'height': sample_h,
            's_min': s_min,
            't_min': t_min,
            'svec': svec,
            'tvec': tvec,
            'styles': active_styles,
            'samples': combined_mono,
            'samples_rgb': combined_rgb,
        })

    # Diagnose colour/brightness after summing every active face style.
    gradient_faces = 0
    chromatic_faces = 0
    if lit_rgb is not None:
        for rec in records:
            samples = rec['samples_rgb']
            if len(samples) > 1:
                ranges = [max(sample[c] for sample in samples) - min(sample[c] for sample in samples)
                          for c in range(3)]
                if max(ranges) >= 3:
                    gradient_faces += 1
            # A brightness gradient is not necessarily a colour gradient.
            if lighting_utils.face_has_chromatic_lighting(samples):
                chromatic_faces += 1
    obj['qss_lit_gradient_faces'] = int(gradient_faces)
    obj['qss_lit_chromatic_faces'] = int(chromatic_faces)
    obj['qss_lit_rgb_faces'] = int(len(records) if lit_rgb is not None else 0)

    if not records:
        obj['qss_lightmap_image_name'] = ''
        obj['qss_lightmap_faces'] = 0
        return None

    packed = _pack_lightmap_rectangles(records)
    if packed is None:
        obj['qss_lightmap_image_name'] = ''
        obj['qss_lightmap_faces'] = 0
        obj['qss_lightmap_note'] = 'Atlas exceeded 2048x2048 at 1 pixel per sample.'
        return None
    atlas_size, scale, placements, gutter = packed

    rgba = array.array('f', [1.0]) * (atlas_size * atlas_size * 4)  # white = unlightmapped
    record_by_face = {r['face_id']: r for r in records}
    for rec in records:
        x0, y0 = placements[rec['face_id']]
        x0 += gutter
        y0 += gutter
        for sy in range(rec['height']):
            for sx in range(rec['width']):
                sample_rgb = rec['samples_rgb'][sy * rec['width'] + sx]
                values = tuple(channel / 255.0 for channel in sample_rgb)
                for dy in range(scale):
                    top_y = y0 + sy * scale + dy
                    bottom_y = atlas_size - 1 - top_y
                    for dx in range(scale):
                        px = x0 + sx * scale + dx
                        index = (bottom_y * atlas_size + px) * 4
                        rgba[index] = values[0]
                        rgba[index + 1] = values[1]
                        rgba[index + 2] = values[2]
                        rgba[index + 3] = 1.0

    image = bpy.data.images.new(
        name=f"QSS_Lightmap_{os.path.basename(obj.get('qss_source_path', 'map'))}",
        width=atlas_size, height=atlas_size, alpha=True, float_buffer=True
    )
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(rgba)
    image.update()
    try:
        image.pack()
    except RuntimeError:
        pass

    # Create the independent lightmap UV layer and face-domain export metadata.
    lm_uv = mesh.uv_layers.new(name='Quake_Lightmap_UV')
    white_uv = (0.5 / atlas_size, 1.0 - 0.5 / atlas_size)
    has_attr = mesh.attributes.new(name='qss_lm_has_data', type='BOOLEAN', domain='FACE')
    x_attr = mesh.attributes.new(name='qss_lm_atlas_x', type='INT', domain='FACE')
    y_attr = mesh.attributes.new(name='qss_lm_atlas_y', type='INT', domain='FACE')
    w_attr = mesh.attributes.new(name='qss_lm_sample_w', type='INT', domain='FACE')
    h_attr = mesh.attributes.new(name='qss_lm_sample_h', type='INT', domain='FACE')
    for poly_index, poly in enumerate(mesh.polygons):
        face_id = face_ids[poly_index]
        rec = record_by_face.get(face_id)
        # Use Blender's actual loop indices, not a reconstructed running cursor.
        # This keeps UV assignment correct if the mesh has been updated by other
        # Blender operators or if a future importer inserts non-face geometry.
        loop_indices = tuple(poly.loop_indices)
        if rec:
            ax, ay = placements[face_id]
            has_attr.data[poly_index].value = True
            x_attr.data[poly_index].value = ax
            y_attr.data[poly_index].value = ay
            w_attr.data[poly_index].value = rec['width']
            h_attr.data[poly_index].value = rec['height']
            positions = positions_by_face[poly_index]
            texinfo = texinfos[rec['texinfo_id']]
            if len(loop_indices) != len(positions):
                raise bsp.BSPError(
                    f"Face {face_id} has {len(loop_indices)} Blender loops but {len(positions)} source vertices."
                )
            for local_index, loop_index in enumerate(loop_indices):
                p = positions[local_index]
                s = p[0] * texinfo[0] + p[1] * texinfo[1] + p[2] * texinfo[2] + texinfo[3]
                t = p[0] * texinfo[4] + p[1] * texinfo[5] + p[2] * texinfo[6] + texinfo[7]
                lm_s = (s - rec['s_min']) / 16.0
                lm_t = (t - rec['t_min']) / 16.0
                pixel_x = ax + gutter + (lm_s + 0.5) * scale
                pixel_y = ay + gutter + (lm_t + 0.5) * scale
                lm_uv.data[loop_index].uv = (pixel_x / atlas_size, 1.0 - pixel_y / atlas_size)
        else:
            has_attr.data[poly_index].value = False
            x_attr.data[poly_index].value = 0
            y_attr.data[poly_index].value = 0
            w_attr.data[poly_index].value = 0
            h_attr.data[poly_index].value = 0
            for loop_index in loop_indices:
                lm_uv.data[loop_index].uv = white_uv

    # The shader uses an explicit UVMap node, and setting this channel as the
    # render UV as well makes the atlas unambiguous to Blender render/bake APIs.
    try:
        lm_uv.active_render = True
    except Exception:
        pass

    for mat in mesh.materials:
        if mat:
            _install_lightmap_nodes(mat, image)

    # Keep the texture UV active by default; the lightmap button switches it.
    texture_uv = mesh.uv_layers.get('Quake_Texture_UV')
    if texture_uv:
        mesh.uv_layers.active = texture_uv
    obj['qss_lightmap_image_name'] = image.name
    obj['qss_lightmap_atlas_size'] = atlas_size
    obj['qss_lightmap_scale'] = scale
    obj['qss_lightmap_gutter'] = gutter
    # Keep a packed immutable source snapshot so a bake or paint session can
    # always be reset to the exact imported BSP lightmaps.
    original_backup = _make_image_snapshot(image, 'QSS_OriginalBSP')
    obj['qss_original_lightmap_backup'] = original_backup.name
    obj['qss_lightmap_faces'] = len(records)
    obj['qss_lightmap_uv_faces'] = sum(1 for value in has_attr.data if value.value)
    uv_valid_faces = 0
    try:
        uv_data_count = len(lm_uv.data)
        for poly in mesh.polygons:
            loop_indices = tuple(poly.loop_indices)
            if not loop_indices or any(i < 0 or i >= uv_data_count for i in loop_indices):
                continue
            try:
                values = [tuple(lm_uv.data[i].uv[:]) for i in loop_indices]
            except (IndexError, RuntimeError, ReferenceError):
                continue
            if values and all(-1e-6 <= u <= 1.000001 and -1e-6 <= v <= 1.000001 for u, v in values):
                if max(u for u, _v in values) - min(u for u, _v in values) > 0 and max(v for _u, v in values) - min(v for _u, v in values) > 0:
                    uv_valid_faces += 1
    except (IndexError, RuntimeError, ReferenceError):
        uv_valid_faces = 0
    obj['qss_lightmap_uv_valid_faces'] = uv_valid_faces
    _rebuild_lightmap_preview(obj)
    return image


def _qss_validate_face_domain_attributes(mesh, names, operation):
    """Validate face-domain collections before indexing after Edit/BMesh changes."""
    face_count = len(mesh.polygons)
    details = {}
    for name in names:
        attr = mesh.attributes.get(name)
        count = len(attr.data) if attr is not None else None
        details[name] = count
        if attr is None or count != face_count:
            raise bsp.BSPError(
                f"Cannot {operation}: face attribute '{name}' has "
                f"{count if count is not None else 'no'} entries for {face_count} polygons. "
                "Return to Object Mode, run Mesh > Clean Up only if needed, or re-import the BSP."
            )
    return {name: mesh.attributes.get(name) for name in names}


def _qss_safe_collection_item(collection, index, label):
    """Fetch a Blender collection element with an actionable QSS error."""
    try:
        count = len(collection)
    except Exception:
        count = 0
    if index < 0 or index >= count:
        raise bsp.BSPError(f"Cannot access {label} index {index}; collection contains {count} entries.")
    try:
        return collection[index]
    except (IndexError, RuntimeError, ReferenceError, TypeError) as exc:
        raise bsp.BSPError(f"Cannot access {label} index {index}; Blender reported: {exc}") from exc


def _patch_lightmap_lump(obj, parsed):
    """Return (monochrome BSP lighting lump, QLIT v1 sidecar or None)."""
    image_name = obj.get('qss_lightmap_image_name', '')
    lighting_source = parsed.lumps[bsp.LUMP_LIGHTING]
    source_lit_path = os.path.splitext(obj.get('qss_source_path', ''))[0] + '.lit'
    source_lit_rgb, source_kind = bsp.resolve_rgb_lighting(
        parsed.bspx_lumps, lighting_source, source_lit_path
    )
    # Some -bspxlit builds omit the monochrome lump. Synthesize it from RGB so
    # classic readers still have valid fallback samples and face offsets work.
    if not lighting_source and source_lit_rgb is not None:
        lighting_source = bsp.rgb_lighting_to_luminance(source_lit_rgb)
    if not image_name:
        original_lit = bsp.build_lit_file(source_lit_rgb) if source_lit_rgb is not None else None
        return lighting_source, original_lit
    image = bpy.data.images.get(image_name)
    if image is None:
        raise bsp.BSPError("The imported lightmap atlas image is missing from this .blend file.")
    mesh = obj.data
    face_attrs = _qss_validate_face_domain_attributes(
        mesh, ('qss_bsp_face_id', 'qss_lm_has_data', 'qss_lm_atlas_x',
               'qss_lm_atlas_y', 'qss_lm_sample_w', 'qss_lm_sample_h'),
        'export the lightmap'
    )
    face_attr = face_attrs['qss_bsp_face_id']
    has_attr = face_attrs['qss_lm_has_data']
    x_attr = face_attrs['qss_lm_atlas_x']
    y_attr = face_attrs['qss_lm_atlas_y']
    w_attr = face_attrs['qss_lm_sample_w']
    h_attr = face_attrs['qss_lm_sample_h']
    size = int(image.size[0])
    if image.size[0] != image.size[1]:
        raise bsp.BSPError("Lightmap atlas must remain square; do not resize it in the Image Editor.")
    scale = int(obj.get('qss_lightmap_scale', 1))
    gutter = int(obj.get('qss_lightmap_gutter', 2))
    px = array.array('f', [0.0]) * (size * size * 4)
    image.update()
    image.pixels.foreach_get(px)
    faces = parsed.faces()
    lighting = bytearray(lighting_source)
    if source_lit_rgb is None:
        lit_rgb = bytearray(channel for sample in lighting for channel in (sample, sample, sample))
    else:
        lit_rgb = bytearray(source_lit_rgb)
    for poly_index, poly in enumerate(mesh.polygons):
        if not has_attr.data[poly_index].value:
            continue
        face_id = int(face_attr.data[poly_index].value)
        if face_id < 0 or face_id >= len(faces):
            raise bsp.BSPError(f"Lightmap atlas refers to invalid BSP face {face_id}.")
        face = faces[face_id]
        styles = face[5:9]
        light_offset = face[9]
        if light_offset < 0 or styles[0] == 255:
            continue
        sample_w = int(w_attr.data[poly_index].value)
        sample_h = int(h_attr.data[poly_index].value)
        atlas_x = int(x_attr.data[poly_index].value) + gutter
        atlas_y = int(y_attr.data[poly_index].value) + gutter
        block_size = sample_w * sample_h
        style_count = sum(1 for style in styles if style != 255)
        if sample_w <= 0 or sample_h <= 0 or light_offset + block_size * style_count > len(lighting):
            raise bsp.BSPError(f"Face {face_id} has invalid lightmap sample bounds.")
        if atlas_x < 0 or atlas_y < 0 or atlas_x + sample_w * scale > size or atlas_y + sample_h * scale > size:
            raise bsp.BSPError(f"Face {face_id} lightmap atlas rectangle exceeds the image bounds.")
        for sy in range(sample_h):
            for sx in range(sample_w):
                total_r = total_g = total_b = 0.0
                count = 0
                for dy in range(scale):
                    top_y = atlas_y + sy * scale + dy
                    bottom_y = size - 1 - top_y
                    for dx in range(scale):
                        px_x = atlas_x + sx * scale + dx
                        index = (bottom_y * size + px_x) * 4
                        r, g, b = px[index], px[index + 1], px[index + 2]
                        total_r += r
                        total_g += g
                        total_b += b
                        count += 1
                divisor = max(1, count)
                rgb = tuple(max(0, min(255, int(round((v / divisor) * 255.0))))
                            for v in (total_r, total_g, total_b))
                sample_index = light_offset + sy * sample_w + sx
                lit_rgb[sample_index * 3:sample_index * 3 + 3] = bytes(rgb)
                # Retain a useful monochrome fallback for engines without QLIT support.
                mono = int(round(0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]))
                lighting[sample_index] = max(0, min(255, mono))
        # QSS edits a single static atlas containing the sum of all active style
        # planes. Flatten that result into the first plane and zero the remaining
        # planes, otherwise the engine would add the old style layers a second time.
        for layer_index in range(1, style_count):
            layer_start = light_offset + layer_index * block_size
            layer_end = layer_start + block_size
            if layer_end <= len(lighting):
                lighting[layer_start:layer_end] = bytes(block_size)
            rgb_start, rgb_end = layer_start * 3, layer_end * 3
            if rgb_end <= len(lit_rgb):
                lit_rgb[rgb_start:rgb_end] = bytes(block_size * 3)
    return bytes(lighting), bsp.build_lit_file(bytes(lit_rgb))



def _quake_to_blender_position(position, unit_scale=DEFAULT_QUAKE_UNIT_SCALE, flip_z=False):
    """Convert Quake XYZ coordinates into Blender metres (both conventions are Z-up)."""
    x, y, z = (float(v) for v in position)
    if flip_z:
        z = -z
    scale = float(unit_scale)
    return (x * scale, y * scale, z * scale)


def _parse_entity_vector(value, default=(0.0, 0.0, 0.0)):
    try:
        parts = [float(v) for v in str(value).replace(',', ' ').split()]
        if len(parts) >= 3:
            return tuple(parts[:3])
    except (TypeError, ValueError):
        pass
    return tuple(default)


def _parse_entity_float(entity, key, default):
    try:
        return float(entity.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _parse_light_value(entity):
    """Read ericw/Quake light key forms: '300' or 'r g b intensity'."""
    raw = str(entity.get('light', '300')).replace(',', ' ').split()
    try:
        values = [float(value) for value in raw]
    except ValueError:
        values = []
    if len(values) >= 4:
        return values[3], tuple(values[:3])
    if len(values) == 3:
        return 300.0, tuple(values)
    if len(values) == 1:
        return values[0], None
    return 300.0, None


def _parse_quake_light_color(entity, embedded_color=None):
    raw = entity.get('_color')
    if raw:
        try:
            values = [float(v) for v in raw.replace(',', ' ').split()[:3]]
        except ValueError:
            values = []
    else:
        values = list(embedded_color) if embedded_color else []
    if len(values) < 3:
        return (1.0, 1.0, 1.0)
    scale = 255.0 if max(values) > 1.0 else 1.0
    return tuple(max(0.0, min(1.0, value / scale)) for value in values)


def _entity_spot_direction(entity, target_map):
    from mathutils import Vector
    target = entity.get('target', '')
    if target and target in target_map and 'origin' in entity:
        origin = Vector(_parse_entity_vector(entity.get('origin')))
        destination = Vector(target_map[target])
        delta = destination - origin
        if delta.length > 1e-6:
            return delta.normalized()
    if entity.get('mangle'):
        yaw, pitch, _roll = _parse_entity_vector(entity.get('mangle'))
        yaw = math.radians(yaw)
        pitch = math.radians(pitch)
        return Vector((math.cos(pitch) * math.cos(yaw),
                       math.cos(pitch) * math.sin(yaw), math.sin(pitch))).normalized()
    if entity.get('angle'):
        yaw = math.radians(_parse_entity_float(entity, 'angle', 0.0))
        return Vector((math.cos(yaw), math.sin(yaw), 0.0)).normalized()
    return Vector((0.0, 0.0, -1.0))


def _apply_quake_light_energy_scale(scene):
    """Apply the live multiplier and per-map source-match calibration."""
    scale = max(0.0, float(getattr(scene, 'qss_light_energy_scale', 1.0)))
    updated = 0
    for light_obj in scene.objects:
        role = light_obj.get('qss_light_role') if light_obj.type == 'LIGHT' else None
        if role not in {'quake_entity_light', 'quake_world_sunlight'}:
            continue
        raw_value = light_obj.get('qss_quake_light_value')
        if raw_value is None:
            continue
        range_scale = float(light_obj.get('qss_quake_world_range', 1.0))
        calibration = max(0.0, float(light_obj.get('qss_energy_calibration', 1.0)))
        light_obj.data.energy = lighting_utils.scaled_quake_light_energy(
            raw_value, scale * calibration
        )
        if range_scale <= 0.0:
            light_obj.data.energy = 0.0
        light_obj['qss_applied_energy_scale'] = scale
        light_obj['qss_applied_energy_calibration'] = calibration
        updated += 1
    return updated


def _on_light_energy_scale_changed(self, context):
    if context and context.scene:
        _apply_quake_light_energy_scale(context.scene)


def _import_bsp_entities(context, obj, parsed, unit_scale, flip_z=False):
    """Create a tagged light collection and spawn marker from the BSP entity lump."""
    entities = bsp.parse_entities_lump(parsed.lumps[bsp.LUMP_ENTITIES])
    if not entities:
        obj['qss_light_entity_count'] = 0
        obj['qss_has_player_start'] = False
        return 0, False

    map_stem = os.path.splitext(os.path.basename(obj.get('qss_source_path', 'map')))[0]
    collection_name = f"QSS_{map_stem}_Entities"
    old = bpy.data.collections.get(collection_name)
    if old is not None:
        for item in list(old.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        for scene in bpy.data.scenes:
            if old in scene.collection.children:
                scene.collection.children.unlink(old)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new(collection_name)
    context.scene.collection.children.link(collection)
    collection['qss_entity_collection'] = True

    # Resolve targetname origins before creating spotlights.
    targets = {}
    for entity in entities:
        targetname = entity.get('targetname', '')
        if targetname and entity.get('origin'):
            targets[targetname] = _parse_entity_vector(entity.get('origin'))

    world = next((e for e in entities if e.get('classname', '').lower() == 'worldspawn'), {})
    world_dist = max(0.001, _parse_entity_float(world, '_dist', 1.0))
    # ericw-tools global range scale defaults to 0.5 (not 1.0).
    # It is a post-lighting brightness multiplier, independent of distance.
    world_range = max(0.0, _parse_entity_float(world, '_range', 0.5))
    world_gamma = max(1e-6, _parse_entity_float(world, '_gamma', 1.0))
    world_anglescale = max(0.0, min(1.0, _parse_entity_float(
        world, '_anglescale', _parse_entity_float(world, '_anglesense', 0.5))))
    energy_scale = float(getattr(context.scene, 'qss_light_energy_scale', 1.0))
    obj['qss_world_bounce'] = max(0, int(_parse_entity_float(world, '_bounce', 0)))
    obj['qss_world_bouncescale'] = max(0.0, _parse_entity_float(world, '_bouncescale', 1.0))
    obj['qss_world_bouncecolorscale'] = max(0.0, min(1.0, _parse_entity_float(world, '_bouncecolorscale', 0.0)))
    obj['qss_world_dist'] = float(world_dist)
    obj['qss_world_range'] = float(world_range)
    obj['qss_world_gamma'] = float(world_gamma)
    obj['qss_world_anglescale'] = float(world_anglescale)
    obj['qss_world_maxlight'] = max(1.0, _parse_entity_float(world, '_maxlight', 255.0))
    obj['qss_light_energy_calibration'] = float(obj.get('qss_light_energy_calibration', 1.0))
    spawn = None
    light_count = 0
    inferred_style_count = 0
    for index, entity in enumerate(entities):
        classname = entity.get('classname', '').lower()
        if classname == 'info_player_start' and entity.get('origin') and spawn is None:
            origin = _parse_entity_vector(entity.get('origin'))
            spawn = (origin, _parse_entity_float(entity, 'angle', 0.0))
            continue
        if not classname.startswith('light') or not entity.get('origin'):
            continue
        origin = _parse_entity_vector(entity.get('origin'))
        intensity, embedded_color = _parse_light_value(entity)
        color_rgb = _parse_quake_light_color(entity, embedded_color)
        light_style, style_inferred = lighting_utils.infer_entity_style(entity)
        if style_inferred:
            inferred_style_count += 1
        is_spot = bool(entity.get('mangle') or entity.get('target') or classname in {'light_spot', 'light_spotlight'})
        light_data = bpy.data.lights.new(f"QSS_{classname}_{index:03d}", 'SPOT' if is_spot else 'POINT')
        light_obj = bpy.data.objects.new(light_data.name, light_data)
        collection.objects.link(light_obj)
        light_obj.location = _quake_to_blender_position(origin, unit_scale, flip_z)
        light_data.color = color_rgb  # ericw-tools _color is normalized RGB (0..1 or 0..255).
        if hasattr(light_data, 'use_nodes'):
            light_data.use_nodes = False
        effective_intensity = intensity * world_range
        light_data.energy = lighting_utils.scaled_quake_light_energy(effective_intensity, energy_scale)
        wait = max(0.001, _parse_entity_float(entity, 'wait', 1.0))
        falloff = max(0.0, _parse_entity_float(entity, '_falloff', 0.0))
        range_qu = falloff if falloff > 0.0 else abs(intensity) * wait * world_dist
        anglescale = max(0.0, min(1.0, _parse_entity_float(
            entity, '_anglescale', _parse_entity_float(entity, '_anglesense', world_anglescale))))
        range_blender = max(unit_scale * 32.0, range_qu * unit_scale)
        if hasattr(light_data, 'use_custom_distance'):
            light_data.use_custom_distance = True
        if hasattr(light_data, 'cutoff_distance'):
            light_data.cutoff_distance = range_blender
        direction_blender = None
        if is_spot:
            # ericw-tools uses 'angle' (default 40) and '_softangle'.
            cone = _parse_entity_float(entity, 'angle', _parse_entity_float(entity, '_cone', 40.0))
            soft_angle = _parse_entity_float(entity, '_softangle', 0.0)
            light_data.spot_size = math.radians(max(1.0, min(179.0, cone)))
            light_data.spot_blend = max(0.0, min(1.0, 1.0 - max(0.0, soft_angle) / max(0.1, cone)))
            direction = _entity_spot_direction(entity, targets)
            raw_direction = tuple(float(v) for v in direction.normalized())
            if flip_z:
                direction.z = -direction.z
            direction_blender = direction.normalized()
            light_obj.rotation_euler = direction_blender.to_track_quat('-Z', 'Y').to_euler()
        light_obj['qss_light_role'] = 'quake_entity_light'
        light_obj['qss_quake_classname'] = classname
        light_obj['qss_quake_light_value'] = float(effective_intensity)
        light_obj['qss_quake_raw_light_value'] = float(intensity)
        light_obj['qss_quake_world_range'] = float(world_range)
        light_obj['qss_quake_world_dist'] = float(world_dist)
        light_obj['qss_quake_anglescale'] = float(anglescale)
        light_obj['qss_applied_energy_scale'] = energy_scale
        light_obj['qss_quake_light_delay'] = int(_parse_entity_float(entity, 'delay', 0))
        light_obj['qss_quake_light_style'] = int(light_style)
        light_obj['qss_quake_style_was_inferred'] = bool(style_inferred)
        light_obj['qss_quake_color'] = list(color_rgb)
        light_obj['qss_energy_calibration'] = float(obj.get('qss_light_energy_calibration', 1.0))
        light_obj['qss_quake_origin'] = list(origin)
        light_obj['qss_quake_range'] = float(range_qu)
        light_obj['qss_quake_wait'] = float(wait)
        light_obj['qss_quake_falloff'] = float(falloff)
        light_obj['qss_quake_spot_angle'] = float(cone if is_spot else 40.0)
        light_obj['qss_quake_spot_softangle'] = float(soft_angle if is_spot else 0.0)
        light_obj['qss_quake_is_spot'] = bool(is_spot)
        if is_spot:
            light_obj['qss_quake_direction'] = list(raw_direction)
        light_obj['qss_quake_no_staticlight'] = bool(_parse_entity_float(entity, '_nostaticlight', 0.0) != 0.0)
        light_obj['qss_quake_world_dist'] = float(world_dist)
        light_obj['qss_quake_world_range'] = float(world_range)
        light_obj['qss_quake_delay_note'] = 'Native Blender live preview approximates delay; Quake Direct CPU Bake evaluates ericw attenuation.'
        light_count += 1

    # Worldspawn sunlight is a directional source in ericw-tools.
    sun_value = _parse_entity_float(world, '_sunlight', _parse_entity_float(world, '_sun_light', 0.0))
    if sun_value > 0.0:
        sun_data = bpy.data.lights.new('QSS_World_Sunlight', 'SUN')
        sun_obj = bpy.data.objects.new('QSS_World_Sunlight', sun_data)
        collection.objects.link(sun_obj)
        sun_color_raw = world.get('_sunlight_color', world.get('_sun_color', ''))
        sun_color = _parse_quake_light_color({'_color': sun_color_raw}, None) if sun_color_raw else (1.0, 1.0, 1.0)
        sun_data.color = sun_color
        sun_data.energy = lighting_utils.scaled_quake_light_energy(sun_value, energy_scale)
        sun_mangle = world.get('_sun_mangle', world.get('_sunlight_mangle', '0 -90 0'))
        proxy = {'mangle': sun_mangle}
        direction = _entity_spot_direction(proxy, {})
        if flip_z:
            direction.z = -direction.z
        sun_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
        penumbra = _parse_entity_float(world, '_sunlight_penumbra', 0.0)
        if hasattr(sun_data, 'angle'):
            sun_data.angle = math.radians(max(0.0, min(90.0, penumbra)))
        sun_obj['qss_light_role'] = 'quake_world_sunlight'
        sun_obj['qss_quake_light_value'] = float(sun_value)
        sun_obj['qss_applied_energy_scale'] = energy_scale
        light_count += 1

    if spawn is not None:
        origin, angle = spawn
        marker = bpy.data.objects.new('QSS_Info_Player_Start', None)
        marker.empty_display_type = 'CONE'
        marker.empty_display_size = max(0.1, 16.0 * unit_scale)
        marker.location = _quake_to_blender_position(origin, unit_scale, flip_z)
        collection.objects.link(marker)
        marker['qss_entity_role'] = 'info_player_start'
        marker['qss_quake_yaw'] = float(angle)
        eye_height = 22.0 * unit_scale
        view_origin = _quake_to_blender_position(origin, unit_scale, flip_z)
        view_origin = (view_origin[0], view_origin[1], view_origin[2] + (-eye_height if flip_z else eye_height))
        obj['qss_player_start'] = list(view_origin)
        obj['qss_player_yaw'] = float(angle)
        obj['qss_has_player_start'] = True
    else:
        obj['qss_has_player_start'] = False
    obj['qss_light_collection'] = collection.name
    obj['qss_light_entity_count'] = int(light_count)
    obj['qss_inferred_light_style_count'] = int(inferred_style_count)
    obj['qss_entity_count'] = len(entities)
    obj['qss_light_energy_scale'] = energy_scale
    return light_count, spawn is not None


def _frame_player_start(context, obj):
    """Place a 3D View camera at info_player_start and face its Quake yaw."""
    if not obj or not obj.get('qss_has_player_start'):
        return False
    from mathutils import Vector
    position = Vector(obj.get('qss_player_start', (0.0, 0.0, 0.0)))
    yaw = math.radians(float(obj.get('qss_player_yaw', 0.0)))
    forward = Vector((math.cos(yaw), math.sin(yaw), 0.0))
    rotation = forward.to_track_quat('-Z', 'Y')
    screen = getattr(context, 'screen', None)
    changed = False
    if screen is not None:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    region_3d = space.region_3d
                    region_3d.view_perspective = 'PERSP'
                    region_3d.view_rotation = rotation
                    region_3d.view_location = position
                    region_3d.view_distance = max(0.001, float(obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE)) * 0.5)
                    changed = True
    return changed

def _create_bsp_object(context, parsed, source_path, palette, game_dir, palette_file,
                       wad_textures=None, loose_textures=None, wad_sources=None, wad_unresolved=None, wad_failures=None,
                       unit_scale=DEFAULT_QUAKE_UNIT_SCALE, flip_z=False):
    source_path = bpy.path.abspath(source_path)
    game_dir = bpy.path.abspath(game_dir) if game_dir else ""
    palette_file = bpy.path.abspath(palette_file) if palette_file else ""
    vertices = parsed.vertices()
    edges = parsed.edges()
    surfedges = parsed.surfedges()
    texinfos = parsed.texinfos()
    faces = parsed.faces()
    entries, materials, material_by_miptex, missing_mat, texture_sources, missing_texture_names = (
        _load_quake_image_and_materials(parsed, palette, wad_textures, loose_textures)
    )

    mesh_vertices = []
    mesh_faces = []
    imported_face_ids = []
    imported_texinfo_ids = []
    imported_miptex_ids = []
    imported_materials = []
    imported_vertex_positions = []

    for face_id, face in enumerate(faces):
        try:
            vertex_ids = parsed.face_vertex_indices(face, edges, surfedges)
            if len(vertex_ids) < 3:
                continue
            if any(v < 0 or v >= len(vertices) for v in vertex_ids):
                continue
            positions = [vertices[v] for v in vertex_ids]
            start = len(mesh_vertices)
            # BSP positions remain in raw Quake units in imported_vertex_positions
            # for texinfo/lightmap maths. Blender mesh coordinates are converted
            # to metres (1 Quake unit ~= 1 inch) for usable viewport navigation.
            mesh_vertices.extend(_quake_to_blender_position(p, unit_scale, flip_z) for p in positions)
            mesh_faces.append(list(range(start, start + len(positions))))
            imported_vertex_positions.append(positions)
            texinfo_id = face[4]
            miptex_id = -1
            mat = missing_mat
            if 0 <= texinfo_id < len(texinfos):
                miptex_id = texinfos[texinfo_id][8]
                mat = material_by_miptex.get(miptex_id, missing_mat)
            imported_face_ids.append(face_id)
            imported_texinfo_ids.append(texinfo_id)
            imported_miptex_ids.append(miptex_id)
            imported_materials.append(mat)
        except bsp.BSPError:
            continue

    if not mesh_faces:
        raise bsp.BSPError("No importable BSP faces were found.")

    mesh = bpy.data.meshes.new(os.path.basename(source_path) + "_Mesh")
    mesh.from_pydata(mesh_vertices, [], mesh_faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(os.path.basename(source_path) + "_QSS", mesh)
    context.collection.objects.link(obj)

    material_slots = {}
    for mat in materials:
        if mat.name not in material_slots:
            obj.data.materials.append(mat)
            material_slots[mat.name] = len(obj.data.materials) - 1
    for poly, mat in zip(mesh.polygons, imported_materials):
        poly.material_index = material_slots[mat.name]

    uv_layer = mesh.uv_layers.new(name="Quake_Texture_UV")
    loop_cursor = 0
    for poly_index, poly in enumerate(mesh.polygons):
        face_id = imported_face_ids[poly_index]
        texinfo_id = imported_texinfo_ids[poly_index]
        tex_id = imported_miptex_ids[poly_index]
        positions = imported_vertex_positions[poly_index]
        if 0 <= texinfo_id < len(texinfos) and 0 <= tex_id < len(entries):
            ti = texinfos[texinfo_id]
            entry = entries[tex_id]
            width = max(1, entry.width)
            height = max(1, entry.height)
            svec = ti[0:4]
            tvec = ti[4:8]
            for local_index in range(len(poly.vertices)):
                p = positions[local_index]
                s = p[0] * svec[0] + p[1] * svec[1] + p[2] * svec[2] + svec[3]
                t = p[0] * tvec[0] + p[1] * tvec[1] + p[2] * tvec[2] + tvec[3]
                uv_layer.data[loop_cursor + local_index].uv = (s / width, 1.0 - t / height)
        loop_cursor += len(poly.vertices)

    attrs = _get_or_make_face_attributes(mesh)
    for i in range(len(imported_face_ids)):
        attrs['qss_bsp_face_id'].data[i].value = imported_face_ids[i]
        attrs['qss_bsp_texinfo_id'].data[i].value = imported_texinfo_ids[i]
        attrs['qss_bsp_miptex_id'].data[i].value = imported_miptex_ids[i]

    obj['qss_object_role'] = 'quake_bsp29'
    obj['qss_source_path'] = os.path.abspath(source_path)
    obj['qss_game_dir'] = os.path.abspath(game_dir) if game_dir else ''
    obj['qss_palette_file'] = os.path.abspath(palette_file) if palette_file else ''
    obj['qss_bsp_version'] = bsp.BSP_VERSION
    obj['qss_unit_scale'] = float(unit_scale)
    obj['qss_flip_z'] = bool(flip_z)
    obj['qss_imported_face_count'] = len(imported_face_ids)
    obj['qss_total_bsp_faces'] = len(faces)
    obj['qss_bspx_lump_names'] = ', '.join(sorted(parsed.bspx_lumps.keys()))
    obj['qss_texture_count'] = len(entries)
    obj['qss_texture_sources'] = str(texture_sources)
    obj['qss_texture_embedded_count'] = int(texture_sources.get('embedded', 0))
    obj['qss_texture_wad_count'] = int(texture_sources.get('wad', 0))
    obj['qss_texture_loose_count'] = int(texture_sources.get('loose', 0))
    obj['qss_texture_white_count'] = int(texture_sources.get('white_fallback', 0))
    obj['qss_missing_texture_names'] = ', '.join(missing_texture_names)[:2000]
    obj['qss_wad_sources'] = '; '.join(wad_sources or [])[:2000]
    obj['qss_wad_unresolved'] = '; '.join(wad_unresolved or [])[:2000]
    obj['qss_wad_failures'] = '; '.join(wad_failures or [])[:2000]
    obj['qss_palette_available'] = True
    source_lit_path = os.path.splitext(source_path)[0] + '.lit'
    source_lit_rgb, source_lighting_kind = bsp.resolve_rgb_lighting(
        parsed.bspx_lumps, parsed.lumps[bsp.LUMP_LIGHTING], source_lit_path
    )
    obj['qss_source_lit_path'] = source_lit_path if source_lighting_kind == 'QLIT v1 .lit sidecar' else ''
    obj['qss_source_lighting_source'] = source_lighting_kind
    atlas_lighting = parsed.lumps[bsp.LUMP_LIGHTING]
    if not atlas_lighting and source_lit_rgb is not None:
        atlas_lighting = bsp.rgb_lighting_to_luminance(source_lit_rgb)
        obj['qss_rgb_only_lighting'] = True
    else:
        obj['qss_rgb_only_lighting'] = False
    _build_lightmap_atlas(
        obj, mesh, parsed, imported_face_ids, imported_texinfo_ids, imported_vertex_positions,
        source_lit_rgb, lighting_data=atlas_lighting
    )

    # Preserve the source BSP's original face indexing for the exporter.
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


@lru_cache(maxsize=4)
def _palette_nearest_lookup(palette, allow_transparency):
    # 5-bit-per-channel lookup table: one-time palette search, cheap per pixel.
    allowed = range(255) if allow_transparency else range(256)
    cols = [(palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]) for i in allowed]
    lookup = bytearray(32 * 32 * 32)
    for r5 in range(32):
        r = r5 * 255.0 / 31.0
        for g5 in range(32):
            g = g5 * 255.0 / 31.0
            for b5 in range(32):
                b = b5 * 255.0 / 31.0
                best_idx = 0
                best_d = 1e30
                for idx, (pr, pg, pb) in enumerate(cols):
                    dr, dg, db = r - pr, g - pg, b - pb
                    # Green-weighted distance works better for classic RGB palettes.
                    d = 0.30 * dr * dr + 0.59 * dg * dg + 0.11 * db * db
                    if d < best_d:
                        best_d = d
                        best_idx = idx
                lookup[(r5 * 32 + g5) * 32 + b5] = best_idx
    return lookup


def _downsample_rgba(src, width, height):
    out_w, out_h = max(1, width // 2), max(1, height // 2)
    out = array.array('f')
    for y in range(out_h):
        for x in range(out_w):
            sums = [0.0, 0.0, 0.0, 0.0]
            count = 0
            for dy in range(2):
                for dx in range(2):
                    sx, sy = min(width - 1, x * 2 + dx), min(height - 1, y * 2 + dy)
                    p = (sy * width + sx) * 4
                    alpha = max(0.0, min(1.0, src[p + 3]))
                    sums[0] += src[p] * alpha
                    sums[1] += src[p + 1] * alpha
                    sums[2] += src[p + 2] * alpha
                    sums[3] += alpha
                    count += 1
            alpha_out = sums[3] / count
            if sums[3] > 1e-8:
                out.extend((sums[0] / sums[3], sums[1] / sums[3], sums[2] / sums[3], alpha_out))
            else:
                out.extend((0.0, 0.0, 0.0, 0.0))
    return out_w, out_h, out


def _encode_image_to_miptex(image, palette, texture_name):
    width, height = int(image.size[0]), int(image.size[1])
    if width < 16 or height < 16 or width > 512 or height > 512:
        raise bsp.BSPError(f"Image '{image.name}' is {width}x{height}; export requires dimensions from 16 to 512.")
    if width & (width - 1) or height & (height - 1):
        raise bsp.BSPError(f"Image '{image.name}' is {width}x{height}; width and height must be powers of two.")

    special = texture_name.startswith('{')
    lut = _palette_nearest_lookup(palette, special)
    is_float_buffer = bool(getattr(image, 'is_float', False))
    px = array.array('f', [0.0]) * (width * height * 4)
    image.update()
    image.pixels.foreach_get(px)
    # Convert Blender's bottom-up linear pixels into Quake's top-down mip rows.
    current = array.array('f')
    for y in range(height - 1, -1, -1):
        start = y * width * 4
        current.extend(px[start:start + width * 4])

    levels = []
    w, h, rgba = width, height, current
    for level in range(4):
        indexed = bytearray(w * h)
        for i in range(w * h):
            p = i * 4
            alpha = rgba[p + 3]
            if special and alpha < 0.5:
                indexed[i] = 255
                continue
            # bpy Image.pixels for byte buffers contains values encoded in the
            # image's assigned colour space (sRGB here); float buffers contain
            # scene-linear values. Convert only the latter.
            r = int(round(color.blender_pixel_to_quake_code(rgba[p], is_float_buffer) * 255.0))
            g = int(round(color.blender_pixel_to_quake_code(rgba[p + 1], is_float_buffer) * 255.0))
            b = int(round(color.blender_pixel_to_quake_code(rgba[p + 2], is_float_buffer) * 255.0))
            index = lut[((r >> 3) * 32 + (g >> 3)) * 32 + (b >> 3)]
            indexed[i] = index
        levels.append(bytes(indexed))
        if level < 3:
            w, h, rgba = _downsample_rgba(rgba, w, h)
    return bsp.build_miptex_blob(texture_name, width, height, levels)


def _safe_texture_name(value, fallback):
    value = str(value or fallback).strip()
    value = re.sub(r'[^A-Za-z0-9_*+\-]', '_', value)
    if not value:
        value = fallback
    return value[:15]


def _export_object(obj, output_path):
    if obj.get('qss_object_role') != 'quake_bsp29':
        raise bsp.BSPError("Active object is not a Quake Surface Studio BSP29 import.")
    source_path = obj.get('qss_source_path', '')
    if not source_path or not os.path.isfile(source_path):
        raise bsp.BSPError("The original BSP path is unavailable. Keep the original BSP at its import location.")
    parsed = bsp.BSP29.from_file(source_path)
    game_dir = obj.get('qss_game_dir', '')
    palette_file = obj.get('qss_palette_file', '')
    palette, palette_origin = bsp.find_quake_palette(game_dir, palette_file)
    if palette is None:
        raise bsp.BSPError(
            "Could not find gfx/palette.lmp. Re-import with the Quake game directory, "
            "or place palette.lmp in the game's gfx folder."
        )

    mesh = obj.data
    face_attr = mesh.attributes.get('qss_bsp_face_id')
    if face_attr is None or face_attr.domain != 'FACE':
        raise bsp.BSPError("The BSP face-ID attribute is missing. Do not dissolve or rebuild imported faces.")
    faces = parsed.faces()
    texinfos = parsed.texinfos()
    entries = parsed.miptextures()
    if len(entries) > bsp.MAX_CLASSIC_TEXTURES:
        raise bsp.BSPError("The source BSP already exceeds the conservative classic texture count limit.")

    face_ids = [int(item.value) for item in face_attr.data]
    if len(face_ids) != len(mesh.polygons):
        raise bsp.BSPError("Face-ID attribute count no longer matches the mesh polygons.")
    if len(set(face_ids)) != len(face_ids):
        raise bsp.BSPError("Duplicate BSP face IDs were detected. Duplicate faces cannot be exported in this prototype.")
    for face_id in face_ids:
        if face_id < 0 or face_id >= len(faces):
            raise bsp.BSPError(f"BSP face ID {face_id} is out of range.")

    # First encode only new/detached materials and edited existing images.
    new_texture_for_material = {}
    replacements = {}
    for mat in obj.data.materials:
        if mat is None or 'qss_texture_index' not in mat:
            continue
        source_texture_id = int(mat.get('qss_texture_index', -2))
        image = _find_image(mat)
        if image is None:
            continue
        digest = _image_hash(image)
        baseline = image.get('qss_import_hash', '')
        if source_texture_id == -1:
            key = mat.as_pointer()
            if key not in new_texture_for_material:
                fallback = f"qss_{len(entries) + len(new_texture_for_material):05d}"
                tex_name = _safe_texture_name(mat.get('qss_export_name', ''), fallback)
                blob = _encode_image_to_miptex(image, palette, tex_name)
                new_texture_for_material[key] = len(entries) + len(new_texture_for_material)
                entries.append(bsp.MipTexture(blob, tex_name, image.size[0], image.size[1]))
            continue
        if source_texture_id >= 0 and source_texture_id < len(entries) and digest != baseline:
            fallback = entries[source_texture_id].name or f"qss_{source_texture_id:05d}"
            tex_name = _safe_texture_name(mat.get('qss_export_name', ''), fallback)
            blob = _encode_image_to_miptex(image, palette, tex_name)
            prior = replacements.get(source_texture_id)
            if prior and prior[0] != digest:
                raise bsp.BSPError(
                    f"Multiple Blender materials contain different edits for shared BSP texture {source_texture_id}. "
                    "Use 'Detach Selected Faces' before painting a face independently."
                )
            replacements[source_texture_id] = (digest, bsp.MipTexture(blob, tex_name, image.size[0], image.size[1]))

    for texture_id, (_, replacement) in replacements.items():
        entries[texture_id] = replacement
    if len(entries) > bsp.MAX_CLASSIC_TEXTURES:
        raise bsp.BSPError(
            f"Export would create {len(entries)} textures, beyond the conservative classic Quake limit ({bsp.MAX_CLASSIC_TEXTURES})."
        )

    # For every face whose material now points to another texture, clone its
    # texinfo record and redirect only that face.
    texinfo_lump = parsed.lumps[bsp.LUMP_TEXINFO]
    faces_lump = parsed.lumps[bsp.LUMP_FACES]
    variant_cache = {}
    new_faces_lump = faces_lump
    new_texinfo_lump = texinfo_lump
    changed_face_assignments = 0

    for poly, face_id in zip(mesh.polygons, face_ids):
        if poly.material_index < 0 or poly.material_index >= len(obj.data.materials):
            continue
        if poly.material_index < 0 or poly.material_index >= len(obj.data.materials):
            continue
        mat = obj.data.materials[poly.material_index]
        if mat is None or 'qss_texture_index' not in mat:
            raise bsp.BSPError(
                f"Face {face_id} uses a material without Quake metadata. Use an imported material or Detach Selected Faces."
            )
        source_texture_id = int(mat.get('qss_texture_index', -2))
        if source_texture_id == -2:
            continue
        if source_texture_id == -1:
            target_texture_id = new_texture_for_material.get(mat.as_pointer())
            if target_texture_id is None:
                raise bsp.BSPError(f"New material '{mat.name}' has no image texture to export.")
        else:
            target_texture_id = source_texture_id
            if target_texture_id >= len(entries):
                raise bsp.BSPError(f"Material '{mat.name}' points to missing miptex {target_texture_id}.")

        original_face = faces[face_id]
        original_texinfo = original_face[4]
        if original_texinfo < 0 or original_texinfo >= len(texinfos):
            raise bsp.BSPError(f"Face {face_id} has an invalid original texinfo index.")
        original_texture_id = texinfos[original_texinfo][8]
        if target_texture_id == original_texture_id:
            continue
        custom_projection = mat.get('qss_texinfo_projection') if mat.get('qss_face_local_projection') else None
        if custom_projection is not None:
            projection_key = tuple(float(v) for v in custom_projection)
            if len(projection_key) != 8:
                raise bsp.BSPError(f"Material '{mat.name}' has an invalid face-local texinfo projection.")
            key = (original_texinfo, target_texture_id, projection_key)
        else:
            projection_key = None
            key = (original_texinfo, target_texture_id, None)
        if key not in variant_cache:
            if projection_key is not None:
                new_texinfo_lump, new_index = bsp.clone_texinfo_with_projection(
                    new_texinfo_lump, original_texinfo, target_texture_id, projection_key
                )
            else:
                new_texinfo_lump, new_index = bsp.clone_texinfo(
                    new_texinfo_lump, original_texinfo, target_texture_id
                )
            variant_cache[key] = new_index
        new_faces_lump = bsp.replace_face_texinfo(new_faces_lump, face_id, variant_cache[key])
        changed_face_assignments += 1

    new_lumps = list(parsed.lumps)
    new_lumps[bsp.LUMP_TEXTURES] = bsp.build_texture_lump(entries)
    new_lumps[bsp.LUMP_TEXINFO] = new_texinfo_lump
    new_lumps[bsp.LUMP_FACES] = new_faces_lump
    lighting_lump, lit_file_data = _patch_lightmap_lump(obj, parsed)
    new_lumps[bsp.LUMP_LIGHTING] = lighting_lump
    new_bspx_lumps = dict(parsed.bspx_lumps)
    if lit_file_data is not None:
        # BSPX RGBLIGHTING is QLIT v1's RGB payload without the 8-byte header.
        # Keep the .lit sidecar too for ports which prefer the external format.
        new_bspx_lumps['RGBLIGHTING'] = lit_file_data[8:]
    output_data = parsed.write(new_lumps, new_bspx_lumps)

    output_path = os.path.abspath(bpy.path.abspath(output_path))
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(output_data)
    lit_output_path = ''
    if lit_file_data is not None:
        lit_output_path = os.path.splitext(output_path)[0] + '.lit'
        with open(lit_output_path, 'wb') as f:
            f.write(lit_file_data)
    return output_path, len(entries), changed_face_assignments, len(replacements), palette_origin, lit_output_path


def _apply_map_view_clipping(context, obj):
    """Fit 3D View near/far clip planes to the imported Quake map bounds."""
    coords = [tuple(v.co) for v in obj.data.vertices]
    if not coords:
        return 0.01, 1000.0
    mins = [min(co[i] for co in coords) for i in range(3)]
    maxs = [max(co[i] for co in coords) for i in range(3)]
    diagonal = math.sqrt(sum((maxs[i] - mins[i]) ** 2 for i in range(3)))
    diagonal = max(diagonal, 1.0)
    # Keep the depth-buffer ratio in a useful range for ordinary Quake map
    # scales, while avoiding a near plane so large that nearby walls vanish.
    clip_start = max(0.01, min(0.5, diagonal * 0.00005))
    clip_end = max(100.0, diagonal * 3.0, clip_start * 10000.0)
    screen = getattr(context, 'screen', None)
    if screen is not None:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_start = clip_start
                    space.clip_end = clip_end
    obj['qss_view_clip_start'] = clip_start
    obj['qss_view_clip_end'] = clip_end
    obj['qss_bounds_diagonal'] = diagonal
    return clip_start, clip_end


def _configure_quake_walk_speed(context, obj):
    """Map Quake's 320 units/s run speed into Blender metres/s."""
    unit_scale = float(obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE))
    speed_qu = float(getattr(context.scene, 'qss_nav_speed_quake', 320.0))
    speed_m = max(0.01, min(100.0, speed_qu * unit_scale))
    fast_factor = max(1.0, min(10.0, float(getattr(context.scene, 'qss_nav_fast_factor', 3.0))))
    try:
        walk = context.preferences.inputs.walk_navigation
        walk.walk_speed = speed_m
        walk.walk_speed_factor = fast_factor
        walk.view_height = 22.0 * unit_scale
        # Free-fly navigation is intentional until collision-aware player movement exists.
        walk.use_gravity = False
        return speed_qu, speed_m, fast_factor
    except Exception:
        return speed_qu, speed_m, fast_factor


class QSS_OT_optimize_clipping(Operator):
    bl_idname = "qss.optimize_view_clipping"
    bl_label = "Optimize View Clipping"
    bl_description = "Set 3D View clip start/end from the imported BSP bounds to reduce depth-buffer z-fighting"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29')

    def execute(self, context):
        start, end = _apply_map_view_clipping(context, context.object)
        _report(self, 'INFO', f"Viewport clipping set to {start:.4g} – {end:.4g} Blender units.")
        return {'FINISHED'}


class QSS_OT_fps_walk(Operator):
    bl_idname = "qss.fps_walk"
    bl_label = "FPS / Walk Navigation"
    bl_description = "Enter Blender's first-person Walk Navigation after fitting clip planes to the imported Quake map"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29')

    def execute(self, context):
        obj = context.object
        _apply_map_view_clipping(context, obj)
        _configure_quake_walk_speed(context, obj)
        # Re-center at the Quake player start for each navigation session.
        _frame_player_start(context, obj)
        screen = getattr(context, 'screen', None)
        preferred_area = context.area if getattr(context.area, 'type', None) == 'VIEW_3D' else None
        areas = ([preferred_area] if preferred_area else []) + [
            a for a in (screen.areas if screen else [])
            if a.type == 'VIEW_3D' and a is not preferred_area
        ]
        for area in areas:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            try:
                space = next((sp for sp in area.spaces if sp.type == 'VIEW_3D'), None)
                if space and space.region_3d.view_perspective == 'ORTHO':
                    space.region_3d.view_perspective = 'PERSP'
                with context.temp_override(window=context.window, area=area, region=region):
                    bpy.ops.view3d.walk('INVOKE_DEFAULT')
                return {'FINISHED'}
            except Exception as exc:
                _report(self, 'ERROR', f"Could not start Blender Walk Navigation: {exc}")
                return {'CANCELLED'}
        _report(self, 'WARNING', "No 3D View found. Run FPS / Walk Navigation from a 3D View.")
        return {'CANCELLED'}



class QSS_OT_hold_mmb_fps(Operator):
    """Hold MMB to look; WASD moves only while the corresponding key is held."""
    bl_idname = 'qss.hold_mmb_fps'
    bl_label = 'Hold MMB for WASD Navigation'
    bl_options = {'INTERNAL'}

    _move_keys = {'W', 'A', 'S', 'D', 'Q', 'E', 'LEFT_SHIFT', 'RIGHT_SHIFT'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(context.area and context.area.type == 'VIEW_3D' and obj and
                    obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29')

    def _finish(self, context):
        try:
            if self._timer is not None:
                context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        try:
            context.area.header_text_set(None)
        except Exception:
            pass
        return {'FINISHED'}

    def invoke(self, context, event):
        from mathutils import Vector
        if context.area.type != 'VIEW_3D' or context.region is None:
            return {'CANCELLED'}
        self._area = context.area
        self._region = context.region
        self._rv3d = context.space_data.region_3d
        if self._rv3d.view_perspective == 'ORTHO':
            self._rv3d.view_perspective = 'PERSP'
        if self._rv3d.view_perspective == 'CAMERA':
            self._rv3d.view_perspective = 'PERSP'
        self._view_distance = max(0.001, float(self._rv3d.view_distance))
        self._rotation = self._rv3d.view_rotation.copy()
        forward = self._rotation @ Vector((0.0, 0.0, -1.0))
        self._yaw = math.atan2(forward.y, forward.x)
        self._pitch = math.asin(max(-1.0, min(1.0, forward.z)))
        self._camera = self._rv3d.view_location.copy() + self._rotation @ Vector((0.0, 0.0, self._view_distance))
        self._last_mouse = (event.mouse_x, event.mouse_y)
        self._keys_down = set()
        self._last_time = time.monotonic()
        self._timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        obj = context.object
        _apply_map_view_clipping(context, obj)
        unit_scale = float(obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE))
        self._unit_scale = unit_scale
        self._speed = float(context.scene.qss_nav_speed_quake) * unit_scale
        self._fast_factor = float(context.scene.qss_nav_fast_factor)
        self._scene = context.scene
        self._window = context.window
        try:
            context.window.cursor_modal_set('NONE')
        except Exception:
            pass
        context.area.header_text_set('QSS FPS: hold MMB | WASD move | Q/E down/up | Shift fast | release MMB to exit')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _move_with_wall_collision(self, context, displacement, right):
        """Simple eye-level ray collision and slide against the imported BSP mesh."""
        from mathutils import Vector
        length = displacement.length
        if length <= 1e-8:
            return Vector((0.0, 0.0, 0.0))
        direction = displacement.normalized()
        radius = 8.0 * self._unit_scale
        depsgraph = context.evaluated_depsgraph_get()
        best_hit = None
        offsets = (Vector((0.0, 0.0, 0.0)), right * radius, -right * radius)
        for offset in offsets:
            hit, location, normal, _face_index, _hit_obj, _matrix = context.scene.ray_cast(
                depsgraph, self._camera + offset, direction, distance=length + radius
            )
            if hit:
                hit_distance = (location - (self._camera + offset)).length
                if best_hit is None or hit_distance < best_hit[0]:
                    best_hit = (hit_distance, normal.copy())
        if best_hit is None:
            return displacement
        hit_distance, normal = best_hit
        safe_distance = max(0.0, min(length, hit_distance - radius))
        safe_move = direction * safe_distance
        remaining = displacement - safe_move
        if normal.dot(displacement) > 0.0:
            normal.negate()
        into_wall = remaining.dot(normal)
        if into_wall < 0.0:
            remaining -= normal * into_wall
        return safe_move + remaining

    def modal(self, context, event):
        from mathutils import Vector
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            return self._finish(context)
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self._finish(context)
        if event.type in self._move_keys:
            if event.value == 'PRESS':
                self._keys_down.add(event.type)
            elif event.value == 'RELEASE':
                self._keys_down.discard(event.type)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            dx = event.mouse_x - self._last_mouse[0]
            dy = event.mouse_y - self._last_mouse[1]
            self._last_mouse = (event.mouse_x, event.mouse_y)
            sensitivity = 0.0022
            self._yaw += dx * sensitivity
            self._pitch = max(math.radians(-89.0), min(math.radians(89.0), self._pitch + dy * sensitivity))
            cp = math.cos(self._pitch)
            forward3 = Vector((cp * math.cos(self._yaw), cp * math.sin(self._yaw), math.sin(self._pitch)))
            self._rotation = forward3.to_track_quat('-Z', 'Y')
            self._rv3d.view_rotation = self._rotation
            self._rv3d.view_location = self._camera - self._rotation @ Vector((0.0, 0.0, self._view_distance))
            return {'RUNNING_MODAL'}
        if event.type == 'TIMER' and event.timer == self._timer:
            now = time.monotonic()
            dt = max(0.0, min(0.05, now - self._last_time))
            self._last_time = now
            if self._keys_down:
                forward = Vector((math.cos(self._yaw), math.sin(self._yaw), 0.0))
                right = Vector((-math.sin(self._yaw), math.cos(self._yaw), 0.0))
                move = Vector((0.0, 0.0, 0.0))
                if 'W' in self._keys_down: move += forward
                if 'S' in self._keys_down: move -= forward
                if 'D' in self._keys_down: move += right
                if 'A' in self._keys_down: move -= right
                if 'E' in self._keys_down: move.z += 1.0
                if 'Q' in self._keys_down: move.z -= 1.0
                if move.length > 1e-8:
                    move.normalize()
                    fast_held = bool({'LEFT_SHIFT', 'RIGHT_SHIFT'} & self._keys_down)
                    speed = self._speed * (self._fast_factor if fast_held else 1.0)
                    right_vector = right
                    displacement = move * speed * dt
                    displacement = self._move_with_wall_collision(context, displacement, right_vector)
                    self._camera += displacement
                    self._rv3d.view_location = self._camera - self._rotation @ Vector((0.0, 0.0, self._view_distance))
            return {'RUNNING_MODAL'}
        # Consume remaining events while MMB is held so Blender's orbit/zoom
        # operators cannot race this modal camera transform.
        return {'RUNNING_MODAL'}


class QSS_OT_player_start(Operator):
    bl_idname = "qss.goto_player_start"
    bl_label = "Go to info_player_start"
    bl_description = "Move the active 3D View to the BSP's player start and face its Quake yaw"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.get('qss_object_role') == 'quake_bsp29' and obj.get('qss_has_player_start'))

    def execute(self, context):
        if _frame_player_start(context, context.object):
            self.report({'INFO'}, "Viewport moved to info_player_start.")
            return {'FINISHED'}
        self.report({'WARNING'}, "No 3D View found or this BSP has no info_player_start.")
        return {'CANCELLED'}


class QSS_OT_import_bsp(Operator, ImportHelper):
    bl_idname = "qss.import_bsp"
    bl_label = "Import Quake BSP29"
    bl_description = "Import classic Quake BSP29 geometry, textures, entity lights and BSPX RGB lightmaps"
    filename_ext = ".bsp"
    filter_glob: StringProperty(default="*.bsp", options={'HIDDEN'})
    game_dir: StringProperty(name="Quake game directory", subtype='DIR_PATH', default="")
    palette_file: StringProperty(name="palette.lmp (optional)", subtype='FILE_PATH', default="")
    unit_scale: FloatProperty(
        name="Quake unit scale", description="Blender metres per Quake map unit (1 Quake unit is conventionally about 1 inch)",
        default=DEFAULT_QUAKE_UNIT_SCALE, min=0.0001, max=10.0, precision=5
    )
    flip_z: BoolProperty(
        name="Invert Z axis", description="Only for non-standard/converter-generated BSPs that use Z-down coordinates",
        default=False
    )

    def invoke(self, context, event):
        self.game_dir = context.scene.qss_game_dir
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'game_dir')
        layout.prop(self, 'palette_file')
        layout.separator()
        layout.prop(self, 'unit_scale')
        layout.prop(self, 'flip_z')

    def execute(self, context):
        try:
            source_path = bpy.path.abspath(self.filepath)
            game_dir = bpy.path.abspath(self.game_dir) if self.game_dir else ""
            palette_file = bpy.path.abspath(self.palette_file) if self.palette_file else ""
            parsed = bsp.BSP29.from_file(source_path)
            palette, palette_origin = bsp.find_quake_palette(game_dir, palette_file)
            if palette is None:
                raise bsp.BSPError(
                    "Could not locate the Quake palette. Set 'Quake game directory' to the folder containing id1, "
                    "or choose gfx/palette.lmp explicitly."
                )
            wad_paths, unresolved_wads = _resolve_worldspawn_wads(parsed, source_path, game_dir)
            wad_textures, loaded_wads, wad_failures = _load_wad_texture_index(wad_paths)
            loose_textures = _index_external_texture_files(source_path, game_dir)
            obj = _create_bsp_object(
                context, parsed, source_path, palette, game_dir, palette_file,
                wad_textures, loose_textures, loaded_wads, unresolved_wads, wad_failures,
                unit_scale=self.unit_scale, flip_z=self.flip_z
            )
            light_count, has_spawn = _import_bsp_entities(
                context, obj, parsed, self.unit_scale, self.flip_z
            )
            context.scene.qss_game_dir = game_dir
            context.scene.qss_quake_unit_scale = float(self.unit_scale)
            # Fit the view's depth buffer and start at info_player_start when available.
            _apply_map_view_clipping(context, obj)
            _frame_player_start(context, obj)
            lit_source = obj.get('qss_source_lighting_source', 'Monochrome BSP lighting')
            lit_note = f" RGB lightmaps: {lit_source}." if obj.get('qss_lit_rgb_faces', 0) else " No RGB lightmaps found; atlas starts grayscale."
            texture_note = (f" Textures: {obj.get('qss_texture_embedded_count', 0)} embedded, "
                            f"{obj.get('qss_texture_wad_count', 0)} WAD, {obj.get('qss_texture_loose_count', 0)} external, "
                            f"{obj.get('qss_texture_white_count', 0)} white fallback.")
            spawn_note = " Spawn view set to info_player_start." if has_spawn else " No info_player_start found."
            _report(self, 'INFO', f"Imported {len(obj.data.polygons)} faces, {light_count} light entities. Palette: {palette_origin}.{texture_note}{lit_note}{spawn_note}")
            return {'FINISHED'}
        except Exception as exc:
            _report(self, 'ERROR', str(exc))
            return {'CANCELLED'}


class QSS_OT_detach_faces(Operator):
    bl_idname = "qss.detach_selected_faces"
    bl_label = "Detach Selected Faces"
    bl_description = "Create an individually paintable, face-local texture for each selected BSP face"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(
            obj and obj.type == 'MESH'
            and obj.get('qss_object_role') == 'quake_bsp29'
            and context.mode in {'OBJECT', 'EDIT_MESH'}
        )

    def execute(self, context):
        import bmesh
        obj = context.object
        mesh = obj.data
        was_edit_mode = (context.mode == 'EDIT_MESH')
        stage = 'read selection'
        created_images = []
        created_materials = []
        plans = []
        selected_indices = []

        try:
            if was_edit_mode:
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                bm.faces.index_update()
                selected_indices = [face.index for face in bm.faces if face.select]
                # Flush Edit Mode's BMesh before reading Mesh UV/attribute
                # collections. The old code mixed BMesh selections with stale
                # mesh polygons/UV data and could index empty collections.
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
                bpy.ops.object.mode_set(mode='OBJECT')
                # Reacquire all RNA wrappers after the mode transition. A cached
                # layer.data collection can be invalidated by Blender's BMesh sync.
                mesh = obj.data
                mesh.update()
                uv_layer = mesh.uv_layers.get('Quake_Texture_UV')
                if len(mesh.polygons) == 0 or len(mesh.loops) == 0:
                    raise bsp.BSPError(
                        'Blender returned an empty mesh after leaving Edit Mode. Save the file, '
                        're-import the BSP and try selecting the face again in Object Mode first.'
                    )
            else:
                selected_indices = [poly.index for poly in mesh.polygons if poly.select]

            if not selected_indices:
                if was_edit_mode:
                    bpy.ops.object.mode_set(mode='EDIT')
                _report(self, 'WARNING', "No faces selected. Use Face Select and select at least one face.")
                return {'CANCELLED'}

            stage = 'validate source BSP path'
            source_path = obj.get('qss_source_path', '')
            if not source_path or not os.path.isfile(source_path):
                raise bsp.BSPError("The original BSP path is unavailable; face-local texture projection cannot be calculated.")
            parsed = bsp.BSP29.from_file(source_path)
            texinfos = parsed.texinfos()

            stage = 'validate mesh UV and face ID collections'
            uv_layer = mesh.uv_layers.get('Quake_Texture_UV')
            if uv_layer is None:
                raise bsp.BSPError("Quake_Texture_UV was lost during Edit Mode synchronization. Re-import the BSP before detaching faces.")
            face_ids_attr = mesh.attributes.get('qss_bsp_face_id')
            texinfo_ids_attr = mesh.attributes.get('qss_bsp_texinfo_id')
            if uv_layer is None:
                raise bsp.BSPError("This mesh is missing Quake texture UVs. Re-import the BSP.")
            face_attrs = _qss_validate_face_domain_attributes(
                mesh, ('qss_bsp_face_id', 'qss_bsp_texinfo_id'), 'detach selected faces'
            )
            face_ids_attr = face_attrs['qss_bsp_face_id']
            texinfo_ids_attr = face_attrs['qss_bsp_texinfo_id']
            if len(uv_layer.data) != len(mesh.loops):
                raise bsp.BSPError(
                    f"Texture UV data has {len(uv_layer.data)} entries for {len(mesh.loops)} loops. Re-import the BSP."
                )
            for name, attr in (('face IDs', face_ids_attr), ('texinfo IDs', texinfo_ids_attr)):
                if len(attr.data) != len(mesh.polygons):
                    raise bsp.BSPError(
                        f"{name} collection has {len(attr.data)} entries for {len(mesh.polygons)} polygons. Re-import the BSP."
                    )

            stage = 'prepare face-local paint images'
            for poly_index in selected_indices:
                if poly_index < 0 or poly_index >= len(mesh.polygons):
                    raise bsp.BSPError(f"Selected polygon index {poly_index} is outside the current mesh ({len(mesh.polygons)} polygons).")
                poly = mesh.polygons[poly_index]
                source_index = int(poly.material_index)
                if source_index < 0 or source_index >= len(mesh.materials):
                    raise bsp.BSPError(f"Face {poly_index} has invalid material slot {source_index}; slots={len(mesh.materials)}.")
                source_mat = mesh.materials[source_index]
                source_image = _find_image(source_mat, 'base_texture') if source_mat else None
                if source_mat is None or source_image is None:
                    raise bsp.BSPError(f"Face {poly_index} has no source texture image to detach.")
                face_id = int(_qss_safe_collection_item(face_ids_attr.data, poly_index, 'BSP face ID attribute').value)
                texinfo_id = int(_qss_safe_collection_item(texinfo_ids_attr.data, poly_index, 'BSP texinfo ID attribute').value)
                if texinfo_id < 0 or texinfo_id >= len(texinfos):
                    raise bsp.BSPError(f"BSP face {face_id} has invalid texinfo {texinfo_id}.")
                loop_indices = tuple(poly.loop_indices)
                if len(loop_indices) != len(poly.vertices) or any(i < 0 or i >= len(uv_layer.data) for i in loop_indices):
                    raise bsp.BSPError(
                        f"Face {face_id} has invalid UV loop references; loops={len(loop_indices)}, UV entries={len(uv_layer.data)}."
                    )
                image_name = f"QSS_Face_{face_id:05d}_Paint"
                image, normalized_uvs, bounds, out_size = _bake_face_local_texture(
                    source_image, uv_layer, poly, image_name
                )
                created_images.append(image)
                projection = _face_local_texinfo_projection(texinfos[texinfo_id], bounds, out_size)
                plans.append({
                    'poly_index': poly_index,
                    'face_id': face_id,
                    'source_mat': source_mat,
                    'source_index': source_index,
                    'old_uvs': [tuple(_qss_safe_collection_item(uv_layer.data, i, 'Quake texture UV').uv) for i in loop_indices],
                    'loop_indices': loop_indices,
                    'image': image,
                    'uvs': normalized_uvs,
                    'projection': projection,
                })

            stage = 'create detached material copies'
            for plan in plans:
                new_mat = plan['source_mat'].copy()
                created_materials.append(new_mat)
                new_mat.name = f"QSS_Detached_F{plan['face_id']:05d}"
                new_mat['qss_texture_index'] = -1
                new_mat['qss_is_new_texture'] = True
                source_texture_name = str(plan['source_mat'].get('qss_texture_name', ''))
                if source_texture_name.startswith('sky'):
                    texture_prefix = 'sky'
                elif source_texture_name.startswith(('*', '{')):
                    texture_prefix = source_texture_name[0]
                else:
                    texture_prefix = ''
                new_mat['qss_export_name'] = (texture_prefix + f"qssf{plan['face_id']:05d}")[:15]
                new_mat['qss_texture_name'] = new_mat['qss_export_name']
                new_mat['qss_face_local_projection'] = True
                new_mat['qss_texinfo_projection'] = [float(v) for v in plan['projection']]
                _set_material_image(new_mat, plan['image'])
                plan['new_mat'] = new_mat

            stage = 'assign detached materials and normalized UVs'
            last_new_index = -1
            for plan in plans:
                mesh.materials.append(plan['new_mat'])
                material_index = len(mesh.materials) - 1
                poly = mesh.polygons[plan['poly_index']]
                poly.material_index = material_index
                for loop_index, uv_value in zip(plan['loop_indices'], plan['uvs']):
                    if loop_index >= len(uv_layer.data):
                        raise bsp.BSPError(
                            f"UV collection changed during detach (loop {loop_index}, size {len(uv_layer.data)})."
                        )
                    _qss_safe_collection_item(uv_layer.data, loop_index, 'Quake texture UV').uv = uv_value
                last_new_index = material_index
            if last_new_index >= 0:
                obj.active_material_index = last_new_index
            mesh.update()

            if was_edit_mode:
                stage = 'restore Edit Mode selection'
                bpy.ops.object.mode_set(mode='EDIT')
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                bm.faces.index_update()
                selected_set = set(selected_indices)
                for face in bm.faces:
                    face.select_set(face.index in selected_set)
                if selected_indices and max(selected_indices) < len(bm.faces):
                    bm.faces.active = bm.faces[selected_indices[-1]]
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

            _report(
                self, 'INFO',
                f"Detached {len(plans)} face(s) into separate 0–1 paint textures. "
                "Use 'Enter Texture Paint' to paint the active selected face."
            )
            return {'FINISHED'}

        except Exception as exc:
            trace = traceback.format_exc()
            obj['qss_last_detach_error'] = f"{stage}: {exc}"
            obj['qss_last_detach_traceback'] = trace[-12000:]
            print(trace)
            # Roll back any material-slot/UV changes already committed.
            for plan in reversed(plans):
                try:
                    poly_index = plan['poly_index']
                    if poly_index < len(mesh.polygons):
                        mesh.polygons[poly_index].material_index = plan['source_index']
                    if 'loop_indices' in plan and 'old_uvs' in plan:
                        for loop_index, uv_value in zip(plan['loop_indices'], plan['old_uvs']):
                            if loop_index < len(uv_layer.data):
                                uv_layer.data[loop_index].uv = uv_value
                except Exception:
                    pass
            for material in created_materials:
                try:
                    if material.users == 0:
                        bpy.data.materials.remove(material)
                except Exception:
                    pass
            for image in created_images:
                try:
                    if image.users == 0:
                        bpy.data.images.remove(image)
                except Exception:
                    pass
            try:
                if was_edit_mode and context.mode != 'EDIT_MESH':
                    bpy.ops.object.mode_set(mode='EDIT')
            except Exception:
                pass
            _report(self, 'ERROR', f"Could not detach face ({stage}): {exc}. If the mesh was hidden/revealed in Edit Mode, switch to Object Mode and re-import if the face/UV attribute counts are stale.")
            return {'CANCELLED'}


def _selected_edit_face_material(obj):
    """Return the active selected edit-face material, or the first selected one."""
    import bmesh
    bm = bmesh.from_edit_mesh(obj.data)
    active = bm.faces.active
    if active is not None and active.select:
        return int(active.material_index)
    for face in bm.faces:
        if face.select:
            return int(face.material_index)
    return None


class QSS_OT_activate_paint(Operator):
    bl_idname = "qss.activate_texture_paint"
    bl_label = "Enter Texture Paint"
    bl_description = "Paint the active selected face material; switches from Edit Mode automatically"

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not (obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'):
            return False
        if context.mode == 'EDIT_MESH':
            try:
                index = _selected_edit_face_material(obj)
                return index is not None and 0 <= index < len(obj.data.materials) and _find_image(obj.data.materials[index]) is not None
            except Exception:
                return False
        return bool(
            context.mode == 'OBJECT' and obj.active_material
            and _find_image(obj.active_material)
        )

    def execute(self, context):
        obj = context.object
        if context.mode == 'EDIT_MESH':
            selected_material_index = _selected_edit_face_material(obj)
            if selected_material_index is None:
                _report(self, 'WARNING', "Select a face in Edit Mode first.")
                return {'CANCELLED'}
            bpy.ops.object.mode_set(mode='OBJECT')
            obj.active_material_index = selected_material_index

        mat = obj.active_material
        image = _find_image(mat, 'base_texture')
        if image is None:
            _report(self, 'ERROR', "The active material has no base texture image.")
            return {'CANCELLED'}
        _set_material_image(mat, image)
        try:
            uv_layers = obj.data.uv_layers
            texture_uv = uv_layers.get("Quake_Texture_UV")
            if texture_uv is None and len(uv_layers) > 0:
                texture_uv = uv_layers[0]
            if texture_uv is not None:
                uv_layers.active = texture_uv
        except (IndexError, RuntimeError, ReferenceError) as exc:
            _report(self, 'ERROR', f"Texture UV layers are unavailable ({exc}). Return to Object Mode and re-import the BSP.")
            return {'CANCELLED'}
        try:
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
        except RuntimeError as exc:
            _report(self, 'ERROR', f"Could not enter Texture Paint mode: {exc}")
            return {'CANCELLED'}
        _report(self, 'INFO', f"Painting image: {image.name}")
        return {'FINISHED'}


class QSS_OT_activate_lightmap_paint(Operator):
    bl_idname = "qss.activate_lightmap_paint"
    bl_label = "Enter Lightmap Paint"
    bl_description = "Make the shared lightmap atlas active and enter Texture Paint mode"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(
            obj and obj.type == 'MESH'
            and obj.get('qss_object_role') == 'quake_bsp29'
            and obj.get('qss_lightmap_image_name')
            and context.mode == 'OBJECT'
        )

    def execute(self, context):
        obj = context.object
        image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        if image is None:
            _report(self, 'ERROR', "The lightmap atlas image is missing.")
            return {'CANCELLED'}
        try:
            _rebuild_lightmap_preview(obj)
        except Exception as exc:
            _report(self, 'ERROR', f"Could not activate the editable working atlas: {exc}")
            return {'CANCELLED'}
        mat = obj.active_material
        node = _find_image_node(mat, 'lightmap') if mat else None
        if node is None:
            _report(self, 'ERROR', "The active material has no lightmap image node.")
            return {'CANCELLED'}
        for n in mat.node_tree.nodes:
            n.select = False
        node.select = True
        mat.node_tree.nodes.active = node
        uv_layer = obj.data.uv_layers.get('Quake_Lightmap_UV')
        if uv_layer:
            obj.data.uv_layers.active = uv_layer
        try:
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
        except RuntimeError as exc:
            _report(self, 'ERROR', f"Could not enter Lightmap Paint mode: {exc}")
            return {'CANCELLED'}
        _report(self, 'INFO', f"Painting RGB lightmap atlas: {image.name}")
        return {'FINISHED'}


def _copy_image_pixels(source, destination):
    if tuple(source.size) != tuple(destination.size):
        raise bsp.BSPError('Lightmap backup dimensions do not match the current atlas.')
    count = int(source.size[0]) * int(source.size[1]) * 4
    pixels = array.array('f', [0.0]) * count
    source.update()
    source.pixels.foreach_get(pixels)
    destination.pixels.foreach_set(pixels)
    destination.update()
    try:
        destination.pack()
    except RuntimeError:
        pass


def _make_image_snapshot(image, suffix):
    snapshot = image.copy()
    snapshot.name = f"{image.name}_{suffix}"
    snapshot.use_fake_user = True
    try:
        snapshot.pack()
    except RuntimeError:
        pass
    return snapshot



class QSS_OT_preview_imported_lights(Operator):
    bl_idname = 'qss.preview_imported_lights'
    bl_label = 'Preview Imported Lights (Live)'
    bl_description = 'Show diffuse Quake textures under coloured imported lights in Eevee Rendered mode'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_light_entity_count', 0) > 0)

    def execute(self, context):
        try:
            _set_lighting_preview(context, context.object, 'realtime')
            self.report({'INFO'}, 'Live imported-light preview enabled in Eevee Rendered mode. Zero energy is black; energy scale changes imported lamps.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not enable live lighting preview: {exc}')
            return {'CANCELLED'}


class QSS_OT_preview_source_lightmaps(Operator):
    bl_idname = 'qss.preview_source_lightmaps'
    bl_label = 'Show Original BSP Lightmaps'
    bl_description = 'Preview the immutable lightmap atlas extracted from the compiled BSP'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_original_lightmap_backup'))

    def execute(self, context):
        try:
            _set_lighting_preview(context, context.object, 'source')
            self.report({'INFO'}, 'Original imported BSP lightmaps are displayed; the editable/baked atlas remains untouched.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not show original BSP lightmaps: {exc}')
            return {'CANCELLED'}


class QSS_OT_preview_bsp_lightmaps(Operator):
    bl_idname = 'qss.preview_bsp_lightmaps'
    bl_label = 'Show Baked / Working Lightmap'
    bl_description = 'Show the editable current atlas, including the last successful Blender bake'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_lightmap_image_name'))

    def execute(self, context):
        try:
            _set_lighting_preview(context, context.object, 'baked')
            self.report({'INFO'}, 'Unlit BSP/baked lightmap preview enabled.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not restore lightmap preview: {exc}')
            return {'CANCELLED'}


def _lightmap_sample_luminances(obj, image):
    """Read only real luxel centers, excluding atlas gutters and empty space."""
    mesh = obj.data
    attrs = _qss_validate_face_domain_attributes(
        mesh, ('qss_lm_has_data', 'qss_lm_atlas_x', 'qss_lm_atlas_y',
               'qss_lm_sample_w', 'qss_lm_sample_h'),
        'sample lightmap luxels'
    )
    size = int(image.size[0])
    scale = max(1, int(obj.get('qss_lightmap_scale', 1)))
    gutter = max(0, int(obj.get('qss_lightmap_gutter', 0)))
    pixels = array.array('f', [0.0]) * (size * size * 4)
    image.update()
    image.pixels.foreach_get(pixels)
    values = []
    for poly_index, _poly in enumerate(mesh.polygons):
        if not _qss_safe_collection_item(attrs['qss_lm_has_data'].data, poly_index, 'qss_lm_has_data').value:
            continue
        x0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_x'].data, poly_index, 'qss_lm_atlas_x').value) + gutter
        y0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_y'].data, poly_index, 'qss_lm_atlas_y').value) + gutter
        width = int(_qss_safe_collection_item(attrs['qss_lm_sample_w'].data, poly_index, 'qss_lm_sample_w').value)
        height = int(_qss_safe_collection_item(attrs['qss_lm_sample_h'].data, poly_index, 'qss_lm_sample_h').value)
        for sy in range(height):
            top_y = y0 + sy * scale + (scale - 1) // 2
            blender_y = size - 1 - top_y
            for sx in range(width):
                px = x0 + sx * scale + (scale - 1) // 2
                if not (0 <= px < size and 0 <= blender_y < size):
                    continue
                idx = (blender_y * size + px) * 4
                r, g, b = pixels[idx], pixels[idx + 1], pixels[idx + 2]
                values.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return values


def _image_pixels_mean(image):
    pixels = array.array('f', [0.0]) * (int(image.size[0]) * int(image.size[1]) * 4)
    image.update()
    image.pixels.foreach_get(pixels)
    count = max(1, len(pixels) // 4)
    return sum(0.2126 * pixels[i] + 0.7152 * pixels[i + 1] + 0.0722 * pixels[i + 2]
               for i in range(0, len(pixels), 4)) / count


def _image_rgb_statistics(image):
    """Return whole-image diagnostics, including whether Cycles wrote any pixels."""
    pixel_count = int(image.size[0]) * int(image.size[1])
    pixels = array.array('f', [0.0]) * (pixel_count * 4)
    image.update()
    image.pixels.foreach_get(pixels)
    if pixel_count <= 0:
        return {'pixels': 0, 'mean_luma': 0.0, 'max_channel': 0.0,
                'nonzero_pixels': 0, 'nonzero_rgb_values': 0}
    luma_sum = 0.0
    max_channel = 0.0
    nonzero_pixels = 0
    nonzero_rgb_values = 0
    for i in range(0, len(pixels), 4):
        r, g, b = float(pixels[i]), float(pixels[i + 1]), float(pixels[i + 2])
        luma_sum += 0.2126 * r + 0.7152 * g + 0.0722 * b
        pixel_max = max(r, g, b)
        max_channel = max(max_channel, pixel_max)
        if pixel_max > 1e-8:
            nonzero_pixels += 1
        nonzero_rgb_values += int(r > 1e-8) + int(g > 1e-8) + int(b > 1e-8)
    return {
        'pixels': pixel_count,
        'mean_luma': luma_sum / pixel_count,
        'max_channel': max_channel,
        'nonzero_pixels': nonzero_pixels,
        'nonzero_rgb_values': nonzero_rgb_values,
    }



def _qss_vector3(values):
    from mathutils import Vector
    return Vector((float(values[0]), float(values[1]), float(values[2])))


def _qss_quake_to_world(obj, point_quake, unit_scale, flip_z):
    from mathutils import Vector
    x, y, z = (float(v) for v in point_quake)
    if flip_z:
        z = -z
    local = Vector((x * unit_scale, y * unit_scale, z * unit_scale))
    return obj.matrix_world @ local


def _qss_collect_direct_lights(context, obj, unit_scale, flip_z):
    """Collect editable imported point/spot lights in original BSP coordinates."""
    from mathutils import Vector
    result = []
    unsupported = []
    inv_scale = 1.0 / max(1e-9, float(unit_scale))
    inverse_map = obj.matrix_world.inverted_safe()
    inverse_map_3x3 = inverse_map.to_3x3()
    for light_obj in context.scene.objects:
        role = light_obj.get('qss_light_role') if light_obj.type == 'LIGHT' else None
        if role not in {'quake_entity_light', 'quake_world_sunlight'}:
            continue
        if light_obj.data.type == 'SUN':
            unsupported.append(light_obj.name + ' (world sun; not included in point/spot pass)')
            continue
        if light_obj.data.type not in {'POINT', 'SPOT'}:
            unsupported.append(light_obj.name + ' (unsupported lamp type)')
            continue
        position_world = light_obj.matrix_world.translation.copy()
        position_local = inverse_map @ position_world
        if flip_z:
            position_local.z = -position_local.z
        origin = (position_local.x * inv_scale,
                  position_local.y * inv_scale,
                  position_local.z * inv_scale)
        direction = (0.0, 0.0, -1.0)
        if light_obj.data.type == 'SPOT':
            direction_world = (light_obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
            direction_local = (inverse_map_3x3 @ direction_world).normalized()
            if flip_z:
                direction_local.z = -direction_local.z
            direction = tuple(float(v) for v in direction_local)
        raw_value = float(light_obj.get('qss_quake_raw_light_value',
                                        light_obj.get('qss_quake_light_value', 300.0)))
        result.append({
            'name': light_obj.name,
            'origin': origin,
            'world_origin': position_world,
            'value': raw_value,
            'color': tuple(float(v) for v in light_obj.data.color[:3]),
            'style': int(light_obj.get('qss_quake_light_style', 0)),
            'delay': max(0, min(5, int(light_obj.get('qss_quake_light_delay', 0)))),
            'wait': max(1e-6, float(light_obj.get('qss_quake_wait', 1.0))),
            'falloff': max(0.0, float(light_obj.get('qss_quake_falloff', 0.0))),
            'anglescale': float(light_obj.get('qss_quake_anglescale', obj.get('qss_world_anglescale', 0.5))),
            'direction': direction,
            'is_spot': light_obj.data.type == 'SPOT',
            'outer_angle': float(light_obj.get('qss_quake_spot_angle', 40.0)),
            'inner_angle': float(light_obj.get('qss_quake_spot_softangle', 0.0)),
            'nostaticlight': bool(light_obj.get('qss_quake_no_staticlight', False)),
            'bleed': bool(light_obj.get('qss_quake_bleed', False)),
        })
    return result, unsupported


def _qss_source_bvh(obj, parsed, unit_scale, flip_z, context):
    """Build a map-only world-space BVH; unrelated Blender objects cannot occlude Quake lights."""
    from mathutils.bvhtree import BVHTree
    vertices = parsed.vertices()
    edges = parsed.edges()
    surfedges = parsed.surfedges()
    world_vertices = [_qss_quake_to_world(obj, v, unit_scale, flip_z) for v in vertices]
    polygons = []
    for face in parsed.faces():
        try:
            ids = parsed.face_vertex_indices(face, edges, surfedges)
        except Exception:
            continue
        if len(ids) >= 3 and all(0 <= idx < len(world_vertices) for idx in ids):
            polygons.append(ids)
    if not polygons:
        return None
    return BVHTree.FromPolygons(world_vertices, polygons, all_triangles=False, epsilon=0.0)


def _qss_read_source_face_sample(mesh, poly_index, face_id, parsed):
    """Return original BSP face, plane, texinfo and lightmap atlas metadata safely."""
    required = ('qss_bsp_face_id', 'qss_lm_has_data', 'qss_lm_atlas_x', 'qss_lm_atlas_y',
                'qss_lm_sample_w', 'qss_lm_sample_h')
    attrs = {name: mesh.attributes.get(name) for name in required}
    for name, attr in attrs.items():
        if attr is None:
            raise bsp.BSPError(f'Mesh attribute {name} is missing; re-import the BSP.')
        if len(attr.data) != len(mesh.polygons):
            raise bsp.BSPError(
                f'Mesh attribute {name} has {len(attr.data)} entries for {len(mesh.polygons)} faces. '
                'The mesh topology or attributes changed; re-import the BSP before baking.'
            )
    if poly_index < 0 or poly_index >= len(mesh.polygons):
        raise bsp.BSPError(f'Polygon index {poly_index} is outside the mesh face collection.')
    has_data = bool(_qss_safe_collection_item(attrs['qss_lm_has_data'].data, poly_index, 'qss_lm_has_data').value)
    if not has_data:
        return None
    actual_face_id = int(_qss_safe_collection_item(attrs['qss_bsp_face_id'].data, poly_index, 'qss_bsp_face_id').value)
    if actual_face_id != int(face_id):
        face_id = actual_face_id
    faces = parsed.faces()
    if face_id < 0 or face_id >= len(faces):
        raise bsp.BSPError(f'Face ID {face_id} is outside the source BSP face lump.')
    face = faces[face_id]
    texinfos = parsed.texinfos()
    texinfo_id = int(face[4])
    if texinfo_id < 0 or texinfo_id >= len(texinfos):
        raise bsp.BSPError(f'BSP face {face_id} references invalid texinfo {texinfo_id}.')
    planes = parsed.planes()
    plane_id = int(face[0])
    if plane_id < 0 or plane_id >= len(planes):
        raise bsp.BSPError(f'BSP face {face_id} references invalid plane {plane_id}.')
    plane = planes[plane_id]
    sign = -1.0 if int(face[1]) else 1.0
    normal = tuple(float(plane[i]) * sign for i in range(3))
    distance = float(plane[3]) * sign
    edges = parsed.edges()
    surfedges = parsed.surfedges()
    vertices = parsed.vertices()
    vertex_ids = parsed.face_vertex_indices(face, edges, surfedges)
    positions = [vertices[i] for i in vertex_ids]
    texinfo = texinfos[texinfo_id]
    s_min, t_min, extent_s, extent_t, _svec, _tvec = _calc_face_lightmap_extents(positions, texinfo)
    sample_w = int(_qss_safe_collection_item(attrs['qss_lm_sample_w'].data, poly_index, 'qss_lm_sample_w').value)
    sample_h = int(_qss_safe_collection_item(attrs['qss_lm_sample_h'].data, poly_index, 'qss_lm_sample_h').value)
    expected_w = (extent_s >> 4) + 1
    expected_h = (extent_t >> 4) + 1
    if sample_w != expected_w or sample_h != expected_h:
        raise bsp.BSPError(
            f'Face {face_id} sample size mismatch: atlas={sample_w}x{sample_h}, BSP extents={expected_w}x{expected_h}. '
            'Re-import the BSP to regenerate UV metadata.'
        )
    return {
        'face_id': face_id,
        'face': face,
        'texinfo': texinfo,
        'plane_normal': normal,
        'plane_distance': distance,
        's_min': s_min,
        't_min': t_min,
        'width': sample_w,
        'height': sample_h,
        'styles': [int(v) for v in face[5:9] if int(v) != 255],
        'atlas_x': int(_qss_safe_collection_item(attrs['qss_lm_atlas_x'].data, poly_index, 'qss_lm_atlas_x').value),
        'atlas_y': int(_qss_safe_collection_item(attrs['qss_lm_atlas_y'].data, poly_index, 'qss_lm_atlas_y').value),
    }


def _qss_run_ericw_direct_bake(context, obj):
    """Evaluate ericw direct light at every BSP luxel and replace the working atlas.

    This deliberately does not use Cycles: Cycles' point lights use physically
    based inverse-square attenuation and cannot select Quake delay 0..5. This
    CPU pass evaluates the Quake attenuation formulas directly, with a map-only
    BVH for hard line-of-sight shadows.
    """
    from mathutils import Vector
    source_path = bpy.path.abspath(obj.get('qss_source_path', ''))
    if not source_path or not os.path.isfile(source_path):
        raise bsp.BSPError('Source BSP is unavailable. Re-import the BSP before a Quake direct bake.')
    parsed = bsp.BSP29.from_file(source_path)
    mesh = obj.data
    if len(mesh.polygons) == 0:
        raise bsp.BSPError('The selected QSS mesh has no polygons.')
    image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
    if image is None or image.size[0] != image.size[1]:
        raise bsp.BSPError('The square lightmap atlas is missing. Re-import the BSP.')
    size = int(image.size[0])
    scale = max(1, int(obj.get('qss_lightmap_scale', 1)))
    gutter = max(0, int(obj.get('qss_lightmap_gutter', 0)))
    unit_scale = float(obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE))
    flip_z = bool(obj.get('qss_flip_z', False))
    energy_scale = max(0.0, float(context.scene.qss_light_energy_scale))
    if energy_scale <= 0.0:
        raise bsp.BSPError('Quake light energy scale is 0; the Quake direct bake will be black.')
    lights, unsupported = _qss_collect_direct_lights(context, obj, unit_scale, flip_z)
    if not lights:
        raise bsp.BSPError('No imported point or spot Quake lights were found. World sun entities are not yet included in this direct pass.')
    world_dist = float(obj.get('qss_world_dist', 1.0))
    world_range = float(obj.get('qss_world_range', 0.5))
    world_gamma = float(obj.get('qss_world_gamma', 1.0))
    maxlight = float(obj.get('qss_world_maxlight', 255.0))
    gate = max(0.0, float(context.scene.qss_quake_bake_gate))
    match_source = bool(context.scene.qss_bake_match_source)
    output_scale = max(0.0, float(context.scene.qss_bake_output_scale))
    bvh = _qss_source_bvh(obj, parsed, unit_scale, flip_z, context) if context.scene.qss_quake_bake_shadows else None
    pixels = array.array('f', [0.0]) * (size * size * 4)
    image.update()
    image.pixels.foreach_get(pixels)
    original_image = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
    original_pixels = None
    if original_image is not None and tuple(original_image.size) == tuple(image.size):
        original_pixels = array.array('f', [0.0]) * (size * size * 4)
        original_image.update()
        original_image.pixels.foreach_get(original_pixels)

    # Validate all face-domain collections once before indexing. This catches
    # BMesh/mesh-domain desynchronization after hide/reveal or edit-mode changes.
    face_id_attr = mesh.attributes.get('qss_bsp_face_id')
    if face_id_attr is None or len(face_id_attr.data) != len(mesh.polygons):
        count = len(face_id_attr.data) if face_id_attr is not None else 'missing'
        raise bsp.BSPError(f'qss_bsp_face_id has {count} entries for {len(mesh.polygons)} polygons; exit Edit Mode and re-import if this persists.')
    # Keep exact per-atlas sample positions and source pixels for brightness matching.
    work = []
    total_luxels = 0
    for poly_index, poly in enumerate(mesh.polygons):
        face_id = int(_qss_safe_collection_item(face_id_attr.data, poly_index, 'qss_bsp_face_id').value)
        face_info = _qss_read_source_face_sample(mesh, poly_index, face_id, parsed)
        if face_info is None:
            continue
        x0 = face_info['atlas_x'] + gutter
        y0 = face_info['atlas_y'] + gutter
        for sy in range(face_info['height']):
            for sx in range(face_info['width']):
                s_value = face_info['s_min'] + sx * 16.0 - float(face_info['texinfo'][3])
                t_value = face_info['t_min'] + sy * 16.0 - float(face_info['texinfo'][7])
                qpoint = lighting_utils.solve_texinfo_plane(
                    face_info['texinfo'][0:3], face_info['texinfo'][4:7],
                    face_info['plane_normal'], s_value, t_value,
                    face_info['plane_distance']
                )
                if qpoint is None:
                    raise bsp.BSPError(f'Face {face_id} has singular texture projection axes; cannot locate its luxels.')
                local_normal = Vector(face_info['plane_normal'])
                if flip_z:
                    local_normal.z = -local_normal.z
                world_normal = (obj.matrix_world.to_3x3().inverted_safe().transposed() @ local_normal).normalized()
                world_point = _qss_quake_to_world(obj, qpoint, unit_scale, flip_z)
                top_y = y0 + sy * scale + (scale - 1) // 2
                pixel_y = size - 1 - top_y
                pixel_x = x0 + sx * scale + (scale - 1) // 2
                pixel_index = (pixel_y * size + pixel_x) * 4
                source_luma = 0.0
                if original_pixels is not None:
                    source_luma = (0.2126 * original_pixels[pixel_index] +
                                   0.7152 * original_pixels[pixel_index + 1] +
                                   0.0722 * original_pixels[pixel_index + 2])
                work.append((face_id, face_info['styles'], qpoint, face_info['plane_normal'],
                             world_point, world_normal, pixel_index, source_luma))
        total_luxels += face_info['width'] * face_info['height']
    if not work:
        raise bsp.BSPError('No valid lightmap luxels were found. Check BSP face styles and UV metadata.')
    if total_luxels > 2000000:
        raise bsp.BSPError(f'This map has {total_luxels:,} luxels. Current QSS direct bake safety limit is 2,000,000.')

    epsilon = max(0.1, 0.5) * unit_scale
    ray_stats = {'tests': 0, 'blocked': 0}

    def visible(light, sample, normal):
        if bvh is None:
            return True
        light_world = light['world_origin']
        to_light = light_world - sample
        distance = to_light.length
        if distance <= epsilon:
            return True
        direction = to_light.normalized()
        ray_origin = sample + normal * epsilon
        ray_vector = light_world - ray_origin
        ray_distance = max(0.0, ray_vector.length - epsilon)
        if ray_distance <= 0.0:
            return True
        ray_stats['tests'] += 1
        hit = bvh.ray_cast(ray_origin, ray_vector.normalized(), ray_distance)
        if hit and hit[0] is not None:
            ray_stats['blocked'] += 1
            return False
        return True

    for light in lights:
        light['world_origin'] = light['world_origin']

    result_samples = []
    total = len(work)
    context.window_manager.progress_begin(0, total)
    try:
        for idx, (face_id, styles, qpoint, quake_normal, world_point, world_normal, pixel_index, source_luma) in enumerate(work):
            rgb = lighting_utils.evaluate_quake_luxel(
                qpoint, quake_normal, lights, styles,
                world_dist=world_dist, world_range=world_range,
                world_gamma=world_gamma, energy_scale=energy_scale,
                visible=lambda light, sample, normal: visible(light, world_point, world_normal),
                maxlight=maxlight, contribution_gate=gate
            )
            # The solver result is already 0..1 after ericw _range/_gamma.
            rgb = tuple(max(0.0, v * output_scale) for v in rgb)
            result_samples.append((pixel_index, rgb, source_luma))
            if idx % 64 == 0 or idx + 1 == total:
                context.window_manager.progress_update(idx + 1)
    finally:
        context.window_manager.progress_end()

    lit_values = [0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
                  for _pixel, rgb, _source in result_samples]
    source_values = [source for _pixel, _rgb, source in result_samples]
    raw_mean = sum(lit_values) / max(1, len(lit_values))
    source_mean = sum(source_values) / max(1, len(source_values)) if source_values else 0.0
    normalization = 1.0
    if match_source and source_mean > 1e-8 and raw_mean > 1e-8:
        normalization = min(16.0, max(0.0625, source_mean / raw_mean))
    for pixel_index, rgb, _source in result_samples:
        final = tuple(max(0.0, min(16.0, c * normalization)) for c in rgb)
        for dy in range(scale):
            py = pixel_index // (size * 4) - dy  # atlas rows are bottom-up
            for dx in range(scale):
                px = pixel_index % (size * 4) // 4 + dx
                index = (py * size + px) * 4
                if 0 <= index and index + 3 < len(pixels):
                    pixels[index:index + 3] = array.array('f', final)
                    pixels[index + 3] = 1.0
    snapshot = _make_image_snapshot(image, 'QSS_PreviousQuakeBake')
    old_snapshot_name = obj.get('qss_last_bake_backup', '')
    old_snapshot = bpy.data.images.get(old_snapshot_name) if old_snapshot_name else None
    try:
        image.pixels.foreach_set(pixels)
        image.update()
        image.pack()
    except Exception:
        _copy_image_pixels(snapshot, image)
        if snapshot.users == 0:
            bpy.data.images.remove(snapshot)
        raise
    if old_snapshot is not None and old_snapshot != snapshot and old_snapshot.users == 0:
        bpy.data.images.remove(old_snapshot)
    obj['qss_last_bake_backup'] = snapshot.name
    obj['qss_lightmap_source'] = 'quake_direct_cpu_bake'
    obj['qss_lightmap_gradient_baked'] = True
    obj['qss_last_quake_bake_luxels'] = int(total_luxels)
    obj['qss_last_quake_bake_lit_luxels'] = sum(1 for value in lit_values if value > 1e-8)
    obj['qss_last_quake_bake_ray_tests'] = int(ray_stats['tests'])
    obj['qss_last_quake_bake_occluded'] = int(ray_stats['blocked'])
    obj['qss_last_quake_bake_modes'] = ', '.join(f'{delay}: {count}' for delay, count in sorted(
        {d: sum(1 for light in lights if light['delay'] == d) for d in set(l['delay'] for l in lights)}.items()))
    obj['qss_last_quake_bake_raw_mean'] = float(raw_mean)
    obj['qss_last_quake_bake_source_mean'] = float(source_mean)
    obj['qss_last_quake_bake_normalization'] = float(normalization)
    obj['qss_last_quake_bake_unsupported'] = '; '.join(unsupported)
    obj['qss_last_quake_bake_error'] = ''
    obj['qss_last_quake_bake_traceback'] = ''
    return {
        'luxels': total_luxels,
        'lit': obj['qss_last_quake_bake_lit_luxels'],
        'rays': ray_stats['tests'],
        'blocked': ray_stats['blocked'],
        'raw_mean': raw_mean,
        'source_mean': source_mean,
        'normalization': normalization,
        'unsupported': unsupported,
    }


class QSS_OT_quake_direct_bake(Operator):
    bl_idname = 'qss.quake_direct_bake'
    bl_label = 'Bake Quake Direct Lighting'
    bl_description = 'Evaluate ericw-tools direct light attenuation at every BSP luxel and write a static RGB atlas'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and context.mode == 'OBJECT' and obj.get('qss_lightmap_image_name'))

    def execute(self, context):
        obj = context.object
        try:
            stats = _qss_run_ericw_direct_bake(context, obj)
            try:
                _set_lighting_preview(context, obj, 'baked')
            except Exception as preview_error:
                self.report({'WARNING'}, f'Bake completed but preview switch failed: {preview_error}')
            unsupported_note = f"; unsupported: {', '.join(stats['unsupported'])}" if stats['unsupported'] else ''
            self.report({'INFO'},
                        f"Quake direct bake: {stats['lit']}/{stats['luxels']} luxels lit; "
                        f"{stats['rays']} visibility rays, {stats['blocked']} blocked; "
                        f"source match ×{stats['normalization']:.3g}{unsupported_note}")
            return {'FINISHED'}
        except Exception as exc:
            trace = traceback.format_exc()
            obj['qss_last_quake_bake_error'] = str(exc)
            obj['qss_last_quake_bake_traceback'] = trace[-16000:]
            print(trace)
            self.report({'ERROR'}, f'Quake direct bake failed: {exc}')
            return {'CANCELLED'}


class QSS_OT_bake_scene_lights(Operator):
    bl_idname = "qss.bake_scene_lights"
    bl_label = "Bake Imported Lights to Lightmap"
    bl_description = "Bake imported Quake lights into a fresh shared RGB atlas, with indirect bounce support"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_light_entity_count', 0) > 0 and obj.get('qss_lightmap_image_name'))

    def execute(self, context):
        obj = context.object
        scene = context.scene
        image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        if image is None:
            self.report({'ERROR'}, "The QSS lightmap atlas is missing; re-import the BSP.")
            return {'CANCELLED'}
        if not hasattr(scene, 'cycles') or not hasattr(scene.render, 'bake'):
            self.report({'ERROR'}, "This Blender build does not expose Cycles baking.")
            return {'CANCELLED'}
        mesh = obj.data
        light_uv = mesh.uv_layers.get('Quake_Lightmap_UV')
        if light_uv is None:
            self.report({'ERROR'}, "The lightmap UV layer is missing; re-import the BSP.")
            return {'CANCELLED'}
        imported_lights = [o for o in scene.objects if o.type == 'LIGHT' and
                           o.get('qss_light_role') in {'quake_entity_light', 'quake_world_sunlight'}]
        if not imported_lights:
            self.report({'ERROR'}, "No imported Quake lights are present in this scene.")
            return {'CANCELLED'}
        current_energy_scale = max(0.0, float(scene.qss_light_energy_scale))
        if current_energy_scale <= 0.0:
            self.report({'ERROR'}, "Live light scale is 0, so a light bake must be black. Set Live light scale to 1 or higher, click Apply Light Energy Scale, verify Live Lights, then bake.")
            return {'CANCELLED'}

        # Use a new float atlas. The source atlas is never the bake target, so it
        # remains recoverable if Cycles fails or a material bake is incomplete.
        bake_target = bpy.data.images.new(
            name=f"QSS_BakeTarget_{obj.name}", width=int(image.size[0]),
            height=int(image.size[1]), alpha=True, float_buffer=True
        )
        bake_target.colorspace_settings.name = 'Non-Color'
        blank = array.array('f', [0.0, 0.0, 0.0, 1.0]) * (int(image.size[0]) * int(image.size[1]))
        bake_target.pixels.foreach_set(blank)
        bake_target.update()

        previous_snapshot = _make_image_snapshot(image, 'QSS_PreviousBake')
        previous_snapshot_name = obj.get('qss_last_bake_backup', '')
        old_previous_snapshot = bpy.data.images.get(previous_snapshot_name) if previous_snapshot_name else None
        old_engine = scene.render.engine
        old_active = context.view_layer.objects.active
        old_selected = list(context.selected_objects)
        old_uv = mesh.uv_layers.active
        old_world = scene.world
        old_cycles = {
            'samples': int(scene.cycles.samples),
            'diffuse_bounces': int(scene.cycles.diffuse_bounces),
            'max_bounces': int(scene.cycles.max_bounces),
        }
        old_bake_settings = {}
        old_light_render_states = []
        material_states = []
        bake_succeeded = False
        old_preview_mode = obj.get('qss_preview_mode', 'lightmap')
        old_object_calibration = float(obj.get('qss_light_energy_calibration', 1.0))
        old_light_calibrations = {
            light_obj.name: float(light_obj.get('qss_energy_calibration', old_object_calibration))
            for light_obj in imported_lights
        }
        updated_lights = _apply_quake_light_energy_scale(scene)
        max_energy = max((float(o.data.energy) for o in imported_lights), default=0.0)
        try:
            _set_black_preview_world(scene, obj)
            scene.render.engine = 'CYCLES'
            # Blender allows baking to either image textures or the active mesh
            # colour attribute. QSS always bakes into the selected atlas image.
            # If the user's previous setting was VERTEX_COLORS, Cycles can finish
            # without writing a single pixel to our image target.
            if hasattr(scene.render.bake, 'target'):
                scene.render.bake.target = 'IMAGE_TEXTURES'
            obj['qss_last_bake_attempt_engine'] = str(scene.render.engine)
            obj['qss_last_bake_attempt_target'] = str(getattr(scene.render.bake, 'target', 'unavailable'))
            obj['qss_last_bake_attempt_type'] = 'DIFFUSE'
            obj['qss_last_bake_attempt_uv'] = light_uv.name
            for light_obj in scene.objects:
                if light_obj.type != 'LIGHT':
                    continue
                old_light_render_states.append((light_obj, bool(light_obj.hide_render)))
                is_quake = light_obj.get('qss_light_role') in {
                    'quake_entity_light', 'quake_world_sunlight'
                }
                light_obj.hide_render = not is_quake

            for name in ('target', 'use_pass_color', 'use_pass_diffuse', 'use_pass_emit', 'use_pass_glossy', 'use_pass_transmission', 'use_pass_direct', 'use_pass_indirect', 'use_clear', 'margin'):
                if hasattr(scene.render.bake, name):
                    old_bake_settings[name] = getattr(scene.render.bake, name)
            scene.render.bake.use_pass_color = False  # bake illumination, not albedo
            if hasattr(scene.render.bake, 'use_pass_diffuse'):
                scene.render.bake.use_pass_diffuse = True
            if hasattr(scene.render.bake, 'use_pass_emit'):
                scene.render.bake.use_pass_emit = False
            if hasattr(scene.render.bake, 'use_pass_glossy'):
                scene.render.bake.use_pass_glossy = False
            if hasattr(scene.render.bake, 'use_pass_transmission'):
                scene.render.bake.use_pass_transmission = False
            scene.render.bake.use_pass_direct = True
            scene.render.bake.use_pass_indirect = True
            if hasattr(scene.render.bake, 'use_clear'):
                # One image is shared by every material. Clearing per material can
                # erase pixels baked for earlier material slots; target starts blank.
                scene.render.bake.use_clear = False
            if hasattr(scene.render.bake, 'margin'):
                scene.render.bake.margin = 0
            scene.cycles.samples = max(96, old_cycles['samples'])
            bake_bounces = max(0, int(getattr(scene, 'qss_bake_bounces', 2)))
            scene.cycles.diffuse_bounces = bake_bounces
            scene.cycles.max_bounces = max(old_cycles['max_bounces'], bake_bounces + 1)

            for selected in list(context.selected_objects):
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            mesh.uv_layers.active = light_uv
            try:
                light_uv.active_render = True
            except Exception:
                pass

            for mat in mesh.materials:
                if mat is None:
                    continue
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                links = mat.node_tree.links
                output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
                if output is None:
                    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
                if output is None:
                    output = nodes.new('ShaderNodeOutputMaterial')
                old_surface = [(l.from_node, l.from_socket) for l in links if l.to_socket == output.inputs['Surface']]
                diffuse = nodes.new('ShaderNodeBsdfDiffuse')
                diffuse.name = 'QSS_TEMP_CyclesBake_Diffuse'
                diffuse.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
                diffuse.inputs['Roughness'].default_value = 1.0
                target_node = _find_image_node(mat, 'lightmap')
                if target_node is None:
                    target_node = nodes.new('ShaderNodeTexImage')
                    target_node['qss_role'] = 'lightmap'
                old_target_image = target_node.image
                target_node.image = bake_target
                target_node.interpolation = 'Closest'
                target_node.extension = 'EXTEND'
                for node in nodes:
                    node.select = False
                target_node.select = True
                nodes.active = target_node
                for link in list(links):
                    if link.to_socket == output.inputs['Surface']:
                        links.remove(link)
                links.new(diffuse.outputs[0], output.inputs['Surface'])
                material_states.append((mat, output, old_surface, diffuse, target_node, old_target_image))

            with context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj],
                selected_editable_objects=[obj]
            ):
                bake_result = bpy.ops.object.bake(type='DIFFUSE')
            obj['qss_last_bake_attempt_operator_result'] = ','.join(sorted(bake_result))
            if 'FINISHED' not in bake_result:
                stats = _image_rgb_statistics(bake_target)
                raise bsp.BSPError(
                    f'Blender cancelled the Cycles bake (operator result={sorted(bake_result)}; '
                    f'atlas nonzero pixels={stats["nonzero_pixels"]}/{stats["pixels"]}). '
                    'Check that the QSS mesh is selected, in Object Mode, and has an active lightmap image node in every used material.'
                )

            # Measure the raw Cycles irradiance at actual BSP luxel centres.
            # The atlas is float/Non-Color: unlike an 8-bit byte image it can
            # preserve low irradiance values and calibrated values above 1.0.
            bake_values = _lightmap_sample_luminances(obj, bake_target)
            raw_bake_mean = (sum(bake_values) / len(bake_values)) if bake_values else 0.0
            raw_image_stats = _image_rgb_statistics(bake_target)
            source_image = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
            source_values = _lightmap_sample_luminances(obj, source_image) if source_image else []
            source_mean = (sum(source_values) / len(source_values)) if source_values else 0.0
            old_calibration = max(1e-8, float(obj.get('qss_light_energy_calibration', 1.0)))
            energy_scale = max(0.0, float(scene.qss_light_energy_scale))
            max_energy_after_bake = max((float(o.data.energy) for o in imported_lights), default=0.0)
            new_calibration = old_calibration
            calibration_output_scale = 1.0
            obj['qss_last_bake_attempt_scale'] = energy_scale
            obj['qss_last_bake_attempt_max_lamp_energy'] = max_energy_after_bake
            obj['qss_last_bake_attempt_sample_count'] = len(bake_values)
            obj['qss_last_bake_attempt_raw_mean'] = float(raw_bake_mean)
            obj['qss_last_bake_attempt_image_stats'] = str(raw_image_stats)
            if energy_scale <= 0.0:
                raise bsp.BSPError(
                    'Live light scale is exactly 0. Set it to 1.0 (or higher), click Apply Light Energy Scale, '
                    'confirm the Live Lights preview is illuminated, then bake again.'
                )
            if bool(getattr(scene, 'qss_bake_match_source', True)) and source_mean > 1e-8:
                if raw_bake_mean <= 1e-8:
                    obj['qss_last_bake_attempt_lights'] = '; '.join(
                        f'{lamp.name}: {float(lamp.data.energy):.6g}W hide_render={bool(lamp.hide_render)} hide_viewport={bool(lamp.hide_viewport)}'
                        for lamp in imported_lights
                    )
                    raise bsp.BSPError(
                        'Cycles finished but sampled BSP lightmap luxels are all zero. '
                        f'Energy scale={energy_scale:g}; imported lamps={len(imported_lights)}; '
                        f'max lamp energy={max_energy_after_bake:.6g} W; '
                        f'sampled luxels={len(bake_values)}; whole atlas nonzero pixels='
                        f'{raw_image_stats["nonzero_pixels"]}/{raw_image_stats["pixels"]}; '
                        f'whole atlas max RGB={raw_image_stats["max_channel"]:.6g}. '
                        'Use Save Lighting Diagnostics and send the report; failed-bake statistics are recorded.'
                    )
                new_calibration = old_calibration * lighting_utils.calibration_factor(source_mean, raw_bake_mean, energy_scale)
                calibration_output_scale = new_calibration / old_calibration
                obj['qss_light_energy_calibration'] = new_calibration
                obj['qss_calibration_source_mean'] = source_mean
                obj['qss_calibration_bake_mean'] = raw_bake_mean
                obj['qss_calibration_factor'] = new_calibration
                for light_obj in imported_lights:
                    light_obj['qss_energy_calibration'] = new_calibration
                _apply_quake_light_energy_scale(scene)

            # Copy the completed float bake into the project's current atlas.
            # Source-match normalization is a global linear calibration, not a
            # claim that Blender's inverse-square lights reproduce every Quake luxel.
            baked = array.array('f', [0.0]) * (int(bake_target.size[0]) * int(bake_target.size[1]) * 4)
            bake_target.pixels.foreach_get(baked)
            # The live lamp calibration and atlas normalization are different
            # quantities. The calibration makes slider=1 reproduce the source
            # *mean* after accounting for the slider value used for this bake.
            # The baked image itself must be normalized by source_mean/raw_mean
            # (not by new_calibration/old_calibration, which would multiply the
            # slider value a second time whenever it is not exactly 1).
            atlas_match_scale = 1.0
            if bool(getattr(scene, 'qss_bake_match_source', True)) and source_mean > 1e-8 and raw_bake_mean > 1e-8:
                atlas_match_scale = lighting_utils.bake_atlas_match_scale(source_mean, raw_bake_mean)
            post_scale = float(getattr(scene, 'qss_bake_output_scale', 1.0)) * atlas_match_scale
            for px in range(0, len(baked), 4):
                baked[px] = max(0.0, baked[px] * post_scale)
                baked[px + 1] = max(0.0, baked[px + 1] * post_scale)
                baked[px + 2] = max(0.0, baked[px + 2] * post_scale)
                baked[px + 3] = 1.0
            image.pixels.foreach_set(baked)
            image.update()
            try:
                image.pack()
            except RuntimeError:
                pass
            bake_succeeded = True
            values = _lightmap_sample_luminances(obj, image)
            obj['qss_last_bake_luxel_mean'] = float(sum(values) / max(1, len(values)))
            obj['qss_last_bake_luxel_max'] = float(max(values, default=0.0))
            obj['qss_last_bake_energy_scale'] = float(scene.qss_light_energy_scale)
            obj['qss_last_bake_output_scale'] = float(post_scale)
            obj['qss_last_bake_raw_mean'] = float(raw_bake_mean)
            obj['qss_last_bake_source_mean'] = float(source_mean)
            obj['qss_last_bake_calibration'] = float(new_calibration)
            obj['qss_last_bake_bounces'] = bake_bounces
            obj['qss_lightmap_source'] = 'cycles_bake_from_quake_entities'
            obj['qss_lightmap_gradient_baked'] = True
            obj['qss_last_bake_backup'] = previous_snapshot.name
            obj['qss_bake_material_count'] = len(material_states)
            obj['qss_bake_light_count'] = updated_lights
            if old_previous_snapshot and old_previous_snapshot != previous_snapshot:
                try:
                    bpy.data.images.remove(old_previous_snapshot)
                except Exception:
                    pass
            self.report({'INFO'},
                        f"Bake complete: {updated_lights} lights, {len(material_states)} materials, "
                        f"{len(values)} luxels, mean {obj['qss_last_bake_luxel_mean']:.4g}, "
                        f"max {obj['qss_last_bake_luxel_max']:.4g}, "
                        f"raw mean {raw_bake_mean:.4g}, source mean {source_mean:.4g}, "
                        f"atlas scale {post_scale:.4g}, {bake_bounces} diffuse bounces. "
                        "Switches to Baked Lightmaps preview.")
        except Exception as exc:
            try:
                _copy_image_pixels(previous_snapshot, image)
            except Exception:
                pass
            # A failure after source-mean normalization must not leave the
            # scene's lamps calibrated against a bake which was discarded.
            obj['qss_light_energy_calibration'] = old_object_calibration
            for light_obj in imported_lights:
                light_obj['qss_energy_calibration'] = old_light_calibrations.get(
                    light_obj.name, old_object_calibration)
            _apply_quake_light_energy_scale(scene)
            self.report({'ERROR'}, f"Cycles bake failed; atlas and light calibration restored: {exc}")
            return {'CANCELLED'}
        finally:
            for mat, output, old_surface, diffuse, target_node, old_target_image in material_states:
                links = mat.node_tree.links
                for link in list(links):
                    if link.to_socket == output.inputs['Surface']:
                        links.remove(link)
                for from_node, from_socket in old_surface:
                    try:
                        links.new(from_socket, output.inputs['Surface'])
                    except Exception:
                        pass
                try:
                    mat.node_tree.nodes.remove(diffuse)
                except Exception:
                    pass
                target_node.image = old_target_image if old_target_image is not None else image
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and (node.image == image or node.image == bake_target):
                        node.select = (node.get('qss_role') == 'lightmap')
                        if node.select:
                            mat.node_tree.nodes.active = node
            for light_obj, was_hidden in old_light_render_states:
                try:
                    light_obj.hide_render = was_hidden
                except Exception:
                    pass
            try:
                scene.render.engine = old_engine
                scene.cycles.samples = old_cycles['samples']
                scene.cycles.diffuse_bounces = old_cycles['diffuse_bounces']
                scene.cycles.max_bounces = old_cycles['max_bounces']
            except Exception:
                pass
            for name, value in old_bake_settings.items():
                try:
                    setattr(scene.render.bake, name, value)
                except Exception:
                    pass
            try:
                if old_uv is not None:
                    mesh.uv_layers.active = old_uv
            except Exception:
                pass
            _restore_preview_world(scene, obj)
            _restore_non_quake_lights(scene)
            for selected in list(context.selected_objects):
                selected.select_set(False)
            for selected in old_selected:
                if selected and selected.name in bpy.data.objects:
                    selected.select_set(True)
            if old_active and old_active.name in bpy.data.objects:
                context.view_layer.objects.active = old_active
            try:
                if bake_target.name in bpy.data.images:
                    bpy.data.images.remove(bake_target)
            except Exception:
                pass
            if not bake_succeeded:
                try:
                    bpy.data.images.remove(previous_snapshot)
                except Exception:
                    pass
                # Restore the mode that was active before the failed bake.
                # This recreates the private black world and enables only QSS
                # lamps again if the user started in Live Lights.
                try:
                    _set_lighting_preview(context, obj, old_preview_mode)
                except Exception:
                    pass

        if bake_succeeded:
            try:
                _set_lighting_preview(context, obj, 'baked')
            except Exception as preview_exc:
                self.report({'WARNING'}, f'Bake completed but preview refresh failed: {preview_exc}')
        return {'FINISHED'}


class QSS_OT_undo_last_bake(Operator):
    bl_idname = 'qss.undo_last_bake'
    bl_label = 'Undo Last Bake'
    bl_description = 'Restore the lightmap atlas exactly as it was immediately before the last Cycles bake'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_last_bake_backup'))

    def execute(self, context):
        obj = context.object
        target = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        backup = bpy.data.images.get(obj.get('qss_last_bake_backup', ''))
        if target is None or backup is None:
            self.report({'ERROR'}, 'The pre-bake snapshot is missing.')
            return {'CANCELLED'}
        try:
            _copy_image_pixels(backup, target)
            bpy.data.images.remove(backup)
            obj['qss_last_bake_backup'] = ''
            obj['qss_lightmap_source'] = 'pre_bake_atlas'
            obj['qss_lightmap_gradient_baked'] = False
            self.report({'INFO'}, 'Restored the atlas to its pre-bake state.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not undo bake: {exc}')
            return {'CANCELLED'}


class QSS_OT_restore_original_lightmap(Operator):
    bl_idname = 'qss.restore_original_lightmap'
    bl_label = 'Restore Imported BSP Lightmaps'
    bl_description = 'Restore the original RGB lightmap atlas extracted at BSP import'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_original_lightmap_backup'))

    def execute(self, context):
        obj = context.object
        target = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        backup = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
        if target is None or backup is None:
            self.report({'ERROR'}, 'The original imported lightmap snapshot is missing.')
            return {'CANCELLED'}
        try:
            _copy_image_pixels(backup, target)
            last_backup = bpy.data.images.get(obj.get('qss_last_bake_backup', ''))
            if last_backup is not None:
                bpy.data.images.remove(last_backup)
            obj['qss_last_bake_backup'] = ''
            obj['qss_lightmap_source'] = 'original_bsp_lightmaps'
            obj['qss_lightmap_gradient_baked'] = False
            self.report({'INFO'}, 'Restored original BSP lightmaps.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not restore source lightmaps: {exc}')
            return {'CANCELLED'}


class QSS_OT_refresh_lightmap_preview(Operator):
    bl_idname = 'qss.refresh_lightmap_preview'
    bl_label = 'Repair Lightmap Preview'
    bl_description = 'Reconnect the RGB atlas to every material slot and check face UV ranges'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_lightmap_image_name'))

    def execute(self, context):
        try:
            hooked, total = _rebuild_lightmap_preview(context.object)
            valid = int(context.object.get('qss_lightmap_uv_valid_faces', 0))
            self.report({'INFO'}, f'Atlas connected to {hooked}/{total} material slots; {valid}/{len(context.object.data.polygons)} UV-valid faces.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not repair lightmap preview: {exc}')
            return {'CANCELLED'}


class QSS_OT_calibrate_lights_to_source(Operator):
    bl_idname = 'qss.calibrate_lights_to_source'
    bl_label = 'Auto-calibrate Live Lights to Source'
    bl_description = 'Run a temporary Cycles bake, determine the source-average energy multiplier, restore the original lightmap, and return to Live Lights'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_original_lightmap_backup') and obj.get('qss_light_entity_count', 0) > 0)

    def execute(self, context):
        obj = context.object
        source_image = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
        current_image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        if source_image is None or current_image is None:
            self.report({'ERROR'}, 'The current or original source lightmap image is missing.')
            return {'CANCELLED'}
        original_pixels = array.array('f', [0.0]) * (len(current_image.pixels))
        current_image.pixels.foreach_get(original_pixels)
        old_source = obj.get('qss_lightmap_source', 'original_bsp_lightmaps')
        old_scale = float(context.scene.qss_light_energy_scale)
        old_object_calibration = float(obj.get('qss_light_energy_calibration', 1.0))
        imported_lights = [light_obj for light_obj in context.scene.objects
                           if light_obj.type == 'LIGHT' and light_obj.get('qss_light_role') in
                           {'quake_entity_light', 'quake_world_sunlight'}]
        old_light_calibrations = {light_obj.name: float(light_obj.get('qss_energy_calibration', old_object_calibration))
                                  for light_obj in imported_lights}
        context.scene.qss_light_energy_scale = max(old_scale, 0.01)
        context.scene.qss_bake_match_source = True
        result = bpy.ops.qss.bake_scene_lights()
        if 'FINISHED' not in result:
            # The bake operator handles its own pixel rollback on failure.
            context.scene.qss_light_energy_scale = old_scale
            obj['qss_lightmap_source'] = old_source
            return {'CANCELLED'}
        try:
            # Bake auto-calibrates the lamp multiplier and image; this command is
            # only a calibration probe, so restore the pristine source atlas.
            current_image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
            if current_image is None:
                raise bsp.BSPError('The lightmap atlas disappeared after calibration bake.')
            _copy_image_pixels(source_image, current_image)
            backup = bpy.data.images.get(obj.get('qss_last_bake_backup', ''))
            if backup is not None:
                bpy.data.images.remove(backup)
            obj['qss_last_bake_backup'] = ''
            obj['qss_lightmap_source'] = 'original_bsp_lightmaps'
            obj['qss_lightmap_gradient_baked'] = False
            context.scene.qss_light_energy_scale = 1.0
            _apply_quake_light_energy_scale(context.scene)
            _set_lighting_preview(context, obj, 'realtime')
            self.report({'INFO'},
                        f"Calibration complete: {float(obj.get('qss_light_energy_calibration', 1.0)):.4g}x; "
                        "live scale 1 targets source mean brightness. Original atlas restored. "
                        "Spatial falloff still approximates ericw's linear attenuation.")
            return {'FINISHED'}
        except Exception as exc:
            if current_image:
                try:
                    current_image.pixels.foreach_set(original_pixels)
                    current_image.update()
                except Exception:
                    pass
            context.scene.qss_light_energy_scale = old_scale
            obj['qss_light_energy_calibration'] = old_object_calibration
            for light_obj in imported_lights:
                light_obj['qss_energy_calibration'] = old_light_calibrations.get(
                    light_obj.name, old_object_calibration)
            _apply_quake_light_energy_scale(context.scene)
            obj['qss_lightmap_source'] = old_source
            self.report({'ERROR'}, f'Could not finish source calibration: {exc}')
            return {'CANCELLED'}


class QSS_OT_apply_light_energy_scale(Operator):
    bl_idname = 'qss.apply_light_energy_scale'
    bl_label = 'Apply Light Energy Scale'
    bl_description = 'Reapply the current multiplier to all imported Quake light objects'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.get('qss_object_role') == 'quake_bsp29')

    def execute(self, context):
        updated = _apply_quake_light_energy_scale(context.scene)
        energies = [float(o.data.energy) for o in context.scene.objects
                    if o.type == 'LIGHT' and o.get('qss_light_role') in {'quake_entity_light', 'quake_world_sunlight'}]
        maximum = max(energies, default=0.0)
        self.report({'INFO'}, f'Applied multiplier {context.scene.qss_light_energy_scale:g} to {updated} lights; max energy {maximum:.3g} W.')
        return {'FINISHED'}


class QSS_OT_frame_selection(Operator):
    bl_idname = "qss.frame_selection"
    bl_label = "Focus Selected Face(s)"
    bl_description = "Frame the selected mesh faces in the 3D View (Numpad Period)"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and context.mode in {'OBJECT', 'EDIT_MESH'})

    def execute(self, context):
        screen = context.screen
        for area in screen.areas if screen else []:
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            try:
                with context.temp_override(window=context.window, area=area, region=region):
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                return {'FINISHED'}
            except Exception as exc:
                _report(self, 'ERROR', f"Could not frame selection: {exc}")
                return {'CANCELLED'}
        _report(self, 'WARNING', "No 3D View found. Move the mouse over the level viewport and try again.")
        return {'CANCELLED'}


class QSS_OT_isolate_faces(Operator):
    bl_idname = "qss.isolate_faces"
    bl_label = "Isolate Selected Faces"
    bl_description = "Hide all unselected faces temporarily; use Reveal All to restore them"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and context.mode == 'EDIT_MESH')

    def execute(self, context):
        import bmesh
        bm = bmesh.from_edit_mesh(context.object.data)
        if not any(face.select for face in bm.faces):
            _report(self, 'WARNING', "Select the face(s) to isolate first.")
            return {'CANCELLED'}
        try:
            bpy.ops.mesh.hide(unselected=True)
            return {'FINISHED'}
        except RuntimeError as exc:
            _report(self, 'ERROR', f"Could not isolate faces: {exc}")
            return {'CANCELLED'}


class QSS_OT_reveal_faces(Operator):
    bl_idname = "qss.reveal_faces"
    bl_label = "Reveal Hidden Faces"
    bl_description = "Restore faces hidden by Isolate Selected Faces"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and context.mode == 'EDIT_MESH')

    def execute(self, context):
        try:
            bpy.ops.mesh.reveal(select=False)
            return {'FINISHED'}
        except RuntimeError as exc:
            _report(self, 'ERROR', f"Could not reveal faces: {exc}")
            return {'CANCELLED'}


class QSS_OT_export_bsp(Operator, ExportHelper):
    bl_idname = "qss.export_bsp"
    bl_label = "Export Modified BSP"
    bl_description = "Write texture and face-material changes back to a BSP29 file"
    filename_ext = ".bsp"
    filter_glob: StringProperty(default="*.bsp", options={'HIDDEN'})

    def invoke(self, context, event):
        obj = context.object
        source = obj.get('qss_source_path', '') if obj else ''
        if source:
            root, ext = os.path.splitext(source)
            self.filepath = root + "_surface_studio" + ext
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            result = _export_object(context.object, self.filepath)
            path, texture_count, changed_faces, replacements, palette_origin, lit_path = result
            detail = f" | {os.path.basename(lit_path)} written" if lit_path else ""
            _report(
                self, 'INFO',
                f"Exported {os.path.basename(path)} | {texture_count} textures | "
                f"{changed_faces} face reassignment(s) | {replacements} edited shared texture(s){detail}."
            )
            return {'FINISHED'}
        except Exception as exc:
            _report(self, 'ERROR', str(exc))
            return {'CANCELLED'}


def _qss_diagnostics_text(context, obj):
    """Build a compact, copyable report for RGB atlas, shaders and imported lights."""
    lines = [
        'QUAKE SURFACE STUDIO DIAGNOSTICS',
        f'Blender: {bpy.app.version_string}',
        f'QSS object: {obj.name}',
        f'Source BSP: {obj.get("qss_source_path", "")}',
        f'Preview mode: {obj.get("qss_preview_mode", "unknown")}',
        f'Render engine: {context.scene.render.engine}',
        f'RGB source: {obj.get("qss_source_lighting_source", "unknown")}',
        f'BSPX lumps: {obj.get("qss_bspx_lump_names", "")}',
        f'Light energy scale: {getattr(context.scene, "qss_light_energy_scale", -1)}',
        f'Source-match calibration: {obj.get("qss_light_energy_calibration", 1.0)}',
        f'Last bake: raw_mean={obj.get("qss_last_bake_raw_mean", "n/a")} source_mean={obj.get("qss_last_bake_source_mean", "n/a")} atlas_mean={obj.get("qss_last_bake_luxel_mean", "n/a")} max={obj.get("qss_last_bake_luxel_max", "n/a")} normalization={obj.get("qss_last_bake_output_scale", "n/a")}',
        f'Last attempted bake: scale={obj.get("qss_last_bake_attempt_scale", "n/a")} max_lamp_energy={obj.get("qss_last_bake_attempt_max_lamp_energy", "n/a")} sampled_luxels={obj.get("qss_last_bake_attempt_sample_count", "n/a")} sampled_mean={obj.get("qss_last_bake_attempt_raw_mean", "n/a")} image_stats={obj.get("qss_last_bake_attempt_image_stats", "n/a")}',
        f'Last Cycles bake operator result: {obj.get("qss_last_bake_attempt_operator_result", "n/a")}',
        f'Last Cycles attempt config: engine={obj.get("qss_last_bake_attempt_engine", "n/a")} target={obj.get("qss_last_bake_attempt_target", "n/a")} type={obj.get("qss_last_bake_attempt_type", "n/a")} uv={obj.get("qss_last_bake_attempt_uv", "n/a")}',
        f'Last attempted lamp states: {obj.get("qss_last_bake_attempt_lights", "n/a")}',
        f'Current (restored) bake settings: engine={context.scene.render.engine} target={getattr(context.scene.render.bake, "target", "n/a")} samples={getattr(getattr(context.scene, "cycles", None), "samples", "n/a")} diffuse_bounces={getattr(getattr(context.scene, "cycles", None), "diffuse_bounces", "n/a")} color={getattr(context.scene.render.bake, "use_pass_color", "n/a")} diffuse={getattr(context.scene.render.bake, "use_pass_diffuse", "n/a")} direct={getattr(context.scene.render.bake, "use_pass_direct", "n/a")} indirect={getattr(context.scene.render.bake, "use_pass_indirect", "n/a")}',
        f'Color management: view_transform={context.scene.view_settings.view_transform} look={context.scene.view_settings.look} exposure={context.scene.view_settings.exposure} gamma={context.scene.view_settings.gamma}',
        f'Compiler bounce: {obj.get("qss_world_bounce", 0)}',
        f'Compiler bounce color scale: {obj.get("qss_world_bouncecolorscale", 0.0)}',
        f'Quake direct bake: luxels={obj.get("qss_last_quake_bake_luxels", "n/a")} lit={obj.get("qss_last_quake_bake_lit_luxels", "n/a")} rays={obj.get("qss_last_quake_bake_ray_tests", "n/a")} blocked={obj.get("qss_last_quake_bake_occluded", "n/a")} raw_mean={obj.get("qss_last_quake_bake_raw_mean", "n/a")} source_mean={obj.get("qss_last_quake_bake_source_mean", "n/a")} normalization={obj.get("qss_last_quake_bake_normalization", "n/a")}',
    ]
    mesh = obj.data
    lines.append(f'Mesh faces: {len(mesh.polygons)}; materials: {len(mesh.materials)}; loops={len(mesh.loops)}; vertices={len(mesh.vertices)}')
    for attr_name in ('qss_bsp_face_id', 'qss_bsp_texinfo_id', 'qss_bsp_miptex_id',
                      'qss_lm_has_data', 'qss_lm_atlas_x', 'qss_lm_atlas_y',
                      'qss_lm_sample_w', 'qss_lm_sample_h'):
        try:
            attr = mesh.attributes.get(attr_name)
            count = len(attr.data) if attr is not None else 'MISSING'
        except Exception as exc:
            count = f'ERROR ({exc})'
        lines.append(f'  Attribute {attr_name}: {count} entries / {len(mesh.polygons)} faces')
    for uv_name in ('Quake_Texture_UV', 'Quake_Lightmap_UV'):
        try:
            uv = mesh.uv_layers.get(uv_name)
            count = len(uv.data) if uv is not None else 'MISSING'
        except Exception as exc:
            count = f'ERROR ({exc})'
        lines.append(f'  UV {uv_name}: {count} entries / {len(mesh.loops)} loops')
    lines.append(f'Last detach error: {obj.get("qss_last_detach_error", "none")}')
    if obj.get('qss_last_detach_traceback'):
        lines.append('Last detach traceback:\n' + str(obj.get('qss_last_detach_traceback'))[-6000:])
    lines.append(f'Last Quake bake error: {obj.get("qss_last_quake_bake_error", "none")}')
    image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
    if image is None:
        lines.append('Lightmap image: MISSING')
    else:
        lines.append(f'Lightmap image: {image.name} {tuple(image.size)} float={image.is_float} colorspace={image.colorspace_settings.name}')
        attrs = {name: mesh.attributes.get(name) for name in (
            'qss_bsp_face_id', 'qss_lm_has_data', 'qss_lm_atlas_x', 'qss_lm_atlas_y',
            'qss_lm_sample_w', 'qss_lm_sample_h'
        )}
        required_count = len(mesh.polygons)
        attrs_valid = all(
            attr is not None and len(attr.data) == required_count
            for attr in attrs.values()
        )
        if attrs_valid:
            size = int(image.size[0])
            scale = max(1, int(obj.get('qss_lightmap_scale', 1)))
            gutter = max(0, int(obj.get('qss_lightmap_gutter', 0)))
            pix = array.array('f', [0.0]) * (size * size * 4)
            image.update()
            image.pixels.foreach_get(pix)
            face_stats = []
            valid_count = chromatic_count = 0
            for i, poly in enumerate(mesh.polygons):
                if i >= len(attrs['qss_lm_has_data'].data):
                    break
                try:
                    if not _qss_safe_collection_item(attrs['qss_lm_has_data'].data, i, 'qss_lm_has_data').value:
                        continue
                    face_id = int(_qss_safe_collection_item(attrs['qss_bsp_face_id'].data, i, 'qss_bsp_face_id').value)
                    x0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_x'].data, i, 'qss_lm_atlas_x').value) + gutter
                    y0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_y'].data, i, 'qss_lm_atlas_y').value) + gutter
                    w = int(_qss_safe_collection_item(attrs['qss_lm_sample_w'].data, i, 'qss_lm_sample_w').value)
                    h = int(_qss_safe_collection_item(attrs['qss_lm_sample_h'].data, i, 'qss_lm_sample_h').value)
                except (bsp.BSPError, IndexError, RuntimeError, ReferenceError) as exc:
                    lines.append(f'  Face {i}: metadata unavailable during diagnostics: {exc}')
                    continue
                samples = []
                for sy in range(h):
                    for sx in range(w):
                        yy = size - 1 - (y0 + sy * scale + (scale - 1) // 2)
                        xx = x0 + sx * scale + (scale - 1) // 2
                        if 0 <= xx < size and 0 <= yy < size:
                            off = (yy * size + xx) * 4
                            samples.append(tuple(pix[off:off + 3]))
                if not samples:
                    continue
                valid_count += 1
                chroma = max((max(c) - min(c) for c in samples), default=0.0)
                if chroma >= 12.0 / 255.0:
                    chromatic_count += 1
                mean_rgb = tuple(sum(c[k] for c in samples) / len(samples) for k in range(3))
                ranges = tuple(max(c[k] for c in samples) - min(c[k] for c in samples) for k in range(3))
                face_stats.append((face_id, len(samples), mean_rgb, ranges, chroma))
            lines.append(f'Atlas face sample stats: {valid_count} faces; chromatic by atlas pixels: {chromatic_count}/{valid_count}')
            for face_id, count, mean_rgb, ranges, chroma in face_stats:
                lines.append('  face {:3d}: {:3d} luxels mean=({:.3f},{:.3f},{:.3f}) range=({:.3f},{:.3f},{:.3f}) chroma={:.3f}'.format(
                    face_id, count, *mean_rgb, *ranges, chroma))
        else:
            lengths = {name: (len(attr.data) if attr is not None else None) for name, attr in attrs.items()}
            lines.append(f'Lightmap face attributes: MISSING OR STALE; required face count={required_count}; lengths={lengths}')

    lines.append('MATERIALS:')
    for slot, mat in enumerate(mesh.materials):
        if mat is None:
            lines.append(f'  slot {slot}: EMPTY')
            continue
        base_images = []
        light_images = []
        uv_maps = []
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    role = node.get('qss_role', '')
                    entry = f'{node.image.name}[{node.image.colorspace_settings.name}]'
                    if role == 'base_texture':
                        base_images.append(entry)
                    elif role == 'lightmap':
                        light_images.append(entry)
                elif node.type == 'UVMAP':
                    uv_maps.append(f'{node.get("qss_role", "")}: {node.uv_map}')
        lines.append(f'  slot {slot} {mat.name}: base={base_images} lightmap={light_images} uv={uv_maps}')

    lines.append('IMPORTED LIGHTS:')
    for light_obj in context.scene.objects:
        if light_obj.type != 'LIGHT' or light_obj.get('qss_light_role') not in {'quake_entity_light', 'quake_world_sunlight'}:
            continue
        lines.append('  {} type={} color={} energy={:.6g} W style={} inferred={} value={} delay={} range={} calibration={}'.format(
            light_obj.name, light_obj.data.type, tuple(round(float(v), 4) for v in light_obj.data.color),
            float(light_obj.data.energy), light_obj.get('qss_quake_light_style', 0),
            light_obj.get('qss_quake_style_was_inferred', False), light_obj.get('qss_quake_light_value', ''),
            light_obj.get('qss_quake_light_delay', 0), light_obj.get('qss_quake_range', ''),
            light_obj.get('qss_energy_calibration', 1.0)))
    world = context.scene.world
    lines.append(f'World: {world.name if world else "None"}')
    if world and world.use_nodes and world.node_tree:
        bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
        if bg:
            lines.append(f'  Background color={tuple(bg.inputs["Color"].default_value)} strength={bg.inputs["Strength"].default_value}')
    # Read original per-face style IDs from the exact compiled BSP. This
    # makes the report useful for separating an RGB atlas issue from a style
    # layer/face-offset issue.
    source_path = obj.get('qss_source_path', '')
    if source_path and os.path.isfile(source_path):
        try:
            parsed_source = bsp.BSP29.from_file(source_path)
            source_faces = parsed_source.faces()
            style_counts = {}
            style_rows = []
            for face_id, face in enumerate(source_faces):
                styles = [int(value) for value in face[5:9] if int(value) != 255]
                for style_id in styles:
                    style_counts[style_id] = style_counts.get(style_id, 0) + 1
                if face_id < len(mesh.polygons):
                    style_rows.append(f'  BSP face {face_id}: styles={styles} lightofs={int(face[9])}')
            lines.append(f'BSP face style distribution: {style_counts}')
            lines.extend(style_rows)
        except Exception as exc:
            lines.append(f'BSP face style metadata: unavailable ({exc})')
    else:
        lines.append('BSP face style metadata: source BSP path unavailable')

    screen = getattr(context, 'screen', None)
    if screen:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                shading = area.spaces.active.shading
                lines.append('Viewport: {} scene_lights={} scene_world={} scene_lights_render={} scene_world_render={}'.format(
                    shading.type, getattr(shading, 'use_scene_lights', None),
                    getattr(shading, 'use_scene_world', None),
                    getattr(shading, 'use_scene_lights_render', None),
                    getattr(shading, 'use_scene_world_render', None)))
                break
    lines.append('')
    lines.append('NOTE: atlas chroma reports actual sampled face pixels, not the source-side summary counter.')
    lines.append('NOTE: Live Lights requires View3D use_scene_lights_render=True and use_scene_world_render=True.')
    lines.append('Run ericw-tools bspinfo on the same BSP for independent per-style lightmap atlas exports.')
    return '\n'.join(lines)


class QSS_OT_write_diagnostics(Operator, ExportHelper):
    bl_idname = 'qss.write_diagnostics'
    bl_label = 'Save Lighting Diagnostics'
    bl_description = 'Save a detailed text report and also create a Blender Text datablock'
    filename_ext = '.txt'
    filter_glob: StringProperty(default='*.txt', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29')

    def invoke(self, context, event):
        obj = context.object
        stem = os.path.splitext(os.path.basename(obj.get('qss_source_path', obj.name)))[0]
        if bpy.data.filepath:
            start_dir = os.path.dirname(bpy.data.filepath)
        else:
            start_dir = os.path.expanduser('~/Desktop')
            if not os.path.isdir(start_dir):
                start_dir = os.path.expanduser('~')
        self.filepath = os.path.join(start_dir, f'QSS_{stem}_diagnostics.txt')
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.object
        try:
            report = _qss_diagnostics_text(context, obj)
            path = bpy.path.abspath(self.filepath)
            if not path:
                raise OSError('Choose a destination filename for the diagnostics report.')
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(report)
            # Also embed the report in the .blend as a Text datablock and copy
            # it to the clipboard so it is easy to retrieve without a file hunt.
            text_name = f'QSS_{os.path.splitext(os.path.basename(obj.get("qss_source_path", obj.name)))[0]}_diagnostics'
            text_block = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
            text_block.clear()
            text_block.write(report)
            context.window_manager.clipboard = report
            print('\n' + report)
            self.report({'INFO'}, f'Saved {path}; report also stored as Blender Text "{text_name}" and copied to clipboard')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Could not write diagnostics: {exc}')
            return {'CANCELLED'}


class QSS_OT_run_blender_selftest(Operator):
    bl_idname = 'qss.run_blender_selftest'
    bl_label = 'Run Blender Self-Test + Luxel Benchmark'
    bl_description = 'Run non-destructive Blender checks, a Cycles image-bake probe, and all six Quake delay modes over the imported map luxels'
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene)

    def execute(self, context):
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qss_blender_diagnostics.py')
        if not os.path.isfile(script_path):
            self.report({'ERROR'}, f'Diagnostic script not found: {script_path}')
            return {'CANCELLED'}
        try:
            with open(script_path, 'r', encoding='utf-8') as handle:
                source = handle.read()
            namespace = {
                '__name__': '__main__',
                '__file__': script_path,
                '__package__': '',
            }
            exec(compile(source, script_path, 'exec'), namespace, namespace)
            output = os.path.expanduser('~/Desktop/QSS_Blender_SelfTest.txt')
            if not os.path.isfile(output):
                output = os.path.expanduser('~/QSS_Blender_SelfTest.txt')
            self.report({'INFO'}, f'Self-test complete. Report: {output}')
            return {'FINISHED'}
        except Exception as exc:
            trace = traceback.format_exc()
            obj = context.object
            if _qss_is_map_object(obj):
                obj['qss_last_selftest_error'] = str(exc)
                obj['qss_last_selftest_traceback'] = trace[-12000:]
            print(trace)
            self.report({'ERROR'}, f'Self-test failed: {exc}')
            return {'CANCELLED'}


def _qss_is_map_object(obj):
    return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29')


class QSS_PT_main(Panel):
    bl_label = "Quake Surface Studio"
    bl_idname = "QSS_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        import_box = layout.box()
        import_box.label(text="START HERE · PROJECT", icon='FILE_3D')
        import_box.operator(QSS_OT_import_bsp.bl_idname, text="Import Quake BSP…", icon='IMPORT')
        obj = context.object
        if _qss_is_map_object(obj):
            summary = layout.box()
            summary.label(text=os.path.basename(obj.get('qss_source_path', obj.name)), icon='FILE_3D')
            grid = summary.grid_flow(columns=2, even_columns=True, even_rows=True, align=True)
            grid.label(text=f"{len(obj.data.polygons)} faces", icon='FACESEL')
            grid.label(text=f"{len(obj.data.materials)} materials", icon='MATERIAL')
            grid.label(text=f"{obj.get('qss_light_entity_count', 0)} lights", icon='LIGHT')
            grid.label(text=f"{obj.get('qss_lightmap_faces', 0)} lit faces", icon='IMAGE')
            status = summary.row()
            if obj.get('qss_last_quake_bake_error'):
                status.alert = True
                status.label(text="Last Quake bake failed · open 05 Diagnostics", icon='ERROR')
            elif obj.get('qss_lightmap_source') == 'quake_direct_cpu_bake':
                status.label(text="Quake direct lightmap active", icon='CHECKMARK')
            else:
                status.label(text="BSP loaded · choose a workflow section", icon='CHECKMARK')
            layout.label(text="WORKFLOW", icon='SORT_ASC')
            layout.label(text="01 Project  →  02 Navigate  →  03 Paint  →  04 Light  →  05 Test  →  06 Export", icon='INFO')
        else:
            layout.label(text="Select an imported BSP29 mesh to access its tools.", icon='INFO')


class QSS_PT_project(Panel):
    bl_label = "01 · Project & Source"
    bl_idname = "QSS_PT_project"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_main"
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='FILE_FOLDER')

    def draw(self, context):
        layout = self.layout
        obj = context.object
        layout.prop(context.scene, 'qss_game_dir', text="Game folder")
        if not _qss_is_map_object(obj):
            layout.label(text="No Quake BSP selected.", icon='INFO')
            return
        layout.label(text=os.path.basename(obj.get('qss_source_path', 'BSP29')), icon='FILE')
        grid = layout.grid_flow(columns=2, even_columns=True, even_rows=True, align=True)
        grid.label(text=f"Faces: {obj.get('qss_total_bsp_faces', len(obj.data.polygons))}")
        grid.label(text=f"Lights: {obj.get('qss_light_entity_count', 0)}")
        grid.label(text=f"Materials: {len(obj.data.materials)}")
        grid.label(text=f"Unit: {obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE):.5g} m")
        layout.label(text=f"Textures: {obj.get('qss_texture_embedded_count', 0)} embedded / "
                          f"{obj.get('qss_texture_wad_count', 0)} WAD / {obj.get('qss_texture_loose_count', 0)} loose")
        if obj.get('qss_bspx_lump_names'):
            layout.label(text=f"BSPX: {obj.get('qss_bspx_lump_names', '')[:100]}", icon='FILE_TEXT')
        for key, text in (
            ('qss_missing_texture_names', 'Missing textures: '),
            ('qss_wad_unresolved', 'WAD not found: '),
            ('qss_wad_failures', 'WAD read issue: '),
        ):
            if obj.get(key):
                row = layout.row()
                row.alert = True
                row.label(text=text + str(obj.get(key))[:80], icon='ERROR')
        if obj.get('qss_texture_white_count', 0):
            layout.label(text=f"White fallbacks: {obj.get('qss_texture_white_count', 0)}", icon='INFO')


class QSS_PT_navigation(Panel):
    bl_label = "02 · Navigation & Selection"
    bl_idname = "QSS_PT_navigation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_main"
    bl_order = 20
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw_header(self, context):
        self.layout.label(text="", icon='VIEW3D')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        obj = context.object
        frame = layout.box()
        frame.label(text="VIEWPORT & SELECTION", icon='VIEW3D')
        frame.operator(QSS_OT_frame_selection.bl_idname, icon='VIEWZOOM')
        row = frame.row(align=True)
        row.operator(QSS_OT_isolate_faces.bl_idname, icon='HIDE_OFF')
        row.operator(QSS_OT_reveal_faces.bl_idname, icon='HIDE_ON')
        frame.operator(QSS_OT_optimize_clipping.bl_idname, icon='MOD_PHYSICS')
        player = layout.box()
        player.label(text="FIRST-PERSON NAVIGATION", icon='ORIENTATION_VIEW')
        if obj.get('qss_has_player_start'):
            player.operator(QSS_OT_player_start.bl_idname, icon='EMPTY_AXIS')
        player.operator(QSS_OT_fps_walk.bl_idname, icon='VIEW_PAN')
        player.prop(context.scene, 'qss_nav_speed_quake', text="Speed (Quake u/s)")
        player.prop(context.scene, 'qss_nav_fast_factor', text="Fast multiplier")
        player.label(text=f"Clip: {obj.get('qss_view_clip_start', 0.01):.3g} / {obj.get('qss_view_clip_end', 1000):.3g}")
        if obj.get('qss_flip_z'):
            row = player.row()
            row.alert = True
            row.label(text="Imported with inverted Z axis", icon='INFO')
        player.prop(context.scene, 'qss_mmb_fps_walk', text='Enable hold-MMB FPS navigation')
        player.label(text="Hold MMB: look + WASD; release to exit")


class QSS_PT_texture(Panel):
    bl_label = "03 · Texture Workshop"
    bl_idname = "QSS_PT_texture"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_main"
    bl_order = 30
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw_header(self, context):
        self.layout.label(text="", icon='IMAGE')

    def draw(self, context):
        layout = self.layout
        obj = context.object
        selected = 0
        if context.mode == 'EDIT_MESH':
            try:
                import bmesh
                selected = sum(1 for face in bmesh.from_edit_mesh(obj.data).faces if face.select)
            except Exception:
                selected = 0
        else:
            selected = sum(1 for poly in obj.data.polygons if poly.select)
        layout.use_property_split = True
        workshop = layout.box()
        workshop.label(text="FACE MATERIAL WORKSHOP", icon='FACESEL')
        workshop.label(text=f"Selected faces: {selected}", icon='RESTRICT_SELECT_OFF')
        workshop.operator(QSS_OT_detach_faces.bl_idname, icon='DUPLICATE')
        active_mat = obj.active_material
        if active_mat and 'qss_export_name' in active_mat:
            workshop.prop(active_mat, '["qss_export_name"]', text="BSP texture name")
        workshop.operator(QSS_OT_activate_paint.bl_idname, icon='BRUSH_DATA')
        workshop.label(text="Detach creates a face-local 0–1 paint canvas.", icon='INFO')


class QSS_PT_lighting(Panel):
    bl_label = "04 · Lighting Studio"
    bl_idname = "QSS_PT_lighting"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_main"
    bl_order = 40
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw_header(self, context):
        self.layout.label(text="", icon='LIGHT')

    def draw(self, context):
        obj = context.object
        layout = self.layout
        layout.use_property_split = True
        row = layout.row(align=True)
        row.label(text=f"Entity lights: {obj.get('qss_light_entity_count', 0)}")
        row.label(text=f"Bounce: {obj.get('qss_world_bounce', 0)}")
        if obj.get('qss_lightmap_image_name'):
            layout.label(text=f"RGB source: {obj.get('qss_source_lighting_source', 'Monochrome')}")
            layout.label(text=f"Lightmapped faces: {obj.get('qss_lightmap_faces', 0)} / {obj.get('qss_total_bsp_faces', len(obj.data.polygons))}")
            layout.label(text=f"RGB chromatic faces: {obj.get('qss_lit_chromatic_faces', 0)} / {obj.get('qss_lit_rgb_faces', 0)}")


class QSS_PT_light_preview(Panel):
    bl_label = "A · Reference / Live / Baked"
    bl_idname = "QSS_PT_light_preview"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_lighting"
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='SHADING_RENDERED')

    def draw(self, context):
        obj = context.object
        layout = self.layout
        original = layout.box()
        original.label(text="01 · ORIGINAL REFERENCE", icon='IMAGE_DATA')
        original.operator(QSS_OT_preview_source_lightmaps.bl_idname, text="1 · Original BSP Lightmap", icon='IMAGE_DATA')
        live = layout.box()
        live.label(text="02 · INTERACTIVE LIGHTING", icon='LIGHT')
        live.operator(QSS_OT_preview_imported_lights.bl_idname, text="2 · Live Lights", icon='LIGHT')
        baked = layout.box()
        baked.label(text="03 · EDITED LIGHTMAP", icon='RENDER_STILL')
        baked.operator(QSS_OT_preview_bsp_lightmaps.bl_idname, text="3 · Baked / Working", icon='RENDER_STILL')
        layout.operator(QSS_OT_refresh_lightmap_preview.bl_idname, icon='FILE_REFRESH')
        layout.prop(context.scene, 'qss_light_energy_scale', text="Live light scale")
        layout.operator(QSS_OT_apply_light_energy_scale.bl_idname, icon='LIGHT')
        layout.operator(QSS_OT_calibrate_lights_to_source.bl_idname, icon='DRIVER')
        layout.label(text=f"Source calibration: {obj.get('qss_light_energy_calibration', 1.0):.4g}×")
        layout.label(text="The live preview uses Blender's physical inverse-square lamp model.", icon='INFO')


class QSS_PT_imported_lights(Panel):
    bl_label = "B · Quake Light Entities"
    bl_idname = "QSS_PT_imported_lights"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_lighting"
    bl_order = 20
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='OUTLINER_OB_LIGHT')

    def draw(self, context):
        layout = self.layout
        obj = context.object
        lamps = [o for o in context.scene.objects if o.type == 'LIGHT' and
                 o.get('qss_light_role') in {'quake_entity_light', 'quake_world_sunlight'}]
        if not lamps:
            layout.label(text="No imported Quake lights.", icon='INFO')
            return
        for lamp in lamps:
            box = layout.box()
            box.label(text=f"{lamp.name} · {float(lamp.data.energy):.3g} W", icon='LIGHT_POINT')
            row = box.row(align=True)
            if 'qss_quake_light_delay' in lamp:
                row.prop(lamp, '["qss_quake_light_delay"]', text="delay")
            if 'qss_quake_light_style' in lamp:
                row.prop(lamp, '["qss_quake_light_style"]', text="style")
            row = box.row(align=True)
            if 'qss_quake_wait' in lamp:
                row.prop(lamp, '["qss_quake_wait"]', text="wait")
            if 'qss_quake_anglescale' in lamp:
                row.prop(lamp, '["qss_quake_anglescale"]', text="anglescale")
            if 'qss_quake_falloff' in lamp:
                box.prop(lamp, '["qss_quake_falloff"]', text="_falloff")
            if lamp.get('qss_quake_style_was_inferred'):
                row = box.row()
                row.alert = True
                row.label(text="Style recovered from malformed empty key", icon='ERROR')
        layout.label(text="delay 4 is a non-additive local-minlight clamp.", icon='INFO')


class QSS_PT_quake_bake(Panel):
    bl_label = "C · Quake Direct Lightmap Solver"
    bl_idname = "QSS_PT_quake_bake"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_lighting"
    bl_order = 30
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='RENDER_STILL')

    def draw(self, context):
        obj = context.object
        layout = self.layout
        hero = layout.box()
        hero.label(text="QUAKE-SPACE RGB LUXEL SOLVER", icon='LIGHT_HEMI')
        hero.operator(QSS_OT_quake_direct_bake.bl_idname, text="Bake Quake Direct Lighting", icon='RENDER_STILL')
        options = layout.box()
        options.label(text="SOLVER OPTIONS", icon='PREFERENCES')
        options.prop(context.scene, 'qss_quake_bake_shadows', text="Ray-traced visibility")
        options.prop(context.scene, 'qss_quake_bake_gate', text="Contribution gate")
        options.prop(context.scene, 'qss_bake_match_source', text="Match source average")
        options.prop(context.scene, 'qss_bake_output_scale', text="Output brightness")
        if obj.get('qss_last_quake_bake_luxels'):
            layout.label(text=f"Luxels lit: {obj.get('qss_last_quake_bake_lit_luxels', 0)} / {obj.get('qss_last_quake_bake_luxels', 0)}")
            layout.label(text=f"Shadow rays: {obj.get('qss_last_quake_bake_ray_tests', 0)} / blocked {obj.get('qss_last_quake_bake_occluded', 0)}")
            layout.label(text=f"Delay modes: {obj.get('qss_last_quake_bake_modes', '')}")
        if obj.get('qss_last_quake_bake_error'):
            box = layout.box()
            box.alert = True
            box.label(text=str(obj.get('qss_last_quake_bake_error'))[:100], icon='ERROR')
        layout.operator(QSS_OT_undo_last_bake.bl_idname, icon='LOOP_BACK')
        layout.operator(QSS_OT_restore_original_lightmap.bl_idname, icon='BACK')
        layout.label(text="Direct point/spot; delay 0–5; hard visibility.", icon='INFO')
        layout.label(text="No radiosity, dirt, deviance/area samples or sky sunlight yet.", icon='INFO')


class QSS_PT_cycles_bake(Panel):
    bl_label = "D · Cycles PBR Bake (Experimental)"
    bl_idname = "QSS_PT_cycles_bake"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_lighting"
    bl_order = 40
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='NODE_MATERIAL')

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, 'qss_bake_bounces', text="Diffuse bounces")
        layout.operator(QSS_OT_bake_scene_lights.bl_idname, text="Cycles Path-Traced Bake", icon='RENDER_STILL')
        layout.label(text="Physically based falloff; does not implement ericw delay modes.", icon='INFO')


class QSS_PT_diagnostics(Panel):
    bl_label = "05 · Diagnostics & Recovery"
    bl_idname = "QSS_PT_diagnostics"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_main"
    bl_order = 50
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw_header(self, context):
        self.layout.label(text="", icon='TEXT')

    def draw(self, context):
        layout = self.layout
        obj = context.object
        diagnostics = layout.box()
        diagnostics.label(text="REPORTS & AUTOMATED TESTS", icon='TEXT')
        diagnostics.operator(QSS_OT_write_diagnostics.bl_idname, text="Save Lighting Diagnostics…", icon='FILE_TEXT')
        diagnostics.operator(QSS_OT_run_blender_selftest.bl_idname, text="Run Full Self-Test + Delay Benchmark", icon='EXPERIMENT')
        diagnostics.label(text="Object Mode required. Tests every BSP luxel in seven passes.", icon='TIME')
        diagnostics.label(text="Progress appears in Blender's status bar; report is saved to Desktop and a Text datablock.", icon='INFO')
        diagnostics.label(text="Dry run only: does not change the BSP or lightmap atlas.", icon='CHECKMARK')
        recovery = layout.box()
        recovery.label(text="Recovery & material repair", icon='TOOL_SETTINGS')
        recovery.operator(QSS_OT_refresh_lightmap_preview.bl_idname, text="Repair Lightmap Material Links", icon='FILE_REFRESH')
        if obj.get('qss_last_detach_traceback') or obj.get('qss_last_quake_bake_traceback') or obj.get('qss_last_selftest_traceback'):
            row = layout.row()
            row.alert = True
            row.label(text="Detailed errors are included in diagnostics.", icon='ERROR')
        layout.label(text="The luxel benchmark tests actual BSP face samples; it does not modify the atlas.", icon='INFO')


class QSS_PT_export(Panel):
    bl_label = "06 · BSP Export"
    bl_idname = "QSS_PT_export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quake"
    bl_parent_id = "QSS_PT_main"
    bl_order = 60
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw_header(self, context):
        self.layout.label(text="", icon='EXPORT')

    def draw(self, context):
        layout = self.layout
        obj = context.object
        layout.operator(QSS_OT_export_bsp.bl_idname, icon='EXPORT')
        layout.label(text="Classic BSP29 export; original unrelated lumps preserved.", icon='INFO')
        layout.label(text="Static lightmap export flattens active styles into style 0.")
        layout.label(text="External .lit output targets QLIT-compatible ports.")
        if obj.get('qss_lightmap_note'):
            row = layout.row()
            row.alert = True
            row.label(text=str(obj.get('qss_lightmap_note')), icon='ERROR')


CLASSES = (
    QSS_OT_import_bsp,
    QSS_OT_detach_faces,
    QSS_OT_activate_paint,
    QSS_OT_activate_lightmap_paint,
    QSS_OT_frame_selection,
    QSS_OT_isolate_faces,
    QSS_OT_reveal_faces,
    QSS_OT_optimize_clipping,
    QSS_OT_player_start,
    QSS_OT_fps_walk,
    QSS_OT_hold_mmb_fps,
    QSS_OT_preview_imported_lights,
    QSS_OT_preview_source_lightmaps,
    QSS_OT_preview_bsp_lightmaps,
    QSS_OT_quake_direct_bake,
    QSS_OT_bake_scene_lights,
    QSS_OT_undo_last_bake,
    QSS_OT_restore_original_lightmap,
    QSS_OT_refresh_lightmap_preview,
    QSS_OT_apply_light_energy_scale,
    QSS_OT_calibrate_lights_to_source,
    QSS_OT_write_diagnostics,
    QSS_OT_run_blender_selftest,
    QSS_OT_export_bsp,
    QSS_PT_main,
    QSS_PT_project,
    QSS_PT_navigation,
    QSS_PT_texture,
    QSS_PT_lighting,
    QSS_PT_light_preview,
    QSS_PT_imported_lights,
    QSS_PT_quake_bake,
    QSS_PT_cycles_bake,
    QSS_PT_diagnostics,
    QSS_PT_export,
)


def _remove_qss_keymaps():
    """Remove every registered MMB navigation keymap item owned by QSS.

    Tracking lists are lost when Blender reloads/reinstalls an add-on module,
    so also scan Blender's add-on keyconfig by operator idname.
    """
    global _addon_keymaps
    for km, kmi in list(_addon_keymaps):
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()

    wm = getattr(bpy.context, 'window_manager', None)
    keyconfigs = getattr(wm, 'keyconfigs', None) if wm else None
    keyconfig = getattr(keyconfigs, 'addon', None) if keyconfigs else None
    if keyconfig is not None:
        for km in list(keyconfig.keymaps):
            for kmi in list(km.keymap_items):
                if getattr(kmi, 'idname', '') == 'qss.hold_mmb_fps':
                    try:
                        km.keymap_items.remove(kmi)
                    except Exception:
                        pass


def _remove_scene_properties():
    """Remove QSS Scene properties, including properties from an older module."""
    for name in (
        'qss_game_dir', 'qss_quake_unit_scale', 'qss_nav_speed_quake',
        'qss_nav_fast_factor', 'qss_light_energy_scale',
        'qss_bake_output_scale', 'qss_bake_bounces', 'qss_bake_match_source', 'qss_mmb_fps_walk',
        'qss_quake_bake_shadows', 'qss_quake_bake_gate',
    ):
        if hasattr(bpy.types.Scene, name):
            try:
                delattr(bpy.types.Scene, name)
            except Exception:
                pass


def _unregister_qss_classes():
    """Unregister stale QSS classes by their Blender RNA names.

    Looking them up on bpy.types is important during upgrades: the class object
    in this newly imported Python module is not the same object as the class
    that Blender registered from the previously enabled module.
    """
    for cls in reversed(CLASSES):
        old_cls = getattr(bpy.types, cls.__name__, None)
        if old_cls is None:
            continue
        try:
            bpy.utils.unregister_class(old_cls)
        except (RuntimeError, TypeError, ValueError):
            # It may already have been unregistered by Blender or another
            # cleanup pass. Do not prevent the remaining classes being removed.
            pass


def _cleanup_previous_registration():
    _remove_qss_keymaps()
    _remove_scene_properties()
    _unregister_qss_classes()


def _update_mmb_walk_keymap():
    """Install optional hold-MMB FPS navigation without changing defaults."""
    global _addon_keymaps
    _remove_qss_keymaps()
    scene = getattr(bpy.context, 'scene', None)
    if scene is None or not getattr(scene, 'qss_mmb_fps_walk', False):
        return
    wm = getattr(bpy.context, 'window_manager', None)
    keyconfigs = getattr(wm, 'keyconfigs', None) if wm else None
    keyconfig = getattr(keyconfigs, 'addon', None) if keyconfigs else None
    if keyconfig is None:
        return
    km = keyconfig.keymaps.new(name='3D View', space_type='VIEW_3D')
    try:
        kmi = km.keymap_items.new(QSS_OT_hold_mmb_fps.bl_idname, 'MIDDLEMOUSE', 'PRESS', head=True)
    except TypeError:
        kmi = km.keymap_items.new(QSS_OT_hold_mmb_fps.bl_idname, 'MIDDLEMOUSE', 'PRESS')
    _addon_keymaps.append((km, kmi))


def _on_mmb_fps_walk_changed(self, context):
    _update_mmb_walk_keymap()



def register():
    """Register QSS safely, including upgrades from an already-enabled build."""
    _cleanup_previous_registration()
    registered = []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)

        bpy.types.Scene.qss_game_dir = StringProperty(
            name="Quake game directory",
            description="Game root or id1 folder; used to locate gfx/palette.lmp or read it from a PAK",
            subtype='DIR_PATH',
            default="",
        )
        bpy.types.Scene.qss_quake_unit_scale = FloatProperty(
            name="Quake unit scale", description="Blender metres per Quake unit", default=DEFAULT_QUAKE_UNIT_SCALE,
            min=0.0001, max=10.0, precision=5
        )
        bpy.types.Scene.qss_nav_speed_quake = FloatProperty(
            name="Navigation speed", description="First-person movement speed in Quake units per second",
            default=640.0, min=1.0, max=4000.0
        )
        bpy.types.Scene.qss_nav_fast_factor = FloatProperty(
            name="Fast movement multiplier", default=4.0, min=1.0, max=10.0
        )
        bpy.types.Scene.qss_light_energy_scale = FloatProperty(
            name="Quake light energy scale",
            description="0 = black; 1 = source-average after using Calibrate Live Scale to Source; higher values brighten live lights",
            default=1.0, min=0.0, max=1000000.0, precision=4,
            update=_on_light_energy_scale_changed,
        )
        bpy.types.Scene.qss_bake_output_scale = FloatProperty(
            name='Bake brightness', description='Linear post-bake multiplier for the generated lightmap; separate from actual lamp energy',
            default=1.0, min=0.1, max=64.0, precision=3
        )
        bpy.types.Scene.qss_bake_bounces = IntProperty(
            name='Cycles diffuse bounces', description='Indirect-light bounces for the artist bake; 0 is direct only',
            default=2, min=0, max=12
        )
        bpy.types.Scene.qss_bake_match_source = BoolProperty(
            name='Match source lightmap brightness',
            description='Automatically calibrate Quake lamp energy so the baked mean luxel brightness matches the imported source lightmap',
            default=True
        )
        bpy.types.Scene.qss_quake_bake_shadows = BoolProperty(
            name='Ray-traced visibility',
            description='Trace each BSP luxel towards its light; disable only for an unoccluded lighting diagnostic',
            default=True
        )
        bpy.types.Scene.qss_quake_bake_gate = FloatProperty(
            name='Light contribution gate',
            description='Ignore per-sample light contributions below this ericw-style intensity threshold',
            default=0.001, min=0.0, max=10.0, precision=5
        )
        bpy.types.Scene.qss_mmb_fps_walk = BoolProperty(
            name='MMB starts FPS / WASD',
            description='Hold middle mouse to look and use WASD; movement stops and Blender navigation resumes immediately on release',
            default=False,
            update=_on_mmb_fps_walk_changed,
        )
        _update_mmb_walk_keymap()
    except Exception:
        # Blender can leave a partially registered add-on behind when register()
        # raises. Roll back everything created in this attempt before propagating.
        _cleanup_previous_registration()
        raise


def unregister():
    """Idempotent cleanup for disable, reload, and reinstall operations."""
    _cleanup_previous_registration()
