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

    def test_rule_and_bend_tables_ship_as_files(self):
        # manufacturability and sheet metal read their limits from TOML tables at run time
        spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")
        for rel in ("form/dfm/rules", "form/sheet/rules", "form/sheet/tables", "form/sheet/services"):
            self.assertIn(f'"{rel}"', spec)
            self.assertTrue(list((ROOT / rel).glob("*.toml")), rel)

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
        hooks.copy_metadata = lambda pkg, recursive=False: []
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

    def test_deploy_clears_the_app_it_builds(self):
        """scripts/deploy_mac.sh removes the previous build of the app the spec makes before building, so the smoke
        test never checks a stale bundle."""
        import re
        script = (ROOT / "scripts" / "deploy_mac.sh").read_text(encoding="utf-8")
        spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")
        app = re.search(r'BUNDLE\(coll, name="([^"]+)"', spec).group(1)
        self.assertIn(f'APP="{app}"', script)
        build = script.index("-m PyInstaller")
        self.assertIn('rm -rf "dist/$APP"', script[:build])
        self.assertIn('scripts/smoke_packaged.py "dist/$APP"', script)

    def test_cadfit_search_stays_out_of_the_app(self):
        """CADFit's opt-in search (CC BY-NC 4.0 vendored code) and trimesh, which only it imports, are not packaged;
        its hook, LICENSE and PERMISSION.md are. scipy and scikit-learn stay: the engine and build123d need them."""
        import sys
        import types
        spec_file = ROOT / "packaging" / "form.spec"
        mods = ["form", "form.recon.cadfit", "form.recon.cadfit.vendor", "form.recon.cadfit.vendor.iou",
                "form.recon.cadfit.driver", "form.recon.cadfit.cqrun", "form.recon.cadfit._compat", "form.recon.pipeline"]
        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_all = lambda pkg: ([], [], [])
        hooks.collect_data_files = lambda pkg, include_py_files=False: []
        hooks.collect_submodules = lambda pkg: list(mods)
        hooks.copy_metadata = lambda pkg, recursive=False: []
        stub = {"PyInstaller": types.ModuleType("PyInstaller"), "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
                "PyInstaller.utils.hooks": hooks}
        got = {}

        def Analysis(*a, **k):
            got.update(k)
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
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
        hidden, excl = got["hiddenimports"], got["excludes"]
        self.assertIn("form.recon.cadfit", hidden)
        self.assertIn("form.recon.pipeline", hidden)
        for m in ("form.recon.cadfit.vendor", "form.recon.cadfit.vendor.iou", "form.recon.cadfit.driver"):
            self.assertNotIn(m, hidden)
        # the app reads the program CADFit sends back from its own environment: its reader stays in
        for m in ("form.recon.cadfit.cqrun", "form.recon.cadfit._compat"):
            self.assertIn(m, hidden)
        for m in ("trimesh", "form.recon.cadfit.vendor", "form.recon.cadfit.driver"):
            self.assertIn(m, excl)
        for m in ("scipy", "sklearn"):
            self.assertNotIn(m, excl)
        # trimesh is imported by CADFit's vendored code only; scikit-learn by build123d itself
        import re
        users = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "form").rglob("*.py")
                       if re.search(r"^\s*(import trimesh|from trimesh)", p.read_text(encoding="utf-8"), re.M))
        self.assertTrue(users and all(u.startswith("form/recon/cadfit/vendor/") for u in users), users)
        # the folder's licence files ship as data (collect_data_files keeps non-.py files)
        import logging
        root = logging.getLogger()
        keep = (root.level, list(root.handlers))
        try:
            try:
                from PyInstaller.utils.hooks import collect_data_files
            except ImportError:
                return
            names = {Path(src).name for src, dest in collect_data_files("form", include_py_files=False)
                     if Path(dest).as_posix() == "form/recon/cadfit"}      # Windows gives form\\recon\\cadfit
        finally:                                     # PyInstaller sets up logging on import: leave it as it was
            root.setLevel(keep[0])
            root.handlers[:] = keep[1]
        self.assertTrue({"LICENSE", "PERMISSION.md"} <= names, names)

    def test_blender_runners_and_the_game_pipeline_ship_as_files(self):
        """Blender runs its runners as files (blender -b --python <path>), and CoACD's environment runs
        `python -m form.game.lod`: the spec ships them on disk, in the app and under engine_src/."""
        import sys
        import types
        spec_file = ROOT / "packaging" / "form.spec"
        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_all = lambda pkg: ([], [], [])
        hooks.collect_data_files = lambda pkg, include_py_files=False: []
        hooks.collect_submodules = lambda pkg: []
        hooks.copy_metadata = lambda pkg, recursive=False: []
        stub = {"PyInstaller": types.ModuleType("PyInstaller"), "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
                "PyInstaller.utils.hooks": hooks}
        got = {}

        def Analysis(*a, **k):
            got.update(k)
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
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
        shipped = {(Path(src).name, dest) for src, dest in got["datas"]}
        for f in ("blender_scene.py", "blender_ops.py", "blender_model.py", "blender_game.py"):
            self.assertIn((f, "form/adapters"), shipped)
        game = sorted(p.name for p in (ROOT / "form" / "game").glob("*.py"))
        self.assertIn("lod.py", game)
        for f in game:
            self.assertIn((f, "form/game"), shipped)
            self.assertIn((f, "engine_src/form/game"), shipped)

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
        # the attach dialog's filters come from the one table of formats (form/formats.py, tests/test_formats.py)
        from form import formats
        talk = (ROOT / "form" / "app" / "qml" / "Form" / "Talk.qml").read_text(encoding="utf-8")
        self.assertIn('Bridge.fileFilters("attach")', talk)
        offered = " ".join(formats.name_filters("attach"))
        for ext in ("*.stl", "*.3mf", "*.obj", "*.step", "*.ply", "*.e57", "*.zip"):
            self.assertIn(ext, offered)


def _run_spec(collect_submodules=lambda pkg: []):
    """Execute packaging/form.spec with PyInstaller's build steps stubbed; return Analysis's keyword arguments."""
    import sys
    import types
    spec_file = ROOT / "packaging" / "form.spec"
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda pkg: ([], [], [])
    hooks.collect_data_files = lambda pkg, include_py_files=False: []
    hooks.collect_submodules = collect_submodules
    hooks.copy_metadata = lambda pkg, recursive=False: []
    stub = {"PyInstaller": types.ModuleType("PyInstaller"), "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
            "PyInstaller.utils.hooks": hooks}
    got = {}

    def Analysis(*a, **k):
        got.update(k)
        return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
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
    return got


class WavesShip(unittest.TestCase):
    """What the integrated waves read or run at run time is in the packaged app (integrate-2)."""

    def test_every_table_read_at_run_time_ships_from_an_explicit_folder(self):
        # rule, bend, service tables (TOML) and any CSV or JSON table in the package: each one's folder is listed as
        # data by name, not only left to collect_data_files
        import subprocess
        got = _run_spec()
        dests = {Path(src).resolve(): dest for src, dest in got["datas"]}
        try:
            tracked = subprocess.run(["git", "ls-files", "form"], cwd=ROOT, capture_output=True, text=True,
                                     check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            tracked = [p.relative_to(ROOT).as_posix() for p in (ROOT / "form").rglob("*")]
        tables = [t for t in tracked if t.endswith((".toml", ".csv")) or
                  (t.endswith(".json") and not t.startswith(("form/app/", "form/web/")))]
        self.assertTrue(any(t.startswith("form/dfm/rules/") for t in tables) and "form/cam/feeds.toml" in tables)
        for t in tables:
            f = (ROOT / t).resolve()
            covered = any(f == src or src in f.parents for src in dests)
            self.assertTrue(covered, f"{t} is read at run time but no datas entry ships its folder")

    def test_the_new_data_modules_are_importable_in_the_app(self):
        # standard parts, calculators, materials, ISO 286 and hardware tables are Python modules: hidden imports
        mods = ["form.catalog", "form.calc.fit", "form.material_data", "form.material_library", "form.iso286",
                "form.hardware_tables", "form.drawing.qtpaint", "form.motion", "form.robot", "form.sequence", "form.bom",
                "form.dfm.rules", "form.sheet.tables", "form.cam", "form.cam.feeds"]
        got = _run_spec(lambda pkg: list(mods) if pkg == "form" else [])
        for m in mods:
            self.assertIn(m, got["hiddenimports"])
        from form import catalog, hardware_tables, iso286, material_data  # noqa: F401  (they import without the kernel)
        self.assertIs(catalog.INSERTS, hardware_tables.INSERTS)

    def test_drawings_paint_and_read_pdfs_in_the_packaged_app(self):
        # form.drawing runs `<executable> -m form.drawing.qtpaint job`: the packaged executable must dispatch it, and
        # the drawing check reads PDFs with QtPdf, which must not be excluded
        entry = (ROOT / "packaging" / "entry.py").read_text(encoding="utf-8")
        self.assertIn('["-m", "form.drawing.qtpaint"]', entry)
        got = _run_spec()
        self.assertNotIn("PySide6.QtPdf", got["excludes"])
        src = (ROOT / "form" / "drawing" / "qtpaint.py").read_text(encoding="utf-8")
        self.assertIn("from PySide6.QtPdf import", src)

    def test_engine_children_find_their_code(self):
        # the strength engine runs `python -m form.fea.run`, the MuJoCo check `python -m form.robot validate`
        got = _run_spec()
        shipped = {(Path(src).name, dest) for src, dest in got["datas"]}
        self.assertIn(("robot.py", "engine_src/form"), shipped)
        for f in sorted(p.name for p in (ROOT / "form" / "fea").glob("*.py")):
            self.assertIn((f, "engine_src/form/fea"), shipped)


if __name__ == "__main__":
    unittest.main()
