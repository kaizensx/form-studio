"""Render the Discord art: a cover for every guide, in the app's palette.

    .venv/bin/python scripts/discord/art/render.py          # writes art/guides/<slug>.png

The pictures inside are the README's drawings of the app (docs/readme/*.svg, drawn from real engine runs) and
product pictures from real builds (docs/readme/made-*.jpg). Fonts are the app's own (site/fonts).
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import server as S  # noqa: E402

W, H = 1600, 800
FONTS = (ROOT / "site" / "fonts").as_uri()
MARK = (ROOT / "brand" / "mark.svg").as_uri()
LOCKUP = (ROOT / "brand" / "lockup.svg").as_uri()
README = ROOT / "docs" / "readme"

BASE = f"""
@font-face{{font-family:'Instrument Sans';src:url('{FONTS}/InstrumentSans.woff2') format('woff2');font-weight:100 900}}
@font-face{{font-family:'Geist Mono';src:url('{FONTS}/GeistMono.woff2') format('woff2');font-weight:100 900}}
html,body{{margin:0;width:{{w}}px;height:{{h}}px;overflow:hidden;background:#0a0c0e;color:#e8edeb;
 font-family:'Instrument Sans';-webkit-font-smoothing:antialiased}}
body{{position:relative;background:radial-gradient(1100px 520px at 18% 0%,rgba(185,232,215,.10),transparent 70%),#0a0c0e}}
.grid{{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
 linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:40px 40px;
 -webkit-mask-image:radial-gradient(1200px 700px at 30% 30%,#000,transparent)}}
.kicker{{font-family:'Geist Mono';font-size:22px;letter-spacing:.14em;text-transform:uppercase;color:#b9e8d7}}
.kicker i{{font-style:normal;color:#717b78}}
h1{{font-weight:620;letter-spacing:-.02em;line-height:1.02;margin:22px 0 0}}
p{{font-size:30px;line-height:1.38;color:#a8b2af;font-weight:420;margin:26px 0 0}}
.datum{{position:absolute;left:0;bottom:0;height:6px;width:100%;background:linear-gradient(90deg,#b9e8d7 0 14%,
 rgba(185,232,215,.25) 14% 100%)}}
.lockup{{position:absolute;height:34px}}
"""


def page(w, h, body):
    css = BASE.replace("{w}", str(w)).replace("{h}", str(h))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>" \
           f"<div class='grid'></div>{body}<div class='datum'></div></body></html>"


def guide(i, title, tag, art):
    if art == "hero":
        pic = f"<img src='{(README / 'hero-dark.svg').as_uri()}' style='position:absolute;right:-40px;top:70px;width:840px;" \
              "border-radius:26px;box-shadow:0 30px 120px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.06)'>"
    elif art.startswith("made-"):                 # a product picture from a real build (docs/readme/made-*.jpg)
        pic = f"<img src='{(README / (art + '.jpg')).as_uri()}' style='position:absolute;right:90px;top:70px;width:660px;" \
              "height:660px;object-fit:cover;border-radius:24px;box-shadow:0 30px 120px rgba(0,0,0,.55),0 0 0 1px " \
              "rgba(255,255,255,.06)'>"
    else:
        # inlined, not <img>: the drawings embed their fonts, which an <img> SVG may refuse to load
        f = README / (art + "-dark.svg")
        svg = (f if f.exists() else README / f"feature-{art}-dark.svg").read_text(encoding="utf-8")
        svg = svg.replace('width="414" height="436"', 'width="653" height="688"', 1)
        pic = f"<div style='position:absolute;right:90px;top:56px;border-radius:24px;overflow:hidden;" \
              f"box-shadow:0 30px 120px rgba(0,0,0,.55);line-height:0'>{svg}</div>"
    body = f"""{pic}
<div style='position:absolute;left:96px;top:120px;width:{560 if art == "hero" else 700}px'>
 <div class='kicker'>Guide {i:02d} <i>·</i> {html.escape(tag)}</div>
 <h1 style='font-size:{76 if len(title) < 30 else 62}px'>{html.escape(title)}</h1>
</div>
<img class='lockup' src='{LOCKUP}' style='left:96px;bottom:84px'>"""
    return page(W, H, body)


def render(jobs):
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView
    app = QApplication.instance() or QApplication([])
    v = QWebEngineView()
    tmp = HERE / ".render.html"
    queue = list(jobs)

    def next_job():
        if not queue:
            tmp.unlink(missing_ok=True)
            app.quit()
            return
        out, w, h, doc = queue[0]
        tmp.write_text(doc, encoding="utf-8")
        dpr = v.devicePixelRatioF() or 1
        v.resize(int(w / dpr), int(h / dpr))
        v.setZoomFactor(1 / dpr)
        v.load(QUrl.fromLocalFile(str(tmp)))

    def loaded(ok):
        out, w, h, _ = queue.pop(0)

        def shoot():
            img = v.grab().toImage().scaled(w, h)
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(out))
            print(out.relative_to(ROOT), img.width(), "x", img.height())
            next_job()
        QTimer.singleShot(900, shoot)                         # fonts and images settle
    v.loadFinished.connect(loaded)
    v.show()
    QTimer.singleShot(0, next_job)
    app.exec()


def main():
    render([(HERE / "guides" / f"{slug}.png", W, H, guide(i, title, tag, art))
            for i, (slug, title, tag, art, _) in enumerate(S.GUIDES, 1)])


if __name__ == "__main__":
    main()
