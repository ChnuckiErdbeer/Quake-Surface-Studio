"""Quake installation configuration and PAK-aware map discovery.

This module has no Blender dependency so PAK parsing, map discovery and the
persistent JSON configuration can be tested in ordinary Python and from Blender.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
from functools import lru_cache


CONFIG_VERSION = 1


def normalize_quake_root(path: str) -> str:
    """Return the installation root; selecting id1 itself is also accepted."""
    if not path:
        return ""
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))
    if os.path.basename(os.path.normpath(root)).lower() == "id1":
        root = os.path.dirname(os.path.normpath(root))
    return root


def discover_game_dirs(quake_root: str) -> list[dict]:
    """Find id1 and immediate mod directories containing maps/ or PAK archives."""
    root = normalize_quake_root(quake_root)
    if not root or not os.path.isdir(root):
        return []
    found = []
    id1 = os.path.join(root, "id1")
    if os.path.isdir(id1):
        found.append({"id": "id1", "label": "id1 (original Quake)", "path": id1})
    try:
        children = sorted(os.scandir(root), key=lambda item: item.name.casefold())
    except OSError:
        children = []
    for item in children:
        if not item.is_dir(follow_symlinks=False) or item.name.casefold() == "id1":
            continue
        path = item.path
        has_maps = os.path.isdir(os.path.join(path, "maps"))
        try:
            has_paks = any(
                entry.is_file(follow_symlinks=False)
                and re.fullmatch(r"pak\d+\.pak", entry.name, flags=re.IGNORECASE)
                for entry in os.scandir(path)
            )
        except OSError:
            has_paks = False
        if has_maps or has_paks:
            found.append({"id": item.name, "label": item.name, "path": path})
    if not found and (
        os.path.isdir(os.path.join(root, "maps"))
        or any(
            re.fullmatch(r"pak\d+\.pak", name, flags=re.IGNORECASE)
            for name in os.listdir(root)
        )
    ):
        found.append({
            "id": ".",
            "label": os.path.basename(root) or root,
            "path": root,
        })
    return found


def resolve_game_dir(quake_root: str, game_id: str) -> str:
    """Resolve a selected game identifier against the installation root."""
    root = normalize_quake_root(quake_root)
    for item in discover_game_dirs(root):
        if item["id"] == game_id:
            return item["path"]
    return ""


def game_id_for_path(quake_root: str, game_dir: str) -> str:
    """Return the configured enum identifier for a game folder."""
    if not game_dir:
        return ""
    target = os.path.normcase(os.path.abspath(os.path.expanduser(game_dir)))
    for item in discover_game_dirs(quake_root):
        if os.path.normcase(os.path.abspath(item["path"])) == target:
            return item["id"]
    return ""


def load_config(path: str) -> dict:
    """Load QSS's user-level JSON config; invalid/missing files are harmless."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            return {}
        return value
    except (OSError, ValueError, TypeError):
        return {}


def save_config(config: dict, path: str) -> None:
    """Atomically persist QSS settings without risking a partially-written file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    payload = dict(config)
    payload["config_version"] = CONFIG_VERSION
    fd, temporary = tempfile.mkstemp(prefix=".qss-config-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass


def _safe_virtual_path(value: str) -> str:
    name = str(value or "").replace("\\", "/").strip()
    while name.startswith("./"):
        name = name[2:]
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return ""
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return ""
    return "/".join(parts)


def _pak_sort_key(path: str) -> tuple:
    name = os.path.basename(path)
    match = re.fullmatch(r"pak(\d+)\.pak", name, flags=re.IGNORECASE)
    return (int(match.group(1)) if match else -1, name.casefold())


@lru_cache(maxsize=256)
def _read_pak_directory_cached(pak_path: str, mtime_ns: int, file_size: int):
    """Cache a validated PAK index by path and stable file signature."""
    try:
        with open(pak_path, "rb") as handle:
            header = handle.read(12)
            if len(header) != 12 or header[:4] != b"PACK":
                raise ValueError("not a Quake PACK archive")
            directory_offset, directory_length = struct.unpack_from("<ii", header, 4)
            if (
                directory_offset < 12 or directory_length < 0
                or directory_length % 64
                or directory_offset + directory_length > file_size
            ):
                raise ValueError("invalid PACK directory bounds")
            handle.seek(directory_offset)
            directory = handle.read(directory_length)
            if len(directory) != directory_length:
                raise ValueError("truncated PACK directory")
    except OSError as exc:
        raise ValueError(f"could not read PAK '{pak_path}': {exc}") from exc

    entries = []
    for offset in range(0, len(directory), 64):
        record = directory[offset:offset + 64]
        raw_name = record[:56].split(b"\0", 1)[0]
        name = _safe_virtual_path(raw_name.decode("latin1", "replace"))
        file_offset, file_length = struct.unpack_from("<ii", record, 56)
        if not name or file_length < 0 or file_offset < 12:
            continue
        if file_offset + file_length > file_size or file_offset + file_length > directory_offset:
            continue
        entries.append((name, file_offset, file_length))
    return tuple(entries)


def read_pak_directory(pak_path: str) -> list[dict]:
    """Read a Quake PACK directory, validating ranges and caching its index."""
    absolute = os.path.abspath(os.path.expanduser(str(pak_path)))
    try:
        stat = os.stat(absolute)
    except OSError as exc:
        raise ValueError(f"could not read PAK '{pak_path}': {exc}") from exc
    entries = _read_pak_directory_cached(
        absolute, int(stat.st_mtime_ns), int(stat.st_size)
    )
    return [
        {"path": name, "offset": offset, "length": length}
        for name, offset, length in entries
    ]


def discover_pak_archives(game_dir: str) -> list[dict]:
    """Return valid direct-child pakN.pak archives in Quake search order."""
    if not game_dir or not os.path.isdir(game_dir):
        return []
    try:
        paths = [
            os.path.join(game_dir, name)
            for name in os.listdir(game_dir)
            if re.fullmatch(r"pak\d+\.pak", name, flags=re.IGNORECASE)
            and os.path.isfile(os.path.join(game_dir, name))
        ]
    except OSError:
        return []
    result = []
    for path in sorted(paths, key=_pak_sort_key):
        try:
            stat = os.stat(path)
            entries = read_pak_directory(path)
        except (OSError, ValueError):
            continue
        result.append({
            "path": os.path.abspath(path),
            "name": os.path.basename(path),
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
            "entry_count": len(entries),
            "total_bytes": sum(int(item["length"]) for item in entries),
        })
    return result


def extract_pak_archive(pak_path: str, destination: str) -> dict:
    """Safely extract one Quake PAK into its own folder without modifying it."""
    absolute = os.path.abspath(os.path.expanduser(str(pak_path)))
    destination = os.path.abspath(os.path.expanduser(str(destination)))
    entries = read_pak_directory(absolute)
    os.makedirs(destination, exist_ok=True)
    extracted = total_bytes = skipped = 0
    for entry in entries:
        virtual = _safe_virtual_path(entry["path"])
        if not virtual:
            continue
        target = os.path.abspath(os.path.join(destination, *virtual.split("/")))
        try:
            if os.path.commonpath((destination, target)) != destination:
                continue
        except ValueError:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        length = int(entry["length"])
        if os.path.isfile(target) and os.path.getsize(target) == length:
            skipped += 1
            continue
        with open(absolute, "rb") as source:
            source.seek(int(entry["offset"]))
            data = source.read(length)
        if len(data) != length:
            raise ValueError(f"Truncated PAK payload while extracting {virtual!r}.")
        fd, temporary = tempfile.mkstemp(
            prefix=".qss-pak-", suffix=".tmp", dir=os.path.dirname(target)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temporary, target)
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        extracted += 1
        total_bytes += length
    return {
        "pak_path": absolute,
        "destination": destination,
        "entry_count": len(entries),
        "files_extracted": extracted,
        "files_skipped": skipped,
        "bytes_extracted": total_bytes,
    }


def extract_all_paks(game_dir: str, cache_dir: str) -> list[dict]:
    """Extract each PAK into its own versioned cache folder, retaining precedence.

    Separate directories preserve duplicate virtual paths from different PAKs.
    The source archive is read-only. Each destination is keyed by archive path,
    size and modification time so a changed archive gets a fresh cache folder.
    """
    root = os.path.abspath(os.path.expanduser(str(game_dir or "")))
    cache_root = os.path.abspath(os.path.expanduser(str(cache_dir or "")))
    if not root or not os.path.isdir(root):
        raise ValueError("Select a valid Quake game directory before extracting PAKs.")
    archives = discover_pak_archives(root)
    if not archives:
        return []
    root_key = hashlib.sha256(os.path.normcase(root).encode("utf-8")).hexdigest()[:16]
    output_root = os.path.join(cache_root, root_key)
    results = []
    for archive in archives:
        signature = (
            f"{archive['path']}\0{archive['size']}\0{archive['mtime_ns']}"
        ).encode("utf-8")
        archive_key = hashlib.sha256(signature).hexdigest()[:16]
        folder = os.path.join(output_root, archive["name"][:-4] + "-" + archive_key)
        results.append(extract_pak_archive(archive["path"], folder))
    return results

def discover_maps(game_dir: str) -> list[dict]:
    """Discover loose and archived BSPs, applying Quake search-path precedence.

    Higher-numbered PAKs override lower-numbered PAKs. Loose files override all
    PAK contents. The returned list has one effective entry per virtual map path.
    """
    if not game_dir or not os.path.isdir(game_dir):
        return []
    selected = {}
    try:
        pak_paths = [
            os.path.join(game_dir, name)
            for name in os.listdir(game_dir)
            if re.fullmatch(r"pak\d+\.pak", name, flags=re.IGNORECASE)
            and os.path.isfile(os.path.join(game_dir, name))
        ]
    except OSError:
        pak_paths = []
    for pak_path in sorted(pak_paths, key=_pak_sort_key):
        try:
            directory = read_pak_directory(pak_path)
        except ValueError:
            continue
        for item in directory:
            virtual_path = item["path"]
            if not virtual_path.lower().startswith("maps/") or not virtual_path.lower().endswith(".bsp"):
                continue
            key = virtual_path.casefold()
            identifier = hashlib.sha1(
                ("pak\0" + os.path.abspath(pak_path) + "\0" + virtual_path).encode("utf-8")
            ).hexdigest()
            selected[key] = {
                "id": identifier,
                "path": virtual_path,
                "kind": "pak",
                "source_label": os.path.basename(pak_path),
                "pak_path": os.path.abspath(pak_path),
                "file_path": "",
                "offset": item["offset"],
                "length": item["length"],
            }
    maps_dir = os.path.join(game_dir, "maps")
    if os.path.isdir(maps_dir):
        for walk_root, dirs, files in os.walk(maps_dir):
            dirs.sort(key=str.casefold)
            for filename in sorted(files, key=str.casefold):
                if not filename.lower().endswith(".bsp"):
                    continue
                file_path = os.path.join(walk_root, filename)
                relative = os.path.relpath(file_path, game_dir).replace(os.sep, "/")
                identifier = hashlib.sha1(
                    ("loose\0" + os.path.abspath(file_path)).encode("utf-8")
                ).hexdigest()
                selected[relative.casefold()] = {
                    "id": identifier,
                    "path": relative,
                    "kind": "loose",
                    "source_label": "Loose file",
                    "pak_path": "",
                    "file_path": os.path.abspath(file_path),
                    "offset": 0,
                    "length": os.path.getsize(file_path),
                }
    return sorted(selected.values(), key=lambda item: item["path"].casefold())


def read_map_entry(entry: dict) -> bytes:
    """Read the BSP payload from either a loose path or a PAK directory entry."""
    if entry.get("kind") == "loose":
        with open(entry["file_path"], "rb") as handle:
            return handle.read()
    pak_path = entry.get("pak_path", "")
    expected_length = int(entry.get("length", -1))
    offset = int(entry.get("offset", -1))
    if not pak_path or expected_length < 0 or offset < 12:
        raise ValueError("invalid PAK map record")
    size = os.path.getsize(pak_path)
    if offset + expected_length > size:
        raise ValueError("PAK map payload points outside the archive")
    with open(pak_path, "rb") as handle:
        handle.seek(offset)
        data = handle.read(expected_length)
    if len(data) != expected_length:
        raise ValueError("truncated PAK map payload")
    return data


def extract_map(entry: dict, cache_dir: str) -> str:
    """Materialize an archived BSP into a stable QSS cache path for Blender import."""
    if entry.get("kind") == "loose":
        path = os.path.abspath(entry["file_path"])
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        return path
    pak_path = os.path.abspath(entry.get("pak_path", ""))
    stat = os.stat(pak_path)
    cache_key = hashlib.sha256(
        (pak_path + "\0" + str(stat.st_mtime_ns) + "\0" + str(stat.st_size)
         + "\0" + entry["path"]).encode("utf-8")
    ).hexdigest()[:24]
    target_dir = os.path.join(cache_dir, cache_key)
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.basename(entry["path"].replace("\\", "/"))
    target = os.path.join(target_dir, filename)
    if not os.path.isfile(target) or os.path.getsize(target) != int(entry["length"]):
        data = read_map_entry(entry)
        temporary = target + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(data)
        os.replace(temporary, target)
    return target
