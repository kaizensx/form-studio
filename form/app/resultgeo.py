"""Geometry of the results drawn on the part: read from the engines' own files, handed to Qt Quick 3D.

The window gets a result's description from form/resultview.py; the arrays stay on disk and are read here, so a
manufacturability overlay of 660,000 vertices never passes through QML as text. Three sources:

    {"file", "kind": "field", "field": "von_mises" | "modes" | "temperature", "mode": i, "lo", "hi", "peak": [x, y, z]}
        a strength field (form.fea.field/1). Per vertex: UV0 = (the value on the legend's 0..1, the distance from the
        peak on 0..1), UV1 = (1 in a singular zone, 0), and the displacement (or the mode shape) as the tangent, so
        the shader draws the deformed shape and the "result develops" moment without a new buffer.
    {"file", "kind": "dfm", "faces": [ids] | absent}
        a manufacturability overlay (form-dfm-overlay/1) with the engine's colour per vertex and UV1 = (0, status).
        With faces: only the triangles of those B-rep faces (what a rule's row lights).
    {"file", "kind": "stock", "setup": i}
        the simulated stock of a CNC setup (form-cam-view/1), coloured by the engine, UV1 = (0, status).

PathGeometry draws a setup's toolpaths as lines: colour per operation, UV0 = (seconds at the segment's end, 1 for a
rapid), so the scrubber moves a uniform and never the buffer.
"""
from __future__ import annotations

import base64
import json
import os
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import Property, QByteArray, Signal, Slot
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DGeometry

from .geometry import smooth_normals

QML_IMPORT_NAME = "FormNative"
QML_IMPORT_MAJOR_VERSION = 1

A = QQuick3DGeometry.Attribute
_FILES: OrderedDict = OrderedDict()          # (path, mtime) → parsed JSON: a result is read once, drawn many ways
_KEEP = 3


def _file(path: str) -> dict:
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return {}
    got = _FILES.get(key)
    if got is None:
        try:
            with open(path, encoding="utf-8") as f:
                got = json.load(f)
        except (OSError, ValueError):
            return {}
        _FILES[key] = got
        while len(_FILES) > _KEEP:
            _FILES.popitem(last=False)
    else:
        _FILES.move_to_end(key)
    return got


def _b64(text, dtype) -> np.ndarray:
    return np.frombuffer(base64.b64decode(text), dtype=dtype) if text else np.zeros(0, dtype=dtype)


def _linear(rgba: np.ndarray) -> np.ndarray:
    c = rgba.astype(np.float32) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)
    lin[:, 3] = 1.0
    return lin


def _plain(v):
    if hasattr(v, "toVariant"):
        v = v.toVariant()
    return v if isinstance(v, dict) else {}


@QmlElement
class ResultGeometry(QQuick3DGeometry):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src: dict = {}
        self._lo, self._hi = QVector3D(), QVector3D()
        self._P = self._T = self._V = self._C = None
        self._count = 0
        self._reach = 1.0

    def _empty(self):
        self.clear()
        self._P = self._T = self._V = self._C = None
        self._count = 0
        self.update()
        self.changed.emit()

    def _rebuild(self):
        s = self._src
        f = _file(str(s.get("file") or "")) if s.get("file") else {}
        kind = s.get("kind")
        if not f:
            return self._empty()
        col = tan = None
        vals = None
        if kind == "field":
            pos = _b64(f.get("positions"), "<f4").reshape(-1, 3)
            tri = _b64(f.get("indices"), "<u4").reshape(-1, 3)
            n = len(pos)
            fields = f.get("fields") or {}
            name = s.get("field") or "von_mises"
            uv0 = np.zeros((n, 2), np.float32)
            uv1 = np.zeros((n, 2), np.float32)
            tan = np.zeros((n, 3), np.float32)
            src = fields.get(name) or {}
            raw = _b64(src.get("data"), "<f4")
            if name == "modes":
                cnt = int(src.get("count") or (len(raw) // max(1, 3 * n)))
                k = max(0, min(cnt - 1, int(s.get("mode") or 0)))
                shape = raw.reshape(cnt, n, 3)[k] if cnt and len(raw) == cnt * n * 3 else np.zeros((n, 3), np.float32)
                tan = shape.astype(np.float32)
                vals = np.linalg.norm(shape, axis=1)
            else:
                vals = raw if len(raw) == n else np.zeros(n, np.float32)
                d = _b64((fields.get("displacement") or {}).get("data"), "<f4")
                if len(d) == 3 * n:
                    tan = d.reshape(n, 3).astype(np.float32)
                sg = _b64((fields.get("singular") or {}).get("data"), "u1")
                if len(sg) == n:
                    uv1[:, 0] = sg
            lo, hi = float(s.get("lo") or 0.0), float(s.get("hi") if s.get("hi") is not None else 1.0)
            uv0[:, 0] = np.clip((vals - lo) / max(hi - lo, 1e-12), 0.0, 1.0)
            pk = s.get("peak")
            origin = np.asarray(pk, np.float32) if pk is not None and len(pk) == 3 else (pos[int(np.argmax(vals))] if n else np.zeros(3, np.float32))
            dist = np.linalg.norm(pos - origin, axis=1) if n else np.zeros(0, np.float32)
            self._reach = float(dist.max()) if n else 1.0
            uv0[:, 1] = dist / max(self._reach, 1e-9)
        elif kind == "dfm":
            pos = _b64(f.get("positions"), "<f4").reshape(-1, 3)
            tri = _b64(f.get("indices"), "<u4").reshape(-1, 3)
            rgba = _b64(f.get("colors"), "u1").reshape(-1, 4)
            st = _b64(f.get("status"), "u1")
            faces = s.get("faces")
            if faces is not None:
                fc = _b64(f.get("face"), "<u4")
                if len(fc) != len(tri) or not len(faces):
                    return self._empty()
                keep = np.isin(fc, np.asarray([int(x) for x in faces], np.uint32))
                tri = tri[keep]
                if not len(tri):
                    return self._empty()
                used = np.unique(tri)
                remap = np.zeros(len(pos), np.uint32)
                remap[used] = np.arange(len(used), dtype=np.uint32)
                pos, rgba, st, tri = pos[used], rgba[used] if len(rgba) == len(remap) else rgba, st[used] if len(st) == len(remap) else st, remap[tri]
            n = len(pos)
            uv0 = np.zeros((n, 2), np.float32)
            uv1 = np.zeros((n, 2), np.float32)
            if len(st) == n:
                uv1[:, 1] = st
            col = _linear(rgba) if len(rgba) == n else np.ones((n, 4), np.float32)
        elif kind == "stock":
            ss = f.get("setups") or []
            i = int(s.get("setup") or 0)
            stock = (ss[i].get("stock") if 0 <= i < len(ss) else None) or {}
            pos = _b64(stock.get("positions"), "<f4").reshape(-1, 3)
            tri = _b64(stock.get("indices"), "<u4").reshape(-1, 3)
            rgba = _b64(stock.get("colors"), "u1").reshape(-1, 4)
            st = _b64(stock.get("status"), "u1")
            n = len(pos)
            uv0 = np.zeros((n, 2), np.float32)
            uv1 = np.zeros((n, 2), np.float32)
            if len(st) == n:
                uv1[:, 1] = st
            col = _linear(rgba) if len(rgba) == n else np.ones((n, 4), np.float32)
        else:
            return self._empty()
        if not len(pos) or not len(tri) or int(tri.max()) >= len(pos):
            return self._empty()
        self.clear()
        cols = [pos.astype(np.float32), smooth_normals(pos, tri), uv0, uv1]
        if col is not None:
            cols.append(col)
        if tan is not None:
            cols.append(tan)
        buf = np.hstack(cols).astype(np.float32)
        self.setStride(buf.shape[1] * 4)
        self.setVertexData(QByteArray(buf.tobytes()))
        self.setIndexData(QByteArray(tri.astype(np.uint32).tobytes()))
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(A.PositionSemantic, 0, A.F32Type)
        self.addAttribute(A.NormalSemantic, 12, A.F32Type)
        self.addAttribute(A.TexCoord0Semantic, 24, A.F32Type)
        self.addAttribute(A.TexCoord1Semantic, 32, A.F32Type)
        off = 40
        if col is not None:
            self.addAttribute(A.ColorSemantic, off, A.F32Type)
            off += 16
        if tan is not None:
            self.addAttribute(A.TangentSemantic, off, A.F32Type)
        self.addAttribute(A.IndexSemantic, 0, A.U32Type)
        lo, hi = pos.min(axis=0), pos.max(axis=0)
        if tan is not None and len(tan):                 # room for the deformed shape, so it is never culled
            pad = float(np.abs(tan).max()) * float(s.get("reach") or 0)
            lo, hi = lo - pad, hi + pad
        self._lo, self._hi = QVector3D(*map(float, lo)), QVector3D(*map(float, hi))
        self.setBounds(self._lo, self._hi)
        self._count = int(len(tri))
        self._P = self._T = self._V = self._C = None
        if kind == "field" and vals is not None and len(vals) == len(pos):
            self._P, self._T, self._V = pos.astype(np.float64), tri.astype(np.int64), vals.astype(np.float64)
            self._C = (self._P[self._T[:, 0]] + self._P[self._T[:, 1]] + self._P[self._T[:, 2]]) / 3
        self.update()
        self.changed.emit()

    @Slot(QVector3D, result=float)
    def valueAt(self, p: QVector3D) -> float:
        """The field's value at a point of the undeformed surface (nearest triangle, interpolated). NaN if none."""
        if self._V is None or not len(self._C):
            return float("nan")
        from ..analysis import closest_on_triangles
        q = np.array([p.x(), p.y(), p.z()], dtype=np.float64)
        near = np.argpartition(np.linalg.norm(self._C - q, axis=1), min(24, len(self._C) - 1))[:24]
        t = self._T[near]
        a_, b_, c_ = self._P[t[:, 0]], self._P[t[:, 1]], self._P[t[:, 2]]
        pts, d = closest_on_triangles(q, a_, b_, c_)
        k = int(np.argmin(d))
        a, b, c, x = a_[k], b_[k], c_[k], pts[k]
        nn = np.cross(b - a, c - a)
        den = float(nn @ nn)
        w = np.array([1.0, 0.0, 0.0]) if den < 1e-18 else np.clip(
            np.array([np.cross(b - x, c - x) @ nn, np.cross(c - x, a - x) @ nn, np.cross(a - x, b - x) @ nn]) / den, 0, None)
        return float((self._V[t[k]] * w).sum() / max(w.sum(), 1e-12))

    def _get_src(self): return self._src
    def _set_src(self, v):
        v = _plain(v)
        if v == self._src:
            return
        self._src = v
        self._rebuild()

    source = Property("QVariant", _get_src, _set_src, notify=changed)
    lo = Property(QVector3D, lambda self: self._lo, notify=changed)
    hi = Property(QVector3D, lambda self: self._hi, notify=changed)
    triangles = Property(int, lambda self: self._count, notify=changed)
    reach = Property(float, lambda self: self._reach, notify=changed)      # mm from the peak to the farthest vertex


@QmlElement
class PathGeometry(QQuick3DGeometry):
    """A CNC setup's toolpaths as line segments (form-cam-view/1). `source`: {"file", "setup": i}."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src: dict = {}
        self._segs = None                # (n, 2, 3) float64, sorted by time
        self._t = None                   # (n,) seconds at each segment's end
        self._dur = 0.0
        self._count = 0

    def _rebuild(self):
        s = self._src
        f = _file(str(s.get("file") or "")) if s.get("file") else {}
        ss = f.get("setups") or []
        i = int(s.get("setup") or 0)
        self.clear()
        self._segs = self._t = None
        self._dur, self._count = 0.0, 0
        tps = (ss[i].get("toolpaths") if 0 <= i < len(ss) else None) or []
        P, C, U, T = [], [], [], []
        for tp in tps:
            seg = _b64(tp.get("positions"), "<f4").reshape(-1, 2, 3)
            t = _b64(tp.get("t"), "<f4")
            if not len(seg) or len(t) != len(seg):
                continue
            h = str(tp.get("color") or "#cccccc").lstrip("#")
            rgb = np.array([int(h[k:k + 2], 16) for k in (0, 2, 4)] + [255], np.uint8).reshape(1, 4)
            rapid = 1.0 if tp.get("kind") == "rapid" else 0.0
            P.append(seg.reshape(-1, 3))
            C.append(np.repeat(_linear(rgb), 2 * len(seg), axis=0))
            U.append(np.stack([np.repeat(t, 2), np.full(2 * len(seg), rapid, np.float32)], axis=1))
            T.append((seg, t))
        if P:
            buf = np.hstack([np.vstack(P), np.vstack(C), np.vstack(U)]).astype(np.float32)
            self.setStride(36)
            self.setVertexData(QByteArray(buf.tobytes()))
            self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Lines)
            self.addAttribute(A.PositionSemantic, 0, A.F32Type)
            self.addAttribute(A.ColorSemantic, 12, A.F32Type)
            self.addAttribute(A.TexCoord0Semantic, 28, A.F32Type)
            allp = np.vstack(P)
            self.setBounds(QVector3D(*map(float, allp.min(axis=0))), QVector3D(*map(float, allp.max(axis=0))))
            segs = np.vstack([x[0] for x in T]).astype(np.float64)
            ts = np.concatenate([x[1] for x in T]).astype(np.float64)
            order = np.argsort(ts, kind="stable")
            self._segs, self._t = segs[order], ts[order]
            self._dur = float(ts.max())
            self._count = int(len(ts))
        self.update()
        self.changed.emit()

    @Slot(float, result=QVector3D)
    def at(self, t: float) -> QVector3D:
        """Where the tool tip is at t seconds: on the segment being cut, by the time between its neighbours' ends."""
        if self._t is None or not len(self._t):
            return QVector3D()
        k = int(np.searchsorted(self._t, t, side="left"))
        k = max(0, min(len(self._t) - 1, k))
        t1 = self._t[k]
        t0 = self._t[k - 1] if k > 0 else 0.0
        u = 1.0 if t1 <= t0 else max(0.0, min(1.0, (t - t0) / (t1 - t0)))
        p = self._segs[k, 0] + (self._segs[k, 1] - self._segs[k, 0]) * u
        return QVector3D(float(p[0]), float(p[1]), float(p[2]))

    def _get_src(self): return self._src
    def _set_src(self, v):
        v = _plain(v)
        if v == self._src:
            return
        self._src = v
        self._rebuild()

    source = Property("QVariant", _get_src, _set_src, notify=changed)
    duration = Property(float, lambda self: self._dur, notify=changed)
    segments = Property(int, lambda self: self._count, notify=changed)
