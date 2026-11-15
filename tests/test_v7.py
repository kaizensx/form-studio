"""v7: new recipes, goal seek, motion, setup wizard. Real kernel, temp data folder."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

TMP = tempfile.mkdtemp(prefix="form-v7-")
os.environ["FORM_DATA"] = TMP

from form import animate, config, optimize, setup  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402


class V7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_new_recipes_build_and_audit(self):
        for rid in ("gridfinity", "hook", "planter"):
            p = self.st.create(f"t {rid}", rid)
            s = self.st.head_summary(p)
            self.assertGreater(s["volume_mm3"], 1000, rid)
            for row in s["interface_audit"]:
                self.assertAlmostEqual(row["intended"], row["modelled"], places=2, msg=f"{rid} {row['key']}")
            self.assertEqual(p["fit"]["gap_min"], self.st.recipes[rid].fit["window"][0])   # window comes from the recipe

    def test_hook_constraint_names_feature(self):
        p = self.st.create("t hook c", "hook")
        with self.assertRaises(StudioError) as cm:
            self.st.preview(p, {"screw_spacing": 120})
        self.assertEqual(cm.exception.extra.get("feature"), "screws")

    def test_hook_impact_reports_safety_factor(self):
        p = self.st.create("t hook i", "hook")
        imp = self.st.preview(p, {"arm_t": 6})["impact"]
        keys = {m["key"] for m in imp["metrics"]}
        self.assertIn("safety_factor", keys)

    def test_optimizer_lighter_and_feasible(self):
        p = self.st.create("t hook o", "hook")
        r = optimize.run(self.st, p, [{"key": "arm_t", "min": 4, "max": 20}], {"minimize": "solid_mass_g"},
                         ["statics.safety_factor >= 3"], budget=16)
        self.assertIsNotNone(r["best"])
        self.assertGreaterEqual(r["best"]["statics.safety_factor"], 3)
        self.assertLess(r["best"]["solid_mass_g"], r["current"]["solid_mass_g"])
        with self.assertRaises(optimize.OptimizeError):
            optimize.run(self.st, p, [{"key": "arm_t"}], {"minimize": "nonsense"}, [], budget=8)

    def test_morph_gif(self):
        p = self.st.create("t planter m", "planter")
        a = self.st.rev(p)["values"]
        out = Path(TMP) / "m.gif"
        info = animate.morph(self.st, p, a, {**a, "twist": 120}, out, frames=4, size=(200, 150), hold=1)
        self.assertEqual(info["built_frames"], 4)
        self.assertGreater(Image.open(out).n_frames, 4)

    def test_setup_check_and_json_merge(self):
        items = {i.id: i for i in setup.check(self.st.cfg)}
        self.assertEqual(items["kernel"].status, "ok")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            f.write_text(json.dumps({"theme": "x", "mcpServers": {"other": {"command": "y"}}}))
            msg = setup._json_register(f)()
            data = json.loads(f.read_text())
            self.assertEqual(set(data["mcpServers"]), {"other", "form"})
            self.assertEqual(data["theme"], "x")
            self.assertIn("backup", msg)
            bad = Path(d) / "bad.json"
            bad.write_text("{ // comment\n}")
            with self.assertRaises(RuntimeError):
                setup._json_register(bad)()
            self.assertEqual(bad.read_text(), "{ // comment\n}")          # untouched


class AgentDetection(unittest.TestCase):
    def test_reads_config_not_health_check(self):
        with tempfile.TemporaryDirectory() as d:
            old = setup.HOME
            setup.HOME = Path(d)
            try:
                me = setup.mcp_command()
                self.assertEqual(setup._agent_item("a", "Claude Code", setup._claude_command(), me, "s", [], []).status, "missing")
                (Path(d) / ".claude.json").write_text(json.dumps({"mcpServers": {"form": {"command": me}}}))
                self.assertEqual(setup._agent_item("a", "Claude Code", setup._claude_command(), me, "s", [], []).status, "ok")
                (Path(d) / ".claude.json").write_text(json.dumps({"mcpServers": {"form": {"command": "/gone/form-mcp"}}}))
                it = setup._agent_item("a", "Claude Code", setup._claude_command(), me, "s", [], ["x"])
                self.assertEqual((it.status, it.fix.commands), ("warn", ["x"]))
            finally:
                setup.HOME = old


if __name__ == "__main__":
    unittest.main()
