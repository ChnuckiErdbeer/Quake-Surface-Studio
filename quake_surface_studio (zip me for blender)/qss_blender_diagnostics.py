"""Quake Surface Studio Blender self-test / diagnostic report.

Run this file from Blender's Text Editor (Scripting workspace -> Open -> Run
Script). It does not modify the selected BSP. By default it also creates a
small isolated plane+lamp and runs a tiny Cycles image-texture bake to verify
that Blender 5.2's bake target writes pixels independently of QSS materials.
"""
from __future__ import annotations

import array
import datetime
import os
import sys
import time
import copy
import traceback

import bpy
from mathutils import Vector

RUN_ISOLATED_CYCLES_PROBE = True
RUN_FULL_QUAKE_LUXEL_SCAN = True
# 0 means benchmark every luxel. A positive value caps the scan for very large maps.
MAX_BENCHMARK_LUXELS = 0
PROGRESS_UPDATE_INTERVAL = 32


def _safe(call, default='unavailable'):
    try:
        return call()
    except Exception as exc:
        return f'{default}: {exc}'


def _image_stats(image):
    try:
        count = int(image.size[0]) * int(image.size[1])
        px = array.array('f', [0.0]) * (count * 4)
        image.update()
        image.pixels.foreach_get(px)
        maximum = 0.0
        total = 0.0
        nonzero = 0
        for i in range(0, len(px), 4):
            r, g, b = px[i:i + 3]
            maximum = max(maximum, r, g, b)
            total += 0.2126 * r + 0.7152 * g + 0.0722 * b
            nonzero += int(max(r, g, b) > 1e-8)
        return f'{image.name}: {image.size[0]}x{image.size[1]} float={image.is_float} ' \
               f'colorspace={image.colorspace_settings.name} mean={total/max(1,count):.6g} ' \
               f'max={maximum:.6g} nonzero={nonzero}/{count}'
    except Exception:
        return f'{getattr(image, "name", "<image>")}: ERROR\n{traceback.format_exc()}'


def _qss_objects():
    return [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.get('qss_object_role') == 'quake_bsp29']


def _run_cycles_probe(lines):
    scene = bpy.context.scene
    wm = bpy.context.window_manager
    old_engine = scene.render.engine
    old_active = bpy.context.view_layer.objects.active
    old_selected = list(bpy.context.selected_objects)
    old_settings = {}
    old_cycles = {}
    old_hidden = []
    temp_collection = None
    plane = None
    lamp = None
    material = None
    mesh = None
    image = None
    result_text = 'NOT RUN'
    image_result = 'n/a'
    try:
        if not hasattr(scene, 'cycles') or not hasattr(scene.render, 'bake'):
            raise RuntimeError('Cycles baking API is unavailable in this Blender build.')
        for name in ('target', 'use_pass_color', 'use_pass_diffuse', 'use_pass_direct',
                     'use_pass_indirect', 'use_clear', 'margin'):
            if hasattr(scene.render.bake, name):
                old_settings[name] = getattr(scene.render.bake, name)
        for name in ('samples', 'diffuse_bounces', 'max_bounces', 'device'):
            if hasattr(scene.cycles, name):
                old_cycles[name] = getattr(scene.cycles, name)
        for obj in list(scene.objects):
            old_hidden.append((obj, bool(obj.hide_render)))
            obj.hide_render = True

        temp_collection = bpy.data.collections.new('QSS_TEMP_CYCLES_PROBE')
        scene.collection.children.link(temp_collection)
        mesh = bpy.data.meshes.new('QSS_TEMP_CYCLES_PROBE_Mesh')
        mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)], [], [(0,1,2,3)])
        mesh.update()
        uv = mesh.uv_layers.new(name='UVMap')
        for loop in mesh.loops:
            co = mesh.vertices[loop.vertex_index].co
            uv.data[loop.index].uv = ((co.x + 1.0) * 0.5, (co.y + 1.0) * 0.5)
        plane = bpy.data.objects.new('QSS_TEMP_CYCLES_PROBE_Plane', mesh)
        plane.location = (0.0, 0.0, -10000.0)
        temp_collection.objects.link(plane)

        material = bpy.data.materials.new('QSS_TEMP_CYCLES_PROBE_Material')
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        diffuse = nodes.new('ShaderNodeBsdfDiffuse')
        diffuse.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        diffuse.inputs['Roughness'].default_value = 1.0
        output = nodes.new('ShaderNodeOutputMaterial')
        material.node_tree.links.new(diffuse.outputs['BSDF'], output.inputs['Surface'])
        tex = nodes.new('ShaderNodeTexImage')
        image = bpy.data.images.new('QSS_TEMP_CYCLES_PROBE_Image', 32, 32, alpha=True, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        tex.image = image
        tex.select = True
        nodes.active = tex
        plane.data.materials.append(material)

        lamp_data = bpy.data.lights.new('QSS_TEMP_CYCLES_PROBE_Light', 'POINT')
        lamp_data.energy = 1000.0
        lamp_data.shadow_soft_size = 0.1
        lamp = bpy.data.objects.new('QSS_TEMP_CYCLES_PROBE_Light', lamp_data)
        lamp.location = (0.0, 0.0, -9996.0)
        temp_collection.objects.link(lamp)

        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 8
        scene.cycles.diffuse_bounces = 0
        if hasattr(scene.render.bake, 'target'):
            scene.render.bake.target = 'IMAGE_TEXTURES'
        scene.render.bake.use_pass_color = False
        scene.render.bake.use_pass_diffuse = True
        scene.render.bake.use_pass_direct = True
        scene.render.bake.use_pass_indirect = False
        scene.render.bake.use_clear = True
        scene.render.bake.margin = 0
        bpy.ops.object.select_all(action='DESELECT')
        plane.hide_render = False
        lamp.hide_render = False
        plane.select_set(True)
        bpy.context.view_layer.objects.active = plane

        window = bpy.context.window
        area = next((a for a in window.screen.areas if a.type == 'VIEW_3D'), None) if window else None
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
        override = {'object': plane, 'active_object': plane,
                    'selected_objects': [plane], 'selected_editable_objects': [plane]}
        if window:
            override['window'] = window
        if area:
            override['area'] = area
        if region:
            override['region'] = region
        with bpy.context.temp_override(**override):
            op_result = bpy.ops.object.bake(type='DIFFUSE')
        result_text = ','.join(sorted(op_result))
        image_result = _image_stats(image)
        pixels = array.array('f', [0.0]) * (32 * 32 * 4)
        image.pixels.foreach_get(pixels)
        maximum = max((max(pixels[i], pixels[i+1], pixels[i+2]) for i in range(0, len(pixels), 4)), default=0.0)
        if maximum <= 1e-8:
            result_text += ' (FINISHED BUT IMAGE ZERO)'
        else:
            result_text += f' (PIXELS WRITTEN, max={maximum:.6g})'
    except Exception as exc:
        result_text = f'FAILED: {exc}\n{traceback.format_exc()}'
    finally:
        try:
            scene.render.engine = old_engine
            for name, value in old_settings.items():
                setattr(scene.render.bake, name, value)
            for name, value in old_cycles.items():
                setattr(scene.cycles, name, value)
        except Exception:
            pass
        for obj, hidden in old_hidden:
            try:
                obj.hide_render = hidden
            except Exception:
                pass
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in old_selected:
                if obj.name in bpy.data.objects:
                    obj.select_set(True)
            if old_active and old_active.name in bpy.data.objects:
                bpy.context.view_layer.objects.active = old_active
        except Exception:
            pass
        for obj in (plane, lamp):
            if obj and obj.name in bpy.data.objects:
                try:
                    bpy.data.objects.remove(obj, do_unlink=True)
                except Exception:
                    pass
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        if lamp and lamp.data and lamp.data.users == 0:
            bpy.data.lights.remove(lamp.data)
        if material and material.users == 0:
            bpy.data.materials.remove(material)
        if image and image.users == 0:
            bpy.data.images.remove(image)
        if temp_collection and temp_collection.name in bpy.data.collections:
            try:
                bpy.data.collections.remove(temp_collection)
            except Exception:
                pass
    lines.append('ISOLATED CYCLES IMAGE-BAKE PROBE:')
    lines.append(f'  Operator result: {result_text}')
    lines.append(f'  Image: {image_result}')



def _run_quake_luxel_benchmark(lines):
    """Run the QSS direct-light evaluator over every BSP luxel for delays 0..5.

    This is deliberately a dry run: it never writes the map's atlas or BSP.
    It reports actual imported light/style values and per-delay luxel coverage.
    """
    qss_objects = _qss_objects()
    if not qss_objects:
        lines.append('QUAKE LUXEL BENCHMARK: skipped (no imported QSS BSP mesh).')
        return
    obj = bpy.context.object if bpy.context.object in qss_objects else qss_objects[0]
    if obj.mode != 'OBJECT':
        lines.append(f'QUAKE LUXEL BENCHMARK: skipped (map object {obj.name} is in {obj.mode}; switch to Object Mode).')
        return
    try:
        package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if package_parent not in sys.path:
            sys.path.insert(0, package_parent)
        import importlib
        qss_bsp = importlib.import_module('quake_surface_studio.bsp')
        qss_lighting = importlib.import_module('quake_surface_studio.lighting')
        qss_addon = importlib.import_module('quake_surface_studio.addon')

        path = bpy.path.abspath(obj.get('qss_source_path', ''))
        if not path or not os.path.isfile(path):
            raise RuntimeError('source BSP path is missing')
        parsed = qss_bsp.BSP29.from_file(path)
        unit = float(obj.get('qss_unit_scale', 0.0254))
        flip_z = bool(obj.get('qss_flip_z', False))
        lights, unsupported = qss_addon._qss_collect_direct_lights(
            bpy.context, obj, unit, flip_z
        )
        if not lights:
            raise RuntimeError('no imported point/spot QSS lights were found')

        required_attrs = ('qss_bsp_face_id', 'qss_lm_has_data', 'qss_lm_atlas_x',
                          'qss_lm_atlas_y', 'qss_lm_sample_w', 'qss_lm_sample_h')
        for name in required_attrs:
            attr = obj.data.attributes.get(name)
            if attr is None or len(attr.data) != len(obj.data.polygons):
                raise RuntimeError(
                    f'{name} has {len(attr.data) if attr else "MISSING"} entries for '
                    f'{len(obj.data.polygons)} polygons; re-import BSP'
                )

        work = []
        for poly_index, _poly in enumerate(obj.data.polygons):
            face_id = int(obj.data.attributes['qss_bsp_face_id'].data[poly_index].value)
            face = qss_addon._qss_read_source_face_sample(obj.data, poly_index, face_id, parsed)
            if face is None:
                continue
            for sy in range(face['height']):
                for sx in range(face['width']):
                    s_value = face['s_min'] + sx * 16.0 - float(face['texinfo'][3])
                    t_value = face['t_min'] + sy * 16.0 - float(face['texinfo'][7])
                    point = qss_lighting.solve_texinfo_plane(
                        face['texinfo'][0:3], face['texinfo'][4:7],
                        face['plane_normal'], s_value, t_value, face['plane_distance']
                    )
                    if point is None:
                        continue
                    n = Vector(face['plane_normal'])
                    if flip_z:
                        n.z = -n.z
                    normal_world = (obj.matrix_world.to_3x3().inverted_safe().transposed() @ n).normalized()
                    point_world = qss_addon._qss_quake_to_world(obj, point, unit, flip_z)
                    work.append((face['face_id'], face['styles'], point, face['plane_normal'], point_world, normal_world))

        if not work:
            raise RuntimeError('no valid lightmap luxels were reconstructed')
        total_source_luxels = len(work)
        if MAX_BENCHMARK_LUXELS > 0 and len(work) > MAX_BENCHMARK_LUXELS:
            # Deterministic even sampling keeps coverage across the entire map.
            stride = len(work) / float(MAX_BENCHMARK_LUXELS)
            work = [work[min(len(work) - 1, int(i * stride))] for i in range(MAX_BENCHMARK_LUXELS)]
            lines.append(f'  benchmark sampling: {len(work):,} of {total_source_luxels:,} luxels (MAX_BENCHMARK_LUXELS={MAX_BENCHMARK_LUXELS})')
        else:
            lines.append(f'  benchmark sampling: all {len(work):,} luxels')
        bvh = None
        if bool(getattr(bpy.context.scene, 'qss_quake_bake_shadows', True)):
            bvh = qss_addon._qss_source_bvh(obj, parsed, unit, flip_z, bpy.context)
        world_dist = float(obj.get('qss_world_dist', 1.0))
        world_range = float(obj.get('qss_world_range', 0.5))
        world_gamma = float(obj.get('qss_world_gamma', 1.0))
        maxlight = float(obj.get('qss_world_maxlight', 255.0))
        energy = float(getattr(bpy.context.scene, 'qss_light_energy_scale', 1.0))
        gate = float(getattr(bpy.context.scene, 'qss_quake_bake_gate', 0.001))
        epsilon = 0.5 * unit
        lines.append('QUAKE LUXEL BENCHMARK (dry run; map and atlas are not modified):')
        lines.append(f'  BSP={os.path.basename(path)} faces={len(parsed.faces())} luxels={len(work)} lights={len(lights)}')
        lines.append(f'  settings: energy_scale={energy} world_dist={world_dist} world_range={world_range} gamma={world_gamma} gate={gate} shadows={bvh is not None}')
        lines.append('  imported lights:')
        for lamp in lights:
            lines.append(f"    {lamp['name']}: style={lamp['style']} delay={lamp['delay']} value={lamp['value']} wait={lamp['wait']} colour={lamp['color']} origin={lamp['origin']} angle={lamp['anglescale']}")
        lines.append('  documented attenuation response (unit lamp value=300, wait=1, world _dist=1):')
        for delay in range(6):
            values = []
            for distance in (16, 32, 64, 128, 256, 512):
                values.append(qss_lighting.ericw_light_value(300.0, delay, distance))
            lines.append(f"    delay {delay}: " + ', '.join(f'{v:.3f}' for v in values) + ' at d=16,32,64,128,256,512')

        progress_total = len(work) * 7
        progress_value = [0]
        wm = bpy.context.window_manager
        progress_started = False
        try:
            wm.progress_begin(0, max(1, progress_total))
            progress_started = True
        except Exception:
            pass

        def run_set(lights_for_run, label):
            start_time = time.perf_counter()
            all_luma = []
            lit_count = 0
            face_chroma = set()
            face_lit = set()
            ray_count = 0
            blocked_count = 0
            for work_index, (face_id, styles, qpoint, qnormal, world_point, world_normal) in enumerate(work):
                progress_value[0] += 1
                if progress_started and (work_index % PROGRESS_UPDATE_INTERVAL == 0 or work_index == len(work) - 1):
                    try:
                        wm.progress_update(min(progress_total, progress_value[0]))
                    except Exception:
                        pass
                def visible(light, _sample, _normal):
                    nonlocal ray_count, blocked_count
                    if bvh is None:
                        return True
                    target = light['world_origin']
                    vector = target - world_point
                    distance = vector.length
                    if distance <= epsilon:
                        return True
                    origin = world_point + world_normal * epsilon
                    vector = target - origin
                    distance = vector.length
                    if distance <= epsilon:
                        return True
                    ray_count += 1
                    hit = bvh.ray_cast(origin, vector.normalized(), max(0.0, distance - epsilon))
                    if hit and hit[0] is not None:
                        blocked_count += 1
                        return False
                    return True
                rgb = qss_lighting.evaluate_quake_luxel(
                    qpoint, qnormal, lights_for_run, styles,
                    world_dist=world_dist, world_range=world_range,
                    world_gamma=world_gamma, energy_scale=energy,
                    visible=visible, maxlight=maxlight, contribution_gate=gate,
                )
                luma = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
                all_luma.append(luma)
                if max(rgb) > 1e-8:
                    lit_count += 1
                    face_lit.add(face_id)
                if max(rgb) - min(rgb) > (12.0 / 255.0):
                    face_chroma.add(face_id)
            elapsed = time.perf_counter() - start_time
            mean = sum(all_luma) / max(1, len(all_luma))
            peak = max(all_luma, default=0.0)
            lines.append(f'  {label}: lit={lit_count}/{len(work)} faces_lit={len(face_lit)}/{len({w[0] for w in work})} chromatic_faces={len(face_chroma)} mean={mean:.6g} peak={peak:.6g} rays={ray_count} blocked={blocked_count} time={elapsed:.2f}s')

        try:
            run_set(lights, 'ACTUAL DELAY SETTINGS')
            for delay in range(6):
                trial = [dict(light, delay=delay) for light in lights]
                run_set(trial, f'ALL LIGHTS OVERRIDDEN TO delay {delay}')
        finally:
            if progress_started:
                try:
                    wm.progress_end()
                except Exception:
                    pass
        if unsupported:
            lines.append('  unsupported: ' + '; '.join(unsupported))
        lines.append('  note: dry-run output is the QSS direct-light approximation; radiosity/bounce, dirtmapping, area/deviance samples and surface emitters are not included.')
    except Exception as exc:
        lines.append(f'QUAKE LUXEL BENCHMARK ERROR: {exc}\n{traceback.format_exc()}')

def run():
    lines = [
        'QUAKE SURFACE STUDIO — BLENDER 5.2 SELF TEST (QSS 0.11.0)',
        f'Timestamp: {datetime.datetime.now().isoformat(timespec="seconds")}',
        f'Blender: {bpy.app.version_string} / {bpy.app.build_hash.decode(errors="replace") if isinstance(bpy.app.build_hash, bytes) else bpy.app.build_hash}',
        f'Blend file: {bpy.data.filepath or "<unsaved>"}',
        f'Render engine: {bpy.context.scene.render.engine}',
        f'Bake target: {getattr(bpy.context.scene.render.bake, "target", "n/a")}',
        f'Bake type: {getattr(bpy.context.scene.render.bake, "type", "n/a")}',
        f'Bake passes: color={getattr(bpy.context.scene.render.bake, "use_pass_color", None)} '
        f'diffuse={getattr(bpy.context.scene.render.bake, "use_pass_diffuse", None)} '
        f'direct={getattr(bpy.context.scene.render.bake, "use_pass_direct", None)} '
        f'indirect={getattr(bpy.context.scene.render.bake, "use_pass_indirect", None)}',
        '', 'QSS MESHES:',
    ]
    qss_meshes = _qss_objects()
    if not qss_meshes:
        lines.append('  No imported QSS BSP mesh found in the active scene.')
    for obj in qss_meshes:
        mesh = obj.data
        lines.append(f'  {obj.name}: mode={obj.mode} verts={len(mesh.vertices)} edges={len(mesh.edges)} '
                     f'loops={len(mesh.loops)} polys={len(mesh.polygons)} materials={len(mesh.materials)}')
        lines.append(f'    source={obj.get("qss_source_path", "")}')
        for layer in mesh.uv_layers:
            lines.append(f'    UV {layer.name}: data={len(layer.data)} loop_count={len(mesh.loops)} active_render={layer.active_render}')
        for attr in mesh.attributes:
            if attr.name.startswith('qss_'):
                lines.append(f'    ATTR {attr.name}: domain={attr.domain} type={attr.data_type} len={len(attr.data)}')
        invalid_materials = []
        for poly in mesh.polygons:
            if poly.material_index < 0 or poly.material_index >= len(mesh.materials):
                invalid_materials.append((poly.index, poly.material_index))
        lines.append(f'    Invalid material indices: {invalid_materials[:20]} (count={len(invalid_materials)})')
        for attr_name in ('qss_bsp_face_id', 'qss_lm_has_data', 'qss_lm_atlas_x',
                          'qss_lm_atlas_y', 'qss_lm_sample_w', 'qss_lm_sample_h'):
            attr = mesh.attributes.get(attr_name)
            if attr and len(attr.data) != len(mesh.polygons):
                lines.append(f'    WARNING: {attr_name} length {len(attr.data)} != polygon count {len(mesh.polygons)}')
        lm = bpy.data.images.get(obj.get('qss_lightmap_image_name', ''))
        if lm:
            lines.append('    ' + _image_stats(lm))
        for key in ('qss_last_detach_error', 'qss_last_detach_traceback',
                    'qss_last_quake_bake_error', 'qss_last_quake_bake_traceback'):
            value = obj.get(key)
            if value:
                lines.append(f'    {key}: {value}')
        lines.append('    MATERIAL NODE CHECKS:')
        for slot, mat in enumerate(mesh.materials):
            if mat is None:
                lines.append(f'      slot {slot}: EMPTY')
                continue
            if not mat.use_nodes or not mat.node_tree:
                lines.append(f'      slot {slot} {mat.name}: nodes disabled')
                continue
            nodes = mat.node_tree.nodes
            image_nodes = []
            active_nodes = []
            outputs = [n for n in nodes if n.type == 'OUTPUT_MATERIAL']
            for node in nodes:
                if node.type == 'TEX_IMAGE':
                    image_nodes.append((node.name, node.get('qss_role', ''), node.image.name if node.image else None,
                                        bool(node.image), bool(node.select)))
                    if node.select or nodes.active == node:
                        active_nodes.append(node.name)
            surface_links = [l for l in mat.node_tree.links if outputs and l.to_node in outputs and l.to_socket.name == 'Surface']
            lines.append(f'      slot {slot} {mat.name}: nodes={len(nodes)} active={active_nodes} '
                         f'images={image_nodes} surface_links={len(surface_links)}')
    lines.extend(['', 'IMPORTED QSS LIGHTS:'])
    for light in bpy.context.scene.objects:
        if light.type == 'LIGHT' and light.get('qss_light_role') in {'quake_entity_light', 'quake_world_sunlight'}:
            lines.append(f'  {light.name}: type={light.data.type} energy={light.data.energy:.6g} '
                         f'color={tuple(light.data.color)} delay={light.get("qss_quake_light_delay", 0)} '
                         f'style={light.get("qss_quake_light_style", 0)} wait={light.get("qss_quake_wait", 1)} '
                         f'falloff={light.get("qss_quake_falloff", 0)} hidden={light.hide_render}/{light.hide_viewport}')
    if RUN_FULL_QUAKE_LUXEL_SCAN:
        _run_quake_luxel_benchmark(lines)
    if RUN_ISOLATED_CYCLES_PROBE:
        _run_cycles_probe(lines)
    text = '\n'.join(lines)
    txt = bpy.data.texts.get('QSS_Blender_SelfTest') or bpy.data.texts.new('QSS_Blender_SelfTest')
    txt.clear()
    txt.write(text)
    desktop = os.path.expanduser('~/Desktop')
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser('~')
    filename = os.path.join(desktop, 'QSS_Blender_SelfTest.txt')
    with open(filename, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print('\n' + text)
    print(f'\nQSS self-test saved to: {filename}')


run()
