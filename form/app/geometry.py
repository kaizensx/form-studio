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
