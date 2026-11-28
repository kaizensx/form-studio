"""A reconstructed layout as edits of the design's source: one named feature per pocket, three parameters.

    ops, summary = ops_for(layout, grid, source)

The ops are the edit protocol's own (form/edits.py): `insert param` three times, then `insert feature` once per
pocket, after the design's last feature. So the optimised part is the person's design with features added to it:
every pocket can be suppressed, deleted or reshaped in the tree, and the parameters (rib inset, corner radius, web
thickness) are sliders like any other. Nothing here imports the kernel.
"""
from __future__ import annotations

PREFIX = "topo_pocket_"
P_INSET, P_FILLET, P_WEB = "topo_inset", "topo_fillet", "topo_web"


def _g(x: float) -> str:
    return f"{float(x):.4g}" if abs(float(x)) < 1e4 else repr(float(x))


def _vec(v) -> str:
    return "(" + ", ".join(_g(round(float(c), 6)) for c in v) + ")"


def frame_literal(grid: dict) -> str:
    return ("{" + f'"origin": {_vec(grid.get("origin", (0, 0, 0)))}, "x": {_vec(grid["e1"])}, "z": {_vec(grid["pull"])}, '
            f'"lo": {_g(round(grid["w0"], 4))}, "hi": {_g(round(grid["w1"], 4))}' + "}")


def feature_code(fid: str, label: str, outline: list, grid: dict) -> str:
    rows, line = [], "    outline = ["
    for k, (x, y) in enumerate(outline):
        tok = f"({x:.3f}, {y:.3f})" + ("," if k < len(outline) - 1 else "]")
        if len(line) + len(tok) > 110:
            rows.append(line.rstrip())
            line = "               "
        line += tok + " "
    rows.append(line.rstrip())
    return (f'@feature("{label}", role="structure")\n'
            f"def {fid}(self, v, body):\n"
            f'    """Cut by topology optimisation: material here carried little of the load."""\n'
            f"    from form.topo import cad\n"
            + "\n".join(rows) + "\n"
            f"    frame = {frame_literal(grid)}\n"
            f'    return cad.pocket(body, frame, outline, v["{P_INSET}"], v["{P_FILLET}"], v["{P_WEB}"])\n')


def params(layout: dict, grid: dict, fillet: float, rmin: float) -> list:
    thick = float(grid["w1"] - grid["w0"])
    first = PREFIX + "1"

    def prm(key, label, default, hi, doc):
        return {"key": key, "label": label, "default": round(float(default), 3), "min": 0.0, "max": round(float(hi), 3),
                "step": 0.1, "unit": "mm", "group": "form", "feature": first, "doc": doc, "provenance": "computed"}
    return [prm(P_INSET, "Rib inset", 0.0, max(2.0, 2 * rmin),
                "every lightening pocket's outline moved inward by this much: each rib is wider by twice this"),
            prm(P_FILLET, "Pocket corner radius", fillet, max(2.0, 2 * rmin),
                "the radius of the arc at every corner of the lightening pockets (smaller where two corners are "
                "close); 0 leaves them sharp"),
            prm(P_WEB, "Web thickness", 0.0, round(thick, 3),
                "a floor left under the lightening pockets, measured from the part's low side along the pull "
                "direction; 0 cuts through")]


def already(source: str) -> bool:
    return f"def {PREFIX}" in (source or "") or f'"{P_INSET}"' in (source or "")


def ops_for(layout: dict, grid: dict, fillet: float, rmin: float) -> tuple:
    """(ops, summary) for a layout of recon.pockets."""
    pockets = layout.get("pockets") or []
    ops = [{"op": "insert", "param": p} for p in params(layout, grid, fillet, rmin)]
    for k, pk in enumerate(pockets, 1):
        fid, label = f"{PREFIX}{k}", f"Lightening pocket {k}"
        ops.append({"op": "insert", "feature": fid, "code": feature_code(fid, label, pk["outline"], grid),
                    "label": label, "role": "structure"})
    area = sum(p["area_mm2"] for p in pockets)
    ribs = layout.get("ribs") or {}
    summary = (f"{len(pockets)} lightening pocket{'s' if len(pockets) != 1 else ''} ({area:.0f} mm² in all) along "
               f"{_vec(grid['pull'])}" + (f", {ribs.get('count')} ribs between {ribs.get('width_min_mm')} and "
                                          f"{max((m['width_mm'] for m in ribs.get('members') or [{'width_mm': 0}]), default=0)} mm wide"
                                          if ribs.get("count") else ""))
    return ops, summary
