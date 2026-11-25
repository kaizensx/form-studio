"""The owner's "make it really beautiful" turned into a plain slab, and the conversations showed raw errors. This covers
the fixes that need no model: the spending cap said plainly, Claude Code's tool names and run environment, the
aesthetic trigger (English and Portuguese) with its beauty protocol, the aesthetic rubric, sheet labels with accents,
and every exemplar's appearance() finishes being real ones."""
import ast
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import chat, critique, design_guide, staged  # noqa: E402
from form.agents.base import Adapter, Run  # noqa: E402
from form.agents.claude import Claude, ClaudeParser  # noqa: E402


class SpendingCap(unittest.TestCase):
    def test_budget_error_is_recognised(self):
        self.assertTrue(chat.is_budget_stop("error_max_budget_usd"))
        self.assertFalse(chat.is_budget_stop("error_during_execution"))
        self.assertFalse(chat.is_budget_stop(""))

    def test_card_says_what_stopped_what_is_kept_and_where_the_cap_is(self):
        c = chat.budget_card(3.0, 3.12, ["sofa-clip"], {"project": "sofa-clip", "from": 1, "to": 4})
        self.assertIn("spending cap of $3.00 per message", c["message"])
        self.assertIn("$3.12", c["message"])
        self.assertIn("sofa-clip", c["message"])
        self.assertIn("revision 4", c["message"])
        self.assertIn("Settings › Chat › Spending cap per message", c["hint"])
        self.assertNotIn("error_max_budget_usd", c["message"] + c["hint"])
        bare = chat.budget_card(3.0)
        self.assertIn("kept", bare["message"])

    def test_the_setting_is_visible_and_its_default_unchanged(self):
        from form import config, config_edit
        s = config_edit.SCHEMA["chat.budget_usd_per_message"]
        self.assertFalse(s.get("hidden"))
        self.assertEqual(s["tab"], "chat")
        self.assertEqual(s["label"], "Spending cap per message")
        self.assertEqual(config.DEFAULTS["chat"]["budget_usd_per_message"], 3.0)


SCRIPT = r"""
import json, sys
print(json.dumps({"type": "system", "subtype": "init", "session_id": "s-1", "model": "claude-test"}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on the clip."}]}}), flush=True)
print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "session_id": "s-1",
                  "total_cost_usd": 3.04, "num_turns": 31}), flush=True)
sys.exit(1)
"""


class OverBudget(Adapter):
    """A stand-in for Claude Code that stops at the spending cap the way the real CLI reports it."""
    id, label, cli = "fake", "Fake agent", "python"
    cost = True

    def executable(self, cfg):
        return sys.executable

    def command(self, run: Run, exe: str):
        return [exe, "-c", SCRIPT]

    def parser(self):
        return ClaudeParser()


class SpendingCapInChat(unittest.TestCase):
    def test_the_chat_shows_the_plain_message_not_the_subtype(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            cfg = {"chat": {"agent": "fake", "model": "default", "effort": "", "budget_usd_per_message": 3.0},
                   "_path": str(Path(tmp) / "studio.toml")}
            c = chat.Chat(cfg, data, "/nonexistent/form-mcp", adapters={"fake": OverBudget()})
            j = c.send("Make the clip really beautiful")
            t0 = time.time()
            while j.state == "running" and time.time() - t0 < 20:
                time.sleep(0.02)
            self.assertEqual(j.state, "failed")
            errs = [e for e in j.events if e["t"] == "error"]
            self.assertEqual(len(errs), 1, errs)
            self.assertEqual(errs[0]["kind"], "budget")
            self.assertIn("spending cap of $3.00", errs[0]["text"])
            self.assertIn("Spending cap per message", errs[0]["hint"])
            self.assertNotIn("error_max_budget_usd", json.dumps(j.events))


class ClaudeToolNames(unittest.TestCase):
    def _run(self, tmp, message="hello"):
        return Run(message=message, system=chat.system_prompt({}, None, Claude(), message), cwd=Path(tmp),
                   scratch=Path(tmp), mcp={"command": "form-mcp", "args": [], "env": {}})

    def test_prompt_names_the_prefix_for_claude_only(self):
        sp = chat.system_prompt({}, None, Claude())
        self.assertIn("mcp__form__design_guide", sp)
        self.assertIn("No such tool available", sp)
        self.assertNotIn("mcp__form__", chat.system_prompt({}, None, None))      # other agents name tools bare

    def test_run_env_turns_tool_search_on_and_the_command_allows_form_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(tmp)
            ad = Claude()
            self.assertEqual(ad.run_env(run).get("ENABLE_TOOL_SEARCH"), "auto")
            cmd = ad.command(run, sys.executable)              # help text of python: no --restricted, still a command
            self.assertIn("ToolSearch", cmd[cmd.index("--tools") + 1].split(","))   # deferred tools stay reachable
            self.assertIn("mcp__form__*", cmd[cmd.index("--allowedTools") + 1])
            self.assertIn("mcp__form__design_guide", cmd[cmd.index("--append-system-prompt") + 1])
            mcp = json.loads((Path(tmp) / "mcp.json").read_text())
            self.assertIn("form", mcp["mcpServers"])           # the server name the prefix is made from

    def test_the_spawned_env_carries_it(self):
        """chat._run builds the process env as os.environ + adapter.env + secrets + run_env: run_env wins."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "ENABLE_TOOL_SEARCH": "false", **Claude().run_env(self._run(tmp))}
            self.assertEqual(env["ENABLE_TOOL_SEARCH"], "auto")


class AestheticTrigger(unittest.TestCase):
    YES = ["make it really beautiful, impress me", "I want something premium and high-end", "wow me",
           "a gorgeous lamp", "a beatiful phone stand", "make it look nice",
           "quero um suporte lindo que impressione", "faz uma coisa bonita", "algo lindíssimo e elegante",
           "uma peça deslumbrante", "capricha no design", "un soporte hermoso"]
    NO = ["an outlet holder for my sofa", "make the hole 2 mm bigger", "para impressão 3D na minha impressora",
          "impresso em PLA", "awesome, now make the wall thicker", "gira 90 graus", "a pretty strong clip",
          "an M6 bracket with a hex head bolt", ""]

    def test_english_and_portuguese_hits(self):
        for t in self.YES:
            self.assertTrue(staged.aesthetic_intent(t)["aesthetic"], t)

    def test_no_false_alarms_on_printing_words_and_praise(self):
        for t in self.NO:
            self.assertFalse(staged.aesthetic_intent(t)["aesthetic"], t)

    def test_assess_routes_aesthetic_briefs_to_the_aesthetics_topic(self):
        a = staged.assess("um porta-cabos lindo")
        self.assertIn("aesthetic", a["families"])
        self.assertIn("aesthetics", staged.topics_for(a["families"]))

    def test_the_beauty_protocol_is_injected_on_a_hit_only(self):
        hit = chat.system_prompt({}, None, Claude(), "Faz-me um suporte de telemóvel muito bonito")
        for must in ('mcp__form__design_guide(topic="aesthetics")', "mcp__form__render_photo",
                     "three_quarter_back", "aesthetic={", "At least two critique passes", "Never drop edge rounding",
                     "design-language statement"):
            self.assertIn(must, hit)
        self.assertNotIn("THIS MESSAGE ASKS FOR SOMETHING THAT LOOKS SPECIAL",
                         chat.system_prompt({}, None, Claude(), "make the hole bigger"))
        plain = chat.system_prompt({}, None, None, "make it beautiful")            # other agents: bare names
        self.assertIn('design_guide(topic="aesthetics")', plain)
        self.assertNotIn("mcp__form__", plain)


class AestheticRubric(unittest.TestCase):
    GOOD = {"surface_mix": {"plane": 0.3, "free": 0.5, "torus": 0.2}, "fillet_faces": 30,
            "fillet_radii": [0.6, 0.8, 2.0, 6.0], "sharp_edge_fraction": 0.1, "tangent_edge_fraction": 0.7,
            "features": {"body": {}, "crown": {}, "foot": {}, "channels": {}},
            "proportions": {"ratios": [{"pair": "long:mid", "ratio": 1.6, "nearest": "golden", "off_pct": 1.0}]}}
    ZONES = [{"features": ["body", "crown"], "finish": "matte", "color": "#d9d2c5"},
             {"features": ["channels"], "finish": "rubber", "color": "#d2703f"},
             {"features": ["foot"], "finish": "rubber", "color": "#2b2c2e"}]
    ALL5 = {i: 5 for i, _, _ in critique.AESTHETIC}

    def test_eight_items(self):
        self.assertEqual([i for i, _, _ in critique.AESTHETIC],
                         ["silhouette", "proportion", "continuity", "radius_hierarchy", "break_up", "detail_rhythm",
                          "material", "would_sell"])

    def test_unscored_does_not_pass_and_says_how_to_score(self):
        r = critique.aesthetic_rubric(self.GOOD, self.ZONES, None)
        self.assertFalse(r["passed"])
        self.assertIsNone(r["mean"])
        self.assertIn("render_photo", r["next"])

    def test_a_well_made_design_passes(self):
        r = critique.aesthetic_rubric(self.GOOD, self.ZONES, dict(self.ALL5, detail_rhythm=4))
        self.assertTrue(r["passed"], r)
        self.assertGreaterEqual(r["mean"], 4)

    def test_the_owners_slab_cannot_pass_however_it_is_scored(self):
        """One colour, no radii, a bent plate: the geometry caps the agent's fives."""
        slab = {"surface_mix": {"plane": 0.95, "cylinder": 0.05}, "fillet_faces": 0, "fillet_radii": [],
                "sharp_edge_fraction": 0.9, "tangent_edge_fraction": 0.05, "features": {"body": {}},
                "proportions": {"ratios": []}}
        r = critique.aesthetic_rubric(slab, [], self.ALL5)
        self.assertFalse(r["passed"])
        caps = {i["id"]: i["cap"] for i in r["items"]}
        self.assertEqual(caps["radius_hierarchy"], 1)
        self.assertEqual(caps["material"], 1)
        self.assertEqual(caps["silhouette"], 1)
        self.assertLessEqual(r["mean"], 3)
        self.assertIn("Fix the lowest first", r["next"])

    def test_gate_needs_mean_four_and_nothing_under_three(self):
        r = critique.aesthetic_rubric(self.GOOD, self.ZONES, dict(self.ALL5, detail_rhythm=2))
        self.assertGreaterEqual(r["mean"], 4)
        self.assertFalse(r["passed"])

    def test_scores_are_clamped_and_unknown_keys_reported(self):
        r = critique.aesthetic_rubric(self.GOOD, self.ZONES, dict(self.ALL5, silhouette=9, sparkle=5))
        self.assertEqual(r["items"][0]["final"], 5)
        self.assertEqual(r["ignored"], ["sparkle"])

    def test_radius_tiers(self):
        self.assertEqual(critique.radius_tiers([]), 0)
        self.assertEqual(critique.radius_tiers([0.6, 0.8, 1.0]), 1)
        self.assertEqual(critique.radius_tiers([0.8, 2.0, 6.0]), 3)


class Guide(unittest.TestCase):
    def test_aesthetics_is_a_method_with_code(self):
        g = design_guide.topic("aesthetics")["guide"]
        for must in ("DESIGN LANGUAGE", "archetype", "PROPORTION", "G2", "superellipse_face", "RADIUS HIERARCHY",
                     "safe_fillet", "NEVER A REASON TO DROP ROUNDING", "SHADOW GAP", "DETAIL RHYTHM", "appearance()",
                     "critique(project, aesthetic="):
            self.assertIn(must, g)
        from form import exemplars
        names = {e["name"] for e in exemplars.catalogue()}
        for ex in ("cable_dock", "valet_tray", "ribbon_phone_stand", "lamp_base", "cube_speaker", "slim_remote",
                   "floating_wall_hook", "sofa_arm_clip"):
            self.assertIn(ex, g)
            self.assertIn(ex, names)


class SheetLabels(unittest.TestCase):
    def test_accented_names_are_not_boxes(self):
        from PIL import Image, ImageDraw
        from form import render

        def bitmap(font, text):
            im = Image.new("L", (80, 30), 0)
            ImageDraw.Draw(im).text((2, 2), text, font=font, fill=255)
            return im.tobytes()
        f = render._font(16)
        for ch in "óíçãê":
            self.assertNotEqual(bitmap(f, ch), bitmap(f, ""), ch)          #  draws the missing-glyph box


class ExemplarFinishes(unittest.TestCase):
    def test_every_appearance_finish_is_a_real_one(self):
        """An unknown finish ("satin") makes render_photo drop every zone and photograph one colour."""
        from form.adapters.blender import FINISHES
        bad = []
        for f in sorted((ROOT / "form" / "exemplars").glob("*.py")):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Dict):
                    for k, val in zip(node.keys, node.values):
                        if isinstance(k, ast.Constant) and k.value == "finish" and isinstance(val, ast.Constant) and isinstance(val.value, str):
                            if val.value not in FINISHES:
                                bad.append((f.name, val.value))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
