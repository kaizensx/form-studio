"""Geometry for the native viewport: kernel meshes and line sets handed straight to Qt Quick 3D."""
from __future__ import annotations

import base64

import numpy as np
from PySide6.QtCore import Property, QByteArray, Signal, Slot
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DGeometry

QML_IMPORT_NAME = "FormNative"
QML_IMPORT_MAJOR_VERSION = 1

A = QQuick3DGeometry.Attribute


def _b64(text: str, dtype) -> np.ndarray:
    return np.frombuffer(base64.b64decode(text), dtype=dtype) if text else np.zeros(0, dtype=dtype)


def smooth_normals(pos: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals. The kernel splits vertices at sharp edges, so creases stay crisp."""
    n = np.zeros_like(pos, dtype=np.float64)
    if len(tri):
        a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
        fn = np.cross(b - a, c - a)
        for k in range(3):
            np.add.at(n, tri[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    return (n / ln).astype(np.float32)


@QmlElement
class MeshGeometry(QQuick3DGeometry):
    """One feature's triangles. `positions` and `indices` are the base64 arrays the engine returns.

    An analysis map (form/analysis.py) also sets `colors` (one sRGB RGBA byte quad per vertex, drawn by clay.frag when
    its uMap is on) and `values` (one float per vertex, NaN where there is none) for `valueAt`.
    """
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos, self._idx = "", ""
        self._col, self._val = "", ""
        self._P = self._T = self._V = self._C = None
        self._lo, self._hi = QVector3D(), QVector3D()

    def _rebuild(self):
        self.clear()
        pos = _b64(self._pos, np.float32).reshape(-1, 3)
        tri = _b64(self._idx, np.uint32).reshape(-1, 3)
        self._P = self._T = self._V = self._C = None
        if not len(pos) or not len(tri):
            self.update()
            return
        cols = [pos, smooth_normals(pos, tri)]
        rgba = _b64(self._col, np.uint8).reshape(-1, 4) if self._col else np.zeros((0, 4), dtype=np.uint8)
        coloured = len(rgba) == len(pos)
        if coloured:                                    # vertex colours are sRGB; the shader works in linear light
            c = rgba.astype(np.float32) / 255.0
            lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
            lin[:, 3] = 1.0
            cols.append(lin)
        buf = np.hstack(cols).astype(np.float32)
        self.setStride(40 if coloured else 24)
        self.setVertexData(QByteArray(buf.tobytes()))
        self.setIndexData(QByteArray(tri.astype(np.uint32).tobytes()))
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(A.PositionSemantic, 0, A.F32Type)
        self.addAttribute(A.NormalSemantic, 12, A.F32Type)
        if coloured:
            self.addAttribute(A.ColorSemantic, 24, A.F32Type)
        vals = _b64(self._val, np.float32) if self._val else np.zeros(0, dtype=np.float32)
        if len(vals) == len(pos):
            self._P, self._T, self._V = pos.astype(np.float64), tri.astype(np.int64), vals.astype(np.float64)
            self._C = (self._P[self._T[:, 0]] + self._P[self._T[:, 1]] + self._P[self._T[:, 2]]) / 3
        self.addAttribute(A.IndexSemantic, 0, A.U32Type)
        lo, hi = pos.min(axis=0), pos.max(axis=0)
        self._lo, self._hi = QVector3D(*map(float, lo)), QVector3D(*map(float, hi))
        self.setBounds(self._lo, self._hi)
        self.update()
        self.changed.emit()

    def _get_pos(self): return self._pos
    def _set_pos(self, v):
        self._pos = v or ""
        if self._idx: self._rebuild()
    def _get_idx(self): return self._idx
    def _set_idx(self, v):
        self._idx = v or ""
        if self._pos: self._rebuild()

    def _get_col(self): return self._col
    def _set_col(self, v):
        self._col = v or ""
        if self._pos and self._idx: self._rebuild()
    def _get_val(self): return self._val
    def _set_val(self, v):
        self._val = v or ""
        if self._pos and self._idx: self._rebuild()

    @Slot(QVector3D, result=float)
    def valueAt(self, p: QVector3D) -> float:
        """The map's value at a point on the surface: nearest triangle, interpolated between its corners. NaN if none."""
        if self._V is None:
            return float("nan")
        from ..analysis import closest_on_triangles
        q = np.array([p.x(), p.y(), p.z()], dtype=np.float64)
        near = np.argpartition(np.linalg.norm(self._C - q, axis=1), min(24, len(self._C) - 1))[:24]
        t = self._T[near]
        A_, B_, C_ = self._P[t[:, 0]], self._P[t[:, 1]], self._P[t[:, 2]]
        pts, d = closest_on_triangles(q, A_, B_, C_)
        k = int(np.argmin(d))
        a, b, c, x = A_[k], B_[k], C_[k], pts[k]
        n = np.cross(b - a, c - a)
        den = float(n @ n)
        if den < 1e-18:
            w = np.array([1.0, 0.0, 0.0])
        else:
            w = np.array([np.cross(b - x, c - x) @ n, np.cross(c - x, a - x) @ n, np.cross(a - x, b - x) @ n]) / den
        v = self._V[t[k]]
        ok = np.isfinite(v)
        if not ok.any():
            return float("nan")
        w = np.clip(w, 0, None) * ok
        return float((v[ok] * w[ok]).sum() / w.sum()) if w.sum() > 1e-12 else float(v[ok][0])

    def _get_src(self): return None
    def _set_src(self, v):
        """All four arrays at once (an analysis map from the engine): one rebuild instead of four."""
        if hasattr(v, "toVariant"):
            v = v.toVariant()
        v = v if isinstance(v, dict) else {}
        self._pos, self._idx = v.get("positions") or "", v.get("indices") or ""
        self._col, self._val = v.get("colors") or "", v.get("values") or ""
        self._rebuild()

    source = Property("QVariant", _get_src, _set_src, notify=changed)
    positions = Property(str, _get_pos, _set_pos, notify=changed)
    indices = Property(str, _get_idx, _set_idx, notify=changed)
    colors = Property(str, _get_col, _set_col, notify=changed)
    values = Property(str, _get_val, _set_val, notify=changed)
    lo = Property(QVector3D, lambda self: self._lo, notify=changed)
    hi = Property(QVector3D, lambda self: self._hi, notify=changed)


@QmlElement
class GameGeometry(QQuick3DGeometry):
    """One LOD of a game asset (form/game/app.py lod()): positions, triangles and UVs, set at once through `source`.
    Normals are smoothed across UV seams (the corners are split there, the surface is not), so a seam never shows
    as a crease; UVs go to TEXCOORD0 for the checker and the baked maps (shaders/game.frag)."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tris = 0

    def _get_src(self): return None
    def _set_src(self, v):
        if hasattr(v, "toVariant"):
            v = v.toVariant()
        v = v if isinstance(v, dict) else {}
        self.clear()
        pos = _b64(v.get("positions") or "", np.float32).reshape(-1, 3)
        tri = _b64(v.get("indices") or "", np.uint32).reshape(-1, 3)
        uv = _b64(v.get("uvs") or "", np.float32).reshape(-1, 2)
        self._tris = int(len(tri))
        if len(pos) and len(tri):
            _, weld = np.unique(np.round(pos, 4), axis=0, return_inverse=True)
            weld = weld.reshape(-1)
            P = np.zeros((int(weld.max()) + 1, 3), dtype=np.float32)
            P[weld] = pos
            nrm = smooth_normals(P, weld[tri])[weld]
            if len(uv) != len(pos):
                uv = np.zeros((len(pos), 2), dtype=np.float32)
            buf = np.hstack([pos, nrm, uv]).astype(np.float32)
            self.setStride(32)
            self.setVertexData(QByteArray(buf.tobytes()))
            self.setIndexData(QByteArray(tri.astype(np.uint32).tobytes()))
            self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
            self.addAttribute(A.PositionSemantic, 0, A.F32Type)
            self.addAttribute(A.NormalSemantic, 12, A.F32Type)
            self.addAttribute(A.TexCoord0Semantic, 24, A.F32Type)
            self.addAttribute(A.IndexSemantic, 0, A.U32Type)
            self.setBounds(QVector3D(*map(float, pos.min(axis=0))), QVector3D(*map(float, pos.max(axis=0))))
        self.update()
        self.changed.emit()

    source = Property("QVariant", _get_src, _set_src, notify=changed)
    triangles = Property(int, lambda self: self._tris, notify=changed)


@QmlElement
class LineGeometry(QQuick3DGeometry):
    """Line segments: either the engine's base64 edge array (`segments`) or a flat list of xyz pairs (`points`)."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data, self._points = "", []

    def _rebuild(self, arr: np.ndarray):
        self.clear()
        arr = np.ascontiguousarray(arr, dtype=np.float32).reshape(-1, 3)
        if len(arr):
            self.setStride(12)
            self.setVertexData(QByteArray(arr.tobytes()))
            self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Lines)
            self.addAttribute(A.PositionSemantic, 0, A.F32Type)
            self.setBounds(QVector3D(*map(float, arr.min(axis=0))), QVector3D(*map(float, arr.max(axis=0))))
        self.update()
        self.changed.emit()

    def _get_data(self): return self._data
    def _set_data(self, v):
        self._data = v or ""
        self._rebuild(_b64(self._data, np.float32))
    def _get_points(self): return self._points
    def _set_points(self, v):
        self._points = list(v or [])
        self._rebuild(np.array(self._points, dtype=np.float32))

    segments = Property(str, _get_data, _set_data, notify=changed)
    points = Property("QVariantList", _get_points, _set_points, notify=changed)


@QmlElement
class ToolpathGeometry(QQuick3DGeometry):
    """The whole sliced print as one vertex buffer (form/toolpath.py ribbon_buffers).

    Set `colors` (line type → colour) and `url` (the engine's /toolpath reply). The reply is fetched and the
    buffers are built on a worker thread, then handed to the scene; `loaded(summary)` carries the per-layer
    numbers (no geometry) for the transport and the chart. `at(progress)` says where the nozzle is.
    `firstLayer`/`lastLayer` (0-based, -1 = to the end) limit what is built."""
    changed = Signal()
    loaded = Signal("QVariantMap")
    failed = Signal(str)
    _built = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._url, self._colors, self._tp = "", {}, None
        self._first, self._last, self._gen, self._busy, self._moves = 0, -1, 0, False, 0
        self._built.connect(self._apply)

    # -- worker thread --
    def _work(self, gen: int, url: str, tp, colors: dict, first: int, last: int):
        import json
        import urllib.error
        import urllib.request

        from .. import toolpath
        try:
            summary = None
            if tp is None:
                try:
                    with urllib.request.urlopen(url, timeout=120) as r:
                        d = json.loads(r.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    try:
                        msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message") or str(e)
                    except ValueError:
                        msg = str(e)
                    self._built.emit((gen, None, None, None, msg))
                    return
                tp = toolpath.from_public(d)
                summary = {k: v for k, v in d.items() if k not in ("seg", "seg_type", "start")}
            buf = toolpath.ribbon_buffers(tp, colors, first, None if last < 0 else last)
            self._built.emit((gen, tp, summary, buf, ""))
        except Exception as e:                                # shown in the view, never swallowed
            self._built.emit((gen, None, None, None, f"The toolpaths could not be prepared: {e}"))

    def _start(self, refetch: bool):
        if not self._url:
            return
        import threading
        self._gen += 1
        self._busy = True
        self.changed.emit()
        tp = None if refetch else self._tp
        threading.Thread(target=self._work, args=(self._gen, self._url, tp, dict(self._colors), self._first, self._last),
                         daemon=True, name="form-toolpath").start()

    # -- interface thread --
    def _apply(self, res):
        gen, tp, summary, buf, err = res
        if gen != self._gen:
            return                                            # a newer request is on its way
        self._busy = False
        if err:
            self.changed.emit()
            self.failed.emit(err)
            return
        self._tp = tp
        self.clear()
        self._moves = buf["moves"]
        if buf["vertices"]:
            self.setStride(buf["stride"])
            self.setVertexData(QByteArray(buf["vertex"]))
            if buf["index"]:
                self.setIndexData(QByteArray(buf["index"]))
                self.addAttribute(A.IndexSemantic, 0, A.U32Type)
            self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles if buf["primitive"] == "triangles"
                                  else QQuick3DGeometry.PrimitiveType.Lines)
            self.addAttribute(A.PositionSemantic, 0, A.F32Type)
            self.addAttribute(A.ColorSemantic, 12, A.F32Type)
            self.addAttribute(A.TexCoord0Semantic, 28, A.F32Type)
            lo, hi = buf["bounds"]
            self.setBounds(QVector3D(*lo), QVector3D(*hi))
        self.update()
        self.changed.emit()
        if summary is not None:
            self.loaded.emit(summary)

    def _set_url(self, v):
        v = v or ""
        if v != self._url:
            self._url, self._tp = v, None
            self._start(True)

    def _set_colors(self, v):
        out = {}
        for k, c in dict(v or {}).items():
            q = QColor(c)
            out[str(k)] = (q.redF(), q.greenF(), q.blueF())
        if out != self._colors:
            self._colors = out
            self._start(self._tp is None)

    def _set_first(self, v):
        if int(v) != self._first:
            self._first = int(v)
            self._start(self._tp is None)

    def _set_last(self, v):
        if int(v) != self._last:
            self._last = int(v)
            self._start(self._tp is None)

    @Slot(float, result="QVariantMap")
    def at(self, progress: float):
        return self._tp.at(progress) if self._tp is not None and self._tp.layers else {}

    url = Property(str, lambda self: self._url, _set_url, notify=changed)
    colors = Property("QVariantMap", lambda self: {}, _set_colors, notify=changed)
    firstLayer = Property(int, lambda self: self._first, _set_first, notify=changed)
    lastLayer = Property(int, lambda self: self._last, _set_last, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    moves = Property(int, lambda self: self._moves, notify=changed)
