"""form.craft: every helper builds a valid solid (or says why it cannot), ISO 286 numbers, and mesh textures."""
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from build123d import Align, Axis, Box, Cylinder, Sphere, Vertex

from form import craft
from form.craft import fits, meshtex
from form.recipes.base import RecipeError

try:                                                                    # the [parts] extra (requirements.lock has it)
    import py_gearworks  # noqa: F401
    HAVE_GEARS = True
except ImportError:
    HAVE_GEARS = False


def valid(test, shape, n=1):
    test.assertIsNotNone(shape)
    test.assertTrue(shape.is_valid, "not a valid solid")
    test.assertGreater(shape.volume, 0)
    test.assertEqual(len(shape.solids()), n)


class Surfaces(unittest.TestCase):
    def test_superellipse_points(self):
        p = craft.superellipse(40, 20, 2.0, count=8)
        self.assertEqual(len(p), 8)
        self.assertAlmostEqual(p[0][0], 40)
        self.assertAlmostEqual(p[2][1], 20)

    def test_profiles(self):
        f = craft.spline_profile([(0, 0), (20, 0), (25, 15), (5, 20)])
        self.assertGreater(f.area, 300)
        self.assertGreater(craft.polygon_profile([(0, 0), (10, 0), (10, 10)]).area, 49)
        self.assertGreater(craft.superellipse_face(20, 10, 3.0).area, math.pi * 200)

    def test_loft_and_shell(self):
        secs = [craft.superellipse_face(40, 30, 2.6, z=0), craft.superellipse_face(36, 26, 2.4, z=30),
                craft.superellipse_face(20, 14, 2.2, z=55)]
        body = craft.loft_sections(secs)
        valid(self, body)
        cup = craft.shell(body, 2.0, openings=craft.faces_at(body, "top"))
        valid(self, cup)
        self.assertLess(cup.volume, body.volume / 3)

    def test_sweep_revolve_thicken(self):
        valid(self, craft.sweep_spline(craft.superellipse_face(4, 3, 2.5), [(0, 0, 0), (20, 0, 20), (40, 0, 10)]))
        valid(self, craft.revolve_profile([(20, 0), (25, 20), (15, 50), (18, 70)], spline=True))
        valid(self, craft.revolve_profile([(10, 0), (10, 10), (5, 20)]))
        valid(self, craft.thicken(craft.superellipse_face(10, 10, 2), 2))

    def test_fillets(self):
        bx = Box(30, 20, 10)
        craft.notes()
        valid(self, craft.variable_fillet(bx, bx.edges().filter_by(Axis.Z)[:1], 1, 4))
        out = craft.safe_fillet(bx, bx.edges(), 8)                 # too big: falls back and says so
        valid(self, out)
        self.assertTrue(any("safe_fillet" in n for n in craft.notes()))

    def test_errors_name_the_argument(self):
        with self.assertRaises(RecipeError) as e:
            craft.shell(Box(10, 10, 10), -1)
        self.assertIn("thickness", e.exception.params)
        with self.assertRaises(RecipeError):
            craft.loft_sections([craft.superellipse_face(10, 10)])


class Mechanisms(unittest.TestCase):
    def test_pin_hinge_leaves_are_separate(self):
        h = craft.pin_hinge()
        valid(self, h.shapes["leaf_a"])
        valid(self, h.shapes["leaf_b"])
        self.assertEqual(craft.overlap(h.shapes["leaf_a"], h.shapes["leaf_b"]), 0.0)
        self.assertEqual(h.axis, (1, 0, 0))

    def test_living_hinge_warns_for_pla(self):
        m = craft.living_hinge(material="PLA")
        valid(self, m.shapes["hinge"])
        self.assertEqual(m.checks[0]["status"], "WARN")

    def test_snaps(self):
        s = craft.cantilever_snap(length=12, thickness=1.6, undercut=0.8)
        valid(self, s.shapes["hook"])
        self.assertAlmostEqual(s["strain"], round(1.5 * 1.6 * 0.8 / 144, 5))
        a = craft.annular_snap()
        valid(self, a.shapes["male"])
        valid(self, a.shapes["groove_cutter"])

    def test_bayonet_dovetail_detent_ratchet(self):
        b = craft.bayonet()
        valid(self, b.shapes["male"])
        valid(self, b.shapes["female_cutter"])
        d = craft.dovetail()
        valid(self, d.shapes["male"])
        bb = d.shapes["slot_cutter"].bounding_box()
        self.assertAlmostEqual((bb.min.Y + bb.max.Y) / 2, 0, places=5)       # centred on Y like the rail
        e = craft.detent()
        valid(self, e.shapes["bump"])
        valid(self, e.shapes["dimple_cutter"])
        r = craft.ratchet()
        valid(self, r.shapes["wheel"])
        valid(self, r.shapes["pawl"])

    def test_cam_and_four_bar(self):
        c = craft.cam(follower_r=4)
        valid(self, c.shapes["cam"])
        self.assertLessEqual(c["pressure_angle_max"], 30)
        self.assertAlmostEqual(c.info["lift_at"](150), 6.0, places=6)
        fb = craft.four_bar(60, 15, 55, 40)
        self.assertEqual(fb.info["kind"], "crank-rocker")
        self.assertTrue(fb.info["full_rotation"])
        for s in fb.shapes.values():
            valid(self, s)

    @unittest.skipUnless(HAVE_GEARS, "py_gearworks is not installed (the [parts] extra)")
    def test_gears(self):
        g = craft.gear_train(teeth=(14, 28))
        valid(self, g.shapes["g0"])
        self.assertAlmostEqual(g["centre_distance_01"], 1.5 * 42 / 2)
        p = craft.planetary()
        for k in ("sun", "ring", "planet0", "planet1", "planet2"):
            valid(self, p.shapes[k])
        self.assertEqual(p.checks[0]["status"], "PASS")                    # no planet overlaps the sun or ring
        self.assertAlmostEqual(p["ratio_ring_fixed"], 5.0)
        with self.assertRaises(RecipeError):
            craft.planetary(sun=12, planet=19, planets=3)                 # cannot space 3 planets evenly


class Fits(unittest.TestCase):
    def test_iso_286(self):
        f = fits.iso_fit("H7/g6", 8)
        self.assertEqual(f["hole"], (8.0, 8.015))
        self.assertEqual(f["shaft"], (7.986, 7.995))
        self.assertEqual(f["kind"], "clearance")
        self.assertEqual(fits.iso_fit("H7/p6", 10)["kind"], "interference")
        self.assertEqual(fits.iso_fit("H7/k6", 20)["kind"], "transition")
        self.assertEqual(fits.shaft_limits("js", 6, 25), (25 - 0.0065, 25 + 0.0065))
        with self.assertRaises(RecipeError):
            fits.iso_fit("H7/s6", 120)                                    # s is tabulated up to 50 mm only
        self.assertEqual(fits.bearing_fit("608")["tolerance"], "k5")


class Structure(unittest.TestCase):
    def test_ribs_gussets_bosses_lattice(self):
        valid(self, craft.rib(40, 6, 1.6, draft=1))
        valid(self, craft.rib_grid(80, 50))
        valid(self, craft.gusset(20, 20))
        plate = Box(80, 40, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
        b = craft.boss_array(plate, [(-30, 0), (30, 0)], top_z=3)
        valid(self, b)
        self.assertGreater(b.volume, plate.volume)
        valid(self, craft.lattice(30, 30, 20, cell=10, strut=1.5))
        with self.assertRaises(RecipeError):
            craft.lattice(200, 200, 200, cell=5, strut=1)                  # over the strut cap


class Organic(unittest.TestCase):
    def test_section_bodies(self):
        secs, tip = craft.dome_sections(120, 100, 60, levels=6)
        valid(self, craft.section_body(secs, tip=tip))
        outer, hollow = craft.section_shell(secs, 2.0, tip=tip)
        valid(self, hollow)
        self.assertLess(hollow.volume, outer.volume / 4)
        grown, gtip = craft.inflate(secs, 3, tip)
        self.assertEqual(gtip[2], tip[2] + 3)
        self.assertEqual(grown[0]["a"], secs[0]["a"] + 3)

    def test_grip_and_handle(self):
        valid(self, craft.grip(length=90, finger_grooves=3))
        valid(self, craft.handle())


class BrepTexture(unittest.TestCase):
    def test_knurls(self):
        d = craft.knurl(30, 18, kind="diamond")
        valid(self, d)
        s = craft.knurl(30, 18, kind="straight")
        valid(self, s)
        bb = d.bounding_box()
        self.assertAlmostEqual(bb.size.Z, 18, places=3)
        self.assertLessEqual(bb.size.X, 30.01)

    def test_spiral_ribs_and_cells(self):
        valid(self, craft.spiral_ribbed_body([(30, 0), (40, 40), (28, 90)], ribs=12, rib_depth=2, twist=60, levels=8))
        valid(self, craft.wrapped_ribs(20, 30, 12, twist=40))
        for k in ("hex", "diamond", "dots", "pyramids"):
            valid(self, craft.emboss_cells(40, 30, 6, kind=k, base=1.0))
            self.assertGreater(len(craft.emboss_cells(40, 30, 6, kind=k).solids()), 1)   # cells alone, to fuse on

    def test_cap(self):
        with self.assertRaises(RecipeError) as e:
            craft.emboss_cells(400, 400, 2.0, gap=0.4)
        self.assertIn("mesh texture", e.exception.hint)


class MeshTextures(unittest.TestCase):
    def setUp(self):
        v, t = Sphere(20).tessellate(0.1, 0.3)
        self.P = np.array([(p.X, p.Y, p.Z) for p in v])
        self.T = np.array(t)

    def closed(self, F):
        E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
        _, cnt = np.unique(E, axis=0, return_counts=True)
        return bool((cnt == 2).all())

    def test_every_kind_keeps_the_mesh_closed(self):
        for kind in meshtex.KINDS:
            if kind == "heightmap":
                continue
            V, F, tags, info = meshtex.apply(self.P, self.T, ["a"] * len(self.T), [craft.MeshTexture(kind, 0.5, 4.0)],
                                             budget=300_000)
            self.assertTrue(self.closed(F), kind)
            self.assertGreater(len(F), len(self.T) * 0.99)
            r = np.linalg.norm(V, axis=1)
            self.assertLess(r.max(), 20 + 0.6)                        # displaced at most by the amplitude
            self.assertEqual(info["label"], meshtex.LABEL)

    def test_only_listed_features_move(self):
        half = np.where(self.P[self.T].mean(axis=1)[:, 2] > 0, "top", "bottom")
        V, F, tags, _ = meshtex.apply(self.P, self.T, half, [craft.MeshTexture("noise", 1.0, 3.0, features=["top"])])
        low = V[np.unique(F[tags == "bottom"])]
        self.assertLessEqual(np.linalg.norm(low, axis=1).max(), 20 + 1e-6)      # nothing outside "top" pushed out
        high = V[np.unique(F[tags == "top"])]
        self.assertGreater(np.linalg.norm(high, axis=1).max(), 20.3)

    def test_heightmap_and_stl(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "h.png"
            Image.fromarray((np.indices((32, 32)).sum(0) % 2 * 255).astype(np.uint8)).save(img)
            V, F, _, _ = meshtex.apply(self.P, self.T, ["a"] * len(self.T),
                                       [craft.MeshTexture("heightmap", 0.4, 10, image=str(img), projection="cylindrical")])
            out = Path(d) / "t.stl"
            meshtex.write_stl(out, V, F)
            self.assertEqual(out.stat().st_size, 84 + 50 * len(F))
        with self.assertRaises(RecipeError):
            craft.MeshTexture("heightmap", image="/nope.png").validate()

    def test_declared(self):
        class R:
            def mesh_texture(self, v):
                return [{"kind": "cells", "amplitude": 0.3}]
        self.assertEqual(meshtex.declared(R(), {})[0].kind, "cells")
        self.assertEqual(meshtex.declared(object(), {}), [])


class EvaluationFixes(unittest.TestCase):
    """What a design evaluation (eight briefs through the tools) found missing or broken in form.craft."""

    def test_profiles_extrude_along_the_plane_whichever_way_the_points_run(self):
        from build123d import Plane, extrude
        for pts in ([(0, 0), (10, 0), (10, 5), (0, 5)], [(0, 0), (0, 5), (10, 5), (10, 0)]):
            for f in (craft.spline_profile(pts, plane=Plane.XZ), craft.polygon_profile(pts, plane=Plane.XZ)):
                self.assertLess(extrude(f, 3).bounding_box().min.Y, -2.9)      # Plane.XZ's normal is -Y

    def test_safe_fillet_goes_edge_by_edge_when_the_set_fails(self):
        b = Box(10, 10, 1.2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        r = craft.safe_fillet(b, b.edges().filter_by(Axis.Z), 4.9)
        craft.notes()
        valid(self, r)
        self.assertLess(r.volume, b.volume)

    def test_mech_indexes_shapes_and_dims(self):
        h = craft.pin_hinge()
        self.assertIs(h["leaf_a"], h.shapes["leaf_a"])
        self.assertGreater(h["knuckle_wall"], 0)
        with self.assertRaises(KeyError):
            h["nope"]
        self.assertEqual(len(h.info["knuckles"]), 5)
        self.assertGreater(h.info["relief_a"].volume, 0)

    def test_bayonet_pair_fits_as_placed_and_locked(self):
        from build123d import Rot
        b = craft.bayonet(d=26, height=7, lugs=3, lug_w=7, lug_h=2.2, lug_depth=1.8, twist=35, clearance=0.25)
        for a in (0, 20, 33):
            self.assertLess((Rot(0, 0, a) * b["male"] - b["female_cutter"]).volume, 1e-3, a)

    def test_four_bar_pose_closes_the_loop(self):
        P = craft.four_bar_pose(22, 45, 22, 46, 72)
        bc = math.dist(P["B"], P["C"])
        dc = math.dist(P["D"], P["C"])
        self.assertAlmostEqual(bc, 22, places=6)
        self.assertAlmostEqual(dc, 46, places=6)
        valid(self, craft.link_between(P["B"], P["C"], 8, 4, 3.4, z=5))
        with self.assertRaises(RecipeError):
            craft.four_bar_pose(100, 10, 10, 10, 0)

    def test_cam_without_a_2d_offset(self):
        import build123d
        orig = build123d.offset
        build123d.offset = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("2D offset failed with distance -4.0"))
        try:
            c = craft.cam(follower_r=4)
        finally:
            build123d.offset = orig
        valid(self, c.shapes["cam"])
        self.assertTrue(any("offset along the normals" in n for n in craft.notes()))

    def test_spiral_ribs_fade_and_take_a_large_twist(self):
        b = craft.spiral_ribbed_body([(30, 0), (24, 40)], ribs=18, rib_depth=1.5, twist=150, levels=10, fade=(0.2, 0.2))
        self.assertTrue(b.is_valid)
        self.assertTrue(any("runs" in n for n in craft.notes()))
        with self.assertRaises(RecipeError):
            craft.spiral_ribbed_body([(30, 0), (24, 40)], fade=(0.9, 0))

    def test_inset_body_and_helmet_sections(self):
        secs, tip = craft.dome_sections(120, 66, 37, levels=6, z0=3)
        inner = craft.inset_body(secs, 2, tip=tip)
        self.assertLess(inner.volume, craft.section_body(secs, tip=tip).volume)
        hs, ht = craft.helmet_sections(270, 215, 165, 95)
        self.assertEqual(hs[0]["z"], 0.0)
        self.assertAlmostEqual(ht[2], 95 + 165)

    def test_mesh_texture_region(self):
        v, t = Sphere(20).tessellate(0.1, 0.3)
        P, T = np.array([(p.X, p.Y, p.Z) for p in v]), np.array(t)
        tex = craft.MeshTexture("noise", 1.0, 3.0, region=((-30, -30, 5), (30, 30, 30)), edge_falloff=0.5)
        V, F, _, _ = meshtex.apply(P, T, ["a"] * len(T), [tex])
        low = V[V[:, 2] < -1]
        self.assertLessEqual(np.linalg.norm(low, axis=1).max(), 20 + 1e-6)      # below the box: untouched
        self.assertGreater(np.linalg.norm(V[V[:, 2] > 10], axis=1).max(), 20.3)
        with self.assertRaises(RecipeError):
            craft.MeshTexture("noise", region=((1, 1, 1), (0, 0, 0))).validate()


class EvaluationPlumbing(unittest.TestCase):
    def test_wrong_solid_count_names_the_stages(self):
        from build123d import Location
        from form import kernel
        from form.recipes.base import Stage
        a = Box(10, 10, 10)
        two = a + Box(4, 4, 4).moved(Location((20, 0, 0)))
        with self.assertRaises(RecipeError) as e:
            kernel._stage_report([Stage("body", a), Stage("lug", two)], 1)
        self.assertIn("body 1, lug 2", str(e.exception))
        self.assertEqual(e.exception.feature, "lug")

    def test_assembly_part_by_point(self):
        from build123d import Location
        from form import assembly
        from form.recipes.base import Assembly, Part
        solids = [Box(10, 10, 4), Box(10, 10, 4).moved(Location((0, 0, 20)))]
        spec = Assembly(parts=[Part("top", "Top", (0, 0, 20)), Part("bottom", "Bottom", (0, 0, 0.5))])
        self.assertEqual(spec.validate(2), [])
        r = assembly._resolve_points(spec, solids)
        self.assertEqual([p.solid for p in r.parts], [1, 0])

    def test_cli_saves_tool_pictures(self):
        import base64
        from types import SimpleNamespace
        from form.__main__ import _save_images
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
        out = _save_images("render", [SimpleNamespace(type="text", text="x"),
                                      SimpleNamespace(type="image", data=png, mime_type="image/png")])
        self.assertEqual(len(out), 1)
        self.assertTrue(Path(out[0]).read_bytes().startswith(b"\x89PNG"))


class Reexports(unittest.TestCase):
    def test_patterns_and_features(self):
        self.assertTrue(hasattr(craft.patterns, "hex_vents"))
        self.assertTrue(hasattr(craft.features, "spec"))
        self.assertIn("knurl", dir(craft))
        _ = Cylinder, Vertex


if __name__ == "__main__":
    unittest.main()
