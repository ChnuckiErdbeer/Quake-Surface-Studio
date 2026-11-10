"""Conservative Quake 1 BSP29/BSPX reader-writer for Quake Surface Studio.

The add-on modifies selected standard lumps and RGBLIGHTING; this module
preserves all unrelated standard and BSPX payloads. It is not a BSP2/2PSB or
rerelease-specific parser.
"""
from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

BSP_VERSION = 29
HEADER_LUMPS = 15
HEADER_SIZE = 4 + HEADER_LUMPS * 8

LUMP_ENTITIES = 0
LUMP_PLANES = 1
LUMP_TEXTURES = 2
LUMP_VERTEXES = 3
LUMP_VISIBILITY = 4
LUMP_NODES = 5
LUMP_TEXINFO = 6
LUMP_FACES = 7
LUMP_LIGHTING = 8
LUMP_CLIPNODES = 9
LUMP_LEAFS = 10
LUMP_MARKSURFACES = 11
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_MODELS = 14

SIZE_PLANE = 20
SIZE_VERTEX = 12
SIZE_EDGE = 4
SIZE_SURFEDGE = 4
SIZE_TEXINFO = 40
SIZE_FACE = 20

MAX_CLASSIC_TEXTURES = 512
MAX_CLASSIC_TEXINFO = 4096


class BSPError(ValueError):
    """Raised for an invalid or unsupported BSP file."""


@dataclass
class MipTexture:
    """One entry in the Quake miptex lump; blob is the miptex_t + mip data."""
    blob: Optional[bytes]
    name: str = ""
    width: int = 0
    height: int = 0


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _checked_slice(data: bytes, offset: int, length: int, what: str) -> bytes:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise BSPError(f"{what} points outside its lump (offset={offset}, length={length}).")
    return data[offset:offset + length]


def face_winding_needs_reversal(vertices, plane_normal, side=0, flip_z=False):
    """Return whether a face's vertex order opposes its oriented BSP plane normal.

    BSP face normals are defined by both the referenced plane and dface.side.
    A reflected Z-up to Z-down import also reverses mesh winding. Compare the
    actual polygon area vector after the coordinate reflection to the intended
    transformed normal, so Cycles/Eevee see the correct front side.
    """
    points = [tuple(float(value) for value in point[:3]) for point in vertices]
    if len(points) < 3:
        return False
    area_normal = [0.0, 0.0, 0.0]
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        x0, y0, z0 = current
        x1, y1, z1 = following
        if flip_z:
            z0, z1 = -z0, -z1
        area_normal[0] += (y0 - y1) * (z0 + z1)
        area_normal[1] += (z0 - z1) * (x0 + x1)
        area_normal[2] += (x0 - x1) * (y0 + y1)

    normal = [float(value) for value in plane_normal[:3]]
    if len(normal) != 3:
        raise BSPError("A BSP face plane normal must contain three components.")
    if int(side):
        normal = [-value for value in normal]
    if flip_z:
        normal[2] = -normal[2]
    dot = sum(area_normal[index] * normal[index] for index in range(3))
    area_sq = sum(value * value for value in area_normal)
    normal_sq = sum(value * value for value in normal)
    if area_sq <= 1e-20 or normal_sq <= 1e-20:
        return False
    return dot < -1e-10 * math.sqrt(area_sq * normal_sq)


class BSP29:
    """Parsed BSP29 file with safe byte-preserving lump access."""

    def __init__(self, data: bytes):
        if len(data) < HEADER_SIZE:
            raise BSPError("File is too small to contain a Quake BSP header.")
        version = struct.unpack_from("<i", data, 0)[0]
        if version != BSP_VERSION:
            if version == int.from_bytes(b"BSP2", "little"):
                raise BSPError("This is BSP2, not classic BSP29. BSP2 support is not in this prototype.")
            if version == int.from_bytes(b"2PSB", "little"):
                raise BSPError("This is 2PSB/RMQ, not classic BSP29. 2PSB support is not in this prototype.")
            raise BSPError(f"Unsupported BSP version/magic {version!r}; this prototype accepts BSP29 only.")

        self.original = data
        self.lumps: list[bytes] = []
        self.lump_ranges: list[tuple[int, int]] = []
        for i in range(HEADER_LUMPS):
            ofs, length = struct.unpack_from("<ii", data, 4 + i * 8)
            if length < 0:
                raise BSPError(f"Lump {i} has a negative length.")
            if length == 0:
                if ofs < 0 or ofs > len(data):
                    raise BSPError(f"Empty lump {i} has an invalid offset.")
                self.lumps.append(b"")
            else:
                self.lumps.append(_checked_slice(data, ofs, length, f"Lump {i}"))
            self.lump_ranges.append((ofs, length))

        self.bspx_lumps, self.bspx_header_offset = self._parse_bspx(data)
        self._validate_fixed_lumps()

    @classmethod
    def from_file(cls, path: str) -> "BSP29":
        with open(path, "rb") as f:
            return cls(f.read())

    @staticmethod
    def _parse_bspx(data: bytes) -> tuple[dict[str, bytes], int | None]:
        """Read an optional BSPX directory at the classic header or after BSP lumps."""
        candidates = [HEADER_SIZE]
        # Some tools append BSPX after the standard lumps rather than reserving
        # the bytes immediately after the 124-byte header.
        try:
            max_end = max((ofs + length for ofs, length in
                           (struct.unpack_from('<ii', data, 4 + i * 8) for i in range(HEADER_LUMPS))
                           if length > 0), default=HEADER_SIZE)
            candidates.append((max_end + 3) & ~3)
        except Exception:
            pass
        for offset in dict.fromkeys(candidates):
            if offset < HEADER_SIZE or offset + 8 > len(data) or data[offset:offset + 4] != b'BSPX':
                continue
            count = struct.unpack_from('<i', data, offset + 4)[0]
            if count < 0 or count > 4096 or offset + 8 + count * 32 > len(data):
                continue
            result: dict[str, bytes] = {}
            valid = True
            for index in range(count):
                pos = offset + 8 + index * 32
                name_raw, file_offset, file_length = struct.unpack_from('<24sii', data, pos)
                name = name_raw.split(b'\0', 1)[0].decode('ascii', 'replace').upper()
                if not name or file_offset < 0 or file_length < 0 or file_offset + file_length > len(data):
                    valid = False
                    break
                result[name] = data[file_offset:file_offset + file_length]
            if valid:
                return result, offset
        return {}, None

    def _validate_fixed_lumps(self) -> None:
        fixed = {
            LUMP_PLANES: SIZE_PLANE,
            LUMP_VERTEXES: SIZE_VERTEX,
            LUMP_TEXINFO: SIZE_TEXINFO,
            LUMP_FACES: SIZE_FACE,
            LUMP_EDGES: SIZE_EDGE,
            LUMP_SURFEDGES: SIZE_SURFEDGE,
        }
        for lump_id, record_size in fixed.items():
            length = len(self.lumps[lump_id])
            if length % record_size:
                raise BSPError(
                    f"Lump {lump_id} length {length} is not a multiple of record size {record_size}."
                )

    def count(self, lump_id: int, record_size: int) -> int:
        return len(self.lumps[lump_id]) // record_size

    def planes(self) -> list[tuple]:
        """Return BSP planes as (nx, ny, nz, distance, type)."""
        lump = self.lumps[LUMP_PLANES]
        return [struct.unpack_from("<4fi", lump, i)
                for i in range(0, len(lump), SIZE_PLANE)]

    def vertices(self) -> list[tuple[float, float, float]]:
        lump = self.lumps[LUMP_VERTEXES]
        return [struct.unpack_from("<3f", lump, i) for i in range(0, len(lump), SIZE_VERTEX)]

    def edges(self) -> list[tuple[int, int]]:
        lump = self.lumps[LUMP_EDGES]
        return [struct.unpack_from("<2H", lump, i) for i in range(0, len(lump), SIZE_EDGE)]

    def surfedges(self) -> list[int]:
        lump = self.lumps[LUMP_SURFEDGES]
        return [x[0] for x in struct.iter_unpack("<i", lump)]

    def texinfos(self) -> list[tuple]:
        lump = self.lumps[LUMP_TEXINFO]
        return [struct.unpack_from("<8fii", lump, i) for i in range(0, len(lump), SIZE_TEXINFO)]

    def faces(self) -> list[tuple]:
        # dface_t: ushort planenum, short side, int firstedge, short numedges,
        # short texinfo, 4 style bytes, int lightofs.
        lump = self.lumps[LUMP_FACES]
        return [struct.unpack_from("<Hhihh4Bi", lump, i) for i in range(0, len(lump), SIZE_FACE)]

    def face_vertex_indices(self, face: tuple, edges=None, surfedges=None) -> list[int]:
        if edges is None:
            edges = self.edges()
        if surfedges is None:
            surfedges = self.surfedges()
        firstedge = face[2]
        numedges = face[3]
        if firstedge < 0 or numedges < 0 or firstedge + numedges > len(surfedges):
            raise BSPError("A face references surfedges outside the surfedges lump.")
        result = []
        for signed_edge in surfedges[firstedge:firstedge + numedges]:
            edge_index = abs(signed_edge)
            if edge_index >= len(edges):
                raise BSPError("A surfedge references an edge outside the edges lump.")
            v0, v1 = edges[edge_index]
            result.append(v0 if signed_edge >= 0 else v1)
        return result

    def miptextures(self) -> list[MipTexture]:
        lump = self.lumps[LUMP_TEXTURES]
        if not lump:
            return []
        if len(lump) < 4:
            raise BSPError("Texture lump is too short.")
        count = struct.unpack_from("<i", lump, 0)[0]
        if count < 0 or count > 65535:
            raise BSPError(f"Invalid miptex count: {count}.")
        directory_end = 4 + count * 4
        if directory_end > len(lump):
            raise BSPError("Miptex offset directory extends beyond the texture lump.")
        result: list[MipTexture] = []
        for i in range(count):
            offset = struct.unpack_from("<i", lump, 4 + i * 4)[0]
            if offset == -1:
                result.append(MipTexture(None))
                continue
            if offset < directory_end or offset + 40 > len(lump):
                raise BSPError(f"Miptex {i} has an invalid offset.")
            name_raw, width, height, o0, o1, o2, o3 = struct.unpack_from("<16s6I", lump, offset)
            if width <= 0 or height <= 0 or width > 8192 or height > 8192:
                raise BSPError(f"Miptex {i} has invalid dimensions {width}x{height}.")
            offsets = (o0, o1, o2, o3)
            ends = []
            for level, level_offset in enumerate(offsets):
                w = max(1, width >> level)
                h = max(1, height >> level)
                if level_offset == 0:
                    # A zero first offset conventionally marks a missing miptex.
                    ends = []
                    break
                if level_offset < 40:
                    raise BSPError(f"Miptex {i} mip level {level} has an invalid offset.")
                ends.append(level_offset + w * h)
            if not ends:
                # A zero mip offset is the conventional marker for a texture
                # stored externally (usually in a WAD2). Preserve its header
                # and name so the Blender importer can resolve it later.
                name = name_raw.split(b"\0", 1)[0].decode("ascii", "replace")
                if all(level_offset == 0 for level_offset in offsets):
                    result.append(MipTexture(bytes(lump[offset:offset + 40]), name, width, height))
                else:
                    result.append(MipTexture(None, name, width, height))
                continue
            blob_end = max(ends)
            if offset + blob_end > len(lump):
                raise BSPError(f"Miptex {i} pixel data extends beyond the texture lump.")
            name = name_raw.split(b"\0", 1)[0].decode("ascii", "replace")
            result.append(MipTexture(bytes(lump[offset:offset + blob_end]), name, width, height))
        return result

    def write(self, lumps: Optional[list[bytes]] = None,
              bspx_lumps: Optional[dict[str, bytes]] = None) -> bytes:
        """Rebuild standard lumps and preserve optional BSPX extensions.

        When BSPX data is present, the directory is placed immediately after
        the standard 124-byte header, and all lump payload offsets are updated.
        Unknown BSPX lumps are carried through unchanged.
        """
        lumps = self.lumps if lumps is None else lumps
        if len(lumps) != HEADER_LUMPS:
            raise BSPError("Exactly 15 lumps are required when writing BSP29.")
        bspx_lumps = self.bspx_lumps if bspx_lumps is None else bspx_lumps
        normalized_bspx = {}
        for name, payload in (bspx_lumps or {}).items():
            safe_name = str(name).upper()
            encoded = safe_name.encode('ascii', 'strict')
            if not encoded or len(encoded) > 23:
                raise BSPError(f"Invalid BSPX lump name: {name!r}.")
            normalized_bspx[safe_name] = bytes(payload)

        output = bytearray(HEADER_SIZE)
        struct.pack_into("<i", output, 0, BSP_VERSION)
        bspx_directory_offset = HEADER_SIZE if normalized_bspx else None
        if normalized_bspx:
            names = list(normalized_bspx.keys())
            output.extend(b'BSPX' + struct.pack('<i', len(names)))
            directory_pos = len(output)
            output.extend(b'\0' * (32 * len(names)))
        else:
            names = []
            directory_pos = None

        for i, lump in enumerate(lumps):
            if not lump:
                struct.pack_into("<ii", output, 4 + i * 8, 0, 0)
                continue
            while len(output) & 3:
                output.append(0)
            offset = len(output)
            output.extend(lump)
            struct.pack_into("<ii", output, 4 + i * 8, offset, len(lump))

        if normalized_bspx:
            for index, name in enumerate(names):
                payload = normalized_bspx[name]
                while len(output) & 3:
                    output.append(0)
                offset = len(output)
                output.extend(payload)
                struct.pack_into('<24sii', output, directory_pos + index * 32,
                                 name.encode('ascii').ljust(24, b'\0'), offset, len(payload))
        return bytes(output)



def build_miptex_blob(name: str, width: int, height: int, mip_levels: Iterable[bytes]) -> bytes:
    """Build one miptex_t + four indexed mip levels."""
    levels = list(mip_levels)
    if len(levels) != 4:
        raise BSPError("A Quake miptex must contain exactly four mip levels.")
    if not (16 <= width <= 512 and 16 <= height <= 512):
        raise BSPError("For this prototype, texture dimensions must be between 16 and 512 pixels.")
    if width & (width - 1) or height & (height - 1):
        raise BSPError("Texture width and height must be powers of two.")
    name_bytes = name.encode("ascii", "replace")[:15].ljust(16, b"\0")
    offsets = []
    cursor = 40
    for level, pixels in enumerate(levels):
        w, h = max(1, width >> level), max(1, height >> level)
        if len(pixels) != w * h:
            raise BSPError(f"Mip level {level} has {len(pixels)} pixels; expected {w*h}.")
        offsets.append(cursor)
        cursor += len(pixels)
    header = struct.pack("<16s6I", name_bytes, width, height, *offsets)
    return header + b"".join(levels)


def build_texture_lump(entries: Iterable[MipTexture]) -> bytes:
    """Rebuild the variable-length BSP texture directory and miptex payloads."""
    entries = list(entries)
    directory_size = 4 + 4 * len(entries)
    out = bytearray(directory_size)
    struct.pack_into("<i", out, 0, len(entries))
    for i, entry in enumerate(entries):
        if entry.blob is None:
            struct.pack_into("<i", out, 4 + 4 * i, -1)
            continue
        while len(out) & 3:
            out.append(0)
        offset = len(out)
        struct.pack_into("<i", out, 4 + 4 * i, offset)
        out.extend(entry.blob)
    return bytes(out)



def replace_face_lightofs(faces_lump: bytes, face_index: int, lightofs: int) -> bytes:
    """Return a face lump with one dface_t lightofs field replaced."""
    if len(faces_lump) % SIZE_FACE:
        raise BSPError("Face lump has an invalid size.")
    count = len(faces_lump) // SIZE_FACE
    if face_index < 0 or face_index >= count:
        raise BSPError(f"Face index {face_index} is out of range.")
    value = int(lightofs)
    if value < -1 or value > 0x7FFFFFFF:
        raise BSPError("Lightmap offset exceeds the signed 32-bit BSP29 field.")
    result = bytearray(faces_lump)
    struct.pack_into("<i", result, face_index * SIZE_FACE + 16, value)
    return bytes(result)


def replace_face_texinfo(faces_lump: bytes, face_index: int, texinfo_index: int) -> bytes:
    if len(faces_lump) % SIZE_FACE:
        raise BSPError("Face lump has an invalid size.")
    count = len(faces_lump) // SIZE_FACE
    if face_index < 0 or face_index >= count:
        raise BSPError(f"Face index {face_index} is out of range.")
    if not (0 <= texinfo_index <= 32767):
        raise BSPError("Texinfo index exceeds the signed 16-bit BSP29 field.")
    result = bytearray(faces_lump)
    struct.pack_into("<h", result, face_index * SIZE_FACE + 10, texinfo_index)
    return bytes(result)


def clone_texinfo(texinfo_lump: bytes, source_index: int, miptex_index: int) -> tuple[bytes, int]:
    """Return (new_lump, new_texinfo_index), cloning projection + flags."""
    if len(texinfo_lump) % SIZE_TEXINFO:
        raise BSPError("Texinfo lump has an invalid size.")
    count = len(texinfo_lump) // SIZE_TEXINFO
    if source_index < 0 or source_index >= count:
        raise BSPError(f"Texinfo index {source_index} is out of range.")
    if not (0 <= miptex_index <= 32767):
        raise BSPError("Miptex index exceeds the signed 16-bit texinfo field.")
    new_index = count
    if new_index >= MAX_CLASSIC_TEXINFO:
        raise BSPError("Classic Quake texinfo limit (4096) would be exceeded.")
    record = bytearray(texinfo_lump[source_index * SIZE_TEXINFO:(source_index + 1) * SIZE_TEXINFO])
    struct.pack_into("<i", record, 32, miptex_index)
    return texinfo_lump + bytes(record), new_index


def clone_texinfo_with_projection(
    texinfo_lump: bytes,
    source_index: int,
    miptex_index: int,
    projection: Sequence[float],
) -> tuple[bytes, int]:
    """Clone one texinfo, replacing its two 4-float texture projection axes.

    ``projection`` is (Sx, Sy, Sz, So, Tx, Ty, Tz, To). The source flags are
    retained and the miptex index is changed to ``miptex_index``.
    """
    if len(projection) != 8:
        raise BSPError("A custom texinfo projection must contain exactly eight floats.")
    if any(not math.isfinite(float(v)) for v in projection):
        raise BSPError("A custom texinfo projection contains a non-finite value.")
    if len(texinfo_lump) % SIZE_TEXINFO:
        raise BSPError("Texinfo lump has an invalid size.")
    count = len(texinfo_lump) // SIZE_TEXINFO
    if source_index < 0 or source_index >= count:
        raise BSPError(f"Texinfo index {source_index} is out of range.")
    if not (0 <= miptex_index <= 32767):
        raise BSPError("Miptex index exceeds the signed 16-bit texinfo field.")
    new_index = count
    if new_index >= MAX_CLASSIC_TEXINFO:
        raise BSPError("Classic Quake texinfo limit (4096) would be exceeded.")
    record = bytearray(texinfo_lump[source_index * SIZE_TEXINFO:(source_index + 1) * SIZE_TEXINFO])
    struct.pack_into("<8f", record, 0, *(float(v) for v in projection))
    struct.pack_into("<i", record, 32, miptex_index)
    return texinfo_lump + bytes(record), new_index



def parse_lit_file(data: bytes, lighting_length: int) -> Optional[bytes]:
    """Return QLIT v1 RGB sample bytes, or None when the sidecar is invalid.

    Quake coloured-lighting sidecars contain: b"QLIT", little-endian
    version 1, then one RGB triplet for each byte in the BSP lighting lump.
    """
    if len(data) < 8 or data[:4] != b"QLIT":
        return None
    version = struct.unpack_from("<i", data, 4)[0]
    if version != 1 or len(data) != 8 + 3 * lighting_length:
        return None
    return data[8:]


def build_lit_file(rgb_samples: bytes) -> bytes:
    """Build a Quake QLIT v1 sidecar from RGB triplets."""
    if len(rgb_samples) % 3:
        raise BSPError("QLIT RGB sample data must contain complete RGB triplets.")
    return b"QLIT" + struct.pack("<i", 1) + rgb_samples


def load_lit_file(path: str, lighting_length: int) -> Optional[bytes]:
    """Read and validate a QLIT v1 sidecar; return RGB bytes or None."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return parse_lit_file(data, lighting_length)


def rgb_lighting_to_luminance(rgb_samples: bytes) -> bytes:
    """Convert packed RGB luxels to an 8-bit luminance fallback."""
    if len(rgb_samples) % 3:
        raise BSPError("RGB light samples must contain complete triplets.")
    mono = bytearray(len(rgb_samples) // 3)
    for i in range(len(mono)):
        r, g, b = rgb_samples[i * 3:i * 3 + 3]
        mono[i] = max(0, min(255, int(round(0.2126 * r + 0.7152 * g + 0.0722 * b))))
    return bytes(mono)


def resolve_rgb_lighting(bspx_lumps: dict[str, bytes], lighting_lump: bytes,
                         lit_path: Optional[str] = None) -> tuple[Optional[bytes], str]:
    """Resolve RGB lightmaps, preferring in-BSPX RGBLIGHTING over a .lit file.

    BSPX RGBLIGHTING stores one RGB triplet per byte/sample of the classic
    LIGHTING lump, but some compilers omit the monochrome lump. In that case
    the RGB lump itself defines the sample count.
    """
    bspx_rgb = (bspx_lumps or {}).get("RGBLIGHTING")
    if bspx_rgb is not None:
        valid_length = (len(bspx_rgb) % 3 == 0 and
                        (not lighting_lump or len(bspx_rgb) == 3 * len(lighting_lump)))
        if valid_length:
            return bytes(bspx_rgb), "BSPX RGBLIGHTING"
    if lit_path and lighting_lump:
        sidecar = load_lit_file(lit_path, len(lighting_lump))
        if sidecar is not None:
            return sidecar, "QLIT v1 .lit sidecar"
    return None, "Monochrome BSP lighting"

def read_wad2_textures(path: str) -> dict[str, MipTexture]:
    """Read uncompressed Quake WAD2 miptex entries by lowercase texture name.

    WAD2 directory records are 32 bytes. Compressed LZSS lumps are skipped;
    the original Quake toolchain normally stores miptex lumps uncompressed.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        raise BSPError(f"Could not read WAD file '{path}': {exc}") from exc
    if len(data) < 12 or data[:4] != b"WAD2":
        raise BSPError(f"'{path}' is not a WAD2 archive.")
    count, directory = struct.unpack_from("<ii", data, 4)
    if count < 0 or count > 100000 or directory < 12 or directory + count * 32 > len(data):
        raise BSPError(f"'{path}' has an invalid WAD2 directory.")

    textures: dict[str, MipTexture] = {}
    for i in range(count):
        pos = directory + i * 32
        file_pos, disk_size, unpacked_size, lump_type, compression = struct.unpack_from("<iiiBB", data, pos)
        raw_name = data[pos + 16:pos + 32].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", "replace").strip()
        if lump_type != 68 or compression != 0 or not name:
            continue
        if file_pos < 0 or disk_size < 40 or file_pos + disk_size > len(data):
            continue
        if unpacked_size not in (0, disk_size):
            continue
        blob_data = data[file_pos:file_pos + disk_size]
        try:
            name_raw, width, height, *offsets = struct.unpack_from("<16s6I", blob_data, 0)
        except struct.error:
            continue
        if width <= 0 or height <= 0 or width > 8192 or height > 8192:
            continue
        if any(value == 0 for value in offsets):
            continue
        ends = []
        valid = True
        for level, level_offset in enumerate(offsets):
            level_size = max(1, width >> level) * max(1, height >> level)
            if level_offset < 40 or level_offset + level_size > len(blob_data):
                valid = False
                break
            ends.append(level_offset + level_size)
        if not valid:
            continue
        blob = bytes(blob_data[:max(ends)])
        header_name = name_raw.split(b"\0", 1)[0].decode("ascii", "replace") or name
        textures.setdefault(header_name.lower(), MipTexture(blob, header_name, width, height))
    return textures



def parse_entities_lump(entities_lump: bytes) -> list[dict[str, str]]:
    """Parse Quake's brace-delimited entity lump into ordered key/value maps.

    Quake entity values are quoted strings. This scanner handles escaped
    quotes/backslashes and ignores whitespace between tokens.
    """
    text = entities_lump.decode("latin1", "replace")
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in '{}':
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            i += 1
            chars = []
            while i < n:
                ch = text[i]
                if ch == '\\' and i + 1 < n:
                    nxt = text[i + 1]
                    if nxt in ('\\', '"'):
                        chars.append(nxt)
                    else:
                        chars.extend((ch, nxt))
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                chars.append(ch)
                i += 1
            tokens.append(''.join(chars))
            continue
        # Be tolerant of stray non-quoted tokens in malformed entity lumps.
        j = i
        while j < n and not text[j].isspace() and text[j] not in '{}':
            j += 1
        tokens.append(text[i:j])
        i = j

    entities: list[dict[str, str]] = []
    pos = 0
    while pos < len(tokens):
        if tokens[pos] != '{':
            pos += 1
            continue
        pos += 1
        entity: dict[str, str] = {}
        while pos < len(tokens) and tokens[pos] != '}':
            key = tokens[pos]
            pos += 1
            if pos >= len(tokens) or tokens[pos] == '}':
                break
            value = tokens[pos]
            pos += 1
            entity[key.lower()] = value
        if pos < len(tokens) and tokens[pos] == '}':
            pos += 1
        if entity:
            entities.append(entity)
    return entities

def worldspawn_wad_names(entities_lump: bytes) -> list[str]:
    """Return semicolon-separated WAD paths from the worldspawn entity."""
    import re

    text = entities_lump.decode("latin1", "replace")
    for block in re.findall(r"\{(.*?)\}", text, flags=re.DOTALL):
        pairs = re.findall(r'"((?:\\.|[^"\\])*)"\s*"((?:\\.|[^"\\])*)"', block)
        entity = {key.replace('\\"', '"').lower(): value.replace('\\"', '"') for key, value in pairs}
        if entity.get("classname", "").lower() == "worldspawn" and entity.get("wad"):
            return [item.strip() for item in entity["wad"].split(";") if item.strip()]
    return []


def load_palette_file(path: str) -> bytes:
    with open(path, "rb") as f:
        data = f.read()
    if len(data) != 768:
        raise BSPError(f"Palette file must be exactly 768 bytes; got {len(data)}.")
    return data


def _palette_from_pak(path: str) -> Optional[bytes]:
    """Read gfx/palette.lmp from an uncompressed Quake PACK archive."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) < 12 or data[:4] != b"PACK":
        return None
    directory_offset, directory_length = struct.unpack_from("<ii", data, 4)
    if directory_offset < 12 or directory_length < 0 or directory_offset + directory_length > len(data):
        return None
    if directory_length % 64:
        return None
    for pos in range(directory_offset, directory_offset + directory_length, 64):
        name_raw = data[pos:pos + 56].split(b"\0", 1)[0].replace(b"\\", b"/").lower()
        if name_raw.endswith(b"gfx/palette.lmp") or name_raw == b"palette.lmp":
            file_pos, file_len = struct.unpack_from("<ii", data, pos + 56)
            if file_pos >= 0 and file_len == 768 and file_pos + file_len <= len(data):
                return data[file_pos:file_pos + file_len]
    return None


def find_quake_palette(game_dir: str = "", palette_file: str = "") -> tuple[Optional[bytes], str]:
    """Find a 768-byte palette.lmp directly or inside a Quake PAK archive."""
    # An explicitly selected palette file takes precedence over game archives.
    if palette_file:
        explicit = os.path.expanduser(palette_file)
        if os.path.isfile(explicit):
            try:
                return load_palette_file(explicit), explicit
            except (OSError, BSPError):
                pass

    candidates = []
    if game_dir:
        root = os.path.abspath(os.path.expanduser(game_dir))
        candidates.extend([
            os.path.join(root, "gfx", "palette.lmp"),
            os.path.join(root, "id1", "gfx", "palette.lmp"),
            os.path.join(root, "palette.lmp"),
        ])
        # Prefer loose palettes (e.g. mod overrides) before looking inside PAKs.
        for path in candidates:
            if os.path.isfile(path):
                try:
                    return load_palette_file(path), path
                except (OSError, BSPError):
                    continue

        for base, dirs, files in os.walk(root):
            # Keep this search bounded and avoid crawling an entire Steam library.
            depth = os.path.relpath(base, root).count(os.sep)
            if depth >= 3:
                dirs[:] = []
            for filename in files:
                low = filename.lower()
                if low == "palette.lmp":
                    path = os.path.join(base, filename)
                    try:
                        return load_palette_file(path), path
                    except (OSError, BSPError):
                        pass
                elif low.startswith("pak") and low.endswith(".pak"):
                    palette = _palette_from_pak(os.path.join(base, filename))
                    if palette:
                        return palette, os.path.join(base, filename) + "!gfx/palette.lmp"
    return None, ""
