"""Sharing recipes (form/recipe_share.py): a .formrecipe package exported and imported again, and a design turned
into a recipe. Real kernel builds."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from form import config, recipe_lib, recipe_share as rs
from form.studio import Studio, StudioError

ROOT = Path(__file__).resolve().parents[1]
CLIP = (ROOT / "tests" / "fixtures" / "recipes" / "cable_clip.py").read_text(encoding="utf-8")


class Share(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-share-"))
        cls._env = os.environ.get("FORM_DATA")
        os.environ["FORM_DATA"] = str(cls.tmp / "a")
        cls.st = Studio(config.load())
        cls.clip = recipe_lib.install(cls.st.root, CLIP, "python", recipe_lib.sha256(CLIP), {"title": "Cable clip", "tags": ["desk"]})

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        if cls._env is None:
            os.environ.pop("FORM_DATA", None)
        else:
            os.environ["FORM_DATA"] = cls._env
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- package ----
    def test_package_round_trip(self):
        r = rs.prepare(self.st, self.clip["id"], {"author": "maker-1", "summary": "Holds a cable.", "tags": "desk, Cables"})
        data = rs.package_bytes(self.st, self.clip["id"])
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(sorted(z.namelist()), ["meta.json", "preview.png", "recipe.py"])
        meta = json.loads(z.read("meta.json"))
        self.assertEqual(meta["sha256"], hashlib.sha256(CLIP.encode()).hexdigest())
        self.assertEqual(meta["author"], "maker-1")
        self.assertEqual(meta["tags"], ["desk", "cables"])
        self.assertEqual(meta["params_count"], 8)
        self.assertEqual({p["key"] for p in meta["params"]} >= {"cable_d", "wall"}, True)
        png = z.read("preview.png")
        self.assertTrue(png.startswith(rs.PNG))
        from PIL import Image
        im = Image.open(io.BytesIO(png))
        self.assertEqual(im.size, rs.PREVIEW_SIZE)
        self.assertGreater(len(im.convert("L").getcolors(65536) or []), 20, "a real picture, not a blank")
        self.assertEqual(meta["preview_sha256"], hashlib.sha256(png).hexdigest())
        self.assertEqual(r["package"]["bytes"], len(data))

        # another person's library: reviewed first, nothing installed or run before Install
        other = self.tmp / "b"
        other.mkdir()
        info = rs.inspect_package(other, data, "cable-clip.formrecipe")
        self.assertTrue(info["verified"])
        self.assertEqual(info["problems"], [])
        self.assertEqual(info["source"], CLIP)
        self.assertEqual(info["meta"]["author"], "maker-1")
        self.assertTrue(info["preview"].endswith(info["sha256"] + ".png"))
        self.assertEqual(recipe_lib.mine(other), [])
        with self.assertRaises(recipe_lib.LibraryError):
            rs.install_package(other, "0" * 64)
        m = rs.install_package(other, info["sha256"])
        self.assertEqual(m["origin"], "package")
        self.assertEqual(m["author"], "maker-1")
        self.assertEqual(m["preview"], f"/api/recipes/mine/{m['id']}/preview.png")
        self.assertEqual(rs.preview_file(other, m["id"]).read_bytes(), png)
        self.assertEqual(recipe_lib.source(other, m["id"])["source"], CLIP)
        self.assertEqual(list((other / ".recipes" / ".pending").iterdir()), [], "the reviewed copy is cleaned up")

    def test_a_tampered_package_is_shown_as_such_and_refused(self):
        data = rs.package_bytes(self.st, self.clip["id"])
        z = zipfile.ZipFile(io.BytesIO(data))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as w:
            w.writestr("meta.json", z.read("meta.json"))
            w.writestr("recipe.py", CLIP.replace("Cable clip", "Cable clip!"))
        d = self.tmp / "c"
        d.mkdir(exist_ok=True)
        info = rs.inspect_package(d, buf.getvalue())
        self.assertFalse(info["verified"])
        self.assertIn("does not match the checksum", info["problems"][0])
        with self.assertRaises(recipe_lib.LibraryError):
            rs.install_package(d, info["sha256"])

    def test_unsafe_packages_are_not_read(self):
        def pkg(files):
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as w:
                for n, v in files.items():
                    w.writestr(n, v)
            return b.getvalue()
        meta = json.dumps({"format": "formrecipe", "version": 1, "kind": "python", "sha256": recipe_lib.sha256(CLIP)})
        for bad in ({"meta.json": meta, "recipe.py": CLIP, "../evil.py": "x"},
                    {"meta.json": meta, "recipe.py": CLIP, "recipe.scad": "cube(1);"},
                    {"meta.json": meta, "recipe.py": CLIP, "preview.png": b"GIF89a"},
                    {"meta.json": json.dumps({"format": "formrecipe", "version": 2, "kind": "python"}), "recipe.py": CLIP},
                    {"recipe.py": CLIP}):
            with self.assertRaises(recipe_lib.LibraryError, msg=str(list(bad))):
                rs.read_package(pkg(bad))
        with self.assertRaises(recipe_lib.LibraryError):
            rs.read_package(b"not a zip")

    # ---- a design, as a recipe ----
    def test_a_design_becomes_a_recipe_that_reproduces_it(self):
        p = self.st.create("Coat hook", "hook", "", {"load_kg": 5.5, "plate_w": 32})
        d = rs.derive(self.st, p["id"], "Strong coat hook", "A hook for heavy coats.", {"load_kg": (2, 10)})
        self.assertTrue(d["check"]["same_volume"], d["check"])
        self.assertEqual(d["problems"], [])
        src = d["source"]
        self.assertNotIn("from .base", src)
        self.assertIn("from form.recipes.base import", src)
        self.assertIn('title = "Strong coat hook"', src)
        load = next(q for q in d["param_list"] if q["key"] == "load_kg")
        self.assertEqual((load["default"], load["min"], load["max"]), (5.5, 2, 10))
        self.assertEqual(next(q for q in d["param_list"] if q["key"] == "plate_w")["default"], 32)
        with self.assertRaises(recipe_lib.LibraryError):
            rs.derive(self.st, p["id"], ranges={"load_kg": (0.01, 50)})          # widened
        with self.assertRaises(recipe_lib.LibraryError):
            rs.derive(self.st, p["id"], ranges={"load_kg": (6, 10)})             # leaves out the design's value
        m = rs.install_derived(self.st.root, d["sha256"], "python", d["title"], d["summary"], p["id"], d["rev"])
        self.assertEqual(m["origin"], "design")
        self.assertEqual(m["derived_from"], {"project": p["id"], "rev": d["rev"]})
        q = recipe_lib.create_from(self.st, m["id"], "From the recipe")
        self.assertEqual(self.st.rev(q)["values"]["load_kg"], 5.5)

    def test_routes_and_cli(self):
        from form import home_api
        got = home_api.route_get(self.st, f"/api/recipes/derive/{self.st.create('Planter', 'planter')['id']}", {})
        self.assertTrue(got["ok"])
        self.assertTrue(all("value" in r and "min" in r for r in got["params"]))
        with self.assertRaises(StudioError):
            home_api.route_post(self.st, "/api/recipes/package/install", {"sha256": "nope"}, {})
        out = self.tmp / "cli.formrecipe"
        env = dict(os.environ, FORM_DATA=str(self.st.root))
        r = subprocess.run([sys.executable, "-m", "form", "recipes", "export", self.clip["id"], "--out", str(out)],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(zipfile.is_zipfile(out))
        other = self.tmp / "cli-b"
        other.mkdir()
        env2 = dict(os.environ, FORM_DATA=str(other))
        r = subprocess.run([sys.executable, "-m", "form", "recipes", "import", str(out)], cwd=ROOT, env=env2, capture_output=True, text=True, timeout=120)
        info = json.loads(r.stdout)
        self.assertIn("--sha256", info["install_with"])
        self.assertEqual(recipe_lib.mine(other), [])
        r = subprocess.run([sys.executable, "-m", "form", "recipes", "import", str(out), "--sha256", info["sha256"]], cwd=ROOT, env=env2,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(recipe_lib.mine(other)), 1)


class Search(unittest.TestCase):
    def test_sort_by_author_and_parameters(self):
        a = {"id": "a", "title": "Alpha", "author": "z", "params": 3}
        b = {"id": "b", "title": "Beta", "author": "m", "params": 1}
        self.assertEqual([i["id"] for i in recipe_lib.search([a, b], sort="author")], ["b", "a"])
        self.assertEqual([i["id"] for i in recipe_lib.search([b, a], sort="params")], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
