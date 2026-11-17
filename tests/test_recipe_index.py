"""The recipe index the website publishes and the app reads (site/tools/build_recipe_index.py)."""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("build_recipe_index", ROOT / "site" / "tools" / "build_recipe_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecipeIndex(unittest.TestCase):
    def test_builtin_recipes_match_the_registry(self):
        from form.recipes import registry
        idx = load()
        found = {r["id"]: r for r in idx.builtin()}
        reg = registry()
        self.assertEqual(set(found), set(reg))
        for rid, r in reg.items():
            self.assertEqual(found[rid]["title"], r.title)
            self.assertEqual(found[rid]["params_count"], len(r.params))
            self.assertTrue(found[rid]["builtin"])
            self.assertIsNone(found[rid]["url"])

    def test_schema(self):
        idx = load()
        errors = []
        recipes = idx.builtin() + idx.community(errors)
        self.assertEqual(errors, [])
        for r in recipes:
            for key in ("id", "title", "summary", "author", "tags", "kind", "builtin", "url", "sha256", "preview"):
                self.assertIn(key, r)
            self.assertIn(r["kind"], ("python", "scad"))
            if not r["builtin"]:
                self.assertTrue(r["url"].startswith("https://raw.githubusercontent.com/kaizensx/form-studio/main/community/recipes/"))
                self.assertRegex(r["sha256"], r"^[0-9a-f]{64}$")
        json.dumps({"version": 1, "recipes": recipes})

    def test_malformed_community_recipe_is_reported(self):
        idx = load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "community" / "recipes" / "Bad_Id"
            d.mkdir(parents=True)
            (d / "meta.json").write_text(json.dumps({"id": "Bad_Id"}), encoding="utf-8")
            (root / "site").mkdir()
            old_root, old_site = idx.ROOT, idx.SITE
            idx.ROOT, idx.SITE = root, root / "site"
            try:
                errors = []
                self.assertEqual(idx.community(errors), [])
                self.assertTrue(errors and re.search("missing or wrong type", errors[0]))
            finally:
                idx.ROOT, idx.SITE = old_root, old_site


if __name__ == "__main__":
    unittest.main()
