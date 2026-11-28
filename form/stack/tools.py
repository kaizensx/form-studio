"""The stack-up over MCP: `tolerance_stack` (compute, and optionally keep) and `get_tolerance_stack` (read).

    call(st, P, a=..., b=...)                    a stack, nothing saved
    call(st, P, a=..., b=..., save=True)         also kept with the design (the Bench lists it, a commit makes it stale)
    call(st, P, stack="s1a2b3")                  a kept stack computed for the head revision and stored
    read(st, P)                                  every kept stack with its state;  read(st, P, "s1a2b3") its result
"""
from __future__ import annotations

from mcp.server.mcpserver import Context

from . import AN, FIELDS, StackError, _serr, compute, define, definitions, listing, run, stored


def call(st, project: str, a=None, b=None, save: bool = False, stack: str = "", **opts) -> dict:
    try:
        p = st.load(project)
        if stack and a is None and b is None:
            return run(st, project, stack)
        if a is None or b is None:
            raise StackError("Pick the two faces of the gap: a and b.",
                             'a={"at": [x, y, z]} (a point on the face, as built; add "part" and "frame": "assembled" '
                             'if you picked it assembled) or {"face": i}. stack= runs a kept one.')
        d = {k: v for k, v in {"a": a, "b": b, **opts}.items() if v is not None and k in FIELDS}
        if save:
            sd = define(st, project, d, sid=stack)
            return {**run(st, project, sd["id"]), "saved": sd["id"]}
        return compute(st, p, **{k: v for k, v in d.items()})
    except StackError as e:
        raise _serr(e) from None


def lean(out):
    """What an agent reads: the loop's faces without their triangles (those are for the viewport)."""
    d = out.get("draw") if isinstance(out, dict) else None
    if isinstance(d, dict) and d.get("faces"):
        out = {**out, "draw": {**d, "faces": [{k: v for k, v in f.items() if k != "mesh"} for f in d["faces"]]}}
    return out


def read(st, project: str, stack: str = "") -> dict:
    try:
        p = st.load(project)
        if not stack:
            return {"stacks": listing(st, p), "definitions": definitions(st, project)}
        cur, newest = stored(st, p, stack)
        if cur is not None:
            return {"state": "current", **cur}
        if newest is not None:
            return {"state": "stale", "why": f"computed for r{newest.get('rev')}; run it again for the head", **newest}
        return {"state": "never", "stack": stack, "next": f"tolerance_stack(project='{project}', stack='{stack}')"}
    except StackError as e:
        raise _serr(e) from None


def register_tools(mcp, studio, run_async, RO, RW, origin) -> None:
    @mcp.tool(annotations=RW)
    async def tolerance_stack(project: str, a: dict | None = None, b: dict | None = None,
                              direction: list[float] | None = None, tolerances: dict | None = None,
                              dist: dict | None = None, spec: list | None = None, t_min: float | None = None,
                              t_max: float | None = None, alpha: dict | None = None,
                              samples: int = AN.DEFAULT_SAMPLES, seed: int = AN.DEFAULT_SEED,
                              params: list[str] | None = None, exclude: list[str] | None = None, name: str = "",
                              save: bool = False, stack: str = "", ctx: Context = None) -> dict:
        """Tolerance stack-up of a gap between two faces of an assembly. a, b: the faces, each {"at": [x, y, z]} (a
        point on the face as built, the frame analyze_selection uses; add "part", or "frame": "assembled") or
        {"face": model face index}. direction: the gap's direction (default: face A's outward normal). Form Studio
        finds the loop itself: the chain of parts from A's part to B's through the declared mates that hold them
        along the direction (seats: opposite faces; radial fits: a pin square to it, whose clearance is a float), each
        part's link between the faces it is entered and left by, and d(link)/d(parameter) per part by finite
        differences on the rebuilt CAD (so angles count). Tolerances, first that applies: tolerances= ({param: ±t |
        [lower, upper]}, or "part:param"), the drawing's ISO 286 fits, the parameter's provenance sigma, the drawing's
        ISO 2768 class, the process (printed: printer calibration, else FDM ±0.2 mm assumed), else ISO 2768-m assumed;
        declared position and profile tolerances on faces of the loop are converted (±zone/2 along the gap). dist:
        {id: normal | uniform} (default normal at ±3 sigma = tolerance; assumed ones uniform). spec: [LSL, USL] of
        the gap (default LSL 0, assumed). t_min, t_max (°C): the gap over a temperature span from each part's sourced
        expansion (alpha={part: 1/K} for a part without one; never assumed). Returns the gap and its loop (closure),
        contributors with evidence and rule, worst case, RSS, Monte Carlo (seeded) with histogram, Cpk and share out
        of spec, the contribution chart (percent of variance), suggestions (what to tighten, cost hints labelled
        assumed), thermal, and draw (the loop's faces and segments for the viewport). save=True keeps it with the
        design (the Bench entry 'stack'); stack= alone runs a kept one for the head."""
        st = studio()
        return lean(await run_async(call, st, project, a, b, save, stack, direction=direction, tolerances=tolerances,
                               dist=dist, spec=spec, t_min=t_min, t_max=t_max, alpha=alpha, samples=samples, seed=seed,
                               params=params, exclude=exclude, name=name))

    @mcp.tool(annotations=RO)
    async def get_tolerance_stack(project: str, stack: str = "") -> dict:
        """Read the tolerance stacks kept with a design. No stack: each with its state (current for the head,
        stale with the revision it describes, never). stack=: its stored result (as tolerance_stack returns it).
        Reads only."""
        st = studio()
        return lean(await run_async(read, st, project, stack))


__all__ = ["call", "read", "register_tools"]
