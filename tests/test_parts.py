"""form.parts (standard hardware) and the enclosure, gear pair and knob recipes, against the real kernel."""
import builtins
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from form import parts
from form.recipes import RecipeError, registry

HAVE_BD = importlib.util.find_spec("bd_warehouse") is not None
HAVE_GEARS = importlib.util.find_spec("py_gearworks") is not None
NEW = ("enclosure", "gear_pair", "knob")


def _bbox_z(shape):
    bb = shape.bounding_box()
    return bb.min.Z, bb.max.Z


class Dimensions(unittest.TestCase):
    def test_m3_clearance_is_iso_273(self):
        self.assertEqual(parts.clearance_d("M3", "close")[0], 3.2)
        self.assertEqual(parts.clearance_d("M3", "normal")[0], 3.4)
        p = parts.screw_clearance("M3", 8, head="socket")
        self.assertEqual(p.kind, "cut")
        self.assertEqual(p["hole_d"], 3.4)
        self.assertEqual(p.dims["hole_d"]["provenance"], "specified")
        self.assertIn("ISO 273", p.dims["hole_d"]["source"])
        self.assertAlmostEqual(p["head_d"], 5.68)
        self.assertAlmostEqual(p["counterbore_d"], 5.68 + 0.3)
        self.assertTrue(p.shape.is_valid)
        lo, hi = _bbox_z(p.shape)
        self.assertAlmostEqual(lo, -8, places=3)
        self.assertAlmostEqual(hi, parts.OVERSHOOT, places=3)
        self.assertEqual(parts.screw_clearance("M3", 8, fit="close")["hole_d"], 3.2)

    def test_recess_deeper_than_hole_is_refused(self):
        with self.assertRaises(RecipeError):
            parts.screw_clearance("M3", 2, head="socket")
        self.assertTrue(parts.screw_clearance("M3", 2, head="socket", recess=False).shape.is_valid)

    def test_m3_heat_insert_is_cnc_kitchen(self):
        p = parts.heat_insert_pocket("M3")
        self.assertEqual((p["hole_d"], p["insert_od"], p["insert_length"], p["min_wall"]), (4.0, 4.6, 5.7, 1.6))
        self.assertAlmostEqual(p["boss_min_d"], 7.2)
        self.assertEqual(p.dims["hole_d"]["provenance"], "specified")
        self.assertIn("CNC Kitchen", p.dims["hole_d"]["source"])
        self.assertEqual(p.dims["depth"]["provenance"], "assumed")
        self.assertEqual(parts.heat_insert_pocket("M3-short")["insert_length"], 3.0)
        with self.assertRaises(RecipeError):
            parts.heat_insert_pocket("M7")

    def test_nuts_magnets_bearings(self):
        n = parts.nut_trap("M3")
        self.assertEqual((n["across_flats"], n["nut_thickness"]), (5.5, 2.4))
        self.assertAlmostEqual(n["pocket_af"], 5.8)
        self.assertTrue(parts.nut_trap("M3", "square", slot=6).shape.is_valid)
        m = parts.magnet_pocket(6, 2)
        self.assertAlmostEqual(m["pocket_d"], 6.2)
        b = parts.bearing_seat("608")
        self.assertEqual((b["bore"], b["outer_d"], b["width"]), (8, 22, 7))
        self.assertTrue(12.1 < b["lip_hole_d"] < 20.0)     # outer ring rests on the lip, inner ring clears it
        with self.assertRaises(RecipeError):
            parts.nut_trap("M3", "wing")

    def test_derived_rows_carry_sources(self):
        rows = parts.heat_insert_pocket("M3").derived("bosses", "ins.", ("hole_d",))
        r = {x["key"]: x for x in rows}
        self.assertTrue(r["ins.hole_d"]["interface"])
        self.assertIn("specified", r["ins.hole_d"]["formula"])

    @unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
    def test_tables_match_bd_warehouse(self):
        from bd_warehouse import bearing, fastener
        for s in parts.CLEARANCE:
            bd = fastener.SocketHeadCapScrew(parts._bd_size(s), 10)
            self.assertAlmostEqual(bd.clearance_hole_diameters["Normal"], parts.CLEARANCE[s][1], msg=s)
            self.assertAlmostEqual(bd.head_diameter, parts.HEADS["socket"][1][s][0], places=2, msg=s)
            nut = fastener.HexNut(parts._bd_size(s))
            self.assertEqual((nut.nut_data["s"], nut.nut_data["m"]), parts.NUTS["hex"][1][s], msg=s)
        for k, name in parts._BEARING_BD.items():
            d = bearing.SingleRowDeepGrooveBallBearing(name).bearing_dict
            self.assertEqual(tuple(float(x) for x in parts.BEARINGS[k]),
                             tuple(float(d[x]) for x in ("d", "D", "B", "d1", "Da")), msg=k)
        # sizes outside FORM's table come from the library
        self.assertEqual(parts.clearance_d("M8", "normal")[0], 9.0)

    @unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
    def test_threads_build(self):
        ext = parts.thread(12, 1.75, 10, external=True)
        inn = parts.thread(12, 1.75, 10, external=False)
        self.assertEqual((ext.kind, inn.kind), ("add", "cut"))
        self.assertTrue(ext.shape.is_valid and inn.shape.is_valid)
        self.assertAlmostEqual(ext["modelled_major_d"], 11.7)
        self.assertAlmostEqual(inn["modelled_major_d"], 12.3)
        with self.assertRaises(RecipeError):
            parts.thread(3, 1.0, 5)


class Gears(unittest.TestCase):
    def test_centre_distance_formula(self):
        self.assertAlmostEqual(parts.centre_distance(1.5, 15, 30), 33.75)
        self.assertAlmostEqual(parts.centre_distance(2, 20, 40), 60.0)
        self.assertAlmostEqual(parts.centre_distance(1, 17, 17), 17.0)

    def test_contact_ratio_textbook_value(self):
        # 20° full depth, z = 20 : 20 gives about 1.56 (standard textbook figure)
        self.assertAlmostEqual(parts.contact_ratio(1, 20, 20), 1.557, places=2)

    @unittest.skipUnless(HAVE_GEARS, "py_gearworks not installed")
    def test_gear_pair_meshes_at_the_standard_distance(self):
        gp = parts.gear_pair(1.5, 15, 30, 6, 5, 5, backlash=0.25)
        self.assertAlmostEqual(gp.centre_distance, 33.75)
        self.assertTrue(gp.a.shape.is_valid and gp.b.shape.is_valid)
        c = gp.b.shape.bounding_box().center()
        self.assertAlmostEqual(c.X, 33.75, delta=0.5)
        inter = gp.a.shape & gp.b.shape                      # thinned teeth: in mesh, not touching
        self.assertTrue(inter is None or inter.volume < 1e-6)
        self.assertAlmostEqual(gp.a["pitch_d"], 22.5)
        # modelled teeth (rounded tips, thinning) overlap a little less than the ideal full-depth formula says
        self.assertTrue(1.2 < gp.contact_ratio <= parts.contact_ratio(1.5, 15, 30) + 1e-6, gp.contact_ratio)
        self.assertIn("py_gearworks", gp.dims["contact_ratio"]["source"])

    def test_missing_library_says_how_to_install(self):
        real = builtins.__import__

        def fake(name, *a, **k):
            if name.startswith("py_gearworks") or name.startswith("bd_warehouse"):
                raise ImportError(f"No module named '{name}'")
            return real(name, *a, **k)
        with mock.patch("builtins.__import__", fake):
            with self.assertRaises(RecipeError) as cm:
                parts.spur_gear()
            self.assertIn("form-studio[parts]", cm.exception.hint)
            with self.assertRaises(RecipeError) as cm:
                parts.thread(12, 1.75, 10)
            self.assertIn("bd_warehouse", str(cm.exception))
            self.assertTrue(parts.heat_insert_pocket("M3").shape.is_valid)     # tabulated parts still work


class NewRecipes(unittest.TestCase):
    def _build(self, r, v):
        stages = r.build(v)
        final = stages[-1].shape
        self.assertTrue(final.is_valid)
        self.assertEqual(len(final.solids()), r.solids)
        self.assertGreaterEqual(final.bounding_box().min.Z, -1e-6)        # on the bed
        return final

    def test_registered(self):
        reg = registry()
        for rid in NEW:
            self.assertIn(rid, reg)
            self.assertEqual(reg[rid].id, rid)
        self.assertEqual((reg["enclosure"].solids, reg["gear_pair"].solids, reg["knob"].solids), (2, 3, 1))

    def test_defaults_build(self):
        reg = registry()
        for rid in NEW:
            if rid == "gear_pair" and not HAVE_GEARS:
                continue
            r = reg[rid]
            v = r.validate(r.defaults())
            with self.subTest(rid):
                f = self._build(r, v)
                derived = {d["key"]: d["value"] for d in r.derived(v)}
                self.assertIn(r.fit["cavity"], derived)
                st = r.statics(v, f.volume, (0, 0, 0))
                self.assertTrue(all(c["status"] in ("PASS", "WARN", "FAIL") for c in st["checks"]))
                self.assertTrue(all(c["status"] == "PASS" for c in st["checks"] if c["id"] != "tooth_strength"), st)
                piece, meta = r.test_piece(v, f)
                self.assertEqual(len(piece.solids()), 1)

    def test_each_param_at_min_and_max(self):
        """Every parameter alone at its limit either builds a valid part or is refused with a named fix."""
        reg = registry()
        for rid in NEW:
            if rid == "gear_pair" and not HAVE_GEARS:
                continue
            r = reg[rid]
            built = refused = 0
            for p in r.params:
                for x in (p.min, p.max):
                    vals = {**r.defaults(), p.key: x}
                    with self.subTest(rid=rid, key=p.key, value=x):
                        try:
                            v = r.validate(vals)
                        except RecipeError as e:
                            self.assertTrue(e.hint and e.params, f"{rid}.{p.key}={x}: {e}")
                            refused += 1
                            continue
                        self._build(r, v)
                        built += 1
            self.assertGreater(built, refused, rid)

    def test_small_and_large_variants(self):
        reg = registry()
        cases = {
            "enclosure": [dict(inner_w=50, inner_d=40, inner_h=20, pcb_w=30, pcb_d=20, hole_x=22, hole_y=12, hole_dx=0,
                               usbc=1, usbc_z=6, round_n=1, round_z=8, vents=4, vent_l=15, fasten=0),
                          dict(inner_w=180, inner_d=110, inner_h=60, usbc=2, round_n=4, vents=20, lid_head=1, lid_t=4.5,
                               lid_screw=4, boss_d=10)],
            "gear_pair": [dict(module=1, teeth_a=12, teeth_b=20, axle_d=3, thickness=4),
                          dict(module=2.5, teeth_a=20, teeth_b=40, axle_d=8, pegs=0, thickness=10)],
            "knob": [dict(knob_d=14, knob_h=10, bore_depth=7, grip_n=16, grip_depth=0.5, skirt=0, set_screw=0, shaft_d=4,
                          shaft_type=0),
                     dict(knob_d=50, knob_h=30, bore_depth=20, grip_n=48, skirt=6, shaft_d=8, shaft_flat=6.5)],
        }
        for rid, variants in cases.items():
            if rid == "gear_pair" and not HAVE_GEARS:
                continue
            r = reg[rid]
            for over in variants:
                with self.subTest(rid=rid, **over):
                    self._build(r, r.validate({**r.defaults(), **over}))

    def test_bad_combinations_name_the_fix(self):
        reg = registry()
        with self.assertRaises(RecipeError) as cm:
            reg["enclosure"].validate({**reg["enclosure"].defaults(), "boss_d": 6.5})     # under the insert's min wall
        self.assertEqual(cm.exception.feature, "bosses")
        with self.assertRaises(RecipeError) as cm:
            reg["gear_pair"].validate({**reg["gear_pair"].defaults(), "teeth_a": 40, "teeth_b": 20})
        self.assertIn("teeth_b", cm.exception.params)
        with self.assertRaises(RecipeError) as cm:
            reg["knob"].validate({**reg["knob"].defaults(), "shaft_flat": 2.5})
        self.assertEqual(cm.exception.feature, "flat")


class Pipeline(unittest.TestCase):
    """The full pipeline on the knob (fast): solid, exports, checks, and a real slice when Bambu Studio is installed."""

    def test_knob_pipeline(self):
        from form import config
        from form.studio import Studio
        with tempfile.TemporaryDirectory() as d:
            old = {k: os.environ.get(k) for k in ("FORM_DATA", "FORM_CONFIG")}
            os.environ["FORM_DATA"], os.environ["FORM_CONFIG"] = str(Path(d)), str(Path(d) / "none.toml")
            st = Studio(config.load())
            try:
                p = st.create("t knob", "knob")
                job = st.run_sync(p["id"])
                steps = {s["node"]: s["state"] for s in job["steps"]}
                for n in ("geometry", "exports", "checks"):
                    self.assertEqual(steps[n], "done", job)
                self.assertIn(steps["slice"], ("done", "blocked"), job)
                checks = st.read(st.load(p["id"]), "checks", st.keys(st.load(p["id"]))["checks"])["checks"]
                self.assertFalse([c for c in checks if c["status"] == "FAIL"], checks)
            finally:
                st.kernel.stop()
                for k, x in old.items():
                    if x is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = x


if __name__ == "__main__":
    unittest.main()
