"""form.craft: the helper library for designs that need real surfacing, mechanisms, structure and texture.

    from form import craft
    shell = craft.shell(craft.loft_sections([...]), 2.4, openings=craft.faces_at(body, "bottom"))
    h = craft.pin_hinge(length=60, outer_d=8, pin_d=3.6)
    knob = craft.knurl(30, 18, pitch=1.6)

Modules (each also importable on its own, e.g. `from form.craft import mechanisms`):
  surfaces    superellipse / spline profiles, loft_sections, sweep_spline, revolve_profile, shell, safe_fillet,
              variable_fillet, thicken, faces_at
  mechanisms  pin_hinge, living_hinge, cantilever_snap, annular_snap, bayonet, dovetail, detent, ratchet, cam,
              four_bar, four_bar_pose, link, link_between, gear_train, planetary (gears via form.parts)
  fits        ISO 286 iso_fit("H7/g6", d), shaft_limits, hole_limits, bearing_fit
  structure   rib, rib_grid, gusset, boss_array, lattice
  organic     section_body, section_shell, inset_body, inflate, dome_sections, helmet_shell, helmet_sections, grip,
              handle
  texture     B-rep: knurl, spiral_ribbed_body, wrapped_ribs, emboss_cells (capped at MAX_INSTANCES = 2000)
  meshtex     MeshTexture for STL/GLB/renders ("mesh texture; STEP carries the smooth body")
  patterns    form.patterns re-exported (hex_vents, perforation_grid, slot_array, knurl, grip_ribs)
  features    form.feature_helpers re-exported (boss and snap-hook specs written into a design's source)

Every helper validates its numbers and raises a RecipeError naming the argument and a fix. Where a kernel operation
has a sensible fallback (ruled loft, intersection offset, a smaller fillet) it is used and recorded: craft.notes()
returns those notes, so a design can report them instead of hiding them.

form.craft.meshtex imports numpy only; the other modules need build123d (the kernel worker, or a design's build()).
"""
from __future__ import annotations

from ._common import RecipeError, attempt, need, notes, num  # noqa: F401
from .meshtex import LABEL as MESH_TEXTURE_LABEL, MeshTexture  # noqa: F401

_LAZY = {
    "surfaces": ("superellipse", "spline_profile", "polygon_profile", "superellipse_face", "section_at", "plane_on_path",
                 "loft_sections", "sweep_spline", "revolve_profile", "faces_at", "shell", "safe_fillet",
                 "variable_fillet", "thicken"),
    "mechanisms": ("Mech", "overlap", "pin_hinge", "living_hinge", "cantilever_snap", "annular_snap", "bayonet",
                   "dovetail", "detent", "ratchet", "cam", "link", "link_between", "four_bar", "four_bar_pose",
                   "gear_train", "planetary"),
    "fits": ("iso_fit", "shaft_limits", "hole_limits", "bearing_fit"),
    "structure": ("rib", "rib_grid", "gusset", "boss_array", "lattice"),
    "organic": ("section_body", "section_shell", "inset_body", "inflate", "dome_sections", "helmet_shell",
                "helmet_sections", "grip", "handle"),
    "texture": ("knurl", "polyhedron", "spiral_ribbed_body", "wrapped_ribs", "emboss_cells", "MAX_INSTANCES"),
}
_WHERE = {name: mod for mod, names in _LAZY.items() for name in names}


def __getattr__(name):
    """Import the kernel-backed modules on first use, so `from form import craft` works without OCCT."""
    import importlib
    if name in _LAZY or name in ("meshtex",):
        return importlib.import_module(f".{name}", __name__)
    if name == "patterns":
        from .. import patterns
        return patterns
    if name == "features":
        from .. import feature_helpers
        return feature_helpers
    if name in _WHERE:
        return getattr(importlib.import_module(f".{_WHERE[name]}", __name__), name)
    raise AttributeError(f"module 'form.craft' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_WHERE) | set(_LAZY) | {"patterns", "features", "meshtex"})
