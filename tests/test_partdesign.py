"""FreeCAD PartDesign export (form/partdesign.py, form/partdesign_fc.py): a design as an editable feature tree.

Without FreeCAD: which arguments are parameters (read from the source), the Sketcher form of a sketch, the script.
With FreeCAD's command line (skipped when it is absent): a bracket made by hand (sketch, pad, ISO holes, fillet,
chamfer, pattern) and a revolve, a shell, a cut on a datum and a polar pattern all come back native, at the same
volume, bounding box and face count; a spreadsheet cell edited in FreeCAD resizes the model exactly as the parameter
does in Form Studio; built-in recipes (free code) come back decomposed or frozen at volume parity, never claimed
editable when they are not."""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-partdesign-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import cad_bridges, handsketch, partdesign  # noqa: E402

RECT = {"plane": {"datum": "XY", "offset": 0}, "points": [[0, 0], [60, 0], [60, 40], [0, 40]], "fixed": [0],
        "entities": [{"k": "line", "p": [0, 1]}, {"k": "line", "p": [1, 2]}, {"k": "line", "p": [2, 3]},
                     {"k": "line", "p": [3, 0]}],
        "constraints": [{"k": "horizontal", "e": [0]}, {"k": "vertical", "e": [1]}, {"k": "horizontal", "e": [2]},
                        {"k": "vertical", "e": [3]}, {"k": "length", "e": [0], "value": 60, "name": "w", "label": "Width"},
                        {"k": "length", "e": [1], "value": 40, "name": "h", "label": "Height"}]}

SOURCE = '''
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    params = [Param("fillet_1_r", "r", 2, 0.1, 8, 0.1, "mm", "form", "fillet_1")]

    @feature("Body")
    def body(self, v, body):
        from form import handsketch
        sketch = {}
        return handsketch.extrude(body, self._form_trail, sketch, v, "body", v["body_depth"], "add")

    @feature("Fillet 1", role="finish")
    def fillet_1(self, v, body):
        from form import handfeat
        return handfeat.fillet(body, self._form_trail, v["fillet_1_r"], [], "fillet_1")

    @feature("Hole 1")
    def hole_1(self, v, body):
        from form import handfeat
        return handfeat.hole(body, self._form_trail, {}, [0, 0, 0], v["hole_1_d"], v["hole_1_depth"],
                             style="counterbore", head_d=v["hole_1_head_d"], head_depth=4.0, what="hole_1")

    @feature("Code")
    def code(self, v, body):
        return body
'''


class Plain(unittest.TestCase):
    """No kernel, no FreeCAD."""

    def test_bindings_are_read_from_the_source(self):
        b = partdesign.bindings(SOURCE)
        self.assertEqual(b["body"], {"call": "handsketch.extrude", "args": {"depth": "body_depth"}})
        self.assertEqual(b["fillet_1"]["args"], {"radius": "fillet_1_r"})
        self.assertEqual(b["hole_1"]["args"], {"d": "hole_1_d", "depth": "hole_1_depth", "head_d": "hole_1_head_d"})
        self.assertNotIn("code", b)                                   # free code: no hand call, nothing bound

    def test_aliases_never_read_as_a_cell(self):
        self.assertEqual(partdesign.alias_of("extrude_1_w"), "extrude_1_w")
        self.assertEqual(partdesign.alias_of("d1"), "p_d1")             # D1 is a spreadsheet cell
        self.assertEqual(partdesign.alias_of("ab12"), "p_ab12")
        self.assertEqual(partdesign.alias_of("1st"), "p_1st")

    def test_a_sketch_as_sketcher_geometry(self):
        class P:                                                      # a plane: what _plane_dict reads
            class V:
                def __init__(self, x, y, z):
                    self.X, self.Y, self.Z = x, y, z
            origin, x_dir, z_dir = V(0, 0, 0), V(1, 0, 0), V(0, 0, 1)
        sk = partdesign._hand_sketch(RECT, {"extrude_1_w": 80}, "extrude_1", P)
        self.assertEqual([g["t"] for g in sk["geometry"]], ["line"] * 4)
        kinds = [c["t"] for c in sk["constraints"]]
        self.assertEqual(kinds.count("Coincident"), 4)                # each shared corner once
        self.assertEqual(kinds.count("Horizontal") + kinds.count("Vertical"), 4)
        dims = {c["name"]: c for c in sk["constraints"] if c.get("name")}
        self.assertEqual(dims["extrude_1_w"]["v"], 80.0)              # at the value the design was built with
        self.assertEqual(dims["extrude_1_w"]["bind"], "extrude_1_w")
        self.assertEqual(dims["extrude_1_h"]["v"], 40.0)
        self.assertAlmostEqual(sk["geometry"][1]["a"][0], 80.0, places=6)   # solved, not as drawn
        self.assertEqual(sk["plane"]["datum"], "XY")

    def test_axis_names_for_a_revolve(self):
        d = {"entities": [{"k": "line"}, {"k": "circle"}, {"k": "line", "construction": True},
                          {"k": "line", "construction": True}, {"k": "line"}]}
        self.assertEqual(partdesign._sketch_axis_ref(d, 0), "Edge1")
        self.assertEqual(partdesign._sketch_axis_ref(d, 4), "Edge3")
        self.assertEqual(partdesign._sketch_axis_ref(d, 2), "Axis0")
        self.assertEqual(partdesign._sketch_axis_ref(d, 3), "Axis1")

    def test_iso_hole_variants_from_the_label(self):
        self.assertEqual(partdesign._hole_iso("M3 clearance hole", "ISO 273 medium series, normal"),
                         [{"iso": {"size": "M3", "fit": "Medium"}}])
        self.assertEqual(partdesign._hole_iso("M4 clearance hole, counterbore", "ISO 273, close")[0]["iso"]["fit"], "Fine")
        self.assertEqual(partdesign._hole_iso("Ø8 H7 hole", "ISO 286"), [])

    def test_the_script_stands_alone(self):
        plan = {"steps": [], "params": [], "fcstd": "x.FCStd", "final_brep": "f.brep", "doc": "X", "label": "X",
                "flag": True, "none": None}
        text = partdesign.script_text(plan, "X")
        ast.parse(text)
        self.assertIn(partdesign.MARK, text.splitlines()[1])
        self.assertIn("main(PLAN", text)
        self.assertNotIn("Form Studio would", text)
        self.assertEqual(partdesign.parse("noise\nFORM_PARTDESIGN_RESULT {\"ok\": true}\n"), {"ok": True})
        self.assertFalse(partdesign.parse("no result")["ok"])

    def test_a_construction_line_is_valid_python_in_the_source(self):
        lit = handsketch.literal({**RECT, "entities": RECT["entities"] + [{"k": "line", "p": [0, 2], "construction": True}]})
        self.assertIn('"construction": True', lit)
        self.assertEqual(ast.literal_eval(lit)["entities"][-1]["construction"], True)


FREECAD = os.environ.get("FORM_FREECADCMD") or cad_bridges.find_freecad({})


@unittest.skipUnless(FREECAD, "FreeCAD's command line (freecadcmd) is not installed")
class InFreeCAD(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())
        cls.out = Path(TMP) / "exports"

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def add(self, p, kind, picks=None, **o):
        from form import modelling
        pl = modelling.plan(self.st, p, kind, picks or [], **o)
        modelling.commit(self.st, p, pl["ops"], p["head"], planned=pl)
        return self.st.load(p["id"])

    def same(self, r, places=4):
        pr = r["parity"]
        self.assertTrue(pr["valid_in_freecad"])
        self.assertLess(pr["volume_mm3"]["deviation_pct"], 1e-4)
        self.assertLess(pr["bbox_mm"]["max_deviation_mm"], 1e-3)
        self.assertLess(r["final_deviation"], 1e-6)
        self.assertTrue(Path(r["fcstd"]).is_file())
        self.assertTrue(Path(r["script"]).is_file())

    def test_bracket_by_hand_round_trips_native_and_edits_from_the_sheet(self):
        from form import modelling
        p = modelling.start_from_sketch(self.st, "Bracket", RECT, "extrude", depth=8)
        p = self.add(p, "hole", [{"at": [15, 20, 8]}], standard="clearance", size="M3")
        p = self.add(p, "hole", [{"at": [45, 20, 8]}], standard="clearance", size="M4", style="counterbore")
        p = self.add(p, "fillet", [{"at": [0, 0, 4]}, {"at": [60, 40, 4]}], radius=3)
        p = self.add(p, "chamfer", [{"at": [30, 0, 8]}], length=1)
        p = self.add(p, "pattern", of="hole_1", mode="linear", axis="y", count=2, pitch=10)
        r = partdesign.export(self.st, p, self.out / "bracket.FCStd", edit={"extrude_1_w": 80})
        rows = {f["feature"]: f for f in r["features"]}
        self.assertEqual({k: f["planned"] for k, f in rows.items()},
                         {"extrude_1": "pad", "hole_1": "hole", "hole_2": "hole", "fillet_1": "fillet",
                          "chamfer_1": "chamfer", "pattern_1": "linear_pattern"})
        self.assertEqual({f["status"] for f in rows.values()}, {"native"})
        self.assertEqual(r["non_parametric"], [])
        self.assertEqual(rows["hole_1"]["iso"], {"size": "M3", "fit": "Medium"})     # FreeCAD's ISO 273 table, Ø3.4
        for k in ("extrude_1_w", "extrude_1_h", "extrude_1_depth", "fillet_1_r", "chamfer_1_d", "pattern_1_pitch",
                  "pattern_1_n", "hole_2_head_d"):
            self.assertIn(k, r["params_bound"])
        self.same(r)
        self.assertEqual(r["parity"]["faces"]["form"], r["parity"]["faces"]["freecad"])
        e = r["edit"]                                                  # the cell edited in FreeCAD, recomputed
        self.assertEqual(e["invalid"], [])
        self.assertAlmostEqual(e["freecad"]["bbox"][1][0], 80.0, places=4)
        self.assertLess(e["parity"]["volume_mm3"]["deviation_pct"], 1e-4)          # = Form Studio's build at w=80
        self.assertIn("toponaming", r)
        # a second export over the first one is allowed; over a script someone else wrote it is refused
        partdesign.export(self.st, p, self.out / "bracket.FCStd")
        (self.out / "mine.py").write_text("print('mine')\n")
        from form.studio import StudioError
        with self.assertRaises(StudioError):
            partdesign.export(self.st, p, self.out / "mine.FCStd")
        self.assertEqual((self.out / "mine.py").read_text(), "print('mine')\n")

    def test_revolve_shell_cut_and_polar_pattern(self):
        from form import modelling
        sk = {"plane": {"datum": "XZ", "offset": 0},
              "points": [[10, 0], [20, 0], [20, 30], [10, 30], [0, 0], [0, 40]], "fixed": [0, 4],
              "entities": [{"k": "line", "p": [0, 1]}, {"k": "line", "p": [1, 2]}, {"k": "line", "p": [2, 3]},
                           {"k": "line", "p": [3, 0]}, {"k": "line", "p": [4, 5], "construction": True}],
              "constraints": [{"k": "horizontal", "e": [0]}, {"k": "vertical", "e": [1]}, {"k": "horizontal", "e": [2]},
                              {"k": "vertical", "e": [3]}, {"k": "vertical", "e": [4]},
                              {"k": "length", "e": [0], "value": 10, "name": "wall"},
                              {"k": "length", "e": [1], "value": 30, "name": "height"}]}
        p = modelling.start_from_sketch(self.st, "Ring", sk, "revolve", axis_entity=4, angle=270)
        r = partdesign.export(self.st, p, self.out / "ring.FCStd", edit={"revolve_1_height": 40})
        self.assertEqual([(f["planned"], f["status"]) for f in r["features"]], [("revolution", "native")])
        self.assertIn("revolve_1_angle", r["params_bound"])
        self.same(r)
        self.assertLess(r["edit"]["parity"]["volume_mm3"]["deviation_pct"], 1e-4)

        sq = {"plane": {"datum": "XY", "offset": 0}, "points": [[-30, -30], [30, -30], [30, 30], [-30, 30]],
              "fixed": [], "entities": RECT["entities"],
              "constraints": RECT["constraints"][:4] + [{"k": "length", "e": [0], "value": 60, "name": "w"},
                                                        {"k": "length", "e": [1], "value": 60, "name": "d"}]}
        p = modelling.start_from_sketch(self.st, "Tray", sq, "extrude", depth=20)
        p = self.add(p, "shell", [{"at": [0, 0, 20]}], thickness=2)
        vent = {"plane": {"datum": "XY", "offset": 0}, "points": [[15, 0]], "fixed": [0],
                "entities": [{"k": "circle", "p": [0], "r": 4}],
                "constraints": [{"k": "diameter", "e": [0], "value": 8, "name": "dia"}]}
        p = self.add(p, "cut", None, sketch=vent, depth=0)
        p = self.add(p, "pattern", of="cut_1", mode="polar", axis="z", count=4, angle=90)
        r = partdesign.export(self.st, p, self.out / "tray.FCStd", edit={"cut_1_dia": 10})
        self.assertEqual([(f["planned"], f["status"]) for f in r["features"]],
                         [("pad", "native"), ("thickness", "native"), ("pocket", "native"), ("polar_pattern", "native")])
        self.same(r)
        self.assertEqual(r["edit"]["invalid"], [])
        self.assertLess(r["edit"]["parity"]["volume_mm3"]["deviation_pct"], 1e-4)

    def test_recipes_free_code_decomposed_or_frozen_at_volume_parity(self):
        seen = set()
        for rid in ("coupon", "pegboard", "device_stand", "storage_box", "hose_adapter", "battery_holder"):
            p = self.st.create(rid, rid, purpose="model")
            r = partdesign.export(self.st, p, self.out / f"{rid}.FCStd")
            self.same(r)
            for f in r["features"]:
                seen.add(f["status"])
                self.assertIn(f["status"], ("decomposed", "frozen", "superseded", "native"), (rid, f))
                self.assertEqual(f["editable"], f["status"] in ("native", "decomposed"))
                if not f["editable"]:
                    self.assertIn(f["feature"], r["non_parametric"])
        self.assertTrue({"decomposed", "frozen"} <= seen)


if __name__ == "__main__":
    unittest.main()
