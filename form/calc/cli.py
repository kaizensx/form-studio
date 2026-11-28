"""`form calc ...`: the engineering calculators from the terminal. Prints JSON.

    form calc list                               the calculators, with every input and its unit
    form calc <calculator> key=value ...         a sheet: every number with its evidence, equation and source
        --build [--name NAME]                    also write the geometry as a new design
        --project P --at X,Y,Z --normal X,Y,Z    put the snap hook or insert boss on a face of design P
        --fea                                    with --build: define the strength study that checks a snap hook
    form calc show <project>                     the sheet of a design a calculator wrote, for its head revision
    form calc verify [--geometry]                the worked examples (and, with --geometry, the solids measured)

    form calc snapfit material=PETG length=15 width=6 undercut=1 mu=0.3
    form calc spring wire_d=1.6 mean_d=14 active=6 force=40 wire=music --build
    form calc fastener axial=2000 shear=1500 mu_interface=0.15 plate_material=AL-6061 into=tapped
    form calc gear module=2 z1=14 z2=30 x1=0.3 torque=800 material=POM
    form calc fit fit=H7/g6 diameter=25 hole_material=AL-6061 shaft_material=STAINLESS t_min=-20 t_max=80

Calculators: snapfit, hinge, spring, fastener, gear, cam, fit. Values are numbers where they parse as numbers, words
otherwise. Exit 0 with a sheet (read "status": PASS, WARN or FAIL), 1 when verify fails, 2 on an error.
"""
from __future__ import annotations

import json
import sys


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def _value(text: str):
    try:
        f = float(text)
    except ValueError:
        return text
    return int(f) if f.is_integer() and text.lstrip("+-").isdigit() else f


def _pt(text: str) -> list:
    v = [float(x) for x in text.split(",")]
    if len(v) != 3:
        raise ValueError(f"A point or a direction is X,Y,Z: got “{text}”.")
    return v


def main(argv: list) -> int:
    from . import CALCULATORS, CalcError, catalogue, run
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if argv else 2
    cmd, args = argv[0], argv[1:]
    if cmd == "list":
        _out({"calculators": catalogue()})
        return 0
    if cmd == "verify":
        from . import verify
        rows = verify.examples()
        out = {"examples": rows, "summary": {k: v for k, v in verify.summary(rows).items() if k != "failed"}}
        ok = all(r["pass"] for r in rows)
        if "--geometry" in args:
            g = verify.geometry()
            out["geometry"] = g
            out["geometry_summary"] = {k: v for k, v in verify.summary(g).items() if k != "failed"}
            ok = ok and all(r["pass"] for r in g)
        _out(out)
        return 0 if ok else 1
    inputs, opt, i = {}, {"build": False, "name": "", "project": "", "at": None, "normal": None, "fea": False}, 0
    try:
        while i < len(args):
            a = args[i]
            if a in ("--build", "--fea"):
                opt[a[2:]] = True
            elif a in ("--name", "--project", "--at", "--normal"):
                i += 1
                if i >= len(args):
                    raise ValueError(f"{a} needs a value.")
                opt[a[2:]] = _pt(args[i]) if a in ("--at", "--normal") else args[i]
            elif "=" in a and not a.startswith("-"):
                k, v = a.split("=", 1)
                inputs[k.strip().replace("-", "_")] = _value(v.strip())
            elif cmd == "show" and not opt["project"]:
                opt["project"] = a
            else:
                raise ValueError(f"Did not understand “{a}”. Inputs are key=value.")
            i += 1
        if cmd == "show":
            if not opt["project"]:
                raise ValueError("form calc show <project>")
        elif cmd not in CALCULATORS:
            raise ValueError(f"Unknown calculator “{cmd}”. Calculators: {', '.join(CALCULATORS)}.")
        if cmd != "show" and not (opt["build"] or opt["project"]):
            _out(run(cmd, inputs))                           # nothing saved: no studio, no kernel
            return 0
    except CalcError as e:
        _out({"error": e.public()})
        return 2
    except ValueError as e:
        _out({"error": {"message": str(e), "hint": "form calc --help"}})
        return 2
    from .. import config
    from ..studio import Studio, StudioError
    from . import tools
    st = Studio(config.load())
    try:
        _out(tools.call(st, "" if cmd == "show" else cmd, inputs, opt["build"], opt["name"], opt["project"], opt["at"],
                        opt["normal"], None, None, opt["fea"], "you"))
        return 0
    except StudioError as e:
        _out({"error": e.public()})
        return 2
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                                    # noqa: BLE001
            pass
