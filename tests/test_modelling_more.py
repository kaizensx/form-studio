"""More hand features (form/handmore.py, form/modelling_more.py) and the end conditions of a sketch feature.

Every kind (sweep, loft, rib, mirror, draft, move face, thicken, boolean, split, variable fillet, datum plane and
axis) and every end condition (blind, through, up to next, up to face, up to vertex, offset from face, mid-plane, a
second direction, draft, thin; revolve two ways, mid-plane, up to face) is planned as edit ops, previewed, committed
as one named method plus its parameters, built at the volume worked out by hand, round-trips through the canonical
source, survives a sweep of its own parameter, leaves the features before it loading from their checkpoints, and is
refused with the reason when it cannot be made."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-modelling-more-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import config, edits, featureprog, handsketch, modelling  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

PI = math.pi


def rect(w, h, x=0.0, y=0.0, plane=None, name=""):
    d, _ = handsketch.apply_ops(handsketch.empty(plane), [{"op": "add_rect", "at": [x, y], "size": [w, h]}])
    if name:
        d["constraints"].append({"k": "length", "e": [0], "value": w, "name": name})
    return d


def circle(r, c=(0.0, 0.0), plane=None, name=""):
    ops = [{"op": "add_circle", "center": list(c), "r": r}]
    if name:
        ops.append({"op": "dimension", "kind": "radius", "entities": [0], "value": r, "name": name})
    return handsketch.apply_ops(handsketch.empty(plane), ops)[0]


def line(pts, plane):
    d, _ = handsketch.apply_ops(handsketch.empty(plane), [{"op": "add_polyline", "points": pts, "auto": False}])
    return d


XY = {"datum": "XY", "offset": 0}
TOP = {"datum": "XY", "offset": 10}


class Base(unittest.TestCase):
    """A 60 x 40 x 10 plate from a sketch (x 0..60, y 0..40, z 0..10), a new design for every test."""

    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    def setUp(self):
        self.p = modelling.start_from_sketch(self.st, self.id().split(".")[-1], rect(60, 40, name="w"), "extrude",
                                             depth=10)

    def load(self):
        return self.st.load(self.p["id"])

    def vol(self, p=None):
        return self.st.head_summary(p or self.load())["volume_mm3"]

    def plan(self, kind, picks=None, **o):
        return modelling.plan(self.st, self.load(), kind, picks or [], **o)

    def preview(self, kind, picks=None, **o):
        p = self.load()
        pl = modelling.plan(self.st, p, kind, picks or [], **o)
        return pl, modelling.preview(self.st, p, pl["ops"])

    def refused(self, kind, why, picks=None, **o):
        """Refused at planning (StudioError) or by the build (preview not ok), with the reason; nothing saved."""
        head = self.load()["head"]
        try:
            _pl, pv = self.preview(kind, picks, **o)
        except StudioError as e:
            self.assertIn(why, str(e))
        else:
            self.assertFalse(pv["ok"], pv)
            self.assertIn(why, pv["refused"])
        self.assertEqual(self.load()["head"], head)

    def add(self, kind, picks=None, sweep=None, keep=True, **o):
        """Commit one feature; check the edit protocol, the checkpoints, the round-trip and a parameter sweep."""
        p = self.load()
        pl = modelling.plan(self.st, p, kind, picks or [], **o)
        pv = modelling.preview(self.st, p, pl["ops"])
        self.assertTrue(pv["ok"], pv)
        modelling.commit(self.st, p, pl["ops"], p["head"], planned=pl)
        p = self.load()
        fid = pl["feature"]
        log = {e["feature"]: e["status"] for e in self.st.rev(p)["build_log"]}
        self.assertIn(log[fid], ("built", "checkpoint"))      # the same feature built in an earlier test is reused
        self.assertEqual({k for k, s in log.items() if k != fid and s != "suppressed"},
                         {k for k, s in log.items() if k != fid and s == "checkpoint"})
        c = edits.canonical(self.st, p)
        self.assertIn(fid, featureprog.feature_ids(c["source"]))
        for prm in pl["params"]:
            self.assertIn(prm["key"], self.st.rev(p)["values"])
        prev = self.st.source_text(p, p["head"] - 1)
        self.assertEqual(edits.apply(prev, edits.delta(prev, c["source"]))[0], c["source"])
        for key, vals in (sweep or {}).items():
            for x in vals:
                s = self.st.preview(p, {key: x})
                self.assertFalse(s.get("skipped"), (kind, key, x, s.get("skipped")))
        out = (pl, pv, self.vol(p))
        if not keep:
            modelling.commit(self.st, p, [{"op": "suppress", "feature": fid}])
        return out


class EndConditions(Base):

    def test_1_cut_end_conditions(self):
        hole = circle(3, (15, 20), TOP, name="r")
        v0 = self.vol()
        a = PI * 9
        cases = [({"end": "blind", "depth": 4}, a * 4),
                 ({"end": "through"}, a * 10),
                 ({"end": "next"}, a * 10),
                 ({"end": "face", "to_at": [30, 20, 0]}, a * 10),
                 ({"end": "offset", "to_at": [30, 20, 0], "offset": 2}, a * 8),
                 ({"end": "vertex", "to": [60, 40, 3]}, a * 7),
                 ({"end": "blind", "depth": 4, "draft": 10}, None)]
        for o, want in cases:
            pl, pv = self.preview("cut", sketch=hole, **o)
            self.assertTrue(pv["ok"], (o, pv))
            if want is not None:
                self.assertAlmostEqual(-pv["volume_mm3"]["change"], want, delta=0.05, msg=o)
        _pl, pv = self.preview("cut", sketch=hole, end="blind", depth=4, draft=10)
        self.assertLess(-pv["volume_mm3"]["change"], a * 4)                 # a taper narrows the cut
        self.assertEqual(self.vol(), v0)
        pl, _pv, v = self.add("cut", sketch=hole, end="offset", to_at=[30, 20, 0], offset=2,
                              sweep={"cut_1_offset": [1, 5], "cut_1_r": [2, 5]})
        self.assertIn('end="offset"', modelling.edits.canonical(self.st, self.load())["source"])
        self.assertIn("offset from a face", pl["summary"])
        self.assertAlmostEqual(v0 - v, a * 8, delta=0.05)

    def test_2_pad_end_conditions_and_two_directions(self):
        boss = circle(4, (45, 20), TOP, name="r")
        a = PI * 16
        _pl, pv = self.preview("extrude", sketch=boss, end="mid", depth=6)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], a * 3, delta=0.05)        # half of it is in the plate
        mid = {"datum": "XY", "offset": 30}
        two = circle(4, (45, 20), mid)
        _pl, pv = self.preview("extrude", sketch=two, end="blind", depth=5, end2="next", new_body=False)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], a * 25, delta=0.05)       # 5 up, 20 down to the plate
        pl, _pv, _v = self.add("extrude", sketch=boss, end="blind", depth=5, end2="blind", depth2=2,
                               sweep={"extrude_2_depth2": [1, 9], "extrude_2_r": [2, 6]})
        self.assertIn("direction 2", pl["summary"])
        self.assertIn("extrude_2_depth2", self.st.rev(self.load())["values"])

    def test_3_thin_and_reverse(self):
        box = rect(20, 10, 5, 5, TOP)
        _pl, pv = self.preview("extrude", sketch=box, depth=8, end="blind", thin=1, thin_mode="mid")
        self.assertAlmostEqual(pv["volume_mm3"]["change"], (21 * 11 - 19 * 9) * 8, delta=0.05)
        _pl, pv = self.preview("extrude", sketch=box, depth=8, end="blind", thin=1, thin_mode="two", thin2=0.5)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], (22 * 12 - 19 * 9) * 8, delta=0.05)
        _pl, pv = self.preview("cut", sketch=rect(10, 10, 40, 5, XY), depth=3, end="blind", reverse=True)
        self.assertAlmostEqual(-pv["volume_mm3"]["change"], 300, delta=0.05)        # from the bottom, upward

    def test_4_refusals(self):
        hole = circle(3, (15, 20), TOP)
        self.refused("cut", "Unknown end condition", sketch=hole, end="sideways")
        self.refused("cut", "needs to_at", sketch=hole, end="face")
        self.refused("cut", "not ahead of the sketch", sketch=hole, end="vertex", to=[0, 0, 20])
        self.refused("extrude", "the body is already there", sketch=circle(3, (15, 20), {"datum": "XY", "offset": 5}),
                     end="next")
        self.refused("extrude", "meets no face ahead", sketch=circle(3, (15, 20), XY), end="next", reverse=True)
        self.refused("extrude", "thickness", sketch=rect(20, 10, 5, 5, TOP), depth=5, end="blind", thin=1,
                     thin_mode="two")

    def test_5_revolve_two_ways_and_mid(self):
        sk = {"plane": {"datum": "XZ", "offset": 0},
              "points": [[10, 0], [20, 0], [20, 30], [10, 30], [0, 0], [0, 40]], "fixed": [0, 4],
              "entities": [{"k": "line", "p": [0, 1]}, {"k": "line", "p": [1, 2]}, {"k": "line", "p": [2, 3]},
                           {"k": "line", "p": [3, 0]}, {"k": "line", "p": [4, 5], "construction": True}],
              "constraints": [{"k": "horizontal", "e": [0]}, {"k": "vertical", "e": [1]}, {"k": "horizontal", "e": [2]},
                              {"k": "vertical", "e": [3]}, {"k": "vertical", "e": [4]},
                              {"k": "length", "e": [0], "value": 10, "name": "wall"}]}
        full = PI * (400 - 100) * 30
        for o, share in (({"angle": 90}, 0.25), ({"angle": 90, "mid": True}, 0.25), ({"angle": 90, "angle2": 45}, 0.375),
                         ({"angle": 60, "reverse": True}, 1 / 6)):
            src, _ = modelling.sketch_design_source("Ring", sk, "revolve", axis_entity=4, **o)
            if "angle2" in o or o.get("mid") or o.get("reverse"):
                src = src.replace('v["revolve_1_angle"], "add")', 'v["revolve_1_angle"], "add"'
                                  + "".join(f", {k}={v!r}" for k, v in o.items() if k != "angle") + ")")
            p = self.st.create_design("Ring", src, purpose="model")
            self.assertAlmostEqual(self.st.head_summary(p)["volume_mm3"], full * share, delta=0.5, msg=o)


class Datums(Base):

    def test_1_datum_plane_drives_a_sketch(self):
        _pl, _pv, v0 = self.add("datum_plane", base="XY", offset=20, sweep={"datum_plane_1_offset": [12, 40]})
        self.assertAlmostEqual(v0, 24000, delta=1e-3)                               # a datum changes nothing
        boss = circle(4, (30, 20), {"ref": "datum_plane_1"})
        pl, _pv, v = self.add("extrude", sketch=boss, end="next", reverse=True)    # from 20 down to the plate
        self.assertAlmostEqual(v - v0, PI * 16 * 10, delta=0.05)
        src = edits.canonical(self.st, self.load())["source"]
        self.assertIn('"ref": "datum_plane_1"', src)
        self.assertIn('"offset": "datum_plane_1_offset"', src)
        s = self.st.preview(self.load(), {"datum_plane_1_offset": 30})              # the datum moves, the boss follows
        self.assertAlmostEqual(s["volume_mm3"] if "volume_mm3" in s else s["summary"]["volume_mm3"],
                               24000 + PI * 16 * 20, delta=0.05)
        with self.assertRaises(StudioError) as e:
            modelling.commit(self.st, self.load(), [{"op": "suppress", "feature": "datum_plane_1"}])
        self.assertIn("extrude_2 reads what datum_plane_1 makes", str(e.exception))

    def test_2_angled_and_three_point_planes_and_axes(self):
        pl, pv = self.preview("datum_plane", base="XZ", angle=30, about="x")
        self.assertTrue(pv["ok"], pv)
        pl, pv = self.preview("datum_plane", through=[[0, 0, 10], [60, 0, 10], [0, 40, 10]])
        self.assertTrue(pv["ok"], pv)
        self.refused("datum_plane", "on one line", through=[[0, 0, 0], [1, 0, 0], [2, 0, 0]])
        _pl, _pv, _v = self.add("datum_axis", base="Z", origin=[30, 20, 0])
        _pl, pv = self.preview("datum_axis", edge_at=[30, 0, 10])
        self.assertTrue(pv["ok"], pv)
        _pl, pv = self.preview("datum_axis", planes=["XZ", "YZ"])
        self.assertTrue(pv["ok"], pv)
        self.refused("datum_axis", "parallel", planes=["XY", "XY"])
        # a polar pattern about the datum axis (vertical through the plate's centre), a mirror about a datum plane
        self.add("cut", sketch=circle(2, (40, 20), TOP), depth=0)
        _pl, pv = self.preview("pattern", of="cut_1", mode="polar", axis="datum_axis_1", count=4)
        self.assertTrue(pv["ok"], pv)
        self.assertAlmostEqual(-pv["volume_mm3"]["change"], 3 * PI * 4 * 10, delta=0.05)
        self.add("datum_plane", base="YZ", offset=60)
        _pl, pv = self.preview("mirror", plane="datum_plane_1")
        self.assertAlmostEqual(pv["volume_mm3"]["after"], 2 * (24000 - PI * 4 * 10), delta=0.05)


class Sweeps(Base):

    def test_1_sweep_along_a_sketch_path_with_twist(self):
        path = line([[30, 10], [30, 30], [50, 30]], {"datum": "XZ", "offset": -20})
        prof = circle(3, (30, 20), TOP, name="r")
        _pl, pv = self.preview("sweep", sketch=prof, path=path)
        self.assertTrue(pv["ok"], pv)
        self.assertGreater(pv["volume_mm3"]["change"], PI * 9 * 38)
        straight = line([[10, 10], [10, 40]], {"datum": "XZ", "offset": -20})
        _pl, pv = self.preview("sweep", sketch=rect(6, 4, 7, 18, TOP), path=straight, twist=90)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], 6 * 4 * 30, delta=1.0)   # a twist keeps the section
        pl, _pv, _v = self.add("sweep", sketch=prof, path=path, sweep={"sweep_1_r": [2, 4]})
        self.assertIn("sweep_1_r", self.st.rev(self.load())["values"])
        self.refused("sweep", "from the path's start", sketch=circle(3, (5, 5), TOP), path=path)
        self.refused("sweep", "no closed profile", sketch=line([[0, 0], [5, 5]], TOP), path=path)

    def test_2_sweep_along_edges_and_cut(self):
        _pl, pv = self.preview("sweep", sketch=circle(1.5, (0, 10), {"datum": "YZ", "offset": 0}),
                               path_picks=[{"at": [30, 0, 10]}], cut=True)
        self.assertTrue(pv["ok"], pv)
        self.assertAlmostEqual(-pv["volume_mm3"]["change"], PI * 2.25 / 4 * 60, delta=0.5)   # a quarter round groove

    def test_3_loft(self):
        a = rect(20, 20, 20, 10, TOP, name="w")
        b = rect(10, 10, 25, 15, {"datum": "XY", "offset": 30})
        _pl, pv = self.preview("loft", sections=[a, b], ruled=True)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], 20 / 3 * (400 + 100 + 200), delta=0.05)
        _pl, pv = self.preview("loft", sections=[a, circle(5, (30, 20), {"datum": "XY", "offset": 30})])
        self.assertTrue(pv["ok"], pv)
        self.add("loft", sections=[a, b], ruled=True, sweep={"loft_1_s1_w": [15, 30]})
        self.refused("loft", "two or more", sections=[a])
        self.refused("loft", "same plane", sections=[a, rect(5, 5, 25, 15, TOP)])


class Ribs(unittest.TestCase):
    """An L bracket (base 60, upright 40, both 5 thick, 40 deep) and a rib in its corner."""

    @classmethod
    def setUpClass(cls):
        from test_modelling import bracket_sketch
        cls.st = Studio(config.load())
        cls.p = modelling.start_from_sketch(cls.st, "Bracket rib", bracket_sketch(), "extrude", depth=40)

    def test_rib(self):
        p = self.st.load(self.p["id"])
        mid = {"datum": "XZ", "offset": 20}                                    # y = -20, the middle of its depth
        ln = line([[40, 5], [5, 35]], mid)
        pl = modelling.plan(self.st, p, "rib", [], sketch=ln, thickness=4)
        pv = modelling.preview(self.st, p, pl["ops"])
        self.assertTrue(pv["ok"], pv)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], 35 * 30 / 2 * 4, delta=0.05)
        modelling.commit(self.st, p, pl["ops"], p["head"], planned=pl)
        p = self.st.load(self.p["id"])
        for t in (2, 8):
            self.assertFalse(self.st.preview(p, {"rib_1_t": t}).get("skipped"), t)
        flip = modelling.plan(self.st, p, "rib", [], sketch=line([[40, 5], [5, 35]], {"datum": "XZ", "offset": 10}),
                              thickness=4, flip=True)
        pv = modelling.preview(self.st, p, flip["ops"])
        self.assertFalse(pv["ok"])
        self.assertIn("run off the part", pv["refused"])
        with self.assertRaises(StudioError):
            modelling.plan(self.st, p, "rib", [], sketch=rect(5, 5, 10, 10, mid), thickness=4)


class BodyOps(Base):

    def test_1_mirror(self):
        _pl, pv = self.preview("mirror", plane="YZ")
        self.assertAlmostEqual(pv["volume_mm3"]["after"], 48000, delta=0.05)
        boss = circle(4, (50, 20), TOP)
        self.add("extrude", sketch=boss, depth=5)
        _pl, _pv, v = self.add("mirror", plane="YZ", plane_offset=30, of="extrude_2")
        self.assertAlmostEqual(v, 24000 + 2 * PI * 16 * 5, delta=0.05)
        self.refused("mirror", "No feature", of="nope")
        self.refused("mirror", "does not join", plane="YZ", plane_offset=-10)

    def test_2_draft(self):
        sides = [{"at": [0, 20, 5]}, {"at": [60, 20, 5]}]
        _pl, pv = self.preview("draft", sides, angle=5, neutral="XY")
        self.assertAlmostEqual(-pv["volume_mm3"]["change"], 2 * 0.5 * 10 * 10 * math.tan(math.radians(5)) * 40,
                               delta=0.05)
        self.add("draft", sides, angle=3, neutral="XY", sweep={"draft_1_angle": [1, 8], "extrude_1_w": [40, 80]}, keep=False)
        self.refused("draft", "faces the pull direction", [{"at": [30, 20, 10]}], angle=5, neutral="XY")
        self.refused("draft", "between 0.01 and 44.9", sides, angle=60)

    def test_3_move_face_and_thicken(self):
        _pl, pv = self.preview("move_face", [{"at": [30, 20, 10]}], distance=5)
        self.assertAlmostEqual(pv["volume_mm3"]["after"], 60 * 40 * 15, delta=0.05)
        self.add("move_face", [{"at": [60, 20, 5]}], distance=-10, sweep={"move_face_1_d": [-20, 5]}, keep=False)
        _pl, pv = self.preview("thicken", [{"at": [30, 20, 10]}], thickness=2)
        self.assertAlmostEqual(pv["volume_mm3"]["change"], 60 * 40 * 2, delta=0.05)
        self.refused("move_face", "distance is 0", [{"at": [30, 20, 10]}], distance=0)
        # a face whose neighbours lean (drafted sides): OCCT's offset stretches them to follow
        self.add("draft", [{"at": [0, 20, 5]}, {"at": [60, 20, 5]}], angle=5, neutral="XY")
        v0 = self.vol()
        _pl, pv = self.preview("move_face", [{"at": [30, 20, 10]}], distance=2)
        self.assertTrue(pv["ok"], pv)
        top = 60 - 2 * 10 * math.tan(math.radians(5))                    # the top's length at z = 10
        grown = 2 * 40 * (top - 2 * math.tan(math.radians(5)))            # the drafted sides carried on up 2 mm
        self.assertAlmostEqual(pv["volume_mm3"]["after"] - v0, grown, delta=0.5)

    def test_4_split_and_boolean(self):
        _pl, _pv, v = self.add("split", plane="YZ", plane_offset=20)
        p = self.load()
        self.assertEqual(self.st.rev(p)["build_log"][-1]["solids"], 2)
        self.assertIn("solids = 2", edits.canonical(self.st, p)["source"])
        self.assertAlmostEqual(v, 24000, delta=0.05)
        self.refused("boolean", "no body is at", target=[10, 20, 5], tools=[[200, 0, 0]])
        self.add("boolean", op="combine", target=[10, 20, 5], tools=[[40, 20, 5]])
        self.assertEqual(self.st.rev(self.load())["build_log"][-1]["solids"], 1)
        self.refused("boolean", "a boolean needs two or more", target=[10, 20, 5], tools=[[40, 20, 5]])
        self.refused("split", "does not cross", plane="YZ", plane_offset=100, keep="above")

    def test_5_new_body_then_subtract(self):
        self.add("extrude", sketch=circle(5, (30, 20), {"datum": "XY", "offset": 5}), depth=10, end="blind",
                 new_body=True)
        p = self.load()
        self.assertEqual(self.st.rev(p)["build_log"][-1]["solids"], 2)
        _pl, pv = self.preview("boolean", op="subtract", target=[5, 5, 5], tools=[[30, 20, 12]])
        self.assertAlmostEqual(pv["volume_mm3"]["after"], 24000 - PI * 25 * 5, delta=0.05)
        _pl, pv = self.preview("boolean", op="intersect", target=[5, 5, 5], tools=[[30, 20, 12]])
        self.assertAlmostEqual(pv["volume_mm3"]["after"], PI * 25 * 5, delta=0.05)

    def test_6_variable_fillet(self):
        pick = [{"at": [30, 0, 10]}]
        _pl, pv = self.preview("variable_fillet", pick, r_start=1, r_end=4, start=[0, 0, 10])
        self.assertTrue(pv["ok"], pv)
        const = (1 - PI / 4) * 60
        removed = -pv["volume_mm3"]["change"]
        self.assertGreater(removed, const * 1)                                 # between r1 and r4 everywhere
        self.assertLess(removed, const * 16)
        pl, _pv, _v = self.add("variable_fillet", pick, r_start=1, r_end=4, start=[0, 0, 10],
                               sweep={"variable_fillet_1_r1": [2, 6], "extrude_1_w": [40, 80]})
        # the start end has the small radius: the half at x < 30 keeps more material than the half at x > 30
        halves = {k: self.preview("split", plane="YZ", plane_offset=30, keep=k)[1]["volume_mm3"]["after"]
                  for k in ("below", "above")}
        self.assertGreater(halves["below"], halves["above"] + 0.1 * const)
        self.refused("variable_fillet", "variable fillet", [{"at": [30, 40, 10]}], r_start=1, r_end=30)

    def test_7_variable_fillet_starts_where_it_is_told(self):
        const = (1 - PI / 4) * 60
        for at, start in (([30, 40, 10], [60, 40, 10]), ([0, 20, 10], [0, 40, 10]), ([60, 20, 0], [60, 0, 0])):
            self.setUp()
            self.add("variable_fillet", [{"at": at}], r_start=1, r_end=4, start=start)
            plane, off, axis = ("YZ", 30, 0) if at[0] == 30 else ("XZ", -20, 1)
            halves = {k: self.preview("split", plane=plane, plane_offset=off, keep=k)[1]["volume_mm3"]["after"]
                      for k in ("below", "above")}
            # which half the start (small radius) end is in, along the plane's normal (XZ's normal is -y)
            start_side = "above" if (start[axis] - (30 if axis == 0 else 20)) * (1 if axis == 0 else -1) > 0 else "below"
            other = "below" if start_side == "above" else "above"
            self.assertGreater(halves[start_side], halves[other] + 0.05 * const, (at, start, halves))


class Interfaces(Base):
    """The same through MCP's add_feature (options=) and `form model` (--end, --opt)."""

    def test_mcp_add_feature(self):
        import asyncio
        import json

        from form import mcp_server
        srv = mcp_server.build()

        def call(args):
            out = asyncio.run(srv.call_tool("add_feature", {"project": self.p["id"], **args}))
            blocks = out if isinstance(out, (list, tuple)) else getattr(out, "content", out)
            if isinstance(blocks, tuple):
                blocks = blocks[0]
            return json.loads(next(b.text for b in blocks if getattr(b, "text", None)))
        out = call({"kind": "mirror", "preview": True, "options": {"plane": "YZ"}})
        self.assertFalse(out["saved"])
        self.assertAlmostEqual(out["preview"]["volume_mm3"]["after"], 48000, delta=0.05)
        out = call({"kind": "cut", "preview": True, "sketch": circle(3, (15, 20), TOP),
                    "options": {"end": "offset", "to_at": [30, 20, 0], "offset": 2}})
        self.assertAlmostEqual(-out["preview"]["volume_mm3"]["change"], PI * 9 * 8, delta=0.05)
        self.assertEqual(self.load()["head"], self.p["head"])

    def test_cli_form_model(self):
        import json
        import subprocess
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-m", "form", "model", self.p["id"], "datum_plane", "--opt", "offset=5",
                            "--opt", "angle=10", "--preview"], capture_output=True, text=True, env=env, cwd=str(ROOT),
                           timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = json.loads(r.stdout)
        self.assertTrue(out["preview"]["ok"], out)
        self.assertIn("turned 10°", out["summary"])
        r = subprocess.run([sys.executable, "-m", "form", "model", self.p["id"], "split", "--opt", "plane=\"YZ\"",
                            "--opt", "plane_offset=100", "--opt", "keep=\"above\"", "--preview"],
                           capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=300)
        out = json.loads(r.stdout)
        self.assertFalse(out["preview"]["ok"])
        self.assertIn("does not cross", out["preview"]["refused"])


if __name__ == "__main__":
    unittest.main()
