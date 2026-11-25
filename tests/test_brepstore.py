"""One build per (design source, values) (form/brepstore.py, form/kernel.py _brep).

Every tolerance and every caller key share one build; the B-rep and its face-to-feature map survive a round trip
through the disk store unchanged; a second process finds the solid the first one built (0 builds), and while one
process builds a key another waits for it instead of building it too. Ephemeral keys (sweeps, optimiser candidates)
stay in memory. The studio's kernel deadlines follow the predicted cost of a build, and the renderer's batched
z-buffer gives the same pixels as drawing triangle after triangle."""
import json
import math
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.mkdtemp(prefix="form-brepstore-")
ENV = {"FORM_SOURCES": str(Path(TMP) / ".sources"), "FORM_BREP_STORE": str(Path(TMP) / ".cache" / "brep"),
       "FORM_CHECKPOINTS": str(Path(TMP) / ".cache" / "checkpoints")}

from form import brepstore, kernel  # noqa: E402
from form.recipes import store_source  # noqa: E402

BORED = '''
from build123d import Box, Cylinder
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Bored block"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body"),
              Param("d", "Bore", 10, 4, 16, 0.5, "mm", "form", "bore")]
    features = [Feature("body", "Body", "structure"), Feature("bore", "Bore", "interface")]

    def build(self, v):
        body = Box(v["w"], v["w"], 20)
        stages = [Stage("body", body)]
        body = body - Cylinder(v["d"] / 2, 40)
        stages.append(Stage("bore", body))
        return stages
'''
RID = store_source(Path(ENV["FORM_SOURCES"]), BORED)


def reset():
    kernel._cache.clear()
    kernel._breps.clear()
    for k in kernel.STATS:
        kernel.STATS[k] = 0 if isinstance(kernel.STATS[k], int) else 0.0


CHILD = textwrap.dedent('''
    import json, os, sys, time
    sys.path.insert(0, {root!r})
    from form import brepstore, kernel
    vals = json.loads(sys.argv[2])
    if sys.argv[1] == "hold":                      # build the key while holding its marker, slowly
        rec = kernel.resolve({rid!r})
        k = brepstore.key(rec, {rid!r}, rec.validate(vals))
        assert brepstore.claim(k)
        print("claimed", flush=True)
        time.sleep(2.0)
        b = kernel._build_brep({rid!r}, vals)
        brepstore.save(k, b["shape"], kernel._meta(b))
        brepstore.release(k)
    else:
        kernel._get("other-caller", {rid!r}, vals, 0.07)
    print(json.dumps(kernel.STATS))
''')


class OneBuild(unittest.TestCase):
    def setUp(self):                              # other test modules in the same run point these elsewhere
        self._env = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        reset()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_every_tolerance_and_caller_key_share_one_build(self):
        vals = {"w": 41.0}
        a = kernel._get("pv-draft", RID, vals, 0.1)
        b = kernel._get("geometry-key", RID, vals, 0.05)
        c = kernel._get("view", RID, vals, 0.03)
        self.assertEqual(kernel.STATS["built"], 1)
        self.assertIs(a["shape"], c["shape"])
        self.assertGreater(len(c["faces"][0]["T"]) + sum(len(f["T"]) for f in c["faces"]),
                           sum(len(f["T"]) for f in a["faces"]))            # each its own tessellation
        self.assertEqual(sorted({f["feature"] for f in b["faces"]}), ["body", "bore"])
        self.assertEqual(kernel.op_summary("again", RID, vals)["timing"]["brep"], "built")

    def test_disk_round_trip_keeps_the_face_to_feature_map(self):
        vals = {"w": 42.0, "d": 9.0}
        built = kernel._get("k1", RID, vals, 0.05)
        reset()
        loaded = kernel._get("k2", RID, vals, 0.05)
        self.assertEqual(kernel.STATS["built"], 0)
        self.assertEqual(kernel.STATS["disk"], 1)
        self.assertEqual(loaded["face_features"], built["face_features"])
        self.assertEqual([f["feature"] for f in loaded["faces"]], [f["feature"] for f in built["faces"]])
        self.assertAlmostEqual(loaded["volume"], built["volume"], places=6)
        self.assertEqual({k: len(v) for k, v in loaded["by_feature"].items()},
                         {k: len(v) for k, v in built["by_feature"].items()})
        s1, s2 = kernel._summary(built), kernel._summary(loaded)
        self.assertEqual(s1["signature"], s2["signature"])
        self.assertEqual(s2["timing"]["brep"], "disk")

    def test_other_values_are_another_build_and_ephemeral_keys_stay_in_memory(self):
        kernel._get("x", RID, {"w": 43.0}, 0.05)
        kernel._get("x2", RID, {"w": 44.0}, 0.05)
        self.assertEqual(kernel.STATS["built"], 2)
        kernel._get("var-sweep", RID, {"w": 45.0}, 0.05)
        reset()
        kernel._get("var-sweep", RID, {"w": 45.0}, 0.05)
        self.assertEqual(kernel.STATS["built"], 1)               # not on disk

    def test_a_fresh_process_builds_nothing(self):
        vals = {"w": 46.0}
        kernel._get("first", RID, vals, 0.03)
        out = subprocess.run([sys.executable, "-c", CHILD.format(root=str(ROOT), rid=RID), "get", json.dumps(vals)],
                             capture_output=True, text=True, env=dict(os.environ), timeout=300)
        stats = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual((stats["built"], stats["disk"]), (0, 1), out.stderr[-800:])

    def test_a_second_process_waits_for_the_builder(self):
        vals = {"w": 47.0}
        child = subprocess.Popen([sys.executable, "-c", CHILD.format(root=str(ROOT), rid=RID), "hold",
                                  json.dumps(vals)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env=dict(os.environ))
        try:
            self.assertEqual(child.stdout.readline().strip(), "claimed")
            t = time.time()
            m = kernel._get("waiter", RID, vals, 0.05)
            self.assertGreater(time.time() - t, 0.5)
            self.assertEqual((kernel.STATS["waited"], kernel.STATS["built"], kernel.STATS["disk"]), (1, 0, 1))
            self.assertEqual(sorted(m["by_feature"]), ["body", "bore"])
        finally:
            child.communicate(timeout=300)

    def test_a_dead_builders_marker_does_not_block(self):
        rec = kernel.resolve(RID)
        k = brepstore.key(rec, RID, rec.validate({"w": 48.0}))
        m = brepstore.directory() / f"{k}.building"
        m.parent.mkdir(parents=True, exist_ok=True)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        m.write_text(json.dumps({"pid": dead.pid, "host": __import__("socket").gethostname(), "ts": time.time()}))
        kernel._get("k", RID, {"w": 48.0}, 0.05)
        self.assertEqual((kernel.STATS["built"], kernel.STATS["waited"]), (1, 0))
        self.assertFalse(m.exists())

    def test_prune_keeps_the_newest(self):
        for w in (50.0, 51.0, 52.0):
            kernel._get(f"p{w}", RID, {"w": w}, 0.05)
            time.sleep(0.02)
        d = brepstore.directory()
        before = len(list(d.glob("*.model.json")))
        brepstore.prune(d, keep=2)
        left = list(d.glob("*.model.json"))
        self.assertEqual(len(left), 2)
        self.assertGreaterEqual(before, 3)
        self.assertEqual(len(list(d.glob("*.bin"))), 2)


class Deadlines(unittest.TestCase):
    def test_deadline_follows_the_predicted_build(self):
        from form import studio as S

        class Fake:
            _build_cost = {}
            recipes = {}
            predicted_build_s = S.Studio.predicted_build_s
            deadline = S.Studio.deadline
        f = Fake()
        self.assertEqual(f.deadline("view"), S.DEADLINE_MIN)            # unknown and small: the floor
        f._build_cost["src:big"] = 160.0                                  # a build measured at 160 s
        self.assertEqual(f.deadline("summary", None, "src:big"), 3.0 * 160 + 45)
        f._build_cost["src:huge"] = 4000.0
        self.assertEqual(f.deadline("summary", None, "src:huge"), S.DEADLINE_MAX)


class Raster(unittest.TestCase):
    def test_batched_zbuffer_matches_triangle_after_triangle(self):
        from form.render import _raster
        rng = np.random.default_rng(3)
        w, h = 160, 120
        n = 900
        c = rng.random((n, 1, 2)) * [w, h]
        X = c[..., 0] + rng.normal(0, 1, (n, 3)) * rng.choice([1.0, 6.0, 40.0], (n, 1))
        Y = c[..., 1] + rng.normal(0, 1, (n, 3)) * rng.choice([1.0, 6.0, 40.0], (n, 1))
        Z = np.round(rng.random((n, 3)) * 4, 1)                        # coarse depths: ties happen
        X[:5] = X[:5, :1]                                               # degenerate triangles
        zb, ib = _raster(X, Y, Z, w, h)
        zr, ir = np.full((h, w), np.inf), np.full((h, w), -1)
        for i in range(n):
            x, y, z = X[i], Y[i], Z[i]
            x0, x1 = max(int(math.floor(x.min())), 0), min(int(math.ceil(x.max())), w - 1)
            y0, y1 = max(int(math.floor(y.min())), 0), min(int(math.ceil(y.max())), h - 1)
            if x1 < x0 or y1 < y0:
                continue
            area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
            if abs(area) < 1e-9:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((x[1] - px) * (y[2] - py) - (x[2] - px) * (y[1] - py)) / area
            w1 = ((x[2] - px) * (y[0] - py) - (x[0] - px) * (y[2] - py)) / area
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
            zs = zr[y0:y1 + 1, x0:x1 + 1]
            m = inside & (zz < zs)
            zs[m] = zz[m]
            ir[y0:y1 + 1, x0:x1 + 1][m] = i
        self.assertTrue(np.array_equal(ib, ir))
        self.assertTrue(np.array_equal(zb, zr))


if __name__ == "__main__":
    unittest.main()
