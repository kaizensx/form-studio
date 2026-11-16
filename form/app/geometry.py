"""Geometry for the native viewport: kernel meshes and line sets handed straight to Qt Quick 3D."""
from __future__ import annotations

import base64

import numpy as np
from PySide6.QtCore import Property, QByteArray, Signal
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
    """One feature's triangles. `positions` and `indices` are the base64 arrays the engine returns."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos, self._idx = "", ""
        self._lo, self._hi = QVector3D(), QVector3D()

    def _rebuild(self):
        self.clear()
        pos = _b64(self._pos, np.float32).reshape(-1, 3)
        tri = _b64(self._idx, np.uint32).reshape(-1, 3)
        if not len(pos) or not len(tri):
            self.update()
            return
        buf = np.hstack([pos, smooth_normals(pos, tri)]).astype(np.float32)
        self.setStride(24)
        self.setVertexData(QByteArray(buf.tobytes()))
        self.setIndexData(QByteArray(tri.astype(np.uint32).tobytes()))
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(A.PositionSemantic, 0, A.F32Type)
        self.addAttribute(A.NormalSemantic, 12, A.F32Type)
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

    positions = Property(str, _get_pos, _set_pos, notify=changed)
    indices = Property(str, _get_idx, _set_idx, notify=changed)
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
