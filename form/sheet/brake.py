"""Bend order on a press brake: a sequence in which every bend can be formed without the part hitting the tools,
with a simple, stated model of the brake (numpy only, from an unfold result).

The model, in the plane across the bend being formed (its cross-section):

- **Die.** A V-die whose opening V is 8 × t (Bystronic, *The rules of press brake tool selection*, 2019: "the V-die
  opening should be 8 times the material thickness"), a groove of 88° (assumed), a block V + 20 mm wide and 60 mm
  high (assumed), on a bed that fills everything below it. The die and bed run the full length of the brake.
- **Punch.** A gooseneck punch (assumed dimensions, Form Studio's model, not a catalogue tool), in the plane across
  the bend with the tip at (0, 0): an 88° tip 10 mm high; a neck from y = -6 to 9.66 mm up to 22 mm (front) and
  30 mm (back); an arm rising forward to a column from y = 25 to 55 mm, up to 120 mm, where the ram is (y = 0 to
  80 mm above 120 mm). Behind the neck (y < 0) and above the arm the punch is open: that is the pocket a return
  flange swings into. The punch is sectioned to the bend's own length, as a shop sets up segmented tooling for a
  box: material beyond the ends of the bend line does not meet it.
- **Air bending.** The part rests on the die's shoulders with the inside of the bend toward the punch; each side
  turns up by half the bend angle. The bend is checked at a quarter, half, three quarters and all of its angle;
  bends already made are rigid, bends still to make are flat. The part may be turned end for end (the punch's
  column on either side).
- **Collision.** Every face of the part (both skins), projected into the cross-section, as the convex hull of its
  sampled points, against the punch, its column, the ram, the die block and the bed (contact within 0.05 mm
  allowed). Faces of the bend being formed are excluded.

Limits, stated on every result: a 2D cross-section (material anywhere along the brake counts against the die and
bed); non-convex faces are taken by their convex hull (conservative); no springback, back gauge, finger stops,
part weight, handling or the operator; hems (bends past 92°) need an acute punch and a flattening step, which
this model does not have, so they come out as collisions; tooling is not chosen from a catalogue.

Order search: depth-first over the bends, deepest first (flanges on flanges before their parents), with each
(bend, bends already made) result remembered; at most `budget` checks.
"""
from __future__ import annotations

import math

import numpy as np

from . import fold as foldmod
from . import geom2d

FRACTIONS = (0.25, 0.5, 0.75, 1.0)
CONTACT = 0.05
RAM_Y = (0.0, 80.0)        # the ram above the punch, across the brake (assumed)
MODEL = {
    "die": {"v_opening": "8 × t", "v_source": "Bystronic Inc., The rules of press brake tool selection (2019-05; read "
                                              "2026-11-28): the V-die opening should be 8 times the material thickness",
            "groove_deg": 88.0, "block_width": "V + 20 mm", "height_mm": 60.0, "evidence": "assumed except V"},
    "punch": {"kind": "gooseneck", "tip_deg": 88.0, "tip_mm": 10.0, "neck_mm": [22.0, 30.0], "column_y_mm": [25.0, 55.0],
              "height_mm": 120.0, "ram_y_mm": [0.0, 80.0], "sectioned": "to the bend's length",
              "evidence": "assumed (Form Studio's model)"},
    "fractions": list(FRACTIONS),
    "limits": ["2D cross-section: material anywhere along the brake meets the die and bed",
               "faces taken by their convex hull in the cross-section (conservative for non-convex faces)",
               "no springback, back gauge, finger stops, part weight or handling",
               "hems and bends past 92° need an acute punch and a flattening step that this model does not have",
               "tooling is not chosen from a catalogue"],
}


def punch_polygon(kind: str = "gooseneck") -> np.ndarray:
    h = math.tan(math.radians(44.0))
    if kind == "straight":
        return np.array([(0, 0), (10 * h, 10), (10 * h, 120), (-10 * h, 120), (-10 * h, 10)], float)
    return np.array([(0, 0), (10 * h, 10), (10 * h, 22), (55, 40), (55, 120), (25, 120), (25, 58), (-6, 30),
                     (-6, 18), (-10 * h, 10)], float)


def die_polygon(V: float, z_sh: float, H: float = 60.0, groove_deg: float = 88.0) -> np.ndarray:
    W = V + 20.0
    g = (V / 2) / math.tan(math.radians(groove_deg / 2))
    zt = z_sh - CONTACT
    return np.array([(-W / 2, z_sh - H), (W / 2, z_sh - H), (W / 2, zt), (V / 2, zt), (0, zt - g), (-V / 2, zt),
                     (-W / 2, zt)], float)


def _hull(P: np.ndarray) -> np.ndarray:
    pts = np.unique(np.round(P, 7), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 1e-12:
            lo.pop()
        lo.append(p)
    for p in pts[::-1]:
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 1e-12:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1])


def _hits(A: np.ndarray, B: np.ndarray) -> bool:
    """Do polygon A (a hull, possibly a segment or point) and simple polygon B overlap?"""
    if len(A) == 0:
        return False
    Bc = np.vstack([B, B[:1]])
    if any(geom2d.inside(p, Bc) for p in A):
        return True
    if len(A) >= 3:
        Ac = np.vstack([A, A[:1]])
        if any(geom2d.inside(p, Ac) for p in B):
            return True
    else:
        Ac = A if len(A) == 2 else np.vstack([A, A])
    return bool(geom2d.crossings(Ac if len(A) < 3 else np.vstack([A, A[:1]]), Bc))


class Brake:
    def __init__(self, res: dict, punch: str = "gooseneck", die_v: float | None = None):
        self.res = res
        self.t = float(res["t"])
        self.bends = {b["id"]: b for b in res["bends"]}
        self.V = float(die_v) if die_v else 8.0 * self.t
        self.punch = punch_polygon(punch)
        self.punch_kind = punch
        self.regions = []
        for fid, r in res["regions"].items():
            S = np.asarray(r.get("samples") or [], float)
            if len(S):
                self.regions.append((int(fid), list(r["path"]), r["zone"], S))
        self.memo: dict = {}
        self.checks = 0

    def _frame(self, b: dict, amount: dict):
        """(origin, X, Y, Z) of the brake for bend b part way: X along the bend, Z toward the punch, origin at the
        inside surface of the bend's middle."""
        q, u, d = np.asarray(b["q"], float), np.asarray(b["u"], float), np.asarray(b["d"], float)
        mid = q + d * (b["w"] / 2) + u * (b["length"] / 2)
        pts = np.array([q, q + u * b["length"], mid])
        path = list(b["path"]) + [b["id"]]
        S = foldmod.fold(pts, 0.0, path, b["id"], self.bends, amount)
        O = foldmod.fold(pts[2:], -self.t, path, b["id"], self.bends, amount)[0]
        X = S[1] - S[0]
        X /= np.linalg.norm(X)
        if b["s"] > 0:
            Z, tip = S[2] - O, S[2]
        else:
            Z, tip = O - S[2], O
        Z = Z - (Z @ X) * X
        Z /= np.linalg.norm(Z)
        Y = np.cross(Z, X)
        along0 = float((S[0] - tip) @ X)
        return tip, X, Y, Z, sorted([along0, along0 + b["length"]])

    def _shoulder(self, b: dict, frac: float) -> float:
        """The height of the die's shoulders in the brake frame (origin at the inside of the bend's middle): where
        the outside of the part, each side turned up by half the angle, meets y = ±V/2."""
        K = float(b["K"])
        r_eff = float(b["R_n"]) / frac - K * self.t
        ro = r_eff + self.t
        a = math.radians(b["angle"]) * frac / 2
        y = self.V / 2
        if y <= ro * math.sin(a):
            return r_eff - math.sqrt(max(ro * ro - y * y, 0.0))
        return r_eff - ro * math.cos(a) + (y - ro * math.sin(a)) * math.tan(a)

    def check(self, bid, done: frozenset) -> dict:
        """Can bend `bid` be formed with the bends in `done` already made? Tries both ends of the part."""
        key = (bid, done)
        if key in self.memo:
            return self.memo[key]
        self.checks += 1
        b = self.bends[bid]
        top = float(self.punch[:, 1].max())
        tries = []
        for flip in (1.0, -1.0):
            hits = []
            for frac in FRACTIONS:
                amount = {c: (1.0 if c in done else 0.0) for c in self.bends}
                amount[bid] = frac
                tip, X, Y, Z, span = self._frame(b, amount)
                die = die_polygon(self.V, self._shoulder(b, frac))
                bed_top = float(die[0][1])
                for fid, path, zone, S in self.regions:
                    if zone == bid:
                        continue
                    what = None
                    for z in (0.0, -self.t):
                        W = foldmod.fold(S, z, path, zone, self.bends, amount)
                        rel = W - tip
                        x = rel @ X
                        yz = np.column_stack([flip * (rel @ Y), rel @ Z])
                        H = _hull(yz)
                        axial = bool(np.any((x > span[0] + 1e-6) & (x < span[1] - 1e-6))
                                     or (x.min() <= span[0] + 1e-6 and x.max() >= span[1] - 1e-6))
                        if np.any(yz[:, 1] < bed_top - CONTACT):
                            what = "bed"
                        elif _hits(H, die):
                            what = "die"
                        elif axial and np.any((yz[:, 1] > top + CONTACT) & (yz[:, 0] > RAM_Y[0]) & (yz[:, 0] < RAM_Y[1])):
                            what = "ram"
                        elif axial and _hits(H, self.punch):
                            what = "punch"
                        if what:
                            break
                    if what:
                        hits.append({"face": fid, "with": what, "at_fraction": frac})
                        break
                if hits:
                    break
            tries.append({"flip": flip < 0, "hits": hits})
            if not hits:
                break
        ok = any(not tr["hits"] for tr in tries)
        out = {"ok": ok, "flip": next((tr["flip"] for tr in tries if not tr["hits"]), None),
               "hits": [] if ok else [h for tr in tries for h in tr["hits"]]}
        self.memo[key] = out
        return out

    def order(self, budget: int = 4000) -> dict:
        ids = list(self.bends)
        depth = {i: len(self.bends[i]["path"]) for i in ids}
        cand = sorted(ids, key=lambda i: (-depth[i], -self.bends[i]["length"]))
        best = {"seq": None}

        def dfs(done: frozenset, seq: list) -> bool:
            if len(seq) == len(ids):
                best["seq"] = list(seq)
                return True
            if self.checks > budget:
                return False
            for c in cand:
                if c in done:
                    continue
                r = self.check(c, done)
                if r["ok"]:
                    seq.append((c, r["flip"]))
                    if dfs(done | {c}, seq):
                        return True
                    seq.pop()
            return False
        dfs(frozenset(), [])
        per = {}
        for c in ids:
            alone = self.check(c, frozenset())
            last = self.check(c, frozenset(set(ids) - {c}))
            per[c] = {"first": alone, "last": last}
        return {"feasible": best["seq"] is not None, "sequence": best["seq"], "per_bend": per,
                "checks": self.checks, "budget_hit": self.checks > budget}


def bend_order(res: dict, punch: str = "gooseneck", die_v: float | None = None, budget: int = 4000) -> dict:
    """A feasible bend sequence for an unfold result, with the collisions that rule others out."""
    if not res.get("bends"):
        return {"feasible": True, "sequence": [], "bends": [], "model": MODEL, "headline": "No bends: nothing to order."}
    if not res.get("regions"):
        raise ValueError("The unfold has no regions: run it again with this version.")
    br = Brake(res, punch, die_v)
    o = br.order(budget)
    names = {b["id"]: f"B{k + 1}" for k, b in enumerate(res["bends"])}
    seq = [{"step": k + 1, "bend": names[c], "id": c, "turn_part": bool(fl),
            "angle": round(br.bends[c]["angle"], 3), "direction": br.bends[c]["direction"],
            "line": br.bends[c]["line"]} for k, (c, fl) in enumerate(o["sequence"] or [])]
    blocked = []
    for c, p in o["per_bend"].items():
        if not p["first"]["ok"] and not p["last"]["ok"]:
            blocked.append({"bend": names[c], "id": c, "hits": p["last"]["hits"][:4] or p["first"]["hits"][:4]})
    model = dict(MODEL)
    model["die"] = {**MODEL["die"], "v_mm": round(br.V, 4), "v_given": bool(die_v)}
    model["punch"] = {**MODEL["punch"], "kind": punch}
    if o["feasible"]:
        head = "Bend order: " + " → ".join(s["bend"] + (" (part turned)" if s["turn_part"] else "") for s in seq)
    elif o["budget_hit"]:
        head = f"Bend order: not found within {budget} checks (not proven infeasible)"
    else:
        head = "Bend order: no sequence forms every bend with these tools"
    return {"feasible": o["feasible"], "sequence": seq, "blocked": blocked, "checks": o["checks"],
            "budget_hit": o["budget_hit"], "bends": [{"bend": names[b["id"]], "id": b["id"], "angle": round(b["angle"], 3),
                                                      "direction": b["direction"], "r": b["r"], "length": round(b["length"], 4)}
                                                     for b in res["bends"]],
            "per_bend": {names[c]: {"alone": p["first"]["ok"], "after_all_others": p["last"]["ok"],
                                    "hits": (p["first"]["hits"] or p["last"]["hits"])[:3]} for c, p in o["per_bend"].items()},
            "model": model, "evidence": "model (2D press-brake cross-section, stated tools)", "headline": head}

