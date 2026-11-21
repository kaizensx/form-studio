"""What a FeatureDesign keeps between builds stays true (form/featureprog.py, form/worker.py, form/recon/bounded.py).

A skipped feature's record follows the part count it failed on; a whole call that runs out of time marks no feature
as hung, only a feature past its own budget is; hang marks expire; checkpoints follow the Form build; the records
next to the checkpoints are pruned; every way of reading the values or the class's members is accounted for; and
two loops with their own clocks (fit_params' search, sending a job to the reconstruction helper) end on time."""
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="form-feature-cache-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import config, featureprog  # noqa: E402
from form.studio import Studio  # noqa: E402

SPLITS = '''
from build123d import Box, Compound, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Splits"
    solids = 1
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], v["w"], 20)

    @feature("Second part")
    def second(self, v, body):
        return Compound([body, Pos(v["w"] + 20, 0, 0) * Box(10, 10, 10)])
'''


def _log(st, p):
    return {e["feature"]: e["status"] for e in st.rev(p)["build_log"]}


class SkipFollowsCount(unittest.TestCase):
    """Blocker 1: a feature skipped because it made more solids than declared builds once `solids` is raised."""

    def test_raising_solids_builds_the_feature_again(self):
        st = Studio(config.load())
        try:
            p = st.create_design("Splits", SPLITS, partial=True)
            self.assertEqual(_log(st, p), {"body": "built", "second": "skipped"})
            sk = st.rev(p)["partial"]["skipped"][0]
            self.assertIn("the design declares 1", sk["message"])
            p = st.update_design(st.load(p["id"]), featureprog.strip_partial(st.source_text(p)), partial=True)
            self.assertEqual(_log(st, p)["second"], "skipped")               # same count: the record is reused
            self.assertTrue(st.rev(p)["build_log"][1].get("cached"))
            src = featureprog.strip_partial(st.source_text(p)).replace("solids = 1", "solids = 2")
            p = st.update_design(st.load(p["id"]), src, partial=True)
            self.assertEqual(_log(st, p), {"body": "checkpoint", "second": "built"})
            self.assertNotIn("partial", st.rev(p))
        finally:
            st.kernel.stop()


class _Conn:
    """A kernel pipe that sends the given progress events, then never answers."""

    def __init__(self, events):
        self.events = list(events)

    def send(self, _msg):
        pass

    def poll(self, t):
        if self.events:
            return True
        time.sleep(max(0.0, min(t, 5.0)))
        return False

    def recv(self):
        return "progress", self.events.pop(0)


class _Proc:
    exitcode = None

    def __init__(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def kill(self):
        self.alive = False

    def join(self, _t=None):
        pass


class WholeCallTimeout(unittest.TestCase):
    """Blocker 2: only a feature past its own budget (plus the grace) is written down as hung."""

    def _call(self, budget, timeout, grace=None):
        from form import worker
        hang = Path(tempfile.mkdtemp(prefix="form-hang-")) / "f.hung.json"
        k = worker.Kernel()
        k._proc = _Proc()
        k._conn = _Conn([{"kind": "feature_start", "feature": "texture", "i": 3, "budget": budget,
                          "hang_file": str(hang)}])
        with mock.patch.object(worker, "FEATURE_GRACE", worker.FEATURE_GRACE if grace is None else grace):
            with self.assertRaises(worker.KernelFailure) as cm:
                k.call("try_build", timeout=timeout)
        return cm.exception.info, hang

    def test_an_innocent_feature_is_not_marked(self):
        info, hang = self._call(budget=90.0, timeout=0.6)                  # the call's limit ends first
        self.assertEqual(info["kind"], "timeout")
        self.assertIn("did not answer within", info["message"])
        self.assertIn("texture", info["message"])                         # still says what it was building
        self.assertFalse(hang.exists(), "a feature inside its budget was marked as hung")

    def test_a_feature_past_its_budget_is_marked(self):
        info, hang = self._call(budget=0.2, timeout=30.0, grace=0.0)
        self.assertIn("did not finish", info["message"])
        self.assertTrue(hang.exists())
        self.assertEqual(json.loads(hang.read_text())["kind"], "kill")


SPINS = '''
import os
from build123d import Box, Cylinder
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Spins on request"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], v["w"], 20)

    @feature("Bore", budget=0.5)
    def bore(self, v, body):
        while os.environ.get("FORM_TEST_SPIN"):
            pass
        return body - Cylinder(4, 40)
'''


def _load(src: str, name: str):
    d = Path(tempfile.mkdtemp(prefix="form-fc-src-"))
    f = d / f"{name}.py"
    f.write_text(textwrap.dedent(src), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, f


class HangMarks(unittest.TestCase):
    """Should-fix 5: a hang mark is honoured for HANG_TTL, then the feature is built again."""

    def test_a_hang_mark_expires(self):
        ck = Path(tempfile.mkdtemp(prefix="form-ck-"))
        mod, _ = _load(SPINS, "fc_spins")
        with mock.patch.dict(os.environ, {"FORM_CHECKPOINTS": str(ck), "FORM_TEST_SPIN": "1"}):
            featureprog.begin()
            d = mod.Design()
            v = {"w": 40}
            d.build(v)
            self.assertEqual([x["status"] for x in featureprog._REPORT["log"]], ["built", "skipped"])
            marks = list(ck.glob("*.hung.json"))
            self.assertEqual(len(marks), 1)
            os.environ.pop("FORM_TEST_SPIN")
            featureprog.begin()
            d = mod.Design()
            d.build(v)                                                     # still marked: left out at once
            self.assertEqual([x["status"] for x in featureprog._REPORT["log"]], ["checkpoint", "skipped"])
            self.assertIn("without building it again", featureprog._REPORT["skipped"][0]["message"])
            old = json.loads(marks[0].read_text())
            old["ts"] = time.time() - featureprog.HANG_TTL - 60
            marks[0].write_text(json.dumps(old))
            featureprog.begin()
            d = mod.Design()
            d.build(v)                                                     # expired: built again
            self.assertEqual([x["status"] for x in featureprog._REPORT["log"]], ["checkpoint", "built"])
            self.assertFalse(marks[0].exists())

    def test_records_are_pruned_with_the_checkpoints(self):
        d = Path(tempfile.mkdtemp(prefix="form-prune-"))
        for i in range(5):
            for ext in (".bin", ".json", ".skip.json", ".deps.json"):
                f = d / f"k{i}{ext}"
                f.write_text("{}")
                os.utime(f, (time.time() - 100 + i, time.time() - 100 + i))
        fresh, stale = d / "fresh.hung.json", d / "stale.hung.json"
        fresh.write_text("{}")
        stale.write_text("{}")
        os.utime(stale, (time.time() - featureprog.HANG_TTL - 10,) * 2)
        with mock.patch.object(featureprog, "DISK_MAX", 2):
            featureprog.prune(d)
        self.assertEqual(sorted(x.name for x in d.glob("*.bin")), ["k3.bin", "k4.bin"])
        self.assertEqual(sorted(x.name for x in d.glob("*.skip.json")), ["k3.skip.json", "k4.skip.json"])
        self.assertEqual(sorted(x.name for x in d.glob("*.deps.json")), ["k3.deps.json", "k4.deps.json"])
        self.assertTrue(fresh.exists())
        self.assertFalse(stale.exists())


class BuildId(unittest.TestCase):
    """Should-fix 4: a checkpoint made by another Form build is never reused."""

    def test_the_fingerprint_follows_the_build(self):
        from form import __version__
        bid = featureprog.build_id()
        self.assertTrue(bid.startswith(f"{__version__}/{featureprog.CRAFT_REV}/"), bid)
        a = featureprog._context_fingerprint()
        with mock.patch.object(featureprog, "_BUILD_ID", bid + "-other"):
            self.assertNotEqual(featureprog._context_fingerprint(), a)
        self.assertEqual(featureprog._context_fingerprint(), a)


class Reads(unittest.TestCase):
    """Should-fix 6: every way of reading the values is recorded; an unrecognised one reads them all."""

    def test_values(self):
        R = featureprog._Reads
        r = R({"a": 1, "b": 2})
        r.setdefault("a")
        r.pop("b")
        self.assertEqual(r.used(), {"a", "b"})
        for name, f in [("|", lambda r: r | {}), ("r|", lambda r: {} | r), ("repr", repr), ("str", str),
                        ("==", lambda r: r == {"a": 1}), ("!=", lambda r: r != {}), ("len", len),
                        ("dict()", dict), ("**", lambda r: {**r}), ("json", json.dumps), ("popitem", R.popitem),
                        ("update", lambda r: r.update(c=3)), ("reversed", lambda r: list(reversed(r))),
                        ("format", lambda r: f"{r}")]:
            r = R({"a": 1})
            f(r)
            self.assertEqual(r.used(), {"*"}, name)

    def test_members(self):
        base = '''
from build123d import Box
from form.featureprog import FeatureDesign, feature

K = 3
Z = 1


def helper(obj):
    return obj


class Mix:
    def lip(self):
        return 2


class Design(Mix, FeatureDesign):
    title = "Members"
    SIZE = 10
    OTHER = 1

    @feature("Body")
    def body(self, v, body):
        return Box(self.lip(), 1, 1)

    @feature("Cls")
    def cls_attr(self, v, body):
        return body.moved(type(self).SIZE) if False else body

    @feature("Passed")
    def passed(self, v, body):
        helper(self)
        return body

    @feature("Plain")
    def plain(self, v, body):
        return body
'''
        a, _ = _load(base, "fc_members_a")
        ca = featureprog.feature_codes(a.Design)
        for i, (old, new, changed) in enumerate([
                ("return 2", "return 3", {"body", "passed"}),          # a mixin method read through self
                ("SIZE = 10", "SIZE = 12", {"cls_attr", "passed"}),    # a class attribute read through type(self)
                ("OTHER = 1", "OTHER = 2", {"passed"}),                # self handed to a function: every member
        ]):
            b, _ = _load(base.replace(old, new), f"fc_members_b{i}")
            cb = featureprog.feature_codes(b.Design)
            self.assertEqual({k for k in ca if ca[k] != cb[k]}, changed, old)


class FitBudget(unittest.TestCase):
    """Should-fix 7: fit_params' search stops at its time budget with the best values so far."""

    def test_stops_on_time_and_keeps_the_best(self):
        import numpy as np
        from form.remodel import fitparams
        notes = []

        def evaluate(x):
            time.sleep(0.15)
            return np.array([x[0] - 3.0, x[1] + 1.0])
        t = time.monotonic()
        res = fitparams.fit(evaluate, [0.0, 0.0], [-5, -5], [5, 5], [0.05, 0.05], max_evals=500, budget_s=1.0,
                            progress=notes.append)
        took = time.monotonic() - t
        self.assertEqual(res["stopped"], "time")
        self.assertLess(took, 1.0 + 0.5)                       # at most one evaluation past the budget
        self.assertLess(res["evals"], 20)
        best = min(h[1] for h in res["history"])
        self.assertLessEqual(best, res["history"][0][1])     # never worse than the start
        self.assertTrue(notes and {"evals", "best_rms", "seconds"} <= set(notes[-1]))


class BoundedSend(unittest.TestCase):
    """Should-fix 8: a job whose input cannot be sent (a helper that stopped reading) still ends at its budget."""

    def test_a_blocked_send_times_out(self):
        from form.recon import bounded
        gate = threading.Event()

        class Stuck:
            def send_bytes(self, _b):
                gate.wait(30)
                raise OSError("closed")

            def close(self):
                gate.set()

            def poll(self, _t):
                return False

        class Alive(_Proc):
            pass
        h = bounded.Helper()
        h.proc, h.conn = Alive(), Stuck()
        t = time.monotonic()
        out = h.run(json.dumps, ({},), {}, 1.0, None)
        self.assertEqual(out["status"], "timeout")
        self.assertIn("being sent", out["error"])
        self.assertLess(time.monotonic() - t, 4.0)


if __name__ == "__main__":
    unittest.main()
