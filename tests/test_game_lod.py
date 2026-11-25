"""LODs against LOD0 and the app's side of a bake: the pure-numpy fidelity measures (silhouette IoU from 8 views,
Hausdorff distance) on shapes whose answers are known, the checks they add to validate(), the LOD plan's levels, the
in-Blender decimation module's safety, and the bridge's game-build timeout, single flight and Blender clean-up on quit.

Nothing here needs Blender (the bench, scripts/game_bench.py, runs the six real assets)."""
import ast
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from form import meshio
from form.game import lod, pipeline, presets, validate

ROOT = Path(__file__).resolve().parents[1]
LOD_MODULE = ROOT / "form" / "adapters" / "blender_lod.py"


def uv_sphere(nu: int, nv: int, r: float = 100.0):
    """A closed UV sphere (Z up, outward triangles) with nu segments around and nv rings."""
    P = [[0, 0, -r]]
    for i in range(1, nv):
        th = np.pi * i / nv - np.pi / 2
        for j in range(nu):
            ph = 2 * np.pi * j / nu
            P.append([r * np.cos(th) * np.cos(ph), r * np.cos(th) * np.sin(ph), r * np.sin(th)])
    P.append([0, 0, r])
    P = np.array(P)
    T = [[0, 1 + (j + 1) % nu, 1 + j] for j in range(nu)]
    for i in range(nv - 2):
        for j in range(nu):
            a, b = 1 + i * nu + j, 1 + i * nu + (j + 1) % nu
            T += [[a, b, b + nu], [a, b + nu, a + nu]]
    top, base = len(P) - 1, 1 + (nv - 2) * nu
    T += [[base + j, base + (j + 1) % nu, top] for j in range(nu)]
    return P, np.array(T)


def lods_glb(meshes):
    """A GLB with one node per LOD (millimetres in, glTF metres, Y up out)."""
    gl = presets.preset("gltf")
    nodes = []
    for i, (P, T) in enumerate(meshes):
        n = P / np.linalg.norm(P, axis=1, keepdims=True)
        uv = np.c_[0.5 + np.arctan2(P[:, 1], P[:, 0]) / (2 * np.pi), 0.5 + P[:, 2] / 400.0] * 0.98 + 0.01
        nodes.append({"name": f"Ball_LOD{i}", "P": presets.to_engine(P, gl), "N": presets.to_engine(n, {"scale": 1, "up": "Y"}),
                      "UV": uv, "idx": T, "material": 0})
    return meshio.glb_scene(nodes, [{"name": "M", "base_color": [1, 1, 1, 1]}])


class Fidelity(unittest.TestCase):
    def test_point_triangle_distance_by_region(self):
        a, b, c = np.array([[0.0, 0, 0]]), np.array([[1.0, 0, 0]]), np.array([[0.0, 1, 0]])
        for p, want in (([0.2, 0.2, 3], 3), ([-1, -1, 0], np.sqrt(2)), ([0.5, -2, 0], 2), ([2, 0, 0], 1),
                        ([1, 1, 0], np.sqrt(0.5)), ([0, 3, 4], np.sqrt(20))):
            got = validate.point_triangle_distance(np.array([p], float), a, b, c)[0]
            self.assertAlmostEqual(got, want, places=9, msg=p)

    def test_identical_meshes_are_perfect(self):
        P, T = uv_sphere(48, 24)
        f = validate.lod_fidelity(P, T, P, T, up=2)
        self.assertEqual(f["iou_min"], 1.0)
        self.assertLess(f["hausdorff_rel"], 1e-9)
        self.assertEqual(len(f["views"]), 8)

    def test_coarser_spheres_score_lower_and_the_distance_is_the_faceting(self):
        P0, T0 = uv_sphere(96, 48)
        last_iou, last_h = 1.0, 0.0
        for nu in (48, 24, 12):
            P, T = uv_sphere(nu, nu // 2)
            f = validate.lod_fidelity(P0, T0, P, T, up=2)
            self.assertLess(f["iou_min"], last_iou)
            self.assertGreater(f["hausdorff_rel"], last_h)
            # a quad's centre sits inside the sphere by about twice an edge's sagitta (both directions)
            sag = 100 * (1 - np.cos(np.pi / nu) ** 2)
            self.assertLess(abs(f["hausdorff"] - sag) / sag, 0.25, (nu, f["hausdorff"], sag))
            last_iou, last_h = f["iou_min"], f["hausdorff_rel"]

    def test_a_missing_part_is_caught_by_both_measures(self):
        P, T = uv_sphere(32, 16)
        Q, U = uv_sphere(16, 8, r=40.0)
        Q = Q + [160, 0, 0]
        both = (np.r_[P, Q], np.r_[T, U + len(P)])
        f = validate.lod_fidelity(*both, P, T, up=2)
        self.assertLess(f["iou_min"], 0.9)
        self.assertFalse(np.isfinite(f["hausdorff_rel"]) and f["hausdorff_rel"] < 0.03)

    def test_a_shifted_plane_reads_its_offset(self):
        g = np.array([[x, y, 0.0] for y in range(11) for x in range(11)])
        T = np.array([[j * 11 + i, j * 11 + i + 1, (j + 1) * 11 + i + 1] for j in range(10) for i in range(10)] +
                     [[j * 11 + i, (j + 1) * 11 + i + 1, (j + 1) * 11 + i] for j in range(10) for i in range(10)])
        h = validate.hausdorff(g, T, g + [0, 0, 0.1], T, reach=1.0)
        self.assertAlmostEqual(h["max"], 0.1, places=6)

    def test_rasterise_fills_a_square_without_cracks(self):
        Q = np.array([[10.2, 10.2], [50.2, 10.2], [50.2, 50.2], [10.2, 50.2]])
        m = validate.rasterise(Q, np.array([[0, 1, 2], [0, 2, 3]]), 64)
        self.assertEqual(int(m.sum()), 40 * 40)

    def test_validate_adds_the_lod_checks(self):
        P0, T0 = uv_sphere(64, 32)
        P1, T1 = uv_sphere(32, 16)
        P2, T2 = uv_sphere(8, 4)
        rep = validate.validate(lods_glb([(P0, T0), (P1, T1), (P2, T2)]), [10000, 5000, 1000], 1024)
        by = {(c["id"], c.get("lod")): c for c in rep["checks"]}
        self.assertEqual(by[("lod_silhouette", 1)]["status"], "PASS", by[("lod_silhouette", 1)])
        self.assertEqual(by[("lod_distance", 1)]["status"], "PASS", by[("lod_distance", 1)])
        self.assertEqual(by[("lod_distance", 2)]["status"], "FAIL", by[("lod_distance", 2)])   # 8 sides: 4%
        self.assertNotIn(("lod_silhouette", 0), by)
        self.assertIn("fidelity", rep["lods"][1])
        self.assertGreaterEqual(rep["lods"][1]["fidelity"]["iou_min"], validate.LOD_IOU_MIN[1])

    def test_one_lod_has_no_fidelity_checks(self):
        P, T = uv_sphere(32, 16)
        rep = validate.validate(lods_glb([(P, T)]), [10000], 1024)
        self.assertFalse({"lod_silhouette", "lod_distance"} & {c["id"] for c in rep["checks"]})


class Plan(unittest.TestCase):
    def test_lod1_and_up_never_finer_than_lod0_and_never_the_bare_cage(self):
        F = [[0, 1, 2, 3]] * 6
        for budgets in ([768, 200, 100, 12], [3000, 700, 100, 13], [50, 40, 30, 12]):
            plan = lod.plan_lods(F, budgets)
            self.assertTrue(all(p["level"] >= 1 for p in plan), plan)
            self.assertTrue(all(p["level"] <= plan[0]["level"] for p in plan[1:]), plan)
            for p in plan[1:]:
                if not p["decimate"]:
                    self.assertGreaterEqual(p["level"], 2, p)

    def test_decimated_lods_start_dense(self):
        F = [[0, 1, 2, 3]] * 100                       # 400 quads at level 1: 800, 3200, 12800 triangles
        plan = lod.plan_lods(F, [12000, 3000, 1000, 300])
        self.assertEqual(plan[0]["level"], 3)
        for p in plan[1:]:
            if p["decimate"]:
                self.assertGreaterEqual(lod.level_tris(F, p["level"]), min(lod.DECIMATE_FROM * p["budget"],
                                                                          lod.level_tris(F, plan[0]["level"])), p)


class LodModuleSafety(unittest.TestCase):
    def test_blender_lod_imports_nothing_that_talks_or_spawns(self):
        tree = ast.parse(LOD_MODULE.read_text(encoding="utf-8"))
        banned = {"socket", "urllib", "subprocess", "http", "requests", "ftplib", "smtplib", "ctypes", "importlib",
                  "multiprocessing", "asyncio", "webbrowser", "shutil", "pickle", "os", "sys"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("exec", "eval", "compile", "__import__", "open"))

    def test_the_runner_hands_decimation_to_it(self):
        src = Path(pipeline.RUNNER).read_text(encoding="utf-8")
        self.assertIn("import blender_lod", src)
        self.assertIn("blender_lod.decimate_to(src, name, budget, globals())", src)
        self.assertEqual(LOD_MODULE.parent, Path(pipeline.RUNNER).parent)

    def test_packaged_with_the_runner(self):
        self.assertIn("blender_lod.py", (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8"))


try:
    import PySide6  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not installed")
class BridgeGameBuild(unittest.TestCase):
    def bridge(self):
        from form.app.bridge import Bridge
        b = Bridge("127.0.0.1", 9, tempfile.mkdtemp(), "test")
        started = []
        b.pool = type("Pool", (), {"start": lambda _self, call: started.append(call)})()
        return b, started

    def test_game_build_waits_longer_than_the_pipeline(self):
        from form.app import bridge
        b, started = self.bridge()
        b.request(1, "POST", "/projects/p1/game", {"action": "build", "preset": "gltf"})
        b.request(2, "GET", "/projects/p1", None)
        self.assertGreaterEqual(started[0].timeout, pipeline.TIMEOUT_S + 60)
        self.assertEqual(started[1].timeout, bridge.HTTP_TIMEOUT_S)

    def test_a_second_build_click_joins_the_first(self):
        b, started = self.bridge()
        got = []
        b.reply.connect(lambda rid, ok, obj: got.append((rid, ok)))
        body = {"action": "build", "preset": "gltf", "texture_px": 1024}
        b.request(1, "POST", "/projects/p1/game", body)
        b.request(2, "POST", "/projects/p1/game", dict(reversed(list(body.items()))))
        self.assertEqual(len(started), 1, "one Blender for one build")
        b.request(3, "POST", "/projects/p1/game", {**body, "preset": "unreal"})
        self.assertEqual(len(started), 2, "other options are another build")
        started[0].emit(True, {"key": "k"})
        self.assertEqual(sorted(got), [(1, True), (2, True)])
        b.request(4, "POST", "/projects/p1/game", body)
        self.assertEqual(len(started), 3, "after it landed, a new click builds again")

    @unittest.skipIf(os.name == "nt", "process groups are POSIX")
    def test_quitting_stops_blender_children(self):
        from form.app import bridge
        d = Path(tempfile.mkdtemp())
        fake = d / "blender"
        fake.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
        fake.chmod(0o755)
        other = subprocess.Popen(["sleep", "60"])
        p = subprocess.Popen([str(fake), "-b"], start_new_session=True)
        try:
            for _ in range(50):
                if p.pid in bridge.blender_children():
                    break
                time.sleep(0.05)
            self.assertIn(p.pid, bridge.blender_children())
            self.assertNotIn(other.pid, bridge.blender_children())
            self.assertIn(p.pid, bridge.kill_blender_children())
            self.assertIsNotNone(p.wait(timeout=10))
            self.assertIsNone(other.poll(), "only Blender is stopped")
        finally:
            for q in (p, other):
                if q.poll() is None:
                    q.kill()
                    q.wait()


if __name__ == "__main__":
    unittest.main()


class HullIndices(unittest.TestCase):
    def test_hull_triangles_index_the_hull_points(self):
        """Regression: with fewer hull points than the cap, the triangles indexed the input points (IndexError)."""
        import numpy as np
        from form.game import lod
        rng = np.random.default_rng(3)
        P = np.vstack([rng.normal(size=(200, 3)) * [30, 20, 10], [[0, 0, 0]]])
        V, T = lod.hull(P)
        self.assertLess(int(T.max()), len(V))
        T2 = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]])
        P2 = np.vstack([rng.normal(size=(40, 3)), [[5, 5, 5]]])
        parts = lod.convex_parts(P2, np.vstack([T2, T2 + 4, T2 + 8]))
        for p in parts:
            self.assertLess(int(p["T"].max()), len(p["V"]))
