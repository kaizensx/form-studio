"""Use the BUILT app the way a person and an agent do, before it is installed or released.

    python scripts/smoke_packaged.py dist/FORM.app        # macOS
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
