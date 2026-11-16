"""The agent-facing layer: headless renders, cross-process locking, first-run examples. No kernel needed."""
import base64
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from form import render
from form.studio import ProjectLock


def _cube_view():
    P = np.array([[x, y, z] for x in (0, 10) for y in (0, 20) for z in (0, 5)], dtype=np.float32)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    T = np.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))], dtype=np.uint32)
    b64 = lambda a: base64.b64encode(a.tobytes()).decode()
    return {"mesh": [{"feature": "body", "positions": b64(P), "indices": b64(T)}],
            "edges": b64(np.array([[0, 0, 5, 10, 0, 5]], dtype=np.float32))}


class Render(unittest.TestCase):
    def test_png_every_view(self):
        v = _cube_view()
        for view in render.VIEWS:
            png = render.render_png(v, [{"id": "body", "label": "Body"}], view, size=(320, 240))
            im = Image.open(io.BytesIO(png))
            self.assertEqual(im.size, (320, 240))
            px = np.asarray(im.convert("RGB")).reshape(-1, 3)
            self.assertGreater((np.abs(px.astype(int) - render.PAPER).sum(1) > 30).mean(), 0.02, view)   # something drawn

    def test_highlight_uses_signal_colour(self):
        png = render.render_png(_cube_view(), [{"id": "body", "label": "Body"}], "iso", highlight="body", size=(320, 240))
        px = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).reshape(-1, 3).astype(int)
        reddish = (px[:, 0] > px[:, 1] + 60) & (px[:, 0] > px[:, 2] + 60)
        self.assertGreater(reddish.mean(), 0.01)

    def test_unknown_view_is_an_error(self):
        with self.assertRaises(ValueError):
            render.render_png(_cube_view(), [], "diagonal")


@unittest.skipIf(sys.platform == "win32", "flock is POSIX")
class Locking(unittest.TestCase):
    def test_lock_excludes_another_process(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.lock"
            probe = textwrap.dedent(f"""
                import fcntl, os, sys
                fd = os.open({str(path)!r}, os.O_RDWR | os.O_CREAT)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print("free")
                except BlockingIOError:
                    print("held")
            """)
            lock = ProjectLock(path)
            with lock:
                with lock:                                   # re-entrant in-process
                    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True).stdout.strip()
                self.assertEqual(out, "held")
            out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True).stdout.strip()
            self.assertEqual(out, "free")


class FirstRun(unittest.TestCase):
    def test_empty_data_folder_stays_empty_and_examples_are_added_on_request(self):
        from form import config
        from form.studio import Studio
        with tempfile.TemporaryDirectory() as d:
            os.environ["FORM_DATA"] = d
            try:
                st = Studio(config.load())
                self.assertEqual(st.list(), [])                # nothing is seeded
                st.seed_examples()
                ids = [p["id"] for p in st.list()]
                self.assertIn("hallway-phone-dock", ids)
                p = st.load("hallway-phone-dock")
                self.assertEqual(p["approvals"], [])
                self.assertTrue(all(v == [] for v in p["produced"].values()))
            finally:
                os.environ.pop("FORM_DATA", None)
                st.kernel.stop()


if __name__ == "__main__":
    unittest.main()
