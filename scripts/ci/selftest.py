"""Tests for the automation scripts, on the fixtures in scripts/ci/fixtures. Standard library only; no CAD kernel, no
network, nothing written to GitHub (every script runs in its dry-run mode).

    python3 scripts/ci/selftest.py
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import compat  # noqa: E402
import issue_recipe  # noqa: E402
import pr_preview  # noqa: E402
import recipe_report  # noqa: E402
import release_notes  # noqa: E402
import triage  # noqa: E402


def png(path: Path, w: int = 4, h: int = 3) -> Path:
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def run(fn, *args) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        rc = fn(list(args))
    assert rc in (0, None), rc
    return buf.getvalue()


class Untrusted(unittest.TestCase):
    def test_md_is_inert(self):
        s = common.md("<img src=x onerror=alert(1)> @someone [link](https://evil) `x`\n# head")
        self.assertNotIn("<img", s)
        self.assertNotIn("@someone", s)
        self.assertNotIn("](", s)
        self.assertNotIn("https://", s)
        self.assertNotIn("\n", s)

    def test_png_check(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(common.png_info(png(d / "a.png")), (4, 3))
        (d / "b.png").write_bytes(b"<svg onload=alert(1)>")
        self.assertIsNone(common.png_info(d / "b.png"))
        self.assertIsNone(common.safe_name("../etc/passwd"))


class IssueParsing(unittest.TestCase):
    def ev(self, name):
        return json.loads((FIX / name).read_text(encoding="utf-8"))["issue"]

    def test_source_field(self):
        out = Path(tempfile.mkdtemp())
        r = issue_recipe.extract(self.ev("issue-recipe-source.json"), out, allow_download=False)
        self.assertTrue(r["found"] and r["wants_check"])
        self.assertEqual((r["mode"], r["origin"], r["file"], r["recipe_id"]), ("source", "field", "recipe.py", "cable-clip-mini"))
        self.assertEqual(r["tags"], ["desk", "cable management", "snap fit"])        # "<script>" dropped
        self.assertIn("class ", (out / "recipe.py").read_text())

    def test_not_a_recipe_and_foreign_link(self):
        r = issue_recipe.extract(self.ev("issue-recipe-missing.json"), Path(tempfile.mkdtemp()), allow_download=False)
        self.assertFalse(r["found"])
        self.assertTrue(any("not fetched" in n for n in r["notes"]))

    def test_links(self):
        self.assertEqual(issue_recipe.raw_link("https://github.com/a/b/blob/main/x/recipe.py"),
                         "https://raw.githubusercontent.com/a/b/main/x/recipe.py")
        self.assertIsNone(issue_recipe.raw_link("https://evil.example/recipe.py"))
        self.assertIsNone(issue_recipe.raw_link("http://raw.githubusercontent.com/a/b/c.py"))
        self.assertIsNone(issue_recipe.raw_link("https://github.com/a/b/settings"))

    def test_zip_with_traversal_name_is_read_not_extracted(self):
        import zipfile
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("../../recipe.py", (FIX.parent.parent.parent / "community/recipes/cable-clip/recipe.py").read_text())
        r = issue_recipe.from_bytes("x.zip", b.getvalue())
        self.assertEqual(r.get("mode"), "source")


class Reports(unittest.TestCase):
    def test_recipe_comment(self):
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIX / "recipe-result", tmp / "res")
        png(tmp / "res" / "out" / "preview.png")
        text = run(recipe_report.main, "--issue", "101", "--result", str(tmp / "res"), "--dry-run",
                   "--event", str(FIX / "issue-recipe-source.json"))
        self.assertIn("Builds and passes its checks", text)
        self.assertIn("recipe:accept", text)
        self.assertIn("verdict: valid", text)

    def test_taken_id_needs_changes(self):
        ev = json.loads((FIX / "issue-recipe-source.json").read_text())
        ev["issue"]["body"] = ev["issue"]["body"].replace("cable-clip-mini", "cable-clip")
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ev.json").write_text(json.dumps(ev))
        text = run(recipe_report.main, "--issue", "101", "--result", str(FIX / "recipe-result"), "--dry-run", "--event", str(tmp / "ev.json"))
        self.assertIn("already taken", text)
        self.assertIn("verdict: needs-changes", text)

    def test_pr_comment(self):
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIX / "pr-preview", tmp / "p")
        for side in ("before", "after"):
            png(tmp / "p" / "recipes" / "builtin-hook" / side / "preview.png")
        text = run(pr_preview.main, "comment", "--dir", str(tmp / "p"), "--head-sha", "abc123def456", "--dry-run")
        self.assertIn("Wall hook", text)
        self.assertIn("builtin-hook-after.png", text)
        with self.assertRaises(SystemExit):
            run(pr_preview.main, "comment", "--dir", str(tmp / "p"), "--head-sha", "not-the-run", "--dry-run")

    def test_affected(self):
        a = pr_preview.affected(["form/recipes/hook.py", "community/recipes/cable-clip/recipe.py", "form/app/qml/Main.qml"],
                                FIX.parent.parent.parent)
        self.assertEqual((a["recipes"], a["community"], a["ui"]), (["hook"], ["cable-clip"], True))
        a = pr_preview.affected(["form/checks.py"], FIX.parent.parent.parent)
        self.assertGreaterEqual(len(a["recipes"]), 9)


class Data(unittest.TestCase):
    def test_compat_merge(self):
        out = Path(tempfile.mkdtemp())
        run(compat.main, "merge", "--in", str(FIX / "compat"), "--out", str(out))
        latest = json.loads((out / "latest.json").read_text())
        self.assertEqual(len(latest["slicers"]), 2)
        self.assertEqual(latest["totals"]["cells"], 20)
        self.assertEqual(json.loads((out / "badge.json").read_text())["schemaVersion"], 1)

    def test_release_notes(self):
        text = release_notes.notes_for("v11.1.1", (FIX.parent.parent.parent / "CHANGELOG.md").read_text())
        self.assertIn("SHA256SUMS", text)
        self.assertNotIn("## 11.1.0", text)
        self.assertIn("Preview update channel", release_notes.notes_for("v99.0.0-preview.1", "## Unreleased\n\n- x\n"))
        body = release_notes.draft_body([{"number": 3, "title": "Fix it", "labels": [{"name": "type:bug"}], "user": {"login": "a"}}], "v1")
        self.assertIn("### Fixed", body)

    def test_triage(self):
        p = triage.plan({"title": "fix(slicer): presets", "additions": 5, "deletions": 1, "labels": [],
                         "author_association": "CONTRIBUTOR", "user": {"login": "x"}, "assignees": []})
        self.assertEqual((p["add"], p["assign"]), (["size/XS", "type:bug"], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
