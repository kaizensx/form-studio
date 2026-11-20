"""Shared plumbing for form.craft: typed arguments, kernel attempts with fallbacks, and the notes they leave.

Every helper in form.craft takes plain numbers in mm and degrees, checks them before touching the kernel, and raises a
RecipeError (message, feature, hint, params) that names what to change. When the first way of building a shape fails
(a loft that twists, a fillet that does not fit), the helper tries the documented fallback and records a note:

    from form import craft
    body = craft.safe_fillet(body, body.edges().filter_by(Axis.Z), 4)
    craft.notes()        # ["safe_fillet: 4 mm did not fit; used 3 mm"]

notes() returns and clears the notes of the current build. A design can put them in derived() or statics() so the
person sees which fallback was taken; they are never hidden.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable

from ..recipes.base import RecipeError

_NOTES: list[str] = []


def note(text: str) -> None:
    if text not in _NOTES:
        _NOTES.append(text)


def notes(clear: bool = True) -> list[str]:
    out = list(_NOTES)
    if clear:
        _NOTES.clear()
    return out


def fail(message: str, hint: str = "", params: Iterable[str] | None = None, feature: str = "") -> RecipeError:
    return RecipeError(message, feature, hint, list(params or []))


def need(cond: bool, message: str, hint: str = "", params: Iterable[str] | None = None, feature: str = "") -> None:
    if not cond:
        raise fail(message, hint, params, feature)


def num(x: Any, name: str, lo: float | None = None, hi: float | None = None, positive: bool = False,
        integer: bool = False) -> float:
    """x as a finite float (or int), inside [lo, hi]. Raises a RecipeError that names the argument."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        try:
            x = float(x)
        except (TypeError, ValueError):
            raise fail(f"{name} must be a number (got {x!r})", f"Pass {name} in mm or degrees as a number.", [name])
    x = float(x)
    if not math.isfinite(x):
        raise fail(f"{name} is not finite", f"Pass a finite {name}.", [name])
    if positive and x <= 0:
        raise fail(f"{name} must be greater than 0 (got {x:g})", f"Give {name} a positive value.", [name])
    if lo is not None and x < lo - 1e-9:
        raise fail(f"{name} = {x:g} is below {lo:g}", f"Use {name} >= {lo:g}.", [name])
    if hi is not None and x > hi + 1e-9:
        raise fail(f"{name} = {x:g} is above {hi:g}", f"Use {name} <= {hi:g}.", [name])
    if integer:
        if abs(x - round(x)) > 1e-9:
            raise fail(f"{name} must be a whole number (got {x:g})", f"Round {name}.", [name])
        return int(round(x))
    return x


def pts2(points: Any, name: str = "points", min_n: int = 2) -> list[tuple[float, float]]:
    try:
        out = [(float(p[0]), float(p[1])) for p in points]
    except (TypeError, ValueError, IndexError):
        raise fail(f"{name} must be a list of (x, y) pairs", f"Pass {name} as [(x, y), ...] in mm.", [name])
    need(len(out) >= min_n, f"{name} needs at least {min_n} points (got {len(out)})", f"Add points to {name}.", [name])
    return out


def ok(shape: Any) -> bool:
    """A usable solid result: valid, positive volume."""
    try:
        return shape is not None and shape.is_valid and len(shape.solids()) >= 1 and shape.volume > 1e-9
    except Exception:
        return False


def one(shape: Any):
    """The single Solid of a Part/Compound result (or the shape itself when it is already one solid or many)."""
    try:
        s = shape.solids()
        return s[0] if len(s) == 1 else shape
    except Exception:
        return shape


def attempt(what: str, tries: list[tuple[str, Callable[[], Any]]], hint: str, params: Iterable[str] | None = None,
            check: Callable[[Any], bool] = ok):
    """Run tries in order; return the first result that passes check. A fallback (any try after the first) leaves a
    note. When every try fails, raise one RecipeError listing what each attempt did."""
    errors = []
    for i, (label, fn) in enumerate(tries):
        try:
            r = fn()
        except RecipeError:
            raise
        except Exception as e:                       # the kernel's own exceptions: Standard_Failure, ValueError, ...
            errors.append(f"{label}: {type(e).__name__}")
            continue
        if check(r):
            if i:
                note(f"{what}: {tries[0][0]} failed; used {label}")
            return r
        errors.append(f"{label}: invalid result")
    raise fail(f"{what} could not be built ({'; '.join(errors)})", hint, params)
