"""Command line. Every command except `serve` and `mcp` prints JSON, so any agent with a shell can drive FORM.

  form setup                         find what is missing, fix what you pick (--check, --yes, --dry-run)
  form serve                         the bench on http://127.0.0.1:4173
  form mcp                           MCP server over stdio (what agents launch)
  form update [--check]              is there a newer release on GitHub? (never installs)
  form doctor                        what is installed and usable
  form list                          projects
  form recipe <id>                   parameters, units, ranges, features
  form new <name> <recipe> [k=v ...] create a project and build it
  form state <project>               digest: parameters, outputs, checks, fit, gate, files
  form preview <project> k=v ...     build a candidate, report its impact, save nothing
  form commit <project> k=v ... [--note N] [--expect-head N] [--measured k,k]
  form run <project> [--force]       regenerate outputs that are not current
  form render <project> [--view iso|front|...|sheet] [--highlight feature] [--out file.png]
  form optimize <project> --vary arm_t:4:20 --minimize solid_mass_g --require "statics.safety_factor>=3"
  form animate <project> [--morph 1:4] [--out x.gif]   turntable or revision morph
  form verify <project> <release>    re-hash a release against its manifest
"""
from __future__ import annotations

import argparse
import json
import sys


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"Expected key=value, got “{p}”.")
        k, v = p.split("=", 1)
        try:
            out[k] = float(v)
        except ValueError:
            raise SystemExit(f"{k}: “{v}” is not a number (units are mm, degrees, grams).")
    return out


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["app"]:                       # the desktop app has its own flags
        from .app.main import main as app_main
        return app_main(argv[1:])
    if argv[:1] == ["update"]:                    # checks only; never installs
        from .updates import main as update_main
        return update_main(argv[1:])
    if argv[:1] == ["setup"]:                     # its own flags; keep argparse out of the way
        from .setup import main as setup_main
        return setup_main(argv[1:])
    ap = argparse.ArgumentParser(prog="form", description="FORM print-design studio",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n", 2)[2])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("app", help="open the desktop app (needs the [app] extra)")
    sub.add_parser("serve", help="start the bench on loopback")
    m = sub.add_parser("mcp", help="MCP server over stdio")
    m.add_argument("--no-bench", action="store_true")
    sub.add_parser("setup", help="find what is missing and fix what you choose (--check, --yes, --dry-run)")
    sub.add_parser("update", help="is there a newer FORM? (--check prints JSON; never installs)")
    sub.add_parser("doctor")
    sub.add_parser("list")
    r = sub.add_parser("recipe")
    r.add_argument("recipe")
    n = sub.add_parser("new")
    n.add_argument("name")
    n.add_argument("recipe")
    n.add_argument("values", nargs="*")
    n.add_argument("--brief", default="")
    for name in ("state", "run", "preview", "commit", "render"):
        c = sub.add_parser(name)
        c.add_argument("project")
        if name in ("preview", "commit"):
            c.add_argument("values", nargs="*")
        if name == "commit":
            c.add_argument("--note", default="")
            c.add_argument("--expect-head", type=int)
            c.add_argument("--measured", default="", help="comma-separated keys whose new values you measured")
        if name == "run":
            c.add_argument("--force", action="store_true")
        if name == "render":
            c.add_argument("--view", default="iso")
            c.add_argument("--highlight")
            c.add_argument("--out")
    o = sub.add_parser("optimize", help="goal seek over parameters")
    o.add_argument("project")
    o.add_argument("--vary", action="append", required=True, help="key:min:max (repeat)")
    g = o.add_mutually_exclusive_group(required=True)
    g.add_argument("--minimize")
    g.add_argument("--maximize")
    o.add_argument("--require", action="append", default=[], help='constraint, e.g. "statics.safety_factor>=3"')
    o.add_argument("--budget", type=int, default=40)
    an = sub.add_parser("animate", help="turntable or revision-morph GIF")
    an.add_argument("project")
    an.add_argument("--morph", help="from:to revision numbers, e.g. 1:4")
    an.add_argument("--frames", type=int, default=36)
    an.add_argument("--out")
    v = sub.add_parser("verify")
    v.add_argument("project")
    v.add_argument("release")
    a = ap.parse_args(argv)

    if a.cmd in (None, "serve"):
        from . import config
        from .server import serve
        return serve(config.load())
    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main(["--no-bench"] if a.no_bench else [])

    from . import advisor, config
    from .digest import digest, impact_digest, job_digest
    from .studio import Studio, StudioError
    st = Studio(config.load())
    try:
        if a.cmd == "doctor":
            env = st.environment()
            env["assistant"] = advisor.cli_status(st.cfg)
            _print(env)
        elif a.cmd == "list":
            _print(st.list())
        elif a.cmd == "recipe":
            if a.recipe not in st.recipes:
                raise StudioError(f"Unknown recipe “{a.recipe}”.", "Known: " + ", ".join(st.recipes))
            r = st.recipes[a.recipe]
            _print({**r.public(), "features": [{"id": f.id, "label": f.label, "role": f.role} for f in r.features]})
        elif a.cmd == "new":
            p = st.create(a.name, a.recipe, a.brief, _kv(a.values))
            job = st.run_sync(p["id"])
            _print({"pipeline": job_digest(job), "project": digest(st, p["id"])})
        elif a.cmd == "state":
            _print(digest(st, a.project))
        elif a.cmd == "preview":
            p = st.load(a.project)
            pv = st.preview(p, _kv(a.values))
            _print({"buildable": True, "base_rev": p["head"], **impact_digest(pv["impact"])})
        elif a.cmd == "commit":
            p = st.load(a.project)
            vals = _kv(a.values)
            prov = {k: {"source": "measured", "note": "via CLI"} for k in a.measured.split(",") if k}
            st.commit(p, vals, a.note, "cli", prov, expect_head=a.expect_head)
            job = st.run_sync(a.project)
            _print({"pipeline": job_digest(job), "project": digest(st, a.project)})
        elif a.cmd == "run":
            job = st.run_sync(a.project, None, a.force)
            _print({"pipeline": job_digest(job), "project": digest(st, a.project)})
            return 0 if job["state"] == "done" else 1
        elif a.cmd == "render":
            from . import render
            p = st.load(a.project)
            v = st.view(p)
            feats = [{"id": f.id, "label": f.label} for f in st.recipe(p).features]
            views = ["iso", "front", "top", "right"] if a.view == "sheet" else [a.view]
            size = (640, 460) if a.view == "sheet" else (960, 680)
            pngs = [render.render_png(v, feats, vw, a.highlight, size=size, title=f"{p['name']} - r{p['head']:02d}") for vw in views]
            out = a.out or f"{a.project}_r{p['head']:02d}_{a.view}.png"
            with open(out, "wb") as f:
                f.write(pngs[0] if len(pngs) == 1 else render.contact_sheet(pngs))
            _print({"png": out})
        elif a.cmd == "optimize":
            from . import optimize as opt
            vary = []
            for item in a.vary:
                k, lo, hi = item.split(":")
                vary.append({"key": k, "min": float(lo), "max": float(hi)})
            obj = {"minimize": a.minimize} if a.minimize else {"maximize": a.maximize}
            _print(opt.run(st, st.load(a.project), vary, obj, a.require, a.budget))
        elif a.cmd == "animate":
            from . import animate
            p = st.load(a.project)
            if a.morph:
                r0, r1 = (int(x) for x in a.morph.split(":"))
                out = a.out or f"{a.project}_r{r0:02d}-r{r1:02d}.gif"
                info = animate.morph(st, p, st.rev(p, r0)["values"], st.rev(p, r1)["values"], out, frames=a.frames,
                                     title=f"{p['name']}: r{r0:02d} to r{r1:02d}")
            else:
                out = a.out or f"{a.project}_r{p['head']:02d}_turntable.gif"
                info = animate.turntable(st, p, out, frames=a.frames)
            _print(info)
        elif a.cmd == "verify":
            res = st.verify_release(st.load(a.project), a.release)
            _print(res)
            return 0 if res["intact"] else 1
    except StudioError as e:
        _print({"error": e.public()})
        return 2
    except ValueError as e:
        _print({"error": {"message": str(e)}})
        return 2
    finally:
        st.kernel.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
