"""Geometry for the native viewport: kernel meshes and line sets handed straight to Qt Quick 3D."""
from __future__ import annotations

import base64

import numpy as np
from PySide6.QtCore import Property, QByteArray, Signal, Slot
from PySide6.QtGui import QVector3D
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
