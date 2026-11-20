"""Command line. Every command except `serve` and `mcp` prints JSON, so any agent with a shell can drive FORM.

  form setup                         find what is missing, fix what you pick (--check, --yes, --dry-run)
  form install --list                everything FORM uses: found or not, and the command that installs it
  form install <id> [--yes] [--dry-run]   install one thing (ids from --list, or "recommended")
  form config get [key] | set <key> <value>   read or change studio.toml (backup first)
  form capabilities [on|off <id>]    what Form Studio is set up for (3D printing is opt-in); off never uninstalls
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
  form turntable <project> --fmt mp4|png|webp|gif      a turntable video or PNG sequence
  form compare-printers <project>                      slice on every printer: time, filament, cost
  form lighter <project> [--apply c1]                  lighter walls, pockets, infill; every passing check kept
  form replace --photo broken.jpg [--name X]           a replacement for a broken part, from a photo, in a chat
  form feature <project> boss --at x,y,z --normal ...  a screw boss or snap-fit hook in the code
  form verify <project> <release>    re-hash a release against its manifest
  form chat "message" [--project ID] [--conversation ID] [--agent claude|codex] [--model X] [--attach FILE] [--json]
                                     one message to an agent with FORM's tools; streams the reply, saves the conversation
  form conversations list|show|delete|rename|pin    saved conversations
  form start --text "…" [--photo F] [--file F] [--sketch F.json] [--link URL] [--purpose print|model] [--json]
                                     start a design the way Home does (words, photos, files, a sketch, links)
  form start --blank [--name N] [--purpose print|model]   a blank design: a rounded block to shape
  form concepts [<group-or-project> | pick <group> <project> [--keep-others]]   concepts to pick from
  form providers list|add URL|edit ID|test ID|remove ID   model providers added by URL (format and models detected)
  form simulate <project> --gif out.gif | --frames dir | --png out.png [--layers a:b] [--layer n]
                                     the sliced toolpaths building up, from the slicer's G-code (not a print)
  form cost <project> [--price-per-kg X --kwh-price Y --watts Z --copies N] [--save]
  form pack <project> --copies N [--spacing mm]   do N copies fit on one plate?
  form analyze <project> --map thickness|overhang|section|features [--json | --png out.png]
  form measure <project> --from x,y,z --to x,y,z   distance and its components; or --at x,y,z: what is at a point
  form orient <project> [--apply [id]]   rank the ways the part can lie on the plate; --apply sets the best (or the id given)
  form variants list|save|promote|delete <project> [name] [k=v ...]   named variants of a design
  form share <project> [--out card.png] [--photo]      1600 x 900 share card of the head revision
  form history <project> [--gif out.gif]               revisions (who, when, stamp); --gif animates them (.gif or .webp)
  form mark <project> --text "LABEL"                    label text for designs with a Label parameter
  form rename <project> <name>                          change the display name (the id stays)
  form duplicate <project> [--name N]                   copy a project under a new id; the copy is not approved
  form delete <project> --yes                           move a project to .trash inside the projects folder
  form export <project> [--out f.formstudio] [--no-conversations]   project + conversations + design code, one file
  form import <file.formstudio | file.formproj | conversation.json>   import; a clashing id gets a new one
  form export-conversation <id> [--format md|json] [--out file]       one conversation as Markdown or JSON
  form starters [add "text" | edit ID "text" | remove ID | pin ID | unpin ID | restore]   Home's learned starters
  form recipes [list|inspect|install|uninstall|community|source] ...  the recipe library (installs need --sha256)
  form recipes [export|import|submit|derive] ...  share a recipe as a .formrecipe, prepare a community submission,
                                     turn a design into a recipe (nothing is uploaded; installs need --sha256)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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


def _utf8_streams() -> None:
    """Output is JSON with real characters (Δ, ·, °, names in any language). A Windows console or pipe defaults to a
    legacy code page that cannot encode them, and `form run` then fails with 'charmap codec can't encode'."""
    for s in (sys.stdout, sys.stderr):
        try:
            if (getattr(s, "encoding", "") or "").lower().replace("-", "") != "utf8":
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass                                   # replaced streams (tests, embedders) keep their own encoding


def _tool(args) -> int:
    """form tool                      list every MCP tool
       form tool NAME [JSON | -]      call one, arguments as a JSON object (or JSON on stdin with -)"""
    import asyncio
    from . import mcp_server
    srv = mcp_server.build()
    if not args or args[0] in ("-h", "--help", "list"):
        tools = asyncio.run(srv.list_tools())
        _print({"tools": [{"name": t.name, "summary": (t.description or "").strip().splitlines()[0][:160]} for t in tools],
                "call_with": "form tool NAME '{\"key\": value}'"})
        return 0
    name, raw = args[0], (args[1] if len(args) > 1 else "{}")
    if raw == "-":
        raw = sys.stdin.read() or "{}"
    try:
        kw = json.loads(raw)
        if not isinstance(kw, dict):
            raise ValueError("not an object")
    except ValueError as e:
        _print({"error": {"message": f"The arguments must be one JSON object: {e}", "hint": "form tool NAME '{\"project\": \"my-part\"}'"}})
        return 2
    try:
        out = asyncio.run(srv.call_tool(name, kw))
    except Exception as e:                          # unknown tool, bad arguments, or the tool's own refusal
        _print({"error": {"message": str(e), "hint": "form tool lists every tool; docs/MCP.md has their arguments."}})
        return 1
    if getattr(out, "is_error", getattr(out, "isError", False)):
        texts = [getattr(b, "text", "") for b in getattr(out, "content", [])]
        _print({"error": {"message": " ".join(texts).strip() or "The tool refused.", "hint": ""}})
        return 1
    structured = getattr(out, "structured_content", None) or getattr(out, "structuredContent", None)
    if structured is not None:
        _print(structured["result"] if isinstance(structured, dict) and set(structured) == {"result"} else structured)
        return 0
    res = [b.text for b in getattr(out, "content", []) if getattr(b, "text", None) is not None]
    try:
        _print(json.loads(res[0]) if len(res) == 1 else {"content": res})
    except ValueError:
        _print({"content": res})
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _utf8_streams()
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
    if argv[:1] == ["replace"]:                   # a replacement for a broken part: the guided brief, sent as one chat
        from . import replace
        from .chat import main_chat
        ap = argparse.ArgumentParser(prog="form replace", description="Design a replacement for a broken part from a photo: "
                                     "the agent estimates sizes from a reference object in the photo, asks you for the "
                                     "critical measurements, then designs it.")
        ap.add_argument("--photo", required=True, action="append", metavar="FILE", help="photo of the broken part (repeat)")
        ap.add_argument("--name", default="")
        ap.add_argument("--what", default="", help="what the part does, what it attaches to")
        ap.add_argument("--broke", default="", help="where and how it broke")
        ap.add_argument("--reference", default="card", choices=list(replace.REFERENCES), help="the object in the photo that gives the scale")
        ap.add_argument("--coin", default="", help="which coin, with --reference coin")
        ap.add_argument("--brief-only", action="store_true", help="print the message instead of sending it")
        a, rest = ap.parse_known_args(argv[1:])
        msg = replace.brief(a.name, a.what, a.reference, a.coin, a.broke)
        if a.brief_only:
            print(json.dumps({"message": msg, "steps": replace.STEPS, "photos": a.photo}, indent=1, ensure_ascii=False))
            return 0
        return main_chat([msg] + sum((["--attach", f] for f in a.photo), []) + rest)
    if argv[:1] == ["conversations"]:             # saved conversations: list | show | delete | rename | pin
        from .chat import main_conversations
        return main_conversations(argv[1:])
    if argv[:1] == ["start"]:                     # how a design starts: Home's composer, or a blank design
        from .start import main as start_main
        return start_main(argv[1:])
    if argv[:1] == ["concepts"]:                  # concepts first: open groups, one board, pick one
        from .concepts import main as concepts_main
        return concepts_main(argv[1:])
    # -- home workstream: archives, conversation export, learned starters, recipe library (each prints JSON) --
    if argv[:1] in (["export"], ["import"], ["export-conversation"]):
        from . import bundle
        return {"export": bundle.main_export, "import": bundle.main_import,
                "export-conversation": bundle.main_export_conversation}[argv[0]](argv[1:])
    if argv[:1] == ["starters"]:
        from .starters import main as starters_main
        return starters_main(argv[1:])
    if argv[:1] == ["recipes"]:
        from .recipe_lib import main as recipes_main
        return recipes_main(argv[1:])
    # -- setup workstream: installer, settings, capabilities (each prints JSON; none starts the kernel) --
    if argv[:1] == ["install"]:
        from .installer import main as install_main
        return install_main(argv[1:])
    if argv[:1] == ["printers"]:                  # engine workstream: printers in every slicer, per-design choice
        from .printers import main as printers_main
        return printers_main(argv[1:])
    if argv[:1] in (["plates"], ["design-only"], ["material"], ["purpose"]):   # engine workstream: plates, Design only, materials
        from .plates import main_cli
        return main_cli(argv)
    if argv[:1] == ["config"]:
        from .config_edit import main as config_main
        return config_main(argv[1:])
    if argv[:1] == ["providers"]:                  # model providers added by URL; keys never on the command line
        from .agents.custom import main as providers_main
        return providers_main(argv[1:])
    if argv[:1] == ["secrets"]:                    # agent keys (Gemini); values never on the command line
        from .secrets import main as secrets_main
        return secrets_main(argv[1:])
    if argv[:1] == ["tool"]:                       # any MCP tool, headless, with the same arguments and rules
        return _tool(argv[1:])
    if argv[:1] == ["capabilities"]:
        from . import config, setup_app
        from .studio import StudioError
        cfg = config.load()
        try:
            if argv[1:2] in (["on"], ["off"]) and len(argv) == 3:
                out = setup_app.set_capabilities(cfg, {"id": argv[2], "on": argv[1] == "on"})
                out["next"] = ("form setup --auto installs " + ", ".join(out["install"])) if out["install"] else "nothing to install"
            elif len(argv) == 1:
                out = setup_app.capabilities_view(cfg)
            else:
                _print({"error": {"message": "Use: form capabilities [on|off <id>]"}})
                return 2
            _print(out)
        except StudioError as e:
            _print({"error": e.public()})
            return 2
        return 0
    ap = argparse.ArgumentParser(prog="form", description="Form Studio AI CAD studio",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n", 2)[2])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("app", help="open the desktop app (needs the [app] extra)")
    sub.add_parser("serve", help="start the bench on loopback")
    m = sub.add_parser("mcp", help="MCP server over stdio")
    m.add_argument("--no-bench", action="store_true")
    sub.add_parser("setup", help="find what is missing and fix what you choose (--check, --yes, --dry-run)")
    sub.add_parser("update", help="is there a newer Form Studio? (--check prints JSON; never installs)")
    sub.add_parser("chat", help='send one message to an agent: form chat "message" [--project ID] [--model X] [--json]')
    sub.add_parser("conversations", help="saved conversations: list | show ID | delete ID | rename ID TITLE | pin ID")
    sub.add_parser("start", help='start a design: --text "…" [--photo F] [--file F] [--sketch F.json] [--link URL] '
                                 '[--purpose print|model], or --blank [--name N]')
    sub.add_parser("concepts", help="concept groups: [<group-or-project>] | pick <group> <project> [--keep-others]")
    sub.add_parser("install", help="install what Form Studio uses (--list, <id>, --yes, --dry-run)")
    sub.add_parser("config", help="get [key] | set <key> <value>: read or change studio.toml")
    sub.add_parser("plates", help="how the design's parts go onto plates | --orient PART=O --material PART=M --color PART=#hex")
    sub.add_parser("design-only", help="design-only <project> on|off: slice this design or not (Design only)")
    sub.add_parser("purpose", help="purpose <project> [print|model] [--process cnc|laser|...]: what the design is for")
    sub.add_parser("material", help="material <project> PLA|PETG|ABS|ASA|TPU|... ('' clears): the filament the slice uses")
    sub.add_parser("printers", help="every printer in your slicers | options KIND NAME | use KIND NAME (--project ID | --default)")
    sub.add_parser("secrets", help="status | set NAME (value from stdin or a hidden prompt) | clear NAME: agent keys such as gemini_api_key")
    sub.add_parser("providers", help="list | add URL [--name N] | edit ID | test ID [--model M --tools|--images] | remove ID: "
                                     "model providers added by URL; the key is read from stdin or a hidden prompt")
    sub.add_parser("capabilities", help="what Form Studio is set up for | on|off <id> (core, parts, mesh, render, exchange, print)")
    sub.add_parser("doctor")
    sub.add_parser("list")
    r = sub.add_parser("recipe")
    r.add_argument("recipe")
    n = sub.add_parser("new")
    n.add_argument("name")
    n.add_argument("recipe")
    n.add_argument("values", nargs="*")
    n.add_argument("--brief", default="")
    n.add_argument("--purpose", default=None, help="print (for 3D printing) or model (just a 3D model); default from [general].printing")
    n.add_argument("--process", default=None, help="for a model: cnc, laser, injection, casting, sheet_metal, render, cad, other")
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
    tt = sub.add_parser("turntable", help="a turntable of the part: --fmt webp|gif|png (a PNG sequence)|mp4 (needs ffmpeg)")
    tt.add_argument("project")
    tt.add_argument("--fmt", default="webp", choices=["webp", "gif", "png", "mp4"])
    tt.add_argument("--frames", type=int, default=36)
    tt.add_argument("--elevation", type=float, default=24, help="camera height, degrees above the horizon")
    tt.add_argument("--out", help="copy the file here")
    lt = sub.add_parser("lighter", help="search wall, pocket and infill changes that cut mass while every passing check still passes")
    lt.add_argument("project")
    lt.add_argument("--builds", type=int, default=4, help="how many geometry candidates go through the full checks")
    lt.add_argument("--apply", metavar="ID", help="keep candidate ID (c1, c2, ...) from the search")
    lt.add_argument("--expect-head", type=int)
    cp = sub.add_parser("compare-printers", help="slice the design on every printer in your slicers: time, filament, cost")
    cp.add_argument("project")
    cp.add_argument("--limit", type=int, default=8, help="how many printers (the selected ones first)")
    cp.add_argument("--printer", action="append", metavar="ID", help="only these printer ids (form printers lists them)")
    fe = sub.add_parser("feature", help="a screw boss or snap-fit hook on a flat face, written into the design's code: "
                                        "feature <project> boss|snap_hook --at x,y,z --normal x,y,z [options] | --list | --remove ID")
    fe.add_argument("project")
    fe.add_argument("kind", nargs="?", choices=["boss", "snap_hook"])
    fe.add_argument("--at", metavar="x,y,z")
    fe.add_argument("--normal", metavar="x,y,z")
    fe.add_argument("--up", metavar="x,y,z", help="which way the snap hook's lip faces (its plane's up)")
    fe.add_argument("--size", default="M3", help="boss screw size, M2 to M5")
    fe.add_argument("--hole", default="tapped", choices=["tapped", "clearance", "insert"])
    for k in ("height", "outer_d", "hole_d", "hole_depth", "length", "thickness", "width", "lip", "lip_height"):
        fe.add_argument("--" + k.replace("_", "-"), dest=k, type=float)
    fe.add_argument("--allow-strain", type=float, help="the hook material's allowable strain, e.g. 0.03")
    fe.add_argument("--list", action="store_true")
    fe.add_argument("--remove", metavar="ID")
    fe.add_argument("--expect-head", type=int)
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
    rf = sub.add_parser("release-files", help="every file of a release in one .zip: models, G-code, sliced 3MF, report, documents")
    rf.add_argument("project")
    rf.add_argument("release", nargs="?", help="r03 (default: the newest release)")
    rf.add_argument("--out", help="where to write the .zip (default: <project>-<release>.zip here)")
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
    # ---- design tools: variants, share card, history, label text ----
    va = sub.add_parser("variants", help="named variants: list, save, promote, delete")
    va.add_argument("action", choices=["list", "save", "promote", "delete"])
    va.add_argument("project")
    va.add_argument("name", nargs="?", default="")
    va.add_argument("values", nargs="*", help="k=v changes on top of the head (save)")
    va.add_argument("--rev", type=int, help="save this revision instead of the head")
    va.add_argument("--note", default="")
    sh = sub.add_parser("share", help="share card PNG of the head revision")
    sh.add_argument("project")
    sh.add_argument("--out")
    sh.add_argument("--photo", action="store_true", help="use the newest current Blender render as the picture")
    hi = sub.add_parser("history", help="revision list; --gif writes an animation through the revisions")
    hi.add_argument("project")
    hi.add_argument("--gif", metavar="FILE", help="write .gif or .webp")
    mk = sub.add_parser("mark", help="label text for designs with marks")
    mk.add_argument("project")
    mk.add_argument("--text", required=True)
    rn = sub.add_parser("rename", help="change a project's display name (the id stays)")
    rn.add_argument("project")
    rn.add_argument("name")
    du = sub.add_parser("duplicate", help="copy a project under a new id; the copy is not approved")
    du.add_argument("project")
    du.add_argument("--name")
    de = sub.add_parser("delete", help="move a project to .trash inside the projects folder (needs --yes)")
    de.add_argument("project")
    de.add_argument("--yes", action="store_true", help="really move it to the trash")
    # -- maker tools (form/engrave.py, form/geomdiff.py, form/instructions.py) --
    eg = sub.add_parser("engrave", help="text on a flat face as a real feature: engrave <project> TEXT --at x,y,z --normal x,y,z "
                                        "[--height 6 --depth 0.6 --sunk] | --list | --remove text_N")
    eg.add_argument("project")
    eg.add_argument("text", nargs="?", default="")
    eg.add_argument("--at", metavar="x,y,z", help="a point on the face, mm (form select --face gives one)")
    eg.add_argument("--normal", metavar="x,y,z", help="the face's outward normal")
    eg.add_argument("--up", metavar="x,y,z", help="which way the capitals point (default: up on a wall, +Y on a floor)")
    eg.add_argument("--height", type=float, default=6.0, help="cap height, mm")
    eg.add_argument("--depth", type=float, default=0.6, help="how far the letters stand out or sink in, mm")
    eg.add_argument("--sunk", action="store_true", help="cut the text into the face instead of raising it")
    eg.add_argument("--list", action="store_true")
    eg.add_argument("--remove", metavar="ID")
    eg.add_argument("--expect-head", type=int)
    gd = sub.add_parser("diff", help="what changed between two revisions, computed on the solids: diff <project> A [B] [--png FILE]")
    gd.add_argument("project")
    gd.add_argument("a", type=int)
    gd.add_argument("b", type=int, nargs="?")
    gd.add_argument("--png", help="also write the picture (added green, removed red) here")
    rc = sub.add_parser("reconstruct", help="a mesh (STL, OBJ, 3MF) as editable CAD, verified against it: reconstruct FILE "
                                            "[--name N] [--tolerance MM] [--layer 0|1|2]")
    rc.add_argument("file")
    rc.add_argument("--name")
    rc.add_argument("--tolerance", type=float, default=0.02, help="largest deviation from the mesh for a fitted surface, mm")
    rc.add_argument("--layer", type=int, choices=(0, 1, 2), default=2,
                    help="0: exact solid only, 1: analytic and B-spline faces (beta), 2: feature tree recipe (beta)")
    ins = sub.add_parser("instructions", help="assembly instructions as a PDF from the assembly declaration: instructions <project> [--rev N] [--out FILE]")
    ins.add_argument("project")
    ins.add_argument("--rev", type=int)
    ins.add_argument("--out", help="copy the PDF here")
    # -- selections, annotations, colours and materials (form/selection.py, form/materials.py) --
    se = sub.add_parser("select", help="analyse points, edges, faces or a painted region on the solid; --keep saves it as an annotation")
    se.add_argument("project")
    for k in ("point", "edge", "face"):
        se.add_argument(f"--{k}", action="append", default=[], metavar="x,y,z", help=f"a {k} at this surface point (repeatable)")
    se.add_argument("--region", action="append", default=[], metavar="x,y,z;x,y,z;...", help="surface within --radius of these points")
    se.add_argument("--radius", type=float, default=2.0, help="region radius, mm")
    se.add_argument("--keep", metavar="NAME", help="keep it with the head revision under this name")
    se.add_argument("--note", default="")
    se.add_argument("--text", action="store_true", help="print the description instead of JSON")
    an_ = sub.add_parser("annotations", help="kept selections: list | show ID | delete ID")
    an_.add_argument("project")
    an_.add_argument("verb", nargs="?", default="list", choices=["list", "show", "delete"])
    an_.add_argument("id", nargs="?")
    apx = sub.add_parser("appearance", help="colour and material of the design or one part: --color #rrggbb --material petg [--part ID]")
    apx.add_argument("project")
    apx.add_argument("--part", default="")
    apx.add_argument("--color")
    apx.add_argument("--material", help="PLA, PETG, ABS, ASA, TPU, PA, PC, PLA-CF, PETG-CF, PA-CF")
    apx.add_argument("--clear", action="store_true", help="remove the colour and material of the design or that part")
    apx.add_argument("--3mf", dest="threemf", metavar="FILE", help="write a 3MF of the head with these colours")
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
                raise StudioError(f"Unknown recipe “{a.recipe}”.", "Known: " + ", ".join(st.recipes.builtins()))
            r = st.recipes[a.recipe]
            _print({**r.public(), "features": [{"id": f.id, "label": f.label, "role": f.role} for f in r.features]})
        elif a.cmd == "new":
            p = st.create(a.name, a.recipe, a.brief, _kv(a.values), purpose=a.purpose, process=a.process)
            job = st.run_sync(p["id"])
            _print({"pipeline": job_digest(job), "project": digest(st, p["id"])})
        elif a.cmd == "state":
            _print(digest(st, a.project))
        elif a.cmd == "reconstruct":
            last = [0.0]

            def show(d):                                  # progress on stderr: stdout stays JSON
                import time as _t
                if _t.monotonic() - last[0] > 1.5:
                    last[0] = _t.monotonic()
                    print(f"[{100 * float(d.get('fraction', 0)):3.0f}%] {d.get('text', '')}", file=sys.stderr, flush=True)
            _print(st.reconstruct(Path(a.file), name=a.name, tolerance=a.tolerance, layer=a.layer, on_progress=show))
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
        elif a.cmd == "turntable":
            from . import animate
            info = animate.export(st, st.load(a.project), a.fmt, a.frames, a.elevation)
            if a.out:
                import shutil as _sh
                _sh.copyfile(info["file"], a.out)
                info["copied_to"] = a.out
            _print(info)
        elif a.cmd == "lighter":
            from . import lighten
            p = st.load(a.project)
            if a.apply:
                r = lighten.cached(st, p) or lighten.search(st, p, builds=a.builds)
                c = next((x for x in r["candidates"] if x["id"] == a.apply), None)
                if c is None:
                    raise StudioError(f"No candidate {a.apply}.", "Run `form lighter <project>` and pick one of its ids.")
                out = lighten.apply(st, p, c, a.expect_head, origin="cli")
                if c.get("changes"):
                    out["job"] = st.run_sync(a.project)["state"]
                _print(out)
            else:
                _print(lighten.search(st, p, builds=a.builds))
        elif a.cmd == "compare-printers":
            from . import slicecompare
            _print(slicecompare.compare(st, st.load(a.project), a.limit, a.printer))
        elif a.cmd == "feature":
            from . import feature_helpers as fh
            xyz = lambda t: [float(x) for x in t.split(",")]
            p = st.load(a.project)
            if a.list:
                _print({"features": fh.list_features(st, p)})
            elif a.remove:
                _print(fh.remove(st, p, a.remove, a.expect_head, origin="cli"))
            else:
                if not (a.kind and a.at and a.normal):
                    raise StudioError("Give boss or snap_hook, --at x,y,z and --normal x,y,z.", "`form select <project> --face x,y,z` reports a face's point and normal.")
                o = {k: getattr(a, k) for k in ("size", "hole", "height", "outer_d", "hole_d", "hole_depth", "length", "thickness",
                                                "width", "lip", "lip_height") if getattr(a, k) is not None}
                if a.up:
                    o["up"] = xyz(a.up)
                out = fh.add(st, p, a.kind, xyz(a.at), xyz(a.normal), a.expect_head, "cli", **o)
                out["checks"] = fh.checks(out["features"][-1], st.slicer_info(p=p).get("nozzle_mm"), a.allow_strain)
                _print(out)
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
        elif a.cmd == "engrave":
            from . import engrave
            xyz = lambda t: [float(x) for x in t.split(",")]
            p = st.load(a.project)
            if a.list:
                _print({"marks": engrave.list_marks(st, p)})
            elif a.remove:
                _print(engrave.remove(st, p, a.remove, a.expect_head, origin="cli"))
            else:
                if not (a.text and a.at and a.normal):
                    raise StudioError("Give the text, --at x,y,z and --normal x,y,z.", "`form select <project> --face x,y,z` reports a face's point and normal.")
                nz = st.slicer_info(p=p).get("nozzle_mm")
                out = engrave.add(st, p, a.text, xyz(a.at), xyz(a.normal), a.height, a.depth, a.sunk, xyz(a.up) if a.up else None,
                                  a.expect_head, origin="cli")
                out["printability"] = engrave.printability(a.text, a.height, a.depth, a.sunk, nz)
                _print(out)
        elif a.cmd == "diff":
            from . import geomdiff
            import shutil as _sh
            p = st.load(a.project)
            d = geomdiff.compute(st, p, a.a, a.b)
            if a.png:
                _sh.copyfile(geomdiff.png_path(st, p, d), a.png)
                d["png"] = str(Path(a.png).resolve())
            _print(d)
        elif a.cmd == "instructions":
            from . import instructions
            import shutil as _sh
            out = instructions.build(st, st.load(a.project), a.rev)
            if a.out:
                _sh.copyfile(out["pdf_path"], a.out)
                out["pdf_path"] = str(Path(a.out).resolve())
            _print(out)
        elif a.cmd == "select":
            from . import selection
            xyz = lambda t: [float(x) for x in t.split(",")]
            items = [{"kind": k, "at": xyz(v)} for k in ("point", "edge", "face") for v in getattr(a, k)]
            items += [{"kind": "region", "points": [xyz(q) for q in r.split(";") if q.strip()], "radius": a.radius} for r in a.region]
            if a.keep:
                out = selection.add(st, a.project, items, a.keep, a.note, by="cli")
                print(out["text"]) if a.text else _print(out)
            else:
                out = selection.analyze(st, st.load(a.project), items)
                for x in out["items"]:
                    x.pop("mesh", None)
                    if isinstance(x.get("edge"), dict):
                        x["edge"].pop("segments", None)
                print(out["text"]) if a.text else _print(out)
        elif a.cmd == "appearance":
            from . import materials
            if a.clear or a.color is not None or a.material is not None:
                materials.set_appearance(st, a.project, a.part, None if a.clear else (a.color if a.color is not None else "keep"),
                                         None if a.clear else (a.material if a.material is not None else "keep"), by="cli")
            p = st.load(a.project)
            out = {"appearance": materials.appearance(p)}
            if a.threemf:
                with open(a.threemf, "wb") as f:
                    f.write(materials.threemf(st, p))
                out["3mf"] = a.threemf
            _print(out)
        elif a.cmd == "annotations":
            from . import selection
            if a.verb == "list":
                _print([{k: x[k] for k in ("id", "name", "note", "rev", "by")} for x in selection.listing(st, a.project)])
            elif not a.id:
                raise StudioError("Name the annotation: form annotations <project> show|delete <id>.")
            elif a.verb == "show":
                x = next((x for x in selection.listing(st, a.project) if x["id"] == a.id), None)
                if x is None:
                    raise StudioError("Unknown annotation.", "List them with: form annotations <project>.")
                _print(x)
            else:
                _print(selection.delete(st, a.project, a.id))
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
        elif a.cmd == "release-files":
            import shutil
            from . import maker_docs
            p = st.load(a.project)
            rels = sorted(d.name for d in (st.dir(p["id"]) / "releases").glob("*") if (d / "MANIFEST.json").is_file()) \
                if (st.dir(p["id"]) / "releases").is_dir() else []
            release = a.release or (rels[-1] if rels else None)
            if not release:
                raise StudioError("This design has no release yet.", "A person approves a revision in the app (Release); then its files can be saved here.")
            z = maker_docs.release_files_zip(st, p, release)
            out = Path(a.out or f"{p['id']}-{release}.zip").expanduser().resolve()
            shutil.move(str(z), out)
            with __import__("zipfile").ZipFile(out) as zf:
                names = zf.namelist()
            _print({"project": p["id"], "release": release, "zip": str(out), "files": len(names), "bytes": out.stat().st_size})
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
        elif a.cmd == "variants":
            from . import variants
            p = st.load(a.project)
            if a.action == "list":
                _print(variants.board(st, p))
            elif not a.name:
                raise StudioError("Name the variant.", f"form variants {a.action} {a.project} \"Thick walls\"")
            elif a.action == "save":
                _print(variants.save(st, p, a.name, _kv(a.values) or None, a.rev, a.note, "you (CLI)"))
            elif a.action == "delete":
                _print(variants.delete(st, p, a.name))
            else:
                res = variants.promote(st, p, a.name, "cli")
                job = st.run_sync(a.project)
                _print({**res, "pipeline": job_digest(job), "project": digest(st, a.project)})
        elif a.cmd == "share":
            from . import share
            c = share.card(st, st.load(a.project), a.out or f"{a.project}_card.png", "photo" if a.photo else "model")
            _print({"png": c["out"], "size": c["size"], "revision": c["rev"], "facts": c["facts"]["rows"],
                    "evidence": c["facts"]["evidence_level"]})
        elif a.cmd == "history":
            from . import share
            p = st.load(a.project)
            out = {"project": p["id"], "head": p["head"], "revisions": share.revisions(st, p)}
            if a.gif:
                out["animation"] = share.history(st, p, a.gif)
            _print(out)
        elif a.cmd == "mark":
            p = st.settings(st.load(a.project), {"mark_text": a.text})
            _print({"project": p["id"], "label_text": p.get("mark_text") or p["name"],
                    "note": "Used by designs with a Label parameter. Outputs for such a revision are stale until you run the pipeline."})
        elif a.cmd == "rename":
            _print(st.rename_project(a.project, a.name))
        elif a.cmd == "duplicate":
            _print(st.duplicate_project(a.project, a.name))
        elif a.cmd == "delete":
            if not a.yes:
                st.load(a.project)                              # an unknown project is reported as such
                raise StudioError(f"Nothing was deleted. “{a.project}” would be moved to {st.root / '.trash'}.",
                                  f"Run it again with --yes: form delete {a.project} --yes")
            _print(st.delete_project(a.project))
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
