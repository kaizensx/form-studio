"""Windows refuses to replace a file another handle has open. Found on a Windows CI runner as a pipeline that
failed right after the solid was built; POSIX never shows it, so it is simulated here."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from form import fsutil


class Replace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-fsutil-"))

    def test_retries_while_the_target_is_busy(self):
        a, b = self.tmp / "a.tmp", self.tmp / "a.json"
        a.write_text("new", encoding="utf-8"); b.write_text("old", encoding="utf-8")
        real, calls = os.replace, []

        def busy(src, dst):
            calls.append(1)
            if len(calls) < 4:
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real(src, dst)
        with mock.patch("form.fsutil.os.replace", busy):
            fsutil.replace(a, b)
        self.assertEqual(b.read_text(encoding="utf-8"), "new")
        self.assertEqual(len(calls), 4)

    def test_gives_up_with_the_real_error(self):
        a, b = self.tmp / "a.tmp", self.tmp / "a.json"
        a.write_text("new", encoding="utf-8")
        with mock.patch("form.fsutil.os.replace", side_effect=PermissionError(13, "busy")):
            with self.assertRaises(PermissionError):
                fsutil.replace(a, b, seconds=0.05)

    def test_replace_dir_swaps_a_folder(self):
        src, dst = self.tmp / "new", self.tmp / "out"
        src.mkdir(); (src / "x.txt").write_text("1", encoding="utf-8")
        dst.mkdir(); (dst / "old.txt").write_text("0", encoding="utf-8")
        fsutil.replace_dir(src, dst)
        self.assertEqual(sorted(p.name for p in dst.iterdir()), ["x.txt"])
        self.assertFalse(src.exists())

    def test_replace_dir_retries_a_busy_file(self):
        src, dst = self.tmp / "new", self.tmp / "out"
        src.mkdir(); dst.mkdir(); (dst / "old.txt").write_text("0", encoding="utf-8")
        import shutil
        real, calls = shutil.rmtree, []

        def busy(path, *a, **k):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "busy")
            return real(path, *a, **k)
        with mock.patch("form.fsutil.shutil.rmtree", busy):
            fsutil.replace_dir(src, dst)
        self.assertTrue(dst.is_dir() and not src.exists())


if __name__ == "__main__":
    unittest.main()


class ConversationReadsOnWindows(unittest.TestCase):
    """Found on a Windows runner: deleting a design left its conversation pointing at it."""

    def test_one_lock_per_folder_across_objects(self):
        from form.conversations import Conversations
        root = Path(tempfile.mkdtemp(prefix="form-conv-lock-"))
        self.assertIs(Conversations(root)._lock, Conversations(root)._lock)
        self.assertIsNot(Conversations(root)._lock, Conversations(Path(tempfile.mkdtemp()))._lock)

    def test_a_busy_read_is_retried(self):
        from form.conversations import Conversations
        store = Conversations(Path(tempfile.mkdtemp(prefix="form-conv-read-")))
        m = store.create(project="p")
        real, calls = Path.read_text, []

        def busy(self, *a, **k):
            if self.name == "meta.json":
                calls.append(1)
                if len(calls) < 3:
                    raise PermissionError(13, "busy")
            return real(self, *a, **k)
        with mock.patch.object(Path, "read_text", busy):
            self.assertEqual(store.meta(m["id"])["project"], "p")
        self.assertEqual(len(calls), 3)
