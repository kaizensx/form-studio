"""One-click optional engines (form/engines.py, form/installer.py): every optional row can be installed or has a page,
the packaged app builds an engine's own Python with a checked uv, a failed build leaves nothing behind, and the
engines run out of process with that interpreter. Nothing here downloads anything: uv is a local stand-in script and
every download is replaced."""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from form import config, engines, installer

POSIX = os.name != "nt"


def cfg_for(tmp: Path) -> dict:
    c = {k: dict(v) for k, v in config.DEFAULTS.items()}
    c["data"]["dir"] = str(tmp / "data")
    c["_path"] = str(tmp / "studio.toml")
    return c


def _no_network(*a, **k):
    raise AssertionError("a test tried to use the network")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-engines-"))
        self.cfg = cfg_for(self.tmp)
        self.env = mock.patch.dict(os.environ, {"FORM_ENGINES_DIR": str(self.tmp / "engines"),
                                                "FORM_CONFIG": str(self.tmp / "studio.toml"),
                                                "FORM_DATA": str(self.tmp / "data")})
        self.env.start()
        for k in ("FORM_INSTALL_FAKE", "FORM_RECON_CADFIT", "FORM_INSTALL_MOCK_DOWNLOADS", "FORM_CADRECODE_DIR",
                  "FORM_EXEMPLAR_CORPUS_DIR"):
            os.environ.pop(k, None)
        self.net = mock.patch("urllib.request.urlopen", _no_network)
        self.net.start()

    def tearDown(self):
        self.net.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_env(self, eid: str) -> Path:
        """A complete engine environment whose python is this test's own interpreter (a wrapper that execs it, so the
        process is the one its parent started and it keeps this environment's libraries)."""
        d = self.tmp / "engines" / eid
        py = engines.env_python(d)
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n", encoding="utf-8")
        py.chmod(0o755)
        (d / engines.MARKER).write_text("{}", encoding="utf-8")
        return py


class EveryRowHasAnAction(Base):
    """The owner's complaint: "not installed" and no button. In the packaged app, with everything reported missing,
    every optional row is installable here or names a page to get it."""

    def rows(self, which=None):
        ids = ",".join(s.id for s in installer.REGISTRY)
        with mock.patch.object(installer, "frozen", lambda: True), \
             mock.patch.dict(os.environ, {"FORM_SETUP_PRETEND_MISSING": ids}):
            return installer.survey(self.cfg, which=which)

    def check(self, rows):
        shown = [r for r in rows if r["id"] != "claude.signin" and not r.get("absent")]   # sign-in has its own card
        self.assertGreater(len(shown), 20)
        for r in shown:
            if r["level"] == "required":
                continue
            if r.get("blocked_by"):
                continue                                 # "Install <that> first" is the action
            self.assertTrue(r["installable"] or r["manual"], (r["id"], r["methods"]))

    def test_frozen_with_nothing_on_path(self):
        self.check(self.rows(which=lambda n: None))

    def test_frozen_with_this_computers_tools(self):
        self.check(self.rows())

    def test_engines_install_in_one_click_in_the_packaged_app(self):
        rows = {r["id"]: r for r in self.rows(which=lambda n: None)}
        for sid in ("recon.learned", "recon.cadfit", "exemplars.cadevolve"):
            r = rows[sid]
            self.assertTrue(r["installable"], sid)
            self.assertEqual(r["plan"]["kind"], "action", sid)
            self.assertTrue(r["size"] and r["licence"] and r["licence_url"], sid)
        for sid in ("recon.learned", "recon.cadfit"):
            self.assertTrue(rows[sid]["noncommercial"])
            self.assertIn("CC BY-NC 4.0", rows[sid]["licence_notice"])
            self.assertIn("accepts", rows[sid]["licence_notice"])
            self.assertTrue(any("uv-" in c and engines.UV_VERSION in c for c in rows[sid]["plan"]["commands"]))
        self.assertFalse(rows["exemplars.cadevolve"]["noncommercial"])
        self.assertEqual(rows["exemplars.cadevolve"]["licence_notice"], "")
        self.assertIn("--accept-licence cc-by-nc-4.0", rows["recon.learned"]["plan"]["commands"][-1])
        self.assertIn("cadfit = true", rows["recon.cadfit"]["plan"]["commands"][-1])

    def test_noncommercial_rows_are_never_pre_ticked_or_installed_by_themselves(self):
        rows = installer.survey(self.cfg)
        for r in rows:
            if r["noncommercial"]:
                self.assertFalse(r["default"], r["id"])
        self.assertFalse({"recon.learned", "recon.cadfit"} & set(installer.auto_ids(rows, self.cfg)))


def _uv_stand_in(folder: Path, pip_exit: int = 0) -> Path:
    """A `uv` that makes a venv by linking this interpreter and whose `pip install` exits with pip_exit."""
    uv = folder / "uv"
    uv.write_text("#!/bin/sh\n"
                  "if [ \"$1\" = venv ]; then for a; do d=\"$a\"; done; mkdir -p \"$d/bin\"; "
                  f"ln -s '{sys.executable}' \"$d/bin/python\"; echo made \"$d\"; exit 0; fi\n"
                  f"if [ \"$1\" = pip ]; then echo installing \"$@\"; exit {pip_exit}; fi\nexit 3\n", encoding="utf-8")
    uv.chmod(0o755)
    return uv


@unittest.skipUnless(POSIX, "the uv stand-in is a shell script")
class BuildAnEnvironment(Base):
    def install(self, uv: Path, ids=("recon.cadfit",)):
        with mock.patch.object(installer, "frozen", lambda: True), \
             mock.patch.object(engines, "ensure_uv", lambda r, io: uv), \
             mock.patch.dict(engines.SPECS["recon.cadfit"], {"check": "import json"}):
            job = installer.Installer(self.cfg).install(list(ids), start=False)
            job.run()
        return job

    def test_install_builds_the_environment_and_turns_cadfit_on(self):
        job = self.install(_uv_stand_in(self.tmp))
        self.assertEqual(job.state, "done", job.public()["log"])
        py = engines.python("recon.cadfit", self.cfg)
        self.assertIsNotNone(py)
        self.assertEqual(json.loads((self.tmp / "engines" / "recon.cadfit" / engines.MARKER).read_text())["uv"],
                         engines.UV_VERSION)
        self.assertEqual(self.cfg["recon"]["cadfit"], True)
        self.assertIn("[recon]\ncadfit = true", (self.tmp / "studio.toml").read_text(encoding="utf-8"))
        self.assertEqual(job.after["recon.cadfit"]["status"], "ok")
        cmds = [l["text"] for l in job.public()["log"] if l["kind"] == "cmd"]
        self.assertTrue(any(" venv --python 3.12 " in c for c in cmds), cmds)
        self.assertTrue(any(" pip install --python " in c and "trimesh==" in c for c in cmds), cmds)
        self.assertEqual([p.name for p in (self.tmp / "engines").iterdir() if ".partial" in p.name], [])

    def test_a_failed_install_leaves_things_as_they_were(self):
        old = self.tmp / "engines" / "recon.cadfit"
        old.mkdir(parents=True)
        (old / "left-by-an-earlier-try").write_text("x")          # incomplete (no marker), so not used
        job = self.install(_uv_stand_in(self.tmp, pip_exit=1))
        self.assertEqual(job.state, "failed")
        self.assertIn("exited with 1", job.steps[0]["message"])
        self.assertEqual(sorted(p.name for p in (self.tmp / "engines").iterdir()), ["recon.cadfit"])
        self.assertEqual([p.name for p in old.iterdir()], ["left-by-an-earlier-try"])
        self.assertIsNone(engines.python("recon.cadfit", self.cfg))
        self.assertFalse(self.cfg["recon"]["cadfit"])
        self.assertFalse((self.tmp / "studio.toml").exists())

    def test_learned_downloads_its_weights_with_the_environments_python(self):
        seen = []

        def fake_run(self_, argv, env=None, timeout=None):
            seen.append([str(a) for a in argv])
            if "download" in argv:                          # the weights: written where the command says
                d = Path(argv[argv.index("--dir") + 1])
                (d / "tokenizer").mkdir(parents=True)
                for f in ("config.json", "model.safetensors", "form-download.json"):
                    (d / f).write_text("{}")
                for f in ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"):
                    (d / "tokenizer" / f).write_text("{}")
            elif argv[1] == "venv":
                (Path(argv[-1]) / "bin").mkdir(parents=True)
                (Path(argv[-1]) / "bin" / "python").symlink_to(sys.executable)
        with mock.patch.object(installer._Runner, "run", fake_run), \
             mock.patch.object(installer, "frozen", lambda: True), \
             mock.patch.object(engines, "ensure_uv", lambda r, io: Path("/x/uv")):
            job = installer.Installer(self.cfg).install(["recon.learned"], start=False)
            job.run()
        self.assertEqual(job.steps[0]["state"], "done", job.public()["log"])
        dl = next(a for a in seen if "download" in a)
        self.assertEqual(dl[1:4], ["-m", "form.recon.learned", "download"])
        self.assertIn("cc-by-nc-4.0", dl)
        self.assertTrue(dl[0].endswith("bin/python") and ".partial" in dl[0], dl[0])   # the new environment's python
        from form.recon import learned
        st = learned.status(Path(self.cfg["data"]["dir"]) / "models" / "cad-recode")
        self.assertTrue(st["installed"], st)
        self.assertIn("recon.learned", st["runs_in"])


class Uv(Base):
    def _tar(self, body: bytes) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            info = tarfile.TarInfo("uv-test/uv")
            info.size = len(body)
            t.addfile(info, io.BytesIO(body))
        return buf.getvalue()

    def io(self):
        lines = []
        return mock.Mock(say=lines.append, cancelled=lambda: False), lines

    def serve(self, data: bytes):
        def dl(url, dest, io_):
            self.urls.append(url)
            dest.write_bytes(data)
            return hashlib.sha256(data).hexdigest()
        self.urls = []
        return mock.patch.object(engines, "_download", dl)

    def test_a_uv_whose_checksum_differs_is_never_used(self):
        r = self.tmp / "engines"
        io_, _ = self.io()
        with self.serve(self._tar(b"#!/bin/sh\necho evil\n")), \
             mock.patch.object(engines, "uv_asset", lambda: ("uv-test.tar.gz", "0" * 64)):
            with self.assertRaises(engines.EngineError) as e:
                engines.ensure_uv(r, io_)
        self.assertIn("not used", str(e.exception))
        self.assertFalse((r / ".uv").exists() and any((r / ".uv").rglob("uv")))

    def test_the_pinned_uv_is_fetched_once_and_checked(self):
        r = self.tmp / "engines"
        data = self._tar(b"#!/bin/sh\necho uv\n")
        io_, lines = self.io()
        with self.serve(data), mock.patch.object(engines, "uv_asset",
                                                  lambda: ("uv-test.tar.gz", hashlib.sha256(data).hexdigest())):
            exe = engines.ensure_uv(r, io_)
            self.assertEqual(engines.ensure_uv(r, io_), exe)           # second time: no download
        self.assertEqual(len(self.urls), 1)
        self.assertTrue(self.urls[0].startswith(engines.UV_BASE))
        self.assertTrue(os.access(exe, os.X_OK) or not POSIX)
        self.assertTrue(any("SHA-256 matches" in l for l in lines))

    def test_every_pinned_asset_has_a_sha256(self):
        for key, (asset, sha) in engines.UV_ASSETS.items():
            self.assertRegex(sha, r"^[0-9a-f]{64}$", key)
            self.assertTrue(asset.startswith("uv-") and asset.endswith((".tar.gz", ".zip")), asset)
        for eid, spec in engines.SPECS.items():
            self.assertTrue(all("==" in p for p in spec["pins"]), eid)              # pinned, not ranges


@unittest.skipUnless(POSIX, "the stand-in engine interpreter is linked")
class OutOfProcess(Base):
    def test_cadfit_status_and_search_use_the_engine_python(self):
        from form.recon import cadfit
        py = self.fake_env("recon.cadfit")
        st = cadfit.status()
        self.assertTrue(st["installed"])
        self.assertEqual(st["engine_python"], str(py))
        child = ("import json, os, sys, time; assert sys.argv[4] == str(os.getppid()); "
                 "print(json.dumps({'script': 'a', 'iou': 0.9}), flush=True); "
                 "print(json.dumps({'script': 'b', 'iou': 0.99, 'final': True}), flush=True)")
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
        F = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        with mock.patch.object(cadfit, "ENGINE_CHILD", child):
            got = cadfit._search(V, F, 20.0)
        self.assertEqual((got["script"], got["iou"]), ("b", 0.99))
        self.assertNotIn("timed_out", got)
        slow = "import json, time; print(json.dumps({'script': 'a', 'iou': 0.5}), flush=True); time.sleep(60)"
        t = time.time()
        with mock.patch.object(cadfit, "ENGINE_CHILD", slow):
            got = cadfit._search(V, F, 2.0)
        self.assertLess(time.time() - t, 15)
        self.assertTrue(got["timed_out"])
        self.assertEqual(got["script"], "a")

    def test_learned_generation_runs_in_the_engine_python(self):
        from form.recon import learned
        from form.recon.learned import engine
        py = self.fake_env("recon.learned")
        self.assertEqual(learned.engine_python(), py)
        child = ("import json, os, sys, numpy as np; d = np.load(sys.argv[1]); "
                 "open(sys.argv[3], 'w').write(json.dumps({'code': 'r = 1', 'pid': os.getpid(), "
                 "'n': int(len(d['V'])), 'parent': int(sys.argv[4])}))")
        V = np.zeros((5, 3))
        F = np.zeros((2, 3), dtype=int)
        with mock.patch.object(engine, "CHILD", child):
            got = engine.generate_in(py, V, F, self.tmp)
        self.assertEqual((got["code"], got["n"], got["parent"]), ("r = 1", 5, os.getpid()))
        self.assertNotEqual(got["pid"], os.getpid())
        with mock.patch.object(engine, "CHILD", "import sys; sys.exit('no weights here')"):
            with self.assertRaises(RuntimeError) as e:
                engine.generate_in(py, V, F, self.tmp)
        self.assertIn("no weights here", str(e.exception))

    def test_child_environment_carries_only_the_engine_source(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/somewhere/else", "VIRTUAL_ENV": "/v"}):
            env = engines.child_env()
        self.assertEqual(env["PYTHONPATH"], str(engines.src_root()))
        self.assertNotIn("VIRTUAL_ENV", env)
        self.assertTrue((engines.src_root() / "form" / "recon" / "cadfit" / "PERMISSION.md").is_file())
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "_MEIPASS", "/app/x", create=True):
            self.assertEqual(engines.src_root(), Path("/app/x/engine_src"))


class Corpus(Base):
    def test_one_click_with_a_stand_in_download(self):
        with mock.patch.dict(os.environ, {"FORM_INSTALL_MOCK_DOWNLOADS": "1"}):
            job = installer.Installer(self.cfg).install(["exemplars.cadevolve"], start=False)
            job.run()
        self.assertEqual(job.state, "done", job.public()["log"])
        self.assertEqual(job.after["exemplars.cadevolve"]["status"], "ok")
        log = " ".join(l["text"] for l in job.public()["log"])
        self.assertIn("FORM_INSTALL_MOCK_DOWNLOADS is set", log)
        self.assertIn("(stand-in download)", log)
        folder = Path(self.cfg["data"]["dir"]) / "corpus"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["cadevolve"])

    def test_a_failed_download_leaves_nothing(self):
        def broken(*a, **k):
            raise OSError("connection reset")
        with mock.patch("form.exemplars.corpus.download", broken):
            job = installer.Installer(self.cfg).install(["exemplars.cadevolve"], start=False)
            job.run()
        self.assertEqual(job.state, "failed")
        self.assertIn("connection reset", job.steps[0]["message"])
        self.assertFalse((Path(self.cfg["data"]["dir"]) / "corpus").exists()
                         and any((Path(self.cfg["data"]["dir"]) / "corpus").iterdir()))


class CardsSayWhatTheyDo(Base):
    """Settings › Software: every optional engine says what it does and when you would want it, and what it gives
    you; the texts name what the code really does (no fillets in CADFit, MIT CoACD, reference-only corpus)."""

    def test_every_engine_card_has_a_description_and_what_it_gives(self):
        rows = {r["id"]: r for r in installer.survey(self.cfg)}
        for sid in ("recon.learned", "recon.cadfit", "game.coacd", "exemplars.cadevolve", "blender", "freecad",
                    "openscad", "slicer.bambu", "slicer.orca", "slicer.prusa", "parts", "kernel"):
            r = rows[sid]
            self.assertGreater(len(r["about"]), 60, sid)
            self.assertTrue(r["gives"], sid)
            self.assertLess(len(r["gives"]), 200, sid)
        self.assertIn("point cloud", rows["recon.learned"]["about"])
        self.assertIn("Non-commercial", rows["recon.learned"]["about"])
        self.assertIn("revolves", rows["recon.cadfit"]["about"])
        self.assertNotIn("fillet", rows["recon.cadfit"]["about"].lower())     # its fillet pass is not run here
        self.assertIn("convex", rows["game.coacd"]["about"])
        self.assertEqual(rows["game.coacd"]["licence"], "MIT")
        self.assertIn("never run", rows["exemplars.cadevolve"]["about"])
        self.assertIn("game assets", rows["blender"]["about"])
        self.assertTrue(all("about" in r and "gives" in r for r in rows.values()))


class RemoveWhatFormStudioDownloaded(Base):
    def test_remove_deletes_the_engine_environment_and_only_that(self):
        self.fake_env("game.coacd")
        other = self.tmp / "engines" / "recon.cadfit" / "keep.txt"
        other.parent.mkdir(parents=True)
        other.write_text("x", encoding="utf-8")
        rows = {r["id"]: r for r in installer.survey(self.cfg, only=["game.coacd"])}
        self.assertEqual(rows["game.coacd"]["status"], "ok")
        self.assertTrue(rows["game.coacd"]["removable"])
        r = installer.remove("game.coacd", self.cfg)
        self.assertFalse((self.tmp / "engines" / "game.coacd").exists())
        self.assertTrue(other.exists(), "another engine is left alone")
        self.assertIn("Removed CoACD", r["message"])
        rows = {r["id"]: r for r in installer.survey(self.cfg, only=["game.coacd"])}
        self.assertEqual(rows["game.coacd"]["status"], "missing")
        self.assertFalse(rows["game.coacd"]["removable"])

    def test_remove_cadfit_turns_it_off(self):
        self.fake_env("recon.cadfit")
        installer._enable_cadfit(self.cfg)
        installer.remove("recon.cadfit", self.cfg)
        self.assertFalse((self.tmp / "engines" / "recon.cadfit").exists())
        from form import config as cfgmod
        self.assertFalse((cfgmod.load().get("recon") or {}).get("cadfit", False))

    def test_the_corpus_and_the_weights_are_removed_from_the_data_folder(self):
        corpus = Path(self.cfg["data"]["dir"]) / "corpus" / "cadevolve"
        corpus.mkdir(parents=True)
        (corpus / "parametric_generators.json").write_text("[]", encoding="utf-8")
        self.assertEqual(installer.removable_paths("exemplars.cadevolve", self.cfg), [corpus.resolve()])
        installer.remove("exemplars.cadevolve", self.cfg)
        self.assertFalse(corpus.exists())
        self.assertTrue((Path(self.cfg["data"]["dir"])).exists(), "the data folder itself stays")

    def test_nothing_outside_form_studios_folders_and_nothing_else_is_removable(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        with mock.patch.dict(os.environ, {"FORM_EXEMPLAR_CORPUS_DIR": str(outside)}):
            self.assertEqual(installer.removable_paths("exemplars.cadevolve", self.cfg), [])
        for sid in ("blender", "slicer.bambu", "kernel", "claude", "freecad"):
            self.assertEqual(installer.removable_paths(sid, self.cfg), [], sid)
            with self.assertRaises(installer.InstallError):
                installer.remove(sid, self.cfg)
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
