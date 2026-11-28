"""The benchmark harness (form/bench): own suites as rows, Parametric CAD Bench v3 plumbing with the stand-in agent,
the leaderboard's scoring rule, the publish page, and scorer parity on real tasks when they and Docker are here.

The fixture task (tests/fixtures/cadbench/fixture-block) has a Harbor task's layout and is not a CAD Bench task.
Scorer parity needs FORM_CADBENCH_TASKS (a `harbor download` export) and a running Docker; it is skipped otherwise.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import bench  # noqa: E402
from form.bench import cadbench, publish, suites  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "cadbench"


class Aggregate(unittest.TestCase):
    """The leaderboard's rule (cad-bench-submission CONTRIBUTING.md): failures count zero, mode means over 30/30/40."""

    def test_missing_rewards_count_zero_and_modes_use_their_counts(self):
        trials = ([{"mode": "create", "reward": 1.0}] * 3 + [{"mode": "create", "reward": None}] * 27
                  + [{"mode": "create_edit", "reward": 0.5}] * 30 + [{"mode": "image_to_cad", "reward": 0.0}] * 40)
        s = cadbench.aggregate(trials, {"create": 30, "create_edit": 30, "image_to_cad": 40})
        self.assertTrue(s["complete"])
        self.assertEqual(s["errors"], 27)
        self.assertAlmostEqual(s["mean_reward"], (3 * 1.0 + 30 * 0.5) / 100)
        self.assertAlmostEqual(s["modes"]["create"]["mean_reward"], 0.1)
        self.assertAlmostEqual(s["modes"]["create_edit"]["mean_reward"], 0.5)
        self.assertEqual(s["perfect"], 3)

    def test_a_subset_says_so(self):
        s = cadbench.aggregate([{"mode": "create", "reward": 0.4}])
        self.assertFalse(s["complete"])
        self.assertEqual(s["modes"]["create"]["mean_reward"], 0.4)


class Tasks(unittest.TestCase):
    def test_modes_and_prompt(self):
        tasks = cadbench.find_tasks(FIXTURES)
        self.assertEqual([t.name for t in tasks], ["fixture-block"])
        self.assertEqual(cadbench.mode_of(tasks[0]), "create")
        ws = Path("/tmp/trial/app")
        p = cadbench.prompt_for(tasks[0], ws, "/opt/freecadcmd")
        self.assertNotIn("`/app/", p)
        self.assertIn("/tmp/trial/app/answer.py", p)
        self.assertIn("block_length = 40.0 mm", p)              # the published text is kept
        self.assertIn("/opt/freecadcmd", p)

    def test_unknown_or_unwired_agents_are_refused(self):
        with self.assertRaises(cadbench.BenchError):
            cadbench.adapter_for("nobody")
        with self.assertRaises(cadbench.BenchError):
            cadbench.adapter_for("codex")


class ClaudeCommand(unittest.TestCase):
    def test_extra_tools_reach_the_allowed_list(self):
        from form.agents.base import Run
        from form.agents.claude import Claude
        tmp = Path(tempfile.mkdtemp())
        try:
            run = Run(message="m", scratch=tmp, cwd=tmp, mcp={"command": "x"}, web=False,
                      extra_tools=["Write(//w/**)", "Bash(/fc:*)"])
            cmd = Claude().command(run, "/nonexistent/claude")
            tools = cmd[cmd.index("--tools") + 1].split(",")
            allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
            self.assertIn("Write", tools)
            self.assertIn("Bash", tools)
            self.assertIn("Write(//w/**)", allowed)
            self.assertIn("Bash(/fc:*)", allowed)
            self.assertNotIn("Bash", allowed)                    # only the rule, never the bare tool
            plain = Claude().command(Run(message="m", scratch=tmp, cwd=tmp, mcp={"command": "x"}), "/nonexistent/claude")
            self.assertNotIn("Bash", plain[plain.index("--tools") + 1].split(","))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class StandInPlumbing(unittest.TestCase):
    """The stand-in agent through the real harness: Form Studio's MCP server, an isolated data folder, FreeCAD when
    installed. The scorer is replaced by a check of the files (the real one needs Docker; see ScorerParity)."""

    def test_one_task_end_to_end(self):
        out = Path(tempfile.mkdtemp(prefix="form-bench-test-"))
        seen = {}

        def fake_score(task, trial, meta):
            seen["files"] = sorted(p.name for p in (trial / "app").iterdir())
            return {"reward": 0.25 if (trial / "app" / "answer.py").is_file() else 0.0, "details": {"score": 0.25}}

        try:
            with mock.patch.object(cadbench, "score", fake_score), \
                    mock.patch.dict(os.environ, {"FORM_UITEST_AGENT": ""}):
                res = cadbench.run(FIXTURES, "standin", out=out, timeout=600)
            t = res["trials"][0]
            self.assertTrue(res["standin"])
            self.assertEqual(t["reward"], 0.25)
            self.assertEqual(t["agent"]["exit"], 0)
            self.assertIn("create_design", t["agent"]["form_tools"])        # it went through Form Studio's MCP server
            self.assertIn("note.txt", seen["files"])                         # the environment files, nothing else
            self.assertNotIn("SECRET.txt", seen["files"])
            self.assertNotIn("Dockerfile", seen["files"])
            trial = out / "trials" / "fixture-block"
            self.assertTrue((trial / "trajectory.jsonl").is_file())
            self.assertTrue(any((trial / "form-data").iterdir()))           # the design landed in the trial's data
            self.assertTrue((out / "results.json").is_file())
            if cadbench._git("rev-parse", "HEAD"):
                self.assertTrue(res["commit"])
            from form import cad_bridges
            if os.environ.get("FORM_FREECADCMD") or cad_bridges.find_freecad({}):
                self.assertIn("answer.FCStd", t["answers"])
                # the answer came from Form Studio's PartDesign export, not from a script the agent wrote
                self.assertIn("freecad_partdesign", t["agent"]["form_tools"])
                self.assertIn("answer_steps", seen["files"])
                self.assertIn("FreeCAD PartDesign export written by Form Studio",
                              (trial / "app" / "answer.py").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(out, ignore_errors=True)


@unittest.skipUnless(os.environ.get("FORM_CADBENCH_TASKS") and cadbench.docker(), "needs FORM_CADBENCH_TASKS and Docker")
class ScorerParity(unittest.TestCase):
    """Each mode's held-back reference, scored through the harness by the task's own verifier, is 1.0."""

    def test_reference_scores_one_in_every_mode(self):
        tasks = cadbench.find_tasks(Path(os.environ["FORM_CADBENCH_TASKS"]))
        pick = {}
        for t in tasks:
            pick.setdefault(cadbench.mode_of(t), t)
        out = Path(tempfile.mkdtemp())
        try:
            for mode, t in pick.items():
                self.assertEqual(cadbench.oracle(t, out)["reward"], 1.0, f"{mode}: {t.name}")
        finally:
            shutil.rmtree(out, ignore_errors=True)


class Suites(unittest.TestCase):
    def test_threshold_probes(self):
        pts = suites._probe_points(">=", 1.0, 2.0)
        self.assertIn((1.0, "warn", "at the fail limit"), pts)
        self.assertTrue(any(w == "fail" and v < 1.0 for v, w, _ in pts))
        self.assertIn((2.0, "pass", "at the warn limit"), pts)
        pts = suites._probe_points("<=", 30.0, 4.0)
        self.assertTrue(any(w == "fail" and v > 30.0 for v, w, _ in pts))
        self.assertTrue(any(w == "warn" and v > 4.0 for v, w, _ in pts))

    def test_iso286_on_this_checkout(self):
        r = bench.run_suite("iso286")
        self.assertTrue(r["available"])
        self.assertGreater(len(r["rows"]), 0)
        self.assertEqual(r["failed"], 0, [x for x in r["rows"] if not x["pass"]])
        self.assertTrue(r["commit"])

    def test_a_suite_without_its_code_says_so(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "form").mkdir()
            (tmp / "form" / "__init__.py").write_text("")
            env = {**os.environ, "PYTHONPATH": str(tmp)}
            import subprocess
            r = subprocess.run([sys.executable, str(bench.RUNNER), "strength"], capture_output=True, text=True, env=env)
            rep = json.loads(r.stdout)
            self.assertFalse(rep["available"])
            self.assertEqual(rep["rows"], [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Publish(unittest.TestCase):
    def test_failures_are_printed_and_the_pending_score_is_said(self):
        tmp = Path(tempfile.mkdtemp())
        row = lambda ok: {"group": "g", "item": "q", "expected": 1.0, "got": 1.0 if ok else 2.0, "unit": "mm",  # noqa: E731
                          "tolerance": 0.01, "error": 0.0 if ok else 1.0, "relative": True, "pass": ok, "source": "s",
                          "note": ""}
        suites_json = {"suites": {"dfm": {"suite": "dfm", "available": True, "rows": [row(True), row(False)], "passed": 1,
                                          "failed": 1, "commit": "abc", "branch": "b", "machine": "m", "date": "d",
                                          "seconds": 1}}}
        (tmp / "s.json").write_text(json.dumps(suites_json))
        (tmp / "c.json").write_text(json.dumps({"runs": []}))
        try:
            with mock.patch.object(publish, "SUITES_JSON", tmp / "s.json"), \
                    mock.patch.object(publish, "CADBENCH_JSON", tmp / "c.json"):
                md = publish.markdown()
                page = publish.page()
            self.assertIn("**FAIL**", md)
            self.assertIn("pending a run with a real model", md)
            self.assertIn("form bench cadbench --tasks", md)
            self.assertIn('class="r-fail"', page)
            self.assertIn("<!--nav-->", page)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
