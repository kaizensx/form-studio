"""Render the Discord art in the app's look, Lightdesk: a cover for every guide, the server banner and the bot's
profile banner.

    .venv/bin/python scripts/discord/art/render.py          # writes art/guides/<slug>.png, art/banner.html,
                                                            # art/banner.png, art/profile-banner.png and art/icon.png

art/icon.png, the server's icon and the bot's avatar, is the app icon at 512 px (brand/build.py draws it).

art/welcome.gif is the same banner in motion: art/frames.py records art/banner.html.

The pictures inside are the README's drawings of the app (docs/readme/*.svg, drawn from real engine runs) and
product pictures from real builds (docs/readme/made-*.jpg). Fonts are the app's own (site/fonts).
"""
from __future__ import annotations

import html
import shutil
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
@font-face{{font-family:'Geist';src:url('{FONTS}/Geist.woff2') format('woff2');font-weight:100 900}}
@font-face{{font-family:'Geist Mono';src:url('{FONTS}/GeistMono.woff2') format('woff2');font-weight:100 900}}
html,body{{margin:0;width:{{w}}px;height:{{h}}px;overflow:hidden;background:#0b0b0c;color:#f4f3f1;
 font-family:'Geist';-webkit-font-smoothing:antialiased}}
body{{position:relative;background:radial-gradient(ellipse 60% 58% at 68% 56%,rgba(255,233,207,.13),transparent 70%),
 linear-gradient(180deg,#0a0a0b 0%,#131314 38%,#1b1b1c 60%,#0d0d0e 100%)}}
.kicker{{display:flex;align-items:center;gap:16px;font-family:'Geist Mono';font-weight:500;font-size:20px;letter-spacing:.16em;
 text-transform:uppercase;color:#3ee6ff}}
.kicker::before{{content:"";width:10px;height:10px;border-radius:50%;background:#3ee6ff;box-shadow:0 0 0 7px rgba(62,230,255,.22)}}
.kicker i{{font-style:normal;color:#7d7c78}}
h1{{font-weight:600;letter-spacing:-.04em;line-height:1.02;margin:26px 0 0}}
p{{font-size:30px;line-height:1.38;color:#a9a8a5;font-weight:400;margin:26px 0 0}}
.lockup{{position:absolute;height:64px}}
.pane{{border-radius:28px;overflow:hidden;line-height:0;box-shadow:0 0 0 1px rgba(255,255,255,.11),0 30px 120px rgba(0,0,0,.6)}}
"""


def page(w, h, body):
    css = BASE.replace("{w}", str(w)).replace("{h}", str(h))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def guide(i, title, tag, art):
    if art == "hero":
        pic = f"<img src='{(README / 'hero-dark.svg').as_uri()}' style='position:absolute;right:-40px;top:70px;width:840px;" \
              "border-radius:28px;box-shadow:0 30px 120px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.11)'>"
    elif art.startswith("made-"):                 # a product picture from a real build (docs/readme/made-*.jpg)
        pic = f"<img src='{(README / (art + '.jpg')).as_uri()}' style='position:absolute;right:90px;top:70px;width:660px;" \
              "height:660px;object-fit:cover;border-radius:28px;box-shadow:0 30px 120px rgba(0,0,0,.55),0 0 0 1px " \
              "rgba(255,255,255,.11)'>"
    else:
        # inlined, not <img>: the drawings embed their fonts, which an <img> SVG may refuse to load
        f = README / (art + "-dark.svg")
        svg = (f if f.exists() else README / f"feature-{art}-dark.svg").read_text(encoding="utf-8")
        svg = svg.replace('width="414" height="436"', 'width="653" height="688"', 1)
        pic = f"<div class='pane' style='position:absolute;right:90px;top:56px'>{svg}</div>"
    body = f"""{pic}
<div style='position:absolute;left:96px;top:120px;width:{560 if art == "hero" else 700}px'>
 <div class='kicker'>Guide {i:02d} <i>·</i> {html.escape(tag)}</div>
 <h1 style='font-size:{76 if len(title) < 30 else 62}px'>{html.escape(title)}</h1>
</div>
<img class='lockup' src='{LOCKUP}' style='left:96px;bottom:88px'>"""
    return page(W, H, body)


def _workspace(width: int) -> str:
    """The README's drawing of the workspace mid-build (docs/readme/building-dark.svg), inlined at a width."""
    svg = (README / "building-dark.svg").read_text(encoding="utf-8")
    return svg.replace('width="828" height="520"', f'width="{width}" height="{round(width * 520 / 828)}"', 1)


def banner():
    """1600 x 900, the server's banner: the lockup over the drawn workspace."""
    return page(1600, 900, f"""
<img class='lockup' src='{LOCKUP}' style='left:50%;top:54px;height:60px;transform:translateX(-50%)'>
<p style='position:absolute;left:0;right:0;top:112px;text-align:center;font-size:26px'>Describe anything. An engineer-grade agent builds it as real, editable CAD.</p>
<div class='pane' style='position:absolute;left:210px;top:212px'>{_workspace(1180)}</div>""")


def profile_banner():
    """1360 x 480, the bot's profile banner: the lockup beside the drawn workspace."""
    return page(1360, 480, f"""
<img class='lockup' src='{LOCKUP}' style='left:72px;top:150px;height:58px'>
<p style='position:absolute;left:72px;top:222px;width:420px;font-size:25px;margin:0'>Describe anything.<br>The open-source AI CAD studio.</p>
<div class='pane' style='position:absolute;left:560px;top:44px'>{_workspace(860)}</div>""")


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
    shutil.copyfile(ROOT / "form" / "app" / "assets" / "icon-512.png", HERE / "icon.png")
    print((HERE / "icon.png").relative_to(ROOT), "512 x 512")
    # also what art/frames.py records for welcome.gif; its links are relative, so the file is the same on any machine
    (HERE / "banner.html").write_text(banner().replace(ROOT.as_uri(), "../../.."), encoding="utf-8")
    render([(HERE / "guides" / f"{slug}.png", W, H, guide(i, title, tag, art))
            for i, (slug, title, tag, art, _) in enumerate(S.GUIDES, 1)]
           + [(HERE / "banner.png", 1600, 900, banner()), (HERE / "profile-banner.png", 1360, 480, profile_banner())])


if __name__ == "__main__":
    main()
