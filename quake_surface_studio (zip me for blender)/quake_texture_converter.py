"""Retired standalone converter entry point.

QSS now executes the material-zone Quake palette conversion directly inside
Blender's Python process. The implementation lives in palette_utils.py and is
invoked by QSS_OT_convert_quake_palette; no subprocess or third-party package
is used. The original experimental standalone tool remains in the repository's
related tools folder for reference.
"""
