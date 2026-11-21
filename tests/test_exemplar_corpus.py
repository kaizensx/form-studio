"""The exemplar corpus (package C): twelve exemplars hand-ported from CADEvolve's seeds, and the opt-in CADEvolve
corpus as a second, lower search tier. Nothing here downloads: the network is patched to fail, and the corpus is a
small fake written to a temporary folder."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="form-exemplar-corpus-"))
os.environ["FORM_EXEMPLAR_CORPUS_DIR"] = str(TMP / "no-corpus-here")       # never the person's data folder

from form import exemplars  # noqa: E402
from form.exemplars import corpus  # noqa: E402

PORTED = ["bearing_flange", "braille_sign", "compression_spring", "connector_panel", "door_wedge", "fan_duct_adapter",
          "flat_flask", "i_beam", "pipe_elbow", "pipe_saddle_clamp", "screw_post_enclosure", "spur_gear"]
ROUTED = "full-face helmet separate parts magnets lens texture"
FAKE = [{"name": "flanged_bolt_plate", "abstract": "flanged bolt plate",
         "detailed": "Square plate with a raised flange and a bolt circle of counterbored holes.",
         "code": "def flanged_bolt_plate(L=40):\n    return cq.Workplane('XY').box(L, L, 5)"},
        {"name": "hex_standoff", "abstract": "hexagonal standoff", "detailed": "Hex prism with a threaded bore.",
         "code": "def hex_standoff(A=5, H=20):\n    return cq.Workplane('XY').polygon(6, 2*A).extrude(H)"}]


def _no_network(*a, **k):
    raise AssertionError("a test tried to use the network")


@contextlib.contextmanager
def fake_corpus():
    folder = TMP / "fake-corpus"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / corpus.KEEP).write_text(json.dumps(FAKE), encoding="utf-8")
    (folder / corpus.MARKER).write_text("{}", encoding="utf-8")
    with mock.patch.dict(os.environ, {"FORM_EXEMPLAR_CORPUS_DIR": str(folder)}):
        yield folder


def _tar(members: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Ported(unittest.TestCase):
    def test_every_ported_exemplar_names_its_source_and_licence(self):
        names = {e["name"]: e for e in exemplars.catalogue()}
        for n in PORTED:
            with self.subTest(n):
                o = names[n]["origin"]
                self.assertEqual(o["repo"], "kulibinai/CADEvolve")
                self.assertEqual(o["sha"], corpus.CODE_SHA)
                self.assertEqual(o["licence"], "Apache-2.0")
                self.assertEqual(o["modified"], "modified (ported to build123d / Form Studio)")
                self.assertTrue(o["seed"] and o["path"])
                self.assertIn("CADEvolve", exemplars.get(n)["source"].split('"""')[1])   # said in the docstring too
                self.assertGreaterEqual(len(names[n]["steps"]), 2)                     # one @feature per feature
                self.assertIn("class Design(FeatureDesign)", exemplars.get(n)["source"])
        lic = (ROOT / "form" / "exemplars" / "LICENSE-CADEvolve").read_text(encoding="utf-8")
        self.assertIn("Apache License", lic)
        self.assertIn("Version 2.0, January 2004", lic)
        self.assertIn(corpus.CODE_SHA, lic)

    def test_corpus_module_is_not_an_exemplar(self):
        names = {e["name"] for e in exemplars.catalogue()}
        self.assertNotIn("corpus", names)
        self.assertLessEqual(set(PORTED), names)
        with self.assertRaises(KeyError):
            exemplars.get("corpus")
        with self.assertRaises(KeyError):
            exemplars.path("corpus")

    def test_every_ported_exemplar_builds(self):
        """Built the way the kernel builds a design: valid, the declared solid count, no feature skipped."""
        spec = importlib.util.spec_from_file_location("exemplar_check", ROOT / "scripts" / "exemplar_check.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for n in PORTED:
            with self.subTest(n):
                r = mod.check(n)
                self.assertTrue(r["ok"], r)
                self.assertEqual(r["skipped"], [])


class Tiers(unittest.TestCase):
    def test_without_the_corpus_search_is_form_only(self):
        self.assertFalse(corpus.installed())
        self.assertEqual(exemplars.reference_hits("flanged bolt plate"), [])
        hits = exemplars.search(ROUTED, 5)
        self.assertEqual(hits[0]["name"], "hero_helmet")
        self.assertFalse(any("tier" in h for h in hits))
        self.assertEqual([h["name"] for h in exemplars.search("hinged case", 5)],
                         [h["name"] for h in exemplars.search("hinged case", 5, reference=0)])

    def test_corpus_hits_follow_every_form_hit(self):
        with fake_corpus():
            self.assertTrue(corpus.installed())
            for q in ("flanged bolt plate with counterbored holes", "hex standoff", ROUTED):
                hits = exemplars.search(q, 5)
                tiers = [h.get("tier", "form") for h in hits]
                self.assertEqual(tiers, sorted(tiers, key=lambda t: t == "reference"), q)   # never before a Form hit
                self.assertLessEqual(tiers.count("reference"), 2)
                for h in hits[len(tiers) - tiers.count("reference"):]:
                    self.assertTrue(h["name"].startswith("cadevolve:"))
                    self.assertEqual(h["label"], "reference CadQuery, not the Form API")
            self.assertEqual(exemplars.search(ROUTED, 5)[0]["name"], "hero_helmet")
            ref = [h for h in exemplars.search("flanged bolt plate", 3) if h.get("tier") == "reference"]
            self.assertEqual(ref[0]["name"], "cadevolve:flanged_bolt_plate")
            self.assertFalse(any(h.get("tier") for h in exemplars.search("flanged bolt plate", 5, "mechanical")))
            self.assertFalse(any(h.get("tier") for h in exemplars.search("flanged bolt plate", 5, reference=0)))
            got = exemplars.get("cadevolve:hex_standoff")
            self.assertIn("polygon(6", got["code"])
            self.assertEqual(got["tier"], "reference")
            self.assertIn("not the Form API", got["how_to_use"])
            with self.assertRaises(KeyError):
                exemplars.get("cadevolve:nothing")
            self.assertNotIn("cadevolve:hex_standoff", {e["name"] for e in exemplars.catalogue()})

    def test_a_broken_corpus_never_breaks_search(self):
        with fake_corpus() as folder:
            (folder / corpus.KEEP).write_text("{not json", encoding="utf-8")
            self.assertEqual(exemplars.reference_hits("hex standoff"), [])
            self.assertEqual(exemplars.search(ROUTED, 3)[0]["name"], "hero_helmet")


class Download(unittest.TestCase):
    def test_only_cadevolve_g_is_ever_wanted(self):
        ok = ["CADEvolve-G/parametric_generators.json", "cadevolve/CADEvolve-G/parametric_generators.json"]
        bad = ["CADEvolve-P/ABC-P/0001.py", "CADEvolve-C/ShapeNet-C/chair.py", "CADEvolve-G/embeddings/e.npy",
               "ABC-G/CADEvolve-G/parametric_generators.json", "ShapeNet-P/CADEvolve-G/parametric_generators.json",
               "../CADEvolve-G/parametric_generators.json", "/CADEvolve-G/parametric_generators.json",
               "parametric_generators.json", "CADEvolve-P/CADEvolve-P-core/parametric_generators.json"]
        for m in ok:
            self.assertTrue(corpus.wanted(m), m)
        for m in bad:
            self.assertFalse(corpus.wanted(m), m)

    def test_extract_writes_only_the_generators(self):
        data = _tar({"cadevolve/CADEvolve-G/parametric_generators.json": json.dumps(FAKE).encode(),
                     "cadevolve/CADEvolve-G/embeddings/e.npy": b"x" * 64,
                     "cadevolve/CADEvolve-P/ABC-P/a.py": b"print('abc')",
                     "cadevolve/CADEvolve-C/ShapeNet-C/s.py": b"print('shapenet')",
                     "cadevolve/CADEvolve-P/CADEvolve-P-core/c.py": b"print('core')"})
        folder = TMP / "extract"
        written = corpus.extract(io.BytesIO(data), folder)
        self.assertEqual(written, ["cadevolve/CADEvolve-G/parametric_generators.json"])
        self.assertEqual(sorted(p.name for p in folder.rglob("*")), [corpus.KEEP])
        self.assertEqual(len(corpus.entries(folder)), 2)

    def test_download_checks_the_tar_and_keeps_nothing_on_a_mismatch(self):
        data = _tar({"CADEvolve-G/parametric_generators.json": json.dumps(FAKE).encode(),
                     "CADEvolve-P/ABC-P/a.py": b"print('abc')"})
        folder = TMP / "dl"
        with mock.patch("urllib.request.urlopen", _no_network):
            with self.assertRaises(RuntimeError):
                corpus.download(folder, echo=lambda s: None, opener=lambda: io.BytesIO(data))
            self.assertFalse((folder / corpus.KEEP).exists())
            self.assertFalse((folder / corpus.MARKER).exists())
            with mock.patch.object(corpus, "TAR_SHA256", hashlib.sha256(data).hexdigest()):
                info = corpus.download(folder, echo=lambda s: None, opener=lambda: io.BytesIO(data))
        self.assertEqual(info["kept"], ["CADEvolve-G/parametric_generators.json"])
        self.assertTrue(corpus.status(folder)["installed"])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([corpus.KEEP, corpus.MARKER]))

    def test_download_refuses_without_the_licence(self):
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", _no_network), contextlib.redirect_stderr(err):
            self.assertEqual(corpus.main(["download", "--dir", str(TMP / "refused")]), 2)
            self.assertEqual(corpus.main(["download", "--accept-licence", "mit", "--dir", str(TMP / "refused")]), 2)
        self.assertIn("4.73 GB", err.getvalue())
        self.assertIn("Apache-2.0", err.getvalue())
        self.assertFalse((TMP / "refused").exists())


class Installer(unittest.TestCase):
    def test_opt_in_with_size_and_licence_shown_first(self):
        from form import config, installer
        sw = installer.get("exemplars.cadevolve")
        self.assertEqual(sw.level, "optional")
        self.assertIn("4.73 GB", sw.size)
        self.assertEqual(sw.licence, "Apache-2.0")
        cfg = config.load()
        cfg["data"]["dir"] = str(TMP / "data")
        row = installer.survey(cfg, only=["exemplars.cadevolve"])[0]
        self.assertEqual(row["status"], "missing")
        self.assertFalse(row["default"])                                  # never pre-ticked
        self.assertIn("4.73 GB", row["size"])
        self.assertEqual(row["licence"], "Apache-2.0")
        for m in row["methods"]:
            self.assertIn("4.73 GB", m["note"])
            self.assertIn("Apache-2.0", m["note"])
            self.assertIn("ABC-*", m["note"])
            self.assertIn("ShapeNet-*", m["note"])
            if m["kind"] == "command":
                self.assertIn("--accept-licence apache-2.0", m["commands"][-1])
        self.assertNotIn("exemplars.cadevolve", installer.auto_ids(installer.survey(cfg)))


if __name__ == "__main__":
    unittest.main()
