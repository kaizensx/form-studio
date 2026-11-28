"""`form strength ...` (and `form study strength|static|modal|buckling ...`): strength studies from the terminal.

    form strength static <project> --fix X,Y,Z --force X,Y,Z:FX,FY,FZ [--material AL-6061]
    form strength modal <project> [--fix X,Y,Z] [--modes 6] [--material KEY]
    form strength buckling <project> --fix X,Y,Z --force X,Y,Z:FX,FY,FZ
    form strength thermal <project> --temperature X,Y,Z:80 --convection X,Y,Z:10:20      steady heat
    form strength thermal_stress <project> --roller X,Y,Z ... --temperature X,Y,Z:80 [--reference 20]
    form strength run <project> <study> [--again]      solve a saved study (again after a change)
    form strength list <project>                        the design's studies with their states
    form strength show <project> <study> [--full] [--field]
    form strength remove <project> <study>
    form strength verify [case ...]                     the verification suite (docs/STRENGTH.md), in the engine's Python

A face is a point on it, X,Y,Z in design millimetres (each part as printed). Options, each repeatable:
    --fix X,Y,Z          a fixed face            --roller X,Y,Z   a face that slides in its plane (symmetry)
    --pin X,Y,Z          a cylindrical face that may turn about its axis
    --force X,Y,Z:FX,FY,FZ       newtons on that face     --pressure X,Y,Z:MPa
    --preload X,Y,Z:X,Y,Z:N      a bolt's clamping force between two faces
    --gravity [G[:DX,DY,DZ]]     1 g downwards (-Z) by default
    --temperature X,Y,Z:C        a face held at a temperature     --convection X,Y,Z:H:AMBIENT   W/(m2 K), deg C
    --heat X,Y,Z:W               watts into a face                --heat-flux X,Y,Z:W_M2
    --reference C                the stress-free temperature of a thermal_stress study (20)
    --material KEY | JSON        a materials-library key, or {"E_GPa", "poisson", "yield_MPa", "density_kg_m3",
                                 "k_W_mK", "cte_per_K", "source"}
    --mesh JSON          {"h0", "levels_max", "dof_max", "budget_s", "tol_stress", "tol_disp", "singular_radius"}
    --name NAME   --study ID (replace that study)   --no-run (save only)   --again (solve even if current)   --full

Prints JSON on standard output; progress goes to standard error. Exit 0 with a result (converged or not: read
"converged"), 1 on an error, 3 when the study ran and did not converge.
"""
from __future__ import annotations

import json
import subprocess
import sys

KINDS = ("static", "modal", "buckling", "thermal", "thermal_stress")


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def _pt(text: str, what: str) -> list:
    try:
        v = [float(x) for x in text.split(",")]
    except ValueError:
        v = []
    if len(v) != 3:
        raise ValueError(f"{what} is X,Y,Z (three numbers, millimetres or newtons): got “{text}”.")
    return v


def parse(kind: str, args: list) -> tuple[dict, dict]:
    """(definition, options) from the command line. Raises ValueError with a sentence."""
    body = {"kind": kind, "fixtures": [], "loads": [], "material": None, "mesh": {}, "name": "", "thermal": []}
    opt = {"study": "", "run": True, "again": False, "full": False}
    i = 0

    def val(flag):
        nonlocal i
        i += 1
        if i >= len(args):
            raise ValueError(f"{flag} needs a value.")
        return args[i]
    while i < len(args):
        a = args[i]
        if a in ("--fix", "--roller", "--pin"):
            body["fixtures"].append({"type": {"--fix": "fixed", "--roller": "roller", "--pin": "pin"}[a],
                                     "faces": [_pt(val(a), f"The face of {a}")]})
        elif a == "--force":
            f, _, v = val(a).partition(":")
            body["loads"].append({"type": "force", "faces": [_pt(f, "The face of --force")], "vector": _pt(v, "The force")})
        elif a == "--pressure":
            f, _, v = val(a).partition(":")
            body["loads"].append({"type": "pressure", "faces": [_pt(f, "The face of --pressure")], "value_MPa": float(v)})
        elif a == "--preload":
            parts = val(a).split(":")
            if len(parts) != 3:
                raise ValueError("--preload is X,Y,Z:X,Y,Z:N (two faces and the clamping force in newtons).")
            body["loads"].append({"type": "preload", "faces": [_pt(parts[0], "The first face of --preload")],
                                  "faces_b": [_pt(parts[1], "The second face of --preload")], "force_N": float(parts[2])})
        elif a == "--gravity":
            g, d = 1.0, [0.0, 0.0, -1.0]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                gs, _, ds = val(a).partition(":")
                g = float(gs)
                d = _pt(ds, "The direction of gravity") if ds else d
            body["loads"].append({"type": "gravity", "g": g, "direction": d})
        elif a == "--temperature":
            f, _, v = val(a).partition(":")
            body["thermal"].append({"type": "temperature", "faces": [_pt(f, "The face of --temperature")], "value_C": float(v)})
        elif a == "--convection":
            parts = val(a).split(":")
            if len(parts) != 3:
                raise ValueError("--convection is X,Y,Z:H:AMBIENT (W/(m2 K) and deg C).")
            body["thermal"].append({"type": "convection", "faces": [_pt(parts[0], "The face of --convection")],
                                    "h_W_m2K": float(parts[1]), "ambient_C": float(parts[2])})
        elif a in ("--heat", "--heat-flux"):
            f, _, v = val(a).partition(":")
            body["thermal"].append({"type": "heat" if a == "--heat" else "heat_flux", "faces": [_pt(f, f"The face of {a}")],
                                    "value": float(v)})
        elif a == "--reference":
            body["reference_C"] = float(val(a))
        elif a == "--material":
            m = val(a)
            body["material"] = json.loads(m) if m.strip().startswith("{") else m
        elif a == "--mesh":
            body["mesh"] = json.loads(val(a))
        elif a == "--modes":
            body["modes"] = int(val(a))
        elif a == "--name":
            body["name"] = val(a)
        elif a == "--study":
            opt["study"] = val(a)
        elif a == "--no-run":
            opt["run"] = False
        elif a in ("--again", "--force-run"):
            opt["again"] = True
        elif a == "--full":
            opt["full"] = True
        elif a == "--json":
            pass
        else:
            raise ValueError(f"Unknown option “{a}”.")
        i += 1
    return body, opt


def _progress(ev) -> None:
    f = ev.get("fraction")
    print(f"  {ev.get('progress')}" + (f" ({100 * f:.0f} %)" if isinstance(f, (int, float)) else ""), file=sys.stderr, flush=True)


def _solve(st, pid: str, sid: str, again: bool, full: bool) -> int:
    from . import study, tools
    r = study.run(st, pid, sid, force=again, on_progress=_progress)
    p = st.load(pid)
    path = study.field_path(st, p, sid)
    res = r.get("result") or {}
    _out({"study": r["study"], "state": r["state"], "result": tools.digest(res, full), "cached": bool(r.get("cached")),
          "field_file": str(path) if path else None})
    return 0 if res.get("converged") else 3


def verify(args: list) -> int:
    """Run the verification suite in the FEA engine's Python and print its JSON report."""
    from .. import config, engines
    from . import HOW_TO_GET, python
    py = python(config.load())
    if py is None:
        _out({"error": {"message": "The strength solver is not installed, so the verification suite cannot run.",
                        "hint": HOW_TO_GET}})
        return 1
    env = engines.child_env() if str(py) != sys.executable else None
    if env is None:
        import os
        env = {**os.environ, "PYTHONPATH": str(engines.src_root()) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    r = subprocess.run([str(py), "-m", "form.fea.verify", "--json", *args], env=env, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode not in (0, 1) or not r.stdout.strip():
        _out({"error": {"message": "The verification suite did not run.", "hint": (r.stderr or "")[-600:]}})
        return 1
    print(r.stdout)
    return r.returncode


def main(argv: list) -> int:
    from .. import config
    from ..studio import Studio, StudioError
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if argv else 2
    cmd, args = argv[0], argv[1:]
    if cmd == "verify":
        return verify(args)
    if cmd not in KINDS + ("run", "list", "show", "remove") or not args:
        print(__doc__, file=sys.stderr)
        return 2
    from . import study, tools
    pid, rest = args[0], args[1:]
    try:
        st = Studio(config.load())
        p = st.load(pid)
        if cmd == "list":
            from . import python
            _out({"project": pid, "studies": study.listing(st, p), "engine_installed": python(st.cfg) is not None})
            return 0
        if cmd in ("run", "show", "remove"):
            if not rest or rest[0].startswith("--"):
                raise StudioError(f"form strength {cmd} <project> <study>", "form strength list <project> names them.")
            sid, flags = rest[0], rest[1:]
            if cmd == "remove":
                _out(study.remove(st, p, sid))
                return 0
            if cmd == "show":
                _out(tools.read_call(st, pid, sid, 0, "--field" in flags, "--full" in flags, False))
                return 0
            return _solve(st, pid, sid, "--again" in flags or "--force-run" in flags, "--full" in flags)
        try:
            body, opt = parse(cmd, rest)
        except (ValueError, json.JSONDecodeError) as e:
            raise StudioError(str(e), "form strength --help shows the options.") from None
        d = study.define(st, p, body, by="you", sid=opt["study"] or None)
        if not opt["run"]:
            _out({"study": d, "state": study.state(st, st.load(pid), d["id"])})
            return 0
        return _solve(st, pid, d["id"], opt["again"], opt["full"])
    except StudioError as e:
        _out({"error": e.public()})
        return 1
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                                # noqa: BLE001
            pass
