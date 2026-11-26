"""Interaction tests for the desktop app: the real window, driven with real synthetic input events.

    python -m form.app --uitest tests/journeys/first_run.py            # runs run(ui) in that file
    python -m form.app --uitest tests/journeys/tools.py::measure      # runs measure(ui)

A journey is a Python file with functions that take one argument, the `UI` below. Targets are found by `objectName`
or by the text a user reads on them, and are pressed with `QTest` mouse and key events sent to the window, so a
button that does nothing fails the journey. Outcomes are asserted against the Store (`ui.store.get("stage")`,
`ui.js("Store.data.project.head")`) and against the engine itself (`ui.api("/projects/x")`, `ui.studio`).

The run uses the data folder in $FORM_DATA (the test suite gives each journey its own copy), its own window
settings, never the network, and - when $FORM_UITEST_AGENT names a script - a stand-in agent CLI, so no model runs.
Exit code 0 means every assertion held and the interface printed no QML warning. When a journey fails, its
screenshot (fail-<journey>-<function>.png) gets a JSON dump of the visible item tree beside it (fail-....json, see
tree()); `python -m form.app --tree out.json` writes the same dump for any screen.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

TEXT_PROPS = ("text", "tip", "title", "label", "placeholder", "k")
TREE_TEXT_MAX = 240                        # characters of one text kept in a tree dump: what a person sees, not a log
PASSWORD_ECHO = (2, 3)                     # TextInput.Password, TextInput.PasswordEchoOnEdit


def _shown_item(item) -> bool:
    if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
        return False
    p = item
    while p is not None:
        if p.opacity() < 0.02:
            return False
        p = p.parentItem()
    return True


def _password(item) -> bool:
    """True for a text input whose echoMode hides what is typed (Password, PasswordEchoOnEdit). An input whose echo
    mode cannot be read counts as one: a dump never risks a secret."""
    mo = item.metaObject()
    if mo.indexOfProperty("echoMode") < 0:
        return False
    try:
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        ex = QQmlExpression(QQmlEngine.contextForObject(item), item, "Number(echoMode)")
        v = ex.evaluate()
        v = v[0] if isinstance(v, tuple) else v
        if ex.hasError() or v is None:
            return True
        return int(v) in PASSWORD_ECHO
    except Exception:                          # noqa: BLE001
        return True


def _qml_file(item) -> str:
    """The QML file an item was declared in (its context's file), relative to form/app/qml; "" when unknown."""
    try:
        from PySide6.QtQml import QQmlEngine
        ctx = QQmlEngine.contextForObject(item)
        url = ctx.baseUrl().toLocalFile() if ctx is not None else ""
    except Exception:                          # noqa: BLE001 - the file is a hint
        return ""
    if not url:
        return ""
    p = Path(url)
    parts = p.parts
    return "/".join(parts[parts.index("qml") + 1:]) if "qml" in parts else p.name


def tree(win, max_text: int = TREE_TEXT_MAX) -> dict:
    """The visible QML item tree of a window as plain data: for each shown item its className, objectName, visible
    texts (each cut to max_text characters), enabled / checked / activeFocus, its bounds in the scene and the QML
    file it comes from. Hidden or fully transparent items and their children are left out. The text of a password
    field (echoMode Password) is never included, nor any other property that holds the same text."""
    from PySide6.QtCore import QRectF
    root = win.contentItem()
    W, H = win.width(), win.height()

    def walk(item):
        yield item
        for c in item.childItems():
            yield from walk(c)

    secrets = set()                            # what password fields hold: redacted wherever it shows up
    for it in walk(root):
        if _password(it):
            for k in ("text", "preeditText"):
                v = it.property(k)
                if isinstance(v, str) and v:
                    secrets.add(v)

    def clean(v: str) -> str:
        for s in secrets:
            if s and s in v:
                v = v.replace(s, "•" * 8)
        return v if len(v) <= max_text else v[:max_text - 1] + "…"

    def node(item) -> dict | None:
        if not _shown_item(item):
            return None
        r = item.mapRectToScene(QRectF(0, 0, item.width(), item.height()))
        on = r.right() >= 0 and r.bottom() >= 0 and r.left() <= W and r.top() <= H
        n = {"className": item.metaObject().className(), "objectName": item.objectName() or "",
             "bounds": [round(r.x(), 1), round(r.y(), 1), round(r.width(), 1), round(r.height(), 1)]}
        if on:                                 # text only for what is inside the window, where a person can read it
            texts = {}
            password = _password(item)
            for k in TEXT_PROPS:
                v = item.property(k)
                if isinstance(v, str) and v:
                    texts[k] = "•" * 8 if password and k == "text" else clean(v)
            if texts:
                n["text"] = texts
        else:
            n["offscreen"] = True
        n["enabled"] = bool(item.isEnabled())
        ch = item.property("checked")
        if isinstance(ch, bool):
            n["checked"] = ch
        if item.hasActiveFocus():
            n["activeFocus"] = True
        src = _qml_file(item)
        if src:
            n["source"] = src
        kids = [k for k in (node(c) for c in item.childItems()) if k]
        if kids:
            n["children"] = kids
        return n

    return {"window": [W, H], "root": node(root) or {}, "max_text": max_text}


def write_tree(win, path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tree(win), indent=1, ensure_ascii=False), encoding="utf-8")
    return p


class UIError(AssertionError):
    pass


def prepare(cfg: dict) -> None:
    """Called before the engine starts: isolate window settings and swap in the stand-in agent when asked."""
    from PySide6.QtCore import QCoreApplication, QSettings
    QCoreApplication.setOrganizationName("FORM-uitest")
    QCoreApplication.setApplicationName("FORM-uitest")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp(prefix="form-uitest-settings-"))
    # QTest's click and key functions process events while this thread holds the interpreter lock. With Qt Quick's
    # threaded render loop the window then waits for the render thread, which waits for the lock to read the
    # Python-made geometry: a deadlock. Rendering on the main thread avoids it (the app itself is unaffected).
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
    if not os.environ.get("FORM_UITEST_FILES"):          # where "saved" files go instead of a native dialog
        os.environ["FORM_UITEST_FILES"] = tempfile.mkdtemp(prefix="form-uitest-files-")
    fake = os.environ.get("FORM_UITEST_AGENT", "")
    if fake:
        cfg["_adapters"] = {"fake": _fake_adapter(Path(fake), Path(cfg["data"]["dir"]))}
        if os.environ.get("FORM_UITEST_API_AGENTS") == "1":     # the API agents too (tests/journeys/agents.py)
            from ..agents.api import all_api_adapters
            cfg["_adapters"].update({a.id: a for a in all_api_adapters()})
        cfg["chat"] = dict(cfg.get("chat") or {}, enabled=True, agent="fake", model="default", effort="")


def _fake_adapter(script: Path, data: Path):
    from ..agents.base import Adapter
    from ..agents.claude import ClaudeParser

    class Fake(Adapter):
        """Runs a script that speaks Claude Code's stream-json (tests/fixtures/fake_agent.py)."""
        id, label, cli = "fake", "Test agent", "python"
        images, cost = True, True

        def executable(self, cfg):
            return sys.executable

        def models(self, cfg, exe):
            return [{"id": "default", "label": "Default", "note": ""}, {"id": "small", "label": "Small", "note": ""}]

        def command(self, run, exe):
            return [exe, str(script), str(data), run.session or "-", run.model, run.message]

        def run_env(self, run):            # the stand-in plays Form Studio's MCP server too: it answers ask_user itself
            env = run.mcp.get("env") or {}  # and records the designs it makes in the conversation
            return {k: env[k] for k in ("FORM_ASK_DIR", "FORM_CONVERSATION") if env.get(k)}

        def parser(self):
            return ClaudeParser()

    return Fake()


class StoreProxy:
    """Reads the QML `Store` singleton. Values come back as plain Python (dict/list/str/number/bool/None)."""

    def __init__(self, ui: "UI"):
        self._ui = ui

    def get(self, name: str):
        return self._ui.js("Store." + name)

    prop = get

    def call(self, expr: str):
        """Run `Store.<expr>` for its effect, e.g. call('openSheet("slicer")'). Prefer real clicks; this is for setup."""
        return self._ui.run_js("Store." + expr)


class UI:
    def __init__(self, app, engine, win, studio, bridge, warnings: list, out_dir: Path):
        from PySide6.QtTest import QTest
        self.app, self.engine, self.win, self.studio, self.bridge = app, engine, win, studio, bridge
        self.base = f"http://{bridge.host}:{bridge.port}"
        self.files = Path(os.environ["FORM_UITEST_FILES"])          # native save dialogs write here
        self.warnings, self.out = warnings, out_dir
        self.store = StoreProxy(self)
        self.T = QTest
        self.timeout = float(os.environ.get("FORM_UITEST_TIMEOUT", "30"))
        self.log: list[str] = []

    # -- time ----------------------------------------------------------------
    def _pump(self, ms: int = 0):
        """Run the event loop for ms. Unlike QTest.qWait this lets go of the interpreter lock, so the engine's
        threads (HTTP server, jobs, geometry loading) keep running while the test waits."""
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(max(0, int(ms)), loop.quit)
        loop.exec()

    def wait(self, ms: int = 50):
        self._pump(ms)

    def wait_until(self, cond, timeout: float | None = None, what: str = ""):
        """Pump the event loop until cond() is truthy. Returns its value; raises with `what` on timeout."""
        t0, last = time.time(), None
        limit = self.timeout if timeout is None else timeout
        while True:
            try:
                last = cond()
            except UIError:
                last = None
            if last:
                return last
            if time.time() - t0 > limit:
                raise UIError(f"timed out after {limit:.0f}s waiting for {what or getattr(cond, '__name__', 'condition')}")
            self._pump(25)

    def settle(self, ms: int = 250):
        """Let running animations finish (sheets enter in 180 ms)."""
        self._pump(ms)

    def idle(self, timeout: float | None = None):
        """Wait until no engine job is running and the project state has loaded."""
        self.wait_until(lambda: self.js("Store.job === '' && !Store.previewBusy") is True, timeout, "the engine to be idle")

    # -- JS ------------------------------------------------------------------
    def _expr(self, code: str):
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        ex = QQmlExpression(QQmlEngine.contextForObject(self.win), self.win, code)
        v = ex.evaluate()
        if isinstance(v, tuple):          # PySide returns (value, valueIsUndefined)
            v = v[0]
        if ex.hasError():
            raise UIError(f"JS error in {code!r}: {ex.error().toString()}")
        return v

    def js(self, expr: str):
        """Evaluate a QML/JS expression in Main.qml's scope and return it as plain Python."""
        v = self._expr("(function(){ var __v = (" + expr + "); return __v === undefined ? 'null' : JSON.stringify(__v) })()")
        try:
            return json.loads(v) if isinstance(v, str) else v
        except ValueError:
            return v

    def run_js(self, code: str):
        self._expr(code)
        self._pump(0)

    # -- engine --------------------------------------------------------------
    def api(self, path: str, body=None):
        """GET (or POST when body is given) the engine API the app itself uses. Returns parsed JSON."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + "/api" + path, data=data, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    # -- files and the world outside the window ---------------------------------
    def pick_file(self, path):
        """The next native open dialog answers with this file (save dialogs answer with a path in ui.files)."""
        self.bridge._test_pick = str(path)

    def saved(self, name: str, timeout: float = 30) -> Path:
        """Wait for a file a save dialog wrote into ui.files; returns its path."""
        p = self.files / name
        self.wait_until(lambda: p.exists() and p.stat().st_size > 0, timeout, f"{name} to be saved")
        return p

    @property
    def outside(self) -> list:
        """What the app asked the desktop to open (Finder reveals, links, folders); recorded, not done."""
        return list(getattr(self.bridge, "outside", []))

    # -- finding -------------------------------------------------------------
    def _roots(self):
        return [self.win.contentItem()]

    def _walk(self, item):
        yield item
        for c in item.childItems():
            yield from self._walk(c)

    def _shown(self, item) -> bool:
        return _shown_item(item)

    def _on_screen(self, item) -> bool:
        from PySide6.QtCore import QPointF
        c = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        return 0 <= c.x() <= self.win.width() and 0 <= c.y() <= self.win.height()

    @staticmethod
    def _text_of(item) -> list[str]:
        out = []
        for p in TEXT_PROPS:
            v = item.property(p)
            if isinstance(v, str) and v:
                out.append(v)
        return out

    def find_all(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True, shown: bool = True) -> list:
        roots = [within] if within is not None else self._roots()
        if isinstance(within, str):
            roots = [self.item(within)]
        hits = []
        for root in roots:
            for it in self._walk(root):
                if name is not None and it.objectName() != name:
                    continue
                if text is not None:
                    ts = self._text_of(it)
                    if not (text in ts if exact else any(text.lower() in t.lower() for t in ts)):
                        continue
                if shown and not self._shown(it):
                    continue
                hits.append(it)
        return hits

    def find(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True, nth: int = 0):
        hits = self.find_all(name, text, within, exact)
        vis = [h for h in hits if self._on_screen(h)] or hits
        return vis[nth] if len(vis) > nth else None

    def item(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True, nth: int = 0, timeout: float | None = None):
        """The visible item with this objectName / text; waits for it to appear."""
        what = f"an item named {name!r}" if name else f"an item reading {text!r}"
        return self.wait_until(lambda: self.find(name, text, within, exact, nth), 8 if timeout is None else timeout, what)

    def exists(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True) -> bool:
        return self.find(name, text, within, exact) is not None

    def texts(self, within=None) -> list[str]:
        """Every visible string under `within` (or the window), in tree order."""
        root = self.item(within) if isinstance(within, str) else within
        out = []
        for it in self._walk(root or self.win.contentItem()):
            if self._shown(it):
                v = it.property("text")
                if isinstance(v, str) and v.strip():
                    out.append(v)
        return out

    def sees(self, text: str, within=None) -> bool:
        low = text.lower()
        return any(low in t.lower() for t in self.texts(within))

    def expect(self, text: str, within=None, timeout: float | None = None):
        self.wait_until(lambda: self.sees(text, within), 8 if timeout is None else timeout, f"the text {text!r} on screen")

    # -- pointer -------------------------------------------------------------
    def _pt(self, target, fx: float = 0.5, fy: float = 0.5):
        from PySide6.QtCore import QPoint, QPointF
        if isinstance(target, (tuple, list)):
            return QPoint(int(target[0]), int(target[1]))
        it = self.item(target) if isinstance(target, str) else target
        p = it.mapToScene(QPointF(it.width() * fx, it.height() * fy))
        return QPoint(int(round(p.x())), int(round(p.y())))

    def _btn(self, button: str):
        from PySide6.QtCore import Qt
        return {"left": Qt.MouseButton.LeftButton, "right": Qt.MouseButton.RightButton, "middle": Qt.MouseButton.MiddleButton}[button]

    def _mods(self, mods: str = ""):
        from PySide6.QtCore import Qt
        m = Qt.KeyboardModifier.NoModifier
        for part in filter(None, mods.split("+")):
            m |= {"ctrl": Qt.KeyboardModifier.ControlModifier, "shift": Qt.KeyboardModifier.ShiftModifier,
                  "alt": Qt.KeyboardModifier.AltModifier, "meta": Qt.KeyboardModifier.MetaModifier}[part.lower()]
        return m

    def _flick(self, item):
        p = item.parentItem()
        while p is not None:
            if p.property("contentY") is not None and p.property("contentHeight") is not None and p.property("interactive") is not None:
                return p
            p = p.parentItem()
        return None

    def scroll_to(self, target, fy: float = 0.5):
        """Bring an item inside a scrolling panel into view with wheel events, the way a hand would."""
        from PySide6.QtCore import QPointF
        it = self.item(target) if isinstance(target, str) else target
        fl = self._flick(it)
        if fl is None:
            return
        for _ in range(60):
            y = it.mapToItem(fl, QPointF(0, it.height() * fy)).y()
            if 60 <= y <= fl.height() - 90:
                for _ in range(80):                        # a press on a view that is still gliding only stops it
                    if not fl.property("moving") and not fl.property("flicking"):
                        break
                    self._pump(25)
                return
            before = fl.property("contentY")
            self.wheel(fl, -240 if y > fl.height() - 90 else 240)
            self._pump(30)
            if abs(fl.property("contentY") - before) < 0.5:        # at the end, or the wheel did nothing: place it
                want = before + (y - fl.height() / 2)
                top = max(0.0, float(fl.property("contentHeight")) - fl.height())
                fl.setProperty("contentY", max(0.0, min(top, want)))
                self._pump(30)
                return

    def _steady(self, target, fx: float, fy: float, limit: float = 3.0) -> None:
        """Wait until the item stops moving: a panel sliding in, a popover growing, a strip changing height. A hand
        aims at where a control rests; on a slow software-rendered runner a click aimed mid-animation lands on
        whatever is there once the event arrives."""
        it = self.item(target) if isinstance(target, str) else target
        t0, last = time.time(), None
        while time.time() - t0 < limit:
            try:
                p = self._pt(it, fx, fy)
                now = (p.x(), p.y(), round(it.width()), round(it.height()))
            except RuntimeError:                       # the item went away; let the caller find out
                return
            if now == last:
                return
            last = now
            self._pump(40)

    def hover(self, target, fx: float = 0.5, fy: float = 0.5):
        if not isinstance(target, (tuple, list)):
            self.scroll_to(target, fy)
            self._steady(target, fx, fy)
        p = self._pt(target, fx, fy)
        self.T.mouseMove(self.win, p)
        self._pump(15)
        return p

    def click(self, target, fx: float = 0.5, fy: float = 0.5, button: str = "left", mods: str = ""):
        """Press and release on an item (by objectName, or the item itself, or (x, y) in the window)."""
        label = target if isinstance(target, (str, tuple)) else (target.objectName() or (self._text_of(target) or [target.metaObject().className()])[0])
        p = self.hover(target, fx, fy)
        self.log.append(f"click {label} @ {p.x()},{p.y()}")
        self.T.mouseClick(self.win, self._btn(button), self._mods(mods), p)
        self._pump(20)

    def click_text(self, text: str, within=None, exact: bool = True, nth: int = 0, button: str = "left"):
        self.click(self.item(text=text, within=within, exact=exact, nth=nth), button=button)

    def right_click(self, target, fx: float = 0.5, fy: float = 0.5):
        self.click(target, fx, fy, button="right")

    def dclick(self, target, fx: float = 0.5, fy: float = 0.5):
        p = self.hover(target, fx, fy)
        self.T.mouseClick(self.win, self._btn("left"), self._mods(), p)
        self.T.mouseDClick(self.win, self._btn("left"), self._mods(), p)
        self._pump(20)

    def drag(self, target, to, fx: float = 0.5, fy: float = 0.5, steps: int = 8, button: str = "left", hold: bool = False):
        """Press on `target` at (fx, fy), move to `to` ((dx, dy) relative pixels, or an item), release."""
        from PySide6.QtCore import QPoint
        a = self._pt(target, fx, fy)
        b = QPoint(a.x() + int(to[0]), a.y() + int(to[1])) if isinstance(to, (tuple, list)) else self._pt(to)
        self.T.mouseMove(self.win, a)
        self.T.mousePress(self.win, self._btn(button), self._mods(), a)
        for i in range(1, steps + 1):
            self.T.mouseMove(self.win, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps))
            self._pump(12)
        if not hold:
            self.T.mouseRelease(self.win, self._btn(button), self._mods(), b)
        self._pump(20)
        return b

    def stroke(self, target, path, fx: float = 0.5, fy: float = 0.5, mods: str = "", steps: int = 4):
        """Press on `target` at (fx, fy), move through `path` ((dx, dy) pixels relative to the press), release: a brush
        stroke or a lasso drawn by hand, with modifiers (``mods="shift"``) held throughout."""
        from PySide6.QtCore import QPoint
        a = self._pt(target, fx, fy)
        m = self._mods(mods)
        self.T.mouseMove(self.win, a)
        self.T.mousePress(self.win, self._btn("left"), m, a)
        prev = a
        for dx, dy in path:
            q = QPoint(a.x() + int(dx), a.y() + int(dy))
            for i in range(1, steps + 1):
                self.T.mouseMove(self.win, QPoint(prev.x() + (q.x() - prev.x()) * i // steps, prev.y() + (q.y() - prev.y()) * i // steps))
                self._pump(8)
            prev = q
        self.T.mouseRelease(self.win, self._btn("left"), m, prev)
        self._pump(20)
        return prev

    def release(self, at, button: str = "left"):
        self.T.mouseRelease(self.win, self._btn(button), self._mods(), self._pt(at))
        self._pump(20)

    def wheel(self, target, dy: int = -120, fx: float = 0.5, fy: float = 0.5):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        p = self._pt(target, fx, fy)
        g = self.win.mapToGlobal(p)
        ev = QWheelEvent(QPointF(p), QPointF(g), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(self.win, ev)
        self._pump(20)

    # -- keyboard ------------------------------------------------------------
    def _activate(self, limit: float = 5.0):
        """Make the app window the focus window again. Qt Quick's Shortcuts (single keys, Ctrl+K, Ctrl+1..5, Esc)
        fire only in the focus window, and a real window on a shared desktop loses it whenever another app or another
        journey's window is activated; clicks still land, so only the keys would fail. A window that cannot get the
        focus back fails here, saying so, instead of as a shortcut that did nothing."""
        if self.win.isActive():
            return
        if os.environ.get("FORM_WINDOW_GHOST") == "1":      # an unseen window: Qt's focus only, the desk keeps its own
            from .main import ghost_focus
            if ghost_focus(self.win) and self.win.isActive():
                return
        t0 = time.time()
        while time.time() - t0 < limit:
            self.win.raise_()
            self.win.requestActivate()
            self._pump(100)
            if self.win.isActive():
                self.log.append("window re-activated")
                return
        raise UIError(f"the app window is not active (another window has the keyboard: {self.app.focusWindow()!r}),"
                      " so its keyboard shortcuts cannot fire")

    def key(self, seq: str, n: int = 1):
        """Press a key or chord written the Qt way: "Ctrl+K", "Escape", "Tab", "Shift+Tab", "V", "Ctrl+Return"."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence
        ks = QKeySequence(seq)
        if ks.count() != 1:
            raise UIError(f"not a single key chord: {seq!r}")
        kc = ks[0]
        k, mods = kc.key(), kc.keyboardModifiers()
        if seq.lower().endswith("shift+tab"):
            k = Qt.Key.Key_Backtab
        self._activate()
        for _ in range(n):
            self.T.keyClick(self.win, k, mods)
            self._pump(20)
        self.log.append(f"key {seq}" + (f" ×{n}" if n > 1 else ""))

    def type(self, text: str):
        """Type into whatever has the keyboard."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        for ch in text:
            code = ord(ch.upper()) if ch.isascii() and ch.isprintable() else 0
            mods = Qt.KeyboardModifier.ShiftModifier if ch.isupper() else Qt.KeyboardModifier.NoModifier
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                self.app.sendEvent(self.win, QKeyEvent(kind, code, mods, ch))
            self._pump(2)
        self._pump(20)
        self.log.append(f"type {text!r}")

    def clear(self):
        """Select all in the focused field and delete it."""
        self.key("Ctrl+A")
        self.key("Backspace")

    def fill(self, target, text: str, enter: bool = False):
        """Click a field, replace its contents, optionally press Return."""
        self.click(target)
        self.clear()
        self.type(text)
        if enter:
            self.key("Return")

    def focus_item(self):
        return self.win.activeFocusItem()

    def focus_inside(self, ancestor) -> bool:
        anc = self.item(ancestor) if isinstance(ancestor, str) else ancestor
        it = self.win.activeFocusItem()
        while it is not None:
            if it is anc or it == anc:
                return True
            it = it.parentItem()
        return False

    # -- window --------------------------------------------------------------
    def resize(self, w: int, h: int):
        self.win.resize(w, h)
        self.wait_until(lambda: self.win.width() == w and self.win.height() == h, 5, f"the window to be {w}x{h}")
        self.settle(350)

    def shot(self, name: str) -> Path:
        self.out.mkdir(parents=True, exist_ok=True)
        p = self.out / (name if name.endswith(".png") else name + ".png")
        self._pump(60)
        self.win.grabWindow().save(str(p))
        return p

    def tree(self, path=None) -> dict:
        """The visible item tree (module tree()); with path, also written there as JSON."""
        t = tree(self.win)
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
        return t

    # -- assertions ----------------------------------------------------------
    def check(self, ok, msg: str = ""):
        if not ok:
            raise UIError(msg or "check failed")

    def eq(self, a, b, msg: str = ""):
        if a != b:
            raise UIError(f"{msg + ': ' if msg else ''}{a!r} != {b!r}")

    def no_warnings(self):
        # a sheet closed while a view was still creating its delegates (slow software rendering): teardown, nothing shown
        teardown = ("Object or context destroyed during incubation", "Cannot create delegate")
        bad = [w for w in self.warnings if "Binding loop" not in w and not any(t in w for t in teardown)]
        if bad:
            raise UIError("QML warnings:\n  " + "\n  ".join(bad))


def _load(script: str):
    path, _, fn = script.partition("::")
    spec = importlib.util.spec_from_file_location("form_journey_" + Path(path).stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(path).resolve().parent))
    spec.loader.exec_module(mod)
    names = [fn] if fn else (["run"] if hasattr(mod, "run") else [n for n in vars(mod) if n.startswith("journey_")])
    return [(n, getattr(mod, n)) for n in names]


def run_script(app, engine, win, studio, bridge, script: str, warnings: list, finish) -> None:
    """Run the journey functions of `script`, then quit the app with 0 (all passed) or 1."""
    import faulthandler
    import signal
    # a journey that blocks the event loop cannot time itself out: print every thread's stack and leave
    faulthandler.dump_traceback_later(float(os.environ.get("FORM_UITEST_WATCHDOG", "900")), exit=True)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    out = Path(os.environ.get("FORM_UITEST_OUT", ".dev/uitest"))
    ui = UI(app, engine, win, studio, bridge, warnings, out)
    rc = 0
    try:
        win.requestActivate()
        ui.wait_until(lambda: ui.js("Store.screen") != "boot", 60, "the app to start")
        for name, fn in _load(script):
            t0 = time.time()
            try:
                fn(ui)
                if os.environ.get("FORM_UITEST_LAX") != "1":
                    ui.no_warnings()
                print(f"PASS {name} ({time.time() - t0:.1f}s)", flush=True)
            except Exception:
                rc = 1
                try:
                    shot = ui.shot("fail-" + Path(script.partition('::')[0]).stem + "-" + name)
                except Exception:
                    shot = None
                try:                               # the item tree beside it: what was on screen, as data
                    dump = write_tree(win, (shot.with_suffix(".json") if shot else
                                            out / f"fail-{Path(script.partition('::')[0]).stem}-{name}.json"))
                except Exception:
                    dump = None
                print(f"FAIL {name} ({time.time() - t0:.1f}s)" + (f"  screenshot: {shot}" if shot else "")
                      + (f"  tree: {dump}" if dump else ""), flush=True)
                traceback.print_exc()
                print("  last actions: " + " | ".join(ui.log[-8:]), file=sys.stderr, flush=True)
                if os.environ.get("FORM_UITEST_DUMP") == "1":
                    try:
                        print("  on screen: " + " ¦ ".join(t.replace("\n", " ")[:60] for t in ui.texts()), file=sys.stderr, flush=True)
                    except Exception:
                        pass
                break
    except Exception:
        rc = 1
        traceback.print_exc()
    finish(rc)
