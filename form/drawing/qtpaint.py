"""Child process: paint a sheet scene with Qt into a vector PDF (QPdfWriter) and/or a PNG, and read PDFs back
(text with positions, page images) for the drawing check.

    python -m form.drawing.qtpaint job.json      # prints one JSON line with what it wrote

A job is {"sheet", "pdf", "png", "dpi", "crops"} to paint, or {"read_pdf": path, "dpi", "out_dir"} to read.
"""
from __future__ import annotations

import json
import math
import sys


def _app():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication(["form-drawing"])


def _font(QFont, family_list, cap_h_px):
    from PySide6.QtGui import QFontDatabase, QFontMetricsF
    fams = set(QFontDatabase.families())
    fam = next((f for f in family_list if f in fams), None)
    f = QFont(fam) if fam else QFont()
    f.setPixelSize(max(1, int(round(cap_h_px / 0.72))))
    f.setPointSizeF(cap_h_px / 0.72) if False else None
    # fit the cap height exactly with a fractional size
    f.setPointSizeF(max(0.5, cap_h_px / 0.72))
    fm = QFontMetricsF(f)
    ch = fm.capHeight() or cap_h_px
    f.setPointSizeF(max(0.5, f.pointSizeF() * cap_h_px / ch))
    return f


def paint(painter, sheet, px_per_mm, H):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF
    from form.drawing import scene as S
    from form.drawing import standards as STD
    from form.drawing.render import QT_FONTS
    colors = sheet.get("colors") or S.THEMES[sheet.get("theme", "night")]
    W = sheet["size"][0]
    painter.fillRect(QRectF(0, 0, W * px_per_mm, H * px_per_mm), QColor(colors["paper"]))
    pt = lambda p: QPointF(p[0] * px_per_mm, (H - p[1]) * px_per_mm)  # noqa: E731

    def pen(layer):
        p = QPen(QColor(colors.get(layer, colors["visible"])))
        p.setWidthF(max(0.6, STD.LINES.get(layer, 0.18) * px_per_mm))
        p.setCapStyle(Qt.RoundCap)
        p.setJoinStyle(Qt.RoundJoin)
        dash = STD.DASH.get(layer)
        if dash:
            p.setDashPattern([d / STD.LINES.get(layer, 0.18) for d in dash])
        return p

    def node(n):
        k = n["kind"]
        if k == "group":
            for c in n["children"]:
                node(c)
            return
        layer = n.get("layer", "visible")
        if k == "line":
            painter.setPen(pen(layer))
            painter.drawLine(pt(n["a"]), pt(n["b"]))
        elif k == "polyline":
            painter.setPen(pen(layer))
            painter.setBrush(Qt.NoBrush)
            poly = QPolygonF([pt(p) for p in n["pts"]])
            (painter.drawPolygon if n.get("closed") else painter.drawPolyline)(poly)
        elif k == "polygon":
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(colors.get(layer, colors["visible"]))))
            painter.drawPolygon(QPolygonF([pt(p) for p in n["pts"]]))
        elif k == "circle":
            painter.setPen(pen(layer))
            painter.setBrush(QBrush(QColor(colors.get(layer))) if n.get("fill") else Qt.NoBrush)
            r = n["r"] * px_per_mm
            painter.drawEllipse(pt(n["c"]), r, r)
        elif k == "arc":
            painter.setPen(pen(layer))
            painter.setBrush(Qt.NoBrush)
            r = n["r"] * px_per_mm
            c = pt(n["c"])
            span = (n["a1"] - n["a0"]) % 360 or 360
            painter.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), int(n["a0"] * 16), int(span * 16))
        elif k == "text":
            f = _font(QFont, QT_FONTS, n["h"] * px_per_mm)
            painter.setFont(f)
            painter.setPen(QColor(colors.get(layer, colors["text"])))
            from PySide6.QtGui import QFontMetricsF
            fm = QFontMetricsF(f)
            w = fm.horizontalAdvance(n["s"])
            ch = fm.capHeight()
            dx = {"start": 0.0, "middle": -w / 2, "end": -w}[n.get("anchor", "middle")]
            dy = {"baseline": 0.0, "middle": ch / 2, "top": ch}[n.get("valign", "baseline")]
            painter.save()
            painter.translate(pt(n["at"]))
            painter.rotate(-n.get("rot", 0.0))
            painter.drawText(QPointF(dx, dy), n["s"])
            painter.restore()

    for c in sheet["children"]:
        node(c)


def do_paint(job):
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
    _app()
    sheet = job["sheet"]
    W, H = sheet["size"]
    out = {}
    if job.get("pdf"):
        w = QPdfWriter(job["pdf"])
        w.setResolution(72)               # PDF points: text is written at its real size, so readers extract it in order
        w.setTitle(sheet.get("title", "Drawing"))
        w.setCreator("Form Studio")
        w.setPageLayout(QPageLayout(QPageSize(QSizeF(W, H), QPageSize.Millimeter), QPageLayout.Portrait,
                                    QMarginsF(0, 0, 0, 0)))
        p = QPainter(w)
        p.setRenderHint(QPainter.Antialiasing)
        paint(p, sheet, 72 / 25.4, H)
        p.end()
        out["pdf"] = job["pdf"]
    if job.get("png") or job.get("crops"):
        ppm = job.get("dpi", 150) / 25.4
        img = QImage(int(math.ceil(W * ppm)), int(math.ceil(H * ppm)), QImage.Format_RGB32)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        paint(p, sheet, ppm, H)
        p.end()
        if job.get("png"):
            img.save(job["png"])
            out["png"] = job["png"]
        out["crops"] = []
        for c in job.get("crops") or []:
            x0, y0, x1, y1 = c["box"]
            q = img.copy(int(x0 * ppm), int((H - y1) * ppm), int((x1 - x0) * ppm), int((y1 - y0) * ppm))
            q.save(c["out"])
            out["crops"].append(c["out"])
    return out


def do_read(job):
    """Text of a PDF with each word's box (page mm, origin lower left), and each page as a PNG."""
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument
    _app()
    doc = QPdfDocument()
    doc.load(job["read_pdf"])
    if doc.status() != QPdfDocument.Status.Ready:
        return {"error": f"could not open the PDF ({doc.status()})"}
    pages = []
    dpi = job.get("dpi", 150)
    for i in range(doc.pageCount()):
        size = doc.pagePointSize(i)                       # points
        wmm, hmm = size.width() * 25.4 / 72, size.height() * 25.4 / 72
        sel = doc.getAllText(i)
        text = sel.text()
        words = []
        j = 0
        import re
        for m in re.finditer(r"\S+", text):
            j = m.start()
            s = doc.getSelectionAtIndex(i, j, m.end() - j)
            r = s.boundingRectangle()
            if r.width() <= 0:
                continue
            x0, x1 = r.left() * 25.4 / 72, r.right() * 25.4 / 72
            y1, y0 = hmm - r.top() * 25.4 / 72, hmm - r.bottom() * 25.4 / 72
            words.append({"s": m.group(0), "box": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]})
        png = None
        if job.get("out_dir"):
            img = doc.render(i, QSize(int(wmm / 25.4 * dpi), int(hmm / 25.4 * dpi)))
            png = f"{job['out_dir']}/page-{i + 1}.png"
            img.save(png)
        pages.append({"page": i + 1, "size_mm": [round(wmm, 3), round(hmm, 3)], "words": words, "png": png})
    return {"pages": pages}


def main():
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    out = do_read(job) if job.get("read_pdf") else do_paint(job)
    sys.stdout.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
