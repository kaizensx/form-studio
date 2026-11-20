"""Mesh to editable CAD, the program route (form/recon/program.py, sketch.py, assembly.py): sketches read off a mesh,
Params pooled, snapped and mirrored, partial acceptance with the rest kept as the mesh, editability measured and
swept, exact Layer 1 edges, assemblies bound. Synthetic parts only (tests/recon_fixtures.py)."""
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = Path(tempfile.mkdtemp(prefix="form-recon-program-"))

import recon_fixtures as fx  # noqa: E402
from form.recon import sketch as sk  # noqa: E402


def rounded_rect(w, h, r, n=12):
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180)):
        for t in np.linspace(math.radians(a0), math.radians(a0 + 90), n):
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return np.array(pts)


class Sketches(unittest.TestCase):
    """A section loop becomes what a person would draw."""

    def test_rounded_rectangle(self):
        lp = sk.fit(rounded_rect(60, 40, 5), 0.01)
        self.assertEqual(lp.kind, "path")
        self.assertEqual(len(lp.nodes), 4)                                     # four corners, each rounded
        self.assertTrue(all(abs(n.r - 5) < 0.01 for n in lp.nodes))
        corners = sorted((round(float(n.p[0]), 3), round(float(n.p[1]), 3)) for n in lp.nodes)
        self.assertEqual(corners, [(-30, -20), (-30, 20), (30, -20), (30, 20)])   # where the lines meet, not polyline points
        self.assertLess(lp.err, 0.02)                                           # the sagitta of the input chords

    def test_circle_and_slot(self):
        t = np.linspace(0, 2 * math.pi, 64, endpoint=False)
        c = sk.fit(np.c_[3 + 2.75 * np.cos(t), -1 + 2.75 * np.sin(t)], 0.01)
        self.assertEqual(c.kind, "circle")
        self.assertAlmostEqual(c.r, 2.75, places=3)
        a = np.linspace(-math.pi / 2, math.pi / 2, 16)
        slot = np.r_[np.c_[10 + 3 * np.cos(a), 3 * np.sin(a)], np.c_[-10 - 3 * np.cos(a), -3 * np.sin(a)]]
        lp = sk.fit(slot, 0.01)
        self.assertEqual([e.kind for e in lp.edges].count("arc"), 2)            # two half circles, two lines
        self.assertEqual([e.kind for e in lp.edges].count("line"), 2)

    def test_pair_keeps_one_structure(self):
        """The two ends of a chamfered slab: the same sketch, other sizes."""
        a = rounded_rect(60, 40, 5)
        b = rounded_rect(59, 39, 4.5)
        pa, pb = sk.fit_pair(a, b, 0.01)
        self.assertEqual(len(pa.nodes), len(pb.nodes))
        self.assertEqual([e.kind for e in pa.edges], [e.kind for e in pb.edges])

    def test_path_rejects_radius_that_does_not_fit(self):
        with self.assertRaises(ValueError):
            sk.path([(0, 0, 0), (10, 0, 6), (10, 10, 6), (0, 10, 0)], [None] * 4)


class Regularisation(unittest.TestCase):
    def test_pool_snaps_mirrors_and_standard_sizes(self):
        from form.recon.program import Pool
        p = Pool(0.05)
        hx = [p.add("X", v, "base") for v in (31.749, -31.751, 31.7502)]
        hd = [p.add("d", 5.4991, "hole1"), p.add("d", 5.501, "hole2")]
        hz = p.add("Z", 2.4996, "base")
        p.solve()
        self.assertEqual({p.code(h) for h in hx}, {"v['x1']", "-v['x1']"})     # one Param, mirrored
        px = next(q for q in p.params if q["key"] == "x1")
        self.assertEqual(px["value"], 31.75)
        self.assertIn("mirrored", px["note"])
        self.assertIn("snapped", px["note"])
        self.assertEqual(p.code(hd[0]), p.code(hd[1]))                          # equal diameters: one Param
        pd = next(q for q in p.params if q["kind"] == "d")
        self.assertEqual(pd["value"], 5.5)
        self.assertIn("M5 clearance", pd["note"])                               # a standard size, said so
        self.assertEqual(p.value(hz), 2.5)
        self.assertTrue(all(q["lo"] < q["value"] < q["hi"] for q in p.params))


class Fits(unittest.TestCase):
    def test_analytic_jacobians(self):
        from form.recon import fit
        rng = np.random.default_rng(1)
        P = rng.normal(size=(40, 3)) * 5
        cases = {
            "cylinder": (np.r_[0.3, -0.2, 0.1, 0.7, 0.4, 3.0],
                         lambda x: fit.Prim("cylinder", {"o": x[:3], "a": fit._dir(x[3], x[4]), "r": abs(x[5])})),
            "cone": (np.r_[0.3, -0.2, 0.1, 0.7, 0.4, 3.0, 0.3],
                     lambda x: fit.Prim("cone", {"o": x[:3], "a": fit._dir(x[3], x[4]), "r": x[5], "half_angle": x[6]})),
            "torus": (np.r_[0.3, -0.2, 0.1, 0.7, 0.4, 6.0, 2.0],
                      lambda x: fit.Prim("torus", {"o": x[:3], "a": fit._dir(x[3], x[4]), "R": abs(x[5]), "r": abs(x[6])})),
            "sphere": (np.r_[0.3, -0.2, 0.1, 3.0], lambda x: fit.Prim("sphere", {"o": x[:3], "r": abs(x[3])})),
        }
        for kind, (x, un) in cases.items():
            J = fit._jacobian(kind, x, P)
            for i in range(len(x)):
                h = np.zeros_like(x)
                h[i] = 1e-6
                num = (un(x + h).dist(P) - un(x - h).dist(P)) / 2e-6
                self.assertLess(float(np.abs(J[:, i] - num).max()), 1e-5, f"{kind} parameter {i}")


def _load(name):
    from form.recon.pipeline import load
    stl = TMP / f"{name}.stl"
    if not stl.exists():
        fx.export(name, TMP)
    return load(stl)[:2]


_programs = {}


def program_of(name, tol=0.02):
    from form.recon import program
    if name not in _programs:
        V, F = _load(name)
        out = TMP / f"prog-{name}"
        out.mkdir(exist_ok=True)
        _programs[name] = program.recipe(V, F, tol, name=name, out_dir=out)
    return _programs[name]


class ProgramRoute(unittest.TestCase):
    """Sketches and extrusions read off the mesh, checked against it."""

    def test_box_with_holes_is_all_params(self):
        r = program_of("box_with_holes")
        rep = r["report"]
        self.assertTrue(r["verified"], rep.get("error"))
        self.assertEqual(rep["editable_pct"], 100.0)
        self.assertLessEqual(rep["hausdorff_mm"], 0.02)
        src = r["source"]
        self.assertIn("provenance='mesh'", src)
        diam = sorted(p["value"] for p in r["params"] if p["kind"] == "d")
        self.assertEqual(diam, [5.5, 8.0])                                     # snapped, one Param for the four M5 holes
        self.assertEqual(rep["regularised"]["mirrored"], 4)                    # the box and the hole grid are symmetric

    def test_wallet_plate_partial_and_editable(self):
        """A 2.5D part with a chamfered band, rails, a pin, a pocket and a hole: most of it Params, verified."""
        r = program_of("wallet_plate")
        rep = r["report"]
        self.assertTrue(r["verified"], rep.get("error"))
        self.assertLessEqual(rep["hausdorff_mm"], 0.02)
        self.assertGreaterEqual(rep["editable_pct"], 90.0)
        kinds = {f["kind"] for f in rep["features"]}
        self.assertIn("ruled loft", kinds)                                      # the chamfered band, as a sketch pair
        self.assertIn(3.4, [p["value"] for p in r["params"] if p["kind"] == "d"])
        # the editability sweep: Params change the part and it rebuilds over their range
        from form.recon import program
        rows = program.sweep(r["source"], r["refs"], samples=3)
        good = [x for x in rows if x["changes"] and x["rebuilds_pct"] >= 80]
        self.assertGreaterEqual(len(good), 0.8 * len(rows), [x for x in rows if x not in good])

    def test_residual_is_kept_and_not_counted(self):
        """A domed boss on a plate: the dome reads as no sketch, so it is kept as the mesh's slices; the plate and the
        boss's straight part stay Params, and editable says how much."""
        from build123d import Align, Box, Cylinder, Pos, Sphere, export_stl
        from form.recon import program
        from form.recon.pipeline import load
        A = (Align.CENTER, Align.CENTER, Align.MIN)
        part = Box(40, 30, 4, align=A) + Pos(0, 0, 4) * Cylinder(6, 5, align=A) + Pos(0, 0, 9) * Sphere(6)
        part = part - Pos(0, 0, -10) * Box(80, 80, 10, align=A)
        stl = TMP / "dome.stl"
        export_stl(part, str(stl), tolerance=0.005, angular_tolerance=0.1)
        V, F = load(stl)[:2]
        out = TMP / "prog-dome"
        out.mkdir(exist_ok=True)
        r = program.recipe(V, F, 0.02, name="dome", out_dir=out)
        rep = r["report"]
        self.assertTrue(r["verified"], rep.get("error"))
        self.assertTrue(r["refs"])                                              # a kept slice of the mesh
        self.assertIn("self.reference(", r["source"])
        self.assertLess(rep["editable_pct"], 100.0)
        self.assertGreater(rep["editable_pct"], 50.0)


class Pipeline(unittest.TestCase):
    def test_editable_first_progress_and_tolerance_flag(self):
        from form.recon import pipeline, project
        stl = TMP / "box_with_holes.stl"
        if not stl.exists():
            fx.export("box_with_holes", TMP)
        stamps = []
        t0 = time.perf_counter()
        rep = pipeline.reconstruct(stl, TMP / "pipe-box", "box", 0.02, 2, progress=lambda d: stamps.append(time.perf_counter()))
        stamps.append(time.perf_counter())
        res = rep["result"]
        self.assertEqual(res["method"], "sketches and extrusions")
        self.assertEqual(res["editable_pct"], 100.0)
        self.assertTrue(res["within_tolerance"])
        self.assertTrue(res["headline"].startswith("100% editable"))
        gaps = np.diff([t0] + stamps)
        self.assertLess(float(gaps.max()), 3.0)                                 # never three seconds of silence
        s = project.summary(rep)
        self.assertEqual(list(s)[:3], ["headline", "editable_pct", "hausdorff_mm"])
        # a result outside the tolerance asked for is flagged
        flag = {"result": {"driven_by_params_pct": 50.0, "hausdorff_mm": 0.12}}
        pipeline._headline(flag, 0.1)
        self.assertFalse(flag["result"]["within_tolerance"])
        self.assertIn("outside the 0.1 mm", flag["result"]["headline"])
        self.assertIn("warning", flag["result"])


class ExactEdges(unittest.TestCase):
    def test_layer1_edges_are_intersection_curves(self):
        from form.recon import brep, segment
        V, F = _load("box_with_holes")
        regions, _ = segment.segment(V, F, 0.02)
        shape, info = brep.build(V, F, regions, 0.02)
        self.assertTrue(info["valid"])
        self.assertTrue(info["exact_edges"])
        self.assertGreater(info["edges_exact"], 0)
        self.assertEqual(info["edges_segment"], 0)                              # no polyline boundaries left
        self.assertLessEqual(info["faces"], 12)                                  # 6 sides and 5 hole walls (+ seams)


class Assemblies(unittest.TestCase):
    def test_slot_and_slider_are_bound(self):
        """A plate with a slot and a block that slides in it, 0.2 mm each side: the slot's walls and the block's are
        tied by one Param plus a clearance, and the combined design builds both parts."""
        from build123d import Align, Box, Pos, export_stl
        from form.recon import assembly, program
        from form.recon.pipeline import load
        A = (Align.CENTER, Align.CENTER, Align.MIN)
        base = Box(40, 60, 6, align=A) - Pos(0, 0, 3) * Box(10.4, 70, 4, align=A)
        block = Pos(0, 0, 3) * Box(10.0, 20, 6, align=A)
        parts = []
        for name, solid in (("Base", base), ("Slider", block)):
            stl = TMP / f"asm_{name}.stl"
            export_stl(solid, str(stl), tolerance=0.005)
            V, F = load(stl)[:2]
            out = TMP / f"asm-{name}"
            out.mkdir(exist_ok=True)
            r = program.recipe(V, F, 0.02, name=name, out_dir=out)
            self.assertTrue(r["verified"], r["report"].get("error"))
            parts.append({"name": name, "V": V, "F": F, "origin": r["plan"]["frame"].o, "params": r["params"],
                          "source": r["source"]})
        got = assembly.bind(parts, near=1.0, tol=0.02)
        gaps = [b for b in got["bindings"] if b["kind"] == "gap" and b["axis"] == "X"]
        self.assertTrue(gaps, got)
        self.assertAlmostEqual(gaps[0]["clearance_mm"], 0.2, places=3)
        src = assembly.combined_source(parts, got["bindings"], "Slot and slider")
        self.assertIn("fit1", src)
        from form.recon.program import build_stages
        stages, rec = build_stages(src)
        self.assertEqual(rec.solids, 2)
        self.assertEqual(len(stages[-1].shape.solids()), 2)


if __name__ == "__main__":
    unittest.main()
