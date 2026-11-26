"""Render the direction mockups to PNG, headless (Qt WebEngine on the offscreen platform: no window opens).

    .venv/bin/python docs/design/directions/tools/shoot.py            # every page listed in PAGES
    .venv/bin/python docs/design/directions/tools/shoot.py a          # one direction

Each page is 1440 x 900 CSS pixels, saved at 2x. The token sheets are taller (1440 x 1200).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = "2"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--hide-scrollbars --disable-gpu")

ROOT = Path(__file__).resolve().parents[1]
SCREENS = [("workspace", "", 900), ("home", "", 900), ("build", "", 900), ("workspace", "light", 900),
           ("tokens", "", 1200)]


def main() -> int:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    only = sys.argv[1:] or ["a", "b", "c"]
    jobs = []
    for d in only:
        for name, theme, h in SCREENS:
            src = ROOT / d / f"{name}.html"
            if src.exists():
                out = ROOT / d / (f"{name}-{theme}.png" if theme else f"{name}-dark.png" if name != "tokens" else "tokens.png")
                jobs.append((src, theme, h, out))
    app = QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.show()
    state = {"i": 0}

    def load():
        if state["i"] >= len(jobs):
            app.quit()
            return
        src, theme, h, out = jobs[state["i"]]
        view.resize(1440, h)
        url = QUrl.fromLocalFile(str(src))
        if theme:
            url.setQuery("theme=" + theme)
        view.setUrl(url)

    def loaded(ok):
        view.page().runJavaScript("document.fonts.ready.then(() => document.title = 'fonts-ready')")
        QTimer.singleShot(2600, grab)

    def grab():
        src, theme, h, out = jobs[state["i"]]
        view.grab().save(str(out))
        print(out.relative_to(ROOT))
        state["i"] += 1
        load()

    view.loadFinished.connect(loaded)
    load()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
