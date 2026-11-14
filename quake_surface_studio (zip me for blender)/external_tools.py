"""External compiler and Quake-engine integration helpers for QSS.

This module intentionally has no Blender dependency. It resolves ericw-tools,
builds safe Ironwail command lines, launches the interactive engine with a
persistent log, and executes compiler processes with bounded timeouts.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Iterable

ERICW_TOOL_NAMES = {
    "qbsp": ("qbsp", "qbsp.exe"),
    "vis": ("vis", "vis.exe"),
    "light": ("light", "light.exe"),
    "bspinfo": ("bspinfo", "bspinfo.exe"),
    "bsputil": ("bsputil", "bsputil.exe"),
}


def resolve_tool(tool_directory: str, tool_name: str) -> str:
    """Resolve a known ericw executable from a configured directory."""
    key = str(tool_name or "").strip().lower()
    if key not in ERICW_TOOL_NAMES:
        raise ValueError(f"Unknown ericw tool: {tool_name!r}")
    directory = os.path.abspath(os.path.expandvars(os.path.expanduser(tool_directory or "")))
    if not os.path.isdir(directory):
        return ""
    try:
        entries = {name.casefold(): name for name in os.listdir(directory)}
    except OSError:
        return ""
    for candidate in ERICW_TOOL_NAMES[key]:
        actual = entries.get(candidate.casefold())
        if actual:
            path = os.path.join(directory, actual)
            if os.path.isfile(path):
                return os.path.abspath(path)
    return ""


def discover_tools(tool_directory: str) -> dict[str, str]:
    """Return absolute executable paths for every known ericw tool."""
    return {name: resolve_tool(tool_directory, name) for name in ERICW_TOOL_NAMES}



def build_qbsp_command(
    executable: str,
    map_path: str,
    output_bsp: str,
    *,
    quake_root: str = "",
    game_dir: str = "",
    wad_paths: Iterable[str] = (),
    search_paths: Iterable[str] = (),
    verbose: bool = True,
) -> list[str]:
    """Build a safe ericw QBSP command for a MAP file and explicit BSP output.

    The caller owns the output directory and working directory. The function
    never invokes a shell and never derives an output path beside the source MAP.
    """
    raw_executable = str(executable or "").strip()
    if not raw_executable:
        raise ValueError("No ericw-tools qbsp executable was configured.")
    exe = os.path.abspath(os.path.expandvars(os.path.expanduser(raw_executable)))
    source = os.path.abspath(os.path.expandvars(os.path.expanduser(map_path or "")))
    destination = os.path.abspath(os.path.expandvars(os.path.expanduser(output_bsp or "")))
    if not source or not source.lower().endswith(".map"):
        raise ValueError("Select a source .map file.")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    if not destination or not destination.lower().endswith(".bsp"):
        raise ValueError("The QBSP output path must end in .bsp.")
    if os.path.normcase(source) == os.path.normcase(destination):
        raise ValueError("The QBSP output must not overwrite the source MAP.")

    command = [exe]
    if verbose:
        command.append("-verbose")

    root = os.path.abspath(os.path.expandvars(os.path.expanduser(quake_root))) if quake_root else ""
    game = os.path.abspath(os.path.expandvars(os.path.expanduser(game_dir))) if game_dir else ""
    if root and os.path.isdir(root):
        command.extend(["-basedir", root])
    if game and os.path.isdir(game):
        command.extend(["-gamedir", game])

    def append_directories(option: str, directories: Iterable[str]) -> None:
        seen = set()
        for directory in directories or ():
            if not directory:
                continue
            path = os.path.abspath(os.path.expandvars(os.path.expanduser(str(directory))))
            key = os.path.normcase(path)
            if key in seen or not os.path.isdir(path):
                continue
            seen.add(key)
            command.extend([option, path])

    append_directories("-wadpath", wad_paths)
    append_directories("-path", search_paths)
    command.extend([source, destination])
    return command


def build_decoupled_light_command(
    executable: str,
    bsp_path: str,
    *,
    world_units_per_luxel: float = 16.0,
    quake_root: str = "",
    game_dir: str = "",
) -> list[str]:
    """Build an ericw light command that writes DECOUPLED_LM into a BSP copy."""
    import math

    exe = os.path.abspath(os.path.expandvars(os.path.expanduser(executable or "")))
    source = os.path.abspath(os.path.expandvars(os.path.expanduser(bsp_path or "")))
    scale = float(world_units_per_luxel)
    if not exe:
        raise ValueError("No ericw-tools light executable was configured.")
    if not source or not source.lower().endswith(".bsp"):
        raise ValueError("Select a source .bsp file.")
    if not math.isfinite(scale) or not 0.0 < scale <= 1024.0:
        raise ValueError("World units per luxel must be greater than 0 and at most 1024.")

    command = [exe, "-verbose", "-world_units_per_luxel", f"{scale:g}"]
    root = os.path.abspath(os.path.expanduser(quake_root)) if quake_root else ""
    game = os.path.abspath(os.path.expanduser(game_dir)) if game_dir else ""
    if root and os.path.isdir(root):
        command.extend(["-basedir", root])
    if game and os.path.isdir(game):
        command.extend(["-gamedir", game])
    command.append(source)
    return command


def run_command(
    executable: str,
    arguments: Iterable[str] = (),
    *,
    timeout: float = 300.0,
    cwd: str | None = None,
) -> dict:
    """Run an external tool without a shell and return captured diagnostics."""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(executable or "")))
    command = [path, *(str(item) for item in arguments)]
    started = time.monotonic()
    if not path or not os.path.isfile(path):
        return {
            "status": "MISSING", "command": command, "returncode": None,
            "duration_seconds": 0.0, "stdout": "", "stderr": "Executable not found.",
        }
    try:
        completed = subprocess.run(
            command, cwd=cwd or os.path.dirname(path), shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            timeout=max(1.0, float(timeout)), check=False,
        )
        output = completed.stdout or ""
        return {
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "command": command, "returncode": int(completed.returncode),
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": output, "stderr": "",
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        error = exc.stderr or ""
        if isinstance(error, bytes):
            error = error.decode("utf-8", "replace")
        return {
            "status": "TIMEOUT", "command": command, "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": str(output), "stderr": str(error) or f"Timed out after {timeout:g}s.",
        }
    except OSError as exc:
        return {
            "status": "ERROR", "command": command, "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": "", "stderr": str(exc),
        }


def _inside_directory(path: str, parent: str) -> str:
    absolute = os.path.abspath(os.path.expanduser(path))
    base = os.path.abspath(os.path.expanduser(parent))
    relative = os.path.relpath(absolute, base)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        raise ValueError(f"Path is outside the configured game directory: {path}")
    return relative.replace(os.sep, "/")


def build_ironwail_command(
    executable: str,
    quake_root: str,
    game_dir: str,
    *,
    map_path: str = "",
    demo_file: str = "",
    timedemo: bool = False,
    developer_mode: bool = True,
) -> list[str]:
    """Build an Ironwail command for a map or a demo inside the active game.

    Exactly one of map_path or demo_file may be supplied. The target is passed
    as a Quake virtual path, never as a shell command or arbitrary command text.
    """
    if bool(map_path) == bool(demo_file):
        raise ValueError("Choose exactly one map or demo target.")
    command = [os.path.abspath(os.path.expanduser(executable))]
    root = os.path.abspath(os.path.expanduser(quake_root))
    game = os.path.abspath(os.path.expanduser(game_dir))
    if root and os.path.isdir(root):
        command.extend(["-basedir", root])
        try:
            relative_game = _inside_directory(game, root)
        except ValueError:
            relative_game = ""
        if relative_game == ".":
            # A game directory that is itself the root has no id1/mod child;
            # make it the engine's base directory rather than relying on id1.
            command[1:3] = ["-basedir", game]
        elif relative_game and relative_game != "id1":
            command.extend(["-game", relative_game])
        elif not relative_game and game and os.path.isdir(game):
            # A separately selected game directory is usable as the base dir.
            command[1:3] = ["-basedir", game]
    if developer_mode:
        command.extend(["-condebug", "+developer", "1"])
    if map_path:
        target = str(map_path).replace("\\", "/").strip()
        if target.lower().startswith("maps/"):
            target = target[5:]
        if target.lower().endswith(".bsp"):
            target = target[:-4]
        if not target or target.startswith("/") or ".." in target.split("/"):
            raise ValueError(f"Invalid Quake map path: {map_path!r}")
        command.extend(["+map", target])
    else:
        relative = _inside_directory(demo_file, game)
        if not relative.lower().endswith(".dem"):
            raise ValueError("Demo file must have a .dem extension.")
        target = relative[:-4]
        command.extend(["+timedemo" if timedemo else "+playdemo", target])
    return command


def launch_process_handle(command: Iterable[str], *, cwd: str, log_path: str) -> subprocess.Popen:
    """Launch a detached GUI process and return its handle for lifecycle cleanup."""
    args = [str(item) for item in command]
    if not args or not os.path.isfile(args[0]):
        raise FileNotFoundError(args[0] if args else "No executable specified")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8", errors="replace")
    try:
        kwargs = {
            "cwd": cwd or os.path.dirname(args[0]),
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "shell": False,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(args, **kwargs)
    finally:
        log_handle.close()


def launch_process(command: Iterable[str], *, cwd: str, log_path: str) -> int:
    """Launch a detached GUI process and return its PID."""
    return int(launch_process_handle(command, cwd=cwd, log_path=log_path).pid)
