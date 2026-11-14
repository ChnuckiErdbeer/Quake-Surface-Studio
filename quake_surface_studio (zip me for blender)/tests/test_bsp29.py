import os
import struct
import tempfile
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import bsp


def make_test_bsp():
    # A tiny structural BSP29 fixture: one triangle face and one 16x16 miptex.
    mip_levels = [bytes([10]) * 256, bytes([10]) * 64, bytes([10]) * 16, bytes([10]) * 4]
    mip_blob = bsp.build_miptex_blob('TEST', 16, 16, mip_levels)
    lumps = [b''] * 15
    lumps[bsp.LUMP_ENTITIES] = b'{"classname" "worldspawn"}\0'
    lumps[bsp.LUMP_PLANES] = struct.pack('<4fi', 0.0, 0.0, 1.0, 0.0, 2)
    lumps[bsp.LUMP_TEXTURES] = bsp.build_texture_lump([bsp.MipTexture(mip_blob, 'TEST', 16, 16)])
    lumps[bsp.LUMP_VERTEXES] = b''.join([
        struct.pack('<3f', 0.0, 0.0, 0.0),
        struct.pack('<3f', 64.0, 0.0, 0.0),
        struct.pack('<3f', 0.0, 64.0, 0.0),
    ])
    lumps[bsp.LUMP_TEXINFO] = struct.pack('<8fii', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0)
    # edge 0 is unused; face uses edges 1, 2, 3 in forward direction.
    lumps[bsp.LUMP_EDGES] = b''.join([
        struct.pack('<2H', 0, 0),
        struct.pack('<2H', 0, 1),
        struct.pack('<2H', 1, 2),
        struct.pack('<2H', 2, 0),
    ])
    lumps[bsp.LUMP_SURFEDGES] = struct.pack('<3i', 1, 2, 3)
    lumps[bsp.LUMP_FACES] = struct.pack('<Hhihh4Bi', 0, 0, 0, 3, 0, 0, 255, 255, 255, -1)
    # One dmodel_t (64 bytes), with face range [0, 1).
    lumps[bsp.LUMP_MODELS] = struct.pack('<9f7i', 0, 0, 0, 64, 64, 64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1)
    return bsp.BSP29(bsp.BSP29(bsp.BSP_VERSION.to_bytes(4, 'little', signed=True) + b'\0' * 120).write(lumps))


class BSP29Tests(unittest.TestCase):
    def test_round_trip_preserves_lumps(self):
        original = make_test_bsp()
        rebuilt = original.write()
        reparsed = bsp.BSP29(rebuilt)
        self.assertEqual(reparsed.lumps, original.lumps)
        self.assertEqual(len(reparsed.faces()), 1)
        self.assertEqual(reparsed.face_vertex_indices(reparsed.faces()[0]), [0, 1, 2])

    def test_texture_lump_parse_and_rebuild(self):
        original = make_test_bsp()
        entries = original.miptextures()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, 'TEST')
        self.assertEqual((entries[0].width, entries[0].height), (16, 16))
        rebuilt = bsp.build_texture_lump(entries)
        check = bsp.BSP29(original.write())
        lumps = list(check.lumps)
        lumps[bsp.LUMP_TEXTURES] = rebuilt
        self.assertEqual(bsp.BSP29(check.write(lumps)).miptextures()[0].name, 'TEST')

    def test_clone_texinfo_and_redirect_one_face(self):
        original = make_test_bsp()
        new_ti, ti_index = bsp.clone_texinfo(original.lumps[bsp.LUMP_TEXINFO], 0, 1)
        new_faces = bsp.replace_face_texinfo(original.lumps[bsp.LUMP_FACES], 0, ti_index)
        lumps = list(original.lumps)
        lumps[bsp.LUMP_TEXINFO] = new_ti
        lumps[bsp.LUMP_FACES] = new_faces
        reparsed = bsp.BSP29(original.write(lumps))
        self.assertEqual(reparsed.faces()[0][4], 1)
        self.assertEqual(reparsed.texinfos()[1][8], 1)
        self.assertEqual(reparsed.lumps[bsp.LUMP_ENTITIES], original.lumps[bsp.LUMP_ENTITIES])
        self.assertEqual(reparsed.lumps[bsp.LUMP_LIGHTING], original.lumps[bsp.LUMP_LIGHTING])

    def test_clone_texinfo_with_custom_projection(self):
        original = make_test_bsp()
        projection = (2.0, 0.0, 0.0, -32.0, 0.0, 4.0, 0.0, -64.0)
        new_ti, index = bsp.clone_texinfo_with_projection(
            original.lumps[bsp.LUMP_TEXINFO], 0, 0, projection
        )
        parsed = bsp.BSP29(original.write([
            original.lumps[i] if i != bsp.LUMP_TEXINFO else new_ti
            for i in range(15)
        ]))
        texinfo = parsed.texinfos()[index]
        self.assertEqual(tuple(texinfo[:8]), projection)
        self.assertEqual(texinfo[8], 0)
        self.assertEqual(texinfo[9], 0)


    def test_replace_face_lightofs(self):
        original = make_test_bsp()
        changed = bsp.replace_face_lightofs(original.lumps[bsp.LUMP_FACES], 0, 1234)
        self.assertEqual(bsp.BSP29(original.write([
            changed if index == bsp.LUMP_FACES else lump
            for index, lump in enumerate(original.lumps)
        ])).faces()[0][9], 1234)

    def test_replace_face_lightofs_rejects_invalid_offset(self):
        original = make_test_bsp()
        with self.assertRaises(bsp.BSPError):
            bsp.replace_face_lightofs(original.lumps[bsp.LUMP_FACES], 0, 0x80000000)

    def test_rejects_non_bsp29(self):
        with self.assertRaises(bsp.BSPError):
            bsp.BSP29(b'BSP2' + b'\0' * 120)

    def test_qlit_v1_parse_and_build(self):
        rgb = bytes((10, 20, 30, 40, 50, 60))
        encoded = bsp.build_lit_file(rgb)
        self.assertEqual(encoded[:4], b"QLIT")
        self.assertEqual(bsp.parse_lit_file(encoded, 2), rgb)
        self.assertIsNone(bsp.parse_lit_file(encoded, 3))
        self.assertIsNone(bsp.parse_lit_file(b"BAD!" + encoded[4:], 2))


    def test_external_miptex_header_is_preserved(self):
        header = struct.pack('<16s6I', b'EXTERNAL\0', 64, 64, 0, 0, 0, 0)
        lump = bsp.build_texture_lump([bsp.MipTexture(header, 'EXTERNAL', 64, 64)])
        wrapper = make_test_bsp()
        lumps = list(wrapper.lumps)
        lumps[bsp.LUMP_TEXTURES] = lump
        reparsed = bsp.BSP29(wrapper.write(lumps))
        entry = reparsed.miptextures()[0]
        self.assertEqual(entry.name, 'EXTERNAL')
        self.assertEqual((entry.width, entry.height), (64, 64))
        self.assertEqual(len(entry.blob), 40)
        self.assertEqual(bsp.build_texture_lump([entry]), lump)

    def test_read_wad2_texture(self):
        levels = [bytes([7]) * 256, bytes([7]) * 64, bytes([7]) * 16, bytes([7]) * 4]
        mip = bsp.build_miptex_blob('WALL01', 16, 16, levels)
        with tempfile.TemporaryDirectory() as td:
            wad_path = os.path.join(td, 'test.wad')
            directory_offset = 12 + len(mip)
            directory_entry = struct.pack('<iiiBB2x16s', 12, len(mip), len(mip), 68, 0, b'WALL01')
            with open(wad_path, 'wb') as f:
                f.write(b'WAD2' + struct.pack('<ii', 1, directory_offset) + mip + directory_entry)
            found = bsp.read_wad2_textures(wad_path)
            self.assertIn('wall01', found)
            self.assertEqual(found['wall01'].name, 'WALL01')
            self.assertEqual((found['wall01'].width, found['wall01'].height), (16, 16))

    def test_extract_worldspawn_wad_names(self):
        entities = (b'{\n"classname" "worldspawn"\n"wad" "a.wad;b.wad"\n}\n\0')
        self.assertEqual(bsp.worldspawn_wad_names(entities), ['a.wad', 'b.wad'])


    def test_bspx_rgb_lighting_round_trip_and_preserve_unknown_lump(self):
        original = make_test_bsp()
        rgb = bytes((10, 20, 30, 40, 50, 60, 70, 80, 90))
        encoded = original.write(bspx_lumps={"RGBLIGHTING": rgb, "FUTURE_DATA": b"keep-me"})
        parsed = bsp.BSP29(encoded)
        self.assertEqual(parsed.bspx_lumps["RGBLIGHTING"], rgb)
        self.assertEqual(parsed.bspx_lumps["FUTURE_DATA"], b"keep-me")
        changed_lumps = list(parsed.lumps)
        changed_lumps[bsp.LUMP_LIGHTING] = b"\x10"
        rebuilt = parsed.write(changed_lumps)
        reparsed = bsp.BSP29(rebuilt)
        self.assertEqual(reparsed.bspx_lumps["RGBLIGHTING"], rgb)
        self.assertEqual(reparsed.bspx_lumps["FUTURE_DATA"], b"keep-me")
        self.assertEqual(reparsed.lumps[bsp.LUMP_LIGHTING], b"\x10")

    def test_rgb_lighting_resolution_prefers_bspx_and_validates_count(self):
        rgb = bytes((1, 2, 3, 4, 5, 6))
        resolved, source = bsp.resolve_rgb_lighting({"RGBLIGHTING": rgb}, b"\x00\x00")
        self.assertEqual(resolved, rgb)
        self.assertEqual(source, "BSPX RGBLIGHTING")
        resolved, source = bsp.resolve_rgb_lighting({"RGBLIGHTING": rgb}, b"\x00")
        self.assertIsNone(resolved)
        self.assertEqual(source, "Monochrome BSP lighting")

    def test_rgb_lighting_falls_back_to_valid_qlit_sidecar(self):
        rgb = bytes((11, 22, 33, 44, 55, 66))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "map.lit")
            with open(path, "wb") as handle:
                handle.write(bsp.build_lit_file(rgb))
            resolved, source = bsp.resolve_rgb_lighting({}, b"\x00\x00", path)
        self.assertEqual(resolved, rgb)
        self.assertEqual(source, "QLIT v1 .lit sidecar")

    def test_rgb_lighting_without_mono_lump_synthesizes_luminance(self):
        rgb = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255))
        mono = bsp.rgb_lighting_to_luminance(rgb)
        self.assertEqual(len(mono), 3)
        self.assertEqual(mono[0], 54)
        self.assertEqual(mono[1], 182)
        self.assertEqual(mono[2], 18)

    def test_entity_parser_extracts_spawn_and_colored_light(self):
        lump = (b'{"classname" "worldspawn"}\n'
                b'{"classname" "info_player_start" "origin" "64 128 24" "angle" "90"}\n'
                b'{"classname" "light" "origin" "32 48 80" "_color" "255 32 16" "light" "240"}\n\0')
        entities = bsp.parse_entities_lump(lump)
        self.assertEqual(entities[1]["origin"], "64 128 24")
        self.assertEqual(entities[2]["_color"], "255 32 16")
        self.assertEqual(entities[2]["light"], "240")

    def test_palette_load_from_pak(self):
        palette = bytes((i % 256 for i in range(768)))
        pak_path = None
        with tempfile.TemporaryDirectory() as td:
            payload = palette
            entry_name = b"gfx/palette.lmp\0".ljust(56, b"\0")
            entry = entry_name + struct.pack('<ii', 12, len(palette))
            directory_offset = 12 + len(palette)
            pak = b"PACK" + struct.pack('<ii', directory_offset, len(entry)) + payload + entry
            pak_path = os.path.join(td, 'pak0.pak')
            with open(pak_path, 'wb') as f:
                f.write(pak)
            found, origin = bsp.find_quake_palette(td)
            self.assertEqual(found, palette)
            self.assertIn('palette.lmp', origin)



class FaceWindingTests(unittest.TestCase):
    def test_face_winding_respects_bsp_plane_and_side(self):
        vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        self.assertFalse(bsp.face_winding_needs_reversal(vertices, (0, 0, 1), side=0))
        self.assertTrue(bsp.face_winding_needs_reversal(vertices, (0, 0, 1), side=1))
        reversed_vertices = list(reversed(vertices))
        self.assertTrue(bsp.face_winding_needs_reversal(reversed_vertices, (0, 0, 1), side=0))
        self.assertFalse(bsp.face_winding_needs_reversal(reversed_vertices, (0, 0, 1), side=1))

    def test_face_winding_accounts_for_z_reflection(self):
        vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        self.assertTrue(bsp.face_winding_needs_reversal(vertices, (0, 0, 1), side=0, flip_z=True))
        self.assertFalse(bsp.face_winding_needs_reversal(vertices, (0, 0, 1), side=1, flip_z=True))
        reversed_vertices = list(reversed(vertices))
        self.assertFalse(bsp.face_winding_needs_reversal(
            reversed_vertices, (0, 0, 1), side=0, flip_z=True
        ))

    def test_degenerate_face_does_not_request_arbitrary_reversal(self):
        self.assertFalse(bsp.face_winding_needs_reversal(
            [(0, 0, 0), (1, 0, 0), (2, 0, 0)], (0, 0, 1)
        ))


if __name__ == '__main__':
    unittest.main(verbosity=2)


class InlineBrushModelTests(unittest.TestCase):
    def test_models_parse_face_ranges_and_face_ownership(self):
        parsed = make_test_bsp()
        face = parsed.lumps[bsp.LUMP_FACES]
        model0 = struct.pack(
            '<9f7i', 0, 0, 0, 64, 64, 64, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 1
        )
        model1 = struct.pack(
            '<9f7i', -16, -16, -16, 16, 16, 16, 0, 0, 0,
            0, 0, 0, 0, 0, 1, 1
        )
        lumps = list(parsed.lumps)
        lumps[bsp.LUMP_FACES] = face + face
        lumps[bsp.LUMP_MODELS] = model0 + model1
        rebuilt = bsp.BSP29(parsed.write(lumps))
        self.assertEqual(len(rebuilt.models()), 2)
        self.assertEqual(rebuilt.face_model_ids(), [0, 1])

    def test_model_face_range_rejects_out_of_bounds(self):
        parsed = make_test_bsp()
        bad_model = struct.pack(
            '<9f7i', 0, 0, 0, 64, 64, 64, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 2
        )
        lumps = list(parsed.lumps)
        lumps[bsp.LUMP_MODELS] = bad_model
        rebuilt = bsp.BSP29(parsed.write(lumps))
        with self.assertRaises(bsp.BSPError):
            rebuilt.face_model_ids()

    def test_inline_model_entity_references(self):
        entities = [
            {'classname': 'worldspawn', 'model': '*0'},
            {'classname': 'func_door', 'model': '*1'},
            {'classname': 'func_plat', 'model': '*2'},
            {'classname': 'light', 'model': '*3'},
            {'classname': 'func_train', 'model': 'not-an-inline-model'},
        ]
        self.assertEqual(
            bsp.parse_inline_model_references(entities, 3),
            [(1, 1), (2, 2)]
        )

    def test_inline_model_origin_and_yaw_transform(self):
        point = bsp.transform_inline_model_position(
            (10, 0, 0), {'origin': '100 200 300', 'angles': '0 90 0'}
        )
        for actual, expected in zip(point, (100, 210, 300)):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_inline_model_rotation_and_origin_defaults(self):
        self.assertEqual(
            bsp.transform_inline_model_position((1, 2, 3), {}),
            (1.0, 2.0, 3.0)
        )
        point = bsp.transform_inline_model_position(
            (0, 1, 0), {'origin': '5 6 7', 'angles': '0 0 90'}
        )
        for actual, expected in zip(point, (5, 6, 8)):
            self.assertAlmostEqual(actual, expected, places=6)


    def test_inline_model_scalar_angle_is_mover_travel_not_orientation(self):
        point = bsp.transform_inline_model_position(
            (10, 0, 0), {'origin': '0 0 0', 'angle': '90'}
        )
        for actual, expected in zip(point, (10, 0, 0)):
            self.assertAlmostEqual(actual, expected, places=6)


