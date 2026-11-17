# PyInstaller spec for the FORM desktop app.   pyinstaller packaging/form.spec --noconfirm
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
datas = [(str(ROOT / "form" / "app" / "qml"), "form/app/qml"),
         (str(ROOT / "form" / "app" / "assets"), "form/app/assets"),
         (str(ROOT / "form" / "web"), "form/web"),
         (str(ROOT / "form" / "recipes"), "form/recipes"),      # recipe sources are hashed into artifact keys
         (str(ROOT / "form" / "examples"), "form/examples"),
         (str(ROOT / "form" / "fonts"), "form/fonts"),          # the font used for text on parts
         (str(ROOT / "form" / "presets"), "form/presets")]
binaries, hidden = [], []
for pkg in ("OCP", "build123d", "ocp_gordon", "ocpsvg", "lib3mf", "mcp", "pypdfium2", "pypdfium2_raw",
            "bd_warehouse", "py_gearworks"):     # parts libraries ship inside the app
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
hidden += collect_submodules("form")
datas += collect_data_files("form", include_py_files=False)

# Qt modules the interface does not use; leaving them out halves the download
EXCLUDE = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
           "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
           "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtPositioning", "PySide6.QtLocation",
           "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSql", "PySide6.QtTest",
           "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DExtras",
           "PySide6.QtQuick3DPhysics", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer", "PySide6.QtStateMachine",
           "tkinter", "pytest"]      # build123d imports IPython at load: keep it

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=EXCLUDE, noarchive=False)
pyz = PYZ(a.pure)
icon = str(ROOT / "form" / "app" / "assets" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FORM", console=False, icon=icon,
          disable_windowed_traceback=False, argv_emulation=False, target_arch=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FORM")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="FORM.app", icon=icon, bundle_identifier="net.form-studio.app",
                 info_plist={"CFBundleShortVersionString": "11.0.2", "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "12.0", "NSRequiresAquaSystemAppearance": False})
