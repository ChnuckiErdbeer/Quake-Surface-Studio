import math
import os
import struct
import tempfile
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import bsp
import export_validation
import lightmap_export
import lighting as lighting_utils
import qss_export_check


def make_test_bsp(lightmapped=False):
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
    lumps[bsp.LUMP_EDGES] = b''.join([
        struct.pack('<2H', 0, 0),
        struct.pack('<2H', 0, 1),
        struct.pack('<2H', 1, 2),
        struct.pack('<2H', 2, 0),
    ])
    lumps[bsp.LUMP_SURFEDGES] = struct.pack('<3i', 1, 2, 3)
    if lightmapped:
        lumps[bsp.LUMP_FACES] = struct.pack(
            '<Hhihh4Bi', 0, 0, 0, 3, 0, 0, 255, 255, 255, 0
        )
        lumps[bsp.LUMP_LIGHTING] = bytes(range(25))
    else:
        lumps[bsp.LUMP_FACES] = struct.pack(
            '<Hhihh4Bi', 0, 0, 0, 3, 0, 255, 255, 255, 255, -1
        )
    lumps[bsp.LUMP_MODELS] = struct.pack(
        '<9f7i', 0, 0, 0, 64, 64, 64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1
    )
    header = bsp.BSP_VERSION.to_bytes(4, 'little', signed=True) + b'\0' * 120
    return bsp.BSP29(bsp.BSP29(header).write(lumps))


class ExportValidationTests(unittest.TestCase):
    def test_compiler_generated_test02_export_round_trip(self):
        fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'mapandbsp'))
        source_path = os.path.join(fixture_dir, 'test02_compile.bsp')
        lit_path = os.path.join(fixture_dir, 'test02_compile.lit')
        if not (os.path.isfile(source_path) and os.path.isfile(lit_path)):
            self.skipTest("Compiler-generated test02 BSP/.lit fixtures are not present")

        with open(source_path, 'rb') as handle:
            source_data = handle.read()
        with open(lit_path, 'rb') as handle:
            source_lit = handle.read()
        source = bsp.BSP29(source_data)
        source_rgb = bsp.parse_lit_file(source_lit, len(source.lumps[bsp.LUMP_LIGHTING]))
        self.assertIsNotNone(source_rgb, "The checked-in compiler .lit must match the BSP LIGHTING sample count")

        # Simulate a valid RGB-lightmap edit while retaining the original
        # classic BSP offsets, geometry, textures and unrelated BSPX records.
        edited_rgb = bytes((value ^ 1) for value in source_rgb)
        lumps = list(source.lumps)
        bspx_lumps = dict(source.bspx_lumps)
        bspx_lumps['RGBLIGHTING'] = edited_rgb
        exported_data = source.write(lumps, bspx_lumps)
        report = export_validation.validate_export_bytes(
            source_data, exported_data, bsp.build_lit_file(edited_rgb)
        )
        self.assertEqual(report['faces'], len(source.faces()))
        self.assertLessEqual(report['classic_required_samples'], len(source.lumps[bsp.LUMP_LIGHTING]))
        self.assertTrue(report['external_lit'])

    def test_compiler_fixture_accepts_appended_lms_hift_payload(self):
        fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'mapandbsp'))
        source_path = os.path.join(fixture_dir, 'test02_compile.bsp')
        lit_path = os.path.join(fixture_dir, 'test02_compile.lit')
        if not (os.path.isfile(source_path) and os.path.isfile(lit_path)):
            self.skipTest("Compiler-generated test02 BSP/.lit fixtures are not present")
        with open(source_path, 'rb') as handle:
            source_data = handle.read()
        with open(lit_path, 'rb') as handle:
            lit_data = handle.read()
        parsed = bsp.BSP29(source_data)
        source_lighting = parsed.lumps[bsp.LUMP_LIGHTING]
        source_rgb = bsp.parse_lit_file(lit_data, len(source_lighting))
        self.assertIsNotNone(source_rgb)

        vertices = parsed.vertices()
        texinfos = parsed.texinfos()
        face_records = {}
        for face_id, face in enumerate(parsed.faces()):
            if face[9] < 0 or face[5] == 255:
                continue
            vertex_ids = parsed.face_vertex_indices(face)
            positions = [vertices[index] for index in vertex_ids]
            texinfo = texinfos[face[4]]
            s_values = [
                p[0] * texinfo[0] + p[1] * texinfo[1] + p[2] * texinfo[2] + texinfo[3]
                for p in positions
            ]
            t_values = [
                p[0] * texinfo[4] + p[1] * texinfo[5] + p[2] * texinfo[6] + texinfo[7]
                for p in positions
            ]
            base_s_min = int(math.floor(min(s_values) / 16.0 + 1e-7)) * 16
            base_t_min = int(__import__('math').floor(min(t_values) / 16.0 + 1e-7)) * 16
            base_width, base_height = export_validation._face_lightmap_dimensions(parsed, face, 16)
            block_size = base_width * base_height
            styles = [style for style in face[5:9] if style != 255]
            combined = lighting_utils.combine_style_samples(
                source_lighting, source_rgb, face[9], block_size, styles
            )
            shift, s_min, t_min, width, height = lightmap_export.choose_luxel_grid(
                s_values, t_values, 2
            )
            rgb = bytearray()
            for sy in range(height):
                v = (t_min + sy * (1 << shift) - base_t_min) / 16.0
                y0 = max(0, min(base_height - 1, int(__import__('math').floor(v))))
                y1 = min(base_height - 1, y0 + 1)
                fy = min(1.0, max(0.0, v - y0))
                for sx in range(width):
                    u = (s_min + sx * (1 << shift) - base_s_min) / 16.0
                    x0 = max(0, min(base_width - 1, int(__import__('math').floor(u))))
                    x1 = min(base_width - 1, x0 + 1)
                    fx = min(1.0, max(0.0, u - x0))
                    for channel in range(3):
                        c00 = combined[y0 * base_width + x0][channel]
                        c10 = combined[y0 * base_width + x1][channel]
                        c01 = combined[y1 * base_width + x0][channel]
                        c11 = combined[y1 * base_width + x1][channel]
                        top = c00 * (1.0 - fx) + c10 * fx
                        bottom = c01 * (1.0 - fx) + c11 * fx
                        rgb.append(max(0, min(255, int(round(top * (1.0 - fy) + bottom * fy)))))
            face_records[face_id] = {
                'shift': shift, 'width': width, 'height': height, 'rgb': bytes(rgb)
            }

        extension = lightmap_export.build_lightmap_extension_data(
            len(parsed.faces()), face_records, len(source_lighting)
        )
        output_lumps = list(parsed.lumps)
        output_lumps[bsp.LUMP_LIGHTING] = source_lighting + extension['LIGHTING_APPEND']
        output_bspx = dict(parsed.bspx_lumps)
        output_bspx.update({
            'LMSHIFT': extension['LMSHIFT'],
            'LMOFFSET': extension['LMOFFSET'],
            'LMSTYLE': extension['LMSTYLE'],
            'RGBLIGHTING': source_rgb + extension['RGBLIGHTING_APPEND'],
        })
        output_lit = bsp.build_lit_file(output_bspx['RGBLIGHTING'])
        report = export_validation.validate_export_bytes(
            source_data, parsed.write(output_lumps, output_bspx), output_lit
        )
        self.assertEqual(report['enhanced_lighting_samples'], extension['enhanced_sample_count'])
        self.assertGreater(report['enhanced_lighting_samples'], 0)

    def test_export_checker_cli_reads_bsp_and_auto_detects_lit(self):
        original = make_test_bsp(lightmapped=True)
        rgb = bytes((30, 60, 90)) * 25
        with tempfile.TemporaryDirectory() as td:
            source_path = os.path.join(td, 'source.bsp')
            export_path = os.path.join(td, 'edited.bsp')
            with open(source_path, 'wb') as handle:
                handle.write(original.write())
            with open(export_path, 'wb') as handle:
                handle.write(original.write())
            with open(os.path.splitext(export_path)[0] + '.lit', 'wb') as handle:
                handle.write(bsp.build_lit_file(rgb))
            self.assertEqual(qss_export_check.main([source_path, export_path]), 0)

    def test_identical_unlit_export_passes(self):
        original = make_test_bsp()
        report = export_validation.validate_export_bytes(original.write(), original.write())
        self.assertEqual(report['faces'], 1)
        self.assertEqual(report['classic_required_samples'], 0)
        self.assertIsNone(report['enhanced_lighting_samples'])

    def test_classic_lightmap_and_qlit_sidecar_pass(self):
        original = make_test_bsp(lightmapped=True)
        lit = bsp.build_lit_file(bytes((128, 96, 64)) * 25)
        report = export_validation.validate_export_bytes(original.write(), original.write(), lit)
        self.assertEqual(report['classic_required_samples'], 25)
        self.assertTrue(report['external_lit'])

    def test_enhanced_lmshift_offset_and_style_arrays_pass(self):
        original = make_test_bsp(lightmapped=True)
        # 64-qu triangle extents sampled every 8 units produce a 9x9 luxel grid.
        # The classic 25-sample area remains at the front for legacy engines;
        # enhanced samples are appended and addressed by LMOFFSET.
        enhanced_rgb = bytes((80, 80, 80)) * 25 + bytes((20, 40, 60)) * 81
        lumps = list(original.lumps)
        lumps[bsp.LUMP_LIGHTING] += bytes(81)
        encoded = original.write(lumps, bspx_lumps={
            'RGBLIGHTING': enhanced_rgb,
            'LMSHIFT': bytes([3]),
            'LMOFFSET': struct.pack('<I', 25),
            'LMSTYLE': bytes([0]),
        })
        lit = bsp.build_lit_file(bytes((100, 100, 100)) * 106)
        report = export_validation.validate_export_bytes(original.write(), encoded, lit)
        self.assertEqual(report['enhanced_lighting_samples'], 81)
        self.assertIn('LMSHIFT', report['bspx_lumps'])
        self.assertTrue(report['external_lit'])

    def test_enhanced_lightmap_rejects_truncated_rgb_data(self):
        original = make_test_bsp(lightmapped=True)
        lumps = list(original.lumps)
        lumps[bsp.LUMP_LIGHTING] += bytes(80)
        encoded = original.write(lumps, bspx_lumps={
            'RGBLIGHTING': bytes(3 * 25) + bytes(3 * 80),
            'LMSHIFT': bytes([3]),
            'LMOFFSET': struct.pack('<I', 25),
            'LMSTYLE': bytes([0]),
        })
        with self.assertRaisesRegex(bsp.BSPError, 'ends at sample 106'):
            export_validation.validate_export_bytes(original.write(), encoded)

    def test_enhanced_lmoffset_cannot_overlap_classic_samples(self):
        original = make_test_bsp(lightmapped=True)
        lumps = list(original.lumps)
        lumps[bsp.LUMP_LIGHTING] += bytes(81)
        encoded = original.write(lumps, bspx_lumps={
            'RGBLIGHTING': bytes(3 * 106),
            'LMSHIFT': bytes([3]),
            'LMOFFSET': struct.pack('<I', 0),
            'LMSTYLE': bytes([0]),
        })
        with self.assertRaisesRegex(bsp.BSPError, 'overlaps the classic sample range'):
            export_validation.validate_export_bytes(original.write(), encoded)

    def test_enhanced_lightmap_requires_per_face_arrays(self):
        original = make_test_bsp(lightmapped=True)
        lumps = list(original.lumps)
        lumps[bsp.LUMP_LIGHTING] += bytes(81)
        encoded = original.write(lumps, bspx_lumps={
            'RGBLIGHTING': bytes(3 * 106),
            'LMSHIFT': bytes([3]),
            'LMOFFSET': struct.pack('<I', 25),
        })
        with self.assertRaisesRegex(bsp.BSPError, 'LMSTYLE'):
            export_validation.validate_export_bytes(original.write(), encoded)

    def test_unknown_bspx_data_must_survive_export(self):
        original = make_test_bsp()
        source = original.write(bspx_lumps={'FUTURE_DATA': b'preserve-me'})
        changed = bsp.BSP29(source).write(bspx_lumps={})
        with self.assertRaisesRegex(bsp.BSPError, 'FUTURE_DATA'):
            export_validation.validate_export_bytes(source, changed)

    def test_entity_changes_are_rejected(self):
        original = make_test_bsp()
        lumps = list(original.lumps)
        lumps[bsp.LUMP_ENTITIES] = b'{"classname" "worldspawn" "message" "changed"}\0'
        changed = original.write(lumps)
        with self.assertRaisesRegex(bsp.BSPError, 'lump 0 changed'):
            export_validation.validate_export_bytes(original.write(), changed)

    def test_invalid_face_texture_reference_is_rejected(self):
        original = make_test_bsp()
        texinfo = struct.pack('<8fii', 1, 0, 0, 0, 0, 1, 0, 0, 999, 0)
        lumps = list(original.lumps)
        lumps[bsp.LUMP_TEXINFO] = lumps[bsp.LUMP_TEXINFO] + texinfo
        lumps[bsp.LUMP_FACES] = bsp.replace_face_texinfo(
            lumps[bsp.LUMP_FACES], 0, 1
        )
        changed = original.write(lumps)
        with self.assertRaisesRegex(bsp.BSPError, 'invalid texture 999'):
            export_validation.validate_export_bytes(original.write(), changed)

    def test_classic_rgb_lightmap_must_match_monochrome_sample_count(self):
        original = make_test_bsp(lightmapped=True)
        encoded = original.write(bspx_lumps={'RGBLIGHTING': bytes(3 * 24)})
        with self.assertRaisesRegex(bsp.BSPError, 'one RGB triplet per'):
            export_validation.validate_export_bytes(original.write(), encoded)

    def test_classic_lightmap_truncation_is_rejected(self):
        original = make_test_bsp(lightmapped=True)
        lumps = list(original.lumps)
        lumps[bsp.LUMP_LIGHTING] = bytes(24)
        changed = original.write(lumps)
        with self.assertRaisesRegex(bsp.BSPError, 'require at least 25'):
            export_validation.validate_export_bytes(original.write(), changed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
