import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import bsp
import export_validation


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
        self.assertEqual(report['classic_required_samples'], len(source.lumps[bsp.LUMP_LIGHTING]))
        self.assertTrue(report['external_lit'])

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
