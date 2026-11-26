"""Write form/preflight_api.json: the names and call signatures of what a design source may call.

    .venv/bin/python scripts/gen_preflight_api.py [--check]

form/preflight.py checks a source's imports, calls and keyword arguments against this snapshot without importing
the kernel. It is read from the installed build123d and from form.craft, form.parts and form.patterns; the snapshot
records the build123d version it was read from, and preflight only treats a mismatch as an error when the installed
version is that one. --check exits 1 when the file on disk differs (tests/test_preflight.py runs it).
"""
from __future__ import annotations

import enum
import inspect
import json
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "form" / "preflight_api.json"


def sig(obj):
    """{"params": [...], "kw": accepts any keyword, "pos": max positional or None} or None when it cannot be read."""
    try:
        target = obj.__init__ if inspect.isclass(obj) else obj
        s = inspect.signature(target)
    except (TypeError, ValueError):
        return None
    ps = list(s.parameters.values())
    if inspect.isclass(obj) and ps and ps[0].name == "self":
        ps = ps[1:]
    if inspect.isclass(obj) and (obj.__init__ is object.__init__ or getattr(obj, "__new__", None) is not object.__new__
                                 and obj.__init__ is object.__init__):
        return None
    names = [p.name for p in ps if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    kwonly = [p.name for p in ps if p.kind is p.KEYWORD_ONLY]
    posonly = [p.name for p in ps if p.kind is p.POSITIONAL_ONLY]
    var_kw = any(p.kind is p.VAR_KEYWORD for p in ps)
    var_pos = any(p.kind is p.VAR_POSITIONAL for p in ps)
    return {"params": [n for n in names if n not in posonly], "kw": var_kw,
            "pos": None if var_pos else len(names) - len(kwonly)}


def module_names(mod, names=None) -> dict:
    out = {}
    for n in sorted(names or [x for x in dir(mod) if not x.startswith("_")]):
        try:
            o = getattr(mod, n)
        except Exception:                                  # noqa: BLE001 - a lazy name that needs something missing
            continue
        if inspect.ismodule(o):
            out[n] = {"kind": "module"}
        elif inspect.isclass(o) and issubclass(o, enum.Enum):
            out[n] = {"kind": "enum", "members": sorted(o.__members__)}
        elif inspect.isclass(o) or callable(o):
            multi = hasattr(o, "dispatch") or hasattr(o, "registry") or type(o).__name__ in ("multimethod", "multidispatch")
            s = None if multi else sig(o)
            out[n] = {"kind": "class" if inspect.isclass(o) else "function", **({"sig": s} if s else {})}
        else:
            out[n] = {"kind": "value"}
    return out


def snapshot() -> dict:
    import build123d
    from form import craft, parts, patterns
    return {"build123d_version": metadata.version("build123d"),
            "modules": {"build123d": module_names(build123d),
                        "form.craft": module_names(craft, dir(craft)),
                        "form.parts": module_names(parts),
                        "form.patterns": module_names(patterns)}}


def main(argv=None) -> int:
    text = json.dumps(snapshot(), indent=0, sort_keys=True) + "\n"
    if "--check" in (argv or sys.argv[1:]):
        return 0 if OUT.is_file() and OUT.read_text(encoding="utf-8") == text else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
