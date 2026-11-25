"""form.craft: the helper library for designs that need real surfacing, mechanisms, structure and texture.

    from form import craft
    shell = craft.shell(craft.loft_sections([...]), 2.4, openings=craft.faces_at(body, "bottom"))
    h = craft.pin_hinge(length=60, outer_d=8, pin_d=3.6)
    knob = craft.knurl(30, 18, pitch=1.6)

Modules (each also importable on its own, e.g. `from form.craft import mechanisms`):
  surfaces    superellipse / spline profiles, loft_sections, sweep_spline, revolve_profile, shell, safe_fillet,
              variable_fillet, thicken, faces_at, cut and fuse (booleans with fuzzy fallbacks)
  mechanisms  pin_hinge, living_hinge, cantilever_snap, annular_snap, bayonet, dovetail, detent, ratchet, cam,
              four_bar, four_bar_pose, link, link_between, gear_train, planetary (gears via form.parts)
  fits        ISO 286 iso_fit("H7/g6", d), shaft_limits, hole_limits, bearing_fit
  structure   rib, rib_grid, gusset, boss_array, lattice
  organic     section_body, section_shell, inset_body, inflate, dome_sections, helmet_shell, helmet_sections, grip,
              handle; silhouette-driven forms: curve, profile_sections, check_sections, loft_report, checked_body;
              details that follow a surface: two_view_cutter, surface_band, slot_grille; product families from
              named proportions: head_form, helmet_fullface, helmet_open, mouse_form, bottle_profile, grip_sections
              (tables HEADFORMS, ANSUR_HEAD, ANSUR_HAND, HELMET_LAYERS, PCO1881); magnets and splits on sculpted
              bodies: surface_point, magnet_boss, magnet_pocket, split_with_magnets, split_spots;
              radial_grid_heightmap (web_heightmap is its deprecated name)
  subd        the skin route for organic shells: skin_from_sections (a section stack fitted as one B-spline grid,
              its deviation measured) returns a Skin: .shell(wall) (three faces), .band(amount, region, depth),
              .layer(lo, hi), .offset(d), .ray(...); offset_grid (a true parametric offset); cages and handles:
              Cage (a quad cage with creases, open borders and named regions to exact CAD patches), region_frame
              and region_tool (where a feature goes on a named region, and a solid that follows it), subdivide and
              limit_points (Catmull-Clark levels and limit positions), voxel_cage, quad_sphere, fit_cage
  assemble    separate parts and their joints: parts(name=solid, ..., clearance) (every pair's gap measured; use it
              instead of fuse(a, b, max_solids=2, min_solids=2)), named_parts, part_list (assembly Parts by a point
              inside each), split (an insert out of a skin shell, resting on a lip), lens (a part from the inner
              offset skin), MAGNETS stock (6x2, 6x3, 8x3, 10x3) with MAGNET_FITS (press, glue, printed) and
              MAGNET_FLOOR (0.6 mm), magnet, magnet_pair (coaxial pockets by construction; pull force unknown unless
              a datasheet value is given), coaxial_error
  safe       operations that degrade gracefully, each fallback noted: safe_union, safe_cut, safe_intersect,
              safe_fillet, safe_chamfer, safe_loft (re-seamed, ruled, pairwise), safe_shell, safe_sweep; repair
              (ShapeFix + face merge), inspect (validity, faults, shortest edge), reseam (sections for a loft)
  finish      finish_cut: decorative cuts (flutes, grooves) each only as deep as the wall behind it allows
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
from . import boolean  # noqa: F401  (craft.boolean.run / diagnose / last)
from .meshtex import LABEL as MESH_TEXTURE_LABEL, MeshTexture  # noqa: F401

_LAZY = {
    "surfaces": ("superellipse", "spline_profile", "polygon_profile", "superellipse_face", "section_at", "plane_on_path",
                 "loft_sections", "sweep_spline", "revolve_profile", "faces_at", "shell", "safe_fillet",
                 "variable_fillet", "thicken", "cut", "fuse"),
    "mechanisms": ("Mech", "overlap", "pin_hinge", "living_hinge", "cantilever_snap", "annular_snap", "bayonet",
                   "dovetail", "detent", "ratchet", "cam", "link", "link_between", "four_bar", "four_bar_pose",
                   "gear_train", "planetary"),
    "fits": ("iso_fit", "shaft_limits", "hole_limits", "bearing_fit"),
    "structure": ("rib", "rib_grid", "gusset", "boss_array", "lattice"),
    "organic": ("section_body", "section_shell", "inset_body", "inflate", "dome_sections", "helmet_shell",
                "helmet_sections", "grip", "handle", "curve", "profile_sections", "check_sections", "loft_report",
                "checked_body", "two_view_cutter", "grow_outline", "surface_band", "offset_body", "slot_grille", "head_form", "helmet_fullface",
                "helmet_open", "mouse_form", "bottle_profile", "grip_sections", "HEADFORMS", "ANSUR_HEAD",
                "ANSUR_HAND", "HELMET_LAYERS", "PCO1881", "surface_point", "magnet_boss", "magnet_pocket",
                "split_with_magnets", "split_spots", "radial_grid_heightmap"),
    "safe": ("safe_union", "safe_cut", "safe_intersect", "safe_chamfer", "safe_loft", "safe_shell", "safe_sweep",
             "repair", "inspect", "reseam", "BRIDGE"),
    "finish": ("finish_cut",),
    "texture": ("knurl", "polyhedron", "spiral_ribbed_body", "wrapped_ribs", "emboss_cells", "MAX_INSTANCES"),
    "assemble": ("parts", "named_parts", "part_list", "inside_point", "split", "Split", "lens", "MAGNETS", "MAGNET_FITS",
                 "MAGNET_FLOOR", "magnet", "magnet_pair", "MagnetPair", "pocket_axes", "coaxial_error"),
    "subd": ("skin_from_sections", "Skin", "offset_grid", "Cage", "region_frame", "region_tool", "subdivide",
             "limit_points", "voxel_cage", "quad_sphere", "fit_cage"),
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
