"""Make it lighter (form/lighten.py) on the real kernel and checks, print-setting overrides over the process preset,
and the Replace a broken part brief (form/replace.py)."""
import asyncio
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-lighter-")

from form import config, lighten, replace  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402


class Knobs(unittest.TestCase):
    def test_ladder_moves_toward_the_lighter_end(self):
        ks = [{"key": "wall", "label": "Wall", "unit": "mm", "from": 2.4, "to": 1.6, "step": 0.1},
              {"key": "pocket_d", "label": "Pocket", "unit": "mm", "from": 4, "to": 12, "step": 1}]
        pts = lighten.ladder(ks)
        self.assertIn({"wall": 1.6}, pts)
        self.assertIn({"pocket_d": 12}, pts)
        self.assertIn({"wall": 2.0, "pocket_d": 8}, pts)
        self.assertTrue(all(1.6 <= p.get("wall", 2) <= 2.4 for p in pts))
        self.assertEqual(len(pts), len({tuple(sorted(p.items())) for p in pts}))


class Overrides(unittest.TestCase):
    def test_infill_and_walls_rewrite_the_process_preset(self):
        st = Studio.__new__(Studio)
        s = {"available": True, "summary": {"infill": "15%", "walls": "2"},
             "presets": {"process": {"name": "0.20mm", "sha": "abc", "data": {"sparse_infill_density": "15%", "wall_loops": "2"}}}}
        out = st._with_print_overrides(s, {"print_overrides": {"infill": 8, "walls": 3}})
        d = out["presets"]["process"]["data"]
        self.assertEqual((d["sparse_infill_density"], d["wall_loops"]), ("8%", "3"))
        self.assertNotEqual(out["presets"]["process"]["sha"], "abc")
        self.assertEqual(s["presets"]["process"]["data"]["sparse_infill_density"], "15%", "the cached preset is untouched")
        self.assertIs(st._with_print_overrides(s, {}), s)


class OnTheKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.pid = cls.st.create("Drawer box", "storage_box")["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_1_search_keeps_every_passing_check(self):
        r = lighten.search(self.st, self.st.load(self.pid), builds=3)
        self.assertIn("wall", [k["key"] for k in r["knobs"]])
        self.assertGreater(r["built"], 4)
        geo = [c for c in r["candidates"] if c["kind"] == "geometry"]
        self.assertTrue(geo, r["rejected"])
        passed = {c["id"] for c in r["baseline"]["checks"] if c["status"] == "PASS"}
        for c in r["candidates"]:
            self.assertLess(c["mass_g"], r["baseline"]["mass_g"] + 1e-9)
            self.assertTrue(all(x["after"] == "PASS" for x in c["checks"] if x["id"] in passed))
        # the volume comes from the real solid: building the candidate again gives the same number
        c = geo[0]
        again = lighten.build(self.st, self.st.load(self.pid), c["changes"])
        self.assertEqual(again["volume_cm3"], c["volume_cm3"])
        self.assertEqual(lighten.cached(self.st, self.st.load(self.pid))["candidates"][0]["id"], r["candidates"][0]["id"])
        type(self).cand = c

    def test_2_apply_is_a_new_revision_with_current_checks(self):
        p = self.st.load(self.pid)
        out = lighten.apply(self.st, p, self.cand, p["head"])
        p = self.st.load(self.pid)
        self.assertEqual(out["head"], p["head"])
        head = self.st.rev(p)
        for k, v in self.cand["changes"].items():
            self.assertAlmostEqual(head["values"][k], v)
        job = self.st.run_sync(self.pid)
        steps = {s["node"]: s["state"] for s in job["steps"]}
        self.assertEqual([steps[n] for n in ("geometry", "exports", "checks")], ["cached"] * 3, "built during the search, under the same keys")
        self.assertEqual(self.st.status(self.st.load(self.pid))["checks"]["state"], "current")

    def test_3_settings_validate(self):
        p = self.st.load(self.pid)
        with self.assertRaises(StudioError):
            self.st.settings(p, {"print_overrides": {"infill": 140}})
        with self.assertRaises(StudioError):
            self.st.settings(p, {"print_overrides": {"speed": 1}})
        self.st.settings(p, {"print_overrides": {"infill": 10}})
        self.assertEqual(self.st.load(self.pid)["print_overrides"], {"infill": 10.0})
        self.st.settings(self.st.load(self.pid), {"print_overrides": {}})
        self.assertNotIn("print_overrides", self.st.load(self.pid))


class Replace(unittest.TestCase):
    def test_brief_asks_for_scale_measurements_then_design(self):
        m = replace.brief("Shelf clip", "holds a shelf on a 5 mm pin", "card", broke="the hook snapped")
        self.assertTrue(m.startswith("Replace a broken part: Shelf clip."))
        self.assertIn("85.60 × 53.98 mm", m)
        i, j, k = m.index("1. Estimate"), m.index("ask_measurement"), m.index("create_design")
        self.assertLess(i, j)
        self.assertLess(j, k)
        self.assertIn("Purpose: for 3D printing.", m)
        self.assertIn("no scale", replace.brief("X", reference="none"))
        self.assertIn("1 euro", replace.brief("X", reference="coin", coin="1 euro"))
        with self.assertRaises(StudioError):
            replace.brief("X", reference="banana")

    def test_mcp_tools_are_listed(self):
        from form.mcp_server import build
        names = {t.name for t in asyncio.run(build().list_tools())}
        self.assertTrue({"make_lighter", "apply_lighter", "replace_part_guide"} <= names)
