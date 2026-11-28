"""A still workspace draws nothing (direction I, motion spec): with nothing touched and nothing building, the window
swaps no frame, whether it is the active window or not, in every mode, with the column open or folded. The one thing
that may draw is the caret of a field being typed in, and only while the window is active: two steps a cycle, never at
the display's rate.

Prints IDLE lines (frames in 3 s) for the record; the journey fails on any redraw outside the caret's.
"""
from _lib import goto, phone_dock, toasts_gone

DATA = "fresh"
MS = 3000


def frames(ui, ms=MS):
    """How many frames the window swaps in ms while nothing is touched."""
    n = [0]

    def tick():
        n[0] += 1
    ui.win.frameSwapped.connect(tick)
    ui._pump(ms)
    ui.win.frameSwapped.disconnect(tick)
    return n[0]


def inactive(ui):
    """Qt's focus window becomes none: the window is not the active one (a ghost window never asks the system)."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QCoreApplication
    import ctypes
    from pathlib import Path
    from PySide6 import QtGui
    lib = None
    for cand in (Path(QtGui.__file__).parent / "Qt" / "lib" / "QtGui.framework" / "Versions" / "A" / "QtGui",
                 Path(QtGui.__file__).parent / "Qt" / "lib" / "libQt6Gui.so.6", Path(QtGui.__file__).parent / "Qt6Gui.dll"):
        if cand.exists():
            lib = ctypes.CDLL(str(cand))
            break
    fn = getattr(lib, "_ZN22QWindowSystemInterface24handleFocusWindowChangedINS_19SynchronousDeliveryEEEvP7QWindowN2Qt11FocusReasonE")
    fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_int], None
    fn(None, 7)
    QCoreApplication.processEvents()
    ui.wait_until(lambda: QGuiApplication.focusWindow() is None and not ui.win.isActive(), 3, "the window to be inactive")


def measure(ui, name, active=True):
    if active:
        ui._activate()
    else:
        inactive(ui)
    ui.settle(1200)
    n = frames(ui)
    print(f"IDLE {name:28s} {'active' if active else 'inactive':8s} {n:3d} frames in {MS / 1000:.0f} s", flush=True)
    return n


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    phone_dock(ui)
    ui.wait_until(lambda: ui.js("!!Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 60, "the build-up to end")
    toasts_gone(ui)
    ui.hover("viewport", 0.92, 0.95)          # the pointer rests on nothing that lights
    bad = []
    for mode in ("shape", "prove", "release", "document"):
        goto(ui, mode)
        ui.hover("viewport", 0.92, 0.95)
        for act in (True, False):
            n = measure(ui, mode, act)
            if n > 1:
                bad.append(f"{mode} ({'active' if act else 'inactive'}): {n}")
    goto(ui, "shape")
    # the column folded
    ui.run_js("Store.talkCalm = true"); ui.settle(700)
    ui.hover("viewport", 0.92, 0.95)
    for act in (True, False):
        n = measure(ui, "shape, column folded", act)
        if n > 1:
            bad.append(f"folded ({'active' if act else 'inactive'}): {n}")
    ui.run_js("Store.talkCalm = false"); ui.settle(700)
    ui.check(not bad, "a still workspace draws nothing: " + "; ".join(bad))

    # typing: the caret blinks, two steps a cycle (about 6 frames in 3 s), and not at all inactive
    ui._activate()
    ui.click("composer")
    ui.type("a bracket")
    ui.settle(900)
    n = frames(ui)
    print(f"IDLE {'typing (caret)':28s} active   {n:3d} frames in {MS / 1000:.0f} s", flush=True)
    ui.check(n <= 7, f"the caret alone redraws: {n} frames in 3 s")
    n = measure(ui, "typing (caret)", False)
    ui.check(n <= 1, f"an inactive window's caret does not blink: {n} frames")
