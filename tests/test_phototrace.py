"""Photo plus scale to a profile (wave AF) on synthetic photos whose every dimension is known.

The pictures are drawn here at a known scale (supersampled, blurred, some with noise, rotation or perspective): a
bracket 60 x 40 mm with a 12 mm corner radius and a 10 mm hole, beside a bank card (85.60 x 53.98 mm, 3.18 mm
corners), a one-euro coin (23.25 mm) or two marks 100 mm apart. Every dimension the trace reports must lie within the
uncertainty it states (k = 2), the scale within its stated relative uncertainty, the sketch must solve, close and be
fully constrained, and everything must be marked as estimated from the photo. Nothing here reads the owner's data."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="form-phototrace-"))
os.environ["FORM_DATA"] = str(TMP / "data")

from form import handsketch, phototrace as PT  # noqa: E402

BG, CARD, PART, COIN = (236, 233, 226), (40, 70, 150), (30, 30, 34), (190, 160, 60)
TRUTH = {"length": [60.0, 28.0, 28.0, 18.0, 20.0, 22.0], "radius": [12.0], "diameter": [10.0],
         "overall width": [60.0], "overall height": [40.0]}


def _rrect(w, h, r, n=24):
    pts = []
    for cx, cy, a0 in ((w - r, r, -90), (w - r, h - r, 0), (r, h - r, 90), (r, r, 180)):
        pts += [(cx + r * math.cos(math.radians(a0 + 90 * k / n)), cy + r * math.sin(math.radians(a0 + 90 * k / n)))
                for k in range(n + 1)]
    return pts


def scene(s=6.0, W=1500, H=1000, angle=0.0, noise=0.0, ref="card", perspective=0.0, ss=4):
    """The picture (PIL image) at s pixels per millimetre."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGB", (W * ss, H * ss), BG)
    d = ImageDraw.Draw(im)
    k = s * ss

    def T(pts, ox, oy, rot=0.0):
        c, sn = math.cos(rot), math.sin(rot)
        return [((ox + x * c - y * sn) * k, (oy + x * sn + y * c) * k) for x, y in pts]
    if ref == "coin":
        cx, cy, r = 30.0, 30.0, 23.25 / 2
        d.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=COIN)
    elif ref == "card":
        d.polygon(T(_rrect(85.60, 53.98, 3.18), 12, 10), fill=CARD)
    part = [(0, 0), (60, 0), (60, 28)] + [(48 + 12 * math.cos(math.radians(90 * q / 24)), 28 + 12 * math.sin(math.radians(90 * q / 24)))
                                         for q in range(25)] + [(20, 40), (20, 22), (0, 22)]
    rot = math.radians(angle)
    d.polygon(T(part, 130, 60, rot), fill=PART)
    d.polygon(T([(42 + 5 * math.cos(math.radians(a)), 14 + 5 * math.sin(math.radians(a))) for a in range(0, 360, 3)], 130, 60, rot), fill=BG)
    if perspective:
        w, h = im.size
        e = perspective
        quad = [(0, 0), (w, 0), (w * (1 + e), h), (-w * e, h)]            # the far edge reads narrower
        # PIL's coefficients map output to input: solve them from four point pairs
        A, b = [], []
        for (x, y), (X, Y) in zip([(0, 0), (w, 0), (w, h), (0, h)], quad):
            A.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
            A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
            b += [X, Y]
        co = np.linalg.solve(np.array(A, float), np.array(b, float))
        im = im.transform((w, h), Image.PERSPECTIVE, tuple(co), Image.BICUBIC, fillcolor=BG)
    im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8))
    if noise:
        a = np.asarray(im).astype(float) + np.random.default_rng(1).normal(0, noise, (H, W, 3))
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return im


def save(name, **kw) -> str:
    f = TMP / f"{name}.png"
    scene(**kw).save(f)
    return str(f)


class Traces(unittest.TestCase):
    def within(self, r, slack=1.0):
        """Every reported dimension against the truth, within its own stated uncertainty."""
        left = {k: list(v) for k, v in TRUTH.items()}
        self.assertEqual(sorted(d["kind"] for d in r["dimensions"]),
                         sorted(k for k, v in TRUTH.items() for _ in v), "the primitives found")
        worst = 0.0
        for d in r["dimensions"]:
            want = min(left[d["kind"]], key=lambda t: abs(t - d["value_mm"]))
            left[d["kind"]].remove(want)
            err = abs(d["value_mm"] - want)
            self.assertLessEqual(err, slack * d["uncertainty_mm"],
                                 f"{d['id']} {d['kind']}: {d['value_mm']} against {want}, stated ±{d['uncertainty_mm']}")
            self.assertEqual(d["evidence"], "estimated from the photo")
            self.assertEqual(d["how_known"], "assumed")
            worst = max(worst, err / d["uncertainty_mm"])
        return worst

    def sketch_ok(self, r):
        sol = handsketch.solve(r["sketch"])
        self.assertTrue(sol["ok"], sol.get("error"))
        self.assertTrue(sol["closed"])
        self.assertEqual(sol["loops"], 2)
        self.assertEqual(sol["dof"], 0, "the dimensions and constraints fix the sketch")
        kinds = [c["k"] for c in r["sketch"]["constraints"]]
        self.assertEqual(kinds.count("tangent"), 2, "the corner arc touches both of its lines")
        self.assertGreaterEqual(kinds.count("horizontal") + kinds.count("vertical"), 6)
        return sol

    def test_card_square_on(self):
        r = PT.trace(save("card"))
        self.assertAlmostEqual(r["scale"]["px_per_mm"], 6.0, delta=6.0 * r["scale"]["relative_uncertainty"])
        self.assertTrue(r["scale"]["perspective_corrected"])
        self.assertLess(abs(r["scale"]["anisotropy"]), 2e-3)
        self.within(r)
        self.sketch_ok(r)
        self.assertEqual(r["profile"]["holes"], 1)
        self.assertEqual((r["profile"]["line"], r["profile"]["arc"], r["profile"]["circle"]), (6, 1, 1))
        self.assertIn("parallax", " ".join(r["uncertainty"]["not_included"]))

    def test_card_rotated_part_with_noise(self):
        r = PT.trace(save("card_rot", angle=17.0, noise=3.0))
        self.within(r)
        self.sketch_ok(r)
        self.assertAlmostEqual(abs(r["rotation_deg"]), 17.0, delta=0.3)

    def test_card_low_resolution_states_a_larger_uncertainty(self):
        hi = PT.trace(save("card"))
        lo = PT.trace(save("lowres", s=3.0, W=800, H=520))
        self.within(lo)
        u_hi = next(d for d in hi["dimensions"] if d["kind"] == "overall width")["uncertainty_mm"]
        u_lo = next(d for d in lo["dimensions"] if d["kind"] == "overall width")["uncertainty_mm"]
        self.assertGreater(u_lo, 1.5 * u_hi)
        self.assertAlmostEqual(lo["mm_per_px"], 1 / 3.0, delta=0.003)

    def test_card_removes_perspective(self):
        f = save("persp", perspective=0.06)
        r = PT.trace(f)
        self.assertGreater(abs(r["scale"]["opposite_sides_ratio"][0] - 1.0), 0.01, "the card reads as a trapezium")
        self.within(r)
        # the same photo with only a scale (two points on the card's lower edge) does not: lengths are off by more
        # than a scale-only reference would state, which is why tilt is listed as not included
        self.assertNotIn("camera tilt (only a card reference corrects it)", r["uncertainty"]["not_included"])

    def test_coin(self):
        r = PT.trace(save("coin", ref="coin", s=7.0), {"kind": "coin", "coin": "eur_1"})
        self.assertEqual(r["scale"]["diameter_mm"], 23.25)
        self.assertTrue(r["scale"]["tolerance_assumed"])
        self.assertFalse(r["scale"]["perspective_corrected"])
        self.assertLess(r["scale"]["axis_ratio"], 1.01)
        self.within(r)
        self.assertIn("camera tilt (only a card reference corrects it)", r["uncertainty"]["not_included"])

    def test_two_points_a_known_distance_apart(self):
        # the part's own 60 mm edge would be cheating: the marks are two points 100 mm apart at 6 px per mm
        r = PT.trace(save("marks", ref="none"), {"kind": "scale", "points": [[100, 900], [700, 900]], "length_mm": 100.0})
        self.assertAlmostEqual(r["scale"]["px_per_mm"], 6.0, places=6)
        self.within(r)

    def test_uncertainty_formula(self):
        r = PT.trace(save("card"))
        s_rel, px = r["scale"]["relative_uncertainty"], r["mm_per_px"]
        d = next(x for x in r["dimensions"] if x["kind"] == "overall width")
        want = 2.0 * math.hypot(math.sqrt(2) * PT.U_EDGE_PX * px, d["value_mm"] * s_rel)
        self.assertAlmostEqual(d["uncertainty_mm"], want, places=3)
        # the scale's own figure: the card's tolerance and the edge term on its short side
        want_rel = math.hypot(PT.CARD_TOL_MM[1] / PT.CARD_MM[1], math.sqrt(2) * PT.U_EDGE_PX / (PT.CARD_MM[1] / px))
        self.assertAlmostEqual(s_rel, want_rel, delta=2e-5)

    def test_refusals(self):
        with self.assertRaises(PT.PhotoError):
            PT.trace(save("marks", ref="none"))                                 # no card in it
        with self.assertRaises(PT.PhotoError):
            PT.trace(save("card"), tolerance_mm=0.05)                           # under a pixel
        with self.assertRaises(PT.PhotoError):
            PT.trace(save("card"), {"kind": "coin"})                            # which coin?
        from PIL import Image
        blank = TMP / "blank.png"
        Image.new("RGB", (400, 300), BG).save(blank)
        with self.assertRaises(PT.PhotoError):
            PT.trace(str(blank))


class Fitting(unittest.TestCase):
    def test_circle_and_line_fits(self):
        t = np.linspace(0.3, 2.1, 80)
        P = np.column_stack([3 + 7 * np.cos(t), -2 + 7 * np.sin(t)])
        c, r, res = PT.fit_circle(P)
        np.testing.assert_allclose(c, [3, -2], atol=1e-9)
        self.assertAlmostEqual(r, 7.0, places=9)
        self.assertLess(res, 1e-9)
        Q = np.column_stack([np.linspace(0, 10, 30), 2 + 0.5 * np.linspace(0, 10, 30)])
        _c0, d0, res = PT.fit_line(Q)
        self.assertAlmostEqual(abs(d0[1] / d0[0]), 0.5, places=9)
        self.assertLess(res, 1e-9)

    def test_homography_maps_its_four_points(self):
        src = np.array([[10, 20], [400, 35], [380, 300], [25, 280]], float)
        dst = np.array([[0, 0], [85.6, 0], [85.6, 53.98], [0, 53.98]], float)
        Hm = PT.homography(src, dst)
        np.testing.assert_allclose(PT.apply_h(Hm, src), dst, atol=1e-8)

    def test_contours_are_subpixel(self):
        # a disc of radius 40.3 px drawn with a soft edge: the traced radius is within a twentieth of a pixel
        y, x = np.mgrid[0:200, 0:200]
        d = np.clip(40.3 - np.hypot(x - 100.2, y - 99.7) + 0.5, 0, 1)
        loops = PT.contours(d, 0.5)
        self.assertEqual(len(loops), 1)
        c, r, res = PT.fit_circle(loops[0])
        self.assertAlmostEqual(r, 40.3, delta=0.05)
        np.testing.assert_allclose(c, [100.2, 99.7], atol=0.05)


class AsADesign(unittest.TestCase):
    def test_build_is_assumed_never_measured(self):
        from form import config
        from form.studio import Studio
        st = Studio(config.load())
        try:
            r = PT.call(st, save("card"), build=True, depth=6.0, name="Bracket from a photo")
            p = st.load(r["project"])
            self.assertEqual(r["depth_mm"]["how_known"], "assumed")
            view = st.view(p)
            bb = view["bbox"]
            size = [bb[1][k] - bb[0][k] for k in range(3)]
            w = next(d for d in r["dimensions"] if d["kind"] == "overall width")
            self.assertAlmostEqual(size[0], 60.0, delta=w["uncertainty_mm"])
            self.assertAlmostEqual(size[2], 6.0, places=6)
            prov = st.rev(p).get("provenance") or {}
            self.assertFalse([k for k, v in prov.items() if (v or {}).get("source") == "measured"],
                             "nothing from a photo is marked measured")
        finally:
            st.kernel.stop()


if __name__ == "__main__":
    unittest.main()
