"""Render direction I's mockups to WebP (quality 95), headless (Qt WebEngine, offscreen, no GPU), 1440 x 900 at 2x, dark and light.

    .venv/bin/python docs/design/directions/i/tools/shoot.py [screen ...] [--dark]
"""
import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); os.environ["QT_SCALE_FACTOR"] = "2"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--hide-scrollbars --disable-gpu")
ROOT = Path(__file__).resolve().parents[1]
DARK_ONLY = {"moment-develop", "moment-unfold", "moment-rollback", "drawing-paper"}

def main():
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication
    from PIL import Image
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; dark = "--dark" in sys.argv
    names = args or sorted(p.stem for p in ROOT.glob("*.html"))
    jobs = [(n, t) for n in names for t in (("dark",) if dark or n in DARK_ONLY else ("dark", "light"))]
    app = QApplication(sys.argv[:1]); view = QWebEngineView(); view.resize(1440, 900); view.show(); st = {"i": 0}
    def load():
        if st["i"] >= len(jobs): app.quit(); return
        n, t = jobs[st["i"]]; url = QUrl.fromLocalFile(str(ROOT / f"{n}.html"))
        if t == "light": url.setQuery("theme=light")
        view.setUrl(url)
    def grab():
        n, t = jobs[st["i"]]; png = ROOT / f"{n}-{t}.png"; view.grab().save(str(png))
        Image.open(png).convert("RGB").save(ROOT / f"{n}-{t}.webp", quality=95, method=6); png.unlink()      # 2880 x 1800
        print(f"{n}-{t}.webp"); st["i"] += 1; load()
    view.loadFinished.connect(lambda ok: QTimer.singleShot(2600, grab)); load(); return app.exec()

if __name__ == "__main__":
    sys.exit(main())
