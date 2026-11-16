"""Blender integration: job generation, camera framing, running Blender safely, and real renders when it is installed."""
import json
import math
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

from form import config
from form.adapters import blender as bl

BLENDER = bl.resolve({})
HAS_BLENDER = BLENDER["available"]


def cube_stl(path: Path, lo=(10, 20, 5), size=(20, 10, 30)):
    """A binary STL box (12 triangles)."""
    x0, y0, z0 = lo
    x1, y1, z1 = x0 + size[0], y0 + size[1], z0 + size[2]
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
             (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    data = b"\0" * 80 + struct.pack("<I", len(faces))
    for f in faces:
        data += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in f) + b"\0\0"
    path.write_bytes(data)
    return path


def fake_blender(tmp: Path, body: str) -> str:
    """An executable that stands in for Blender (POSIX only): a shell wrapper around a Python script."""
    py = tmp / "fake_blender.py"
    py.write_text("import sys, json, time\n" + body, encoding="utf-8")
    f = tmp / "fake-blender"
    f.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
    f.chmod(0o755)
    return str(f)


class Numbers(unittest.TestCase):
    def test_srgb_to_linear(self):
        self.assertEqual(bl.hex_to_linear("#000000"), [0, 0, 0])
        self.assertAlmostEqual(bl.hex_to_linear("#ffffff")[0], 1.0)
        self.assertAlmostEqual(bl.hex_to_linear("#808080")[1], 0.2158, places=3)
        with self.assertRaises(ValueError):
            bl.hex_to_linear("blue")

    def test_view_direction_matches_the_app(self):
        # the app's viewport puts the camera at -Y for azimuth 0, +X for azimuth 90, straight up at elevation 90
        for (az, el), want in (((0, 0), (0, -1, 0)), ((90, 0), (1, 0, 0)), ((0, 90), (0, 0, 1))):
            d = bl.view_dir(az, el)
            for a, b in zip(d, want):
                self.assertAlmostEqual(a, b, places=9)
        d = bl.view_dir(*bl.APP_ISO)
        self.assertLess(d[0], 0)          # front-left, from above
        self.assertLess(d[1], 0)
        self.assertGreater(d[2], 0)

    def test_framing_fits_every_corner_and_is_tight(self):
        for lo, hi in (([-40, -45, 0], [40, 45, 35]), ([-5, -5, 0], [5, 5, 120]), ([-90, -10, 0], [90, 10, 4])):
            cam = bl.frame_camera(lo, hi, fill=0.7)
            self.assertLessEqual(cam["reach"], 0.7 + 1e-9)
            self.assertGreater(cam["reach"], 0.69)              # one corner touches the margin
            c = cam["target"]
            d = [(a - b) / cam["distance"] for a, b in zip(cam["location"], c)]
            for a, b in zip(d, bl.view_dir(*bl.APP_ISO)):
                self.assertAlmostEqual(a, b, places=9)
            self.assertAlmostEqual(cam["hfov_deg"], math.degrees(2 * math.atan(18 / bl.LENS_MM)))

    def test_bigger_part_moves_the_camera_back_proportionally(self):
        a = bl.frame_camera([-10, -10, 0], [10, 10, 10])
        b = bl.frame_camera([-100, -100, 0], [100, 100, 100])
        self.assertAlmostEqual(b["distance"] / a["distance"], 10, places=6)


class Jobs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stl = cube_stl(self.tmp / "box.stl")

    def test_stl_bounds_binary_and_ascii(self):
        lo, hi = bl.stl_bounds(self.stl)
        self.assertEqual([round(x, 4) for x in lo], [10, 20, 5])
        self.assertEqual([round(x, 4) for x in hi], [30, 30, 35])
        a = self.tmp / "a.stl"
        a.write_text("solid t\nfacet normal 0 0 1\nouter loop\nvertex -1 2 3\nvertex 4 -5 6\nvertex 0 0 9\n"
                     "endloop\nendfacet\nendsolid t\n", encoding="utf-8")
        self.assertEqual(bl.stl_bounds(a), ([-1, -5, 3], [4, 2, 9]))

    def test_job_places_the_part_on_the_floor_in_metres(self):
        j = bl.build_job(self.stl, self.tmp / "o.png", "dark", "silk", "#3d6fb6", layer_mm=0.2)
        self.assertEqual(j["offset_mm"], [-20.0, -25.0, -5.0])          # centred in XY, bottom at z = 0
        self.assertAlmostEqual(j["size_m"], 0.030)
        self.assertEqual(j["camera"]["target"], [0.0, 0.0, 0.015])
        self.assertEqual(j["engine"], "cycles")
        self.assertEqual(j["finish"]["id"], "silk")
        self.assertEqual(j["layer_mm"], 0.2)
        self.assertEqual(j["resolution"], [1600, 1200])
        json.dumps(j)                                                   # it is written as a job file

    def test_job_options(self):
        j = bl.build_job(self.stl, self.tmp / "o.png", fast=True, layer_mm=5.0)
        self.assertEqual(j["engine"], "eevee")
        self.assertIsNone(j["layer_mm"])                                # not a plausible layer height
        with self.assertRaises(ValueError):
            bl.build_job(self.stl, self.tmp / "o.png", preset="beach")
        with self.assertRaises(ValueError):
            bl.build_job(self.stl, self.tmp / "o.png", finish="wood")

    def test_scene_script_is_valid_python_and_reads_the_job(self):
        src = bl.SCENE_SCRIPT.read_text(encoding="utf-8")
        compile(src, str(bl.SCENE_SCRIPT), "exec")
        for k in ("FORM_RESULT", "offset_mm", "layer_mm", "render_stats", "OPENIMAGEDENOISE"):
            self.assertIn(k, src)

    def test_missing_blender_says_where_to_get_it(self):
        r = bl.resolve({"blender": {"app": str(self.tmp / "no-such-blender")}})
        if r["available"]:                   # a real Blender elsewhere on this machine wins; that is fine
            return
        self.assertIn("blender.org", r["reason"])


@unittest.skipIf(sys.platform.startswith("win"), "the stand-in Blender is a POSIX script")
class Running(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stl = cube_stl(self.tmp / "box.stl")
        self.job = bl.build_job(self.stl, self.tmp / "out.png")

    def test_timeout_kills_blender(self):
        app = fake_blender(self.tmp, "print('warming up', flush=True)\ntime.sleep(60)\n")
        t0 = time.time()
        with self.assertRaises(bl.BlenderFailed) as cm:
            bl.run_job(app, self.job, self.tmp / "job.json", timeout=1.5)
        self.assertLess(time.time() - t0, 15)
        self.assertIn("did not finish within 2 s", str(cm.exception))
        self.assertIn("warming up", cm.exception.log)

    def test_failure_reports_the_log_tail(self):
        app = fake_blender(self.tmp, "print('Error: no such operator', flush=True)\n"
                                     "print('FORM_RESULT ' + json.dumps({'ok': False, 'error': 'boom'}))\nsys.exit(3)\n")
        with self.assertRaises(bl.BlenderFailed) as cm:
            bl.run_job(app, self.job, self.tmp / "job.json", timeout=20)
        self.assertIn("boom", str(cm.exception))
        self.assertIn("no such operator", cm.exception.log)

    def test_progress_and_result(self):
        body = ("job = json.load(open(sys.argv[-1]))\n"
                "for i in (1, 5, 10): print(f'FORM_STATS Mem: 1M | Sample {i}/10', flush=True)\n"
                "open(job['out'], 'wb').write(b'png')\n"
                "print('FORM_RESULT ' + json.dumps({'ok': True, 'engine': 'CYCLES'}))\n")
        app = fake_blender(self.tmp, body)
        seen = []
        rep = bl.run_job(app, self.job, self.tmp / "job.json", timeout=20, progress=lambda f, t: seen.append(f))
        self.assertEqual(rep["engine"], "CYCLES")
        self.assertEqual(seen, [0.1, 0.5, 1.0])


@unittest.skipUnless(HAS_BLENDER, "Blender is not installed")
class RealBlender(unittest.TestCase):
    def test_tiny_render(self):
        tmp = Path(tempfile.mkdtemp())
        stl = cube_stl(tmp / "box.stl")
        out = tmp / "box.png"
        for fast in (False, True):
            job = bl.build_job(stl, out, "studio", "matte", "#3d6fb6", layer_mm=0.2, fast=fast, samples=4, size=(160, 120))
            rep = bl.run_job(BLENDER["app"], job, tmp / "job.json", timeout=170)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["engine"], "BLENDER_EEVEE" if fast else "CYCLES")
            data = out.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (160, 120))
            out.unlink()

    def test_photo_artifact_is_cached_and_goes_stale(self):
        from form import photo
        from form.studio import Studio
        tmp = Path(tempfile.mkdtemp())
        os.environ["FORM_DATA"] = str(tmp)
        cfg = config.load()
        cfg["blender"].update(samples=4)
        st = Studio(cfg)
        try:
            p = st.create("Coupon", "coupon")
            m = photo.render(st, p, "dark", "petg", "#c0392b", fast=True)
            self.assertFalse(m["cached"])
            self.assertEqual(m["evidence"], "illustration")
            self.assertIn("not a photo of a print", m["label"])
            self.assertTrue(photo.file(st, p, "latest").is_file())
            again = photo.render(st, st.load(p["id"]), "dark", "petg", "#c0392b", fast=True)
            self.assertTrue(again["cached"])
            self.assertEqual(again["key"], m["key"])
            p = st.commit(st.load(p["id"]), {"slots": 4})
            self.assertIsNone(photo.latest(st, p))                     # new geometry: the old render is stale
            self.assertEqual(photo.state(st, p)["stale"], 1)
        finally:
            st.kernel.stop()


@unittest.skipUnless(HAS_BLENDER, "Blender is not installed")
class OverMCP(unittest.TestCase):
    def test_render_photo_tool(self):
        import asyncio
        from mcp import Client, StdioServerParameters
        root = Path(__file__).resolve().parents[1]

        async def go():
            with tempfile.TemporaryDirectory() as d:
                env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(root)}
                params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"],
                                               env=env, cwd=str(root))
                async with Client(params) as c:
                    self.assertIn("render_photo", {t.name for t in (await c.list_tools()).tools})
                    p = await c.call_tool("create_project", {"name": "Coupon", "recipe": "coupon", "run": False})
                    pid = (p.structured_content or {}).get("project") or json.loads(p.content[0].text)["project"]
                    r = await c.call_tool("render_photo", {"project": pid, "preset": "studio", "fast": True})
                    self.assertFalse(r.is_error, r.content)
                    self.assertIn("image", [x.type for x in r.content])
                    cap = "\n".join(x.text for x in r.content if x.type == "text")
                    self.assertIn("not a photo of a print", cap)
                    bad = await c.call_tool("render_photo", {"project": pid, "preset": "beach"})
                    self.assertTrue(bad.is_error)
        asyncio.run(go())


class Setup(unittest.TestCase):
    def test_setup_lists_blender(self):
        from form import setup
        items = {i.id: i for i in setup.check()}
        self.assertIn("blender", items)
        if HAS_BLENDER:
            self.assertEqual(items["blender"].status, "ok")
            self.assertIn("blender.print3d", items)
        else:
            self.assertIn("blender.org", items["blender"].detail)


if __name__ == "__main__":
    unittest.main()
