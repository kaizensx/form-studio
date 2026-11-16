"""Headless print simulation: pictures of the sliced toolpaths building up, layer by layer.

No GPU and no window: the moves from the slicer's G-code (form/toolpath.py) are drawn with Pillow, in
print order, from a camera above the plate. Drawing in print order is exact for such a camera: a
later, higher move can only cover an earlier, lower one. Colours are the app's line-type colours.

Every image is labelled "Simulated from the slicer's G-code. Not a print."
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import toolpath as tpm
from .render import _font

LABEL = "Simulated from the slicer's G-code. Not a print."
PLATE, GRID, EDGE = (14, 17, 19), (30, 37, 41), (85, 97, 106)
INK, INK2, INK3, DATUM, SIGNAL = (232, 237, 235), (168, 178, 175), (113, 123, 120), (185, 232, 215), (255, 111, 81)
# the app's line-type colours (LayerView.qml typeColor)
TYPE_RGB = {
    "Outer wall": (232, 237, 235), "Inner wall": (128, 138, 135), "Sparse infill": (233, 184, 96),
    "Internal solid infill": (134, 168, 255), "Top surface": (185, 232, 215), "Bottom surface": (109, 136, 126),
    "Bridge": (255, 111, 81), "Overhang wall": (255, 111, 81), "Floating vertical shell": (255, 150, 120),
    "Gap infill": (73, 82, 79), "Support": (134, 217, 173), "Support interface": (134, 217, 173),
}
OTHER_RGB = (168, 178, 175)


def type_rgb(name: str) -> tuple:
    return TYPE_RGB.get(name, OTHER_RGB)


class Scene:
    """A fixed camera and a canvas that the print is drawn onto, move by move."""

    def __init__(self, tp: tpm.Toolpath, size=(720, 540), azimuth: float = -34.0, elevation: float = 32.0,
                 bed: list | None = None, ss: int = 2, top_layer: int | None = None):
        self.tp, self.size, self.ss = tp, size, ss
        self.W, self.H = size[0] * ss, size[1] * ss
        a, e = math.radians(azimuth), math.radians(max(5.0, min(90.0, elevation)))
        self.right = (math.cos(a), math.sin(a))
        self.fwd = (-math.sin(a) * math.sin(e), math.cos(a) * math.sin(e))
        self.up = math.cos(e)
        (x0, y0, _), (x1, y1, z1) = tp.bbox
        if top_layer is not None and tp.layers:
            z1 = float(tp.z[min(max(top_layer, 0), tp.layers - 1)])
        corners = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (0.0, z1)])
        u, v = self._uv(corners[:, 0], corners[:, 1], corners[:, 2])
        head, foot, side = 74 * ss, 62 * ss, 28 * ss
        span_u, span_v = max(u.max() - u.min(), 1e-6), max(v.max() - v.min(), 1e-6)
        self.k = min((self.W - 2 * side) / span_u, (self.H - head - foot) / span_v)
        self.ou = self.W / 2 - self.k * (u.max() + u.min()) / 2
        self.ov = head + (self.H - head - foot) / 2 + self.k * (v.max() + v.min()) / 2
        self.bed = bed or tpm.bed_from_settings(tp.settings)
        self.p0, self.p1 = tp.progress_arrays()
        self.colors = [type_rgb(t) for t in tp.types]
        self.side_colors = [tuple(int(c * 0.42) for c in rgb) for rgb in self.colors]
        self.lw = max(1, int(round(tp.width * self.k)))
        self.canvas = Image.new("RGB", (self.W, self.H), PLATE)
        self._plate()
        self.drawn = 0                                      # moves drawn so far
        self.partial = 0.0                                  # progress drawn so far

    def _uv(self, x, y, z):
        return x * self.right[0] + y * self.right[1], x * self.fwd[0] + y * self.fwd[1] + z * self.up

    def px(self, x, y, z):
        u, v = self._uv(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64), np.asarray(z, dtype=np.float64))
        return self.ou + self.k * u, self.ov - self.k * v

    def _plate(self):
        d = ImageDraw.Draw(self.canvas)
        if self.bed:
            bx0, by0, bx1, by1 = self.bed
        else:                                               # no stated bed: a grid a little larger than the part
            (x0, y0, _), (x1, y1, _) = self.tp.bbox
            bx0, by0 = math.floor(x0 / 10 - 1) * 10, math.floor(y0 / 10 - 1) * 10
            bx1, by1 = math.ceil(x1 / 10 + 1) * 10, math.ceil(y1 / 10 + 1) * 10
        w = max(1, self.ss // 2)
        g = math.ceil(bx0 / 10) * 10
        while g <= bx1 + 1e-6:
            (ax, bx), (ay, by) = self.px([g, g], [by0, by1], [0, 0])
            d.line([(ax, ay), (bx, by)], fill=GRID, width=w)
            g += 10
        g = math.ceil(by0 / 10) * 10
        while g <= by1 + 1e-6:
            (ax, bx), (ay, by) = self.px([bx0, bx1], [g, g], [0, 0])
            d.line([(ax, ay), (bx, by)], fill=GRID, width=w)
            g += 10
        if self.bed:
            xs, ys = self.px([bx0, bx1, bx1, bx0, bx0], [by0, by0, by1, by1, by0], [0] * 5)
            d.line(list(zip(xs, ys)), fill=EDGE, width=self.ss)

    def advance(self, progress: float, only: set | None = None):
        """Draw every move up to `progress` (layer + fraction) that has not been drawn yet."""
        tp = self.tp
        progress = min(max(progress, 0.0), float(tp.layers))
        if progress <= self.partial or not len(tp.seg):
            return
        hi = int(np.searchsorted(self.p0, progress, side="left"))       # moves that have started
        lo = self.drawn
        if hi > lo:
            idx = np.arange(lo, hi)
            layer = np.searchsorted(tp.start, idx, side="right") - 1
            z = tp.z[layer].astype(np.float64)
            seg = tp.seg[lo:hi].astype(np.float64)
            # a move in progress is drawn up to where the nozzle is
            frac = np.clip((progress - self.p0[lo:hi]) / np.maximum(self.p1[lo:hi] - self.p0[lo:hi], 1e-9), 0.0, 1.0)
            ex = seg[:, 0] + (seg[:, 2] - seg[:, 0]) * frac
            ey = seg[:, 1] + (seg[:, 3] - seg[:, 1]) * frac
            ax, ay = self.px(seg[:, 0], seg[:, 1], z)
            bx, by = self.px(ex, ey, z)
            drop = tp.h[layer].astype(np.float64) * self.up * self.k
            kinds = tp.seg_type[lo:hi]
            show = np.ones(len(idx), bool) if only is None else np.isin(kinds, [tp.types.index(t) for t in only if t in tp.types])
            d = ImageDraw.Draw(self.canvas)
            # one layer at a time: its sides first, then its tops, so a bead's side never covers its neighbour's top
            cuts = np.flatnonzero(np.diff(layer)) + 1
            for a, b in zip(np.concatenate([[0], cuts]), np.concatenate([cuts, [len(idx)]])):
                for i in range(a, b):
                    if show[i]:
                        d.line([(ax[i], ay[i] + drop[i]), (bx[i], by[i] + drop[i])], fill=self.side_colors[kinds[i]], width=self.lw + 1)
                for i in range(a, b):
                    if show[i]:
                        d.line([(ax[i], ay[i]), (bx[i], by[i])], fill=self.colors[kinds[i]], width=self.lw)
            # a move cut short is drawn again, further, next time
            done = frac >= 1.0
            self.drawn = lo + (int(np.argmin(done)) if not done.all() else len(done))
        self.partial = progress

    def frame(self, progress: float, title: str = "", nozzle: bool = True, legend: bool = True) -> Image.Image:
        """The canvas as it stands, with the nozzle, the readout and the label, at the output size."""
        tp, ss = self.tp, self.ss
        img = self.canvas.copy()
        d = ImageDraw.Draw(img)
        at = tp.at(min(progress, tp.layers - 1e-6)) if tp.layers else {}
        finished = progress >= tp.layers - 1e-6
        if nozzle and at and not finished:
            (x,), (y,) = self.px([at["x"]], [at["y"]], [at["z"]])
            for r, c in ((9, (60, 84, 76)), (6, (120, 160, 146)), (3.2, (235, 255, 248))):
                d.ellipse([x - r * ss, y - r * ss, x + r * ss, y + r * ss], fill=c)
        f_title, f_body, f_small = _font(17 * ss), _font(13 * ss), _font(11 * ss)
        m = 18 * ss
        d.text((m, 14 * ss), title or "Print simulation", fill=INK, font=f_title)
        d.text((m, 38 * ss), LABEL, fill=(233, 184, 96), font=f_small)
        if at:
            l = tp.layers if finished else at["layer"] + 1
            line = f"Layer {l} / {tp.layers}   z {float(tp.z[l - 1]):.2f} mm"
            if not finished:
                line += f"   {at['type']}"
            d.text((m, self.H - 44 * ss), line, fill=INK, font=f_body)
            if tp.total_time_s:
                el = tp.total_time_s if finished else at["elapsed_s"]
                t = f"{tpm.fmt_duration(el)} elapsed   {tpm.fmt_duration(tp.total_time_s - el)} remaining   slicer estimate, {tp.time_source}"
                d.text((m, self.H - 24 * ss), t, fill=INK3, font=f_small)
            # progress bar
            d.rectangle([0, self.H - 3 * ss, self.W, self.H], fill=GRID)
            d.rectangle([0, self.H - 3 * ss, self.W * min(1.0, progress / max(tp.layers, 1)), self.H], fill=DATUM)
        if legend:
            y = 16 * ss
            for i, t in enumerate(tp.types):
                w = d.textlength(t, font=f_small)
                d.rectangle([self.W - m - w - 16 * ss, y + 5 * ss, self.W - m - w - 6 * ss, y + 8 * ss], fill=self.colors[i])
                d.text((self.W - m - w, y), t, fill=INK2, font=f_small)
                y += 15 * ss
        return img.resize(self.size, Image.LANCZOS) if ss > 1 else img


def image_at(tp: tpm.Toolpath, progress: float, size=(960, 720), title: str = "", only=None, **cam) -> Image.Image:
    """The print as it would stand at `progress` (layer index + fraction of that layer)."""
    sc = Scene(tp, size, **cam)
    sc.advance(progress, set(only) if only else None)
    return sc.frame(progress, title)


def png_at(tp: tpm.Toolpath, progress: float, **kw) -> bytes:
    buf = io.BytesIO()
    image_at(tp, progress, **kw).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def frames(tp: tpm.Toolpath, first: int = 0, last: int | None = None, count: int = 72, size=(720, 540), title: str = "",
           by: str = "time", **cam):
    """Yield (progress, image) for `count` moments from the start of layer `first` to the end of layer `last`.

    by="time" spaces the frames evenly in slicer time (falls back to path length when the slice has no time);
    by="layer" gives every layer the same number of frames."""
    last = tp.layers - 1 if last is None else last
    sc = Scene(tp, size, top_layer=None, **cam)
    sc.advance(float(first))                                 # what is already on the plate when the clip starts
    count = max(2, int(count))
    if by == "time" and tp.total_time_s:
        t_a, t_b = float(tp.t0[first]), float(tp.t0[last + 1])
        marks = [tp.progress_at_time(t_a + (t_b - t_a) * i / (count - 1)) for i in range(count)]
    elif by == "layer":
        marks = [first + (last + 1 - first) * i / (count - 1) for i in range(count)]
    else:
        cum = np.concatenate([[0.0], np.cumsum(tp.length)])
        want = np.linspace(cum[first], cum[last + 1], count)
        marks = []
        for s in want:
            l = min(int(np.searchsorted(cum, s, side="right")) - 1, tp.layers - 1)
            marks.append(l + (min((s - cum[l]) / tp.length[l], 1.0) if tp.length[l] > 0 else 0.0))
    marks[-1] = float(last + 1)
    for pr in marks:
        pr = min(max(pr, float(first)), float(last + 1))
        sc.advance(pr)
        yield pr, sc.frame(pr, title)


def save_frames(tp: tpm.Toolpath, out_dir, **kw) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, (pr, img) in enumerate(frames(tp, **kw)):
        f = out_dir / f"frame_{i:04d}.png"
        img.save(f, "PNG")
        files.append(str(f))
    return {"dir": str(out_dir), "frames": len(files), "first": files[0], "last": files[-1]}


def save_gif(tp: tpm.Toolpath, out, ms: int = 80, hold: int = 14, colors: int = 48, max_bytes: int | None = None, **kw) -> dict:
    """An animated GIF of the build-up. The last frame is held. If max_bytes is given and the file is larger,
    it is written again with fewer colours and then fewer frames until it fits (or cannot shrink further)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    imgs = [img for _, img in frames(tp, **kw)]
    step = 1
    while True:
        seq = imgs[::step]
        if seq[-1] is not imgs[-1]:
            seq.append(imgs[-1])
        pal = imgs[-1].convert("P", palette=Image.ADAPTIVE, colors=colors)
        q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in seq]
        durations = [ms * step] * (len(q) - 1) + [ms * hold]
        q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=True, disposal=1)
        size = out.stat().st_size
        if not max_bytes or size <= max_bytes or (colors <= 16 and len(seq) <= 12):
            break
        if colors > 16:
            colors = max(16, colors // 2)
        else:
            step += 1
    return {"file": str(out), "frames": len(seq), "bytes": size, "colors": colors, "frame_ms": ms * step,
            "size": list(imgs[0].size), "label": LABEL}
