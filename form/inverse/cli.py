"""`form optimize pareto ...` and `form optimize topology ...`: inverse design and topology optimisation from the
terminal. Both print JSON on standard output; progress goes to standard error.

    form optimize pareto <project> --minimize mass_g [--minimize fea.max_displacement_mm] [--maximize METRIC]
                         [--require "fea.safety_factor>=3"] [--vary t:3:10] [--study ID] [--modal-study ID]
                         [--solves 24] [--seconds 900] [--evaluations N] [--per-kg 25] [--full]
    form optimize pareto <project> --show [RUN] [--full]         the stored search (the newest)
    form optimize pareto <project> --save INDEX[:NAME] [--run RUN]   keep a point as a named variant
    form optimize pareto --verify                                 the search on ZDT1 and ZDT2 against the known fronts

    form optimize topology <project> [--volfrac 0.5 | --mass G | --safety-factor 3] [--study ID]
                         [--mode pockets|free] [--pull z] [--h MM] [--rmin MM] [--keep MM] [--rim MM]
                         [--max-iter 80] [--budget 240] [--tries 3] [--full]
    form optimize topology <project> --show [RUN] [--full] [--frames]
    form optimize topology <project> --apply [RUN] [--as-new NAME] [--mesh-body] [--expect-head N]
    form optimize topology --verify                               SIMP on the MBB beam against the published values

`form optimize <project> --vary ... --minimize ...` (one objective, no subcommand) is the goal seek it always was.
Exit 0 with a result, 1 on an error, 3 when a search found nothing that meets the requirements or a topology run
ended without verified features.
"""
from __future__ import annotations

import json
import subprocess
import sys


def _out(d) -> None:
    print(json.dumps(d, indent=1, ensure_ascii=False, default=str))


def _flags(args: list, spec: dict) -> tuple:
    """spec: {"--flag": (key, kind)} with kind "list" | "str" | "float" | "int" | "bool" | "opt" (an optional value).
    Returns (values, positionals)."""
    out, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a in spec:
            key, kind = spec[a]
            if kind == "bool":
                out[key] = True
            elif kind == "opt":
                nxt = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
                out[key] = nxt
                i += 1 if nxt else 0
            else:
                if i + 1 >= len(args):
                    raise ValueError(f"{a} needs a value.")
                v = args[i + 1]
                i += 1
                if kind == "list":
                    out.setdefault(key, []).append(v)
                else:
                    out[key] = float(v) if kind == "float" else int(v) if kind == "int" else v
        elif a.startswith("--"):
            raise ValueError(f"Unknown option {a}.")
        else:
            pos.append(a)
        i += 1
    return out, pos


PARETO = {"--minimize": ("minimize", "list"), "--maximize": ("maximize", "list"), "--require": ("require", "list"),
          "--vary": ("vary", "list"), "--study": ("study", "str"), "--modal-study": ("modal_study", "str"),
          "--solves": ("solves", "int"), "--seconds": ("seconds", "float"), "--evaluations": ("evaluations", "int"),
          "--per-kg": ("per_kg", "float"), "--full": ("full", "bool"), "--show": ("show", "opt"),
          "--save": ("save", "str"), "--run": ("run", "str"), "--verify": ("verify", "bool")}
TOPOLOGY = {"--volfrac": ("volfrac", "float"), "--mass": ("mass_g", "float"), "--safety-factor": ("safety_factor", "float"),
            "--study": ("study", "str"), "--mode": ("mode", "str"), "--pull": ("pull", "str"), "--h": ("h", "float"),
            "--rmin": ("rmin", "float"), "--keep": ("keep", "float"), "--rim": ("rim", "float"),
            "--max-iter": ("max_iter", "int"), "--budget": ("budget_s", "float"), "--tries": ("tries", "int"),
            "--full": ("full", "bool"), "--show": ("show", "opt"), "--frames": ("frames", "bool"),
            "--apply": ("apply", "opt"), "--as-new": ("as_new", "str"), "--mesh-body": ("mesh_body", "bool"),
            "--expect-head": ("expect_head", "int"), "--verify": ("verify", "bool")}


def verify_pareto() -> int:
    from . import verify
    r = verify.run()
    _out(r)
    return 0 if r["passed"] else 1


def verify_topology() -> int:
    """The SIMP benchmark, in the engine's Python (it needs SciPy)."""
    from .. import config, engines
    from ..fea import HOW_TO_GET, python
    py = python(config.load())
    if py is None:
        _out({"error": {"message": "The strength engine is not installed, so the benchmark cannot run.", "hint": HOW_TO_GET}})
        return 1
    import os
    env = engines.child_env() if str(py) != sys.executable else None
    if env is None:
        env = {**os.environ, "PYTHONPATH": str(engines.src_root()) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    r = subprocess.run([str(py), "-m", "form.topo.verify", "--json"], env=env, capture_output=True, text=True, encoding="utf-8")
    if r.returncode not in (0, 1) or not r.stdout.strip():
        _out({"error": {"message": "The benchmark did not run.", "hint": (r.stderr or "")[-600:]}})
        return 1
    print(r.stdout)
    return r.returncode


def _progress(ev) -> None:
    print(f"  {ev.get('progress')}", file=sys.stderr, flush=True)


def main(argv: list) -> int:
    from .. import config
    from ..studio import Studio, StudioError
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__, file=sys.stderr)
        return 0 if len(argv) >= 2 else 2
    what, args = argv[0], argv[1:]
    st = None
    try:
        try:
            o, pos = _flags(args, PARETO if what == "pareto" else TOPOLOGY)
        except ValueError as e:
            raise StudioError(str(e), "form optimize " + what + " --help shows the options.") from None
        if o.get("verify"):
            return verify_pareto() if what == "pareto" else verify_topology()
        if len(pos) != 1:
            raise StudioError(f"form optimize {what} <project> ...", "form list names the designs.")
        pid = pos[0]
        st = Studio(config.load())
        st.load(pid)
        if what == "pareto":
            from . import design, tools
            if "show" in o:
                _out(tools.read_call(st, pid, o["show"], 0, bool(o.get("full"))))
                return 0
            if "save" in o:
                idx, _, name = o["save"].partition(":")
                _out(design.save_point(st, pid, o.get("run", ""), int(idx), name, by="you"))
                return 0
            vary = []
            for item in o.get("vary", []):
                k, _, rng = item.partition(":")
                lo, _, hi = rng.partition(":")
                vary.append({"key": k, **({"min": float(lo)} if lo else {}), **({"max": float(hi)} if hi else {})})
            body = {"minimize": o.get("minimize", []), "maximize": o.get("maximize", []), "require": o.get("require", []),
                    "vary": vary, "study": o.get("study", ""), "modal_study": o.get("modal_study", ""),
                    "budget": {k: o[k] for k in ("solves", "seconds", "evaluations") if k in o},
                    "rates": {"per_kg": o["per_kg"]} if "per_kg" in o else None}
            rec = design.run(st, pid, body, on_progress=_progress)
            _out(tools.digest(rec, bool(o.get("full"))))
            return 0 if rec["front"] else 3
        from ..topo import study as topo
        from ..topo import tools as ttools
        if "show" in o:
            _out(ttools.read_call(st, pid, o["show"], 0, bool(o.get("full")), False, bool(o.get("frames"))))
            return 0
        if "apply" in o:
            _out(topo.apply(st, pid, o["apply"], o.get("expect_head"), o.get("as_new") or False, bool(o.get("mesh_body")), "you"))
            return 0
        opts = {k: o[k] for k in ("volfrac", "mass_g", "safety_factor", "study", "mode", "pull", "h", "rmin", "keep", "rim",
                                  "max_iter", "budget_s", "tries") if k in o}
        rec = topo.run(st, pid, opts, on_progress=_progress)
        _out(ttools.digest(rec, bool(o.get("full"))))
        return 0 if rec["outcome"] == "features" else 3
    except StudioError as e:
        _out({"error": e.public()})
        return 1
    finally:
        if st is not None:
            try:
                st.kernel.shutdown()
            except Exception:                            # noqa: BLE001
                pass
