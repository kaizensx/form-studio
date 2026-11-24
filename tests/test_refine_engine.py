"""The design refinement engine (form/refine): the deficit vector is deterministic, a candidate that fails a gate is
never kept, the ledger reorders operators, and the kept steps land in the source as role="refine" features that undo
cleanly. The search runs on stub operators and a stub evaluator (no kernel); the analysis runs on plain meshes."""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")
TMP = tempfile.mkdtemp(prefix="form-refine-")
os.environ["FORM_DATA"] = TMP

from form import refine  # noqa: E402
from form.featureprog import delete_feature  # noqa: E402
from form.refine import DEFICITS, Analysis, Design, Operator, Patch, analyze, engine, ledger, styles  # noqa: E402

SOURCE = '''
from build123d import Box, Cylinder
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title, summary = "Block", "A block with a bore."
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 30, 10)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(4, 20)
'''

BASE = {"silhouette": 0.8, "edge_hierarchy": 0.9, "surface_breaks": 0.6, "material_zones": 1.0, "touch_points": 0.5}
FROZEN = {"bore": {"area": 250.0, "faces": 1, "lo": [-4, -4, -5], "hi": [4, 4, 5]}}
CHECKS = [{"id": "solid", "label": "One valid solid", "status": "PASS"},
          {"id": "interfaces", "label": "Interfaces as modelled", "status": "PASS"}]


def box(sx=60, sy=40, sz=20, n=4, off=(0, 0, 0)):
    """A closed box mesh, n x n quads per face, outward winding."""
    P, T = [], []

    def face(o, u, v):
        base = len(P)
        for i in range(n + 1):
            for j in range(n + 1):
                P.append(o + u * i / n + v * j / n)
        for i in range(n):
            for j in range(n):
                a = base + i * (n + 1) + j
                T.append([a, a + n + 1, a + n + 2])
                T.append([a, a + n + 2, a + 1])
    x, y, z = np.eye(3)
    o = np.array(off, float) - np.array([sx, sy, sz]) / 2
    face(o, y * sy, x * sx)
    face(o + z * sz, x * sx, y * sy)
    face(o, x * sx, z * sz)
    face(o + y * sy, z * sz, x * sx)
    face(o, z * sz, y * sy)
    face(o + x * sx, y * sy, z * sz)
    return np.array(P, float), np.array(T, np.int64)


# ---- stubs: an operator writes its effect into the code; the evaluator reads it back ------------------------------

class StubOp(Operator):
    def __init__(self, name, targets, effect, cost=0.5, breaks=None):
        self.name, self.targets, self.effect, self.cost, self.breaks = name, tuple(targets), effect, cost, breaks
        self.label, self.domain, self.params = name.replace("_", " ").capitalize(), "cad", {"k": 1}

    def apply(self, design, analysis, params):
        tags = " ".join(f"{k}={v}" for k, v in sorted(self.effect.items()))
        brk = f"\n    # breaks: {self.breaks}" if self.breaks else ""
        return Patch(code=f"def whatever(self, v, body):\n    # effect: {tags}{brk}\n    return body\n",
                     reason=f"Stub {self.name}.")


class StubEvaluator(engine.Evaluator):
    def __init__(self, purpose="model"):
        self.purpose, self.calls, self.batches, self.sources = purpose, 0, [], []

    def evaluate(self, sources, timeout=None):
        self.batches.append(len(sources))
        self.sources += list(sources)
        out = []
        for s in sources:
            self.calls += 1
            d = dict(BASE)
            for m in re.finditer(r"# effect: (.*)", s):
                for kv in m.group(1).split():
                    k, v = kv.split("=")
                    d[k] = max(0.0, round(d[k] - float(v), 4))
            frozen = {k: dict(v) for k, v in FROZEN.items()}
            checks = [dict(c) for c in CHECKS]
            wall = 2.0
            for m in re.finditer(r"# breaks: (\w+)", s):
                if m.group(1) == "frozen":
                    frozen["bore"]["area"] = 240.0
                elif m.group(1) == "checks":
                    checks[1]["status"] = "FAIL"
                elif m.group(1) == "wall":
                    wall = 0.3
                elif m.group(1) == "build":
                    out.append(engine.Evaluation(ok=False, error="stub build failure"))
                    break
            else:
                tot = round(sum(d.values()) / len(d), 4)
                out.append(engine.Evaluation(ok=True, analysis=Analysis(deficits=d, total=tot), checks=checks,
                                             frozen=frozen, wall_mm=wall))
        return out


def design(**kw):
    return Design.from_source(SOURCE, purpose="model", style="clean_consumer", **kw)


class TestOperatorAPI(unittest.TestCase):
    def test_parse_features_and_frozen(self):
        d = design()
        self.assertEqual(d.feature_ids, ["body", "bore"])
        self.assertEqual(d.frozen, {"bore"})
        self.assertEqual(d.refined, [])

    def test_keep_clear_drops_items_in_frozen_boxes(self):
        class E:
            def __init__(self, x):
                self.x = x

            def center(self):
                return type("V", (), {"X": self.x, "Y": 0.0, "Z": 0.0})()
        items = [E(0.0), E(3.0), E(10.0)]
        kept = refine.keep_clear(items, [((-1, -1, -1), (1, 1, 1))], margin=0.5)
        self.assertEqual([e.x for e in kept], [3.0, 10.0])

    def test_example_operator_makes_one_valid_method(self):
        op = refine.ExampleEdgeBreak()
        a = Analysis(deficits={"edge_hierarchy": 0.9}, total=0.9)
        self.assertTrue(op.check(design(), a)[0])
        self.assertFalse(op.check(design(), Analysis(deficits={"edge_hierarchy": 0.1}, total=0.1))[0])
        patch = op.apply(design(), a, op.params)
        compile(patch.code, "patch", "exec")
        self.assertIn("keep_clear", patch.code)

    def test_register_and_operators(self):
        op = StubOp("stub_registered", ["silhouette"], {"silhouette": 0.1})
        refine.register(op)
        try:
            self.assertIn("stub_registered", [o.name for o in refine.operators("cad")])
        finally:
            refine.unregister("stub_registered")
        self.assertNotIn("stub_registered", [o.name for o in refine.operators()])


class TestAnalysis(unittest.TestCase):
    def test_deficit_vector_is_deterministic_and_bounded(self):
        P, T = box()
        a1 = analyze.analyze(analyze.Measurement(P, T))
        a2 = analyze.analyze(analyze.Measurement(P.copy(), T.copy()))
        self.assertEqual(a1.deficits, a2.deficits)
        self.assertEqual(a1.total, a2.total)
        self.assertTrue(set(a1.deficits) <= set(DEFICITS))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in a1.deficits.values()))
        self.assertNotIn("wear", a1.deficits)                    # wear is a game measure

    def test_a_box_reads_as_a_blob_and_an_l_does_not(self):
        P, T = box()
        P2, T2 = box(20, 40, 40, off=(20, 0, 20))
        blob = analyze.analyze(analyze.Measurement(P, T))
        ell = analyze.analyze(analyze.Measurement(np.r_[P, P2], np.r_[T, T2 + len(P)]))
        self.assertGreater(blob.deficits["silhouette"], 0.5)
        self.assertLess(ell.deficits["silhouette"], blob.deficits["silhouette"])
        self.assertEqual(blob.deficits["edge_hierarchy"], 1.0)    # no radii and every crease sharp
        self.assertEqual(blob.deficits["material_zones"], 1.0)

    def test_zones_and_metrics_lower_their_deficits(self):
        P, T = box()
        zones = [{"features": ["body"], "color": "#202020"}, {"features": ["bore"], "color": "#e0e0e0"},
                 {"features": ["grip"], "color": "#c04020", "finish": "matte"}]
        metrics = {"radius_tiers": 3, "sharp_edge_fraction": 0.1, "fillet_radii": [0.4, 1.5, 5.0],
                   "features": {"body": {"lo": [-30, -20, -10], "hi": [30, 20, 10]},
                                "boss": {"lo": [0, 0, 0], "hi": [8, 8, 4]}}}
        a = analyze.analyze(analyze.Measurement(P, T, metrics=metrics, zones=zones))
        self.assertEqual(a.deficits["material_zones"], 0.0)
        self.assertEqual(a.deficits["material_contrast"], 0.0)
        self.assertEqual(a.deficits["edge_hierarchy"], 0.0)
        self.assertEqual(a.deficits["detail_scales"], 0.0)

    def test_game_wear_band(self):
        P, T = box()
        g = {"wear": {"edge_mask_share": 0.05}, "edges": {"coverage": 0.8}, "scales": {"count": 3},
             "materials": {"count": 3}, "value_contrast": 0.3}
        a = analyze.analyze(analyze.Measurement(P, T, game=g, purpose="game"))
        self.assertEqual(a.deficits["wear"], 0.0)
        g["wear"] = {"edge_mask_share": 0.002}
        self.assertGreater(analyze.analyze(analyze.Measurement(P, T, game=g, purpose="game")).deficits["wear"], 0.8)


class TestGates(unittest.TestCase):
    def ev(self, **kw):
        base = dict(ok=True, analysis=Analysis(deficits={}, total=0.5), checks=[dict(c) for c in CHECKS],
                    frozen={k: dict(v) for k, v in FROZEN.items()}, wall_mm=2.0)
        base.update(kw)
        return engine.Evaluation(**base)

    def test_each_gate(self):
        b = self.ev()
        self.assertEqual(engine.gate(b, self.ev()), [])
        self.assertTrue(engine.gate(b, self.ev(ok=False, error="x"))[0].startswith("build"))
        bad = [dict(c) for c in CHECKS]
        bad[0]["status"] = "WARN"
        self.assertTrue(engine.gate(b, self.ev(checks=bad))[0].startswith("checks"))
        moved = {"bore": dict(FROZEN["bore"], hi=[4, 4, 5.2])}
        self.assertTrue(engine.gate(b, self.ev(frozen=moved))[0].startswith("frozen"))
        self.assertTrue(engine.gate(b, self.ev(wall_mm=0.6), "print")[0].startswith("wall"))
        self.assertTrue(engine.gate(b, self.ev(wall_mm=1.5))[0].startswith("wall"))      # under 80 % of the base
        self.assertEqual(engine.gate(b, self.ev(wall_mm=1.7)), [])
        self.assertTrue(engine.gate(b, self.ev(triangles=12000), "game", [10000])[0].startswith("game"))
        self.assertTrue(engine.gate(b, self.ev(game={"ok": False, "checks": [{"label": "LOD0 manifold",
                                                                               "status": "FAIL"}]}), "game"))


class TestSearch(unittest.TestCase):
    def test_keeps_good_steps_as_refine_features(self):
        ops = [StubOp("fillet_hierarchy", ["edge_hierarchy"], {"edge_hierarchy": 0.6}),
               StubOp("parting_line", ["surface_breaks"], {"surface_breaks": 0.4})]
        ev = StubEvaluator()
        r = engine.search(design(), ev, ops=ops, ledger=ledger.Ledger.memory(), budget_s=60)
        self.assertTrue(r["changed"])
        # candidates carry a feature alarm from the time left; the committed source keeps the default budget
        self.assertTrue(all("budget=" in s for s in ev.sources[1:]))
        self.assertNotIn("budget=", r["source"])
        self.assertEqual({a["operator"] for a in r["applied"]}, {"fillet_hierarchy", "parting_line"})
        feats = refine.parse_features(r["source"])
        refined = [k for k, f in feats.items() if f["role"] == "refine"]
        self.assertEqual(sorted(refined), ["refine_fillet_hierarchy", "refine_parting_line"])
        self.assertIn("deficit", feats["refine_fillet_hierarchy"]["doc"])              # reason + measured delta
        self.assertLess(r["final"]["total"], r["base"]["total"])
        src = r["source"]
        for fid in refined:                                                           # undo is delete_feature
            src = delete_feature(src, fid)
        self.assertEqual(refine.parse_features(src), refine.parse_features(SOURCE))

    def test_gate_failing_candidate_is_never_kept(self):
        for breaks in ("frozen", "checks", "wall", "build"):
            ops = [StubOp("too_good", ["silhouette"], {"silhouette": 0.8, "edge_hierarchy": 0.9}, breaks=breaks),
                   StubOp("modest", ["edge_hierarchy"], {"edge_hierarchy": 0.3})]
            r = engine.search(design(), StubEvaluator(), ops=ops, ledger=ledger.Ledger.memory(), budget_s=60)
            self.assertNotIn("too_good", [a["operator"] for a in r["applied"]], breaks)
            self.assertNotIn("breaks:", r["source"], breaks)
            self.assertIn("too_good", [x["operator"] for x in r["rejected"]], breaks)
            self.assertEqual([a["operator"] for a in r["applied"]], ["modest"], breaks)

    def test_operator_dropped_after_two_gate_failures(self):
        ops = [StubOp("bad", ["silhouette"], {"silhouette": 0.5}, breaks="frozen")]
        ev = StubEvaluator()
        r = engine.search(design(), ev, ops=ops, ledger=ledger.Ledger.memory(), budget_s=60)
        self.assertFalse(r["changed"])
        self.assertLessEqual(r["strikes"]["bad"], engine.GATE_STRIKES)

    def test_ledger_reorders_operators(self):
        a = StubOp("op_a", ["silhouette"], {"silhouette": 0.3})
        b = StubOp("op_b", ["silhouette"], {"silhouette": 0.3})
        first = engine.search(design(), StubEvaluator(), ops=[a, b], ledger=ledger.Ledger.memory(), budget_s=60,
                              per_round=1, depth=1)
        self.assertEqual(first["rounds"][0]["candidates"][0]["operator"], "op_a")      # tie: by name
        led = ledger.Ledger.memory()
        for _ in range(6):
            led.record(None, "clean_consumer", "op_a", accepted=False)
            led.record(None, "clean_consumer", "op_b", accepted=True, gain=0.08)
        self.assertGreater(led.prior(None, "clean_consumer", "op_b"), 1.0)
        self.assertLess(led.prior(None, "clean_consumer", "op_a"), 1.0)
        second = engine.search(design(), StubEvaluator(), ops=[a, b], ledger=led, budget_s=60, per_round=1, depth=1)
        self.assertEqual(second["rounds"][0]["candidates"][0]["operator"], "op_b")

    def test_stops_when_gain_is_under_two_percent(self):
        ops = [StubOp("tiny", ["silhouette"], {"silhouette": 0.01})]
        r = engine.search(design(), StubEvaluator(), ops=ops, ledger=ledger.Ledger.memory(), budget_s=60)
        self.assertFalse(r["changed"])
        self.assertEqual(r["stopped"], "no step gains 2 %")

    def test_budget_stops_the_search(self):
        t = [0.0]

        def clock():
            t[0] += 7.0
            return t[0]
        ops = [StubOp(f"op_{i}", ["silhouette"], {"silhouette": 0.2}) for i in range(4)]
        r = engine.search(design(), StubEvaluator(), ops=ops, ledger=ledger.Ledger.memory(), budget_s=20,
                          clock=clock)
        self.assertEqual(r["stopped"], "time budget spent")
        self.assertLess(len(r["rounds"]), engine.DEPTH)

    def test_beam_limits(self):
        ops = [StubOp(f"op_{i}", ["silhouette"], {"silhouette": 0.2}) for i in range(10)]
        ev = StubEvaluator()
        r = engine.search(design(), ev, ops=ops, ledger=ledger.Ledger.memory(), budget_s=600)
        self.assertLessEqual(max(ev.batches[1:]), engine.PER_ROUND)                     # [0] is the base
        self.assertLessEqual(len(r["rounds"]), engine.DEPTH)
        self.assertLessEqual(len(r["applied"]), engine.DEPTH)
        self.assertGreaterEqual(len(r["rounds"]), 2)


class TestOptOutsStylesLedger(unittest.TestCase):
    def test_opt_outs(self):
        self.assertTrue(engine.enabled({}, SOURCE)[0])
        self.assertFalse(engine.enabled({}, SOURCE, "off")[0])
        self.assertFalse(engine.enabled({"refine": {"enabled": False}}, SOURCE)[0])
        off = SOURCE.replace('    title, summary', '    refine = False\n    title, summary')
        self.assertFalse(engine.enabled({}, off)[0])
        self.assertFalse(engine.enabled({}, "x = 1\n")[0])

    def test_style_detection(self):
        self.assertEqual(styles.detect("a rugged field tool with a knurled grip"), "rugged_tool")
        self.assertEqual(styles.detect("sci-fi drone armour panel"), "scifi_hard_surface")
        self.assertEqual(styles.detect("a fantasy treasure chest"), "stylised_fantasy")
        self.assertEqual(styles.detect("a soft organic pebble vase"), "organic")
        self.assertEqual(styles.detect("a thing"), "clean_consumer")
        self.assertEqual(styles.detect("", "helmet_fullface"), "scifi_hard_surface")
        self.assertEqual(styles.params("rugged_tool", refine.ExampleEdgeBreak())["r"], 0.3)

    def test_ledger_file_is_local_and_resets(self):
        led = ledger.Ledger.open()
        self.assertEqual(led.path, Path(TMP) / ledger.FILE)
        led.record("mouse", "clean_consumer", "parting_line", accepted=True, gain=0.05)
        led.save()
        again = ledger.Ledger.open()
        self.assertEqual(again.row("mouse", "clean_consumer", "parting_line")["accepts"], 1)
        self.assertEqual(again.prior("bottle", "clean_consumer", "parting_line"),
                         again.prior("mouse", "clean_consumer", "parting_line"))   # falls back over classes
        ledger.reset()
        self.assertFalse((Path(TMP) / ledger.FILE).exists())
        self.assertEqual(ledger.Ledger.open().rows, {})


if __name__ == "__main__":
    unittest.main()
