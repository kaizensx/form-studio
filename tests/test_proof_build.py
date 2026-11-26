"""The proof-carrying build: canonical form (form/canon.py), the edit protocol (form/edits.py), the contract and its
audit (form/contract.py), preflight without the kernel (form/preflight.py), kernel-checked obligations
(form/proving.py, @feature(expects=)), and the whole loop over real MCP stdio (scripts/proof_demo.py)."""
import ast
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.mkdtemp(prefix="form-proof-")
os.environ["FORM_DATA"] = TMP
sys.path.insert(0, str(ROOT))

from form import canon, config, contract, edits, featureprog, preflight  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

PLAIN = '''from build123d import Align, Box, Cylinder, Polygon, Pos, extrude
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


def post(r, h):
    return Cylinder(r, h, align=A)


class Design(Recipe):
    title = "Plate"
    summary = "A plate with a post and holes."
    params = [
        Param("w", "Width", 60, 20, 200, 1, "mm", "form", "plate"),
        Param("t", "Thickness", 6, 2, 20, 0.5, "mm", "form", "plate"),
        Param("post_d", "Post", 12, 4, 30, 0.5, "mm", "form", "post"),
        Param("hole_d", "Hole", 4, 2, 10, 0.1, "mm", "interface", "holes"),
    ]
    features = [Feature("plate", "Plate", "structure"), Feature("post", "Post", "structure"),
                Feature("holes", "Holes", "interface")]

    def constraints(self, v):
        e = []
        if v["post_d"] > v["w"] / 2:
            e.append(RecipeError("Post wider than half the plate", "post", "Make the post thinner.", ["post_d", "w"]))
        return e

    def build(self, v):
        w, t = v["w"], v["t"]
        half = w / 2 - 8
        body = Box(w, w, t, align=A)
        st = [Stage("plate", body)]
        # the post stands in the middle
        body = body + Pos(0, 0, t) * post(v["post_d"] / 2, 10)
        st.append(Stage("post", body))
        for sx in (-1, 1):
            for sy in (-1, 1):
                body = body - Pos(sx * half, sy * half, 0) * Cylinder(v["hole_d"] / 2, t, align=A)
        st.append(Stage("holes", body))
        return st
'''


def src(text: str = PLAIN, **swap) -> str:
    for a, b in swap.items():
        text = text.replace(a, b)
    return text


class Lift(unittest.TestCase):
    def test_build_is_split_at_its_stages_with_what_each_piece_needs(self):
        r = canon.lift(PLAIN)
        self.assertEqual((r["mode"], r["features"]), ("features", ["plate", "post", "holes"]))
        out = r["source"]
        self.assertTrue(featureprog.is_feature_design(out))
        self.assertNotIn("def build(", out)
        self.assertIn("class Design(FeatureDesign):", out)
        spans = featureprog.method_spans(out)
        lines = out.splitlines()
        holes = "\n".join(lines[spans["holes"][0] - 1:spans["holes"][1]])
        self.assertIn("half = w / 2 - 8", holes)                  # the arithmetic it reads is replayed in it
        self.assertNotIn("Box(", holes)                           # the geometry before it is not
        self.assertIn("@feature('Holes', role='interface')", holes)
        self.assertIn("def holes(self, v, body):", holes)
        post = "\n".join(lines[spans["post"][0] - 1:spans["post"][1]])
        self.assertIn("# the post stands in the middle", post)    # comments stay with their statements
        self.assertEqual(canon.lift(out)["mode"], "native")

    def test_a_value_measured_on_an_earlier_body_merges_the_pieces(self):
        s = src(**{"        for sx in (-1, 1):": "        top = body.bounding_box().max.Z\n        for sx in (-1, 1):"})
        s = s.replace('st.append(Stage("holes", body))\n        return st',
                      'st.append(Stage("holes", body))\n        body = body + Pos(0, 0, top) * post(2, 3)\n'
                      '        st.append(Stage("post", body))\n        return st')
        r = canon.lift(s)
        self.assertEqual(r["mode"], "features")
        self.assertEqual(len(r["features"]), 3)
        self.assertTrue(r["features"][-1].endswith("_stages"), r["features"])   # holes + the piece that reads `top`
        ast.parse(r["source"])

    def test_geometry_is_never_replayed_into_a_later_feature(self):
        s = src(**{"        body = Box(w, w, t, align=A)": "        tool = post(v['hole_d'] / 2, t)\n        body = Box(w, w, t, align=A)",
                   "Cylinder(v[\"hole_d\"] / 2, t, align=A)": "tool"})
        r = canon.lift(s)
        self.assertNotEqual(r["mode"], "none")
        for fid, (a, b) in featureprog.method_spans(r["source"]).items():
            body = "\n".join(r["source"].splitlines()[a - 1:b])
            self.assertLessEqual(body.count("tool = post("), 1)
        self.assertEqual(r["source"].count("tool = post("), 1)

    def test_what_cannot_be_split_is_one_skeleton_feature_and_what_cannot_be_wrapped_says_why(self):
        s = PLAIN.replace("        return st\n", "        self.made = len(st)\n        return st\n")
        r = canon.lift(s)
        self.assertEqual((r["mode"], r["features"]), ("skeleton", ["recipe_stages"]))
        self.assertIn("state on self", r["why"])
        self.assertEqual(canon.lift("x = (")["mode"], "none")
        self.assertEqual(canon.lift(PLAIN.replace("    title", "    mesh = True\n    title"))["mode"], "none")

    def test_one_line_statements_and_one_space_indents_still_lift(self):
        s = ('from build123d import *\nfrom form.recipes.base import Feature, Param, Recipe, Stage\nclass Design(Recipe):\n'
             ' title="T"\n params=[Param("s","S",10,1,20,1,"mm","form","a")]\n'
             ' features=[Feature("a","A","structure"),Feature("b","B","structure")]\n'
             ' def build(self,v):\n  s=v["s"]; a=Box(s,s,s); st=[Stage("a",a)]\n  a=a-Cylinder(s/4,s); st.append(Stage("b",a))\n'
             '  return st\n')
        r = canon.lift(s)
        self.assertEqual((r["mode"], r["features"]), ("features", ["a", "b"]))
        ast.parse(r["source"])
        one = s.replace(' def build(self,v):\n  s=v["s"]; a=Box(s,s,s); st=[Stage("a",a)]\n  a=a-Cylinder(s/4,s); '
                        'st.append(Stage("b",a))\n  return st\n', ' def build(self,v): return [Stage("a",Box(1,1,1))]\n')
        w = canon.lift(one)
        self.assertEqual(w["mode"], "skeleton")
        ast.parse(w["source"])


class Ops(unittest.TestCase):
    def setUp(self):
        self.src = canon.lift(PLAIN)["source"]

    def test_every_op_and_what_it_touched(self):
        new, info = edits.apply(self.src, [
            {"op": "replace", "feature": "post", "code": "def post(self, v, body):\n    return body + Pos(0, 0, v['t']) * post(v['post_d'] / 2, 14)"},
            {"op": "insert", "feature": "rim", "code": "def rim(self, v, body):\n    return body", "after": "post", "label": "Rim"},
            {"op": "insert", "param": {"key": "rim_h", "label": "Rim height", "default": 2, "min": 1, "max": 5}},
            {"op": "set_param", "param": "hole_d", "default": 4.5, "max": 12},
            {"op": "set_param", "param": "w", "value": 80},
            {"op": "replace", "def": "post", "code": "def post(r, h):\n    return Cylinder(r, h + 0, align=A)"},
            {"op": "insert", "def": "ring", "code": "def ring(r):\n    return Cylinder(r, 1, align=A)"},
            {"op": "replace", "find": 'summary = "A plate with a post and holes."', "with": 'summary = "Edited."'},
        ])
        ast.parse(new)
        self.assertEqual(featureprog.feature_ids(new), ["plate", "post", "rim", "holes"])
        self.assertEqual(info["features"], {"changed": ["post"], "added": ["rim"], "removed": []})
        self.assertTrue(info["shared"])
        self.assertEqual(info["values"], {"hole_d": 4.5, "w": 80.0})
        self.assertIn("Param('hole_d', 'Hole', 4.5, 2, 12, 0.1, 'mm', 'interface', 'holes')", new)
        self.assertIn("Param('rim_h', 'Rim height', 2, 1, 5)", new)
        self.assertIn("def ring(r):", new)
        self.assertLess(new.index("def ring(r):"), new.index("class Design"))
        self.assertIn("h + 0", new)
        gone, info = edits.apply(new, [{"op": "delete", "feature": "rim"}, {"op": "delete", "param": "rim_h"},
                                       {"op": "delete", "def": "ring"}])
        self.assertNotIn("rim", gone)
        self.assertNotIn("ring", gone)
        ast.parse(gone)

    def test_every_bad_op_is_reported_at_once_and_nothing_is_applied(self):
        with self.assertRaises(StudioError) as cm:
            edits.apply(self.src, [
                {"op": "replace", "feature": "nope", "code": "def nope(self, v, body):\n    return body"},
                {"op": "set_param", "param": "missing", "default": 3},
                {"op": "replace", "find": "Stage(", "with": "x"},
                {"op": "bogus"},
                {"op": "set_param", "param": "w", "value": 70},
            ])
        probs = cm.exception.extra["problems"]
        self.assertEqual([x["op"] for x in probs], [1, 2, 3, 4])
        self.assertIn("4 of 5", str(cm.exception))

    def test_delta_turns_one_source_into_another_exactly(self):
        b = canon.lift(PLAIN.replace("post(v[\"post_d\"] / 2, 10)", "post(v[\"post_d\"] / 2, 12)")
                       .replace('Param("t", "Thickness", 6,', 'Param("t", "Thickness", 7,'))["source"]
        for structural in (True, False):
            ops = edits.delta(self.src, b, structural)
            self.assertEqual(edits.apply(self.src, ops)[0], b)
        ops = edits.delta(self.src, b)
        self.assertEqual([o.get("feature") for o in ops if "feature" in o], ["post"])
        tight = edits.tighten(self.src, ops)
        self.assertEqual(edits.apply(self.src, tight)[0], b)
        self.assertLess(len(json.dumps(tight)), len(json.dumps(ops)))
        self.assertLess(len(json.dumps(tight)), 0.3 * len(b))


class Contract(unittest.TestCase):
    def test_a_brief_becomes_typed_assertions_with_provenance(self):
        c = contract.compile_brief({"goal": "A flange Ø70 with a Ø20 bore, 4×Ø5.2 on a 60 mm bolt circle, 2.4 mm walls.",
                                    "requirements": ["M6 thread in the hub", "fits in 80 x 80 x 20 mm", "two-part"],
                                    "dimensions": {"wall": {"value": 2.4, "unit": "mm", "source": "specified"}}},
                                   [{"kind": "hole_count", "count": 1, "d": 20, "tol": 0.05}])
        kinds = [a["kind"] for a in c["assertions"]]
        for k in ("hole_count", "cylinder", "bolt_circle", "min_wall", "thread", "bbox", "part_count"):
            self.assertIn(k, kinds)
        self.assertEqual(kinds.count("min_wall"), 1)                 # the dimension and the sentence say the same
        bc = next(a for a in c["assertions"] if a["kind"] == "bolt_circle")
        self.assertEqual((bc["count"], bc["hole_d"], bc["circle_d"], bc["tol"]), (4, 5.2, 60.0, contract.DEFAULT_TOL))
        self.assertEqual(bc["provenance"]["source"], "brief")
        self.assertIn("bolt circle", bc["provenance"]["quote"])
        self.assertIn("assumed", bc["provenance"]["tolerance"])
        self.assertEqual(c["assertions"][0]["tol"], 0.05)
        self.assertNotIn("tolerance", c["assertions"][0]["provenance"])
        self.assertTrue(c["audit"]["ok"])
        self.assertEqual(len({a["id"] for a in c["assertions"]}), len(c["assertions"]))

    def test_the_audit_finds_what_cannot_hold_before_any_code(self):
        c = contract.compile_brief({"goal": "A flange Ø68 with 4 x Ø5.2 on a 60 mm bolt circle and 2.4 mm walls"})
        au = c["audit"]
        self.assertFalse(au["ok"])
        self.assertIn("1.40 mm", au["conflicting"][0]["why"])
        self.assertIn("at least 70 mm", au["conflicting"][0]["why"])
        self.assertIn("Conflict:", contract.audit_text(au))
        c = contract.compile_brief({"goal": "12 x Ø9 on a 30 mm bolt circle; walls of 3 mm and a 2 mm wall",
                                    "requirements": ["a threaded bore", "holes on a bolt circle of the usual size"],
                                    "unknowns": ["screw size"]})
        self.assertTrue(any("overlap" in x["why"] for x in c["audit"]["impossible"]))
        self.assertTrue(any("two different values" in x["why"] for x in c["audit"]["conflicting"]))
        whats = [m["what"] for m in c["audit"]["missing"]]
        for w in ("thread", "bolt circle", "unknown"):
            self.assertIn(w, whats)
        # what reads like a requirement but is not one is left alone: a wall's width, the value before an edit, one of two
        c = contract.compile_brief({"goal": "A vertical wall 60 mm wide; enlarge the bore from Ø20 mm to Ø24 mm; one Ø8 mm "
                                            "hole in the base and one Ø8 mm hole in the wall; a flange 6 mm thick."})
        self.assertEqual([a["text"] for a in c["assertions"]], ["Ø24 mm cylinder", "Ø8 mm bore"])
        c = contract.compile_brief({"goal": "Six bolt holes of diameter 11 mm, equally spaced on a 95 mm bolt circle (PCD). "
                                            "Outside diameter 120 mm, bore diameter 40 mm, overall length 14 mm; a plate "
                                            "80 mm x 80 mm, 8 mm thick with four Ø9 mm fastener holes."})
        self.assertEqual([a["text"] for a in c["assertions"]],
                         ["6 x Ø11 mm on a Ø95 mm bolt circle", "Ø120 mm boss", "Ø40 mm bore",
                          "overall size 14 mm (along one axis)", "size 80 x 80 x 8 mm (any orientation)", "4 hole(s) Ø9 mm"])
        self.assertEqual(c["audit"]["missing"], [])
        bad = contract.compile_brief({"goal": "a box"}, [{"kind": "bolt_circle", "count": 4}, {"kind": "nope"}])
        self.assertEqual(len(bad["audit"]["invalid"]), 2)
        self.assertFalse(bad["audit"]["ok"])

    def test_each_assertion_is_an_obligation_of_one_feature(self):
        feats = [{"id": "disc", "label": "Disc"}, {"id": "bore", "label": "Centre bore"},
                 {"id": "mounting", "label": "Bolt holes", "expects": [contract.holes(2, 3)]}, {"id": "edges", "label": "Chamfer"}]
        got = contract.assign([contract.normalise(a) for a in (
            contract.bolt_circle(4, 5.2, 60), contract.cylinder(20, "bore"), contract.cylinder(70, "boss"),
            contract.bbox(70, 70, 8), contract.holes(2, 3), {**contract.wall(2.4), "feature": "disc"})], feats)
        self.assertEqual([(a["feature"], a["assigned"]) for a in got],
                         [("mounting", "matched by name"), ("bore", "matched by name"), ("disc", "matched by name"),
                          ("edges", "the finished design"), ("mounting", "expects"), ("disc", "named")])


WINDING = PLAIN.replace("        body = body + Pos(0, 0, t) * post(v[\"post_d\"] / 2, 10)",
                        "        pts = [(0, 0), (0, w / 4), (w / 4, w / 4), (w / 4, 0)]\n"
                        "        body = body + Pos(0, 0, t) * extrude(Polygon(*pts, align=None), amount=5)")


class Preflight(unittest.TestCase):
    def rules(self, source, **kw):
        r = preflight.check(source, **kw)
        self.assertEqual(r["kernel_s"], 0.0)
        return r, [(f["rule"], f["severity"]) for f in r["findings"] if f["severity"] != "note"]

    def test_a_clean_design_has_nothing_to_say(self):
        r, rules = self.rules(PLAIN)
        self.assertEqual(rules, [])
        self.assertTrue(r["ok"])
        self.assertEqual(r["dry_run"]["ran"], ["load", "constraints", "build"])
        r, rules = self.rules(canon.lift(PLAIN)["source"])
        self.assertEqual(rules, [])
        self.assertEqual(r["dry_run"]["ran"][-3:], ["plate", "post", "holes"])

    def test_the_three_logged_mistakes_are_found_without_the_kernel(self):
        # 1. a constraint the design's own defaults violate
        r, rules = self.rules(PLAIN.replace('Param("post_d", "Post", 12,', 'Param("post_d", "Post", 40,')
                              .replace("30, 0.5", "60, 0.5"))
        self.assertEqual(rules, [("constraints", "error")])
        f = r["findings"][0]
        self.assertIn("Post wider than half the plate", f["message"])
        self.assertIn("post_d = 40", f["hint"])
        # 2. a clockwise polygon extruded with a positive amount goes down
        r, rules = self.rules(WINDING)
        self.assertEqual(rules, [("winding", "error")])
        self.assertIn("clockwise", r["findings"][0]["message"])
        self.assertIn("-Z", r["findings"][0]["message"])
        self.assertEqual(r["findings"][0]["line"], WINDING.splitlines().index(
            "        body = body + Pos(0, 0, t) * extrude(Polygon(*pts, align=None), amount=5)") + 1)
        ccw = WINDING.replace("[(0, 0), (0, w / 4), (w / 4, w / 4), (w / 4, 0)]", "[(0, 0), (w / 4, 0), (w / 4, w / 4), (0, w / 4)]")
        self.assertEqual(self.rules(ccw)[1], [])
        # 3. a bolt and a threaded hole whose clearances were added twice, and a thread the contract wants that nothing makes
        th = PLAIN.replace("from form.recipes.base", "from form import parts\nfrom form.recipes.base").replace(
            "        body = body + Pos(0, 0, t) * post(v[\"post_d\"] / 2, 10)",
            "        bolt = parts.thread(10, 2.0, 12)\n        hole = parts.thread(10 + 0.5, 2.0, 12, external=False)\n"
            "        body = body + Pos(0, 0, t) * bolt.shape - hole.shape")
        r, rules = self.rules(th)
        self.assertEqual(rules, [("threads", "warn")])
        f = r["findings"][0]
        self.assertEqual((f["play_mm"], f["engagement_mm"], f["basic_depth_mm"]), (1.1, 0.532, 1.083))
        self.assertIn("49 %", f["message"])
        r, rules = self.rules(PLAIN, contract=[contract.normalise(contract.thread(6))])
        self.assertEqual(rules, [("threads", "warn")])
        self.assertIn("plain bore", r["findings"][0]["hint"])
        lone = th.replace("        hole = parts.thread(10 + 0.5, 2.0, 12, external=False)\n", "").replace(" - hole.shape", "")
        self.assertIn("no internal thread", self.rules(lone)[0]["findings"][0]["message"])

    def test_names_keywords_parameters_selectors_and_order(self):
        bad = PLAIN.replace("Box(w, w, t, align=A)", "Box(w, w, t, aling=A)") \
            .replace("from build123d import Align, Box,", "from build123d import Align, Bx, Box,") \
            .replace('v["hole_d"] / 2, t, align=A)', 'v["hole_dia"] / 2, t, align=Align.MIDDLE)')
        r, rules = self.rules(bad)
        msgs = " | ".join(f["message"] for f in r["findings"])
        self.assertIn("build123d has no Bx", msgs)
        self.assertIn("Box() has no argument aling", msgs)
        self.assertIn("Align has no member MIDDLE", msgs)
        self.assertIn("reads v['hole_dia'], which is not a parameter", msgs)
        self.assertTrue(all(sev == "error" for _r, sev in rules), rules)
        self.assertIn("align", next(f for f in r["findings"] if "aling" in f["message"])["hint"])
        sel = PLAIN.replace("        st.append(Stage(\"holes\", body))",
                            "        body = fillet(body.edges()[3], 1)\n        st.append(Stage(\"holes\", body))") \
            .replace("extrude\n", "extrude, fillet\n")
        r, rules = self.rules(sel)
        self.assertEqual(rules, [("index_selector", "warn")])
        self.assertIn("craft.made_by", r["findings"][0]["hint"])
        order = PLAIN.replace("        st.append(Stage(\"post\", body))",
                              "        body = fillet(body.edges(), 0.5)\n        st.append(Stage(\"post\", body))") \
            .replace("extrude\n", "extrude, fillet, GridLocations\n") \
            .replace("        for sx in (-1, 1):", "        for loc in GridLocations(10, 10, 2, 2):\n            pass\n        for sx in (-1, 1):")
        r, rules = self.rules(order)
        self.assertEqual(rules, [("finish_order", "warn")])
        self.assertEqual(r["findings"][0]["features"], ["post", "holes"])
        parts_ = canon.lift(PLAIN)["source"].replace("@feature('Post', role='structure')", "@feature('Post', role='structure', parts=2)")
        self.assertIn(("parts", "error"), self.rules(parts_)[1])
        self.assertEqual(self.rules("def x(:\n")[1], [("syntax", "error")])

    def test_only_what_an_edit_introduces_blocks_it(self):
        a = preflight.check(WINDING)["findings"]
        moved = preflight.check("# a comment\n" + WINDING)["findings"]
        self.assertEqual(preflight.new_findings(moved, a), [])
        self.assertEqual(len(preflight.new_findings(a, [])), 1)

    def test_preflight_imports_no_kernel(self):
        code = ("import sys, json; sys.path.insert(0, %r)\nfrom form import preflight\n"
                "r = preflight.check(open(sys.argv[1]).read())\n"
                "print(json.dumps({'rules': [f['rule'] for f in r['findings']], 'ran': r['dry_run']['ran'],\n"
                "                  'kernel': sorted(m for m in sys.modules if m.split('.')[0] in ('OCP', 'build123d', 'bd_warehouse'))}))\n"
                % str(ROOT))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "winding.py"
            f.write_text(WINDING, encoding="utf-8")
            out = subprocess.run([sys.executable, "-c", code, str(f)], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-600:])
        got = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(got["kernel"], [])                          # neither OCCT nor build123d was imported
        self.assertEqual(got["rules"], ["winding"])
        self.assertIn("build", got["ran"])

    def test_the_api_snapshot_is_the_installed_api(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_preflight_api.py"), "--check"],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, "form/preflight_api.json is stale: run scripts/gen_preflight_api.py")
        self.assertTrue(preflight.api()["current"])

    def test_the_shipped_examples_raise_no_error(self):
        from form import design_guide, exemplars
        srcs = [("guide", design_guide.EXAMPLE), ("guide features", design_guide.FEATURE_EXAMPLE)]
        srcs += [(e["name"], exemplars.get(e["name"])["source"]) for e in exemplars.catalogue()]
        for name, s in srcs:
            errs = [f for f in preflight.check(s)["findings"] if f["severity"] == "error"]
            self.assertEqual(errs, [], name)


FLANGE = (ROOT / "scripts" / "proof_demo.py").read_text(encoding="utf-8").split("SOURCE = '''", 1)[1].split("'''", 1)[0]


class Kernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        shutil.rmtree(TMP, ignore_errors=True)

    def test_a_lifted_design_is_the_same_solid_and_an_edit_builds_only_what_changed(self):
        st = self.st
        p = st.create_design("Plate", PLAIN)
        base = st.head_summary(p)
        c = edits.canonical(st, p)
        self.assertEqual((c["mode"], c["verified"]), ("features", True))
        r = edits.edit(st, p, [{"op": "replace", "feature": "holes", "code":
                                "def holes(self, v, body):\n    return body - Cylinder(v['hole_d'] * 1.2, v['t'], align=A)"}],
                       expect_head=1)
        self.assertEqual(r["head"], 2)
        self.assertEqual([(e["feature"], e["status"]) for e in r["changed"]], [("holes", "built")])
        self.assertEqual(r["reused"], ["plate", "post"])
        self.assertEqual(r["canonical"]["mode"], "features")
        self.assertEqual(r["source_sha"], st.rid(st.load(p["id"])).split(":")[1])
        self.assertNotEqual(round(st.head_summary(st.load(p["id"]))["volume_mm3"], 3), round(base["volume_mm3"], 3))
        # a value only: a commit, and only the feature that reads it is built
        r = edits.edit(st, st.load(p["id"]), [{"op": "set_param", "param": "hole_d", "value": 4.5}], expect_head=2)
        self.assertEqual([(e["feature"], e["status"]) for e in r["changed"]], [("holes", "built")])
        self.assertEqual(st.rid(st.load(p["id"])).split(":")[1], r["source_sha"])
        with self.assertRaises(StudioError) as cm:
            edits.edit(st, st.load(p["id"]), [{"op": "set_param", "param": "w", "value": 90}], expect_head=1)
        self.assertEqual(cm.exception.status, 409)
        # an edit that introduces a preflight error is refused before the kernel, with every finding
        with self.assertRaises(StudioError) as cm:
            edits.edit(st, st.load(p["id"]), [{"op": "replace", "feature": "post", "code":
                                               "def post(self, v, body):\n    return body + Box(1, 1, v['tall'], aling=A)"}])
        self.assertEqual(cm.exception.extra["kind"], "preflight")
        self.assertEqual(sorted({f["rule"] for f in cm.exception.extra["findings"] if f["severity"] == "error"}), ["api", "params"])
        self.assertEqual(st.load(p["id"])["head"], 3)

    def test_proof_sheet_obligations_and_the_claim_gate(self):
        st = self.st
        from form import staged
        b = staged.save_brief(st, "Flange", "A flange Ø70 with a Ø20 bore, 4 x Ø5.2 on a 60 mm bolt circle and 2.4 mm walls",
                              purpose="model", assertions=[contract.part_count(1)])
        p = st.create_design("Flange", FLANGE, purpose="model")
        staged.attach(st, p["id"], brief=b)
        p = st.load(p["id"])
        sheet = contract.prove(st, p)
        rows = {r["kind"] + ":" + r["requirement"]: r for r in sheet["rows"]}
        bc = next(r for r in sheet["rows"] if r["kind"] == "bolt_circle")
        self.assertEqual((bc["status"], bc["feature"], bc["evidence"]), ("FAIL", "holes", "computed"))
        self.assertIn("Ø5", bc["measured_text"])
        self.assertEqual((bc["repair"], bc["where"]), ("holes", "not met when holes finished, nor after any later feature"))
        self.assertEqual(sheet["counts"], {"PASS": len(rows) - 1, "FAIL": 1, "UNPROVEN": 0})
        self.assertFalse(sheet["green"])
        wall = next(r for r in sheet["rows"] if r["kind"] == "min_wall")
        self.assertEqual(wall["status"], "PASS")
        self.assertIn("samples", wall["measured_text"])
        gate = contract.claim_gate(st, p)
        self.assertEqual((gate["green"], gate["has_contract"], gate["physical"]), (False, True, False))
        self.assertEqual([x["requirement"] for x in gate["must_not_claim"]], [bc["requirement"]])
        self.assertEqual(len(gate["may_claim"]), len(rows) - 1)
        self.assertIn("fail", " ".join(st.gate(p)["reasons"]))
        table = contract.table(sheet)
        self.assertEqual(set(table[0]) >= {"requirement", "measured", "tolerance", "evidence", "status"}, True)
        # one op repairs the red row; the sheet of the new revision is another file under another key
        r = edits.edit(st, p, [{"op": "set_param", "param": "hole_d", "default": 5.2}], expect_head=1)
        p = r["project"]
        sheet2 = contract.prove(st, p)
        self.assertTrue(sheet2["green"], sheet2["rows"])
        self.assertEqual(sheet2["rev"], 2)
        self.assertTrue(contract.claim_gate(st, p)["green"])
        self.assertNotIn("requirement", " ".join(st.gate(p)["reasons"]))
        from form.digest import digest
        self.assertTrue(digest(st, p["id"])["proof"]["green"])
        # a hole lost at a later feature says where
        r = edits.edit(st, p, [{"op": "replace", "feature": "edges", "code":
                                "def edges(self, v, body):\n    return body + Cylinder(v['outer_d'] / 2, v['t'], align=A)"
                                " - Cylinder(v['bore_d'] / 2, v['t'], align=A)"}], expect_head=2)
        bc = next(x for x in contract.prove(st, r["project"])["rows"] if x["kind"] == "bolt_circle")
        self.assertEqual((bc["status"], bc["where"], bc["repair"]), ("FAIL", "met after holes, lost at edges", "edges"))
        # a design with no contract promises nothing checkable
        q = st.create_design("Plate 2", PLAIN.replace('"Plate"', '"Plate 2"'))
        self.assertIsNone(contract.prove(st, q))
        g = contract.claim_gate(st, q)
        self.assertEqual((g["has_contract"], g["green"], g["may_claim"]), (False, False, []))

    def test_expects_fails_at_its_feature_with_measured_against_wanted(self):
        st = self.st
        s = canon.lift(FLANGE)["source"].replace(
            "from form.recipes.base", "from form import contract\nfrom form.recipes.base").replace(
            "@feature('Bolt holes', role='interface')",
            "@feature('Bolt holes', role='interface', expects=[contract.bolt_circle(4, 5.2, 60), contract.holes(1, 20)])")
        with self.assertRaises(StudioError) as cm:
            st.create_design("Expecting", s)
        e = cm.exception
        self.assertEqual(e.extra.get("feature"), "holes")
        self.assertIn("does not meet what it promises", str(e))
        self.assertIn("measured 0 hole(s) Ø5.2", str(e))
        self.assertNotIn("1 hole(s) Ø20", str(e))                      # the one it does meet is not listed
        p = st.create_design("Expecting", s, partial=True)             # kept: the features before it built
        part = st.rev(p)["partial"]
        self.assertEqual((part["failed"], part["built"]), ("holes", ["disc", "bore", "edges"]))
        r = edits.edit(st, p, [{"op": "set_param", "param": "hole_d", "default": 5.2}], expect_head=1)
        self.assertNotIn("partial", r)
        self.assertEqual([(x["feature"], x["status"]) for x in r["changed"]], [("holes", "built"), ("edges", "built")])
        sheet = contract.prove(st, r["project"])
        self.assertEqual([(x["source"], x["status"], x["feature"]) for x in sheet["rows"]],
                         [("expects", "PASS", "holes"), ("expects", "PASS", "holes")])

    def test_a_threaded_hole_has_a_thread_and_made_by_selects_what_a_cut_made(self):
        out = self.st.kernel.call("candidate", timeout=120, key="thread-probe", recipe_id=self.st._load_design(THREADED),
                                  values={}, tol=0.1, sweep=False)
        self.assertTrue(out.get("ok", True), out)
        p = self.st.create_design("Threaded", THREADED)
        from form import staged
        staged.attach(self.st, p["id"], brief={"id": "b-00000000", "contract": contract.compile_brief(
            {"goal": "a block with an M10 thread"})})
        sheet = contract.prove(self.st, self.st.load(p["id"]))
        row = sheet["rows"][0]
        self.assertEqual((row["kind"], row["status"], row["evidence"]), ("thread", "PASS", "heuristic"))
        plain = self.st.create_design("Plain bore", THREADED.replace("parts.thread(10, 1.5, 12, external=False).shape",
                                                                     "Pos(0, 0, -12) * Cylinder(5, 12, align=A)"))
        staged.attach(self.st, plain["id"], brief={"id": "b-00000001", "contract": contract.compile_brief(
            {"goal": "a block with an M10 thread"})})
        row = contract.prove(self.st, self.st.load(plain["id"]))["rows"][0]
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("plain bore", row["why"])


THREADED = '''from build123d import Align, Box, Cylinder, Pos
from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Threaded block"
    summary = "A block with a threaded hole."
    params = [Param("s", "Size", 30, 20, 60, 1, "mm", "form", "block")]
    features = [Feature("block", "Block", "structure"), Feature("thread", "Thread", "interface")]

    def build(self, v):
        body = Box(v["s"], v["s"], 14, align=(Align.CENTER, Align.CENTER, Align.MAX))
        st = [Stage("block", body)]
        out = body - parts.thread(10, 1.5, 12, external=False).shape
        new = craft.made_by(out, body, "faces")
        if not 0 < len(new) < len(out.faces()):
            raise RecipeError(f"made_by found {len(new)} new faces of {len(out.faces())}", "thread")
        st.append(Stage("thread", out))
        return st
'''


class OverMcp(unittest.TestCase):
    def test_the_demo_goes_red_then_green_and_the_last_feature_edit_builds_only_it(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "demo.json"
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "proof_demo.py"), "--json", str(out)],
                               capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONPATH": str(ROOT)})
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])
            got = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("1.40 mm", got["audit_trap"]["ask"])
        self.assertEqual(got["red_rows_first"], 1)
        self.assertFalse(got["first"]["green"])
        self.assertTrue(got["repaired"]["green"])
        self.assertEqual(got["repair_edit"]["canonical"]["mode"], "features")
        self.assertEqual([(x["feature"], x["status"]) for x in got["repair_edit"]["changed"]],
                         [("holes", "built"), ("edges", "built")])
        self.assertEqual(got["repair_edit"]["reused"], 2)
        last = got["last_feature_edit"]
        self.assertEqual(([x["feature"] for x in last["changed"]], last["reused"]), (["edges"], 3))
        steps = {s["tool"]: s for s in got["steps"] if not s["error"]}
        self.assertLess(steps["edit_design"]["input_chars"], 0.1 * steps["create_design"]["input_chars"])
        self.assertTrue(next(s for s in got["steps"] if s["tool"] == "create_design")["error"])   # the trap brief

    def test_tools_refuse_before_the_kernel_and_read_one_feature(self):
        asyncio.run(self._tools())

    async def _tools(self):
        from mcp import Client, StdioServerParameters

        def text(res):
            return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"],
                                           env=env, cwd=str(ROOT))
            async with Client(params) as c:
                bad = WINDING.replace("Box(w, w, t, align=A)", "Box(w, w, t, aling=A)")
                r = await c.call_tool("create_design", {"name": "Plate", "source": bad, "run": False})
                self.assertTrue(r.is_error)
                self.assertIn("Preflight found 2 problem(s) before building (no kernel time used)", text(r))
                self.assertIn("[api, line", text(r))
                self.assertIn("[winding, line", text(r))
                self.assertFalse(any(Path(d).glob("*/project.json")))          # nothing was made
                r = await c.call_tool("create_design", {"name": "Plate", "source": PLAIN, "run": False, "refine": "off"})
                self.assertFalse(r.is_error, text(r))
                pid = json.loads(next(x.text for x in r.content if getattr(x, "type", "") == "text"))["project"]
                src = json.loads(text(await c.call_tool("get_design_source", {"project": pid})))
                self.assertEqual((src["form"], src["features"]), ("features", ["plate", "post", "holes"]))
                self.assertIn("def holes(self, v, body):", src["source"])
                one = json.loads(text(await c.call_tool("get_design_source", {"project": pid, "feature": "post"})))
                self.assertTrue(one["source"].startswith("@feature('Post'"))
                self.assertNotIn("def holes", one["source"])
                self.assertEqual(one["reads"], {"post_d": 12.0, "t": 6.0, "w": 60.0})
                raw = json.loads(text(await c.call_tool("get_design_source", {"project": pid, "canonical": False})))
                self.assertEqual(raw["source"], PLAIN)
                r = await c.call_tool("edit_design", {"project": pid, "expect_head": 1, "look": False, "run": False, "ops": [
                    {"op": "replace", "feature": "nope", "code": "def nope(self, v, body):\n    return body"},
                    {"op": "set_param", "param": "missing", "value": 1}]})
                self.assertTrue(r.is_error)
                self.assertIn("2 of 2 op(s) cannot be applied", text(r))
                r = await c.call_tool("edit_design", {"project": pid, "expect_head": 1, "look": False, "run": False, "ops": [
                    {"op": "replace", "find": "post(v[\"post_d\"] / 2, 10)", "with": "post(v[\"post_d\"] / 2, 14)"}]})
                self.assertFalse(r.is_error, text(r))
                e = json.loads(text(r))
                self.assertEqual(([x["feature"] for x in e["changed"]], e["reused"], e["head"]), (["post", "holes"], 1, 2))
                self.assertEqual(e["edit"]["features"]["changed"], ["post"])
                self.assertNotIn("source", e)                                  # the file does not come back


class Threads(unittest.TestCase):
    def test_every_internal_thread_cutter_leaves_a_thread_in_one_solid(self):
        code = ("import sys, json; sys.path.insert(0, %r)\nfrom build123d import Align, Box\nfrom form import parts\n"
                "out = {}\n"
                "for name, fn in (('iso', lambda: parts.thread(10.5, 2, 12, external=False)),\n"
                "                 ('iso_fine', lambda: parts.thread(8, 1.25, 10, external=False)),\n"
                "                 ('trapezoid', lambda: parts.trapezoidal_thread(10, 2, 12, external=False)),\n"
                "                 ('lead_screw', lambda: parts.trapezoidal_thread(8, 2, 10, starts=4, external=False)),\n"
                "                 ('bottle', lambda: parts.bottle_thread(external=False))):\n"
                "    s = fn().shape\n    bb = s.bounding_box()\n"
                "    blk = Box(80, 80, -bb.min.Z + 2, align=(Align.CENTER, Align.CENTER, Align.MAX)) - s\n"
                "    out[name] = [len(blk.solids()), sum(1 for f in blk.faces() if f.geom_type.name == 'BSPLINE'), bool(blk.is_valid)]\n"
                "print(json.dumps(out))\n" % str(ROOT))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        got = json.loads(r.stdout.strip().splitlines()[-1])
        for name, (solids, helical, valid) in got.items():
            self.assertEqual((solids, valid), (1, True), name)
            self.assertGreater(helical, 10, name)            # a plain bore has none: that was the defect


if __name__ == "__main__":
    unittest.main()
