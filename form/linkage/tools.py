"""Four-bar synthesis over MCP and for the command line.

    call(st, "motion", poses=[...])                       link lengths, checks, the simulation; nothing saved
    call(st, "path", targets=[...], build=True)           and the linkage written as a design with its assembly,
                                                          then played on the real parts (form/motion.py)
"""
from __future__ import annotations

from . import LinkageError, create, synthesise


def _err(e: LinkageError):
    from ..studio import StudioError
    return StudioError(str(e), e.hint, status=422)


def brief(r: dict) -> dict:
    """The result without the long lists (the simulated path, the runners-up's internals)."""
    out = {k: v for k, v in r.items() if k not in ("link",)}
    v = dict(out.get("verification") or {})
    if "path" in v:
        v["path_points"] = len(v.pop("path"))
    out["verification"] = v
    out["alternatives"] = [{k: x for k, x in a.items() if k != "link"} for a in out.get("alternatives") or []]
    return out


def call(st, mode: str = "", poses: list | None = None, pairs: list | None = None, targets: list | None = None,
         ground: float = 100.0, closed: bool = True, seed: int = 1, steps: int = 24, max_size: float = 6.0,
         require_crank: bool = False, alternatives: int = 3, build: bool = False, name: str = "", motion: bool = True,
         purpose: str | None = None, full: bool = False) -> dict:
    if not mode:
        return {"modes": {
            "motion": 'three poses of the coupler: poses=[{"at": [x, y], "angle": deg}, ...] (Burmester, exact)',
            "function": "three input and output angles: pairs=[[phi, psi], ...], ground= (Freudenstein, exact)",
            "path": "a coupler curve through points: targets=[[x, y], ...] (optimisation; the error is reported)"},
            "how": "linkage_synthesis(mode, ...) returns the link lengths, Grashof, the transmission angle, the "
                   "branch and order checks and a simulation through the targets; build=True writes the design."}
    try:
        r = synthesise(mode, poses=poses, pairs=pairs, targets=targets, ground=ground, closed=closed, seed=seed,
                       steps=steps, max_size=max_size, require_crank=require_crank, alternatives=alternatives)
    except LinkageError as e:
        raise _err(e) from None
    out = r if full else brief(r)
    if build:
        p = create(st, r, name, purpose)
        out["project"] = p["id"]
        out["head"] = p["head"]
        if motion:
            out["motion_study"] = _play(st, p, r)
    return out


def _play(st, p: dict, r: dict) -> dict:
    """The built design played by form/motion.py on its real parts: loop closure and clearance along the drive."""
    from .. import motion as M
    from ..studio import StudioError
    drive = (r["checks"].get("drive") or {})
    if r["checks"]["crank_turns_fully"]:
        drv = [{"joint": "crank", "from": 0, "to": 360}]
    elif drive:
        drv = [{"joint": "crank", "from": 0, "to": drive["direction"] * drive["sweep_deg"]}]
    else:
        return {"skipped": "the crank's reachable range was not established"}
    try:
        res = M.run(st, st.load(p["id"]), drivers=drv, frames=73, torque_check=False)
    except StudioError as e:
        return {"error": str(e)}
    s = res.get("summary") or {}
    return {"drivers": drv, "frames": len(res.get("frames") or []), "closed_frames": res.get("closed_frames"),
            "summary": s, "evidence": "computed (kinematics on the built assembly; clearance by mesh distance)",
            "note": "links are stacked in layers, so they pass over one another; pins are coincident axes"}


def register_tools(mcp, studio, run_async, RO, RW, origin) -> None:
    @mcp.tool(annotations=RW)
    async def linkage_synthesis(mode: str = "", poses: list[dict] | None = None, pairs: list[list[float]] | None = None,
                                targets: list[list[float]] | None = None, ground: float = 100.0, closed: bool = True,
                                seed: int = 1, steps: int = 24, max_size: float = 6.0, require_crank: bool = False,
                                alternatives: int = 3, build: bool = False, name: str = "", purpose: str = "",
                                full: bool = False) -> dict:
        """Find a four-bar linkage from what it must do, check it and play it. mode "motion": three poses of the
        coupler, poses=[{"at": [x, y], "angle": deg}, ...] (Burmester's three-position synthesis in dyad form; the
        free choices are searched on a grid of `steps` per turn, links up to max_size times the poses' spread;
        require_crank=True keeps only linkages whose crank turns fully). mode "function": three pairs of input and
        output angles, pairs=[[phi, psi], ...] in degrees from the ground line, ground= its length (Freudenstein's
        equation). Both are exact at the three positions. mode "path": a coupler point through targets=[[x, y], ...]
        (4 to 60 points, in order; closed=True needs a crank that turns fully) by differential evolution and a
        Nelder-Mead polish, deterministic for seed: an approximation, its RMS and largest error in mm are returned.
        Units mm and degrees. Returns linkage (ground pivots, link lengths, coupler point), checks (Grashof and
        class, transmission angle against 40 degrees, branch and order defects), verification (the linkage played
        by Form Studio's motion solver through the targets: point and angle error, or distance to the path) and
        alternatives. build=True writes it as a design: four bars with an assembly of three hinges and a loop,
        played again on the real parts (motion_study). full=True adds the simulated path. No mode: the modes."""
        st = studio()
        return await run_async(call, st, mode, poses, pairs, targets, ground, closed, seed, steps, max_size,
                               require_crank, alternatives, build, name, True, purpose or None, full)


def main(argv: list) -> int:
    """`form linkage motion|function|path ...`: prints JSON. Exit 0 with a result, 2 on an error."""
    import json
    import sys
    doc = """form linkage motion --poses '[{"at": [0, 0], "angle": 0}, {"at": [30, 20], "angle": 20}, {"at": [60, 15], "angle": 45}]'
form linkage function --pairs '[[40, 70], [60, 85], [85, 110]]' [--ground 100]
form linkage path --targets '[[x, y], ...]' [--open] [--seed 1]
    [--require-crank] [--steps 24] [--max-size 6] [--build] [--name N] [--full]      JSON; mm and degrees"""
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(doc, file=sys.stderr)
        return 0 if argv else 2
    kw: dict = {"mode": argv[0]}
    i = 1
    flags = {"--build": ("build", True), "--full": ("full", True), "--open": ("closed", False),
             "--require-crank": ("require_crank", True)}
    try:
        while i < len(argv):
            a = argv[i]
            if a in flags:
                kw[flags[a][0]] = flags[a][1]
                i += 1
                continue
            if i + 1 >= len(argv):
                raise ValueError(f"{a} needs a value.")
            v = argv[i + 1]
            if a in ("--poses", "--pairs", "--targets"):
                kw[a[2:]] = json.loads(v)
            elif a in ("--ground", "--max-size"):
                kw[a[2:].replace("-", "_")] = float(v)
            elif a in ("--seed", "--steps", "--alternatives"):
                kw[a[2:]] = int(v)
            elif a == "--name":
                kw["name"] = v
            else:
                raise ValueError(f"Unknown option {a}.")
            i += 2
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    st = None
    try:
        if kw.get("build"):
            from .. import config
            from ..studio import Studio
            st = Studio(config.load())
        print(json.dumps(call(st, **kw), indent=1, ensure_ascii=False, default=str))
        return 0
    except Exception as e:                                    # noqa: BLE001 - StudioError: said as JSON
        if type(e).__name__ != "StudioError":
            raise
        print(json.dumps({"error": str(e), "hint": getattr(e, "hint", "")}, indent=1, ensure_ascii=False))
        return 2
    finally:
        if st is not None:
            try:
                st.kernel.stop()
            except Exception:                                 # noqa: BLE001
                pass


__all__ = ["call", "brief", "register_tools", "main"]
