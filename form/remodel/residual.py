"""reference_residual: what is left between a design and the mesh it rebuilds, as a named work list of bodies.

compare_to_reference says how far the two surfaces are apart and where. This says what to build next: the material
the mesh has and the design lacks ("missing": add it) and the material the design has and the mesh lacks ("extra":
cut it), each as one body with its volume, centre, principal axis, size and shape (cylinder, box or body), and its
angle and radius about an axis, so that bodies repeated around a circle read as one polar pattern at equal angles and
bodies on a row or a grid read as a linear or grid pattern. One body or one pattern is one feature to add.

How: both solids are filled on one shared voxel grid (occupancy.py, rays along Z, even-odd rule), the two
differences are opened by one voxel (a skin thinner than two voxels is tessellation, not a feature) and split into
connected bodies. When manifold3d is installed and both meshes are closed manifolds, each body's volume and centre
come from the exact boolean difference instead of the voxels (volume_method says which).

The idea of the residual as a work list of missing and extra bodies, with angles about an axis so polar patterns
read as equal angles, comes from kulibinai/cadmageddon (contrib/instruments/residual.py at 368fb87, MIT). This is
an independent implementation; no code was copied.

numpy and scipy only (manifold3d optional): no OCCT. Evidence: computed on the design's tessellation and the mesh
as given, to about half a voxel at the surface.
"""
from __future__ import annotations

import math

import numpy as np

from .analyze import _r, where

AXES = {"x": 0, "y": 1, "z": 2}


def _grids(V, F, P, T, h: float | None, max_cells: int):
    """Both solids on one grid: the occupancy of each is built over the union of the two meshes' vertices."""
    from .occupancy import Occupancy
    W = np.vstack([V, P])
    span = np.ptp(W, axis=0)
    if h is None:
        h = max(float(span.max()) / 240, 0.1)
    h = float(h)
    pad = 2 * h
    ref = Occupancy(W, F, h=h, pad=pad, max_cells=max_cells)
    des = Occupancy(W, T + len(V), h=h, pad=pad, max_cells=max_cells)
    assert ref.h == des.h and np.allclose(ref.lo, des.lo)
    return ref, des


def _weld(V, F):
    from ..recon.mesh import weld
    return weld(V[F], 1e-6)[:2]


def _manifold(V, F):
    try:
        import manifold3d as m3
    except ImportError:
        return None
    try:
        V, F = _weld(np.asarray(V, dtype=np.float64), np.asarray(F, dtype=np.int64))
        mf = m3.Manifold(m3.Mesh(vert_properties=V.astype(np.float32), tri_verts=F.astype(np.uint32)))
        if mf.status() != m3.Error.NoError or mf.is_empty():
            return None
        return mf
    except Exception:                                   # noqa: BLE001
        return None


def _mesh_props(mf) -> tuple[float, np.ndarray]:
    """Volume and centroid of a manifold, by the divergence theorem over its triangles."""
    mesh = mf.to_mesh()
    V = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    F = np.asarray(mesh.tri_verts, dtype=np.int64)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    v6 = np.einsum("ij,ij->i", a, np.cross(b, c))
    vol = v6.sum() / 6
    if abs(vol) < 1e-12:
        return 0.0, V.mean(0) if len(V) else np.zeros(3)
    cen = ((a + b + c) * v6[:, None]).sum(0) / (4 * v6.sum())
    return float(vol), cen


def _exact_parts(V, F, P, T):
    """(missing parts, extra parts) as [(volume, centroid)], from manifold3d's exact boolean, or None."""
    mr, md = _manifold(V, F), _manifold(P, T)
    if mr is None or md is None:
        return None
    try:
        out = []
        for d in (mr - md, md - mr):
            out.append([_mesh_props(c) for c in d.decompose()])
        return out
    except Exception:                                   # noqa: BLE001
        return None


def _axis_name(u) -> str | None:
    k = int(np.argmax(np.abs(u)))
    return "xyz"[k] if abs(u[k]) > 0.995 else None


def _body(X: np.ndarray, h: float, kind: str):
    """Shape of one body from its voxel centres X: centre, axes, extents, and a cylinder or box when it reads so."""
    c = X.mean(0)
    vol = len(X) * h ** 3
    if len(X) < 4:
        w, U = np.ones(3), np.eye(3)
    else:
        w, U = np.linalg.eigh(np.cov((X - c).T))
    w = np.maximum(w, 1e-12)
    U = U.T                                           # rows: eigenvectors, smallest variance first
    ext = np.array([float(np.ptp((X - c) @ u)) + h for u in U])
    for i, u in enumerate(U):                         # world-aligned directions read as +x, +y, +z
        k = int(np.argmax(np.abs(u)))
        if u[k] < 0:
            U[i] = -u
    row = {"volume_mm3": round(vol, 3), "centre": _r(c), "voxels": int(len(X))}
    longest = int(np.argmax(ext))
    row["principal_axis"] = _r(U[longest], 4)
    if _axis_name(U[longest]):
        row["principal_axis_name"] = _axis_name(U[longest])
    row["size_mm"] = _r(sorted(ext.tolist(), reverse=True))
    # a cylinder: two equal transverse variances; its axis is the third eigenvector
    shape, sym = "body", None
    for i in range(3):
        j, k = [x for x in range(3) if x != i]
        if abs(w[j] - w[k]) <= 0.12 * max(w[j], w[k]):
            L = ext[i]
            d = 2 * math.sqrt(vol / (math.pi * max(L, h)))
            if abs(math.pi * (d / 2) ** 2 * L - vol) <= 0.15 * vol and abs(4 * math.sqrt(w[j]) - d) <= 0.2 * d + h:
                shape, sym = "cylinder", i
                row["axis"] = _r(U[i], 4)
                if _axis_name(U[i]):
                    row["axis_name"] = _axis_name(U[i])
                row["diameter_mm"] = round(d, 3)
                row["length_mm"] = round(float(L), 3)
                break
    if shape == "body" and abs(float(np.prod(ext)) - vol) <= 0.15 * vol:
        shape = "box"
        row["box_mm"] = _r(ext[::-1])
        row["box_axes"] = [_r(u, 4) for u in U[::-1]]
    row["shape"] = shape
    return row


def _about(bodies, axis_k: int | None, axis_v: np.ndarray, centre: np.ndarray):
    """Angle (degrees, 0-360, right-handed about the axis) and radius of every body about the given axis."""
    a = axis_v / np.linalg.norm(axis_v)
    e1 = np.cross(a, [0, 0, 1.0] if abs(a[2]) < 0.9 else [1.0, 0, 0])
    e1 /= np.linalg.norm(e1)
    if axis_k == 2:
        e1 = np.array([1.0, 0, 0])
    elif axis_k == 0:
        e1 = np.array([0, 1.0, 0])
    elif axis_k == 1:
        e1 = np.array([0, 0, 1.0])
    e2 = np.cross(a, e1)
    for b in bodies:
        d = np.asarray(b["centre"]) - centre
        d = d - (d @ a) * a
        b["radius_mm"] = round(float(np.linalg.norm(d)), 3)
        b["angle_deg"] = round(math.degrees(math.atan2(d @ e2, d @ e1)) % 360.0, 2)


def _similar(a, b) -> bool:
    if a["kind"] != b["kind"] or a["shape"] != b["shape"]:
        return False
    va, vb = a["volume_mm3"], b["volume_mm3"]
    if abs(va - vb) > 0.15 * max(va, vb):
        return False
    sa, sb = np.asarray(a["size_mm"]), np.asarray(b["size_mm"])
    return bool(np.all(np.abs(sa - sb) <= 0.15 * np.maximum(sa, sb) + 0.2))


def _patterns(bodies, axis_v, centre, h):
    """Groups of alike bodies that repeat: polar (equal angles at one radius), linear (equal pitch on a line), grid."""
    groups, used = [], set()
    for i, b in enumerate(bodies):
        if i in used:
            continue
        g = [i] + [j for j in range(i + 1, len(bodies)) if j not in used and _similar(b, bodies[j])]
        if len(g) < 2:
            continue
        used.update(g)
        groups.append(g)
    out = []
    a = axis_v / np.linalg.norm(axis_v)
    tol = max(0.25, 1.5 * h)
    for g in groups:
        mem = [bodies[i] for i in g]
        names = [m["name"] for m in mem]
        r = np.array([m["radius_mm"] for m in mem])
        pat = None
        if len(mem) >= 3 and r.min() > 2 * tol and np.ptp(r) <= max(tol, 0.02 * r.mean()):
            ang = np.sort([m["angle_deg"] for m in mem])
            gaps = np.diff(np.r_[ang, ang[0] + 360.0])
            full = 360.0 / len(mem)
            tol_deg = math.degrees(tol / r.mean()) + 0.5
            if np.all(np.abs(gaps - full) <= tol_deg):
                # the phase of the pattern: the circular mean of every angle modulo the pitch, in (-pitch/2, pitch/2]
                ph = np.radians(ang * len(mem))
                start = math.degrees(math.atan2(np.sin(ph).mean(), np.cos(ph).mean())) / len(mem)
                pat = {"type": "polar", "count": len(mem), "pitch_deg": round(full, 3), "radius_mm": round(float(r.mean()), 3),
                       "start_deg": round(start, 2), "angles_deg": [round(float(x), 2) for x in ang],
                       "full_circle": True}
            else:                                         # an arc: all gaps but the largest equal
                k = int(np.argmax(gaps))
                rest = np.delete(gaps, k)
                if len(rest) >= 2 and np.ptp(rest) <= tol_deg:
                    st = ang[(k + 1) % len(ang)]
                    pat = {"type": "polar", "count": len(mem), "pitch_deg": round(float(rest.mean()), 3),
                           "radius_mm": round(float(r.mean()), 3), "start_deg": round(float(st), 2),
                           "angles_deg": [round(float(x), 2) for x in ang], "full_circle": False}
        if pat is None:
            C = np.array([m["centre"] for m in mem])
            if len(mem) >= 2:
                c0 = C.mean(0)
                w, U = np.linalg.eigh(np.cov((C - c0).T)) if len(mem) > 2 else (None, None)
                d = (C[-1] - C[0]) if len(mem) == 2 else U[:, -1]
                d = d / max(np.linalg.norm(d), 1e-12)
                t = (C - c0) @ d
                off = np.linalg.norm((C - c0) - np.outer(t, d), axis=1)
                ts = np.sort(t)
                steps = np.diff(ts)
                if off.max() <= tol and np.ptp(steps) <= tol:
                    k = int(np.argmax(np.abs(d)))
                    if d[k] < 0:
                        d = -d
                    pat = {"type": "linear", "count": len(mem), "pitch_mm": round(float(steps.mean()), 3),
                           "direction": _r(d, 4), "first": _r(C[np.argmin(t * np.sign(d[k] or 1))])}
                    if _axis_name(d):
                        pat["direction_name"] = _axis_name(d)
            if pat is None and len(mem) >= 4:             # a grid in the plane across the axis
                k = int(np.argmax(np.abs(a)))
                if abs(a[k]) > 0.995:
                    i1, i2 = [x for x in range(3) if x != k]
                    u1 = _levels(C[:, i1], tol)
                    u2 = _levels(C[:, i2], tol)
                    if len(u1) * len(u2) == len(mem) and len(u1) >= 2 and len(u2) >= 2 \
                            and _even(u1, tol) and _even(u2, tol):
                        pat = {"type": "grid", "count": len(mem), "rows": len(u2), "columns": len(u1),
                               "pitch_mm": {"xyz"[i1]: round(float(np.diff(u1).mean()), 3),
                                            "xyz"[i2]: round(float(np.diff(u2).mean()), 3)},
                               "centre": _r(C.mean(0))}
        if pat is None:
            pat = {"type": "repeated", "count": len(mem)}
        pat["members"] = names
        pat["kind"] = mem[0]["kind"]
        pat["shape"] = mem[0]["shape"]
        if "diameter_mm" in mem[0]:
            pat["diameter_mm"] = round(float(np.mean([m["diameter_mm"] for m in mem])), 3)
        out.append(pat)
    return out


def _levels(x, tol):
    xs = np.sort(x)
    lv = [[xs[0]]]
    for v in xs[1:]:
        if v - lv[-1][-1] <= tol:
            lv[-1].append(v)
        else:
            lv.append([v])
    return np.array([np.mean(g) for g in lv])


def _even(u, tol):
    return len(u) < 3 or np.ptp(np.diff(u)) <= tol


def residual(V, F, P, T, h: float | None = None, axis: str | list | None = None, centre=None,
             min_volume: float | None = None, max_cells: int = 12_000_000, max_bodies: int = 40) -> dict:
    """The work list between a reference mesh (V, F) and a design (P, T): missing and extra bodies and patterns."""
    from scipy import ndimage
    V, P = np.asarray(V, dtype=np.float64), np.asarray(P, dtype=np.float64)
    F, T = np.asarray(F, dtype=np.int64), np.asarray(T, dtype=np.int64)
    ref, des = _grids(V, F, P, T, h, max_cells)
    h = ref.h
    vox = h ** 3
    vol_ref = float(ref.grid.sum()) * vox
    vol_des = float(des.grid.sum()) * vox
    raw = {"missing": ref.grid & ~des.grid, "extra": des.grid & ~ref.grid}
    st = ndimage.generate_binary_structure(3, 1)
    if min_volume is None:
        min_volume = max(27 * vox, 1e-4 * max(vol_ref, vox))
    lo, hi = V.min(0), V.max(0)
    if axis is None:
        axis_k, axis_v = 2, np.array([0, 0, 1.0])
    elif isinstance(axis, str):
        if axis.lower() not in AXES:
            raise ValueError("axis: x, y or z, or a direction [dx, dy, dz].")
        axis_k = AXES[axis.lower()]
        axis_v = np.eye(3)[axis_k]
    else:
        axis_v = np.asarray(axis, dtype=np.float64)
        if axis_v.shape != (3,) or np.linalg.norm(axis_v) < 1e-9:
            raise ValueError("axis: x, y or z, or a direction [dx, dy, dz].")
        axis_v = axis_v / np.linalg.norm(axis_v)
        axis_k = AXES.get(_axis_name(axis_v) or "", None)
    if centre is None:                                  # the reference's own centre of volume
        idx = np.argwhere(ref.grid)
        cen = ref.lo + (idx.mean(0) + 0.5) * h if len(idx) else (lo + hi) / 2
    else:
        cen = np.asarray(centre, dtype=np.float64)
        if cen.shape != (3,):
            raise ValueError("centre: a point [x, y, z] on the axis.")
    bodies = []
    for kind, g in raw.items():
        opened = ndimage.binary_opening(g, structure=st)
        lab, n = ndimage.label(opened, structure=st)
        if not n:
            continue
        counts = np.bincount(lab.ravel())
        for l in range(1, n + 1):
            if counts[l] * vox < min_volume:
                continue
            X = ref.lo + (np.argwhere(lab == l) + 0.5) * h
            b = _body(X, h, kind)
            b["kind"] = kind
            bodies.append(b)
    exact = _exact_parts(V, F, P, T) if bodies else None
    method = "voxels"
    if exact is not None:
        method = "manifold3d (exact boolean difference)"
        for b in bodies:
            parts = exact[0 if b["kind"] == "missing" else 1]
            c = np.asarray(b["centre"])
            best, bd = None, None
            for vol, pc in parts:
                if not (0.5 * b["volume_mm3"] <= vol <= 1.6 * b["volume_mm3"]):
                    continue
                dd = float(np.linalg.norm(pc - c))
                if dd <= max(b["size_mm"]) / 2 and (bd is None or dd < bd):
                    best, bd = (vol, pc), dd
            if best is not None:
                b["voxel_volume_mm3"] = b["volume_mm3"]
                b["volume_mm3"] = round(best[0], 3)
                b["centre"] = _r(best[1])
                b["volume_method"] = "exact"
                if b["shape"] == "cylinder":
                    b["diameter_mm"] = round(2 * math.sqrt(best[0] / (math.pi * max(b["length_mm"], h))), 3)
            else:
                b["volume_method"] = "voxels"
    bodies.sort(key=lambda b: -b["volume_mm3"])
    bodies = bodies[:max_bodies]
    n_kind = {"missing": 0, "extra": 0}
    for b in bodies:
        n_kind[b["kind"]] += 1
        b["name"] = f"{b['kind']}-{n_kind[b['kind']]}"
        b["where"] = where(b["centre"], lo, hi)
        b["action"] = "add material here (the mesh has it, the design does not)" if b["kind"] == "missing" else \
            "cut this away (the design has it, the mesh does not)"
        b["label"] = _label(b)
    _about(bodies, axis_k, axis_v, cen)
    pats = _patterns(bodies, axis_v, cen, h)
    raw_missing = float(raw["missing"].sum()) * vox
    raw_extra = float(raw["extra"].sum()) * vox
    listed = sum(b["volume_mm3"] for b in bodies)
    out = {"evidence": f"computed (voxel difference on a {h:.3g} mm grid; exact to about half a voxel at the surface"
                       + ("; body volumes and centres from manifold3d's exact boolean" if method != "voxels" else "") + ")",
           "voxel_mm": round(h, 4), "volume_method": method,
           "reference_volume_mm3": round(vol_ref, 2), "design_volume_mm3": round(vol_des, 2),
           "missing_volume_mm3": round(raw_missing, 2), "extra_volume_mm3": round(raw_extra, 2),
           "residual_pct": round(100 * (raw_missing + raw_extra) / max(vol_ref, vox), 3),
           "axis": _r(axis_v, 4), "axis_centre": _r(cen),
           "missing": [b for b in bodies if b["kind"] == "missing"],
           "extra": [b for b in bodies if b["kind"] == "extra"],
           "patterns": pats,
           "unlisted_volume_mm3": round(max(raw_missing + raw_extra - listed, 0.0), 2),
           "min_body_mm3": round(min_volume, 4)}
    out["work_list"] = _work_list(out)
    if not bodies:
        out["verdict"] = (f"No body left over {min_volume:.3g} mm³: what remains is a skin thinner than two voxels "
                          f"({2 * h:.3g} mm). Refine sizes with compare_to_reference or fit_params.")
    else:
        out["verdict"] = (f"{len(out['missing'])} missing and {len(out['extra'])} extra bodies"
                          + (f", {len(pats)} pattern(s)" if pats else "") + ". Build one item of the work list (a pattern "
                          "is one feature), check the residual again, and keep the change only if the residual drops.")
    return out


def _label(b) -> str:
    what = {"missing": "missing", "extra": "extra"}[b["kind"]]
    if b["shape"] == "cylinder":
        ax = b.get("axis_name") or "tilted"
        s = f"{what} cylinder dia {b['diameter_mm']:.2f} x {b['length_mm']:.2f} along {ax}"
    elif b["shape"] == "box":
        s = f"{what} box " + " x ".join(f"{x:.2f}" for x in b["box_mm"])
    else:
        s = f"{what} body " + " x ".join(f"{x:.2f}" for x in b["size_mm"])
    return f"{s}, {b['volume_mm3']:.1f} mm3, at {b['where']}"


def _work_list(res) -> list[str]:
    """One line per thing to build, patterns first (one feature each), then the bodies not in a pattern."""
    lines, inpat = [], set()
    for p in res["patterns"]:
        inpat.update(p["members"])
        verb = "add" if p["kind"] == "missing" else "cut"
        size = f" dia {p['diameter_mm']:.2f}" if "diameter_mm" in p else ""
        if p["type"] == "polar":
            lines.append(f"{verb} {p['count']} x {p['shape']}{size} as a polar pattern: radius {p['radius_mm']:.2f}, "
                         f"every {p['pitch_deg']:.2f} deg from {p['start_deg']:.2f} deg ({', '.join(p['members'])})")
        elif p["type"] == "linear":
            lines.append(f"{verb} {p['count']} x {p['shape']}{size} in a row: pitch {p['pitch_mm']:.2f} along "
                         f"{p.get('direction_name') or p['direction']} from {p['first']} ({', '.join(p['members'])})")
        elif p["type"] == "grid":
            pt = ", ".join(f"{k} {v:.2f}" for k, v in p["pitch_mm"].items())
            lines.append(f"{verb} {p['count']} x {p['shape']}{size} as a {p['columns']} x {p['rows']} grid: pitch {pt}, "
                         f"centred at {p['centre']} ({', '.join(p['members'])})")
        else:
            lines.append(f"{verb} {p['count']} alike {p['shape']}s{size} ({', '.join(p['members'])})")
    for b in res["missing"] + res["extra"]:
        if b["name"] not in inpat:
            lines.append(f"{'add' if b['kind'] == 'missing' else 'cut'} {b['name']}: {b['label']}, centre {b['centre']}")
    return lines


def reference_residual(st, p: dict, reference: str, part: str | None = None, rev: int | None = None,
                       voxel: float | None = None, axis=None, centre=None) -> dict:
    """The work list between a project's design (or one part of it) and one of its imported meshes."""
    from ..studio import StudioError
    from . import analyze as an
    from . import compare as cmp
    from .project import _ref
    rec, path = _ref(st, p, reference)
    if voxel is not None and not (0.02 <= float(voxel) <= 5):
        raise StudioError("voxel: between 0.02 and 5 mm.", "Leave it out for about 1/240 of the part's size.")
    view = st.view(p, rev, tol=0.01, timeout=300)
    try:
        P, T = cmp.design_mesh(view, part)
    except ValueError as e:
        raise StudioError(str(e), "Name the part as the design's assembly does (get_project lists the parts), "
                                  "or leave part out to compare the whole design.") from None
    V, F, info = an.load(path)
    if not info.get("closed"):
        raise StudioError(f"{rec['file']} is not closed (it has open edges), so it does not bound a solid.",
                          "Close it in the program that made it, or reconstruct it.")
    try:
        out = residual(V, F, P, T, h=voxel, axis=axis, centre=centre)
    except ValueError as e:
        raise StudioError(str(e)) from None
    out.update({"reference": rec["file"], "part": part, "rev": st.rev(p, rev)["n"],
                "next": "Build the first line of work_list as one feature (a pattern is one feature with a count and a "
                        "pitch Param), run reference_residual again and keep the change only if residual_pct drops. "
                        "When no body is left, fit_params tunes the declared Params and compare_to_reference checks "
                        "the tolerance."})
    return out
