"""Backups (wave L, form/backup.py): a round trip restores every byte, verify finds damage, retention keeps the newest
and touches nothing else, the Git destination pushes to a repository the person owns (here a bare repository in a temp
folder) and never creates one, and Recently deleted keeps a design 30 days and longer when no backup holds it.

Every test runs in its own scratch data folder (FORM_DATA in a temp dir): the owner's ~/FORM is never read or written."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from form import backup  # noqa: E402
from form.conversations import Conversations  # noqa: E402
from test_modelling import PLATE  # noqa: E402
from test_studio import make_studio  # noqa: E402


def tree(base: Path, skip_artifacts: bool = False) -> dict:
    out = {}
    for f in sorted(base.rglob("*")):
        rel = f.relative_to(base).as_posix()
        if f.is_file() and not f.name.endswith(backup.SKIP_SUFFIX) and not (skip_artifacts and rel.startswith("artifacts/")):
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def in_scratch(st, tmp: Path):
    assert Path(st.root).resolve().is_relative_to(Path(tmp).resolve()), "the tests never touch the owner's data"


class Backups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        cls.st = make_studio(cls.base / "data")
        in_scratch(cls.st, cls.base)
        cls.pid = cls.st.create_design("Backup plate", PLATE, purpose="model")["id"]
        jid = cls.st.run(cls.pid)
        while cls.st.jobs[jid]["state"] == "running":
            time.sleep(0.2)
        conv = Conversations(cls.st.root)
        c = conv.create(project=cls.pid, title="About the plate")
        conv.append(c["id"], {"t": "user", "text": "make it 5 mm thicker"})
        cls.cid = c["id"]
        cls.folder = cls.base / "backups"
        cls.st.cfg["backup"] = {**backup.DEFAULTS, "folder": str(cls.folder), "keep": 3}

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()
        cls.tmp.cleanup()

    def test_1_round_trip_restores_byte_identically(self):
        made = backup.snapshot(self.st, self.folder)
        self.assertTrue(Path(made["file"]).is_file())
        self.assertEqual(made["projects"], 1)
        self.assertEqual(made["conversations"], 1)
        v = backup.verify(Path(made["file"]))
        self.assertTrue(v["ok"], v)
        self.assertGreater(v["checked"], 3)
        want_p = tree(self.st.dir(self.pid))
        want_c = tree(Conversations(self.st.root).root / self.cid)
        want_s = tree(self.st.root / ".sources")
        self.assertIn("project.json", want_p)
        self.assertTrue(any(k.startswith("artifacts/") for k in want_p))      # built outputs are in by default
        # a second data folder, empty: everything comes back as the same bytes
        other = make_studio(self.base / "fresh")
        try:
            in_scratch(other, self.base)
            r = backup.restore(other, Path(made["file"]))
            self.assertEqual([x["id"] for x in r["restored"]], [self.pid])
            self.assertEqual(r["conversations"], [self.cid])
            self.assertEqual(tree(other.dir(self.pid)), want_p)
            self.assertEqual(tree(Conversations(other.root).root / self.cid), want_c)
            self.assertEqual(tree(other.root / ".sources"), want_s)
            self.assertEqual(other.load(self.pid)["head"], self.st.load(self.pid)["head"])
            # a design that exists is not overwritten without replace
            again = backup.restore(other, Path(made["file"]))
            self.assertEqual(again["restored"], [])
            self.assertEqual(again["skipped"][0]["id"], self.pid)
        finally:
            other.kernel.shutdown()
            os.environ["FORM_DATA"] = str(self.st.root)

    def test_2_verify_finds_a_changed_byte_and_restore_refuses(self):
        made = backup.snapshot(self.st, self.base / "damaged")
        src = Path(made["file"])
        bad = src.with_name("form-backup-20000101T000000Z.zip")
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zout:
            for i in zin.infolist():
                data = zin.read(i)
                if i.filename == f"projects/{self.pid}/project.json":
                    data = data.replace(b'"name"', b'"Name"', 1)
                zout.writestr(i, data)
        v = backup.verify(bad)
        self.assertFalse(v["ok"])
        self.assertEqual(v["damaged"], [f"projects/{self.pid}/project.json"])
        other = make_studio(self.base / "fresh2")
        try:
            with self.assertRaises(backup.BackupError):
                backup.restore(other, bad)
            self.assertFalse((other.root / self.pid).exists())          # nothing was written
        finally:
            other.kernel.shutdown()
            os.environ["FORM_DATA"] = str(self.st.root)

    def test_3_retention_keeps_the_newest_and_touches_nothing_else(self):
        folder = self.base / "keep"
        folder.mkdir()
        (folder / "notes.txt").write_text("mine", encoding="utf-8")
        (folder / "form-backup-notmine.zip").write_bytes(b"not a backup")
        t = time.time()
        names = [backup.snapshot(self.st, folder, built=False, now=t + i * 3600)["name"] for i in range(5)]
        removed = backup.prune(folder, 3)
        self.assertEqual(sorted(removed), sorted(names[:2]))
        left = sorted(f.name for f in folder.iterdir())
        self.assertEqual(left, sorted(names[2:] + ["form-backup-notmine.zip", "notes.txt"]))
        # without built outputs the project folder's artifacts are left out
        with zipfile.ZipFile(folder / names[-1]) as z:
            self.assertFalse(any("/artifacts/" in n for n in z.namelist()))
            self.assertIn(f"projects/{self.pid}/project.json", z.namelist())

    def test_4_run_writes_verifies_prunes_and_records_state(self):
        for _ in range(4):
            out = backup.run(self.st, self.st.cfg)
            self.assertTrue(out["ok"])
            self.assertTrue(out["folder"]["verified"])
        self.assertLessEqual(len(backup.backups(self.folder)), 3)
        s = backup.status(self.st)
        self.assertTrue(s["last_ok"]["ok"])
        self.assertFalse(s["due"])                                   # not enabled
        self.assertFalse(backup.due(self.st, {**self.st.cfg, "backup": {**self.st.cfg["backup"], "enabled": True}}))
        self.assertTrue(backup.due(self.st, {**self.st.cfg, "backup": {**self.st.cfg["backup"], "enabled": True}},
                                   now=time.time() + 2 * 86400))

    def test_5_the_folder_is_never_inside_the_project_folder(self):
        cfg = {**self.st.cfg, "backup": {**self.st.cfg["backup"], "folder": str(self.st.root / "bk")}}
        with self.assertRaises(backup.BackupError):
            backup.run(self.st, cfg)
        cfg = {**self.st.cfg, "backup": {**self.st.cfg["backup"], "folder": "relative/path"}}
        with self.assertRaises(backup.BackupError):
            backup.folder_of(cfg, self.st.root)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_6_git_pushes_to_a_repository_the_person_owns(self):
        bare = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)
        out = backup.push_git(self.st, str(bare), "main")
        self.assertTrue(out["changed"])
        self.assertTrue(out["commit"])
        check = self.base / "check"
        subprocess.run(["git", "clone", "--quiet", "--branch", "main", str(bare), str(check)], check=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        man = json.loads((check / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(man["format"], backup.FORMAT)
        self.assertFalse(man["built_outputs"])
        self.assertIn(f"projects/{self.pid}/project.json", man["files"])
        self.assertFalse((check / "projects" / self.pid / "artifacts").exists())   # built outputs are never pushed
        self.assertTrue((check / "conversations" / self.cid / "meta.json").is_file())
        self.assertEqual(tree(check / "projects" / self.pid), tree(self.st.dir(self.pid), skip_artifacts=True))
        self.assertTrue(backup.verify(check)["ok"])                  # a clone verifies like a backup file
        # nothing changed: no new commit
        time.sleep(1.1)                                              # a new time stamp alone is not a change
        again = backup.push_git(self.st, str(bare), "main")
        self.assertFalse(again["changed"])
        log = subprocess.run(["git", "--git-dir", str(bare), "rev-list", "--count", "main"], capture_output=True, text=True)
        self.assertEqual(log.stdout.strip(), "1")
        # a restore from the clone brings the designs back (without built outputs)
        other = make_studio(self.base / "fromgit")
        try:
            r = backup.restore(other, check)
            self.assertEqual([x["id"] for x in r["restored"]], [self.pid])
            self.assertEqual(tree(other.dir(self.pid)), tree(self.st.dir(self.pid), skip_artifacts=True))
        finally:
            other.kernel.shutdown()
            os.environ["FORM_DATA"] = str(self.st.root)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_7_git_never_creates_a_repository_and_refuses_passwords(self):
        missing = self.base / "nowhere.git"
        with self.assertRaises(backup.BackupError) as cm:
            backup.push_git(self.st, str(missing), "main")
        self.assertIn("never creates", cm.exception.hint)
        self.assertFalse(missing.exists())
        for bad in ("https://me:secret@example.com/r.git", "--upload-pack=x", "a b"):
            with self.assertRaises(backup.BackupError):
                backup.check_remote(bad)
        self.assertEqual(backup.check_remote("git@github.com:me/designs.git"), "git@github.com:me/designs.git")
        from form import config_edit
        with self.assertRaises(config_edit.ConfigError):
            config_edit.coerce("backup.git_remote", "https://me:token@example.com/r.git")

    def test_8_recently_deleted_keeps_30_days_and_longer_without_a_backup(self):
        pid = self.st.create_design("Bin plate", PLATE, purpose="model")["id"]
        conv = Conversations(self.st.root)
        c = conv.create(project=pid, title="About the bin plate")
        conv.append(c["id"], {"t": "user", "text": "hello"})
        self.st.delete_project(pid)
        rows = [r for r in backup.deleted(self.st) if r["id"] == pid]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["days_left"], 30)
        self.assertIsNone(rows[0]["backup"])
        # 31 days later, no backup holds it: it stays
        later = time.time() + 31 * 86400
        out = backup.purge_expired(self.st, self.st.cfg, now=later)
        self.assertIn(rows[0]["entry"], [k["entry"] for k in out["kept"]])
        self.assertTrue((self.st.root / ".trash" / rows[0]["entry"]).is_dir())
        # put it back: the conversation points at it again
        back = backup.undelete(self.st, rows[0]["entry"])
        self.assertEqual(back["id"], pid)
        self.assertEqual(back["conversations_reattached"], 1)
        self.assertEqual(conv._read(c["id"])["project"], pid)
        # back up, delete again: after 30 days the backup holds it, so it leaves the bin
        backup.snapshot(self.st, self.folder, built=False)
        self.st.delete_project(pid)
        row = next(r for r in backup.deleted(self.st) if r["id"] == pid)
        self.assertTrue(row["backup"])
        out = backup.purge_expired(self.st, self.st.cfg, now=later)
        self.assertIn(row["entry"], [k["entry"] for k in out["removed"]])
        self.assertFalse((self.st.root / ".trash" / row["entry"]).exists())

    def test_9_restore_with_replace_moves_the_current_copy_to_recently_deleted(self):
        made = backup.snapshot(self.st, self.base / "replace")
        before = tree(self.st.dir(self.pid))
        self.st.rename_project(self.pid, "Renamed plate")
        self.assertNotEqual(tree(self.st.dir(self.pid)), before)
        r = backup.restore(self.st, Path(made["file"]), [self.pid], replace=True)
        self.assertEqual(len(r["moved_to_recently_deleted"]), 1)
        self.assertTrue(Path(r["moved_to_recently_deleted"][0]).is_dir())
        self.assertEqual(tree(self.st.dir(self.pid)), before)
        meta = Conversations(self.st.root)._read(self.cid)
        self.assertEqual(meta["project"], self.pid)                  # its conversation still points at it


if __name__ == "__main__":
    unittest.main()
