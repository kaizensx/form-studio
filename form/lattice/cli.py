"""`form lattice ...`: lattices and TPMS infill from the terminal. Prints JSON.

    form lattice list                                              the cells
    form lattice props KIND key=value ... [--verify]               what a cell is worth (nothing saved)
    form lattice fill <project> KIND key=value ... [--verify]      put it in a design: a new revision
    form lattice show <project> [--process P] [--verify]           the lattice a design carries, with its numbers
    form lattice remove <project>                                  take it out

Keys: cell=8 density=0.2 | wall=0.8 | strut_d=1.0  form=sheet|network  skin=1.2  node=1.25  output=auto|brep|mesh
      resolution=14  material=PA12  process=fdm|sla|sls|mjf|lpbf  nozzle=0.4  study=ID
      region=x0,y0,z0:x1,y1,z1        grading='{"mode": "distance", "from": "boundary", "over": 10, "density": [0.4, 0.1]}'

    form lattice props gyroid cell=8 density=0.2 material=AL-6061 process=lpbf --verify
    form lattice fill bracket octet cell=8 strut_d=1.0 skin=1.2 process=sls
Exit 0 with a result, 2 on an error.
"""
from __future__ import annotations

import json
import sys

NUM = ("cell", "density", "wall", "strut_d", "skin", "node", "nozzle")


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def parse(args: list) -> dict:
    d: dict = {}
    for a in args:
        if a == "--verify":
            d["verify"] = True
            continue
        if "=" not in a:
            raise ValueError(f"“{a}” is not key=value.")
        k, _, v = a.partition("=")
        if k in NUM:
            d[k] = float(v)
        elif k == "resolution":
            d[k] = int(v)
        elif k == "region":
            lo, _, hi = v.partition(":")
            d[k] = {"min": [float(x) for x in lo.split(",")], "max": [float(x) for x in hi.split(",")]}
        elif k == "grading":
            d[k] = json.loads(v)
        elif k in ("form", "output", "material", "process", "study"):
            d[k] = v
        else:
            raise ValueError(f"Unknown key {k}.")
    return d


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if argv else 2
    from . import tools
    cmd = argv[0]
    try:
        if cmd == "list":
            _out(tools.catalogue())
            return 0
        if cmd == "props":
            if len(argv) < 2:
                raise ValueError("form lattice props KIND key=value ...")
            _out(tools.props(argv[1], **{"cell": 8.0, **parse(argv[2:])}))
            return 0
    except ValueError as e:
        _out({"error": str(e), "hint": getattr(e, "hint", "")})
        return 2
    except Exception as e:                                    # noqa: BLE001 - StudioError without a Studio
        if type(e).__name__ != "StudioError":
            raise
        _out({"error": str(e), "hint": getattr(e, "hint", "")})
        return 2
    if cmd not in ("fill", "show", "remove") or len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    from .. import config
    from ..studio import Studio, StudioError
    st = Studio(config.load())
    try:
        pid = argv[1]
        if cmd == "remove":
            _out(tools.fill(st, pid, remove=True, by="you"))
        elif cmd == "show":
            _out(tools.fill(st, pid, **{k: v for k, v in parse(argv[2:]).items() if k in ("material", "process", "nozzle", "verify")}))
        else:
            if len(argv) < 3:
                raise ValueError("form lattice fill <project> KIND key=value ...")
            _out(tools.fill(st, pid, argv[2], by="you", **parse(argv[3:])))
        return 0
    except (StudioError, ValueError) as e:
        _out({"error": str(e), "hint": getattr(e, "hint", "")})
        return 2
    finally:
        try:
            st.kernel.stop()
        except Exception:                                     # noqa: BLE001
            pass
