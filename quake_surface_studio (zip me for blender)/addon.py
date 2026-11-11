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
import hashlib
import struct
import sys
import tempfile
import time
import traceback

import bpy
from bpy.props import StringProperty, FloatProperty, FloatVectorProperty, BoolProperty, IntProperty, EnumProperty
from bpy.types import Operator, Panel, Menu
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import bsp, color, lighting as lighting_utils, material_utils, lightmap_export as lightmap_export_utils
from . import export_validation, quake_paths, external_tools, texture_export, navigation_utils, toolbar_utils, visibility_utils, viewport_utils, palette_utils


ADDON_VERSION = (0, 20, 8)

# Quake mapping convention: one map unit is conventionally treated as one inch.
# Blender scene units are metres, so this keeps movement and light distances intuitive.
DEFAULT_QUAKE_UNIT_SCALE = 0.0254

# Track keymap items created by this add-on. This must exist before register().
_addon_keymaps = []
_qss_focus_clip_sessions = {}
_qss_focus_cycle_state = {}
_qss_focus_transition_sessions = {}
_qss_camera_transition_sessions = {}
_qss_edit_overlay_sessions = {}




def _report(op, level, message):
    op.report({level}, message)


def _qss_log(level, event, message):
    """Write a consistently tagged Slipgate message to Blender's console."""
    stamp = time.strftime('%H:%M:%S')
    print(f"[{stamp}] [Slipgate] [{str(level).upper()}] [{event}] {message}", flush=True)


# QSS per-user installation settings are kept outside .blend files in config.json.
_qss_config_update_depth = False
_qss_game_map_entries = []


def _qss_config_path():
    directory = bpy.utils.user_resource('CONFIG', path='qss', create=True)
    return os.path.join(directory, 'config.json')

def _qss_abspath(path):
    """Resolve a non-empty Blender path without turning an empty path into the blend directory."""
    return bpy.path.abspath(path) if path else ''


def _qss_map_artifact_dir(obj, create=False):
    """Return the per-map generated-artifact directory without creating it on import."""
    if not _qss_is_map_object(obj):
        raise bsp.BSPError("Select an imported Slipgate map before generating map artifacts.")
    source = _qss_abspath(obj.get("qss_source_path", ""))
    if not source:
        raise bsp.BSPError("The active map has no source BSP path.")
    map_directory = os.path.dirname(os.path.abspath(source))
    if not os.path.isdir(map_directory):
        raise bsp.BSPError(f"The source map directory does not exist: {map_directory}")
    stem = os.path.splitext(os.path.basename(source))[0] or "Map"
    clean_stem = bpy.path.clean_name(stem) or "Map"
    folder = os.path.join(map_directory, "##slipgate", clean_stem)
    if create:
        os.makedirs(folder, exist_ok=True)
        if not os.path.isdir(folder):
            raise OSError(f"Generated-artifact path is not a directory: {folder}")
        obj["qss_slipgate_folder"] = folder
        _qss_log("INFO", "artifacts", f"Map artifact directory ready: {folder}")
    return folder


def _qss_map_artifact_path(obj, filename, create=True):
    folder = _qss_map_artifact_dir(obj, create=create)
    return os.path.join(folder, os.path.basename(str(filename)))



def _qss_load_config():
    return quake_paths.load_config(_qss_config_path())


# Map collections are the project boundary: mesh, entity lights and spawn
# markers for one BSP stay together and can be isolated as a unit.
_qss_map_enum_cache = []
_qss_map_switch_depth = False
_QSS_CONFIG_DEFAULTS = {
    "import_behavior": "ASK",
    "export_mode": "AUTO",
    "prefer_enhanced_last_export": True,
    "import_lightmap_resolution": "1",
    "rebake_behavior": "ASK",
    "lighting_mode_storage": "PER_MAP",
    "global_lighting_mode": "source",
    "viewport_fov_degrees": 90.0,
}


def _qss_config_settings():
    values = dict(_QSS_CONFIG_DEFAULTS)
    values.update(_qss_load_config())
    return values


def _qss_last_export_path(obj):
    if not _qss_is_map_object(obj):
        return ""
    if obj.get("qss_last_export_mode") == "BOTH":
        settings = _qss_config_settings()
        preferred = "qss_last_export_enhanced_path" if settings.get("prefer_enhanced_last_export", True) else "qss_last_export_classic_path"
        alternate = "qss_last_export_classic_path" if preferred.endswith("enhanced_path") else "qss_last_export_enhanced_path"
        for key in (preferred, alternate, "qss_last_export_path"):
            candidate = obj.get(key, "")
            if candidate and os.path.isfile(candidate):
                return candidate
        return ""
    candidate = obj.get("qss_last_export_path", "")
    return candidate if candidate and os.path.isfile(candidate) else ""


def _qss_scene_map_collections(scene):
    found = []

    def visit(collection):
        for child in collection.children:
            if bool(child.get("qss_map_collection", False)):
                found.append(child)
            visit(child)

    if scene is not None:
        visit(scene.collection)
    return sorted(found, key=lambda item: item.name.casefold())


def _qss_collection_objects(collection):
    objects = set()

    def visit(item):
        objects.update(item.objects)
        for child in item.children:
            visit(child)

    if collection is not None:
        visit(collection)
    return objects


def _qss_map_collection_items(self, context):
    global _qss_map_enum_cache
    scene = getattr(context, "scene", None) if context else None
    collections = _qss_scene_map_collections(scene)
    _qss_map_enum_cache = [
        (item.name,
         os.path.basename(str(item.get("qss_source_path", item.name)))[:63],
         str(item.get("qss_source_path", item.name))[:255],
         "OUTLINER_COLLECTION", index)
        for index, item in enumerate(collections)
    ]
    if not _qss_map_enum_cache:
        _qss_map_enum_cache = [
            ("__QSS_NO_MAP__", "No imported maps",
             "Import a BSP to create a map collection", "INFO", 0)
        ]
    return _qss_map_enum_cache


def _qss_make_map_collection(context, obj, source_path):
    stem = os.path.splitext(os.path.basename(source_path))[0] or "Map"
    collection = bpy.data.collections.new(f"QSS_Map_{stem}")
    collection["qss_map_collection"] = True
    collection["qss_source_path"] = os.path.abspath(source_path)
    context.scene.collection.children.link(collection)
    for old_collection in list(obj.users_collection):
        old_collection.objects.unlink(obj)
    collection.objects.link(obj)
    obj["qss_map_collection"] = collection.name
    obj["qss_painted_textures_enabled"] = True
    obj["qss_painted_lightmaps_enabled"] = True
    obj["qss_base_textures_enabled"] = True
    obj["qss_source_lightmaps_enabled"] = True
    obj["qss_preview_mode"] = "source"
    return collection


def _qss_migrate_legacy_map_collections(scene):
    """Wrap pre-v0.18 imported BSP objects and entity collections in map roots."""
    if scene is None:
        return
    for obj in list(scene.objects):
        if not _qss_is_map_object(obj) or obj.get("qss_map_collection", ""):
            continue
        source_path = obj.get("qss_source_path", "") or obj.name
        stem = os.path.splitext(os.path.basename(source_path))[0] or obj.name
        root = bpy.data.collections.new(f"QSS_Map_{stem}")
        root["qss_map_collection"] = True
        root["qss_source_path"] = os.path.abspath(source_path) if os.path.isabs(source_path) else str(source_path)
        scene.collection.children.link(root)
        for parent in list(obj.users_collection):
            parent.objects.unlink(obj)
        root.objects.link(obj)
        obj["qss_map_collection"] = root.name
        if "qss_preview_mode" not in obj:
            obj["qss_preview_mode"] = "source"
        if "qss_painted_textures_enabled" not in obj:
            obj["qss_painted_textures_enabled"] = True
        if "qss_painted_lightmaps_enabled" not in obj:
            obj["qss_painted_lightmaps_enabled"] = True
        if "qss_base_textures_enabled" not in obj:
            obj["qss_base_textures_enabled"] = True
        if "qss_source_lightmaps_enabled" not in obj:
            obj["qss_source_lightmaps_enabled"] = True
        entity_name = obj.get("qss_light_collection", "")
        entity_collection = bpy.data.collections.get(entity_name) if entity_name else None
        if entity_collection is not None and entity_collection != root:
            for parent in list(bpy.data.collections):
                try:
                    if entity_collection in parent.children:
                        parent.children.unlink(entity_collection)
                except Exception:
                    pass
            try:
                if entity_collection in scene.collection.children:
                    scene.collection.children.unlink(entity_collection)
            except Exception:
                pass
            root.children.link(entity_collection)


def _qss_remove_map_collection(scene, name):
    collection = bpy.data.collections.get(name) if name else None
    if collection is None or not collection.get("qss_map_collection", False):
        return False

    # Track datablocks owned/referenced by this map before removing its objects.
    # Shared images/materials stay alive when another scene object still uses them.
    materials = {}
    images = {}
    for obj in _qss_collection_objects(collection):
        if getattr(obj, "type", "") == "MESH" and getattr(obj, "data", None) is not None:
            for material in obj.data.materials:
                if material is None:
                    continue
                try:
                    materials[int(material.as_pointer())] = material
                except Exception:
                    materials[id(material)] = material
                if material.use_nodes and material.node_tree is not None:
                    for node in material.node_tree.nodes:
                        image = getattr(node, "image", None)
                        if image is not None:
                            try:
                                images[int(image.as_pointer())] = image
                            except Exception:
                                images[id(image)] = image
        # QSS map objects also keep lightmap image datablocks by name.
        for key in (
            "qss_lightmap_image_name",
            "qss_original_lightmap_backup",
            "qss_painted_original_lightmap",
            "qss_painted_baked_lightmap",
        ):
            image_name = str(obj.get(key, "") or "")
            image = bpy.data.images.get(image_name) if image_name else None
            if image is not None:
                try:
                    images[int(image.as_pointer())] = image
                except Exception:
                    images[id(image)] = image

    def remove_tree(item):
        for child in list(item.children):
            remove_tree(child)
        for obj in list(item.objects):
            data = getattr(obj, "data", None)
            data_collection = (
                bpy.data.meshes if obj.type == "MESH" else
                bpy.data.lights if obj.type == "LIGHT" else None
            )
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
            if data_collection is not None and data is not None and getattr(data, "users", 1) == 0:
                try:
                    data_collection.remove(data)
                except Exception:
                    pass
        for parent in bpy.data.collections:
            try:
                if item in parent.children:
                    parent.children.unlink(item)
            except Exception:
                pass
        try:
            bpy.data.collections.remove(item)
        except Exception:
            pass

    remove_tree(collection)

    # Remove only datablocks that became truly orphaned. Fake-user and shared
    # assets are deliberately retained, so closing one map cannot delete
    # textures or materials still used by unrelated scene content.
    for material in materials.values():
        try:
            if material.users == 0 and not material.use_fake_user:
                bpy.data.materials.remove(material)
        except (ReferenceError, RuntimeError):
            pass
    for image in images.values():
        try:
            if image.users == 0 and not image.use_fake_user:
                bpy.data.images.remove(image, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    return True


def _qss_active_map_objects(scene, obj):
    name = obj.get("qss_map_collection", "") if obj else ""
    collection = bpy.data.collections.get(name) if name else None
    if collection is not None:
        return _qss_collection_objects(collection)
    return set(scene.objects) if scene is not None else set()


def _qss_has_baked_lightmap(obj):
    return bool(
        obj and (
            obj.get("qss_lightmap_source") in {
                "quake_direct_cpu_bake", "cycles_bake_from_quake_entities"
            }
            or obj.get("qss_lightmap_gradient_baked", False)
        )
    )


def _qss_lightmap_preview_image(obj, mode, for_paint=False):
    if mode == "source":
        base_name, painted_key = obj.get("qss_original_lightmap_backup", ""), "qss_painted_original_lightmap"
    elif mode == "baked":
        base_name, painted_key = obj.get("qss_lightmap_image_name", ""), "qss_painted_baked_lightmap"
    else:
        raise bsp.BSPError("Lightmap painting is available only in Original or Baked mode.")
    base = bpy.data.images.get(base_name) if base_name else None
    if base is None:
        raise bsp.BSPError("The active map's lightmap image is missing.")
    painted_name = obj.get(painted_key, "")
    painted = bpy.data.images.get(painted_name) if painted_name else None
    if for_paint and painted is None:
        painted = base.copy()
        painted.name = f"{obj.name}_{'Original' if mode == 'source' else 'Baked'}_PaintedLightmap"
        painted.use_fake_user = True
        try:
            painted.pack()
        except RuntimeError:
            pass
        obj[painted_key] = painted.name
    if for_paint:
        obj["qss_painted_lightmaps_enabled"] = True
    return painted if bool(obj.get("qss_painted_lightmaps_enabled", True)) and painted else base


def _qss_has_painted_texture_faces(obj):
    mesh = getattr(obj, "data", None)
    marker = mesh.attributes.get("qss_painted_face") if mesh is not None else None
    return bool(marker and marker.domain == "FACE" and any(item.value for item in marker.data))


def _qss_activate_map_collection(scene, name, context=None):
    global _qss_map_switch_depth
    if scene is None:
        return None
    if context is not None and getattr(context, "mode", "OBJECT") != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:
            print(f"QSS: could not leave the current mode before switching maps: {exc}")
            return None
    collection = next((item for item in _qss_scene_map_collections(scene) if item.name == name), None)
    if collection is None:
        return None
    view_layer = getattr(context, "view_layer", None) if context else None
    old_active = view_layer.objects.active if view_layer is not None else None
    if _qss_is_map_object(old_active) and old_active.get("qss_preview_mode", "source") in {"realtime", "cycles"}:
        try:
            _set_lighting_preview(context, old_active, "source")
        except Exception as exc:
            print(f"QSS: could not restore previous map lighting: {exc}")

    active_objects = _qss_collection_objects(collection)
    for obj in scene.objects:
        try:
            if "qss_isolation_original_hide" not in obj:
                obj["qss_isolation_original_hide"] = bool(obj.hide_get())
                obj["qss_isolation_original_hide_render"] = bool(obj.hide_render)
            should_hide = obj not in active_objects or bool(obj.get("qss_isolation_original_hide", False))
            obj.hide_set(should_hide)
            obj.hide_render = obj not in active_objects or bool(obj.get("qss_isolation_original_hide_render", False))
        except (AttributeError, RuntimeError, ReferenceError):
            pass

    map_object = next((obj for obj in active_objects if _qss_is_map_object(obj)), None)
    _qss_map_switch_depth = True
    try:
        if hasattr(scene, "qss_active_map_collection"):
            scene.qss_active_map_collection = collection.name
    finally:
        _qss_map_switch_depth = False

    if map_object is not None:
        map_game_dir = _qss_abspath(map_object.get("qss_game_dir", "") or "")
        if map_game_dir and os.path.isdir(map_game_dir):
            root_path = _qss_abspath(getattr(scene, "qss_quake_root", "") or "")
            game_id = quake_paths.game_id_for_path(root_path, map_game_dir)
            global _qss_config_update_depth
            _qss_config_update_depth = True
            try:
                if game_id:
                    scene.qss_game_folder = game_id
                scene.qss_game_dir = map_game_dir
            finally:
                _qss_config_update_depth = False
            if game_id:
                try:
                    _qss_save_config(scene)
                except Exception as exc:
                    print(f"QSS: could not persist active map game/mod: {exc}")

    if map_object is not None and view_layer is not None:
        try:
            for selected in list(context.selected_objects):
                selected.select_set(False)
            map_object.select_set(True)
            view_layer.objects.active = map_object
        except (RuntimeError, ReferenceError):
            pass

    if map_object is not None and context is not None:
        try:
            if str(getattr(scene, "qss_paint_color_picker", "STANDARD")) == "QUAKE":
                _qss_assign_quake_palette(context, map_object)
        except Exception as exc:
            print(f"QSS: could not update the brush palette for {map_object.name}: {exc}")
        try:
            settings = _qss_config_settings()
            if str(settings.get("lighting_mode_storage", "PER_MAP")).upper() == "GLOBAL":
                preview_mode = str(settings.get("global_lighting_mode", "source"))
                if preview_mode not in {"source", "realtime", "cycles", "baked"}:
                    preview_mode = "source"
                map_object["qss_preview_mode"] = preview_mode
            else:
                preview_mode = map_object.get("qss_preview_mode", "source")
            if preview_mode not in {"source", "realtime", "cycles", "baked"}:
                preview_mode = "source"
            if preview_mode == "baked" and not _qss_has_baked_lightmap(map_object):
                preview_mode = "source"
                map_object["qss_preview_mode"] = "source"
                if str(settings.get("lighting_mode_storage", "PER_MAP")).upper() == "GLOBAL":
                    settings["global_lighting_mode"] = "source"
                    try:
                        quake_paths.save_config(settings, _qss_config_path())
                    except Exception:
                        pass
            _set_lighting_preview(context, map_object, preview_mode)
        except Exception as exc:
            print(f"QSS: could not restore lighting for {map_object.name}: {exc}")
    return map_object


def _qss_on_active_map_changed(self, context):
    if _qss_map_switch_depth:
        return
    name = getattr(self, "qss_active_map_collection", "")
    if name and name != "__QSS_NO_MAP__":
        _qss_activate_map_collection(context.scene, name, context)


def _qss_save_config(scene=None, last_source_bsp=None):
    config = _qss_load_config()
    if scene is not None:
        root = quake_paths.normalize_quake_root(
            _qss_abspath(getattr(scene, 'qss_quake_root', '') or '')
        )
        game_dir = _qss_abspath(getattr(scene, 'qss_game_dir', '') or '')
        config['quake_root'] = root
        config['active_game_dir'] = game_dir
        config['active_game_id'] = getattr(scene, 'qss_game_folder', '') or ''
    if last_source_bsp:
        config['last_source_bsp'] = os.path.abspath(bpy.path.abspath(last_source_bsp))
    quake_paths.save_config(config, _qss_config_path())


def _qss_game_folder_items(self, context):
    # Blender may evaluate dynamic EnumProperty items during RNA registration,
    # when context and its Scene are not available yet. Fall back to the
    # persisted installation root so the configured default is a valid item.
    scene = getattr(context, 'scene', None) if context else None
    root = _qss_abspath(getattr(scene, 'qss_quake_root', '') or '') if scene else ''
    if not root:
        root = quake_paths.normalize_quake_root(_qss_load_config().get('quake_root', ''))
    items = quake_paths.discover_game_dirs(root)
    if not items:
        return [('NONE', 'No game folders found', 'Set the Quake installation folder first', 'ERROR', 0)]
    return [
        (item['id'], item['label'], item['path'], 'FILE_FOLDER', index)
        for index, item in enumerate(items)
    ]


def _on_quake_root_changed(self, context):
    global _qss_config_update_depth
    if _qss_config_update_depth:
        return
    scene = context.scene
    _qss_config_update_depth = True
    try:
        root = quake_paths.normalize_quake_root(_qss_abspath(scene.qss_quake_root or ''))
        if root != _qss_abspath(scene.qss_quake_root or ''):
            scene.qss_quake_root = root
        folders = quake_paths.discover_game_dirs(root)
        if folders:
            current = getattr(scene, 'qss_game_folder', '')
            ids = [item['id'] for item in folders]
            if current not in ids:
                current = next((item['id'] for item in folders if item['id'] == 'id1'), folders[0]['id'])
            scene.qss_game_folder = current
            scene.qss_game_dir = quake_paths.resolve_game_dir(root, current)
        else:
            scene.qss_game_folder = 'NONE'
            scene.qss_game_dir = root
        _qss_save_config(scene)
    except Exception as exc:
        print(f"QSS: could not save Quake installation settings: {exc}")
    finally:
        _qss_config_update_depth = False


def _on_game_folder_changed(self, context):
    global _qss_config_update_depth
    if _qss_config_update_depth:
        return
    scene = context.scene
    root = _qss_abspath(scene.qss_quake_root or '')
    game_dir = quake_paths.resolve_game_dir(root, scene.qss_game_folder)
    if game_dir:
        scene.qss_game_dir = game_dir
    _qss_save_config(scene)


def _on_external_tool_path_changed(self, context):
    """Persist external executable/tool paths immediately when edited in the UI."""
    scene = getattr(context, 'scene', None) if context else None
    if scene is None:
        return
    config = _qss_load_config()
    config['ericw_tools_dir'] = _qss_abspath(
        getattr(scene, 'qss_ericw_tools_dir', '') or ''
    )
    config['ironwail_executable'] = _qss_abspath(
        getattr(scene, 'qss_ironwail_executable', '') or ''
    )
    config['ironwail_demo'] = _qss_abspath(
        getattr(scene, 'qss_ironwail_demo', '') or ''
    )
    quake_paths.save_config(config, _qss_config_path())


def _qss_write_text_report(name, contents):
    report = bpy.data.texts.get(name)
    if report is None:
        report = bpy.data.texts.new(name)
    else:
        report.clear()
    report.write(contents)
    return report


def _qss_format_export_report(report):
    lines = [
        "PASS: QSS BSP export integrity checks",
        f"Faces: {report['faces']}",
        f"Textures: {report['textures']}",
        f"Texinfo records: {report['texinfos']}",
        f"Classic lighting: {report['classic_lighting_bytes']} bytes "
        f"({report['classic_required_samples']} required samples)",
        "Enhanced BSPX lighting: "
        + (f"{report['enhanced_lighting_samples']} RGB samples"
           if report['enhanced_lighting_samples'] is not None else "not present"),
        "BSPX lumps: " + (", ".join(report['bspx_lumps']) or "(none)"),
        "External .lit sidecar: " + ("validated" if report['external_lit'] else "not present"),
    ]
    return "\n".join(lines) + "\n"


def _qss_game_map_enum_items(self, context):
    global _qss_game_map_entries
    scene = getattr(context, 'scene', None) if context else None
    game_dir = _qss_abspath(getattr(scene, 'qss_game_dir', '') or '') if scene else ''
    try:
        entries = quake_paths.discover_maps(game_dir)
    except Exception:
        entries = []
    _qss_game_map_entries = entries
    if not entries:
        return [('__NO_MAPS__', 'No BSP maps found', 'This game folder has no loose or PAK maps', 'ERROR', 0)]
    return [
        (
            entry['id'],
            os.path.basename(entry['path'])[:63],
            f"{entry['path']} · {entry['source_label']}"[:255],
            'FILE',
            index,
        )
        for index, entry in enumerate(entries)
    ]


def _qss_choose_initial_game_settings(config):
    root = quake_paths.normalize_quake_root(config.get('quake_root', ''))
    folders = quake_paths.discover_game_dirs(root)
    saved_dir = config.get('active_game_dir', '')
    active_id = quake_paths.game_id_for_path(root, saved_dir)
    if not active_id:
        active_id = next((item['id'] for item in folders if item['id'] == 'id1'), folders[0]['id'] if folders else 'NONE')
    active_dir = quake_paths.resolve_game_dir(root, active_id) if folders else root
    return root, active_id, active_dir


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



def _set_principled_roughness(mat, value=1.0):
    """Set every Principled BSDF in a QSS Quake material to the requested roughness."""
    if mat is None:
        return
    mat.use_nodes = True
    for node in mat.node_tree.nodes:
        if node.type != 'BSDF_PRINCIPLED':
            continue
        socket = node.inputs.get('Roughness')
        if socket is not None:
            socket.default_value = float(value)


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
    _set_principled_roughness(mat, 1.0)



def _set_texture_paint_target(context, obj, image, uv_name, material=None):
    """Bind Texture Paint to either one material slot or a shared image atlas.

    Face-local albedo images must use Material mode. Single Image mode applies
    a canvas override across the whole object, so unrelated BSP faces whose UVs
    overlap the face-local 0..1 island can display/paint the wrong image.
    Shared lightmap atlases remain in Single Image mode because all face
    materials intentionally reference the same atlas and the lightmap UVs are
    packed into non-overlapping islands.
    """
    if image is None:
        raise bsp.BSPError("The requested QSS paint image is missing.")
    uv_layers = obj.data.uv_layers
    uv_layer = uv_layers.get(uv_name)
    if uv_layer is None:
        raise bsp.BSPError(f"Required paint UV map '{uv_name}' is missing.")
    try:
        uv_layer.active_render = True
        uv_layers.active = uv_layer
    except (AttributeError, IndexError, RuntimeError, ReferenceError) as exc:
        raise bsp.BSPError(f"Could not activate paint UV map '{uv_name}': {exc}") from exc

    try:
        tool_settings = context.scene.tool_settings
        paint_mode = tool_settings.paint_mode
        if paint_mode is None:
            raise RuntimeError("Blender has no active PaintModeSettings.")
        image_paint = tool_settings.image_paint
        image_paint.interpolation = 'CLOSEST'

        # BSP face winding can differ from Blender's paint-projection culling
        # convention. Keep occlusion, but never cull backfaces while painting.
        material_utils.configure_texture_paint_visibility(image_paint)

        if material is not None:
            if obj.active_material != material:
                raise RuntimeError(
                    f"Material '{material.name}' is not the object's active material."
                )
            if not material.use_nodes or material.node_tree is None:
                raise RuntimeError(f"Material '{material.name}' has no node tree.")
            nodes = material.node_tree.nodes
            image_nodes = [node for node in nodes if node.type == 'TEX_IMAGE']
            target_node = next(
                (node for node in image_nodes if node.image == image), None
            )
            if target_node is None:
                raise RuntimeError(
                    f"Image '{image.name}' is not an Image Texture slot in '{material.name}'."
                )

            # Blender's paint-slot cache is not the same API collection as
            # node_tree.nodes. Select the actual target node and let Blender
            # rebuild its slot cache when Texture Paint mode is entered.
            # A node-list index is not a safe paint_active_slot index.
            for node in nodes:
                node.select = False
            target_node.select = True
            nodes.active = target_node
            try:
                material.update_tag()
                context.view_layer.update()
            except Exception:
                pass

            # Material mode takes its canvas from the hit face's material slot.
            # Never leave an image-wide canvas override set while painting
            # per-material face textures.
            paint_mode.canvas_source = 'MATERIAL'
            paint_mode.canvas_image = None
            image_paint.mode = 'MATERIAL'
            image_paint.canvas = None
            if (
                paint_mode.canvas_source != 'MATERIAL'
                or paint_mode.canvas_image is not None
                or image_paint.mode != 'MATERIAL'
                or image_paint.canvas is not None
            ):
                raise RuntimeError(
                    "Blender did not retain Material paint mode without a global canvas."
                )
        else:
            # The BSP lightmap is one shared atlas referenced by every face
            # material; it intentionally uses the object-wide image canvas.
            paint_mode.canvas_source = 'IMAGE'
            paint_mode.canvas_image = image
            image_paint.mode = 'IMAGE'
            image_paint.canvas = image
            if (
                paint_mode.canvas_source != 'IMAGE'
                or paint_mode.canvas_image != image
                or image_paint.mode != 'IMAGE'
                or image_paint.canvas != image
            ):
                raise RuntimeError(
                    "Blender did not retain the requested Single Image canvas."
                )
    except Exception as exc:
        raise bsp.BSPError(
            f"Could not set '{image.name}' as the Texture Paint target: {exc}"
        ) from exc


def _next_pow2_clamped(value, minimum=16, maximum=512):
    """Choose a supported Quake miptex dimension for a face-local texture."""
    value = max(1, int(math.ceil(float(value))))
    dimension = 1 << (value - 1).bit_length()
    return max(minimum, min(maximum, dimension))


def _next_quake_texture_dimension(value, maximum=512):
    """Round a face-local texture dimension up to the next supported power of two."""
    return texture_export.quake_texture_dimension(value, maximum)


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

    # Slipgate's indexed miptex exporter requires power-of-two dimensions.
    # Pad each face-local image upward without stretching the face UV
    # footprint; only spans beyond 512 px are resampled.
    width_out = _next_quake_texture_dimension(span_s)
    height_out = _next_quake_texture_dimension(span_t)
    source_pixels = array.array('f', [0.0]) * (width_src * height_src * 4)
    source_image.update()
    source_image.pixels.foreach_get(source_pixels)
    output_pixels = array.array('f')
    scale_s = texture_export.face_local_projection_scale(span_s, width_out)
    scale_t = texture_export.face_local_projection_scale(span_t, height_out)

    # Blender image pixels are bottom-up. Keep the original texel pitch when
    # the face-local image is padded to a power of two. Only spans beyond
    # 512 px are resampled to fit the classic miptexture limit.
    for y in range(height_out):
        t = min_t + (height_out - (y + 0.5)) / scale_t
        v_src = (1.0 - (t / height_src)) % 1.0
        sy = min(height_src - 1, int(v_src * height_src))
        for x in range(width_out):
            s = min_s + (x + 0.5) / scale_s
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
        ((s - min_s) * scale_s / width_out,
         1.0 - ((t - min_t) * scale_t / height_out))
        for s, t in zip(s_values, t_values)
    ]
    return image, normalized_uvs, (min_s, min_t, span_s, span_t), (width_out, height_out)


def _face_local_texinfo_projection(source_texinfo, bounds, output_size):
    """Return a texinfo projection matching the padded face-local texture."""
    return texture_export.face_local_texinfo_projection(source_texinfo, bounds, output_size)


def _qss_create_detached_face_atlas(plans, atlas_size=512):
    """Pack multiple detached face images into one shared paint canvas.

    Each face keeps its own material and texinfo projection, but all those
    materials reference the same image so Blender can paint the whole selected
    group in one Material paint slot.
    """
    if len(plans) < 2:
        return None
    source_images = [plan["image"] for plan in plans]
    layout = texture_export.pack_face_rectangles(
        [tuple(int(value) for value in image.size) for image in source_images],
        atlas_size=atlas_size, padding=2,
    )
    atlas = bpy.data.images.new(
        name="QSS_Detached_Face_Atlas", width=atlas_size, height=atlas_size,
        alpha=True, float_buffer=True,
    )
    try:
        try:
            atlas.colorspace_settings.name = source_images[0].colorspace_settings.name
        except Exception:
            pass
        atlas_pixels = array.array("f", [0.0]) * (atlas_size * atlas_size * 4)
        padding = int(layout["padding"])
        for plan, source, tile in zip(plans, source_images, layout["tiles"]):
            width, height = int(source.size[0]), int(source.size[1])
            source_pixels = array.array("f", [0.0]) * (width * height * 4)
            source.update()
            source.pixels.foreach_get(source_pixels)
            target_w, target_h = int(tile["width"]), int(tile["height"])
            resized = texture_export.resample_rgba_nearest(
                source_pixels, width, height, target_w, target_h
            )
            # Duplicate edge texels into a two-pixel border to prevent linear
            # filtering/mipmap bleed between adjacent detached-face tiles.
            for y in range(-padding, target_h + padding):
                source_y = min(target_h - 1, max(0, y))
                dest_y = int(tile["y"]) + y
                for x in range(-padding, target_w + padding):
                    source_x = min(target_w - 1, max(0, x))
                    dest_x = int(tile["x"]) + x
                    src_offset = (source_y * target_w + source_x) * 4
                    dst_offset = (dest_y * atlas_size + dest_x) * 4
                    atlas_pixels[dst_offset] = resized[src_offset]
                    atlas_pixels[dst_offset + 1] = resized[src_offset + 1]
                    atlas_pixels[dst_offset + 2] = resized[src_offset + 2]
                    atlas_pixels[dst_offset + 3] = resized[src_offset + 3]
            plan["uvs"] = texture_export.remap_uvs_to_atlas(
                plan["uvs"], tile, atlas_size
            )
            plan["projection"] = texture_export.projection_for_atlas_tile(
                plan["projection"], (width, height), tile, atlas_size
            )
            plan["local_image"] = source
            plan["image"] = atlas
        atlas.pixels.foreach_set(atlas_pixels)
        atlas.update()
        try:
            atlas.pack()
        except RuntimeError:
            pass
        atlas["qss_import_hash"] = ""
        atlas["qss_face_local_baked"] = True
        atlas["qss_detached_face_atlas"] = True
        atlas["qss_detached_atlas_scale"] = float(layout["scale"])
        return atlas
    except Exception:
        try:
            if atlas.users == 0:
                bpy.data.images.remove(atlas, do_unlink=True)
        except Exception:
            pass
        raise



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
    # Adding the lightmap Image Texture node can make it Blender's active
    # paint canvas by default. Keep albedo as the default Material paint slot;
    # the dedicated lightmap-paint operator explicitly selects the atlas.
    base_image_node = _find_image_node(mat, 'base_texture')
    if base_image_node is not None:
        for node in nodes:
            node.select = False
        base_image_node.select = True
        nodes.active = base_image_node
        try:
            mat.update_tag()
        except Exception:
            pass

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



def _qss_apply_viewport_fov(context, fov_degrees):
    """Apply configured horizontal field of view to all currently open 3D Views."""
    lens = viewport_utils.viewport_lens_from_fov(float(fov_degrees), sensor_width=32.0)
    screens = set()
    screen = getattr(context, "screen", None) if context else None
    if screen is not None:
        screens.add(screen)
    wm = getattr(context, "window_manager", None) if context else None
    if wm is not None:
        for window in wm.windows:
            if window.screen is not None:
                screens.add(window.screen)
    changed = 0
    for target_screen in screens:
        for area in target_screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space is None or space.type != "VIEW_3D":
                continue
            space.lens = lens
            area.tag_redraw()
            changed += 1
    return changed


def _set_viewport_lighting_mode(context, mode):
    """Apply Original/Eevee/Cycles/Baked viewport shading."""
    live = mode in {"realtime", "cycles"}
    # File-browser operators can execute with a non-3D active area. Apply the
    # preset to every open window's 3D View spaces, not only context.screen.
    screens = set()
    screen = getattr(context, "screen", None)
    if screen is not None:
        screens.add(screen)
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        for window in wm.windows:
            if window.screen is not None:
                screens.add(window.screen)
    for target_screen in screens:
        for area in target_screen.areas:
            if area.type != "VIEW_3D":
                continue
            # The active SpaceView3D is the one Blender actually draws. Updating
            # inactive spaces in area.spaces alone can leave the visible viewport
            # in Solid shading after a file-browser import.
            space = area.spaces.active
            if space is None or space.type != "VIEW_3D":
                continue
            shading = space.shading
            shading.type = "RENDERED" if mode == "cycles" else "MATERIAL"
            for name in ("use_scene_lights", "use_scene_world",
                         "use_scene_lights_render", "use_scene_world_render"):
                if hasattr(shading, name):
                    setattr(shading, name, live)
            try:
                area.tag_redraw()
            except Exception:
                pass

    try:
        _qss_apply_viewport_fov(
            context, _qss_config_settings().get("viewport_fov_degrees", 90.0)
        )
    except Exception:
        pass

def _qss_apply_base_texture_visibility(obj):
    """Apply the per-map diffuse-texture toggle without disturbing lightmap nodes."""
    enabled = bool(obj.get("qss_base_textures_enabled", True))
    mode = str(obj.get("qss_preview_mode", "source"))
    changed = 0
    for mat in getattr(getattr(obj, "data", None), "materials", ()):
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        base = _find_image_node(mat, "base_texture")
        multiply = next((node for node in nodes
                         if node.type == "MIX_RGB" and node.get("qss_role") == "lightmap_multiply"), None)
        bsdf = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if mode in {"realtime", "cycles"} and bsdf is not None:
            socket = bsdf.inputs.get("Base Color")
            if socket is not None:
                for link in list(links):
                    if link.to_socket == socket:
                        links.remove(link)
                if enabled and base is not None:
                    links.new(base.outputs["Color"], socket)
                else:
                    socket.default_value = (1.0, 1.0, 1.0, 1.0)
                changed += 1
        elif multiply is not None:
            socket = multiply.inputs.get("Color1")
            if socket is not None:
                for link in list(links):
                    if link.to_socket == socket:
                        links.remove(link)
                if enabled and base is not None:
                    links.new(base.outputs["Color"], socket)
                else:
                    socket.default_value = (1.0, 1.0, 1.0, 1.0)
                changed += 1
        try:
            mat.update_tag()
        except Exception:
            pass
    return changed


def _qss_apply_source_lightmap_visibility(obj):
    """Show or suppress the active unpainted/painted lightmap contribution."""
    enabled = bool(obj.get("qss_source_lightmaps_enabled", True))
    mode = str(obj.get("qss_preview_mode", "source"))
    if mode not in {"source", "baked"}:
        return 0
    changed = 0
    for mat in getattr(getattr(obj, "data", None), "materials", ()):
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        multiply = next((node for node in nodes
                         if node.type == "MIX_RGB" and node.get("qss_role") == "lightmap_multiply"), None)
        lightmap = _find_image_node(mat, "lightmap")
        if multiply is None:
            continue
        socket = multiply.inputs.get("Color2")
        if socket is None:
            continue
        for link in list(links):
            if link.to_socket == socket:
                links.remove(link)
        if enabled and lightmap is not None:
            links.new(lightmap.outputs["Color"], socket)
        else:
            socket.default_value = (1.0, 1.0, 1.0, 1.0)
        changed += 1
        try:
            mat.update_tag()
        except Exception:
            pass
    return changed


def _set_lighting_preview(context, obj, mode):
    """Set a map-local lighting preset while keeping source and painted images separate."""
    if mode not in {"source", "realtime", "cycles", "baked"}:
        raise bsp.BSPError(f"Unknown QSS lighting mode: {mode}")
    if mode == "baked" and not _qss_has_baked_lightmap(obj):
        raise bsp.BSPError("This map has no generated lightmap yet. Bake it first.")

    if mode in {"realtime", "cycles"}:
        _restore_preview_world(context.scene, obj)
        _store_and_enter_eevee_live_engine(context.scene, obj)
        if mode == "cycles":
            context.scene.render.engine = "CYCLES"
        else:
            try:
                context.scene.render.engine = "BLENDER_EEVEE_NEXT"
            except Exception:
                context.scene.render.engine = "BLENDER_EEVEE"
        for mat in obj.data.materials:
            if mat is not None:
                _install_realtime_light_nodes(mat)
        for light_obj in _qss_active_map_objects(context.scene, obj):
            if light_obj.type == "LIGHT" and light_obj.get("qss_light_role") in {
                "quake_entity_light", "quake_world_sunlight"
            }:
                light_obj.hide_viewport = False
                light_obj.hide_render = False
                try:
                    light_obj.hide_set(False)
                except Exception:
                    pass
        _apply_quake_light_energy_scale(context.scene)
    else:
        # QSS does not change visibility on user-authored scene lights.
        # Avoid restoring state that this preview path never modified.
        _restore_preview_world(context.scene, obj)
        _restore_preview_engine(context.scene, obj)
        _apply_quake_light_energy_scale(context.scene)
        image = _qss_lightmap_preview_image(obj, mode, for_paint=False)
        _rebuild_lightmap_preview(obj, image_override=image)

    obj["qss_preview_mode"] = mode
    _qss_apply_base_texture_visibility(obj)
    _qss_apply_source_lightmap_visibility(obj)
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
    _set_principled_roughness(mat, 1.0)
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



def _qss_decoupled_lightmap_state(parsed, sample_count=None):
    """Return per-face DECOUPLED_LM records and effective light-style lists.

    DECOUPLED_LM carries dimensions, offsets and independent world-to-luxel
    vectors. LMSTYLE optionally replaces the classic dface style bytes.
    """
    extensions = parsed.bspx_lumps
    faces = parsed.faces()
    face_count = len(faces)
    if 'LMSTYLE16' in extensions:
        raise bsp.BSPError(
            "This BSP uses LMSTYLE16, whose variable-length style table is not supported yet."
        )
    style_payload = extensions.get('LMSTYLE')
    if style_payload is not None and len(style_payload) != face_count:
        raise bsp.BSPError(
            f"LMSTYLE must contain one byte for each of {face_count} BSP faces."
        )
    if 'DECOUPLED_LM' not in extensions:
        legacy = {'LMSHIFT', 'LMOFFSET'}.intersection(extensions)
        if legacy:
            raise bsp.BSPError(
                "This BSP uses LMSHIFT/LMOFFSET without DECOUPLED_LM. "
                "That legacy lightmap layout is not supported yet."
            )
        records = None
    else:
        try:
            records = lightmap_export_utils.parse_decoupled_lightmap_data(
                extensions['DECOUPLED_LM'], face_count
            )
        except ValueError as exc:
            raise bsp.BSPError(f"Invalid BSPX DECOUPLED_LM data: {exc}") from exc

    styles_by_face = []
    for face_id, face in enumerate(faces):
        if style_payload is not None:
            style = int(style_payload[face_id])
            styles = [] if style == 255 else [style]
        else:
            styles = [int(value) for value in face[5:9] if int(value) != 255]
        styles_by_face.append(styles)

    if records is not None and sample_count is not None:
        available = int(sample_count)
        for face_id, record in enumerate(records):
            if record is None:
                continue
            styles = styles_by_face[face_id]
            if not styles:
                raise bsp.BSPError(
                    f"DECOUPLED_LM face {face_id} has samples but no active light style."
                )
            required = record['width'] * record['height'] * len(styles)
            end = record['offset'] + required
            if end > available:
                raise bsp.BSPError(
                    f"DECOUPLED_LM face {face_id} references samples {record['offset']}..{end - 1}, "
                    f"but the available light data contains only {available} samples."
                )
    return records, styles_by_face

def _pack_lightmap_rectangles(records, gutter=2, max_atlas_size=2048):
    # Prefer 2x sample blocks for easier painting; fall back to 1:1 if needed.
    ordered = sorted(records, key=lambda r: (-(r['height']), -(r['width']), r['face_id']))
    for scale in (2, 1):
        atlas_sizes = (512, 1024, 2048) if int(max_atlas_size) >= 512 else (256, 128)
        for atlas_size in atlas_sizes:
            if atlas_size > int(max_atlas_size):
                continue
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
                          lit_rgb=None, lighting_data=None, resolution=1):
    faces = parsed.faces()
    texinfos = parsed.texinfos()
    lighting = (parsed.lumps[bsp.LUMP_LIGHTING] if lighting_data is None else lighting_data)
    sample_count = max(len(lighting), len(lit_rgb) // 3 if lit_rgb is not None else 0)
    decoupled_records, styles_by_face = _qss_decoupled_lightmap_state(parsed, sample_count)
    records = []
    positions_lookup = dict(zip(face_ids, positions_by_face))
    for face_id, texinfo_id in zip(face_ids, texinfo_ids):
        if face_id < 0 or face_id >= len(faces) or texinfo_id < 0 or texinfo_id >= len(texinfos):
            continue
        face = faces[face_id]
        decoupled = decoupled_records[face_id] if decoupled_records is not None else None
        if decoupled_records is not None and decoupled is None:
            continue
        active_styles = styles_by_face[face_id]
        if decoupled is not None:
            light_offset = decoupled['offset']
            sample_w = decoupled['width']
            sample_h = decoupled['height']
            lmvecs = decoupled['lmvecs']
            svec, tvec = lmvecs[:4], lmvecs[4:8]
            s_min = t_min = 0.0
            positions = positions_lookup[face_id]
            s_values = [p[0] * svec[0] + p[1] * svec[1] + p[2] * svec[2] + svec[3] for p in positions]
            t_values = [p[0] * tvec[0] + p[1] * tvec[1] + p[2] * tvec[2] + tvec[3] for p in positions]
            if (min(s_values) < -0.01 or min(t_values) < -0.01
                    or max(s_values) > sample_w - 1 + 0.01
                    or max(t_values) > sample_h - 1 + 0.01):
                raise bsp.BSPError(
                    f"DECOUPLED_LM face {face_id} projection falls outside its "
                    f"{sample_w}x{sample_h} sample grid."
                )
        else:
            light_offset = face[9]
            if light_offset < 0 or not active_styles:
                continue
            ext = _calc_face_lightmap_extents(positions_lookup[face_id], texinfos[texinfo_id])
            s_min, t_min, extent_s, extent_t, svec, tvec = ext
            sample_w = (extent_s >> 4) + 1
            sample_h = (extent_t >> 4) + 1
            lmvecs = None
        style_count = len(active_styles)
        block_size = sample_w * sample_h
        if not active_styles or light_offset + block_size * style_count > sample_count:
            raise bsp.BSPError(
                f"Face {face_id} lightmap samples exceed the available LIGHTING/RGBLIGHTING data."
            )
        # DECOUPLED_LM changes the sample offset and dimensions; LMSTYLE
        # optionally replaces the classic dface style list.
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
            'decoupled_lmvecs': lmvecs,
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

    resolution = material_utils.validate_lightmap_resolution(resolution)
    max_base_size = material_utils.MAX_LIGHTMAP_IMAGE_SIZE // resolution
    packed = _pack_lightmap_rectangles(records, max_atlas_size=max_base_size)
    if packed is None:
        obj['qss_lightmap_image_name'] = ''
        obj['qss_lightmap_faces'] = 0
        obj['qss_lightmap_note'] = 'Atlas exceeded 2048x2048 at 1 pixel per sample.'
        return None
    atlas_size, scale, placements, gutter = packed

    image_size = material_utils.lightmap_resolution_dimensions(atlas_size, resolution)
    rgba = array.array('f', [1.0]) * (image_size * image_size * 4)  # white = unlightmapped
    record_by_face = {r['face_id']: r for r in records}
    for rec in records:
        x0, y0 = placements[rec['face_id']]
        x0 = (x0 + gutter) * resolution
        y0 = (y0 + gutter) * resolution
        effective_scale = scale * resolution
        for sy in range(rec['height']):
            for sx in range(rec['width']):
                sample_rgb = rec['samples_rgb'][sy * rec['width'] + sx]
                values = tuple(channel / 255.0 for channel in sample_rgb)
                for dy in range(effective_scale):
                    top_y = y0 + sy * effective_scale + dy
                    bottom_y = image_size - 1 - top_y
                    for dx in range(effective_scale):
                        px = x0 + sx * effective_scale + dx
                        index = (bottom_y * image_size + px) * 4
                        rgba[index] = values[0]
                        rgba[index + 1] = values[1]
                        rgba[index + 2] = values[2]
                        rgba[index + 3] = 1.0

    image = bpy.data.images.new(
        name=f"QSS_Lightmap_{os.path.basename(obj.get('qss_source_path', 'map'))}",
        width=image_size, height=image_size, alpha=True, float_buffer=True
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
                if rec.get('decoupled_lmvecs') is not None:
                    lmvecs = rec['decoupled_lmvecs']
                    lm_s = p[0] * lmvecs[0] + p[1] * lmvecs[1] + p[2] * lmvecs[2] + lmvecs[3]
                    lm_t = p[0] * lmvecs[4] + p[1] * lmvecs[5] + p[2] * lmvecs[6] + lmvecs[7]
                    lm_s = min(max(lm_s, 0.0), rec['width'] - 1.0)
                    lm_t = min(max(lm_t, 0.0), rec['height'] - 1.0)
                else:
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
    obj['qss_lightmap_resolution'] = resolution
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


def _qss_lightmap_pixel_scale(obj, image):
    """Return the integer image-pixel scale relative to stored base atlas metadata."""
    base_size = int(obj.get('qss_lightmap_atlas_size', 0))
    if base_size <= 0:
        raise bsp.BSPError('Stored base lightmap atlas size is missing; re-import the BSP.')
    try:
        return material_utils.lightmap_resolution_ratio(base_size, int(image.size[0]))
    except ValueError as exc:
        raise bsp.BSPError(f'Working lightmap resolution metadata is invalid: {exc}') from exc


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



def _build_enhanced_lightmap_payload(
    obj, parsed, image, pixels, classic_lighting, classic_rgb,
    source_lighting, source_lit_rgb, face_attrs, resolution,
    base_pixel_scale, base_gutter,
):
    """Append enhanced samples and rebuild the per-face DECOUPLED_LM table.

    Existing DECOUPLED_LM projections are imported and rebased from their own
    world-to-luxel vectors. Classic faces continue to derive their original
    lightmap basis from texinfo. The classic sample region remains at the front
    of LIGHTING/RGBLIGHTING for engines that ignore BSPX.
    """
    sample_count = max(
        len(source_lighting),
        len(source_lit_rgb) // 3 if source_lit_rgb is not None else 0,
    )
    decoupled_records, styles_by_face = _qss_decoupled_lightmap_state(parsed, sample_count)
    mesh = obj.data
    face_id_attr = face_attrs['qss_bsp_face_id']
    has_attr = face_attrs['qss_lm_has_data']
    x_attr = face_attrs['qss_lm_atlas_x']
    y_attr = face_attrs['qss_lm_atlas_y']
    w_attr = face_attrs['qss_lm_sample_w']
    h_attr = face_attrs['qss_lm_sample_h']
    polygons_by_face = {}
    for poly_index, _poly in enumerate(mesh.polygons):
        face_id = int(face_id_attr.data[poly_index].value)
        if face_id in polygons_by_face:
            raise bsp.BSPError(f"Duplicate mesh metadata found for BSP face {face_id}.")
        polygons_by_face[face_id] = poly_index

    faces = parsed.faces()
    texinfos = parsed.texinfos()
    vertices = parsed.vertices()
    image_size = int(image.size[0])
    image_pixels = pixels
    face_records = {}

    for face_id, face in enumerate(faces):
        decoupled = decoupled_records[face_id] if decoupled_records is not None else None
        if decoupled_records is not None and decoupled is None:
            continue
        active_styles = styles_by_face[face_id]
        if not active_styles:
            continue
        vertex_ids = parsed.face_vertex_indices(face)
        if len(vertex_ids) < 3 or any(index < 0 or index >= len(vertices) for index in vertex_ids):
            raise bsp.BSPError(f"Face {face_id} has invalid vertex references for enhanced lightmap export.")
        positions = [vertices[index] for index in vertex_ids]

        if decoupled is not None:
            light_offset = int(decoupled['offset'])
            base_width = int(decoupled['width'])
            base_height = int(decoupled['height'])
            lmvecs = tuple(float(value) for value in decoupled['lmvecs'])
            s_values = [
                p[0] * lmvecs[0] + p[1] * lmvecs[1] + p[2] * lmvecs[2] + lmvecs[3]
                for p in positions
            ]
            t_values = [
                p[0] * lmvecs[4] + p[1] * lmvecs[5] + p[2] * lmvecs[6] + lmvecs[7]
                for p in positions
            ]
            if (min(s_values) < -0.01 or min(t_values) < -0.01
                    or max(s_values) > base_width - 1 + 0.01
                    or max(t_values) > base_height - 1 + 0.01):
                raise bsp.BSPError(
                    f"DECOUPLED_LM face {face_id} projection falls outside its "
                    f"{base_width}x{base_height} sample grid."
                )
            texinfo_id = int(face[4])
            base_s_min = base_t_min = 0
        else:
            light_offset = int(face[9])
            if light_offset < 0:
                continue
            texinfo_id = int(face[4])
            if texinfo_id < 0 or texinfo_id >= len(texinfos):
                raise bsp.BSPError(f"Face {face_id} has an invalid source texinfo index for enhanced lightmap export.")
            base_s_min, base_t_min, base_extent_s, base_extent_t, svec, tvec = _calc_face_lightmap_extents(
                positions, texinfos[texinfo_id]
            )
            base_width = (base_extent_s >> 4) + 1
            base_height = (base_extent_t >> 4) + 1
            lmvecs = None

        block_size = base_width * base_height
        if light_offset + block_size * len(active_styles) > sample_count:
            raise bsp.BSPError(f"Face {face_id} source lightmap samples exceed the LIGHTING/RGBLIGHTING data.")

        record = None
        poly_index = polygons_by_face.get(face_id)
        if poly_index is not None and has_attr.data[poly_index].value:
            stored_width = int(w_attr.data[poly_index].value)
            stored_height = int(h_attr.data[poly_index].value)
            if (stored_width, stored_height) != (base_width, base_height):
                raise bsp.BSPError(
                    f"Face {face_id} atlas dimensions {stored_width}x{stored_height} do not match "
                    f"the source BSP's {base_width}x{base_height} lightmap grid."
                )
            try:
                if lmvecs is not None:
                    factor = int(resolution)
                    while factor > 1 and (
                        (base_width - 1) * factor + 1 > lightmap_export_utils.MAX_SURFACE_LUXELS
                        or (base_height - 1) * factor + 1 > lightmap_export_utils.MAX_SURFACE_LUXELS
                    ):
                        factor //= 2
                    width = (base_width - 1) * factor + 1
                    height = (base_height - 1) * factor + 1
                    if width > lightmap_export_utils.MAX_SURFACE_LUXELS or height > lightmap_export_utils.MAX_SURFACE_LUXELS:
                        raise ValueError(
                            f"source grid {base_width}x{base_height} exceeds the "
                            f"{lightmap_export_utils.MAX_SURFACE_LUXELS}x{lightmap_export_utils.MAX_SURFACE_LUXELS} limit"
                        )
                    sample_s = tuple(index / factor for index in range(width))
                    sample_t = tuple(index / factor for index in range(height))
                    scaled_lmvecs = tuple(value * factor for value in lmvecs)
                    rgb_samples = lightmap_export_utils.sample_face_rgb_at_lm_coordinates(
                        image_pixels, image_size, resolution,
                        int(x_attr.data[poly_index].value),
                        int(y_attr.data[poly_index].value),
                        int(base_gutter), int(base_pixel_scale),
                        sample_s, sample_t,
                    )
                    record = {
                        'shift': 4,
                        'width': width,
                        'height': height,
                        'lmvecs': scaled_lmvecs,
                        'rgb': rgb_samples,
                    }
                else:
                    s_values = [
                        p[0] * svec[0] + p[1] * svec[1] + p[2] * svec[2] + svec[3]
                        for p in positions
                    ]
                    t_values = [
                        p[0] * tvec[0] + p[1] * tvec[1] + p[2] * tvec[2] + tvec[3]
                        for p in positions
                    ]
                    shift, s_min, t_min, width, height = lightmap_export_utils.choose_luxel_grid(
                        s_values, t_values, resolution
                    )
                    rgb_samples = lightmap_export_utils.sample_face_rgb_from_atlas(
                        image_pixels, image_size, resolution,
                        int(x_attr.data[poly_index].value),
                        int(y_attr.data[poly_index].value),
                        int(base_gutter), int(base_pixel_scale),
                        int(base_s_min), int(base_t_min),
                        int(s_min), int(t_min), int(width), int(height),
                        1 << shift,
                    )
                    record = {
                        'shift': shift,
                        'width': width,
                        'height': height,
                        's_min': s_min,
                        't_min': t_min,
                        'rgb': rgb_samples,
                    }
            except ValueError as exc:
                raise bsp.BSPError(f"Could not sample enhanced lightmap for face {face_id}: {exc}") from exc

        if record is None:
            # A face without an editable atlas island retains its imported
            # static lighting, including the original independent lmvecs.
            try:
                original_rgb = lighting_utils.combine_style_samples(
                    source_lighting, source_lit_rgb, light_offset, block_size, active_styles
                )
            except (ValueError, IndexError) as exc:
                raise bsp.BSPError(f"Could not recover source lightmap samples for face {face_id}: {exc}") from exc
            rgb_samples = bytes(channel for sample in original_rgb for channel in sample)
            record = {
                'shift': 4,
                'width': base_width,
                'height': base_height,
                'rgb': rgb_samples,
            }
            if lmvecs is not None:
                record['lmvecs'] = lmvecs
            else:
                record['s_min'] = base_s_min
                record['t_min'] = base_t_min
        face_records[face_id] = record

    try:
        extension = lightmap_export_utils.build_lightmap_extension_data(
            len(faces), face_records, len(classic_lighting)
        )
    except ValueError as exc:
        raise bsp.BSPError(f"Could not build enhanced BSPX lightmap data: {exc}") from exc

    appended_mono = extension['LIGHTING_APPEND']
    appended_rgb = extension['RGBLIGHTING_APPEND']
    lighting = bytearray(classic_lighting)
    rgb = bytearray(classic_rgb)
    lighting.extend(appended_mono)
    rgb.extend(appended_rgb)
    if len(rgb) != len(lighting) * 3:
        raise bsp.BSPError("Enhanced RGB and monochrome lightmap sample counts do not match.")

    try:
        decoupled_lm = lightmap_export_utils.build_decoupled_lightmap_data(
            faces, texinfos, face_records, extension['LMOFFSET']
        )
    except ValueError as exc:
        raise bsp.BSPError(f"Could not build DECOUPLED_LM BSPX data: {exc}") from exc
    bspx = {
        'DECOUPLED_LM': decoupled_lm,
        'LMSTYLE': extension['LMSTYLE'],
        'RGBLIGHTING': bytes(rgb),
    }
    return bytes(lighting), bsp.build_lit_file(bytes(rgb)), bspx




def _qss_append_decoupled_classic_fallback(
    obj, parsed, face_id, face, decoupled, active_styles, texinfos, faces_lump,
    lighting, lit_rgb, pixels, image_size, resolution,
    atlas_x, atlas_y, gutter, pixels_per_luxel,
):
    """Reproject an editable decoupled face into a vanilla BSP29 fallback grid."""
    fallback_styles = [int(value) for value in active_styles]
    if not fallback_styles:
        return faces_lump
    if len(fallback_styles) > 4 or any(style < 0 or style >= 255 for style in fallback_styles):
        raise bsp.BSPError(f"Decoupled face {face_id} has invalid classic fallback style IDs.")
    texinfo_id = int(face[4])
    if texinfo_id < 0 or texinfo_id >= len(texinfos):
        raise bsp.BSPError(f"Decoupled face {face_id} has an invalid output texinfo index.")
    texinfo = texinfos[texinfo_id]
    vertex_ids = parsed.face_vertex_indices(face)
    vertices = parsed.vertices()
    if len(vertex_ids) < 3 or any(index < 0 or index >= len(vertices) for index in vertex_ids):
        raise bsp.BSPError(f"Decoupled face {face_id} has invalid vertex references.")
    positions = [vertices[index] for index in vertex_ids]
    s_min, t_min, extent_s, extent_t, _svec, _tvec = _calc_face_lightmap_extents(
        positions, texinfo
    )
    width = (extent_s >> 4) + 1
    height = (extent_t >> 4) + 1
    if width <= 0 or height <= 0 or width > 256 or height > 256:
        raise bsp.BSPError(
            f"Decoupled face {face_id} needs a {width}x{height} classic fallback lightmap; "
            "the supported per-face limit is 256x256."
        )
    planes = parsed.planes()
    plane_id = int(face[0])
    if plane_id < 0 or plane_id >= len(planes):
        raise bsp.BSPError(f"Decoupled face {face_id} references an invalid plane.")
    plane = planes[plane_id]
    sign = -1.0 if int(face[1]) else 1.0
    normal = tuple(float(plane[i]) * sign for i in range(3))
    distance = float(plane[3]) * sign
    lmvecs = tuple(float(value) for value in decoupled['lmvecs'])
    coordinate_pairs = []
    for sy in range(height):
        target_t = t_min + sy * 16.0
        for sx in range(width):
            target_s = s_min + sx * 16.0
            point = lighting_utils.solve_texinfo_plane(
                texinfo[0:3], texinfo[4:7], normal,
                target_s - float(texinfo[3]),
                target_t - float(texinfo[7]),
                distance,
            )
            if point is None:
                raise bsp.BSPError(
                    f"Decoupled face {face_id} has a singular output texinfo projection; "
                    "cannot create its classic lightmap fallback."
                )
            lm_s = point[0] * lmvecs[0] + point[1] * lmvecs[1] + point[2] * lmvecs[2] + lmvecs[3]
            lm_t = point[0] * lmvecs[4] + point[1] * lmvecs[5] + point[2] * lmvecs[6] + lmvecs[7]
            # A rotated or independently edited texture projection can make
            # the rectangular vanilla lightmap grid extend beyond the source
            # face's projected polygon at its corners. Those corner luxels are
            # not sampled on the polygon itself; clamp them to the nearest edge
            # of the imported lightmap island.
            coordinate_pairs.append((
                min(max(lm_s, 0.0), int(decoupled['width']) - 1.0),
                min(max(lm_t, 0.0), int(decoupled['height']) - 1.0),
            ))
    try:
        rgb_samples = lightmap_export_utils.sample_face_rgb_at_lm_coordinate_pairs(
            pixels, image_size, resolution,
            atlas_x, atlas_y, gutter, pixels_per_luxel,
            coordinate_pairs,
        )
    except ValueError as exc:
        raise bsp.BSPError(
            f"Could not create classic fallback samples for decoupled face {face_id}: {exc}"
        ) from exc
    expected = width * height * 3
    if len(rgb_samples) != expected:
        raise bsp.BSPError(f"Decoupled face {face_id} classic fallback sampler returned an invalid block.")
    mono_samples = bytes(
        max(0, min(255, int(round(
            0.2126 * rgb_samples[index]
            + 0.7152 * rgb_samples[index + 1]
            + 0.0722 * rgb_samples[index + 2]
        ))))
        for index in range(0, len(rgb_samples), 3)
    )
    new_lightofs = len(lighting)
    if new_lightofs > 0x7FFFFFFF:
        raise bsp.BSPError("Decoupled classic fallback samples exceed the signed BSP29 lightofs range.")
    faces_lump = bsp.replace_face_lightofs(faces_lump, face_id, new_lightofs)
    style_bytes = bytes(fallback_styles + [255] * (4 - len(fallback_styles)))
    face_record_start = face_id * bsp.SIZE_FACE
    face_record = bytearray(faces_lump)
    face_record[face_record_start + 12:face_record_start + 16] = style_bytes
    faces_lump = bytes(face_record)
    lighting.extend(mono_samples)
    lit_rgb.extend(rgb_samples)
    if len(fallback_styles) > 1:
        lighting.extend(bytes(width * height * (len(fallback_styles) - 1)))
        lit_rgb.extend(bytes(width * height * (len(fallback_styles) - 1) * 3))
    return faces_lump


def _patch_lightmap_lump(obj, parsed, enhanced=False, output_faces_lump=None, output_texinfo_lump=None):
    """Return (monochrome BSP lighting lump, QLIT v1 sidecar or None).

    Export follows the selected lightmap layer: Original uses the immutable
    source snapshot (or its painted override), Baked uses the generated atlas
    (or its painted override), and live-lighting previews fall back to Original.
    """
    preview_mode = obj.get("qss_preview_mode", "source")
    painted_enabled = bool(obj.get("qss_painted_lightmaps_enabled", True))
    if preview_mode == "baked":
        painted_name = obj.get("qss_painted_baked_lightmap", "")
        image_name = painted_name if painted_enabled and bpy.data.images.get(painted_name) else obj.get("qss_lightmap_image_name", "")
    else:
        painted_name = obj.get("qss_painted_original_lightmap", "")
        source_name = obj.get("qss_original_lightmap_backup", "")
        image_name = painted_name if painted_enabled and bpy.data.images.get(painted_name) else (source_name or obj.get("qss_lightmap_image_name", ""))
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
        if enhanced:
            raise bsp.BSPError('Enhanced lightmap export requires an imported working lightmap atlas.')
        original_lit = bsp.build_lit_file(source_lit_rgb) if source_lit_rgb is not None else None
        return lighting_source, original_lit, {}, (output_faces_lump or parsed.lumps[bsp.LUMP_FACES])
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
    resolution = _qss_lightmap_pixel_scale(obj, image)
    scale = int(obj.get('qss_lightmap_scale', 1)) * resolution
    gutter = int(obj.get('qss_lightmap_gutter', 2)) * resolution
    px = array.array('f', [0.0]) * (size * size * 4)
    image.update()
    image.pixels.foreach_get(px)
    faces = parsed.faces()
    faces_lump = bytes(output_faces_lump or parsed.lumps[bsp.LUMP_FACES])
    texinfos = parsed.texinfos()
    output_texinfo_data = bytes(output_texinfo_lump or parsed.lumps[bsp.LUMP_TEXINFO])
    if len(output_texinfo_data) % bsp.SIZE_TEXINFO:
        raise bsp.BSPError("Output texinfo lump has an invalid record size.")
    output_texinfos = [
        struct.unpack_from("<8fii", output_texinfo_data, offset)
        for offset in range(0, len(output_texinfo_data), bsp.SIZE_TEXINFO)
    ]
    vertices = parsed.vertices()
    decoupled_records, _styles_by_face = _qss_decoupled_lightmap_state(
        parsed, max(len(lighting_source), len(source_lit_rgb) // 3 if source_lit_rgb is not None else 0)
    )
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
        decoupled = decoupled_records[face_id] if decoupled_records is not None else None
        if decoupled is not None:
            output_face = struct.unpack_from("<Hhihh4Bi", faces_lump, face_id * bsp.SIZE_FACE)
            faces_lump = _qss_append_decoupled_classic_fallback(
                obj, parsed, face_id, output_face, decoupled, _styles_by_face[face_id],
                output_texinfos, faces_lump,
                lighting, lit_rgb, px, size, resolution,
                int(x_attr.data[poly_index].value),
                int(y_attr.data[poly_index].value),
                int(obj.get('qss_lightmap_gutter', 2)),
                int(obj.get('qss_lightmap_scale', 1)),
            )
            continue
        styles = face[5:9]
        light_offset = face[9]
        if light_offset < 0 or styles[0] == 255:
            continue
        sample_w = int(w_attr.data[poly_index].value)
        sample_h = int(h_attr.data[poly_index].value)
        atlas_x = int(x_attr.data[poly_index].value) * resolution + gutter
        atlas_y = int(y_attr.data[poly_index].value) * resolution + gutter
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
    # Classic BSP29 derives lightmap extents from texinfo. Detached faces
    # use a face-local texture projection, so append a replacement classic
    # lightmap block sampled through the original projection and redirect only
    # that face's lightofs. This also provides a valid vanilla fallback when
    # the optional DECOUPLED_LM BSPX extension is ignored by an engine.
    for poly_index, poly in enumerate(mesh.polygons):
        if not has_attr.data[poly_index].value:
            continue
        if poly.material_index < 0 or poly.material_index >= len(mesh.materials):
            continue
        mat = mesh.materials[poly.material_index]
        custom_projection = (
            mat.get('qss_texinfo_projection')
            if mat is not None and mat.get('qss_face_local_projection') else None
        )
        if custom_projection is None:
            continue
        face_id = int(face_attr.data[poly_index].value)
        if face_id < 0 or face_id >= len(faces):
            raise bsp.BSPError(f"Detached lightmap refers to invalid BSP face {face_id}.")
        face = faces[face_id]
        if decoupled_records is not None and decoupled_records[face_id] is not None:
            # The decoupled face already received a vanilla fallback sampled
            # through its final output texinfo in the first pass.
            continue
        light_offset = int(face[9])
        if light_offset < 0 or int(face[5]) == 255:
            continue
        style_count = sum(1 for style in face[5:9] if int(style) != 255)
        if style_count <= 0:
            continue
        source_texinfo_id = int(face[4])
        if source_texinfo_id < 0 or source_texinfo_id >= len(texinfos):
            raise bsp.BSPError(f"Detached face {face_id} has an invalid source texinfo.")
        old_texinfo = texinfos[source_texinfo_id]
        projection = tuple(float(value) for value in custom_projection)
        if len(projection) != 8:
            raise bsp.BSPError(f"Detached face {face_id} has an invalid texture projection.")
        new_texinfo = projection + tuple(old_texinfo[8:10])
        vertex_ids = parsed.face_vertex_indices(face)
        if len(vertex_ids) < 3 or any(index < 0 or index >= len(vertices) for index in vertex_ids):
            raise bsp.BSPError(f"Detached face {face_id} has invalid vertex references.")
        positions = [vertices[index] for index in vertex_ids]
        base_s_min, base_t_min, base_extent_s, base_extent_t, _sv, _tv = _calc_face_lightmap_extents(
            positions, old_texinfo
        )
        base_width = (base_extent_s >> 4) + 1
        base_height = (base_extent_t >> 4) + 1
        stored_width = int(w_attr.data[poly_index].value)
        stored_height = int(h_attr.data[poly_index].value)
        if (stored_width, stored_height) != (base_width, base_height):
            raise bsp.BSPError(
                f"Detached face {face_id} atlas metadata is {stored_width}x{stored_height}, "
                f"but its source lightmap grid is {base_width}x{base_height}. Re-import the BSP."
            )
        new_s_min, new_t_min, new_extent_s, new_extent_t, _nsv, _ntv = _calc_face_lightmap_extents(
            positions, new_texinfo
        )
        new_width = (new_extent_s >> 4) + 1
        new_height = (new_extent_t >> 4) + 1
        if new_width <= 0 or new_height <= 0 or new_width > 256 or new_height > 256:
            raise bsp.BSPError(
                f"Detached face {face_id} would need a {new_width}x{new_height} classic lightmap, "
                "outside the supported 256x256 surface limit."
            )
        new_s_coordinates = tuple(new_s_min + index * 16 for index in range(new_width))
        new_t_coordinates = tuple(new_t_min + index * 16 for index in range(new_height))
        try:
            old_s_coordinates = texture_export.inverse_project_axis_coordinates(
                old_texinfo[0:4], new_texinfo[0:4], new_s_coordinates
            )
            old_t_coordinates = texture_export.inverse_project_axis_coordinates(
                old_texinfo[4:8], new_texinfo[4:8], new_t_coordinates
            )
            rgb_samples = lightmap_export_utils.sample_face_rgb_at_coordinates(
                px, size, resolution,
                int(x_attr.data[poly_index].value),
                int(y_attr.data[poly_index].value),
                int(obj.get('qss_lightmap_gutter', 2)),
                int(obj.get('qss_lightmap_scale', 1)),
                base_s_min, base_t_min,
                old_s_coordinates, old_t_coordinates,
            )
        except ValueError as exc:
            raise bsp.BSPError(
                f"Could not reproject the lightmap for detached BSP face {face_id}: {exc}"
            ) from exc
        block_size = new_width * new_height
        if len(rgb_samples) != block_size * 3:
            raise bsp.BSPError(f"Detached face {face_id} lightmap sampler returned an invalid RGB block.")
        mono_samples = bytes(
            max(0, min(255, int(round(
                0.2126 * rgb_samples[index]
                + 0.7152 * rgb_samples[index + 1]
                + 0.0722 * rgb_samples[index + 2]
            ))))
            for index in range(0, len(rgb_samples), 3)
        )
        new_lightofs = len(lighting)
        if new_lightofs > 0x7FFFFFFF:
            raise bsp.BSPError("Detached-face lightmaps exceed the signed BSP29 lightofs range.")
        faces_lump = bsp.replace_face_lightofs(faces_lump, face_id, new_lightofs)
        lighting.extend(mono_samples)
        lit_rgb.extend(rgb_samples)
        # The editable atlas contains the sum of the source styles. Preserve
        # the face's style count but clear the unused source planes.
        if style_count > 1:
            lighting.extend(bytes(block_size * (style_count - 1)))
            lit_rgb.extend(bytes(block_size * 3 * (style_count - 1)))

    if enhanced:
        enhanced_lighting, enhanced_lit, enhanced_bspx = _build_enhanced_lightmap_payload(
            obj, parsed, image, px, lighting, lit_rgb,
            lighting_source, source_lit_rgb, face_attrs, resolution,
            int(obj.get('qss_lightmap_scale', 1)),
            int(obj.get('qss_lightmap_gutter', 2)),
        )
        return enhanced_lighting, enhanced_lit, enhanced_bspx, faces_lump
    return bytes(lighting), bsp.build_lit_file(bytes(lit_rgb)), {}, faces_lump



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


def _qss_make_cycles_math_node(nodes, name, operation, location):
    """Create a named math node for the QSS Cycles light shader."""
    node = nodes.new("ShaderNodeMath")
    node.name = name
    node.label = name.removeprefix("QSS_")
    node.operation = operation
    node.location = location
    node["qss_cycles_falloff_node"] = True
    return node


def _qss_cycles_falloff_tree_is_owned(light_data):
    """True only when every node in this light tree belongs to QSS."""
    if int(light_data.get("qss_cycles_delay_falloff_version", 0)) != 1:
        return False
    node_tree = getattr(light_data, "node_tree", None)
    if node_tree is None or not node_tree.nodes:
        return False
    return all(bool(node.get("qss_cycles_falloff_node", False))
               for node in node_tree.nodes)


def _qss_build_cycles_delay_falloff_nodes(light_data, delay):
    """Build a Cycles-only multiplier that converts the base point falloff.

    The standard QSS lamp energy is already calibrated at one reference point.
    With Smooth=0, the Light Falloff node's Quadratic output is Strength and
    Linear is Strength multiplied by ray length, so Linear/Quadratic recovers
    the shading-point distance.
    The math nodes then apply the exact ratio between that inverse-square base
    and ericw delay 0 or delay 5. Eevee ignores this light node tree and retains
    the ordinary lamp-energy approximation.
    """
    # Never clear a node graph that did not originate from this helper.
    # Fresh imported QSS lights have nodes disabled; an existing enabled tree
    # that is not fully QSS-owned belongs to the user.
    existing_tree = getattr(light_data, "node_tree", None)
    if (bool(light_data.use_nodes) and existing_tree is not None
            and len(existing_tree.nodes) > 0
            and not _qss_cycles_falloff_tree_is_owned(light_data)):
        raise RuntimeError("Existing user-authored light nodes were preserved; QSS Cycles falloff was not installed")

    light_data.use_nodes = True
    node_tree = getattr(light_data, "node_tree", None)
    if node_tree is None:
        raise RuntimeError("Blender did not create a node tree for this light")

    nodes = node_tree.nodes
    links = node_tree.links
    nodes.clear()

    falloff = nodes.new("ShaderNodeLightFalloff")
    falloff.name = "QSS_Ericw_LightFalloff"
    falloff.label = "ericw distance probe"
    falloff["qss_cycles_falloff_node"] = True
    falloff.location = (-900, 120)
    falloff.inputs["Strength"].default_value = 1.0
    falloff.inputs["Smooth"].default_value = 0.0

    safe_quadratic = _qss_make_cycles_math_node(
        nodes, "QSS_SafeQuadratic", "MAXIMUM", (-680, -40)
    )
    safe_quadratic.inputs[1].default_value = 1e-20

    distance_m = _qss_make_cycles_math_node(
        nodes, "QSS_DistanceMeters", "DIVIDE", (-460, 120)
    )
    distance_quake = _qss_make_cycles_math_node(
        nodes, "QSS_DistanceQuakeUnits", "DIVIDE", (-240, 120)
    )

    links.new(falloff.outputs["Quadratic"], safe_quadratic.inputs[0])
    links.new(falloff.outputs["Linear"], distance_m.inputs[0])
    links.new(safe_quadratic.outputs[0], distance_m.inputs[1])
    links.new(distance_m.outputs[0], distance_quake.inputs[0])

    if int(delay) == 0:
        normalized = _qss_make_cycles_math_node(
            nodes, "QSS_NormalizedRadius", "DIVIDE", (0, 180)
        )
        one_minus = _qss_make_cycles_math_node(
            nodes, "QSS_OneMinusRadius", "SUBTRACT", (220, 180)
        )
        positive_remainder = _qss_make_cycles_math_node(
            nodes, "QSS_PositiveRemainder", "MAXIMUM", (440, 180)
        )
        positive_remainder.inputs[1].default_value = 0.0
        normalized_squared = _qss_make_cycles_math_node(
            nodes, "QSS_NormalizedRadiusSquared", "MULTIPLY", (220, -80)
        )
        times_eight = _qss_make_cycles_math_node(
            nodes, "QSS_DelayZeroScale", "MULTIPLY", (440, -80)
        )
        times_eight.inputs[1].default_value = 8.0
        correction = _qss_make_cycles_math_node(
            nodes, "QSS_EricwCorrection", "MULTIPLY", (660, 100)
        )

        links.new(distance_quake.outputs[0], normalized.inputs[0])
        links.new(normalized.outputs[0], one_minus.inputs[1])
        one_minus.inputs[0].default_value = 1.0
        links.new(one_minus.outputs[0], positive_remainder.inputs[0])
        links.new(normalized.outputs[0], normalized_squared.inputs[0])
        links.new(normalized.outputs[0], normalized_squared.inputs[1])
        links.new(normalized_squared.outputs[0], times_eight.inputs[0])
        links.new(times_eight.outputs[0], correction.inputs[0])
        links.new(positive_remainder.outputs[0], correction.inputs[1])
    elif int(delay) == 5:
        scaled_distance = _qss_make_cycles_math_node(
            nodes, "QSS_WaitScaledDistance", "MULTIPLY", (0, 180)
        )
        shifted_distance = _qss_make_cycles_math_node(
            nodes, "QSS_ShiftedDistance", "ADD", (220, 180)
        )
        shifted_distance.inputs[1].default_value = lighting_utils.ERICW_LIGHT_SCALE
        shift_ratio = _qss_make_cycles_math_node(
            nodes, "QSS_ShiftRatio", "DIVIDE", (440, 180)
        )
        shift_ratio_squared = _qss_make_cycles_math_node(
            nodes, "QSS_ShiftRatioSquared", "MULTIPLY", (660, 180)
        )
        times_four = _qss_make_cycles_math_node(
            nodes, "QSS_DelayFiveScale", "MULTIPLY", (880, 180)
        )
        times_four.inputs[1].default_value = 4.0

        links.new(distance_quake.outputs[0], scaled_distance.inputs[0])
        links.new(scaled_distance.outputs[0], shifted_distance.inputs[0])
        links.new(scaled_distance.outputs[0], shift_ratio.inputs[0])
        links.new(shifted_distance.outputs[0], shift_ratio.inputs[1])
        links.new(shift_ratio.outputs[0], shift_ratio_squared.inputs[0])
        links.new(shift_ratio.outputs[0], shift_ratio_squared.inputs[1])
        links.new(shift_ratio_squared.outputs[0], times_four.inputs[0])
        correction = times_four
    else:
        raise ValueError(f"Unsupported QSS Cycles falloff delay: {delay}")

    emission = nodes.new("ShaderNodeEmission")
    emission.name = "QSS_Ericw_Emission"
    emission.label = "inverse-square × ericw correction"
    emission["qss_cycles_falloff_node"] = True
    emission.location = (1120, 100)
    # The Light datablock retains the Quake _color and calibrated energy.
    emission.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(correction.outputs[0], emission.inputs["Strength"])

    output = nodes.new("ShaderNodeOutputLight")
    output.name = "QSS_Ericw_LightOutput"
    output.label = "Cycles light output"
    output["qss_cycles_falloff_node"] = True
    output.location = (1360, 100)
    if hasattr(output, "target"):
        output.target = "CYCLES"
    links.new(emission.outputs[0], output.inputs["Surface"])

    light_data["qss_cycles_delay_falloff_version"] = 1
    light_data["qss_cycles_delay_falloff_profile"] = int(delay)
    return node_tree


def _qss_update_cycles_delay_falloff(light_obj, delay, raw_value):
    """Enable/update the Cycles correction for ericw delay 0 and delay 5 only."""
    light_data = light_obj.data
    marker = int(light_data.get("qss_cycles_delay_falloff_version", 0))

    if int(delay) not in {0, 5}:
        # Do not disturb unrelated or user-authored light node trees. Only
        # disable a complete node tree installed by this SLOPGATE helper.
        if _qss_cycles_falloff_tree_is_owned(light_data):
            light_data.use_nodes = False
        light_obj["qss_cycles_falloff_active"] = False
        light_obj["qss_cycles_falloff_profile"] = "native_fallback"
        return False

    if not hasattr(light_data, "use_nodes"):
        light_obj["qss_cycles_falloff_active"] = False
        light_obj["qss_cycles_falloff_error"] = "Light shader nodes are unavailable in this Blender build"
        return False

    existing_tree = getattr(light_data, "node_tree", None)
    if (bool(light_data.use_nodes) and existing_tree is not None
            and len(existing_tree.nodes) > 0
            and not _qss_cycles_falloff_tree_is_owned(light_data)):
        light_obj["qss_cycles_falloff_active"] = False
        light_obj["qss_cycles_falloff_profile"] = "user_nodes_preserved_native_fallback"
        light_obj["qss_cycles_falloff_error"] = (
            "Existing user-authored light nodes were left untouched; this light uses native falloff"
        )
        return False

    world_dist = max(1e-6, float(light_obj.get("qss_quake_world_dist", 1.0)))
    wait = max(1e-6, float(light_obj.get("qss_quake_wait", 1.0)))
    unit_scale = max(1e-9, abs(float(light_obj.get(
        "qss_quake_unit_scale", DEFAULT_QUAKE_UNIT_SCALE
    ))))
    falloff = max(0.0, float(light_obj.get("qss_quake_falloff", 0.0)))

    try:
        node_tree = getattr(light_data, "node_tree", None) if light_data.use_nodes else None
        required = {
            "QSS_Ericw_LightFalloff", "QSS_SafeQuadratic",
            "QSS_DistanceMeters", "QSS_DistanceQuakeUnits",
            "QSS_Ericw_Emission", "QSS_Ericw_LightOutput",
        }
        if int(light_data.get("qss_cycles_delay_falloff_version", 0)) != 1 or int(
            light_data.get("qss_cycles_delay_falloff_profile", -1)
        ) != int(delay) or node_tree is None or not required.issubset(
            {node.name for node in node_tree.nodes}
        ):
            node_tree = _qss_build_cycles_delay_falloff_nodes(light_data, int(delay))
        else:
            light_data.use_nodes = True

        nodes = node_tree.nodes
        by_name = {node.name: node for node in nodes}
        by_name["QSS_Ericw_LightFalloff"].inputs["Strength"].default_value = 1.0
        by_name["QSS_Ericw_LightFalloff"].inputs["Smooth"].default_value = 0.0
        by_name["QSS_DistanceQuakeUnits"].inputs[1].default_value = unit_scale

        if int(delay) == 0:
            radius = (
                falloff * world_dist
                if falloff > 0.0
                else abs(float(raw_value)) / (wait * world_dist)
            )
            by_name["QSS_NormalizedRadius"].inputs[1].default_value = max(1e-9, radius)
        else:
            by_name["QSS_WaitScaledDistance"].inputs[1].default_value = wait * world_dist

        emission = by_name["QSS_Ericw_Emission"]
        emission.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        light_obj["qss_cycles_falloff_active"] = True
        light_obj["qss_cycles_falloff_profile"] = (
            "ericw_delay0_linear" if int(delay) == 0
            else "ericw_delay5_soft_inverse_square"
        )
        light_obj["qss_cycles_falloff_error"] = ""
        try:
            light_data.update_tag()
        except Exception:
            pass
        return True
    except Exception as exc:
        # Keep the existing native lamp usable if this Blender build cannot
        # construct the Cycles-specific node graph.
        try:
            if _qss_cycles_falloff_tree_is_owned(light_data):
                light_data.use_nodes = False
        except Exception:
            pass
        light_obj["qss_cycles_falloff_active"] = False
        light_obj["qss_cycles_falloff_error"] = str(exc)
        print(f"SLOPGATE: Cycles falloff setup failed for {light_obj.name}: {exc}")
        return False


def _apply_quake_light_energy_scale(scene):
    """Apply the user live-light slider and any explicit per-light calibration."""
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
        # Only the explicit Auto-calibrate action may change this per-light
        # multiplier. Cycles source-match atlas normalization never writes it.
        manual_calibration = max(
            0.0, float(light_obj.get('qss_manual_energy_calibration', 1.0))
        )
        if role == 'quake_entity_light':
            delay = int(light_obj.get('qss_quake_light_delay', 0))
            preview = lighting_utils.blender_live_light_preview_parameters(
                raw_value,
                light_obj.get('qss_quake_raw_light_value', raw_value),
                delay,
                wait=light_obj.get('qss_quake_wait', 1.0),
                world_dist=light_obj.get('qss_quake_world_dist', 1.0),
                falloff=light_obj.get('qss_quake_falloff', 0.0),
                unit_scale=light_obj.get('qss_quake_unit_scale', DEFAULT_QUAKE_UNIT_SCALE),
            )
            light_obj.data.energy = lighting_utils.scaled_quake_light_energy(
                preview['energy'], scale * manual_calibration
            )
            cycles_falloff_active = _qss_update_cycles_delay_falloff(
                light_obj, delay, light_obj.get('qss_quake_raw_light_value', raw_value)
            )
            cycles_exact_falloff = (
                str(getattr(scene.render, 'engine', '')) == 'CYCLES'
                and cycles_falloff_active
                and delay in {0, 5}
            )
            if hasattr(light_obj.data, 'use_custom_distance'):
                # Delay 5 has an infinite tail. Do not truncate it in Cycles;
                # Eevee retains its finite native-lamp range approximation.
                light_obj.data.use_custom_distance = not (
                    cycles_exact_falloff and delay == 5
                )
            if hasattr(light_obj.data, 'cutoff_distance'):
                light_obj.data.cutoff_distance = preview['cutoff_distance']
            if hasattr(light_obj.data, 'shadow_soft_size'):
                # A finite emitter radius changes the inverse-square base curve.
                # Keep exact Cycles sources point-sized; Eevee retains the
                # established soft-radius native-lamp approximation.
                light_obj.data.shadow_soft_size = (
                    0.0 if cycles_exact_falloff else preview['shadow_soft_size']
                )
            light_obj['qss_quake_live_preview_profile'] = preview['profile']
            light_obj['qss_quake_live_preview_reference_distance'] = preview['reference_distance']
        else:
            light_obj.data.energy = lighting_utils.scaled_quake_light_energy(
                raw_value, scale * manual_calibration
            )
        if range_scale <= 0.0:
            light_obj.data.energy = 0.0
        light_obj['qss_applied_energy_scale'] = scale
        light_obj['qss_applied_energy_calibration'] = manual_calibration
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
    collection = bpy.data.collections.new(collection_name)
    map_collection = bpy.data.collections.get(obj.get("qss_map_collection", ""))
    if map_collection is not None:
        map_collection.children.link(collection)
    else:
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
    obj['qss_manual_light_energy_calibration'] = float(
        obj.get('qss_manual_light_energy_calibration', 1.0)
    )
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
        light_obj['qss_quake_unit_scale'] = float(unit_scale)
        light_obj['qss_quake_world_range'] = float(world_range)
        light_obj['qss_quake_world_dist'] = float(world_dist)
        light_obj['qss_quake_anglescale'] = float(anglescale)
        light_obj['qss_applied_energy_scale'] = energy_scale
        light_obj['qss_quake_light_delay'] = int(_parse_entity_float(entity, 'delay', 0))
        light_obj['qss_quake_light_style'] = int(light_style)
        light_obj['qss_quake_style_was_inferred'] = bool(style_inferred)
        light_obj['qss_quake_color'] = list(color_rgb)
        light_obj['qss_energy_calibration'] = float(obj.get('qss_light_energy_calibration', 1.0))
        light_obj['qss_manual_energy_calibration'] = float(
            obj.get('qss_manual_light_energy_calibration', 1.0)
        )
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
        light_obj['qss_quake_delay_note'] = 'Cycles uses a per-light shader correction for delay 0 and 5; Eevee keeps the native-lamp approximation. Delay 2 uses native inverse-square falloff. Quake Direct remains a separate exact direct-light path.'
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
        sun_obj['qss_manual_energy_calibration'] = float(
            obj.get('qss_manual_light_energy_calibration', 1.0)
        )
        sun_obj['qss_energy_calibration'] = float(
            obj.get('qss_manual_light_energy_calibration', 1.0)
        )
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


class QSS_OT_edit_face_overlay_watch(Operator):
    bl_idname = "qss.edit_face_overlay_watch"
    bl_label = "Keep QSS Edit Mode Material Colors Clear"
    bl_description = "Temporarily hide Blender's face-fill selection overlay while editing a QSS map"

    def _finish_restore(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        try:
            overlay = self._space.overlay
            if bool(overlay.show_faces) != self._original_show_faces:
                overlay.show_faces = self._original_show_faces
            if hasattr(overlay, "show_floor") and bool(overlay.show_floor) != self._original_show_floor:
                overlay.show_floor = self._original_show_floor
            self._area.tag_redraw()
        except Exception:
            pass
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                self._window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None
        try:
            key = self._area.as_pointer()
            if _qss_edit_overlay_sessions.get(key) is self:
                _qss_edit_overlay_sessions.pop(key, None)
        except Exception:
            pass

    def invoke(self, context, event):
        area = context.area if context.area and context.area.type == "VIEW_3D" else None
        if area is None or context.object is None or not _qss_is_map_object(context.object):
            return {"CANCELLED"}
        previous = _qss_edit_overlay_sessions.get(area.as_pointer())
        if previous is not None:
            previous._finish_restore()
        self._area = area
        self._space = area.spaces.active
        self._object = context.object
        self._window_manager = context.window_manager
        self._original_show_faces = bool(self._space.overlay.show_faces)
        self._original_show_floor = bool(getattr(self._space.overlay, "show_floor", True))
        self._finished = False
        self._timer = None
        if context.mode == "EDIT_MESH":
            self._space.overlay.show_faces = False
        if hasattr(self._space.overlay, "show_floor"):
            self._space.overlay.show_floor = False
        try:
            self._timer = self._window_manager.event_timer_add(0.25, window=context.window)
            self._window_manager.modal_handler_add(self)
            _qss_edit_overlay_sessions[area.as_pointer()] = self
            area.tag_redraw()
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self._finish_restore()
            self.report({"WARNING"}, f"Could not manage the Edit Mode face overlay: {exc}")
            return {"CANCELLED"}

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}
        if event.type == "TIMER":
            try:
                active_object = getattr(context, "object", None)
                active_is_qss = _qss_is_map_object(active_object)
                if active_is_qss:
                    # A 3D View owns one watcher, not one watcher per map.
                    # Retarget it when the user imports or activates another BSP.
                    self._object = active_object
                else:
                    try:
                        previous_object_valid = (
                            self._object is not None
                            and bool(self._object.name)
                            and _qss_is_map_object(self._object)
                        )
                    except (ReferenceError, RuntimeError):
                        previous_object_valid = False
                    if not previous_object_valid:
                        self._finish_restore()
                        return {"FINISHED"}

                should_hide_faces = active_is_qss and context.mode == "EDIT_MESH"
                target_faces = False if should_hide_faces else self._original_show_faces
                target_floor = False if active_is_qss else self._original_show_floor
                overlay = self._space.overlay
                changed = False
                if bool(overlay.show_faces) != bool(target_faces):
                    overlay.show_faces = target_faces
                    changed = True
                if hasattr(overlay, "show_floor") and bool(overlay.show_floor) != bool(target_floor):
                    overlay.show_floor = target_floor
                    changed = True
                if changed:
                    self._area.tag_redraw()
            except Exception:
                self._finish_restore()
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish_restore()


def _qss_start_edit_face_overlay_watchers(context, obj):
    """Keep face-fill overlay off only while this imported map is in Edit Mode."""
    if not _qss_is_map_object(obj):
        return
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return
    for window in list(wm.windows):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            existing = _qss_edit_overlay_sessions.get(area.as_pointer())
            if existing is not None:
                # The area watcher must follow the active map. Without this,
                # importing a second BSP leaves it bound to the first map and
                # the timer turns the Edit Mode face-fill overlay back on.
                existing._object = obj
                try:
                    existing._space = area.spaces.active
                    existing._space.overlay.show_floor = False
                    if context.mode == "EDIT_MESH":
                        existing._space.overlay.show_faces = False
                    area.tag_redraw()
                except Exception as exc:
                    print(f"QSS: could not retarget the Edit Mode overlay watcher: {exc}")
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is None:
                continue
            try:
                with context.temp_override(
                    window=window, area=area, region=region,
                    object=obj, active_object=obj,
                ):
                    bpy.ops.qss.edit_face_overlay_watch("INVOKE_DEFAULT")
            except Exception as exc:
                print(f"QSS: could not start the Edit Mode overlay watcher: {exc}")


def _qss_enter_face_edit_mode(context, obj):
    """Finish BSP import in Edit Mode with Face Select active and nothing selected."""
    if not _qss_is_map_object(obj):
        return False
    try:
        import bmesh
        if getattr(obj, "mode", "OBJECT") != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected in list(context.selected_objects):
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        context.scene.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data)
        for face in bm.faces:
            face.select = False
        for edge in bm.edges:
            edge.select = False
        for vertex in bm.verts:
            vertex.select = False
        bm.select_history.clear()
        bm.faces.active = None
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        try:
            bpy.ops.mesh.select_mode(type="FACE")
        except Exception:
            context.scene.tool_settings.mesh_select_mode = (False, False, True)
        _qss_start_edit_face_overlay_watchers(context, obj)
        return True
    except Exception as exc:
        print(f"QSS: imported BSP but could not enter face-select Edit Mode: {exc}")
        return False


class QSS_OT_camera_transition(Operator):
    bl_idname = "qss.camera_transition"
    bl_label = "Smooth View Transition"
    bl_description = "Ease the active 3D View to a target location, rotation and distance"

    target_location: FloatVectorProperty(size=3, subtype="TRANSLATION")
    target_rotation: FloatVectorProperty(
        size=4, subtype="QUATERNION", default=(1.0, 0.0, 0.0, 0.0)
    )
    target_distance: FloatProperty(default=1.0, min=0.001)
    duration: FloatProperty(default=0.5, min=0.05, max=5.0)

    def _finish(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                self._window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None
        try:
            key = self._area.as_pointer()
            if _qss_camera_transition_sessions.get(key) is self:
                _qss_camera_transition_sessions.pop(key, None)
            self._area.tag_redraw()
        except Exception:
            pass

    def invoke(self, context, event):
        from mathutils import Quaternion, Vector
        area = context.area if context.area and context.area.type == "VIEW_3D" else None
        if area is None:
            self.report({"WARNING"}, "Smooth camera movement needs a 3D View.")
            return {"CANCELLED"}
        space = area.spaces.active
        if space is None or space.type != "VIEW_3D" or space.region_3d is None:
            return {"CANCELLED"}
        previous = _qss_camera_transition_sessions.get(area.as_pointer())
        if previous is not None:
            previous._finish()
        region = space.region_3d
        self._area = area
        self._space = space
        self._window_manager = context.window_manager
        self._start_location = region.view_location.copy()
        self._start_rotation = region.view_rotation.copy()
        self._start_distance = float(region.view_distance)
        self._target_location = Vector(self.target_location)
        self._target_rotation = Quaternion(self.target_rotation).normalized()
        self._target_distance = float(self.target_distance)
        self._started_at = time.perf_counter()
        self._duration = float(self.duration)
        self._finished = False
        self._timer = None
        try:
            self._timer = self._window_manager.event_timer_add(0.02, window=context.window)
            self._window_manager.modal_handler_add(self)
            _qss_camera_transition_sessions[area.as_pointer()] = self
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self._finish()
            self.report({"WARNING"}, f"Could not animate the viewport: {exc}")
            return {"CANCELLED"}

    def execute(self, context):
        from mathutils import Quaternion, Vector
        area = context.area if context.area and context.area.type == "VIEW_3D" else None
        if area is None:
            self.report({"WARNING"}, "Smooth camera movement needs a 3D View.")
            return {"CANCELLED"}
        region = area.spaces.active.region_3d
        region.view_location = Vector(self.target_location)
        region.view_rotation = Quaternion(self.target_rotation).normalized()
        region.view_distance = float(self.target_distance)
        area.tag_redraw()
        return {"FINISHED"}

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}
        if event.type == "TIMER":
            progress = min(1.0, max(
                0.0, (time.perf_counter() - self._started_at) / self._duration
            ))
            eased = progress * progress * (3.0 - 2.0 * progress)
            region = self._space.region_3d
            region.view_location = self._start_location.lerp(self._target_location, eased)
            region.view_rotation = self._start_rotation.slerp(self._target_rotation, eased)
            region.view_distance = (
                self._start_distance + (self._target_distance - self._start_distance) * eased
            )
            self._area.tag_redraw()
            if progress >= 1.0:
                self._finish()
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish()


def _qss_start_camera_transition(context, window, area, location, rotation, distance, duration=0.5):
    """Start the shared eased camera movement inside one 3D View area."""
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    if region is None:
        return False
    try:
        with context.temp_override(window=window, area=area, region=region):
            result = bpy.ops.qss.camera_transition(
                "INVOKE_DEFAULT",
                target_location=tuple(location),
                target_rotation=tuple(rotation),
                target_distance=float(distance),
                duration=float(duration),
            )
        return "CANCELLED" not in result
    except Exception as exc:
        print(f"QSS: could not start shared camera transition: {exc}")
        return False


def _frame_player_start(context, obj):
    """Ease every open 3D View to info_player_start using the shared camera transition."""
    if not obj or not obj.get('qss_has_player_start'):
        return False
    from mathutils import Vector
    position = Vector(obj.get('qss_player_start', (0.0, 0.0, 0.0)))
    yaw = math.radians(float(obj.get('qss_player_yaw', 0.0)))
    forward = Vector((math.cos(yaw), math.sin(yaw), 0.0))
    rotation = forward.to_track_quat('-Z', 'Y')
    distance = max(0.001, float(obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE)) * 0.5)
    window_manager = getattr(context, "window_manager", None)
    windows = list(window_manager.windows) if window_manager is not None else []
    if context.window is not None and all(window != context.window for window in windows):
        windows.append(context.window)
    changed = False
    seen_areas = set()
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D" or area.as_pointer() in seen_areas:
                continue
            seen_areas.add(area.as_pointer())
            space = area.spaces.active
            if space is None or space.type != "VIEW_3D":
                continue
            region_3d = space.region_3d
            region_3d.view_perspective = "PERSP"
            started = _qss_start_camera_transition(
                context, window, area, position, rotation, distance, duration=0.5
            )
            if not started:
                region_3d.view_rotation = rotation
                region_3d.view_location = position
                region_3d.view_distance = distance
            try:
                area.tag_redraw()
            except Exception:
                pass
            changed = True
    return changed

def _create_bsp_object(context, parsed, source_path, palette, game_dir, palette_file,
                       wad_textures=None, loose_textures=None, wad_sources=None, wad_unresolved=None, wad_failures=None,
                       unit_scale=DEFAULT_QUAKE_UNIT_SCALE, flip_z=False, lightmap_resolution=1):
    source_path = bpy.path.abspath(source_path)
    game_dir = bpy.path.abspath(game_dir) if game_dir else ""
    palette_file = bpy.path.abspath(palette_file) if palette_file else ""
    vertices = parsed.vertices()
    edges = parsed.edges()
    surfedges = parsed.surfedges()
    texinfos = parsed.texinfos()
    faces = parsed.faces()
    planes = parsed.planes()
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
            plane_id = int(face[0])
            if plane_id < 0 or plane_id >= len(planes):
                raise bsp.BSPError(f"BSP face {face_id} references invalid plane {plane_id}.")
            if bsp.face_winding_needs_reversal(
                positions, planes[plane_id][:3], side=face[1], flip_z=flip_z
            ):
                # Honour dface.side and the optional Z reflection. Without
                # this, faces whose surfedge winding disagrees with their
                # oriented plane import with inverted normals and can receive
                # almost no Cycles diffuse light.
                vertex_ids.reverse()
                positions.reverse()
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
    _qss_make_map_collection(context, obj, source_path)

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
        source_lit_rgb, lighting_data=atlas_lighting, resolution=lightmap_resolution
    )

    # Preserve the source BSP's original face indexing for the exporter.
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def _miptex_fullbright_mask(
    entry, width, height, fullbright_start=224, source_image=None
):
    """Recover fullbright texels from the source miptex or a sibling mask image."""
    if entry is not None and entry.blob is not None:
        try:
            _name_raw, source_width, source_height, o0, _o1, _o2, _o3 = struct.unpack_from(
                '<16s6I', entry.blob, 0
            )
            if (int(source_width), int(source_height)) == (int(width), int(height)):
                count = int(source_width) * int(source_height)
                if o0 > 0 and o0 + count <= len(entry.blob):
                    indices = entry.blob[o0:o0 + count]
                    return bytearray(
                        1 if fullbright_start <= index < 255 else 0
                        for index in indices
                    )
        except (struct.error, TypeError, ValueError):
            pass

    source_path = str(
        getattr(source_image, "filepath_raw", "")
        or getattr(source_image, "filepath", "")
        or ""
    ) if source_image is not None else ""
    if not source_path:
        return None
    try:
        source_path = bpy.path.abspath(source_path)
        if not os.path.isfile(source_path):
            return None
        mask, mask_image = _qss_read_fullbright_mask(source_path, width, height)
        if mask_image is not None:
            try:
                bpy.data.images.remove(mask_image, do_unlink=True)
            except Exception:
                pass
        return mask
    except Exception:
        return None


def _encode_image_to_miptex(
    image, palette, texture_name, *, fullbright_mask=None, settings=None
):
    """Encode a Blender texture with Slipgate's material-zone converter at every mip level."""
    width, height = int(image.size[0]), int(image.size[1])
    if width < 16 or height < 16 or width > 512 or height > 512:
        raise bsp.BSPError(
            f"Image '{image.name}' is {width}x{height}; export requires dimensions from 16 to 512."
        )
    if width & (width - 1) or height & (height - 1):
        raise bsp.BSPError(
            f"Image '{image.name}' is {width}x{height}; width and height must be powers of two."
        )
    try:
        width, height, rgba = _qss_image_pixels_to_rgba8(image)
        if settings is None:
            settings_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "quake_texture_converter.ini",
            )
            settings = palette_utils.load_settings(settings_path)
        mip_levels, _mip_stats = palette_utils.convert_rgba8_mip_chain(
            width, height, rgba, palette, settings,
            transparent=str(texture_name).startswith("{"),
            fullbright_mask=fullbright_mask,
        )
        return bsp.build_miptex_blob(texture_name, width, height, mip_levels)
    except Exception as exc:
        raise bsp.BSPError(
            f"Material-zone Quake palette conversion failed for '{image.name}': {exc}"
        ) from exc


def _safe_texture_name(value, fallback):
    value = str(value or fallback).strip()
    value = re.sub(r'[^A-Za-z0-9_*+\-]', '_', value)
    if not value:
        value = fallback
    return value[:15]


def _export_object(obj, output_path, lightmap_export_mode='CLASSIC'):
    if getattr(obj, 'mode', 'OBJECT') != 'OBJECT':
        raise bsp.BSPError("Switch to Object Mode before exporting the BSP. Edit Mode changes may not be synchronized to mesh face attributes.")
    if lightmap_export_mode not in {'CLASSIC', 'ENHANCED'}:
        raise bsp.BSPError(f"Unknown lightmap export mode: {lightmap_export_mode}")
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
    converter_settings_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "quake_texture_converter.ini",
    )
    converter_settings = palette_utils.load_settings(converter_settings_path)
    fullbright_start = int(converter_settings.get("fullbright_start", 224))
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
    new_texture_for_image = {}
    replacements = {}
    used_material_indices = {int(poly.material_index) for poly in mesh.polygons}
    for material_index, mat in enumerate(obj.data.materials):
        if material_index not in used_material_indices:
            continue
        if mat is None or 'qss_texture_index' not in mat:
            continue
        source_texture_id = int(mat.get('qss_texture_index', -2))
        image = _find_image(mat)
        if image is None:
            continue
        digest = _image_hash(image)
        baseline = image.get('qss_import_hash', '')
        if source_texture_id == -1:
            material_key = mat.as_pointer()
            image_key = image.as_pointer()
            if image_key not in new_texture_for_image:
                fallback = f"qss_{len(entries):05d}"
                tex_name = _safe_texture_name(mat.get('qss_export_name', ''), fallback)
                source_id = int(mat.get("qss_fullbright_source_texture_id", -1))
                source_entry = entries[source_id] if 0 <= source_id < len(entries) else None
                fullbright_mask = _miptex_fullbright_mask(
                    source_entry, image.size[0], image.size[1], fullbright_start, image
                )
                blob = _encode_image_to_miptex(
                    image, palette, tex_name, fullbright_mask=fullbright_mask,
                    settings=converter_settings,
                )
                texture_index = texture_export.allocate_image_texture_index(
                    entries, new_texture_for_image, image_key,
                    bsp.MipTexture(blob, tex_name, image.size[0], image.size[1]),
                )
                new_texture_for_image[image_key] = texture_index
            new_texture_for_material[material_key] = new_texture_for_image[image_key]
            continue
        if source_texture_id >= 0 and source_texture_id < len(entries) and digest != baseline:
            fallback = entries[source_texture_id].name or f"qss_{source_texture_id:05d}"
            tex_name = _safe_texture_name(mat.get('qss_export_name', ''), fallback)
            source_entry = entries[source_texture_id]
            fullbright_mask = _miptex_fullbright_mask(
                source_entry, image.size[0], image.size[1], fullbright_start, image
            )
            blob = _encode_image_to_miptex(
                image, palette, tex_name, fullbright_mask=fullbright_mask,
                settings=converter_settings,
            )
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
            # DECOUPLED_LM keeps the lightmap projection independent of this
            # face-local texture projection in BSPX-aware engines.
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
    lighting_lump, lit_file_data, lightmap_bspx_updates, new_faces_lump = _patch_lightmap_lump(
        obj, parsed, enhanced=(lightmap_export_mode == 'ENHANCED'),
        output_faces_lump=new_faces_lump,
        output_texinfo_lump=new_texinfo_lump,
    )
    new_lumps[bsp.LUMP_LIGHTING] = lighting_lump
    new_lumps[bsp.LUMP_FACES] = new_faces_lump
    new_bspx_lumps = dict(parsed.bspx_lumps)
    if lightmap_export_mode == 'ENHANCED':
        for obsolete_name in ('LMSHIFT', 'LMOFFSET', 'LMSTYLE16'):
            new_bspx_lumps.pop(obsolete_name, None)
    new_bspx_lumps.update(lightmap_bspx_updates)
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
    """Configure Blender's native Walk Navigation from the imported Quake map scale."""
    settings = navigation_utils.quake_walk_preferences(
        obj.get('qss_unit_scale', DEFAULT_QUAKE_UNIT_SCALE),
        getattr(context.scene, 'qss_nav_speed_quake', 640.0),
        getattr(context.scene, 'qss_nav_fast_factor', 4.0),
    )
    walk = context.preferences.inputs.walk_navigation
    for name, value in settings.items():
        setattr(walk, name, value)
    return settings


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
    bl_label = "Quake Walk / Noclip Navigation"
    bl_description = (
        "Start Blender's native first-person Walk Navigation with free flight. "
        "Move the mouse to look, WASD to fly, Q/E vertically, Shift to move faster. "
        "LMB confirms and exits; Esc or RMB cancels and restores the starting view"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        area = context.area
        obj = context.object
        return bool(
            area and area.type == "VIEW_3D"
            and obj and obj.type == "MESH"
            and obj.get("qss_object_role") == "quake_bsp29"
        )

    def _start_walk(self, context):
        area = context.area
        if area is None or area.type != "VIEW_3D":
            self.report({"WARNING"}, "Start Quake Walk Navigation from a 3D View.")
            return {"CANCELLED"}

        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        if region is None:
            self.report({"WARNING"}, "The 3D View has no usable window region.")
            return {"CANCELLED"}

        try:
            _configure_quake_walk_speed(context, context.object)
            # Sidebar buttons execute in the UI region. Blender's native
            # view3d.walk operator must run in the 3D View's WINDOW region.
            with context.temp_override(
                window=context.window,
                area=area,
                region=region,
            ):
                result = bpy.ops.view3d.walk("INVOKE_DEFAULT")
            if "CANCELLED" in result:
                raise RuntimeError("Blender could not start native Walk Navigation.")
        except Exception as exc:
            self.report({"ERROR"}, f"Could not start Quake Walk Navigation: {exc}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            "Quake free-fly active: mouse-look + WASD/QE; LMB exits, Esc or RMB cancels.",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        return self._start_walk(context)

    def execute(self, context):
        return self._start_walk(context)


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



class QSS_OT_confirm_import(Operator):
    bl_idname = "qss.confirm_import"
    bl_label = "Import BSP into Project"
    bl_description = "Choose whether to add the map or replace the active QSS map"

    filepath: StringProperty(subtype="FILE_PATH", options={"HIDDEN"})
    game_dir: StringProperty(subtype="DIR_PATH", options={"HIDDEN"})
    game_map_path: StringProperty(options={"HIDDEN"})
    unit_scale: FloatProperty(default=DEFAULT_QUAKE_UNIT_SCALE, min=0.0001, max=10.0, options={"HIDDEN"})
    flip_z: BoolProperty(default=False, options={"HIDDEN"})
    lightmap_resolution: EnumProperty(
        items=(("1", "1×", "Original working atlas resolution"),
               ("2", "2×", "Double working atlas resolution"),
               ("4", "4×", "Four times working atlas resolution"),
               ("8", "8×", "Eight times working atlas resolution")),
        default="1", options={"HIDDEN"},
    )
    import_action: EnumProperty(
        name="Import behaviour",
        items=(("ADD", "Add as new map", "Keep existing maps in their own collections"),
               ("REPLACE", "Replace active map", "Remove only the active QSS map after the new import succeeds")),
        default="ADD",
    )

    def invoke(self, context, event):
        self.import_action = "ADD"
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        layout = self.layout
        layout.label(text="A map is already loaded. What should QSS do with it?")
        layout.prop(self, "import_action", expand=True)
        layout.label(text="Add preserves existing maps. Replace removes only the active QSS map.", icon="INFO")

    def execute(self, context):
        result = bpy.ops.qss.import_bsp(
            "EXEC_DEFAULT",
            filepath=self.filepath,
            game_dir=self.game_dir,
            game_map_path=self.game_map_path,
            unit_scale=self.unit_scale,
            flip_z=self.flip_z,
            lightmap_resolution=self.lightmap_resolution,
            import_action=self.import_action,
            skip_import_prompt=True,
        )
        return {"CANCELLED"} if "CANCELLED" in result else {"FINISHED"}


class QSS_OT_import_bsp(Operator, ImportHelper):
    bl_idname = "qss.import_bsp"
    bl_label = "Import Quake BSP29"
    bl_description = "Import classic Quake BSP29 geometry, textures, entity lights and BSPX RGB lightmaps"
    filename_ext = ".bsp"
    filter_glob: StringProperty(default="*.bsp", options={'HIDDEN'})
    game_dir: StringProperty(name="Quake game directory", subtype='DIR_PATH', default="", options={'HIDDEN'})
    palette_file: StringProperty(name="palette.lmp (optional)", subtype='FILE_PATH', default="", options={'HIDDEN'})
    unit_scale: FloatProperty(
        name="Quake unit scale", description="Blender metres per Quake map unit",
        default=DEFAULT_QUAKE_UNIT_SCALE, min=0.0001, max=10.0, precision=5, options={'HIDDEN'}
    )
    flip_z: BoolProperty(
        name="Invert Z axis", description="Non-standard converter-generated BSPs only",
        default=False, options={'HIDDEN'}
    )
    lightmap_resolution: EnumProperty(
        name="Working lightmap resolution",
        description="Working paint-atlas scale; BSP source luxel density is unchanged",
        items=(('1', '1× · Original', 'Original packed atlas resolution'),
               ('2', '2×', 'Twice the pixels per axis'),
               ('4', '4×', 'Four times the pixels per axis'),
               ('8', '8×', 'Eight times the pixels per axis')),
        default='1', options={'HIDDEN'}
    )
    import_action: EnumProperty(
        name="Import behaviour",
        items=(('ADD', "Add as new map", "Keep existing maps in their own collections"),
               ('REPLACE', "Replace active map", "Replace only the active QSS map collection")),
        default='ADD', options={'HIDDEN'}
    )
    skip_import_prompt: BoolProperty(default=False, options={'HIDDEN'})
    game_map_path: StringProperty(default="", options={'HIDDEN'})

    def invoke(self, context, event):
        self.game_dir = context.scene.qss_game_dir
        self.unit_scale = float(getattr(context.scene, "qss_quake_unit_scale", DEFAULT_QUAKE_UNIT_SCALE))
        self.lightmap_resolution = getattr(context.scene, "qss_import_lightmap_resolution", "1")
        self.flip_z = False
        # Start in the active game's maps directory instead of making users
        # navigate from Blender's last unrelated file-browser location.
        game_dir = _qss_abspath(self.game_dir or "")
        maps_dir = os.path.join(game_dir, "maps") if game_dir else ""
        start_dir = maps_dir if maps_dir and os.path.isdir(maps_dir) else game_dir
        if start_dir and os.path.isdir(start_dir):
            self.filepath = os.path.join(start_dir, "")
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        self.layout.label(text="Uses the active Game / Mod and QSS project defaults.")

    def execute(self, context):
        settings = _qss_config_settings()
        existing_maps = _qss_scene_map_collections(context.scene)
        old_active_name = getattr(context.scene, "qss_active_map_collection", "")
        policy = str(settings.get("import_behavior", "ASK")).upper()
        if existing_maps and policy == "ASK" and not self.skip_import_prompt:
            return bpy.ops.qss.confirm_import(
                "INVOKE_DEFAULT",
                filepath=self.filepath,
                game_dir=self.game_dir,
                game_map_path=self.game_map_path,
                unit_scale=self.unit_scale,
                flip_z=self.flip_z,
                lightmap_resolution=self.lightmap_resolution,
            )
        if self.skip_import_prompt:
            policy = self.import_action
        if policy not in {"ADD", "REPLACE"}:
            policy = "ADD"
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
                unit_scale=self.unit_scale, flip_z=self.flip_z,
                lightmap_resolution=int(self.lightmap_resolution)
            )
            light_count, has_spawn = _import_bsp_entities(
                context, obj, parsed, self.unit_scale, self.flip_z
            )
            context.scene.qss_game_dir = game_dir
            context.scene.qss_quake_unit_scale = float(self.unit_scale)
            if self.game_map_path:
                obj["qss_game_map_path"] = self.game_map_path
            elif game_dir:
                try:
                    relative_map_path = os.path.relpath(os.path.abspath(source_path), os.path.abspath(game_dir))
                    if relative_map_path != os.pardir and not relative_map_path.startswith(os.pardir + os.sep):
                        obj["qss_game_map_path"] = relative_map_path.replace(os.sep, "/")
                except ValueError:
                    pass
            _qss_save_config(context.scene, last_source_bsp=source_path)
            _qss_activate_map_collection(context.scene, obj.get("qss_map_collection", ""), context)
            try:
                _set_lighting_preview(context, obj, "source")
            except Exception as preview_exc:
                print(f"QSS: imported map but could not set Original preview: {preview_exc}")
            _apply_map_view_clipping(context, obj)
            _frame_player_start(context, obj)
            _qss_enter_face_edit_mode(context, obj)
            if policy == "REPLACE" and old_active_name and old_active_name != obj.get("qss_map_collection", ""):
                _qss_remove_map_collection(context.scene, old_active_name)
            lit_source = obj.get('qss_source_lighting_source', 'Monochrome BSP lighting')
            lit_note = f" RGB lightmaps: {lit_source}." if obj.get('qss_lit_rgb_faces', 0) else " No RGB lightmaps found; atlas starts grayscale."
            texture_note = (f" Textures: {obj.get('qss_texture_embedded_count', 0)} embedded, "
                            f"{obj.get('qss_texture_wad_count', 0)} WAD, {obj.get('qss_texture_loose_count', 0)} external, "
                            f"{obj.get('qss_texture_white_count', 0)} white fallback.")
            spawn_note = " Spawn view set to info_player_start." if has_spawn else " No info_player_start found."
            resolution_note = f" Working lightmap: {obj.get('qss_lightmap_resolution', 1)}× ({obj.get('qss_lightmap_atlas_size', 0) * obj.get('qss_lightmap_resolution', 1)}²)." if obj.get('qss_lightmap_image_name') else ""
            _report(self, 'INFO', f"Imported {len(obj.data.polygons)} faces, {light_count} light entities. Palette: {palette_origin}.{texture_note}{lit_note}{resolution_note}{spawn_note}")
            return {'FINISHED'}
        except Exception as exc:
            _report(self, 'ERROR', str(exc))
            return {'CANCELLED'}


class QSS_OT_browse_game_maps(Operator):
    bl_idname = "qss.browse_game_maps"
    bl_label = "Browse Game Maps"
    bl_description = "Choose a BSP from loose maps or PAK archives in the selected Quake game folder"

    map_id: EnumProperty(name="BSP map", items=_qss_game_map_enum_items)

    def invoke(self, context, event):
        entries = quake_paths.discover_maps(context.scene.qss_game_dir)
        if not entries:
            self.report({'WARNING'}, "No BSP maps found in the selected game folder.")
            return {'CANCELLED'}
        global _qss_game_map_entries
        _qss_game_map_entries = entries
        self.map_id = entries[0]['id']
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Maps found: {len(_qss_game_map_entries)}")
        layout.prop(self, "map_id", text="Map")

    def execute(self, context):
        entry = next(
            (item for item in quake_paths.discover_maps(context.scene.qss_game_dir)
             if item['id'] == self.map_id),
            None,
        )
        if entry is None:
            self.report({'ERROR'}, "That game map is no longer available.")
            return {'CANCELLED'}
        try:
            cache_dir = bpy.utils.user_resource('DATAFILES', path=os.path.join('qss', 'maps'), create=True)
            map_path = quake_paths.extract_map(entry, cache_dir)
            result = bpy.ops.qss.import_bsp(
                'EXEC_DEFAULT',
                filepath=map_path,
                game_dir=context.scene.qss_game_dir,
                unit_scale=context.scene.qss_quake_unit_scale,
                lightmap_resolution=context.scene.qss_import_lightmap_resolution,
                game_map_path=entry["path"],
            )
            if 'CANCELLED' in result:
                raise RuntimeError("The QSS BSP importer cancelled the map import.")
            if 'RUNNING_MODAL' in result:
                self.report({'INFO'}, "Choose Add or Replace to continue importing the selected map.")
                return {'FINISHED'}
            imported_obj = context.view_layer.objects.active
            if _qss_is_map_object(imported_obj):
                imported_obj["qss_game_map_path"] = entry["path"]
            self.report({'INFO'}, f"Imported {entry['path']} from {entry['source_label']}.")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Could not import {entry['path']}: {exc}")
            return {'CANCELLED'}


class QSS_OT_validate_bsp_export(Operator, ImportHelper):
    bl_idname = "qss.validate_bsp_export"
    bl_label = "Validate BSP Export"
    bl_description = "Compare an exported BSP with its original source and validate its lightmaps and optional .lit sidecar"
    filename_ext = ".bsp"
    filter_glob: StringProperty(default="*.bsp", options={'HIDDEN'})
    source_bsp: StringProperty(name="Original / source BSP", subtype='FILE_PATH', default="")
    lit_file: StringProperty(name="Optional .lit sidecar", subtype='FILE_PATH', default="")

    def invoke(self, context, event):
        obj = context.object
        source = obj.get('qss_source_path', '') if _qss_is_map_object(obj) else ''
        if not source:
            source = _qss_load_config().get('last_source_bsp', '')
        self.source_bsp = source
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Choose the exported BSP in the file browser.")
        layout.prop(self, "source_bsp")
        layout.prop(self, "lit_file")

    def execute(self, context):
        source = bpy.path.abspath(self.source_bsp) if self.source_bsp else ''
        exported = bpy.path.abspath(self.filepath) if self.filepath else ''
        lit_path = bpy.path.abspath(self.lit_file) if self.lit_file else None
        try:
            if not source or not os.path.isfile(source):
                raise FileNotFoundError("Choose a valid original/source BSP in the operator options.")
            if not exported or not os.path.isfile(exported):
                raise FileNotFoundError("Choose a valid exported BSP.")
            report = export_validation.validate_export_pair(source, exported, lit_path)
            body = _qss_format_export_report(report)
            body = f"Original: {source}\nExported: {exported}\n\n" + body
            _qss_write_text_report("QSS_Export_Validation", body)
            _qss_save_config(context.scene, last_source_bsp=source)
            self.report({'INFO'}, "PASS: BSP export integrity checks. See Text datablock QSS_Export_Validation.")
            return {'FINISHED'}
        except (OSError, bsp.BSPError, ValueError) as exc:
            message = f"FAIL: {exc}"
            _qss_write_text_report(
                "QSS_Export_Validation",
                f"Original: {source}\nExported: {exported}\n\n{message}\n",
            )
            self.report({'ERROR'}, message[:240])
            return {'CANCELLED'}


class QSS_OT_scan_game_maps(Operator):
    bl_idname = "qss.scan_game_maps"
    bl_label = "Validate Maps in Game Folder"
    bl_description = "Run BSP29 structural/reference/lightmap validation on every discovered loose or PAK map"

    def execute(self, context):
        game_dir = _qss_abspath(context.scene.qss_game_dir or '')
        entries = quake_paths.discover_maps(game_dir)
        if not entries:
            self.report({'WARNING'}, "No loose or PAK BSP maps found in this game folder.")
            return {'CANCELLED'}
        lines = [f"QSS game-map validation: {game_dir}", f"Discovered maps: {len(entries)}", ""]
        passed = failed = 0
        for entry in entries:
            try:
                data = quake_paths.read_map_entry(entry)
                report = export_validation.validate_export_bytes(data, data)
                lines.append(
                    f"PASS  {entry['path']} [{entry['source_label']}] "
                    f"faces={report['faces']} textures={report['textures']}"
                )
                passed += 1
            except Exception as exc:
                lines.append(f"FAIL  {entry['path']} [{entry['source_label']}] :: {exc}")
                failed += 1
        lines.extend(["", f"Result: {passed} passed, {failed} failed"])
        _qss_write_text_report("QSS_Game_Map_Validation", "\n".join(lines) + "\n")
        if failed:
            self.report({'ERROR'}, f"Map scan finished: {passed} passed, {failed} failed. See QSS_Game_Map_Validation.")
        else:
            self.report({'INFO'}, f"Map scan passed: {passed} maps. See QSS_Game_Map_Validation.")
        return {'FINISHED'}


class QSS_OT_run_python_tests(Operator):
    bl_idname = "qss.run_python_tests"
    bl_label = "Run QSS Python Test Suite"
    bl_description = "Run the add-on's standalone unittest suite inside Blender and write its results to a Text datablock"

    def execute(self, context):
        import io
        import unittest

        tests_dir = os.path.join(os.path.dirname(__file__), "tests")
        if not os.path.isdir(tests_dir):
            self.report({'ERROR'}, "The installed QSS package does not contain its tests folder.")
            return {'CANCELLED'}
        stream = io.StringIO()
        try:
            suite = unittest.defaultTestLoader.discover(tests_dir, pattern="test_*.py")
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            output = stream.getvalue()
            failures = len(result.failures)
            errors = len(result.errors)
            skipped = len(getattr(result, "skipped", []))
            passed = result.testsRun - failures - errors - skipped
            summary = (
                f"QSS test suite: {passed} passed, {failures} failed, "
                f"{errors} errors, {skipped} skipped ({result.testsRun} total)"
            )
            body = summary + "\n\n" + output
            _qss_write_text_report("QSS_Python_Test_Report", body)
            if result.wasSuccessful():
                self.report({'INFO'}, summary + ". See QSS_Python_Test_Report.")
            else:
                self.report({'ERROR'}, summary + ". See QSS_Python_Test_Report.")
            return {'FINISHED'}
        except Exception as exc:
            body = stream.getvalue() + f"\nTest runner error: {exc}\n"
            _qss_write_text_report("QSS_Python_Test_Report", body)
            self.report({'ERROR'}, f"QSS test runner failed: {exc}")
            return {'CANCELLED'}


# Map-audit helpers. These deliberately use disposable Blender objects and files.
def _qss_audit_add_check(record, name, status, detail=""):
    record.setdefault("checks", []).append({
        "name": str(name), "status": str(status).upper(), "detail": str(detail)
    })
    if str(status).upper() in {"FAIL", "TIMEOUT", "ERROR"}:
        record["status"] = "FAIL"


def _qss_audit_context_override(context, obj=None):
    override = {
        "scene": context.scene,
        "view_layer": context.view_layer,
    }
    window = getattr(context, "window", None)
    if window is not None:
        override["window"] = window
        screen = getattr(window, "screen", None)
        areas = list(screen.areas) if screen else []
        area = next((item for item in areas if item.type == "VIEW_3D"), None)
        if area is not None:
            override["area"] = area
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is not None:
                override["region"] = region
    if obj is not None:
        override.update({
            "object": obj,
            "active_object": obj,
            "selected_objects": [obj],
            "selected_editable_objects": [obj],
        })
    return override


def _qss_audit_set_active(context, obj):
    for selected in list(context.selected_objects):
        try:
            selected.select_set(False)
        except Exception:
            pass
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _qss_audit_call(context, operator, obj=None, **kwargs):
    with context.temp_override(**_qss_audit_context_override(context, obj)):
        return operator("EXEC_DEFAULT", **kwargs)


def _qss_audit_external(record, label, result, log_directory):
    status = result.get("status", "ERROR")
    output = (result.get("stdout", "") or "")
    errors = result.get("stderr", "") or ""
    command = result.get("command", [])
    log_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") + ".log"
    log_path = os.path.join(log_directory, log_name)
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as handle:
            handle.write("$ " + " ".join(str(part) for part in command) + "\n")
            handle.write(output)
            if errors:
                handle.write("\n[stderr]\n" + errors)
    except OSError as exc:
        errors += f"\nCould not write tool log: {exc}"
    _qss_audit_add_check(
        record, label, status,
        f"exit={result.get('returncode')} · {result.get('duration_seconds', 0):.2f}s · log={log_path}"
        + (f" · {errors[-1000:]}" if errors else "")
    )
    record.setdefault("external_tools", []).append({
        "name": label, "status": status, "returncode": result.get("returncode"),
        "duration_seconds": result.get("duration_seconds", 0.0),
        "command": command, "log": log_path, "output_tail": output[-6000:],
        "error": errors[-2000:],
    })


def _qss_audit_run_external_tools(record, source_path, entry, game_dir, quake_root,
                                  output_dir, timeout, run_light, run_compile):
    tools_dir = _qss_abspath(getattr(bpy.context.scene, "qss_ericw_tools_dir", "") or "")
    tools = external_tools.discover_tools(tools_dir)
    log_dir = os.path.join(output_dir, "ericw_logs")
    os.makedirs(log_dir, exist_ok=True)
    if not tools_dir:
        _qss_audit_add_check(record, "ericw-tools", "SKIP", "No ericw-tools folder configured.")
        return

    bspinfo = tools.get("bspinfo", "")
    if bspinfo:
        result = external_tools.run_command(bspinfo, [source_path], timeout=min(timeout, 60))
        _qss_audit_external(record, "ericw bspinfo", result, log_dir)
    else:
        _qss_audit_add_check(record, "ericw bspinfo", "SKIP", "bspinfo executable not found in configured folder.")

    if run_light:
        light = tools.get("light", "")
        if not light:
            _qss_audit_add_check(record, "ericw light", "SKIP", "light executable not found.")
        else:
            copy_path = os.path.join(output_dir, "ericw_relight_input.bsp")
            try:
                shutil.copy2(source_path, copy_path)
                args = ["-verbose", "-nocolor"]
                if quake_root and os.path.isdir(quake_root):
                    args.extend(["-basedir", quake_root])
                if game_dir and os.path.isdir(game_dir):
                    args.extend(["-gamedir", game_dir])
                args.append(copy_path)
                result = external_tools.run_command(light, args, timeout=timeout, cwd=output_dir)
                _qss_audit_external(record, "ericw light disposable relight", result, log_dir)
                if result.get("status") == "PASS" and os.path.isfile(copy_path):
                    try:
                        with open(copy_path, "rb") as handle:
                            relit_data = handle.read()
                        checked = export_validation.validate_export_bytes(relit_data, relit_data)
                        _qss_audit_add_check(
                            record, "ericw light output BSP parse", "PASS",
                            f"faces={checked['faces']} textures={checked['textures']}"
                        )
                    except Exception as exc:
                        _qss_audit_add_check(record, "ericw light output BSP parse", "FAIL", exc)
            except Exception as exc:
                _qss_audit_add_check(record, "ericw light disposable relight", "FAIL", exc)

    if run_compile:
        qbsp = tools.get("qbsp", "")
        vis = tools.get("vis", "")
        light = tools.get("light", "")
        map_source = ""
        if entry.get("kind") == "loose":
            candidate = os.path.splitext(entry.get("file_path", ""))[0] + ".map"
            if os.path.isfile(candidate):
                map_source = candidate
        if not map_source:
            _qss_audit_add_check(
                record, "ericw qbsp/vis/light pipeline", "SKIP",
                "No sibling .map source file was found for this BSP."
            )
        elif not qbsp:
            _qss_audit_add_check(record, "ericw qbsp/vis/light pipeline", "SKIP", "qbsp executable not found.")
        else:
            compiled = os.path.join(output_dir, "ericw_compiled.bsp")
            args = ["-verbose"]
            if quake_root and os.path.isdir(quake_root):
                args.extend(["-basedir", quake_root])
            if game_dir and os.path.isdir(game_dir):
                args.extend(["-gamedir", game_dir])
            args.extend([map_source, compiled])
            qbsp_result = external_tools.run_command(qbsp, args, timeout=timeout, cwd=output_dir)
            _qss_audit_external(record, "ericw qbsp compile", qbsp_result, log_dir)
            if qbsp_result.get("status") == "PASS" and os.path.isfile(compiled):
                if vis:
                    result = external_tools.run_command(vis, ["-verbose", compiled],
                                                        timeout=timeout, cwd=output_dir)
                    _qss_audit_external(record, "ericw vis", result, log_dir)
                else:
                    _qss_audit_add_check(record, "ericw vis", "SKIP", "vis executable not found.")
                if light:
                    args = ["-verbose", "-nocolor"]
                    if quake_root and os.path.isdir(quake_root):
                        args.extend(["-basedir", quake_root])
                    if game_dir and os.path.isdir(game_dir):
                        args.extend(["-gamedir", game_dir])
                    args.append(compiled)
                    result = external_tools.run_command(light, args, timeout=timeout, cwd=output_dir)
                    _qss_audit_external(record, "ericw light compiled MAP", result, log_dir)
                else:
                    _qss_audit_add_check(record, "ericw light compiled MAP", "SKIP", "light executable not found.")
            elif qbsp_result.get("status") == "PASS":
                _qss_audit_add_check(record, "ericw qbsp output", "FAIL", "qbsp returned success but no BSP was written.")


def _qss_audit_map(context, entry, index, output_root, options):
    record = {
        "map": entry.get("path", ""),
        "source_kind": entry.get("kind", ""),
        "source_label": entry.get("source_label", ""),
        "source_size": int(entry.get("length", 0)),
        "status": "PASS",
        "checks": [],
        "metrics": {},
        "external_tools": [],
    }
    output_dir = os.path.join(
        output_root, f"{index:04d}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', os.path.basename(entry.get('path', 'map')))}"
    )
    os.makedirs(output_dir, exist_ok=True)
    original_active = context.view_layer.objects.active
    original_selected = list(context.selected_objects)
    original_engine = context.scene.render.engine
    original_world = context.scene.world
    original_mode = getattr(original_active, "mode", "OBJECT") if original_active else "OBJECT"
    before_object_ids = {item.as_pointer() for item in bpy.data.objects}
    before_mesh_ids = {item.as_pointer() for item in bpy.data.meshes}
    before_material_ids = {item.as_pointer() for item in bpy.data.materials}
    before_image_ids = {item.as_pointer() for item in bpy.data.images}
    viewport_states = []
    if context.screen is not None:
        for area in context.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = next((item for item in area.spaces if item.type == "VIEW_3D"), None)
            if space is None:
                continue
            region_3d = space.region_3d
            viewport_states.append({
                "space": space,
                "clip_start": float(space.clip_start),
                "clip_end": float(space.clip_end),
                "view_location": region_3d.view_location.copy(),
                "view_distance": float(region_3d.view_distance),
                "view_rotation": region_3d.view_rotation.copy(),
                "view_perspective": region_3d.view_perspective,
            })
    imported_obj = None
    test_obj = None
    source_path = ""
    try:
        # Parse the source before Blender import; this isolates malformed map files.
        data = quake_paths.read_map_entry(entry)
        structure = export_validation.validate_export_bytes(data, data)
        record["metrics"].update({
            "bsp_faces": structure.get("faces"),
            "bsp_textures": structure.get("textures"),
            "bsp_texinfos": structure.get("texinfos"),
            "classic_lighting_bytes": structure.get("classic_lighting_bytes"),
            "bspx_lumps": structure.get("bspx_lumps", []),
        })
        _qss_audit_add_check(
            record, "BSP29 structural / reference / lightmap validation", "PASS",
            f"faces={structure.get('faces')} · textures={structure.get('textures')} · "
            f"lighting={structure.get('classic_lighting_bytes')} bytes"
        )

        cache_dir = bpy.utils.user_resource("DATAFILES", path=os.path.join("qss", "maps"), create=True)
        source_path = quake_paths.extract_map(entry, cache_dir)
        record["materialized_source"] = source_path

        _qss_audit_run_external_tools(
            record, source_path, entry, _qss_abspath(context.scene.qss_game_dir or ""),
            _qss_abspath(context.scene.qss_quake_root or ""), output_dir,
            int(options.get("timeout", 300)), bool(options.get("ericw_light")),
            bool(options.get("ericw_compile")),
        )

        result = _qss_audit_call(
            context, bpy.ops.qss.import_bsp, None,
            filepath=source_path,
            game_dir=context.scene.qss_game_dir,
            unit_scale=context.scene.qss_quake_unit_scale,
            lightmap_resolution="1",
        )
        new_maps = [
            item for item in bpy.data.objects
            if item.as_pointer() not in before_object_ids and _qss_is_map_object(item)
        ]
        if "FINISHED" not in result or not new_maps:
            raise RuntimeError(f"QSS import did not produce a BSP object (operator result: {result}).")
        imported_obj = next(
            (item for item in new_maps if os.path.abspath(item.get("qss_source_path", "")) == os.path.abspath(source_path)),
            new_maps[-1],
        )
        imported_obj["qss_game_map_path"] = entry.get("path", "")
        mesh = imported_obj.data
        texture_uv = mesh.uv_layers.get("Quake_Texture_UV")
        light_uv = mesh.uv_layers.get("Quake_Lightmap_UV")
        face_id = mesh.attributes.get("qss_bsp_face_id")
        texinfo_id = mesh.attributes.get("qss_bsp_texinfo_id")
        total_faces = len(mesh.polygons)
        bad_material_faces = sum(
            1 for poly in mesh.polygons
            if poly.material_index < 0 or poly.material_index >= len(mesh.materials)
        )
        record["metrics"].update({
            "mesh_faces": total_faces,
            "vertices": len(mesh.vertices),
            "loops": len(mesh.loops),
            "materials": len(mesh.materials),
            "lights": int(imported_obj.get("qss_light_entity_count", 0)),
            "lightmap_faces": int(imported_obj.get("qss_lightmap_faces", 0)),
            "texture_uv_entries": len(texture_uv.data) if texture_uv else 0,
            "lightmap_uv_entries": len(light_uv.data) if light_uv else 0,
            "source_has_player_start": bool(imported_obj.get("qss_has_player_start")),
            "missing_textures": str(imported_obj.get("qss_missing_texture_names", "")),
        })
        _qss_audit_add_check(record, "QSS BSP import", "PASS",
                             f"{total_faces} Blender faces · {len(mesh.materials)} material slots")
        _qss_audit_add_check(
            record, "Face/material/UV metadata",
            "PASS" if (total_faces > 0 and face_id is not None and texinfo_id is not None
                       and len(face_id.data) == total_faces and len(texinfo_id.data) == total_faces
                       and texture_uv is not None and len(texture_uv.data) == len(mesh.loops)
                       and bad_material_faces == 0) else "FAIL",
            f"faces={total_faces} · face_ids={len(face_id.data) if face_id else 0} · "
            f"texinfo_ids={len(texinfo_id.data) if texinfo_id else 0} · "
            f"texture_uv={len(texture_uv.data) if texture_uv else 0}/{len(mesh.loops)} · "
            f"invalid_material_faces={bad_material_faces}"
        )
        lightmap_name = imported_obj.get("qss_lightmap_image_name", "")
        original_name = imported_obj.get("qss_original_lightmap_backup", "")
        lightmap_image = bpy.data.images.get(lightmap_name) if lightmap_name else None
        source_image = bpy.data.images.get(original_name) if original_name else None
        _qss_audit_add_check(
            record, "Original and editable lightmap images",
            "PASS" if (lightmap_image is not None and source_image is not None
                       and lightmap_image.size[0] > 0 and lightmap_image.size[1] > 0) else "FAIL",
            f"working={tuple(lightmap_image.size) if lightmap_image else 'missing'} · "
            f"original_snapshot={'present' if source_image else 'missing'}"
        )

        # Exercise the public lighting-preview operators and ensure they do not
        # mutate the immutable imported atlas.
        _qss_audit_set_active(context, imported_obj)
        preview_checks = [
            ("Original lightmap preview", bpy.ops.qss.preview_source_lightmaps, "source"),
            ("Working lightmap preview", bpy.ops.qss.preview_bsp_lightmaps, "baked"),
        ]
        if source_image is not None:
            source_hash_before = _image_hash(source_image)
        else:
            source_hash_before = ""
        for label, operator, expected_mode in preview_checks:
            op_result = _qss_audit_call(context, operator, imported_obj)
            good = ("FINISHED" in op_result and imported_obj.get("qss_preview_mode") == expected_mode)
            _qss_audit_add_check(record, label, "PASS" if good else "FAIL",
                                 f"operator={op_result} · mode={imported_obj.get('qss_preview_mode')}")
        if int(imported_obj.get("qss_light_entity_count", 0)) > 0:
            op_result = _qss_audit_call(context, bpy.ops.qss.preview_imported_lights, imported_obj)
            good = ("FINISHED" in op_result and imported_obj.get("qss_preview_mode") == "realtime")
            _qss_audit_add_check(record, "Live imported-light preview", "PASS" if good else "FAIL",
                                 f"operator={op_result} · mode={imported_obj.get('qss_preview_mode')}")
            # Return through the public source-preview operator so QSS restores
            # the user's render engine/world state before the temporary import is removed.
            _qss_audit_call(context, bpy.ops.qss.preview_source_lightmaps, imported_obj)
        else:
            _qss_audit_add_check(record, "Live imported-light preview", "SKIP",
                                 "This map contains no imported point/spot lights.")
        if source_image is not None:
            unchanged = _image_hash(source_image) == source_hash_before
            _qss_audit_add_check(record, "Preview source atlas immutability",
                                 "PASS" if unchanged else "FAIL",
                                 "Original RGB snapshot unchanged." if unchanged else "Original RGB snapshot changed.")
        op_result = _qss_audit_call(context, bpy.ops.qss.refresh_lightmap_preview, imported_obj)
        _qss_audit_add_check(record, "Repair lightmap material links",
                             "PASS" if "FINISHED" in op_result else "FAIL",
                             f"operator={op_result} · valid_uv_faces={imported_obj.get('qss_lightmap_uv_valid_faces', 0)}")

        # Optional direct light solver. It is deliberately opt-in because each
        # real BSP luxel may require visibility rays against the imported mesh.
        if options.get("quake_bake"):
            if int(imported_obj.get("qss_light_entity_count", 0)) > 0:
                source_before_direct_bake = bpy.data.images.get(imported_obj.get("qss_original_lightmap_backup", ""))
                source_before_hash = _image_hash(source_before_direct_bake) if source_before_direct_bake else ""
                op_result = _qss_audit_call(context, bpy.ops.qss.quake_direct_bake, imported_obj)
                baked = ("FINISHED" in op_result
                         and imported_obj.get("qss_lightmap_source") == "quake_direct_cpu_bake")
                _qss_audit_add_check(record, "Quake Direct Lightmap Solver",
                                     "PASS" if baked else "FAIL",
                                     f"operator={op_result} · luxels={imported_obj.get('qss_last_quake_bake_luxels', 'n/a')} · "
                                     f"lit={imported_obj.get('qss_last_quake_bake_lit_luxels', 'n/a')} · "
                                     f"rays={imported_obj.get('qss_last_quake_bake_ray_tests', 'n/a')} · "
                                     f"error={imported_obj.get('qss_last_quake_bake_error', '')}")
                restore_result = _qss_audit_call(context, bpy.ops.qss.restore_original_lightmap, imported_obj)
                restored_working = bpy.data.images.get(imported_obj.get("qss_lightmap_image_name", ""))
                restored_hash = _image_hash(restored_working) if restored_working else ""
                restore_good = "FINISHED" in restore_result and restored_hash == source_before_hash
                _qss_audit_add_check(record, "Restore original after Quake bake",
                                     "PASS" if restore_good else "FAIL",
                                     f"operator={restore_result} · exact_source_match={restored_hash == source_before_hash}")
            else:
                _qss_audit_add_check(record, "Quake Direct Lightmap Solver", "SKIP",
                                     "No Quake light entities are present.")
        else:
            _qss_audit_add_check(record, "Quake Direct Lightmap Solver", "SKIP",
                                 "Enable the optional full lighting bake in QSS audit settings.")

        # Clone the imported object and mesh: selection, hide/reveal, detachment
        # and texture-paint mode transitions must never alter the imported source.
        test_obj = imported_obj.copy()
        test_obj.data = imported_obj.data.copy()
        # Copy material datablocks too: paint-target and node changes on the test
        # object must not leak into the imported reference object.
        material_copies = {}
        for slot_index, material in enumerate(list(test_obj.data.materials)):
            if material is None:
                continue
            pointer = material.as_pointer()
            if pointer not in material_copies:
                material_copies[pointer] = material.copy()
            test_obj.data.materials[slot_index] = material_copies[pointer]
        test_obj.name = "QSS_AUDIT_" + os.path.basename(entry.get("path", "map"))
        context.scene.collection.objects.link(test_obj)
        _qss_audit_set_active(context, test_obj)

        view3d = next((area for area in context.screen.areas if area.type == "VIEW_3D"), None) if context.screen else None
        if view3d is not None:
            try:
                with context.temp_override(**_qss_audit_context_override(context, test_obj)):
                    bpy.ops.object.mode_set(mode="EDIT")
                    import bmesh
                    bm = bmesh.from_edit_mesh(test_obj.data)
                    bm.faces.ensure_lookup_table()
                    if bm.faces:
                        for face in bm.faces:
                            face.select_set(False)
                        bm.faces[0].select_set(True)
                        bm.faces.active = bm.faces[0]
                        bmesh.update_edit_mesh(test_obj.data, loop_triangles=False, destructive=False)
                        isolate_result = bpy.ops.qss.isolate_faces("EXEC_DEFAULT")
                        hidden_count = sum(1 for face in bm.faces if face.hide)
                        reveal_result = bpy.ops.qss.reveal_faces("EXEC_DEFAULT")
                        revealed_count = sum(1 for face in bm.faces if face.hide)
                        good = ("FINISHED" in isolate_result and "FINISHED" in reveal_result and revealed_count == 0)
                        _qss_audit_add_check(
                            record, "Isolate / reveal selected faces", "PASS" if good else "FAIL",
                            f"isolate={isolate_result} · hidden_after_isolate={hidden_count} · "
                            f"reveal={reveal_result} · hidden_after_reveal={revealed_count}"
                        )
                    else:
                        _qss_audit_add_check(record, "Isolate / reveal selected faces", "SKIP", "Mesh has no faces.")
                    bpy.ops.object.mode_set(mode="OBJECT")
                    if test_obj.data.polygons:
                        for poly in test_obj.data.polygons:
                            poly.select = False
                        test_obj.data.polygons[0].select = True
                        frame_result = bpy.ops.qss.frame_selection("EXEC_DEFAULT")
                        _qss_audit_add_check(record, "Focus selected face",
                                             "PASS" if "FINISHED" in frame_result else "FAIL",
                                             f"operator={frame_result}")
                        clip_result = bpy.ops.qss.optimize_view_clipping("EXEC_DEFAULT")
                        _qss_audit_add_check(record, "Optimize view clipping",
                                             "PASS" if "FINISHED" in clip_result else "FAIL",
                                             f"operator={clip_result}")
                        _qss_audit_add_check(record, "FPS / Walk Navigation",
                                             "SKIP", "The walk operator is modal and requires real keyboard/mouse input.")
                    else:
                        _qss_audit_add_check(record, "Focus selected face", "SKIP", "Mesh has no faces.")
                    if test_obj.get("qss_has_player_start"):
                        spawn_result = bpy.ops.qss.goto_player_start("EXEC_DEFAULT")
                        _qss_audit_add_check(record, "Go to info_player_start",
                                             "PASS" if "FINISHED" in spawn_result else "FAIL",
                                             f"operator={spawn_result}")
                    else:
                        _qss_audit_add_check(record, "Go to info_player_start", "SKIP",
                                             "No info_player_start was imported.")
            except Exception as exc:
                try:
                    if test_obj.mode != "OBJECT":
                        bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
                _qss_audit_add_check(record, "Viewport navigation operations", "FAIL",
                                     f"{exc}\n{traceback.format_exc()[-3000:]}")
        else:
            _qss_audit_add_check(record, "Viewport navigation operations", "SKIP",
                                 "No VIEW_3D area is available in this Blender session.")

        # Optional Cycles bake on the isolated duplicate. Undo must restore the
        # exact pre-bake atlas; this is deliberately opt-in due to render cost.
        if options.get("cycles_bake"):
            if int(test_obj.get("qss_light_entity_count", 0)) > 0:
                before_cycles_image = bpy.data.images.get(test_obj.get("qss_lightmap_image_name", ""))
                before_cycles_hash = _image_hash(before_cycles_image) if before_cycles_image else ""
                cycles_result = _qss_audit_call(context, bpy.ops.qss.bake_scene_lights, test_obj)
                has_backup = bool(test_obj.get("qss_last_bake_backup"))
                _qss_audit_add_check(
                    record, "Cycles PBR lightmap bake",
                    "PASS" if ("FINISHED" in cycles_result and has_backup) else "FAIL",
                    f"operator={cycles_result} · backup_created={has_backup} · "
                    f"raw_mean={test_obj.get('qss_last_bake_raw_mean', 'n/a')} · "
                    f"sampled_luxels={test_obj.get('qss_last_bake_attempt_sample_count', 'n/a')} · "
                    f"error={test_obj.get('qss_last_bake_error', '')}"
                )
                if has_backup:
                    undo_result = _qss_audit_call(context, bpy.ops.qss.undo_last_bake, test_obj)
                    restored_image = bpy.data.images.get(test_obj.get("qss_lightmap_image_name", ""))
                    restored_hash = _image_hash(restored_image) if restored_image else ""
                    restored = ("FINISHED" in undo_result and restored_hash == before_cycles_hash)
                    _qss_audit_add_check(
                        record, "Undo Cycles bake restores exact atlas",
                        "PASS" if restored else "FAIL",
                        f"operator={undo_result} · hash_restored={restored}"
                    )
            else:
                _qss_audit_add_check(record, "Cycles PBR lightmap bake", "SKIP",
                                     "No imported Quake light entities are present.")
        else:
            _qss_audit_add_check(record, "Cycles PBR lightmap bake", "SKIP",
                                 "Enable the optional Cycles bake in QSS audit settings.")

        # Face-local detach and paint-mode transitions are run on the disposable clone.
        if test_obj.mode != "OBJECT":
            with context.temp_override(**_qss_audit_context_override(context, test_obj)):
                bpy.ops.object.mode_set(mode="OBJECT")
        candidate_face = None
        detached = False
        for poly in test_obj.data.polygons:
            slot = int(poly.material_index)
            if 0 <= slot < len(test_obj.data.materials):
                material = test_obj.data.materials[slot]
                if material and _find_image(material, "base_texture") is not None:
                    candidate_face = int(poly.index)
                    break
        if candidate_face is None:
            _qss_audit_add_check(record, "Detach selected face", "SKIP",
                                 "No face with an imported paintable base texture was found.")
        else:
            for poly in test_obj.data.polygons:
                poly.select = False
            test_obj.data.polygons[candidate_face].select = True
            material_count_before = len(test_obj.data.materials)
            detach_result = _qss_audit_call(context, bpy.ops.qss.detach_selected_faces, test_obj)
            detached_index = int(test_obj.data.polygons[candidate_face].material_index)
            detached_material = (test_obj.data.materials[detached_index]
                                 if 0 <= detached_index < len(test_obj.data.materials) else None)
            detached = ("FINISHED" in detach_result and len(test_obj.data.materials) > material_count_before
                        and detached_material is not None
                        and bool(detached_material.get("qss_face_local_projection")))
            _qss_audit_add_check(record, "Detach selected face", "PASS" if detached else "FAIL",
                                 f"operator={detach_result} · material_slots={material_count_before}->"
                                 f"{len(test_obj.data.materials)} · face_local={bool(detached_material and detached_material.get('qss_face_local_projection'))}")
            if detached and view3d is not None:
                try:
                    paint_result = _qss_audit_call(context, bpy.ops.qss.activate_texture_paint, test_obj)
                    paint_good = "FINISHED" in paint_result and test_obj.mode == "TEXTURE_PAINT"
                    _qss_audit_add_check(record, "Enter texture paint on detached face",
                                         "PASS" if paint_good else "FAIL",
                                         f"operator={paint_result} · mode={test_obj.mode}")
                    if test_obj.mode != "OBJECT":
                        with context.temp_override(**_qss_audit_context_override(context, test_obj)):
                            bpy.ops.object.mode_set(mode="OBJECT")
                except Exception as exc:
                    _qss_audit_add_check(record, "Enter texture paint on detached face", "FAIL", exc)
            elif detached:
                _qss_audit_add_check(record, "Enter texture paint on detached face", "SKIP",
                                     "Requires a VIEW_3D area.")
        # The lightmap paint operator requires a selected face with a valid luxel island.
        has_data = test_obj.data.attributes.get("qss_lm_has_data")
        lit_face = None
        if has_data is not None and len(has_data.data) == len(test_obj.data.polygons):
            lit_face = next((i for i, item in enumerate(has_data.data) if bool(item.value)), None)
        if lit_face is not None and view3d is not None:
            for poly in test_obj.data.polygons:
                poly.select = False
            test_obj.data.polygons[int(lit_face)].select = True
            try:
                light_paint_result = _qss_audit_call(context, bpy.ops.qss.activate_lightmap_paint, test_obj)
                light_paint_good = "FINISHED" in light_paint_result and test_obj.mode == "TEXTURE_PAINT"
                _qss_audit_add_check(record, "Enter lightmap paint", "PASS" if light_paint_good else "FAIL",
                                     f"operator={light_paint_result} · mode={test_obj.mode}")
            except Exception as exc:
                _qss_audit_add_check(record, "Enter lightmap paint", "FAIL", exc)
            finally:
                try:
                    if test_obj.mode != "OBJECT":
                        with context.temp_override(**_qss_audit_context_override(context, test_obj)):
                            bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
        else:
            _qss_audit_add_check(record, "Enter lightmap paint", "SKIP",
                                 "No lightmapped face or no VIEW_3D area.")

        # Classic export exercises the same public operator used by the user.
        _qss_audit_set_active(context, imported_obj)
        classic_path = os.path.join(output_dir, "qss_classic_export.bsp")
        export_result = _qss_audit_call(
            context, bpy.ops.qss.export_bsp, imported_obj,
            filepath=classic_path, lightmap_export_mode="CLASSIC"
        )
        if "FINISHED" in export_result and os.path.isfile(classic_path):
            try:
                validation = export_validation.validate_export_pair(source_path, classic_path)
                _qss_audit_add_check(record, "Classic BSP29 export + integrity validator", "PASS",
                                     f"faces={validation.get('faces')} · textures={validation.get('textures')} · "
                                     f"lit={validation.get('external_lit')}")
                record["classic_export"] = classic_path
            except Exception as exc:
                _qss_audit_add_check(record, "Classic BSP29 export + integrity validator", "FAIL", exc)
        else:
            _qss_audit_add_check(record, "Classic BSP29 export + integrity validator", "FAIL",
                                 f"export operator={export_result} · file_exists={os.path.isfile(classic_path)}")

        # Export the detached clone too, proving new face-local materials can be serialized.
        if detached:
            detached_path = os.path.join(output_dir, "qss_detached_export.bsp")
            try:
                _export_object(test_obj, detached_path, "CLASSIC")
                validation = export_validation.validate_export_pair(source_path, detached_path)
                _qss_audit_add_check(record, "Detached-face BSP export + integrity validator", "PASS",
                                     f"faces={validation.get('faces')} · textures={validation.get('textures')}")
                record["detached_export"] = detached_path
            except Exception as exc:
                _qss_audit_add_check(record, "Detached-face BSP export + integrity validator", "FAIL", exc)

        if options.get("enhanced_export"):
            enhanced_path = os.path.join(output_dir, "qss_enhanced_export.bsp")
            try:
                _export_object(imported_obj, enhanced_path, "ENHANCED")
                validation = export_validation.validate_export_pair(source_path, enhanced_path)
                _qss_audit_add_check(record, "Enhanced BSPX export + integrity validator", "PASS",
                                     f"RGB samples={validation.get('enhanced_lighting_samples')}")
                record["enhanced_export"] = enhanced_path
            except Exception as exc:
                message = str(exc)
                expected_limit = any(token in message.lower() for token in (
                    "enhanced", "bspx", "decoupled_lm", "texinfo projection", "lmshift"
                ))
                _qss_audit_add_check(record, "Enhanced BSPX export",
                                     "SKIP" if expected_limit else "FAIL", message)
        else:
            _qss_audit_add_check(record, "Enhanced BSPX export", "SKIP",
                                 "Disabled in QSS audit settings.")

        record["result_counts"] = {
            state: sum(1 for check in record["checks"] if check["status"] == state)
            for state in ("PASS", "FAIL", "SKIP", "TIMEOUT", "ERROR", "MISSING")
        }
        if any(check["status"] == "FAIL" for check in record["checks"]):
            record["status"] = "FAIL"
        return record

    except Exception as exc:
        _qss_audit_add_check(record, "Map audit runner", "FAIL",
                             f"{exc}\n{traceback.format_exc()[-5000:]}")
        record["status"] = "FAIL"
        return record
    finally:
        # Restore preview/render state before deleting the temporary QSS object.
        if imported_obj is not None:
            try:
                if bpy.data.objects.get(imported_obj.name) is not None:
                    _qss_audit_set_active(context, imported_obj)
                    if bpy.data.images.get(imported_obj.get("qss_original_lightmap_backup", "")):
                        _qss_audit_call(context, bpy.ops.qss.preview_source_lightmaps, imported_obj)
            except Exception:
                pass
        for obj in list(bpy.data.objects):
            if obj.as_pointer() not in before_object_ids:
                try:
                    bpy.data.objects.remove(obj, do_unlink=True)
                except Exception:
                    pass
        # Remove only datablocks created by this map's import/tests and now orphaned.
        for collection, previous in (
            (bpy.data.meshes, before_mesh_ids),
            (bpy.data.materials, before_material_ids),
            (bpy.data.images, before_image_ids),
        ):
            for block in list(collection):
                if block.as_pointer() not in previous and getattr(block, "users", 0) == 0:
                    try:
                        collection.remove(block)
                    except Exception:
                        pass
        try:
            for state in viewport_states:
                try:
                    space = state["space"]
                    space.clip_start = state["clip_start"]
                    space.clip_end = state["clip_end"]
                    region_3d = space.region_3d
                    region_3d.view_location = state["view_location"]
                    region_3d.view_distance = state["view_distance"]
                    region_3d.view_rotation = state["view_rotation"]
                    region_3d.view_perspective = state["view_perspective"]
                except Exception:
                    pass
            context.scene.render.engine = original_engine
            context.scene.world = original_world
            for selected in list(context.selected_objects):
                selected.select_set(False)
            for selected in original_selected:
                if bpy.data.objects.get(selected.name) is not None:
                    selected.select_set(True)
            if original_active is not None and bpy.data.objects.get(original_active.name) is not None:
                context.view_layer.objects.active = original_active
                if original_mode == "EDIT" and original_active.type == "MESH":
                    with context.temp_override(**_qss_audit_context_override(context, original_active)):
                        bpy.ops.object.mode_set(mode="EDIT")
        except Exception:
            pass


class QSS_OT_run_map_audit(Operator):
    bl_idname = "qss.run_map_audit"
    bl_label = "Run Full Map Audit"
    bl_description = "Import every discovered map, exercise QSS workflows, export/validate, and capture optional ericw-tools diagnostics"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene and getattr(context.scene, "qss_game_dir", ""))

    def _begin(self, context):
        self._saved_active = context.view_layer.objects.active
        self._saved_mode = getattr(self._saved_active, "mode", "OBJECT") if self._saved_active else "OBJECT"
        game_dir = _qss_abspath(context.scene.qss_game_dir or "")
        self._entries = quake_paths.discover_maps(game_dir)
        if not self._entries:
            self.report({"WARNING"}, "No loose or PAK maps found in the active game folder.")
            return False
        if self._saved_active is not None and self._saved_mode != "OBJECT":
            with context.temp_override(**_qss_audit_context_override(context, self._saved_active)):
                bpy.ops.object.mode_set(mode="OBJECT")
        root_dir = bpy.utils.user_resource("DATAFILES", path=os.path.join("qss", "audits"), create=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self._output_root = os.path.join(root_dir, "Map_Audit_" + stamp)
        os.makedirs(self._output_root, exist_ok=True)
        self._index = 0
        self._records = []
        self._options = {
            "enhanced_export": bool(context.scene.qss_audit_enhanced_export),
            "quake_bake": bool(context.scene.qss_audit_quake_bake),
            "cycles_bake": bool(context.scene.qss_audit_cycles_bake),
            "ericw_light": bool(context.scene.qss_audit_ericw_light),
            "ericw_compile": bool(context.scene.qss_audit_ericw_compile),
            "timeout": int(context.scene.qss_audit_timeout),
        }
        self._metadata = {
            "qss_version": ".".join(str(part) for part in ADDON_VERSION),
            "blender_version": bpy.app.version_string,
            "game_dir": game_dir,
            "quake_root": _qss_abspath(context.scene.qss_quake_root or ""),
            "ericw_tools_dir": _qss_abspath(context.scene.qss_ericw_tools_dir or ""),
            "ironwail_executable": _qss_abspath(context.scene.qss_ironwail_executable or ""),
            "options": dict(self._options),
            "started": stamp,
            "discovered_maps": len(self._entries),
        }
        # Run the pure-Python regression suite once per audit, not once per map.
        try:
            test_result = bpy.ops.qss.run_python_tests("EXEC_DEFAULT")
            text_block = bpy.data.texts.get("QSS_Python_Test_Report")
            test_text = text_block.as_string() if text_block else ""
            status = "PASS" if "failed, 0 errors" in test_text and "0 failed" in test_text else (
                "PASS" if "0 failed, 0 errors" in test_text else "FAIL"
            )
            self._global_checks = [{
                "name": "QSS standalone Python test suite", "status": status,
                "detail": f"operator={test_result}; report=QSS_Python_Test_Report; {test_text.splitlines()[0] if test_text else 'no report'}"
            }]
        except Exception as exc:
            self._global_checks = [{
                "name": "QSS standalone Python test suite", "status": "FAIL", "detail": str(exc)
            }]
        return True

    def _save_report(self, context, cancelled=False):
        from datetime import datetime
        report = {
            "schema_version": 1,
            "metadata": dict(self._metadata),
            "global_checks": list(self._global_checks),
            "cancelled": bool(cancelled),
            "completed": datetime.now().astimezone().isoformat(timespec="seconds"),
            "maps": list(self._records),
        }
        counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        for item in self._records:
            counts[item.get("status", "FAIL")] = counts.get(item.get("status", "FAIL"), 0) + 1
        report["summary"] = {
            "maps_total": len(self._entries),
            "maps_processed": len(self._records),
            "maps_passed": counts["PASS"],
            "maps_failed": counts["FAIL"],
            "maps_cancelled_or_remaining": max(0, len(self._entries) - len(self._records)),
        }
        report_json = os.path.join(self._output_root, "report.json")
        with open(report_json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
        lines = [
            "QUAKE SURFACE STUDIO — AUTOMATED MAP AUDIT",
            f"QSS {self._metadata['qss_version']} · Blender {self._metadata['blender_version']}",
            f"Game: {self._metadata['game_dir']}",
            f"Maps: {report['summary']['maps_processed']}/{report['summary']['maps_total']} processed · "
            f"{counts['PASS']} map pass · {counts['FAIL']} map fail",
            f"Cancelled: {bool(cancelled)}",
            "",
            "GLOBAL CHECKS",
        ]
        lines.extend(f"{item['status']:6} {item['name']}: {item['detail']}" for item in self._global_checks)
        for item in self._records:
            lines.extend(["", "=" * 72, f"{item['status']}  {item['map']} [{item['source_label']}]"])
            if item.get("metrics"):
                lines.append("METRICS " + json.dumps(item["metrics"], ensure_ascii=False, default=str))
            for check in item.get("checks", []):
                lines.append(f"{check['status']:7} {check['name']}: {check['detail']}")
        report_text = "\n".join(lines) + "\n"
        report_path = os.path.join(self._output_root, "report.txt")
        with open(report_path, "w", encoding="utf-8", errors="replace") as handle:
            handle.write(report_text)
        _qss_write_text_report("QSS_Map_Audit_Report", report_text)
        _qss_write_text_report("QSS_Map_Audit_JSON", json.dumps(report, indent=2, ensure_ascii=False, default=str))
        try:
            if self._saved_active is not None and bpy.data.objects.get(self._saved_active.name) is not None:
                context.view_layer.objects.active = self._saved_active
                if self._saved_mode == "EDIT" and self._saved_active.type == "MESH":
                    with context.temp_override(**_qss_audit_context_override(context, self._saved_active)):
                        bpy.ops.object.mode_set(mode="EDIT")
                elif self._saved_mode == "TEXTURE_PAINT" and self._saved_active.type == "MESH":
                    with context.temp_override(**_qss_audit_context_override(context, self._saved_active)):
                        bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
        except Exception as exc:
            print(f"QSS audit could not restore the original interaction mode: {exc}")
        self._report_json = report_json
        self._report_text = report_path
        return report

    def _process_next(self, context):
        index = self._index
        entry = self._entries[index]
        try:
            record = _qss_audit_map(context, entry, index + 1, self._output_root, self._options)
        except Exception as exc:
            record = {
                "map": entry.get("path", ""), "status": "FAIL",
                "checks": [{"name": "Unhandled map audit exception", "status": "FAIL",
                            "detail": f"{exc}\n{traceback.format_exc()[-5000:]}"}],
            }
        self._records.append(record)
        self._index += 1
        # Checkpoint after every map, so a Blender crash cannot erase completed work.
        try:
            with open(os.path.join(self._output_root, "progress.json"), "w", encoding="utf-8") as handle:
                json.dump({"metadata": self._metadata, "processed": self._index,
                           "total": len(self._entries), "maps": self._records},
                          handle, indent=2, ensure_ascii=False, default=str)
        except OSError as exc:
            print(f"QSS audit checkpoint warning: {exc}")

    def invoke(self, context, event):
        if not self._begin(context):
            return {"CANCELLED"}
        wm = context.window_manager
        wm.progress_begin(0, len(self._entries))
        self._timer = wm.event_timer_add(0.15, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, f"QSS map audit started: {len(self._entries)} maps. Press Esc to stop after the current map.")
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self._begin(context):
            return {"CANCELLED"}
        wm = context.window_manager
        wm.progress_begin(0, len(self._entries))
        try:
            while self._index < len(self._entries):
                self._process_next(context)
                wm.progress_update(self._index)
        finally:
            wm.progress_end()
        report = self._save_report(context, cancelled=False)
        summary = report["summary"]
        self.report({"INFO"} if summary["maps_failed"] == 0 else {"WARNING"},
                    f"Audit finished: {summary['maps_passed']} passed, {summary['maps_failed']} failed. "
                    f"Report: {self._report_text}")
        return {"FINISHED"}

    def modal(self, context, event):
        wm = context.window_manager
        if event.type == "ESC":
            wm.event_timer_remove(self._timer)
            wm.progress_end()
            report = self._save_report(context, cancelled=True)
            self.report({"WARNING"}, f"Audit stopped after {len(self._records)} maps. Partial report: {self._report_text}")
            return {"CANCELLED"}
        if event.type == "TIMER":
            if self._index < len(self._entries):
                self._process_next(context)
                wm.progress_update(self._index)
            if self._index >= len(self._entries):
                wm.event_timer_remove(self._timer)
                wm.progress_end()
                report = self._save_report(context, cancelled=False)
                summary = report["summary"]
                self.report({"INFO"} if summary["maps_failed"] == 0 else {"WARNING"},
                            f"Audit finished: {summary['maps_passed']} passed, {summary['maps_failed']} failed. "
                            f"Report: {self._report_text}")
                return {"FINISHED"}
        return {"RUNNING_MODAL"}


class QSS_OT_launch_ironwail(Operator):
    bl_idname = "qss.launch_ironwail"
    bl_label = "Launch Ironwail"
    bl_description = "Launch Ironwail with developer output and load the active map or a selected demo"

    demo_file: StringProperty(name="Demo file (optional)", subtype="FILE_PATH", default="")
    timedemo: BoolProperty(name="Timedemo", default=False)

    @classmethod
    def poll(cls, context):
        scene = context.scene
        executable = _qss_abspath(getattr(scene, "qss_ironwail_executable", "") or "")
        target = bool(getattr(scene, "qss_ironwail_demo", "") or _qss_is_map_object(context.object))
        return bool(executable and os.path.isfile(executable)
                    and scene.qss_game_dir and os.path.isdir(_qss_abspath(scene.qss_game_dir))
                    and target)

    def invoke(self, context, event):
        self.demo_file = getattr(context.scene, "qss_ironwail_demo", "") or ""
        return context.window_manager.invoke_props_dialog(self, width=620)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "demo_file")
        layout.prop(self, "timedemo")
        layout.label(text="Leave Demo file empty to launch the active imported map.", icon="INFO")
        layout.label(text="Developer console output is captured to a QSS log file.", icon="TEXT")

    def execute(self, context):
        scene = context.scene
        executable = _qss_abspath(scene.qss_ironwail_executable or "")
        quake_root = _qss_abspath(scene.qss_quake_root or "")
        game_dir = _qss_abspath(scene.qss_game_dir or "")
        demo_file = bpy.path.abspath(self.demo_file) if self.demo_file else ""
        try:
            if not executable or not os.path.isfile(executable):
                raise FileNotFoundError("Set a valid Ironwail executable in Project & Source.")
            if demo_file:
                if not os.path.isfile(demo_file):
                    raise FileNotFoundError(f"Demo file does not exist: {demo_file}")
                scene.qss_ironwail_demo = demo_file
                _qss_save_config(scene)
                command = external_tools.build_ironwail_command(
                    executable, quake_root, game_dir,
                    demo_file=demo_file, timedemo=bool(self.timedemo), developer_mode=True
                )
                label = os.path.basename(demo_file)
            else:
                obj = context.object
                if not _qss_is_map_object(obj):
                    raise RuntimeError("Select an imported Quake BSP or choose a demo file.")
                virtual_path = str(obj.get("qss_game_map_path", "") or "")
                if not virtual_path:
                    source = os.path.abspath(obj.get("qss_source_path", ""))
                    try:
                        virtual_path = os.path.relpath(source, game_dir).replace(os.sep, "/")
                    except ValueError:
                        virtual_path = ""
                if not virtual_path or virtual_path.startswith(".."):
                    raise RuntimeError("The active BSP is outside the configured game directory and has no Quake virtual map path.")
                command = external_tools.build_ironwail_command(
                    executable, quake_root, game_dir, map_path=virtual_path, developer_mode=True
                )
                label = os.path.basename(virtual_path)
            log_root = bpy.utils.user_resource("DATAFILES", path=os.path.join("qss", "ironwail_logs"), create=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join(log_root, f"Ironwail_{stamp}")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "process_output.log")
            console_log = os.path.join(log_dir, "qconsole.log")
            pid = external_tools.launch_process(command, cwd=log_dir, log_path=log_path)
            self.report({"INFO"}, f"Ironwail launched for {label} (PID {pid}). Console log: {console_log}; process output: {log_path}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not launch Ironwail: {exc}")
            return {"CANCELLED"}




class QSS_OT_generate_decoupled_lightmaps(Operator, ImportHelper):
    bl_idname = "qss.generate_decoupled_lightmaps"
    bl_label = "Generate Decoupled Lightmaps"
    bl_description = (
        "Run ericw-tools light on a separate copy of a BSP and generate the "
        "DECOUPLED_LM BSPX extension"
    )
    filename_ext = ".bsp"
    filter_glob: StringProperty(default="*.bsp", options={'HIDDEN'})
    world_units_per_luxel: FloatProperty(
        name="World units per luxel",
        description="Target spacing for the generated decoupled lightmaps",
        default=16.0, min=0.01, max=1024.0, precision=2,
    )

    def invoke(self, context, event):
        obj = context.object
        source = obj.get("qss_source_path", "") if _qss_is_map_object(obj) else ""
        if source and os.path.isfile(bpy.path.abspath(source)):
            self.filepath = bpy.path.abspath(source)
        self.world_units_per_luxel = float(
            getattr(context.scene, "qss_decoupled_world_units_per_luxel", 16.0)
        )
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "world_units_per_luxel")
        value = float(self.world_units_per_luxel)
        if value <= 4.0:
            layout.label(text="Fine luxel density: expect a much longer build and a larger BSP.", icon="TIME")
        elif value <= 8.0:
            layout.label(text="Higher detail: expect more build time and disk space.", icon="INFO")
        elif value <= 16.0:
            layout.label(text="Balanced density for many maps.", icon="INFO")
        else:
            layout.label(text="Coarser lighting: faster and smaller, with less spatial detail.", icon="INFO")
        layout.label(text="A new *_decoupled.bsp copy will be created in this map's ##slipgate folder.", icon="INFO")
        layout.label(text="The source BSP is never modified; lighting is recalculated.", icon="INFO")

    def execute(self, context):
        import shutil

        source_path = bpy.path.abspath(self.filepath)
        output_path = ""
        output_lit = ""
        try:
            if not source_path or not os.path.isfile(source_path):
                raise FileNotFoundError(f"Source BSP does not exist: {source_path}")
            if not source_path.lower().endswith(".bsp"):
                raise ValueError("Select a .bsp file.")

            scene = context.scene
            tools_dir = _qss_abspath(getattr(scene, "qss_ericw_tools_dir", "") or "")
            light = external_tools.resolve_tool(tools_dir, "light")
            if not light:
                raise FileNotFoundError(
                    "ericw-tools light was not found. Set the ericw-tools folder in Project & Source."
                )

            source_root, extension = os.path.splitext(source_path)
            candidate = source_root + "_decoupled" + extension
            suffix = 1
            while os.path.exists(candidate):
                candidate = f"{source_root}_decoupled_{suffix:03d}{extension}"
                suffix += 1
            output_path = candidate
            output_lit = os.path.splitext(output_path)[0] + ".lit"

            command = external_tools.build_decoupled_light_command(
                light,
                output_path,
                world_units_per_luxel=self.world_units_per_luxel,
                quake_root=_qss_abspath(getattr(scene, "qss_quake_root", "") or ""),
                game_dir=_qss_abspath(getattr(scene, "qss_game_dir", "") or ""),
            )

            shutil.copy2(source_path, output_path)
            result = external_tools.run_command(
                light, command[1:], timeout=float(getattr(scene, "qss_audit_timeout", 300)),
                cwd=os.path.dirname(output_path) or None,
            )
            lines = [
                "QSS DECOUPLED LIGHTMAP GENERATION",
                f"Source: {source_path}",
                f"Output: {output_path}",
                f"World units per luxel: {self.world_units_per_luxel:g}",
                f"Command: {command!r}",
                f"Process status: {result.get('status')}",
                f"Return code: {result.get('returncode')}",
                "",
                result.get("stdout", ""),
                result.get("stderr", ""),
            ]

            if result.get("status") != "PASS":
                raise RuntimeError(
                    f"ericw-tools light failed ({result.get('status')}): "
                    f"{(result.get('stdout') or result.get('stderr') or '')[-1200:]}"
                )
            if not os.path.isfile(output_path):
                raise RuntimeError("ericw-tools reported success but did not write the output BSP.")

            generated = bsp.BSP29.from_file(output_path)
            decoupled = generated.bspx_lumps.get("DECOUPLED_LM", b"")
            if not decoupled:
                raise RuntimeError(
                    "ericw-tools completed, but the output BSP has no DECOUPLED_LM lump."
                )
            if len(decoupled) % 40:
                raise RuntimeError(
                    f"Generated DECOUPLED_LM has an invalid size ({len(decoupled)} bytes; expected multiples of 40)."
                )

            lines.extend([
                "",
                "VERIFICATION: PASS",
                f"DECOUPLED_LM bytes: {len(decoupled)}",
                f"Decoupled face records: {len(decoupled) // 40}",
                f"Other BSPX lumps: {', '.join(sorted(generated.bspx_lumps))}",
                f"Output .lit sidecar: {'present' if os.path.isfile(output_lit) else 'not present'}",
            ])
            _qss_write_text_report("QSS_Decoupled_Lightmap_Generation", "\n".join(lines))
            self.report(
                {"INFO"},
                f"Generated {len(decoupled) // 40} decoupled lightmap records: {os.path.basename(output_path)}",
            )
            return {"FINISHED"}

        except Exception as exc:
            if output_path:
                for path in (output_path, output_lit):
                    try:
                        if path and os.path.isfile(path):
                            os.remove(path)
                    except OSError:
                        pass
            detail = f"QSS DECOUPLED LIGHTMAP GENERATION FAILED\n{exc}"
            _qss_write_text_report("QSS_Decoupled_Lightmap_Generation", detail)
            self.report({"ERROR"}, str(exc)[:240])
            return {"CANCELLED"}


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
        # Detach is transactional: remember the material-slot boundary and
        # active slot so an exception cannot leave orphaned QSS material slots.
        original_material_count = len(mesh.materials)
        original_active_material_index = int(obj.active_material_index)
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
            original_uv_layer = mesh.uv_layers.get("Quake_Texture_UV_Original")
            if original_uv_layer is None:
                original_uv_layer = mesh.uv_layers.new(name="Quake_Texture_UV_Original")
                for loop_index in range(len(uv_layer.data)):
                    original_uv_layer.data[loop_index].uv = uv_layer.data[loop_index].uv
            painted_uv_layer = mesh.uv_layers.get("Quake_Texture_UV_Painted")
            if painted_uv_layer is None:
                painted_uv_layer = mesh.uv_layers.new(name="Quake_Texture_UV_Painted")
                for loop_index in range(len(uv_layer.data)):
                    painted_uv_layer.data[loop_index].uv = uv_layer.data[loop_index].uv
            painted_marker_existing = mesh.attributes.get("qss_painted_face")
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
                    'was_already_detached': bool(
                        painted_marker_existing
                        and poly_index < len(painted_marker_existing.data)
                        and painted_marker_existing.data[poly_index].value
                    ),
                    'face_id': face_id,
                    'source_mat': source_mat,
                    'source_index': source_index,
                    'old_uvs': [tuple(_qss_safe_collection_item(uv_layer.data, i, 'Quake texture UV').uv) for i in loop_indices],
                    'loop_indices': loop_indices,
                    'image': image,
                    'uvs': normalized_uvs,
                    'projection': projection,
                })

            stage = 'pack selected faces into one paint atlas'
            if len(plans) > 1:
                atlas_image = _qss_create_detached_face_atlas(plans, atlas_size=512)
                if atlas_image is not None:
                    created_images.append(atlas_image)

            stage = 'create detached material copies'
            for plan in plans:
                new_mat = plan['source_mat'].copy()
                created_materials.append(new_mat)
                new_mat.name = f"QSS_Detached_F{plan['face_id']:05d}"
                new_mat['qss_texture_index'] = -1
                new_mat['qss_is_new_texture'] = True
                new_mat['qss_fullbright_source_texture_id'] = int(
                    plan['source_mat'].get(
                        'qss_fullbright_source_texture_id',
                        plan['source_mat'].get('qss_texture_index', -1),
                    )
                )
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
            original_material_attr = mesh.attributes.get("qss_original_material_index")
            if original_material_attr is None:
                original_material_attr = mesh.attributes.new(name="qss_original_material_index", type="INT", domain="FACE")
            painted_material_attr = mesh.attributes.get("qss_painted_material_index")
            if painted_material_attr is None:
                painted_material_attr = mesh.attributes.new(name="qss_painted_material_index", type="INT", domain="FACE")
            painted_face_attr = mesh.attributes.get("qss_painted_face")
            if painted_face_attr is None:
                painted_face_attr = mesh.attributes.new(name="qss_painted_face", type="INT", domain="FACE")
            last_new_index = -1
            for plan in plans:
                mesh.materials.append(plan['new_mat'])
                material_index = len(mesh.materials) - 1
                poly = mesh.polygons[plan['poly_index']]
                face_index = int(plan["poly_index"])
                if not painted_face_attr.data[face_index].value:
                    original_material_attr.data[face_index].value = int(plan["source_index"])
                poly.material_index = material_index
                painted_material_attr.data[face_index].value = int(material_index)
                painted_face_attr.data[face_index].value = 1
                for loop_index, uv_value in zip(plan['loop_indices'], plan['uvs']):
                    if loop_index >= len(uv_layer.data):
                        raise bsp.BSPError(
                            f"UV collection changed during detach (loop {loop_index}, size {len(uv_layer.data)})."
                        )
                    if not plan.get("was_already_detached", False):
                        original_uv_layer.data[loop_index].uv = uv_layer.data[loop_index].uv
                    painted_uv_layer.data[loop_index].uv = uv_value
                    _qss_safe_collection_item(uv_layer.data, loop_index, 'Quake texture UV').uv = uv_value
                last_new_index = material_index
            if last_new_index >= 0:
                obj.active_material_index = last_new_index
            mesh.update()

            # Prepare the detached material slot immediately. This also makes
            # a direct Blender mode-toggle enter the same face-isolated paint
            # mode, even when the user does not invoke the QSS paint button.
            if last_new_index >= 0:
                # Restrict Texture Paint to the selected detached face(s).
                # Without the mesh face mask, a brush footprint crossing a
                # boundary also paints neighbouring faces through their own
                # materials, including shared source textures/lightmaps.
                mesh.use_paint_mask = True
                detached_mat = mesh.materials[last_new_index]
                detached_image = _find_image(detached_mat, 'base_texture')
                _set_texture_paint_target(
                    context, obj, detached_image, 'Quake_Texture_UV',
                    material=detached_mat
                )
                paint_slot_index = material_utils.find_image_slot_index(
                    list(detached_mat.texture_paint_images), detached_image
                )
                if paint_slot_index >= 0:
                    detached_mat.paint_active_slot = paint_slot_index

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

            for plan in plans:
                local_image = plan.get("local_image")
                if local_image is not None:
                    try:
                        if local_image.users == 0:
                            bpy.data.images.remove(local_image, do_unlink=True)
                        if local_image in created_images:
                            created_images.remove(local_image)
                    except Exception:
                        pass
            atlas_scale_note = ""
            if len(plans) > 1 and plans[0].get("image") is not None:
                atlas_scale = float(plans[0]["image"].get("qss_detached_atlas_scale", 1.0))
                if atlas_scale < 0.999:
                    atlas_scale_note = (
                        f" Face textures were resampled to {atlas_scale:.0%} "
                        "to fit the 512x512 Quake texture limit."
                    )
            _report(
                self, 'INFO',
                f"Detached {len(plans)} face(s). "
                + ("Their face-local textures share one paint atlas." if len(plans) > 1
                   else "The face has its own paint texture.")
                + atlas_scale_note
                + " Use 'Enter Texture Paint' to paint the selected face(s)."
            )
            return {'FINISHED'}

        except Exception as exc:
            trace = traceback.format_exc()
            obj['qss_last_detach_error'] = f"{stage}: {exc}"
            obj['qss_last_detach_traceback'] = trace[-12000:]
            print(trace)
            # Material/UV Mesh collections are not safe to edit while a failed
            # Edit Mode restore has left the object in BMesh mode. Return to
            # Object Mode before rolling back the original Mesh data.
            try:
                if context.mode == 'EDIT_MESH':
                    bpy.ops.object.mode_set(mode='OBJECT')
                    mesh = obj.data
                    uv_layer = mesh.uv_layers.get('Quake_Texture_UV')
            except Exception:
                pass
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
            # Remove every appended mesh slot before deleting the copied
            # materials. Merely resetting polygon indices does not remove the
            # slots, so users would remain non-zero and failed detaches leaked
            # QSS_Detached_* materials into the mesh.
            try:
                material_utils.trim_appended_material_slots(
                    mesh.materials, original_material_count
                )
                obj.active_material_index = min(
                    original_active_material_index,
                    max(0, original_material_count - 1)
                )
                mesh.update()
            except Exception as rollback_exc:
                print(f"QSS detach material-slot rollback warning: {rollback_exc}")
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
                    bm = bmesh.from_edit_mesh(obj.data)
                    bm.faces.ensure_lookup_table()
                    bm.faces.index_update()
                    selected_set = set(selected_indices)
                    for face in bm.faces:
                        face.select_set(face.index in selected_set)
                    if selected_indices and max(selected_indices) < len(bm.faces):
                        bm.faces.active = bm.faces[selected_indices[-1]]
                    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            except Exception as restore_exc:
                print(f"QSS detach selection restore warning: {restore_exc}")
            _report(self, 'ERROR', f"Could not detach face ({stage}): {exc}. If the mesh was hidden/revealed in Edit Mode, switch to Object Mode and re-import if the face/UV attribute counts are stale.")
            return {'CANCELLED'}


def _qss_current_paint_image(context):
    settings = getattr(getattr(context, "scene", None), "tool_settings", None)
    image_paint = getattr(settings, "image_paint", None) if settings else None
    image = getattr(image_paint, "canvas", None) if image_paint else None
    if image is None and settings is not None:
        paint_mode = getattr(settings, "paint_mode", None)
        image = getattr(paint_mode, "canvas_image", None) if paint_mode else None
    return image


def _qss_quake_palette_for_map(obj):
    """Get or build a Blender Palette datablock from the map's exact Quake palette."""
    if not _qss_is_map_object(obj):
        raise bsp.BSPError("Select an imported QSS map before loading its Quake palette.")
    palette_bytes, origin = bsp.find_quake_palette(
        str(obj.get("qss_game_dir", "") or ""),
        str(obj.get("qss_palette_file", "") or ""),
    )
    if palette_bytes is None:
        raise bsp.BSPError(
            "Could not locate the map's Quake palette. Check the game's gfx/palette.lmp "
            "or re-import with an explicit palette file."
        )
    signature = hashlib.sha256(palette_bytes).hexdigest()
    name = f"QSS Quake Palette {signature[:10]}"
    palette = bpy.data.palettes.get(name)
    if palette is None:
        palette = bpy.data.palettes.new(name)
    while len(palette.colors) < 256:
        palette.colors.new()
    while len(palette.colors) > 256:
        palette.colors.remove(palette.colors[-1])
    for index in range(256):
        offset = index * 3
        palette.colors[index].color = (
            palette_bytes[offset] / 255.0,
            palette_bytes[offset + 1] / 255.0,
            palette_bytes[offset + 2] / 255.0,
        )
        palette.colors[index].weight = 1.0
    palette["qss_palette_signature"] = signature
    palette["qss_palette_origin"] = str(origin)
    palette["qss_quake_palette"] = True
    return palette, palette_bytes, origin


def _qss_assign_quake_palette(context, obj):
    """Assign the active map's Quake palette to Blender's Image Paint settings."""
    palette, _palette_bytes, _origin = _qss_quake_palette_for_map(obj)
    image_paint = getattr(getattr(context.scene, "tool_settings", None), "image_paint", None)
    if image_paint is None:
        raise bsp.BSPError("Blender's Image Paint settings are unavailable in this context.")
    image_paint.palette = palette
    return palette


def _qss_on_paint_color_picker_changed(self, context):
    if str(getattr(self, "qss_paint_color_picker", "STANDARD")) != "QUAKE":
        return
    obj = getattr(context, "object", None) if context else None
    if _qss_is_map_object(obj):
        try:
            _qss_assign_quake_palette(context, obj)
        except Exception as exc:
            print(f"QSS: could not load the map's Quake brush palette: {exc}")


def _qss_image_pixels_to_rgba8(image):
    """Read a Blender image as top-down sRGB RGBA8 for palette conversion."""
    width, height = int(image.size[0]), int(image.size[1])
    if width < 1 or height < 1 or width * height > 16_777_216:
        raise bsp.BSPError(
            "The image is empty or larger than the 16-megapixel safe conversion limit."
        )
    image.update()
    pixels = array.array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    # Blender byte buffers already contain values encoded in their image
    # colour space (sRGB for QSS albedo); float buffers are scene-linear.
    # Encoding every sRGB-tagged image here applies the transfer curve twice
    # to byte textures and makes BSP exports visibly too bright in Quake.
    is_float_buffer = bool(getattr(image, "is_float", False))
    output = bytearray(width * height * 4)

    def byte(value):
        return max(0, min(255, int(round(float(value) * 255.0))))

    for y in range(height):
        source_row = (height - 1 - y) * width
        target_row = y * width
        for x in range(width):
            source = (source_row + x) * 4
            target = (target_row + x) * 4
            output[target] = byte(color.blender_pixel_to_quake_code(pixels[source], is_float_buffer))
            output[target + 1] = byte(color.blender_pixel_to_quake_code(pixels[source + 1], is_float_buffer))
            output[target + 2] = byte(color.blender_pixel_to_quake_code(pixels[source + 2], is_float_buffer))
            output[target + 3] = byte(pixels[source + 3])
    return width, height, bytes(output)


def _qss_read_fullbright_mask(source_path, width, height):
    """Read an optional sibling *_fullbrights.png mask through Blender's image API."""
    if not source_path:
        return None, None
    mask_path = os.path.splitext(source_path)[0] + "_fullbrights.png"
    if not os.path.isfile(mask_path):
        return None, None
    mask_image = None
    try:
        mask_image = bpy.data.images.load(mask_path, check_existing=False)
        if tuple(int(value) for value in mask_image.size[:2]) != (width, height):
            raise bsp.BSPError("The *_fullbrights.png mask dimensions do not match the source image.")
        pixels = array.array("f", [0.0]) * (width * height * 4)
        mask_image.pixels.foreach_get(pixels)
        mask = bytearray(width * height)
        for target_y in range(height):
            source_y = height - 1 - target_y
            for x in range(width):
                index = (source_y * width + x) * 4
                luminance = (
                    0.2126 * pixels[index]
                    + 0.7152 * pixels[index + 1]
                    + 0.0722 * pixels[index + 2]
                )
                mask[target_y * width + x] = 1 if luminance >= 0.5 else 0
        return mask, mask_image
    except Exception:
        if mask_image is not None:
            try:
                bpy.data.images.remove(mask_image, do_unlink=True)
            except Exception:
                pass
        raise


def _qss_converter_source_image(context):
    """Resolve the active paint canvas, Image Editor image, or rendered result."""
    if _qss_is_texture_paint_context(context):
        image = _qss_current_paint_image(context)
        if image is not None:
            return image
    area = getattr(context, "area", None)
    if area is not None and area.type == "IMAGE_EDITOR":
        image = getattr(area.spaces.active, "image", None)
        if image is not None:
            return image
    render_result = bpy.data.images.get("Render Result")
    if render_result is not None and bool(getattr(render_result, "has_data", False)):
        return render_result
    obj = getattr(context, "object", None)
    if obj is not None and getattr(obj, "type", "") == "MESH":
        material_index = (
            _selected_edit_face_material(obj)
            if getattr(context, "mode", "") == "EDIT_MESH"
            else getattr(obj, "active_material_index", -1)
        )
        if material_index is not None and 0 <= int(material_index) < len(obj.data.materials):
            return _find_image(obj.data.materials[int(material_index)], "base_texture")
    return None


def _qss_save_image_copy_as_png(image, output_path, context):
    """Write an in-memory Blender image as PNG without changing its original path."""
    if image is None:
        raise bsp.BSPError("No source image is available for Quake palette conversion.")
    if image.name == "Render Result":
        settings = context.scene.render.image_settings
        previous = {
            "file_format": settings.file_format,
            "color_mode": settings.color_mode,
            "color_depth": settings.color_depth,
            "compression": settings.compression,
        }
        try:
            settings.file_format = "PNG"
            settings.color_mode = "RGBA"
            settings.color_depth = "8"
            settings.compression = 15
            image.save_render(output_path, scene=context.scene)
        finally:
            for key, value in previous.items():
                try:
                    setattr(settings, key, value)
                except Exception:
                    pass
        return

    copy = image.copy()
    try:
        copy.filepath_raw = output_path
        copy.file_format = "PNG"
        copy.color_mode = "RGBA"
        copy.color_depth = "8"
        copy.save()
        if not os.path.isfile(output_path):
            raise bsp.BSPError("Blender did not create the temporary PNG for palette conversion.")
    finally:
        try:
            bpy.data.images.remove(copy, do_unlink=True)
        except Exception:
            pass


def _qss_selected_paint_face_indices(context, obj):
    """Return visible selected polygon indices from the active mesh selection."""
    if obj is None or getattr(obj, "type", "") != "MESH":
        return []
    if getattr(context, "mode", "") == "EDIT_MESH":
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        return [int(face.index) for face in bm.faces if face.select and not face.hide]
    return [int(poly.index) for poly in obj.data.polygons if poly.select]


def _qss_selected_paint_face_count(context, obj):
    return len(_qss_selected_paint_face_indices(context, obj))


def _qss_estimate_texture_paint_memory(context, obj):
    """Estimate peak CPU image-buffer memory for selected face detachment."""
    indices = _qss_selected_paint_face_indices(context, obj)
    mesh = getattr(obj, "data", None)
    if not indices or mesh is None:
        return palette_utils.estimate_face_local_paint_bytes([])
    uv_layer = mesh.uv_layers.get("Quake_Texture_UV")
    spans = []
    float_buffer = False
    for index in indices:
        if index < 0 or index >= len(mesh.polygons):
            continue
        poly = mesh.polygons[index]
        material_index = int(poly.material_index)
        material = mesh.materials[material_index] if 0 <= material_index < len(mesh.materials) else None
        image = _find_image(material, "base_texture") if material else None
        if image is None:
            continue
        float_buffer = float_buffer or bool(getattr(image, "is_float", False))
        source_width = max(1, int(image.size[0]))
        source_height = max(1, int(image.size[1]))
        width_span, height_span = float(source_width), float(source_height)
        if uv_layer is not None:
            try:
                uv_values = [
                    uv_layer.data[int(loop_index)].uv
                    for loop_index in poly.loop_indices
                ]
                if len(uv_values) >= 3:
                    width_span = max(
                        1.0,
                        (max(float(uv.x) for uv in uv_values) -
                         min(float(uv.x) for uv in uv_values)) * source_width,
                    )
                    height_span = max(
                        1.0,
                        (max(float(uv.y) for uv in uv_values) -
                         min(float(uv.y) for uv in uv_values)) * source_height,
                    )
            except Exception:
                # Stale Edit Mode UV collections should not prevent a warning;
                # fall back to the full source-image footprint.
                pass
        spans.append((width_span, height_span))
    if len(spans) != len(indices):
        # Unknown source faces are conservatively estimated as 512x512 images.
        spans.extend([(512.0, 512.0)] * (len(indices) - len(spans)))
    estimate = palette_utils.estimate_face_local_paint_bytes(
        spans, bytes_per_face_pixel=16 if float_buffer else 4,
        atlas_size=512, bytes_per_atlas_pixel=16,
    )
    # The face-local bake also holds temporary float arrays while sampling and
    # packing the images. Use a conservative 3x multiplier for those working
    # buffers; Blender undo and GPU allocations remain additional overhead.
    estimate["working_buffer_reserve_bytes"] = estimate["peak_pixel_bytes"] * 2
    estimate["peak_pixel_bytes"] *= 3
    return estimate


def _qss_available_memory_bytes():
    """Return the best available physical/cgroup memory estimate, or None."""
    candidates = []
    try:
        with open("/sys/fs/cgroup/memory.max", "r", encoding="ascii") as handle:
            limit_text = handle.read().strip()
        with open("/sys/fs/cgroup/memory.current", "r", encoding="ascii") as handle:
            current_text = handle.read().strip()
        if limit_text != "max":
            available = max(0, int(limit_text) - int(current_text))
            candidates.append(available)
    except (OSError, ValueError):
        pass
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    candidates.append(max(0, int(line.split()[1]) * 1024))
                    break
    except (OSError, ValueError, IndexError):
        pass
    if not candidates and hasattr(os, "sysconf"):
        try:
            pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            if pages > 0 and page_size > 0:
                candidates.append(pages * page_size)
        except (OSError, ValueError, TypeError):
            pass
    return min(candidates) if candidates else None


def _qss_map_image_memory_bytes(obj):
    """Estimate existing image pixel buffers referenced by this map's materials."""
    if obj is None or getattr(obj, "type", "") != "MESH":
        return 0
    images = {}
    for material in obj.data.materials:
        if material is None or not material.use_nodes or material.node_tree is None:
            continue
        for node in material.node_tree.nodes:
            image = getattr(node, "image", None)
            if image is None:
                continue
            try:
                key = int(image.as_pointer())
            except Exception:
                key = id(image)
            images[key] = image
    total = 0
    for image in images.values():
        try:
            channels = 4
            bytes_per_channel = 4 if bool(getattr(image, "is_float", False)) else 1
            total += max(1, int(image.size[0])) * max(1, int(image.size[1])) * channels * bytes_per_channel
        except Exception:
            pass
    return total


def _qss_paint_confirmation_needed(
    face_count, estimated_bytes, available_bytes, *,
    minimum_bytes=32 * 1024 * 1024, available_fraction=0.05,
):
    """Ask before paint preparation only when its peak allocation is material."""
    return bool(
        int(estimated_bytes) >= int(minimum_bytes)
        or (
            available_bytes is not None and available_bytes > 0
            and int(estimated_bytes) >= int(available_bytes * float(available_fraction))
        )
    )


def _qss_is_texture_paint_context(context):
    """Recognise Blender's context and object-mode spellings across supported versions."""
    mode = str(getattr(context, "mode", ""))
    if mode in {"PAINT_TEXTURE", "TEXTURE_PAINT"}:
        return True
    obj = getattr(context, "object", None)
    return bool(obj is not None and getattr(obj, "mode", "") == "TEXTURE_PAINT")


def _qss_focus_clip_context(context):
    """Face-focus depth clipping applies in Edit Mode and Texture Paint."""
    return bool(
        getattr(context, "mode", "") == "EDIT_MESH"
        or _qss_is_texture_paint_context(context)
    )


def _qss_exit_texture_paint(context, obj):
    """Leave Texture Paint and restore the pre-paint Object/Edit mode."""
    return_to_edit = bool(obj.get("qss_paint_return_edit", False))
    bpy.ops.object.mode_set(mode="OBJECT")
    obj["qss_active_paint_kind"] = ""
    obj["qss_paint_return_edit"] = False
    if return_to_edit:
        bpy.ops.object.mode_set(mode="EDIT")


def _qss_is_lightmap_paint_image(obj, image):
    if obj is None or image is None:
        return False
    names = {
        obj.get("qss_original_lightmap_backup", ""),
        obj.get("qss_lightmap_image_name", ""),
        obj.get("qss_painted_original_lightmap", ""),
        obj.get("qss_painted_baked_lightmap", ""),
    }
    return image.name in names


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
    bl_label = "Prepare Texture Paint Anyway"
    bl_description = "Paint the active selected face material; switches from Edit Mode automatically"

    warning_face_count: IntProperty(default=0, options={'HIDDEN'})
    warning_peak_bytes: FloatProperty(default=0.0, options={'HIDDEN'})
    warning_available_bytes: FloatProperty(default=0.0, options={'HIDDEN'})
    warning_existing_bytes: FloatProperty(default=0.0, options={'HIDDEN'})

    def invoke(self, context, event):
        obj = context.object
        already_texture_painting = (
            _qss_is_texture_paint_context(context)
            and str(obj.get("qss_active_paint_kind", "texture")) == "texture"
        )
        if already_texture_painting:
            return self.execute(context)
        estimate = _qss_estimate_texture_paint_memory(context, obj)
        available = _qss_available_memory_bytes()
        self.warning_face_count = int(estimate["face_count"])
        self.warning_peak_bytes = int(estimate["peak_pixel_bytes"])
        self.warning_available_bytes = int(available or 0)
        self.warning_existing_bytes = _qss_map_image_memory_bytes(obj)
        if _qss_paint_confirmation_needed(
            self.warning_face_count, self.warning_peak_bytes, available
        ):
            return context.window_manager.invoke_props_dialog(self, width=500)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.alert = True
        layout.label(
            text=f"You selected {self.warning_face_count} faces. QSS must prepare paint images for these surfaces.",
            icon="INFO",
        )
        layout.label(
            text=f"Estimated extra memory, including temporary working buffers: about {palette_utils.format_mib(self.warning_peak_bytes)}"
        )
        layout.label(
            text=f"Existing QSS map image buffers: about {palette_utils.format_mib(self.warning_existing_bytes)}"
        )
        if self.warning_available_bytes > 0:
            layout.label(
                text=f"Currently available system memory: about {palette_utils.format_mib(self.warning_available_bytes)}"
            )
        layout.label(
            text="This is an estimate. Blender also uses memory for undo history, GPU copies and other data, so actual use can be higher.",
            icon="INFO",
        )
        layout.label(
            text="If memory runs out, Blender may crash and unsaved work may be lost. Safest option: Cancel and paint smaller batches.",
            icon="ERROR",
        )
        layout.alert = False

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not (obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'):
            return False
        if _qss_is_texture_paint_context(context):
            return True
        if context.mode == 'EDIT_MESH':
            try:
                index = _selected_edit_face_material(obj)
                return index is not None and 0 <= index < len(obj.data.materials) and _find_image(obj.data.materials[index]) is not None
            except Exception:
                return False
        return bool(context.mode == 'OBJECT' and obj.active_material and _find_image(obj.active_material))

    def execute(self, context):
        obj = context.object
        currently_painting_texture = (
            _qss_is_texture_paint_context(context)
            and str(obj.get("qss_active_paint_kind", "texture")) == "texture"
        )
        if _qss_is_texture_paint_context(context):
            current_kind = str(obj.get("qss_active_paint_kind", ""))
            if not current_kind:
                current_kind = ("lightmap" if _qss_is_lightmap_paint_image(
                    obj, _qss_current_paint_image(context)) else "texture")
            if current_kind == "texture":
                _qss_exit_texture_paint(context, obj)
                self.report({'INFO'}, "Texture Paint mode closed.")
                return {'FINISHED'}
            # Switch from lightmap painting to texture painting, retaining the
            # user's original return-to-Edit-Mode preference.
            bpy.ops.object.mode_set(mode='OBJECT')
        elif context.mode == 'EDIT_MESH':
            obj["qss_paint_return_edit"] = True
        else:
            obj["qss_paint_return_edit"] = False

        if context.mode == 'EDIT_MESH':
            import bmesh
            bm = bmesh.from_edit_mesh(obj.data)
            selected_faces = [face for face in bm.faces if face.select]
            if not selected_faces:
                _report(self, 'WARNING', "Select one or more faces in Edit Mode first.")
                return {'CANCELLED'}
            marker = obj.data.attributes.get("qss_painted_face")
            already_detached = bool(marker and all(
                face.index < len(marker.data) and marker.data[face.index].value
                for face in selected_faces
            ))
            selected_image_keys = set()
            for face in selected_faces:
                material_index = int(face.material_index)
                if material_index < 0 or material_index >= len(obj.data.materials):
                    _report(self, 'ERROR', f"Selected face uses invalid material slot {material_index}.")
                    return {'CANCELLED'}
                material = obj.data.materials[material_index]
                image = _find_image(material, "base_texture") if material else None
                if image is None:
                    _report(self, 'ERROR', "A selected face has no base texture image.")
                    return {'CANCELLED'}
                selected_image_keys.add(image.as_pointer())
            if not already_detached or len(selected_image_keys) > 1:
                result = bpy.ops.qss.detach_selected_faces()
                if "CANCELLED" in result:
                    return {"CANCELLED"}
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
        # Face masking is essential for detached painting: Texture Paint
        # otherwise continues onto neighbouring polygons and writes through
        # their respective (possibly shared) source materials.
        obj.data.use_paint_mask = True
        try:
            _set_texture_paint_target(
                context, obj, image, 'Quake_Texture_UV', material=mat
            )
        except bsp.BSPError as exc:
            _report(self, 'ERROR', str(exc))
            return {'CANCELLED'}
        try:
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
            obj["qss_active_paint_kind"] = "texture"
            if str(getattr(context.scene, "qss_paint_color_picker", "STANDARD")) == "QUAKE":
                _qss_assign_quake_palette(context, obj)
            slot_index = material_utils.find_image_slot_index(
                list(mat.texture_paint_images), image
            )
            if slot_index < 0:
                raise bsp.BSPError(
                    f"Blender's Material paint slots do not contain '{image.name}'. "
                    "The image was not made the active paint target; no painting started."
                )
            mat.paint_active_slot = slot_index
            mat.update_tag()
            context.view_layer.update()
            active_slot = int(mat.paint_active_slot)
            paint_images = list(mat.texture_paint_images)
            paint_slots = list(mat.texture_paint_slots)
            if active_slot >= len(paint_images) or paint_images[active_slot] != image:
                raise bsp.BSPError(
                    f"Blender selected paint slot {active_slot}, not '{image.name}'. "
                    "The paint target was rejected to protect other textures."
                )
            if active_slot >= len(paint_slots):
                raise bsp.BSPError("Blender did not provide paint-slot UV metadata.")
            slot = paint_slots[active_slot]
            slot_uv = str(getattr(slot, 'uv_layer', '') or '')
            if not bool(getattr(slot, 'is_valid', True)):
                raise bsp.BSPError(
                    f"Paint slot for '{image.name}' has no valid UV mapping."
                )
            if slot_uv and slot_uv != 'Quake_Texture_UV':
                raise bsp.BSPError(
                    f"Paint slot for '{image.name}' uses UV map '{slot_uv}', "
                    "not 'Quake_Texture_UV'."
                )
        except Exception as exc:
            try:
                if _qss_is_texture_paint_context(context):
                    bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            obj["qss_active_paint_kind"] = ""
            obj["qss_paint_return_edit"] = False
            _report(self, 'ERROR', f"Could not validate the detached paint target: {exc}")
            return {'CANCELLED'}
        _report(
            self, 'INFO',
            f"Painting image (material paint slot {active_slot}): {image.name}; "
            "face selection mask enabled."
        )
        return {'FINISHED'}


class QSS_OT_activate_lightmap_paint(Operator):
    bl_idname = "qss.activate_lightmap_paint"
    bl_label = "Enter Lightmap Paint"
    bl_description = "Paint the working lightmap atlas, restricted to selected lightmapped faces"
    warning_face_count: IntProperty(default=0, options={'HIDDEN'})
    warning_atlas_bytes: FloatProperty(default=0.0, options={'HIDDEN'})
    warning_available_bytes: FloatProperty(default=0.0, options={'HIDDEN'})

    def invoke(self, context, event):
        obj = context.object
        already_painting_lightmap = (
            _qss_is_texture_paint_context(context)
            and str(obj.get("qss_active_paint_kind", "")) == "lightmap"
        )
        if already_painting_lightmap:
            return self.execute(context)
        count = _qss_selected_paint_face_count(context, obj)
        self.warning_face_count = int(count)
        image = bpy.data.images.get(str(obj.get("qss_lightmap_image_name", "")))
        self.warning_atlas_bytes = 0
        if image is not None:
            bpp = 16 if bool(getattr(image, "is_float", False)) else 4
            self.warning_atlas_bytes = max(1, int(image.size[0])) * max(1, int(image.size[1])) * bpp
        available = _qss_available_memory_bytes()
        self.warning_available_bytes = float(available or 0)
        if _qss_paint_confirmation_needed(
            count, int(self.warning_atlas_bytes * 2), available,
            minimum_bytes=256 * 1024 * 1024, available_fraction=0.10,
        ):
            return context.window_manager.invoke_props_dialog(self, width=460)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.alert = True
        layout.label(
            text=(
                f"You selected {self.warning_face_count} "
                f"{'face' if self.warning_face_count == 1 else 'faces'} for Lightmap Paint."
            ),
            icon="INFO",
        )
        layout.label(
            text="QSS creates a working copy of the shared atlas for the first lightmap-paint pass."
        )
        layout.label(
            text=f"Current working lightmap atlas: about {palette_utils.format_mib(self.warning_atlas_bytes)}"
        )
        if self.warning_available_bytes > 0:
            layout.label(
                text=f"Currently available system memory: about {palette_utils.format_mib(self.warning_available_bytes)}"
            )
        layout.label(
            text="Blender may also need memory for undo history and GPU copies. If memory runs out, Blender may crash and unsaved work may be lost.",
            icon="ERROR",
        )
        layout.alert = False

    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(
            obj and obj.type == 'MESH'
            and obj.get('qss_object_role') == 'quake_bsp29'
            and obj.get('qss_lightmap_image_name')
            and obj.get("qss_preview_mode", "source") in {"source", "baked"}
            and (obj.get("qss_preview_mode", "source") != "baked" or _qss_has_baked_lightmap(obj))
            and (context.mode in {'OBJECT', 'EDIT_MESH'} or _qss_is_texture_paint_context(context))
        )

    def execute(self, context):
        obj = context.object
        currently_painting_lightmap = (
            _qss_is_texture_paint_context(context)
            and str(obj.get("qss_active_paint_kind", "")) == "lightmap"
        )
        if _qss_is_texture_paint_context(context):
            current_kind = str(obj.get("qss_active_paint_kind", ""))
            if not current_kind:
                current_kind = ("lightmap" if _qss_is_lightmap_paint_image(
                    obj, _qss_current_paint_image(context)) else "texture")
            if current_kind == "lightmap":
                _qss_exit_texture_paint(context, obj)
                self.report({'INFO'}, "Lightmap Paint mode closed.")
                return {'FINISHED'}
            # Switch from texture painting to lightmap painting while retaining
            # the user's original return-to-Edit-Mode preference.
            bpy.ops.object.mode_set(mode='OBJECT')
        elif context.mode == 'EDIT_MESH':
            obj["qss_paint_return_edit"] = True
        else:
            obj["qss_paint_return_edit"] = False
        mesh = obj.data
        active_face_index = None
        try:
            # Capture Edit Mode selection before switching modes. The shared
            # atlas contains many UV islands, so face masking must be explicit.
            if context.mode == 'EDIT_MESH':
                import bmesh
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                bm.faces.index_update()
                selected_indices = [int(face.index) for face in bm.faces if face.select]
                active_face = bm.faces.active
                if active_face is not None and active_face.select:
                    active_face_index = int(active_face.index)
                if not selected_indices:
                    raise bsp.BSPError(
                        "Select one or more lightmapped faces in Edit Mode before entering Lightmap Paint."
                    )
                bpy.ops.object.mode_set(mode='OBJECT')
                mesh = obj.data
            else:
                selected_indices = [int(poly.index) for poly in mesh.polygons if bool(poly.select)]
                if not selected_indices:
                    raise bsp.BSPError(
                        "No faces are selected. Switch to Edit Mode, select the faces to paint, "
                        "then click Enter Lightmap Paint."
                    )

            has_data_attr = mesh.attributes.get('qss_lm_has_data')
            if has_data_attr is None or len(has_data_attr.data) != len(mesh.polygons):
                raise bsp.BSPError(
                    "The BSP lightmap face metadata is missing or out of date. Re-import the map."
                )
            lightmap_flags = [bool(item.value) for item in has_data_attr.data]
            selected_indices = material_utils.filter_lightmapped_face_indices(
                selected_indices, lightmap_flags
            )
            if not selected_indices:
                raise bsp.BSPError(
                    "The selected faces have no imported lightmap samples. Select a lightmapped face."
                )

            # Make the captured selection authoritative in Object Mode, then
            # enable Texture Paint's face mask to prevent UV-island spillover.
            selected_set = set(selected_indices)
            for poly in mesh.polygons:
                poly.select = poly.index in selected_set
            mesh.use_paint_mask = True
            mesh.update()
            if active_face_index not in selected_set:
                active_face_index = selected_indices[-1]
            active_material_index = int(mesh.polygons[active_face_index].material_index)
            if 0 <= active_material_index < len(mesh.materials):
                obj.active_material_index = active_material_index

            preview_mode = obj.get("qss_preview_mode", "source")
            if preview_mode not in {"source", "baked"}:
                raise bsp.BSPError("Switch to Original or Baked lighting before painting lightmaps.")
            if preview_mode == "baked" and not _qss_has_baked_lightmap(obj):
                raise bsp.BSPError("This map has no generated lightmap to paint yet.")
            image = _qss_lightmap_preview_image(obj, preview_mode, for_paint=True)
            _rebuild_lightmap_preview(obj, image_override=image)
            mat = obj.active_material
            node = _find_image_node(mat, 'lightmap') if mat else None
            if node is None or node.image != image:
                raise bsp.BSPError(
                    "The active face material is not connected to the editable lightmap atlas."
                )
            for n in mat.node_tree.nodes:
                n.select = False
            node.select = True
            mat.node_tree.nodes.active = node
            try:
                mat.update_tag()
                context.view_layer.update()
            except Exception:
                pass

            _set_texture_paint_target(context, obj, image, 'Quake_Lightmap_UV')
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
            obj["qss_active_paint_kind"] = "lightmap"
            if str(getattr(context.scene, "qss_paint_color_picker", "STANDARD")) == "QUAKE":
                _qss_assign_quake_palette(context, obj)

            # Verify the post-transition state, not only the requested state.
            tool_settings = context.scene.tool_settings
            paint_mode = tool_settings.paint_mode
            image_paint = tool_settings.image_paint
            active_uv = mesh.uv_layers.active
            if (
                paint_mode is None
                or paint_mode.canvas_source != 'IMAGE'
                or paint_mode.canvas_image != image
                or image_paint.mode != 'IMAGE'
                or image_paint.canvas != image
            ):
                raise bsp.BSPError(
                    "Blender did not retain the editable lightmap as the active paint canvas."
                )
            if active_uv is None or active_uv.name != 'Quake_Lightmap_UV':
                raise bsp.BSPError(
                    "Blender did not retain Quake_Lightmap_UV as the active paint UV map."
                )
            if not mesh.use_paint_mask:
                raise bsp.BSPError(
                    "Blender disabled the selected-face paint mask; lightmap painting was stopped for safety."
                )
        except Exception as exc:
            try:
                if context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            obj["qss_active_paint_kind"] = ""
            obj["qss_paint_return_edit"] = False
            _report(self, 'ERROR', f"Could not enter Lightmap Paint mode: {exc}")
            return {'CANCELLED'}

        _report(
            self, 'INFO',
            f"Painting working lightmap atlas '{image.name}' on {len(selected_indices)} "
            f"selected lightmapped face(s); Quake_Lightmap_UV and face mask active."
        )
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
    resolution = _qss_lightmap_pixel_scale(obj, image)
    scale = max(1, int(obj.get('qss_lightmap_scale', 1))) * resolution
    gutter = max(0, int(obj.get('qss_lightmap_gutter', 0))) * resolution
    pixels = array.array('f', [0.0]) * (size * size * 4)
    image.update()
    image.pixels.foreach_get(pixels)
    values = []
    for poly_index, _poly in enumerate(mesh.polygons):
        if not _qss_safe_collection_item(attrs['qss_lm_has_data'].data, poly_index, 'qss_lm_has_data').value:
            continue
        x0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_x'].data, poly_index, 'qss_lm_atlas_x').value) * resolution + gutter
        y0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_y'].data, poly_index, 'qss_lm_atlas_y').value) * resolution + gutter
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


def _lightmap_face_coverage(obj, image, threshold=1e-8):
    """Summarize how many imported faces receive nonzero sampled bake luxels."""
    mesh = obj.data
    attrs = _qss_validate_face_domain_attributes(
        mesh, ('qss_lm_has_data', 'qss_lm_atlas_x', 'qss_lm_atlas_y',
               'qss_lm_sample_w', 'qss_lm_sample_h'),
        'measure lightmap face coverage'
    )
    size = int(image.size[0])
    resolution = _qss_lightmap_pixel_scale(obj, image)
    scale = max(1, int(obj.get('qss_lightmap_scale', 1))) * resolution
    gutter = max(0, int(obj.get('qss_lightmap_gutter', 0))) * resolution
    pixels = array.array('f', [0.0]) * (size * size * 4)
    image.update()
    image.pixels.foreach_get(pixels)
    total_faces = lit_faces = total_luxels = lit_luxels = 0
    face_max_luminance = 0.0
    for poly_index, _poly in enumerate(mesh.polygons):
        if not _qss_safe_collection_item(
            attrs['qss_lm_has_data'].data, poly_index, 'qss_lm_has_data'
        ).value:
            continue
        total_faces += 1
        x0 = int(_qss_safe_collection_item(
            attrs['qss_lm_atlas_x'].data, poly_index, 'qss_lm_atlas_x'
        ).value) * resolution + gutter
        y0 = int(_qss_safe_collection_item(
            attrs['qss_lm_atlas_y'].data, poly_index, 'qss_lm_atlas_y'
        ).value) * resolution + gutter
        width = int(_qss_safe_collection_item(
            attrs['qss_lm_sample_w'].data, poly_index, 'qss_lm_sample_w'
        ).value)
        height = int(_qss_safe_collection_item(
            attrs['qss_lm_sample_h'].data, poly_index, 'qss_lm_sample_h'
        ).value)
        face_lit = 0
        face_max = 0.0
        for sy in range(height):
            top_y = y0 + sy * scale + (scale - 1) // 2
            blender_y = size - 1 - top_y
            for sx in range(width):
                px = x0 + sx * scale + (scale - 1) // 2
                if not (0 <= px < size and 0 <= blender_y < size):
                    continue
                offset = (blender_y * size + px) * 4
                luminance = (
                    0.2126 * pixels[offset]
                    + 0.7152 * pixels[offset + 1]
                    + 0.0722 * pixels[offset + 2]
                )
                total_luxels += 1
                face_max = max(face_max, luminance)
                if luminance > threshold:
                    face_lit += 1
                    lit_luxels += 1
        if face_lit:
            lit_faces += 1
        face_max_luminance = max(face_max_luminance, face_max)
    return {
        'total_faces': total_faces,
        'lit_faces': lit_faces,
        'dark_faces': max(0, total_faces - lit_faces),
        'total_luxels': total_luxels,
        'lit_luxels': lit_luxels,
        'face_max_luminance': face_max_luminance,
    }


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


def _qss_read_source_face_sample(mesh, poly_index, face_id, parsed, sample_count=None):
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
    sample_w = int(_qss_safe_collection_item(attrs['qss_lm_sample_w'].data, poly_index, 'qss_lm_sample_w').value)
    sample_h = int(_qss_safe_collection_item(attrs['qss_lm_sample_h'].data, poly_index, 'qss_lm_sample_h').value)
    if sample_count is None:
        source_rgb = parsed.bspx_lumps.get('RGBLIGHTING')
        sample_count = max(len(parsed.lumps[bsp.LUMP_LIGHTING]), len(source_rgb) // 3 if source_rgb else 0)
    decoupled_records, styles_by_face = _qss_decoupled_lightmap_state(parsed, sample_count)
    decoupled = decoupled_records[face_id] if decoupled_records is not None else None
    if decoupled_records is not None and decoupled is None:
        return None
    if decoupled is not None:
        expected_w, expected_h = decoupled['width'], decoupled['height']
        s_min = t_min = 0.0
        lmvecs = decoupled['lmvecs']
        s_values = [
            p[0] * lmvecs[0] + p[1] * lmvecs[1] + p[2] * lmvecs[2] + lmvecs[3]
            for p in positions
        ]
        t_values = [
            p[0] * lmvecs[4] + p[1] * lmvecs[5] + p[2] * lmvecs[6] + lmvecs[7]
            for p in positions
        ]
        if (min(s_values) < -0.01 or min(t_values) < -0.01
                or max(s_values) > expected_w - 1 + 0.01
                or max(t_values) > expected_h - 1 + 0.01):
            raise bsp.BSPError(
                f'DECOUPLED_LM face {face_id} projection falls outside its {expected_w}x{expected_h} sample grid.'
            )
        light_offset = decoupled['offset']
    else:
        s_min, t_min, extent_s, extent_t, _svec, _tvec = _calc_face_lightmap_extents(positions, texinfo)
        expected_w = (extent_s >> 4) + 1
        expected_h = (extent_t >> 4) + 1
        lmvecs = None
        light_offset = int(face[9])
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
        'light_offset': light_offset,
        'decoupled_lmvecs': lmvecs,
        'width': sample_w,
        'height': sample_h,
        'styles': styles_by_face[face_id],
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
    source_lit_rgb, _source_lighting_kind = bsp.resolve_rgb_lighting(
        parsed.bspx_lumps,
        parsed.lumps[bsp.LUMP_LIGHTING],
        os.path.splitext(source_path)[0] + '.lit',
    )
    light_sample_count = max(
        len(parsed.lumps[bsp.LUMP_LIGHTING]),
        len(source_lit_rgb) // 3 if source_lit_rgb is not None else 0,
    )
    mesh = obj.data
    if len(mesh.polygons) == 0:
        raise bsp.BSPError('The selected QSS mesh has no polygons.')
    image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
    if image is None or image.size[0] != image.size[1]:
        raise bsp.BSPError('The square lightmap atlas is missing. Re-import the BSP.')
    size = int(image.size[0])
    resolution = _qss_lightmap_pixel_scale(obj, image)
    scale = max(1, int(obj.get('qss_lightmap_scale', 1))) * resolution
    gutter = max(0, int(obj.get('qss_lightmap_gutter', 0))) * resolution
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
        face_info = _qss_read_source_face_sample(mesh, poly_index, face_id, parsed, light_sample_count)
        if face_info is None:
            continue
        x0 = face_info['atlas_x'] * resolution + gutter
        y0 = face_info['atlas_y'] * resolution + gutter
        for sy in range(face_info['height']):
            for sx in range(face_info['width']):
                lmvecs = face_info.get('decoupled_lmvecs')
                if lmvecs is not None:
                    s_value = float(sx) - float(lmvecs[3])
                    t_value = float(sy) - float(lmvecs[7])
                    qpoint = lighting_utils.solve_texinfo_plane(
                        lmvecs[0:3], lmvecs[4:7],
                        face_info['plane_normal'], s_value, t_value,
                        face_info['plane_distance']
                    )
                else:
                    s_value = face_info['s_min'] + sx * 16.0 - float(face_info['texinfo'][3])
                    t_value = face_info['t_min'] + sy * 16.0 - float(face_info['texinfo'][7])
                    qpoint = lighting_utils.solve_texinfo_plane(
                        face_info['texinfo'][0:3], face_info['texinfo'][4:7],
                        face_info['plane_normal'], s_value, t_value,
                        face_info['plane_distance']
                    )
                if qpoint is None:
                    raise bsp.BSPError(f'Face {face_id} has singular lightmap projection axes; cannot locate its luxels.')
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

    def invoke(self, context, event):
        obj = context.object
        settings = _qss_config_settings()
        if obj and _qss_has_baked_lightmap(obj) and str(settings.get("rebake_behavior", "ASK")).upper() == "ASK":
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

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
        imported_lights = [
            o for o in _qss_active_map_objects(scene, obj)
            if o.type == 'LIGHT' and o.get('qss_light_role') in {
                'quake_entity_light', 'quake_world_sunlight'
            }
        ]
        if not imported_lights:
            self.report({'ERROR'}, "No imported Quake lights are present in this scene.")
            return {'CANCELLED'}
        current_energy_scale = max(0.0, float(scene.qss_light_energy_scale))
        if current_energy_scale <= 0.0:
            self.report({'ERROR'}, "Live light scale is 0, so a light bake must be black. Set Live light scale to 1 or higher, click Apply Light Energy Scale, verify Live Lights, then bake.")
            return {'CANCELLED'}
        output_scale = max(0.0, float(getattr(scene, 'qss_bake_output_scale', 1.0)))
        if output_scale <= 0.0:
            self.report({'ERROR'}, "Bake output scale is 0. Set it above 0 before baking.")
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
        old_object_visibility = (
            bool(obj.hide_render), bool(obj.hide_viewport), bool(obj.hide_get())
        )
        active_map_collection = bpy.data.collections.get(obj.get("qss_map_collection", ""))
        old_map_collection_visibility = (
            (bool(active_map_collection.hide_render), bool(active_map_collection.hide_viewport))
            if active_map_collection is not None else None
        )
        material_states = []
        bake_succeeded = False
        progress_wm = context.window_manager
        progress_workspace = getattr(context, 'workspace', None)
        progress_started = False
        def _bake_progress(step, label):
            if progress_started:
                progress_wm.progress_update(step)
            if progress_workspace is not None and hasattr(progress_workspace, 'status_text_set'):
                try:
                    progress_workspace.status_text_set(f"Slipgate: {label}")
                except Exception:
                    pass
            _qss_log('INFO', 'bake', label)
        old_preview_mode = obj.get('qss_preview_mode', 'lightmap')
        old_object_calibration = float(obj.get('qss_light_energy_calibration', 1.0))
        old_light_calibrations = {
            light_obj.name: float(light_obj.get('qss_energy_calibration', old_object_calibration))
            for light_obj in imported_lights
        }
        updated_lights = _apply_quake_light_energy_scale(scene)
        max_energy = max((float(o.data.energy) for o in imported_lights), default=0.0)
        try:
            progress_wm.progress_begin(0, 5)
            progress_started = True
            _bake_progress(0, f"Starting Cycles lightmap bake for {obj.name}: {len(imported_lights)} lights")
            _set_black_preview_world(scene, obj)
            scene.render.engine = 'CYCLES'
            # Re-apply after selecting Cycles: delay 0/5 use point-sized emitters
            # here so the node correction matches the calibrated radial curves.
            _apply_quake_light_energy_scale(scene)
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
            # Cycles renders the scene, so temporarily guarantee that the
            # active BSP and its own QSS lights are render-visible. Other maps'
            # lights stay excluded; merely checking the QSS role would also
            # enable lights belonging to every hidden map in the scene.
            active_light_pointers = {int(light_obj.as_pointer()) for light_obj in imported_lights}
            for light_obj in scene.objects:
                if light_obj.type != 'LIGHT':
                    continue
                old_light_render_states.append((
                    light_obj,
                    bool(light_obj.hide_render),
                    bool(light_obj.hide_viewport),
                    bool(light_obj.hide_get()),
                ))
                is_active_map_light = int(light_obj.as_pointer()) in active_light_pointers
                light_obj.hide_render = not is_active_map_light
                if is_active_map_light:
                    light_obj.hide_viewport = False
                    try:
                        light_obj.hide_set(False)
                    except Exception:
                        pass
            obj.hide_render = False
            obj.hide_viewport = False
            try:
                obj.hide_set(False)
            except Exception:
                pass
            if active_map_collection is not None:
                active_map_collection.hide_render = False
                active_map_collection.hide_viewport = False
            context.view_layer.update()
            _bake_progress(1, 'Preparing active map visibility and Cycles bake settings')
            obj['qss_last_bake_attempt_scene_visibility'] = (
                f"mesh hide_render={bool(obj.hide_render)} hide_viewport={bool(obj.hide_viewport)} "
                f"hide_get={bool(obj.hide_get())}; active_map={active_map_collection.name if active_map_collection else 'none'}"
            )

            for name in ('target', 'use_pass_color', 'use_pass_diffuse', 'use_pass_emit', 'use_pass_glossy', 'use_pass_transmission', 'use_pass_direct', 'use_pass_indirect', 'use_clear', 'margin', 'margin_type'):
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
                # Each packed face island has a reserved gutter. Extend the
                # baked edge pixels into that gutter so rasterization/texture
                # filtering cannot expose the black unbaked bake target.
                bake_margin = lighting_utils.lightmap_bake_margin_pixels(
                    int(obj.get('qss_lightmap_gutter', 2)),
                    _qss_lightmap_pixel_scale(obj, image),
                )
                scene.render.bake.margin = bake_margin
                if hasattr(scene.render.bake, 'margin_type'):
                    scene.render.bake.margin_type = 'EXTEND'
                obj['qss_last_bake_margin'] = int(bake_margin)
            scene.cycles.samples = max(96, old_cycles['samples'])
            bake_bounces = max(0, int(getattr(scene, 'qss_bake_bounces', 2)))
            scene.cycles.diffuse_bounces = bake_bounces
            scene.cycles.max_bounces = max(old_cycles['max_bounces'], bake_bounces + 1)
            _bake_progress(2, f'Configuring {len(mesh.materials)} material slots and {bake_bounces} diffuse bounces')

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

            _bake_progress(3, f'Running Cycles diffuse bake ({len(material_states)} materials, {int(image.size[0])}x{int(image.size[1])} atlas)')
            with context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj],
                selected_editable_objects=[obj]
            ):
                bake_result = bpy.ops.object.bake(type='DIFFUSE')
            obj['qss_last_bake_attempt_operator_result'] = ','.join(sorted(bake_result))
            _bake_progress(4, 'Cycles bake returned; validating sampled luxels and atlas coverage')
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
            raw_face_coverage = _lightmap_face_coverage(obj, bake_target)
            obj['qss_last_bake_attempt_face_coverage'] = str(raw_face_coverage)
            source_image = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
            source_values = _lightmap_sample_luminances(obj, source_image) if source_image else []
            source_mean = (sum(source_values) / len(source_values)) if source_values else 0.0
            energy_scale = max(0.0, float(scene.qss_light_energy_scale))
            max_energy_after_bake = max((float(o.data.energy) for o in imported_lights), default=0.0)
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
            if not bake_values or raw_bake_mean <= 1e-8:
                obj['qss_last_bake_attempt_lights'] = '; '.join(
                    f'{lamp.name}: {float(lamp.data.energy):.6g}W type={lamp.data.type} '
                    f'hide_render={bool(lamp.hide_render)} hide_viewport={bool(lamp.hide_viewport)} '
                    f'hide_get={bool(lamp.hide_get())} cutoff={float(getattr(lamp.data, "cutoff_distance", 0.0)):.4g}'
                    for lamp in imported_lights
                )
                raise bsp.BSPError(
                    'Cycles completed without producing any nonzero sampled BSP lightmap luxels. '
                    f'Energy scale={energy_scale:g}; output scale={float(getattr(scene, "qss_bake_output_scale", 1.0)):.6g}; '
                    f'imported lamps={len(imported_lights)}; max lamp energy={max_energy_after_bake:.6g} W; '
                    f'sampled luxels={len(bake_values)}; source mean={source_mean:.6g}; '
                    f'whole atlas nonzero pixels={raw_image_stats["nonzero_pixels"]}/{raw_image_stats["pixels"]}; '
                    f'whole atlas max RGB={raw_image_stats["max_channel"]:.6g}. '
                    'The failed bake was discarded. Use Save Lighting Diagnostics and send the report.'
                )
            if bool(getattr(scene, 'qss_bake_match_source', True)) and source_mean > 1e-8:
                # Source matching is an image-atlas operation only. Preserve
                # imported lamp energies and the user's live energy slider.
                obj['qss_calibration_source_mean'] = source_mean
                obj['qss_calibration_bake_mean'] = raw_bake_mean
                obj['qss_last_bake_atlas_match_scale'] = (
                    lighting_utils.bake_atlas_match_scale(source_mean, raw_bake_mean)
                )

            # Copy the completed float bake into the project's current atlas.
            # Source-match normalization is a global linear calibration, not a
            # claim that Blender's inverse-square lights reproduce every Quake luxel.
            baked = array.array('f', [0.0]) * (int(bake_target.size[0]) * int(bake_target.size[1]) * 4)
            bake_target.pixels.foreach_get(baked)
            # The bake already contains the selected live-light scale.
            # Normalize only the baked image to the source atlas mean; never
            # feed this image multiplier back into the imported scene lights.
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
            _bake_progress(5, 'Bake validated and atlas updated; restoring Blender scene state')
            values = _lightmap_sample_luminances(obj, image)
            obj['qss_last_bake_luxel_mean'] = float(sum(values) / max(1, len(values)))
            obj['qss_last_bake_luxel_max'] = float(max(values, default=0.0))
            obj['qss_last_bake_energy_scale'] = float(scene.qss_light_energy_scale)
            obj['qss_last_bake_output_scale'] = float(post_scale)
            obj['qss_last_bake_raw_mean'] = float(raw_bake_mean)
            obj['qss_last_bake_source_mean'] = float(source_mean)
            # Source matching now changes only the image atlas; lamp calibration
            # remains the user's live-light multiplier.
            obj['qss_last_bake_calibration'] = float(
                obj.get('qss_light_energy_calibration', 1.0)
            )
            obj['qss_last_bake_bounces'] = bake_bounces
            obj['qss_lightmap_source'] = 'cycles_bake_from_quake_entities'
            obj['qss_lightmap_gradient_baked'] = True
            obj['qss_baked_lightmap_image_name'] = image.name
            old_painted_bake = bpy.data.images.get(obj.get("qss_painted_baked_lightmap", ""))
            if old_painted_bake is not None:
                try:
                    bpy.data.images.remove(old_painted_bake, do_unlink=True)
                except Exception:
                    pass
            obj["qss_painted_baked_lightmap"] = ""
            obj['qss_last_bake_backup'] = previous_snapshot.name
            obj['qss_bake_material_count'] = len(material_states)
            obj['qss_bake_light_count'] = updated_lights
            if old_previous_snapshot and old_previous_snapshot != previous_snapshot:
                try:
                    bpy.data.images.remove(old_previous_snapshot)
                except Exception:
                    pass
            _qss_log('INFO', 'bake', f"Completed: {updated_lights} lights, {len(material_states)} materials, "
                     f"{raw_face_coverage['lit_faces']}/{raw_face_coverage['total_faces']} faces lit; "
                     f"mean={obj['qss_last_bake_luxel_mean']:.5g}, atlas_scale={post_scale:.5g}")
            self.report({'INFO'},
                        f"Bake complete: {updated_lights} lights, {len(material_states)} materials, "
                        f"{raw_face_coverage['lit_faces']}/{raw_face_coverage['total_faces']} faces lit, "
                        f"{raw_face_coverage['lit_luxels']}/{raw_face_coverage['total_luxels']} raw luxels lit, "
                        f"mean {obj['qss_last_bake_luxel_mean']:.4g}, "
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
            _qss_log('ERROR', 'bake', f"Failed; atlas and light calibration restored: {exc}")
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
            for light_obj, was_hidden_render, was_hidden_viewport, was_hidden_set in old_light_render_states:
                try:
                    light_obj.hide_render = was_hidden_render
                    light_obj.hide_viewport = was_hidden_viewport
                    light_obj.hide_set(was_hidden_set)
                except Exception:
                    pass
            try:
                obj.hide_render, obj.hide_viewport = old_object_visibility[0], old_object_visibility[1]
                obj.hide_set(old_object_visibility[2])
            except Exception:
                pass
            if active_map_collection is not None and old_map_collection_visibility is not None:
                try:
                    active_map_collection.hide_render = old_map_collection_visibility[0]
                    active_map_collection.hide_viewport = old_map_collection_visibility[1]
                except Exception:
                    pass
            try:
                scene.render.engine = old_engine
                _apply_quake_light_energy_scale(scene)
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
            if progress_started:
                try:
                    progress_wm.progress_end()
                except Exception:
                    pass
            if progress_workspace is not None and hasattr(progress_workspace, 'status_text_set'):
                try:
                    progress_workspace.status_text_set(None)
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
    bl_description = 'Run a temporary Cycles bake, calibrate imported live lights to the source atlas mean, restore the original lightmap, and return to Live Lights'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.get('qss_object_role') == 'quake_bsp29'
                    and obj.get('qss_original_lightmap_backup') and obj.get('qss_light_entity_count', 0) > 0)

    def execute(self, context):
        obj = context.object
        scene = context.scene
        source_image = bpy.data.images.get(obj.get('qss_original_lightmap_backup', ''))
        current_image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        if source_image is None or current_image is None:
            self.report({'ERROR'}, 'The current or original source lightmap image is missing.')
            return {'CANCELLED'}

        active_map_objects = _qss_active_map_objects(scene, obj)
        imported_lights = [
            light_obj for light_obj in active_map_objects
            if light_obj.type == 'LIGHT'
            and light_obj.get('qss_light_role') in {'quake_entity_light', 'quake_world_sunlight'}
        ]
        if not imported_lights:
            self.report({'ERROR'}, 'No imported lights belong to the active map.')
            return {'CANCELLED'}

        original_pixels = array.array('f', [0.0]) * len(current_image.pixels)
        current_image.pixels.foreach_get(original_pixels)
        old_preview_mode = str(obj.get('qss_preview_mode', 'source'))
        old_source = obj.get('qss_lightmap_source', 'original_bsp_lightmaps')
        old_scale = float(scene.qss_light_energy_scale)
        old_manual = max(0.0, float(obj.get('qss_manual_light_energy_calibration', 1.0)))
        old_legacy_calibration = float(obj.get('qss_light_energy_calibration', old_manual))
        old_light_manual = {
            light_obj.name: float(light_obj.get('qss_manual_energy_calibration', old_manual))
            for light_obj in imported_lights
        }
        old_light_legacy = {
            light_obj.name: float(light_obj.get('qss_energy_calibration', old_manual))
            for light_obj in imported_lights
        }
        bake_scale = max(old_scale, 0.01)
        scene.qss_light_energy_scale = bake_scale
        scene.qss_bake_match_source = True

        result = bpy.ops.qss.bake_scene_lights()
        if 'FINISHED' not in result:
            scene.qss_light_energy_scale = old_scale
            obj['qss_lightmap_source'] = old_source
            return {'CANCELLED'}

        try:
            # The normal bake now source-matches only its atlas. This explicit
            # calibration action separately promotes that measured source/raw
            # ratio into the manual live-light multiplier.
            source_mean = float(obj.get('qss_last_bake_source_mean', 0.0))
            raw_mean = float(obj.get('qss_last_bake_raw_mean', 0.0))
            measured_scale = max(0.0, float(obj.get('qss_last_bake_energy_scale', bake_scale)))
            if source_mean <= 1e-8 or raw_mean <= 1e-8 or measured_scale <= 0.0:
                raise bsp.BSPError(
                    'The calibration bake did not produce usable source and raw means. '
                    'The original lightmap and live-light settings have been restored.'
                )
            calibration_step = lighting_utils.calibration_factor(
                source_mean, raw_mean, measured_scale
            )
            new_manual = old_manual * calibration_step
            if not math.isfinite(new_manual) or new_manual <= 0.0:
                raise bsp.BSPError('The calculated manual light calibration is invalid.')

            obj['qss_manual_light_energy_calibration'] = float(new_manual)
            # Keep the legacy summary key readable in existing diagnostics and
            # saved .blend files, while runtime lamp application uses the
            # explicitly named manual calibration property.
            obj['qss_light_energy_calibration'] = float(new_manual)
            for light_obj in imported_lights:
                light_obj['qss_manual_energy_calibration'] = float(new_manual)
                light_obj['qss_energy_calibration'] = float(new_manual)

            current_image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
            if current_image is None:
                raise bsp.BSPError('The lightmap atlas disappeared after calibration bake.')
            _copy_image_pixels(source_image, current_image)
            backup = bpy.data.images.get(obj.get('qss_last_bake_backup', ''))
            if backup is not None:
                bpy.data.images.remove(backup)
            obj['qss_last_bake_backup'] = ''
            obj['qss_painted_baked_lightmap'] = ''
            obj['qss_lightmap_source'] = 'original_bsp_lightmaps'
            obj['qss_lightmap_gradient_baked'] = False
            scene.qss_light_energy_scale = 1.0
            _apply_quake_light_energy_scale(scene)
            _set_lighting_preview(context, obj, 'realtime')
            self.report(
                {'INFO'},
                f"Manual live-light calibration set to {new_manual:.4g}x. "
                "Original lightmap restored; live scale is now 1.0. "
                "Spatial falloff remains an Eevee/Cycles approximation of Quake attenuation."
            )
            return {'FINISHED'}
        except Exception as exc:
            try:
                current_image = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
                if current_image is not None:
                    current_image.pixels.foreach_set(original_pixels)
                    current_image.update()
            except Exception:
                pass
            scene.qss_light_energy_scale = old_scale
            obj['qss_manual_light_energy_calibration'] = old_manual
            obj['qss_light_energy_calibration'] = old_legacy_calibration
            for light_obj in imported_lights:
                light_obj['qss_manual_energy_calibration'] = old_light_manual.get(
                    light_obj.name, old_manual
                )
                light_obj['qss_energy_calibration'] = old_light_legacy.get(
                    light_obj.name, old_legacy_calibration
                )
            _apply_quake_light_energy_scale(scene)
            obj['qss_lightmap_source'] = old_source
            try:
                _set_lighting_preview(context, obj, old_preview_mode)
            except Exception:
                pass
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


def _qss_restore_focus_clip_session(area=None):
    """Restore and stop a temporary face-focus clipping session for one 3D View."""
    global _qss_focus_clip_sessions
    keys = []
    if area is not None:
        try:
            keys = [area.as_pointer()]
        except Exception:
            keys = []
    else:
        keys = list(_qss_focus_clip_sessions)
    for key in keys:
        session = _qss_focus_clip_sessions.get(key)
        if session is not None:
            try:
                session._finish_restore()
            except Exception as exc:
                print(f"QSS: could not restore temporary focus clipping: {exc}")
            _qss_focus_clip_sessions.pop(key, None)


def _qss_selected_face_for_focus(context, obj, cycle_direction=1):
    """Return the next selected face's world-space focus geometry."""
    import bmesh
    from mathutils import Vector

    area = context.area if context.area and context.area.type == "VIEW_3D" else None
    area_key = int(area.as_pointer()) if area is not None else 0
    state_key = (int(obj.as_pointer()), area_key)

    if context.mode == "EDIT_MESH":
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        selected = sorted(face.index for face in bm.faces if face.select and not face.hide)
        if not selected:
            raise bsp.BSPError("Select a visible face before using Focus.")
        active = bm.faces.active
        active_index = active.index if active is not None and active.select and not active.hide else None
        signature = (tuple(selected), active_index)
        previous = _qss_focus_cycle_state.get(state_key)
        previous_index = previous.get("face_index") if previous and previous.get("signature") == signature else None
        face_index = viewport_utils.next_selected_face_index(
            selected, active_index, previous_index, cycle_direction
        )
        face = bm.faces[face_index]
        center_local = face.calc_center_median()
        normal_local = face.normal.copy()
        points_local = [vertex.co.copy() for vertex in face.verts]
    elif _qss_is_texture_paint_context(context):
        selected = sorted(poly.index for poly in obj.data.polygons if poly.select)
        if not selected:
            raise bsp.BSPError("No faces are selected in the Texture Paint face mask.")
        signature = (tuple(selected), None)
        previous = _qss_focus_cycle_state.get(state_key)
        previous_index = previous.get("face_index") if previous and previous.get("signature") == signature else None
        face_index = viewport_utils.next_selected_face_index(
            selected, None, previous_index, cycle_direction
        )
        face = obj.data.polygons[face_index]
        center_local = face.center.copy()
        normal_local = face.normal.copy()
        points_local = [obj.data.vertices[index].co.copy() for index in face.vertices]
    else:
        raise bsp.BSPError("Focus requires a selected face in Edit Mode or Texture Paint face-mask mode.")

    _qss_focus_cycle_state[state_key] = {
        "signature": signature,
        "face_index": int(face_index),
    }
    world_matrix = obj.matrix_world
    normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
    center_world = world_matrix @ Vector(center_local)
    normal_world = (normal_matrix @ Vector(normal_local)).normalized()
    if normal_world.length <= 1e-8:
        raise bsp.BSPError("The selected face has an invalid surface normal.")
    points_world = [world_matrix @ Vector(point) for point in points_local]
    radius = max((point - center_world).length for point in points_world) if points_world else 0.0
    return center_world, normal_world, points_world, max(radius, 1e-4), f"face {face_index}"


class QSS_OT_focus_clip_watch(Operator):
    bl_idname = "qss.focus_clip_watch"
    bl_label = "Restore Face Focus Clipping"
    bl_description = "Restore the normal viewport clipping range when painting ends or the view moves"
    clip_start: FloatProperty(default=0.1, min=0.0001)
    clip_end: FloatProperty(default=1000.0, min=0.01)

    def invoke(self, context, event):
        area = context.area if context.area and context.area.type == "VIEW_3D" else None
        if area is None:
            self.report({"WARNING"}, "Temporary face clipping needs a 3D View.")
            return {"CANCELLED"}
        space = area.spaces.active
        if space is None or space.type != "VIEW_3D" or space.region_3d is None:
            return {"CANCELLED"}
        _qss_restore_focus_clip_session(area)
        self._area = area
        self._space = space
        self._object = context.object
        self._window_manager = context.window_manager
        self._original_clip_start = float(self.clip_start)
        self._original_clip_end = float(self.clip_end)
        region = space.region_3d
        self._view_location = region.view_location.copy()
        self._view_rotation = region.view_rotation.copy()
        self._view_distance = float(region.view_distance)
        self._finished = False
        try:
            self._timer = self._window_manager.event_timer_add(0.12, window=context.window)
            self._window_manager.modal_handler_add(self)
        except Exception as exc:
            self._finish_restore()
            self.report({"WARNING"}, f"Could not monitor face-focus clipping: {exc}")
            return {"CANCELLED"}
        _qss_focus_clip_sessions[area.as_pointer()] = self
        return {"RUNNING_MODAL"}

    def _view_was_moved(self):
        try:
            region = self._space.region_3d
            if (region.view_location - self._view_location).length > 1e-4:
                return True
            if region.view_rotation.rotation_difference(self._view_rotation).angle > 1e-4:
                return True
            return abs(float(region.view_distance) - self._view_distance) > max(1e-4, self._view_distance * 1e-5)
        except Exception:
            return True

    def _finish_restore(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        try:
            self._space.clip_start = self._original_clip_start
            self._space.clip_end = self._original_clip_end
            self._area.tag_redraw()
        except Exception:
            pass
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                self._window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None
        try:
            key = self._area.as_pointer()
            if _qss_focus_clip_sessions.get(key) is self:
                _qss_focus_clip_sessions.pop(key, None)
        except Exception:
            pass

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}
        if event.type == "TIMER":
            if not _qss_focus_clip_context(context) or context.object != self._object:
                self._finish_restore()
                return {"FINISHED"}
            if self._view_was_moved():
                self._finish_restore()
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish_restore()


class QSS_OT_frame_selection(Operator):
    bl_idname = "qss.frame_selection"
    bl_label = "Focus on Face"
    bl_description = (
        "Smoothly frame the selected face; click again to cycle selected faces. "
        "Hover over this button and scroll to cycle forward or backward."
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(
            _qss_is_map_object(obj)
            and (context.mode == "EDIT_MESH" or _qss_is_texture_paint_context(context))
        )

    def _mouse_over_button(self, event):
        # Blender's Python panel API does not expose the exact button rectangle
        # to a modal operator. The activation point plus a tight hit box gives
        # wheel gestures to this control without stealing viewport zoom.
        return (
            abs(float(event.mouse_x) - self._button_x) <= 36.0
            and abs(float(event.mouse_y) - self._button_y) <= 16.0
        )

    def _begin_focus(self, context, direction=1):
        from mathutils import Vector

        _qss_restore_focus_clip_session(self._area)
        if _qss_focus_clip_context(context):
            if self._clip_original is None:
                self._clip_original = (
                    float(self._space.clip_start), float(self._space.clip_end)
                )
            else:
                self._space.clip_start, self._space.clip_end = self._clip_original

        center, normal, points, radius, label = _qss_selected_face_for_focus(
            context, self._object, cycle_direction=direction
        )
        region_3d = self._space.region_3d
        if region_3d.view_perspective == "CAMERA":
            region_3d.view_perspective = "PERSP"

        camera_side = region_3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        normal = Vector(viewport_utils.face_normal_toward_view(normal, camera_side))
        target_rotation = normal.to_track_quat("Z", "Y")
        right = target_rotation @ Vector((1.0, 0.0, 0.0))
        up = target_rotation @ Vector((0.0, 1.0, 0.0))
        half_width = max(abs((point - center).dot(right)) for point in points)
        half_height = max(abs((point - center).dot(up)) for point in points)
        window_region = next(
            (item for item in self._area.regions if item.type == "WINDOW"), None
        )
        if window_region is None:
            raise bsp.BSPError("The 3D View has no usable window region for face framing.")
        aspect = max(0.1, float(window_region.width) / max(1.0, float(window_region.height)))
        unit_scale = max(
            1e-5, float(self._object.get("qss_unit_scale", DEFAULT_QUAKE_UNIT_SCALE))
        )
        horizontal_fov = float(_qss_config_settings().get("viewport_fov_degrees", 90.0))
        vertical_fov = math.degrees(
            2.0 * math.atan(math.tan(math.radians(horizontal_fov) * 0.5) / aspect)
        )
        distance = viewport_utils.face_focus_distance(
            half_width, half_height, aspect, radius, unit_scale,
            fov_degrees=vertical_fov, margin=1.65,
        )

        self._start_location = region_3d.view_location.copy()
        self._start_rotation = region_3d.view_rotation.copy()
        self._start_distance = float(region_3d.view_distance)
        self._target_location = Vector(center)
        self._target_rotation = target_rotation
        self._target_distance = float(distance)
        self._animation_start = time.perf_counter()
        self._animation_duration = 0.5
        self._is_animating = True
        self._target_label = label
        self._clip_watch_started = False

        if _qss_focus_clip_context(context):
            near_gap = max(radius * 0.02, unit_scale * 0.05, 0.005)
            far_gap = max(radius * 1.5, unit_scale * 2.0, 0.1)
            self._space.clip_start = max(0.0001, distance - near_gap)
            self._space.clip_end = max(
                self._space.clip_start * 1.05, distance + far_gap
            )
        self._area.tag_redraw()
        return label

    def _launch_clip_watch(self, context):
        if self._clip_original is None or self._clip_watch_started:
            return
        if not _qss_focus_clip_context(context):
            self._space.clip_start, self._space.clip_end = self._clip_original
            self._clip_original = None
            return
        try:
            with context.temp_override(window=self._window, area=self._area):
                result = bpy.ops.qss.focus_clip_watch(
                    "INVOKE_DEFAULT",
                    clip_start=self._clip_original[0],
                    clip_end=self._clip_original[1],
                )
            if "CANCELLED" in result:
                raise RuntimeError("Blender could not start the clipping restoration watcher.")
            self._clip_watch_started = True
        except Exception as exc:
            self._space.clip_start, self._space.clip_end = self._clip_original
            self._clip_original = None
            self.report({"WARNING"}, f"Temporary face clipping was not retained: {exc}")

    def _finish_modal(self, context, restore_clip=False):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        if restore_clip:
            try:
                _qss_restore_focus_clip_session(self._area)
                if self._clip_original is not None:
                    self._space.clip_start, self._space.clip_end = self._clip_original
            except Exception:
                pass
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                self._window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None
        try:
            key = self._area.as_pointer()
            if _qss_focus_transition_sessions.get(key) is self:
                _qss_focus_transition_sessions.pop(key, None)
        except Exception:
            pass
        try:
            self._area.tag_redraw()
        except Exception:
            pass

    def invoke(self, context, event):
        area = context.area if context.area and context.area.type == "VIEW_3D" else None
        if area is None:
            self.report({"WARNING"}, "Focus needs an open 3D View.")
            return {"CANCELLED"}
        space = area.spaces.active if area.spaces.active and area.spaces.active.type == "VIEW_3D" else None
        if space is None or space.region_3d is None:
            self.report({"WARNING"}, "The active 3D View has no usable 3D region.")
            return {"CANCELLED"}

        existing = _qss_focus_transition_sessions.get(area.as_pointer())
        if existing is not None and existing is not self:
            existing._finish_modal(
                context, restore_clip=not getattr(existing, "_clip_watch_started", False)
            )

        self._area = area
        self._space = space
        self._object = context.object
        self._window = context.window
        self._window_manager = context.window_manager
        self._button_x = float(event.mouse_x)
        self._button_y = float(event.mouse_y)
        self._hovered = True
        self._finished = False
        self._timer = None
        self._clip_original = None
        self._clip_watch_started = False
        self._initial_paint_mode = _qss_focus_clip_context(context)

        try:
            self._begin_focus(context, direction=1)
            self._timer = self._window_manager.event_timer_add(
                0.02, window=self._window
            )
            self._window_manager.modal_handler_add(self)
            _qss_focus_transition_sessions[area.as_pointer()] = self
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self._finish_modal(context, restore_clip=True)
            self.report({"ERROR"}, f"Could not focus the selected face: {exc}")
            return {"CANCELLED"}

    def execute(self, context):
        area = context.area if context.area and context.area.type == "VIEW_3D" else None
        if area is None:
            self.report({"WARNING"}, "Focus needs an open 3D View.")
            return {"CANCELLED"}
        self._area = area
        self._space = area.spaces.active
        self._object = context.object
        self._window = context.window
        self._clip_original = None
        self._clip_watch_started = False
        try:
            self._begin_focus(context, direction=1)
            region_3d = self._space.region_3d
            region_3d.view_location = self._target_location
            region_3d.view_rotation = self._target_rotation
            region_3d.view_distance = self._target_distance
            self._launch_clip_watch(context)
            self._area.tag_redraw()
            self.report({"INFO"}, f"Focused {self._target_label} along its surface normal.")
            return {"FINISHED"}
        except Exception as exc:
            if self._clip_original is not None:
                self._space.clip_start, self._space.clip_end = self._clip_original
            self.report({"ERROR"}, f"Could not focus the selected face: {exc}")
            return {"CANCELLED"}

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}
        if context.object != self._object:
            self._finish_modal(context, restore_clip=not self._clip_watch_started)
            return {"FINISHED"}
        if self._initial_paint_mode and not _qss_focus_clip_context(context):
            self._finish_modal(context, restore_clip=True)
            return {"FINISHED"}

        if event.type == "TIMER":
            if self._is_animating:
                progress = min(
                    1.0,
                    max(0.0, (time.perf_counter() - self._animation_start) / self._animation_duration),
                )
                eased = progress * progress * (3.0 - 2.0 * progress)
                region_3d = self._space.region_3d
                region_3d.view_location = self._start_location.lerp(
                    self._target_location, eased
                )
                region_3d.view_rotation = self._start_rotation.slerp(
                    self._target_rotation, eased
                )
                region_3d.view_distance = (
                    self._start_distance
                    + (self._target_distance - self._start_distance) * eased
                )
                self._area.tag_redraw()
                if progress >= 1.0:
                    self._is_animating = False
                    self._launch_clip_watch(context)
                    self.report(
                        {"INFO"},
                        f"Focused {self._target_label}. Click again or scroll over Focus to cycle selected faces.",
                    )
                    if not self._hovered:
                        self._finish_modal(context, restore_clip=False)
                        return {"FINISHED"}
            elif not self._hovered:
                self._finish_modal(context, restore_clip=False)
                return {"FINISHED"}
            return {"RUNNING_MODAL"}

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self._hovered = self._mouse_over_button(event)
            if not self._hovered and not self._is_animating:
                self._finish_modal(context, restore_clip=False)
                return {"FINISHED"}
            return {"PASS_THROUGH"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and self._hovered and self._mouse_over_button(event):
            try:
                self._begin_focus(
                    context, direction=1 if event.type == "WHEELUPMOUSE" else -1
                )
            except Exception as exc:
                self.report({"WARNING"}, f"Could not cycle focused face: {exc}")
            return {"RUNNING_MODAL"}

        if event.type in {"LEFTMOUSE", "RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            restore = not self._clip_watch_started
            self._finish_modal(context, restore_clip=restore)
            return {"CANCELLED"} if event.type == "ESC" else {"PASS_THROUGH"}

        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish_modal(context, restore_clip=not self._clip_watch_started)


def _qss_toggle_face_isolation_in_edit(obj):
    """Toggle the saved Edit-Mode face visibility/selection snapshot."""
    import bmesh
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    vertex_count, edge_count, face_count = len(bm.verts), len(bm.edges), len(bm.faces)
    snapshot_key = "qss_face_visibility_snapshot"
    payload = obj.get(snapshot_key, "")

    if visibility_utils.snapshot_is_active(payload):
        try:
            hidden_faces, selected_faces = visibility_utils.decode_face_visibility_snapshot(
                payload, vertex_count, edge_count, face_count
            )
        except ValueError:
            # Topology changed since isolation. Discard the stale indices and
            # ask the user to Reveal Hidden before creating a fresh snapshot.
            try:
                del obj[snapshot_key]
            except Exception:
                pass
            raise
        for face in bm.faces:
            face.hide_set(False)
        for face_index in sorted(hidden_faces):
            bm.faces[face_index].hide_set(True)
        for face in bm.faces:
            if face.select:
                face.select_set(False)
        for face_index in sorted(selected_faces):
            bm.faces[face_index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        del obj[snapshot_key]
        return True, "Face visibility and selection restored."

    selected_indices = [face.index for face in bm.faces if face.select and not face.hide]
    if not selected_indices:
        return False, "Select one or more visible faces before isolating."
    hidden_indices = [face.index for face in bm.faces if face.hide]
    snapshot = visibility_utils.encode_face_visibility_snapshot(
        vertex_count, edge_count, face_count, hidden_indices, selected_indices
    )
    try:
        selected_set = set(selected_indices)
        for face in bm.faces:
            if face.index not in selected_set and not face.hide:
                face.hide_set(True)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        obj[snapshot_key] = snapshot
    except Exception:
        # Best-effort rollback to the exact pre-isolation state.
        for face in bm.faces:
            face.hide_set(False)
        for face_index in hidden_indices:
            bm.faces[face_index].hide_set(True)
        for face in bm.faces:
            if face.select:
                face.select_set(False)
        for face_index in selected_indices:
            bm.faces[face_index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        raise
    return True, (
        f"Isolated {len(selected_indices)} selected face(s). "
        "Click Isolate Selection again to restore the previous visibility."
    )


class QSS_OT_isolate_faces(Operator):
    bl_idname = "qss.isolate_faces"
    bl_label = "Toggle Face Isolation"
    bl_description = "Hide all other faces; click again to restore the previous visibility and selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(
            _qss_is_map_object(context.object)
            and (context.mode == "EDIT_MESH" or _qss_is_texture_paint_context(context))
        )

    def execute(self, context):
        obj = context.object
        was_paint = _qss_is_texture_paint_context(context)
        paint_kind = str(obj.get("qss_active_paint_kind", "texture")) if was_paint else ""
        try:
            if was_paint:
                bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.mode_set(mode="EDIT")
            success, message = _qss_toggle_face_isolation_in_edit(obj)
        except Exception as exc:
            success, message = False, f"Could not toggle face isolation: {exc}"
        finally:
            if was_paint:
                try:
                    if getattr(obj, "mode", "") == "EDIT":
                        bpy.ops.object.mode_set(mode="OBJECT")
                    bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
                    obj["qss_active_paint_kind"] = paint_kind
                except Exception as restore_exc:
                    success, message = False, (
                        f"{message} Texture Paint could not be restored: {restore_exc}. "
                        "Use Tab to return to Edit Mode and re-enter painting."
                    )
        if success:
            _report(self, "INFO", message)
            return {"FINISHED"}
        _report(self, "WARNING" if "Select one or more" in message else "ERROR", message)
        return {"CANCELLED"}


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
            area = context.area if context.area and context.area.type == 'VIEW_3D' else None
            if area is None:
                area = next(
                    (item for item in (context.screen.areas if context.screen else [])
                     if item.type == 'VIEW_3D'),
                    None,
                )
            region = next(
                (item for item in area.regions if item.type == 'WINDOW'),
                None,
            ) if area else None
            if area is None or region is None:
                raise RuntimeError("No usable 3D View window region is available.")
            with context.temp_override(window=context.window, area=area, region=region):
                bpy.ops.mesh.reveal(select=False)
            return {'FINISHED'}
        except Exception as exc:
            _report(self, 'ERROR', f"Could not reveal faces: {exc}")
            return {'CANCELLED'}


class QSS_OT_export_bsp(Operator, ExportHelper):
    bl_idname = "qss.export_bsp"
    bl_label = "Export Modified BSP"
    bl_description = "Write texture and face-material changes back to a BSP29 file"
    filename_ext = ".bsp"
    filter_glob: StringProperty(default="*.bsp", options={'HIDDEN'})
    lightmap_export_mode: EnumProperty(
        name="Lightmap export",
        description="Automatic chooses a suitable format; Both writes Classic and Enhanced variants",
        items=(
            ('AUTO', "Automatic", "Choose format from the active map's lightmap requirements"),
            ('CLASSIC', "Classic BSP29", "Broad engine compatibility"),
            ('ENHANCED', "Enhanced BSPX", "Use DECOUPLED_LM for enhanced engines"),
            ('BOTH', "Both", "Write _c.bsp and _e.bsp variants"),
        ),
        default='AUTO',
    )

    def invoke(self, context, event):
        obj = context.object
        source = obj.get('qss_source_path', '') if obj else ''
        mode = str(_qss_config_settings().get("export_mode", "AUTO")).upper()
        self.lightmap_export_mode = mode if mode in {"AUTO", "CLASSIC", "ENHANCED", "BOTH"} else "AUTO"
        if source:
            root, ext = os.path.splitext(source)
            self.filepath = root + "_surface_studio" + (ext or ".bsp")
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        self.layout.prop(self, "lightmap_export_mode", text="Format")
        self.layout.label(text="Automatic selects Enhanced for upscaled or decoupled lightmaps.", icon="INFO")
        self.layout.label(text="Both writes _c and _e variants.", icon="INFO")

    def execute(self, context):
        obj = context.object
        try:
            mode = self.lightmap_export_mode
            if mode == "AUTO":
                mode = "ENHANCED" if (
                    int(obj.get("qss_lightmap_resolution", 1)) > 1
                    or float(getattr(context.scene, "qss_decoupled_world_units_per_luxel", 16.0)) < 16.0
                    or "DECOUPLED_LM" in str(obj.get("qss_bspx_lump_names", ""))
                ) else "CLASSIC"
            output = bpy.path.abspath(self.filepath)
            if not output:
                raise OSError("Choose an output BSP filename.")
            os.makedirs(os.path.dirname(output) or os.getcwd(), exist_ok=True)
            if mode == "BOTH":
                root, ext = os.path.splitext(output)
                ext = ext or ".bsp"
                classic_path = root + "_c" + ext
                enhanced_path = root + "_e" + ext
                classic_result = _export_object(obj, classic_path, "CLASSIC")
                try:
                    enhanced_result = _export_object(obj, enhanced_path, "ENHANCED")
                except Exception:
                    for partial_path in (classic_result[0], classic_result[5], enhanced_path, os.path.splitext(enhanced_path)[0] + ".lit"):
                        if partial_path and os.path.isfile(partial_path):
                            try:
                                os.remove(partial_path)
                            except OSError:
                                pass
                    raise
                obj["qss_last_export_classic_path"] = classic_result[0]
                obj["qss_last_export_enhanced_path"] = enhanced_result[0]
                prefer_enhanced = bool(_qss_config_settings().get("prefer_enhanced_last_export", True))
                chosen = enhanced_result[0] if prefer_enhanced else classic_result[0]
                results = (classic_result, enhanced_result)
                summary = f"Both variants exported: {os.path.basename(classic_result[0])} and {os.path.basename(enhanced_result[0])}"
            else:
                result = _export_object(obj, output, mode)
                chosen = result[0]
                results = (result,)
                obj["qss_last_export_classic_path"] = result[0] if mode == "CLASSIC" else ""
                obj["qss_last_export_enhanced_path"] = result[0] if mode == "ENHANCED" else ""
                summary = f"Exported {os.path.basename(result[0])} ({mode})"
            obj["qss_last_export_path"] = chosen
            obj["qss_last_export_mode"] = mode
            detail = ""
            for result in results:
                lit_path = result[5]
                if lit_path:
                    detail += f" | {os.path.basename(lit_path)} written"
            _report(self, "INFO", summary + detail)
            return {"FINISHED"}
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
        f'Last attempted face coverage (raw bake): {obj.get("qss_last_bake_attempt_face_coverage", "n/a")}',
        f'Last Cycles bake operator result: {obj.get("qss_last_bake_attempt_operator_result", "n/a")}',
        f'Last Cycles attempt config: engine={obj.get("qss_last_bake_attempt_engine", "n/a")} target={obj.get("qss_last_bake_attempt_target", "n/a")} type={obj.get("qss_last_bake_attempt_type", "n/a")} uv={obj.get("qss_last_bake_attempt_uv", "n/a")}',
        f'Last attempted lamp states: {obj.get("qss_last_bake_attempt_lights", "n/a")}',
        f'Last attempted scene visibility: {obj.get("qss_last_bake_attempt_scene_visibility", "n/a")}',
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
            resolution = _qss_lightmap_pixel_scale(obj, image)
            scale = max(1, int(obj.get('qss_lightmap_scale', 1))) * resolution
            gutter = max(0, int(obj.get('qss_lightmap_gutter', 0))) * resolution
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
                    x0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_x'].data, i, 'qss_lm_atlas_x').value) * resolution + gutter
                    y0 = int(_qss_safe_collection_item(attrs['qss_lm_atlas_y'].data, i, 'qss_lm_atlas_y').value) * resolution + gutter
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
        lines.append('  {} type={} color={} energy={:.6g} W style={} inferred={} value={} delay={} range={} manual_calibration={}'.format(
            light_obj.name, light_obj.data.type, tuple(round(float(v), 4) for v in light_obj.data.color),
            float(light_obj.data.energy), light_obj.get('qss_quake_light_style', 0),
            light_obj.get('qss_quake_style_was_inferred', False), light_obj.get('qss_quake_light_value', ''),
            light_obj.get('qss_quake_light_delay', 0), light_obj.get('qss_quake_range', ''),
            light_obj.get('qss_manual_energy_calibration', 1.0)))
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
        try:
            self.filepath = _qss_map_artifact_path(obj, f'QSS_{stem}_diagnostics.txt', create=False)
        except Exception:
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
            _qss_log('INFO', 'diagnostics', f"Saved report to {path}")
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
            output = _qss_map_artifact_path(context.object, 'QSS_Blender_SelfTest.txt', create=False) if _qss_is_map_object(context.object) else os.path.expanduser('~/Desktop/QSS_Blender_SelfTest.txt')
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



class QSS_OT_settings(Operator):
    bl_idname = "qss.settings"
    bl_label = "Quake Surface Studio Settings"
    bl_description = "Configure import behaviour, export defaults and map workflow"

    quake_root: StringProperty(
        name="Quake installation folder",
        description="Folder containing id1 and your installed mods",
        subtype="DIR_PATH",
    )
    ironwail_executable: StringProperty(
        name="Ironwail executable",
        description="Path to the Ironwail executable used by Open Last Export",
        subtype="FILE_PATH",
    )
    import_behavior: EnumProperty(
        name="Import behaviour",
        items=(("ASK", "Ask", "Ask whether to add or replace when another map is loaded"),
               ("ADD", "Add", "Always add imported maps as separate collections"),
               ("REPLACE", "Replace", "Replace the active QSS map after a successful import")),
        default="ASK",
    )
    export_mode: EnumProperty(
        name="Default export format",
        items=(("AUTO", "Automatic", "Choose Classic or Enhanced from map requirements"),
               ("CLASSIC", "Classic", "Always default to Classic BSP29"),
               ("ENHANCED", "Enhanced", "Always default to Enhanced BSPX"),
               ("BOTH", "Both", "Always default to exporting both variants")),
        default="AUTO",
    )
    prefer_enhanced_last_export: BoolProperty(name="Prefer Enhanced when opening a Both export", default=True)
    rebake_behavior: EnumProperty(
        name="Re-bake an existing lightmap",
        items=(("ASK", "Ask", "Confirm before replacing the generated lightmap"),
               ("OVERWRITE", "Overwrite", "Replace the generated lightmap without another confirmation")),
        default="ASK",
    )
    lighting_mode_storage: EnumProperty(
        name="Lighting mode memory",
        items=(("PER_MAP", "Per map", "Each imported map remembers its own lighting mode"),
               ("GLOBAL", "Global", "Use one lighting mode for every imported map")),
        default="PER_MAP",
    )
    viewport_fov_degrees: FloatProperty(
        name="Viewport FOV",
        description="Horizontal field of view used by QSS 3D viewports and Focus on Face",
        default=90.0, min=30.0, max=120.0, precision=1,
    )
    import_lightmap_resolution: EnumProperty(
        name="Default working lightmap resolution",
        items=(("1", "1× · Original", "Original packed atlas resolution"),
               ("2", "2×", "Twice the pixels per axis"),
               ("4", "4×", "Four times the pixels per axis"),
               ("8", "8×", "Eight times the pixels per axis")),
        default="1",
    )

    def invoke(self, context, event):
        settings = _qss_config_settings()
        self.quake_root = str(settings.get("quake_root", "") or getattr(context.scene, "qss_quake_root", ""))
        self.ironwail_executable = str(settings.get("ironwail_executable", "") or getattr(context.scene, "qss_ironwail_executable", ""))
        self.import_behavior = str(settings.get("import_behavior", "ASK")).upper()
        self.export_mode = str(settings.get("export_mode", "AUTO")).upper()
        self.prefer_enhanced_last_export = bool(settings.get("prefer_enhanced_last_export", True))
        self.rebake_behavior = str(settings.get("rebake_behavior", "ASK")).upper()
        self.lighting_mode_storage = str(settings.get("lighting_mode_storage", "PER_MAP")).upper()
        self.import_lightmap_resolution = str(settings.get("import_lightmap_resolution", "1"))
        self.viewport_fov_degrees = float(settings.get("viewport_fov_degrees", 90.0))
        if self.import_behavior not in {"ASK", "ADD", "REPLACE"}:
            self.import_behavior = "ASK"
        if self.export_mode not in {"AUTO", "CLASSIC", "ENHANCED", "BOTH"}:
            self.export_mode = "AUTO"
        if self.import_lightmap_resolution not in {"1", "2", "4", "8"}:
            self.import_lightmap_resolution = "1"
        if self.rebake_behavior not in {"ASK", "OVERWRITE"}:
            self.rebake_behavior = "ASK"
        if self.lighting_mode_storage not in {"PER_MAP", "GLOBAL"}:
            self.lighting_mode_storage = "PER_MAP"
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Game installation", icon="FILE_FOLDER")
        layout.prop(self, "quake_root")
        layout.prop(self, "ironwail_executable")
        layout.separator()
        layout.label(text="Project workflow defaults", icon="PREFERENCES")
        layout.prop(self, "import_behavior")
        layout.prop(self, "export_mode")
        layout.prop(self, "prefer_enhanced_last_export")
        layout.prop(self, "import_lightmap_resolution")
        layout.prop(self, "viewport_fov_degrees")
        layout.separator()
        layout.label(text="Lighting workflow", icon="LIGHT")
        layout.prop(self, "lighting_mode_storage")
        layout.prop(self, "rebake_behavior")
        layout.label(text="Cycles is the supported bake backend; Eevee uses this same low-priority test path.", icon="INFO")
        layout.label(text="Only QSS map collections are replaced. Other scene content is preserved.", icon="INFO")

    def execute(self, context):
        settings = _qss_load_config()
        previous_lighting_storage = str(settings.get("lighting_mode_storage", "PER_MAP")).upper()
        normalized_root = quake_paths.normalize_quake_root(_qss_abspath(self.quake_root or ""))
        ironwail_path = _qss_abspath(self.ironwail_executable or "")
        settings.update({
            "quake_root": normalized_root,
            "ironwail_executable": ironwail_path,
            "import_behavior": self.import_behavior,
            "export_mode": self.export_mode,
            "prefer_enhanced_last_export": bool(self.prefer_enhanced_last_export),
            "import_lightmap_resolution": self.import_lightmap_resolution,
            "viewport_fov_degrees": float(self.viewport_fov_degrees),
            "rebake_behavior": self.rebake_behavior,
            "lighting_mode_storage": self.lighting_mode_storage,
        })
        if self.lighting_mode_storage == "GLOBAL" and previous_lighting_storage != "GLOBAL":
            active_obj = context.object
            settings["global_lighting_mode"] = (
                active_obj.get("qss_preview_mode", "source") if _qss_is_map_object(active_obj) else "source"
            )
        try:
            context.scene.qss_quake_root = normalized_root
            context.scene.qss_ironwail_executable = ironwail_path
            settings["active_game_dir"] = _qss_abspath(context.scene.qss_game_dir or "")
            settings["active_game_id"] = str(context.scene.qss_game_folder or "")
            quake_paths.save_config(settings, _qss_config_path())
            _qss_apply_viewport_fov(context, self.viewport_fov_degrees)
            context.scene.qss_import_lightmap_resolution = self.import_lightmap_resolution
            self.report({"INFO"}, "Quake Surface Studio settings saved.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not save QSS settings: {exc}")
            return {"CANCELLED"}


class QSS_OT_open_config_text(Operator):
    bl_idname = "qss.open_config_text"
    bl_label = "Open Config File in Text Editor"
    bl_description = "Open QSS config.json in a separate Blender window for direct editing"

    def execute(self, context):
        path = _qss_config_path()
        if not os.path.isfile(path):
            quake_paths.save_config(_qss_load_config(), path)
        try:
            bpy.ops.wm.window_new()
            windows = list(context.window_manager.windows)
            target_window = windows[-1] if windows else context.window
            target_area = next(
                (area for area in target_window.screen.areas if area.type == "VIEW_3D"),
                max(target_window.screen.areas, key=lambda area: area.width * area.height),
            )
            text = next(
                (item for item in bpy.data.texts if bpy.path.abspath(item.filepath) == path),
                None,
            )
            if text is None:
                text = bpy.data.texts.load(path, internal=False)
            target_area.type = "TEXT_EDITOR"
            target_area.spaces.active.text = text
            self.report({"INFO"}, "QSS config.json opened in a separate Blender window.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not open config.json in a separate editor window: {exc}")
            return {"CANCELLED"}


class QSS_OT_set_lighting_mode(Operator):
    bl_idname = "qss.set_lighting_mode"
    bl_label = "Set Lighting Preview"
    bl_options = {"INTERNAL"}
    mode: EnumProperty(
        name="Lighting mode",
        items=(("source", "Original", "Display imported BSP lightmaps"),
               ("realtime", "Eevee", "Preview scene lights in Material Preview"),
               ("cycles", "Cycles", "Preview scene lights in Cycles"),
               ("baked", "Baked", "Display the generated lightmap")),
    )

    @classmethod
    def poll(cls, context):
        return bool(
            _qss_is_map_object(context.object)
            and context.mode in {"OBJECT", "EDIT_MESH"}
        )

    def execute(self, context):
        obj = context.object
        if self.mode == "baked" and not _qss_has_baked_lightmap(obj):
            self.report({"WARNING"}, "Bake a lightmap for this map before selecting Baked.")
            return {"CANCELLED"}
        try:
            _set_lighting_preview(context, obj, self.mode)
            settings = _qss_load_config()
            if str(settings.get("lighting_mode_storage", "PER_MAP")).upper() == "GLOBAL":
                settings["global_lighting_mode"] = self.mode
                quake_paths.save_config(settings, _qss_config_path())
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not change lighting mode: {exc}")
            return {"CANCELLED"}


class QSS_OT_toggle_textures(Operator):
    bl_idname = "qss.toggle_textures"
    bl_label = "Toggle Base Textures"
    bl_description = "Show base textures or pure BSP lightmaps"

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object) and context.mode in {"OBJECT", "EDIT_MESH"}

    def execute(self, context):
        obj = context.object
        enabled = not bool(obj.get("qss_base_textures_enabled", True))
        obj["qss_base_textures_enabled"] = enabled
        changed = _qss_apply_base_texture_visibility(obj)
        if not changed:
            obj["qss_base_textures_enabled"] = not enabled
            self.report({"WARNING"}, "No QSS diffuse/lightmap material nodes were found to update.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Diffuse textures {'enabled' if enabled else 'hidden'}; the active lightmap remains visible.")
        return {"FINISHED"}


class QSS_OT_toggle_source_lightmaps(Operator):
    bl_idname = "qss.toggle_source_lightmaps"
    bl_label = "Toggle Source Lightmaps"
    bl_description = "Show or hide the current unpainted Original/Baked lightmap contribution"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(_qss_is_map_object(obj) and context.mode in {"OBJECT", "EDIT_MESH"}
                    and obj.get("qss_preview_mode", "source") in {"source", "baked"})

    def execute(self, context):
        obj = context.object
        enabled = not bool(obj.get("qss_source_lightmaps_enabled", True))
        obj["qss_source_lightmaps_enabled"] = enabled
        changed = _qss_apply_source_lightmap_visibility(obj)
        if not changed:
            obj["qss_source_lightmaps_enabled"] = not enabled
            self.report({"WARNING"}, "No QSS lightmap material nodes were found.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Source lightmaps {'enabled' if enabled else 'hidden'}.")
        return {"FINISHED"}


def _qss_rebuild_original_quake_texture_uvs(obj, original_uv, active_uv, original_material, painted_marker):
    """Reconstruct source texinfo UVs from the BSP for detached faces."""
    source_path = bpy.path.abspath(str(obj.get("qss_source_path", "") or ""))
    if not source_path or not os.path.isfile(source_path):
        return 0
    try:
        parsed = bsp.BSP29.from_file(source_path)
        vertices = parsed.vertices()
        edges = parsed.edges()
        surfedges = parsed.surfedges()
        faces = parsed.faces()
        texinfos = parsed.texinfos()
        face_ids = obj.data.attributes.get("qss_bsp_face_id")
        if face_ids is None or len(face_ids.data) != len(obj.data.polygons):
            return 0
        changed = 0
        for poly in obj.data.polygons:
            if poly.index >= len(painted_marker.data) or not painted_marker.data[poly.index].value:
                continue
            face_id = int(face_ids.data[poly.index].value)
            if face_id < 0 or face_id >= len(faces):
                continue
            face_record = faces[face_id]
            texinfo_id = int(face_record[4])
            if texinfo_id < 0 or texinfo_id >= len(texinfos):
                continue
            original_index = int(original_material.data[poly.index].value)
            if original_index < 0 or original_index >= len(obj.data.materials):
                continue
            source_material = obj.data.materials[original_index]
            source_image = _find_image(source_material, "base_texture")
            if source_image is None:
                continue
            width = max(1, int(source_image.size[0]))
            height = max(1, int(source_image.size[1]))
            vertex_ids = parsed.face_vertex_indices(face_record, edges, surfedges)
            loop_indices = tuple(poly.loop_indices)
            if len(vertex_ids) != len(loop_indices):
                continue
            texinfo = texinfos[texinfo_id]
            svec, tvec = texinfo[0:4], texinfo[4:8]
            for loop_index, vertex_id in zip(loop_indices, vertex_ids):
                if vertex_id < 0 or vertex_id >= len(vertices):
                    continue
                point = vertices[vertex_id]
                s = point[0] * svec[0] + point[1] * svec[1] + point[2] * svec[2] + svec[3]
                t = point[0] * tvec[0] + point[1] * tvec[1] + point[2] * tvec[2] + tvec[3]
                uv = (s / width, 1.0 - t / height)
                original_uv.data[loop_index].uv = uv
                active_uv.data[loop_index].uv = uv
            changed += 1
        return changed
    except Exception as exc:
        print(f"QSS: could not reconstruct original Quake texture UVs: {exc}")
        return 0


def _qss_bind_original_texture_uv(material):
    """Ensure a material samples its base texture through Quake_Texture_UV."""
    if material is None or not material.use_nodes or material.node_tree is None:
        return
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_node = _find_image_node(material, "base_texture")
    if image_node is None:
        return
    uv_node = next(
        (node for node in nodes if node.type == "UVMAP" and node.get("qss_role") == "texture_uv"),
        None,
    )
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node["qss_role"] = "texture_uv"
    uv_node.uv_map = "Quake_Texture_UV"
    for link in list(links):
        if link.to_socket == image_node.inputs["Vector"]:
            links.remove(link)
    links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])


class QSS_OT_toggle_painted_textures(Operator):
    bl_idname = "qss.toggle_painted_textures"
    bl_label = "Toggle Painted Textures"
    bl_description = "Switch detached face textures between original and painted material versions"

    @classmethod
    def poll(cls, context):
        return (
            _qss_is_map_object(context.object)
            and context.mode in {"OBJECT", "EDIT_MESH"}
            and _qss_has_painted_texture_faces(context.object)
        )

    def execute(self, context):
        obj = context.object
        was_edit_mode = context.mode == "EDIT_MESH"
        try:
            if was_edit_mode:
                bpy.ops.object.mode_set(mode="OBJECT")
            mesh = obj.data
            original = mesh.attributes.get("qss_original_material_index")
            painted = mesh.attributes.get("qss_painted_material_index")
            marker = mesh.attributes.get("qss_painted_face")
            if not all((original, painted, marker)):
                raise bsp.BSPError("This map has no detached painted textures.")
            enabled = not bool(obj.get("qss_painted_textures_enabled", True))
            original_uv = mesh.uv_layers.get("Quake_Texture_UV_Original")
            painted_uv = mesh.uv_layers.get("Quake_Texture_UV_Painted")
            active_uv = mesh.uv_layers.get("Quake_Texture_UV")
            if active_uv is None or original_uv is None or painted_uv is None:
                raise bsp.BSPError(
                    "The original/painted UV backups are missing. Re-import this BSP before toggling painted textures."
                )
            if not enabled:
                _qss_rebuild_original_quake_texture_uvs(
                    obj, original_uv, active_uv, original, marker
                )
            for poly in mesh.polygons:
                index = poly.index
                if marker.data[index].value:
                    target = int(painted.data[index].value) if enabled else int(original.data[index].value)
                    if 0 <= target < len(mesh.materials):
                        poly.material_index = target
                    source_uv = painted_uv if enabled else active_uv
                    for loop_index in poly.loop_indices:
                        active_uv.data[loop_index].uv = source_uv.data[loop_index].uv
            obj["qss_painted_textures_enabled"] = enabled
            active_uv.active_render = True
            mesh.uv_layers.active = active_uv
            for material in mesh.materials:
                _qss_bind_original_texture_uv(material)
            mesh.update()
        except Exception as exc:
            self.report({"ERROR"}, f"Could not switch painted textures: {exc}")
            return {"CANCELLED"}
        finally:
            if was_edit_mode and getattr(obj, "mode", "") == "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                except Exception as exc:
                    self.report({"WARNING"}, f"Painted textures changed, but Edit Mode could not be restored: {exc}")
        self.report({"INFO"}, f"Painted textures {'enabled' if enabled else 'disabled'}.")
        return {"FINISHED"}


class QSS_OT_toggle_painted_lightmaps(Operator):
    bl_idname = "qss.toggle_painted_lightmaps"
    bl_label = "Toggle Painted Lightmaps"
    bl_description = "Switch between the active lightmap source and its painted override"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(_qss_is_map_object(obj) and context.mode in {"OBJECT", "EDIT_MESH"}
                    and obj.get("qss_preview_mode", "source") in {"source", "baked"}
                    and (obj.get("qss_preview_mode", "source") != "baked" or _qss_has_baked_lightmap(obj)))

    def execute(self, context):
        obj = context.object
        mode = obj.get("qss_preview_mode", "source")
        key = "qss_painted_original_lightmap" if mode == "source" else "qss_painted_baked_lightmap"
        if not obj.get(key, ""):
            self.report({"WARNING"}, "Paint a lightmap first; no painted override exists for this source.")
            return {"CANCELLED"}
        enabled = not bool(obj.get("qss_painted_lightmaps_enabled", True))
        obj["qss_painted_lightmaps_enabled"] = enabled
        try:
            _set_lighting_preview(context, obj, mode)
        except Exception as exc:
            obj["qss_painted_lightmaps_enabled"] = not enabled
            self.report({"ERROR"}, f"Could not switch painted lightmaps: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Painted lightmaps {'enabled' if enabled else 'disabled'}.")
        return {"FINISHED"}


def _qss_rebuild_map_lightmap_resolution(obj, resolution):
    source_path = bpy.path.abspath(obj.get("qss_source_path", ""))
    if not source_path or not os.path.isfile(source_path):
        raise bsp.BSPError("The source BSP is unavailable; cannot rebuild its lightmap atlas.")
    parsed = bsp.BSP29.from_file(source_path)
    mesh = obj.data
    face_ids_attr = mesh.attributes.get("qss_bsp_face_id")
    texinfo_attr = mesh.attributes.get("qss_bsp_texinfo_id")
    if not face_ids_attr or not texinfo_attr or len(face_ids_attr.data) != len(mesh.polygons) or len(texinfo_attr.data) != len(mesh.polygons):
        raise bsp.BSPError("BSP face metadata is missing or stale; re-import this map.")
    unit_scale = max(1e-8, float(obj.get("qss_unit_scale", DEFAULT_QUAKE_UNIT_SCALE)))
    flip_z = bool(obj.get("qss_flip_z", False))
    face_ids = [int(item.value) for item in face_ids_attr.data]
    texinfo_ids = [int(item.value) for item in texinfo_attr.data]
    positions_by_face = []
    for poly in mesh.polygons:
        positions = []
        for vertex_index in poly.vertices:
            co = mesh.vertices[vertex_index].co
            z = -float(co.z) if flip_z else float(co.z)
            positions.append((float(co.x) / unit_scale, float(co.y) / unit_scale, z / unit_scale))
        positions_by_face.append(positions)
    source_lit_path = os.path.splitext(source_path)[0] + ".lit"
    source_lit_rgb, _ = bsp.resolve_rgb_lighting(parsed.bspx_lumps, parsed.lumps[bsp.LUMP_LIGHTING], source_lit_path)
    atlas_lighting = parsed.lumps[bsp.LUMP_LIGHTING]
    if not atlas_lighting and source_lit_rgb is not None:
        atlas_lighting = bsp.rgb_lighting_to_luminance(source_lit_rgb)

    old_names = (
        obj.get("qss_lightmap_image_name", ""),
        obj.get("qss_original_lightmap_backup", ""),
        obj.get("qss_painted_original_lightmap", ""),
        obj.get("qss_painted_baked_lightmap", ""),
        obj.get("qss_last_bake_backup", ""),
    )
    lm_uv = mesh.uv_layers.get("Quake_Lightmap_UV")
    if lm_uv is not None:
        mesh.uv_layers.remove(lm_uv)
    for name in ("qss_lm_has_data", "qss_lm_atlas_x", "qss_lm_atlas_y", "qss_lm_sample_w", "qss_lm_sample_h"):
        attr = mesh.attributes.get(name)
        if attr is not None:
            mesh.attributes.remove(attr)
    _build_lightmap_atlas(obj, mesh, parsed, face_ids, texinfo_ids, positions_by_face,
                          source_lit_rgb, lighting_data=atlas_lighting, resolution=int(resolution))
    obj["qss_painted_original_lightmap"] = ""
    obj["qss_painted_baked_lightmap"] = ""
    obj["qss_last_bake_backup"] = ""
    obj["qss_baked_lightmap_image_name"] = ""
    obj["qss_lightmap_gradient_baked"] = False
    obj["qss_lightmap_source"] = "source_bsp"
    for key in (
        "qss_last_bake_luxel_mean", "qss_last_bake_luxel_max",
        "qss_last_bake_energy_scale", "qss_last_bake_output_scale",
        "qss_last_bake_raw_mean", "qss_last_bake_source_mean",
        "qss_last_bake_calibration", "qss_last_bake_bounces",
    ):
        if key in obj:
            del obj[key]
    for name in old_names:
        image = bpy.data.images.get(name) if name else None
        if image is not None and image.users == 0:
            try:
                bpy.data.images.remove(image, do_unlink=True)
            except Exception:
                pass


class QSS_OT_change_lightmap_resolution(Operator):
    bl_idname = "qss.change_lightmap_resolution"
    bl_label = "Change Lightmap Resolution"
    bl_description = "Rebuild the active map's working lightmap atlas at a different resolution"
    resolution: EnumProperty(
        name="Working resolution",
        items=(("1", "1× · Original", "Original packed atlas resolution"),
               ("2", "2×", "Twice the pixels per axis"),
               ("4", "4×", "Four times the pixels per axis"),
               ("8", "8×", "Eight times the pixels per axis")),
        default="1",
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        return _qss_is_map_object(obj) and context.mode == "OBJECT" and bool(obj.get("qss_lightmap_image_name"))

    def invoke(self, context, event):
        self.resolution = str(context.object.get("qss_lightmap_resolution", 1))
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "resolution")
        layout.label(text="Rebuilds the atlas from the original BSP source.", icon="INFO")
        layout.label(text="Existing generated and painted lightmaps for this map are discarded.", icon="ERROR")
        layout.label(text="Painted textures and geometry edits are preserved.", icon="INFO")

    def execute(self, context):
        obj = context.object
        if str(obj.get("qss_lightmap_resolution", 1)) == self.resolution:
            self.report({"INFO"}, "The active map already uses this lightmap resolution.")
            return {"CANCELLED"}
        try:
            _qss_rebuild_map_lightmap_resolution(obj, int(self.resolution))
            _set_lighting_preview(context, obj, "source")
            self.report({"INFO"}, f"Lightmap atlas rebuilt at {self.resolution}×.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not rebuild lightmap atlas: {exc}")
            return {"CANCELLED"}


class QSS_OT_open_last_export(Operator):
    bl_idname = "qss.open_last_export"
    bl_label = "Open Last Export in Ironwail"
    bl_description = "Launch Ironwail with the last successful BSP export for the active map"

    @classmethod
    def poll(cls, context):
        obj = context.object
        executable = _qss_abspath(getattr(context.scene, "qss_ironwail_executable", "") or "")
        quake_root = _qss_abspath(getattr(context.scene, "qss_quake_root", "") or "")
        path = _qss_last_export_path(obj)
        game_dir = _qss_abspath(obj.get("qss_game_dir", "") or getattr(context.scene, "qss_game_dir", "") or "")
        inside_game = False
        if path and game_dir and os.path.isdir(game_dir):
            try:
                relative = os.path.relpath(os.path.abspath(path), game_dir)
                inside_game = relative != os.pardir and not relative.startswith(os.pardir + os.sep)
            except ValueError:
                inside_game = False
        return bool(executable and os.path.isfile(executable) and quake_root and os.path.isdir(quake_root)
                    and path and os.path.isfile(path) and inside_game)

    def execute(self, context):
        obj = context.object
        path = _qss_last_export_path(obj)
        if not path:
            self.report({"ERROR"}, "No existing export is available for this map.")
            return {"CANCELLED"}
        try:
            game_dir = _qss_abspath(obj.get("qss_game_dir", "") or context.scene.qss_game_dir)
            relative = os.path.relpath(os.path.abspath(path), game_dir)
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                raise RuntimeError("The last export is outside the active Game / Mod folder. Export inside the game directory to launch it in Ironwail.")
            command = external_tools.build_ironwail_command(
                _qss_abspath(context.scene.qss_ironwail_executable),
                _qss_abspath(context.scene.qss_quake_root), game_dir,
                map_path=relative.replace(os.sep, "/"), developer_mode=True)
            log_root = bpy.utils.user_resource("DATAFILES", path=os.path.join("qss", "ironwail_logs"), create=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join(log_root, f"Ironwail_{stamp}")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "process_output.log")
            pid = external_tools.launch_process(command, cwd=log_dir, log_path=log_path)
            self.report({"INFO"}, f"Ironwail launched with {os.path.basename(path)} (PID {pid}).")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not open last export: {exc}")
            return {"CANCELLED"}


class QSS_OT_test_in_ironwail(Operator):
    bl_idname = "qss.test_in_ironwail"
    bl_label = "Test in Ironwail"
    bl_description = "Export a temporary copy of the current map and launch it in Ironwail without changing the saved export"

    @classmethod
    def poll(cls, context):
        obj = context.object
        executable = _qss_abspath(getattr(context.scene, "qss_ironwail_executable", "") or "")
        quake_root = _qss_abspath(getattr(context.scene, "qss_quake_root", "") or "")
        game_dir = _qss_abspath(
            (obj.get("qss_game_dir", "") if obj else "")
            or getattr(context.scene, "qss_game_dir", "") or ""
        )
        return bool(
            _qss_is_map_object(obj)
            and context.mode in {"OBJECT", "EDIT_MESH"}
            and executable and os.path.isfile(executable)
            and quake_root and os.path.isdir(quake_root)
            and game_dir and os.path.isdir(game_dir)
        )

    def execute(self, context):
        obj = context.object
        scene = context.scene
        executable = _qss_abspath(scene.qss_ironwail_executable)
        quake_root = _qss_abspath(scene.qss_quake_root)
        game_dir = _qss_abspath(obj.get("qss_game_dir", "") or scene.qss_game_dir)
        original_mode = context.mode
        output_path = ""
        lit_path = ""
        process = None
        try:
            if original_mode == "EDIT_MESH":
                bpy.ops.object.mode_set(mode="OBJECT")

            mode = str(_qss_config_settings().get("export_mode", "AUTO")).upper()
            if mode not in {"AUTO", "CLASSIC", "ENHANCED", "BOTH"}:
                mode = "AUTO"
            if mode == "AUTO":
                mode = "ENHANCED" if (
                    int(obj.get("qss_lightmap_resolution", 1)) > 1
                    or float(getattr(scene, "qss_decoupled_world_units_per_luxel", 16.0)) < 16.0
                    or "DECOUPLED_LM" in str(obj.get("qss_bspx_lump_names", ""))
                ) else "CLASSIC"
            elif mode == "BOTH":
                mode = "ENHANCED" if bool(
                    _qss_config_settings().get("prefer_enhanced_last_export", True)
                ) else "CLASSIC"

            test_dir = os.path.join(game_dir, "maps", "qss_preview")
            os.makedirs(test_dir, exist_ok=True)
            stem = f"qss_test_{time.time_ns()}"
            output_path = os.path.join(test_dir, stem + ".bsp")
            export_result = _export_object(obj, output_path, mode)
            output_path = export_result[0]
            lit_path = export_result[5]

            relative = os.path.relpath(output_path, game_dir).replace(os.sep, "/")
            command = external_tools.build_ironwail_command(
                executable, quake_root, game_dir, map_path=relative, developer_mode=True
            )
            log_root = bpy.utils.user_resource(
                "DATAFILES", path=os.path.join("qss", "ironwail_logs"), create=True
            )
            log_dir = os.path.join(log_root, f"Ironwail_Test_{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "process_output.log")
            process = external_tools.launch_process_handle(
                command, cwd=log_dir, log_path=log_path
            )

            cleanup_paths = tuple(path for path in (output_path, lit_path) if path)
            cleanup_dir = test_dir

            def cleanup_test_export():
                if process.poll() is None:
                    return 3.0
                for path in cleanup_paths:
                    try:
                        if os.path.isfile(path):
                            os.remove(path)
                    except OSError:
                        pass
                try:
                    os.rmdir(cleanup_dir)
                except OSError:
                    pass
                return None

            bpy.app.timers.register(cleanup_test_export, first_interval=3.0)
            self.report(
                {"INFO"},
                f"Temporary {mode} test map launched in Ironwail (PID {process.pid}); "
                "the BSP and optional .lit are removed when Ironwail exits.",
            )
            return {"FINISHED"}
        except Exception as exc:
            for path in (output_path, lit_path):
                try:
                    if path and os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
            self.report({"ERROR"}, f"Could not test map in Ironwail: {exc}")
            return {"CANCELLED"}
        finally:
            if original_mode == "EDIT_MESH" and getattr(obj, "mode", "") == "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                except Exception as exc:
                    self.report({"WARNING"}, f"Map was exported, but Edit Mode could not be restored: {exc}")




class QSS_OT_load_quake_palette(Operator):
    bl_idname = "qss.load_quake_palette"
    bl_label = "Load Quake Palette"
    bl_description = "Load the active map's 256 RGB colors into Blender's Image Paint palette"

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def execute(self, context):
        try:
            palette = _qss_assign_quake_palette(context, context.object)
            context.scene.qss_paint_color_picker = "QUAKE"
            self.report(
                {"INFO"},
                f"Loaded {len(palette.colors)} Quake palette entries from "
                f"{palette.get('qss_palette_origin', 'the active game')}.",
            )
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not load Quake palette: {exc}")
            return {"CANCELLED"}


class QSS_OT_convert_quake_palette(Operator):
    bl_idname = "qss.convert_quake_palette"
    bl_label = "Optional: Convert Image to Quake Palette"
    bl_description = "Run the material-zone Quake converter inside Blender's own Python process"

    output_filepath: StringProperty(
        name="Converted PNG",
        description="Destination for the indexed Quake palette PNG",
        subtype="FILE_PATH",
    )
    source_image_name: StringProperty(
        name="Source Image",
        description="Blender image datablock to convert",
    )

    def invoke(self, context, event):
        image = _qss_converter_source_image(context)
        if image is None:
            self.report(
                {"WARNING"},
                "Choose an image in the Image Editor, enter Texture Paint, or render the scene first.",
            )
            return {"CANCELLED"}
        self.source_image_name = image.name
        stem = bpy.path.clean_name(
            "render" if image.name == "Render Result" else image.name
        ) or "texture"
        try:
            self.output_filepath = _qss_map_artifact_path(context.object, stem + "_quake.png", create=False)
        except Exception:
            self.output_filepath = bpy.path.abspath(f"//{stem}_quake.png")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        self.layout.label(text=f"Source: {self.source_image_name or '—'}", icon="IMAGE")
        self.layout.label(
            text="Runs inside Blender. No external Python installation or third-party modules are needed.",
            icon="INFO",
        )

    def execute(self, context):
        image = bpy.data.images.get(self.source_image_name)
        if image is None:
            self.report({"ERROR"}, "The source image is no longer available.")
            return {"CANCELLED"}
        obj = context.object
        if not _qss_is_map_object(obj):
            self.report({"ERROR"}, "Select an imported QSS map so its Quake palette is available.")
            return {"CANCELLED"}

        output_path = _qss_abspath(self.output_filepath or "")
        if not output_path:
            self.report({"ERROR"}, "Choose an output PNG path.")
            return {"CANCELLED"}
        if not output_path.lower().endswith(".png"):
            output_path += ".png"
        source_path = _qss_abspath(
            str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "") or "")
        )
        if source_path and os.path.isfile(source_path):
            try:
                if os.path.samefile(source_path, output_path):
                    self.report({"ERROR"}, "The converted PNG must not overwrite the source image.")
                    return {"CANCELLED"}
            except OSError:
                pass

        render_copy = None
        render_temp_dir = ""
        mask_image = None
        try:
            os.makedirs(os.path.dirname(output_path) or os.getcwd(), exist_ok=True)
            palette_bytes, palette_origin = bsp.find_quake_palette(
                str(obj.get("qss_game_dir", "") or ""),
                str(obj.get("qss_palette_file", "") or ""),
            )
            if palette_bytes is None:
                raise bsp.BSPError(
                    "Could not find the active map's Quake palette. Check gfx/palette.lmp "
                    "or re-import with an explicit palette file."
                )

            source_image = image
            if image.name == "Render Result":
                render_temp_dir = tempfile.mkdtemp(prefix="qss_render_palette_")
                render_path = os.path.join(render_temp_dir, "render_source.png")
                image.save_render(render_path, scene=context.scene)
                render_copy = bpy.data.images.load(render_path, check_existing=False)
                source_image = render_copy

            width, height, rgba = _qss_image_pixels_to_rgba8(source_image)
            fullbright_mask, mask_image = _qss_read_fullbright_mask(
                source_path, width, height
            )
            settings_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "quake_texture_converter.ini",
            )
            conversion_settings = palette_utils.load_settings(settings_path)
            indices, stats = palette_utils.convert_rgba8(
                width, height, rgba, palette_bytes,
                settings=conversion_settings,
                fullbright_mask=fullbright_mask,
            )
            os.makedirs(os.path.dirname(output_path) or os.getcwd(), exist_ok=True)
            palette_utils.save_indexed_png(
                output_path, width, height, indices, palette_bytes
            )
            if not os.path.isfile(output_path):
                raise bsp.BSPError("The indexed Quake PNG was not written.")

            converted = bpy.data.images.load(output_path, check_existing=False)
            converted.name = bpy.path.clean_name(
                os.path.splitext(os.path.basename(output_path))[0] + "_QSS_Quake"
            )
            try:
                converted.colorspace_settings.name = "sRGB"
            except Exception:
                pass
            try:
                converted.pack()
            except RuntimeError:
                pass
            converted["qss_quake_palette_converted"] = True
            converted["qss_quake_palette_origin"] = str(palette_origin)
            converted["qss_converter_ramp_candidates_per_zone"] = int(
                conversion_settings["ramp_candidates_per_zone"]
            )
            converted["qss_converter_regions"] = int(stats["regions"])
            converted["qss_converter_colors_used"] = int(stats["colors_used"])
            converted["qss_converter_transparent_pixels"] = int(stats["transparent_pixels"])
            converted["qss_converter_fullbright_pixels"] = int(stats["fullbright_pixels"])
            self.report(
                {"INFO"},
                f"Converted {width}×{height} pixels into {stats['colors_used']} Quake colors "
                f"across {stats['regions']} material zones. New image: {converted.name}.",
            )
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Quake palette conversion failed: {exc}")
            return {"CANCELLED"}
        finally:
            if mask_image is not None:
                try:
                    bpy.data.images.remove(mask_image, do_unlink=True)
                except Exception:
                    pass
            if render_copy is not None:
                try:
                    bpy.data.images.remove(render_copy, do_unlink=True)
                except Exception:
                    pass
            if render_temp_dir:
                try:
                    import shutil
                    shutil.rmtree(render_temp_dir, ignore_errors=True)
                except Exception:
                    pass


class QSS_OT_viewport_material_preview(Operator):
    bl_idname = "qss.viewport_material_preview"
    bl_label = "Use Material Preview"
    bl_description = "Show QSS materials and lightmaps in the active 3D View"

    @classmethod
    def poll(cls, context):
        return bool(context.area and context.area.type == "VIEW_3D")

    def execute(self, context):
        try:
            context.area.spaces.active.shading.type = "MATERIAL"
            context.area.tag_redraw()
            self.report({"INFO"}, "Viewport Material Preview enabled.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not enable Material Preview: {exc}")
            return {"CANCELLED"}


class QSS_OT_open_quake_palette(Operator):
    bl_idname = "qss.open_quake_palette"
    bl_label = "Choose Quake Palette Color"
    bl_description = "Open the active map's 256-color palette for the current paint brush"

    def invoke(self, context, event):
        try:
            _qss_assign_quake_palette(context, context.object)
            context.scene.qss_paint_color_picker = "QUAKE"
            # invoke_popup anchors the palette to the current mouse position.
            # This is used by the Paint-mode right-click context menu.
            return context.window_manager.invoke_popup(self, width=380)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not open the Quake palette: {exc}")
            return {"CANCELLED"}

    def draw(self, context):
        image_paint = context.scene.tool_settings.image_paint
        layout = self.layout
        layout.template_ID(image_paint, "palette", new="palette.new")
        if image_paint.palette is not None:
            layout.template_palette(image_paint, "palette")
            layout.label(
                text="Select a swatch to set the brush color. "
                     "224–254 are fullbright; 255 is transparent in Quake textures."
            )


_qss_context_menu_types = []


def _qss_draw_quake_palette_context_menu(self, context):
    if not _qss_is_map_object(getattr(context, "object", None)):
        return
    if not _qss_is_texture_paint_context(context):
        return
    self.layout.separator()
    self.layout.operator(
        QSS_OT_open_quake_palette.bl_idname,
        text="Quake Palette Colors…",
        icon="COLOR",
    )


def _qss_remove_context_menus():
    global _qss_context_menu_types
    for menu_type in tuple(_qss_context_menu_types):
        try:
            menu_type.remove(_qss_draw_quake_palette_context_menu)
        except Exception:
            pass
    _qss_context_menu_types.clear()


def _qss_register_context_menus():
    _qss_remove_context_menus()
    for name in ("WM_MT_button_context", "VIEW3D_MT_brush_context_menu"):
        menu_type = getattr(bpy.types, name, None)
        if menu_type is None:
            continue
        try:
            menu_type.append(_qss_draw_quake_palette_context_menu)
            _qss_context_menu_types.append(menu_type)
        except Exception as exc:
            print(f"QSS: could not add Quake palette to {name}: {exc}")


class QSS_OT_close_active_map(Operator):
    bl_idname = "qss.close_active_map"
    bl_label = "Close Active Map"
    bl_description = "Remove the selected QSS map collection and all of its imported map objects"

    collection_name: StringProperty(default="", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return bool(_qss_scene_map_collections(getattr(context, "scene", None)))

    def invoke(self, context, event):
        scene = context.scene
        name = str(scene.qss_active_map_collection or "")
        if not name or name == "__QSS_NO_MAP__":
            obj = context.object
            name = str(obj.get("qss_map_collection", "") if _qss_is_map_object(obj) else "")
        collection = bpy.data.collections.get(name) if name else None
        if collection is None or not bool(collection.get("qss_map_collection", False)):
            self.report({"WARNING"}, "Choose a loaded QSS map before closing it.")
            return {"CANCELLED"}
        self.collection_name = name
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        collection = bpy.data.collections.get(self.collection_name)
        source = str(collection.get("qss_source_path", "") if collection else "")
        layout = self.layout
        layout.label(text=f"Close '{os.path.basename(source) if source else self.collection_name}'?")
        layout.label(text="Imported objects, paint images and unsaved Blender edits in this map will be removed.", icon="ERROR")
        layout.label(text="The original BSP file on disk is not changed.")

    def execute(self, context):
        scene = context.scene
        collection = bpy.data.collections.get(self.collection_name)
        if collection is None or not bool(collection.get("qss_map_collection", False)):
            self.report({"WARNING"}, "The selected QSS map collection no longer exists.")
            return {"CANCELLED"}
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            closing_objects = _qss_collection_objects(collection)
            current_active_name = str(getattr(scene, "qss_active_map_collection", "") or "")
            remaining = [
                item for item in _qss_scene_map_collections(scene)
                if item.name != self.collection_name
            ]
            active = context.view_layer.objects.active
            if active in closing_objects and _qss_is_map_object(active):
                if active.get("qss_preview_mode", "source") in {"realtime", "cycles"}:
                    try:
                        _set_lighting_preview(context, active, "source")
                    except Exception:
                        pass

            if remaining:
                next_active = next(
                    (item for item in remaining if item.name == current_active_name),
                    remaining[0],
                )
                if current_active_name == self.collection_name:
                    _qss_activate_map_collection(scene, next_active.name, context)
            else:
                # When the final QSS map closes, restore objects that were hidden
                # by QSS map isolation, including non-QSS scene content.
                for item in list(scene.objects):
                    try:
                        if "qss_isolation_original_hide" in item:
                            item.hide_set(bool(item.get("qss_isolation_original_hide", False)))
                            del item["qss_isolation_original_hide"]
                        if "qss_isolation_original_hide_render" in item:
                            item.hide_render = bool(item.get("qss_isolation_original_hide_render", False))
                            del item["qss_isolation_original_hide_render"]
                        item.select_set(False)
                    except (AttributeError, RuntimeError, ReferenceError):
                        pass
                try:
                    context.view_layer.objects.active = None
                except Exception:
                    pass

            if not _qss_remove_map_collection(scene, self.collection_name):
                raise bsp.BSPError("QSS could not remove the selected map collection.")
            if not remaining:
                global _qss_map_switch_depth
                _qss_map_switch_depth = True
                try:
                    scene.qss_active_map_collection = "__QSS_NO_MAP__"
                finally:
                    _qss_map_switch_depth = False
            self.report(
                {"INFO"},
                f"Closed map '{self.collection_name}'. "
                + (f"Active map is now '{remaining[0].name}'." if remaining else "The scene's non-QSS content was restored."),
            )
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not close QSS map: {exc}")
            return {"CANCELLED"}


class QSS_PT_main(Panel):
    """Root container for the Slipgate sidebar workflow panels."""
    bl_label = "SLIPGATE"
    bl_idname = "QSS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slipgate"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        # Keep the root panel compact: version, settings and direct config edit.
        # These controls existed in the original v0.18.0 sidebar header.
        header = layout.row(align=True)
        header.label(
            text=f"v{'.'.join(str(part) for part in ADDON_VERSION)}",
            icon="INFO",
        )
        header.operator(
            QSS_OT_settings.bl_idname,
            text="",
            icon="PREFERENCES",
        )
        header.operator(
            QSS_OT_open_config_text.bl_idname,
            text="",
            icon="TEXT",
        )
        layout.label(text="Quake BSP editing and export", icon="WORLD")


class QSS_PT_quick_actions(Panel):
    bl_label = "QUICK ACTIONS"
    bl_idname = "QSS_PT_quick_actions"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slipgate"
    bl_parent_id = "QSS_PT_main"
    bl_order = 20

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw(self, context):
        obj = context.object
        layout = self.layout
        row = layout.row(align=True)
        row.operator(QSS_OT_fps_walk.bl_idname, text="WASD", icon="CAMERA_DATA")
        row.operator(QSS_OT_player_start.bl_idname, text="Start", icon="EMPTY_AXIS")
        row.operator(QSS_OT_isolate_faces.bl_idname, text="Isolate", icon="HIDE_OFF")
        row.operator(QSS_OT_frame_selection.bl_idname, text="Focus", icon="VIEWZOOM")


class QSS_PT_project(Panel):
    bl_label = "MAIN"
    bl_idname = "QSS_PT_project"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slipgate"
    bl_parent_id = "QSS_PT_main"
    bl_order = 30

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.object
        game_selector = layout.row()
        game_selector.enabled = bool(scene.qss_quake_root and os.path.isdir(_qss_abspath(scene.qss_quake_root)))
        game_selector.prop(scene, "qss_game_folder", text="Game / Mod")
        game_ready = bool(
            scene.qss_game_folder != "NONE"
            and scene.qss_game_dir
            and os.path.isdir(_qss_abspath(scene.qss_game_dir))
        )
        # Import BSP opens Blender's standard file selector directly in the
        # active game's maps directory. Keep the archive-aware browser operator
        # registered for compatibility/F3 access, but don't spend sidebar space
        # on a second map-browsing workflow.
        row = layout.row(align=True)
        import_button = row.row()
        import_button.enabled = game_ready
        import_button.operator(QSS_OT_import_bsp.bl_idname, text="Import BSP", icon="IMPORT")
        export_row = row.row(align=True)
        export_row.enabled = _qss_is_map_object(obj) and context.mode == "OBJECT"
        export_row.operator(QSS_OT_export_bsp.bl_idname, text="Export BSP", icon="EXPORT")
        launch = layout.row(align=True)
        test_button = launch.row(align=True)
        test_button.enabled = bool(
            _qss_is_map_object(obj)
            and context.mode in {"OBJECT", "EDIT_MESH"}
            and scene.qss_quake_root and os.path.isdir(_qss_abspath(scene.qss_quake_root))
            and scene.qss_ironwail_executable
            and os.path.isfile(_qss_abspath(scene.qss_ironwail_executable))
            and scene.qss_game_dir and os.path.isdir(_qss_abspath(scene.qss_game_dir))
        )
        test_button.operator(
            QSS_OT_test_in_ironwail.bl_idname, text="Test in Ironwail", icon="PLAY"
        )
        maps = _qss_scene_map_collections(scene)
        if maps:
            layout.separator()
            active_map_row = layout.row(align=True)
            # The map-switch callback safely exits Edit/Paint mode before
            # changing the active collection, so the selector need not be locked.
            active_map_row.prop(scene, "qss_active_map_collection", text="Loaded Map")
            close_button = active_map_row.row(align=True)
            close_button.operator(
                QSS_OT_close_active_map.bl_idname, text="Close", icon="TRASH"
            )
        else:
            layout.label(text="No imported maps yet.", icon="INFO")
        if _qss_is_map_object(obj):
            box = layout.box()
            row = box.row(align=True)
            row.label(text=f"Lightmap Resolution: {int(obj.get('qss_lightmap_resolution', 1))}×")
            change = row.row()
            change.enabled = context.mode == "OBJECT" and bool(obj.get("qss_lightmap_image_name"))
            change.operator(QSS_OT_change_lightmap_resolution.bl_idname, text="Change")
            box.label(text=f"Source: {os.path.basename(obj.get('qss_source_path', ''))}", icon="FILE")
        else:
            layout.label(text="Import a BSP to enable export and lighting controls.", icon="INFO")


class QSS_PT_lighting(Panel):
    bl_label = "LIGHTING"
    bl_idname = "QSS_PT_lighting"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slipgate"
    bl_parent_id = "QSS_PT_main"
    bl_order = 40

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw(self, context):
        obj = context.object
        layout = self.layout
        mode = obj.get("qss_preview_mode", "source")
        row = layout.row(align=True)
        # Switching material nodes/render engine is safe in Edit Mode, but
        # deliberately unavailable while Texture Paint owns the active image.
        row.enabled = context.mode in {"OBJECT", "EDIT_MESH"}
        for value, label in (("source", "Original"), ("realtime", "Eevee"),
                             ("cycles", "Cycles"), ("baked", "Baked")):
            button = row.row(align=True)
            button.enabled = value != "baked" or _qss_has_baked_lightmap(obj)
            op = button.operator(QSS_OT_set_lighting_mode.bl_idname, text=label, depress=(mode == value))
            op.mode = value

        selected_faces = False
        if context.mode == "EDIT_MESH":
            try:
                import bmesh
                selected_faces = any(face.select for face in bmesh.from_edit_mesh(obj.data).faces)
            except Exception:
                selected_faces = False
        elif _qss_is_texture_paint_context(context):
            selected_faces = True
        paint = layout.row(align=True)
        paint.enabled = selected_faces
        current_paint_image = _qss_current_paint_image(context) if _qss_is_texture_paint_context(context) else None
        is_lightmap_paint = _qss_is_lightmap_paint_image(obj, current_paint_image)
        paint.operator(
            QSS_OT_activate_paint.bl_idname, text="Paint Texture", icon="BRUSH_DATA",
            depress=(_qss_is_texture_paint_context(context) and not is_lightmap_paint),
        )
        light_paint = paint.row()
        light_paint.enabled = selected_faces and (
            _qss_is_texture_paint_context(context)
            or (mode in {"source", "baked"} and (mode != "baked" or _qss_has_baked_lightmap(obj)))
        )
        light_paint.operator(
            QSS_OT_activate_lightmap_paint.bl_idname, text="Paint Lightmap", icon="TPAINT_HLT",
            depress=(_qss_is_texture_paint_context(context) and is_lightmap_paint),
        )

        if _qss_is_texture_paint_context(context):
            image_paint = context.scene.tool_settings.image_paint
            brush = image_paint.brush
            color_row = layout.row(align=True)
            color_row.label(text="Brush Color")
            color_row.prop(context.scene, "qss_paint_color_picker", expand=True)
            if str(context.scene.qss_paint_color_picker) == "QUAKE":
                try:
                    if image_paint.palette is None or not bool(image_paint.palette.get("qss_quake_palette", False)):
                        _qss_assign_quake_palette(context, obj)
                    layout.template_ID(image_paint, "palette", new="palette.new")
                    # Blender's native palette template computes its columns
                    # from the available layout width and draws square swatches.
                    # Keep this native widget so it resizes with the sidebar.
                    layout.template_palette(image_paint, "palette")
                    layout.label(text="224–254 fullbright · 255 transparent", icon="INFO")
                except Exception as exc:
                    layout.label(text=f"Quake palette unavailable: {exc}", icon="ERROR")
            elif brush is not None:
                color_controls = layout.row(align=True)
                color_controls.prop(brush, "color", text="Primary")
                color_controls.prop(brush, "secondary_color", text="Secondary")
                layout.template_color_picker(brush, "color", value_slider=True)
        else:
            picker_row = layout.row(align=True)
            picker_row.prop(context.scene, "qss_paint_color_picker", expand=True)

        # Three explicit fixed-width columns keep labels and checkboxes aligned.
        table = layout.box()
        header = table.row(align=True)
        header_split = header.split(factor=0.50, align=True)
        header_split.label(text="")
        header_columns = header_split.row(align=True)
        header_columns.alignment = "CENTER"
        header_columns.label(text="Painted")
        header_columns.label(text="Source")

        can_toggle_layers = context.mode in {"OBJECT", "EDIT_MESH"}
        texture_row = table.row(align=True)
        texture_split = texture_row.split(factor=0.50, align=True)
        texture_split.label(text="Textures")
        texture_columns = texture_split.row(align=True)
        painted_texture = texture_columns.row(align=True)
        painted_texture.alignment = "CENTER"
        painted_texture.enabled = can_toggle_layers and _qss_has_painted_texture_faces(obj)
        painted_texture.operator(
            QSS_OT_toggle_painted_textures.bl_idname,
            text="",
            icon="CHECKBOX_HLT" if bool(obj.get("qss_painted_textures_enabled", True)) else "CHECKBOX_DEHLT",
            depress=bool(obj.get("qss_painted_textures_enabled", True)),
        )
        source_texture = texture_columns.row(align=True)
        source_texture.alignment = "CENTER"
        source_texture.enabled = can_toggle_layers
        source_texture.operator(
            QSS_OT_toggle_textures.bl_idname,
            text="",
            icon="CHECKBOX_HLT" if bool(obj.get("qss_base_textures_enabled", True)) else "CHECKBOX_DEHLT",
            depress=bool(obj.get("qss_base_textures_enabled", True)),
        )

        lightmap_row = table.row(align=True)
        lightmap_split = lightmap_row.split(factor=0.50, align=True)
        lightmap_split.label(text="Lightmaps")
        lightmap_columns = lightmap_split.row(align=True)
        mode_has_paint = (
            bool(obj.get("qss_painted_original_lightmap", "")) if mode == "source"
            else bool(obj.get("qss_painted_baked_lightmap", "")) if mode == "baked"
            else False
        )
        painted_lightmap = lightmap_columns.row(align=True)
        painted_lightmap.alignment = "CENTER"
        painted_lightmap.enabled = (
            can_toggle_layers and mode in {"source", "baked"} and mode_has_paint
        )
        painted_lightmap.operator(
            QSS_OT_toggle_painted_lightmaps.bl_idname,
            text="",
            icon="CHECKBOX_HLT" if bool(obj.get("qss_painted_lightmaps_enabled", True)) else "CHECKBOX_DEHLT",
            depress=bool(obj.get("qss_painted_lightmaps_enabled", True)),
        )
        source_lightmap = lightmap_columns.row(align=True)
        source_lightmap.alignment = "CENTER"
        source_lightmap.enabled = can_toggle_layers and mode in {"source", "baked"}
        source_lightmap.operator(
            QSS_OT_toggle_source_lightmaps.bl_idname,
            text="",
            icon="CHECKBOX_HLT" if bool(obj.get("qss_source_lightmaps_enabled", True)) else "CHECKBOX_DEHLT",
            depress=bool(obj.get("qss_source_lightmaps_enabled", True)),
        )

        bake = layout.row()
        bake.enabled = context.mode == "OBJECT" and mode in {"realtime", "cycles"} and obj.get("qss_light_entity_count", 0) > 0
        bake.operator(QSS_OT_bake_scene_lights.bl_idname, text="Bake Lightmap", icon="RENDER_STILL")
        if mode == "realtime":
            layout.label(text="Eevee preview selected; baking currently uses the Cycles backend.", icon="INFO")
        if obj.get("qss_last_quake_bake_error"):
            row = layout.row()
            row.alert = True
            row.label(text=str(obj.get("qss_last_quake_bake_error"))[:100], icon="ERROR")
        if obj.get("qss_last_bake_luxel_mean") is not None:
            layout.label(text=f"Last bake mean: {float(obj.get('qss_last_bake_luxel_mean', 0.0)):.4g}", icon="IMAGE")


class QSS_PT_stats(Panel):
    bl_label = "STATS"
    bl_idname = "QSS_PT_stats"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Slipgate"
    bl_parent_id = "QSS_PT_main"
    bl_order = 50
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _qss_is_map_object(context.object)

    def draw_header(self, context):
        self.layout.label(text="", icon="INFO")

    def draw(self, context):
        obj = context.object
        mesh = obj.data
        layout = self.layout
        source = obj.get("qss_source_path", "")
        root = bpy.data.collections.get(obj.get("qss_map_collection", ""))
        map_objects = _qss_collection_objects(root) if root else {obj}
        entity_objects = [item for item in map_objects if item.get("qss_entity_role") or item.get("qss_light_role")]
        lights = [item for item in map_objects if item.type == "LIGHT" and item.get("qss_light_role")]
        source_box = layout.box()
        source_box.label(text="MAP", icon="FILE_3D")
        source_box.label(text=os.path.basename(source) if source else obj.name)
        source_box.label(text=f"BSP version: {obj.get('qss_bsp_version', 'unknown')}")
        if obj.get("qss_bounds_diagonal"):
            source_box.label(text=f"Bounds diagonal: {float(obj.get('qss_bounds_diagonal', 0.0)):.3f} m")
        geometry = layout.box()
        geometry.label(text="GEOMETRY", icon="MESH_DATA")
        geometry.label(text=f"Source BSP faces: {obj.get('qss_total_bsp_faces', len(mesh.polygons))}")
        geometry.label(text=f"Imported mesh: {len(mesh.polygons)} polygons · {len(mesh.vertices)} vertices")
        geometry.label(text=f"Materials: {len(mesh.materials)}")
        selected_paint_faces = _qss_selected_paint_face_count(context, obj)
        if selected_paint_faces:
            estimate = _qss_estimate_texture_paint_memory(context, obj)
            geometry.label(
                text=f"Paint prep: {selected_paint_faces} faces · "
                     f"~{palette_utils.format_mib(estimate['peak_pixel_bytes'])} peak image buffers"
            )
            available_memory = _qss_available_memory_bytes()
            if available_memory:
                geometry.label(
                    text=f"Available system/cgroup memory: {palette_utils.format_mib(available_memory)}"
                )
        entities = layout.box()
        entities.label(text="ENTITIES", icon="EMPTY_AXIS")
        entities.label(text=f"Entities: {obj.get('qss_entity_count', len(entity_objects))}")
        entities.label(text=f"Lights: {len(lights)}")
        entities.label(text=f"Player start: {'Yes' if obj.get('qss_has_player_start') else 'No'}")
        lighting = layout.box()
        lighting.label(text="TEXTURES & LIGHTING", icon="IMAGE")
        lighting.label(text=f"Textures: {obj.get('qss_texture_count', 0)}")
        missing = [v for v in str(obj.get("qss_missing_texture_names", "")).split(",") if v.strip()]
        lighting.label(text=f"Missing textures: {len(missing)}")
        lighting.label(text=f"Lightmapped faces: {obj.get('qss_lightmap_faces', 0)}")
        image = bpy.data.images.get(obj.get("qss_lightmap_image_name", ""))
        if image is not None:
            memory = int(image.size[0]) * int(image.size[1]) * (16 if image.is_float else 4)
            lighting.label(text=f"Working atlas: {image.size[0]}×{image.size[1]} · ~{memory / (1024 * 1024):.1f} MiB")
        lighting.label(text=f"Generated bake: {'Available' if _qss_has_baked_lightmap(obj) else 'Not baked'}")
        diagnostics = layout.box()
        diagnostics.label(text="EXPORT & DIAGNOSTICS", icon="EXPORT")
        last_export = _qss_last_export_path(obj)
        diagnostics.label(text=f"Last export: {os.path.basename(last_export) if last_export else 'Not exported'}")
        diagnostics.label(text=f"Format: {obj.get('qss_last_export_mode', '—')}")
        for key, label in (("qss_wad_unresolved", "WAD not found"),
                           ("qss_wad_failures", "WAD read issue"),
                           ("qss_missing_texture_names", "Missing textures"),
                           ("qss_last_quake_bake_error", "Last bake error"),
                           ("qss_last_detach_error", "Last paint/detach error")):
            value = obj.get(key, "")
            if value:
                row = diagnostics.row()
                row.alert = True
                row.label(text=f"{label}: {str(value)[:100]}", icon="ERROR")



CLASSES = (
    QSS_OT_confirm_import, QSS_OT_import_bsp, QSS_OT_browse_game_maps, QSS_OT_validate_bsp_export,
    QSS_OT_scan_game_maps, QSS_OT_run_python_tests, QSS_OT_run_map_audit,
    QSS_OT_launch_ironwail, QSS_OT_open_last_export, QSS_OT_test_in_ironwail, QSS_OT_open_config_text,
    QSS_OT_close_active_map, QSS_OT_load_quake_palette, QSS_OT_open_quake_palette,
    QSS_OT_convert_quake_palette, QSS_OT_viewport_material_preview,
    QSS_OT_settings, QSS_OT_change_lightmap_resolution, QSS_OT_set_lighting_mode,
    QSS_OT_toggle_textures, QSS_OT_toggle_source_lightmaps,
    QSS_OT_toggle_painted_textures, QSS_OT_toggle_painted_lightmaps,
    QSS_OT_generate_decoupled_lightmaps, QSS_OT_detach_faces,
    QSS_OT_activate_paint, QSS_OT_activate_lightmap_paint,
    QSS_OT_edit_face_overlay_watch, QSS_OT_camera_transition, QSS_OT_frame_selection, QSS_OT_focus_clip_watch, QSS_OT_isolate_faces, QSS_OT_reveal_faces,
    QSS_OT_optimize_clipping, QSS_OT_player_start, QSS_OT_fps_walk,
    QSS_OT_preview_imported_lights, QSS_OT_preview_source_lightmaps,
    QSS_OT_preview_bsp_lightmaps, QSS_OT_quake_direct_bake,
    QSS_OT_bake_scene_lights, QSS_OT_undo_last_bake,
    QSS_OT_restore_original_lightmap, QSS_OT_refresh_lightmap_preview,
    QSS_OT_apply_light_energy_scale, QSS_OT_calibrate_lights_to_source,
    QSS_OT_write_diagnostics, QSS_OT_run_blender_selftest, QSS_OT_export_bsp,
    QSS_PT_main, QSS_PT_quick_actions, QSS_PT_project, QSS_PT_lighting, QSS_PT_stats,
)

def _remove_qss_keymaps():
    """Remove legacy QSS MMB-to-FPS bindings from add-on and user keyconfigs."""
    global _addon_keymaps
    for km, kmi in list(_addon_keymaps):
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()

    wm = getattr(bpy.context, 'window_manager', None)
    keyconfigs = getattr(wm, 'keyconfigs', None) if wm else None
    if keyconfigs is None:
        return

    # Older QSS builds could leave the optional MMB operator in Blender's
    # effective user keyconfig after its Scene toggle and operator were removed.
    # Only remove this exact legacy QSS operator; preserve all Blender bindings.
    seen_keyconfigs = set()
    for config_name in ("addon", "user"):
        keyconfig = getattr(keyconfigs, config_name, None)
        if keyconfig is None or id(keyconfig) in seen_keyconfigs:
            continue
        seen_keyconfigs.add(id(keyconfig))
        for km in list(keyconfig.keymaps):
            for kmi in list(km.keymap_items):
                if getattr(kmi, "idname", "") == "qss.hold_mmb_fps":
                    try:
                        km.keymap_items.remove(kmi)
                    except Exception:
                        pass


def _remove_scene_properties():
    """Remove QSS Scene properties, including properties from an older module."""
    for name in (
        'qss_quake_root', 'qss_game_folder', 'qss_game_dir', 'qss_active_map_collection', 'qss_ericw_tools_dir',
        'qss_ironwail_executable', 'qss_ironwail_demo', 'qss_audit_enhanced_export',
        'qss_audit_quake_bake', 'qss_audit_cycles_bake', 'qss_audit_ericw_light', 'qss_audit_ericw_compile',
        'qss_audit_timeout', 'qss_quake_unit_scale', 'qss_nav_speed_quake',
        'qss_nav_fast_factor', 'qss_light_energy_scale',
        'qss_import_lightmap_resolution', 'qss_decoupled_world_units_per_luxel',
        'qss_bake_output_scale', 'qss_bake_bounces', 'qss_bake_match_source', 'qss_mmb_fps_walk',
        'qss_quake_bake_shadows', 'qss_quake_bake_gate', 'qss_paint_color_picker',
    ):
        if hasattr(bpy.types.Scene, name):
            try:
                delattr(bpy.types.Scene, name)
            except Exception:
                pass


def _unregister_qss_classes():
    """Unregister stale QSS classes by RNA name and current Python class.

    Blender may retain registered classes after an interrupted add-on enable.
    Resolve the registered RNA class first (it can belong to an older module
    instance), then also try the current class object as a defensive fallback.
    """
    # Remove panels from the pre-v0.18 multi-panel UI which are intentionally retired.
    for stale_name in (
        "QSS_PT_texture", "QSS_PT_light_preview", "QSS_PT_imported_lights",
        "QSS_PT_quake_bake", "QSS_PT_cycles_bake", "QSS_PT_diagnostics", "QSS_PT_export",
        "QSS_PT_palette_converter", "QSS_OT_check_quake_converter",
    ):
        stale_cls = getattr(bpy.types, stale_name, None)
        if stale_cls is not None:
            try:
                bpy.utils.unregister_class(stale_cls)
            except (RuntimeError, TypeError, ValueError):
                pass
    # Removed in the persistent FPS-navigation redesign; clean up an older registration.
    legacy_fps = getattr(bpy.types, "QSS_OT_hold_mmb_fps", None)
    if legacy_fps is not None:
        try:
            bpy.utils.unregister_class(legacy_fps)
        except (RuntimeError, TypeError, ValueError):
            pass
    for cls in reversed(CLASSES):
        old_cls = getattr(bpy.types, cls.__name__, None)
        candidates = [old_cls] if old_cls is not None else []
        if cls not in candidates:
            candidates.append(cls)
        for candidate in candidates:
            try:
                bpy.utils.unregister_class(candidate)
            except (RuntimeError, TypeError, ValueError):
                pass


def _cleanup_previous_registration():
    _qss_restore_focus_clip_session()
    _qss_remove_context_menus()
    for session in tuple(_qss_edit_overlay_sessions.values()):
        try:
            session._finish_restore()
        except Exception:
            pass
    _qss_edit_overlay_sessions.clear()
    for session in tuple(_qss_camera_transition_sessions.values()):
        try:
            session._finish()
        except Exception:
            pass
    _qss_camera_transition_sessions.clear()
    for session in tuple(_qss_focus_transition_sessions.values()):
        try:
            session._finish_modal(bpy.context, restore_clip=True)
        except Exception:
            pass
    _qss_focus_transition_sessions.clear()
    _qss_focus_cycle_state.clear()
    # Stop any legacy QSS modal navigation session left by v0.17.6 or earlier.
    # globals().get keeps fresh installs independent of that removed state.
    legacy_sessions = globals().get("_qss_fps_navigation_sessions", {})
    for session in tuple(legacy_sessions.values()):
        timer = session.get("timer")
        window_manager = session.get("window_manager")
        if timer is not None and window_manager is not None:
            try:
                window_manager.event_timer_remove(timer)
            except Exception:
                pass
        try:
            session["area"].header_text_set(None)
            session["area"].tag_redraw()
        except Exception:
            pass
        session["timer"] = None
        session["finished"] = True
    legacy_sessions.clear()
    _remove_qss_keymaps()
    _remove_scene_properties()
    _unregister_qss_classes()


def register():
    """Register QSS safely, including upgrades from an already-enabled build."""
    _cleanup_previous_registration()
    registered = []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)

        initial_config = _qss_load_config()
        initial_root, initial_game_id, initial_game_dir = _qss_choose_initial_game_settings(initial_config)
        available_game_ids = [item['id'] for item in quake_paths.discover_game_dirs(initial_root)]
        if initial_game_id not in available_game_ids:
            initial_game_id = available_game_ids[0] if available_game_ids else 'NONE'
        bpy.types.Scene.qss_quake_root = StringProperty(
            name="Quake installation folder",
            description="The folder containing id1 and any installed mod folders; selecting id1 itself is also accepted",
            subtype='DIR_PATH',
            default=initial_root,
            update=_on_quake_root_changed,
        )
        # Dynamic EnumProperty items must not specify a registration-time
        # default. Blender 5.2 can validate that default before a Scene
        # context exists, causing RNA registration to fail even when the
        # callback can later provide valid items.
        bpy.types.Scene.qss_game_folder = EnumProperty(
            name="Game / Mod",
            description="Select id1 or another detected Quake game/mod folder",
            items=_qss_game_folder_items,
            update=_on_game_folder_changed,
        )
        bpy.types.Scene.qss_game_dir = StringProperty(
            name="Active Quake game directory",
            description="Resolved active game folder used by the importer and texture/WAD lookup",
            subtype='DIR_PATH',
            default=initial_game_dir,
        )
        bpy.types.Scene.qss_active_map_collection = EnumProperty(
            name="Loaded Map",
            description="Choose the active imported BSP map; other scene objects are hidden",
            items=_qss_map_collection_items,
            update=_qss_on_active_map_changed,
        )
        bpy.types.Scene.qss_paint_color_picker = EnumProperty(
            name="Brush color source",
            description="Choose Blender's normal color picker or the active map's 256-entry Quake palette",
            items=(
                ("STANDARD", "Standard", "Use Blender's normal brush color picker"),
                ("QUAKE", "Quake", "Pick directly from the active map's 256-color Quake palette"),
            ),
            default="STANDARD",
            update=_qss_on_paint_color_picker_changed,
        )
        bpy.types.Scene.qss_ericw_tools_dir = StringProperty(
            name="ericw-tools folder", description="Folder containing qbsp, vis, light and bspinfo",
            subtype='DIR_PATH', default=_qss_abspath(initial_config.get('ericw_tools_dir', '')),
            update=_on_external_tool_path_changed,
        )
        bpy.types.Scene.qss_ironwail_executable = StringProperty(
            name="Ironwail executable", description="Path to ironwail.exe or the Ironwail executable",
            subtype='FILE_PATH', default=_qss_abspath(initial_config.get('ironwail_executable', '')),
            update=_on_external_tool_path_changed,
        )
        bpy.types.Scene.qss_ironwail_demo = StringProperty(
            name="Ironwail demo", description="Optional .dem file to play when launching Ironwail",
            subtype='FILE_PATH', default=_qss_abspath(initial_config.get('ironwail_demo', '')),
            update=_on_external_tool_path_changed,
        )
        bpy.types.Scene.qss_audit_enhanced_export = BoolProperty(
            name="Test Enhanced BSPX export", default=False,
            description="Attempt enhanced DECOUPLED_LM lightmap export on each imported map where supported",
        )
        bpy.types.Scene.qss_audit_quake_bake = BoolProperty(
            name="Run Quake direct lightmap bake", default=False,
            description="Run the full CPU ray-traced Quake lightmap solver on each map; can take a long time",
        )
        bpy.types.Scene.qss_audit_cycles_bake = BoolProperty(
            name="Run Cycles PBR lightmap bake", default=False,
            description="Run the experimental Cycles bake on a disposable duplicate and verify exact undo; can be very slow",
        )
        bpy.types.Scene.qss_audit_ericw_light = BoolProperty(
            name="Run ericw light on disposable BSP copy", default=False,
            description="Run verbose ericw light on a copy of each BSP; never overwrites the game map",
        )
        bpy.types.Scene.qss_audit_ericw_compile = BoolProperty(
            name="Compile sibling MAP files with ericw-tools", default=False,
            description="Run qbsp, vis and light when a loose sibling .map source is available",
        )
        bpy.types.Scene.qss_audit_timeout = IntProperty(
            name="External tool timeout (seconds)", default=300, min=10, max=7200,
        )
        initial_lightmap_resolution = str(initial_config.get("import_lightmap_resolution", "1"))
        if initial_lightmap_resolution not in {"1", "2", "4", "8"}:
            initial_lightmap_resolution = "1"
        bpy.types.Scene.qss_import_lightmap_resolution = EnumProperty(
            name="Visual lightmap resolution",
            description="Working paint-atlas scale only; does not change the source BSP's luxel density",
            items=(
                ('1', "1× · Original", "Original packed atlas resolution"),
                ('2', "2×", "Twice the pixels per axis"),
                ('4', "4×", "Four times the pixels per axis"),
                ('8', "8×", "Eight times the pixels per axis"),
            ),
            default=initial_lightmap_resolution,
        )
        bpy.types.Scene.qss_decoupled_world_units_per_luxel = FloatProperty(
            name="Target world units per luxel",
            description=(
                "Lower values create denser, more detailed lightmaps but increase compile time "
                "and BSP size; higher values are faster and smaller but less detailed"
            ),
            default=16.0, min=0.01, max=1024.0, precision=2,
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
        # Apply the persisted selection only after the dynamic enum and
        # its item callback are registered and a real Scene is available.
        scene = getattr(bpy.context, 'scene', None)
        if scene is not None:
            global _qss_config_update_depth
            _qss_config_update_depth = True
            try:
                scene.qss_game_folder = initial_game_id
                scene.qss_game_dir = initial_game_dir
                _qss_migrate_legacy_map_collections(scene)
                existing_maps = _qss_scene_map_collections(scene)
                active_obj = getattr(getattr(bpy.context, "view_layer", None), "objects", None)
                active_obj = getattr(active_obj, "active", None) if active_obj is not None else None
                active_collection_name = (
                    active_obj.get("qss_map_collection", "")
                    if _qss_is_map_object(active_obj) else
                    (existing_maps[0].name if existing_maps else "__QSS_NO_MAP__")
                )
                scene.qss_active_map_collection = active_collection_name
                if active_collection_name != "__QSS_NO_MAP__":
                    _qss_activate_map_collection(scene, active_collection_name, bpy.context)
                _qss_register_context_menus()
                _qss_apply_viewport_fov(
                    bpy.context, _qss_config_settings().get("viewport_fov_degrees", 90.0)
                )
            finally:
                _qss_config_update_depth = False
    except Exception:
        # Blender can leave a partially registered add-on behind when register()
        # raises. Roll back everything created in this attempt before propagating.
        _cleanup_previous_registration()
        raise


def unregister():
    """Idempotent cleanup for disable, reload, and reinstall operations."""
    _cleanup_previous_registration()
