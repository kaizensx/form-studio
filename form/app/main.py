"""FORM desktop app: a native Qt Quick interface over the same engine the MCP server and CLI use.

    form app                      open the app
    form app --check              load every screen once and report QML errors (CI, development)
    form app --shot out.png       render a screenshot and quit (see --project, --stage, --size, --wait, --eval)
    form app --tree out.json      save the visible item tree as JSON and quit (with or without --shot)
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _engine(cfg):
    """The engine API on a loopback port chosen by the OS, served from this process."""
    from ..server import EngineServer, make_handler
    from ..studio import Studio
    from ..capabilities import migrate_safely
    migrate_safely(cfg)                                  # once: people who already print keep printing
    st = Studio(cfg)
    httpd = EngineServer(("127.0.0.1", 0), make_handler(st))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="form-engine").start()

    def warm():
        try:
            st.kernel_id()
        except Exception:
            pass                     # reported on the first real kernel call
    threading.Thread(target=warm, daemon=True, name="form-kernel-warm").start()
    return st, httpd


def _reduced_motion() -> bool:
    """The system's "reduce motion" setting, or FORM_REDUCED_MOTION=1/0. The interface reads it once at start through
    Bridge.reducedMotion (Theme.reduced); this copy is for callers that have no Bridge."""
    env = os.environ.get("FORM_REDUCED_MOTION", "").strip().lower()
    if env:
        return env not in ("0", "false", "no", "off")
    try:
        if sys.platform == "darwin":
            import subprocess
            r = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                               capture_output=True, text=True, timeout=2)
            return r.stdout.strip() == "1"
        if sys.platform == "win32":
            import ctypes
            on = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)   # SPI_GETCLIENTAREAANIMATION
            return on.value == 0
    except Exception:
        pass
    return False


def _ghost(win) -> None:
    """Keep a development window out of the way: fully transparent, above the others (so the system keeps drawing
    it), deaf to the real pointer and keyboard. Synthetic events from a journey still reach it."""
    from PySide6.QtCore import Qt
    win.setOpacity(0.0)
    win.setFlags(win.flags() | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
    win.setOpacity(0.0)


def ghost_focus(win) -> bool:
    """Tell Qt this window has the keyboard without asking the system for it (a ghost window never takes it from
    the person at the desk). Qt Quick's Shortcuts fire only in Qt's focus window."""
    import ctypes
    try:
        import shiboken6
        from PySide6 import QtGui
        from PySide6.QtCore import QCoreApplication
        lib = None
        for cand in (Path(QtGui.__file__).parent / "Qt" / "lib" / "QtGui.framework" / "Versions" / "A" / "QtGui",
                     Path(QtGui.__file__).parent / "Qt" / "lib" / "libQt6Gui.so.6",
                     Path(QtGui.__file__).parent / "Qt6Gui.dll"):
            if cand.exists():
                lib = ctypes.CDLL(str(cand))
                break
        if lib is None:
            return False
        fn = getattr(lib, "_ZN22QWindowSystemInterface24handleFocusWindowChangedINS_19SynchronousDeliveryEEEvP7QWindowN2Qt11FocusReasonE")
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_int], None
        fn(shiboken6.getCppPointer(win)[0], 7)          # Qt::OtherFocusReason
        QCoreApplication.processEvents()
        return True
    except Exception:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="form app", description="Form Studio desktop app")
    ap.add_argument("--check", action="store_true", help="load the interface, report QML errors, quit")
    ap.add_argument("--shot", metavar="PNG", help="save a screenshot and quit")
    ap.add_argument("--tree", metavar="JSON", help="save the visible item tree as JSON (with or instead of --shot) and quit")
    ap.add_argument("--project", help="open this project id")
    ap.add_argument("--stage", choices=["brief", "shape", "fit", "prove", "release"])
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--wait", type=int, default=2600, help="ms to wait before --shot")
    ap.add_argument("--eval", dest="js", help="QML/JS expression run in Main.qml before --shot (development)")
    ap.add_argument("--after", type=int, default=900, help="ms between --eval and the screenshot")
    ap.add_argument("--uitest", metavar="SCRIPT", help="drive the window with real input events from a journey "
                    "script (file.py or file.py::function), then quit; see form/app/uitest.py")
    args = ap.parse_args(argv)

    try:
        from PySide6.QtCore import QCoreApplication, Qt, QTimer, QUrl
        from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
        from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
        from PySide6.QtQuick import QQuickWindow
    except ImportError:
        print("The desktop app needs Qt. Install it with:\n\n    uv tool install --force 'form-studio[app]'\n\n"
              "or, in a checkout:  pip install PySide6", file=sys.stderr)
        return 2

    from .. import __version__, config
    from . import geometry  # noqa: F401  (registers the FormNative QML types)
    from .bridge import Bridge

    cfg = config.load()
    QCoreApplication.setOrganizationName("FORM")
    QCoreApplication.setApplicationName("FORM")             # the settings store key: keep, or saved window state is lost
    QGuiApplication.setApplicationDisplayName("Form Studio")
    if args.uitest:
        from . import uitest
        uitest.prepare(cfg)          # its own window settings; a stand-in agent when $FORM_UITEST_AGENT is set
    QCoreApplication.setApplicationVersion(__version__)
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    # FORM_WINDOW_GHOST=1 (development: screenshots and journeys on a desk someone is working at): the real window,
    # rendered by the real GPU path, but never seen and never given the keyboard or the pointer. See _ghost().
    ghost = os.environ.get("FORM_WINDOW_GHOST") == "1" and bool(args.shot or args.check or args.tree or args.uitest)
    if ghost:
        os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] = "1"      # no Dock icon, never the active app
    app = QGuiApplication(sys.argv[:1])
    # the app icon (brand/build.py) in every size it ships in, so the dock, the taskbar and the title bar each pick a sharp one
    icon = QIcon()
    for name in ("icon.png", "icon-512.png", "icon-256.png", "icon-128.png", "icon-64.png", "icon-32.png", "icon-16.png"):
        icon.addFile(str(HERE / "assets" / name))
    app.setWindowIcon(icon)
    # Tab reaches every control, not only text fields (macOS limits it to text fields unless "Keyboard navigation"
    # is on in System Settings). Sheets rely on this to keep the keyboard inside them.
    app.styleHints().setTabFocusBehavior(Qt.TabFocusBehavior.TabFocusAllControls)
    for f in ("InstrumentSans.ttf", "GeistMono.ttf", "lucide.ttf"):
        QFontDatabase.addApplicationFont(str(HERE / "assets" / "fonts" / f))

    st, httpd = _engine(cfg)
    # agents this app starts (and their MCP servers) hand long background work, such as design refinement, to this
    # engine, which outlives an agent's turn (form/refine/jobs.py)
    os.environ["FORM_ENGINE_URL"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    bridge = Bridge("127.0.0.1", httpd.server_address[1], cfg["data"]["dir"], __version__)
    bridge.under_test = bool(args.uitest)
    qmlRegisterSingletonInstance(Bridge, "FormNative", 1, 0, "Bridge", bridge)
    app.styleHints().colorSchemeChanged.connect(lambda *_: bridge.systemDarkChanged.emit())   # "Match the system" follows it live

    engine = QQmlApplicationEngine()
    errors: list[str] = []
    engine.warnings.connect(lambda ws: errors.extend(w.toString() for w in ws))
    engine.addImportPath(str(HERE / "qml"))
    w, h = (int(x) for x in args.size.lower().split("x"))
    initial = {"startProject": args.project or "", "startStage": args.stage or "",
               "headless": bool(args.shot or args.check or args.tree), "width": w, "height": h}
    if ghost:
        initial["opacity"] = 0.0
    engine.setInitialProperties(initial)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    code = {"rc": 0}

    def finish(rc: int):
        code["rc"] = rc
        app.quit()

    if not engine.rootObjects():
        print("Form Studio could not load its interface:", *errors, sep="\n  ", file=sys.stderr)
        httpd.shutdown(); st.kernel.stop()
        return 1
    win: QQuickWindow = engine.rootObjects()[0]
    if ghost:
        _ghost(win)

    if args.check or args.shot or args.tree:
        def done():
            if args.js:
                from PySide6.QtQml import QQmlExpression
                from PySide6.QtQml import QQmlEngine
                ex = QQmlExpression(QQmlEngine.contextForObject(win), win, args.js)
                ex.evaluate()
                if ex.hasError():
                    errors.append("--eval: " + ex.error().toString())
            def snap():
                if args.shot:
                    win.grabWindow().save(args.shot)
                if args.tree:
                    try:
                        from .uitest import write_tree
                        write_tree(win, args.tree)
                    except Exception as e:           # noqa: BLE001 - reported like a QML problem
                        errors.append(f"--tree: {type(e).__name__}: {e}")
                bad = [e for e in errors if "Binding loop" not in e]
                try:
                    kernel = st.kernel_id()          # the CAD kernel answers: the engine really works in this build
                except Exception as e:
                    kernel, bad = "", bad + [f"CAD kernel did not start: {e}"]
                lines = [f"QML: {e}" for e in bad] + [f"kernel: {kernel}" if kernel else "kernel: not running",
                         f"ok: {len(bad)} warning(s)" + (f", saved {args.shot}" if args.shot else "")
                         + (f", tree {args.tree}" if args.tree else "")]
                # A windowed Windows build has no console, so the result is also written to a file when asked.
                out = os.environ.get("FORM_CHECK_OUT")
                if out:
                    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
                for line in lines:
                    try:
                        print(line, file=sys.stderr if line.startswith("QML:") else sys.stdout)
                    except Exception:
                        pass
                finish(1 if (args.check and bad) else 0)
            QTimer.singleShot(args.after if args.js else 0, snap)
        QTimer.singleShot(args.wait, done)

    if args.uitest:
        QTimer.singleShot(200, lambda: uitest.run_script(app, engine, win, st, bridge, args.uitest, errors, finish))

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer(); tick.start(250); tick.timeout.connect(lambda: None)     # let Python see Ctrl+C
    app.exec()
    httpd.shutdown()
    if getattr(st, "chat", None) is not None:        # end agent runs and their tool servers with the app
        st.chat.shutdown()
    st.kernel.stop()
    return code["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
