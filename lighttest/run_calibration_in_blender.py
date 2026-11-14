"""Run the Slipgate light calibration from Blender's Text Editor.

Open this file in Blender and choose Text > Run Script.
It compiles both calibration variants, then commits and pushes only the
new results_<timestamp> folder to the configured GitHub branch.

The script does not modify the source MAP/BSP or any other project files.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import bpy


BRANCH = "fix/v0.11.1-metadata-style-order-test"
TOOLS_DIR = Path(
    "/mnt/sde1/FPS/IdTech2/QuakeDev/##tools/ericw-tools-2.0.0-alpha11-Linux"
)
REPO_FOLDER_NAME = "Quake-Surface-Studio"


def log(message: str) -> None:
    print(f"[Slipgate calibration] {message}", flush=True)


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Git command failed: git {' '.join(args)}")
    return result


def locate_repository() -> Path:
    candidates = []

    # When opened from disk, Blender normally retains the source filepath.
    space = getattr(bpy.context, "space_data", None)
    text_block = getattr(space, "text", None)
    text_path = getattr(text_block, "filepath", "") if text_block else ""
    if text_path:
        candidates.append(Path(bpy.path.abspath(text_path)).expanduser().resolve().parent.parent)

    # Standard clone location used in the setup instructions.
    candidates.append(Path.home() / REPO_FOLDER_NAME)

    for candidate in candidates:
        if (candidate / ".git").exists() and (candidate / "lighttest" / "run_lighttest_calibration.py").is_file():
            return candidate.resolve()

    searched = "\n".join(f"  {path}" for path in candidates)
    raise RuntimeError(
        "Could not locate the local repository. Expected the clone at "
        f"~/{REPO_FOLDER_NAME} or this launcher inside its lighttest folder.\n"
        f"Checked:\n{searched}"
    )


def main() -> None:
    repo = locate_repository()
    lighttest = repo / "lighttest"
    runner = lighttest / "run_lighttest_calibration.py"
    source_map = lighttest / "lighttest01-compile.map"

    log(f"Repository: {repo}")
    log(f"Branch required: {BRANCH}")

    branch = run_git(repo, "branch", "--show-current").stdout.strip()
    if branch != BRANCH:
        raise RuntimeError(f"Wrong Git branch: {branch!r}. Check out {BRANCH!r} first.")

    # Refuse to mix calibration outputs with unrelated local work.
    status = run_git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if status:
        raise RuntimeError(
            "The repository has local changes or untracked files. Nothing was compiled or uploaded.\n"
            "Please commit/stash those changes or use a clean clone, then run this launcher again."
        )

    if not runner.is_file() or not source_map.is_file():
        raise RuntimeError("The calibration runner or source MAP is missing from lighttest/.")

    runner_text = runner.read_text(encoding="utf-8")
    required_markers = ("sample_z", "plane_sign", "sample_floor_luxel")
    missing_markers = [marker for marker in required_markers if marker not in runner_text]
    if missing_markers:
        raise RuntimeError(
            "The calibration runner is not the corrected sampler version. Missing markers: "
            + ", ".join(missing_markers)
            + ". Pull the latest branch before running."
        )

    if not TOOLS_DIR.is_dir():
        raise RuntimeError(f"ericw-tools folder not found: {TOOLS_DIR}")
    for executable in ("qbsp", "vis", "light"):
        path = TOOLS_DIR / executable
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"Required executable is missing or not executable: {path}")

    python = shutil.which("python3")
    if not python:
        raise RuntimeError("Could not find python3 on PATH. Start Blender from an environment with Python 3 available.")

    before = {path.resolve() for path in lighttest.glob("results_*") if path.is_dir()}
    command = [
        python,
        str(runner),
        "--compile",
        "--tools-dir",
        str(TOOLS_DIR),
    ]

    log("Starting both calibration compiles. Blender may appear busy while the tools run.")
    log("The original MAP and BSP are read-only inputs; the runner creates a new timestamped results folder.")
    result = subprocess.run(command, cwd=str(lighttest))
    if result.returncode:
        raise RuntimeError(
            f"Calibration runner exited with status {result.returncode}. "
            "Any partial diagnostic output remains in lighttest/; nothing was committed or pushed."
        )

    after = {path.resolve() for path in lighttest.glob("results_*") if path.is_dir()}
    created = sorted(after - before)
    if len(created) != 1:
        raise RuntimeError(
            f"Expected exactly one new results folder, found {len(created)}. "
            "Nothing was committed or pushed."
        )

    output_dir = created[0]
    summary_path = output_dir / "calibration_summary.json"
    if not summary_path.is_file():
        raise RuntimeError(
            f"Missing {summary_path.name}; results remain local and were not uploaded."
        )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    reports = summary.get("variants", [])
    if len(reports) != 2:
        raise RuntimeError("The summary does not contain both expected calibration variants.")

    log("Calibration summary:")
    for report in reports:
        samples = report.get("sample_results", {})
        written = samples.get("samples_written", 0)
        missing = samples.get("missing_samples", 0)
        styles = report.get("switchable_light_styles")
        log(
            f"  {report.get('variant')}: samples={written}, "
            f"missing={missing}, switchable_styles={styles}"
        )
        if missing:
            log("  WARNING: Some luxel samples are missing; uploading diagnostics for inspection.")

    relative_output = output_dir.relative_to(repo).as_posix()
    log(f"Staging only: {relative_output}")
    run_git(repo, "add", "-f", "--", relative_output)

    staged = run_git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    if not staged:
        raise RuntimeError("Git staged no result files. Nothing was committed or pushed.")
    unexpected = [path for path in staged if not (path == relative_output or path.startswith(relative_output + "/"))]
    if unexpected:
        run_git(repo, "reset", "--", *staged, check=False)
        raise RuntimeError(
            "Safety check failed: files outside the new results folder were staged: "
            + ", ".join(unexpected)
        )

    run_git(
        repo,
        "commit",
        "-m",
        f"Add light calibration results {output_dir.name}",
    )
    log(f"Pushing results to origin/{BRANCH}")
    run_git(repo, "push", "origin", BRANCH)

    log("SUCCESS: calibration results committed and pushed to GitHub.")
    log(f"Uploaded folder: {relative_output}")


try:
    main()
except Exception as exc:
    log(f"STOPPED: {exc}")
    log("No source MAP/BSP files or unrelated project files were intentionally changed.")
finally:
    log("Finished.")
