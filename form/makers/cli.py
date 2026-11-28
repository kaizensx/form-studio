"""`form make ...`: the makers' generators from the terminal. Prints JSON.

    form make list                                          every generator with its presets and inputs
    form make <generator> [preset] [key=value ...] [--text T] [--image FILE] [--name NAME] [--purpose print|model]

    form make name_tag keychain --text "MAYA" cap_h=9
    form make lithophane --image photo.jpg width=120
    form make gridfinity tray grid_x=3
    form make knob shaft_d=6.35 flat=0
    form make hinge_box inner_w=90
    form make threaded_jar iso
    form make spur_gears 1:3 module=1.5

The design is built in the kernel and saved; `form render <project> --view sheet` looks at it, `form run <project>`
checks and slices a print design. Exit 0 on success, 2 on an error.
"""
from __future__ import annotations

import json
import sys


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def parse(argv: list) -> dict:
    from . import get
    g = get(argv[0])
    opt = {"gid": g.id, "preset": "", "values": {}, "text": None, "image": None, "name": "", "purpose": None}
    i, args = 0, argv[1:]
    while i < len(args):
        a = args[i]
        if a in ("--text", "--image", "--name", "--purpose", "--preset"):
            i += 1
            if i >= len(args):
                raise ValueError(f"{a} needs a value.")
            opt[a[2:]] = args[i]
        elif "=" in a and not a.startswith("-"):
            k, v = a.split("=", 1)
            try:
                opt["values"][k.strip()] = float(v)
            except ValueError:
                raise ValueError(f"{k} = {v!r} is not a number.") from None
        elif not a.startswith("-") and not opt["preset"] and a in g.presets:
            opt["preset"] = a
        else:
            raise ValueError(f"Did not understand “{a}”. Presets: {', '.join(g.presets)}; parameters are key=value.")
        i += 1
    return opt


def main(argv: list) -> int:
    from . import MakeError, catalogue
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if argv else 2
    if argv[0] == "list":
        _out({"generators": catalogue()})
        return 0
    try:
        opt = parse(argv)
    except (MakeError, ValueError) as e:
        _out({"error": {"message": str(e), "hint": getattr(e, "hint", "") or "form make --help"}})
        return 2
    from .. import config
    from ..studio import Studio, StudioError
    from . import make
    st = Studio(config.load())
    try:
        _out(make(st, opt["gid"], opt["values"], opt["text"], opt["image"], opt["preset"], opt["name"], opt["purpose"]))
        return 0
    except MakeError as e:
        _out({"error": {"message": str(e), "hint": e.hint, "params": e.params}})
        return 2
    except StudioError as e:
        _out({"error": e.public()})
        return 2
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                                    # noqa: BLE001
            pass
