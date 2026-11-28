"""`form generate ...`: mesh generators from the terminal. Prints JSON.

    form generate list                                   every generator, whether it is ready and what it needs
    form generate enable meshy | disable meshy           turn a generator on or off (yours to decide)
    form generate trellis2 /path/to/TRELLIS.2 [--python PY]   use a TRELLIS.2 you installed (its licence is checked)
    form generate run <provider> --text "a desk lamp" | --image photo.png [--size 80] [--name N] [--yes]
                                                         generate, split into parts, rebuild as an editable design
    form generate cad <mesh file> [--size 80] [--label L]   the second half alone: a mesh you have, into parts and CAD

Before a hosted run the disclosure (what is sent, to which host, billed to whom) is printed and you are asked;
--yes answers it for you. Keys are stored with `form secrets set meshy_api_key` (or in Settings > Agents).
"""
from __future__ import annotations

import json
import sys


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def main(argv: list) -> int:
    from .. import config
    from . import DEFAULT_SIZE_MM, GenerateError, disclose, enable, providers, set_trellis
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if argv else 2
    cfg = config.load()
    cmd, args = argv[0], argv[1:]
    opt = {"text": None, "image": None, "size": DEFAULT_SIZE_MM, "name": "", "python": "", "label": "", "yes": False}
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--yes":
            opt["yes"] = True
        elif a in ("--text", "--image", "--size", "--name", "--python", "--label"):
            i += 1
            if i >= len(args):
                _out({"error": {"message": f"{a} needs a value."}})
                return 2
            opt[a[2:]] = float(args[i]) if a == "--size" else args[i]
        else:
            pos.append(a)
        i += 1
    try:
        if cmd == "list":
            _out(providers(cfg))
            return 0
        if cmd in ("enable", "disable") and pos:
            _out(enable(cfg, pos[0], cmd == "enable"))
            return 0
        if cmd == "trellis2" and pos:
            _out(set_trellis(cfg, pos[0], opt["python"]))
            return 0
        if cmd not in ("run", "cad") or not pos:
            print(__doc__, file=sys.stderr)
            return 2
        from ..studio import Studio, StudioError
        st = Studio(cfg)
        try:
            if cmd == "cad":
                from . import to_cad
                _out(to_cad(st, pos[0], opt["label"] or "a mesh you gave", opt["size"], name=opt["name"]))
                return 0
            d = disclose(cfg, pos[0], opt["text"], opt["image"])
            if not d["ready"]:
                _out({"ran": False, "why": d["why"]})
                return 2
            print(d["text"], file=sys.stderr)
            if d["kind"] == "hosted" and not opt["yes"]:
                if not sys.stdin.isatty() or input("Send it? [y/N] ").strip().lower() not in ("y", "yes"):
                    _out({"ran": False, "why": "Not sent: you did not agree.", "disclosure": d})
                    return 2
            from . import make
            _out({"ran": True, **make(st, pos[0], opt["text"], opt["image"], d["consent"], opt["size"], name=opt["name"])})
            return 0
        except StudioError as e:
            _out({"error": e.public()})
            return 2
        finally:
            try:
                st.kernel.shutdown()
            except Exception:                            # noqa: BLE001
                pass
    except GenerateError as e:
        _out({"error": e.public()})
        return 2
