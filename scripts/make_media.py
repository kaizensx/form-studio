"""Regenerate every image and animation in docs/assets from real kernel builds.

Nothing here is drawn by hand: each frame is a recipe built by build123d/OCCT and
rasterised by form/render.py. Run:  .venv/bin/python scripts/make_media.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "assets"


def main():
    tmp = tempfile.mkdtemp(prefix="form-media-")
    os.environ["FORM_DATA"] = tmp
    from PIL import Image, ImageDraw
    from form import animate, config, optimize, render
    from form.studio import Studio
    OUT.mkdir(parents=True, exist_ok=True)
    st = Studio(config.load())
    log = {}
    t0 = time.time()

    def proj(name, rid, **vals):
        return st.create(name, rid, values=vals)

    # --- motion: real builds between two designs -------------------------------------------------
    bin_ = proj("Workshop bin", "gridfinity")
    a = st.rev(bin_)["values"]
    b = {**a, "grid_x": 3, "grid_y": 2, "height_u": 4, "dividers_x": 2, "dividers_y": 1, "label_w": 14}
    log["bin_morph"] = animate.morph(st, bin_, a, b, OUT / "morph-gridfinity.gif", frames=18, title="Gridfinity bin: 2x1 to 3x2",
                                     size=(560, 400))
    pl = proj("Twist planter", "planter")
    a = {**st.rev(pl)["values"], "twist": 0}
    b = {**a, "twist": 150, "sides": 7, "bulge": 0.16}
    log["planter_morph"] = animate.morph(st, pl, a, b, OUT / "morph-planter.gif", frames=22, title="Planter: twist 0 to 150 deg",
                                         size=(560, 400), elevation=18)
    dock = proj("Phone dock", "dock")
    a = st.rev(dock)["values"]
    b = {**a, "lean": 22, "depth": 96, "relief_width": 36, "back_height": 44}
    log["dock_morph"] = animate.morph(st, dock, a, b, OUT / "morph-dock.gif", frames=18, title="Phone dock: lean 15 to 22 deg",
                                      size=(560, 400))

    # --- turntables ---------------------------------------------------------------------------------
    hook = proj("Coat hook", "hook")
    for p, name in ((bin_, "gridfinity"), (hook, "hook"), (pl, "planter"), (dock, "dock")):
        log[f"turntable_{name}"] = animate.turntable(st, p, OUT / f"turntable-{name}.gif", frames=30, size=(420, 320))

    # --- gallery ------------------------------------------------------------------------------------
    coupon = proj("Fit coupon", "coupon")
    tiles = []
    for p in (dock, bin_, hook, pl, coupon):
        r = st.recipes[p["recipe"]]
        v = st.view(p)
        tiles.append(render.render_png(v, [{"id": f.id, "label": f.label} for f in r.features], "iso", size=(520, 420),
                                       title=r.title, as_image=True))
    W, H = tiles[0].size
    sheet = Image.new("RGB", (W * 3, H * 2), render.PAPER)
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * W, (i // 3) * H))
    d = ImageDraw.Draw(sheet)
    f1, f2 = render._font(30), render._font(16)
    d.text((2 * W + 30, H + 140), "Your recipe here.", fill=render.INK, font=f1)
    d.text((2 * W + 30, H + 186), "About 200 lines of build123d.", fill=render.MUTED, font=f2)
    d.text((2 * W + 30, H + 210), "See docs/RECIPES.md", fill=render.MUTED, font=f2)
    sheet.save(OUT / "gallery.png", optimize=True)

    # --- optimizer before / after -------------------------------------------------------------------
    res = optimize.run(st, hook, [{"key": "arm_t", "min": 4, "max": 20}, {"key": "plate_w", "min": 14, "max": 40}],
                       {"minimize": "solid_mass_g"}, ["statics.safety_factor >= 3"], budget=36)
    log["optimize"] = res
    r = st.recipes["hook"]
    feats = [{"id": f.id, "label": f.label} for f in r.features]
    before = st.view(hook)
    after = st.preview(hook, res["best"]["values"])
    cur = res["current"]
    imgs = [render.render_png(before, feats, "iso", size=(560, 440), title=f"Before: {cur['solid_mass_g']:.1f} g, safety {cur['statics.safety_factor']:.1f}x",
                              highlight="arm", as_image=True),
            render.render_png(after, feats, "iso", size=(560, 440), title=f"After: {res['best']['solid_mass_g']:.1f} g, safety {res['best']['statics.safety_factor']:.1f}x",
                              highlight="arm", as_image=True)]
    pair = Image.new("RGB", (1120, 500), render.PAPER)
    pair.paste(imgs[0], (0, 0))
    pair.paste(imgs[1], (560, 0))
    d = ImageDraw.Draw(pair)
    d.text((18, 456), f"optimize: minimize solid_mass_g subject to statics.safety_factor >= 3   ·   {res['evaluated']} designs built by the kernel",
           fill=render.MUTED, font=render._font(15))
    pair.save(OUT / "optimize-hook.png", optimize=True)

    # --- social preview (1280 x 640) ----------------------------------------------------------------
    card = Image.new("RGB", (1280, 640), render.PAPER)
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, 1280, 8], fill=render.SIGNAL)
    d.text((64, 70), "FORM", fill=render.INK, font=render._font(120))
    d.text((68, 220), "Coding agents that design parts", fill=render.INK, font=render._font(40))
    d.text((68, 270), "you can actually print.", fill=render.INK, font=render._font(40))
    d.text((68, 350), "Real CAD kernel  ·  real slicer  ·  honest evidence  ·  MCP", fill=render.MUTED, font=render._font(24))
    d.text((68, 560), "Claude Code  ·  Codex  ·  Gemini CLI  ·  Cursor", fill=render.MUTED, font=render._font(22))
    for i, p in enumerate((bin_, pl)):
        rr = st.recipes[p["recipe"]]
        im = render.render_png(st.view(p), [{"id": f.id, "label": f.label} for f in rr.features], camera=(-55, 26),
                               frame_box=animate._bbox(st.view(p)), size=(360, 300), overlay=False, as_image=True)
        import numpy as np
        px = np.asarray(im).astype(int)
        mask = Image.fromarray(((np.abs(px - render.PAPER).sum(2) > 6) * 255).astype("uint8"))   # part only, no tile
        card.paste(im, (700 + i * 230, 90 + i * 230), mask)
    card.save(OUT / "social-preview.png", optimize=True)

    (OUT / "agent-session.svg").write_text(agent_svg())
    st.kernel.stop()
    log["seconds"] = round(time.time() - t0, 1)
    (OUT / "MEDIA_LOG.json").write_text(json.dumps(log, indent=1, default=str)
                                     .replace(str(ROOT), "<repo>").replace(tmp, "<tmp>").replace(str(Path.home()), "~"))
    print(json.dumps({k: (v.get("bytes") if isinstance(v, dict) else v) for k, v in log.items() if k != "optimize"}, indent=1))


# Lines from the real Claude Code (Opus 5.5) session recorded in docs/VERIFICATION.md, trimmed for width.
SESSION = [
    ("prompt", "> I measured my phone with calipers: 75.6 mm wide, 8.4 mm thick"),
    ("prompt", "  with the case. Make me a desk dock and tell me if it's ready."),
    ("gap", ""),
    ("call", "form_overview"),
    ("out", "  build123d 0.13.0 / OCP 8.0.1.1 · Bambu Studio 02.09.01.70 · A1 mini"),
    ("call", "describe_recipe dock"),
    ("out", "  20 parameters (mm, deg, g) · 6 features · fit: pocket <-> device"),
    ("call", "create_project \"Desk phone dock\""),
    ("call", "preview_change device_width=75.6 device_thickness=8.4"),
    ("out", "  Pocket resized · Solid, STEP+STL, Checks, Slice would go stale"),
    ("call", "commit_change expect_head=1 provenance=measured (calipers)"),
    ("out", "  r02 · solid 0.33 s · exports · checks · slice done"),
    ("call", "render view=sheet"),
    ("img", "  [image: four views, coloured by feature]"),
    ("call", "request_release"),
    ("warn", "  ready · acknowledge: tip-over resistance 0.75 N (model)"),
    ("gap", ""),
    ("say", "Nearly ready. Pocket 76.1 x 8.9 mm, 0.25 mm per side."),
    ("say", "Slice: 94 min, 57.6 g, no supports (simulated, not a print)."),
    ("say", "Tip-over uses a default phone height and mass. Tell me yours."),
    ("say", "I can't approve it. Review it on the bench:"),
    ("link", "http://127.0.0.1:4174/#p=desk-phone-dock&tab=release"),
]


def agent_svg() -> str:
    W, lh, top = 760, 21, 58
    H = top + lh * len(SESSION) + 36
    colors = {"prompt": "#f4f1ea", "call": "#9fd3a6", "out": "#9a968c", "img": "#c9a26b", "warn": "#e8b35a",
              "say": "#f4f1ea", "link": "#ff8a5c", "gap": "#000"}
    step, total = 0.55, 0.55 * len(SESSION) + 6
    css, rows = [], []
    for i, (kind, text) in enumerate(SESSION):
        t0 = (0.8 + i * step) / total * 100
        css.append(f"@keyframes k{i}{{0%,{t0:.2f}%{{opacity:0;transform:translateY(4px)}}"
                   f"{min(t0 + 1.2, 96):.2f}%,96%{{opacity:1;transform:none}}100%{{opacity:0}}}}"
                   f".l{i}{{animation:k{i} {total:.1f}s infinite;opacity:0}}")
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        prefix = '<tspan fill="#e24d26">● </tspan>' if kind == "call" else ""
        rows.append(f'<text class="l{i}" x="24" y="{top + i * lh}" fill="{colors[kind]}">{prefix}{esc}</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img"
 aria-label="A real Claude Code session using FORM over MCP">
<style>text{{font:13.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre}}{''.join(css)}</style>
<rect width="{W}" height="{H}" rx="12" fill="#1c1b19"/>
<circle cx="22" cy="22" r="6" fill="#e24d26"/><circle cx="42" cy="22" r="6" fill="#e8b35a"/><circle cx="62" cy="22" r="6" fill="#9fd3a6"/>
<text x="{W - 24}" y="27" text-anchor="end" fill="#9a968c" style="font-size:12px">claude code · FORM over MCP · real session, trimmed</text>
{chr(10).join(rows)}
</svg>
"""


if __name__ == "__main__":
    main()
