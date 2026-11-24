"""Game purpose and pipeline: purpose aliases, presets, LOD plan, the GLB writer, the pure-numpy validator against
seeded defects, the fixed runner's safety, option checks before Blender starts, collision hulls, the CoACD engine row,
and (with Blender installed) one end-to-end build.

Everything except the end-to-end build runs without Blender."""
import ast
import asyncio
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from form import meshio, meshsource, purpose
from form.adapters import blender as bl
from form.game import lod, pipeline, presets, validate

BLENDER = bl.resolve({})
HAS_BLENDER = BLENDER["available"]
RUNNER = Path(pipeline.RUNNER)


# ---- fixtures ------------------------------------------------------------------------------------------------------

def uv_cube(n: int = 6, size_mm: float = 100.0):
    """A closed cube, n x n quads per side, each side its own UV island in a 3 x 2 atlas (0.3 wide cells inside 1/3
    slots). Returns (P mm, N, UV, T, island id per triangle). Points are split per side (UV seams), as in a GLB."""
    P, N, UV, T, isl = [], [], [], [], []
    axes = [(0, 1, 2, 1), (0, 1, 2, -1), (1, 2, 0, 1), (1, 2, 0, -1), (2, 0, 1, 1), (2, 0, 1, -1)]
    g = np.linspace(-0.5, 0.5, n + 1)
    for s, (a, b, c, sign) in enumerate(axes):
        base = len(P)
        for j in range(n + 1):
            for i in range(n + 1):
                p = np.zeros(3)
                p[a], p[b], p[c] = g[i], g[j], 0.5 * sign
                P.append(p * size_mm)
                nn = np.zeros(3)
                nn[c] = sign
                N.append(nn)
                cx, cy = (s % 3) / 3 + 0.02, (s // 3) / 2 + 0.02
                UV.append([cx + 0.29 * i / n, cy + 0.29 * j / n])
        for j in range(n):
            for i in range(n):
                q = [base + j * (n + 1) + i, base + j * (n + 1) + i + 1, base + (j + 1) * (n + 1) + i + 1,
                     base + (j + 1) * (n + 1) + i]
                t1, t2 = [q[0], q[1], q[2]], [q[0], q[2], q[3]]
                if sign < 0:
                    t1, t2 = t1[::-1], t2[::-1]
                T += [t1, t2]
                isl += [s, s]
    P, N, UV, T = np.array(P), np.array(N), np.array(UV), np.array(T)
    # outward winding check: a, b, c right-handed for +sign
    v = np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])).sum()
    if v < 0:
        T = T[:, ::-1]
    return P, N, UV, T, np.array(isl)


def cube_glb(P, N, UV, T, budgets=(10_000,), extra_nodes=()):
    gl = presets.preset("gltf")
    nodes = [{"name": "Box_LOD0", "P": presets.to_engine(P, gl), "N": presets.to_engine(N, {"scale": 1, "up": "Y"}),
              "UV": np.c_[UV[:, 0], 1 - UV[:, 1]], "idx": T, "material": 0}]
    return meshio.glb_scene(nodes + list(extra_nodes), [{"name": "M", "base_color": [1, 1, 1, 1]}])


def box_cage(lo, hi, regions_name=None):
    """A closed 6-quad box cage, outward faces."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    V = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return V, F


def grid_box_cage(lo, hi, n=3):
    """A closed box cage with n x n quads on every side (outward faces) and a "top" region."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    ids, V, F, top = {}, [], [], []

    def pid(i, j, k):
        if (i, j, k) not in ids:
            ids[(i, j, k)] = len(V)
            V.append(lo + (hi - lo) * np.array([i, j, k]) / n)
        return ids[(i, j, k)]
    for a in range(n):
        for b in range(n):
            F.append([pid(a, b, 0), pid(a, b + 1, 0), pid(a + 1, b + 1, 0), pid(a + 1, b, 0)])
            top.append(len(F))
            F.append([pid(a, b, n), pid(a + 1, b, n), pid(a + 1, b + 1, n), pid(a, b + 1, n)])
            F.append([pid(a, 0, b), pid(a + 1, 0, b), pid(a + 1, 0, b + 1), pid(a, 0, b + 1)])
            F.append([pid(a, n, b), pid(a, n, b + 1), pid(a + 1, n, b + 1), pid(a + 1, n, b)])
            F.append([pid(0, a, b), pid(0, a, b + 1), pid(0, a + 1, b + 1), pid(0, a + 1, b)])
            F.append([pid(n, a, b), pid(n, a + 1, b), pid(n, a + 1, b + 1), pid(n, a, b + 1)])
    return meshsource.cage(np.array(V), F, [], {"top": top})


# ---- purpose ----------------------------------------------------------------------------------------------------

class Purpose(unittest.TestCase):
    def test_game_purpose_and_aliases(self):
        self.assertIn("game", purpose.PURPOSES)
        for s in ("game", "Game asset", "game-asset", "asset de jogo", "Unity", "unreal", "godot", "realtime"):
            self.assertEqual(purpose.normalise(s), "game", s)
        self.assertEqual(purpose.normalise("model"), "model")
        self.assertEqual(purpose.normalise("print"), "print")
        self.assertIsNone(purpose.normalise("teapot"))

    def test_print_checks_do_not_apply_and_model_is_unchanged(self):
        g = {"purpose": "game"}
        self.assertTrue(purpose.is_model(g))          # not printed: the model path for checks, no slicing
        self.assertTrue(purpose.is_game(g))
        d = purpose.describe(g)
        self.assertEqual(d["purpose"], "game")
        self.assertEqual(len(d["not_applicable"]), len(purpose.PRINT_ONLY))
        m = purpose.describe({"purpose": "model"})
        self.assertEqual(m["purpose"], "model")
        self.assertIn("process", m)
        self.assertFalse(purpose.is_game({"purpose": "model"}))
        self.assertFalse(purpose.is_model({"purpose": "print"}))
        self.assertEqual(purpose.of({}), "print")


# ---- presets, LOD plan ------------------------------------------------------------------------------------------

class Presets(unittest.TestCase):
    def test_presets(self):
        self.assertEqual(presets.preset("unreal")["unit"], "cm")
        self.assertEqual(presets.collision_name(presets.preset("unreal"), "Chest", 0), "UCX_Chest_LOD0_00")
        self.assertTrue(presets.collision_name(presets.preset("godot"), "Chest", 1).endswith("-convcolonly"))
        with self.assertRaises(ValueError):
            presets.preset("cryengine")

    def test_budgets(self):
        self.assertEqual(presets.budgets(None), list(presets.DEFAULT_BUDGETS))
        self.assertEqual(presets.budgets({"LOD0": 100, "LOD1": 50}), [100, 50])
        for bad in ([100, 200], [5], [1.5], ["10"], [True], [], [1, 2, 3, 4, 5]):
            with self.assertRaises(ValueError, msg=bad):
                presets.budgets(bad)

    def test_axes_round_trip(self):
        P = np.array([[10.0, 20.0, 30.0]])
        g = presets.preset("gltf")
        self.assertTrue(np.allclose(presets.to_engine(P, g), [[0.01, 0.03, -0.02]]))
        for k in presets.PRESETS:
            self.assertTrue(np.allclose(presets.from_engine(presets.to_engine(P, presets.preset(k)), presets.preset(k)), P))

    def test_pivot(self):
        P = np.array([[0, 0, 5], [10, 20, 15.0]])
        self.assertTrue(np.allclose(presets.pivot_offset(P, "bottom_center"), [-5, -10, -5]))
        self.assertTrue(np.allclose(presets.pivot_offset(P, "center"), [-5, -10, -10]))

    def test_lod_plan_prefers_cage_levels(self):
        _V, F = box_cage((0, 0, 0), (1, 1, 1))     # 6 quads -> 24 quads at level 1
        self.assertEqual([lod.level_tris(F, L) for L in range(4)], [12, 48, 192, 768])
        plan = lod.plan_lods(F, [768, 200, 100, 12])
        self.assertEqual([(p["level"], p["decimate"]) for p in plan], [(3, False), (2, False), (2, True), (0, False)])
        self.assertIn("automatic retopology", plan[2]["source"])
        self.assertIn("clean quads", plan[0]["source"])


# ---- GLB writer and the validator -----------------------------------------------------------------------------

class Validator(unittest.TestCase):
    def setUp(self):
        self.P, self.N, self.UV, self.T, self.isl = uv_cube()

    def check(self, data, budgets=(10_000,), **kw):
        return validate.validate(data, list(budgets), 1024, **kw)

    def test_good_asset_passes_everything(self):
        rep = self.check(cube_glb(self.P, self.N, self.UV, self.T), expect_size_mm=[100, 100, 100])
        self.assertTrue(rep["ok"], validate.failed(rep))
        self.assertEqual(rep["lods"][0]["triangles"], 6 * 6 * 6 * 2)
        self.assertEqual({c["id"] for c in rep["checks"]},
                         {"glb", "budget", "manifold", "normals", "uv_bounds", "uv_overlap", "texel", "scale"})

    def test_glb_round_trip_is_metres_y_up(self):
        g = validate.parse_glb(cube_glb(self.P, self.N, self.UV, self.T))
        n = g["nodes"][0]
        self.assertTrue(np.allclose(presets.from_engine(n["P"], presets.preset("gltf")), self.P, atol=1e-5))
        self.assertTrue(np.allclose(1 - n["UV"][:, 1], self.UV[:, 1], atol=1e-6))

    def seeded(self):
        P, N, UV, T, isl = self.P, self.N, self.UV, self.T, self.isl
        out = {}
        out["budget"] = (cube_glb(P, N, UV, T), {"budgets": (300,)})
        out["manifold"] = (cube_glb(P, N, UV, T[1:]), {})
        Tf = T.copy()
        Tf[:3] = Tf[:3, ::-1]
        out["normals"] = (cube_glb(P, N, UV, Tf), {})
        UVo = UV.copy()
        pts1 = np.unique(T[isl == 1])
        UVo[pts1] -= [1 / 3, 0]                    # island 1 lands on island 0
        out["uv_overlap"] = (cube_glb(P, N, UVo, T), {})
        UVb = UV.copy()
        pts5 = np.unique(T[isl == 5])
        UVb[pts5] += [0.0, 0.6]                    # island 5 leaves the square
        out["uv_bounds"] = (cube_glb(P, N, UVb, T), {})
        UVt = UV.copy()
        for s in (0, 1, 2):                        # three islands at 0.3 scale: texel density spread ~3.3
            pts = np.unique(T[isl == s])
            c = UVt[pts].mean(0)
            UVt[pts] = c + (UVt[pts] - c) * 0.3
        out["texel"] = (cube_glb(P, N, UVt, T), {})
        good = cube_glb(P, N, UV, T)
        out["glb"] = (good[:-40], {})              # cut off: the header length no longer matches
        return out

    def test_catches_every_seeded_defect(self):
        caught = []
        for want, (data, kw) in self.seeded().items():
            rep = self.check(data, **kw)
            got = validate.failed(rep)
            self.assertIn(want, got, (want, got))
            if want != "glb":
                self.assertEqual(got, [want], f"{want}: only that check should fail, got {got}")
            caught.append(want)
        self.assertEqual(len(caught), 7)

    def test_corrupt_files_never_raise(self):
        good = cube_glb(self.P, self.N, self.UV, self.T)
        for bad in (b"", b"glTF" + bytes(30), good.replace(b"glTF", b"gltf", 1), good[:12] + b"\xff" * 20):
            rep = self.check(bad)
            self.assertFalse(rep["ok"])
            self.assertEqual(validate.failed(rep), ["glb"])

    def test_wrong_scale_is_caught(self):
        rep = self.check(cube_glb(self.P * 1000, self.N, self.UV, self.T), expect_size_mm=[100, 100, 100])
        self.assertIn("scale", validate.failed(rep))

    def test_collision_nodes_are_not_lods(self):
        hull = {"name": "UCX_Box_00", "P": presets.to_engine(self.P, presets.preset("gltf")), "idx": self.T}
        rep = self.check(cube_glb(self.P, self.N, self.UV, self.T, extra_nodes=[hull]))
        self.assertTrue(rep["ok"], validate.failed(rep))
        self.assertEqual(rep["collision"][0]["name"], "UCX_Box_00")
        self.assertEqual(len(rep["lods"]), 1)


# ---- the fixed runner and the option checks ---------------------------------------------------------------------

class RunnerSafety(unittest.TestCase):
    def test_runner_imports_no_network_or_process_modules_and_never_evaluates(self):
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        banned = {"socket", "urllib", "subprocess", "http", "requests", "ftplib", "smtplib", "ctypes", "importlib",
                  "multiprocessing", "asyncio", "webbrowser", "shutil", "pickle"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("exec", "eval", "compile", "__import__", "open_url"))
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                self.assertNotIn(node.attr, ("system", "popen", "spawnv", "execv", "execvp", "fork"))
        src = RUNNER.read_text(encoding="utf-8")
        self.assertIn("allow_pickle=False", src)
        self.assertNotIn("allow_pickle=True", src)

    def test_bad_options_are_refused_before_blender_starts(self):
        cage = meshsource.cage(*box_cage((0, 0, 0), (10, 10, 10)))
        bad = [dict(preset="cryengine"), dict(budgets=[10, 20]), dict(texture_px=3000), dict(bake="slow"),
               dict(pivot="top"), dict(uv="magic"), dict(collision="vhacd"), dict(formats=["blend"]),
               dict(retopo="instant")]
        with mock.patch.object(bl, "resolve", side_effect=AssertionError("Blender was resolved")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("a process was started")):
            for kw in bad:
                with self.assertRaises(pipeline.GameError, msg=kw):
                    pipeline.build({"cage": cage}, tempfile.mkdtemp(), **kw)
            for mats in ({"lid": {"finish": "matte"}}, {"default": {"finish": "chrome"}},
                         {"default": {"color": "red"}}, {"default": {"pattern": "python"}},
                         {"default": {"finish": "matte", "script": "x"}}):
                with self.assertRaises(pipeline.GameError, msg=mats):
                    pipeline.build({"cage": cage, "materials": mats}, tempfile.mkdtemp())
            V, F = box_cage((0, 0, 0), (1, 1, 1))
            with self.assertRaises(pipeline.GameError):                     # open cage
                pipeline.build({"cage": meshsource.cage(V, F[:-1])}, tempfile.mkdtemp())

    def test_cages_are_read_from_source_without_running_it(self):
        V, F = box_cage((0, 0, 0), (1, 2, 3))
        src = ("import os\nos.system('echo no')\nfrom form import meshsource\n"
               + meshsource.cage(V, F, [[0, 1, 1.0]], {"top": [1]}).literal()
               + "OTHER = meshsource.cage(V=make_points(), F=[])\n")
        with mock.patch("os.system", side_effect=AssertionError("source was executed")):
            cages = pipeline.cages_in_source(src)
        self.assertEqual(len(cages), 1)
        self.assertEqual(cages[0].regions, {"top": [1]})
        self.assertEqual(cages[0].creases, [[0, 1, 1.0]])

    def test_uv_method(self):
        V, F = box_cage((0, 0, 0), (1, 1, 1))
        closed = meshsource.cage(V, F, [], {"all": list(range(6))})
        self.assertEqual(pipeline.uv_method(closed)[0], "smart")           # a closed box is not a disc
        discs = meshsource.cage(V, F, [], {"top": [1], "bottom": [0], "band": [2, 3, 4, 5]})
        self.assertEqual(pipeline.uv_method(discs)[0], "smart")            # the band is an annulus
        ok = meshsource.cage(V, F, [], {"top": [1], "side": [2, 3, 4, 5, 0]})
        self.assertEqual(pipeline.uv_method(ok)[0], "regions")
        self.assertEqual(pipeline.uv_method(meshsource.cage(V, F))[0], "smart")


@unittest.skipIf(os.name == "nt", "the stand-in Blender is a shell script")
class Timeout(unittest.TestCase):
    def test_a_hung_blender_is_killed_and_nothing_is_written(self):
        tmp = Path(tempfile.mkdtemp())
        fake = tmp / "blender"
        fake.write_text("#!/bin/sh\nif [ \"$1\" = --version ]; then echo Blender 5.2.3; exit 0; fi\n"
                        "echo FORM_STEP started\nsleep 30\n", encoding="utf-8")
        fake.chmod(0o755)
        out = tmp / "asset"
        out.mkdir()
        (out / "keep.txt").write_text("before", encoding="utf-8")
        t0 = __import__("time").time()
        with self.assertRaises(bl.BlenderFailed) as cm:
            pipeline.build({"cage": grid_box_cage((0, 0, 0), (10, 10, 10))}, out, app=str(fake), timeout=1.5)
        self.assertLess(__import__("time").time() - t0, 20)
        self.assertIn("stopped", str(cm.exception))
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["keep.txt"])
        self.assertEqual([p.name for p in tmp.iterdir() if p.name.startswith("form-game-")], [])


class Collision(unittest.TestCase):
    def mesh(self, boxes):
        P, T = [], []
        for lo, hi in boxes:
            V, F = box_cage(lo, hi)
            o = len(P)
            P += V
            T += [[o + f[0], o + f[1], o + f[2]] for f in F] + [[o + f[0], o + f[2], o + f[3]] for f in F]
        return np.array(P, float), np.array(T)

    def test_a_hull_per_part(self):
        P, T = self.mesh([((0, 0, 0), (10, 10, 10)), ((20, 0, 0), (30, 10, 10))])
        parts = lod.convex_parts(P, T)
        self.assertEqual(len(parts), 2)
        for p in parts:
            self.assertAlmostEqual(p["volume_mm3"], 1000.0, places=6)
            self.assertLessEqual(len(p["V"]), lod.HULL_POINTS)

    def test_a_part_inside_another_hull_is_covered(self):
        P, T = self.mesh([((0, 0, 0), (100, 100, 100)), ((40, 40, 99), (60, 60, 100.5))])
        self.assertEqual(len(lod.convex_parts(P, T)), 1)

    def test_hull_points_are_capped(self):
        rng = np.random.default_rng(0)
        Q = rng.normal(size=(2000, 3))
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        V, H = lod.hull(Q * 50)
        self.assertLessEqual(len(V), lod.HULL_POINTS)
        c = V.mean(0)
        n = np.cross(V[H[:, 1]] - V[H[:, 0]], V[H[:, 2]] - V[H[:, 0]])
        self.assertTrue((np.einsum("ij,ij->i", n, V[H[:, 0]] - c) > 0).all())   # outward

    def test_coacd_missing_says_how_to_get_it(self):
        P, T = self.mesh([((0, 0, 0), (1, 1, 1))])
        with mock.patch("form.engines.python", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "one click"):
                lod.coacd_parts(P, T, {"data": {"dir": tempfile.mkdtemp()}})


class CoacdEngine(unittest.TestCase):
    def test_registry_row_and_pins(self):
        from form import engines, installer
        self.assertIn("game.coacd", engines.SPECS)
        self.assertTrue(all("==" in p for p in engines.SPECS["game.coacd"]["pins"]))
        row = next(s for s in installer.REGISTRY if s.id == "game.coacd")
        self.assertEqual(row.level, "optional")
        self.assertEqual(row.licence, "MIT")
        self.assertFalse(row.noncommercial)
        cfg = {"data": {"dir": tempfile.mkdtemp()}}
        with mock.patch.dict(os.environ, {"FORM_ENGINES_DIR": tempfile.mkdtemp()}):
            self.assertEqual(row.detect(cfg, {}).status, "missing")
            ms = row.methods("darwin", {"cfg": cfg})
        self.assertEqual(ms[0].kind, "action")
        self.assertTrue(any("coacd==" in c for c in ms[0].commands))


class Register(unittest.TestCase):
    def test_register_adds_game_asset(self):
        tools = {}

        class FakeMCP:
            def tool(self, name, **kw):
                def deco(fn):
                    tools[name] = fn
                    return fn
                return deco
        import form.game as game
        st = types.SimpleNamespace()
        with mock.patch.object(game, "game_asset", return_value={"ok": 1}) as ga:
            game.register(FakeMCP(), get_studio=lambda: st, run=lambda fn: asyncio.sleep(0, fn()))
            out = asyncio.run(tools["game_asset"]("p", action="validate", preset="godot"))
        self.assertEqual(out, {"ok": 1})
        self.assertEqual(ga.call_args.args[:4], (st, "p", "validate", "godot"))


def stub_studio(source_text: str):
    root = Path(tempfile.mkdtemp())
    p = {"id": "chest", "name": "Chest", "head": 3}
    return types.SimpleNamespace(root=root, cfg={}, load=lambda pid: dict(p), keys=lambda p: {"geometry": "g" * 16},
                                 source_text=lambda p: source_text)


class GameAssetTool(unittest.TestCase):
    def test_refusals_before_anything_runs(self):
        from form import game
        from form.studio import StudioError
        st = stub_studio("")
        st.load = mock.Mock(side_effect=AssertionError("the project was read"))
        for kw in (dict(action="delete"), dict(preset="cry"), dict(budgets=[1, 2]), dict(texture_px=7)):
            with self.assertRaises(StudioError, msg=kw):
                game.game_asset(st, "chest", **kw)

    def test_validate_before_build_is_404(self):
        from form import game
        from form.studio import StudioError
        with self.assertRaises(StudioError) as cm:
            game.game_asset(stub_studio(""), "chest", action="validate")
        self.assertEqual(getattr(cm.exception, "status", None), 404)


# ---- end to end, with Blender ----------------------------------------------------------------------------------

@unittest.skipUnless(HAS_BLENDER and os.environ.get("FORM_TEST_GAME_BLENDER", "1") != "0", "needs Blender")
class EndToEnd(unittest.TestCase):
    def test_small_cage_asset(self):
        cage = grid_box_cage((-20, -15, 0), (20, 15, 25))      # a 6-quad box is too coarse: its UVs, laid out on
        self.assertEqual(cage.open_edges(), 0)                   # the cage, measured a texel spread of 2.76
        out = Path(tempfile.mkdtemp()) / "asset"
        rep = pipeline.build({"cage": cage, "materials": {"default": {"finish": "matte", "color": "#7a4a26",
                                                                      "pattern": "wood"},
                                                          "top": {"finish": "metal", "color": "#c9a23a"}}},
                             out, asset="Crate", preset="unreal", budgets=[1500, 700, 300, 60], texture_px=1024,
                             formats=["usd"], timeout=600)
        v = rep["validation"]
        self.assertTrue(v["ok"], [c for c in v["checks"] if c["status"] != "PASS"])
        for r in rep["lods"]:
            self.assertLessEqual(r["triangles"], r["budget"] * 1.02)
        for li in v["lods"]:
            self.assertLessEqual(li["uv_overlap"], 0.005)
            self.assertEqual(li["uv_outside"], 0.0)
        self.assertGreater(rep["bake"]["total_seconds"], 0)
        self.assertEqual(sorted(rep["bake"]["files"]), ["ao", "base_color", "normal", "orm"])
        self.assertTrue((out / "Crate.glb").is_file() and (out / "Crate.fbx").is_file() and (out / "Crate.usd").is_file())
        self.assertTrue(rep["collision"]["names"][0].startswith("UCX_Crate_"))
        again = pipeline.revalidate(out)
        self.assertTrue(again["ok"])
        json.dumps(rep, default=float)

    def test_game_asset_tool_reads_the_cage_from_source_and_caches(self):
        from form import game
        src = "from form import meshsource\n" + grid_box_cage((0, 0, 0), (30, 20, 10)).literal()
        st = stub_studio(src)
        first = game.game_asset(st, "chest", budgets=[600, 300, 150, 40], preset="godot")
        self.assertFalse(first["cached"])
        self.assertTrue(first["validation"]["ok"], first["validation"]["failed"])
        self.assertTrue(Path(first["files"]["Chest.glb"]).is_file())
        again = game.game_asset(st, "chest", budgets=[600, 300, 150, 40], preset="godot")
        self.assertTrue(again["cached"])
        self.assertEqual(again["key"], first["key"])
        v = game.game_asset(st, "chest", action="validate", budgets=[600, 300, 150, 40], preset="godot")
        self.assertTrue(v["validation"]["ok"])


if __name__ == "__main__":
    unittest.main()
