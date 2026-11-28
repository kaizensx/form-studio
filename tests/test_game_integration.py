"""WP5 integration: model_mesh and game_asset on the MCP server (model_mesh's stages reach the app as a draft), the
purpose "game" everywhere a purpose is offered, Unreal collision names after the exported LOD0 mesh, the baked
normal-map check, the app's game routes (form/game/app.py), the packaged subd API in form.craft, and the cage design
source. No Blender, no network: Blender runs are stubbed."""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")


def tools():
    from form import mcp_server
    return {t.name: t for t in asyncio.run(mcp_server.build().list_tools())}


class Wiring(unittest.TestCase):
    def test_both_tools_are_registered(self):
        t = tools()
        self.assertIn("model_mesh", t)
        self.assertIn("game_asset", t)
        self.assertEqual(len(t), 145)  # prepare_recipe_submission retired; edit_design, triage, mass_properties, the Bench (3), sketches (2), strength_study, get_strength_study, calculate, manufacturability (2), sheet metal (4), drawing, export_pmi, check_drawing, standard_part, bom, motion_study, robot_files, assembly_sequence, cam_plan, cam_post, cam_simulate, board_import, board_check, board_fab and freecad_partdesign added; print physics (3); inverse design (2) and topology (3); cost_compare and cost_rates; tolerance_stack, get_tolerance_stack; test_plan, results_report and backup; board_schematic, board_place and board_route
        self.assertIn("hybrid", t["design_guide"].description)
        self.assertIn("game", t["design_guide"].description)
        self.assertIn("route", t["plan_design"].description)

    def test_model_mesh_streams_its_stages_to_the_app_as_a_draft(self):
        from form import mcp_server, meshsource
        from form.adapters import blender_model
        data = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"FORM_DATA": str(data), "FORM_CONFIG": str(data / "studio.toml")}):
            mcp_server.S["studio"] = None
            try:
                st = mcp_server.studio()
                p = st.create("Box", "storage_box", purpose="model")
                V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)

                def fake_run_ops(norm, cfg=None, timeout=0, on_stage=None, keep_dir=None, **kw):
                    P = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], np.float32)
                    on_stage({"kind": "stage", "feature": "model_mesh:0:cage_new", "index": 1, "at": 1, "of": 1,
                              "label": "cage new", "positions": base64.b64encode(P.tobytes()).decode(),
                              "indices": base64.b64encode(np.array([0, 1, 2], np.uint32).tobytes()).decode(),
                              "bbox": [[0, 0, 0], [10, 10, 0]], "triangles": 1})
                    return {"cage": meshsource.CageData(V, [[0, 1, 2, 3]]), "hash": "h", "key": "k" * 16,
                            "ops": [0.1], "stages": 1, "blender": "5.2.3", "seconds": 0.1}
                with mock.patch.object(blender_model, "run_ops", fake_run_ops):
                    m = mcp_server.build()
                    res = asyncio.run(m.call_tool("model_mesh", {"project": p["id"], "ops": [
                        {"op": "cage_new", "primitive": "cube", "size": [10, 10, 10]}], "expect_head": p["head"]}))
                text = "".join(getattr(c, "text", "") for c in res.content)
                out = json.loads(text)
                self.assertTrue(out["draft"].startswith("draft-"), out)
                d = st.draft(out["draft"])
                self.assertIsNotNone(d, "the stage was written as a draft the app draws (/api/drafts)")
                self.assertEqual(d["feature"], "model_mesh:0:cage_new")
                self.assertTrue(any(e.get("draft") == out["draft"] for e in st.activity_since(0)),
                                "and named in the activity log")
            finally:
                try:
                    mcp_server.studio().kernel.stop()
                except Exception:
                    pass
                mcp_server.S["studio"] = None

    def test_new_subd_api_is_in_craft(self):
        from form import craft
        from form.craft import subd
        for n in ("region_frame", "region_tool", "subdivide", "limit_points", "voxel_cage", "Cage"):
            self.assertIs(getattr(craft, n), getattr(subd, n), n)


class Purpose(unittest.TestCase):
    def test_game_is_offered_everywhere(self):
        from form import chat, purpose, server, start
        self.assertIn("game", start.PURPOSES)
        self.assertIn("game", server.start_purposes())
        self.assertIn("game_asset", start.purpose_line("game", None))
        self.assertIn('"game"', chat.SYSTEM if hasattr(chat, "SYSTEM") else Path(chat.__file__).read_text())
        self.assertEqual(purpose.normalise("Game asset"), "game")

    def test_studio_creates_and_switches_to_game(self):
        from form import config
        from form.studio import Studio, StudioError
        data = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"FORM_DATA": str(data), "FORM_CONFIG": str(data / "studio.toml")}):
            st = Studio(config.load())
            try:
                p = st.create("Box", "storage_box", purpose="game")
                self.assertEqual(p["purpose"], "game")
                self.assertIn("game asset", p["decisions"][-1]["text"])
                self.assertEqual(st.slice_mode(p)["why"], "purpose")
                self.assertIn("game asset", st.slice_mode(p)["text"])
                with self.assertRaises(StudioError) as cm:
                    st.create("Box", "storage_box", purpose="toy")
                self.assertIn("game", cm.exception.hint)
            finally:
                st.kernel.stop()


class UnrealCollision(unittest.TestCase):
    def test_hulls_are_named_after_the_exported_lod0_mesh(self):
        from form import design_guide
        from form.game import presets as pz
        pre = pz.preset("unreal")
        for asset in ("Chest", "Wall_kit_A"):
            lod0 = pz.lod_name(asset, 0)
            self.assertEqual(pz.collision_name(pre, asset, 0), f"UCX_{lod0}_00")
            self.assertEqual(pz.collision_name(pre, asset, 12), f"UCX_{lod0}_12")
        self.assertIn("UCX_<asset>_LOD0_00", design_guide.GAME)
        self.assertNotIn("named UCX_<asset>.", design_guide.GAME)


class NormalMap(unittest.TestCase):
    def test_inward_texels_are_measured(self):
        from form.game import validate
        rgb = np.zeros((64, 64, 3))
        rgb[..., 0] = rgb[..., 1] = 0.5
        rgb[..., 2] = 1.0
        rgb[:, 32:, 2] = 0.0                           # the right half: olive, the normal points into the surface
        UV = np.array([[0, 0], [0.5, 0], [0.5, 1], [0, 1], [0.5, 0], [1, 0], [1, 1], [0.5, 1]], float)
        T = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
        r = validate.normal_map_inward(rgb, UV, T)
        self.assertAlmostEqual(r["fraction"], 0.5, places=2)
        self.assertEqual(r["triangles"], 2)
        good = validate.normal_map_inward(rgb[:, :32].repeat(2, axis=1), UV, T)
        self.assertEqual(good["fraction"], 0.0)
        buf = io.BytesIO()
        from PIL import Image
        Image.fromarray((rgb * 255).astype(np.uint8)).save(buf, "PNG")
        c = validate.normal_map_check(buf.getvalue(), UV, T)
        self.assertEqual(c["status"], "FAIL")
        self.assertEqual(c["id"], "normal_map")

    def test_the_runner_bakes_surfaces_exploded(self):
        src = (ROOT / "form" / "adapters" / "blender_game.py").read_text(encoding="utf-8")
        self.assertIn("def explode(high, low, spacing)", src)
        a, n, e = src.index('bake("ao"'), src.index('bake("normal"'), src.index("restore, moved = explode(")
        self.assertLess(a, e, "AO is baked with the parts in place")
        self.assertLess(e, n, "the normal map is baked exploded")


class AppRoutes(unittest.TestCase):
    def fake_asset(self, root: Path) -> str:
        key = "0123456789abcdef"
        d = root / ".cache" / "game" / key
        (d / "lods").mkdir(parents=True)
        (d / "textures").mkdir()
        P = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]], np.float32)   # a seam: point 4 = point 0
        T = np.array([[0, 1, 2], [4, 2, 3]], np.int64)
        np.savez(d / "lods" / "lod0.npz", P=P, N=np.zeros_like(P), UV=np.zeros((5, 2), np.float32), T=T)
        (d / "textures" / "Box_normal.png").write_bytes(b"\x89PNG")
        (d / "report.json").write_text(json.dumps({"asset": "Box", "preset": {"id": "unreal"}, "pivot_offset_mm": [0, 0, 0],
                                                   "lods": [{"lod": 0, "triangles": 2, "budget": 10, "source": "s"}]}))
        return key

    def test_lod_wire_textures_and_zip(self):
        from form.game import app
        from form.studio import StudioError
        root = Path(tempfile.mkdtemp())
        st = mock.Mock(root=root)
        key = self.fake_asset(root)
        m = app.lod(st, key, 0)
        self.assertEqual(m["triangles"], 2)
        self.assertEqual(m["edges"], 5, "the shared diagonal is drawn once, across the seam")
        self.assertEqual(len(base64.b64decode(m["wire"])), 5 * 2 * 3 * 4)
        self.assertEqual(app.textures(st, key), {"normal": str(root / ".cache" / "game" / key / "textures" / "Box_normal.png")})
        self.assertEqual(app.texture(st, key, "normal"), b"\x89PNG")
        data, name = app.archive(st, key)
        self.assertEqual(name, "Box-unreal.zip")
        self.assertIn("Box-unreal/report.json", zipfile.ZipFile(io.BytesIO(data)).namelist())
        for bad in ("../../etc", "zz", key[:-1] + "g"):
            with self.assertRaises(StudioError):
                app.lod(st, bad, 0)
        with self.assertRaises(StudioError):
            app.texture(st, key, "../report")


class CageSource(unittest.TestCase):
    def test_split_and_source_keep_every_part(self):
        from form import meshsource
        from form.game import pipeline
        a = meshsource.cage(np.eye(3).tolist() + [[1, 1, 1]], [[0, 1, 3, 2]], [], {"lid": [0]})
        two = pipeline.merge_cages([a, meshsource.cage((np.array(a.V) + 5).tolist(), [[0, 1, 3, 2]], [[0, 1, 1.0]], {})])
        parts = pipeline.split_cage(two)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].regions, {"lid": [0]})
        self.assertEqual(parts[1].creases, [[0, 1, 1.0]])
        src = pipeline.cage_design_source(two, "Two")
        back = pipeline.merge_cages(pipeline.cages_in_source(src))
        self.assertEqual(back.full_hash(), two.full_hash(), "game_asset reads back exactly the cage the design builds")

    def test_blender_crease_weights_map_to_subd_sharpness(self):
        from form import meshsource
        s = meshsource.subd_creases([[0, 1, 1.0], [2, 1, 0.5], [3, 4, 0.0]])
        self.assertEqual(s[(0, 1)], float("inf"))
        self.assertAlmostEqual(s[(1, 2)], 2.5)
        self.assertNotIn((3, 4), s)


if __name__ == "__main__":
    unittest.main()
