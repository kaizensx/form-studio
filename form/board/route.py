"""Form Studio's own board router: a grid maze router for two copper layers with vias, rip-up and reroute, and
PathFinder negotiated congestion, followed by a pull-tight pass. Pure Python; no KiCad and no Freerouting code.

    res = route(doc)             # doc: form.board.pcb.Pcb; tracks and vias are added to it; res says what happened
    doc.save(out)

How it works

1.  The grid. Track centres run on a square grid over the board. For each net class, every cell is marked with
    the copper that a track of that class centred there would come too close to: the pads, kept tracks and vias of
    other nets grown by half the track width plus the larger of the two clearances, the board edge grown by the
    edge clearance, non-plated holes, keep-out areas. The growth is sqrt(R^2 + g^2 / 2) for a need R and pitch g, so
    that a straight or diagonal step between two free cells is also at least R away at every point between them
    (the proof is in docs/BOARDS.md). A second map does the same for a via. The pitch is chosen so that tracks of
    the default class pack at their width plus clearance, to within the grid's rounding.
2.  A search. A* over (layer, cell) with eight moves, an octile heuristic to the target's box, a cost per bend and
    per via; or Lee's wavefront (four moves, expanded in order of cost) on small grids, which gives the path of
    fewest steps. Multi-pin nets are joined as a minimum spanning tree (Prim): each pad is routed to the tree
    grown so far.
3.  Net order: shortest span first; ties by name, so the same board always routes the same way.
4.  Rip-up and reroute. A net that finds no way is routed once more with other nets' copper allowed at a high
    cost; the nets that path crosses are removed and queued behind it. Each net can be removed a bounded number of
    times.
5.  Negotiated congestion (PathFinder: McMurchie and Ebeling, 1995). When rip-up leaves nets without a way, every
    net is routed with sharing allowed; a cell's cost grows with its present sharing and with its history of
    sharing, iteration after iteration, until no two nets share. If it does not get there, the nets still in
    conflict are removed and reported as not routed. A net is never dropped silently.
6.  Pull-tight. Each path is shortened to straight and 45 degree segments; every new segment is tested in closed
    form against the real copper shapes (form/board/geom.py) before it replaces the grid path.

The result is checked by Form Studio's own geometric check (form/board/drc.py), labelled as such, and by KiCad's
DRC when kicad-cli is installed (form/board/k2.py). Zone fills are not seen: fill the zones again in KiCad.
"""
from __future__ import annotations

import heapq
import math
import time

from . import drc, geom
from .pcb import Pcb, pad_copper

VERSION = 1
SQ2 = math.sqrt(2.0)
MOVES8 = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
MAX_CELLS = 450_000              # per layer; a larger board gets a coarser pitch, and the result says so
PIECE = 2.0                      # mm: long edges are stamped in pieces of this length


def auto_pitch(need: float, target: float = 0.1) -> float:
    """The pitch at which two tracks k cells apart are exactly `need` apart after the grid's safety growth:
    k g >= sqrt(need^2 + g^2 / 2), so g = need / sqrt(k^2 - 1/2), for the k that puts g nearest target."""
    k = max(1, round(need / target))
    return math.ceil(need / math.sqrt(k * k - 0.5) * 1.0005 * 1e4) / 1e4


class _Net:
    __slots__ = ("id", "name", "k", "cls", "terms", "wires", "vias", "stubs", "pins", "routed", "why", "span",
                 "rips", "length", "expansions", "dead", "missing", "fixed_fail")

    def __init__(self, nid, name, k, cls):
        self.id, self.name, self.k, self.cls = nid, name, k, cls
        self.dead: list = []           # pads no track of this net can legally reach (fixed copper, keep-outs, edge)
        self.missing: list = []        # pads a partial route left out
        self.fixed_fail = False        # no way even with every other routed net ignored
        self.terms: list = []
        self.wires: list = []          # (layer index, [cell, ...]) and after pull-tight (layer, [(x, y), ...])
        self.vias: list = []           # cells
        self.stubs: list = []          # (layer index, cell, (x, y))
        self.pins: set = set()
        self.routed = False
        self.why = ""
        self.span = 0.0
        self.rips = 0
        self.length = 0.0
        self.expansions = 0


class Router:
    def __init__(self, doc: Pcb, pitch: float | None = None, layers=("F.Cu", "B.Cu"), nets=None, skip=None,
                 keep_existing: bool = True, via_cost: float = 4.0, bend_cost: float = 0.25, vias: bool = True,
                 algorithm: str = "auto", max_rips: int = 4, max_iterations: int = 40, time_limit: float = 120.0):
        self.doc = doc
        self.t0 = time.time()
        self.time_limit = time_limit
        self.notes: list[str] = []
        self.algorithm = algorithm
        self.max_rips, self.max_iterations = max_rips, max_iterations
        cu = doc.cu_layers()
        self.L = [x for x in layers if x in cu] or ["F.Cu"]
        if len(cu) > 2:
            self.notes.append(f"The board has {len(cu)} copper layers; Form Studio's router uses {', '.join(self.L)} only.")
        self.nl = len(self.L)
        self.use_vias = vias and self.nl == 2
        rules = doc.rules
        names = doc.nets()
        pads = doc.pads()
        by: dict = {}
        for p in pads:
            if p["net"] > 0 and p["kind"] != "np_thru_hole":
                by.setdefault(p["net"], []).append(p)
        want = set(nets) if nets else None
        skip = set(skip or ())
        self.cls_of = {n: rules.for_net(nm) for n, nm in names.items()}
        self.dflt = rules.for_net("")
        ks: list = []
        self.nets: dict[int, _Net] = {}
        self.skipped: list = []
        for nid in sorted(by):
            nm = names.get(nid, str(nid))
            if len(by[nid]) < 2:
                continue
            if (want is not None and nm not in want) or nm in skip:
                self.skipped.append(nm)
                continue
            c = self.cls_of.get(nid) or self.dflt
            key = (c["track_width"], c["clearance"], c["via_diameter"], c["via_drill"])
            if key not in ks:
                ks.append(key)
            self.nets[nid] = _Net(nid, nm, ks.index(key), c)
        if not ks:
            d = self.dflt
            ks.append((d["track_width"], d["clearance"], d["via_diameter"], d["via_drill"]))
        self.K = ks
        self.edge_clr = rules.board["min_copper_edge_clearance"]
        self.hole_clr = rules.board["min_hole_clearance"]
        self.h2h = rules.board["min_hole_to_hole"]
        self.max_clr = max([k[1] for k in ks] + [c["clearance"] for c in self.cls_of.values()] + [self.dflt["clearance"]])
        self.pads_by_net = by
        self._grid(pitch)
        self.via_cost = via_cost / self.g
        self.bend_cost = bend_cost
        self._static(keep_existing)
        self._terminals(keep_existing)
        self._masks()
        n2 = self.n * self.nl
        self.gc = [0.0] * n2
        self.par = [0] * n2
        self.dirv = [0] * n2
        self.seen = [0] * n2
        self.closed = [0] * n2
        self.tgt = [0] * n2
        self.sid = 0
        self.hist = [[0.0] * self.n for _ in range(self.nl)]
        self.occ_t = [[[0] * self.n for _ in range(self.nl)] for _ in ks]
        self.own_t = [[[0] * self.n for _ in range(self.nl)] for _ in ks]
        self.occ_v = [[0] * self.n for _ in ks]
        self.own_v = [[0] * self.n for _ in ks]
        self.stats = {"expansions": 0, "searches": 0, "ripped": 0, "negotiation_iterations": 0, "lee_searches": 0,
                      "astar_searches": 0}

    # ---- the grid --------------------------------------------------------------------------------------------------
    def _grid(self, pitch):
        outline, cutouts, notes = self.doc.edges()
        self.notes += notes
        if not outline:
            raise ValueError("The board has no closed outline (Edge.Cuts), so there is nowhere to route.")
        self.outline, self.cutouts = outline, cutouts
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        w0, c0 = self.K[0][0], self.K[0][1]
        need = min(k[0] + k[1] for k in self.K)
        auto = pitch is None
        g = float(pitch) if pitch else auto_pitch(need)
        while auto and ((x1 - x0) / g) * ((y1 - y0) / g) > MAX_CELLS:
            k = round(need / g)
            if k <= 1:
                g = math.sqrt((x1 - x0) * (y1 - y0) / MAX_CELLS) * 1.01
                break
            g = auto_pitch(need, need / (k - 1))
        if not 0.02 <= g <= 2.0:
            raise ValueError("pitch must be between 0.02 and 2 mm.")
        self.g = g
        rho = max(max(k[0] for k in self.K) / 2 + max(k[2] for k in self.K) / 2 + self.max_clr,
                  max(k[0] for k in self.K) + self.max_clr, self.edge_clr + max(k[2] for k in self.K) / 2,
                  max(k[2] for k in self.K) + self.max_clr, max(k[3] for k in self.K) + self.h2h)
        self.B = int(math.ceil(math.sqrt(rho * rho + g * g / 2) / g)) + 2
        self.X0, self.Y0 = x0 - self.B * g, y0 - self.B * g
        self.nx = int(math.floor((x1 - x0) / g)) + 1 + 2 * self.B
        self.ny = int(math.floor((y1 - y0) / g)) + 1 + 2 * self.B
        self.n = self.nx * self.ny
        self.DC = [dx + dy * self.nx for dx, dy in MOVES8]
        del w0, c0

    def xy(self, c: int):
        return self.X0 + (c % self.nx) * self.g, self.Y0 + (c // self.nx) * self.g

    def _cells_near(self, shape, r: float) -> list[int]:
        """Cells whose centre is closer than r to a shape's copper. Long thin shapes are walked in pieces."""
        pts, sr = shape
        g, nx, ny, X0, Y0 = self.g, self.nx, self.ny, self.X0, self.Y0
        out = []
        pieces = [shape]
        if len(pts) == 2:
            a, b = pts
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            k = int(L // PIECE) + 1
            if k > 1:
                pieces = [(((a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k),
                            (a[0] + (b[0] - a[0]) * (i + 1) / k, a[1] + (b[1] - a[1]) * (i + 1) / k)), sr) for i in range(k)]
        lim = r - 1e-9
        for s in pieces:
            bx0, by0, bx1, by1 = geom.bbox(s)
            ix0 = max(0, int(math.floor((bx0 - r - X0) / g)))
            ix1 = min(nx - 1, int(math.ceil((bx1 + r - X0) / g)))
            iy0 = max(0, int(math.floor((by0 - r - Y0) / g)))
            iy1 = min(ny - 1, int(math.ceil((by1 + r - Y0) / g)))
            for iy in range(iy0, iy1 + 1):
                y = Y0 + iy * g
                base = iy * nx
                for ix in range(ix0, ix1 + 1):
                    if geom.pt_gap((X0 + ix * g, y), s) < lim:
                        out.append(base + ix)
        return out

    @staticmethod
    def _mark(arr, cells, owner):
        for c in cells:
            o = arr[c]
            if o == -1:
                arr[c] = owner
            elif o != owner:
                arr[c] = -2

    def _fill_polygon(self, arr, poly, inside: bool):
        """Mark as fixed (-2) the cells inside a polygon, or the cells outside it (scanline, even-odd)."""
        g, nx, ny, X0, Y0 = self.g, self.nx, self.ny, self.X0, self.Y0
        m = len(poly)
        for iy in range(ny):
            y = Y0 + iy * g
            xs = []
            for i in range(m):
                xa, ya = poly[i]
                xb, yb = poly[i - 1]
                if (ya > y) != (yb > y):
                    xs.append((xb - xa) * (y - ya) / (yb - ya) + xa)
            xs.sort()
            base = iy * nx
            spans = []                        # inside spans as cell index ranges [a, b)
            for j in range(0, len(xs) - 1, 2):
                a = max(0, int(math.ceil((xs[j] - X0) / g)))
                b = min(nx, int(math.floor((xs[j + 1] - X0) / g)) + 1)
                if b > a:
                    spans.append((a, b))
            if inside:
                for a, b in spans:
                    arr[base + a:base + b] = [-2] * (b - a)
            else:
                at = 0
                for a, b in spans:
                    if a > at:
                        arr[base + at:base + a] = [-2] * (a - at)
                    at = max(at, b)
                if at < nx:
                    arr[base + at:base + nx] = [-2] * (nx - at)

    # ---- what is already on the board ------------------------------------------------------------------------------
    def _static(self, keep_existing: bool):
        doc, g = self.doc, self.g
        li = {name: i for i, name in enumerate(self.L)}
        obs = []                     # (shape, owner, layer indices, clearance rule, kind)
        for f in doc.footprints():
            for p in f["pads"]:
                shape, _exact = pad_copper(p)
                if p["kind"] == "np_thru_hole":
                    if p["drill"]:
                        obs.append((geom.circle((p["x"], p["y"]), p["drill_max"] or p["drill"]), -2, list(range(self.nl)),
                                    self.hole_clr, "hole"))
                    continue
                ls = [li[x] for x in p["layers"] if x in li]
                if ls:
                    obs.append((shape, p["net"] if p["net"] > 0 else -2, ls, None, "pad"))
        self.fixed_tracks = 0
        if keep_existing:
            for t in doc.tracks():
                if t["layer"] in li:
                    obs.append((geom.capsule(t["a"], t["b"], t["w"]), t["net"] if t["net"] > 0 else -2, [li[t["layer"]]],
                                None, "track"))
                    self.fixed_tracks += 1
            for v in doc.vias():
                obs.append((geom.circle(v["at"], v["size"]), v["net"] if v["net"] > 0 else -2, list(range(self.nl)), None, "via"))
        edges = []
        for loop in [self.outline] + self.cutouts:
            for i in range(len(loop)):
                edges.append(geom.capsule(loop[i], loop[(i + 1) % len(loop)], 0.0))
        self.kos = [z for z in doc.keepouts() if set(z["layers"]) & set(self.L)]
        self.obs, self.edges = obs, edges
        # exact shapes for the pull-tight pass
        self.index = geom.Index(2.0)
        for shape, owner, ls, rule, kind in obs:
            self.index.add(shape, net=owner, layers=ls, need=rule, kind=kind)
        for e in edges:
            self.index.add(e, net=-2, layers=list(range(self.nl)), need=self.edge_clr, kind="edge")
        for z in self.kos:
            ls = [li[x] for x in z["layers"] if x in li]
            poly = z["polygon"]
            for i in range(len(poly)):
                self.index.add(geom.capsule(poly[i], poly[(i + 1) % len(poly)], 0.0), net=-2, layers=ls, need=0.0,
                               kind="keepout_" + ("t" if z["keepout"].get("tracks") == "not_allowed" else "") +
                                    ("v" if z["keepout"].get("vias") == "not_allowed" else ""))
        self.own = []                 # per class: per layer: owner map for a track centre
        self.vown = []                # per class: owner map for a via centre (both layers at once)
        cache: dict = {}

        def near(i, shape, r):
            key = (i, round(r, 6))
            if key not in cache:
                cache[key] = self._cells_near(shape, r)
            return cache[key]
        for (w, clr, vd, vdr) in self.K:
            tr = [[-1] * self.n for _ in range(self.nl)]
            va = [-1] * self.n
            for a in tr + [va]:
                self._fill_polygon(a, self.outline, inside=False)
                for c in self.cutouts:
                    self._fill_polygon(a, c, inside=True)
            for i, e in enumerate(edges):
                cells = near(("e", i), e, math.sqrt((self.edge_clr + w / 2) ** 2 + g * g / 2))
                for a in tr:
                    self._mark(a, cells, -2)
                self._mark(va, near(("e", i), e, self.edge_clr + vd / 2), -2)
            for z in self.kos:
                poly = z["polygon"]
                ring = [geom.capsule(poly[i], poly[(i + 1) % len(poly)], 0.0) for i in range(len(poly))]
                if z["keepout"].get("tracks") == "not_allowed":
                    for name in z["layers"]:
                        if name in li:
                            self._fill_polygon(tr[li[name]], poly, inside=True)
                            for j, e in enumerate(ring):
                                self._mark(tr[li[name]], near(("k", id(z), j), e, math.sqrt((w / 2) ** 2 + g * g / 2)), -2)
                if z["keepout"].get("vias") == "not_allowed":
                    self._fill_polygon(va, poly, inside=True)
                    for j, e in enumerate(ring):
                        self._mark(va, near(("k", id(z), j), e, vd / 2), -2)
            for i, (shape, owner, ls, rule, kind) in enumerate(obs):
                oc = (self.cls_of.get(owner) or self.dflt)["clearance"] if owner > 0 else self.dflt["clearance"]
                need = rule if rule is not None else max(clr, oc)
                cells = near(i, shape, math.sqrt((w / 2 + need) ** 2 + g * g / 2))
                for l in ls:
                    self._mark(tr[l], cells, owner)
                self._mark(va, near(i, shape, vd / 2 + need), owner)
                if kind in ("pad", "via", "hole"):          # no via on or touching a pad, also of its own net
                    self._mark(va, near(i, shape, vd / 2 + (self.h2h if kind == "hole" else 0.0)), -2)
            self.own.append(tr)
            self.vown.append(va)

    def _terminals(self, keep_existing: bool):
        g, nx = self.g, self.nx
        li = {name: i for i, name in enumerate(self.L)}
        conn = drc.connectivity(self.doc) if (keep_existing and self.fixed_tracks) else {}
        for net in self.nets.values():
            pads = self.pads_by_net[net.id]
            w = net.cls["track_width"]
            groups = None
            if net.name in conn:
                key = {f"{p['ref']}.{p['num']}": p for p in pads}
                groups = [[key[x] for x in grp if x in key] for grp in conn[net.name]["groups"]]
            groups = groups or [[p] for p in sorted(pads, key=lambda p: (p["ref"], p["num"], p["x"], p["y"]))]
            xs = [p["x"] for p in pads]
            ys = [p["y"] for p in pads]
            net.span = (max(xs) - min(xs)) + (max(ys) - min(ys))
            for grp in groups:
                states: dict = {}
                for p in grp:
                    shape, _e = pad_copper(p)
                    bx0, by0, bx1, by1 = geom.bbox(shape)
                    best, inner, inpad = None, [], []
                    for iy in range(int(math.floor((by0 - self.Y0) / g)) - 1, int(math.ceil((by1 - self.Y0) / g)) + 2):
                        for ix in range(int(math.floor((bx0 - self.X0) / g)) - 1, int(math.ceil((bx1 - self.X0) / g)) + 2):
                            if not (0 <= ix < nx and 0 <= iy < self.ny):
                                continue
                            pt = (self.X0 + ix * g, self.Y0 + iy * g)
                            ins = geom.inset(pt, shape)
                            c = iy * nx + ix
                            if ins >= w / 2 - 1e-9:
                                inner.append(c)
                            elif ins >= 0:
                                inpad.append(c)
                            d = math.hypot(pt[0] - p["x"], pt[1] - p["y"])
                            if best is None or d < best[0]:
                                best = (d, c)
                    cells = [(c, True) for c in inner] or [(c, False) for c in inpad] or ([(best[1], True)] if best else [])
                    for l in [li[x] for x in p["layers"] if x in li]:
                        own = self.own[net.k][l]
                        # a track is led to the pad's centre only when the centre itself is clear of other copper
                        centre_ok = self._clear_seg((p["x"], p["y"]), (p["x"], p["y"]), l, net)
                        for c, stub in cells:
                            if own[c] in (-1, net.id):
                                states[l * self.n + c] = (p["x"], p["y"]) if (stub and centre_ok) else None
                cx = sum(p["x"] for p in grp) / len(grp)
                cy = sum(p["y"] for p in grp) / len(grp)
                names = [f"{p['ref']}.{p['num']}" for p in grp]
                if states:
                    net.terms.append({"states": states, "at": (cx, cy), "pads": names})
                else:
                    net.dead += names
            if len(groups) < 2:
                net.routed = True
                net.why = "already joined by the tracks on the board"
            elif len(net.terms) < 2:
                net.fixed_fail = True
                net.why = "no legal way onto its pads at this track width and clearance"

    def _masks(self):
        g, nx = self.g, self.nx

        def mask(dx, dy, r):
            R = int(math.ceil(r / g)) + 1
            out = []
            a, b = (0.0, 0.0), (dx * g, dy * g)
            for oy in range(min(0, dy) - R, max(0, dy) + R + 1):
                for ox in range(min(0, dx) - R, max(0, dx) + R + 1):
                    if geom.pt_seg((ox * g, oy * g), a, b) < r - 1e-9:
                        out.append(oy * nx + ox)
            return out
        nk = len(self.K)
        self.m_tt = [[None] * nk for _ in range(nk)]      # [router class][owner class] -> 9 masks (8 steps, then a dot)
        self.m_tv = [[None] * nk for _ in range(nk)]      # a via centre of the router class against the owner's track
        self.m_vt = [[None] * nk for _ in range(nk)]      # a track centre of the router class against the owner's via
        self.m_vv = [[None] * nk for _ in range(nk)]
        for a, (wa, ca, va, da) in enumerate(self.K):
            for b, (wb, cb, vb, db) in enumerate(self.K):
                c = max(ca, cb)
                rt = math.sqrt((wa / 2 + wb / 2 + c) ** 2 + g * g / 2)
                self.m_tt[a][b] = [mask(dx, dy, rt) for dx, dy in MOVES8] + [mask(0, 0, rt)]
                rv = va / 2 + wb / 2 + c
                self.m_tv[a][b] = [mask(dx, dy, rv) for dx, dy in MOVES8] + [mask(0, 0, rv)]
                self.m_vt[a][b] = mask(0, 0, math.sqrt((vb / 2 + wa / 2 + c) ** 2 + g * g / 2))
                self.m_vv[a][b] = mask(0, 0, max(va / 2 + vb / 2 + c, da / 2 + db / 2 + self.h2h))

    # ---- a routed net's copper on the shared maps --------------------------------------------------------------------
    def _stamp(self, net: _Net, sign: int):
        dcs = self.DC
        for a in range(len(self.K)):
            mtt, mtv = self.m_tt[a][net.k], self.m_tv[a][net.k]
            ov, wv = self.occ_v[a], self.own_v[a]
            for l, cells in net.wires:
                ot, wt = self.occ_t[a][l], self.own_t[a][l]
                prev = None
                for c in cells:
                    if prev is None:
                        if len(cells) == 1:
                            mt, mv, base = mtt[8], mtv[8], c
                        else:
                            prev = c
                            continue
                    else:
                        d = dcs.index(c - prev)
                        mt, mv, base = mtt[d], mtv[d], prev
                    for o in mt:
                        ot[base + o] += sign
                    for o in mv:
                        ov[base + o] += sign
                    if sign > 0:
                        for o in mt:
                            wt[base + o] = net.id
                        for o in mv:
                            wv[base + o] = net.id
                    prev = c
            mt, mv = self.m_vt[a][net.k], self.m_vv[a][net.k]
            for c in net.vias:
                for l in range(self.nl):
                    ot, wt = self.occ_t[a][l], self.own_t[a][l]
                    for o in mt:
                        ot[c + o] += sign
                        if sign > 0:
                            wt[c + o] = net.id
                for o in mv:
                    ov[c + o] += sign
                    if sign > 0:
                        wv[c + o] = net.id

    def _conflicts(self, net: _Net, wires=None, vias=None) -> list:
        """(layer or -1 for a via, cell) of this net's path that lie in another net's room. The net must not be stamped."""
        out = []
        for l, cells in (net.wires if wires is None else wires):
            ot = self.occ_t[net.k][l]
            out += [(l, c) for c in cells if ot[c] > 0]
        ov = self.occ_v[net.k]
        out += [(-1, c) for c in (net.vias if vias is None else vias) if ov[c] > 0]
        return out

    # ---- searching ---------------------------------------------------------------------------------------------------
    def _search(self, net: _Net, sources, box, hard: bool, pf: float, lee: bool = False):
        """From any source state to any state marked in self.tgt. Returns the states source..target, or None."""
        n, nx = self.n, self.nx
        self.sid += 1
        sid = self.sid
        gc, par, dirv, seen, closed, tgt = self.gc, self.par, self.dirv, self.seen, self.closed, self.tgt
        tid = self.tid
        owns = self.own[net.k]
        occs = self.occ_t[net.k]
        vown, vocc = self.vown[net.k], self.occ_v[net.k]
        hist = self.hist
        nid = net.id
        tx0, ty0, tx1, ty1 = box
        vcost = self.via_cost
        bend = 0.0 if lee else self.bend_cost
        pfm = 1.0 + pf
        use_hist = not hard
        moves = [(MOVES8[i][0], MOVES8[i][1], self.DC[i], (SQ2 if i % 2 else 1.0), i) for i in range(8) if not (lee and i % 2)]
        heap = []
        cnt = 0
        for s in sorted(sources):
            seen[s] = sid
            gc[s] = 0.0
            par[s] = -1
            dirv[s] = -1
            heap.append((0.0, cnt, s))
            cnt += 1
        heapq.heapify(heap)
        pop, push = heapq.heappop, heapq.heappush
        exp = 0
        found = -1
        use_vias = self.use_vias
        while heap:
            _f, _c, s = pop(heap)
            if closed[s] == sid:
                continue
            closed[s] = sid
            if tgt[s] == tid:
                found = s
                break
            exp += 1
            if not exp & 0x3FFF and time.time() - self.t0 > self.time_limit:
                break
            l = s // n
            c = s - l * n
            x = c % nx
            y = c // nx
            gs = gc[s]
            ds = dirv[s]
            own = owns[l]
            occ = occs[l]
            hl = hist[l]
            base = l * n
            for dx, dy, dc, cost, di in moves:
                c2 = c + dc
                o = own[c2]
                if o != -1 and o != nid:
                    continue
                s2 = base + c2
                if closed[s2] == sid:
                    continue
                m = cost
                if occ[c2]:
                    if hard:
                        continue
                    m *= pfm
                if use_hist:
                    m *= 1.0 + hl[c2]
                if di != ds and ds >= 0:
                    m += bend
                ng = gs + m
                if seen[s2] == sid and ng >= gc[s2]:
                    continue
                seen[s2] = sid
                gc[s2] = ng
                par[s2] = s
                dirv[s2] = di
                x2 = x + dx
                y2 = y + dy
                hx = tx0 - x2 if x2 < tx0 else (x2 - tx1 if x2 > tx1 else 0)
                hy = ty0 - y2 if y2 < ty0 else (y2 - ty1 if y2 > ty1 else 0)
                if lee:
                    h = 0.0
                else:
                    h = hx + 0.41421356 * hy if hx > hy else hy + 0.41421356 * hx
                cnt += 1
                push(heap, (ng + h, cnt, s2))
            if use_vias:
                vo = vown[c]
                if vo == -1 or vo == nid:
                    l2 = 1 - l
                    o = owns[l2][c]
                    s2 = l2 * n + c
                    if (o == -1 or o == nid) and closed[s2] != sid:
                        m = vcost
                        if vocc[c] or occs[l2][c]:
                            if hard:
                                continue
                            m *= pfm
                        if use_hist:
                            m *= 1.0 + hist[l2][c]
                        ng = gs + m
                        if not (seen[s2] == sid and ng >= gc[s2]):
                            seen[s2] = sid
                            gc[s2] = ng
                            par[s2] = s
                            dirv[s2] = -1
                            hx = tx0 - x if x < tx0 else (x - tx1 if x > tx1 else 0)
                            hy = ty0 - y if y < ty0 else (y - ty1 if y > ty1 else 0)
                            h = 0.0 if lee else (hx + 0.41421356 * hy if hx > hy else hy + 0.41421356 * hx)
                            cnt += 1
                            push(heap, (ng + h, cnt, s2))
        self.stats["expansions"] += exp
        self.stats["searches"] += 1
        self.stats["lee_searches" if lee else "astar_searches"] += 1
        net.expansions += exp
        if found < 0:
            return None
        path = [found]
        while par[path[-1]] >= 0:
            path.append(par[path[-1]])
        path.reverse()
        return path

    def _route_net(self, net: _Net, hard: bool, pf: float = 0.0, partial: bool = False) -> bool:
        """Join the net's terminals as a tree. On success its wires, vias and stubs are set (not stamped).
        partial: a terminal that cannot be reached is left out (net.missing) and the rest are still joined."""
        n, nx = self.n, self.nx
        terms = net.terms
        net.missing = []
        if len(terms) < 2:
            return False
        self.tid = getattr(self, "tid", 0) + 1
        tid = self.tid
        tgt = self.tgt
        tree: dict = {}
        wires, vias, stubs, pins = [], [], [], set()
        done = [0]
        left = list(range(1, len(terms)))

        def add(states):
            for s, stub in states.items():
                tgt[s] = tid
                tree[s] = stub
        add(terms[0]["states"])
        txs = [s % n % nx for s in tree]
        tys = [s % n // nx for s in tree]
        box = [min(txs), min(tys), max(txs), max(tys)]
        lee = self.algorithm == "lee" or (self.algorithm == "auto" and hard and self.n <= 40_000)
        while left:
            # Prim: the terminal nearest the tree's terminals
            best = min(left, key=lambda i: (min(math.hypot(terms[i]["at"][0] - terms[j]["at"][0],
                                                           terms[i]["at"][1] - terms[j]["at"][1]) for j in done), i))
            src = terms[best]["states"]
            if any(tgt[s] == tid for s in src):
                path = None                       # the pads overlap: their copper already joins them
            else:
                path = self._search(net, src, box, hard, pf, lee)
                if path is None:
                    net.why = (f"no way found to {', '.join(terms[best]['pads'])}" +
                               (" within the time limit" if time.time() - self.t0 > self.time_limit else ""))
                    if not partial:
                        return False
                    net.missing += terms[best]["pads"]
                    left.remove(best)
                    continue
            if path:
                if src[path[0]] is not None:
                    stubs.append((path[0] // n, path[0] % n, src[path[0]]))
                end = path[-1]
                if tree.get(end) is not None:
                    stubs.append((end // n, end % n, tree[end]))
                pins.add(path[0])
                pins.add(end)
                run = [path[0]]
                for s in path[1:]:
                    if s // n != run[-1] // n:
                        wires.append((run[0] // n, [q % n for q in run]))
                        vias.append(s % n)
                        pins.add(run[-1])
                        pins.add(s)
                        run = [s]
                    else:
                        run.append(s)
                wires.append((run[0] // n, [q % n for q in run]))
                for s in path:
                    if tgt[s] != tid:
                        tgt[s] = tid
                        tree[s] = None
                        cx, cy = s % n % nx, s % n // nx
                        if cx < box[0]:
                            box[0] = cx
                        if cx > box[2]:
                            box[2] = cx
                        if cy < box[1]:
                            box[1] = cy
                        if cy > box[3]:
                            box[3] = cy
            add(src)
            for s in src:
                cx, cy = s % n % nx, s % n // nx
                box = [min(box[0], cx), min(box[1], cy), max(box[2], cx), max(box[3], cy)]
            done.append(best)
            left.remove(best)
        if net.missing and len(done) < 2:
            return False
        net.wires, net.vias, net.stubs, net.pins = wires, vias, stubs, pins
        if not net.missing:
            net.why = ""
        return True

    def _clear(self, net: _Net):
        net.wires, net.vias, net.stubs, net.pins = [], [], [], set()
        net.routed = False

    # ---- the passes --------------------------------------------------------------------------------------------------
    def _timeout(self) -> bool:
        return time.time() - self.t0 > self.time_limit

    def _ripup(self, order: list) -> list:
        from collections import deque
        q = deque(order)
        failed = []
        while q:
            net = q.popleft()
            if net.routed:
                continue
            if self._timeout():
                net.why = net.why or "not tried: the time limit was reached"
                failed.append(net)
                continue
            if self._route_net(net, hard=True):
                net.routed = True
                self._stamp(net, 1)
                continue
            why = net.why
            if net.fixed_fail or net.rips >= self.max_rips or not self._route_net(net, hard=False, pf=30.0):
                if net.fixed_fail:
                    net.why = why
                elif net.rips < self.max_rips:
                    net.fixed_fail = True
                    net.why = why + ": fixed copper, keep-outs or the board edge leave no way at this width and clearance"
                else:
                    net.why = why + f" (after {net.rips} rip-ups)"
                self._clear(net)
                failed.append(net)
                continue
            hits = self._conflicts(net)
            victims = set()
            for l, c in hits:
                victims.add(self.own_v[net.k][c] if l < 0 else self.own_t[net.k][l][c])
            victims = [self.nets[v] for v in sorted(victims) if v in self.nets and self.nets[v].routed]
            relaxed = (net.wires, net.vias)
            self._clear(net)
            for v in victims:
                self._stamp(v, -1)
            if self._conflicts(net, *relaxed):          # the owner marks were stale: find who is really in the way
                for v in [m for m in self.nets.values() if m.routed and m not in victims]:
                    before = len(self._conflicts(net, *relaxed))
                    if not before:
                        break
                    self._stamp(v, -1)
                    if len(self._conflicts(net, *relaxed)) < before:
                        victims.append(v)
                    else:
                        self._stamp(v, 1)
            net.rips += 1
            for v in victims:
                self._clear(v)
                self.stats["ripped"] += 1
            if self._route_net(net, hard=True):
                net.routed = True
                self._stamp(net, 1)
            else:
                self._clear(net)
                failed.append(net)
            q.extendleft(reversed(victims))
        return [f for f in failed if not f.routed]

    def _negotiate(self, order: list) -> bool:
        """PathFinder over every net. True when no two nets share room."""
        pf, hf = 0.6, 0.35
        live = [m for m in order if not m.fixed_fail]
        for it in range(self.max_iterations):
            self.stats["negotiation_iterations"] += 1
            for net in live:
                if self._timeout():
                    return False
                if net.routed:
                    self._stamp(net, -1)
                keep = (net.wires, net.vias, net.stubs, net.pins, net.routed)
                if self._route_net(net, hard=False, pf=pf):
                    net.routed = True
                    self._stamp(net, 1)
                else:                                # fixed copper leaves no way at all
                    net.wires, net.vias, net.stubs, net.pins, net.routed = keep
                    if net.routed:
                        self._stamp(net, 1)
            total = 0
            for net in live:
                if not net.routed:
                    continue
                self._stamp(net, -1)
                hits = self._conflicts(net)
                self._stamp(net, 1)
                total += len(hits)
                for l, c in hits:
                    for ll in (range(self.nl) if l < 0 else (l,)):
                        self.hist[ll][c] += hf
            if total == 0:
                return all(m.routed for m in live)
            pf *= 1.6
        return False

    def _legalise(self, order: list) -> None:
        """After a negotiation that did not settle: remove the nets still in conflict, most conflicts first."""
        while True:
            worst, wn = 0, None
            for net in order:
                if not net.routed or not net.wires:
                    continue
                self._stamp(net, -1)
                k = len(self._conflicts(net))
                self._stamp(net, 1)
                if k > worst:
                    worst, wn = k, net
            if wn is None:
                return
            self._stamp(wn, -1)
            self._clear(wn)
            wn.why = "no room found: negotiated routing did not settle with this net in"

    def run(self, strategy: str = "auto") -> None:
        order = sorted([m for m in self.nets.values() if not m.routed], key=lambda m: (m.span, m.name))
        self.order = [m.name for m in order]
        self.phase = "rip-up and reroute"
        failed = self._ripup(order) if strategy in ("auto", "ripup") else list(order)
        if any(not m.fixed_fail for m in failed) and strategy in ("auto", "negotiated") and not self._timeout():
            snap = {m.id: (m.wires, m.vias, m.stubs, m.pins, m.routed, m.why) for m in order}
            n_before = sum(1 for m in order if m.routed)
            self.phase = "negotiated congestion"
            settled = self._negotiate(order)
            if not settled:
                self._legalise(order)
                for m in order:                               # one more exact try for what was removed
                    if not m.routed and not self._timeout() and self._route_net(m, hard=True):
                        m.routed = True
                        self._stamp(m, 1)
            if sum(1 for m in order if m.routed) < n_before:   # negotiation did worse: keep the rip-up result
                for m in order:
                    if m.routed:
                        self._stamp(m, -1)
                for m in order:
                    m.wires, m.vias, m.stubs, m.pins, m.routed, m.why = snap[m.id]
                    if m.routed:
                        self._stamp(m, 1)
                self.phase = "rip-up and reroute (negotiation did not do better)"
        for m in order:                    # what cannot be finished: join the pads that can be, and say which cannot
            if not m.routed and len(m.terms) >= 2 and not self._timeout():
                why = m.why
                for _turn in range(len(m.terms)):          # the tree can start from any pad: try each as the root
                    if self._route_net(m, hard=True, partial=True):
                        m.routed = True
                        self._stamp(m, 1)
                        break
                    m.terms = m.terms[1:] + m.terms[:1]
                m.why = why or m.why
            if not m.routed and not m.why:
                m.why = "no way found"

    @staticmethod
    def complete(m: _Net) -> bool:
        return m.routed and not m.missing and not m.dead

    # ---- pull-tight --------------------------------------------------------------------------------------------------
    def _clear_seg(self, a, b, l: int, net: _Net) -> bool:
        w = net.cls["track_width"]
        cn = net.cls["clearance"]
        cap = geom.capsule(a, b, w)
        for _i, s, m in self.index.near(geom.bbox(cap), self.max_clr + self.edge_clr + 0.01):
            if m["net"] == net.id or l not in m["layers"]:
                continue
            kind = m["kind"]
            if kind.startswith("keepout"):
                if "t" not in kind[8:]:
                    continue
                need = 0.0
            elif m["need"] is not None:
                need = m["need"]
            else:
                oc = (self.cls_of.get(m["net"]) or self.dflt)["clearance"] if m["net"] > 0 else self.dflt["clearance"]
                need = max(cn, oc)
            if geom.gap(cap, s) < need + 1e-7:
                return False
        return True

    @staticmethod
    def _compress(pts: list) -> list:
        out = [pts[0]]
        for i in range(1, len(pts)):
            if pts[i] == out[-1]:
                continue
            if len(out) >= 2:
                ax, ay = out[-2]
                bx, by = out[-1]
                cx, cy = pts[i]
                if (bx - ax) * (cy - by) == (by - ay) * (cx - bx) and (bx - ax) * (cx - bx) + (by - ay) * (cy - by) > 0:
                    out[-1] = pts[i]
                    continue
            out.append(pts[i])
        return out

    def _tight(self, pts: list, l: int, net: _Net) -> list:
        """Integer grid points -> fewer points: the farthest point reachable by one straight and one 45 degree leg."""
        g, X0, Y0 = self.g, self.X0, self.Y0
        P = lambda q: (X0 + q[0] * g, Y0 + q[1] * g)
        pts = self._compress(pts)
        changed = True
        rounds = 0
        while changed and rounds < 3:
            changed = False
            rounds += 1
            i = 0
            while i < len(pts) - 2:
                a = pts[i]
                for j in range(len(pts) - 1, i + 1, -1):
                    b = pts[j]
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    dg = min(abs(dx), abs(dy))
                    sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
                    if dg == 0 or abs(dx) == abs(dy):
                        mids = [None]
                    else:
                        mids = [(a[0] + sx * dg, a[1] + sy * dg), (b[0] - sx * dg, b[1] - sy * dg)]
                    old = sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(i, j))
                    for mid in mids:
                        legs = [(a, b)] if mid is None else [(a, mid), (mid, b)]
                        new = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in legs)
                        fewer = (j - i - 1) > (0 if mid is None else 1)
                        if not (new < old - 1e-9 or (new <= old + 1e-9 and fewer)):
                            continue
                        if all(self._clear_seg(P(p), P(q), l, net) for p, q in legs):
                            pts[i + 1:j] = [] if mid is None else [mid]
                            changed = True
                            break
                    else:
                        continue
                    break
                i += 1
            pts = self._compress(pts)
        return pts

    def smooth(self) -> None:
        g, X0, Y0, nx = self.g, self.X0, self.Y0, self.nx
        P = lambda q: (X0 + q[0] * g, Y0 + q[1] * g)
        routed = [m for m in self.nets.values() if m.routed and m.wires]
        ids: dict = {}
        pieces: dict = {}
        for net in routed:
            w = net.cls["track_width"]
            for wi, (l, cells) in enumerate(net.wires):
                pts = [(c % nx, c // nx) for c in cells]
                # split at pinned cells so junctions, vias and pad entries stay where they are
                runs, cur = [], [pts[0]]
                for k in range(1, len(pts)):
                    cur.append(pts[k])
                    if (l * self.n + cells[k]) in net.pins and k < len(pts) - 1:
                        runs.append(cur)
                        cur = [pts[k]]
                runs.append(cur)
                for ri, run in enumerate(runs):
                    run = self._compress(run)
                    pieces[(net.id, wi, ri)] = (l, run)
                    ids[(net.id, wi, ri)] = [self.index.add(geom.capsule(P(run[k]), P(run[k + 1]), w), net=net.id,
                                                            layers=[l], need=None, kind="track")
                                             for k in range(len(run) - 1)]
            for c in net.vias:
                self.index.add(geom.circle(self.xy(c), net.cls["via_diameter"]), net=net.id, layers=list(range(self.nl)),
                               need=None, kind="via")
        for net in routed:
            w = net.cls["track_width"]
            out = []
            for key in sorted(k for k in pieces if k[0] == net.id):
                l, run = pieces[key]
                for i in ids[key]:
                    self.index.remove(i)
                if len(run) > 2 and not self._timeout():
                    run = self._tight(list(run), l, net)
                ids[key] = [self.index.add(geom.capsule(P(run[k]), P(run[k + 1]), w), net=net.id, layers=[l], need=None,
                                           kind="track") for k in range(len(run) - 1)]
                out.append((l, [P(q) for q in run]))
            net.wires = out

    def write(self) -> dict:
        """Add every routed net's segments and vias to the document."""
        segs = vias = 0
        length = 0.0
        for net in sorted(self.nets.values(), key=lambda m: m.name):
            if not net.routed:
                continue
            w = net.cls["track_width"]
            net.length = 0.0
            for l, pts in net.wires:
                if pts and not isinstance(pts[0], tuple):
                    pts = [self.xy(c) for c in pts]
                for k in range(len(pts) - 1):
                    d = math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
                    if d < 1e-9:
                        continue
                    self.doc.add_segment(pts[k], pts[k + 1], w, self.L[l], net.id)
                    segs += 1
                    net.length += d
            for l, c, at in net.stubs:
                a = self.xy(c)
                d = math.hypot(at[0] - a[0], at[1] - a[1])
                if d > 1e-6:
                    self.doc.add_segment(a, at, w, self.L[l], net.id)
                    segs += 1
                    net.length += d
            for c in net.vias:
                self.doc.add_via(self.xy(c), net.cls["via_diameter"], net.cls["via_drill"], net.id)
                vias += 1
            length += net.length
        return {"segments": segs, "vias": vias, "length_mm": round(length, 3)}


def route(doc: Pcb, pitch: float | None = None, layers=("F.Cu", "B.Cu"), nets=None, skip=None, strategy: str = "auto",
          algorithm: str = "auto", keep_existing: bool = True, vias: bool = True, smooth: bool = True,
          via_cost: float = 4.0, bend_cost: float = 0.25, max_rips: int = 4, max_iterations: int = 40,
          time_limit: float = 120.0, check: bool = True) -> dict:
    """Route the board's unrouted nets and add the copper to doc. strategy: auto (rip-up and reroute, then negotiated
    congestion for what is left), ripup, or negotiated. algorithm: auto (Lee's wavefront on a small grid, A*
    otherwise), astar, lee. Returns the routed and unrouted nets with the reason, counts, and Form Studio's own
    geometric check of the result (labelled; not KiCad's DRC)."""
    if strategy not in ("auto", "ripup", "negotiated"):
        raise ValueError("strategy is auto, ripup or negotiated.")
    if algorithm not in ("auto", "astar", "lee"):
        raise ValueError("algorithm is auto, astar or lee.")
    t0 = time.time()
    if not keep_existing:
        doc.clear_routes()
    r = Router(doc, pitch=pitch, layers=layers, nets=nets, skip=skip, keep_existing=keep_existing, via_cost=via_cost,
               bend_cost=bend_cost, vias=vias, algorithm=algorithm, max_rips=max_rips, max_iterations=max_iterations,
               time_limit=time_limit)
    r.run(strategy)
    if smooth:
        r.smooth()
    wrote = r.write()
    joined = sorted(m.name for m in r.nets.values() if m.name not in r.order and m.routed)
    todo = [m for m in r.nets.values() if m.name not in joined]
    done = [m for m in todo if r.complete(m)]
    unrouted = []
    for m in sorted(todo, key=lambda m: m.name):
        if r.complete(m):
            continue
        every = [p for t in m.terms for p in t["pads"]] + m.dead
        left = sorted(set(m.dead + m.missing)) if m.routed else sorted(every)
        unrouted.append({"net": m.name, "why": m.why or "no legal way onto " + ", ".join(m.dead), "pads_not_joined": left,
                         "pads_joined": sorted(set(every) - set(left)), "partly_routed": bool(m.routed and m.wires)})
    out = {"by": "Form Studio router", "version": VERSION, "engine": "form",
           "nets": len(todo), "routed": len(done), "unrouted": unrouted, "already_joined": joined,
           "complete": len(done) == len(todo), **wrote,
           "per_net": [{"net": m.name, "class": m.cls["class"], "width_mm": m.cls["track_width"],
                        "length_mm": round(m.length, 3), "vias": len(m.vias), "ripped": m.rips,
                        "complete": r.complete(m)}
                       for m in sorted(todo, key=lambda m: m.name) if m.routed],
           "grid": {"pitch_mm": r.g, "cells_per_layer": r.n, "layers": r.L},
           "order": r.order, "phase": r.phase, "stats": dict(r.stats), "skipped": r.skipped,
           "rules": doc.rules.describe(), "seconds": round(time.time() - t0, 2), "notes": r.notes,
           "timed_out": time.time() - r.t0 > r.time_limit}
    if any(z["keepout"] is None for z in doc.zones()):
        out["notes"].append("The router does not see zone fills. Fill the zones again in KiCad (Edit > Fill All Zones) "
                            "before checking or ordering.")
    if check:
        out["check"] = drc.check(doc)
    return out
