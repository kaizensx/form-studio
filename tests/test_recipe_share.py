"""Sharing recipes (form/recipe_share.py): a .formrecipe package exported and imported again, the community
submission (folder and pre-filled issue link), and a design turned into a recipe. Real kernel builds."""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

from form import config, recipe_lib, recipe_share as rs
from form.studio import Studio, StudioError

ROOT = Path(__file__).resolve().parents[1]
CLIP = (ROOT / "community" / "recipes" / "cable-clip" / "recipe.py").read_text(encoding="utf-8")


def index_builder():
    spec = importlib.util.spec_from_file_location("build_recipe_index", ROOT / "site" / "tools" / "build_recipe_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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

    # ---- community submission ----
    def test_submission_folder_passes_the_gallery_check_and_the_link_is_prefilled(self):
        rs.edit_meta(self.st.root, self.clip["id"], author="maker-1", summary="Holds a cable.", tags=["desk"])
        r = rs.prepare(self.st, self.clip["id"])
        sub = r["submission"]
        self.assertEqual(sub["problems"], [])
        self.assertEqual(sub["meta"], {"id": "cable-clip", "title": "Cable clip", "summary": "Holds a cable.", "author": "maker-1",
                                       "tags": ["desk"], "kind": "python", "params_count": 8})
        url = urllib.parse.urlparse(sub["issue"]["url"])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", "https://github.com/kaizensx/form-studio/issues/new")
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        self.assertEqual(q["template"], "3-recipe.yml")
        self.assertEqual(q["title"], "[Recipe] Cable clip")
        self.assertEqual(q["recipe_id"], "cable-clip")
        self.assertIn(CLIP.strip()[:200], q["recipe_code"])
        self.assertIn('"params_count": 8', q["recipe_meta"])
        self.assertLessEqual(len(sub["issue"]["url"]), rs.URL_LIMIT)
        # every field the link fills in exists in the issue form, by id
        form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "3-recipe.yml").read_text(encoding="utf-8")
        for k in q:
            if k not in ("template", "title"):
                self.assertIn(f"id: {k}\n", form, k)
        self.assertIn(rs.ISSUE_KIND, form)

        # the folder for a pull request: exactly what site/tools/build_recipe_index.py reads
        out = self.tmp / "pr" / "community" / "recipes"
        out.mkdir(parents=True)
        saved = rs.save_submission(self.st, self.clip["id"], out)
        self.assertEqual(sorted(p.name for p in (out / "cable-clip").iterdir()), ["meta.json", "preview.png", "recipe.py"])
        idx = index_builder()
        idx.ROOT, idx.SITE = self.tmp / "pr", self.tmp / "pr" / "site"
        errors = []
        got = idx.community(errors)
        self.assertEqual(errors, [])
        self.assertEqual(got[0]["sha256"], hashlib.sha256(CLIP.encode()).hexdigest())
        self.assertEqual(saved["problems"], [])

    def test_a_long_recipe_leaves_its_code_out_of_the_link_and_says_so(self):
        fields = rs.issue_fields({"id": "x-y", "title": "T", "summary": "s", "author": "a", "tags": [], "kind": "python", "params_count": 1},
                                 "#" * 20000, [])
        link = rs.issue_link(fields)
        self.assertEqual(link["omitted"], ["recipe_code"])
        self.assertLessEqual(link["chars"], rs.URL_LIMIT)
        self.assertIn("too long for a link", urllib.parse.unquote_plus(link["url"]))

    def test_missing_author_and_builtin_ids_are_named_before_anything_leaves(self):
        cm = {"id": "hook", "title": "Hook", "summary": "", "author": "", "tags": [], "kind": "python", "params_count": 2}
        p = " ".join(rs.submission_problems(cm))
        self.assertIn("built-in", p)
        self.assertIn("GitHub username", p)
        self.assertIn("summary", p)
        with self.assertRaises(recipe_lib.LibraryError):
            rs.edit_meta(self.st.root, self.clip["id"], author="not a name")

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
        r = subprocess.run([sys.executable, "-m", "form", "recipes", "submit", self.clip["id"], "--author", "maker-1"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=600)
        sub = json.loads(r.stdout)
        self.assertTrue(sub["issue_url"].startswith("https://github.com/kaizensx/form-studio/issues/new?template=3-recipe.yml"))
        self.assertIn("Nothing was sent", sub["note"])


class GalleryIndex(unittest.TestCase):
    def test_the_index_carries_discussion_links_and_dates(self):
        idx = json.dumps({"version": 1, "recipes": [
            {"id": "a", "title": "Alpha", "author": "z", "kind": "python", "params_count": 3, "added": "2026-01-02",
             "discussion": "https://github.com/kaizensx/form-studio/discussions/12"},
            {"id": "b", "title": "Beta", "author": "m", "kind": "python", "discussion": "https://evil.example/x"}]}).encode()
        a, b = recipe_lib.parse_index(idx)
        self.assertEqual(a["discussion"], "https://github.com/kaizensx/form-studio/discussions/12")
        self.assertTrue(b["discussion"].startswith("https://github.com/kaizensx/form-studio/discussions?discussions_q="))
        self.assertEqual((a["params"], a["added"]), (3, "2026-01-02"))
        self.assertEqual([i["id"] for i in recipe_lib.search([a, b], sort="author")], ["b", "a"])
        self.assertEqual([i["id"] for i in recipe_lib.search([b, a], sort="added")], ["a", "b"])
        self.assertEqual([i["id"] for i in recipe_lib.search([b, a], sort="params")], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
