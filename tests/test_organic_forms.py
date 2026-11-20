"""Organic form vocabulary (form.craft.organic), product classes and silhouettes (form.product_classes), photo
material zones (form.appearance) and the critique checks that use them."""
import math
import unittest

import numpy as np

from form import product_classes as pc
from form.adapters import blender as bl


def _box_mesh(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
    T = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return P, T


class ProportionTables(unittest.TestCase):
    def test_head_form_follows_en960_sizes(self):
        from form.craft import organic as org
        j = org.head_form("J")
        self.assertEqual(j["circumference"], 570)
        self.assertTrue(190 < j["length"] < 205 and 148 < j["breadth"] < 160, j)
        m = org.head_form("M")
        self.assertGreater(m["length"], j["length"])
        round_ = org.head_form("J", cephalic=0.85)
        self.assertGreater(round_["breadth"], j["breadth"])
        self.assertLess(round_["length"], j["length"])          # same circumference, rounder head
        with self.assertRaises(Exception):
            org.head_form(400)

    def test_helmet_fullface_is_sized_from_the_head(self):
        from form.craft import organic as org
        F = org.helmet_fullface("J")
        hd = F["head"]
        self.assertAlmostEqual(F["L"], hd["length"] + 2 * F["offset"], delta=0.2)
        self.assertTrue(280 < F["L"] < 310 and 240 < F["W"] < 265 and 270 < F["H"] < 310, (F["L"], F["W"], F["H"]))
        pb, pt = F["port_z"]
        self.assertLess(pb, F["z_eye"])
        self.assertGreater(pt, F["z_eye"])
        zs = [s["z"] for s in F["sections"]]
        self.assertEqual(zs, sorted(zs))
        self.assertTrue(all(s["seam"] == 180.0 for s in F["sections"]))

    def test_mouse_form_follows_the_hand(self):
        from form.craft import organic as org
        f = org.mouse_form()
        self.assertAlmostEqual(f["L"], 0.65 * 194, delta=0.2)
        self.assertGreater(f["tip"][2], f["z_eq"])
        self.assertLess(f["crown_x"], 0)                             # the hump sits behind the centre
        left = org.mouse_form(hand="left")
        self.assertEqual(left["thumb_y"], -1.0)

    def test_profile_sections_follow_the_guides(self):
        from form.craft import organic as org
        secs, tip = org.profile_sections([(0, 50), (40, 55)], [(0, -50), (40, -60)], [(0, 30), (40, 35)],
                                         crown=(-10, 80), levels=5, dome_levels=6)
        lo = secs[0]
        self.assertAlmostEqual(lo["cx"] + lo["a"], 50, places=6)
        self.assertAlmostEqual(lo["cx"] - lo["a"], -50, places=6)
        self.assertEqual(tip[2], 80)
        self.assertTrue(all(s.get("dome") for s in secs[5:]))
        self.assertFalse(org.check_sections(secs))
        bad = [dict(secs[0]), {**secs[1], "seam": 0.0}]
        self.assertTrue(any("twist" in w for w in org.check_sections(bad)))

    def test_bottle_and_grip(self):
        from form.craft import organic as org
        b = org.bottle_profile(500)
        self.assertTrue(55 < b["diameter"] < 75, b["diameter"])
        self.assertAlmostEqual(b["profile"][-1][0], 27.4 / 2)
        secs, _ = org.grip_sections()
        ds = [2 * s["a"] for s in secs]
        self.assertTrue(31 <= max(ds) <= 38, ds)


class LoftChecks(unittest.TestCase):
    def test_smooth_dome_has_no_folds_and_a_wiggle_does(self):
        from form.craft import organic as org
        secs, tip = org.dome_sections(80, 60, 40, levels=6)
        r = org.loft_report(org.section_body(secs, tip=tip))
        self.assertEqual(r["folds"], 0, r)
        self.assertEqual(r["faces_checked"], 1)
        wig = [dict(z=0, a=30, b=20), dict(z=2, a=30, b=20, cx=25), dict(z=4, a=30, b=20), dict(z=6, a=30, b=20, cx=25),
               dict(z=20, a=30, b=20)]
        try:
            body = org.section_body(wig)
        except Exception:
            self.skipTest("OCCT refused the folded loft outright")
        r2 = org.loft_report(body, grid=40)
        self.assertGreater(r2["worst_deg"], r["worst_deg"])

    def test_surface_band_cut_and_fuse(self):
        from build123d import Box, Pos
        from form import craft
        secs, tip = craft.dome_sections(80, 60, 40, levels=6)
        outer = craft.section_body(secs, tip=tip)
        inner = craft.inset_body(secs, 2.0, tip=tip)
        shell = craft.cut(outer, inner)
        pad = craft.surface_band(secs, tip, 2.0, Pos(0, 0, 30) * Box(20, 20, 30), depth=1.0)
        out = craft.fuse(shell, pad)
        self.assertEqual(len(out.solids()), 1)
        self.assertGreater(out.volume, shell.volume)
        with self.assertRaises(Exception):                      # a part that must stay separate but touches
            craft.fuse(shell, pad, max_solids=2, min_solids=2)
        g = craft.grow_outline([(0, 0), (10, 0), (10, 10), (0, 10)], 1)
        self.assertLess(min(x for x, _ in g), 0)


class ProductClasses(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(pc.detect("A full-face motorcycle helmet with vents"), "helmet_fullface")
        self.assertEqual(pc.detect("An ergonomic computer mouse shell"), "mouse")
        self.assertEqual(pc.detect("a road bike helmet"), "helmet_open")
        self.assertIsNone(pc.detect("A GoPro mount on a helmet base"))

    def test_outline_compares_with_itself(self):
        out = pc.CLASSES["helmet_fullface"]["outlines"]["side"]
        m = pc._poly_mask(out, (120, 130))
        r = pc.compare(m, out)
        self.assertGreater(r["iou"], 0.97)
        self.assertLess(r["profile_dev"], 0.01)
        self.assertGreater(pc.mirror_match(pc._poly_mask(pc.CLASSES["helmet_fullface"]["outlines"]["front"],
                                                         (100, 100))), 0.95)

    def test_a_box_does_not_read_as_a_helmet(self):
        P, T = _box_mesh((-150, -125, 0), (150, 125, 280))
        V = pc.views(P, T)
        a = pc.assess("helmet_fullface", V, {"shell": 1.0})
        self.assertLess(a["score"], 0.6, a["parts"])
        self.assertFalse(next(s for s in a["signature"] if s["id"] == "eye_port")["ok"])
        self.assertFalse(next(s for s in a["signature"] if s["id"] == "visor")["ok"])
        self.assertTrue(all(r["ok"] for r in a["ratios"]) or a["ratios"])

    def test_views_depth_sees_into_an_opening(self):
        P, T = _box_mesh((0, 0, 0), (100, 50, 40))
        V = pc.views(P, T)
        d = V["top"]["depth"]
        self.assertTrue(np.nanmax(d) <= 40.01 and np.nanmedian(d) >= 39.9)
        self.assertLess(np.mean(d < 39), 0.02)


class PhotoZones(unittest.TestCase):
    def test_validate(self):
        from form import appearance
        ok = appearance.validate([{"features": ["visor"], "finish": "smoke", "color": "#112233"}], {"visor", "shell"},
                                 bl.FINISHES)
        self.assertEqual(ok[0]["finish"], "smoke")
        for bad in ([{"features": ["nope"], "finish": "smoke"}], [{"features": ["visor"], "finish": "chrome"}],
                    [{"features": ["visor"], "color": "red"}], [{"finish": "matte"}]):
            with self.assertRaises(ValueError):
                appearance.validate(bad, {"visor"}, bl.FINISHES)

    def test_photo_views(self):
        self.assertEqual(bl.photo_view(), bl.APP_ISO)
        az, el = bl.photo_view("right")                      # a product facing +X shows its face
        cam = bl.view_dir(az, el)
        self.assertGreater(cam[0], 0.95)
        az, el = bl.photo_view(azimuth=-90, elevation=10)     # from -Y, like render(view="front")
        self.assertLess(bl.view_dir(az, el)[1], -0.9)
        with self.assertRaises(ValueError):
            bl.photo_view("sideways")
        for f in ("carbon", "smoke", "rubber", "gloss", "metal"):
            self.assertIn(f, bl.FINISHES)

    def test_build_job_with_zones(self):
        import tempfile
        from pathlib import Path
        from form.craft import meshtex
        d = Path(tempfile.mkdtemp())
        P, T = _box_mesh((0, 0, 0), (10, 10, 10))
        meshtex.write_stl(d / "a.stl", P, T)
        P2, T2 = _box_mesh((20, 0, 0), (30, 10, 5))
        meshtex.write_stl(d / "b.stl", P2, T2)
        job = bl.build_job(d / "a.stl", d / "o.png", finish="matte",
                           zones=[{"stl": d / "a.stl", "finish": "carbon", "color": "#222222"},
                                  {"stl": d / "b.stl", "finish": None, "color": None}])
        self.assertEqual(len(job["parts"]), 2)
        self.assertEqual(job["parts"][0]["finish"]["id"], "carbon")
        self.assertEqual(job["parts"][1]["finish"]["id"], "matte")
        self.assertAlmostEqual(job["span_m"][0], 0.030)


class CritiqueChecklist(unittest.TestCase):
    def test_reads_as_must_be_answered(self):
        from form import critique
        m = {"form": {"class": {"label": "computer mouse", "score": 0.9, "parts": {"outline": 1, "ratios": 1,
                                                                                  "signature": 0.75},
                                "views": {"side": {"profile_dev": 0.02}}, "ratios": [], "ratios_source": "x",
                                "signature": [{"id": "wheel", "ok": False}]}},
             "folds": {"faces_checked": 1, "folds": 3, "worst_deg": 150, "where": [(0, 0, 0)]},
             "walls": {"samples": 100, "min_mm": 0.0, "p2_mm": 0.1, "p5_mm": 1, "median_mm": 2, "thin_fraction": 0.05,
                       "thin_at": []}}
        items = critique.checklist(m, None, "model")
        q = {i["question"].split(":")[0][:12]: i for i in items}
        reads = next(i for i in items if i["question"].startswith("Reads as"))
        self.assertTrue(reads["attention"])
        self.assertTrue(next(i for i in items if "lofted skin" in i["question"])["attention"])
        self.assertTrue(next(i for i in items if "walls whole" in i["question"])["attention"])
        self.assertIn("wheel", next(i for i in items if i["question"].startswith("Silhouette"))["why"])
        items2 = critique.checklist(m, None, "model", reads_as="yes: wheel, split buttons, hump")
        self.assertFalse(next(i for i in items2 if i["question"].startswith("Reads as"))["attention"])
        self.assertTrue(q)


class CharacterMask(unittest.TestCase):
    """The hybrid exemplar (WP-F): a sculpted cage skin, eye openings from a constrained sketch, magnet bosses,
    a split held by magnets and two eye lenses; every solid valid, and the handles and the sketch drive it."""

    def test_builds_four_valid_parts_and_parameters_drive_it(self):
        from form import exemplars
        d = exemplars.load("character_mask")
        v = d.validate(d.defaults())
        st = d.build(v)
        self.assertEqual([s.feature for s in st], ["shell", "eyes", "magnets", "split", "lenses"])
        final = st[-1].shape
        self.assertEqual(len(final.solids()), 4)
        self.assertTrue(all(s.is_valid for s in final.solids()))
        self.assertEqual(len(st[0].shape.faces()), 3)               # the sculpted shell: skin, inside, rim
        self.assertGreater(len(st[1].shape.faces()), 3)             # the eye openings cut it
        brow = d.build(d.validate({**v, "brow": 10}))[0].shape
        self.assertGreater(brow.bounding_box().max.X, st[0].shape.bounding_box().max.X - 1e-6)
        der = {x["key"]: x["value"] for x in d.derived(v)}
        self.assertAlmostEqual(der["pocket_d"], v["magnet_d"] + 2 * v["magnet_clear"])
        self.assertEqual(d.mesh_texture(v)[0].kind, "hex")
        self.assertEqual(d.mesh_texture({**v, "pattern": 1})[0].kind, "heightmap")      # the web relief


if __name__ == "__main__":
    unittest.main()
