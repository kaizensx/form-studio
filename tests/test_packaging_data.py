"""Files the app reads at run time as data must ship in the packaged app, not only as importable modules."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagedData(unittest.TestCase):
    def test_exemplar_sources_ship_as_files(self):
        # design_examples reads each exemplar's source text; PyInstaller keeps .py files only as bytecode unless listed
        spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")
        self.assertIn('"form/exemplars"', spec)
        from form import exemplars
        self.assertGreaterEqual(len(exemplars.catalogue()), 56)

    def test_the_packaged_app_serves_every_exemplar(self):
        """Run packaging/form.spec with PyInstaller's build steps stubbed, lay out its datas the way the bundle does
        (only files listed as data exist; modules are bytecode), and read the exemplar catalogue from that layout:
        design_examples("") in the app must list at least 56 exemplars, each with its source."""
        import importlib.util
        import shutil
        import sys
        import tempfile
        import types
        spec_file = ROOT / "packaging" / "form.spec"
        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_all = lambda pkg: ([], [], [])
        hooks.collect_data_files = lambda pkg, include_py_files=False: []
        hooks.collect_submodules = lambda pkg: []
        stub = {"PyInstaller": types.ModuleType("PyInstaller"), "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
                "PyInstaller.utils.hooks": hooks}
        captured = {}

        def Analysis(*a, datas=(), **k):
            captured["datas"] = list(datas)
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=list(datas))
        ns = {"SPECPATH": str(spec_file.parent), "Analysis": Analysis, "PYZ": lambda *a, **k: None,
              "EXE": lambda *a, **k: None, "COLLECT": lambda *a, **k: None, "BUNDLE": lambda *a, **k: None,
              "__file__": str(spec_file)}
        saved = {k: sys.modules.get(k) for k in stub}
        sys.modules.update(stub)
        try:
            exec(compile(spec_file.read_text(encoding="utf-8"), str(spec_file), "exec"), ns)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        bundle = Path(tempfile.mkdtemp(prefix="form-bundle-"))
        try:
            for src, dest in captured["datas"]:
                src = Path(src)
                if src.is_file() and dest.startswith("form/exemplars"):
                    (bundle / dest).mkdir(parents=True, exist_ok=True)
                    shutil.copy(src, bundle / dest / src.name)
            init = ROOT / "form" / "exemplars" / "__init__.py"       # the package itself is bytecode in the app
            (bundle / "form" / "exemplars").mkdir(parents=True, exist_ok=True)
            shutil.copy(init, bundle / "form" / "exemplars" / "_init_copy.py")
            m = importlib.util.spec_from_file_location("bundled_exemplars", bundle / "form" / "exemplars" / "_init_copy.py")
            mod = importlib.util.module_from_spec(m)
            m.loader.exec_module(mod)
            cat = mod.catalogue()
            self.assertGreaterEqual(len(cat), 56, "the packaged app would serve too few exemplars")
            from form import exemplars
            self.assertEqual({e["name"] for e in cat}, {e["name"] for e in exemplars.catalogue()})
            self.assertIn("class Design(Recipe)", mod.get(cat[0]["name"])["source"])
        finally:
            shutil.rmtree(bundle, ignore_errors=True)

    def test_every_exemplar_loads_as_a_design_source(self):
        """An agent pastes an exemplar into create_design: it must pass the same checks a design source gets (one
        Recipe, params that name real features), not only build when imported directly."""
        import tempfile
        from form import exemplars
        from form.recipes import load_source, store_source
        store = Path(tempfile.mkdtemp(prefix="form-exemplar-sources-"))
        for e in exemplars.catalogue():
            with self.subTest(e["name"]):
                rid = store_source(store, exemplars.get(e["name"])["source"])
                load_source(store / f"{rid[4:]}.py", rid)

    def test_exemplars_cover_every_category(self):
        from form import exemplars
        cov = exemplars.coverage()
        for c in exemplars.CATEGORIES:
            self.assertGreaterEqual(cov.get(c, 0), 3, (c, cov))
        self.assertNotIn("uncategorised", cov)

    def test_chat_attachments_accept_meshes(self):
        talk = (ROOT / "form" / "app" / "qml" / "Form" / "Talk.qml").read_text(encoding="utf-8")
        for ext in ("*.stl", "*.3mf", "*.obj", "*.step"):
            self.assertIn(ext, talk)


if __name__ == "__main__":
    unittest.main()
