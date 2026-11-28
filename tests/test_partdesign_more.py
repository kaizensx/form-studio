"""FreeCAD PartDesign export of the further hand features and the end conditions (form/partdesign.py).

Without FreeCAD: which arguments of the new calls are parameters. With FreeCAD's command line (skipped when it is
absent): a datum plane with a sketch on it, pads and pockets under every end condition PartDesign has (up to face
with an offset, up to first, two sides, a taper, mid-plane, reversed), a two-angle revolve, a pipe along a sketch and
along edges, a loft, a mirror of a feature and of the whole body, and a draft come back as native PartDesign
features, at the same volume, bounding box and face count; the datum plane's offset edited in FreeCAD's spreadsheet
moves the sketch on it as the parameter does here. The features PartDesign has no equivalent for (rib, move face,
thicken, split, boolean, variable fillet, a twisted sweep, a thin wall) go in decomposed or frozen, at volume
parity, saying why, never claimed editable."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-partdesign-more-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from form import cad_bridges, partdesign  # noqa: E402
from test_modelling_more import TOP, circle, line, rect  # noqa: E402

SRC = '''
from form.featureprog import FeatureDesign, feature


class Design(FeatureDesign):
    params = []

    @feature("Sweep 1")
    def sweep_1(self, v, body):
        from form import handmore
        return handmore.sweep(body, self._form_trail, {}, {}, v, "sweep_1", "add", v["sweep_1_twist"])

    @feature("Draft 1")
    def draft_1(self, v, body):
        from form import handmore
        return handmore.draft(body, self._form_trail, [], v["draft_1_angle"], {}, v, "draft_1")

    @feature("Cut 1")
    def cut_1(self, v, body):
        from form import handsketch
        return handsketch.extrude(body, self._form_trail, {}, v, "cut_1", v["cut_1_depth"], "cut", end="offset",
                                  offset=v["cut_1_offset"], draft=v["cut_1_draft"])
'''


class Plain(unittest.TestCase):

    def test_bindings_of_the_new_calls(self):
        b = partdesign.bindings(SRC)
        self.assertEqual(b["sweep_1"], {"call": "handmore.sweep", "args": {"twist": "sweep_1_twist"}})
        self.assertEqual(b["draft_1"]["args"], {"angle": "draft_1_angle"})
        self.assertEqual(b["cut_1"]["args"], {"depth": "cut_1_depth", "offset": "cut_1_offset", "draft": "cut_1_draft"})

    def test_every_new_call_is_watched_or_says_why_not(self):
        from form import handmore
        for name in partdesign.HAND_CALLS["handmore"]:
            self.assertTrue(callable(getattr(handmore, name)), name)
            native = name in ("sweep", "loft", "mirror", "draft", "datum_plane")
            self.assertEqual(f"handmore.{name}" in partdesign.NO_PD, not native, name)


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

    def plate(self, name):
        from form import modelling
        return modelling.start_from_sketch(self.st, name, rect(60, 40, name="w"), "extrude", depth=10)

    def add(self, p, kind, picks=None, **o):
        from form import modelling
        pl = modelling.plan(self.st, p, kind, picks or [], **o)
        modelling.commit(self.st, p, pl["ops"], p["head"], planned=pl)
        return self.st.load(p["id"])

    def same(self, r):
        pr = r["parity"]
        self.assertTrue(pr["valid_in_freecad"], r)
        self.assertLess(pr["volume_mm3"]["deviation_pct"], 1e-3, r)
        self.assertLess(pr["bbox_mm"]["max_deviation_mm"], 1e-3, r)
        self.assertLess(r["final_deviation"], 1e-5, r)

    def rows(self, r):
        return {f["feature"]: f for f in r["features"]}

    def test_1_datum_plane_end_conditions_and_the_sheet(self):
        p = self.plate("Datum and ends")
        p = self.add(p, "datum_plane", base="XY", offset=20)
        p = self.add(p, "extrude", sketch=circle(4, (45, 20), {"ref": "datum_plane_1"}), end="next", reverse=True)
        p = self.add(p, "cut", sketch=circle(3, (15, 20), TOP), end="offset", to_at=[30, 20, 0], offset=2)
        p = self.add(p, "extrude", sketch=circle(3, (15, 10), TOP), end="blind", depth=6, draft=5)
        p = self.add(p, "extrude", sketch=rect(6, 6, 25, 5, {"datum": "XY", "offset": 15}), end="blind", depth=3,
                     end2="next")
        p = self.add(p, "cut", sketch=rect(4, 4, 50, 30, TOP), end="mid", depth=8)
        r = partdesign.export(self.st, p, self.out / "ends.FCStd", edit={"datum_plane_1_offset": 25})
        rows = self.rows(r)
        self.assertEqual({k: f["status"] for k, f in rows.items()},
                         {"extrude_1": "native", "datum_plane_1": "native", "extrude_2": "native", "cut_1": "native",
                          "extrude_3": "native", "extrude_4": "native", "cut_2": "native"}, r["features"])
        self.assertIn("datum_plane_1_offset", r["params_bound"])
        self.assertIn("cut_1_offset", r["params_bound"])
        self.assertIn("extrude_3_draft", r["params_bound"])
        self.same(r)
        e = r["edit"]                                          # the datum plane moved in FreeCAD: the boss follows
        self.assertEqual(e["invalid"], [])
        self.assertLess(e["parity"]["volume_mm3"]["deviation_pct"], 1e-3)

    def test_2_revolve_pipe_loft_mirror_draft(self):
        from form import modelling
        sk = {"plane": {"datum": "XZ", "offset": 0},
              "points": [[10, 0], [20, 0], [20, 30], [10, 30], [0, 0], [0, 40]], "fixed": [0, 4],
              "entities": [{"k": "line", "p": [0, 1]}, {"k": "line", "p": [1, 2]}, {"k": "line", "p": [2, 3]},
                           {"k": "line", "p": [3, 0]}, {"k": "line", "p": [4, 5], "construction": True}],
              "constraints": [{"k": "horizontal", "e": [0]}, {"k": "vertical", "e": [1]},
                              {"k": "horizontal", "e": [2]}, {"k": "vertical", "e": [3]}, {"k": "vertical", "e": [4]},
                              {"k": "length", "e": [0], "value": 10, "name": "wall"}]}
        src, _ = modelling.sketch_design_source("Two way", sk, "revolve", axis_entity=4, angle=90)
        src = src.replace('v["revolve_1_angle"], "add")', 'v["revolve_1_angle"], "add", angle2=45)')
        p = self.st.create_design("Two way", src, purpose="model")
        r = partdesign.export(self.st, p, self.out / "twoway.FCStd")
        self.assertEqual([(f["planned"], f["status"]) for f in r["features"]], [("revolution", "native")])
        self.same(r)

        p = self.plate("Pipe loft mirror draft")
        p = self.add(p, "draft", [{"at": [0, 20, 5]}, {"at": [60, 20, 5]}], angle=4, neutral="XY")
        p = self.add(p, "sweep", sketch=circle(3, (30, 20), TOP), path=line([[30, 10], [30, 30], [50, 30]],
                                                                              {"datum": "XZ", "offset": -20}))
        p = self.add(p, "loft", sections=[rect(10, 10, 5, 5, TOP), rect(4, 4, 8, 8, {"datum": "XY", "offset": 25})],
                     ruled=True)
        p = self.add(p, "mirror", plane="XZ", plane_offset=-20, of="loft_1")
        r = partdesign.export(self.st, p, self.out / "pipe.FCStd")
        rows = self.rows(r)
        self.assertEqual({k: (f["planned"], f["status"]) for k, f in rows.items()},
                         {"extrude_1": ("pad", "native"), "draft_1": ("draft", "native"),
                          "sweep_1": ("pipe", "native"), "loft_1": ("loft", "native"),
                          "mirror_1": ("mirrored", "native")}, r["features"])
        self.assertIn("draft_1_angle", r["params_bound"])
        self.same(r)

    def test_3_no_equivalent_goes_in_frozen_or_decomposed_at_parity(self):
        p = self.plate("Frozen ones")
        p = self.add(p, "move_face", [{"at": [30, 20, 10]}], distance=3)
        p = self.add(p, "variable_fillet", [{"at": [30, 0, 13]}], r_start=1, r_end=3, start=[0, 0, 13])
        p = self.add(p, "thicken", [{"at": [60, 20, 5]}], thickness=2)
        p = self.add(p, "extrude", sketch=rect(20, 10, 5, 5, {"datum": "XY", "offset": 13}), end="blind", depth=5,
                     thin=1)
        r = partdesign.export(self.st, p, self.out / "frozen.FCStd")
        rows = self.rows(r)
        for fid in ("move_face_1", "variable_fillet_1", "thicken_1", "extrude_2"):
            self.assertIn(rows[fid]["status"], ("frozen", "decomposed"), rows[fid])
            self.assertTrue(rows[fid].get("why") or rows[fid].get("note"), rows[fid])
        self.assertIn("one radius", rows["variable_fillet_1"].get("why", "") + rows["variable_fillet_1"].get("note", ""))
        self.assertIn("thin wall", rows["extrude_2"].get("why", "") + rows["extrude_2"].get("note", ""))
        self.same(r)

    def test_4_split_and_boolean_and_rib(self):
        p = self.plate("Split and combine")
        p = self.add(p, "split", plane="YZ", plane_offset=20)
        p = self.add(p, "boolean", op="combine", target=[10, 20, 5], tools=[[40, 20, 5]])
        r = partdesign.export(self.st, p, self.out / "split.FCStd")
        self.same(r)
        from form import modelling
        from test_modelling import bracket_sketch
        b = modelling.start_from_sketch(self.st, "Bracket rib", bracket_sketch(), "extrude", depth=40)
        b = self.add(b, "rib", sketch=line([[40, 5], [5, 35]], {"datum": "XZ", "offset": 20}), thickness=4)
        r = partdesign.export(self.st, b, self.out / "rib.FCStd")
        rows = self.rows(r)
        self.assertEqual(rows["rib_1"]["status"], "decomposed", rows["rib_1"])      # a prism: a sketch and a Pad
        self.assertIn("no rib", rows["rib_1"]["note"])
        self.same(r)


if __name__ == "__main__":
    unittest.main()
