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

            async def call(name, **kw):
                res = await s.call_tool(name, kw)
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
                if res.is_error and "not found" in text.lower() and "blender" in text.lower():
                    step("Blender render", "SKIP", "Blender is not installed")
                else:
                    imgs = sum(1 for c in res.content if getattr(c, "type", "") == "image")
                    step("Blender render", "FAIL" if res.is_error or not imgs else "PASS", text[:160].replace("\n", " "))


PID = "phone-stand"              # the design main() makes from the device_stand recipe


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
    ok = r.returncode == 0 and secs is not None and float(secs) <= budget + 1.0
    detail = (f"{secs} s of a {budget:g} s budget ({took:.0f} s with app start), layer {summ.get('layer')}, "
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
    src = engine_src_of(target)
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
                       env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
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
