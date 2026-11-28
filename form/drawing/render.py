"""Draw a sheet scene: SVG (here), PDF and PNG (Qt, in a child process), DXF (ezdxf).

The PDF is vector, written by Qt's QPdfWriter with the font embedded; the PNG is the same painter on an image. Qt
runs in its own process with the offscreen platform, so the engine, the MCP server and the CLI never need a GUI
thread. Line widths and dash patterns are ISO 128-2's (form/drawing/standards.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from html import escape
from pathlib import Path

from . import scene as S
from . import standards as STD

FONT_FAMILY = "Helvetica, Arial, 'DejaVu Sans', sans-serif"
QT_FONTS = ("Helvetica", "Arial", "DejaVu Sans")


def _color(sheet, layer):
    c = sheet.get("colors") or S.THEMES[sheet.get("theme", "night")]
    return c.get(layer, c["visible"])


def themed(sheet: dict, theme: str) -> dict:
    out = dict(sheet)
    out["theme"] = theme
    out["colors"] = S.THEMES[theme]
    return out


def svg(sheet: dict) -> str:
    W, H = sheet["size"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" fill="{_color(sheet, "paper")}"/>',
           f'<g transform="translate(0,{H}) scale(1,-1)" fill="none" stroke-linecap="round" stroke-linejoin="round">']

    def stroke(layer):
        w = STD.LINES.get(layer, 0.18)
        dash = STD.DASH.get(layer)
        d = f' stroke-dasharray="{",".join(str(x) for x in dash)}"' if dash else ""
        return f'stroke="{_color(sheet, layer)}" stroke-width="{w}"{d}'

    def node(n):
        k = n["kind"]
        if k == "group":
            out.append(f'<g data-role="{escape(n["role"])}" id="{escape(n["id"] or "")}">')
            for c in n["children"]:
                node(c)
            out.append("</g>")
        elif k == "line":
            out.append(f'<line x1="{n["a"][0]}" y1="{n["a"][1]}" x2="{n["b"][0]}" y2="{n["b"][1]}" {stroke(n["layer"])}/>')
        elif k == "polyline":
            pts = " ".join(f"{p[0]},{p[1]}" for p in n["pts"])
            tag = "polygon" if n.get("closed") else "polyline"
            out.append(f'<{tag} points="{pts}" {stroke(n["layer"])}/>')
        elif k == "polygon":
            pts = " ".join(f"{p[0]},{p[1]}" for p in n["pts"])
            out.append(f'<polygon points="{pts}" fill="{_color(sheet, n["layer"])}" stroke="none"/>')
        elif k == "circle":
            fill = _color(sheet, n["layer"]) if n.get("fill") else "none"
            out.append(f'<circle cx="{n["c"][0]}" cy="{n["c"][1]}" r="{n["r"]}" fill="{fill}" {stroke(n["layer"])}/>')
        elif k == "arc":
            import math
            a0, a1 = math.radians(n["a0"]), math.radians(n["a1"])
            while a1 <= a0:
                a1 += 2 * math.pi
            x0, y0 = n["c"][0] + n["r"] * math.cos(a0), n["c"][1] + n["r"] * math.sin(a0)
            x1, y1 = n["c"][0] + n["r"] * math.cos(a1), n["c"][1] + n["r"] * math.sin(a1)
            large = 1 if a1 - a0 > math.pi else 0
            out.append(f'<path d="M{x0:.3f},{y0:.3f} A{n["r"]},{n["r"]} 0 {large} 1 {x1:.3f},{y1:.3f}" {stroke(n["layer"])}/>')
        elif k == "text":
            x, y = n["at"]
            anchor = n.get("anchor", "middle")
            base = {"baseline": "alphabetic", "middle": "central", "top": "hanging"}[n.get("valign", "baseline")]
            size = n["h"] / 0.72                         # cap height -> font size (Helvetica caps are 0.72 em)
            rot = -n.get("rot", 0.0)
            out.append(f'<text transform="translate({x},{y}) scale(1,-1) rotate({rot})" font-family="{FONT_FAMILY}" '
                       f'font-size="{size:.3f}" text-anchor="{anchor}" dominant-baseline="{base}" '
                       f'fill="{_color(sheet, n["layer"])}" stroke="none">{escape(n["s"])}</text>')

    for c in sheet["children"]:
        node(c)
    out.append("</g></svg>")
    return "\n".join(out)


def dxf(sheet: dict, path: str) -> str:
    """The sheet as DXF (R2013, mm): one layer per line type, text as TEXT with its height."""
    import ezdxf
    doc = ezdxf.new("R2013", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    lt = {"hidden": "DASHED", "center": "CENTER"}
    for layer in ("visible", "hidden", "thin", "center", "dimension", "hatch", "section", "frame", "text", "gdt", "title"):
        doc.layers.add(layer.upper(), linetype=lt.get(layer, "CONTINUOUS"),
                       lineweight=int(round(STD.LINES.get(layer, 0.18) * 100)))

    def node(n, role):
        k = n["kind"]
        L = {"layer": n.get("layer", "visible").upper()}
        if k == "group":
            for c in n["children"]:
                node(c, n["role"])
        elif k == "line":
            msp.add_line(n["a"], n["b"], dxfattribs=L)
        elif k == "polyline":
            msp.add_lwpolyline(n["pts"], close=n.get("closed", False), dxfattribs=L)
        elif k == "polygon":
            h = msp.add_hatch(dxfattribs=L)
            h.paths.add_polyline_path(n["pts"], is_closed=True)
        elif k == "circle":
            msp.add_circle(n["c"], n["r"], dxfattribs=L)
        elif k == "arc":
            msp.add_arc(n["c"], n["r"], n["a0"], n["a1"], dxfattribs=L)
        elif k == "text":
            align = {"start": "LEFT", "middle": "CENTER", "end": "RIGHT"}[n.get("anchor", "middle")]
            v = {"baseline": "BOTTOM", "middle": "MIDDLE", "top": "TOP"}[n.get("valign", "baseline")]
            if v == "BOTTOM":
                v = "BASELINE" if False else "BOTTOM"
            from ezdxf.enums import TextEntityAlignment
            al = getattr(TextEntityAlignment, f"{v}_{align}" if v != "BASELINE" else align)
            t = msp.add_text(n["s"], height=n["h"], rotation=n.get("rot", 0.0), dxfattribs=L)
            t.set_placement(n["at"], align=al)
    for c in sheet["children"]:
        node(c, "")
    doc.saveas(path)
    return path


def qt(sheet: dict, pdf: str | None = None, png: str | None = None, dpi: int = 150, crops: list | None = None) -> dict:
    """PDF and/or PNG of the sheet by Qt, in a child process. crops: [{"box": [x0,y0,x1,y1] sheet mm, "out": png}]."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"sheet": sheet, "pdf": pdf, "png": png, "dpi": dpi, "crops": crops or []}, fh)
        job = fh.name
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        r = subprocess.run([sys.executable, "-m", "form.drawing.qtpaint", job], env=env, capture_output=True,
                           text=True, timeout=180)
    finally:
        try:
            os.unlink(job)
        except OSError:
            pass
    if r.returncode != 0:
        raise RuntimeError("Qt could not draw the sheet: " + (r.stderr or r.stdout)[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])
