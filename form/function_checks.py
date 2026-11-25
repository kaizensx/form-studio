"""Does it work: checks of what a declared interface is for, not only of its gap.

A thread that does not engage, or a ratchet whose pawl rides over teeth lower than its play, passes every gap and
overlap check. These rows measure the function on the solids, from a declared interface (form/recipes/assembly.py
Mate: kind "thread" or "ratchet" with axis= and origin=; form/assembly.py adds the rows), or when a design or a
mechanism calls them directly:

    thread_engagement(rod, nut, axis, origin, pitch)   the nut's ridges inside the screw's major diameter, as a
                                                       volume, a radial depth and an engaged length (computed)
    ratchet_engagement(wheel, pawl, axis, origin, clearance)
                                                       how deep the pawl reaches into the teeth against the play
                                                       (computed); the lock thresholds are rules of thumb (heuristic)
    snap_strain(thickness, undercut, length, allow)    cantilever strain 1.5 t y / L² against an allowed strain
                                                       (heuristic: a beam formula and a rule-of-thumb limit)

Each returns one row in form/checks.py's shape (id, label, status, value, detail, evidence). Measurements are taken
on the B-rep (a boolean volume) and on a fine tessellation (radii about the axis); thresholds are stated in the row.
"""
from __future__ import annotations

import math

import numpy as np

TESS = 0.02                                  # mm: tessellation for radii about an axis


def _row(id_, label, status, value, detail, evidence="computed", **kw):
    return {"id": id_, "label": label, "status": status, "value": value, "detail": detail, "evidence": evidence, **kw}


def _frame(axis, origin):
    a = np.asarray(axis, float)
    a = a / (np.linalg.norm(a) or 1.0)
    return a, np.asarray(origin, float)


def _radial(shape, axis, origin) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(r, z, angle) of the shape's tessellation vertices about the axis."""
    a, o = _frame(axis, origin)
    verts, _tris = shape.tessellate(TESS)
    P = np.array([[v.X, v.Y, v.Z] for v in verts], float) - o
    z = P @ a
    radial = P - np.outer(z, a)
    r = np.linalg.norm(radial, axis=1)
    ref = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1.0, 0])
    ref /= np.linalg.norm(ref)
    ang = np.arctan2(radial @ np.cross(a, ref), radial @ ref)
    return r, z, ang


def _cylinder(r: float, z0: float, z1: float, axis, origin):
    from build123d import Align, Cylinder, Plane
    a, o = _frame(axis, origin)
    pl = Plane(origin=tuple(o + a * z0), z_dir=tuple(a))
    return pl * Cylinder(r, z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def thread_engagement(rod, nut, axis=(0, 0, 1), origin=(0, 0, 0), pitch: float | None = None,
                      label: str = "Thread engages", id_: str = "fn_thread") -> dict:
    """The screw (rod) in the threaded part (nut), placed as assembled. Engaged volume: the nut's material inside the
    screw's major diameter over the length they share (B-rep boolean). Zero means a plain hole: the screw turns
    without gripping. Radial depth: the screw's major radius minus the nut's minor radius."""
    rr, rz, _ = _radial(rod, axis, origin)
    nr, nz, _ = _radial(nut, axis, origin)
    rod_major = float(rr.max())
    z0, z1 = max(float(rz.min()), float(nz.min())), min(float(rz.max()), float(nz.max()))
    length = max(0.0, z1 - z0)
    near = (nz >= z0) & (nz <= z1) & (nr < rod_major + (pitch or 1.0) * 2)
    nut_minor = float(nr[near].min()) if near.any() else float("inf")
    depth = rod_major - nut_minor
    vol = 0.0
    if length > 0:
        try:
            inter = nut & _cylinder(rod_major, z0, z1, axis, origin)
            vol = float(inter.volume) if inter is not None else 0.0
        except Exception:                    # noqa: BLE001 - a failed boolean is said, never read as engagement
            vol = float("nan")
    p = pitch or 0.0
    basic = 0.541266 * p if p else None        # ISO 68-1 basic thread engagement depth 5H/8
    value = f"{vol:.1f} mm³ engaged, {max(depth, 0):.2f} mm deep over {length:.1f} mm"
    detail = (f"Measured on the solids as assembled: the threaded part's material inside the screw's major diameter "
              f"(Ø{2 * rod_major:.2f} mm) over the {length:.2f} mm they share is {vol:.2f} mm³ (B-rep boolean); the "
              f"screw's crest reaches {depth:.2f} mm past the hole's minor radius (tessellation ±{TESS} mm).")
    if not math.isfinite(vol):
        return _row(id_, label, "WARN", "not measured", detail + " The boolean failed, so engagement is unknown.")
    if length <= 0:
        return _row(id_, label, "FAIL", "no shared length", detail + " The screw and the threaded part do not overlap "
                    "along the axis: nothing engages.")
    if vol <= 1e-3 or depth <= TESS:
        return _row(id_, label, "FAIL", value, detail + " Nothing inside the screw's major diameter: the hole has no thread "
                    "ridges (a plain bore), so the screw turns without gripping.")
    if p and length < 2 * p:
        return _row(id_, label, "WARN", value, detail + f" Under two pitches ({2 * p:g} mm) of engagement: the thread "
                    "can strip (heuristic).", evidence="heuristic")
    if basic and depth < 0.5 * basic:
        return _row(id_, label, "WARN", value, detail + f" Under half the ISO basic engagement depth ({basic:.2f} mm for "
                    f"pitch {p:g}): a shallow thread strips under load (heuristic).", evidence="heuristic")
    return _row(id_, label, "PASS", value, detail)


def _outline_radii(wheel, axis, origin) -> tuple[float, float]:
    """(tip, root) radius of a toothed wheel: the largest and smallest radius along the outer edge of its largest
    flat face across the axis (sampled along every edge, so a long straight tooth flank is measured, not only its
    corners)."""
    a, o = _frame(axis, origin)
    flat = [f for f in wheel.faces() if f.geom_type.name == "PLANE" and abs(abs(np.dot(tuple(f.normal_at()), a)) - 1) < 1e-6]
    if not flat:
        r, _z, _ = _radial(wheel, axis, origin)
        return float(r.max()), float(r.max())
    face = max(flat, key=lambda f: f.area)
    pts = []
    for e in face.outer_wire().edges():
        for t in np.linspace(0, 1, 25):
            p = e.position_at(float(t))
            pts.append((p.X, p.Y, p.Z))
    P = np.array(pts) - o
    rad = P - np.outer(P @ a, a)
    r = np.linalg.norm(rad, axis=1)
    return float(r.max()), float(r.min())


def ratchet_engagement(wheel, pawl, axis=(0, 0, 1), origin=(0, 0, 0), clearance: float = 0.3,
                       label: str = "Ratchet locks", id_: str = "fn_ratchet") -> dict:
    """The pawl in its locking pose against the toothed wheel. Tooth height: the wheel's tip radius minus its root
    radius, along the outer edge of its face. Reach: how far the pawl's tip goes inside the tip
    radius. The pawl locks only when that reach exceeds the play: with `clearance` (per side, the declared or assumed
    printed gap) on the tooth face and on the pivot, a reach under 2 x clearance lets the pawl ride over; under
    0.5 mm or a third of the tooth it holds unreliably (thresholds: rules of thumb, heuristic)."""
    pr, _pz, _pa = _radial(pawl, axis, origin)
    tip, root = _outline_radii(wheel, axis, origin)
    tooth = tip - root
    reach = max(0.0, tip - float(pr.min()))
    engaged = min(reach, tooth)
    play = 2 * clearance
    margin = engaged - play
    play_deg = math.degrees(play / max(root, 1e-6))
    value = f"{engaged:.2f} mm engaged, {play:.2f} mm play"
    detail = (f"Measured on the solids as assembled: teeth {tooth:.2f} mm high (tip Ø{2 * tip:.2f}, root Ø{2 * root:.2f} mm), "
              f"the pawl reaches {reach:.2f} mm inside the tips, so {engaged:.2f} mm of the locking face is engaged "
              f"(computed, tessellation ±{TESS} mm). Play from a {clearance:g} mm clearance per side: {play:.2f} mm "
              f"(about {play_deg:.1f}° at the root).")
    if engaged <= play:
        return _row(id_, label, "FAIL", value, detail + " The engaged depth is not more than the play: the pawl can ride "
                    "over the teeth instead of locking. Raise the teeth or let the pawl reach deeper (heuristic).",
                    evidence="heuristic")
    if engaged < 0.5 or engaged < tooth / 3:
        return _row(id_, label, "WARN", value, detail + f" Only {margin:.2f} mm more than the play: it may slip under load "
                    "or once the printed teeth wear (heuristic).", evidence="heuristic")
    return _row(id_, label, "PASS", value, detail + f" {margin:.2f} mm more than the play.", evidence="heuristic")


def snap_strain(thickness: float, undercut: float, length: float, allow: float = 0.02,
                label: str = "Snap strain", id_: str = "fn_snap") -> dict:
    """Cantilever snap hook: strain e = 1.5 t y / L² (constant rectangular section, deflection y at the tip). 2 % is a
    rule of thumb for printed PLA/PETG along the layers; pass the material's own value as allow."""
    e = 1.5 * thickness * undercut / max(length, 1e-9) ** 2
    st = "PASS" if e <= allow else ("WARN" if e <= 1.5 * allow else "FAIL")
    return _row(id_, label, st, f"{e * 100:.2f} % (allowed {allow * 100:.1f} %)",
                f"Beam formula 1.5 t y / L² with t {thickness:g} mm, undercut {undercut:g} mm, beam {length:g} mm. A "
                "beam model and a rule-of-thumb limit, not a test of the part.", evidence="heuristic")
