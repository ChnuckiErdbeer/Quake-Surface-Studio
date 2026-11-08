"""Command-line wrapper for validating a Quake Surface Studio BSP export.

Run from this directory:
    python qss_export_check.py source.bsp exported.bsp
"""
from __future__ import annotations

import argparse
import sys

try:
    from .export_validation import validate_export_pair
    from . import bsp
except ImportError:
    from export_validation import validate_export_pair
    import bsp


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check QSS BSP export integrity against its source BSP.")
    parser.add_argument("source_bsp", help="Original BSP imported into Blender")
    parser.add_argument("exported_bsp", help="BSP produced by Quake Surface Studio")
    parser.add_argument("--lit", dest="lit_path", help="Optional QLIT v1 .lit sidecar (auto-detected by default)")
    args = parser.parse_args(argv)
    try:
        report = validate_export_pair(args.source_bsp, args.exported_bsp, args.lit_path)
    except (OSError, bsp.BSPError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS: QSS BSP export integrity checks")
    print(f"  Faces: {report['faces']}")
    print(f"  Textures: {report['textures']}")
    print(f"  Texinfo records: {report['texinfos']}")
    print(f"  Classic lighting: {report['classic_lighting_bytes']} bytes "
          f"({report['classic_required_samples']} required samples)")
    if report["enhanced_lighting_samples"] is not None:
        print(f"  Enhanced BSPX lighting: {report['enhanced_lighting_samples']} RGB samples")
    else:
        print("  Enhanced BSPX lighting: not present")
    print(f"  BSPX lumps: {', '.join(report['bspx_lumps']) or '(none)'}")
    print(f"  External .lit sidecar: {'validated' if report['external_lit'] else 'not present'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
