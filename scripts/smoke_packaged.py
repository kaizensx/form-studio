"""Use the BUILT app the way a person and an agent do, before it is installed or released.

    python scripts/smoke_packaged.py "dist/Form Studio.app"        # macOS
    python scripts/smoke_packaged.py dist/FORM/FORM.exe   # Windows
    python scripts/smoke_packaged.py dist/FORM/FORM       # Linux

The unit and interface tests run the source. Everything here runs the packaged program, because that is where
earlier packaging bugs lived: no certificates for https, the Blender script missing from the bundle,
and chat handing agents an old form-mcp from PATH instead of the app itself. Each step uses a real outside
program when it is installed (slicer, Blender) and says SKIP when it is not. Nothing is uploaded or printed.
Exit code 0 only when every step that ran passed.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RESULTS: list[tuple[str, str, str]] = []


def step(name: str, status: str, detail: str = "") -> None:
    RESULTS.append((name, status, detail))
    print(f"{status:5} {name}" + (f"  · {detail}" if detail else ""), flush=True)


def exe_of(target: str) -> Path:
    p = Path(target)
    if p.suffix == ".app":
        return p / "Contents" / "MacOS" / "FORM"
    return p


def cli(exe: Path, env: dict, *args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run([str(exe), "cli", *args], env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


async def mcp_steps(exe: Path, env: dict) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=str(exe), args=["-m", "form.mcp_server", "--no-bench"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            step("MCP server is the app itself", "PASS" if len(tools) >= 40 else "FAIL", f"{len(tools)} tools")

            async def call(tool, **kw):
                res = await s.call_tool(tool, kw)
                text = " ".join(getattr(c, "text", "") or "" for c in res.content)
                return res, text

            res, text = await call("brief_presets", preset="bathroom mount")
            step("brief_presets by the agent's words", "FAIL" if res.is_error else "PASS", text[:80].replace("\n", " "))

            res, text = await call("design_examples", query="")       # exemplars ship as source files (form.spec)
            try:
                n = len(json.loads(text).get("examples", []))
            except ValueError:
                n = 0
            step("design_examples lists the exemplars", "PASS" if not res.is_error and n >= 40 else "FAIL", f"{n} exemplars")

            url = "https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf"
            import urllib.request
            try:                                             # the step tests the app over https, not that site's uptime
                urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=15).close()
                reachable = True
            except Exception as e:
                reachable, why = False, str(e)[:80]
            if not reachable:
                step("read_document over https", "SKIP", f"the test document's site did not answer ({why})")
            else:
                res, text = await call("read_document", source=url, pages="1")
                imgs = sum(1 for c in res.content if getattr(c, "type", "") == "image")
                step("read_document over https", "FAIL" if res.is_error or not imgs else "PASS",
                     (text[:120] if res.is_error else f"{imgs} page image(s)").replace("\n", " "))

            if os.environ.get("SMOKE_BLENDER", "1") != "0":
                res, text = await call("render_photo", project=PID, preset="studio", fast=True)
                low = text.lower()
                if res.is_error and "blender" in low and ("not found" in low or "not installed" in low or "not available" in low):
                    step("Blender render", "SKIP", "Blender is not installed")
                else:
                    imgs = sum(1 for c in res.content if getattr(c, "type", "") == "image")
                    step("Blender render", "FAIL" if res.is_error or not imgs else "PASS", text[:160].replace("\n", " "))
                await game_step(call)


def cage_source() -> str:
    """A small subdivision cage design (a box cage, 3 quads a side) as a design source: form/game/pipeline.py writes
    it, so the smoke test sends exactly what an agent would."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import numpy as np
    from form import meshsource
    from form.game import pipeline
    n, lo, hi = 3, np.array([0.0, 0.0, 0.0]), np.array([40.0, 30.0, 20.0])
    V, F, ids = [], [], {}

    def pid(i, j, k):
        if (i, j, k) not in ids:
            ids[(i, j, k)] = len(V)
            V.append(lo + (hi - lo) * np.array([i, j, k]) / n)
        return ids[(i, j, k)]
    for a in range(n):
        for b in range(n):
            F += [[pid(a, b, 0), pid(a, b + 1, 0), pid(a + 1, b + 1, 0), pid(a + 1, b, 0)],
                  [pid(a, b, n), pid(a + 1, b, n), pid(a + 1, b + 1, n), pid(a, b + 1, n)],
                  [pid(a, 0, b), pid(a + 1, 0, b), pid(a + 1, 0, b + 1), pid(a, 0, b + 1)],
                  [pid(a, n, b), pid(a, n, b + 1), pid(a + 1, n, b + 1), pid(a + 1, n, b)],
                  [pid(0, a, b), pid(0, a, b + 1), pid(0, a + 1, b + 1), pid(0, a + 1, b)],
                  [pid(n, a, b), pid(n, a + 1, b), pid(n, a + 1, b + 1), pid(n, a, b + 1)]]
    return pipeline.cage_design_source(meshsource.cage(np.array(V), F, [], {}), "Smoke cage")


async def game_step(call) -> None:
    """A small cage design made a game asset in the packaged app: Blender's game runner and form/game ship as files
    (packaging/form.spec). 1k textures, the fast bake, the Unreal preset; every check must pass. SKIP when Blender is
    not installed."""
    import re
    res, text = await call("create_design", name="Smoke cage", source=cage_source(), purpose="game", run=False)
    m = None if res.is_error else re.search(r'"(?:project|id)":\s*"([a-z0-9-]+)"', text)
    if m is None:
        step("game asset from a cage (1k, fast bake)", "FAIL", text[:160].replace("\n", " ") or "no project id")
        return
    res, text = await call("game_asset", project=m.group(1), preset="unreal", budgets=[800, 400, 200, 60],
                           texture_px=1024, bake="fast")
    low = text.lower()
    if res.is_error and "blender" in low and ("install" in low or "not found" in low):
        step("game asset from a cage (1k, fast bake)", "SKIP", "Blender is not installed")
        return
    try:
        out = json.loads(text)
    except ValueError:
        out = {}
    ok = not res.is_error and (out.get("validation") or {}).get("ok") is True
    detail = (f"LOD triangles {[x['triangles'] for x in out.get('lods', [])]}, bake "
              f"{(out.get('bake') or {}).get('total_seconds')} s, every check PASS") if ok else text[:200].replace("\n", " ")
    step("game asset from a cage (1k, fast bake)", "PASS" if ok else "FAIL", detail)


PID ="phone-stand"              # the design main() makes from the device_stand recipe


def ring_stl(path: Path, r_out: float = 20.0, r_in: float = 6.0, h: float = 12.0, n: int = 96) -> None:
    """An ASCII STL of a faceted ring (a flange blank): n sides outside, n inside, flat ends. No libraries needed."""
    import math
    def p(r, k, z):
        a = 2 * math.pi * k / n
        return (r * math.cos(a), r * math.sin(a), z)
    tris = []
    for k in range(n):
        o0, o1, i0, i1 = p(r_out, k, 0), p(r_out, k + 1, 0), p(r_in, k, 0), p(r_in, k + 1, 0)
        O0, O1, I0, I1 = p(r_out, k, h), p(r_out, k + 1, h), p(r_in, k, h), p(r_in, k + 1, h)
        tris += [(o0, o1, O1), (o0, O1, O0), (i1, i0, I0), (i1, I0, I1),        # outer and inner walls
                 (O0, O1, I1), (O0, I1, I0), (o1, o0, i0), (o1, i0, i1)]        # top and bottom
    lines = ["solid ring"]
    for t in tris:
        lines += ["facet normal 0 0 0", "outer loop", *[f"vertex {x:.6f} {y:.6f} {z:.6f}" for x, y, z in t],
                  "endloop", "endfacet"]
    path.write_text("\n".join(lines + ["endsolid ring"]) + "\n", encoding="ascii")


def recon_step(exe: Path, env: dict, tmp: Path, budget: float = 30.0) -> None:
    """Mesh to CAD keeps its time budget in the packaged app too (its bounded steps run in spawned helpers)."""
    stl = tmp / "ring.stl"
    ring_stl(stl)
    t = time.time()
    r = cli(exe, env, "reconstruct", str(stl), "--name", "Ring", "--budget", f"{budget:g}", timeout=int(budget) + 300)
    took = time.time() - t
    try:
        summ = json.loads(r.stdout or "{}").get("summary") or {}
    except json.JSONDecodeError:
        summ = {}
    secs = summ.get("seconds")
    # a step in flight finishes before the budget is read again, so a quarter over is still a budget that is kept.
    # On top of that comes what does not shrink with the budget: loading the CAD kernel, in the app and again in
    # every helper that replaces one stopped at its limit. How long that takes on this machine is measured in this
    # very run (the time the command took beyond the reconstruction it reports: 1 to 2 s on a fast machine, 9 s on
    # CI's Intel Mac runner, where a 30 s budget ended at 36 to 41 s), and that much more is allowed
    start = max(0.0, took - float(secs)) if secs is not None else 0.0
    ok = r.returncode == 0 and secs is not None and float(secs) <= budget * 1.25 + 1.0 + start
    detail = (f"{secs} s of a {budget:g} s budget ({took:.0f} s for the command, {start:.1f} s of it starting the app and saving; "
              f"allowed {budget * 1.25 + 1.0 + start:.1f} s), layer {summ.get('layer')}, "
              f"editable {summ.get('editable_pct')}%" + (f", cut short: {', '.join(summ['cut_short'])}"
                                                          if summ.get("cut_short") else "")) if secs is not None \
        else r.stderr.strip()[-160:]
    step("mesh to CAD within its time budget", "PASS" if ok else "FAIL", detail)


def engine_src_of(target: str) -> Path | None:
    """engine_src/ inside the built app: the engine code an engine environment imports (packaging/form.spec)."""
    p = Path(target)
    roots = [p / "Contents" / "Frameworks", p / "Contents" / "Resources"] if p.suffix == ".app" else [p.parent, p.parent / "_internal"]
    return next((r / "engine_src" for r in roots if (r / "engine_src" / "form" / "__init__.py").is_file()), None)


def cadfit_engine_step(target: str) -> None:
    """CADFit's code ships as files for its engine environment (with its LICENSE and PERMISSION.md); when that
    environment is installed on this computer, its interpreter imports CADFit from the built app. Read-only: the
    environment is only used, never made or changed here."""
    src = engine_src_of(target).resolve()      # absolute: the import check runs from another folder
    if src is None:
        step("CADFit ships for its engine environment", "FAIL", "no engine_src/ in the app")
        return
    cf = src / "form" / "recon" / "cadfit"
    missing = [n for n in ("LICENSE", "PERMISSION.md", "__init__.py", "driver.py", "cqrun.py", "vendor/greedy_search.py")
               if not (cf / n).is_file()]
    compiled = [str(x.relative_to(cf)) for x in cf.rglob("*.pyc")]
    step("CADFit ships for its engine environment", "FAIL" if missing or compiled else "PASS",
         f"missing {', '.join(missing)}" if missing else f"compiled files {compiled[:3]}" if compiled else str(cf.relative_to(src)))
    engines = Path(os.environ.get("SMOKE_ENGINES_DIR") or Path.home() / "FORM" / ".engines") / "recon.cadfit"
    py = engines / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not ((engines / "form-engine.json").is_file() and py.exists()):
        step("CADFit imports through its engine environment", "SKIP", "CADFit is not installed on this computer")
        return
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    env.update(PYTHONPATH=str(src), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([str(py), "-c", "import form.recon.cadfit as c, form.recon.cadfit.driver, form.recon.cadfit.cqrun, "
                        "form.recon.cadfit.vendor.greedy_search, trimesh, manifold3d, sklearn, scipy, build123d; print(c.__file__)"],
                       env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
                       cwd=tempfile.gettempdir())     # never the checkout: `python -c` puts the cwd first on sys.path
    where = (r.stdout.strip().splitlines() or [""])[-1]
    ok = r.returncode == 0 and where.startswith(str(src))
    step("CADFit imports through its engine environment", "PASS" if ok else "FAIL",
         where if ok else (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1][:160])


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    exe = exe_of(argv[0]).resolve()
    if not exe.exists():
        print(f"No program at {exe}")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="form-smoke-"))
    env = dict(os.environ, FORM_DATA=str(tmp / "data"), FORM_NO_UPDATE_CHECK="1", FORM_CHECK_OUT=str(tmp / "check.txt"))
    env.pop("FORM_CONFIG", None)            # the user's own studio.toml: their slicer and presets, never edited here
    for k in ("PYTHONPATH", "VIRTUAL_ENV", "SSL_CERT_FILE"):    # the app must work without a developer's environment
        env.pop(k, None)
    print(f"Form Studio smoke test · {exe} · data in {tmp}")

    t = time.time()
    subprocess.run([str(exe), "--check", "--wait", "15000"], env=env, capture_output=True, timeout=300)
    out = (tmp / "check.txt").read_text(encoding="utf-8") if (tmp / "check.txt").exists() else ""
    ok = "ok:" in out and "kernel: build123d" in out
    step("window opens and the CAD kernel starts", "PASS" if ok else "FAIL", " ".join(out.split())[:120] or "no output")

    r = cli(exe, env, "new", "Phone stand", "device_stand", "--purpose", "print")     # a design from a recipe
    step("new design from a recipe", "PASS" if r.returncode == 0 else "FAIL", r.stderr.strip()[-160:])
    r = cli(exe, env, "run", PID)
    step("pipeline: solid, exports, checks", "PASS" if r.returncode == 0 else "FAIL", r.stderr.strip()[-160:])
    st = json.loads(cli(exe, env, "state", PID).stdout or "{}")
    sl = st.get("slice_simulated") or {}
    if sl.get("layers"):
        step("slice with the installed slicer", "PASS", f"{sl.get('layers')} layers, {sl.get('filament_g')} g")
        png = tmp / "sim.png"
        r = cli(exe, env, "simulate", PID, "--png", str(png))
        step("print simulation picture", "PASS" if png.exists() else "FAIL", r.stderr.strip()[-160:])
    else:
        step("slice with the installed slicer", "SKIP", "no slicer found or not configured")

    recon_step(exe, env, tmp)
    cadfit_engine_step(argv[0])

    try:
        asyncio.run(mcp_steps(exe, env))
    except Exception as e:
        step("MCP steps", "FAIL", f"{type(e).__name__}: {e}"[:200])

    failed = [n for n, s, _ in RESULTS if s == "FAIL"]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} steps passed or skipped in {time.time() - t:.0f} s"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
