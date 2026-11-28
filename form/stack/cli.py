"""`form stack ...`: tolerance stack-up from the terminal. Prints JSON.

    form stack run <project> --a X,Y,Z[@part] --b X,Y,Z[@part] [options]   a stack, nothing saved
    form stack add <project> --a ... --b ... --name N [options]            kept with the design, computed for the head
    form stack list <project>                                              every kept stack with its state
    form stack show <project> <id>                                         a kept stack's stored result
    form stack rerun <project> <id>                                        compute a kept stack for the head
    form stack rm <project> <id>                                           forget a kept stack

Options:
    --a / --b X,Y,Z[@part]       a point on each face of the gap, as built (the frame selections use); --assembled
                                 reads both points in the assembled frame. --a-face I / --b-face I: a model face index
    --dir X,Y,Z                  the gap's direction (default: face A's outward normal)
    --tol KEY=T | KEY=LO:HI      a tolerance (KEY is a parameter, or part:parameter); repeat it
    --dist KEY=normal|uniform    a contributor's distribution
    --spec LO,HI                 the gap's limits (either may be "-" for open); default LO 0, assumed
    --temps TMIN,TMAX            temperature span in °C;  --alpha PART=1/K for a part with no sourced expansion
    --samples N --seed S         Monte Carlo
    --brief                      only the headline, the chart and the suggestions

    form stack run box-lid --a 100,0,0@screw --b 0,0,8 --tol screw_l=0.2 --tol lid_t=0.1 --spec 0.5,-
Exit 0 with a result, 2 on an error.
"""
from __future__ import annotations

import json
import sys


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def _pt(text: str) -> list:
    v = [float(x) for x in text.split(",")]
    if len(v) != 3:
        raise ValueError(f"A point or a direction is X,Y,Z: got “{text}”.")
    return v


def _pick(text: str, assembled: bool) -> dict:
    pt, _, part = text.partition("@")
    out = {"at": _pt(pt)}
    if part:
        out["part"] = part
    if assembled:
        out["frame"] = "assembled"
    return out


def parse(args: list) -> dict:
    d = {"tolerances": {}, "dist": {}, "alpha": {}}
    assembled = "--assembled" in args
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--assembled", "--brief"):
            i += 1
            continue
        if i + 1 >= len(args):
            raise ValueError(f"{a} needs a value.")
        v = args[i + 1]
        if a in ("--a", "--b"):
            d[a[2:]] = _pick(v, assembled)
        elif a in ("--a-face", "--b-face"):
            d[a[2]] = {"face": int(v)}
        elif a == "--dir":
            d["direction"] = _pt(v)
        elif a == "--tol":
            k, _, t = v.partition("=")
            if ":" in t.lstrip("-") and t.count(":") == 1:
                lo, hi = t.split(":")
                d["tolerances"][k] = [float(lo), float(hi)]
            else:
                d["tolerances"][k] = float(t)
        elif a == "--dist":
            k, _, t = v.partition("=")
            d["dist"][k] = t
        elif a == "--alpha":
            k, _, t = v.partition("=")
            d["alpha"][k] = float(t)
        elif a == "--spec":
            lo, hi = v.split(",")
            d["spec"] = [None if lo.strip() in ("-", "") else float(lo), None if hi.strip() in ("-", "") else float(hi)]
        elif a == "--temps":
            lo, hi = v.split(",")
            d["t_min"], d["t_max"] = float(lo), float(hi)
        elif a in ("--samples", "--seed"):
            d[a[2:]] = int(v)
        elif a == "--name":
            d["name"] = v
        else:
            raise ValueError(f"Unknown option {a}.")
        i += 2
    return {k: v for k, v in d.items() if v not in ({}, None)}


def _brief(r: dict) -> dict:
    return {k: r.get(k) for k in ("headline", "chart", "suggestions", "caveats", "thermal", "spec", "capability")}


def main(argv: list) -> int:
    from . import tools
    from .. import config
    from ..studio import Studio, StudioError
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if argv else 2
    cmd = argv[0]
    if cmd not in ("run", "add", "list", "show", "rerun", "rm") or len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    st = Studio(config.load())
    try:
        pid = argv[1]
        if cmd == "list":
            _out(tools.read(st, pid))
        elif cmd in ("show", "rerun", "rm"):
            if len(argv) < 3:
                raise ValueError(f"form stack {cmd} <project> <id>")
            if cmd == "show":
                _out(tools.read(st, pid, argv[2]))
            elif cmd == "rerun":
                _out(tools.call(st, pid, stack=argv[2]))
            else:
                from . import remove
                remove(st, pid, argv[2])
                _out({"removed": argv[2]})
        else:
            d = parse(argv[2:])
            r = tools.call(st, pid, save=(cmd == "add"), **d)
            _out(_brief(r) if "--brief" in argv else r)
        return 0
    except (StudioError, ValueError) as e:
        _out({"error": str(e), "hint": getattr(e, "hint", "")})
        return 2
    finally:
        try:
            st.kernel.stop()
        except Exception:                  # noqa: BLE001
            pass
