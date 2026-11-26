"""The part is lit from every side: the view from below, and every elevation from -89 to 89 degrees at a close, the
usual and the farthest zoom, shows the part well lit, never a dark shape, and orbiting or zooming never flashes.

The part's pixels are found by picking (Viewport.hitAt on a grid), so the measure does not depend on the part's
colour: it is the mean luminance of the pixels that show the part. Each frame must keep at least a quarter of the
iso view's luminance, no frame may be all dark, and between two frames of a continuous orbit or zoom the mean
luminance of the part and of the whole free area may only change a little.

Run it in both appearances: FORM_APPEARANCE=dark (the default) and FORM_APPEARANCE=light. With FORM_WPB_FRAMES set,
every frame and a contact sheet of them are saved there."""
import json
import os
from pathlib import Path

from _lib import make

DATA = "fresh"
S = {"frames": [], "log": [], "fails": []}
VIEWS = ("iso", "front", "side", "back", "top", "under")
DISTS = (30, 420, 3000)
MIN_K = 0.25            # every frame keeps a quarter of the iso view's part luminance
STEP_PART = 0.24        # the most the part’s luminance may change between frames 2 degrees (or 8% zoom) apart, of iso.
                        # (0.22 until the view became a plate 16 px narrower: at 3000 mm the part is some 40 px wide and the
                        # sample grid lands on it differently; the step through the floor measured 0.19 before and 0.22 after
                        # with the same shaders)
STEP_FRAME = 0.12       # the same for the whole free area, of its own luminance range (0..255)


def need(ui, cond, msg):
    """A failed check is kept and reported at the end, so one run shows every dark frame, not just the first."""
    if not cond:
        S["fails"].append(msg)
        print("  FAIL " + msg, flush=True)


def appearance(ui):
    return "dark" if ui.js("Theme.dark") else "light"


def out_dir(ui):
    d = os.environ.get("FORM_WPB_FRAMES")
    p = Path(d) / appearance(ui) if d else Path(ui.out) / ("viewport-light-" + appearance(ui))
    p.mkdir(parents=True, exist_ok=True)
    return p


def lum(c):
    return 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()


def free_rect(ui):
    from PySide6.QtCore import QPointF
    v = ui.item("viewport")
    p = v.mapToScene(QPointF(0, 0))
    l = float(v.property("insetLeft"))
    t = float(v.property("insetTop"))
    r = v.width() - float(v.property("insetRight"))
    b = v.height() - float(v.property("insetBottom"))
    return p.x(), p.y(), l, t, max(l + 40, r), max(t + 40, b)


PICK = """(function (l, t, r, b, nx, ny) {   // viewport-local points that show the part
    var v = Store.viewer, out = []
    for (var i = 0; i < nx; i++) for (var j = 0; j < ny; j++) {
        var x = l + (r - l) * (i + 0.5) / nx, y = t + (b - t) * (j + 0.5) / ny
        if (v.hitAt(x, y)) out.push([x, y])
    }
    return out })(%f, %f, %f, %f, %d, %d)"""


def measure(ui, name=None, sheet=True):
    """{part: mean luminance of the part's pixels, n: how many, frame: mean luminance of the free area, bright: share
    of free-area pixels brighter than 40}"""
    ui.settle(160)
    img = ui.win.grabWindow()
    k = img.width() / max(1, ui.win.width())
    ox, oy, l, t, r, b = free_rect(ui)
    pts = ui.js(PICK % (l, t, r, b, 44, 30)) or []
    if len(pts) < 40:                       # small on screen (far away): a finer grid around what was hit
        gx, gy = (r - l) / 44, (b - t) / 30
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            box = (max(l, min(xs) - gx), max(t, min(ys) - gy), min(r, max(xs) + gx), min(b, max(ys) + gy))
        else:                               # nothing hit: the orbit centre is the middle of the free area
            cx, cy = (l + r) / 2, (t + b) / 2
            box = (cx - 3 * gx, cy - 3 * gy, cx + 3 * gx, cy + 3 * gy)
        pts = ui.js(PICK % (box + (36, 36))) or pts
    cols = [img.pixelColor(int((ox + x) * k), int((oy + y) * k)) for x, y in pts]
    vals = [lum(c) for c in cols]
    # the camera inside the solid (zoomed all the way in) sees the cut colour, mint: those frames are a different
    # picture by design, so a step into or out of them is not a flash
    inside = sum(1 for c in cols if c.green() - c.red() > 12) / max(1, len(cols))
    frame = []
    for i in range(40):
        for j in range(28):
            frame.append(lum(img.pixelColor(int((ox + l + (r - l) * (i + 0.5) / 40) * k), int((oy + t + (b - t) * (j + 0.5) / 28) * k))))
    m = {"part": sum(vals) / len(vals) if vals else 0.0, "n": len(vals), "frame": sum(frame) / len(frame),
         "bright": sum(1 for x in frame if x > 40) / len(frame), "inside": inside}
    if name:
        p = out_dir(ui) / (name + ".png")
        img.copy(int((ox + l) * k), int((oy + t) * k), int((r - l) * k), int((b - t) * k)).save(str(p))
        if sheet:
            S["frames"].append((name, p, m))
    return m


def place(ui, az, el, dist):
    ui.run_js("(function () { var v = Store.viewer; v.tween = false; v.target = v.center(v.bounds); v.az = %f; v.el = %f; v.dist = %f })()" % (az, el, dist))


def note(ui, what, m):
    line = f"{what}: part {m['part']:.1f} ({m['n']} px)  frame {m['frame']:.1f}  bright {m['bright']:.2f}"
    S["log"].append(line)
    print("  " + line, flush=True)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["pid"] = make(ui, "enclosure", "Lit box")
    ui.settle(800)
    ui.run_js("Store.viewer.setView('iso', false)")
    ui.settle(500)
    S["iso"] = measure(ui, "view-iso")
    note(ui, "iso", S["iso"])
    ui.check(S["iso"]["n"] > 60 and S["iso"]["part"] > 40, f"the part is on screen and lit at iso: {S['iso']}")


def ok(ui, what, m):
    iso = S["iso"]["part"]
    need(ui, m["n"] >= 3, f"the part is on screen {what}: {m}")
    need(ui, m["part"] >= MIN_K * iso, f"the part is lit {what}: {m['part']:.1f} < {MIN_K:.0%} of iso {iso:.1f}")
    need(ui, m["bright"] > 0.004 or m["part"] > 40, f"the frame is not all dark {what}: {m}")


def journey_standard_views(ui):
    for v in VIEWS:
        ui.run_js("Store.viewer.setView(%r, false)" % v)
        m = measure(ui, "view-" + v)
        note(ui, v, m)
        S.setdefault("views", {})[v] = m
        ok(ui, "in the " + v + " view", m)


def _steps(ui, what, seq):
    """Frame-to-frame: neither the part nor the whole view jumps between two neighbouring camera positions."""
    iso = S["iso"]["part"]
    worst_p, worst_f = 0.0, 0.0
    for i in range(1, len(seq)):
        (a, ma), (b, mb) = seq[i - 1], seq[i]
        if (ma["inside"] > 0.5) != (mb["inside"] > 0.5):
            S["log"].append(f"{what}: {a} → {b} goes through the part's wall (the cut colour), not compared")
            continue
        if ma["n"] >= 3 and mb["n"] >= 3:
            dp = abs(ma["part"] - mb["part"]) / max(1.0, iso)
            worst_p = max(worst_p, dp)
            need(ui, dp <= STEP_PART, f"the part's light jumps {what} between {a} and {b}: {ma['part']:.1f} → {mb['part']:.1f}")
        df = abs(ma["frame"] - mb["frame"]) / 255
        worst_f = max(worst_f, df)
        need(ui, df <= STEP_FRAME, f"the view flashes {what} between {a} and {b}: {ma['frame']:.1f} → {mb['frame']:.1f}")
    S["log"].append(f"{what}: worst step part {worst_p:.3f} of iso, frame {worst_f:.3f}")
    print(f"  {what}: worst step part {worst_p:.3f} of iso, frame {worst_f:.3f}", flush=True)


def journey_elevation_sweep(ui):
    for d in DISTS:
        seq = []
        for el in range(-89, 90, 2):
            place(ui, -34, el, d)
            m = measure(ui, f"sweep-d{d}-el{el:+03d}", sheet=el % 10 in (1, -9) or el in (-89, 89))
            seq.append((f"el {el}", m))
            ok(ui, f"at elevation {el}, distance {d}", m)
        lo = min(seq, key=lambda x: x[1]["part"])
        S["log"].append(f"sweep d={d}: darkest {lo[0]} part {lo[1]['part']:.1f}, brightest {max(x[1]['part'] for x in seq):.1f}")
        print("  " + S["log"][-1], flush=True)
        _steps(ui, f"orbiting at distance {d}", seq)


def journey_zoom_sweep(ui):
    for el in (28.4, -30, 6):
        seq, d = [], 30.0
        while d <= 3000:
            place(ui, -34, el, d)
            seq.append((f"dist {d:.0f}", measure(ui)))
            ok(ui, f"zooming at elevation {el}, distance {d:.0f}", seq[-1][1])
            d *= 1.08
        _steps(ui, f"zooming at elevation {el}", seq)


def journey_contact_sheet(ui):
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    fr = S["frames"]
    cols, tw, th = 8, 300, 200
    rows = (len(fr) + cols - 1) // cols
    sheet = QImage(cols * tw, rows * (th + 34), QImage.Format_RGB32)
    sheet.fill(QColor("#202020"))
    p = QPainter(sheet)
    p.setFont(QFont("Helvetica", 11))
    for i, (name, path, m) in enumerate(fr):
        x, y = (i % cols) * tw, (i // cols) * (th + 34)
        im = QImage(str(path)).scaled(tw - 4, th - 4, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage(x + 2 + (tw - 4 - im.width()) // 2, y + 2 + (th - 4 - im.height()) // 2, im)
        p.setPen(QColor("#f0f0f0"))
        p.drawText(QRect(x + 4, y + th, tw - 8, 32), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{name}\npart {m['part']:.0f} ({m['n']})  frame {m['frame']:.0f}")
    p.end()
    out = out_dir(ui)
    sheet.save(str(out / "contact_sheet.png"))
    (out / "measurements.txt").write_text("\n".join(S["log"]) + "\n", encoding="utf-8")
    (out / "frames.json").write_text(json.dumps({n: m for n, _, m in fr}, indent=1), encoding="utf-8")
    print(f"  contact sheet: {out / 'contact_sheet.png'}", flush=True)
    ui.check(not S["fails"], f"{len(S['fails'])} frames failed: " + "; ".join(S["fails"][:12]))
