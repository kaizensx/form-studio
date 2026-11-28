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
  form optimize pareto <project> --minimize mass_g --require "fea.safety_factor>=3"
                                     inverse design: the variants that meet a requirement, on a Pareto front; JSON
  form optimize topology <project> --volfrac 0.5
                                     topology optimisation written back as features (--apply keeps it); JSON
  form animate <project> [--morph 1:4] [--out x.gif]   turntable or revision morph
  form turntable <project> --fmt mp4|png|webp|gif      a turntable video or PNG sequence
  form compare-printers <project>                      slice on every printer: time, filament, cost
  form slicer-open <project> [--printer ID] [--explain] [--no-open]
                                     slice with settings chosen for this part, open the project in the slicer
  form lighter <project> [--apply c1]                  lighter walls, pockets, infill; every passing check kept
  form replace --photo broken.jpg [--name X]           a replacement for a broken part, from a photo, in a chat
  form feature <project> boss --at x,y,z --normal ...  a screw boss or snap-fit hook in the code
  form strength static <project> --fix X,Y,Z --force X,Y,Z:FX,FY,FZ --material AL-6061
                                     a strength study with a stated error (also modal, buckling, list, show, verify;
                                     `form study strength ...` is the same); JSON
  form study list|run|show <project> [id] [--force]   the Bench: every study, route and document, with its state
  form bench list|run|publish|cadbench|oracle          benchmarks: own suites and Parametric CAD Bench v3, published
  form calc <calculator> key=value ... [--build]   size a snap fit, hinge, spring, bolted joint, gear pair, cam or fit
                                     from a standard's equations; every number with its source (form calc list); JSON
  form testplan <project> [--out DIR]                 what to measure on the made part: PDF, Markdown, checklist
  form testplan record <project> TEST V... | --csv F   record what you measured (provenance measured)
  form report <project> [--out DIR]                   the results report: measured against the plan, open items, verdict
  form backup status|run|list|verify|restore|deleted|undelete|purge   backups and Recently deleted
  form tree <project> [suppress|restore|move|rename FEATURE] [--upto FEATURE]   the feature tree, by hand
  form model <project> fillet|chamfer|hole|pattern|shell --at x,y,z ... [--preview]   a picked feature as code
  form model <project> extrude|cut|revolve --sketch F.json [--at x,y,z] [--depth D]    a feature from a sketch
  form sketch <project> FEATURE [--ops JSON] [--set name=v]   a feature's sketch, solved; edit it
  form verify <project> <release>    re-hash a release against its manifest
  form chat "message" [--project ID] [--conversation ID] [--agent claude|codex] [--model X] [--attach FILE] [--json]
                                     one message to an agent with FORM's tools; streams the reply, saves the conversation
  form conversations list|show|delete|rename|pin|designs|migrate    saved conversations, the designs each made
  form start --text "…" [--photo F] [--file F] [--sketch F.json] [--link URL] [--purpose print|model] [--json]
                                     start a design the way Home does (words, photos, files, a sketch, links)
  form start --blank [--name N] [--purpose print|model]   a blank design: a rounded block to shape
  form concepts [<group-or-project> | pick <group> <project> [--keep-others]]   concepts to pick from
  form providers list|add URL|edit ID|test ID|remove ID   model providers added by URL (format and models detected)
  form simulate <project> --gif out.gif | --frames dir | --png out.png [--layers a:b] [--layer n]
                                     the sliced toolpaths building up, from the slicer's G-code (not a print)
  form cost <project> [--price-per-kg X --kwh-price Y --watts Z --copies N] [--save]
  form cost <project> --process fdm|sla|sls|mjf|lpbf|cnc|injection|sheet_metal|purchased [--qty 1,100,1000]
                                     a cost per process from its drivers, every rate sourced, yours or assumed
  form cost compare <project> [--processes fdm,cnc,injection] [--qty ...]   cost per part vs quantity, crossovers
  form cost rates [--shop S] [--rate ID=VALUE] [--currency EUR] [--fx USD=1.1] [--part-price D=X] [--use]
                                     the sourced rates table and your shops' own rates
  form pack <project> --copies N [--spacing mm]   do N copies fit on one plate?
  form analyze <project> --map thickness|overhang|section|features [--json | --png out.png]
  form measure <project> --from x,y,z --to x,y,z   distance and its components; or --at x,y,z: what is at a point
  form mass <project> [--part P] [--pose JSON] [--material M] [--frame as_built|assembled] [--library]
                                     mass, centre of mass, inertia and principal axes from the B-rep, per part and assembled
  form materials [ID]                the materials library: density and mechanical properties, each with its source
  form motion <project> [--drivers JSON] [--duration S] [--frames N] [--traces JSON] [--hold JSON] [--video]
                                     a motion study: loops closed, points traced, clearance along the cycle, holding torque
  form urdf|mjcf <project> [--collision auto|coacd|hull|box] [--assume M] [--limits JSON]
                                     robot files (URDF, SRDF, MJCF) with inertia and meshes per link, checked and parsed back
  form sequence <project> [--budget S]   an assembly order and each part's insertion direction (the explode follows it)
  form orient <project> [--apply [id]]   rank the ways the part can lie on the plate; --apply sets the best (or the id given)
  form print orient <project> [--cosmetic X,Y,Z] [--study ID | --load X,Y,Z] [--calibrate] [--verify N] [--pick ID]
                                     the Pareto front of print orientations (support, time, strength, surface,
                                     tip-over); --pick writes one to the print setup; --verify slices the best
  form print strength <project> --study ID [--orientation O]   strength as printed: a layered material, the safety
                                     factor across the layers and how it changes with orientation
  form print warp <project> [--orientation O] [--chamber C]    warp risk (an indicator, never a predicted lift); JSON
  form variants list|save|promote|delete <project> [name] [k=v ...]   named variants of a design
  form share <project> [--out card.png] [--photo]      1600 x 900 share card of the head revision
  form history <project> [--gif out.gif]               revisions (who, when, stamp); --gif animates them (.gif or .webp)
  form mark <project> --text "LABEL"                    label text for designs with a Label parameter
  form rename <project> <name>                          change the display name (the id stays)
  form duplicate <project> [--name N]                   copy a project under a new id; the copy is not approved
  form delete <project> --yes                           move a project to .trash inside the projects folder
  form export <project> [--out f.formstudio] [--no-conversations]   project + conversations + design code, one file
  form export fcstd <project> [--out f.FCStd] [--edit key=value ...]   a FreeCAD PartDesign feature tree (sketches,
                                     pads, holes, fillets, patterns, a Params spreadsheet), recomputed in FreeCAD and
                                     compared with Form Studio's solid (JSON)
  form import <file.formstudio | file.formproj | conversation.json>   import; a clashing id gets a new one
  form formats                                          every file format Form Studio reads (kind, units), as JSON
  form import-reference <project> FILE [--name N]       keep a part, mesh, scan or zip of them as a reference
  form export-conversation <id> [--format md|json] [--out file]       one conversation as Markdown or JSON
  form starters [add "text" | edit ID "text" | remove ID | pin ID | unpin ID | restore]   Home's learned starters
  form recipes [list|inspect|install|uninstall|source] ...  the agents' building blocks (installs need --sha256)
  form recipes [export|import|derive] ...  a recipe as a .formrecipe file, or a design turned into a recipe
                                     (nothing is uploaded; installs need --sha256)
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
    blocks = list(getattr(out, "content", []))
    res = [b.text for b in blocks if getattr(b, "text", None) is not None]
    images = _save_images(name, blocks)
    try:                                           # the first block is the tool's JSON; later ones are captions
        first = json.loads(res[0]) if res else {}
        body = first if len(res) == 1 else ({**first, "notes": res[1:]} if isinstance(first, dict) else {"content": res})
    except ValueError:
        body = {"content": res}
    if images:                                     # a terminal cannot show pictures: say where they are, so you can open them
        body = {**body, "images": images} if isinstance(body, dict) else {"result": body, "images": images}
    _print(body)
    return 0


def _save_images(tool: str, blocks) -> list[str]:
    """Write the tool's image blocks (sheets, sections, close-ups, renders) to PNG files and return their paths."""
    import base64
    import tempfile
    import time
    imgs = [b for b in blocks if getattr(b, "type", "") == "image" and getattr(b, "data", None)]
    if not imgs:
        return []
    d = Path(tempfile.gettempdir()) / "form-tool-images"
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = []
    for i, b in enumerate(imgs):
        ext = (getattr(b, "mime_type", None) or getattr(b, "mimeType", None) or "image/png").split("/")[-1]
        f = d / f"{tool}-{stamp}-{i + 1}.{ext}"
        f.write_bytes(base64.b64decode(b.data))
        out.append(str(f))
    return out


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
    if argv[:1] in (["fetch"], ["resolve"], ["mesh-preflight"]):   # inputs: model links and big meshes (JSON)
        from .start import main_inputs
        return main_inputs(argv)
    if argv[:1] == ["formats"]:                   # every file format Form Studio reads (form/formats.py), as JSON
        from .formats import cli_table
        print(json.dumps(cli_table(), indent=1))
        return 0
    if argv[:1] == ["triage"]:                    # what an input is and the route it takes (JSON)
        from .triage import main as triage_main
        return triage_main(argv[1:])
    if argv[:1] == ["concepts"]:                  # concepts first: open groups, one board, pick one
        from .concepts import main as concepts_main
        return concepts_main(argv[1:])
    # -- home workstream: archives, conversation export, learned starters, recipe library (each prints JSON) --
    if argv[:2] == ["export", "fcstd"]:           # a FreeCAD PartDesign feature tree, checked in FreeCAD (JSON)
        from .partdesign import main as fcstd_main
        return fcstd_main(argv[2:])
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
    if argv[:1] == ["bench"]:                      # benchmarks in public: own suites, Parametric CAD Bench v3
        from .bench import main_cli as bench_main
        return bench_main(argv[1:])
    if argv[:1] == ["strength"] or (argv[:1] == ["study"] and argv[1:2] and argv[1] in ("strength", "static", "modal", "buckling", "thermal", "thermal_stress", "verify")):
        from .fea.cli import main as strength_main  # strength studies with a stated error (form/fea)
        return strength_main(argv[1:] if argv[0] == "strength" else argv[2:] if argv[1] == "strength" else argv[1:])
    if argv[:1] == ["print"]:                      # print physics: orientation front, layered strength, warp (form/printphys)
        from .printphys.cli import main as print_main
        return print_main(argv[1:])
    if argv[:1] == ["optimize"] and argv[1:2] and argv[1] in ("pareto", "topology"):
        from .inverse.cli import main as search_main  # inverse design and topology optimisation (form/inverse, form/topo)
        return search_main(argv[1:])
    if argv[:1] == ["stack"]:                      # tolerance stack-up from the assembly (form/stack)
        from .stack.cli import main as stack_main
        return stack_main(argv[1:])
    if argv[:1] == ["calc"]:                       # engineering calculators that write geometry (form/calc)
        from .calc.cli import main as calc_main
        return calc_main(argv[1:])
    if argv[:1] == ["study"]:                      # the Bench: every study, route and document with its state (form/studies.py)
        from .studies import main_cli as study_main
        return study_main(argv[1:])
    if argv[:1] == ["testplan"]:                   # what to measure on the made part, and results (form/reports.py)
        from .reports import main_testplan
        return main_testplan(argv[1:])
    if argv[:1] == ["report"]:                     # the results report: measured against the plan, and what is open
        from .reports import main_report
        return main_report(argv[1:])
    if argv[:1] == ["backup"]:                     # backups of designs and conversations, recently deleted (form/backup.py)
        from .backup import main as backup_main
        return backup_main(argv[1:])
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
    sub.add_parser("conversations", help="saved conversations: list | show ID | delete ID | rename ID TITLE | pin ID | designs ID | migrate")
    sub.add_parser("start", help='start a design: --text "…" [--photo F] [--file F] [--sketch F.json] [--link URL] '
                                 '[--purpose print|model], or --blank [--name N]')
    sub.add_parser("fetch", help="fetch URL [--conversation ID]: download a linked file or a model page's files (JSON)")
    sub.add_parser("resolve", help="resolve URL: what a model link is (site, title, licence, files) without downloading")
    sub.add_parser("mesh-preflight", help="mesh-preflight FILE [--no-proxy]: triangles, size, closed, class, time "
                                          "estimate and a display proxy for a large mesh or scan")
    sub.add_parser("triage", help="triage FILE|LINK|WORDS: what the input is (mesh class, defects, units, bodies) and "
                                  "the route Form Studio takes for it (JSON); any format `form formats` lists")
    sub.add_parser("formats", help="every file format Form Studio reads, with its kind and units (JSON)")
    ir = sub.add_parser("import-reference", help="import-reference <project> FILE [--name N]: keep a part, mesh, scan "
                                                 "or zip of them as a reference of the design (any 3D format `form "
                                                 "formats` lists)")
    ir.add_argument("project")
    ir.add_argument("file")
    ir.add_argument("--name")
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
            c.add_argument("--upto", metavar="FEATURE", help="the head as it stood after this feature (never saved)")
    o = sub.add_parser("optimize", help="goal seek over parameters")
    o.add_argument("project")
    o.add_argument("--vary", action="append", required=True, help="key:min:max (repeat)")
    g = o.add_mutually_exclusive_group(required=True)
    g.add_argument("--minimize")
    g.add_argument("--maximize")
    o.add_argument("--require", action="append", default=[], help='constraint, e.g. "statics.safety_factor>=3"')
    o.add_argument("--budget", type=int, default=40)
    o.add_argument("--study", default="", help='the static strength study a "fea.safety_factor>=2" constraint is read from')
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
    lt.add_argument("--require", action="append", default=[], help='a strength constraint to keep, e.g. "fea.safety_factor>=2"')
    lt.add_argument("--study", default="", help="the static strength study the constraint is read from")
    so = sub.add_parser("slicer-open", help="slice with settings chosen for this part on this printer and open the project in the slicer")
    so.add_argument("project")
    so.add_argument("--printer", metavar="ID", help="a printer id from `form printers` (default: the design's printer)")
    so.add_argument("--explain", action="store_true", help="lead the JSON with each decision as one plain line")
    so.add_argument("--no-open", action="store_true", help="slice and write the project 3MF, but do not open the slicer")
    so.add_argument("--copies", type=int, default=1, help="this many of the design, on as many plates as it takes")
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
    # -- modelling by hand (form/modelling.py): the feature tree and picked features, written as the design's code --
    tr = sub.add_parser("tree", help="the feature tree: tree <project> (build order, suppressed, what each reads) | "
                                     "suppress|restore FEATURE | move FEATURE --after|--before F | rename FEATURE "
                                     "[--label L] [--id I] | --upto FEATURE (the rollback view)")
    tr.add_argument("project")
    tr.add_argument("action", nargs="?", choices=["suppress", "restore", "move", "rename"])
    tr.add_argument("feature", nargs="?")
    tr.add_argument("--after")
    tr.add_argument("--before")
    tr.add_argument("--label")
    tr.add_argument("--id", dest="new_id")
    tr.add_argument("--upto", metavar="FEATURE", help="the head as it stood after this feature (never saved)")
    tr.add_argument("--png", help="with --upto: write a picture of it here")
    tr.add_argument("--preview", action="store_true", help="build and report, save nothing")
    tr.add_argument("--expect-head", type=int)
    mo = sub.add_parser("model", help="a picked feature as code: model <project> fillet|chamfer|hole|pattern|shell "
                                      "[--at x,y,z ...] [options] [--preview]")
    mo.add_argument("project")
    mo.add_argument("kind", choices=["fillet", "chamfer", "hole", "pattern", "shell", "extrude", "cut", "revolve"])
    mo.add_argument("--sketch", metavar="FILE.json", help="extrude, cut, revolve: the sketch ({plane, points, entities, "
                    "constraints}); with --at, it goes on the face at that point")
    mo.add_argument("--axis-entity", type=int, help="revolve: the sketch line it turns about")
    mo.add_argument("--at", action="append", default=[], metavar="x,y,z", help="a point on an edge (fillet, chamfer) "
                    "or on a face (hole, shell); repeat for several edges")
    for k in ("radius", "length", "thickness", "nominal", "d", "depth", "pitch", "angle", "head_d", "head_depth"):
        mo.add_argument("--" + k.replace("_", "-"), dest=k, type=float)
    mo.add_argument("--count", type=int)
    mo.add_argument("--standard", choices=["clearance", "tapped", "iso286", "plain"])
    mo.add_argument("--size", help="hole screw size, M2 to M6")
    mo.add_argument("--fit", help="close|normal|loose (clearance) or a hole tolerance such as H7 (iso286)")
    mo.add_argument("--style", choices=["plain", "counterbore", "countersink"])
    mo.add_argument("--of", help="pattern: the feature to repeat")
    mo.add_argument("--mode", choices=["linear", "polar"])
    mo.add_argument("--axis", help="x, y, z or x,y,z")
    mo.add_argument("--origin", metavar="x,y,z", help="polar pattern: a point on the axis")
    mo.add_argument("--after", help="the feature it goes after (default: last)")
    mo.add_argument("--preview", action="store_true", help="build and report, save nothing")
    mo.add_argument("--expect-head", type=int)
    sk = sub.add_parser("sketch", help="a feature's sketch: sketch <project> FEATURE (solved, degrees of freedom) | "
                                       "--ops JSON|- | --set NAME=VALUE ... [--preview] | sketch --new NAME --file F.json "
                                       "[--depth D] (a new design from a sketch on a datum plane)")
    sk.add_argument("project", nargs="?")
    sk.add_argument("feature", nargs="?")
    sk.add_argument("--ops", help="edit_sketch ops as JSON, or - for stdin")
    sk.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="a named dimension's value")
    sk.add_argument("--preview", action="store_true")
    sk.add_argument("--expect-head", type=int)
    sk.add_argument("--new", metavar="NAME", help="start a design from --file (extruded --depth mm)")
    sk.add_argument("--file", metavar="F.json")
    sk.add_argument("--depth", type=float, default=10.0)
    sk.add_argument("--purpose", default="model")
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
    co = sub.add_parser("cost", help="filament, electricity and machine time for the current slice; with --process a cost "
                                     "per process (fdm, sla, sls, mjf, lpbf, cnc, injection, sheet_metal, purchased) at "
                                     "--qty quantities; cost compare <project>: curves and crossovers; cost rates: the "
                                     "sourced rates and your shops")
    co.add_argument("project", help="a project, or `compare` / `rates`")
    co.add_argument("extra", nargs="?", default="", help="with compare: the project")
    co.add_argument("--process", default="", help="fdm, sla, sls, mjf, lpbf, cnc, injection, sheet_metal, purchased")
    co.add_argument("--processes", default="", help="compare: a comma list (default: every process that applies)")
    co.add_argument("--qty", default="", help="quantities, e.g. 1,10,100,1000")
    co.add_argument("--option", action="append", default=[], metavar="PROCESS.KEY=VALUE",
                    help="e.g. injection.resin=ABS injection.cavities=2 cnc.tool_d=6")
    co.add_argument("--shop", default="")
    co.add_argument("--currency", default="")
    co.add_argument("--rate", action="append", default=[], metavar="ID=VALUE",
                    help="with a process or compare: a rate for this estimate only; with rates: a shop override "
                         "(ID= forgets it)")
    co.add_argument("--fx", action="append", default=[], metavar="CUR=PER_EUR", help="rates: your exchange rate")
    co.add_argument("--part-price", action="append", default=[], metavar="DESIGNATION=PRICE",
                    help="rates: a purchased part's price")
    co.add_argument("--label", default=None, help="rates: the shop's name")
    co.add_argument("--use", action="store_true", help="rates: make the shop the one costs use")
    co.add_argument("--delete", action="store_true", help="rates: delete the shop")
    co.add_argument("--full", action="store_true", help="every input with its source")
    co.add_argument("--price-per-kg", type=float)
    co.add_argument("--kwh-price", type=float)
    co.add_argument("--watts", type=float)
    co.add_argument("--machine-rate", type=float, help="per hour")
    co.add_argument("--copies", type=int, default=1)
    co.add_argument("--save", action="store_true", help="remember the given prices in <data dir>/cost.json")
    pk = sub.add_parser("pack", help="do N copies fit on one plate? (and how many plates they take)")
    pk.add_argument("project")
    pk.add_argument("--copies", type=int, default=1)
    pk.add_argument("--spacing", type=float, help="gap between parts in mm (default 6)")
    pk.add_argument("--no-rotate", action="store_true")
    pk.add_argument("--3mf", dest="threemf", metavar="DIR", help="write the copies on their plates as a 3MF (or several) into DIR")
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
    dm = sub.add_parser("dfm", help="manufacturability, every rule with its source, measured on the solid: dfm <project> "
                                    "[--process cnc|injection|fdm|sla|sls|mjf|lpbf] [--set k=v ...] [--fix ID [--preview]] "
                                    "[--png FILE]; dfm rules [PROCESS] lists the rule tables")
    dm.add_argument("project", help="a project, or `rules` for the rule tables")
    dm.add_argument("extra", nargs="?", default="", help="with `rules`: one process")
    dm.add_argument("--process", default="")
    dm.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="an option: tool_d=6 material=metal axes=5 resin=abs pull=0,0,1 up=0,0,1 machine=200,200,200")
    dm.add_argument("--override", action="append", default=[], metavar="RULE:fail=X,warn=Y",
                    help="your shop's limit for one rule (recorded as specified)")
    dm.add_argument("--fix", metavar="ID", help="apply a proposed fix (its id or rule id) and prove it by checking again")
    dm.add_argument("--preview", action="store_true", help="with --fix: build and check the fix, save nothing")
    dm.add_argument("--accept-trades", action="store_true")
    dm.add_argument("--expect-head", type=int)
    dm.add_argument("--png", help="write a picture of the result on the part here")
    dm.add_argument("--full", action="store_true", help="every finding, not the first 30")
    sh = sub.add_parser("sheet", help="sheet metal and cut parts, JSON: sheet flat <project> [--set material=steel_mild "
                                      "--set k=0.42 --out part.dxf]; sheet profile <project> [--kerf 0.2]; sheet check "
                                      "<file.dxf|project> [--process laser|waterjet|router --set t=2]; sheet bends "
                                      "<project>; sheet preflight <project|file.dxf> [--service sendcutsend --material "
                                      "al_5052_h32 --thickness 3.175]; sheet tables")
    sh.add_argument("action", choices=["flat", "profile", "check", "bends", "preflight", "tables"])
    sh.add_argument("target", nargs="?", default="", help="a project, or a DXF file for check and preflight")
    sh.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="material, k, method (table|din6935), forming (air|bottoming|coining), label, t, punch, die_v")
    sh.add_argument("--kerf", type=float, default=0.0)
    sh.add_argument("--process", default="laser")
    sh.add_argument("--service", default="sendcutsend")
    sh.add_argument("--material", default="")
    sh.add_argument("--thickness", type=float)
    sh.add_argument("--rev", type=int)
    sh.add_argument("--out", help="write the DXF here too")
    # -- standard parts and the parts list (form/catalog.py, form/placement.py, form/bom.py) --
    pa = sub.add_parser("parts", help="standard parts from published tables: parts search QUERY | families | describe "
                                      "SPEC [--step] | din DESIGNATION | snap|place|list|fit|remove <project> ...")
    pa.add_argument("action", choices=("search", "families", "describe", "din", "snap", "place", "list", "fit", "remove"))
    pa.add_argument("args", nargs="*", help="search: the query; describe: a spec as JSON or family:size; din: the "
                                            "designation; snap/place/list/fit/remove: the project first")
    pa.add_argument("--spec", help='the part as JSON ({"family": "iso4762", "size": "M3", "length": 10}) or family:size')
    pa.add_argument("--at", metavar="x,y,z", help="a point on a hole's wall or a flat face, mm")
    pa.add_argument("--normal", metavar="x,y,z", help="outward direction (needed with --no-snap)")
    pa.add_argument("--depth", type=float, help="host thickness the cut goes through (default: measured)")
    pa.add_argument("--qty", type=int, default=1)
    pa.add_argument("--no-cut", action="store_true", help="record the part without cutting its mating feature")
    pa.add_argument("--no-snap", action="store_true", help="use --at and --normal as given")
    pa.add_argument("--step", action="store_true", help="describe: also build it and write a STEP")
    pa.add_argument("--expect-head", type=int)
    bo = sub.add_parser("bom", help="the parts list: bom <project> [--csv FILE | --pdf FILE] | supplier add|remove "
                                    "<project> DESIGNATION ... | catalogue [QUERY] [--confirm]")
    bo.add_argument("args", nargs="+", help="<project>, or supplier add|remove <project> DESIGNATION, or catalogue [QUERY]")
    bo.add_argument("--csv", metavar="FILE")
    bo.add_argument("--pdf", metavar="FILE")
    bo.add_argument("--no-made", action="store_true", help="purchased items only (no kernel call for the made parts)")
    bo.add_argument("--supplier")
    bo.add_argument("--part-number")
    bo.add_argument("--url", default="")
    bo.add_argument("--note", default="")
    bo.add_argument("--confirm", action="store_true", help="catalogue: really search after reading what is sent")
    cm = sub.add_parser("cam", help="CNC, 3-axis: cam plan|post|simulate|status <project> [--machine grbl|linuxcnc|fanuc|haas|marlin] "
                                    "[--tool 6mm-flat ...] [--material aluminum] [--set k=v ...]; cam materials lists the "
                                    "speeds table. G-code is simulated on a stock model and measured against the design")
    cm.add_argument("action", choices=["plan", "post", "simulate", "status", "materials", "posts"])
    cm.add_argument("project", nargs="?", default="")
    cm.add_argument("--machine", default="", help="the post: grbl, linuxcnc, fanuc, haas, marlin")
    cm.add_argument("--tool", action="append", default=[], metavar="NAME|JSON",
                    help="a tool: 6mm-flat, 3mm-ball, 6mm-bull-r1, 5mm-drill, 6mm-chamfer-90, or JSON with flute_l, length, holder_d")
    cm.add_argument("--material", default="")
    cm.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="an option: setups=auto stock.margin_xy=6 machine.rapid=5000 machine.accel=800 tolerance=0.05 chamfer=0.5")
    cm.add_argument("--options", default="", help="plan options as JSON (ops, feeds, stock, machine)")
    cm.add_argument("--units", default="", choices=["", "mm", "inch"])
    cm.add_argument("--wcs", default="")
    cm.add_argument("--include", action="store_true", help="ask for the program to go into the next release")
    cm.add_argument("--exclude", action="store_true", help="leave the program out of the release")
    cm.add_argument("--line-numbers", action="store_true")
    cm.add_argument("--cell", type=float, help="simulation cell size, mm")
    cm.add_argument("--out", help="with post: also copy the first program here")
    cm.add_argument("--force", action="store_true")
    # -- circuit boards and their enclosures (form/board) --
    bd = sub.add_parser("board", help="circuit boards: board read FILE | import FILE [--project P] [--step S] "
                                      "[--heights JSON] [--regenerate] | check <project> [--fit|--board] [--fab F] | "
                                      "fab <project> [--kinds gerbers,drill,pos,bom,step] | kicad | "
                                      "schematic read|netlist|erc|edit|symbols|to_board <project or .kicad_sch> [--ops JSON] | "
                                      "place <project or .kicad_pcb> | route <project or .kicad_pcb> [--engine form|freerouting] | "
                                      "copper <project or .kicad_pcb> (JSON)")
    bd.add_argument("action", choices=("read", "import", "check", "fab", "kicad", "schematic", "place", "route", "copper"))
    bd.add_argument("args", nargs="*", help="read/import: the board file (.kicad_pcb or .emn); check/fab: the project; "
                                            "schematic: the action, then a project or a .kicad_sch; place/route/copper: a "
                                            "project or a .kicad_pcb")
    bd.add_argument("--ops", default="", help="schematic edit: operations as JSON, or @file.json")
    bd.add_argument("--lib", action="append", help="schematic: a .kicad_sym file or a folder of libraries; repeat")
    bd.add_argument("--query", default="", help="schematic symbols: what to look for")
    bd.add_argument("--out", default="", help="schematic/place/route on a file: where the result goes")
    bd.add_argument("--size", default="", help="schematic to_board: the new board's W,D in mm")
    bd.add_argument("--overwrite", action="store_true")
    bd.add_argument("--engine", default="form", help="route: form (Form Studio's router) or freerouting (yours)")
    bd.add_argument("--nets", default="", help="route: only these nets, comma-separated")
    bd.add_argument("--skip", default="", help="route: not these nets, comma-separated")
    bd.add_argument("--layers", default="", help="route: F.Cu,B.Cu (default) or one of them")
    bd.add_argument("--pitch", type=float, help="route: grid pitch in mm (default: chosen from the rules)")
    bd.add_argument("--strategy", default="auto", help="route: auto, ripup or negotiated")
    bd.add_argument("--algorithm", default="auto", help="route: auto, astar or lee")
    bd.add_argument("--rip-existing", action="store_true", help="route: remove the tracks on the board first")
    bd.add_argument("--no-vias", action="store_true")
    bd.add_argument("--no-smooth", action="store_true", help="route: keep the grid paths (no pull-tight pass)")
    bd.add_argument("--passes", type=int, default=20, help="route --engine freerouting: its pass limit")
    bd.add_argument("--time-limit", type=float, default=120.0)
    bd.add_argument("--fixed", default="", help='place: parts to hold, as JSON {"U1": "why"}')
    bd.add_argument("--keepouts", default="", help="place: extra keep-outs as JSON")
    bd.add_argument("--max-height", type=float, help="place on a file: the room over the board, mm")
    bd.add_argument("--no-rotate", action="store_true")
    bd.add_argument("--only", default="", help="place: only these parts, comma-separated")
    bd.add_argument("--check-only", action="store_true", help="place: measure the placement, change nothing")
    bd.add_argument("--project", default="", help="import: the design whose board this replaces")
    bd.add_argument("--name", default="")
    bd.add_argument("--step", default="", help="import: KiCad's board STEP, for the parts' heights")
    bd.add_argument("--kicad-step", action="store_true", help="import: have your KiCad export the board STEP for heights")
    bd.add_argument("--heights", default="", help='import: part heights as JSON, e.g. {"C1": 10.5}')
    bd.add_argument("--connectors", default="", help='import: overrides as JSON, e.g. {"J2": {"side": "+x"}}')
    bd.add_argument("--regenerate", action="store_true", help="import into a project: make the enclosure again")
    bd.add_argument("--lid-screw", type=float, default=3.0)
    bd.add_argument("--fit", action="store_true", help="check: only the board against the enclosure")
    bd.add_argument("--board", action="store_true", help="check: only KiCad's DRC/ERC and the fab limits")
    bd.add_argument("--fab", action="append", help="check: a fab (jlcpcb, pcbway, oshpark); repeat")
    bd.add_argument("--no-kicad", action="store_true", help="check: do not run KiCad even when it is installed")
    bd.add_argument("--kinds", default="", help="fab: comma-separated kinds")
    bd.add_argument("--expect-head", type=int)
    gd = sub.add_parser("diff", help="what changed between two revisions, computed on the solids: diff <project> A [B] [--png FILE]")
    gd.add_argument("project")
    gd.add_argument("a", type=int)
    gd.add_argument("b", type=int, nargs="?")
    gd.add_argument("--png", help="also write the picture (added green, removed red) here")
    rc = sub.add_parser("reconstruct", help="a mesh or scan (any format `form formats` lists, or a zip) as editable CAD, "
                                            "verified against it: reconstruct FILE "
                                            "[FILE ...] [--name N] [--tolerance MM] [--layer 0|1|2]; several files of one "
                                            "product make one design with one part each")
    rc.add_argument("file")
    rc.add_argument("more", nargs="*", help="more meshes of the same product: one design, one part per mesh")
    rc.add_argument("--name")
    rc.add_argument("--tolerance", type=float, default=0.02, help="largest deviation from the mesh for a fitted surface, mm")
    rc.add_argument("--layer", type=int, choices=(0, 1, 2), default=2,
                    help="0: exact solid only, 1: analytic and B-spline faces (beta), 2: feature tree recipe (beta)")
    rc.add_argument("--budget", type=float, default=240.0,
                    help="seconds the reconstruction may take in all; the best result found in that time is kept")
    rc.add_argument("--route", choices=("auto", "parametric", "surface_body", "mesh_body"), default="auto",
                    help="auto: the route the triage chooses (see `form triage FILE`); or force one")
    rc.add_argument("--scale", type=float, default=1.0, help="multiply the file's coordinates (a mesh in metres: 1000)")
    rc.add_argument("--units", choices=("auto", "mm", "cm", "m", "in"), default="auto",
                    help="what the file's numbers are; auto: millimetres, and a size that makes no sense in mm is asked about")
    ar = sub.add_parser("analyze-reference", help="an imported mesh read like an engineer: sections with dimensions, features "
                                                  "with sizes, symmetry, walls: analyze-reference <project> <mesh> [--levels JSON]")
    ar.add_argument("project")
    ar.add_argument("reference")
    ar.add_argument("--tolerance", type=float, default=0.05, help="how far a surface may be from the mesh to count as a plane, cylinder... (mm)")
    ar.add_argument("--levels", help='extra section levels per axis, JSON: {"z": [3.2, 6.5]}')
    aa = sub.add_parser("analyze-assembly", help="how imported meshes go together and move: analyze-assembly <project> FIXED OTHER... "
                                                 "(mating surfaces, clearances, slide and turn ranges, couplings)")
    aa.add_argument("project")
    aa.add_argument("references", nargs="+")
    aa.add_argument("--fixed", help="the part that stays still (default: the first)")
    aa.add_argument("--near", type=float, default=1.0, help="gaps up to this count as mating (mm)")
    cr = sub.add_parser("compare-reference", help="the design (or one part) against an imported mesh: Hausdorff, worst regions, "
                                                  "per-feature differences: compare-reference <project> <mesh> [--part P] [--png FILE]")
    cr.add_argument("project")
    cr.add_argument("reference")
    cr.add_argument("--part", help="a part id or label of the design's assembly")
    cr.add_argument("--tolerance", type=float, default=0.1, help="the limit, mm (0.1 by default for a remodel)")
    cr.add_argument("--rev", type=int)
    cr.add_argument("--png", help="also copy the deviation picture here")
    ins = sub.add_parser("instructions", help="assembly instructions as a PDF from the assembly declaration: instructions <project> [--rev N] [--out FILE]")
    ins.add_argument("project")
    ins.add_argument("--rev", type=int)
    ins.add_argument("--out", help="copy the PDF here")
    # -- engineering drawings, PMI and drawing checks (form/drawing) --
    dr = sub.add_parser("drawing", help="engineering drawing from the solid: drawing <project> [--sheet A3] [--projection first] "
                                        "[--out part.pdf]; drawing pmi <project>; drawing check <project> <file>; "
                                        "drawing spec <project> <json>; drawing set <project> <dimension> <value>")
    dr.add_argument("args", nargs="+", help="<project> | pmi <project> | check <project> <file> [--rows JSON] | "
                                            "spec <project> <json> | set <project> <dimension id> <value>")
    dr.add_argument("--sheet", default=None, help="A4-A0 or 'ANSI A'-'ANSI E' (A3 by default)")
    dr.add_argument("--projection", default=None, choices=["first", "third"])
    dr.add_argument("--rev", type=int)
    dr.add_argument("--out", help="copy the PDF (or the STEP for pmi) here")
    dr.add_argument("--rows", help="check: the rows an agent read off an image, as JSON")
    dr.add_argument("--no-prove", action="store_true", help="bind parameters by value only (no nudged rebuilds)")
    dr.add_argument("--expect-head", type=int)
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
    ms = sub.add_parser("mass", help="mass, centre of mass, inertia tensor and principal axes from the B-rep: mass <project> "
                                     "[--part P] [--pose JSON] [--material M] [--frame as_built|assembled] [--library]")
    ms.add_argument("project")
    ms.add_argument("--part", default="")
    ms.add_argument("--pose", help='joint values as JSON, e.g. {"lid_hinge": 90}')
    ms.add_argument("--material", help="a what-if material for every part (or --part), nothing saved")
    ms.add_argument("--frame", choices=["as_built", "assembled"])
    ms.add_argument("--rev", type=int)
    ms.add_argument("--library", action="store_true", help="add the sourced record of each material used")
    mt = sub.add_parser("materials", help="the materials library with sources: materials [ID]")
    mt.add_argument("id", nargs="?")
    mo = sub.add_parser("motion", help="motion study: motion <project> [--drivers JSON] [--duration S] [--frames N] "
                                       "[--traces JSON] [--hold JSON] [--video]")
    mo.add_argument("project")
    mo.add_argument("--drivers", help='JSON, e.g. \'[{"joint": "crank", "from": 0, "to": 360}]\'')
    mo.add_argument("--duration", type=float, default=2.0)
    mo.add_argument("--frames", type=int, default=49)
    mo.add_argument("--traces", help='JSON, e.g. \'[{"part": "coupler", "at": [10, 0, 0]}]\'')
    mo.add_argument("--hold", help="JSON {joint: value} for joints nothing drives")
    mo.add_argument("--no-clearance", action="store_true")
    mo.add_argument("--no-torque", action="store_true")
    mo.add_argument("--video", action="store_true", help="also an MP4 (needs ffmpeg)")
    mo.add_argument("--budget", type=float, default=60.0, help="seconds for the clearance check")
    mo.add_argument("--assume", help="a material for parts without one (labelled), for the torque")
    mo.add_argument("--rev", type=int)
    mo.add_argument("--full", action="store_true", help="print every frame (default: frames per joint and trace are left out)")
    for nm in ("urdf", "mjcf"):
        rb = sub.add_parser(nm, help=f"robot files (URDF, SRDF and MJCF; prints the {nm.upper()} path first): {nm} <project> "
                                     "[--collision auto|coacd|hull|box] [--assume M] [--limits JSON]")
        rb.add_argument("project")
        rb.add_argument("--collision", default="auto", choices=["auto", "coacd", "hull", "box"])
        rb.add_argument("--assume", help="a material for parts without one (labelled)")
        rb.add_argument("--limits", help='JSON {joint: {"effort": N·m, "velocity": rad/s}}')
        rb.add_argument("--samples", type=int, default=64, help="random poses for the SRDF's Never pairs")
        rb.add_argument("--rev", type=int)
    sq = sub.add_parser("sequence", help="assembly order and insertion directions: sequence <project> [--budget S]")
    sq.add_argument("project")
    sq.add_argument("--budget", type=float, default=90.0)
    sq.add_argument("--rev", type=int)
    apx = sub.add_parser("appearance", help="colour and material of the design or one part: --color #rrggbb --material petg [--part ID]")
    apx.add_argument("project")
    apx.add_argument("--part", default="")
    apx.add_argument("--color")
    apx.add_argument("--material", help="PLA, PETG, ABS, ASA, TPU, PA, PC, PLA-CF, PETG-CF, PA-CF; a model: AL-6061, STEEL, ... (form materials)")
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
        elif a.cmd == "import-reference":
            _print(st.import_reference(st.load(a.project), Path(a.file).expanduser(), a.name))
        elif a.cmd == "reconstruct":
            last = [0.0]

            def show(d):                                  # progress on stderr: stdout stays JSON
                import time as _t
                if _t.monotonic() - last[0] > 1.5:
                    last[0] = _t.monotonic()
                    print(f"[{100 * float(d.get('fraction', 0)):3.0f}%] {d.get('text', '')}", file=sys.stderr, flush=True)
            if a.more:
                from . import multipart
                _print(multipart.reconstruct_parts(st, [Path(a.file), *map(Path, a.more)], name=a.name,
                                                   tolerance=a.tolerance, layer=a.layer, on_progress=show))
            else:
                _print(st.reconstruct(Path(a.file), name=a.name, tolerance=a.tolerance, layer=a.layer,
                                      budget_s=a.budget, on_progress=show, route=a.route, scale=a.scale,
                                      units=a.units))
        elif a.cmd in ("analyze-reference", "analyze-assembly", "compare-reference"):
            from .remodel import project as rp
            p = st.load(a.project)
            if a.cmd == "analyze-reference":
                _print(rp.analyze_reference(st, p, a.reference, a.tolerance, json.loads(a.levels) if a.levels else None))
            elif a.cmd == "analyze-assembly":
                _print(rp.analyze_assembly(st, p, a.references, a.fixed, a.near))
            else:
                out = rp.compare_to_reference(st, p, a.reference, a.part, a.tolerance, a.rev)
                if a.png:
                    import shutil as _sh
                    _sh.copyfile(out["image"], a.png)
                    out["png"] = str(Path(a.png).resolve())
                _print(out)
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
            if a.upto:
                from . import modelling
                v = modelling.view_upto(st, p, a.upto)
            else:
                v = st.view(p)
            feats = [{"id": f.id, "label": f.label} for f in st.recipe(p).features]
            views = ["iso", "front", "top", "right"] if a.view == "sheet" else [a.view]
            size = (640, 460) if a.view == "sheet" else (960, 680)
            title = f"{p['name']} - r{p['head']:02d}" + (f" up to {a.upto} (not saved)" if a.upto else "")
            pngs = [render.render_png(v, feats, vw, a.highlight, size=size, title=title) for vw in views]
            out = a.out or f"{a.project}_r{p['head']:02d}_{a.view}{'_upto-' + a.upto if a.upto else ''}.png"
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
            _print(opt.run(st, st.load(a.project), vary, obj, a.require, a.budget, study=a.study))
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
                _print(lighten.search(st, p, builds=a.builds, require=a.require or None, study=a.study))
        elif a.cmd == "slicer-open":
            from . import slicer_open
            r = slicer_open.run(st, st.load(a.project), a.printer, open_app=not a.no_open, copies=a.copies)
            if a.explain:
                r = {"explain": slicer_open.explain(r).splitlines(), **r}
            _print(r)
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
        elif a.cmd == "sketch":
            from . import modelling
            if a.new:
                if not a.file:
                    raise StudioError("--new needs --file F.json (the sketch).")
                data = json.loads(Path(a.file).read_text(encoding="utf-8"))
                p = modelling.start_from_sketch(st, a.new, data, "extrude", a.purpose, depth=a.depth)
                job = st.run_sync(p["id"])
                _print({"project": p["id"], "head": p["head"], "pipeline": job_digest(job)})
                return 0
            if not (a.project and a.feature):
                raise StudioError("Give a project and the feature whose sketch it is.", "`form tree <project>` lists them.")
            p = st.load(a.project)
            ops = json.loads(sys.stdin.read() if a.ops == "-" else a.ops) if a.ops else []
            for kv in a.set:
                k, _, val = kv.partition("=")
                ops.append({"op": "set", "name": k, "value": float(val)})
            if not ops:
                _print(modelling.get_sketch(st, p, a.feature))
            else:
                eops, _new = modelling.sketch_edit_ops(st, p, a.feature, ops)
                if a.preview:
                    pv = modelling.preview(st, p, eops)
                    pv.pop("rid", None)
                    _print({"saved": False, "ops": eops, "preview": pv})
                else:
                    r = modelling.commit(st, p, eops, a.expect_head, "cli", note=f"Changed the sketch of {a.feature}")
                    r.pop("project")
                    st.activity(a.project, "commit", f"r{r['head']:02d}: {r['said']}", by="cli")
                    _print({**r, "pipeline": job_digest(st.run_sync(a.project))})
        elif a.cmd in ("tree", "model"):
            from . import modelling
            p = st.load(a.project)
            xyz = lambda t: [float(x) for x in t.split(",")]
            if a.cmd == "tree" and a.upto:
                v = modelling.view_upto(st, p, a.upto)
                out = {"upto": v["upto"], "volume_mm3": v["volume_mm3"], "bbox": v["bbox"], "faces": v["faces"]}
                if a.png:
                    from . import render
                    feats = [{"id": f.id, "label": f.label} for f in st.recipe(p).features]
                    with open(a.png, "wb") as fh_:
                        fh_.write(render.render_png(v, feats, "iso", None, size=(960, 680),
                                                    title=f"{p['name']} - r{p['head']:02d} up to {a.upto} (not saved)"))
                    out["png"] = a.png
                _print(out)
            elif a.cmd == "tree" and not a.action:
                _print(modelling.tree(st, p))
            else:
                if a.cmd == "tree":
                    if not a.feature:
                        raise StudioError(f"{a.action} needs a feature id.", "`form tree <project>` lists them.")
                    op = {"op": a.action, "feature": a.feature}
                    op.update({k: v for k, v in (("after", a.after), ("before", a.before), ("label", a.label),
                                                 ("id", a.new_id)) if v})
                    ops, planned = [op], None
                else:
                    o = {k: getattr(a, k) for k in ("radius", "length", "thickness", "nominal", "d", "depth", "pitch",
                                                    "angle", "head_d", "head_depth", "count", "standard", "size", "fit",
                                                    "style", "of", "mode", "after") if getattr(a, k) is not None}
                    if a.axis:
                        o["axis"] = a.axis if a.axis.lower().lstrip("+-") in ("x", "y", "z") else xyz(a.axis)
                    if a.origin:
                        o["origin"] = xyz(a.origin)
                    if a.sketch:
                        o["sketch"] = json.loads(Path(a.sketch).read_text(encoding="utf-8"))
                    if a.axis_entity is not None:
                        o["axis_entity"] = a.axis_entity
                    planned = modelling.plan(st, p, a.kind, [{"at": xyz(t)} for t in a.at], **o)
                    ops = planned["ops"]
                if a.preview:
                    pv = modelling.preview(st, p, ops)
                    pv.pop("rid", None)
                    _print({"saved": False, "ops": ops, "preview": pv,
                            **({"summary": planned["summary"], "picked": planned["picked"]} if planned else {})})
                else:
                    r = modelling.commit(st, p, ops, a.expect_head, "cli", planned=planned)
                    r.pop("project")
                    st.activity(a.project, "commit", f"r{r['head']:02d}: {r['said']}", by="cli")
                    job = st.run_sync(a.project)
                    _print({**r, "pipeline": job_digest(job)})
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
        elif a.cmd == "dfm":
            from . import dfm
            from .dfm import rules as dfm_rules
            if a.project == "rules":
                procs = [dfm.process_id(a.extra)] if a.extra else dfm_rules.processes()
                _print({pid: dfm_rules.table(pid) for pid in procs})
            else:
                opts: dict = {}
                for kv in a.set:
                    k, _, v = kv.partition("=")
                    opts[k.strip()] = v.strip()
                ovr: dict = {}
                for o in a.override:
                    rid, _, rest = o.partition(":")
                    ovr[rid] = {k: float(v) for k, v in (x.split("=") for x in rest.split(",") if "=" in x)}
                if ovr:
                    opts["overrides"] = ovr
                p = st.load(a.project)
                if a.fix:
                    out = dfm.apply_fix(st, p, a.process or None, a.fix, opts, apply=not a.preview,
                                        accept_trades=a.accept_trades, expect_head=a.expect_head)
                else:
                    res = dfm.check(st, p, a.process or None, opts)
                    out = dfm.summary(res, findings=10 ** 6 if a.full else 30)
                    out["fixes"] = [{k: v for k, v in f.items() if k != "attempts"} for f in res.get("fixes", [])]
                    if a.png and res.get("overlay_file"):
                        import shutil as _sh
                        _sh.copyfile(dfm.render(st, p, res), a.png)
                        out["png"] = str(Path(a.png).resolve())
                _print(out)
        elif a.cmd == "sheet":
            from . import sheet
            from .sheet import cutcheck as _cc, tables as _tb
            sopts: dict = {}
            for kv in a.set:
                k, _, v = kv.partition("=")
                sopts[k.strip()] = v.strip()
            is_file = a.target.lower().endswith(".dxf")
            if a.action == "tables":
                _print({"bend": {k: v for k, v in _tb.bend_table().items() if k not in ("source", "material")},
                        "services": {sid: {k: v for k, v in _tb.service(sid).items() if k not in ("source", "material")}
                                     for sid in _tb.services()}})
            elif a.action == "check":
                if is_file:
                    _print(sheet.cut_check(a.target, _cc.process_id(a.process), sopts))
                else:
                    _print(sheet.cut_check(None, _cc.process_id(a.process), sopts, st, st.load(a.target), a.rev))
            elif a.action == "preflight":
                if is_file:
                    _print(sheet.service_preflight(service=a.service, material=a.material or None, t=a.thickness,
                                                   path=a.target))
                else:
                    _print(sheet.service_preflight(st, st.load(a.target), a.service, a.material or None, a.thickness,
                                                   rev=a.rev))
            else:
                p = st.load(a.target)
                if a.action == "flat":
                    res = sheet.flat_pattern(st, p, sopts, a.rev, out=a.out)
                    _print({**sheet.summary(res), "dxf": res.get("dxf"), "png": res.get("png")})
                elif a.action == "profile":
                    res = sheet.profile(st, p, a.kerf, sopts.get("label"), a.rev, out=a.out)
                    _print({k: v for k, v in res.items() if k not in ("entities", "exact", "etch")})
                else:
                    _print(sheet.bend_order(st, p, sopts, a.rev))
        elif a.cmd == "parts":
            from . import catalog, placement
            xyz = lambda t: [float(x) for x in t.split(",")]

            def spec_of(t):
                if not t:
                    raise StudioError("Give the part: --spec as JSON, or family:size (form parts search finds one).")
                if t.strip().startswith("{"):
                    return json.loads(t)
                fam, _, size = t.partition(":")
                return {"family": fam, "size": size}
            args = list(a.args)
            if a.action == "search":
                _print({"results": catalog.search(" ".join(args)), "note": "Local tables only; nothing was sent anywhere."})
            elif a.action == "families":
                _print({"families": catalog.families()})
            elif a.action == "din":
                _print(catalog.din(" ".join(args)))
            elif a.action == "describe":
                sp = spec_of(a.spec or (args[0] if args else ""))
                if a.step:
                    out = st.root / ".catalog" / "step"
                    out.mkdir(parents=True, exist_ok=True)
                    it = catalog.resolve(sp)
                    _print(catalog.part_info(st, it, step_path=str(out / f"{it['family']}-{it['size']}.step")))
                else:
                    _print(catalog.describe(sp))
            else:
                if not args:
                    raise StudioError(f"parts {a.action} needs the project.")
                p = st.load(args[0])
                if a.action == "list":
                    _print({"placements": placement.list_parts(st, p)})
                elif a.action == "fit":
                    _print(placement.fit(st, p))
                elif a.action == "remove":
                    if len(args) < 2:
                        raise StudioError("parts remove <project> std_N")
                    _print(placement.remove(st, p, args[1], a.expect_head, origin="cli"))
                elif a.action == "snap":
                    if not a.at:
                        raise StudioError("Give --at x,y,z.")
                    _print(placement.snap(st, p, xyz(a.at), xyz(a.normal) if a.normal else None))
                else:
                    if not a.at:
                        raise StudioError("Give --at x,y,z (a point on a hole's wall or a flat face).")
                    _print(placement.place(st, p, spec_of(a.spec or (args[1] if len(args) > 1 else "")), xyz(a.at),
                                           xyz(a.normal) if a.normal else None, a.depth, a.qty, not a.no_cut,
                                           not a.no_snap, None, a.expect_head, origin="cli"))
        elif a.cmd == "board":
            from .board import api as board_api, kicad_cli, model as board_model
            args = list(a.args)
            csv = lambda s: [x for x in s.split(",") if x] or None
            target = lambda t, ext: ({"file": t} if t.lower().endswith(ext) else {"project": t})
            if a.action == "kicad":
                from .board import specctra
                _print({**kicad_cli.status(st.cfg), "freerouting": specctra.status(st.cfg)})
            elif a.action == "schematic":
                from .board import k2
                act = args[0] if args else "read"
                if act != "symbols" and len(args) < 2:
                    raise StudioError("form board schematic ACTION needs a project or a .kicad_sch file.",
                                      "Actions: " + ", ".join(k2.ACTIONS) + ".")
                ops = None
                if a.ops:
                    ops = json.loads(Path(a.ops[1:]).read_text(encoding="utf-8") if a.ops.startswith("@") else a.ops)
                _print(k2.schematic(st, act, ops=ops, libraries=a.lib, query=a.query or " ".join(args[1:] if act == "symbols" else []),
                                    out=a.out or None, size=[float(x) for x in a.size.split(",")] if a.size else None,
                                    overwrite=a.overwrite, kicad=not a.no_kicad,
                                    **(target(args[1], ".kicad_sch") if act != "symbols" else {})))
            elif a.action in ("place", "route", "copper"):
                from .board import k2
                if not args:
                    raise StudioError(f"form board {a.action} needs a project or a .kicad_pcb file.")
                t = target(args[0], ".kicad_pcb")
                if a.action == "place":
                    _print(k2.place(st, out=a.out or None, fixed=json.loads(a.fixed) if a.fixed else None,
                                    keepouts=json.loads(a.keepouts) if a.keepouts else None, max_height=a.max_height,
                                    rotate=not a.no_rotate, only=csv(a.only), check_only=a.check_only, overwrite=a.overwrite, **t))
                elif a.action == "route":
                    _print(k2.route(st, out=a.out or None, engine=a.engine, nets=csv(a.nets), skip=csv(a.skip),
                                    layers=csv(a.layers), pitch=a.pitch, strategy=a.strategy, algorithm=a.algorithm,
                                    keep_existing=not a.rip_existing, vias=not a.no_vias, smooth=not a.no_smooth,
                                    passes=a.passes, time_limit=a.time_limit, kicad=not a.no_kicad, overwrite=a.overwrite, **t))
                elif "file" in t:
                    from .board import drc as board_drc, pcb as board_pcb
                    _print(board_drc.check(board_pcb.Pcb.load(t["file"])))
                else:
                    _print(k2.copper_check(st, st.load(t["project"]), kicad=not a.no_kicad))
            elif not args:
                raise StudioError(f"form board {a.action} needs " + ("a board file." if a.action in ("read", "import") else "a project."))
            elif a.action == "read":
                b = board_api.read(args[0])
                _print({"summary": board_model.summary(b), "board": b})
            elif a.action == "import":
                _print(board_api.import_board(st, args[0], project=a.project or None, name=a.name, step=a.step or None,
                                              heights=json.loads(a.heights) if a.heights else None,
                                              connectors=json.loads(a.connectors) if a.connectors else None,
                                              regenerate=a.regenerate, expect_head=a.expect_head, lid_screw=a.lid_screw,
                                              use_kicad_step=a.kicad_step))
            elif a.action == "check":
                p = st.load(args[0])
                out = {}
                if not a.board:
                    out["fit"] = board_api.fit(st, p)
                if not a.fit:
                    out["board"] = board_api.checks(st, p, a.fab, not a.no_kicad)
                _print(out)
            else:
                p = st.load(args[0])
                _print(board_api.fab_files(st, p, [k for k in a.kinds.split(",") if k] or None))
        elif a.cmd == "bom":
            from . import bom as bm
            args = list(a.args)
            if args[0] == "catalogue":
                q = " ".join(args[1:])
                _print(bm.catalogue_search(st.cfg, q, a.confirm) if q else bm.catalogue_status(st.cfg))
            elif args[0] == "supplier":
                if len(args) < 4 or args[1] not in ("add", "remove"):
                    raise StudioError("bom supplier add|remove <project> DESIGNATION --supplier NAME --part-number N [--url URL]")
                p = st.load(args[2])
                dsg = " ".join(args[3:])
                if args[1] == "add":
                    _print(bm.add_supplier(st, p, dsg, a.supplier, a.part_number, a.url, a.note, by="person"))
                else:
                    _print(bm.remove_supplier(st, p, dsg, a.supplier or "", a.part_number or ""))
            else:
                p = st.load(args[0])
                b = bm.build(st, p, made=not a.no_made)
                if a.csv:
                    Path(a.csv).write_text(bm.csv_text(b), encoding="utf-8")
                    b["csv"] = str(Path(a.csv).resolve())
                if a.pdf:
                    import shutil as _sh
                    _sh.copyfile(bm.pdf(st, p, b), a.pdf)
                    b["pdf"] = str(Path(a.pdf).resolve())
                _print(b)
        elif a.cmd == "cam":
            from . import cam
            from .cam import feeds as cam_feeds, posts as cam_posts
            if a.action == "materials":
                _print({"materials": cam_feeds.materials(),
                        "sources": {k: cam_feeds.source_text(v) for k, v in cam_feeds.table()["sources"].items()}})
            elif a.action == "posts":
                _print({k: {"label": v["label"], "extension": v["ext"], "canned_cycles": v["canned"], "tool_changer": v["m6"]}
                        for k, v in cam_posts.DIALECTS.items()})
            else:
                if not a.project:
                    raise StudioError("Which project?", "form cam " + a.action + " <project>")
                p = st.load(a.project)
                given = bool(a.tool or a.material or a.set or a.options)
                opts = cam.options_from_cli(a.tool, a.material, a.set, a.options) if given else None
                inc = True if a.include else False if a.exclude else None
                if a.action == "plan":
                    _print(cam.plan_summary(cam.plan(st, p, opts if opts is not None else (p.get("cam") or {}).get("options") or {},
                                                     force=a.force)))
                elif a.action == "post":
                    out = cam.post(st, p, a.machine or None, opts, a.units or None, a.wcs or None, inc, a.line_numbers,
                                   a.cell, a.force)
                    if a.out:
                        import shutil as _sh
                        _sh.copyfile(out["programs"][0]["file"], a.out)
                        out["out"] = str(Path(a.out).resolve())
                    _print(out)
                elif a.action == "simulate":
                    out = cam.simulate(st, p, sim_cell=a.cell, force=a.force)
                    out["status"] = cam.status(st, p)
                    _print(out)
                else:
                    _print(cam.status(st, p))
        elif a.cmd == "diff":
            from . import geomdiff
            import shutil as _sh
            p = st.load(a.project)
            d = geomdiff.compute(st, p, a.a, a.b)
            if a.png:
                _sh.copyfile(geomdiff.png_path(st, p, d), a.png)
                d["png"] = str(Path(a.png).resolve())
            _print(d)
        elif a.cmd == "drawing":
            import shutil as _sh
            from . import drawing as _dr
            args = list(a.args)
            verb = args[0] if args[0] in ("pmi", "check", "spec", "set") and len(args) > 1 else "make"
            if verb != "make":
                args = args[1:]
            p = st.load(args[0])
            try:
                if verb == "pmi":
                    out = _dr.export_pmi(st, p, a.rev, sheet=a.sheet)
                    if a.out:
                        _sh.copyfile(out["path"], a.out)
                        out["path"] = str(Path(a.out).resolve())
                elif verb == "check":
                    from .drawing import check as _chk
                    if len(args) < 2:
                        raise SystemExit("drawing check <project> <file>")
                    out = _chk.run(st, p, args[1], json.loads(a.rows) if a.rows else None, a.rev)
                elif verb == "spec":
                    out = _dr.set_spec(st, p["id"], json.loads(args[1]) if len(args) > 1 else {})
                elif verb == "set":
                    if len(args) < 3:
                        raise SystemExit("drawing set <project> <dimension id> <value>")
                    out = _dr.set_dimension(st, p, args[1], float(args[2]), a.expect_head, a.rev)
                else:
                    out = _dr.build(st, p, a.rev, sheet=a.sheet, projection=a.projection, prove=not a.no_prove)
                    if a.out:
                        _sh.copyfile(out["paths"]["pdf"], a.out)
                        out["paths"]["pdf"] = str(Path(a.out).resolve())
            except _dr.DrawingError as e:
                raise StudioError(str(e), e.hint)
            _print(out)
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
        elif a.cmd == "mass":
            import json as _json
            from . import material_library as ml, massprops
            try:
                pose = _json.loads(a.pose) if a.pose else None
            except ValueError:
                raise StudioError("--pose is JSON.", 'For example --pose \'{"lid_hinge": 90}\'')
            r = massprops.compute(st, st.load(a.project), part=a.part, pose=pose, material=a.material, frame=a.frame,
                                  rev=a.rev)
            r["headline"] = massprops.headline(r)
            if a.library:
                r["library"] = {k: ml.record(k) for k in r["materials"]}
            _print(r)
        elif a.cmd == "motion":
            from . import motion

            def js(x, what):
                try:
                    return json.loads(x) if x else None
                except ValueError:
                    raise StudioError(f"--{what} is JSON.")
            r = motion.run(st, st.load(a.project), drivers=js(a.drivers, "drivers"), duration_s=a.duration, frames=a.frames,
                           hold=js(a.hold, "hold"), traces=js(a.traces, "traces"), clearance_check=not a.no_clearance,
                           torque_check=not a.no_torque, video=a.video, budget_s=a.budget, assume=a.assume, rev=a.rev)
            r["headline"] = motion.headline(r)
            if not a.full:
                r.pop("frames", None)
                for j in r.get("joints", []):
                    for k in ("value", "velocity", "acceleration"):
                        j.pop(k, None)
                for t in r.get("traces", []):
                    for k in ("positions_mm", "velocity_mm_s", "acceleration_mm_s2", "speed_mm_s", "accel_mm_s2"):
                        t.pop(k, None)
                if r.get("clearance"):
                    r["clearance"].pop("per_frame", None)
                if r.get("torque"):
                    for j in r["torque"].get("joints", []):
                        j.pop("values", None)
            _print(r)
        elif a.cmd in ("urdf", "mjcf"):
            from . import robot
            try:
                lim = json.loads(a.limits) if a.limits else None
            except ValueError:
                raise StudioError("--limits is JSON.")
            r = robot.write(st, st.load(a.project), collision=a.collision, assume_material=a.assume, limits=lim,
                            samples=a.samples, rev=a.rev)
            r["headline"] = robot.headline(r)
            _print({"file": r["paths"][a.cmd], **r})
        elif a.cmd == "sequence":
            from . import sequence
            r = sequence.plan(st, st.load(a.project), budget_s=a.budget, rev=a.rev)
            r["headline"] = sequence.headline(r)
            _print(r)
        elif a.cmd == "materials":
            from . import material_library as ml
            try:
                _print(ml.record(a.id) if a.id else {"materials": ml.library()})
            except KeyError as e:
                raise StudioError(str(e).strip("'\""), "`form materials` lists them.")
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
        elif a.cmd == "cost" and (a.project in ("compare", "rates") or a.process or a.qty):
            from . import costing
            from .costing import rates as cr

            def kv(items, num=True):
                out = {}
                for x in items:
                    k, sep, val = x.rpartition("=")
                    if not sep or not k:
                        raise StudioError(f"“{x}” is not KEY=VALUE.")
                    out[k.strip()] = (None if val.strip() == "" else float(val)) if num else val.strip()
                return out
            opts: dict = {}
            for k, val in kv(a.option, num=False).items():
                proc, _, key = k.partition(".")
                try:
                    val = float(val)
                except ValueError:
                    pass
                opts.setdefault(costing.process_id(proc), {})[key] = val
            if a.project == "rates":
                if a.rate or a.fx or a.part_price or a.currency or a.label is not None or a.use or a.delete:
                    cr.update_shop(st.cfg, a.shop, a.label, a.currency or None, kv(a.rate), kv(a.fx), a.use,
                                   delete=a.delete, part_prices=kv(a.part_price))
                out = cr.listing(st.cfg, None if a.delete else (a.shop or None))
                if not a.full:
                    out = {**{k: out[k] for k in ("shop", "label", "currency", "shops", "active", "fx", "part_prices",
                                                  "rule", "table")},
                           "rates": [{k: r.get(k) for k in ("id", "value", "unit", "evidence", "applies", "source", "why",
                                                            "needs", "overridden") if r.get(k) not in (None, False)}
                                     for r in out["rates"]]}
                _print(out)
            elif a.project == "compare":
                if not a.extra:
                    raise StudioError("Which project?", "form cost compare <project>")
                r = costing.compare(st, st.load(a.extra), [x for x in a.processes.split(",") if x] or None,
                                    a.qty or None, opts, a.shop or None, a.currency or None, kv(a.rate))
                _print(r if a.full else costing.brief(r))
            else:
                r = costing.estimate(st, st.load(a.project), a.process or "fdm", a.qty or None, opts, a.shop or None,
                                     a.currency or None, kv(a.rate))
                _print(r if a.full else costing.brief(r))
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
            if a.threemf:
                from . import plates as plates_mod
                res["export"] = plates_mod.write_3mf(st, st.load(a.project), Path(a.threemf).expanduser(), a.copies)
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
        st.kernel.shutdown()          # the process ends: no worker is started again (form/worker.py)
    return 0


if __name__ == "__main__":
    sys.exit(main())
