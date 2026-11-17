"""Plate packing: do these footprints, or N copies of one, fit on the bed?

Rectangles only (each part's bounding box as printed), with a gap between parts and a margin to the
bed edge, each part free to turn 90°. It answers "does it fit" and gives a layout to look at. It is
a computed arrangement, not the slicer's: the slicer arranges again when it slices the plate, and
FORM's export stays one plate.
"""
from __future__ import annotations

DEFAULT_SPACING_MM = 6.0
EPS = 1e-6


def _split(free: list, used: tuple) -> list:
    """MaxRects: cut the used rectangle out of every free rectangle it overlaps, keep the maximal ones."""
    ux, uy, uw, uh = used
    out = []
    for fx, fy, fw, fh in free:
        if ux >= fx + fw - EPS or ux + uw <= fx + EPS or uy >= fy + fh - EPS or uy + uh <= fy + EPS:
            out.append((fx, fy, fw, fh))
            continue
        if ux > fx + EPS:
            out.append((fx, fy, ux - fx, fh))
        if ux + uw < fx + fw - EPS:
            out.append((ux + uw, fy, fx + fw - ux - uw, fh))
        if uy > fy + EPS:
            out.append((fx, fy, fw, uy - fy))
        if uy + uh < fy + fh - EPS:
            out.append((fx, uy + uh, fw, fy + fh - uy - uh))
    keep = []
    for i, a in enumerate(out):
        inside = False
        for j, b in enumerate(out):
            if i != j and a[0] >= b[0] - EPS and a[1] >= b[1] - EPS and a[0] + a[2] <= b[0] + b[2] + EPS \
                    and a[1] + a[3] <= b[1] + b[3] + EPS and (a != b or i > j):
                inside = True
                break
        if not inside:
            keep.append(a)
    return keep


def _maxrects(sizes: list, bw: float, bh: float, rotate: bool, rule: str) -> list:
    """Place rectangles (already inflated by the gap) in a bw × bh area. Returns [(x, y, w, h, rotated) | None]."""
    free = [(0.0, 0.0, bw, bh)]
    placed = [None] * len(sizes)
    order = sorted(range(len(sizes)), key=lambda i: (-max(sizes[i]), -sizes[i][0] * sizes[i][1]))
    for i in order:
        w, h = sizes[i]
        best = None
        for fx, fy, fw, fh in free:
            for rw, rh, rot in ((w, h, False), (h, w, True)) if rotate and abs(w - h) > EPS else ((w, h, False),):
                if rw <= fw + EPS and rh <= fh + EPS:
                    score = (fy + rh, fx) if rule == "bottom-left" else (min(fw - rw, fh - rh), max(fw - rw, fh - rh))
                    if best is None or score < best[0]:
                        best = (score, (fx, fy, rw, rh, rot))
        if best is None:
            continue
        placed[i] = best[1]
        free = _split(free, best[1][:4])
    return placed


def _grid(w: float, h: float, n: int, bw: float, bh: float, rotate: bool) -> list | None:
    """N identical rectangles as rows, optionally with a block of turned ones beside them."""
    best = compact = None
    for rw, rh, rot in ((w, h, False), (h, w, True)) if rotate else ((w, h, False),):
        cols, rows = int((bw + EPS) // rw), int((bh + EPS) // rh)
        cells = [(c * rw, r * rh, rw, rh, rot) for r in range(rows) for c in range(cols)]
        if rotate:                                   # the strip left at the right edge, filled with turned parts
            left = bw - cols * rw
            c2, r2 = int((left + EPS) // rh), int((bh + EPS) // rw)
            cells += [(cols * rw + c * rh, r * rw, rh, rw, not rot) for r in range(r2) for c in range(c2)]
        if best is None or len(cells) > len(best):
            best = cells
        # a compact block of plain rows when that is enough: as square as it can be
        for c in range(1, cols + 1):
            r = -(-n // c)
            if r <= rows:
                block = [(i % c * rw, i // c * rh, rw, rh, rot) for i in range(n)]
                if compact is None or _extent(block) < _extent(compact):
                    compact = block
    if compact:
        return compact
    return best[:n] if best and len(best) >= n else None


def _extent(cells) -> float:
    done = [x for x in cells if x]
    return max(max(x + w for x, _, w, _, _ in done), max(y + h for _, y, _, h, _ in done)) if done else 0.0


def pack(parts: list, bed: tuple, spacing: float = DEFAULT_SPACING_MM, margin: float = 0.0, rotate: bool = True) -> dict:
    """Arrange `parts` ([{"id", "w", "h"}], millimetres) on a bed (width, depth).

    Returns {"fits", "placed": [{"id", "x", "y", "w", "h", "rotated"}], "unplaced": [ids], ...}; x, y are the
    lower-left corner of the part itself (not its gap) in bed coordinates, the layout centred on the bed."""
    bed_w, bed_h = float(bed[0]), float(bed[1])
    spacing, margin = max(0.0, float(spacing)), max(0.0, float(margin))
    aw, ah = bed_w - 2 * margin + spacing, bed_h - 2 * margin + spacing       # usable area, in inflated units
    sizes = [(float(p["w"]) + spacing, float(p["h"]) + spacing) for p in parts]
    candidates = []
    if aw > 0 and ah > 0 and parts:
        for rule in ("short-side", "bottom-left"):
            candidates.append(_maxrects(sizes, aw, ah, rotate, rule))
        if len({(round(w, 4), round(h, 4)) for w, h in sizes}) == 1:
            g = _grid(sizes[0][0], sizes[0][1], len(sizes), aw, ah, rotate)
            if g:
                candidates.append(list(g))
    best = max(candidates, key=lambda c: (sum(1 for x in c if x), -_extent(c)), default=[None] * len(parts))
    done = [x for x in best if x]
    # centre what was placed
    if done:
        x1 = max(x + w for x, _, w, _, _ in done) - spacing
        y1 = max(y + h for _, y, _, h, _ in done) - spacing
        ox, oy = (bed_w - x1) / 2, (bed_h - y1) / 2
    else:
        x1 = y1 = ox = oy = 0.0
    placed, unplaced = [], []
    for p, x in zip(parts, best):
        if not x:
            unplaced.append(p["id"])
            continue
        placed.append({"id": p["id"], "x": round(ox + x[0], 2), "y": round(oy + x[1], 2),
                       "w": round(x[2] - spacing, 2), "h": round(x[3] - spacing, 2), "rotated": bool(x[4])})
    return {"fits": not unplaced and bool(parts), "placed": placed, "unplaced": unplaced,
            "bed_mm": [bed_w, bed_h], "spacing_mm": spacing, "margin_mm": margin,
            "used_mm": [round(x1, 2), round(y1, 2)], "rotation": "90° turns allowed" if rotate else "no rotation",
            "evidence": "computed",
            "note": "Bounding boxes on one plate, computed by Form Studio. The slicer arranges again when it slices; "
                    "Form Studio's export stays one part per plate."}


def copies(w: float, h: float, n: int, bed: tuple, spacing: float = DEFAULT_SPACING_MM, margin: float = 0.0,
           rotate: bool = True) -> dict:
    """N copies of one w × h footprint. Adds "copies", "max_copies" (how many would fit at most)."""
    n = max(1, int(n))
    out = pack([{"id": f"copy {i + 1}", "w": w, "h": h} for i in range(n)], bed, spacing, margin, rotate)
    out["copies"] = n
    out["footprint_mm"] = [round(float(w), 2), round(float(h), 2)]
    out["max_copies"] = max_copies(w, h, bed, spacing, margin, rotate, at_least=len(out["placed"]))
    return out


def max_copies(w: float, h: float, bed: tuple, spacing: float = DEFAULT_SPACING_MM, margin: float = 0.0,
               rotate: bool = True, at_least: int = 0, cap: int = 400) -> int:
    """The largest N this packer can place (a lower bound on what fits; a cleverer arrangement may fit more)."""
    aw, ah = bed[0] - 2 * margin + spacing, bed[1] - 2 * margin + spacing
    sw, sh = w + spacing, h + spacing
    if aw <= 0 or ah <= 0 or sw <= 0 or sh <= 0:
        return 0
    upper = min(cap, int((aw * ah) // (sw * sh)))
    best = at_least
    for n in range(max(1, at_least + 1), upper + 1):
        g = _grid(sw, sh, n, aw, ah, rotate)
        if g:
            best = n
            continue
        got = sum(1 for x in _maxrects([(sw, sh)] * n, aw, ah, rotate, "short-side") if x)
        if got >= n:
            best = n
        else:
            break
    return best


# ---- a project ----------------------------------------------------------------------------------
def bed_for(st, tp=None) -> tuple[list, str]:
    """Bed width and depth: the selected printer preset, else what the G-code states, else studio.toml."""
    s = st.slicer_info()
    if s.get("envelope_mm"):
        return [float(s["envelope_mm"][0]), float(s["envelope_mm"][1])], f"printer preset in {s.get('label') or 'the slicer'}"
    if tp is not None:
        from .toolpath import bed_from_settings
        b = bed_from_settings(tp.settings)
        if b:
            return [b[2] - b[0], b[3] - b[1]], "printable area in the G-code"
    e = st.cfg["printer"]["envelope_mm"]
    return [float(e[0]), float(e[1])], "[printer].envelope_mm in studio.toml"


def footprints(st, p: dict) -> tuple[list, str]:
    """What goes on the plate once: every printed part's bounding box, and where the numbers come from."""
    from . import toolpath
    from .studio import StudioError
    v = st.view(p)
    asm = v.get("assembly") if isinstance(v.get("assembly"), dict) and not v["assembly"].get("error") else None
    if asm and len(asm.get("parts", [])) > 1:
        parts = [{"id": x.get("label") or x["id"], "w": x["bbox"][1][0] - x["bbox"][0][0], "h": x["bbox"][1][1] - x["bbox"][0][1]}
                 for x in asm["parts"]]
        return parts, "each part's bounding box as printed (computed from the solid)"
    try:
        tp = toolpath.for_project(st, p)
        b = tp.bbox
        return [{"id": p["name"], "w": b[1][0] - b[0][0], "h": b[1][1] - b[0][1]}], \
            "extent of the sliced toolpaths (includes any brim or skirt the slicer added)"
    except StudioError:
        b = v["bbox"]
        return [{"id": p["name"], "w": b[1][0] - b[0][0], "h": b[1][1] - b[0][1]}], \
            "bounding box of the solid as modelled (no current slice; a brim or another orientation changes it)"


def project(st, p: dict, n: int = 1, spacing: float | None = None, rotate: bool = True) -> dict:
    """Do `n` copies of this design (all of its printed parts) fit on one plate?"""
    from . import toolpath
    from .studio import StudioError
    n = max(1, int(n))
    spacing = DEFAULT_SPACING_MM if spacing is None else float(spacing)
    parts, source = footprints(st, p)
    try:
        tp = toolpath.for_project(st, p)
    except StudioError:
        tp = None
    bed, bed_source = bed_for(st, tp)
    margin = float(st.cfg["printer"].get("plate_margin_mm", 0) or 0)
    if len(parts) == 1:
        out = copies(parts[0]["w"], parts[0]["h"], n, bed, spacing, margin, rotate)
    else:
        every = [{"id": f"{x['id']} · {i + 1}" if n > 1 else x["id"], "w": x["w"], "h": x["h"]} for i in range(n) for x in parts]
        out = pack(every, bed, spacing, margin, rotate)
        out["copies"] = n
    out |= {"project": p["id"], "rev": p["head"], "parts_per_copy": len(parts), "footprint_source": source,
            "bed_source": bed_source,
            "summary": (f"{n} {'copy fits' if n == 1 else 'copies fit'}" if out["fits"] else
                        f"{n} {'copy does' if n == 1 else 'copies do'} not fit: {len(out['placed'])} of {len(out['placed']) + len(out['unplaced'])} "
                        f"{'parts' if len(parts) > 1 else 'copies'} placed")
                       + f" on the {bed[0]:g} × {bed[1]:g} mm plate with {spacing:g} mm between parts."}
    return out
