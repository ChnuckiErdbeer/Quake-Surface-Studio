import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import lightmap_export


class LightmapExportTests(unittest.TestCase):
    def test_resolution_selects_expected_lmshift(self):
        expected = {1: 4, 2: 3, 4: 2, 8: 1}
        for resolution, shift in expected.items():
            with self.subTest(resolution=resolution):
                result = lightmap_export.choose_luxel_grid(
                    [0, 64], [0, 64], resolution
                )
                self.assertEqual(result[0], shift)
                self.assertEqual(result[3:], (64 // (1 << shift) + 1,) * 2)

    def test_oversized_face_coarsens_to_engine_limit(self):
        shift, s_min, t_min, width, height = lightmap_export.choose_luxel_grid(
            [0, 2048], [0, 1024], 8
        )
        self.assertGreaterEqual(shift, 4)
        self.assertLessEqual(width, 256)
        self.assertLessEqual(height, 256)

    def test_fails_when_face_exceeds_limit_even_at_classic_spacing(self):
        with self.assertRaisesRegex(ValueError, 'even at 16 units per luxel'):
            lightmap_export.choose_luxel_grid([0, 8192], [0, 8192], 8)

    def test_bilinear_sampler_interpolates_four_pixels(self):
        pixels = (
            0.0, 0.0, 0.0, 1.0,
            1.0, 0.0, 0.0, 1.0,
            0.0, 1.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        )
        sampled = lightmap_export.bilinear_sample_rgba(pixels, 2, 2, 0.5, 0.5)
        self.assertEqual(sampled, (0.5, 0.5, 0.25, 1.0))

    def test_face_atlas_sampling_converts_linear_rgb_to_bytes(self):
        pixels = (0.5, 0.25, 1.0, 1.0) * 16
        sampled = lightmap_export.sample_face_rgb_from_atlas(
            pixels, image_size=4, working_resolution=1,
            atlas_x=0, atlas_y=0, gutter=0, pixels_per_luxel=1,
            base_s_min=0, base_t_min=0, s_min=0, t_min=0,
            sample_width=1, sample_height=1, spacing=16,
        )
        self.assertEqual(sampled, bytes((128, 64, 255)))

    def test_builds_face_ordered_extension_with_classic_prefix_offsets(self):
        records = {
            0: {"shift": 3, "width": 2, "height": 1, "rgb": bytes((255, 0, 0, 0, 255, 0))},
            2: {"shift": 2, "width": 1, "height": 2, "rgb": bytes((0, 0, 255, 255, 255, 255))},
        }
        result = lightmap_export.build_lightmap_extension_data(3, records, base_sample_count=10)
        self.assertEqual(result["LMSHIFT"], bytes((3, 4, 2)))
        self.assertEqual(result["LMSTYLE"], bytes((0, 255, 0)))
        self.assertEqual(
            result["LMOFFSET"],
            b"".join((int(10).to_bytes(4, "little"), int(0xFFFFFFFF).to_bytes(4, "little"),
                      int(12).to_bytes(4, "little")))
        )
        self.assertEqual(result["RGBLIGHTING_APPEND"], records[0]["rgb"] + records[2]["rgb"])
        self.assertEqual(result["LIGHTING_APPEND"], bytes((54, 182, 18, 255)))
        self.assertEqual(result["enhanced_sample_count"], 4)


    def test_arbitrary_coordinate_sampler_matches_classic_grid_centres(self):
        pixels = []
        for y in range(4):
            for x in range(4):
                pixels.extend((x / 3.0, y / 3.0, 0.5, 1.0))
        sampled = lightmap_export.sample_face_rgb_at_coordinates(
            pixels, image_size=4, working_resolution=1,
            atlas_x=0, atlas_y=0, gutter=0, pixels_per_luxel=1,
            base_s_min=0, base_t_min=0,
            s_coordinates=(0, 16), t_coordinates=(0, 16),
        )
        self.assertEqual(len(sampled), 12)
        self.assertEqual(sampled[0:3], bytes((0, 255, 128)))
        self.assertEqual(sampled[9:12], bytes((85, 170, 128)))

    def test_arbitrary_coordinate_sampler_rejects_non_finite_coordinates(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            lightmap_export.sample_face_rgb_at_coordinates(
                [0.0, 0.0, 0.0, 1.0] * 4, 2, 1, 0, 0, 0, 1,
                0, 0, (float("nan"),), (0,),
            )


    def test_builds_decoupled_lightmap_records_with_independent_axes(self):
        faces = [
            (0, 0, 0, 3, 0, 0, 255, 255, 255, 0),
            (0, 0, 0, 3, 0, 255, 255, 255, 255, -1),
        ]
        texinfos = [(2.0, 0.0, 0.0, 8.0, 0.0, 4.0, 0.0, 16.0, 0, 0)]
        records = {0: {
            "shift": 3, "width": 3, "height": 2,
            "s_min": 8, "t_min": 16, "rgb": bytes(18),
        }}
        offsets = (100).to_bytes(4, "little") + (0xFFFFFFFF).to_bytes(4, "little")
        data = lightmap_export.build_decoupled_lightmap_data(faces, texinfos, records, offsets)
        self.assertEqual(len(data), 40 * 2)
        first = __import__("struct").unpack_from("<HHI8f", data, 0)
        self.assertEqual(first[:3], (3, 2, 100))
        self.assertEqual(first[3:], (0.25, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0))
        second = __import__("struct").unpack_from("<HHI8f", data, 40)
        self.assertEqual(second[:3], (0, 0, 0xFFFFFFFF))
        self.assertEqual(second[3:], (0.0,) * 8)

    def test_decoupled_builder_rejects_missing_offsets(self):
        with self.assertRaisesRegex(ValueError, "one uint32"):
            lightmap_export.build_decoupled_lightmap_data(
                [(0, 0, 0, 3, 0, 0, 255, 255, 255, 0)],
                [(1, 0, 0, 0, 0, 1, 0, 0, 0, 0)],
                {}, b"",
            )

    def test_rejects_invalid_face_sample_buffer(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            lightmap_export.build_lightmap_extension_data(
                1, {0: {"shift": 3, "width": 2, "height": 2, "rgb": bytes(3)}}, 0
            )

    def test_rejects_invalid_resolution_and_shift(self):
        with self.assertRaises(ValueError):
            lightmap_export.choose_luxel_grid([0, 64], [0, 64], 3)
        with self.assertRaisesRegex(ValueError, 'invalid LMSHIFT'):
            lightmap_export.build_lightmap_extension_data(
                1, {0: {"shift": 5, "width": 1, "height": 1, "rgb": bytes(3)}}, 0
            )


    def test_half_luxel_edge_padding_adds_resampled_rim(self):
        source = bytes(
            channel
            for value in (0, 100, 200, 255)
            for channel in (value, value, value)
        )
        record = {"shift": 4, "width": 2, "height": 2, "s_min": 0, "t_min": 16, "rgb": source}

        padded, did_pad = lightmap_export.add_half_luxel_edge_padding(record)

        self.assertTrue(did_pad)
        self.assertEqual((padded["width"], padded["height"]), (3, 3))
        self.assertEqual(len(padded["rgb"]), 3 * 3 * 3)
        red = list(padded["rgb"][0::3])
        self.assertEqual(red, [
            0, 50, 100,
            100, 139, 178,
            200, 228, 255,
        ])
        self.assertEqual((padded["s_min"], padded["t_min"]), (-8.0, 8.0))
        self.assertEqual(record["rgb"], source)

    def test_half_luxel_edge_padding_offsets_explicit_decoupled_vectors(self):
        record = {
            "shift": 4, "width": 2, "height": 1,
            "lmvecs": (1.0, 0.0, 0.0, -4.0, 0.0, 1.0, 0.0, 8.0),
            "rgb": bytes((10, 20, 30, 40, 50, 60)),
        }
        padded, did_pad = lightmap_export.add_half_luxel_edge_padding(record)
        self.assertTrue(did_pad)
        self.assertEqual((padded["width"], padded["height"]), (3, 2))
        self.assertEqual(padded["lmvecs"], (1.0, 0.0, 0.0, -3.5, 0.0, 1.0, 0.0, 8.5))

    def test_half_luxel_edge_padding_offsets_classic_luxel_grid_origin(self):
        faces = [(0, 0, 0, 3, 0, 0, 255, 255, 255, 0)]
        texinfos = [(2.0, 0.0, 0.0, 8.0, 0.0, 4.0, 0.0, 16.0, 0, 0)]
        record = {
            "shift": 3, "width": 2, "height": 1,
            "s_min": 16, "t_min": 32, "rgb": bytes(6),
        }
        padded, did_pad = lightmap_export.add_half_luxel_edge_padding(record)
        self.assertTrue(did_pad)
        self.assertEqual((padded["s_min"], padded["t_min"]), (12.0, 28.0))
        offsets = (100).to_bytes(4, "little")
        data = lightmap_export.build_decoupled_lightmap_data(
            faces, texinfos, {0: padded}, offsets
        )
        values = struct.unpack_from("<HHI8f", data, 0)
        self.assertEqual(values[:3], (3, 2, 100))
        self.assertAlmostEqual(values[3], 0.25)
        self.assertAlmostEqual(values[6], -0.5)
        self.assertAlmostEqual(values[10], -1.5)

    def test_half_luxel_edge_padding_skips_dimensions_over_engine_limit(self):
        record = {
            "shift": 4, "width": 256, "height": 1,
            "s_min": 0, "t_min": 0, "rgb": bytes(256 * 3),
        }
        padded, did_pad = lightmap_export.add_half_luxel_edge_padding(record)
        self.assertFalse(did_pad)
        self.assertEqual(padded, record)

    def test_half_luxel_edge_padding_rejects_invalid_rgb_length(self):
        with self.assertRaisesRegex(ValueError, "needs 6"):
            lightmap_export.add_half_luxel_edge_padding({
                "shift": 4, "width": 2, "height": 1,
                "s_min": 0, "t_min": 0, "rgb": bytes(3),
            })



class CoplanarEdgeStitchTests(unittest.TestCase):
    def setUp(self):
        # Two adjacent 16x32 coplanar faces. Edge 1 is shared; its only
        # interior 16-unit luxel lies at world position (16, 16, 0).
        self.faces = [
            (0, 0, 0, 4, 0, 0, 255, 255, 255, 0),
            (0, 0, 4, 4, 0, 0, 255, 255, 255, 6),
        ]
        self.texinfos = [
            (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0, 0)
        ]
        self.vertices = [
            (0.0, 0.0, 0.0),
            (16.0, 0.0, 0.0),
            (16.0, 32.0, 0.0),
            (0.0, 32.0, 0.0),
            (32.0, 0.0, 0.0),
            (32.0, 32.0, 0.0),
        ]
        self.edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (1, 4), (4, 5), (5, 2),
        ]
        self.surfedges = [0, 1, 2, 3, 4, 5, 6, -1]
        self.planes = [(0.0, 0.0, 1.0, 0.0, 2)]
        self.model_ids = [0, 0]
        self.lighting = bytearray(12)
        self.lit_rgb = bytearray(12 * 3)
        self.lighting[3] = 20
        self.lighting[8] = 60
        self.lit_rgb[9:12] = bytes((20, 20, 20))
        self.lit_rgb[24:27] = bytes((60, 60, 60))

    def _stitch(self):
        return lightmap_export.stitch_coplanar_edge_samples(
            self.faces, self.texinfos, self.vertices, self.edges,
            self.surfedges, self.planes, self.model_ids,
            self.lighting, self.lit_rgb,
        )

    def test_shared_coplanar_edge_samples_are_averaged_without_blurring_faces(self):
        result = self._stitch()
        self.assertEqual(result["shared_coplanar_edges"], 1)
        self.assertEqual(result["matched_sample_pairs"], 1)
        self.assertEqual(result["changed_sample_pairs"], 1)
        self.assertEqual(self.lighting[3], 40)
        self.assertEqual(self.lighting[8], 40)
        self.assertEqual(self.lit_rgb[9:12], bytes((40, 40, 40)))
        self.assertEqual(self.lit_rgb[24:27], bytes((40, 40, 40)))
        self.assertEqual(self.lighting[2], 0)
        self.assertEqual(self.lighting[9], 0)

    def test_does_not_stitch_non_coplanar_faces(self):
        planes = list(self.planes)
        planes.append((0.0, 1.0, 0.0, 0.0, 1))
        faces = list(self.faces)
        faces[1] = (1, 0, 4, 4, 0, 0, 255, 255, 255, 6)
        result = lightmap_export.stitch_coplanar_edge_samples(
            faces, self.texinfos, self.vertices, self.edges, self.surfedges,
            planes, self.model_ids, self.lighting, self.lit_rgb,
        )
        self.assertEqual(result["matched_sample_pairs"], 0)
        self.assertEqual(self.lighting[3], 20)
        self.assertEqual(self.lighting[8], 60)

    def test_does_not_stitch_faces_with_different_styles_or_models(self):
        styled = list(self.faces)
        styled[1] = (0, 0, 4, 4, 0, 32, 255, 255, 255, 6)
        result = lightmap_export.stitch_coplanar_edge_samples(
            styled, self.texinfos, self.vertices, self.edges, self.surfedges,
            self.planes, self.model_ids, self.lighting, self.lit_rgb,
        )
        self.assertEqual(result["matched_sample_pairs"], 0)
        result = lightmap_export.stitch_coplanar_edge_samples(
            self.faces, self.texinfos, self.vertices, self.edges, self.surfedges,
            self.planes, [0, 1], self.lighting, self.lit_rgb,
        )
        self.assertEqual(result["matched_sample_pairs"], 0)

    def test_does_not_interpolate_when_classic_luxel_grids_do_not_align(self):
        shifted_texinfos = [
            self.texinfos[0],
            (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 8.0, 0, 0),
        ]
        faces = [
            self.faces[0],
            (0, 0, 4, 4, 1, 0, 255, 255, 255, 6),
        ]
        result = lightmap_export.stitch_coplanar_edge_samples(
            faces, shifted_texinfos, self.vertices, self.edges, self.surfedges,
            self.planes, self.model_ids, self.lighting, self.lit_rgb,
        )
        self.assertEqual(result["matched_sample_pairs"], 0)
        self.assertEqual(self.lighting[3], 20)
        self.assertEqual(self.lighting[8], 60)


class WorldAlignedLightmapChartTests(unittest.TestCase):
    def setUp(self):
        self.faces = [
            (0, 0, 0, 4, 0, 0, 255, 255, 255, 0),
            (0, 0, 4, 4, 0, 0, 255, 255, 255, 4),
        ]
        self.planes = [(0.0, 0.0, 1.0, 0.0, 2)]
        self.vertices = [
            (0.0, 0.0, 0.0), (16.0, 0.0, 0.0),
            (16.0, 16.0, 0.0), (0.0, 16.0, 0.0),
            (32.0, 0.0, 0.0), (32.0, 16.0, 0.0),
        ]
        self.edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (1, 4), (4, 5), (5, 2),
        ]
        self.surfedges = [0, 1, 2, 3, 4, 5, 6, -1]
        self.texinfo = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0, 0)
        self.records = [
            {
                "face_id": 0, "positions": self.vertices[:4],
                "styles": (0, 255, 255, 255), "texinfo": self.texinfo,
                "s_min": 0, "t_min": 0, "width": 2, "height": 2,
                "samples_rgb": [(20, 20, 20)] * 4,
            },
            {
                "face_id": 1, "positions": [
                    self.vertices[1], self.vertices[4],
                    self.vertices[5], self.vertices[2],
                ],
                "styles": (0, 255, 255, 255), "texinfo": self.texinfo,
                "s_min": 16, "t_min": 0, "width": 2, "height": 2,
                "samples_rgb": [(60, 60, 60)] * 4,
            },
        ]

    def test_world_plane_frame_uses_world_xy_for_horizontal_surface(self):
        frame = lightmap_export.world_plane_frame(self.planes[0], 0)
        self.assertEqual(frame["normal"], (0.0, 0.0, 1.0))
        self.assertEqual(frame["axis_s"], (1.0, 0.0, 0.0))
        self.assertEqual(frame["axis_t"], (0.0, 1.0, 0.0))
        flipped = lightmap_export.world_plane_frame(self.planes[0], 1)
        self.assertEqual(flipped["axis_s"], frame["axis_s"])
        self.assertEqual(flipped["axis_t"], frame["axis_t"])

    def test_adjacent_faces_share_one_world_anchored_chart(self):
        charts, face_to_chart, _records = lightmap_export.build_coplanar_face_charts(
            self.records, self.faces, self.planes, self.edges, self.surfedges, [0, 0]
        )
        self.assertEqual(len(charts), 1)
        chart = charts[0]
        self.assertEqual(chart["face_ids"], (0, 1))
        self.assertEqual((chart["s_min"], chart["t_min"]), (0.0, 0.0))
        self.assertEqual((chart["width"], chart["height"]), (3, 2))
        self.assertEqual(face_to_chart[0], face_to_chart[1])

    def test_shared_edge_source_samples_become_one_averaged_chart_luxel(self):
        charts, _face_to_chart, records = lightmap_export.build_coplanar_face_charts(
            self.records, self.faces, self.planes, self.edges, self.surfedges, [0, 0]
        )
        samples, valid = lightmap_export.resample_coplanar_chart_sources(charts[0], records)
        self.assertEqual(len(samples), 6)
        self.assertEqual(samples[1], (40, 40, 40))
        self.assertEqual(samples[4], (40, 40, 40))
        self.assertEqual(samples[0], (20, 20, 20))
        self.assertEqual(samples[2], (60, 60, 60))
        self.assertEqual(valid, bytes((1, 1, 1, 1, 1, 1)))

    def test_outward_rounded_classic_luxel_column_is_filled_past_face_edge(self):
        vertices = [
            (0.0, 0.0, 0.0), (20.0, 0.0, 0.0),
            (20.0, 16.0, 0.0), (0.0, 16.0, 0.0),
        ]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
        faces = [(0, 0, 0, 4, 0, 0, 255, 255, 255, 0)]
        records = [{
            "face_id": 0,
            "positions": vertices,
            "styles": (0, 255, 255, 255),
            "texinfo": self.texinfo,
            "s_min": 0,
            "t_min": 0,
            "width": 3,
            "height": 2,
            "samples_rgb": [
                (10, 10, 10), (20, 20, 20), (30, 30, 30),
                (40, 40, 40), (50, 50, 50), (60, 60, 60),
            ],
        }]
        charts, _mapping, chart_records = lightmap_export.build_coplanar_face_charts(
            records, faces, self.planes, edges, [0, 1, 2, 3], [0]
        )
        self.assertEqual((charts[0]["width"], charts[0]["height"]), (3, 2))
        samples, valid = lightmap_export.resample_coplanar_chart_sources(
            charts[0], chart_records
        )
        # The third sample centre is x=32, beyond the 20-unit polygon edge,
        # but it is present in the classic BSP29 face lightmap rectangle.
        self.assertEqual(valid[2], 1)
        self.assertEqual(samples[2], (30, 30, 30))


    def test_world_chart_edge_support_clamps_only_within_half_cell_diagonal(self):
        root_half = 2.0 ** 0.5
        texinfo = (
            1.0 / root_half, 1.0 / root_half, 0.0, 0.0,
            -1.0 / root_half, 1.0 / root_half, 0.0, 32.0,
        )
        chart = {
            "face_ids": (0,),
            "axis_s": (1.0, 0.0, 0.0),
            "axis_t": (0.0, 1.0, 0.0),
            "normal": (0.0, 0.0, 1.0),
            "distance": 0.0,
            "s_min": 0.0,
            "t_min": 0.0,
            "width": 3,
            "height": 3,
        }
        records = {
            0: {
                "positions": (
                    (0.0, 0.0, 0.0),
                    (32.0, 0.0, 0.0),
                    (0.0, 32.0, 0.0),
                ),
                "texinfo": texinfo,
                "s_min": 0.0,
                "t_min": -32.0,
                "width": 3,
                "height": 5,
                "samples_rgb": [(77, 77, 77)] * 15,
            }
        }
        samples, valid = lightmap_export.resample_coplanar_chart_sources(
            chart, records
        )
        # (16, 32) is just outside the triangle but within half a luxel
        # diagonal. Its rotated texinfo projection exceeds the source S grid,
        # so the face's own edge sample must be clamped into the chart.
        self.assertEqual(valid[2 * 3 + 1], 1)
        self.assertEqual(samples[2 * 3 + 1], (77, 77, 77))
        # (32, 32) is farther than the support radius and must stay invalid.
        self.assertEqual(valid[2 * 3 + 2], 0)


    def test_different_models_or_styles_do_not_share_a_chart(self):
        charts, _mapping, _records = lightmap_export.build_coplanar_face_charts(
            self.records, self.faces, self.planes, self.edges, self.surfedges, [0, 1]
        )
        self.assertEqual(len(charts), 2)
        styled_records = [dict(record) for record in self.records]
        styled_records[1]["styles"] = (32, 255, 255, 255)
        charts, _mapping, _records = lightmap_export.build_coplanar_face_charts(
            styled_records, self.faces, self.planes, self.edges, self.surfedges, [0, 0]
        )
        self.assertEqual(len(charts), 2)

    def test_world_chart_coordinates_return_stable_pixel_centres(self):
        first = lightmap_export.world_chart_pixel_coordinates(
            16.0, 16.0, 10, 20, 0.0, 0.0, 2, 2, 2, 1024
        )
        self.assertAlmostEqual(first[0], 29.5)
        self.assertAlmostEqual(first[1], 973.5)


class WorldChartSamplingTests(unittest.TestCase):
    def test_float_sampling_preserves_hdr_values_while_export_stays_byte_clamped(self):
        size = 16
        pixels = [0.0] * (size * size * 4)
        for index in range(size * size):
            pixels[index * 4:index * 4 + 4] = (0.25, 1.5, 3.0, 1.0)
        args = (
            pixels, size, 1, 2, 2, 1, 1,
            (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0), 0.0,
            0.0, 0.0, 1, 1,
            (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 0.0, 0.0,
        )
        exported = lightmap_export.sample_classic_face_grid_from_world_chart(*args)
        measured = lightmap_export.sample_classic_face_grid_from_world_chart(
            *args, preserve_float=True
        )
        self.assertEqual(exported, bytes((64, 255, 255)))
        self.assertEqual(len(measured), 3)
        self.assertAlmostEqual(measured[0], 0.25)
        self.assertAlmostEqual(measured[1], 1.5)
        self.assertAlmostEqual(measured[2], 3.0)

    def test_classic_face_grid_samples_map_to_shared_world_chart_positions(self):
        # The two face-local grids use different S offsets, but the shared
        # physical point (16, 16, 0) must read the same chart pixel.
        size = 16
        pixels = [0.0] * (size * size * 4)
        for i in range(size * size):
            pixels[i * 4:i * 4 + 4] = [0.25, 0.5, 0.75, 1.0]
        first = lightmap_export.sample_rgb_from_world_chart_positions(
            pixels, size, 1, 2, 3, 1, 1,
            [(16.0, 16.0, 0.0)], (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0), 0.0, 0.0,
        )
        second = lightmap_export.sample_rgb_from_world_chart_positions(
            pixels, size, 1, 2, 3, 1, 1,
            [(16.0, 16.0, 0.0)], (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0), 0.0, 0.0,
        )
        self.assertEqual(first, bytes((64, 128, 191)))
        self.assertEqual(first, second)

    def test_classic_face_grid_pixel_coordinates_match_sampler_centres(self):
        coords = lightmap_export.classic_face_grid_world_chart_pixel_coordinates(
            16, 1, 2, 2, 1, 1,
            (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0), 0.0,
            0.0, 0.0, 1, 1,
            (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 0.0, 0.0,
        )
        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(coords[0][0], 3.0)
        self.assertAlmostEqual(coords[0][1], 12.0)

    def test_world_chart_grid_positions_solve_classic_texinfo_coordinates(self):
        texinfo = (0.0, 1.0, 0.0, -32.0, 0.0, 0.0, -1.0, 0.0)
        positions = lightmap_export.world_chart_grid_positions(
            texinfo, (1.0, 0.0, 0.0), 496.0,
            (0.0, 16.0), (0.0, 16.0),
        )
        self.assertEqual(positions[0], (496.0, 32.0, 0.0))
        self.assertEqual(positions[-1], (496.0, 48.0, -16.0))

    def test_affine_classic_grid_sampler_matches_xyz_reference_sampler(self):
        size = 64
        pixels = [0.0] * (size * size * 4)
        for y in range(size):
            for x in range(size):
                offset = (y * size + x) * 4
                pixels[offset:offset + 4] = (
                    x / (size - 1), y / (size - 1), 0.25, 1.0
                )
        texinfo = (0.0, 1.0, 0.0, -32.0, 0.0, 0.0, -1.0, 0.0)
        plane_normal = (1.0, 0.0, 0.0)
        plane_distance = 496.0
        s_values = (0.0, 16.0, 32.0)
        t_values = (0.0, 16.0, 32.0)
        positions = lightmap_export.world_chart_grid_positions(
            texinfo, plane_normal, plane_distance, s_values, t_values
        )
        reference = lightmap_export.sample_rgb_from_world_chart_positions(
            pixels, size, 1, 4, 4, 1, 1, positions,
            (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), 0.0, -32.0,
        )
        optimized = lightmap_export.sample_classic_face_grid_from_world_chart(
            pixels, size, 1, 4, 4, 1, 1,
            texinfo, plane_normal, plane_distance,
            0.0, 0.0, 3, 3,
            (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), 0.0, -32.0,
        )
        self.assertEqual(optimized, reference)



class SourceLightmapPassThroughTests(unittest.TestCase):
    def test_unedited_source_and_live_previews_preserve_compiled_lightmaps(self):
        for mode in ("source", "realtime", "cycles"):
            with self.subTest(mode=mode):
                self.assertTrue(
                    lightmap_export.should_preserve_source_lightmaps(mode)
                )

    def test_baked_or_painted_source_lightmaps_use_rebuild_path(self):
        self.assertFalse(lightmap_export.should_preserve_source_lightmaps("baked"))
        self.assertFalse(
            lightmap_export.should_preserve_source_lightmaps(
                "source", painted_override_active=True
            )
        )

    def test_detached_face_projection_uses_rebuild_path(self):
        self.assertFalse(
            lightmap_export.should_preserve_source_lightmaps(
                "source", has_face_local_projection=True
            )
        )

    def test_unrecognized_preview_mode_does_not_claim_source_passthrough(self):
        self.assertFalse(lightmap_export.should_preserve_source_lightmaps("unknown"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
