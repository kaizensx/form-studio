"""The sliced toolpaths as arrays: what the print simulation draws, scrubs and times.

Everything here comes from the slicer's G-code (parsed by form/adapters). Nothing is invented:

- geometry: every extruding move, with its layer and the slicer's feature type;
- time: the slicer's total estimate, placed along the path by its own "M73 R<minutes>" remaining-time
  markers when the file has them (time_source "slicer markers": whole-minute steps, spread by extrusion
  length between two markers), otherwise spread over the whole print by extrusion length
  (time_source "interpolated"). Either way the layer times add up to the slicer's total.

A simulation of a slice is still a simulation. It is not a print.
"""
from __future__ import annotations

import base64
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Drawing order and the two groups the "jump to" buttons look for. Names are Bambu Studio / OrcaSlicer's;
# PrusaSlicer's are mapped onto them by its adapter.
BRIDGE_TYPES = ("Bridge",)
OVERHANG_TYPES = ("Overhang wall", "Floating vertical shell")
TYPE_ORDER = ["Outer wall", "Inner wall", "Overhang wall", "Floating vertical shell", "Bridge", "Top surface",
              "Bottom surface", "Internal solid infill", "Sparse infill", "Gap infill", "Support", "Support interface",
              "Skirt", "Brim", "Prime tower", "Custom"]


@dataclass
class Toolpath:
    types: list                    # feature type names, index = seg_type value
    seg: np.ndarray                # (N, 4) float32: x0, y0, x1, y1 of every extruding move, in plate millimetres
    seg_type: np.ndarray           # (N,) uint8
    seg_len: np.ndarray            # (N,) float32, millimetres
    start: np.ndarray              # (L + 1,) int32: layer l is seg[start[l]:start[l + 1]]
    z: np.ndarray                  # (L,) float32: top of each layer
    h: np.ndarray                  # (L,) float32: layer height
    length: np.ndarray             # (L,) float64: extrusion path length per layer, mm
    time: np.ndarray               # (L,) float64: seconds per layer
    t0: np.ndarray                 # (L + 1,) float64: seconds elapsed at the start of each layer
    total_time_s: float | None
    time_source: str               # "slicer markers" | "interpolated" | "unknown"
    width: float                   # extrusion width used for drawing, mm
    width_source: str
    bbox: list                     # [[x0, y0, 0], [x1, y1, zmax]]
    settings: dict = field(default_factory=dict)
    _cum: np.ndarray | None = None     # (N,) cumulative length inside the layer, at the end of each move

    @property
    def layers(self) -> int:
        return len(self.z)

    def progress_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """For every move: progress at its start and end, where progress = layer index + fraction of the layer done."""
        n = len(self.seg)
        layer = np.repeat(np.arange(self.layers), np.diff(self.start))
        ll = np.maximum(self.length[layer], 1e-9)
        p1 = layer + np.minimum(self._cum / ll, 1.0)
        p0 = layer + np.maximum(self._cum - self.seg_len, 0.0) / ll
        return p0.astype(np.float32)[:n], p1.astype(np.float32)[:n]

    def at(self, progress: float) -> dict:
        """Where the nozzle is at `progress` (layer + fraction): position, feature type, slicer time."""
        if not self.layers:
            return {}
        progress = min(max(float(progress), 0.0), self.layers - 1e-6)
        l = int(progress)
        f = progress - l
        a, b = int(self.start[l]), int(self.start[l + 1])
        want = f * float(self.length[l])
        i = min(a + int(np.searchsorted(self._cum[a:b], want, side="left")), b - 1)
        sl = float(self.seg_len[i]) or 1.0
        t = min(max((want - (float(self._cum[i]) - float(self.seg_len[i]))) / sl, 0.0), 1.0)
        x0, y0, x1, y1 = (float(v) for v in self.seg[i])
        el = float(self.t0[l] + f * self.time[l]) if self.total_time_s else None
        return {"layer": l, "fraction": round(f, 4), "x": round(x0 + (x1 - x0) * t, 3), "y": round(y0 + (y1 - y0) * t, 3),
                "z": round(float(self.z[l]), 3), "type": self.types[int(self.seg_type[i])],
                "elapsed_s": None if el is None else round(el, 1),
                "remaining_s": None if el is None else round(self.total_time_s - el, 1)}

    def progress_at_time(self, seconds: float) -> float:
        if not self.total_time_s:
            return 0.0
        s = min(max(float(seconds), 0.0), self.total_time_s)
        l = min(int(np.searchsorted(self.t0, s, side="right")) - 1, self.layers - 1)
        return l + (min((s - self.t0[l]) / self.time[l], 1.0) if self.time[l] > 0 else 0.0)

    def layer_types(self, l: int) -> list:
        a, b = int(self.start[l]), int(self.start[l + 1])
        return [self.types[i] for i in np.unique(self.seg_type[a:b])]

    def layers_with(self, names) -> list:
        """Indices of the layers that contain any of these feature types."""
        idx = [self.types.index(n) for n in names if n in self.types]
        if not idx:
            return []
        layer = np.repeat(np.arange(self.layers), np.diff(self.start))
        return sorted(int(v) for v in np.unique(layer[np.isin(self.seg_type, idx)]))

    def type_lengths(self) -> dict:
        return {t: round(float(self.seg_len[self.seg_type == i].sum()), 1) for i, t in enumerate(self.types)}

    def summary(self) -> dict:
        """Per-layer numbers for charts and agents (no geometry)."""
        timed = self.total_time_s is not None
        return {
            "layers": self.layers, "segments": int(len(self.seg)), "types": self.types,
            "z": [round(float(v), 3) for v in self.z], "height": [round(float(v), 3) for v in self.h],
            "length_mm": [round(float(v), 1) for v in self.length],
            "time_s": [round(float(v), 2) for v in self.time] if timed else None,
            "t0_s": [round(float(v), 2) for v in self.t0] if timed else None,
            "total_time_s": self.total_time_s, "time_source": self.time_source,
            "time_note": TIME_NOTES[self.time_source],
            "bridge_layers": self.layers_with(BRIDGE_TYPES), "overhang_layers": self.layers_with(OVERHANG_TYPES),
            "type_length_mm": self.type_lengths(), "total_length_mm": round(float(self.length.sum()), 1),
            "width_mm": self.width, "width_source": self.width_source, "bbox": self.bbox,
            "evidence": "simulated", "note": "Simulated from the slicer's G-code. Not a print.",
        }

    def public(self) -> dict:
        """summary() plus the packed geometry the app draws (base64 little-endian arrays)."""
        out = self.summary()
        out["start"] = [int(v) for v in self.start]
        out["seg"] = _b64(self.seg.astype("<f4"))
        out["seg_type"] = _b64(self.seg_type.astype("u1"))
        return out


TIME_NOTES = {
    "slicer markers": "Time is the slicer's estimate, placed by its own remaining-time markers (M73, whole minutes) "
                      "and spread by extrusion length between two markers and within a layer. Start-up time counts toward the first layer.",
    "interpolated": "Interpolated: the slicer's total time, spread over the path by extrusion length. "
                    "The G-code has no per-layer time markers.",
    "unknown": "The slicer did not report a print time for this G-code.",
}


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def order_types(found) -> list:
    known = [t for t in TYPE_ORDER if t in found]
    return known + sorted(t for t in found if t not in TYPE_ORDER)


def time_curve(marks: list, total_len: float, total_time: float) -> tuple[np.ndarray, np.ndarray, str]:
    """Breakpoints (path length, seconds elapsed) from 0 to the end.

    marks: [(path length so far, minutes remaining)] in file order. Only the moments where the slicer's
    counter drops are used (that is when "R minutes remain" is closest to true), and only if they keep
    both axes increasing."""
    xs, ts, last_r = [0.0], [0.0], None
    for s, r in marks:
        if last_r is not None and r < last_r:
            el = total_time - r * 60.0
            if xs[-1] < s < total_len and ts[-1] < el < total_time:
                xs.append(float(s))
                ts.append(float(el))
        last_r = r if last_r is None else min(last_r, r)
    source = "slicer markers" if len(xs) > 1 else "interpolated"
    return np.array(xs + [total_len]), np.array(ts + [total_time]), source


def build(layers: list, total_time_s: float | None = None, width: float | None = None, width_source: str = "",
          settings: dict | None = None) -> Toolpath:
    """Pack the adapter's parse_layers() result ([{z, paths: [{t, p: [x, y, ...]}], marks?}]) into arrays."""
    types = order_types({p["t"] or "Unlabelled" for l in layers for p in l["paths"]})
    tix = {t: i for i, t in enumerate(types)}
    segs, kinds, start, cums, lens, marks = [], [], [0], [], [], []
    done = 0.0                                              # path length of the layers before this one
    n = 0
    for l in layers:
        layer_cum = 0.0
        path_s0, path_cum = [], []                          # per path: length before it, cumulative length per point
        for p in l["paths"]:
            pts = np.asarray(p["p"], dtype=np.float64).reshape(-1, 2)
            d = np.hypot(*(pts[1:] - pts[:-1]).T)
            segs.append(np.hstack([pts[:-1], pts[1:]]))
            kinds.append(np.full(len(d), tix[p["t"] or "Unlabelled"], dtype=np.uint8))
            c = np.concatenate([[0.0], np.cumsum(d)])
            cums.append(layer_cum + c[1:])
            path_s0.append(layer_cum)
            path_cum.append(c)
            layer_cum += float(c[-1])
            n += len(d)
        for pi, npts, r in l.get("marks", []):
            if pi < len(path_cum):
                s = path_s0[pi] + float(path_cum[pi][min(max(npts - 1, 0), len(path_cum[pi]) - 1)])
            else:
                s = layer_cum
            marks.append((done + s, int(r)))
        lens.append(layer_cum)
        done += layer_cum
        start.append(n)
    seg = np.vstack(segs).astype(np.float32) if segs else np.zeros((0, 4), np.float32)
    seg_type = np.concatenate(kinds) if kinds else np.zeros(0, np.uint8)
    cum = np.concatenate(cums) if cums else np.zeros(0)
    seg_len = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]).astype(np.float32) if len(seg) else np.zeros(0, np.float32)
    length = np.array(lens, dtype=np.float64)
    z = np.array([l["z"] for l in layers], dtype=np.float32)
    h = np.diff(np.concatenate([[0.0], z])).astype(np.float32) if len(z) else z
    ok = h[(h > 0.03) & (h < 1.5)]
    typical = float(np.median(ok)) if len(ok) else 0.2
    h = np.where((h > 0.03) & (h < 1.5), h, typical).astype(np.float32)

    L = len(layers)
    if total_time_s and total_time_s > 0 and done > 0:
        xs, ts, source = time_curve(marks, done, float(total_time_s))
        ends = np.interp(np.concatenate([[0.0], np.cumsum(length)]), xs, ts)
        ends[-1] = float(total_time_s)
        t0, time = ends, np.diff(ends)
        total = float(total_time_s)
    else:
        t0, time, source, total = np.zeros(L + 1), np.zeros(L), "unknown", None
    if not width:
        width, width_source = 0.45, "assumed 0.45 mm (the G-code does not state a line width)"
    if len(seg):
        bbox = [[float(min(seg[:, 0].min(), seg[:, 2].min())), float(min(seg[:, 1].min(), seg[:, 3].min())), 0.0],
                [float(max(seg[:, 0].max(), seg[:, 2].max())), float(max(seg[:, 1].max(), seg[:, 3].max())), float(z.max())]]
    else:
        bbox = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return Toolpath(types=types, seg=seg, seg_type=seg_type, seg_len=seg_len, start=np.array(start, dtype=np.int32),
                    z=z, h=h, length=length, time=time, t0=t0, total_time_s=total, time_source=source,
                    width=float(width), width_source=width_source, bbox=bbox, settings=settings or {}, _cum=cum)


# ---- the slicer's own settings, as written into the G-code ---------------------------------------
SETTING_KEYS = ("line_width", "outer_wall_line_width", "extrusion_width", "external_perimeter_extrusion_width",
                "nozzle_diameter", "layer_height", "filament_density", "filament_diameter", "filament_cost",
                "filament_type", "filament_settings_id", "printable_area", "bed_shape", "printable_height",
                "max_print_height")


def gcode_settings(path: Path, head_lines: int = 1500, tail_bytes: int = 400_000) -> dict:
    """`; key = value` comment lines from the config block (start of the file for Bambu Studio, end for PrusaSlicer)."""
    lines = []
    with open(path, "rb") as f:
        for i, raw in enumerate(f):
            if i >= head_lines:
                break
            lines.append(raw[:400].decode("utf-8", "ignore"))
        size = os.fstat(f.fileno()).st_size
        if size > tail_bytes:
            f.seek(size - tail_bytes)
            lines += [ln[:400] for ln in f.read().decode("utf-8", "ignore").splitlines()[1:]]
    out = {}
    for ln in lines:
        m = re.match(r"^; ([a-z_0-9]+) = (.*)$", ln.rstrip("\r\n"))
        if m and m.group(1) in SETTING_KEYS:
            out[m.group(1)] = m.group(2).strip()
    return out


def _first_number(text) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    return float(m.group(0)) if m else None


def drawing_width(settings: dict) -> tuple[float | None, str]:
    for key in ("line_width", "outer_wall_line_width", "extrusion_width", "external_perimeter_extrusion_width"):
        v = _first_number(settings.get(key))
        if v and 0.05 < v < 3 and "%" not in str(settings.get(key)):
            return v, f"{key} in the G-code"
    v = _first_number(settings.get("nozzle_diameter"))
    if v and 0.05 < v < 3:
        return round(v * 1.1, 3), "nozzle diameter in the G-code × 1.1"
    return None, ""


def bed_from_settings(settings: dict) -> list | None:
    """[x0, y0, x1, y1] of the printable area, if the G-code states it ("0x0,180x0,180x180,0x180")."""
    pts = re.findall(r"(-?\d+(?:\.\d+)?)x(-?\d+(?:\.\d+)?)", settings.get("printable_area") or settings.get("bed_shape") or "")
    if len(pts) < 3:
        return None
    xs, ys = [float(a) for a, _ in pts], [float(b) for _, b in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


# ---- a project's current slice -------------------------------------------------------------------
_cache: dict = {}
_cache_lock = threading.Lock()


def for_project(st, p: dict) -> Toolpath:
    """The toolpath of the project's current slice (raises StudioError if it has none). Cached per slice."""
    from .studio import StudioError
    key = st.keys(p)["slice"]
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    meta = st.read(p, "slice", key)
    if not meta:
        raise StudioError("There is no current slice to simulate.", "Run the pipeline first (form run <project>).", status=409)
    layers = st.layers(p)
    if not layers:
        raise StudioError("The slicer's G-code has no extrusion moves FORM can read.", status=409)
    settings = gcode_settings(st.apath(p, "slice", key) / meta["gcode"])
    w, src = drawing_width(settings)
    tp = build(layers, meta.get("time_s"), w, src, settings)
    with _cache_lock:
        _cache.clear()
        _cache[key] = tp
    return tp


def from_gcode(path, kind: str | None = None, total_time_s: float | None = None) -> Toolpath:
    """A toolpath straight from a G-code file (tests, fixtures, files that are not a project's slice)."""
    from . import slicer
    from .adapters.common import gcode_stats
    path = Path(path)
    if total_time_s is None:
        total_time_s = gcode_stats(path).get("time_s")
    settings = gcode_settings(path)
    w, src = drawing_width(settings)
    return build(slicer.parse_layers(path, kind), total_time_s, w, src, settings)


def stats_at(tp: Toolpath, layer: int) -> dict:
    """What an agent needs to know about the print at the end of `layer` (0-based)."""
    layer = min(max(int(layer), 0), tp.layers - 1)
    done = float(tp.length[: layer + 1].sum())
    total = float(tp.length.sum())
    out = {"layer": layer + 1, "layers": tp.layers, "z_mm": round(float(tp.z[layer]), 3),
           "layer_height_mm": round(float(tp.h[layer]), 3), "types_in_layer": tp.layer_types(layer),
           "layer_path_mm": round(float(tp.length[layer]), 1),
           "path_done_fraction": round(done / total, 4) if total else None,
           "has_bridge": any(t in BRIDGE_TYPES for t in tp.layer_types(layer)),
           "has_overhang_wall": any(t in OVERHANG_TYPES for t in tp.layer_types(layer)),
           "time_source": tp.time_source, "evidence": "simulated"}
    if tp.total_time_s:
        out |= {"layer_time_s": round(float(tp.time[layer]), 1), "elapsed_s": round(float(tp.t0[layer + 1]), 1),
                "remaining_s": round(float(tp.total_time_s - tp.t0[layer + 1]), 1), "total_time_s": tp.total_time_s}
    return out


def parse_range(text: str | None, count: int) -> tuple[int, int]:
    """"a:b" (1-based, inclusive, either side optional) to 0-based [first, last]."""
    if not text:
        return 0, count - 1
    a, _, b = str(text).partition(":")
    try:
        first = int(a) if a.strip() else 1
        last = int(b) if b.strip() else (count if ":" in str(text) else first)
    except ValueError:
        raise ValueError(f"--layers expects a:b (for example 1:60), got “{text}”.")
    first, last = max(1, min(count, first)), max(1, min(count, last))
    if last < first:
        raise ValueError(f"--layers {text}: the last layer is before the first.")
    return first - 1, last - 1


def from_public(d: dict) -> Toolpath:
    """The inverse of Toolpath.public(): what the app rebuilds from the engine's reply."""
    seg = np.frombuffer(base64.b64decode(d["seg"]), dtype="<f4").reshape(-1, 4).astype(np.float32)
    seg_type = np.frombuffer(base64.b64decode(d["seg_type"]), dtype="u1")
    start = np.array(d["start"], dtype=np.int32)
    seg_len = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]).astype(np.float32) if len(seg) else np.zeros(0, np.float32)
    cum = np.zeros(len(seg))
    for a, b in zip(start[:-1], start[1:]):
        cum[a:b] = np.cumsum(seg_len[a:b], dtype=np.float64)
    L = len(d["z"])
    timed = d.get("total_time_s") is not None
    return Toolpath(types=list(d["types"]), seg=seg, seg_type=seg_type, seg_len=seg_len, start=start,
                    z=np.array(d["z"], dtype=np.float32), h=np.array(d["height"], dtype=np.float32),
                    length=np.array([cum[b - 1] if b > a else 0.0 for a, b in zip(start[:-1], start[1:])], dtype=np.float64),
                    time=np.array(d["time_s"], dtype=np.float64) if timed else np.zeros(L),
                    t0=np.array(d["t0_s"], dtype=np.float64) if timed else np.zeros(L + 1),
                    total_time_s=d.get("total_time_s"), time_source=d.get("time_source", "unknown"),
                    width=float(d.get("width_mm") or 0.45), width_source=d.get("width_source", ""), bbox=d["bbox"], _cum=cum)


# ---- vertex buffers for the app's viewport ---------------------------------------------------------
VERTEX_FLOATS = 9          # x y z | r g b type | progress across
RIBBON_LIMIT = 700_000     # moves; above this the print is drawn as plain lines (a third of the memory)


def ribbon_buffers(tp: Toolpath, colors: dict | None = None, first: int = 0, last: int | None = None,
                   mode: str = "auto") -> dict:
    """One vertex buffer for layers first..last (0-based, inclusive): the whole print in a single draw call.

    Every move becomes a low "tent": a ridge at the layer's top, eaves half a line width to each side one layer
    height below (4 triangles, 6 vertices), so stacked layers read as solid from any angle. Each vertex carries
    its line type's colour, the type index (in the colour's alpha, for the type filter) and its progress
    (layer + fraction of the layer), so the shader can hide what has not been printed yet without touching the buffer.
    mode "line" (or more than RIBBON_LIMIT moves) gives two vertices per move instead.

    Returns {"vertex": bytes, "index": bytes | None, "stride", "vertices", "primitive": "triangles" | "lines", "bounds"}."""
    L = tp.layers
    last = L - 1 if last is None else min(max(last, 0), L - 1)
    first = min(max(first, 0), last) if L else 0
    a, b = (int(tp.start[first]), int(tp.start[last + 1])) if L else (0, 0)
    n = b - a
    if mode == "auto":
        mode = "ribbon" if n <= RIBBON_LIMIT else "line"
    stride = VERTEX_FLOATS * 4
    if n == 0:
        return {"vertex": b"", "index": None, "stride": stride, "vertices": 0,
                "primitive": "triangles" if mode == "ribbon" else "lines", "bounds": [[0, 0, 0], [0, 0, 0]], "moves": 0}
    seg = tp.seg[a:b].astype(np.float64)
    kind = tp.seg_type[a:b]
    layer = np.repeat(np.arange(L), np.diff(tp.start))[a:b]
    p0, p1 = tp.progress_arrays()
    p0, p1 = p0[a:b], np.minimum(p1[a:b], layer + 0.99995)        # a finished layer never reads as the next one
    z, h = tp.z[layer].astype(np.float64), tp.h[layer].astype(np.float64)
    pal = np.array([(colors or {}).get(t, (0.66, 0.70, 0.69)) for t in tp.types], dtype=np.float64).reshape(-1, 3)
    rgbt = np.hstack([pal[kind], kind[:, None].astype(np.float64)])            # (n, 4)
    lo = [float(min(seg[:, 0].min(), seg[:, 2].min())), float(min(seg[:, 1].min(), seg[:, 3].min())), float((z - h).min())]
    hi = [float(max(seg[:, 0].max(), seg[:, 2].max())), float(max(seg[:, 1].max(), seg[:, 3].max())), float(z.max())]
    if mode == "line":
        v = np.zeros((n, 2, VERTEX_FLOATS), dtype=np.float32)
        v[:, 0, 0:2], v[:, 1, 0:2] = seg[:, 0:2], seg[:, 2:4]
        v[:, :, 2] = z[:, None]
        v[:, :, 3:7] = rgbt[:, None, :]
        v[:, 0, 7], v[:, 1, 7] = p0, p1
        return {"vertex": v.tobytes(), "index": None, "stride": stride, "vertices": n * 2, "primitive": "lines",
                "bounds": [lo, hi], "moves": n}
    d = seg[:, 2:4] - seg[:, 0:2]
    ln = np.hypot(d[:, 0], d[:, 1])
    d = d / np.maximum(ln, 1e-9)[:, None]
    half = tp.width / 2.0
    side = np.stack([-d[:, 1], d[:, 0]], axis=1) * half               # to the left of the direction of travel
    ext = d * (tp.width * 0.3)                                        # a little overlap, so corners close
    A, B = seg[:, 0:2] - ext, seg[:, 2:4] + ext
    v = np.zeros((n, 6, VERTEX_FLOATS), dtype=np.float32)
    for k, (base, pr) in enumerate(((A, p0), (B, p1))):
        v[:, 3 * k + 0, 0:2] = base + side
        v[:, 3 * k + 1, 0:2] = base
        v[:, 3 * k + 2, 0:2] = base - side
        v[:, 3 * k + 0, 2] = v[:, 3 * k + 2, 2] = z - h
        v[:, 3 * k + 1, 2] = z
        v[:, 3 * k:3 * k + 3, 7] = pr[:, None]
        v[:, 3 * k + 0, 8], v[:, 3 * k + 2, 8] = 1.0, -1.0
    v[:, :, 3:7] = rgbt[:, None, :]
    quad = np.array([0, 3, 4, 0, 4, 1, 1, 4, 5, 1, 5, 2], dtype=np.uint32)
    idx = (np.arange(n, dtype=np.uint32)[:, None] * 6 + quad[None, :]).astype(np.uint32)
    lo[0] -= half; lo[1] -= half; hi[0] += half; hi[1] += half
    return {"vertex": v.tobytes(), "index": idx.tobytes(), "stride": stride, "vertices": n * 6, "primitive": "triangles",
            "bounds": [lo, hi], "moves": n}


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    s = int(round(seconds))
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {s % 60:02d} s" if m else f"{s} s")

