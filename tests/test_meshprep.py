"""Big meshes: attach by path, preflight, display proxy.

Found in the audit: attachments stopped at 60 MB, the app read the whole file on its interface thread and sent it to
the engine over HTTP, and nothing said how heavy a mesh was before work on it began.

The large-file test (a generated binary STL of 250 MB) runs only with FORM_SLOW_TESTS=1."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("FORM_SKIP_UI", "1")

from form import conversations, meshprep  # noqa: E402
from form.conversations import Conversations, ConversationError  # noqa: E402
from form.recon import mesh  # noqa: E402

from big_mesh import sphere, write_sphere_stl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("FORM_SLOW_TESTS") == "1"


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = self.tmp / "cache"


class Preflight(Tmp):
    def test_a_small_closed_mesh(self):
        V, F = sphere(5000)
        mesh.write_stl(self.tmp / "s.stl", V, F)
        r = meshprep.preflight(self.tmp / "s.stl", cache=self.cache)
        self.assertEqual((r["triangles"], r["closed"], r["boundary_edges"], r["class"]), (len(F), True, 0, "light"))
        self.assertIsNone(r["proxy"])                       # light enough to draw as it is
        np.testing.assert_allclose(r["size_mm"], np.ptp(V, axis=0), atol=1e-3)
        self.assertIn("estimate", r["estimate_note"].lower())

    def test_an_open_mesh_is_not_closed(self):
        V, F = sphere(5000)
        mesh.write_stl(self.tmp / "open.stl", V, F[:-10])
        r = meshprep.preflight(self.tmp / "open.stl", cache=self.cache)
        self.assertFalse(r["closed"])
        self.assertGreater(r["boundary_edges"], 0)

    def test_a_heavy_mesh_gets_a_display_proxy_and_the_source_is_untouched(self):
        src = self.tmp / "scan.stl"
        n = write_sphere_stl(src, triangles=1_200_000)
        before = (src.stat().st_size, mesh.sha256_file(src))
        t = time.perf_counter()
        r = meshprep.preflight(src, cache=self.cache)
        first = time.perf_counter() - t
        self.assertLess(first, 10.0, "preflight and proxy for 1.2M triangles")
        self.assertEqual((r["triangles"], r["class"], r["closed"]), (n, "heavy", True))
        proxy = Path(r["proxy"]["path"])
        self.assertTrue(proxy.is_file() and proxy.is_relative_to(self.cache))
        self.assertLess(r["proxy"]["triangles"], 1.3 * meshprep.PROXY_TRIANGLES)
        self.assertIn("display only", r["proxy"]["note"])
        pv = mesh.read_triangles(proxy)[0].reshape(-1, 3)
        np.testing.assert_allclose(pv.max(0) - pv.min(0), r["size_mm"], rtol=0.05)   # the same thing, lighter
        self.assertEqual((src.stat().st_size, mesh.sha256_file(src)), before)
        t = time.perf_counter()
        again = meshprep.preflight(src, cache=self.cache)
        self.assertLess(time.perf_counter() - t, 0.2, "a cached preflight")
        self.assertTrue(again["cached"])
        self.assertEqual(again["proxy"]["path"], r["proxy"]["path"])
        os.utime(src, ns=(time.time_ns(), time.time_ns() + 10_000_000_000))   # a changed file is looked at again
        self.assertFalse(meshprep.preflight(src, cache=self.cache, proxy=False)["cached"])

    def test_3mf_parts_are_listed(self):
        r = meshprep.preflight(ROOT / "tests/fixtures/3mf/bambustudio-2.9-two-objects.3mf", cache=self.cache)
        self.assertEqual([p["name"] for p in r["parts"]], ["cube.stl", "bar.stl"])
        self.assertEqual(r["triangles"], 24)

    def test_quick_reads_only_the_header(self):
        V, F = sphere(2000)
        mesh.write_stl(self.tmp / "q.stl", V, F)
        with mock.patch.object(mesh, "read_parts", side_effect=AssertionError("must not read the mesh")):
            q = meshprep.quick(self.tmp / "q.stl")
        self.assertEqual((q["triangles"], q["class"]), (len(F), "light"))
        with mock.patch.object(meshprep, "WARN_BYTES", 10):
            self.assertIn("very large", meshprep.quick(self.tmp / "q.stl")["warning"])

    def test_cli(self):
        V, F = sphere(500)
        mesh.write_stl(self.tmp / "c.stl", V, F)
        env = {**os.environ, "FORM_DATA": str(self.tmp / "data")}
        out = subprocess.run([sys.executable, "-m", "form", "mesh-preflight", str(self.tmp / "c.stl")], cwd=ROOT,
                             capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["triangles"], len(F))


class AttachByPath(Tmp):
    def test_a_local_file_is_placed_not_read(self):
        store = Conversations(self.tmp / "data")
        cid = store.create()["id"]
        src = self.tmp / "scan.stl"
        V, F = sphere(20000)
        mesh.write_stl(src, V, F)
        real_read = Path.read_bytes

        def no_read(p):
            if Path(p) == src:
                raise AssertionError("the attachment was read into memory")
            return real_read(p)
        with mock.patch.object(Path, "read_bytes", no_read):
            rec = store.attach(cid, src)
        self.assertIn(rec["placed"], ("cloned", "linked", "copied"))
        if sys.platform == "darwin":
            self.assertEqual(rec["placed"], "cloned")          # APFS: a copy-on-write clone, instant
        self.assertEqual((rec["kind"], rec["mesh"]["triangles"]), ("cad", len(F)))
        f = store.attachment(cid, rec["file"])
        self.assertEqual(mesh.sha256_file(f), mesh.sha256_file(src))

    def test_limits(self):
        store = Conversations(self.tmp / "data")
        cid = store.create()["id"]
        self.assertEqual(conversations.MAX_ATTACHMENT, 2_000_000_000)
        (self.tmp / "big.stl").write_bytes(b"solid x\nendsolid x\n")
        with mock.patch.object(conversations, "MAX_ATTACHMENT", 10), self.assertRaises(ConversationError) as e:
            store.attach(cid, self.tmp / "big.stl")
        self.assertIn("larger than", str(e.exception))
        (self.tmp / "part.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        self.assertEqual(store.attach(cid, self.tmp / "part.obj")["kind"], "cad")

    def test_placement_falls_back(self):
        a, b, c = self.tmp / "a.bin", self.tmp / "b.bin", self.tmp / "c.bin"
        a.write_bytes(b"x" * 1000)
        with mock.patch.object(conversations, "_clone", return_value=False):
            self.assertEqual(conversations.place(a, b), "linked")
            with mock.patch.object(os, "link", side_effect=OSError("cross-device")):
                self.assertEqual(conversations.place(a, c), "copied")
        self.assertEqual(c.read_bytes(), b"x" * 1000)


ATTACH_PROBE = r"""
import json, resource, sys, time
from pathlib import Path
from form.conversations import Conversations
store = Conversations(Path(sys.argv[1]))
cid = store.create()["id"]
base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
t = time.perf_counter()
rec = store.attach(cid, Path(sys.argv[2]))
dt = time.perf_counter() - t
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
scale = 1 if sys.platform == "darwin" else 1024          # bytes on macOS, kilobytes on Linux
print(json.dumps({"seconds": dt, "rss_growth": (peak - base) * scale, "placed": rec["placed"], "rec": rec}))
"""


@unittest.skipUnless(SLOW, "set FORM_SLOW_TESTS=1 to attach and preflight a generated 250 MB STL")
class LargeFile(Tmp):
    def test_a_250_mb_stl(self):
        src = self.tmp / "dense-scan.stl"
        n = write_sphere_stl(src, megabytes=250)
        self.assertGreaterEqual(src.stat().st_size, 200_000_000)
        out = subprocess.run([sys.executable, "-c", ATTACH_PROBE, str(self.tmp / "data"), str(src)], cwd=ROOT,
                             capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertLess(got["seconds"], 2.0, got)
        self.assertLess(got["rss_growth"], 150_000_000, got)
        self.assertEqual(got["rec"]["mesh"]["triangles"], n)
        t = time.perf_counter()
        r = meshprep.preflight(src, cache=self.cache)
        print(f"\n250 MB STL ({n} triangles): attach {got['seconds']:.3f} s ({got['placed']}, RSS +"
              f"{got['rss_growth'] / 1e6:.1f} MB), preflight + proxy {time.perf_counter() - t:.1f} s", file=sys.stderr)
        self.assertEqual((r["triangles"], r["closed"]), (n, True))
        self.assertIn(r["class"], ("heavy", "very heavy"))
        self.assertTrue(Path(r["proxy"]["path"]).is_file())


class BridgeUpload(Tmp):
    """The app's side: Bridge.upload returns at once; an attachment goes to the engine as a path, other uploads are
    streamed from a worker thread. Nothing is read on the interface thread."""

    def test_upload_never_reads_on_the_interface_thread(self):
        try:
            from PySide6.QtCore import QCoreApplication, QUrl
            from form.app.bridge import Bridge
        except ImportError as e:                            # no Qt here: the app is not installed with [app]
            self.skipTest(f"PySide6 not available: {e}")
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        got, done = [], threading.Event()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                got.append((self.path, self.headers.get("Content-Type"), self.rfile.read(n)))
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if len(got) == 2:
                    done.set()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        app = QCoreApplication.instance() or QCoreApplication([])  # noqa: F841
        big = self.tmp / "scan.stl"
        with open(big, "wb") as f:
            f.truncate(64_000_000)
        (self.tmp / "a.formstudio").write_bytes(b"archive")
        b = Bridge("127.0.0.1", srv.server_address[1], str(self.tmp), "test")
        real = Path.read_bytes
        with mock.patch.object(Path, "read_bytes", lambda p: (_ for _ in ()).throw(AssertionError("read")) if p == big else real(p)):
            t = time.perf_counter()
            b.upload(1, "/conversations/0123456789ab/attach?name=dense%20scan.stl", QUrl.fromLocalFile(str(big)))
            b.upload(2, "/import", QUrl.fromLocalFile(str(self.tmp / "a.formstudio")))
            self.assertLess(time.perf_counter() - t, 0.05, "Bridge.upload blocked the interface thread")
        self.assertTrue(done.wait(20))
        by = {p: (ct, body) for p, ct, body in got}
        ct, body = by["/api/conversations/0123456789ab/attach"]
        self.assertEqual(ct, "application/json")
        self.assertEqual(json.loads(body), {"paths": [str(big)], "names": ["dense scan.stl"]})
        self.assertEqual(by["/api/import"], ("application/octet-stream", b"archive"))


if __name__ == "__main__":
    unittest.main()
