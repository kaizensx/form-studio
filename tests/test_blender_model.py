"""Blender modelling bridge: op schema, the fixed runner's safety, stage previews, replay and Catmull-Clark agreement.

The tests that need Blender skip cleanly without it; the schema, AST, timeout (a stand-in Blender) and register tests
always run."""
import ast
import asyncio
import base64
import inspect
import json
import os
import struct
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from form import meshsource
from form.adapters import blender as bl
from form.adapters import blender_model as bm
from form.craft import subd

BLENDER = bl.resolve({})
HAS_BLENDER = BLENDER["available"]

CUBE = [{"op": "cage_new", "primitive": "cube", "size": [20, 20, 20]}]
MODEL = CUBE + [
    {"op": "name_region", "name": "top", "faces": {"normal": [0, 0, 1], "within_deg": 10}},
    {"op": "extrude_region", "faces": {"region": "top"}, "offset": 5},
    {"op": "loop_cut", "edge": [0, 1], "cuts": 2},
    {"op": "move", "verts": {"region": "top"}, "by": [0, 0, 2]},
    {"op": "crease", "region_boundary": "top", "value": 1.0},
    {"op": "mirror", "axis": "x"},
    {"op": "sculpt_ops", "strokes": [{"brush": "inflate", "center": [0, 0, 17], "radius": 12, "strength": 0.5},
                                     {"brush": "smooth", "center": [0, 0, 0], "radius": 40, "strength": 0.2,
                                      "iterations": 2}]},
]


def no_blender(*a, **k):
    raise AssertionError("Blender was started")


def max_rel(A, B):
    from scipy.spatial import cKDTree
    d1, _ = cKDTree(B).query(A)
    d2, _ = cKDTree(A).query(B)
    return max(d1.max(), d2.max()) / np.linalg.norm(A.max(0) - A.min(0))


class Schema(unittest.TestCase):
    BAD = [
        ([], "list of 1"),
        ("not json", "not JSON"),
        ([{"op": "exec", "code": "import os"}], "unknown op"),
        ([{"op": "__import__"}], "unknown op"),
        ([{"nop": 1}], "\"op\" name"),
        ([{"op": "move", "verts": {"all": True}, "by": [1, 0, 0]}], "first op"),
        (CUBE + CUBE, "first op"),
        ([{"op": "cage_new", "primitive": "teapot"}], "primitive"),
        ([{"op": "cage_new", "primitive": "cube", "size": [1, 2]}], "[x, y, z]"),
        ([{"op": "cage_new", "primitive": "cube", "size": [1, float("nan"), 1]}], "outside"),
        ([{"op": "cage_new", "primitive": "cube", "size": [1, True, 1]}], "number"),
        ([{"op": "cage_new", "primitive": "cube", "script": "bpy.ops.wm.quit()"}], "does not take"),
        ([{"op": "cage_new", "quads": {"V": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "F": [[0, 1, 7]]}}], "outside"),
        ([{"op": "cage_new", "quads": {"V": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "F": [[0, 1, 1]]}}], "repeats"),
        (CUBE + [{"op": "name_region", "name": "Top; rm -rf", "faces": {"all": True}}], "name like"),
        (CUBE + [{"op": "extrude_region", "faces": {"all": True}}], "offset"),
        (CUBE + [{"op": "extrude_region", "faces": {"where": "top"}, "offset": 1}], "face selection"),
        (CUBE + [{"op": "loop_cut", "edge": [0, 0]}], "itself"),
        (CUBE + [{"op": "loop_cut", "edge": [0, 1], "cuts": 1000}], "outside"),
        (CUBE + [{"op": "mirror", "axis": "w"}], "axis"),
        (CUBE + [{"op": "sculpt_ops", "strokes": [{"brush": "python", "center": [0, 0, 0], "radius": 1}]}], "brush"),
        (CUBE + [{"op": "sculpt_ops", "strokes": [{"brush": "draw", "center": [0, 0, 0], "radius": 1}] * 65}], "1..64"),
        (CUBE + [{"op": "geonodes_scatter", "count": 10 ** 6}], "outside"),
        (CUBE + [{"op": "remesh", "mode": "quadriflow"}], "voxel or quad"),
        (CUBE + [{"op": "crease", "edges": [[0, 1]], "value": 2}], "outside"),
    ]

    def test_refused_before_blender_starts(self):
        with mock.patch.object(bm.subprocess, "Popen", side_effect=no_blender), \
                mock.patch.object(bm, "resolve", side_effect=no_blender):
            for ops, words in self.BAD:
                with self.subTest(ops=str(ops)[:80]):
                    with self.assertRaises(bm.OpError) as cm:
                        bm.run_ops(ops)
                    self.assertIn(words, str(cm.exception))

    def test_error_names_the_op_and_the_schema(self):
        with self.assertRaises(bm.OpError) as cm:
            bm.validate_ops(CUBE + [{"op": "move", "verts": {"all": True}}])
        self.assertEqual(cm.exception.index, 1)
        self.assertIn("move", cm.exception.hint)

    def test_normalised_and_keyed(self):
        a = bm.validate_ops(MODEL)
        self.assertEqual(a[0]["op"], "cage_new")
        self.assertEqual(a[6], {"op": "mirror", "axis": "x", "clip": True, "merge": 1e-4})
        self.assertEqual(bm.op_key(MODEL, "5.2.3"), bm.op_key(json.loads(json.dumps(MODEL)), "5.2.1"))
        self.assertNotEqual(bm.op_key(MODEL, "5.2.3"), bm.op_key(MODEL, "5.1.0"))
        self.assertNotEqual(bm.op_key(MODEL, "5.2.3"), bm.op_key(MODEL[:-1], "5.2.3"))
        self.assertEqual(set(bm.OP_SCHEMA), {"cage_new", "extrude_region", "loop_cut", "move", "crease", "name_region",
                                             "mirror", "geonodes_array", "geonodes_scatter", "sculpt_ops", "remesh",
                                             # the detail vocabulary (tests/test_cage_ops.py)
                                             "bevel", "support_loops", "inset", "panel_line", "trim_strip",
                                             "solidify", "bridge", "kit_place"})

    def test_every_runner_op_is_in_the_schema(self):
        """The runner maps exactly the schema's op names, each to its own function (read from its syntax tree)."""
        t = ast.parse(bm.RUNNER.read_text(encoding="utf-8"))
        ops = next(n.value for n in t.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "OPS")
        self.assertEqual({k.value for k in ops.keys}, set(bm.OP_SCHEMA))
        self.assertEqual({v.id for v in ops.values}, {f"op_{k}" for k in bm.OP_SCHEMA})

    def test_high_only_and_kit_reach_the_job_but_not_the_key(self):
        ops = MODEL + [{"op": "kit_place", "part": "rivet_dome", "faces": {"region": "top"}, "high_only": True}]
        n = bm.validate_ops(ops)
        job = [bm.expand(o) for o in n]
        self.assertEqual(job[:-1], n[:-1])
        self.assertTrue(job[-1]["high_only"])
        self.assertIn("mesh", job[-1])
        self.assertNotIn("mesh", n[-1])
        self.assertEqual(bm.op_key(n, "5.2.3"), bm.op_key(ops, "5.2.3"))


class Safety(unittest.TestCase):
    NET = {"socket", "urllib", "subprocess", "http", "ftplib", "smtplib", "requests", "asyncio", "ssl", "telnetlib",
           "multiprocessing", "ctypes", "importlib", "webbrowser", "xmlrpc", "pty"}

    def _tree(self, path):
        return ast.parse(Path(path).read_text(encoding="utf-8"))

    def test_runner_has_no_network_or_process_imports(self):
        t = self._tree(bm.RUNNER)
        mods = set()
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        self.assertFalse(mods & self.NET, mods & self.NET)
        self.assertEqual(mods, {"json", "math", "os", "struct", "sys", "threading", "time", "bmesh", "bpy",
                                "mathutils"})

    def test_the_runner_watches_its_parent(self):
        """A Form Studio killed mid-run does not leave Blender running: the runner ends itself when re-parented."""
        src = Path(bm.RUNNER).read_text(encoding="utf-8")
        t = ast.parse(src)
        main = next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = [n.func.id for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn("watch_parent", calls)
        self.assertIn("getppid", src)

    def test_no_exec_or_eval_of_agent_text(self):
        for path in (bm.RUNNER, Path(bm.__file__), Path(meshsource.__file__)):
            for n in ast.walk(self._tree(path)):
                if isinstance(n, ast.Call):
                    name = getattr(n.func, "id", None)                 # a builtin called by its bare name
                    if name is None and getattr(n.func, "attr", None) in {"system", "popen", "spawnv", "execv"}:
                        name = n.func.attr                             # os.system and friends
                    banned = {"exec", "eval", "compile", "__import__", "system", "popen", "spawnv", "execv"}
                    if path == bm.RUNNER:              # the runner never looks a name up from the job's text
                        banned |= {"getattr", "setattr"}
                    self.assertNotIn(name, banned, f"{path.name}:{n.lineno}")
        src = bm.RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("--python-expr", Path(bm.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("bpy.ops.script", src)

    def test_command_and_environment(self):
        work = Path(tempfile.mkdtemp())
        cmd = bm.command("/x/blender", "5.2.3", work / "job.json")
        for flag in ("-b", "--factory-startup", "-Y", "--offline-mode", "-noaudio"):
            self.assertIn(flag, cmd)
        self.assertNotIn("-y", cmd)
        self.assertEqual(cmd[cmd.index("--python") + 1], str(bm.RUNNER))
        self.assertNotIn("--offline-mode", bm.command("/x/blender", "4.1.1", work / "job.json"))
        self.assertEqual(bm.offline_flag("4.2.0"), ["--offline-mode"])
        self.assertEqual(bm.offline_flag(""), [])
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/evil", "OPENAI_API_KEY": "k", "BLENDER_USER_SCRIPTS": "/u"}):
            env = bm.scrubbed_env(work)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("BLENDER_USER_SCRIPTS", env)
        self.assertEqual(env["HOME"], str(work))
        self.assertEqual(env["TMPDIR"], str(work))

    @unittest.skipIf(os.name == "nt", "the stand-in Blender is a POSIX shell script")
    def test_timeout_kills_blender_and_leaves_the_project(self):
        tmp = Path(tempfile.mkdtemp())
        child = tmp / "child.pid"
        fake = tmp / "fake-blender"
        fake.write_text("#!/bin/sh\n"
                        "case \"$1\" in --version) echo 'Blender 5.2.0'; exit 0;; esac\n"
                        f"sleep 60 & echo $! > '{child}'\n"
                        "echo 'FORM_STEP 1/1 cage_new'\n"
                        "sleep 60\n", encoding="utf-8")
        fake.chmod(0o755)
        root = tmp / "data"
        (root / "proj").mkdir(parents=True)
        pj = root / "proj" / "project.json"
        pj.write_text(json.dumps({"id": "proj", "head": 3, "name": "Proj"}), encoding="utf-8")
        before = pj.read_bytes()
        st = types.SimpleNamespace(root=root, cfg={"blender": {"app": str(fake)}},
                                   load=lambda pid: json.loads((root / pid / "project.json").read_text()))
        bl._version_cache.pop(str(fake), None)
        t0 = time.time()
        with mock.patch.object(bm, "resolve", return_value={"available": True, "app": str(fake), "version": "5.2.0"}):
            with self.assertRaises(bl.BlenderFailed) as cm:
                bm.model_mesh(st, "proj", CUBE, expect_head=3, timeout=1.5)
        self.assertLess(time.time() - t0, 15)
        self.assertIn("was stopped", str(cm.exception))
        self.assertEqual(pj.read_bytes(), before)
        self.assertFalse((root / ".cache" / "model_mesh").exists() and any((root / ".cache" / "model_mesh").iterdir()))
        pid = int(child.read_text())                    # the grandchild went with the process group
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("a process Blender started is still running")

    @unittest.skipIf(os.name == "nt", "the stand-in Blender is a POSIX shell script")
    def test_a_running_blender_is_killed_at_exit(self):
        """model_mesh's Blender is in the registry kill_all (atexit) empties while it runs, and leaves it after."""
        from form.game import pipeline
        tmp = Path(tempfile.mkdtemp())
        fake = tmp / "fake-blender"
        fake.write_text("#!/bin/sh\necho 'FORM_STEP 1/1 cage_new'\nsleep 60\n", encoding="utf-8")
        fake.chmod(0o755)
        seen = {}

        def at_exit_mid_run():
            for _ in range(100):
                with pipeline._LIVE_LOCK:
                    if pipeline._LIVE:
                        break
                time.sleep(0.05)
            with pipeline._LIVE_LOCK:
                seen["live"] = list(pipeline._LIVE)
            seen["killed"] = pipeline.kill_all()     # what atexit runs when Form Studio quits
        t = threading.Thread(target=at_exit_mid_run)
        t.start()
        t0 = time.time()
        bm._run([str(fake)], tmp, 60, list(CUBE), None, "")
        t.join(10)
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(len(seen["live"]), 1)
        self.assertEqual(seen["killed"], 1)
        self.assertEqual(pipeline._LIVE, {})

    def test_stale_head_refused(self):
        from form.studio import StudioError
        st = types.SimpleNamespace(root=Path(tempfile.mkdtemp()), cfg={}, load=lambda pid: {"head": 4, "name": "x"})
        with mock.patch.object(bm.subprocess, "Popen", side_effect=no_blender):
            with self.assertRaises(StudioError):
                bm.model_mesh(st, "proj", CUBE, expect_head=3)


class Register(unittest.TestCase):
    def test_register_against_a_stub(self):
        tools = {}

        class StubMCP:
            def tool(self, name=None, **kw):
                def deco(fn):
                    tools[name or fn.__name__] = (fn, kw)
                    return fn
                return deco

        st = types.SimpleNamespace(root=Path(tempfile.mkdtemp()), cfg={}, load=lambda pid: {"head": 1, "name": "x"})

        async def run(fn):
            return fn()
        bm.register(StubMCP(), get_studio=lambda: st, run=run)
        self.assertIn("model_mesh", tools)
        fn, kw = tools["model_mesh"]
        self.assertEqual(list(inspect.signature(fn).parameters), ["project", "ops", "expect_head"])
        self.assertTrue(inspect.iscoroutinefunction(fn))
        self.assertIn("Blender", fn.__doc__)
        with mock.patch.object(bm.subprocess, "Popen", side_effect=no_blender):
            out = asyncio.run(fn("proj", [{"op": "rm_rf"}], 1))
        self.assertTrue(out["refused"])
        self.assertEqual(out["error"]["op"], 0)
        self.assertIn("cage_new", out["schema"])
        self.assertIn("kit_place", out["schema"])
        self.assertIn("bolt_hex", out["kit"])                  # a refusal lists the kit parts and their numbers
        self.assertIn("params", out["kit"]["bolt_hex"])
        self.assertIn("high_only", fn.__doc__)


class MeshSource(unittest.TestCase):
    def test_hash_rounds_points_and_reads_faces(self):
        V = np.array([[0.0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]])
        a = meshsource.CageData(V, [[0, 1, 2, 3]])
        self.assertEqual(a.hash(), meshsource.CageData(V + 1e-8, [[0, 1, 2, 3]]).hash())
        self.assertEqual(a.hash(), meshsource.CageData(np.where(V == 0, -0.0, V), [[0, 1, 2, 3]]).hash())
        self.assertNotEqual(a.hash(), meshsource.CageData(V + 1e-3, [[0, 1, 2, 3]]).hash())
        self.assertNotEqual(a.hash(), meshsource.CageData(V, [[1, 2, 3, 0]]).hash())
        b = meshsource.CageData(V, [[0, 1, 2, 3]], creases=[[0, 1, 1.0]], regions={"lid": [0]})
        self.assertEqual(a.hash(), b.hash())
        self.assertNotEqual(a.full_hash(), b.full_hash())

    def test_literal_round_trip_and_subd(self):
        V, F = subd.quad_sphere(3, 10.0)
        c = meshsource.CageData(V, F, creases=[[int(F[0][0]), int(F[0][1]), 1.0]], regions={"cap": [0, 1]})
        ns = {}
        exec(c.literal(), {"meshsource": meshsource}, ns)          # the test runs the generated source, not agent text
        self.assertEqual(ns["CAGE"].full_hash(), c.full_hash())
        self.assertEqual(c.open_edges(), 0)
        cage = c.to_subd()
        self.assertEqual(cage.patches().shape, (len(F), 4, 4, 3))
        self.assertEqual(cage.regions, {"cap": [0, 1]})

    def test_stage_file_is_a_stream_stage(self):
        tmp = Path(tempfile.mkdtemp())
        P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        T = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.uint32)
        f = tmp / "stage_002.bin"
        f.write_bytes(b"FMS1" + struct.pack("<III", 2, 4, 4) + P.tobytes() + T.tobytes())
        ev = meshsource.stage_event(f, "model_mesh:2:move", "move", of=5)
        self.assertEqual((ev["kind"], ev["index"], ev["of"], ev["triangles"]), ("stage", 3, 5, 4))
        self.assertTrue(np.array_equal(np.frombuffer(base64.b64decode(ev["positions"]), np.float32).reshape(-1, 3), P))
        # the same dict the kernel streams: Studio._draft_sink writes it where /api/drafts and Store.showStage read it
        from form.studio import Studio
        acts = []
        fake = types.SimpleNamespace(root=tmp, _prune_drafts=Studio._prune_drafts,
                                     activity=lambda *a, **k: acts.append((a, k)))
        Studio._draft_sink(fake, "draft-ab12", "Proj")(ev)
        d = json.loads((tmp / ".cache" / "drafts" / "draft-ab12.json").read_text())
        self.assertEqual(d["mesh"][0]["indices"], ev["indices"])
        self.assertEqual(d["feature"], "model_mesh:2:move")
        self.assertEqual(len(acts), 1)
        f.write_bytes(f.read_bytes()[:-4])
        with self.assertRaises(ValueError):
            meshsource.read_stage(f)


@unittest.skipUnless(HAS_BLENDER, BLENDER["reason"] or "Blender is not installed")
class WithBlender(unittest.TestCase):
    def test_replay_gives_the_same_cage(self):
        evs = []
        a = bm.run_ops(MODEL, on_stage=evs.append)
        for _ in range(3):        # some bmesh operators order output by memory address; the runner sorts it out
            b = bm.run_ops(MODEL)
            self.assertEqual(a["hash"], b["hash"])
            self.assertEqual(a["key"], b["key"])
            self.assertEqual(a["cage"].full_hash(), b["cage"].full_hash())
        c = a["cage"]
        self.assertTrue(c.is_quads())
        self.assertEqual(c.open_edges(), 0)
        self.assertIn("top", c.regions)
        self.assertGreater(len(c.creases), 0)
        self.assertEqual([e["feature"] for e in evs], [f"model_mesh:{i}:{o['op']}" for i, o in enumerate(MODEL)])
        self.assertEqual(a["stages"], len(MODEL))
        for e in evs:                                  # level 2: each cage quad is 16 quads, 32 triangles
            self.assertEqual(e["triangles"] % 32, 0)

    def test_numpy_catmull_clark_matches_blender_level_3(self):
        for ops in (CUBE, MODEL, [{"op": "cage_new", "primitive": "quad_sphere", "radius": 30, "segments": 3}]):
            r = bm.run_ops(ops, export_subdiv=3)
            V, F = r["cage"].V, r["cage"].F
            for _ in range(3):
                V, F = subd.catmull_clark(V, F)
            B = np.array(r["subdiv"]["V"])
            self.assertEqual(len(B), len(V))
            self.assertLessEqual(max_rel(V, B), 1e-4)

    def test_every_op_runs(self):
        ops = MODEL + [{"op": "geonodes_array", "count": 3, "offset": [40, 0, 0]},
                       {"op": "geonodes_scatter", "count": 20, "seed": 3, "item_size": 1, "scale": [0.5, 1.5]},
                       {"op": "remesh", "mode": "voxel", "voxel_size": 2},
                       {"op": "remesh", "mode": "quad", "target_faces": 600}]
        r = bm.run_ops(ops)
        self.assertEqual([o["op"] for o in r["ops"]], [o["op"] for o in ops])
        self.assertGreater(len(r["cage"].F), 100)

    def test_model_mesh_streams_drafts_and_keeps_the_ops(self):
        from form.studio import Studio
        root = Path(tempfile.mkdtemp())
        acts = []
        st = types.SimpleNamespace(root=root, cfg={}, load=lambda pid: {"head": 2, "name": "Proj"},
                                   _prune_drafts=Studio._prune_drafts, activity=lambda *a, **k: acts.append(k))
        st._draft_sink = lambda draft, name="": Studio._draft_sink(st, draft, name)
        out = bm.model_mesh(st, "proj", MODEL, expect_head=2)
        d = json.loads((root / ".cache" / "drafts" / f"{out['draft']}.json").read_text())
        self.assertEqual(d["feature"], f"model_mesh:{len(MODEL) - 1}:sculpt_ops")
        self.assertEqual(len(acts), len(MODEL))
        keep = root / ".cache" / "model_mesh" / out["key"]
        self.assertEqual(json.loads((keep / "ops.json").read_text()), bm.validate_ops(MODEL))
        self.assertEqual(meshsource.CageData.load(keep / "cage.json").hash(), out["hash"])
        ns = {}
        exec(out["source"], {}, ns)                     # the returned design source rebuilds the same cage
        self.assertEqual(ns["CAGE"].hash(), out["hash"])

    def test_a_failing_op_is_named(self):
        with self.assertRaises(bl.BlenderFailed) as cm:
            bm.run_ops(CUBE + [{"op": "loop_cut", "edge": [0, 7], "cuts": 1}])
        self.assertIn("op 1 (loop_cut)", str(cm.exception))

    def test_real_blender_timeout(self):
        with self.assertRaises(bl.BlenderFailed) as cm:
            bm.run_ops(CUBE, timeout=0.05)
        self.assertIn("was stopped", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
