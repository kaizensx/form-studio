"""Command line. Every command except `serve` and `mcp` prints JSON, so any agent with a shell can drive FORM.

  form setup                         find what is missing, fix what you pick (--check, --yes, --dry-run)
  form install --list                everything FORM uses: found or not, and the command that installs it
  form install <id> [--yes] [--dry-run]   install one thing (ids from --list, or "recommended")
  form config get [key] | set <key> <value>   read or change studio.toml (backup first)
  form examples [add [id ...]]       list the shipped examples, or add them to your projects
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
  form chat "message" [--project ID] [--conversation ID] [--agent claude|codex] [--model X] [--attach FILE] [--json]
                                     one message to an agent with FORM's tools; streams the reply, saves the conversation
  form conversations list|show|delete|rename|pin    saved conversations
  form simulate <project> --gif out.gif | --frames dir | --png out.png [--layers a:b] [--layer n]
                                     the sliced toolpaths building up, from the slicer's G-code (not a print)
  form cost <project> [--price-per-kg X --kwh-price Y --watts Z --copies N] [--save]
  form pack <project> --copies N [--spacing mm]   do N copies fit on one plate?
  form analyze <project> --map thickness|overhang|section|features [--json | --png out.png]
  form measure <project> --from x,y,z --to x,y,z   distance and its components; or --at x,y,z: what is at a point
  form orient <project> [--apply [id]]   rank the ways the part can lie on the plate; --apply sets the best (or the id given)
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
    if argv[:1] == ["chat"]:                      # chat workstream: one message to an agent, streamed, saved
        from .chat import main_chat
        return main_chat(argv[1:])
    if argv[:1] == ["conversations"]:             # saved conversations: list | show | delete | rename | pin
        from .chat import main_conversations
        return main_conversations(argv[1:])
    # -- setup workstream: installer, settings, examples (each prints JSON; none starts the kernel) --
    if argv[:1] == ["install"]:
        from .installer import main as install_main
        return install_main(argv[1:])
    if argv[:1] == ["config"]:
        from .config_edit import main as config_main
        return config_main(argv[1:])
    if argv[:1] == ["examples"]:
        from . import config
        from .studio import StudioError, add_examples, list_examples
        root = config.load()["data"]["dir"]
        try:
            if argv[1:2] == ["add"]:
                _print({"added": add_examples(root, argv[2:] or None), "data_dir": root})
            else:
                _print({"examples": list_examples(root), "add_with": "form examples add [id ...]"})
        except StudioError as e:
            _print({"error": e.public()})
            return 2
        return 0
    ap = argparse.ArgumentParser(prog="form", description="FORM print-design studio",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n", 2)[2])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("app", help="open the desktop app (needs the [app] extra)")
    sub.add_parser("serve", help="start the bench on loopback")
    m = sub.add_parser("mcp", help="MCP server over stdio")
    m.add_argument("--no-bench", action="store_true")
    sub.add_parser("setup", help="find what is missing and fix what you choose (--check, --yes, --dry-run)")
    sub.add_parser("update", help="is there a newer FORM? (--check prints JSON; never installs)")
    sub.add_parser("chat", help='send one message to an agent: form chat "message" [--project ID] [--model X] [--json]')
    sub.add_parser("conversations", help="saved conversations: list | show ID | delete ID | rename ID TITLE | pin ID")
    sub.add_parser("install", help="install what FORM uses (--list, <id>, --yes, --dry-run)")
    sub.add_parser("config", help="get [key] | set <key> <value>: read or change studio.toml")
    sub.add_parser("examples", help="list the shipped examples; `add` copies them into your projects")
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
    # -- analysis on the model (form/analysis.py) --
    az = sub.add_parser("analyze", help="an analysis map: wall thickness, overhangs, layer cross-section, small features")
    az.add_argument("project")
    az.add_argument("--map", default="thickness", choices=["thickness", "overhang", "section", "features"])
    az.add_argument("--json", action="store_true", help="print the statistics (the default)")
    az.add_argument("--png", metavar="FILE", help="also draw the map, with its legend, to this file")
    az.add_argument("--view", default="iso")
    ms = sub.add_parser("measure", help="distance between two points, or what is at one point")
    ms.add_argument("project")
    ms.add_argument("--from", dest="a", metavar="x,y,z")
    ms.add_argument("--to", dest="b", metavar="x,y,z")
    ms.add_argument("--at", metavar="x,y,z", help="face, edge and hole diameter at a point")
    orp = sub.add_parser("orient", help="rank print orientations by a documented score")
    orp.add_argument("project")
    orp.add_argument("--apply", nargs="?", const="best", metavar="ID", help="set the best orientation (or the id given) and re-run")
    orp.add_argument("--png", metavar="FILE", help="draw the top three as printed")
    v = sub.add_parser("verify")
    v.add_argument("project")
    v.add_argument("release")
    # -- print simulation, cost, plate packing --
    sm = sub.add_parser("simulate", help="pictures of the sliced toolpaths building up (from the slicer's G-code)")
    sm.add_argument("project")
    sm.add_argument("--gif", help="write an animated GIF")
    sm.add_argument("--frames", help="write PNG frames into this folder")
    sm.add_argument("--png", help="write one picture (use --layer)")
    sm.add_argument("--layers", help="a:b, 1-based and inclusive (default: the whole print)")
    sm.add_argument("--layer", type=int, help="for --png and the statistics: the print at the end of this layer")
    sm.add_argument("--count", type=int, default=72, help="number of frames")
    sm.add_argument("--size", default="720x540")
    sm.add_argument("--max-mb", type=float, default=4.0, help="shrink the GIF until it is at most this large")
    co = sub.add_parser("cost", help="filament, electricity and machine time for the current slice")
    co.add_argument("project")
    co.add_argument("--price-per-kg", type=float)
    co.add_argument("--kwh-price", type=float)
    co.add_argument("--watts", type=float)
    co.add_argument("--machine-rate", type=float, help="per hour")
    co.add_argument("--copies", type=int, default=1)
    co.add_argument("--save", action="store_true", help="remember the given prices in <data dir>/cost.json")
    pk = sub.add_parser("pack", help="do N copies fit on one plate?")
    pk.add_argument("project")
    pk.add_argument("--copies", type=int, default=1)
    pk.add_argument("--spacing", type=float, help="gap between parts in mm (default 6)")
    pk.add_argument("--no-rotate", action="store_true")
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
        elif a.cmd == "analyze":
            from . import analysis
            p = st.load(a.project)
            r = analysis.run_map(st, p, a.map)
            out = analysis.digest(r)
            if a.png:
                with open(a.png, "wb") as f:
                    f.write(analysis.render_map_png(r, f"{p['name']} - r{r['rev']:02d}", a.view, edges=st.view(p).get("edges")))
                out["png"] = a.png
            _print(out)
        elif a.cmd == "measure":
            from . import analysis
            xyz = lambda t: [float(x) for x in t.split(",")]
            p = st.load(a.project)
            if a.at:
                _print(analysis.probe(st, p, xyz(a.at)))
            elif a.a and a.b:
                _print(analysis.measure(st, p, xyz(a.a), xyz(a.b)))
            else:
                raise StudioError("Give --from x,y,z and --to x,y,z, or --at x,y,z.", "Points are in millimetres in the design frame.")
        elif a.cmd == "orient":
            from . import analysis
            p = st.load(a.project)
            r = analysis.orientations(st, p)
            out = analysis.orientation_digest(r)
            if a.png:
                with open(a.png, "wb") as f:
                    f.write(analysis.orientation_thumbs(st, p, r))
                out["png"] = a.png
            if a.apply:
                pick = r["candidates"][0]["id"] if a.apply == "best" else a.apply
                st.settings(p, {"orientation": pick})
                job = st.run_sync(a.project)
                out["applied"] = {"orientation": pick, "label": analysis.orientation_label(pick), "pipeline": job_digest(job)}
            _print(out)
        elif a.cmd == "verify":
            res = st.verify_release(st.load(a.project), a.release)
            _print(res)
            return 0 if res["intact"] else 1
        elif a.cmd == "simulate":
            from . import simulate, toolpath
            p = st.load(a.project)
            tp = toolpath.for_project(st, p)
            first, last = toolpath.parse_range(a.layers, tp.layers)
            size = tuple(int(x) for x in a.size.lower().split("x"))
            title = f"{p['name']}  r{p['head']:02d}"
            at = (a.layer - 1) if a.layer else last
            out = {"project": p["id"], "rev": p["head"], "layers": [first + 1, last + 1], "of": tp.layers,
                   "time_source": tp.time_source, "time_note": toolpath.TIME_NOTES[tp.time_source],
                   "at": toolpath.stats_at(tp, at), "label": simulate.LABEL}
            if a.gif:
                out["gif"] = simulate.save_gif(tp, a.gif, first=first, last=last, count=a.count, size=size, title=title,
                                               max_bytes=int(a.max_mb * 1_000_000))
            if a.frames:
                out["frames"] = simulate.save_frames(tp, a.frames, first=first, last=last, count=a.count, size=size, title=title)
            if a.png:
                with open(a.png, "wb") as f:
                    f.write(simulate.png_at(tp, at + 1, size=size, title=title))
                out["png"] = a.png
            _print(out)
        elif a.cmd == "cost":
            from . import cost
            p = st.load(a.project)
            given = {"price_per_kg": a.price_per_kg, "kwh_price": a.kwh_price, "watts": a.watts, "machine_rate_per_h": a.machine_rate}
            if a.save:
                body = {k: v for k, v in given.items() if v is not None and k != "price_per_kg"}
                if a.price_per_kg is not None:
                    ftype = cost.project(st, p, with_materials=False)["filament"]["filament_type"]
                    body |= {"price_per_kg": a.price_per_kg, "filament_type": ftype}
                cost.save_prefs(st.cfg, body)
            _print(cost.project(st, p, a.copies, given))
        elif a.cmd == "pack":
            from . import packing
            res = packing.project(st, st.load(a.project), a.copies, a.spacing, not a.no_rotate)
            _print(res)
            return 0 if res["fits"] else 1
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
