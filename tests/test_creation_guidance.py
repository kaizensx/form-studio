"""Guidance, routing and the creation bench (WP4): design_brief's route, plan_design's helper check and executable
steps, multi-part plans that must declare parts, clearances and magnet stock, exemplars as decomposed steps and
routed search, the guide's skeleton-first lead (its FeatureDesign example builds), feature-level candidates on a
shared upstream checkpoint, and the scripted agent's bench on two briefs."""
import json
import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-guidance-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import config, design_guide, exemplars, featureprog, staged  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAILING_QUERY = "full-face helmet separate parts magnets lens texture"


class Route(unittest.TestCase):
    def test_routes(self):
        cases = {"An original full-face hero helmet with a magnetic faceplate and two lenses": "skin+features",
                 "A 5:1 planetary gearbox stage": "mechanism", "A vase with spiral ribs": "revolve",
                 "A knurled knob for a 6 mm D-shaft with a pointer": "revolve",
                 "A 35 mm DIN-rail clip": "prismatic", "A pillow block for a 608 bearing": "prismatic",
                 "A cable drag-chain link": "mechanism", "A creature horn": "skin+features"}
        for text, want in cases.items():
            with self.subTest(text):
                r = staged.route(text)
                self.assertEqual(r["route"], want)
                self.assertEqual(r["evidence"], "heuristic")
        self.assertTrue(staged.route("a two-part organizer held by 8x3 magnets")["multi_part"])
        self.assertFalse(staged.route("a spacer, 20 mm")["multi_part"])

    def test_skeleton_advice_names_only_real_helpers(self):
        for r, text in staged.SKELETON.items():
            self.assertEqual(staged.check_how(text)["unknown"], [], r)


class PlanCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_fake_helper_refused_with_closest_names(self):
        c = staged.check_how("craft.loft_sections, then craft.magnet_pocket and craft.fusee; parts.magnet_pocket")
        self.assertEqual(c["helpers"], ["craft.loft_sections", "parts.magnet_pocket"])
        bad = {u["name"]: u["closest"] for u in c["unknown"]}
        self.assertIn("craft.organic.magnet_pocket", bad["craft.magnet_pocket"])
        self.assertIn("craft.fuse", bad["craft.fusee"])
        b = staged.save_brief(self.st, "Knob", "A knurled knob for a 6 mm D-shaft")
        feats = [{"id": "skirt", "label": "Skirt", "how": "craft.revolve_profile"},
                 {"id": "grip", "label": "Grip", "how": "craft.knurl_magic diamond"},
                 {"id": "bore", "label": "Bore", "how": "D bore"}]
        with self.assertRaises(StudioError) as cm:
            staged.save_plan(self.st, b["id"], feats, risks=["knurl too fine"])
        self.assertIn("craft.knurl_magic", str(cm.exception))
        self.assertIn("craft.knurl", cm.exception.hint + str(cm.exception))

    def test_steps_ordered_with_risk_and_fallback(self):
        b = staged.save_brief(self.st, "Knob", "A knurled knob for a 6 mm D-shaft")
        feats = [{"id": "skirt", "label": "Skirt", "how": "craft.revolve_profile of the side outline"},
                 {"id": "grip", "label": "Grip", "how": "craft.knurl diamond"},
                 {"id": "bore", "label": "Bore", "how": "a D bore cut with Box and Cylinder"}]
        r = staged.save_plan(self.st, b["id"], feats, risks=["knurl too fine"])
        s = r["plan"]["steps"]
        self.assertEqual([x["id"] for x in s], ["skirt", "grip", "bore"])
        self.assertEqual(s[0]["call"]["tool"], "create_design")
        self.assertEqual(s[1]["call"]["tool"], "add_feature")
        self.assertEqual(s[1]["risk"], "high")
        self.assertEqual(s[1]["call"]["alternative"]["tool"], "build_candidates")
        self.assertIn("craft.MeshTexture", s[1]["fallback"])
        self.assertEqual(s[2]["risk"], "low")
        self.assertTrue(all(x["retries"] == 2 for x in s))
        self.assertEqual(r["plan"]["route"], "revolve")
        for x in s:                                            # every fallback that names a helper names a real one
            for f in x["fallback"]:
                if f.startswith("craft."):
                    self.assertEqual(staged.check_how(f)["unknown"], [], f)

    def test_multi_part_must_declare_parts_clearances_magnets(self):
        b = staged.save_brief(self.st, "Hero helmet", "An original full-face helmet with separate parts: a shell, a "
                              "magnetic faceplate and two lenses, with a hex texture.")
        feats = [{"id": "shell", "label": "Shell", "how": "craft.checked_body through sections"},
                 {"id": "eye_port", "label": "Eye port", "how": "craft.two_view_cutter"},
                 {"id": "faceplate", "label": "Faceplate", "how": "a separate solid", "part": "faceplate"},
                 {"id": "magnets", "label": "Magnet pockets", "how": "parts.magnet_pocket pairs"}]
        with self.assertRaises(StudioError) as cm:
            staged.save_plan(self.st, b["id"], feats, risks=["band on the skin"])
        msg = str(cm.exception)
        self.assertIn("parts", msg)
        self.assertIn("clearances", msg)
        self.assertIn("magnet stock", msg)
        parts = [{"id": "shell", "label": "Shell"}, {"id": "faceplate", "label": "Faceplate"}]
        with self.assertRaises(StudioError):
            staged.save_plan(self.st, b["id"], feats, parts=parts, clearances={"faceplate/shell": 0.3},
                             magnets=[{"stock": "7x7", "count": 4}], risks=["x"])
        r = staged.save_plan(self.st, b["id"], feats, parts=parts, clearances={"faceplate/shell": 0.3},
                             magnets=[{"stock": "8x3", "count": 4, "retention": "press"}], risks=["band on the skin"])
        self.assertEqual(r["plan"]["route"], "skin+features")
        self.assertEqual(r["plan"]["clearances"], {"faceplate/shell": 0.3})


class Exemplars(unittest.TestCase):
    def test_decomposed_steps(self):
        s = exemplars.steps("helmet")
        self.assertGreaterEqual(len(s), 4)
        self.assertEqual(s[0]["id"], "shell")
        self.assertIn("craft.checked_body", s[0]["craft"])
        hit = exemplars.search("knurled knob")[0]
        self.assertTrue(hit["steps"])
        self.assertEqual(exemplars.get("knurled_knob")["steps"][0]["id"], "skirt")

    def test_routing_puts_the_preferred_exemplar_first(self):
        cat = [{"name": "hero_helmet"}, {"name": "helmet"}]
        self.assertEqual(exemplars.routed(FAILING_QUERY, cat), ["hero_helmet"])
        self.assertEqual(exemplars.routed("full-face helmet with a carbon texture", cat), [])
        cat = [{"name": "x", "route": {"all": ["planter"], "any": ["hex"]}}]
        self.assertEqual(exemplars.routed("a hex planter", cat), ["x"])

    @unittest.skipUnless((ROOT / "form" / "exemplars" / "hero_helmet.py").is_file(), "hero_helmet.py not present yet (WP3)")
    def test_failing_query_returns_the_hero_helmet_first(self):
        self.assertEqual(exemplars.search(FAILING_QUERY)[0]["name"], "hero_helmet")


class GuideAndCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_guide_leads_with_skeleton_first(self):
        g = design_guide.topic("core")
        self.assertTrue(g["guide"].startswith("SKELETON FIRST"))
        for words in ("FeatureDesign", "add_feature", "2 times", "defer", "build_candidates", "render"):
            self.assertIn(words, g["guide"][:2600])
        self.assertTrue(featureprog.is_feature_design(g["example_source_features"]))

    def test_feature_example_builds_and_feature_candidates_share_upstream(self):
        from form import candidates
        st = self.st
        src = design_guide.FEATURE_EXAMPLE
        skeleton = featureprog.delete_feature(featureprog.delete_feature(featureprog.delete_feature(
            featureprog.delete_feature(src, "edges"), "slots"), "bore"), "arm")
        p = st.create_design("Bracket", skeleton, partial=True)
        self.assertNotIn("partial", st.rev(p))
        p = st.update_design(st.load(p["id"]), src)
        self.assertNotIn("partial", st.rev(p))
        log = {e["feature"]: e["status"] for e in st.rev(p)["build_log"]}
        self.assertEqual(log["plate"], "checkpoint")
        self.assertEqual(set(log.values()) - {"built", "checkpoint"}, set())
        good = 'def edges(self, v, body):\n    return craft.safe_fillet(body, body.edges().filter_by(Axis.Y), 1.0)\n'
        bad = 'def edges(self, v, body):\n    raise ValueError("BRep_API: command not done")\n'
        r = candidates.run(st, [{"label": "r1", "feature": "edges", "code": good},
                                {"label": "broken", "feature": "edges", "code": bad}],
                           project=p["id"], keep="none", sweep=False)
        rows = {x["label"]: x for x in r["ranking"]}
        self.assertTrue(rows["r1"]["ok"])
        self.assertFalse(rows["broken"]["ok"])
        self.assertEqual(r["best"], "r1")
        self.assertTrue({"plate", "arm", "bore", "slots"} <= set(r["upstream"]["shared"]), r["upstream"])
        st_log = {e["feature"]: e["status"] for e in rows["r1"]["build_log"]}
        self.assertEqual(st_log["edges"], "built")
        with self.assertRaises(StudioError):                  # feature candidates need a FeatureDesign base
            candidates.run(st, [{"label": "x", "feature": "edges", "code": good}], keep="none")


class Bench(unittest.TestCase):
    def test_scripted_agent_runs_two_briefs_and_writes_measured_json(self):
        import subprocess
        import sys
        out = Path(TMP) / "bench.json"
        env = {**os.environ, "FORM_KERNEL_WORKERS": "2", "PYTHONPATH": str(ROOT)}
        env.pop("FORM_DATA", None)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "creation_bench.py"), "--only",
                            "shaft_coupler,din_clip", "--json", str(out), "--no-score"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        res = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(res["briefs"]), 2)
        for b in res["briefs"]:
            self.assertTrue(b["project"], b)                   # no outcome without a project
            self.assertIsNotNone(b["first_visible_s"])
            self.assertGreaterEqual(b["features_built"], 1)
        self.assertIn("first_build_ok_pct", res["summary"])
        self.assertEqual(res["agent"], "scripted (deterministic stub, no model)")


if __name__ == "__main__":
    unittest.main()
