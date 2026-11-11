"""Loss-minimizing Quake MAP entity editing for SLOPGATE.

The parser deliberately treats brush bodies as opaque source text. It only
indexes top-level entity key/value pairs, so synchronizing lights never rebuilds
brush planes, texture axes, comments, or unrelated entity data.
"""
from __future__ import annotations

import hashlib
import os
import tempfile


class MapSyncError(ValueError):
    """Raised when a MAP cannot be safely associated or edited."""


def find_companion_map(bsp_path: str) -> str:
    """Find a same-basename .map beside a BSP; ambiguous case variants are ignored."""
    source = os.path.abspath(os.path.expanduser(str(bsp_path or "")))
    if not source or not source.lower().endswith(".bsp"):
        return ""
    root = os.path.splitext(source)[0]
    exact = root + ".map"
    if os.path.isfile(exact):
        return exact
    directory = os.path.dirname(source)
    wanted = os.path.basename(root).casefold() + ".map"
    try:
        matches = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.casefold() == wanted and os.path.isfile(os.path.join(directory, name))
        ]
    except OSError:
        return ""
    return os.path.abspath(matches[0]) if len(matches) == 1 else ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def _scan_tokens(source: str) -> list[dict]:
    """Tokenize braces and quoted strings while skipping comments and whitespace."""
    text = str(source)
    result = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise MapSyncError(f"Unterminated block comment at character {i}.")
            i = end + 2
            continue
        if ch in "{}":
            result.append({"kind": "brace", "value": ch, "start": i, "end": i + 1})
            i += 1
            continue
        if ch == '"':
            start = i
            i += 1
            chars = []
            closed = False
            while i < n:
                ch = text[i]
                if ch == "\\":
                    if i + 1 >= n:
                        raise MapSyncError(f"Trailing escape in quoted string at character {i}.")
                    nxt = text[i + 1]
                    if nxt in {'\\', '"'}:
                        chars.append(nxt)
                    else:
                        chars.extend(("\\", nxt))
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    closed = True
                    break
                chars.append(ch)
                i += 1
            if not closed:
                raise MapSyncError(f"Unterminated quoted string at character {start}.")
            result.append({
                "kind": "string", "value": "".join(chars),
                "start": start, "end": i,
            })
            continue
        start = i
        while i < n and not text[i].isspace() and text[i] not in '{}"':
            if text.startswith("//", i) or text.startswith("/*", i):
                break
            i += 1
        if i == start:
            raise MapSyncError(f"Unexpected character {text[i]!r} at character {i}.")
        result.append({"kind": "bare", "value": text[start:i], "start": start, "end": i})
    return result


def parse_map_entities(source: str) -> list[dict]:
    """Return source spans and decoded top-level key/value pairs for each entity.

    Nested brush blocks are counted but not interpreted. Entity and property
    order is retained, including duplicate keys, so the original MAP remains
    the authoritative representation.
    """
    tokens = _scan_tokens(source)
    entities = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token["kind"] != "brace" or token["value"] != "{":
            i += 1
            continue
        start = token["start"]
        depth = 1
        i += 1
        properties = []
        close_token = None
        while i < len(tokens):
            current = tokens[i]
            if current["kind"] == "brace":
                if current["value"] == "{":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        close_token = current
                        i += 1
                        break
                i += 1
                continue
            if depth == 1:
                if current["kind"] != "string":
                    raise MapSyncError(
                        f"Expected an entity key at character {current['start']}."
                    )
                if i + 1 >= len(tokens) or tokens[i + 1]["kind"] != "string":
                    raise MapSyncError(
                        f"Entity key {current['value']!r} has no quoted value."
                    )
                value_token = tokens[i + 1]
                properties.append({
                    "key": current["value"],
                    "key_lower": current["value"].casefold(),
                    "value": value_token["value"],
                    "key_start": current["start"],
                    "key_end": current["end"],
                    "value_start": value_token["start"],
                    "value_end": value_token["end"],
                })
                i += 2
                continue
            i += 1
        if close_token is None:
            raise MapSyncError(f"Entity beginning at character {start} is not closed.")
        values = {}
        for item in properties:
            values[item["key_lower"]] = item["value"]
        entities.append({
            "index": len(entities),
            "start": start,
            "end": close_token["end"],
            "close_start": close_token["start"],
            "properties": properties,
            "values": values,
        })
    return entities


def _origin(value):
    try:
        parts = [float(part) for part in str(value).replace(",", " ").split()]
    except (TypeError, ValueError):
        return None
    if len(parts) < 3:
        return None
    return tuple(parts[:3])


def _same_origin(left, right, tolerance=0.05):
    a, b = _origin(left), _origin(right)
    return bool(a is not None and b is not None and
                all(abs(a[i] - b[i]) <= float(tolerance) for i in range(3)))


def match_bsp_entities_to_map_entities(
    bsp_entities: list[dict], map_entities: list[dict], *, tolerance: float = 0.05
) -> dict[int, int]:
    """Map BSP entity indices to companion MAP entity indices conservatively.

    A matching classname and origin are required for lights. Worldspawn is
    matched by classname. Same-index matching is preferred when it also agrees
    with those identity fields; ambiguous or unmatched lights stay unlinked.
    """
    mapping = {}
    used = set()
    for bsp_index, source in enumerate(bsp_entities or []):
        classname = str(source.get("classname", "")).casefold()
        if not classname:
            continue
        candidates = [
            item for item in map_entities
            if item["index"] not in used
            and str(item["values"].get("classname", "")).casefold() == classname
        ]
        if classname == "worldspawn":
            if candidates:
                preferred = next((item for item in candidates if item["index"] == bsp_index), candidates[0])
                mapping[bsp_index] = preferred["index"]
                used.add(preferred["index"])
            continue
        if not classname.startswith("light") or not source.get("origin"):
            continue
        matches = [
            item for item in candidates
            if _same_origin(source.get("origin"), item["values"].get("origin"), tolerance)
        ]
        if not matches:
            continue
        preferred = next((item for item in matches if item["index"] == bsp_index), None)
        if preferred is None:
            preferred = min(matches, key=lambda item: (abs(item["index"] - bsp_index), item["index"]))
        mapping[bsp_index] = preferred["index"]
        used.add(preferred["index"])
    return mapping


def _quote(value: str) -> str:
    value = str(value).replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\r", "\\r").replace("\n", "\\n")
    return '"' + value + '"'


def _property_indent(source: str, entity: dict) -> str:
    for item in entity["properties"]:
        line_start = source.rfind("\n", 0, item["key_start"]) + 1
        prefix = source[line_start:item["key_start"]]
        if not prefix.strip():
            return prefix
    return "    "


def _insert_entity_properties(source: str, entity: dict, pairs: list[tuple[str, str]]) -> tuple[int, int, str]:
    newline = "\r\n" if "\r\n" in source else "\n"
    indent = _property_indent(source, entity)
    lines = [f"{indent}{_quote(key)} {_quote(value)}" for key, value in pairs]
    close_line_start = source.rfind("\n", 0, entity["close_start"]) + 1
    close_prefix = source[close_line_start:entity["close_start"]]
    if not close_prefix.strip():
        return close_line_start, close_line_start, newline.join(lines) + newline
    return (
        entity["close_start"], entity["close_start"],
        newline + newline.join(lines) + newline,
    )


def format_entity(entity: dict[str, str], *, indent: str = "    ", newline: str = "\n") -> str:
    lines = ["{"]
    for key, value in entity.items():
        lines.append(f"{indent}{_quote(key)} {_quote(value)}")
    lines.append("}")
    return newline.join(lines)


def apply_entity_changes(
    source: str,
    updates: dict[int, dict[str, str]] | None = None,
    *,
    remove_entities=(),
    append_entities=(),
) -> dict:
    """Patch entity keys and optionally remove/append entities without rebuilding brushes."""
    text = str(source)
    entities = parse_map_entities(text)
    updates = updates or {}
    removals = {int(index) for index in remove_entities}
    if any(index < 0 or index >= len(entities) for index in removals):
        raise MapSyncError("A requested MAP entity removal index is out of range.")
    for raw_index in updates:
        index = int(raw_index)
        if index < 0 or index >= len(entities):
            raise MapSyncError("A requested MAP entity update index is out of range.")
        if index in removals:
            raise MapSyncError("An entity cannot be updated and removed in the same operation.")

    operations = []
    for index, values in updates.items():
        entity = entities[int(index)]
        existing = {}
        for item in entity["properties"]:
            existing.setdefault(item["key_lower"], []).append(item)
        additions = []
        for key, raw_value in values.items():
            if raw_value is None:
                raise MapSyncError(f"Removing MAP key {key!r} is not supported by this safe patch operation.")
            key_text = str(key)
            key_lower = key_text.casefold()
            value_text = str(raw_value)
            matches = existing.get(key_lower, [])
            if matches:
                for item in matches:
                    operations.append((
                        item["value_start"], item["value_end"], _quote(value_text)
                    ))
            else:
                additions.append((key_text, value_text))
        if additions:
            operations.append(_insert_entity_properties(text, entity, additions))

    for index in removals:
        entity = entities[index]
        operations.append((entity["start"], entity["end"], ""))

    for start, end, replacement in sorted(operations, key=lambda item: (item[0], item[1]), reverse=True):
        text = text[:start] + replacement + text[end:]

    newline = "\r\n" if "\r\n" in text else "\n"
    appended_indices = []
    if append_entities:
        current_count = len(parse_map_entities(text))
        suffix = "" if not text else ("" if text.endswith(("\n", "\r")) else newline)
        blocks = [format_entity(item, newline=newline) for item in append_entities]
        text += suffix + (newline + newline).join(blocks) + newline
        appended_indices = list(range(current_count, current_count + len(blocks)))

    output_entities = parse_map_entities(text)
    old_to_new = {
        old_index: old_index - sum(1 for removed in removals if removed < old_index)
        for old_index in range(len(entities)) if old_index not in removals
    }
    if len(output_entities) != len(entities) - len(removals) + len(appended_indices):
        raise MapSyncError("The patched MAP entity count did not validate.")
    return {
        "text": text,
        "old_to_new": old_to_new,
        "appended_indices": appended_indices,
        "removed_indices": sorted(removals),
        "entity_count": len(output_entities),
    }


def write_text_atomic(path: str, text: str) -> None:
    """Atomically replace a MAP file in its destination directory."""
    destination = os.path.abspath(os.path.expanduser(str(path or "")))
    if not destination:
        raise MapSyncError("No MAP output path was supplied.")
    directory = os.path.dirname(destination) or os.getcwd()
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".slopgate-map-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
            handle.write(str(text))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
