"""macOS: the window's close, minimise and zoom buttons centred on Form Studio's own top bar.

The window draws its content under a see-through title bar (Main.qml), so the top bar is taller than the system's
title bar and the three buttons would sit above its middle. This moves the title bar's container to the bar's height
and centres the buttons in it. AppKit lays the title bar out again on resize and full screen, so the window calls this
again then. Nothing here is needed for the app to work: any failure leaves the buttons where AppKit put them.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys


class _Pt(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Sz(ctypes.Structure):
    _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Pt), ("size", _Sz)]


_objc = None


def _lib():
    global _objc
    if _objc is None:
        _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return _objc


def _send(restype, obj, sel, *args, argtypes=()):
    lib = _lib()
    f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(("objc_msgSend", lib))
    return f(obj, lib.sel_registerName(sel.encode()), *args)


def _frame(view) -> _Rect:
    return _send(_Rect, view, "frame")


def center_buttons(view_id: int, bar_height: float) -> bool:
    """view_id: QWindow.winId() (an NSView). True when the buttons were moved."""
    if sys.platform != "darwin" or not view_id or bar_height <= 0:
        return False
    try:
        vp = ctypes.c_void_p
        win = _send(vp, vp(view_id), "window")
        if not win:
            return False
        close = _send(vp, vp(win), "standardWindowButton:", ctypes.c_long(0), argtypes=(ctypes.c_long,))
        if not close:
            return False
        titlebar = _send(vp, vp(close), "superview")                  # NSTitlebarView
        container = _send(vp, vp(titlebar), "superview") if titlebar else None   # NSTitlebarContainerView
        if not container:
            return False
        theme = _send(vp, vp(container), "superview")                 # the window's frame view
        if not theme:
            return False
        outer = _frame(vp(theme))
        c = _frame(vp(container))
        if abs(c.size.h - bar_height) > 0.5 or abs(c.origin.y - (outer.size.h - bar_height)) > 0.5:
            c.size.h = bar_height
            c.origin.y = outer.size.h - bar_height                     # the frame view is not flipped: y from the bottom
            _send(None, vp(container), "setFrame:", c, argtypes=(_Rect,))
        for kind in (0, 1, 2):                                         # close, minimise, zoom
            b = _send(vp, vp(win), "standardWindowButton:", ctypes.c_long(kind), argtypes=(ctypes.c_long,))
            if not b:
                continue
            f = _frame(vp(b))
            y = round((bar_height - f.size.h) / 2)
            if abs(f.origin.y - y) > 0.5:
                _send(None, vp(b), "setFrameOrigin:", _Pt(f.origin.x, y), argtypes=(_Pt,))
        return True
    except Exception:
        return False
