# PyInstaller spec for the FORM desktop app.   pyinstaller packaging/form.spec --noconfirm
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "form" / "__init__.py").read_text(encoding="utf-8")).group(1)
datas = [(str(ROOT / "form" / "app" / "qml"), "form/app/qml"),
         (str(ROOT / "form" / "app" / "assets"), "form/app/assets"),
         (str(ROOT / "form" / "web"), "form/web"),
         (str(ROOT / "form" / "recipes"), "form/recipes"),      # recipe sources are hashed into artifact keys
         (str(ROOT / "form" / "fonts"), "form/fonts"),          # the font used for text on parts
         (str(ROOT / "form" / "presets"), "form/presets"),
         # What's New after an update reads the running version's section from here (form/whatsnew.py)
         (str(ROOT / "CHANGELOG.md"), "form"),
         # credits for outside projects whose ideas the engine builds on
         (str(ROOT / "THIRD_PARTY_NOTICES.md"), "form"),
         # run by Blender itself as files (blender -b --python <path>), so they must exist on disk inside the app:
         # the scene runner, the modelling runner (model_mesh) and the game-asset runner (game_asset)
         (str(ROOT / "form" / "adapters" / "blender_scene.py"), "form/adapters"),
         (str(ROOT / "form" / "adapters" / "blender_ops.py"), "form/adapters"),
         (str(ROOT / "form" / "adapters" / "blender_model.py"), "form/adapters"),
         (str(ROOT / "form" / "adapters" / "blender_game.py"), "form/adapters")]
# the game pipeline as files too (form/game): its runner path is resolved from them on disk
datas += [(str(p), "form/game") for p in sorted((ROOT / "form" / "game").glob("*.py"))]
binaries, hidden = [], []
for pkg in ("OCP", "build123d", "ocp_gordon", "ocpsvg", "lib3mf", "mcp", "pypdfium2", "pypdfium2_raw",
            "bd_warehouse", "py_gearworks", "manifold3d"):     # parts libraries and mesh booleans ship inside the app
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
# Optional engines with libraries the app does not carry (CAD-Recode: PyTorch; CADFit: trimesh and friends) run in an
# environment of their own that Settings > Software makes (form/engines.py), out of the app's process. That interpreter
# imports the engine's code from these files, shipped as plain source under engine_src/ (never on the app's own path).
# CADFit (form/recon/cadfit, CC BY-NC 4.0, included with its author's permission) ships whole, LICENSE and
# PERMISSION.md included; no compiled file.
ENGINE_SRC = [(ROOT / "form" / "__init__.py", "engine_src/form"),
              (ROOT / "form" / "recon" / "__init__.py", "engine_src/form/recon")]
ENGINE_SRC += [(p, "engine_src/form/recon/learned") for p in sorted((ROOT / "form" / "recon" / "learned").glob("*.py"))]
for sub in ("", "vendor"):
    d = ROOT / "form" / "recon" / "cadfit" / sub
    ENGINE_SRC += [(p, f"engine_src/form/recon/cadfit{'/' + sub if sub else ''}") for p in sorted(d.glob("*.py"))]
ENGINE_SRC += [(ROOT / "form" / "recon" / "cadfit" / n, "engine_src/form/recon/cadfit") for n in ("LICENSE", "PERMISSION.md")]
# CoACD (game collision, form/engines.py "game.coacd") runs `python -m form.game.lod coacd ...` in its environment
ENGINE_SRC += [(p, "engine_src/form/game") for p in sorted((ROOT / "form" / "game").glob("*.py"))]
datas += [(str(p), dest) for p, dest in ENGINE_SRC]
# Inside the app itself, CADFit's search code and trimesh (which only that code imports) stay out: the search runs in
# its own environment. Its reader (cqrun) and _compat stay in: the app reads the program CADFit sends back.
CADFIT_ONLY = ("form.recon.cadfit.vendor", "form.recon.cadfit.driver")
hidden += [m for m in collect_submodules("form") if not m.startswith(CADFIT_ONLY)]
datas += collect_data_files("form", include_py_files=False)
# exemplar designs are read as source text by design_examples, so they ship as files too
datas += [(str(p), "form/exemplars") for p in (ROOT / "form" / "exemplars").glob("*.py") if not p.name.startswith("_")]
datas += [(str(ROOT / "form" / "exemplars" / "LICENSE-CADEvolve"), "form/exemplars")]   # ported exemplars carry their licence

# Qt modules the interface does not use; leaving them out halves the download
EXCLUDE = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
           "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
           "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtPositioning", "PySide6.QtLocation",
           "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSql", "PySide6.QtTest",
           "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DExtras",
           "PySide6.QtQuick3DPhysics", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer", "PySide6.QtStateMachine",
           "tkinter", "pytest",      # build123d imports IPython at load: keep it
           "trimesh", *CADFIT_ONLY]  # only CADFit's opt-in search imports these (see CADFIT_ONLY above)

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=EXCLUDE, noarchive=False)
pyz = PYZ(a.pure)
icon = str(ROOT / "form" / "app" / "assets" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FORM", console=False, icon=icon,
          disable_windowed_traceback=False, argv_emulation=False, target_arch=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FORM")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Form Studio.app", icon=icon, bundle_identifier="net.form-studio.app",
                 info_plist={"CFBundleName": "Form Studio", "CFBundleDisplayName": "Form Studio",
                             # macOS wants digits in the short version; -dev stays in the build number
                             "CFBundleShortVersionString": VERSION.split("-")[0], "CFBundleVersion": VERSION,
                             "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "12.0", "NSRequiresAquaSystemAppearance": False})
