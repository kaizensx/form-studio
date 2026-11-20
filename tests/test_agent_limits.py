"""What agents are told and how their failures are shown: the sandbox in the instructions, usage limits as a calm card
without upsell text, effort raised for hard tasks, and the printing note that follows the person's setting."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import chat  # noqa: E402
from form.agents import ADAPTERS, effort, limits  # noqa: E402

CODEX_LIMIT = ("You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
               "https://chatgpt.com/settings/usage to purchase more credits or try again at 9:34 PM.")


class Prompt(unittest.TestCase):
    def test_the_sandbox_is_stated_per_agent(self):
        cfg = {"general": {"capabilities": ["core"]}}
        codex = chat.system_prompt(cfg, None, ADAPTERS["codex"])
        self.assertIn("read-only sandbox", codex)
        self.assertIn("Never try python", codex)
        self.assertIn("build_candidates", codex)
        self.assertIn("safe_union", codex)
        generic = chat.system_prompt(cfg, None)
        self.assertIn("no shell you can use", generic)

    def test_new_designs_are_models_unless_asked_for_printing(self):
        printer = {"general": {"capabilities": ["core", "print"]}}
        note = chat.system_prompt(printer, None)
        self.assertIn("New designs are 3D models", note)
        self.assertNotIn("new designs are for printing unless they say otherwise", note)
        chosen = chat.system_prompt({"general": {"capabilities": ["core", "print"], "new_designs": "print"}}, None)
        self.assertIn("chose, in Settings, that new designs are made for printing", chosen)
        self.assertIn("does not 3D print", chat.system_prompt({"general": {"capabilities": ["core"]}}, None))


class Limits(unittest.TestCase):
    def test_codex_limit_is_a_calm_card(self):
        card = limits.usage_limit(CODEX_LIMIT, "Codex", ["wallet-base"])
        self.assertEqual(card["kind"], "usage_limit")
        self.assertEqual(card["until"], "9:34 PM")
        text = card["message"] + card["hint"]
        for upsell in ("http", "Upgrade", "Pro", "purchase", "credits"):
            self.assertNotIn(upsell, text)
        self.assertIn("wallet-base", card["message"])
        self.assertIn("another agent", card["hint"])

    def test_claude_epoch_and_other_errors(self):
        self.assertIsNotNone(limits.usage_limit("Claude AI usage limit reached|1795190938", "Claude")["until"])
        claude = limits.usage_limit("You've hit your 5-hour limit · resets 11pm (Europe/Zurich)", "Claude Code")
        self.assertEqual(claude["until"], "11pm")                        # seen live in an evaluation run
        self.assertIsNone(limits.usage_limit("Fusion failed at step 0", "Codex"))
        self.assertIsNone(limits.usage_limit("model_not_found", "Codex"))

    def test_the_time_reads_right(self):
        card = limits.usage_limit("You've hit your usage limit. Try again in 2 hours.", "Codex")
        self.assertEqual(card["again"], "in about 2 hours")
        self.assertIn("it can work again in about 2 hours.", card["message"])
        self.assertIn("send the message again in about 2 hours.", card["hint"])
        self.assertNotIn("at 2 hours", card["message"] + card["hint"])
        self.assertEqual(limits.usage_limit(CODEX_LIMIT, "Codex")["again"], "at 9:34 PM")
        self.assertEqual(limits.usage_limit("You've hit your 5-hour limit · resets 11pm (Europe/Zurich)", "C")["again"],
                         "at 11pm")
        import time
        tomorrow = int(time.time()) + 2 * 86400
        again = limits.usage_limit(f"Claude AI usage limit reached|{tomorrow}", "Claude")["again"]
        self.assertRegex(again, r"^at \d\d:\d\d on \w{3} \d{1,2} \w{3}$")          # another day: the day is said

    def test_a_rate_limit_or_a_quota_word_is_not_a_usage_limit(self):
        for text in ("429 Too Many Requests", "rate limited, retrying", "Rate limit exceeded for this minute",
                     "the quota field is missing", "HTTP 429"):
            self.assertIsNone(limits.usage_limit(text, "Codex"), text)
        qml = (ROOT / "form" / "app" / "qml" / "Form" / "Store.qml").read_text()
        body = qml.split("function usageLimit(ev)", 1)[1].split("\n    }", 1)[0]
        self.assertIn('ev.kind !== "usage_limit"', body)                            # the card reads the kind only
        self.assertNotIn("429", body)
        self.assertNotIn("quota", body)

    def test_chat_replaces_a_limit_error_event(self):
        c = chat.Chat.__new__(chat.Chat)
        c.adapters = ADAPTERS
        job = chat.ChatJob("hi", None, None, None, "codex")
        job.before = set()
        c._project_ids = lambda: set()
        card = c._limit(job, CODEX_LIMIT)
        self.assertEqual(card["agent"], "Codex")


class Effort(unittest.TestCase):
    def test_hard_tasks_are_raised_never_lowered(self):
        lv = ["low", "medium", "high"]
        self.assertEqual(effort.pick("make these STLs editable", ["a.stl"], "low", lv)[0], "high")
        self.assertEqual(effort.pick("a sliding wallet with a hinge", [], "", lv)[0], "high")
        self.assertEqual(effort.pick("make the wall 2 mm thicker", [], "low", lv), ("low", ""))
        self.assertEqual(effort.pick("design a desk hook", [], "low", lv)[0], "medium")
        self.assertEqual(effort.pick("a helmet", [], "high", lv), ("high", ""))
        self.assertEqual(effort.pick("a helmet", [], "low", []), ("low", ""))            # the agent has no levels

    def test_a_raise_is_said_in_the_conversation_and_can_be_turned_off(self):
        lv = ["low", "medium", "high"]
        self.assertEqual(effort.pick("two gears that mesh", [], "low", lv),
                         ("high", "Using high effort for this task: gears"))
        self.assertEqual(effort.pick("rebuild it", ["a.stl"], "low", lv)[1], "Using high effort for this task: a mesh attached")
        # the reply's start event carries it, and the feed shows it as a line from Form Studio
        talk = (ROOT / "form" / "app" / "qml" / "Form" / "Talk.qml").read_text()
        self.assertIn('if (ev.effort_why) { group = null; out.push({ t: "act"', talk)
        # Settings › Agents has the switch, [chat] auto_effort, on by default; off keeps the person's effort
        from form import config, config_edit
        self.assertEqual(config_edit.SCHEMA["chat.auto_effort"]["type"], "bool")
        self.assertEqual(config_edit.SCHEMA["chat.auto_effort"]["tab"], "chat")
        self.assertIs(config.DEFAULTS["chat"]["auto_effort"], True)
        c = chat.Chat.__new__(chat.Chat)
        c.cfg = {"chat": {"auto_effort": False}}
        job = chat.ChatJob("two gears that mesh", None, None, None, "codex")
        job.effort = "low"
        self.assertEqual(c._effort(job, ADAPTERS["codex"], "codex"), "low")


if __name__ == "__main__":
    unittest.main()
