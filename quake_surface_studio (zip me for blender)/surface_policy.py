"""Quake BSP surface policy for SLOPGATE viewport and light baking.

Compiler-only surfaces are retained in the imported mesh and BSP export, but
are not treated as visible lightmap receivers or ordinary shadow occluders.
The special blocklight surface remains invisible and does not receive light,
but deliberately continues to occlude light rays.
"""

from __future__ import annotations


POLICY_RENDER = "RENDER"
POLICY_NODRAW = "NODRAW"
POLICY_NODRAW_BLOCKER = "NODRAW_BLOCKER"

# Exact names and conventional variants used by Quake-family map compilers.
# A suffix is accepted only when separated by an underscore, hyphen, dot, or
# digit so ordinary texture names such as "triggered" and "clipboard" survive.
_NODRAW_NAMES = {
    "trigger",
    "clip",
    "origin",
    "hint",
    "skip",
    "hintskip",
    "null",
    "nodraw",
    "bevel",
    "aaatrigger",
    "playerclip",
    "monsterclip",
    "npcclip",
    "weaponclip",
    "weapclip",
    "areaportal",
}

# Deliberately invisible but semantically opaque to light.
_LIGHT_BLOCKER_NAMES = {"blocklight"}


def normalize_texture_name(name: str) -> str:
    """Normalize a BSP texture name without changing its identity otherwise."""
    value = str(name or "").strip().replace("\\", "/")
    value = value.rsplit("/", 1)[-1].rstrip("\x00").strip().casefold()
    # Quake uses these leading markers for masked and turbulent textures.
    # They are not themselves nodraw flags, so classify the remaining name.
    while value.startswith(("{", "*")):
        value = value[1:]
    return value.strip()


def _matches_name_or_variant(value: str, base: str) -> bool:
    if value == base:
        return True
    if not value.startswith(base) or len(value) <= len(base):
        return False
    return value[len(base)] in "_-.0123456789"


def classify_texture(name: str) -> str:
    """Return RENDER, NODRAW, or NODRAW_BLOCKER for a Quake miptex name."""
    value = normalize_texture_name(name)
    if not value:
        return POLICY_RENDER
    if any(_matches_name_or_variant(value, base) for base in _LIGHT_BLOCKER_NAMES):
        return POLICY_NODRAW_BLOCKER
    if any(_matches_name_or_variant(value, base) for base in _NODRAW_NAMES):
        return POLICY_NODRAW
    return POLICY_RENDER


def is_nodraw_policy(policy: str) -> bool:
    """Whether a stored material policy should be invisible in the viewport."""
    return str(policy or "").upper() in {POLICY_NODRAW, POLICY_NODRAW_BLOCKER}


def policy_receives_light(policy: str) -> bool:
    """Whether a surface should receive a baked lightmap."""
    return str(policy or "").upper() == POLICY_RENDER


def receives_light(name: str) -> bool:
    """Whether a texture name represents a lightmap-receiving surface."""
    return policy_receives_light(classify_texture(name))


def policy_casts_light_shadow(policy: str) -> bool:
    """Whether a surface should occlude light rays during the direct bake."""
    return str(policy or "").upper() in {POLICY_RENDER, POLICY_NODRAW_BLOCKER}


def casts_light_shadow(name: str) -> bool:
    """Whether a texture name should occlude light rays during the direct bake."""
    return policy_casts_light_shadow(classify_texture(name))


__all__ = [
    "POLICY_RENDER",
    "POLICY_NODRAW",
    "POLICY_NODRAW_BLOCKER",
    "normalize_texture_name",
    "classify_texture",
    "is_nodraw_policy",
    "policy_receives_light",
    "receives_light",
    "policy_casts_light_shadow",
    "casts_light_shadow",
]
