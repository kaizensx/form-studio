"""Assembly sequence: an order the parts can go together in, and the straight direction each one goes in.

Assembly by disassembly (after Wilson and Latombe's non-directional blocking graph, 1994): starting from the assembled
design, repeatedly take out one part that can leave in a straight line; the assembly order is the reverse, and each
part's insertion direction is the opposite of the way it left.

For a part and a direction d (candidates: the axes, the joint, mate and loop axes, and the directions the contact
normals give):
  1. Local freedom. Wherever the part touches a part still in place (triangles of its mesh within the contact distance
     of the other's surface), d must not point into the other part: d . n <= 0 for every outward contact normal n of
     the moving part. A screw seated on a lid can leave upward; a lid under screw heads cannot.
  2. Global freedom. The part is swept along d until its bounding box is clear of every part still in place, by
     conservative advancement on the meshes (collide.query): each step is no longer than the clearance, so nothing is
     skipped, except where the parts slide in contact, where the step is the contact distance and the sweep is sampled.
     An overlap deeper than the mesh tolerance blocks d, and says which part blocked it.
Pairs joined by design are treated by what they are: a thread unscrews along its declared axis (helical motion, not
swept), a snap is taken to deflect, a press fit to be pushed along its axis; their contact does not block those
directions. Smaller parts are tried first (fasteners leave first and go in last); +Z is tried first among directions.

Limits (stated with every result): geometric feasibility only, one part at a time on a straight line; no gravity,
fixtures, tool or hand access, friction or flexible parts beyond what a Mate declares; contact normals from the mesh
(within the stated tolerance); a set of parts that cannot come apart one at a time (they need a sub-assembly move, a
rotation or deformation) is reported as such, never ordered by guess.

    from form import sequence
    r = sequence.plan(st, p)     # {"steps": [{part, insert, ...}], "explode": {part: [x, y, z]}, "limits": ...}
"""
from __future__ import annotations

import json
import math
import time

import numpy as np

VERSION = 1
EVIDENCE = "computed (geometric feasibility)"
LIMITS = ("Geometric feasibility only: one part at a time moving on a straight line. No gravity, fixtures, tool or hand "
          "access, friction or flexible parts beyond what a Mate declares (a thread unscrews along its axis, a snap "
          "deflects, a press fit is pushed). Contact normals come from the mesh, within its tolerance; where parts slide "
          "in contact the sweep is sampled at the contact distance, elsewhere each step is shorter than the clearance.")


def _u(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def directions(spec, extra=()) -> list:
    """Candidate directions: +Z first, then the other axes, then declared axes, then the 26 cube directions."""
    out = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    for j in spec.joints:
        if j.kind in ("slide", "cylindrical"):
            out += [tuple(_u(j.axis)), tuple(-_u(j.axis))]
    for m in spec.mates:
        if m.axis is not None:
            out += [tuple(_u(m.axis)), tuple(-_u(m.axis))]
    for e in extra:
        out += [tuple(_u(e))]
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            for z in (-1, 0, 1):
                if (x, y, z) != (0, 0, 0) and abs(x) + abs(y) + abs(z) > 1:
                    out.append(tuple(_u((x, y, z))))
    seen, uniq = [], []
    for d in out:
        d = np.asarray(d, float)
        if not any(float(d @ s) > 1 - 1e-6 for s in seen):
            seen.append(d)
            uniq.append(d)
    return uniq


def contact_normals(A, B, MA, MB, dist: float) -> np.ndarray:
    """Outward normals (world) of A's triangles within `dist` of B's surface. A, B: collide.Body (own frames);
    MA, MB: 4x4 placing them in the world."""
    from . import collide
    if A.tree is None or B.tree is None:
        return np.zeros((0, 3))
    M = np.linalg.inv(MB) @ MA                      # A in B's frame
    C = A.C @ M[:3, :3].T + M[:3, 3]
    lo, hi = B.lo - dist - A.rmax, B.hi + dist + A.rmax
    cand = np.nonzero(np.all((C >= lo) & (C <= hi), axis=1))[0]
    if not len(cand):
        return np.zeros((0, 3))
    d0, _ = B.tree.query(C[cand], k=1, distance_upper_bound=dist + A.r[cand].max() + B.rmax + 1e-9)
    near = cand[np.isfinite(d0) & (d0 <= dist + A.r[cand] + B.rmax)]
    if not len(near):
        return np.zeros((0, 3))
    dd = collide.surface_distance(B, C[near])
    keep = near[dd <= dist]
    N = A.N[keep] @ MA[:3, :3].T
    if not len(N):
        return np.zeros((0, 3))
    return np.unique(np.round(N, 3), axis=0)


def _sweep(A, MA, others, d, length, tol2, step_min, deadline, max_steps=4000):
    """Translate A along d up to `length`: (free, blocker, sampled, steps). others: [(id, Body, M)]."""
    from . import collide
    t, sampled, n = 0.0, False, 0
    while t < length:
        n += 1
        if n > max_steps or time.perf_counter() > deadline:
            return None, None, True, n
        T = np.eye(4)
        T[:3, 3] = d * t
        M = T @ MA
        g = math.inf
        for oid, Bo, Mo in others:
            r = collide.query(A, Bo, np.linalg.inv(Mo) @ M, max(1.0, 4 * step_min), deadline)
            st = r.state(tol2)
            if st == "overlap" and t > 0:
                return False, oid, sampled, n
            g = min(g, 0.0 if st in ("overlap", "contact") else r.d)
        if g < step_min:
            sampled = True
        t += max(g - 1e-9, step_min) if math.isfinite(g) else length
    return True, None, sampled, n


def _clear_length(A, MA, others, d) -> float:
    """How far A must go along d for its bounding box to leave the others' (plus 5 % and 1 mm)."""
    P = A.V @ MA[:3, :3].T + MA[:3, 3]
    Q = np.concatenate([Bo.V @ Mo[:3, :3].T + Mo[:3, 3] for _, Bo, Mo in others]) if others else P
    a = P @ d
    b = Q @ d
    return max(0.0, float(b.max() - a.min())) * 1.05 + 1.0


def plan_spec(spec, meshes: dict, tol: float, budget_s: float = 90.0) -> dict:
    """The disassembly search on an Assembly and {part id: (P, T)} print-frame meshes."""
    from . import collide
    from .recipes.assembly import placement_matrix
    t0 = time.perf_counter()
    deadline = t0 + float(budget_s)
    ids = [p.id for p in spec.parts if p.id in meshes]
    lab = {p.id: p.label for p in spec.parts}
    B = {pid: collide.Body(*meshes[pid], tol) for pid in ids}
    M = {pid: placement_matrix(next(x for x in spec.parts if x.id == pid)) for pid in ids}
    vol = {pid: abs(float(np.einsum("ij,ij->i", B[pid].orig[0], np.cross(B[pid].orig[1], B[pid].orig[2])).sum()) / 6)
           for pid in ids}
    tol2 = 2 * tol
    cd = max(0.05, 2.5 * tol2)                       # contact distance
    step_min = max(cd, 0.25)
    dirs = directions(spec)
    remaining = list(ids)
    removed, blocked_log = [], []
    while len(remaining) > 1 and time.perf_counter() < deadline:
        cands = sorted(remaining, key=lambda x: (vol[x], ids.index(x)))
        took = None
        for pid in cands:
            others = [(o, B[o], M[o]) for o in remaining if o != pid]
            normals, allow = [], []
            for o, _, _ in others:
                m = spec.mate(pid, o)
                N = contact_normals(B[pid], B[o], M[pid], M[o], cd)
                if m is not None and m.kind in ("thread", "press", "snap", "slip", "pin") and m.axis is not None:
                    allow.append((o, _u(m.axis), m.kind))      # its own axis is free for this pair
                    ax = _u(m.axis)
                    N = N[np.abs(N @ ax) < 0.5] if m.kind in ("thread", "press") else N
                elif m is not None and m.kind == "snap":
                    allow.append((o, None, "snap"))
                    N = np.zeros((0, 3))
                normals.append((o, N))
            for d in dirs:
                local_block = [o for o, N in normals if len(N) and float(np.max(N @ d)) > 0.05]
                axial = [a for a in allow if a[1] is not None and abs(float(a[1] @ d)) > 1 - 1e-6]
                local_block = [o for o in local_block if not any(a[0] == o for a in axial)]
                if local_block:
                    continue
                sweep_others = [x for x in others if not any(a[0] == x[0] and (a[1] is None or abs(float(a[1] @ d)) > 1 - 1e-6)
                                                             for a in allow)]
                L = _clear_length(B[pid], M[pid], others, d)
                free, who, sampled, n = _sweep(B[pid], M[pid], sweep_others, d, L, tol2, step_min, deadline)
                if free is None:
                    break
                if not free:
                    blocked_log.append({"part": pid, "direction": d.tolist(), "blocked_by": who})
                    continue
                took = {"part": pid, "remove": d.tolist(), "distance_mm": round(L, 3), "sampled": sampled, "evaluations": n,
                        "contacts": [o for o, N in normals if len(N)],
                        "joined": [{"with": a[0], "kind": a[2]} for a in allow
                                   if a[1] is None or abs(float(a[1] @ d)) > 1 - 1e-6]}
                break
            if took:
                break
        if not took:
            break
        removed.append(took)
        remaining.remove(took["part"])
    complete = len(remaining) <= 1
    partial = not complete and time.perf_counter() >= deadline
    base = remaining[0] if complete and remaining else None
    order = ([base] if base else []) + [x["part"] for x in reversed(removed)]
    steps = []
    if base:
        steps.append({"n": 1, "part": base, "label": lab[base], "insert": None, "role": "base",
                      "text": f"Place the {lab[base].lower()}."})
    for x in reversed(removed):
        ins = [-c for c in x["remove"]]
        how = []
        if x["joined"]:
            how += [f"{'screw' if j['kind'] == 'thread' else j['kind']} into {lab[j['with']].lower()}" for j in x["joined"]]
        steps.append({"n": len(steps) + 1, "part": x["part"], "label": lab[x["part"]],
                      "insert": [round(c, 6) for c in ins], "remove": [round(c, 6) for c in x["remove"]],
                      "direction_text": dir_text(ins), "distance_mm": x["distance_mm"], "sampled": x["sampled"],
                      "touches": x["contacts"], "joined": x["joined"],
                      "text": f"Insert the {lab[x['part']].lower()} {dir_text(ins)}" + (f" ({'; '.join(how)})" if how else "") + ".",
                      "proof": ("local freedom from the contact normals; swept clear along the direction"
                                + (" (sampled where it slides in contact)" if x["sampled"] else " (each step within the clearance)"))})
    # exploded view: each part along its own free direction, the last ones in farthest
    explode = {}
    if base:
        explode[base] = [0.0, 0.0, 0.0]
    n = len(removed)
    for k, x in enumerate(removed):                  # k = 0 left first (goes in last): farthest out
        dist = x["distance_mm"] * (1.0 + 0.35 * (n - 1 - k) / max(n, 1)) + 4.0
        explode[x["part"]] = [round(c * dist, 3) for c in x["remove"]]
    stuck = None
    if not complete:
        stuck = {"parts": remaining, "labels": [lab[x] for x in remaining],
                 "why": ("the time budget ran out" if partial else
                         "no one of them can leave on a straight line without hitting another: they need a sub-assembly "
                         "move, a rotation or deformation"),
                 "tried": blocked_log[-12:]}
    return {"version": VERSION, "evidence": EVIDENCE, "complete": complete, "partial": partial, "order": order,
            "steps": steps, "explode": explode, "stuck": stuck, "directions_tried": len(dirs),
            "contact_distance_mm": cd, "tolerance_mm": tol2, "limits": LIMITS,
            "hardware": [{"name": h.name, "after": h.after, "note": h.note} for h in spec.hardware],
            "seconds": round(time.perf_counter() - t0, 2)}


def dir_text(v) -> str:
    v = np.asarray(v, float)
    names = ["X", "Y", "Z"]
    comps = [(abs(c), i, c) for i, c in enumerate(v) if abs(c) > 1e-6]
    if len(comps) == 1:
        _, i, c = comps[0]
        return {("Z", -1): "from above (along −Z)", ("Z", 1): "from below (along +Z)"}.get(
            (names[i], int(np.sign(c))), f"along {'+' if c > 0 else '−'}{names[i]}")
    return "along (" + ", ".join(f"{c:.2f}" for c in v) + ")"


def plan(st, p: dict, budget_s: float = 90.0, rev: int | None = None) -> dict:
    """The sequence of a revision, stored under artifacts/sequence/<key>.json by geometry key (cached)."""
    from . import fsutil, motion
    from .recipes.assembly import Assembly
    from .studio import H, StudioError
    r = st.rev(p, rev)
    gk = st.keys(p, r["n"])["geometry"]
    key = H("sequence", VERSION, gk, budget_s)
    f = path(st, p, gk)
    if f.is_file():
        try:
            res = json.loads(f.read_text(encoding="utf-8"))
            if res.get("key") == key:
                return res | {"cached": True}
        except ValueError:
            pass
    view = st.view(p, r["n"])
    a = view.get("assembly") or {}
    if not a.get("parts") or a.get("error"):
        raise StudioError("This design has no usable assembly: " + (a.get("error") or "it is one part."),
                          "An assembly sequence needs several parts placed where they go (assembly()).")
    if a.get("derived"):
        raise StudioError("This design builds several bodies but does not say where each goes, so there is nothing to "
                          "sequence.", "Declare assembly() with each Part placed in the assembled frame.")
    spec = Assembly.from_public(a)
    res = plan_spec(spec, motion.part_meshes(view), float(view.get("tol") or 0.05), budget_s)
    res.update(project=p["id"], rev=r["n"], key=key, geometry_key=gk)
    res["text"] = text(res)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(res, indent=1), encoding="utf-8")
    fsutil.replace(tmp, f)
    return res | {"cached": False}


def path(st, p: dict, gk: str):
    return st.dir(p["id"]) / "artifacts" / "sequence" / f"{gk}.json"


def stored(st, p: dict, rev: int | None = None) -> dict | None:
    """The sequence of this revision's geometry, if one was computed (no computing here)."""
    try:
        gk = st.keys(p, st.rev(p, rev)["n"])["geometry"]
        f = path(st, p, gk)
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except Exception:                                  # noqa: BLE001 - nothing stored, or no head yet
        return None


def annotate_view(st, p: dict, view: dict, rev: int | None = None) -> dict:
    """Add a stored sequence to the assembly view: each part's sequence_explode (its own free direction, the last
    in farthest) and the order. Nothing is computed here."""
    a = view.get("assembly") or {}
    if not a.get("parts") or a.get("derived"):
        return view
    s = stored(st, p, rev)
    if not s or not s.get("complete"):
        return view
    for x in a["parts"]:
        if x["id"] in s["explode"]:
            x["sequence_explode"] = s["explode"][x["id"]]
    a["sequence"] = {"order": s["order"], "evidence": s["evidence"], "key": s["key"]}
    return view


def headline(res: dict) -> str:
    if not res["complete"]:
        return f"stuck: {', '.join(res['stuck']['labels'])} cannot come apart one at a time"
    return f"{len(res['steps'])} steps · " + " → ".join(s["label"] for s in res["steps"][:5]) + (" …" if len(res["steps"]) > 5 else "")


def text(res: dict) -> str:
    out = []
    if res["complete"]:
        out.append(f"A feasible assembly order in {len(res['steps'])} steps ({res['evidence']}):")
        out += [f"{s['n']}. {s['text']}" for s in res["steps"]]
    else:
        out.append(f"No complete order: {', '.join(res['stuck']['labels'])} — {res['stuck']['why']}.")
        if res["steps"]:
            out.append("The parts that do come off, in assembly order: " + "; ".join(s["text"] for s in res["steps"]))
    if res.get("hardware"):
        out.append("Purchased hardware without a model is not sequenced: " + ", ".join(h["name"] for h in res["hardware"]) + ".")
    out.append(res["limits"])
    return " ".join(out)
