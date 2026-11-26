"""A sharp picture of the website's live replica of the app, for the README (it links to the page where it runs).

    python -m http.server 8793 --directory site &
    QT_QPA_PLATFORM=offscreen python scripts/media/site_shot.py "http://127.0.0.1:8793/?reduce&desk=build-6" docs/images/try-it.webp
    QT_QPA_PLATFORM=offscreen python scripts/media/site_shot.py "http://127.0.0.1:8793/?reduce&desk=rest" docs/images/try-it-workspace.webp

Loads the page in Qt WebEngine, crops to the drawn window and saves it. The desk parameter chooses the moment the
drawing holds (rest, build-N for line N of the program, answer-N, pick-N); reduce turns motion off. This is a picture
of the website's drawing of the app, not a screenshot of the app.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    url, out = sys.argv[1], Path(sys.argv[2])
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 1600
    from PySide6.QtCore import QRect, QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.resize(width, 1200)
    view.setUrl(QUrl(url))
    view.show()
    box = {}

    def measure():
        js = ("(function(){ document.getElementById('nav').style.display = 'none'; const f = document.getElementById('desk-frame'); window.scrollTo(0, f.getBoundingClientRect().top + scrollY - 40);"
              " const r = f.getBoundingClientRect(); return JSON.stringify([r.left, r.top, r.width, r.height]); })()")
        view.page().runJavaScript(js, 0, got)

    def got(r):
        import json; box["r"] = json.loads(r)
        QTimer.singleShot(1500, grab)

    def grab():
        x, y, w, h = box["r"]
        img = view.grab().toImage()
        k = img.devicePixelRatio()
        img = img.copy(QRect(int(x * k), int(y * k), int(w * k), int(h * k)))
        from PIL import Image
        tmp = out.with_name(out.stem + ".grab.png")
        img.save(str(tmp))
        im = Image.open(tmp).convert("RGB")
        im.save(out, quality=90, method=6) if out.suffix == ".webp" else im.save(out)
        tmp.unlink()
        print(out, im.size)
        app.quit()

    view.loadFinished.connect(lambda ok: QTimer.singleShot(3500, measure))
    QTimer.singleShot(60000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
