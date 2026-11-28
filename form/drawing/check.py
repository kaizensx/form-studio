"""Check a person's drawing against the part: one row per dimension, expected against the model, PASS or FAIL,
or UNSURE when the number could not be read with certainty. Never a summary verdict.

    from form.drawing import check
    out = check.run(st, p, "their_drawing.pdf")                  # a PDF with a text layer is read exactly
    out = check.run(st, p, "photo_of_print.png", rows=[...])     # anything else: the agent reads, each row located

Where each number comes from (the row's "read"):

- "dxf dimension": a DXF DIMENSION entity's measurement (exact); "dxf text": a DXF TEXT/MTEXT that is a dimension.
- "pdf text": a PDF's own text layer, with the word's box on the page (exact text, no OCR).
- "agent": a row the agent read off the page image (read_document) and gave with its box. The agent's own
  "unsure" is kept; a row without a box, or whose value does not parse, is UNSURE. Form Studio runs no OCR of its
  own, so an image without the agent's rows reads nothing, and says so.

The verdict is Form Studio's, not the reader's: the expected size with its tolerance (an ISO 286 class, a written
+-, else the general tolerance the sheet states, else ISO 2768-m, marked assumed) against the size measured on the
B-rep. Each row carries a crop of the sheet where the number is printed and the part rendered with the measured
feature lit.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

NUM = r"[+\-−]?\d*[.,]?\d+"
DIM = re.compile(
    rf"^(?:(?P<n>\d+)\s*[×xX]\s*)?(?P<sym>[ØR⌀]|M)?\s*(?P<v>\d+(?:[.,]\d+)?)"
    rf"(?:\s*(?P<cls>[A-Z]{{1,2}}\d{{1,2}}|[a-z]{{1,2}}\d{{1,2}}))?"
    rf"(?:\s*\(\s*(?P<up>{NUM})\s*/\s*(?P<lo>{NUM})\s*\))?"
    rf"(?:\s*±\s*(?P<pm>\d*[.,]?\d+))?$")
GENERAL = re.compile(r"ISO\s*2768\s*[-‑–]?\s*([fmcv])([HKL])?", re.I)


def _f(x: str) -> float:
    return float(x.replace(",", ".").replace("−", "-"))


def parse(text: str) -> dict | None:
    """A dimension's text as data: kind, value, count, class or limits. None when it is not a dimension."""
    t = text.strip().replace("⌀", "Ø")
    m = DIM.match(t)
    if not m or m.group("sym") == "M":
        return None
    out = {"text": t, "value": _f(m.group("v")), "count": int(m.group("n") or 1),
           "kind": {"Ø": "diameter", "R": "radius"}.get(m.group("sym") or "", "linear")}
    if m.group("cls"):
        out["class"] = m.group("cls")
    if m.group("up") is not None:
        out["upper"], out["lower"] = _f(m.group("up")), _f(m.group("lo"))
    if m.group("pm"):
        out["upper"], out["lower"] = _f(m.group("pm")), -_f(m.group("pm"))
    return out


def _lines(words: list) -> list:
    """Words grouped into the strings a reader sees: same baseline (or same column, for rotated text), close."""
    ws = sorted(words, key=lambda w: (-round(w["box"][1], 0), w["box"][0]))
    lines = []
    def tall(w):
        return (w["box"][3] - w["box"][1]) > 1.5 * (w["box"][2] - w["box"][0]) and len(w["s"]) > 1

    for w in ws:
        h = max(w["box"][3] - w["box"][1], 0.5)
        for ln in lines:
            last = ln[-1]
            if tall(w) or tall(last):          # a piece of turned text: joined by columns below
                continue
            h = min(h, max(last["box"][3] - last["box"][1], 0.5))
            same_row = abs(last["box"][1] - w["box"][1]) < 0.35 * h and 0 <= w["box"][0] - last["box"][2] < 1.2 * h
            if same_row:
                ln.append(w)
                break
        else:
            lines.append([w])
    out = []
    for ln in lines:
        box = [min(w["box"][0] for w in ln), min(w["box"][1] for w in ln), max(w["box"][2] for w in ln),
               max(w["box"][3] for w in ln)]
        out.append({"s": " ".join(w["s"] for w in ln), "box": box})
    # text turned 90 degrees (vertical dimensions) comes out one short piece per line, stacked in a column:
    # join the pieces of a column, read from the bottom up
    def piece(o):
        b = o["box"]
        return len(o["s"]) <= 2 or (b[3] - b[1]) > 1.5 * (b[2] - b[0])
    short = [o for o in out if piece(o)]
    rest = [o for o in out if not piece(o)]
    used = set()
    for i, a in enumerate(sorted(short, key=lambda o: (o["box"][0], o["box"][1]))):
        if id(a) in used:
            continue
        col = [a]
        used.add(id(a))
        changed = True
        while changed:
            changed = False
            for b in short:
                if id(b) in used:
                    continue
                top = max(c["box"][3] for c in col)
                bot = min(c["box"][1] for c in col)
                x0 = min(c["box"][0] for c in col)
                x1 = max(c["box"][2] for c in col)
                w = max(x1 - x0, 0.5)
                bc = (b["box"][0] + b["box"][2]) / 2
                inside = x0 - 0.15 * w <= bc <= x1 + 0.15 * w and b["box"][2] - b["box"][0] < 1.6 * w
                if inside and (-0.2 * w <= b["box"][1] - top < 0.8 * w or -0.2 * w <= bot - b["box"][3] < 0.8 * w):
                    col.append(b)
                    used.add(id(b))
                    changed = True
        col.sort(key=lambda c: c["box"][1])
        box = [min(c["box"][0] for c in col), min(c["box"][1] for c in col), max(c["box"][2] for c in col),
               max(c["box"][3] for c in col)]
        rest.append({"s": "".join(c["s"] for c in col), "box": box, "rotated": len(col) > 1})
    return rest


# ── reading ────────────────────────────────────────────────────────────────

def read_pdf(path: str, out_dir: Path) -> dict:
    import os
    import subprocess
    import sys
    import tempfile
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"read_pdf": str(path), "dpi": 200, "out_dir": str(out_dir)}, fh)
        job = fh.name
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        r = subprocess.run([sys.executable, "-m", "form.drawing.qtpaint", job], env=env, capture_output=True, text=True,
                           timeout=180)
    finally:
        os.unlink(job)
    if r.returncode != 0:
        raise RuntimeError("could not read the PDF: " + (r.stderr or "")[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def read_dxf(path: str) -> list:
    import ezdxf
    doc = ezdxf.readfile(path)
    rows = []
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "DIMENSION":
            try:
                v = float(e.get_measurement())
            except Exception:  # noqa: BLE001
                continue
            dt = e.dimtype & 7
            kind = {3: "diameter", 4: "radius"}.get(dt, "linear")
            txt = e.dxf.get("text", "") or ""
            p = parse(txt.replace("<>", f"{v:g}")) if txt and txt != "<>" else None
            row = {"text": txt or f"{v:g}", "value": round(v, 6), "kind": kind, "count": 1, "read": "dxf dimension"}
            if p:
                row.update({k: p[k] for k in ("class", "upper", "lower", "count") if k in p})
            rows.append(row)
        elif t in ("TEXT", "MTEXT"):
            s = e.dxf.text if t == "TEXT" else e.plain_text()
            p = parse(s)
            if p:
                ins = e.dxf.insert
                h = float(e.dxf.get("height", 2.5) or 2.5) if t == "TEXT" else float(e.dxf.get("char_height", 2.5))
                p.update(read="dxf text", box=[ins[0] - h, ins[1] - h, ins[0] + h * len(s) * 0.8, ins[1] + h * 1.5])
                rows.append(p)
    return rows


def rows_from_pdf(info: dict) -> tuple[list, str | None, list]:
    rows, general, pages = [], None, []
    for pg in info.get("pages", []):
        pages.append(pg)
        text = " ".join(w["s"] for w in pg["words"])
        g = GENERAL.search(text)
        if g and general is None:
            general = g.group(1).lower()
        for ln in _lines(pg["words"]):
            p = parse(ln["s"])
            if p:
                p.update(read="pdf text", page=pg["page"], box=ln["box"])
                rows.append(p)
    return rows, general, pages


def rows_from_agent(rows: list) -> list:
    out = []
    for r in rows or []:
        txt = str(r.get("text") or r.get("value") or "")
        p = parse(txt) if txt else None
        row = {"text": txt, "read": "agent", "page": int(r.get("page", 1)), "box_frac": r.get("box"),
               "agent_unsure": bool(r.get("unsure"))}
        if p is None:
            row.update(value=None, kind=r.get("kind", "linear"), count=1, unparsed=True)
        else:
            row.update(p)
        out.append(row)
    return out


# ── judging ────────────────────────────────────────────────────────────────

def tolerance(row: dict, general: str | None) -> dict:
    from .. import iso286
    from . import standards as STD
    v = row["value"]
    if row.get("class"):
        try:
            lim = iso286.limits(row["class"], v)
            return {"lower": lim["min"] - v, "upper": lim["max"] - v, "from": f"ISO 286 {lim['class']}",
                    "assumed": False}
        except iso286.FitError as e:
            return {"lower": 0.0, "upper": 0.0, "from": f"{row['class']} not computed: {e}", "assumed": True,
                    "unsure": True}
    if row.get("upper") is not None:
        return {"lower": row["lower"], "upper": row["upper"], "from": "written on the sheet", "assumed": False}
    cls = general or "m"
    try:
        t = STD.general_break(v, cls) if row["kind"] == "radius" else STD.general_linear(v, cls)
    except STD.StandardError as e:
        return {"lower": 0.0, "upper": 0.0, "from": str(e), "assumed": True, "unsure": True}
    return {"lower": -t, "upper": t, "from": f"ISO 2768-{cls}" + ("" if general else " (assumed: the sheet states none)"),
            "assumed": general is None}


def judge(rows: list, cands: list, general: str | None) -> list:
    pool = {"diameter": ("diameter",), "radius": ("radius",),
            "linear": ("linear", "pitch", "location", "diameter")}
    out = []
    for i, r in enumerate(rows):
        res = {"n": i + 1, "text": r.get("text"), "read": r["read"], "page": r.get("page", 1), "box": r.get("box"),
               "box_frac": r.get("box_frac"), "expected": r.get("value"), "kind": r.get("kind"),
               "count": r.get("count", 1)}
        why_unsure = None
        if r.get("unparsed") or r.get("value") is None:
            why_unsure = "the text does not read as a dimension"
        elif r.get("agent_unsure"):
            why_unsure = "the reader marked it unsure"
        elif r["read"] == "agent" and not r.get("box_frac"):
            why_unsure = "the reader gave no place on the sheet for it"
        if why_unsure:
            res.update(status="UNSURE", why=why_unsure, model=None)
            out.append(res)
            continue
        v = r["value"]
        if v < 0.5:
            res.update(status="UNSURE", why="below 0.5 mm: likely a tolerance value in a frame, not a size", model=None)
            out.append(res)
            continue
        tol = tolerance(r, general)
        res["tolerance"] = tol
        kinds = pool[r["kind"]]
        cs = [c for c in cands if c["kind"] in kinds]
        if r["kind"] == "linear":     # a plain number may be a boss measured across: diameters last
            cs = sorted(cs, key=lambda c: c["kind"] == "diameter")
        if not cs:
            res.update(status="FAIL", why=f"the part has no {r['kind']} size", model=None)
            out.append(res)
            continue
        best = min(cs, key=lambda c: (abs(c["value"] - v), c["kind"] == "diameter" and r["kind"] == "linear"))
        lo, hi = v + tol["lower"], v + tol["upper"]
        ok = lo - 1e-9 <= best["value"] <= hi + 1e-9
        res.update(model=best["value"], candidate=best["id"], features=best.get("features", []),
                   faces=best.get("faces", []), limits=[round(lo, 4), round(hi, 4)],
                   deviation=round(best["value"] - v, 4))
        if v < 0.5 and r["kind"] == "linear":
            res.update(status="UNSURE", why="below 0.5 mm: likely a tolerance value, not a size")
        elif tol.get("unsure"):
            res.update(status="UNSURE", why=tol["from"])
        elif not ok:
            res.update(status="FAIL", why=f"the part measures {best['value']:g} mm, outside {lo:g} to {hi:g}")
        elif r.get("count", 1) > 1 and best.get("count", 1) != r["count"]:
            res.update(status="FAIL", why=f"the sheet says {r['count']}×, the part has {best.get('count', 1)}")
        else:
            res.update(status="PASS", why="")
        out.append(res)
    return out


# ── the whole check ────────────────────────────────────────────────────────

def run(st, p: dict, source: str, rows: list | None = None, n: int | None = None) -> dict:
    """Check `source` (PDF, DXF or image) against revision n of the design. rows: what the agent read, for images
    or scans: [{"text": "Ø8 H7", "box": [x0, y0, x1, y1] as page fractions from the top left, "page": 1,
    "unsure": False}]."""
    from ..studio import H
    from . import dims as D
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"no file {src}")
    r = st.rev(p, n)
    gk = st.keys(p, r["n"])["geometry"]
    key = H("drawing-check", 1, gk, src.read_bytes(), rows)[:16]
    out_dir = st.dir(p["id"]) / "artifacts" / "side" / f"drawing-check-{key}"
    meta = out_dir / "check.json"
    if meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    general, pages, note = None, [], ""
    if ext == ".dxf":
        read = read_dxf(str(src))
        for e in read:
            e["page"] = 1
    elif ext == ".pdf":
        info = read_pdf(str(src), out_dir)
        if info.get("error"):
            raise RuntimeError(info["error"])
        read, general, pages = rows_from_pdf(info)
        if not read and not rows:
            note = ("This PDF has no text layer to read the dimensions from. Read the page with read_document and "
                    "give each dimension as a row with its place on the sheet.")
    elif ext in (".png", ".jpg", ".jpeg", ".webp"):
        read = []
        pages = [{"page": 1, "png": str(src)}]
        if not rows:
            note = ("An image has no text Form Studio can read without OCR, and it runs none. Read it with "
                    "read_document and give each dimension as a row with its place on the sheet.")
    else:
        raise ValueError("check a PDF, DXF, PNG, JPEG or WebP drawing")
    read += rows_from_agent(rows)
    if not pages and ext == ".pdf":
        pages = []
    raw = st._k("drawing_views", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"],
                views=[], sections=[], perturb=None)
    cands = D.candidates(raw["measure"])
    results = judge(read, cands, general)
    _crops(results, pages, out_dir)
    _lights(st, p, r, results, out_dir)
    for x in results:
        x.pop("faces", None)
    counts = {k: sum(x["status"] == k for x in results) for k in ("PASS", "FAIL", "UNSURE")}
    res = {"source": str(src), "rev": r["n"], "rows": results, "counts": counts, "general_tolerance": general,
           "note": note, "dir": str(out_dir), "geometry": gk}
    meta.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _crops(results, pages, out_dir: Path):
    from PIL import Image
    by = {pg["page"]: pg for pg in pages}
    for x in results:
        pg = by.get(x.get("page", 1))
        if not pg or not pg.get("png"):
            continue
        try:
            img = Image.open(pg["png"])
        except OSError:
            continue
        W, Hh = img.size
        if x.get("box") and pg.get("size_mm"):
            wmm, hmm = pg["size_mm"]
            b = x["box"]
            pad = 6.0
            box = (int((b[0] - pad) / wmm * W), int((hmm - b[3] - pad) / hmm * Hh), int((b[2] + pad) / wmm * W),
                   int((hmm - b[1] + pad) / hmm * Hh))
        elif x.get("box_frac"):
            f = x["box_frac"]
            px, py = 0.02 * W, 0.02 * Hh
            box = (int(f[0] * W - px), int(f[1] * Hh - py), int(f[2] * W + px), int(f[3] * Hh + py))
        else:
            continue
        box = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(Hh, box[3]))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            continue
        f = out_dir / f"crop-{x['n']:03d}.png"
        img.crop(box).save(f)
        x["crop"] = str(f)


def _lights(st, p, r, results, out_dir: Path):
    """The part with the measured feature lit, one picture per feature (shared by the rows that measured it)."""
    from .. import render as rendering
    feats = [{"id": f.id, "label": f.label} for f in st.recipe(p, r["n"]).features]
    ids = {f["id"] for f in feats}
    v = None
    done = {}
    for x in results:
        fs = [f for f in x.get("features") or [] if f in ids]
        if not fs:
            continue
        f = fs[0]
        if f not in done:
            if v is None:
                v = st.view(p, r["n"])
            path = out_dir / f"lit-{f}.png"
            path.write_bytes(rendering.render_png(v, feats, "iso", f, size=(640, 460), title=f"{p['name']} · {f}"))
            done[f] = str(path)
        x["lit"] = done[f]
        x["feature"] = f
