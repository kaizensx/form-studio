"""`form print ...`: print physics from the terminal. Prints JSON on standard output.

    form print orient <project> [--cosmetic X,Y,Z]... [--study ID | --load X,Y,Z] [--weights JSON] [--level 1|2|3]
                                [--calibrate] [--verify N] [--critical DEG] [--top N] [--free]
                                the Pareto front of print orientations: support, time, strength, surface, tip-over
    form print orient <project> --pick ID        write the chosen orientation to the design's print setup
    form print strength <project> --study ID [--orientation O] [--sweep a,b,... | --no-sweep] [--assume JSON]
    form print strength <project> --fix X,Y,Z --force X,Y,Z:FX,FY,FZ [--material KEY|JSON] [--orientation O] ...
                                a static strength study with a layered material in the print orientation: the
                                safety factor across the layers and in them, and how it changes with orientation
    form print strength <project>                the design's layered studies
    form print warp <project> [--orientation O] [--material M] [--chamber C] [--alpha 1/K] [--tg C] [--layer MM]
                                [--source TEXT]  the warp-risk indicator (never a predicted lift)

An orientation is as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from the front.
A face is a point on it, X,Y,Z in design millimetres. Exit 0 with a result, 1 on an error, 3 when a strength study
ran and did not converge.
"""
from __future__ import annotations

import json
import sys


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def _pt(text: str) -> list:
    v = [float(x) for x in text.split(",")]
    if len(v) != 3:
        raise ValueError(f"A point or direction is X,Y,Z: got “{text}”.")
    return v


def _take(args: list, flag: str, default=None, many: bool = False):
    out = []
    while flag in args:
        i = args.index(flag)
        if i + 1 >= len(args):
            raise ValueError(f"{flag} needs a value.")
        out.append(args[i + 1])
        del args[i:i + 2]
    return out if many else (out[-1] if out else default)


def _flag(args: list, flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def main(argv: list) -> int:
    from .. import config
    from ..studio import Studio, StudioError
    if not argv or argv[0] in ("-h", "--help", "help") or argv[0] not in ("orient", "strength", "warp") or len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 0 if argv and argv[0] in ("-h", "--help", "help") else 2
    cmd, pid, args = argv[0], argv[1], list(argv[2:])
    _flag(args, "--json")
    st = None
    try:
        st = Studio(config.load())
        from . import tools
        try:
            if cmd == "orient":
                pick = _take(args, "--pick", "")
                cos = [_pt(x) for x in _take(args, "--cosmetic", many=True)]
                load = _take(args, "--load")
                w = _take(args, "--weights")
                kw = dict(cosmetic=cos or None, study=_take(args, "--study", ""), load_direction=_pt(load) if load else None,
                          weights=json.loads(w) if w else None, level=int(_take(args, "--level", 2)),
                          calibrate=True if _flag(args, "--calibrate") else "auto", verify=int(_take(args, "--verify", 0)),
                          critical_deg=(lambda x: float(x) if x is not None else None)(_take(args, "--critical")),
                          pick=pick, top=int(_take(args, "--top", 8)), free=_flag(args, "--free"))
                if args:
                    raise ValueError(f"Unknown option “{args[0]}”.")
                _out(tools.orient_call(st, pid, **kw))
                return 0
            if cmd == "warp":
                num = lambda f: (lambda x: float(x) if x is not None else None)(_take(args, f))     # noqa: E731
                kw = dict(orientation=_take(args, "--orientation"), material=_take(args, "--material"), chamber_C=num("--chamber"),
                          alpha_per_K=num("--alpha"), tg_C=num("--tg"), layer_height_mm=num("--layer"), source=_take(args, "--source", ""))
                if args:
                    raise ValueError(f"Unknown option “{args[0]}”.")
                _out(tools.warp_call(st, pid, **kw))
                return 0
            # strength
            from ..fea import cli as fcli
            from ..fea import study as fstudy
            orientation = _take(args, "--orientation", "setup")
            sweep = _take(args, "--sweep")
            sweep = [] if _flag(args, "--no-sweep") else ([s for s in sweep.split(";") if s] if sweep else "auto")
            a = _take(args, "--assume")
            assume = json.loads(a) if a else None
            study = _take(args, "--study", "")
            again, full, norun = _flag(args, "--again"), _flag(args, "--full"), _flag(args, "--no-run")
            body = None
            if any(x in args for x in ("--fix", "--roller", "--pin", "--force", "--pressure", "--gravity", "--preload")):
                body, _opt = fcli.parse("static", args)
            elif args:
                raise ValueError(f"Unknown option “{args[0]}”.")
            r = tools.strength_call(st, pid, study, body, orientation, sweep, assume, (body or {}).get("name", ""), False, False, "you")
            if "studies" in r or norun:
                _out(r)
                return 0
            sid = r["study"]["id"]
            res = fstudy.run(st, pid, sid, force=again, on_progress=fcli._progress)
            from ..fea import tools as ftools
            out = res.get("result") or {}
            _out({"study": res["study"], "state": res["state"], "result": ftools.digest(out, full),
                  "cached": bool(res.get("cached")), "material_note": r.get("material_note")})
            return 0 if out.get("converged") else 3
        except (ValueError, json.JSONDecodeError) as e:
            raise StudioError(str(e), "form print --help shows the options.") from None
    except StudioError as e:
        _out({"error": e.public()})
        return 1
    finally:
        try:
            if st is not None:
                st.kernel.shutdown()
        except Exception:                                # noqa: BLE001
            pass
