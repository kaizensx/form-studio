"""FORM over the Model Context Protocol.

Any MCP client (Claude Code, Codex, Gemini CLI, Cursor, ...) drives the same
deterministic engine the app uses. The agent proposes; Form Studio builds, measures,
checks, exports (and, for a design made for printing, slices) and keeps the record. Release approval is
deliberately not a tool: it needs a person, in the app.

Run:  form-mcp            (stdio; what agents launch)
      form-mcp --no-bench (no local web page)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import __version__, advisor, config
from . import render as rendering
from .digest import impact_digest, job_digest
from .digest import digest as _digest
from .studio import H, Studio, StudioError

INSTRUCTIONS = """\
Form Studio is an AI CAD studio: it designs parts, products and mechanisms as real, editable CAD (a parametric kernel)
and keeps an honest record of what is known. 3D printing is optional and off unless the person turned it on
(form_overview: has_printer).

Workflow: form_overview -> create_design from your own code (design_guide; design_brief first for a complex
design), or create_project from a recipe (describe_recipe) -> render (look at it) -> preview_change ->
commit_change, or edit_design (ops on one feature or parameter; update_design sends a whole file) -> get_project
(checks, the proof sheet of the brief's requirements, next actions). Only for a design whose purpose is "print":
run_pipeline (exports, print checks, a slice) -> request_release (a person approves in Form Studio).
After every build, refinement runs in the background and lands as one more revision (refine_design shows, undoes
or turns it off; game assets only when turned on). Long work answers with a job: get_job.

Rules:
- Units are mm, degrees, grams. Only change parameters that describe_recipe lists.
- Always preview_change before commit_change; pass expect_head so you never overwrite a newer revision.
- Provenance is evidence. Mark a value "measured" only when the user measured it and told you the number.
  Never invent physical results; record_physical_result is only for what the user reports.
- For a print design: a slice is a simulation, not a print, and fit yield is a model. Say so when you report them.
- You cannot approve a release. request_release returns a link that opens the release in Form Studio for the user.
- Nothing here starts a print or sends files anywhere.
- Every design has a purpose: "print" or "model" (just a 3D model: rendering, CAD exchange, CNC, laser cutting,
  moulding). get_project reports it. For a model never ask about a printer, slicer, filament or orientation. Pass
  purpose to create_project/create_design when the person says what it is for (default: form_overview
  purpose_default). A "Purpose:" line in the message is binding: "just a 3D model" means no print talk.
- Ask the person only what changes fit, load or safety and you cannot look up: ask_user, one question at a time,
  at most three per task; ask_measurement for a dimension they can measure. Where Form Studio's chat or your
  client's form cannot reach the person, the result tells you to ask in your own interface.
- A new idea that is not a precise specification: propose_concepts with 3-4 genuinely different structural
  approaches as real designs, a one-line rationale each; then stop and let the person pick. Do not offer recipes.
- Photos: scale from a reference object (bank card 85.60 x 53.98 mm, a coin, a ruler); photo dimensions stay
  assumed until measured. Form Studio sketches carry JSON that is authoritative over the picture. STEP/STL/3MF:
  import_reference. PDF drawings: read_document. Links the person gives: fetch_link, never a shell; a large mesh:
  mesh_preflight first. Download only what the person gave you.
- Meshes to make editable: never embed them as the design. design_guide(topic="reference_parts"): analyze_reference
  (analyze_assembly for several parts) -> named features -> build123d with Params -> compare_to_reference until
  within tolerance (0.1 mm by default).
- One request makes one design. Several files of one product are one design with several parts (reconstruct
  files=[...], create_design relation="part_of"). A second create_design in a conversation says its relation
  (replaces, part_of, alternative, new).
- Complex designs (mechanisms, organic or styled forms, textures, several parts) are staged: design_brief ->
  design_guide(topic=...) and design_examples -> plan_design -> create_design(plan=...) -> look at the sheet ->
  critique -> update_design. The design_guide topics (and this server's skills, where your client lists them)
  hold the full workflow for each kind of design.
"""

S: dict[str, Any] = {"studio": None, "bench": {"url": None}, "lock": threading.Lock()}


MEASURE_EXAMPLE = ('Each point is [x, y, z] in millimetres in the design frame. Examples: measure(project="p1", '
                   'from_point=[0, -55.75, 0], to_point=[0, 55.75, 0]) for the distance between two points; '
                   'measure(project="p1", at=[-18, -43.25, 4]) for what is at one point (face, edge, a hole\'s diameter). '
                   'For a reference mesh, use analyze_reference instead.')


def _measure_usage(from_point, to_point) -> str:
    """What was wrong with a measure call, said so the next call is right."""
    if (from_point is None) != (to_point is None):
        given = "from_point" if from_point is not None else "to_point"
        return f"measure got {given} but not the other point: give both from_point and to_point, or only at."
    return "measure needs a point: at=[x, y, z] (what is there), or from_point and to_point (the distance between them)."


def studio() -> Studio:
    with S["lock"]:
        if S["studio"] is None:
            S["studio"] = Studio(config.load())
        return S["studio"]


def _bench(path: str = "") -> str | None:
    url = S["bench"].get("url")
    return f"{url}/{path}" if url else None


def _fail(e: StudioError) -> ToolError:
    pub = e.public()
    msg = pub.pop("message")
    hint = pub.pop("hint", "")
    extra = {k: v for k, v in pub.items() if v not in (None, [], "")}
    return ToolError(msg + (f"\nHint: {hint}" if hint else "") + (f"\nDetails: {json.dumps(extra, default=str)}" if extra else ""))


async def _run(fn, *a, **kw):
    """Run blocking engine work off the event loop; turn engine errors into tool errors."""
    def call():
        try:
            return fn(*a, **kw)
        except StudioError as e:
            raise _fail(e)
    return await anyio.to_thread.run_sync(call)


def _origin(ctx: Context | None) -> str:
    """Who made a change: "agent:<client name>". On 2026-07-28 every request carries the client's info in its own
    `_meta` (there is no session to remember it); a handshake-era client said it once in `initialize`. Neither:
    "agent"."""
    from mcp_types import CLIENT_INFO_META_KEY
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS
    try:
        info = (ctx.request_context.meta or {}).get(CLIENT_INFO_META_KEY)
        name = info.get("name") if isinstance(info, dict) else getattr(info, "name", None)
        if isinstance(name, str) and name.strip():
            return f"agent:{name.strip()}"
    except Exception:
        pass
    try:
        if ctx.protocol_version not in MODERN_PROTOCOL_VERSIONS:      # handshake era: the initialize request said it
            return f"agent:{ctx.session.client_params.client_info.name}"
    except Exception:
        pass
    return "agent"


def act(pid, kind: str, text: str, ctx=None, **extra):
    """Tell the bench what the agent is doing; open it the first time there is something to show."""
    st = studio()
    st.activity(pid, kind, text, by=_origin(ctx).replace("agent:", "") or "agent", **extra)
    url = S["bench"].get("url")
    if url and pid and not str(pid).startswith("draft-") and not S.get("opened") and st.cfg.get("bench", {}).get("auto_open", True):
        S["opened"] = True
        try:
            webbrowser.open(f"{url}/#p={pid}")
        except Exception:
            pass


def _partial_line(info: dict) -> str:
    from .studio import _partial_text
    return _partial_text(info)


def _refine_after(st, pid: str | None, ctx=None, refine: str | None = None) -> dict | None:
    """Start the background refinement of a design that was just built (form/refine/jobs.py), and say so in the
    result. None when it is off for this design (the reason is in refine_design(action="status"))."""
    if not pid:
        return None
    from .refine import jobs
    jid = jobs.after_design(st, pid, _origin(ctx), refine)
    if not jid:
        return None
    return {"state": "running", "job": jid,
            "note": "Refinement runs in the background: named, reversible refine features (fillet tiers, parting "
                    "lines, grip zones, materials) kept only when the function checks hold, landing as one new "
                    "revision \"Refined: N changes\". refine_design(project, action=\"status\") follows it; "
                    "action=\"off\" turns it off for this design."}


def _made(pid: str | None, tool: str, role: str = "made", group: str | None = None, family: bool = True) -> None:
    """Record a design this tool made, picked, copied or reconstructed in the conversation this server works for
    ($FORM_CONVERSATION, set by Form Studio's chat): it is listed in the conversation's designs and put in front, and
    the second and later designs one request makes join the first one's family. Outside Form Studio's chat (no
    conversation) nothing is recorded. Every tool in conversations.CREATOR_TOOLS calls this."""
    from . import conversations
    try:
        conversations.made(studio().root, pid, role, tool, group=group, family=family)
    except Exception:                               # the design exists either way; linking never fails a tool
        pass


def _front() -> str | None:
    """The live design in front of this server's conversation, if any."""
    from . import conversations
    cid = conversations.env_conversation()
    if not cid:
        return None
    try:
        meta = conversations.Conversations(studio().root).meta(cid)
    except conversations.ConversationError:
        return None
    pid = meta.get("project")
    return pid if pid and (studio().root / pid / "project.json").is_file() else None


RELATIONS = ("replaces", "part_of", "alternative", "new")


def _purpose(purpose: str | None) -> str | None:
    """The purpose a design gets: the agent's, else the one the person chose on Home for this chat run (FORM_PURPOSE),
    else None (the person's default, form/purpose.py)."""
    if purpose:
        return purpose
    from . import start
    return start.env_purpose()


# Tools that only make sense for someone who prints (form/capabilities.py "print"). With printing off they are left out
# of form_overview and refuse with PRINTING_OFF: Form Studio is for making things; printing is opt-in.
PRINT_TOOLS = ("choose_printer", "plate_plan", "pack_plate", "print_simulation", "slice_test_piece", "set_print_setup",
               "open_in_slicer")
PRINTING_OFF = ("printing is off; enable it in Settings (Set up for › 3D printing). Form Studio still designs, checks "
                "and exports this as a 3D model (STEP, STL, 3MF, OBJ, GLB).")


def _printing_on() -> bool:
    from . import purpose as purpose_mod
    return purpose_mod.printing(studio().cfg)


def _need_printing() -> None:
    if not _printing_on():
        raise ToolError(PRINTING_OFF)


def digest(st: Studio, pid: str) -> dict:
    try:                                             # measure the contract on this revision once (kept under its key)
        from . import contract
        contract.prove(st, st.load(pid))
    except StudioError:
        pass
    return _digest(st, pid, S["bench"].get("url"))


def _preflight(source: str, values: dict | None, mode: str, before: str | None = None, project: dict | None = None,
               before_values: dict | None = None) -> list:
    strict = before is None
    """Run form/preflight.py on a source before any kernel time. mode "block": errors refuse the call, every one
    listed (for an update: only the errors this source introduces); "warn": they are returned; "off": nothing.
    Returns the findings that did not block, compact."""
    if mode not in ("block", "warn", "off"):
        raise ToolError('preflight is "block" (the default), "warn" or "off".')
    if mode == "off":
        return []
    from . import preflight as pf
    found = pf.check(source, values=values, project=project, strict_values=strict)["findings"]
    errs = [f for f in found if f["severity"] == "error"]
    if before is not None:
        errs = pf.new_findings(errs, pf.check(before, values=before_values, project=project,
                                              strict_values=False)["findings"])
    if errs and mode == "block":
        raise ToolError(pf.message(errs) + "\nHint: nothing was built. Fix every one in the same call; "
                        'preflight="warn" builds anyway.')
    return [{k: f[k] for k in ("rule", "severity", "line", "message", "hint") if f.get(k)} for f in found
            if f["severity"] != "note"]


def _proof(st: Studio, pid: str) -> dict | None:
    """The proof sheet of the head as a tool result carries it: one row per requirement."""
    from . import contract
    try:
        sheet = contract.prove(st, st.load(pid))
    except StudioError:
        return None
    if not sheet:
        return None
    return {"summary": contract.summary(sheet), "green": sheet["green"], "rows": contract.table(sheet)}


async def _wait_job(st: Studio, jid: str, wait_s: float) -> dict:
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if st.jobs[jid]["state"] != "running":
            break
        await anyio.sleep(0.25)
    return st.jobs[jid]


# ---- server ---------------------------------------------------------------

# Tools Claude Code loads up front when tool search defers the rest (the others are found by searching their
# descriptions, so each description's first sentence names its verb and object). Every tool INSTRUCTIONS tells an
# agent to call before it has searched for anything is here: a deferred one answers "No such tool available" when
# called by name. Kept small: each one costs context in every run.
ALWAYS_LOAD = ("form_overview", "get_project", "create_design", "update_design", "render", "preview_change",
               "commit_change", "design_guide", "design_brief", "ask_user", "get_job", "edit_design")
ALWAYS = {"anthropic/alwaysLoad": True}


def extensions() -> list:
    """The MCP extensions this server offers, each only when its module is part of this build:
    io.modelcontextprotocol/skills (form/mcp_skills.py: skills_extension()) and io.modelcontextprotocol/tasks
    (form/mcp_tasks.py: tasks_extension(studio)). A missing module is skipped; any other import error is raised."""
    out = []
    try:
        from .mcp_skills import skills_extension
    except ModuleNotFoundError as e:
        if e.name != f"{__package__}.mcp_skills":
            raise
    else:
        out.append(skills_extension())
    try:
        from .mcp_tasks import tasks_extension
    except ModuleNotFoundError as e:
        if e.name != f"{__package__}.mcp_tasks":
            raise
    else:
        out.append(tasks_extension(studio))
    return out


def build() -> MCPServer:
    import secrets as _secrets
    from mcp.server.request_state import RequestStateSecurity
    from . import elicit
    # requestState (a 2026-07-28 form's round trip) is sealed with a key of this process; a person may take up to
    # elicit.STATE_TTL_S to answer
    security = RequestStateSecurity(keys=[_secrets.token_bytes(32)], ttl=elicit.STATE_TTL_S)
    mcp = MCPServer("form", title="Form Studio AI CAD studio", version=__version__, instructions=INSTRUCTIONS,
                    extensions=extensions(), request_state_security=security)
    RO = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    RW = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

    @mcp.tool(annotations=RO, meta=ALWAYS)
    async def form_overview() -> dict:
        """Get an overview of Form Studio: engine, slicer, printer, available recipes, existing projects and the bench
        URL. Start here."""
        st = studio()
        def go():
            env = st.environment()
            out = {
                "version": env["version"], "kernel": env["kernel"], "printer": env["printer"],
                "slicer": {k: env["slicer"].get(k) for k in ("kind", "available", "reason", "version")} |
                          {"presets": {k: v["name"] for k, v in env["slicer"].get("presets", {}).items()}},
                "calibration_profile": env["profile"],
                "recipes": [{"id": r.id, "title": r.title, "summary": r.summary} for r in st.recipes.builtins().values()],
                "projects": [{k: q.get(k) for k in ("id", "name", "recipe", "head", "approved_rev", "purpose")} for q in st.list()],
                "data_dir": env["data_dir"], "bench": _bench(),
                "has_printer": env["purpose"]["printing"], "purpose_default": env["purpose"]["default"],
                "capabilities": env["purpose"].get("capabilities", []),
                "print_tools": list(PRINT_TOOLS),
            }
            if not env["purpose"]["printing"]:      # printing is off (the default): no printer talk at all
                out.pop("printer"); out.pop("calibration_profile"); out.pop("print_tools")
                out["slicer"] = {"needed": False, "note": "3D printing is off. Do not suggest a printer, a slicer, filament "
                                                          "or print orientation; the print tools refuse until the person "
                                                          "turns 3D printing on in Settings."}
            return out
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def setup_status() -> dict:
        """Check this machine's setup. What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap.
        Never run a fix without asking the user; the simplest path is to ask them to run `form setup` in a terminal."""
        def go():
            from . import installer, setup
            rows = installer.survey(studio().cfg)
            return {"items": [i.public() for i in setup.check(studio().cfg)],
                    # the installer registry: what each thing is for, whether it was found, and the exact commands
                    "software": [{k: r[k] for k in ("id", "label", "why", "level", "status", "detail", "size", "installable", "manual")}
                                 | {"commands": (r["plan"] or {}).get("commands", [])} for r in rows],
                    **installer.summary(rows),
                    "tell_the_user": "Form Studio's app installs these under Settings, Engines & software. Headless: `form install <id>`, "
                                     "or install_software(id, confirm=True) after the user agrees to the command shown."}
        return await _run(go)

    @mcp.tool()
    async def install_software(id: str, confirm: bool = False, method: str | None = None, ctx: Context = None) -> dict:
        """Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude",
        "slicer.orca". Without confirm=True nothing runs: you get the exact commands to show the user. Ask the user
        first, then call again with confirm=True. Never asks for a password; sign-in is not an install.
        Outside Form Studio's chat, a client with its own forms (MCP elicitation) shows the command and the licence
        and asks the person instead (always for a non-commercial licence, even with confirm=True)."""
        from . import elicit
        from . import installer
        cfg = studio().cfg

        def prepare():
            inst = installer.Installer(cfg)
            try:
                pairs = inst.prepare([id], None, {id: method} if method else None)
            except installer.InstallError as e:
                return None, {"installed": False, "error": e.public()}
            sw, m = pairs[0]
            plan = {"id": sw.id, "label": sw.label, "why": sw.why, "size": sw.size, "method": m.label, "commands": m.commands,
                    **({"edits_a_file": m.note} if m.kind == "action" else {})}
            return sw, plan

        def install(plan):
            job = installer.run_blocking(cfg, [id], {id: method} if method else None)
            lines = [l["text"] for l in job.public(0)["log"]]
            return {"installed": job.state == "done", "state": job.state, "ran": plan, "steps": job.steps,
                    "log_tail": lines[-40:], "after": {k: {"status": v["status"], "detail": v["detail"]} for k, v in job.after.items()}}

        sw, plan = await _run(prepare)
        if sw is None:
            return plan
        if elicit.available(ctx) and (confirm is not True or sw.noncommercial):
            r = await elicit.form(ctx, "install", elicit.install_message(plan, sw.licence, sw.licence_url, sw.noncommercial),
                                  elicit.install_schema(sw.licence))
            if elicit.pending(r):
                return r
            if r is not None:
                if not (r.accepted and r.content.get("accept_licence") is True):
                    return {"installed": False, "refused": "The person did not accept the install.", "would_run": plan,
                            "note": "Nothing was installed. Do not ask again unless the person brings it up."}
                return await _run(install, plan)
        if confirm is not True:
            return {"installed": False, "refused": "confirm=True is required.", "would_run": plan,
                    "tell_the_user": "Show these commands and ask before installing."}
        return await _run(install, plan)

    @mcp.tool(annotations=RO)
    async def describe_recipe(recipe: str) -> dict:
        """Describe a recipe's parameters. Parameters (unit, range, group, the feature each one drives), features and what the recipe checks."""
        st = studio()
        if recipe not in st.recipes:
            raise ToolError(f"Unknown recipe “{recipe}”. Known: {', '.join(st.recipes.builtins())}.")
        r = st.recipes[recipe]
        pub = r.public()
        return {"id": r.id, "title": r.title, "summary": r.summary, "category": r.category, "tags": list(r.tags),
                **({"legacy": "Retired from the library; kept so designs that use it still build. Prefer a listed recipe for new designs."}
                   if r.legacy else {}),
                "parameters": [{k: pp[k] for k in ("key", "label", "unit", "default", "min", "max", "group", "feature", "doc") if k in pp}
                               for pp in pub["params"]],
                "features": [{"id": f.id, "label": f.label, "role": f.role} for f in r.features],
                "fit_interface": r.fit,
                "groups": {"brief": "facts about the world (measure these)", "interface": "how parts meet",
                           "form": "free design choices"}}

    @mcp.tool(annotations=RO, meta=ALWAYS)
    async def design_guide(topic: str = "core", purpose: str | None = None) -> dict:
        """Read the design guide for code designs. Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter,
        holder, mechanism...). topic="core" (default) returns the contract for a design written as code, the rules,
        the staged workflow and a complete example that builds; it leads with skeleton first, one validated feature
        at a time (a FeatureDesign, 2 retries per feature, then defer). Other topics, for complex designs: surfacing,
        mechanisms, organic, texture, aesthetics, dfm (design for printing; not applicable when purpose="model"),
        reference_parts (meshes to rebuild as clean editable CAD: analyze, plan, write, compare, refine),
        hybrid (a construction route per feature: kernel, subd_cage, sculpt_recon or procedural, and when to model a
        cage in Blender with model_mesh), game (purpose "game": budgets, LODs, UVs, bakes, collision and engine
        presets, built with game_asset).
        They document form.craft, the helper library for lofts, shells, hinges, snaps, gears, organic bodies and
        textures. Then design_examples for a close exemplar, and create_design."""
        from . import design_guide as dg
        from . import purpose as purpose_mod
        pur = purpose_mod.normalise(_purpose(purpose)) or purpose_mod.default(studio().cfg)
        try:
            out = dg.topic(topic, pur)
        except KeyError:
            raise ToolError(f"Unknown topic “{topic}”. Topics: {', '.join(dg.TOPICS)}.")
        if out["topic"] == "core":
            out["built_in_recipes"] = ", ".join(studio().recipes.builtins()) + " (use create_project for these)"
        return out

    @mcp.tool(annotations=RW, meta=ALWAYS)
    async def design_brief(name: str, goal: str, requirements: list[str] | None = None,
                           dimensions: dict[str, Any] | None = None, constraints: list[str] | None = None,
                           unknowns: list[str] | None = None, style: str = "", purpose: str | None = None,
                           references: list[str] | None = None, project: str | None = None,
                           assertions: list[dict] | None = None, ctx: Context = None) -> dict:
        """Write a design brief. Stage 1 of a complex design: store the structured brief before any geometry. goal: what it is and does.
        requirements: what it must do. dimensions: {name: {value, unit, source}} where source is measured, specified
        (datasheet, standard) or assumed. constraints: limits (bed size, material, process). unknowns: what you could
        not settle; list them, never guess them (ask_user / ask_measurement for ones that change fit, load or
        safety). style: the design language. project: attach to an existing project instead of a new design.
        The brief becomes a contract: requirements the kernel can check, each with a tolerance and where it came
        from. Numbers in goal, requirements and constraints are read ("4 x Ø5.2 on a 60 mm bolt circle", "2.4 mm
        wall", "80 x 60 x 20 mm", "M6 thread", "two-part", "Ø30 bore"); add what words cannot say as assertions:
        [{"kind": "bolt_circle", "count": 4, "hole_d": 5.2, "circle_d": 60}] with kind bbox (size [x, y, z]),
        volume (mm3, op), part_count (count), face_count (count, of), hole_count (count, d), cylinder (d, of
        any|boss|bore), bolt_circle, pattern (count, pitch, hole_d), min_wall (t), thread (major, pitch); each may
        carry tol (mm; 0.1 when not given, said to be assumed), axis and feature (the feature that must meet it).
        Returns contract.assertions and contract.audit: what is missing, conflicting or impossible in the numbers
        themselves (arithmetic, nothing measured). When audit.ask is there, put it to the person once with ask_user
        before any code; a brief with conflicting or impossible numbers cannot be planned or built from.
        After a build, get_project and every commit return the proof sheet: one row per requirement with what the
        kernel measured, the tolerance, the evidence class and PASS, FAIL or UNPROVEN.
        Also returns the brief id, whether it is complex (heuristic), which design_guide topics and exemplars to
        read, and the route (prismatic, revolve, skin+features or mechanism) with how its skeleton is built."""
        st = studio()
        from . import exemplars, staged
        b = await _run(staged.save_brief, st, name, goal, requirements, dimensions, constraints, unknowns, style,
                       _purpose(purpose), references, project, assertions)
        from . import contract as contract_mod
        con = b.get("contract") or {}
        au = dict(con.get("audit") or {})
        ask = contract_mod.audit_text(au)
        if ask:
            au["ask"] = ask
        a = b["assessment"]
        act(project, "design", f"Brief: {name}", ctx)
        hits = exemplars.search(" ".join([name, goal, style]), 3)
        ex = [{"name": e["name"], "title": e["title"]} for e in hits]
        if ex:                                         # the closest one's lessons up front: they are what gets skipped
            ex[0]["lessons"] = hits[0].get("lessons", [])
        adv = staged.advice(" ".join([name, goal, " ".join(map(str, requirements or [])), style]))
        return {"brief": b["id"] if not project else project, "complex": a["complex"], "reasons": a["reasons"],
                "evidence": a["evidence"], "read_topics": staged.topics_for(a["families"]),
                "examples": ex, **adv,
                "unknowns": b["unknowns"],
                "contract": {"assertions": [{k: a[k] for k in ("id", "kind", "text", "tol", "provenance") if k in a}
                                            for a in con.get("assertions") or []], "audit": au},
                "next": "design_guide(topic=...) for each topic, design_examples(name=...) for the closest exemplar, then "
                        "plan_design(brief=...)."}

    @mcp.tool(annotations=RW)
    async def plan_design(brief: str, features: list[dict], parts: list[dict] | None = None,
                          key_dimensions: dict[str, Any] | None = None, mechanisms: list[str] | None = None,
                          textures: list[str] | None = None, risks: list[str] | None = None, approach: str = "",
                          references_used: list[str] | None = None, product_class: str = "",
                          clearances: dict[str, float] | None = None, magnets: list[dict] | None = None) -> dict:
        """Plan a design's features. Stage 2: store the feature plan for a brief (the id design_brief returned, or a project id).
        features: [{id, label, how, part?, dims?}] in build order; id becomes the Feature id in the code, how names
        the construction (e.g. "craft.loft_sections through 9 superellipse sections", "craft.pin_hinge 0.35 mm").
        parts: [{id, label, material?}]. key_dimensions: {name: value or {value, unit, why}}. mechanisms: each with its
        clearance and motion. textures: each with its tier (B-rep or mesh texture). risks: what could make it fail and
        how you will check it. A complex brief needs at least 3 features and named risks. Every craft.x, parts.x and
        patterns.x a how names must exist (an unknown one is refused with the closest real names). Several parts
        (magnets, a lid, a faceplate, separate parts): parts, clearances ({"faceplate/shell": 0.3}, mm per side) and
        magnets ([{stock: "8x3", count, retention: press|glue|printed}]) are required.
        Returns the plan as ordered steps: the skeleton first (create_design with that feature only), then one
        add_feature(kind="code") per feature, each with its risk class, a fallback and the retry cap.
        Each feature may name its construction route (route: kernel | subd_cage | sculpt_recon | procedural); without
        one it is read from the feature's words (heuristic, said so). feature_routes gives each with the words that
        chose it; a mechanical interface on a mesh-only route is warned about; mesh routes point at model_mesh.
        product_class: what critique compares the silhouette with (helmet_fullface, helmet_open, mouse, bottle);
        empty: detected from the brief's words, or none. The design faces +X with Z up for the comparison.
        Then create_design(..., plan=<brief id>)."""
        st = studio()
        from . import staged
        r = await _run(staged.save_plan, st, brief, features, parts, key_dimensions, mechanisms, textures, risks,
                       approach, references_used, product_class, clearances, magnets)
        return {**r, "steps": r["plan"]["steps"], "route": r["plan"]["route"],
                "next": f"Step 1: create_design(..., plan='{brief}') with a FeatureDesign holding only the first feature "
                        "(or update_design for an existing project); look at the sheet; then one add_feature(kind=\"code\") "
                        "per step. Defer a feature after 2 retries and list the deferred ones at the end."}

    @mcp.tool(annotations=RO)
    async def design_examples(query: str = "", name: str = "", technique: str = "", category: str = "") -> dict:
        """Search example designs and their code. Complete, high-quality example designs (build123d + form.craft) to learn construction from, over 40 of
        them: mechanical parts (linear slide, shaft coupler, pillow block, cam follower, gearbox), consumer products
        (mouse, earbud case, bottle and cap, game controller), organic forms (horn, handle), textured parts
        (knurl, hex relief, woven, fluted), assemblies (hinged case, ratchet wrench, robot head), helmets (full-face,
        open-face) and enclosures (electronics box with bosses, sliding battery box, handheld shell).
        query: words to search (ranked); name: one exemplar with its full source; technique: just the code block that
        does one thing ("hollow a lofted shell", "snap-fit lid", "two-view opening"); category: mechanical, consumer,
        organic, textured, assembly, helmet or enclosure. They are references for you, never projects, and never
        shown to the person as designs."""
        from . import exemplars
        if name:
            try:
                return exemplars.get(name)
            except KeyError:
                raise ToolError(f"Unknown exemplar “{name}”. Known: {', '.join(e['name'] for e in exemplars.retrievable())}.")
        if technique:
            return {"snippets": exemplars.snippets(technique, 4),
                    "next": "design_examples(name=...) returns the whole design a snippet comes from."}
        if query:
            hits = exemplars.search(query, 5, category or None)
        else:
            keep = ("name", "title", "category", "summary", "tags", "snippets")
            hits = [{k: e.get(k) for k in keep} for e in exemplars.retrievable() if not category or e["category"] == category]
        return {"examples": hits, "next": "design_examples(name=...) returns the full source and the lessons; "
                                          "technique=... returns just the block that does one thing."}

    @mcp.tool(annotations=RW, structured_output=False)
    async def critique(project: str, notes: str = "", reads_as: str = "", product_class: str = "",
                       aesthetic: dict[str, float] | None = None, ctx: Context = None) -> list:
        """Critique a design with close-ups and metrics. Stage 5: look closely and measure. Returns a close-up render of each feature, computed metrics (smallest
        fillet, sharp-edge fraction, symmetry, proportions, surface mix, sliver faces, planned features missing, folds
        in lofted skins, wall thickness by rays with break-through spots, silhouette kinks) and a checklist to answer
        by looking. When the brief names a product class (helmet_fullface, helmet_open, mouse, bottle; or pass
        product_class), the side, front and top silhouettes are compared with the class outline, the proportions
        with the class range (with sources) and its signature is checked (an eye port, a neck opening, a palm hump...);
        the design must face +X with Z up. Then look at the views and answer "does it read as a <class>?" in
        reads_as (what makes it read as one, what gives it away); the checklist keeps asking until you do.
        aesthetic: after render_photo from three angles, your 0-5 scores for silhouette, proportion, continuity,
        radius_hierarchy, break_up, detail_rhythm, material, would_sell. The rubric caps each by what the geometry and
        the appearance() zones support and reports the gate (mean >= 4, none under 3); run it on every request for
        something beautiful, at least twice.
        All of it is heuristic evidence: numbers to prompt a look, not a verdict. Records one critique pass for the
        head revision (with your notes: what you saw, what you will change); a briefed or planned design cannot be
        released before its head revision has one."""
        st = studio()
        from . import critique as crit
        r = await _run(crit.run, st, project, notes, reads_as, product_class or None, aesthetic or None)
        act(project, "look", "Critiquing the design: close-ups, metrics, checklist", ctx)
        out: list = []
        if r.get("closeups"):
            out.append(Image(path=r["closeups"]))
        out.append(json.dumps({k: v for k, v in r.items() if k != "closeups"}, indent=1, default=str))
        return out

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True), structured_output=False)
    async def read_document(source: str, pages: str = "1") -> list:
        """Read a document such as a datasheet or drawing. Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). PDF pages come
        back as images, because a drawing's dimensions are graphics that text extraction loses, plus any text on the page.
        pages: "1", "1-3", "2,5" (at most 4). Use this for official dimensions of boards, devices and hardware."""
        st = studio()
        def go():
            from . import documents
            try:
                f = documents.fetch(source, st.root / ".references")
                r = documents.render(f, pages)
            except Exception as e:                       # network, format, size
                raise StudioError(f"Could not read {source}: {e}", "Try the document's direct PDF link, or a local copy.")
            return f, r
        f, r = await _run(go)
        act(None, "look", f"Reading {source.split('/')[-1][:60]}", None)
        out: list = [Image(data=b, format="png") for b in r["images"]]
        out.append(f"Pages {r['pages']} of {r['page_count']} from {source} (saved as {f.name})."
                   + (f"\n\nText on the page:\n{r['text'][:4000]}" if r["text"] else ""))
        return out

    # -- links and big meshes (form/sources, form/start.py, form/meshprep.py) ------------------------------------
    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
    async def fetch_link(url: str, conversation: str = "", ctx: Context = None) -> dict:
        """Download what a link the person gave points to, from Form Studio's engine (use this instead of a shell: it
        works where your sandbox has no network). A file link (STL, 3MF, OBJ, STEP, PDF, image; also a signed
        MakerWorld download link, fetched at once before it expires) is downloaded; a Printables model page has its
        part files downloaded with title, author and licence; a Thingiverse or MakerWorld page returns why its files
        cannot be fetched and what the person can do; any other page is not read (resolve_model_page reads its title).
        In a Form Studio chat the files are attached to the conversation; otherwise they are saved under the data
        folder. Each mesh comes with its preflight (triangles, size, closed or not, class). Only fetch links the
        person gave you. Outside Form Studio's chat, a client with its own forms (MCP elicitation) asks the person
        before a download over 100 MB; declined: {fetched: false, refused}."""
        import hashlib
        import os
        st = studio()
        from . import elicit, meshprep
        from . import start as start_mod
        cid = conversation or os.environ.get("FORM_CONVERSATION", "")
        if not cid and elicit.available(ctx):
            size = await anyio.to_thread.run_sync(elicit.link_size, url)
            if size and size > elicit.FETCH_CONFIRM_BYTES:
                r = await elicit.form(ctx, "download", elicit.download_message(url, size), elicit.DOWNLOAD_SCHEMA)
                if elicit.pending(r):
                    return r
                if r is not None and not (r.accepted and r.content.get("download") is True):
                    return {"fetched": False, "url": url, "size_bytes": size,
                            "refused": "The person did not want this download.",
                            "note": "Nothing was downloaded. Ask for a smaller file, or for the person to drop it here."}

        def go():
            if cid:
                from .conversations import Conversations
                store = Conversations(st.root)
                got = start_mod.fetch(st, cid, url)
                for a in got.get("attachments", []):
                    a["path"] = str(store.attachment(cid, a["file"]))
            else:
                key = hashlib.sha256(url.encode()).hexdigest()[:12]
                got = start_mod.fetch_to_folder(url, st.root / ".references" / "links" / key)
            for a in got.get("attachments", []):
                if a["path"].lower().endswith((".stl", ".obj", ".3mf")):
                    try:
                        pf = meshprep.preflight(Path(a["path"]), cache=st.root / ".cache" / "meshprep")
                        a["preflight"] = {k: pf.get(k) for k in ("triangles", "size_mm", "closed", "class", "estimate_s",
                                                                 "parts", "warning") if pf.get(k) is not None}
                    except (OSError, ValueError) as e:
                        a["preflight"] = {"error": str(e)}
            return got
        got = await _run(go)
        act(None, "look", f"Fetching {url[:80]}", None)
        if got.get("attachments"):
            got["next"] = ("Import a part with import_reference(project, path), or analyze_reference(path) to understand "
                           "it. Keep the licence in mind when the design copies a published model.")
        return got

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    async def resolve_model_page(url: str) -> dict:
        """Resolve a model page link. What a model link is, without downloading files: site, title, author, licence, pictures and the file list
        (Printables, Thingiverse with an app token), or why the files cannot be fetched and how the person gets them
        (MakerWorld, Thingiverse without a token). Any other page: its OpenGraph title, description and pictures as a
        visual reference. Then fetch_link(url) downloads what can be downloaded."""
        from . import sources

        def go():
            try:
                r = sources.resolve(url)
            except sources.SourceError as e:
                raise StudioError(str(e), e.hint)
            r.pop("model_id", None)
            return r
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def mesh_preflight(path: str) -> dict:
        """Preflight a mesh file. Before working on a large mesh (STL, OBJ, 3MF): triangles, vertices, bounds, closed or not, its class
        (light, medium, heavy, very heavy), estimated seconds for reading and analysing it, and a decimated display
        proxy for a heavy one. The proxy is for display only; analysis and import always use the file itself.
        path: absolute local path. Cached by path, size and time, so asking again is instant."""
        st = studio()
        from . import meshprep

        def go():
            try:
                return meshprep.preflight(Path(path).expanduser(), cache=st.root / ".cache" / "meshprep")
            except (OSError, ValueError) as e:
                raise StudioError(f"Could not read {Path(path).name} as a mesh: {e}", "Give the absolute path of an STL, OBJ or 3MF.")
        return await _run(go)

    async def _with_views(st, pid: str, payload: dict) -> list:
        """The tool's result as text plus the six-view sheet and the section (form/critique.py design_views)."""
        from . import critique as crit
        out: list = [json.dumps(payload, indent=1, default=str)]
        try:
            v = await _run(crit.design_views, st, pid)
        except Exception as e:                             # a design that built but cannot be drawn says so
            out.append(f"Views could not be rendered: {e}")
            return out
        out += [Image(path=v["sheet"]), v["caption"]]
        if v.get("section"):
            out += [Image(path=v["section"]), "Section through the centre (cut face picked out). Check walls, voids and "
                    "clearances."]
        elif v.get("section_error"):
            out.append(v["section_error"])
        return out

    @mcp.tool(annotations=RW, structured_output=False, meta=ALWAYS)
    async def create_design(name: str, source: str, brief: str = "", values: dict[str, float] | None = None,
                            run: bool = True, language: str = "python", references: list[str] | None = None,
                            purpose: str | None = None, process: str | None = None, plan: str = "",
                            relation: str = "", partial: bool = True, refine: str = "auto", preflight: str = "block",
                            ctx: Context = None) -> list:
        """Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass,
        built with build123d. Form Studio builds it and returns a six-view sheet and a section to look at; with
        run=True it also exports STEP and STL and runs the checks (and, for a design whose purpose is "print", the
        print checks and a slice). Load errors come back with the line and a hint; fix and call again.
        Skeleton first: create the main body, then add one feature per call. partial=True (default): when a later
        feature fails, the stages that built before it are saved as a partial revision (flagged, release blocked)
        and shown, and the result names the failed feature with its diagnosis; fix it with update_design. partial=False
        refuses the whole design instead. Each stage is shown in Form Studio as it builds. A FeatureDesign
        (`from form.featureprog import FeatureDesign, feature`; one `@feature("Label")` method per feature,
        `def eyes(self, v, body): return body_after`, the first gets body=None) skips a failing feature and goes on,
        and keeps a checkpoint per feature, so update_design(feature=, code=) rebuilds only that feature and later ones.
        Several parts: declare assembly() (design_guide, ASSEMBLIES): parts with attach=, joints with parent= (chains: a
        joint moves everything attached below it), Mate() for pins and threads. A declaration that cannot be used
        (unknown part, a loop, two parents) is refused with the reason; the assembly checks then run in their own time
        budget and say which joint ranges they reached.
        language="openscad": source is an OpenSCAD file; parameters come from Customizer comments (`w = 40; // [20:1:120]`).
        OpenSCAD output is a mesh: no STEP, no B-rep checks (reported as not available, never faked).
        references: absolute paths of STEP/STL parts to import first, so a Python design can use self.reference("name.step").
        purpose: "print" (for 3D printing) or "model" (just a 3D model; not sliced, no print checks). Omitted: the
        person's default. process (models only): cnc, laser, injection, casting, sheet_metal, render, cad, other.
        plan: the brief id from design_brief/plan_design. A complex brief (a mechanism, an organic or styled form, a
        texture, several parts) is refused without one; one brief serves every design of the request.
        relation: in Form Studio's chat, when the conversation already has a design in front, say what this code is to
        it: "replaces" (a new revision of that design), "part_of" (one more part of that design, e.g. the lid of a
        box), "alternative" (a separate design in its family) or "new" (an unrelated design). One request makes one
        design: use part_of for the parts of one product.
        refine: "auto" (default): after the build, design refinement runs in the background and lands as one more
        revision, "Refined: N changes", each change a named refine feature you can undo (refine_design); "off": not
        for this design; "on": also for a game asset, which is not refined unless asked.
        preflight: before the kernel is asked for anything, the source is checked without it and every problem comes
        back at once (a constraint its own values violate, a name or keyword build123d and form.craft do not have,
        a parameter that is read but not declared, a Polygon wound clockwise and extruded upward, a thread pair
        that does not engage); "block" (default) refuses on errors, "warn" builds anyway, "off" skips it.
        Returns the project (with the proof sheet when the brief has a contract), a six-view sheet and a section: look."""
        st = studio()
        from . import staged
        if refine not in ("auto", "off", "on", ""):
            raise ToolError("refine is \"auto\" (the default), \"off\" or \"on\" (also refine a game asset).")
        if relation and relation not in RELATIONS:
            raise ToolError(f"Unknown relation “{relation}”: use {', '.join(RELATIONS)}.")
        front = _front()
        if front and not relation:
            raise ToolError(f"This conversation already has a design in front: {front}. Say what this code is to it: "
                            "relation=\"replaces\" (a new revision of it), \"part_of\" (one more part of it), "
                            "\"alternative\" (a separate design in its family) or \"new\" (an unrelated design). "
                            "One request makes one design: the parts of one product are part_of.")
        if relation in ("replaces", "part_of") and not front:
            raise ToolError(f"relation=\"{relation}\" needs a design in front of this conversation, and there is none. "
                            "Leave relation out.")
        if language == "python":
            await _run(staged.require_plan, st, f"{name}. {brief}", source, plan)
        pre = await _run(_preflight, source, values, preflight) if language == "python" else []
        if relation in ("replaces", "part_of"):
            if relation == "replaces":
                act(front, "design", f"Replacing the design's code: {name}", ctx)
                p = await _run(lambda: st.update_design(st.load(front), source, f"Replaced: {name}", values,
                                                        _origin(ctx), None, language))
                note = f"r{p['head']:02d}: replaced with {name}"
            else:
                from . import multipart
                act(front, "design", f"Adding a part: {name}", ctx)
                r = await _run(multipart.add_part, st, front, name, source, values, _origin(ctx))
                p = st.load(front)
                note = f"r{p['head']:02d}: added part {r['part']} ({name})"
            act(front, "commit", note, ctx)
            if plan:
                await _run(staged.attach_pending, st, front, plan)
            _made(front, "create_design", role="continued")
            res: dict[str, Any] = {"relation": relation, "head": p["head"]}
            if refine == "off":
                from .refine import jobs
                await _run(jobs.set_project, st, front, "off")
            rf = _refine_after(st, front, ctx)
            if rf:
                res["refinement"] = rf
            if run:
                jid = st.run(front)
                res["pipeline"] = job_digest(await _wait_job(st, jid, 45))
            res["project"] = await _run(digest, st, front)
            return await _with_views(st, front, res)
        draft = "draft-" + uuid.uuid4().hex[:10]
        act(None, "design", f"Writing a new design: {name}", ctx, draft=draft)
        p = await _run(st.create_design, name, source, brief, values, language, references, _purpose(purpose), process,
                       partial, draft)
        part = st.rev(p).get("partial")
        act(p["id"], "commit", f"Created {name} (r01" + (", partial" if part else "") + ")", ctx, draft=draft)
        if relation == "alternative" and front:
            await _run(st.adopt, p["id"], front, "alternative")
        _made(p["id"], "create_design", family=relation != "new")
        if plan:
            await _run(staged.attach_pending, st, p["id"], plan)
        if refine == "off":
            from .refine import jobs
            await _run(jobs.set_project, st, p["id"], "off")
        rf = _refine_after(st, p["id"], ctx)
        job = None
        if run:
            jid = st.run(p["id"])
            job = await _wait_job(st, jid, 50)
        res = await _run(digest, st, p["id"])
        if rf:
            res = {**res, "refinement": rf}
        if pre:
            res = {**res, "preflight": pre}
        if part and not part.get("failed") and part.get("parts"):
            res = {**res, "partial": part,
                   "next": f"Saved: {_partial_line(part)}. Add the next part or feature with add_feature(project="
                           f"'{p['id']}', kind=\"code\", feature=..., code=...); release waits until every part is "
                           "there."}
        elif part:
            res = {**res, "partial": part,
                   "next": f"Saved as a partial design: {_partial_line(part)}. Fix that feature and send it with "
                           f"update_design(project='{p['id']}', source=...) (or feature=, code= for a FeatureDesign); "
                           "the shown solid is what built."}
        if job is not None and job["state"] == "running":     # checks on a heavy design outlast the wait: say so
            res = {**res, "pipeline": job_digest(job),
                   "next": f"Exports and checks are still running: get_job(project='{p['id']}', job='{jid}') "
                           "waits for them (or run_pipeline(project), which reuses finished outputs); look at the "
                           "sheet meanwhile."}
        return await _with_views(st, p["id"], res)

    @mcp.tool(annotations=RW, structured_output=False, meta=ALWAYS)
    async def update_design(project: str, source: str = "", note: str = "", values: dict[str, float] | None = None,
                            expect_head: int | None = None, run: bool = True, language: str | None = None,
                            feature: str = "", code: str = "", partial: bool = False, preflight: str = "block",
                            ctx: Context = None) -> list:
        """Replace a design's code as a new revision (history keeps every version). To change one feature, a helper or
        a parameter, use edit_design: it sends only what changes. Existing parameter values carry over;
        changing a default does not change a saved value, so pass values={...} to change them. New parameters start at
        their defaults. Use preview_change/commit_change instead when only values change. language defaults to the
        project's current one ("python" or "openscad"). An unusable assembly() declaration is refused with the reason,
        and no revision is made. Returns the result with a six-view sheet and a section of the new revision: look.
        One feature of a FeatureDesign: feature="eyes", code="def eyes(self, v, body): ..." (no source) replaces that
        method only; features before it load from their checkpoints. A feature that fails makes no revision (the head
        stays) and returns its diagnosis, unless partial=True, which saves the revision with it left out (release
        blocked). result.build_log says per feature whether it was built, loaded from its checkpoint or skipped.
        preflight: as create_design (an update is refused only for errors this source introduces).
        For a briefed design, critique(project) the revision before asking for release."""
        st = studio()
        if bool(feature) != bool(code) or (feature and source):
            raise ToolError("Send either source (the whole file) or feature and code (one feature method).")
        if not feature and not source:
            raise ToolError("Send source, or feature and code.")
        draft = "draft-" + uuid.uuid4().hex[:10]
        act(project, "design", f"Building {'feature ' + feature if feature else 'new code'}", ctx, draft=draft)

        pre: list = []

        def go():
            from . import featureprog
            p0 = st.load(project)
            py = (language or ("openscad" if st.rid(p0).startswith("scad:") else "python")) == "python"
            if feature:
                src = featureprog.replace_feature(featureprog._source(st, p0), feature, code)
            else:
                src = source
            if py:
                vals = {**st.rev(p0)["values"], **(values or {})}
                pre.extend(_preflight(src, vals, preflight, st.source_text(p0) or "", p0, st.rev(p0)["values"]))
            if feature:
                return featureprog.update_feature(st, p0, feature, code, note, values, _origin(ctx),
                                                  expect_head, partial, draft)
            return st.update_design(p0, source, note, values, _origin(ctx), expect_head, language,
                                    partial=partial, draft=draft)
        p = await _run(go)
        head = st.rev(p)
        act(project, "commit", f"r{p['head']:02d}: {note or (('feature ' + feature) if feature else 'design code updated')}"
            + (" (partial)" if head.get("partial") else ""), ctx, draft=draft)
        res: dict[str, Any] = {"head": p["head"]}
        if head.get("build_log"):
            res["build_log"] = head["build_log"]
        if head.get("partial"):
            res["partial"] = head["partial"]
        if pre:
            res["preflight"] = pre
        rf = _refine_after(st, project, ctx)
        if rf:
            res["refinement"] = rf
        if run:
            jid = st.run(project)
            res["pipeline"] = job_digest(await _wait_job(st, jid, 45))
            if res["pipeline"]["state"] == "running":
                res["next"] = (f"Exports and checks are still running: get_job(project='{project}', job='{jid}') waits "
                               "for them (or run_pipeline(project), which reuses finished outputs); look at the sheet meanwhile.")
        res["project"] = await _run(digest, st, project)
        return await _with_views(st, project, res)

    @mcp.tool(annotations=RW, structured_output=False, meta=ALWAYS)
    async def edit_design(project: str, ops: list[dict], expect_head: int | None = None, note: str = "",
                          run: bool = True, partial: bool = False, preflight: str = "block", look: bool = True,
                          ctx: Context = None) -> list:
        """Edit a design's code by naming what changes: one build, one revision. Send ops, not the file.
        ops, applied in order, all checked before any is applied (every problem comes back at once):
        {"op": "replace", "feature": "holes", "code": "def holes(self, v, body): ..."}  one feature method;
        {"op": "replace", "def": "poly", "code": "def poly(pts, L): ..."}  a helper or another method (constraints,
        derived, setup); {"op": "replace", "find": "exact text", "with": "new text"}  text found exactly once;
        {"op": "insert", "feature": "ribs", "code": "...", "after": "body", "label": "Ribs", "role": "structure"};
        {"op": "insert", "def": "ring", "code": "def ring(r): ..."}; {"op": "insert", "param": {"key": "rib_t",
        "label": "Rib thickness", "default": 2, "min": 1, "max": 4}}; {"op": "delete", "feature" | "def" | "param": name};
        {"op": "set_param", "param": "wall", "value": 2.4}  this revision's value; with default, min, max, step,
        label or doc it changes the declaration too (a new default is also the value).
        A design written as a plain Recipe is edited in its canonical form: its build() is lifted into one method
        per Stage, built once and accepted only when volume, face count and bounding box are unchanged (computed);
        get_design_source returns that form, and its feature ids are what ops name.
        Only what changed is built: features before the first changed one load from their checkpoints. The source
        is checked without the kernel first (preflight: "block" refuses on errors the edit introduces, "warn",
        "off"); a feature that fails makes no revision unless partial=True. Pass expect_head.
        Returns head, source_sha, changed (only the features built again: status, seconds, volume change), reused
        (how many loaded from checkpoints), the proof sheet (requirement, measured, tolerance, evidence, status)
        when the design has a contract or expects=, failing checks, and with look=True the six-view sheet."""
        st = studio()
        if preflight not in ("block", "warn", "off"):
            raise ToolError('preflight is "block" (the default), "warn" or "off".')
        draft = "draft-" + uuid.uuid4().hex[:10]
        act(project, "design", f"Editing: {len(ops or [])} op(s)", ctx, draft=draft)

        def go():
            from . import edits
            return edits.edit(st, st.load(project), ops, expect_head, note, _origin(ctx), partial, draft, preflight)
        r = await _run(go)
        p = r.pop("project")
        head = st.rev(p)
        act(project, "commit", f"r{p['head']:02d}: {head.get('note') or 'edited'}"
            + (" (partial)" if head.get("partial") else ""), ctx, draft=draft)
        res: dict[str, Any] = {"head": r["head"], "source_sha": r["source_sha"], "changed": r["changed"],
                               "reused": len(r["reused"]), "edit": r["edit"]}
        for k in ("canonical", "partial"):
            if r.get(k):
                res[k] = r[k]
        if r.get("preflight"):
            res["preflight"] = [{k: f[k] for k in ("rule", "severity", "line", "message", "hint") if f.get(k)}
                                for f in r["preflight"] if f["severity"] != "note"]
        rf = _refine_after(st, project, ctx)
        if rf:
            res["refinement"] = rf
        if run:
            jid = st.run(project)
            res["pipeline"] = job_digest(await _wait_job(st, jid, 45))
            if res["pipeline"]["state"] == "running":
                res["next"] = f"Exports and checks are still running: get_job(project='{project}', job='{jid}')."
        d = await _run(digest, st, project)
        if d.get("proof"):
            res["proof"] = d["proof"]
        bad = [c for c in d.get("checks", []) if c.startswith(("FAIL", "WARN"))]
        if bad:
            res["checks_to_look_at"] = bad
        res["release_gate"] = {"ready": d["release_gate"]["ready"], "blocking": d["release_gate"]["blocking"]}
        if not look:
            return [json.dumps(res, indent=1, default=str)]
        return await _with_views(st, project, res)

    @mcp.tool(annotations=RW, structured_output=False)
    async def build_candidates(candidates: list[dict], name: str = "", project: str = "", brief: str = "",
                               targets: dict | None = None, product_class: str = "", keep: str = "best",
                               purpose: str | None = None, plan: str = "", expect_head: int | None = None,
                               sweep: bool = True, ctx: Context = None) -> list:
        """Build 2-6 versions of a risky design or step at the same time (one kernel worker each), verify and score
        every one, and keep the best. candidates: [{label, source}] or, after the first, {label, values} to try other
        values on the first one's source. Use it when there are two or three plausible constructions (a loft or a
        sweep, one shell or two halves, a thick or a thin wall) instead of trying them one by one.
        One risky feature of a FeatureDesign: {label, feature, code} entries are versions of that one method on the
        project's head source (project=...) or on a first {label, source}; they share the checkpoints of the
        features before it, so only the feature under test is built per version.
        Scores (0-100, heuristic, the parts are returned): builds (a valid solid with the declared count; a failure
        carries its diagnosis), brief (targets: {"size_mm": [x, y, z], "tolerance_mm": 1, "solids": n,
        "derived": {key: value}}), quality (critique metrics; the product class silhouette with product_class),
        robust (fewer form.craft fallbacks) and editable (the share of parameters that still build at both ends of
        their range). keep="best": create the design `name` from the winner (or a new revision of `project`, with
        expect_head); keep="none": only compare. A candidate that fails never sinks the others. Returns the ranking
        and, when a design was kept, its six-view sheet: look."""
        st = studio()
        from . import candidates as cand, staged
        if keep == "best" and name and not project:
            first = next((c.get("source") for c in candidates if isinstance(c, dict) and c.get("source")), "")
            await _run(staged.require_plan, st, f"{name}. {brief}", first, plan)
        act(project or None, "design", f"Building {len(candidates)} candidates" + (f" for {name}" if name else ""), ctx)
        r = await _run(cand.run, st, candidates, name, project, brief, targets, product_class or None, keep,
                       _purpose(purpose), sweep, 25.0, "", expect_head, _origin(ctx))
        pid = r.get("project")
        if not pid:
            return [json.dumps(r, indent=1, default=str)]
        if not project:
            _made(pid, "build_candidates")
            if plan:
                await _run(staged.attach_pending, st, pid, plan)
        act(pid, "commit", f"r{r['head']:02d}: best of {len(candidates)} candidates ({r['best']})", ctx)
        rf = _refine_after(st, pid, ctx)
        if rf:
            r["refinement"] = rf
        r["project"] = await _run(digest, st, pid)
        return await _with_views(st, pid, r)

    @mcp.tool(annotations=RW)
    async def refine_design(project: str, action: str = "status", feature: str = "", wait: float = 0,
                            expect_head: int | None = None, ctx: Context = None) -> dict:
        """Show, rerun, undo or turn off design refinement of a project. It runs on its own after every build (create_design, update_design,
        add_feature, a kept candidate): named, reversible refine features (fillet tiers, an edge break, a parting
        line, a grip texture, a recessed panel, button pads, ribs; materials and contrast; for game assets cage ops
        such as support loops, panel lines and silhouette breakers), each kept only when the function checks still
        pass, the faces of fit, access, mechanism and interface features are unchanged and the walls hold. What it
        keeps lands as one new revision, "Refined: N changes", each change with its reason and measured change.
        action: "status" (the job's stage and events, and the refine changes the head carries; wait=s waits up to s
        seconds for a running job), "rerun" (refine the head again now), "undo" (feature="refine_..." takes one change
        out, no feature takes all of them out, as a new revision; expect_head guards it), "off" (no automatic
        refinement for this design from now on; "on" turns it back on). Game assets (Beta) are not refined unless
        asked: "on" or "rerun" for this design, or Settings › Refine game assets for all. Measures are computed
        heuristics (form/refine/analyze.py); the checks are the kernel's."""
        st = studio()
        from .refine import engine, jobs
        if action not in ("status", "rerun", "undo", "off", "on"):
            raise ToolError("action is status, rerun, undo, off or on.")
        if action == "status":
            if wait and wait > 0:
                return await _run(jobs.wait, st, project, min(float(wait), 300.0))
            return await _run(jobs.status, st, project)
        if action == "rerun":
            jid = await _run(jobs.start, st, project, "on")
            act(project, "refine", "Refining again" if jid else "Refinement is off for this design", ctx)
            return {**(await _run(jobs.status, st, project)), "job": jid}
        if action == "undo":
            jobs.cancel(project)
            p = await _run(engine.undo, st, project, feature or None, expect_head)
            act(project, "commit", f"r{p['head']:02d}: undid refinement" + (f" ({feature})" if feature else ""), ctx)
            return {"head": p["head"], "changes": await _run(engine.changes, st, p)}
        await _run(jobs.set_project, st, project, "off" if action == "off" else "on")
        if action == "off":
            jobs.cancel(project)
        return await _run(jobs.status, st, project)

    @mcp.tool(annotations=RO)
    async def get_design_source(project: str, rev: int | None = None, feature: str = "", canonical: bool = True) -> dict:
        """Get a design's source code: the code a revision was built from (built-in recipes return their recipe file).
        Read it once; then change it with edit_design ops, which name features, and never send it back whole.
        The head comes in canonical form, one method per feature: a FeatureDesign as it is, a plain Recipe lifted
        (form: "features" when its build() split into feature methods, "skeleton" when it is one feature, "none"
        with the reason when it stays as written), kernel-checked to be the same solid. features lists the ids
        edit_design addresses; source_sha names this text. feature="holes" returns only that method (and the
        parameters it reads). canonical=False, or a rev, returns the stored text."""
        st = studio()
        def go():
            p = st.load(project)
            if rev is not None or not canonical:
                return {"project": project, "rev": rev or p["head"], "recipe": st.rid(p, rev),
                        "source": st.source_text(p, rev)}
            from . import edits, featureprog
            c = edits.canonical(st, p)
            out = {"project": project, "rev": p["head"], "recipe": st.rid(p), "form": c["mode"],
                   "features": c["features"], "source_sha": c["rid"].split(":", 1)[-1], "source": c["source"]}
            if c.get("why"):
                out["why"] = c["why"]
            if feature:
                spans = featureprog.method_spans(c["source"])
                if feature not in spans:
                    raise StudioError(f"No feature “{feature}” in this design.", "Features: " + ", ".join(spans) + ".")
                a, b = spans[feature]
                import re as _re
                import textwrap as _tw
                code = _tw.dedent("\n".join(c["source"].splitlines()[a - 1:b]))
                keys = sorted(set(_re.findall(r"\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]", code)))
                vals = st.rev(p)["values"]
                out["source"] = code
                out["feature"] = feature
                out["reads"] = {k: vals[k] for k in keys if k in vals}
            return out
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def create_project(name: str, recipe: str, brief: str = "", values: dict[str, float] | None = None,
                             run: bool = True, purpose: str | None = None, process: str | None = None,
                             ctx: Context = None) -> dict:
        """Create a project from a built-in recipe (form_overview lists them: gridfinity_bin, storage_box, pegboard, device_stand, ...).
        For anything else, write a design: design_guide, then create_design. values override recipe defaults (all start as 'assumed').
        With run=True the solid, exports and checks are built (and sliced if a slicer is available and it is for printing).
        purpose: "print" or "model" (just a 3D model); omitted: the person's default. process: see create_design."""
        st = studio()
        p = await _run(lambda: st.create(name, recipe, brief, values, purpose=_purpose(purpose), process=process))
        act(p["id"], "commit", f"Created {name} from the {recipe} recipe", ctx)
        _made(p["id"], "create_project")
        if run:
            jid = st.run(p["id"])
            await _wait_job(st, jid, 50)
        return await _run(digest, st, p["id"])

    @mcp.tool(annotations=RO, meta=ALWAYS)
    async def get_project(project: str) -> dict:
        """Get a project's state: current revision with every parameter and its provenance, output status (current/stale/failed/missing),
        checks, fit model, next best actions, simulated slice, file paths, release gate and bench link."""
        st = studio()
        return await _run(digest, st, project)

    @mcp.tool(annotations=RO, meta=ALWAYS)
    async def preview_change(project: str, values: dict[str, float], ctx: Context = None) -> dict:
        """Build a candidate change for real and report what it would touch, without saving anything:
        changed features, interface dimensions, stability, fit yield, which outputs it would invalidate.
        Invalid candidates come back as an error naming the feature, parameters and a fix."""
        st = studio()
        def go():
            p = st.load(project)
            v = st.preview(p, values)
            out = {"buildable": True, "base_rev": p["head"], **impact_digest(v["impact"]),
                   "built_in_s": v["round_trip_s"]}
            if v.get("fit"):
                out["fit_after"] = f"{v['fit']['yield'] * 100:.0f}% modelled yield, expected gap {v['fit']['expected_gap']:.2f} mm"
            out["next"] = f"render(project, values=...) to look; commit_change(..., expect_head={p['head']}) to keep."
            return out
        res = await _run(go)
        act(project, "draft", "Trying " + ", ".join(res["changes"]), ctx, values=values)
        return res

    @mcp.tool(annotations=RW, meta=ALWAYS)
    async def commit_change(project: str, values: dict[str, float], note: str = "", expect_head: int | None = None,
                            provenance: dict[str, dict] | None = None, run: bool = True, ctx: Context = None) -> dict:
        """Save a change as a new revision (history is never rewritten). Pass expect_head from get_project/preview_change
        so a concurrent edit is refused instead of overwritten.
        provenance: {param: {"source": "measured"|"specified"|"calibrated"|"assumed", "sigma": mm, "instrument": str, "note": str}}.
        Use "measured" only for numbers the user measured and gave you. With run=True outputs are regenerated."""
        st = studio()
        def go():
            p = st.load(project)
            st.commit(p, values, note, _origin(ctx), provenance, expect_head=expect_head)
            return st.load(project)["head"]
        head = await _run(go)
        act(project, "commit", f"r{head:02d}: {note or ', '.join(f'{k}={v:g}' for k, v in values.items())}", ctx)
        res: dict[str, Any] = {"head": head}
        if run:
            jid = st.run(project)
            res["pipeline"] = job_digest(await _wait_job(st, jid, 45))
        res["project"] = await _run(digest, st, project)
        return res

    @mcp.tool(annotations=RW)
    async def run_pipeline(project: str, force: bool = False, wait_s: float = 45) -> dict:
        """Regenerate whatever is not current: solid -> STEP+STL -> checks -> slice. Cached outputs are reused unless
        force=True. Returns when done or after wait_s; then poll get_job."""
        st = studio()
        jid = st.run(project, None, force)
        job = await _wait_job(st, jid, max(1.0, min(wait_s, 300)))
        return job_digest(job) | ({"project": await _run(digest, st, project)} if job["state"] != "running" else
                                  {"next": f"get_job(project='{project}', job='{jid}')"})

    @mcp.tool(annotations=RO, meta=ALWAYS)
    async def get_job(project: str, job: str, wait_s: float = 30) -> dict:
        """Get a job's status: a pipeline job started by run_pipeline/commit_change; waits up to wait_s for it to finish."""
        st = studio()
        if job not in st.jobs:
            raise ToolError("Unknown job. Jobs are kept on disk under the data folder; check the id from the call that started it.")
        return job_digest(await _wait_job(st, job, max(0.0, min(wait_s, 300))))

    @mcp.tool(annotations=RO, structured_output=False, meta=ALWAYS)
    async def render(project: str, view: str = "iso", highlight: str | None = None, rev: int | None = None,
                     values: dict[str, float] | None = None, ctx: Context = None) -> list:
        """Render the part as an image. Look at the part. Returns a PNG rendered from the real kernel geometry, coloured by feature.
        view: iso, iso_back, front, back, left, right, top, bottom, "sheet" (four views at once), or for a design with
        several parts "assembled" (put together) and "exploded" (pulled apart along its explode offsets).
        highlight: a feature id to pick out. values: render an uncommitted candidate (same as preview_change)."""
        st = studio()
        def go():
            p = st.load(project)
            recipe = st.recipe(p, rev)
            feats = [{"id": f.id, "label": f.label} for f in recipe.features]
            if highlight and highlight not in [f["id"] for f in feats]:
                raise StudioError(f"Unknown feature “{highlight}”.", "Features: " + ", ".join(f["id"] for f in feats))
            # the picture's name first: a render made before needs no view (no kernel call at all)
            if values:
                draft = {**st.rev(p)["values"], **{k: float(x) for k, x in values.items()}}
                title, key = f"{p['name']} - r{p['head']:02d} + DRAFT (not saved)", "pv-" + H(st.rid(p), draft)
            else:
                n = rev or p["head"]
                title, key = f"{p['name']} - r{n:02d}", st.keys(p, n)["geometry"]
            cache = st.dir(p["id"]) / "artifacts" / "renders"
            cache.mkdir(parents=True, exist_ok=True)
            f = cache / f"{key}-{view}-{highlight or 'all'}-v{rendering.VERSION}.png"
            said = f.with_suffix(".caption.txt")
            if f.exists() and said.is_file():
                return f, said.read_text(encoding="utf-8")
            v = st.preview(p, values) if values else st.view(p, n)
            if view in rendering.POSES:
                try:
                    v = rendering.posed(v, view)
                except ValueError as e:
                    raise StudioError(str(e))
            views = ["iso", "front", "top", "right"] if view == "sheet" else ["iso"] if view in rendering.POSES else [view]
            if not f.exists():
                size = (640, 460) if view == "sheet" else (960, 680)
                try:
                    pngs = [rendering.render_png(v, feats, vw, highlight, size=size, title=title) for vw in views]
                except ValueError as e:
                    raise StudioError(str(e))
                f.write_bytes(pngs[0] if len(pngs) == 1 else rendering.contact_sheet(pngs))
            caption = (f"{title}. Rendered from the kernel tessellation ({v['triangles']} triangles), "
                       f"bounding box {' x '.join(f'{b - a:.1f}' for a, b in zip(*v['bbox']))} mm. File: {f}")
            try:
                said.write_text(caption, encoding="utf-8")
            except OSError:
                pass
            return f, caption
        f, caption = await _run(go)
        act(project, "look", f"Looking at the {view} view" + (f", {highlight}" if highlight else "")
            + (" of a draft" if values else ""), ctx, view=view, highlight=highlight, values=values)
        return [Image(path=f), caption]

    @mcp.tool(annotations=RO, structured_output=False)
    async def animate(project: str, kind: str = "turntable", from_rev: int | None = None, to_rev: int | None = None,
                      to_values: dict[str, float] | None = None, frames: int = 24, fmt: str = "gif") -> list:
        """Animate a design. Make motion from real geometry. kind="turntable" spins the head revision. kind="morph" builds every in-between
        design from from_rev (default: head) to to_rev or to_values, so you can show how a change transforms the part.
        Returns the file path and a still. fmt: gif or webp."""
        st = studio()
        def go():
            from . import animate as anim
            p = st.load(project)
            d = st.dir(project) / "artifacts" / "motion"
            if kind == "turntable":
                out = d / f"r{p['head']:02d}-turntable.{fmt}"
                info = anim.turntable(st, p, out, frames=max(12, min(frames, 72)))
            elif kind == "morph":
                a = st.rev(p, from_rev)["values"]
                if to_values:
                    b = {**a, **{k: float(v) for k, v in to_values.items()}}
                elif to_rev:
                    b = st.rev(p, to_rev)["values"]
                else:
                    raise StudioError("A morph needs to_rev or to_values.")
                out = d / f"morph-{H(a, b)[:8]}.{fmt}"
                try:
                    info = anim.morph(st, p, a, b, out, frames=max(8, min(frames, 48)), title=p["name"])
                except ValueError as e:
                    raise StudioError(str(e))
            else:
                raise StudioError("kind is turntable or morph.")
            from PIL import Image as PImage
            still = out.with_suffix(".png")
            im = PImage.open(out)
            im.seek(min(im.n_frames - 1, im.n_frames // 3))
            im.convert("RGB").save(still)
            return info, still
        info, still = await _run(go)
        return [Image(path=still), f"{info['kind']}: {info['file']} ({info['frames']} frames, {info['bytes'] // 1024} kB)"
                + (f". Frames that did not build: {info['skipped']}" if info.get("skipped") else "")]

    @mcp.tool(annotations=RO)
    async def compare_revisions(project: str, a: int, b: int) -> dict:
        """Compare two revisions. What changed between two revisions: parameters, features, interfaces, stability, fit."""
        st = studio()
        def go():
            p = st.load(project)
            cand = st.head_summary(p, b)
            return {"a": a, "b": b, "note_a": st.rev(p, a)["note"], "note_b": st.rev(p, b)["note"],
                    **impact_digest(st.impact(p, st.rev(p, b)["values"], cand, base_rev=a))}
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def geometry_diff(project: str, a: int, b: int | None = None) -> dict:
        """Diff the geometry of two revisions. What changed in the solid between revision a and b (default the head): material added (b minus a) and removed
        (a minus b), each with its volume in mm³, number of separate regions and bounding box, computed with booleans on
        the B-rep. Also writes a picture (added green, removed red, the rest grey); look at it with the returned path."""
        st = studio()
        def go():
            from . import geomdiff
            p = st.load(project)
            d = geomdiff.compute(st, p, a, b)
            return {**d, "png": str(geomdiff.png_path(st, p, d))}
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def add_text(project: str, text: str, at: list[float], normal: list[float], height: float = 6.0,
                       depth: float = 0.6, sunk: bool = False, up: list[float] | None = None,
                       expect_head: int | None = None) -> dict:
        """Put raised (or, with sunk, cut-in) lettering on a flat face of a Python design, as a real feature of its source:
        a new revision whose build adds a stage text_N with Form Studio's bundled font. at: a point on the face and
        normal: its outward normal, both in design millimetres (analyze_selection on a face returns them). height is the
        cap height, depth how far the letters stand out or sink in. Returns the new head, the marks and printability
        (stroke width against the nozzle, computed on the glyphs). Remove one with remove_text."""
        st = studio()
        def go():
            from . import engrave
            p = st.load(project)
            out = engrave.add(st, p, text, at, normal, height, depth, sunk, up, expect_head, origin="agent")
            out["printability"] = engrave.printability(text, height, depth, sunk, st.slicer_info(p=p).get("nozzle_mm"))
            return out
        return await _run(go)

    @mcp.tool(annotations=RW, structured_output=False)
    async def add_feature(project: str, kind: str, at: list[float] | None = None, normal: list[float] | None = None,
                          size: str = "M3",
                          hole: str = "tapped", height: float | None = None, outer_d: float | None = None,
                          hole_d: float | None = None, hole_depth: float | None = None, length: float | None = None,
                          thickness: float | None = None, width: float | None = None, lip: float | None = None,
                          lip_height: float | None = None, up: list[float] | None = None, allow_strain: float | None = None,
                          expect_head: int | None = None, feature: str = "", code: str = "", label: str = "",
                          role: str = "structure", after: str = "", partial: bool = False, ctx: Context = None):
        """Add a feature to a Python design as a new revision. kind="code" (a FeatureDesign): feature = its id, code = one
        method `def <feature>(self, v, body): return body_after`, label/role for the feature list, after = the feature
        it goes after (default: last). Only it is built: the features before it load from their checkpoints, and the
        stage is shown in Form Studio as it builds. Returns the head, build_log (per feature: built, checkpoint or
        skipped, with seconds, solids and volume change) and a six-view sheet and a section: look. A feature that adds
        parts says so in the code (`@feature("Lenses", parts=2)`); while parts are still to come the revision is
        saved as partial (release blocked). If it fails, no revision is made and the diagnosis comes back
        (partial=True saves it left out, release blocked).
        Standard features: on a flat face of a Python design, written into its source as a feature block and built
        in the kernel as a new revision. kind="boss": a screw boss (size M2..M5; hole tapped = ISO tap drill, clearance =
        ISO 273, insert = a typical heat-set insert hole; height, outer_d, hole_d, hole_depth in mm). kind="snap_hook":
        a cantilever snap-fit hook (length, thickness, width, lip = undercut, lip_height; up = the lip's direction).
        at / normal: a point on the face and its outward normal (analyze_selection gives them). Returns the new head, the
        features and check rows: boss wall vs the nozzle; hook strain 1.5·t·y/L² vs allow_strain (a rule of thumb when
        not given). Remove one with remove_feature."""
        st = studio()
        if kind == "code":
            if not feature or not code:
                raise ToolError('kind="code" needs feature (its id) and code (one method).')

            draft = "draft-" + uuid.uuid4().hex[:10]
            act(project, "design", f"Building feature {feature}", ctx, draft=draft)

            def go_code():
                from . import featureprog
                p = featureprog.add_code_feature(st, st.load(project), feature, code, label, role, after,
                                                 _origin(ctx), expect_head, partial, draft)
                head = st.rev(p)
                return {"head": p["head"], "feature": feature, "build_log": head.get("build_log", []),
                        **({"partial": head["partial"]} if head.get("partial") else {})}
            out = await _run(go_code)
            act(project, "commit", f"r{out['head']:02d}: added feature {feature}"
                + (" (partial)" if out.get("partial") else ""), ctx, draft=draft)
            if out.get("partial"):
                out["next"] = f"Saved as a partial design: {_partial_line(out['partial'])}."
            rf = _refine_after(st, project, ctx)
            if rf:
                out["refinement"] = rf
            out["project"] = await _run(digest, st, project)
            return await _with_views(st, project, out)
        if at is None or normal is None:
            raise ToolError(f'kind="{kind}" needs at and normal (a point on a flat face and its outward normal).')
        o = {k: v for k, v in dict(size=size, hole=hole, height=height, outer_d=outer_d, hole_d=hole_d, hole_depth=hole_depth,
                                   length=length, thickness=thickness, width=width, lip=lip, lip_height=lip_height, up=up).items()
             if v is not None}
        def go():
            from . import feature_helpers as fh
            p = st.load(project)
            out = fh.add(st, p, kind, at, normal, expect_head, "agent", **o)
            out["checks"] = fh.checks(out["features"][-1], st.slicer_info(p=p).get("nozzle_mm"), allow_strain)
            return out
        out = await _run(go)
        rf = _refine_after(st, project, ctx)
        if rf and isinstance(out, dict):
            out["refinement"] = rf
        return out

    @mcp.tool(annotations=RW)
    async def remove_feature(project: str, feature_id: str, expect_head: int | None = None) -> dict:
        """Remove a feature as a new revision: a standard feature added with add_feature ("boss_1", "hook_1"), or any
        feature of a FeatureDesign (its method goes; the features before it load from their checkpoints)."""
        st = studio()
        def go():
            from . import feature_helpers as fh
            return fh.remove(st, st.load(project), feature_id, expect_head, origin="agent")
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def compare_printers(project: str, limit: int = 8, printers: list[str] | None = None) -> dict:
        """Slice the head revision's exported model for real on every printer set up in every installed slicer (the
        selected printers first, up to limit; or only the printer ids given, from list_printers) and return each one's
        simulated print time, filament grams and cost from the user's prices, with the fastest, least filament and
        cheapest. A printer whose bed is too small is reported without slicing; a failed slice says why. Each slice is a
        simulation, not a print. Slices are cached per model and presets."""
        st = studio()
        def go():
            from . import slicecompare
            return slicecompare.compare(st, st.load(project), limit, printers)
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def make_lighter(project: str, builds: int = 4) -> dict:
        """Make it lighter: search changes that reduce mass while every check that passes now still passes. Tries the
        design's wall, thickness and lightening-pocket parameters (never interface parameters; a candidate that moves an
        interface dimension is dropped), building a ladder of values in the kernel, then takes the lightest few (builds)
        through the real checks and slicer. Also slices lower infill and one wall fewer over the slicer's process. Returns
        the baseline and candidates (id, changes and/or settings, computed mass_g, slicer slice_g, every check before and
        after) and what was rejected and why. Nothing is committed: keep one with apply_lighter."""
        st = studio()
        def go():
            from . import lighten
            return lighten.search(st, st.load(project), builds=builds)
        act(project, "search", "Searching for a lighter design that keeps every check passing")
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def apply_lighter(project: str, changes: dict[str, float] | None = None, settings: dict[str, float] | None = None,
                            expect_head: int | None = None) -> dict:
        """Keep a make_lighter candidate: changes (parameter values) are committed as a new revision; settings
        ({"infill": percent, "walls": count}) become this design's print settings over the slicer's process. Pass the
        candidate's own changes and settings exactly. Then run_pipeline."""
        st = studio()
        def go():
            from . import lighten
            return lighten.apply_values(st, st.load(project), changes, settings, expect_head, origin="agent")
        out = await _run(go)
        if changes:
            act(project, "commit", f"r{out['head']:02d}: lighter")
        return out

    @mcp.tool(annotations=RO)
    async def replace_part_guide() -> dict:
        """Guide a replacement part from a photo. How to design a replacement for a broken part from the person's photo: find the scale from a reference
        object in the photo and estimate sizes (assumed), ask_measurement for each fit-critical size (at most three),
        then create_design with the measured values and strengthen where it broke. In Form Studio this flow starts from
        Home › Replace a broken part."""
        from . import replace
        return replace.guide()

    @mcp.tool(annotations=RO)
    async def turntable(project: str, fmt: str = "webp", frames: int = 36, elevation: float = 24) -> list:
        """Render a turntable of the head revision from the kernel's mesh. fmt: webp or gif (one animated file), png (a
        numbered PNG sequence, zipped), mp4 (H.264; needs ffmpeg installed, refused with the reason otherwise). Returns a
        still and the file path."""
        st = studio()
        def go():
            from . import animate as anim
            return anim.export(st, st.load(project), fmt, frames, elevation)
        info = await _run(go)
        return [Image(path=info["still"]), f"turntable ({info['fmt']}): {info['file']} ({info['frames']} frames, "
                f"{info['seconds']} s at {info['fps']} fps, {info['bytes'] // 1024} kB)"]

    @mcp.tool(annotations=RW)
    async def remove_text(project: str, mark_id: str, expect_head: int | None = None) -> dict:
        """Remove lettering added with add_text (mark_id like "text_1"; get_design_source shows the block). A new revision."""
        st = studio()
        def go():
            from . import engrave
            return engrave.remove(st, st.load(project), mark_id, expect_head, origin="agent")
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def assembly_instructions(project: str, rev: int | None = None) -> dict:
        """Write assembly instructions. Assembly instructions as a PDF from the design's assembly declaration: a parts page with computed volumes, then
        one page per part going on (in the declaration's parent order, at its explode offset, with arrows). Step text is
        the part's note, or what the declaration says. Returns the PDF path, page images and the steps. A design without
        an assembly() has none."""
        st = studio()
        def go():
            from . import instructions
            p = st.load(project)
            out = instructions.build(st, p, rev)
            d = Path(out["pdf_path"]).parent
            return {**out, "page_images": [str(d / x) for x in out["pages"]]}
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def checkout_revision(project: str, rev: int) -> dict:
        """Make an earlier revision the head again (nothing is deleted). Outputs for it are reused if still cached."""
        st = studio()
        await _run(lambda: st.checkout(st.load(project), rev))
        jid = st.run(project)
        await _wait_job(st, jid, 45)
        return await _run(digest, st, project)

    @mcp.tool(annotations=RW)
    async def set_print_setup(project: str, orientation: str | None = None, fit_gap_min_mm: float | None = None,
                              fit_gap_max_mm: float | None = None, auto_slice: bool | None = None,
                              design_only: bool | None = None, material: str | None = None,
                              purpose: str | None = None, process: str | None = None) -> dict:
        """Set the print setup. Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from
        suggest_orientation), the acceptable total fit gap
        window, and whether the pipeline slices automatically. The checks include an orientation comparison table.
        design_only=True: the design is not sliced (checks, exports and release still work; the release says it was
        not sliced). material: PLA, PETG, ABS, ASA, TPU, PA, PC, ... for the whole design ("" clears): the slice uses the
        printer's filament preset for it and the checks add notes for that material. Ask the user before changing either.
        purpose: "print" or "model" (just a 3D model, never sliced); process: for a model, how it will be made.
        With 3D printing off only purpose="model" and process are accepted."""
        st = studio()
        if not _printing_on() and (any(v is not None for v in (orientation, fit_gap_min_mm, fit_gap_max_mm, auto_slice,
                                                                design_only, material)) or (purpose and purpose != "model")):
            raise ToolError(PRINTING_OFF)
        body: dict[str, Any] = {}
        if orientation is not None:
            body["orientation"] = orientation
        if fit_gap_min_mm is not None or fit_gap_max_mm is not None:
            cur = (await _run(st.load, project))["fit"]
            body["fit"] = {"gap_min": fit_gap_min_mm if fit_gap_min_mm is not None else cur["gap_min"],
                           "gap_max": fit_gap_max_mm if fit_gap_max_mm is not None else cur["gap_max"]}
        if auto_slice is not None:
            body["auto_slice"] = auto_slice
        if design_only is not None:
            body["design_only"] = design_only
        if material is not None:
            body["material"] = material
        if purpose is not None:
            body["purpose"] = purpose
        if process is not None:
            body["process"] = process
        await _run(lambda: st.settings(st.load(project), body))
        jid = st.run(project)
        await _wait_job(st, jid, 45)
        return await _run(digest, st, project)

    @mcp.tool(annotations=RO)
    async def explore_alternatives(project: str, axes: list[dict], weights: dict[str, float] | None = None) -> dict:
        """Build a small grid of real variants (1-2 parameters, up to 5 values each) and rank them.
        axes: [{"key": "depth", "values": [78, 85, 92]}]. weights over objectives: material, stability, fit, footprint.
        Nothing is saved; commit the one you choose."""
        st = studio()
        def go():
            p = st.load(project)
            try:
                res = advisor.alternatives(st, p, axes, weights or {})
            except (ValueError, KeyError) as e:
                raise StudioError(str(e))
            return res
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def optimize(project: str, vary: list[dict], objective: dict[str, str], constraints: list[str] | None = None,
                       budget: int = 40, ctx: Context = None) -> dict:
        """Optimize a design. Goal seek: search parameter ranges for the best design that meets constraints. Every candidate is built by the kernel.
        vary: [{"key": "arm_t", "min": 4, "max": 20}] (1-4 parameters).
        objective: {"minimize": "solid_mass_g"} or {"maximize": "statics.safety_factor"}.
        constraints: ["statics.safety_factor >= 3", "overhang_mm2 <= 1", "derived.usable_depth >= 30", "fit_yield >= 0.9"].
        Metrics: volume_cm3, solid_mass_g, width, depth, height, overhang_mm2, contact_mm2, min_wall_mm, fit_yield,
        derived.<key>, statics.<key>. Nothing is saved: preview_change/render the best, then commit_change."""
        st = studio()
        def go():
            from . import optimize as opt
            p = st.load(project)
            try:
                return opt.run(st, p, vary, objective, constraints or [], budget)
            except (opt.OptimizeError, KeyError) as e:
                raise StudioError(str(e).strip("'"), "Check parameter keys with describe_recipe.")
        act(project, "search", f"Searching: {next(iter(objective))} {next(iter(objective.values()))}"
            + (f" with {', '.join(constraints)}" if constraints else ""), ctx)
        res = await _run(go)
        if res.get("best"):
            act(project, "draft", f"Best of {res['evaluated']} builds", ctx, values=res["best"]["values"])
        return res

    @mcp.tool(annotations=RW)
    async def slice_test_piece(project: str) -> dict:
        """Cut a thin ring through the fit interface of this revision and slice it, so a cheap test print can check the fit
        before the whole part. Returns its STL path and simulated time and material."""
        _need_printing()
        st = studio()
        def go():
            p = st.load(project)
            info = st.side_slice(p, "test_piece")
            d = st.dir(p["id"]) / "artifacts" / "side" / info["key"]
            return {"piece": info["piece"]["label"], "stl": str(d / info["stl"]), "gcode": str(d / info["gcode"]),
                    "time_min": round(info["time_s"] / 60) if info.get("time_s") is not None else None, "filament_g": info["filament_g"], "evidence": "simulated slice"}
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def record_physical_result(project: str, kind: str, result: str | None = None,
                                     widths: list[dict] | None = None, source: str = "part", note: str = "") -> dict:
        """Record what the USER observed after a real print. Never call this with values the user did not report.
        kind="fit": result is too_tight | good | too_loose for this revision.
        kind="widths": measured pairs [{"nominal": mm, "measured": mm}] from a coupon (source="coupon") or this part
        (source="part"); they calibrate this printer profile for every future design."""
        st = studio()
        body = {"kind": kind, "note": note}
        if kind == "fit":
            body["result"] = result
        elif kind == "widths":
            body.update({"pairs": widths or [], "source": source})
        def go():
            p = st.load(project)
            try:
                rec = st.add_evidence(p, body)
            except ValueError as e:
                raise StudioError(str(e))
            return rec
        rec = await _run(go)
        jid = st.run(project)
        await _wait_job(st, jid, 30)
        return {"recorded": rec, "project": await _run(digest, st, project)}

    @mcp.tool(annotations=RO)
    async def request_release(project: str, open_browser: bool = False) -> dict:
        """Check whether the head revision can be released and hand the decision to the user.
        Agents cannot approve: approval happens in Form Studio, where the user reviews checks and acknowledges warnings."""
        st = studio()
        def go():
            p = st.load(project)
            g, ap = st.gate(p), st.approval_state(p)
            return p, g, ap
        p, g, ap = await _run(go)
        act(project, "release", "Ready for your approval" if g["ready"] else "Not ready: " + "; ".join(g["reasons"])[:200], None)
        url = _bench(f"#p={project}&tab=release")
        if open_browser and url:
            webbrowser.open(url)
        out = {"revision": p["head"], "ready": g["ready"], "blocking": g["reasons"],
               "user_must_acknowledge": [f"{w['label']}: {w['value']}" for w in g["warnings"]],
               "evidence": g["evidence_level"].replace(" · ", "; "), "approval": ap}
        if url:
            out["approve_here"] = url
            out["tell_the_user"] = ("Open the bench link, review the checks and warnings, then press Approve. "
                                    "Form Studio writes a release folder with STEP, STL, 3MF, G-code, MANIFEST.json and REPORT.md.")
        else:
            out["tell_the_user"] = "Start the bench (`form serve`) to review and approve."
        return out

    @mcp.tool(annotations=RO)
    async def verify_release(project: str, release: str) -> dict:
        """Re-hash every file of a release against its manifest and say whether it still matches the head revision."""
        st = studio()
        return await _run(lambda: st.verify_release(st.load(project), release))

    OPEN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @mcp.tool(annotations=OPEN)
    async def open_in(project: str, what: str = "3mf", app: str = "") -> dict:
        """Open a current output in the user's own software: what = step | stl | 3mf | gcode | folder.
        app overrides studio.toml [apps] (e.g. "BambuStudio"); app="freecad" finds FreeCAD. Uses the system's open command;
        nothing is uploaded."""
        st = studio()
        from .cad_bridges import open_output
        return await _run(open_output, st, project, what, app)

    @mcp.tool(annotations=OPEN)
    async def open_in_slicer(project: str, printer: str = "", open_app: bool = True, ctx: Context = None) -> dict:
        """Open the design in the user's slicer, sliced with settings chosen for this part on this printer: orientation
        (the orientation finder's first choice), layer height, walls, top/bottom layers, infill and pattern, supports
        (only where overhangs need them), brim, seam, filament for the design's material and the speed profile (one of
        the printer's own process presets). Each decision has a one-line reason labelled "computed" or "heuristic".
        It starts from the slicer's own preset and overrides only those keys, slices for real (time and grams are the
        slicer's simulation), writes a project 3MF with the plate, the oriented part, the settings and the filament,
        checks the settings are in that file, and opens it in the slicer's app. printer: an id from list_printers
        (default: the design's printer). open_app=false writes the file without opening it. Nothing is printed or sent."""
        _need_printing()
        st = studio()
        act(project, "look", "Choosing print settings and opening the design in the slicer", ctx)
        def go():
            from . import slicer_open
            return slicer_open.run(st, st.load(project), printer or None, open_app=open_app)
        return await _run(go)

    @mcp.tool(annotations=OPEN)
    async def open_bench(project: str | None = None, open_browser: bool = True) -> dict:
        """Open the bench web page. The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases."""
        url = _bench(f"#p={project}" if project else "")
        if not url:
            raise ToolError("The bench is not running in this server (started with --no-bench, or no free port).")
        if open_browser:
            webbrowser.open(url)
        return {"url": url, "opened": open_browser}

    @mcp.tool(annotations=RO)
    async def brief_presets(preset: str = "") -> dict:
        """List brief presets. Intake guidance for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure,
        car accessory): the questions worth asking the person, environment defaults (temperature, humidity, UV, load), a
        material to start from and the checks to plan for. Use it while gathering requirements; the defaults are
        assumptions to confirm with the person, never measurements."""
        from . import presets as pr
        if not preset:
            return {"presets": [{k: p[k] for k in ("id", "title", "summary")} for p in pr.all_presets()]}
        try:
            return pr.get(preset)
        except KeyError:
            raise ToolError(f"Unknown preset “{preset}”. Known: {', '.join(p['id'] for p in pr.all_presets())}.") from None

    # ---- bridges to other CAD tools -----------------------------------------------------------------------------

    @mcp.tool(annotations=RW)
    async def import_reference(project: str, path: str, name: str | None = None, ctx: Context = None) -> dict:
        """Import an existing part (STEP or STL, e.g. a Raspberry Pi 5 STEP from the manufacturer) into a project's
        references. FORM copies it, measures it in the kernel (bounding box, volume: computed) and draws it in the 3D
        view as a blueprint companion, in its own coordinates. A Python design can then read it with
        self.reference("<name>") for clearance cuts. path: absolute local path. Re-importing a name replaces it."""
        st = studio()
        rec = await _run(lambda: st.import_reference(st.load(project), Path(path).expanduser(), name))
        act(project, "look", f"Imported reference part {rec['file']}", ctx)
        size = [round(b - a, 2) for a, b in zip(*rec["bbox"])]
        return {"reference": rec["file"], "format": rec["format"], "bbox_mm": rec["bbox"], "size_mm": size,
                "volume_mm3": round(rec["volume_mm3"], 1) if rec.get("volume_mm3") is not None else None,
                "evidence": "computed (read by Form Studio's kernel from the file)",
                "use_in_design": f'self.reference("{rec["file"]}") returns it as a build123d shape in the same coordinates.',
                "note": "The part is drawn where its file puts it. Model your design around those coordinates, or move "
                        "the reference inside your design code (Pos(...) * self.reference(...))."}

    @mcp.tool(annotations=RW)
    async def reconstruct(project_or_file: str = "", tolerance: float = 0.02, layer: int = 2, name: str | None = None,
                          reference: str | None = None, files: list[str] | None = None,
                          references: list[str] | None = None, ctx: Context = None) -> dict:
        """Turn a mesh (STL, OBJ or 3MF) into editable CAD as a new design. project_or_file: an absolute path to the
        mesh, or a project id whose imported mesh reference to use (reference: which one; default the first mesh).
        Several meshes of ONE product (a base, a slider and a lid): pass them all at once, as files=[absolute paths]
        (or project_or_file=<project id> with references=[names]); they become ONE design with one part per mesh, in
        the positions the files give (parts that fail are listed in "failed", the others are kept). Never call this
        once per part: that makes unrelated designs.
        Layer 0 is always built: the mesh as an exact solid (Hausdorff at float precision). Layer 1 (beta) replaces
        facets with planes, cylinders, cones, spheres and tori where they fit within `tolerance` mm, and smooth
        organic regions with fitted B-spline surfaces ("freeform"); the rest stay frozen facets. Layer 2 (beta)
        writes a build123d recipe with Params as a feature tree: a base (extrusion stack with steps and pockets, a
        revolution, or the reconstructed solid itself) then fillets, chamfers and holes (counterbores, countersinks,
        holes on any axis, snapped to standard sizes, patterns); a spur gear becomes a parametric gear (teeth, module,
        pressure angle). A feature that does not verify stays in the base and is reported; the recipe is used only
        if its rebuild is within the limit. Before any of these, the program route reads the part as sketches
        extruded and lofted between levels, and keeps what does not read as a sketch as the mesh's own slices.
        Returns the new project and the verification, led by summary.headline: editable_pct (the share of Params
        that are real dimensions, lengths, diameters, radii, angles and levels rather than positions of sketch
        corners, and that move 0.5 mm with the design still building) and the two-sided Hausdorff distance to
        the mesh; then feature_area_pct (the share of the surface parametric features make), the volume delta and
        the parametric, freeform and frozen area. Tell the person the editable share first and never call a result
        with 0% editable "editable". Values are computed from the mesh; nothing is decimated and every repair is
        listed. Large meshes take minutes."""
        st = studio()
        said = [0.0]

        def progress(d):
            # the activity log is what the app and every agent read: a line at most every 3 s, so a long run is not silent
            if time.time() - said[0] >= 3.0 and d.get("text"):
                said[0] = time.time()
                st.activity(None, "reconstruct", f"Reconstructing: {d.get('text')}"[:300], by="engine",
                            fraction=round(float(d.get("fraction", 0)), 3), part=d.get("part"))
            if ctx is not None:
                try:
                    anyio.from_thread.run(ctx.report_progress, float(d.get("fraction", 0)), 1.0, str(d.get("text", "")))
                except Exception:
                    pass

        def go():
            kw = {"tolerance": tolerance, "layer": layer, "on_progress": progress}
            if name:
                kw["name"] = name
            from . import multipart
            many = [str(f) for f in files or [] if str(f).strip()]
            if references:
                p = st.load(project_or_file)
                d = st.dir(p["id"]) / "references"
                known = {r["file"] for r in st.references(p)}
                bad = [r for r in references if r not in known]
                if bad:
                    raise StudioError(f"No reference part named {', '.join(bad)} in this project.",
                                      "Import the meshes first (import_reference); names as get_project lists them.")
                many += [str(d / r) for r in references]
            elif project_or_file and Path(project_or_file).expanduser().suffix and many:
                many.insert(0, project_or_file)
            if len(many) >= 2:
                return multipart.reconstruct_parts(st, many, purpose=_purpose(None), **kw)
            if len(many) == 1:
                return st.reconstruct(Path(many[0]).expanduser(), **kw)
            if not project_or_file:
                raise StudioError("Give the mesh to reconstruct.", "project_or_file=<absolute path>, or files=[paths] "
                                  "for the parts of one product.")
            src = Path(project_or_file).expanduser()
            if src.suffix and src.is_file():
                return st.reconstruct(src, **kw)
            p = st.load(project_or_file)
            meshes = [r["file"] for r in st.references(p) if r.get("format") != "step"]
            if not meshes:
                raise StudioError("This project has no imported mesh.", "Import an STL, OBJ or 3MF first (import_reference), "
                                  "or pass the path of the mesh file.")
            return st.reconstruct_reference(p, reference or meshes[0], **kw)
        out = await _run(go)
        if "parts" in out:
            act(out["project"], "design", f"Reconstructed {len(out['parts'])} meshes as one design with "
                                          f"{len(out['parts'])} parts", ctx)
        else:
            sm = out["summary"]
            act(out["project"], "design", f"Reconstructed a mesh as CAD: {sm.get('editable_pct') or 0:g}% editable, "
                f"{sm.get('hausdorff_mm') or 0:.4g} mm from the mesh (Layer {sm['layer']})", ctx)
        _made(out["project"], "reconstruct")
        return {**out, "evidence": "computed (Form Studio's kernel compared the result with the mesh)",
                "next": "get_project to read the design; get_design_source to edit the recipe or add features."}

    # ---- reference parts an agent rebuilds as clean CAD (form/remodel) ------------------------------------------
    @mcp.tool(annotations=RO, structured_output=False)
    async def analyze_reference(project: str, reference: str, tolerance: float = 0.05, levels: dict | None = None,
                                ctx: Context = None) -> list:
        """Read an imported mesh (STL, OBJ, 3MF) like an engineer before modelling it again as clean CAD
        (design_guide topic "reference_parts"). Returns pictures of dimensioned sections in the three principal
        planes at several levels (look at them), and JSON: principal axes, levels of the flat faces (steps), section
        loops with sizes and vector outlines, and features with sizes: holes, bosses, openings (pockets, slots,
        cutouts, with count and pitch when repeated), plates, walls, ribs, rails and grooves, ramps with angles,
        draft, fillets and chamfers with radii and widths, round edges, detail areas (text, embossing, knurls),
        symmetry and wall thicknesses. reference: the mesh's file name in the project (import_reference first).
        tolerance (mm): how far a surface may be from the mesh to count as a plane, cylinder... levels: extra section
        levels per axis, e.g. {"z": [3.2, 6.5], "y": [-40]}. Evidence: computed on the mesh as given. Never embed
        the mesh as the design: plan features from this, write build123d with Params, then compare_to_reference."""
        st = studio()
        from .remodel import project as rp
        out = await _run(lambda: rp.analyze_reference(st, st.load(project), reference, tolerance, levels))
        act(project, "look", f"Analysing the reference part {out.get('reference', reference)}", ctx)
        imgs = [Image(path=i["path"]) for i in out.get("images", [])]
        return imgs + [json.dumps(out, default=str, ensure_ascii=False)]

    @mcp.tool(annotations=RO)
    async def analyze_assembly(project: str, references: list[str], fixed: str | None = None, near: float = 1.0,
                               ctx: Context = None) -> dict:
        """Analyze an assembly of meshes. How several imported meshes go together and move, measured in the positions they were given. references:
        the mesh files (the part that stays still first, or name it in fixed). Returns mating surfaces (facing,
        area, gap, where), clearances per pair, each part's travel against the fixed one along +/-X, Y, Z and about
        the axes of round faces they share (free distance before touching, distance past bumps such as detents and
        flexing arms, the obstacles met and where), the joints this implies (slide axis and range, hinge axis,
        origin and range) and couplings between moving parts (a slide meshing with a part that turns: rack and gear
        or cam with the ratio; a slide on a leaning face: a ramp with the lift per mm), plus a one-paragraph summary.
        Rigid parts: it does not know springs or gravity; say so. near (mm): gaps up to this count as mating."""
        st = studio()
        from .remodel import project as rp
        out = await _run(lambda: rp.analyze_assembly(st, st.load(project), references, fixed, near))
        act(project, "look", "Working out how the reference parts move together", ctx)
        return out

    @mcp.tool(annotations=RO, structured_output=False)
    async def compare_to_reference(project: str, reference: str, part: str | None = None, tolerance: float = 0.1,
                                   rev: int | None = None, ctx: Context = None) -> list:
        """Compare the design (or one part of its assembly) with an imported mesh, to iterate a remodel until it is
        within tolerance (default 0.1 mm for a remodel; say which you used). Returns a picture (the design coloured
        by its distance to the mesh, and the mesh by its distance to the design) and JSON: two-sided Hausdorff, mean,
        99th percentile, the worst regions by where they are (words and coordinates, the nearest feature of the
        reference analysis, and whether the design has extra or missing material there) and per-feature
        differences (the design's diameter or radius next to the mesh's). part: a part id or label of the design's
        assembly, so a multi-part design is compared part by part. Run analyze_reference first for feature names.
        Evidence: computed on the design's tessellation against the mesh."""
        st = studio()
        from .remodel import project as rp
        out = await _run(lambda: rp.compare_to_reference(st, st.load(project), reference, part, tolerance, rev))
        act(project, "look", f"Comparing the design with {out['reference']}" + (f" ({part})" if part else ""), ctx)
        return [Image(path=out["image"]), json.dumps(out, default=str, ensure_ascii=False)]

    @mcp.tool(annotations=RO)
    async def reference_residual(project: str, reference: str, part: str | None = None, rev: int | None = None,
                                 voxel: float | None = None, axis: str | list[float] | None = None,
                                 center: list[float] | None = None, ctx: Context = None) -> dict:
        """List what remains of a remodel. What is left to build in a remodel: the volume difference between the design (or one part) and an imported
        mesh as a named work list. missing: bodies the mesh has and the design lacks (add them); extra: bodies the
        design has and the mesh lacks (cut them). Each body has its volume, centre, principal axis, size, shape
        (cylinder with diameter and length along an axis, box, or body), where it is in words, and its angle and
        radius about an axis, so bodies around a circle read as one polar pattern at equal angles. patterns groups
        alike bodies (polar: count, pitch, radius, start angle; linear: pitch and direction; grid: pitches).
        work_list: one line per feature to build, patterns first. residual_pct: missing plus extra volume as a share
        of the mesh's volume, the number to drive down. axis: "x", "y", "z" (default) or a direction; center: a point
        on it (default the mesh's centre of volume). voxel (mm): grid size (default about 1/240 of the part).
        Build one item, run this again, keep the change only if residual_pct drops (design_guide topic
        "reference_parts"). Evidence: computed (voxels; manifold3d's exact boolean for volumes when installed)."""
        st = studio()
        from .remodel import residual as rr
        out = await _run(lambda: rr.reference_residual(st, st.load(project), reference, part, rev, voxel, axis, center))
        act(project, "look", f"Listing what is left between the design and {out['reference']}", ctx)
        return out

    @mcp.tool(annotations=RW)
    async def fit_params(project: str, reference: str, params: list[str] | None = None, part: str | None = None,
                         max_change: float = 2.0, commit: bool = True, expect_head: int | None = None,
                         max_builds: int = 60, budget_s: float = 120.0, ctx: Context = None) -> dict:
        """Tune the design's declared Params so it lies closer to an imported mesh: bounded least squares over those
        Params only (each inside its own min and max and at most max_change mm from its value), every evaluation a
        real build. params: which (default every Param in mm, at most 8). The result is kept, as a new revision with
        provenance "mesh", only if the mean distance drops and the largest does not grow; otherwise nothing changes
        (kept: false), so it never makes the deviation worse. commit=false reports the fitted values without saving.
        It cannot add a missing feature: use reference_residual for what is missing or extra, then this for sizes,
        then compare_to_reference for the tolerance. budget_s (default 120, 1 to 3600): the whole fit's time; when
        it is up the best values found so far are used (stopped says why it ended). Evidence: computed on the
        design's tessellation."""
        st = studio()
        from .remodel import fitparams as fp
        if not (1 <= int(max_builds) <= 200):
            raise ToolError("max_builds: between 1 and 200.")
        if not (1 <= float(budget_s) <= 3600):
            raise ToolError("budget_s: between 1 and 3600 seconds.")
        said = [0.0]

        def progress(d):
            if time.time() - said[0] >= 3.0:            # the activity log: a line at most every 3 s
                said[0] = time.time()
                st.activity(project, "look", d["text"][:300], by="engine", fraction=d.get("fraction"))
            if ctx is not None:
                try:
                    anyio.from_thread.run(ctx.report_progress, float(d.get("fraction", 0)), 1.0, d["text"])
                except Exception:
                    pass
        out = await _run(lambda: fp.fit_design(st, st.load(project), reference, params, part, max_change, commit,
                                               expect_head, int(max_builds), float(budget_s), progress))
        act(project, "commit" if out.get("committed") else "look",
            f"Fitted {', '.join(out['params'])} to {out['reference']}" if out.get("committed")
            else f"Fitting the Params to {out['reference']}: no gain, nothing changed", ctx)
        return out

    @mcp.tool(annotations=RO)
    async def freecad_macro(project: str) -> dict:
        """Write a FreeCAD macro (.FCMacro) next to the current STEP export. Run it in FreeCAD to rebuild the part
        from the STEP (hash-checked) with a spreadsheet of FORM's parameters and their provenance. Not for mesh designs."""
        st = studio()
        def go():
            p = st.load(project)
            fname, text = st.freecad_macro(p)
            out = st.apath(p, "exports", st.keys(p)["exports"]) / fname
            out.write_text(text, encoding="utf-8")
            return {"macro": str(out), "step": str(out.with_name(st.read(p, "exports", st.keys(p)["exports"])["files"]["step"]["name"])),
                    "note": "The spreadsheet records values; the STEP is a frozen solid. Edit the design in Form Studio and export again."}
        return await _run(go)

    # ---- analysis on the model (form/analysis.py): maps, measuring, print orientation -------------
    @mcp.tool(annotations=RO, structured_output=False)
    async def analyze(project: str, map: str = "thickness", view: str = "iso", rev: int | None = None, ctx: Context = None) -> list:
        """Analyze the part as a map. An analysis map of the part, computed from the real geometry: a picture with its legend, and the statistics.
        map: thickness (opposing-wall distance by ray, the same ray as the Thinnest-wall check; colours follow the nozzle),
        overhang (angle past vertical in the print orientation; plate contact and bridged ceilings are separate classes),
        section (area of each layer's slice by height, with the weakest neck: computed geometry, NOT a strength analysis),
        features (walls and gaps under one nozzle width, holes too small to print true).
        Every result is `computed` on the stated tessellation and says what it does not tell you; repeat that caveat."""
        st = studio()
        from . import analysis
        def go():
            p = st.load(project)
            r = analysis.run_map(st, p, map, rev)
            cache = st.dir(p["id"]) / "artifacts" / "analysis"
            f = cache / f"{map}-{st.keys(p, r['rev'])['geometry']}-{p['orientation'].replace(':', '_').replace(',', '_')}-{view}-v{analysis.ANALYSIS_VERSION}.png"
            if not f.exists():
                try:
                    f.write_bytes(analysis.render_map_png(r, f"{p['name']} - r{r['rev']:02d}", view, edges=st.view(p, r["rev"]).get("edges")))
                except ValueError as e:
                    raise StudioError(str(e))
            return f, analysis.digest(r)
        f, d = await _run(go)
        act(project, "look", f"Looking at the {d['label'].lower()} map", ctx, view=view if view in ("iso", "front", "top") else None)
        return [Image(path=f), json.dumps(d, default=str, ensure_ascii=False)]

    @mcp.tool(annotations=RO)
    async def measure(project: str, from_point: list[float] | None = None, to_point: list[float] | None = None,
                      at: list[float] | None = None, rev: int | None = None) -> dict:
        """Measure distances and features of the part. Points are [x, y, z] in millimetres in the design frame.
        from_point + to_point: straight-line distance with dX/dY/dZ, and how far each point is from the surface.
        at: what is at that point: the nearest face (type, area, tilt to the bed), the nearest edge, and for a hole or
        round boss the diameter: exact from the CAD solid, or "fitted" to mesh edges for a mesh design (with its residual)."""
        st = studio()
        from . import analysis
        def go():
            p = st.load(project)
            if at is not None:
                return analysis.probe(st, p, at, rev)
            if from_point is None or to_point is None:
                raise StudioError(_measure_usage(from_point, to_point), MEASURE_EXAMPLE)
            return analysis.measure(st, p, from_point, to_point, rev)
        return await _run(go)

    # ── selections, annotations, colours and materials (form/selection.py, form/materials.py) ──
    @mcp.tool(annotations=RO)
    async def analyze_selection(project: str, items: list[dict], rev: int | None = None) -> dict:
        """Analyse a selection on the CAD solid without saving it. items: up to 24 of
        {"kind": "point" | "edge" | "face", "at": [x, y, z]} or {"kind": "region", "points": [[x, y, z], ...], "radius": mm}
        in design millimetres with each part as printed (the frame measure uses). Per item: feature, face type, area,
        normal and tilt to the bed, overhang, local wall thickness along the inward normal, gap in front, curvature radii,
        height above the bed; an edge's length, radius and the angle its faces meet at; a region's painted area, overhang
        share, features touched and thinnest sampled wall. Returns the numbers and `text`, the same in sentences.
        Evidence class: computed."""
        st = studio()
        from . import selection
        def go():
            r = selection.analyze(st, st.load(project), items, rev)
            for x in r["items"]:
                x.pop("mesh", None)
                if isinstance(x.get("edge"), dict):
                    x["edge"].pop("segments", None)
            return r
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def list_annotations(project: str) -> dict:
        """List annotations. The selections the person named and kept on this design (annotations): name, note, the revision they were
        made on, the picked items and their computed analysis, and `text` describing each. An annotation from an older
        revision describes that revision; reanalyse it with analyze_selection(items=...) to see the head."""
        st = studio()
        from . import selection
        return {"annotations": await _run(selection.listing, st, project)}

    @mcp.tool(annotations=RW)
    async def annotate(project: str, items: list[dict], name: str = "", note: str = "", ctx: Context = None) -> dict:
        """Keep a selection on the head revision with a name and a note (for example a place you want the person to look
        at, or one you changed). items as in analyze_selection. Shown as a pin in Form Studio's viewport and listed in
        its Annotations panel."""
        st = studio()
        from . import selection
        a = await _run(selection.add, st, project, items, name, note, None, by=_origin(ctx))
        act(project, "annotation", f"Annotated “{a['name']}”", ctx)
        return a

    @mcp.tool(annotations=RW)
    async def set_appearance(project: str, part: str = "", color: str | None = None, material: str | None = None,
                             clear: bool = False, ctx: Context = None) -> dict:
        """Set the colour and material of a design. Colour (#rrggbb) and material of the whole design (part="") or of one part (an assembly part id from
        get_project / render). Filaments (a print design): PLA, PETG, ABS, ASA, TPU, PA (nylon), PC, PLA-CF, PETG-CF, PA-CF; Form Studio
        adds their notes to the checks (heat, sunlight, warping, flexible, fibre-filled) and the slicer picks the matching filament.
        Engineering materials (a model design: CNC, casting, rendering): AL-6061, AL-7075, STEEL, STAINLESS, BRASS, COPPER, TITANIUM,
        OAK, WALNUT, MAPLE, PINE, POM, PTFE, PEEK, PMMA ("aluminium 7075", "delrin" also work), with bd_materials' typical density and
        look; get_project then reports the computed mass (volume x typical density). The colour is drawn and written into the 3MF;
        stored in the project's material fields (parts.<id>.material). Leave an argument out to keep it; clear=True removes both."""
        st = studio()
        from . import materials
        def go():
            had = materials.fingerprint(st.load(project))
            out = materials.set_appearance(st, project, part, None if clear else (color if color is not None else "keep"),
                                           None if clear else (material if material is not None else "keep"), by=_origin(ctx))
            if materials.fingerprint(st.load(project)) != had and st.load(project).get("auto_run", True):
                st.run(project)
            p = st.load(project)
            res = {"appearance": out, "materials": [{"id": k, "label": v["label"], "heat_c": v["heat_c"]} for k, v in materials.MATERIALS.items()]}
            from . import purpose as purpose_mod
            if purpose_mod.is_model(p):
                res["engineering_materials"] = [{"id": k, "label": v["label"], "density_g_cm3": v["density_g_cm3"]}
                                                for k, v in materials.engineering().items()]
                try:
                    m = materials.mass(p, (st.head_summary(p) or {}).get("volume_mm3"), part)
                except Exception:                    # noqa: BLE001 - the mass is a convenience
                    m = None
                if m:
                    res["mass"] = m
            return res
        return await _run(go)

    @mcp.tool(annotations=RO, structured_output=False)
    async def suggest_orientation(project: str, ctx: Context = None) -> list:
        """Rank the ways the part can lie on the plate: the six axis orientations plus every flat face on its convex hull.
        Returns a picture of the top three as printed and, for each candidate, the numbers behind its score (support
        volume, overhang area, plate contact, height, smallest layer cross-section through the structure features) and
        each term's contribution. The score formula is in the result. It ranks computed geometry; it does not predict
        print success. Apply one with set_print_setup(project, orientation=<id>)."""
        st = studio()
        from . import analysis
        def go():
            p = st.load(project)
            r = analysis.orientations(st, p)
            f = st.dir(p["id"]) / "artifacts" / "analysis" / f"orient-{st.keys(p)['geometry']}-v{analysis.ANALYSIS_VERSION}.png"
            if not f.exists():
                f.write_bytes(analysis.orientation_thumbs(st, p, r))
            return f, analysis.orientation_digest(r)
        f, d = await _run(go)
        act(project, "look", "Comparing print orientations", ctx)
        return [Image(path=f), json.dumps(d, default=str, ensure_ascii=False)]

    @mcp.prompt(title="Design a part")
    def design_part(goal: str) -> str:
        """A guided Form Studio session for a part or a product."""
        return (f"Goal: {goal}\n\n"
                "Use the Form Studio tools. 1) form_overview; design_brief and design_guide for anything complex. "
                "2) Ask me for any dimension you would otherwise assume, and how I measured it. "
                "3) create_design with your own code (or create_project from a recipe), then render(view='sheet') "
                "and look at it. 4) For each change: update_design, or preview_change then commit_change with "
                "expect_head, and look again. 5) get_project and read the checks and next actions. "
                "Only if I want it printed (purpose \"print\"): run_pipeline, then request_release and give me the "
                "link; report slices as simulated and fit as modelled, and never claim a print succeeded.")

    # ---- print simulation, cost, plate packing -------------------------------------------------
    @mcp.tool(annotations=RO, structured_output=False)
    async def print_simulation(project: str, layer: int | None = None, only: list[str] | None = None,
                               plate: int | None = None, ctx: Context = None) -> list:
        """Simulate the print layer by layer. Look at the sliced print as it would stand at the end of `layer` (1-based; default: finished). Returns a
        picture drawn from the slicer's G-code toolpaths, coloured by line type, plus statistics: z, line types in
        that layer, whether it has bridges or overhang walls, slicer time elapsed and remaining, and the list of
        bridge and overhang layers. only: draw just these line types (e.g. ["Bridge", "Overhang wall"]).
        plate: which plate (1-based) when the design was sliced on several (plate_plan). Needs a current slice
        (run_pipeline). This is a simulation of the slice, not a print: say so."""
        _need_printing()
        st = studio()
        def go():
            from . import simulate, toolpath
            p = st.load(project)
            tp = toolpath.for_project(st, p, plate)
            n = tp.layers if layer is None else max(1, min(tp.layers, int(layer)))
            bad = [t for t in (only or []) if t not in tp.types]
            if bad:
                raise StudioError(f"Unknown line type “{bad[0]}”.", "This slice has: " + ", ".join(tp.types))
            cache = st.dir(p["id"]) / "artifacts" / "renders"
            cache.mkdir(parents=True, exist_ok=True)
            f = cache / f"sim-{st.keys(p)['slice']}-{plate or 1}-{n}-{H(sorted(only or []))}.png"
            if not f.exists():
                f.write_bytes(simulate.png_at(tp, float(n), title=f"{p['name']}  r{p['head']:02d}", only=only))
            s = tp.summary()
            stats = toolpath.stats_at(tp, n - 1) | {
                "bridge_layers": [i + 1 for i in s["bridge_layers"]], "overhang_layers": [i + 1 for i in s["overhang_layers"]],
                "line_type_length_mm": s["type_length_mm"], "time_note": s["time_note"], "file": str(f)}
            return f, stats
        f, stats = await _run(go)
        act(project, "look", f"Looking at the print simulation, layer {stats['layer']} of {stats['layers']}", ctx)
        return [Image(path=f), "Simulated from the slicer's G-code. Not a print.\n" + json.dumps(stats, ensure_ascii=False)]

    @mcp.tool(annotations=RO)
    async def estimate_cost(project: str, price_per_kg: float | None = None, kwh_price: float | None = None,
                            watts: float | None = None, machine_rate_per_h: float | None = None, copies: int = 1) -> dict:
        """Estimate the print cost. Filament, electricity and machine-time cost of the current slice, per plate and for `copies`, plus the same
        volume in the other materials the slicer has presets for. Grams and hours are the slicer's simulation; prices
        are the user's (saved ones are used when you pass none). Never invent a price: when a cost is null, "needs"
        says which number to ask the user for. No currency is assumed."""
        st = studio()
        def go():
            from . import cost
            given = {"price_per_kg": price_per_kg, "kwh_price": kwh_price, "watts": watts, "machine_rate_per_h": machine_rate_per_h}
            out = cost.project(st, st.load(project), copies, given)
            out.pop("prefs", None)
            return out
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def plate_plan(project: str) -> dict:
        """Plan the plates. How the design's printed parts go onto plates: each part as it lies on its own (orientation, size, material),
        the plates they are packed onto when the design does not fit one plate (or its parts differ in material), parts
        too big for the plate, and per plate the slicer's time and filament when it has been sliced. Computed by FORM from
        bounding boxes; each plate is sliced on its own. Needs current checks (run_pipeline)."""
        _need_printing()
        st = studio()
        def go():
            from . import plates
            return plates.for_project(st, st.load(project))
        return await _run(go)

    @mcp.tool()
    async def set_part_print(project: str, part: str, orientation: str | None = None, material: str | None = None,
                             color: str | None = None, ctx: Context = None) -> dict:
        """Set one part's print settings. Print settings for one printed part of a multi-part design (part ids from plate_plan): orientation (a named
        one, a "down:x,y,z" id, or "auto" for the best-ranked way for that part alone), material (PLA, PETG, TPU, ...;
        parts in different materials go on different plates, each sliced with its own filament), color ("#rrggbb").
        "" clears a setting. Checks and slice go stale; the pipeline runs again."""
        st = studio()
        def go():
            st.set_part(project, part, by=_origin(ctx).replace("agent:", "") or "agent",
                        orientation=orientation, material=material, color=color)
            return st.run(project)
        jid = await _run(go)
        await _wait_job(st, jid, 45)
        return await _run(lambda: __import__("form.plates", fromlist=["for_project"]).for_project(st, st.load(project)))

    @mcp.tool(annotations=RO)
    async def pack_plate(project: str, copies: int = 1, spacing_mm: float | None = None) -> dict:
        """Pack copies on a plate. Do `copies` of this design fit on one plate? Bounding-box packing with a gap (default 6 mm) and 90° turns,
        on the selected printer's bed. Returns the layout and the most copies this packer can place. Computed by FORM;
        the slicer arranges again when it slices, and FORM's export stays one plate."""
        _need_printing()
        st = studio()
        def go():
            from . import packing
            return packing.project(st, st.load(project), copies, spacing_mm)
        return await _run(go)

    # ---- Blender (optional): illustrative renders ---------------------------------------------
    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                          open_world_hint=False), structured_output=False)
    async def render_photo(project: str, preset: str = "studio", material: str = "matte", color: str = "#eeece6",
                           fast: bool = False, layer_lines: bool = True, view: str = "iso",
                           azimuth: float | None = None, elevation: float | None = None, zones: bool = True,
                           ctx: Context = None) -> list:
        """Render a photo-real image. A realistic-looking render of the current revision's exported STL, made by Blender headless (if installed).
        preset: studio (soft box, light backdrop) | desk (wooden desk) | dark (graphite, rim light).
        material: matte (PLA) | petg (gloss) | silk (silk PLA) | gloss (paint, clear coat) | carbon (carbon twill,
        clear coat) | smoke (smoked polycarbonate) | rubber | metal. color: hex, e.g. "#3d6fb6".
        view: iso | front | back | left | right | top | three_quarter | three_quarter_back, or azimuth/elevation in
        degrees (azimuth from +X toward +Y, as in render: "front" looks from -Y, so a product facing +X shows its face
        at azimuth 0). Render a styled product from at least three angles before you judge it.
        zones: when the design declares appearance() (material zones: a smoked visor, rubber trim, a carbon shell),
        each zone gets its own material; the rest takes material/color.
        layer_lines draws faint lines at the slicer's layer height when a process preset is selected.
        fast=True uses EEVEE instead of Cycles. Cached per geometry and settings. This is an illustration with
        invented light and material, not a photo of a print: never present it as evidence of anything."""
        st = studio()
        from . import photo
        m = await _run(lambda: photo.render(st, st.load(project), preset, material, color, fast, layer_lines,
                                            view=view, azimuth=azimuth, elevation=elevation, use_zones=zones))
        f = st.dir(project) / "artifacts" / "photo" / m["file"]
        act(project, "look", f"Rendered in Blender ({m['preset_label']}, {m['finish_label']})", ctx)
        lh = m["layer"]
        caption = (f"{m['label']}. r{m['rev']:02d}, {m['preset_label']} · {m['finish_label']} {m['color']}, "
                   f"{m['engine']} on {m['device']}, {m['samples']} samples, Blender {m['blender']}"
                   + (f", layer lines at {lh['mm']:g} mm ({lh['note']})" if lh.get("mm") else "")
                   + f", view {m.get('view', 'iso')}"
                   + ("; zones " + ", ".join(f"{'+'.join(z['features'][:3])}: {z['finish'] or material}"
                                             for z in m["zones"]) if m.get("zones") else "")
                   + (" (cached)" if m.get("cached") else f", {m['seconds']:.0f} s") + f". File: {f}")
        return [Image(path=f), caption]

    # ---- design tools: variants, share card, revision history (form/variants.py, form/share.py) ----
    @mcp.tool(annotations=RW)
    async def save_variant(project: str, name: str, values: dict[str, float] | None = None, rev: int | None = None,
                           note: str = "", ctx: Context = None) -> dict:
        """Save a named variant of the design ("Travel version", "Thick walls"): a complete set of parameter values kept
        in the project next to the revisions. values are changes on top of the head (or of rev); leave them out to save
        the head (or rev) as it is. The candidate is built before it is saved; saving a name again replaces it. Nothing
        is committed: promote a variant in Form Studio or with `form variants promote`."""
        st = studio()
        from . import variants
        v = await _run(lambda: variants.save(st, st.load(project), name, values, rev, note, _origin(ctx).replace("agent:", "") or "agent"))
        act(project, "variant", f"Saved variant “{v['name']}”", ctx)
        return v

    @mcp.tool(annotations=RO)
    async def list_variants(project: str) -> dict:
        """List variants. The head and every saved variant side by side: size and volume (computed), print time and grams (simulated,
        only when the variant is a revision with a current slice), fit yield (modelled), checks, and each variant's
        differences from the head."""
        st = studio()
        from . import variants
        return await _run(lambda: variants.board(st, st.load(project)))

    @mcp.tool(annotations=RO, structured_output=False)
    async def share_card(project: str, picture: str = "model", ctx: Context = None) -> list:
        """Make a share card image. A 1600 x 900 share image of the head revision: the part with dimension lines, its name, size and volume
        (computed), print time and grams (simulated; only if the slice is current), checks, the revision and
        "Designed with FORM". picture: "model" (kernel geometry) or "photo" (the newest current Blender render, an
        illustration). The card states only what FORM knows; it is not evidence of a print."""
        st = studio()
        from . import share
        c = await _run(lambda: share.card(st, st.load(project), picture=picture))
        act(project, "look", "Made the share card", ctx)
        rows = "; ".join(f"{r['k']}: {r['v']}" + (f" [{r['tag']}]" if r["tag"] else "") for r in c["facts"]["rows"])
        return [Image(path=c["file"]), f"Share card for {c['facts']['name']} r{c['rev']:02d}. {rows}. File: {c['file']}"]

    # ---- project housekeeping: rename, duplicate, delete (Studio.rename_project and friends) ----
    @mcp.tool(annotations=RW)
    async def rename_project(project: str, name: str, ctx: Context = None) -> dict:
        """Change a project's display name (up to 80 characters). The project id stays the same, so links, files and
        releases keep working. Returns the project's summary: id, name, recipe, head, revisions, updated, approved_rev."""
        st = studio()
        row = await _run(st.rename_project, project, name)
        act(project, "project", f"Renamed to “{row['name']}”", ctx)
        return row

    @mcp.tool(annotations=RW)
    async def duplicate_project(project: str, name: str | None = None, ctx: Context = None) -> dict:
        """Copy a project with its revisions, variants and built outputs under a new id (from the new name; default
        "<old name> copy"). The copy is not approved: approvals and release folders belong to the original and are not
        copied. Returns the new project's summary; use its id from then on."""
        st = studio()
        row = await _run(st.duplicate_project, project, name)
        act(row["id"], "project", f"Copied from {project} as “{row['name']}”", ctx)
        _made(row["id"], "duplicate_project")
        return row

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False))
    async def delete_project(project: str, ctx: Context = None) -> dict:
        """Delete a project by moving its whole folder to the trash folder inside the projects folder
        (<projects folder>/.trash/<id>-<UTC time>). Nothing is erased, and moving the folder back restores it, but the
        project disappears from FORM. Ask the user first and only call this after they said yes to deleting this
        project. Returns {ok, id, trash}: tell the user the trash path. Outside Form Studio's chat, a client with
        its own forms (MCP elicitation) asks the person to confirm first; declined: {ok: false, refused}."""
        from . import elicit
        st = studio()
        if elicit.available(ctx):
            def who():
                pid = st._pid(project)
                if not (st.dir(pid) / "project.json").exists() and not (st.dir(pid) / "project.json.bak").exists():
                    raise StudioError("Unknown project.", status=404)
                try:
                    return pid, st.load(pid).get("name") or pid
                except Exception:
                    return pid, pid
            pid, name = await _run(who)
            r = await elicit.form(ctx, "confirm", elicit.delete_message(name, pid, st.root / ".trash"),
                                  elicit.CONFIRM_DELETE)
            if elicit.pending(r):
                return r
            if r is not None and not (r.accepted and r.content.get("confirm") is True):
                return {"ok": False, "id": pid, "refused": "The person did not confirm deleting this project.",
                        "note": "Nothing was moved. Do not ask again unless the person brings it up."}
        res = await _run(st.delete_project, project)
        act(None, "project", f"Moved {project} to the trash folder", ctx)
        return res

    # ---- printers: every printer the user set up in any installed slicer (engine workstream, form/printers.py) ----
    @mcp.tool(annotations=RO)
    async def list_printers(project: str | None = None, printer: str | None = None) -> dict:
        """List printers. Every printer set up in every installed slicer (the user's own presets and the system printers they enabled),
        with slicer, bed size and nozzle, plus the default printer. With `project`: which printer that design uses and
        why (its own choice, the default, or the slicer's selection). With `printer` ("<kind>:<printer name>", the id from
        this list): the filaments and processes that printer can use."""
        def go():
            from . import printers
            st = studio()
            if printer:
                kind, _, name = printer.partition(":")
                try:
                    return printers.options(st.cfg, kind, name)
                except printers.PrinterError as e:
                    raise StudioError(e.message, e.hint)
            out = printers.inventory(st.cfg)
            if project:
                out["project"] = {"id": project, **st.printer_state(st.load(project))}
            return out
        return await _run(go)

    @mcp.tool()
    async def choose_printer(printer: str, project: str | None = None, filament: str = "", process: str = "",
                             default: bool = False, ctx: Context = None) -> dict:
        """Use a printer for one design (`project`) or as the default for designs without their own choice
        (`default=True`, written to studio.toml after a backup). `printer` is an id from list_printers ("bambu:Bambu Lab
        A1 mini 0.4 nozzle"); "" with a project clears its choice. Filament and process default to what the slicer would
        pick for that printer. Slicing and the bed-size and nozzle checks follow the choice; the slice goes stale.
        Ask the user which printer before calling this."""
        _need_printing()
        def go():
            from . import printers
            st = studio()
            choice = None
            if printer:
                kind, _, name = printer.partition(":")
                choice = {"kind": kind, "machine": name, "filament": filament, "process": process}
            if default:
                try:
                    done = printers.set_default(st.cfg, choice)
                except Exception as e:
                    raise StudioError(str(getattr(e, "message", e)), getattr(e, "hint", ""))
                st.slicer_info(refresh=True)
                return {"default": done["default"], "path": done["path"], "backup": done["backup"]}
            if not project:
                raise StudioError("Give a project, or default=True.")
            return st.set_printer(project, choice, by=_origin(ctx).replace("agent:", "") or "agent")
        res = await _run(go)
        act(project, "printer", f"Printer: {printer or 'default'}", ctx)
        return res

    # ---- talking with the person (chat workstream): ask_user, suggest_replies ---------------------------------
    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False), meta=ALWAYS)
    async def ask_user(question: str, choices: list[str] | None = None, multi_select: bool = False,
                       allow_text: bool = True, why: str = "", kind: str = "question", ctx: Context = None) -> dict:
        """Ask the person one question and wait for the answer. Use it only when the answer changes the design
        and you cannot find it yourself: a measurement that sets a fit or a load, or an intent you cannot tell
        apart (which device, which side opens). At most a few questions per task; ask them one at a time.
        choices: up to 8 short options shown as buttons (multi_select lets the person pick several);
        allow_text lets them type their own answer; why: one line on what the answer changes.
        kind="confirm" shows an approval card (choices default to Yes / No) before an action the person
        should agree to. Returns {answered, answer, choices, text} or, when nobody answered, {answered: false,
        reason, note}: then continue with safe assumptions marked assumed. Outside Form Studio's chat the question
        is shown in your client's own form when it supports one (MCP elicitation); otherwise nobody can answer
        here and the result tells you to ask in your own interface."""
        from . import ask as ask_mod
        from . import elicit
        try:
            q = ask_mod.question(question, choices, multi_select, allow_text, why, kind)
        except ask_mod.AskError as e:
            raise ToolError(str(e))
        return await elicit.ask(ctx, q)

    @mcp.tool(annotations=RW)
    async def ask_measurement(project: str, param: str, question: str, where: str = "", unit: str = "mm",
                              tolerance_mm: float | None = None, diagram: dict | None = None, image: str | None = None,
                              mark: list[float] | None = None, ctx: Context = None) -> dict:
        """Ask the person to measure one dimension of the design, and wait. Form Studio shows a measurement card:
        the question, where to measure (where, e.g. "across the widest part of the phone, without the case"), the
        precision that matters (tolerance_mm), a diagram ({"shape": "box"|"cylinder"|"hole"|"gap"|"thickness",
        "axis": "x"|"y"|"z"|"d"}) and optionally a picture: image is an absolute path to a PNG or JPEG (a render, or
        the person's photo) with mark = [x0, y0, x1, y1] (0..1) outlining where to measure. The person types the
        number and says how they measured it (calipers, ruler, tape, or estimate). The answer becomes a new revision
        of the design with provenance measured (calipers sigma 0.05 mm, ruler 0.5, tape 1.0) or, for an estimate,
        assumed. One question at a time. Returns {answered, value, unit, method, source, rev}; when nobody answered,
        {answered: false, reason, note}. Outside Form Studio's chat it is asked in your client's own form when it
        supports one (value, calipers / ruler / datasheet, or skipped; a datasheet value is recorded as specified);
        otherwise it tells you to ask in your own interface."""
        from . import ask as ask_mod
        from . import elicit, start
        import os as _os
        import shutil as _sh
        st = studio()

        def check():
            p = st.load(project)
            head = st.rev(p)
            if param not in head["values"]:
                raise StudioError(f"“{param}” is not a parameter of {project}.", "get_project lists the parameters.")
            try:
                spec = st.recipe(p).spec(param)
                bounds = (float(spec.min), float(spec.max))
            except Exception:
                bounds = (None, None)
            return head["values"][param], bounds
        current, (lo, hi) = await _run(check)
        folder = _os.environ.get(ask_mod.ENV_DIR)
        qid = ask_mod.new_id()
        ext = None
        if image:
            src = Path(image).expanduser()
            ext = src.suffix.lower().lstrip(".")
            if not src.is_absolute() or not src.is_file() or ext not in ("png", "jpg", "jpeg"):
                raise ToolError("image must be the absolute path of a PNG or JPEG file.")
        try:
            q = ask_mod.measure_question(question, project, param, where, unit, tolerance_mm, diagram,
                                         f"{qid}.{ext}" if ext else None, mark, current)
        except ask_mod.AskError as e:
            raise ToolError(str(e))
        if not folder:
            r = await elicit.form(ctx, "measurement", elicit.measurement_message(q), elicit.measurement_schema(q, lo, hi))
            if r is None:
                return {**ask_mod.unreachable(q), "param": param, "current": current, "where": q["where"]}
            if elicit.pending(r):
                return r
            got = elicit.measurement_reply(q, r, lo, hi)
            if isinstance(got, dict):
                return got
            rec = await _run(elicit.record_measurement, st, project, param, *got)
            return elicit.measurement_result(q, rec)
        Path(folder).mkdir(parents=True, exist_ok=True)
        if ext:
            _sh.copyfile(Path(image).expanduser(), Path(folder) / f"{qid}.{ext}")   # before the question appears
        timeout = ask_mod.timeout_from_env()
        ask_mod.post(Path(folder), q, timeout, qid=qid)
        st_, extra = await elicit.wait_folder(Path(folder), qid, timeout)
        res = ask_mod.measure_result(q, st_, extra)
        if res.get("answered") and res.get("value") is not None and not res.get("rev") and res.get("method"):
            # answered where nothing committed it (a terminal): record it here, the same way the app does
            rec = await _run(start.apply_measurement, st, project, param, res["value"], res["method"])
            res = {**res, "rev": rec["rev"], "source": rec["source"],
                   "note": ask_mod.measure_result(q, st_, {**(extra or {}), **rec})["note"]}
        return res

    # ---- concepts first (form/concepts.py) --------------------------------------------------------------------
    @mcp.tool(annotations=RW)
    async def propose_concepts(name: str, concepts: list[dict], brief: str = "", group: str | None = None,
                               run: bool = True, ctx: Context = None) -> dict:
        """Propose concepts. For a new idea: build 2-4 genuinely different concepts as real designs, so the person can pick one.
        concepts: [{"title": short name, "rationale": one line on the approach, "source": design code as for
        create_design (see design_guide), "language": "python", "values": {...} or null}]. Make them different
        structural approaches (how it holds, mounts, opens), not size variants. Each becomes its own project
        ("<name> · A", "· B", ...). A concept that fails to build comes back in "failed" with its error; the others are
        kept. group: an open group's id to add concepts to (at most 6 in a group), e.g. one mixed concept when the
        person asks for "the base of A with the hook of C". With run=True each is exported and checked.
        Returns the board: {id, name, state, members: [{project, letter, title, rationale, numbers}], failed}."""
        from . import concepts as concepts_mod
        st = studio()
        by = _origin(ctx).replace("agent:", "") or "agent"
        act(None, "design", f"Building concepts for {name}", ctx)
        res = await _run(concepts_mod.create, st, name, concepts, brief, group, None, by)
        if run:
            jobs = [st.run(m["project"]) for m in res["members"] if not m.get("trashed") and not m.get("error")]
            t0 = time.time()
            for j in jobs:
                await _wait_job(st, j, max(1.0, 60 - (time.time() - t0)))
            res = {**await _run(concepts_mod.board, st, res["id"]), "failed": res["failed"]}
        _made(None, "propose_concepts", role="concept", group=res["id"])
        for m in res.get("members") or []:              # each concept is listed, not put in front: the person picks
            if m.get("project") and not m.get("trashed"):
                _made(m["project"], "propose_concepts", role="concept", group=res["id"])
        res["note"] = ("Stop here and let the person pick in Form Studio's concepts view. If they pick in words, call "
                       "pick_concept(group, project). If they ask for a mix (\"the base of A with the hook of C\"), call "
                       "propose_concepts(name, [one mixed concept], group=\"" + res["id"] + "\").")
        return res

    @mcp.tool(annotations=RW)
    async def pick_concept(group: str, project: str, keep_others: bool = False, ctx: Context = None) -> dict:
        """Pick a concept. The person picked a concept (in words; in the app they pick on the board). The picked project takes the
        group's name and records the choice; the other concepts move to the trash (recoverable) unless keep_others.
        Then refine the picked design with update_design. Only call this when the person said which one."""
        from . import concepts as concepts_mod
        st = studio()
        res = await _run(concepts_mod.pick, st, group, project, keep_others, _origin(ctx).replace("agent:", "") or "agent")
        _made(project, "pick_concept", group=group)
        return res

    @mcp.tool(annotations=RW)
    async def dismiss_concepts(group: str, keep: str = "all", ctx: Context = None) -> dict:
        """Dismiss concepts. The person wants none of the concepts picked: close the group without a pick. keep="all" keeps every
        concept as an ordinary design; keep="none" moves them all to the trash (recoverable). Only call this when
        the person said so."""
        from . import concepts as concepts_mod
        st = studio()
        return await _run(concepts_mod.dismiss, st, group, keep, _origin(ctx).replace("agent:", "") or "agent")

    @mcp.tool(annotations=RO)
    async def list_concepts(group: str = "") -> dict:
        """List concepts. Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>."""
        from . import concepts as concepts_mod
        st = studio()
        if group:
            return await _run(concepts_mod.board, st, group)
        return {"groups": await _run(concepts_mod.groups, st, "open")}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def suggest_replies(options: list[str]) -> dict:
        """Offer up to 3 short follow-up messages the person might send next (each under 80 characters, written
        as the person would say it, e.g. "Make the walls 2 mm"). Form Studio's chat shows them as buttons under
        your reply. Call it at most once, at the end of a reply, and only with useful next steps."""
        from . import ask as ask_mod
        opts = ask_mod.clean_suggestions(options)
        return {"shown": opts, "note": "Shown as buttons under your reply when this runs in Form Studio's chat."}

    # ---- home workstream: starters, recipe library, archives (form/starters.py, recipe_lib.py, bundle.py) ----
    def _home(fn, *a, **kw):
        from .home_api import _call
        return _call(fn, *a, **kw)

    @mcp.tool(annotations=RO)
    async def list_starters() -> dict:
        """List starter ideas. Ideas for what this person might design next, ranked from what they already design (the building blocks
        and kinds of part in their projects, their printer and material, what they pinned or used):
        {prompts: [{id, text, source, pinned}], briefs: [...]}. Offer them as suggestions when the person asks what to
        make; they edit the list with `form starters`."""
        from . import starters
        st = studio()
        return await _run(starters.for_studio, st)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def recipe_library(q: str = "", section: str = "", tag: str = "") -> dict:
        """Search the recipe library: built-in recipes and recipes the person installed ("mine"), to find a building
        block to start a design from. section: builtin | mine. Recipes are internal building blocks: use one when it
        fits, but do not offer the library to the person. Installing code is the person's decision and happens only
        with `form recipes install`, after they review the source and its SHA-256."""
        from . import recipe_lib
        st = studio()
        def go():
            lib = recipe_lib.everything(st.root, st.recipes.builtins())
            return {"recipes": recipe_lib.search(lib["items"], q, section, tag)}
        return await _run(go)

    # ---- recipe sharing (form/recipe_share.py): packages are written locally; nothing is posted ----
    @mcp.tool(annotations=RW)
    async def export_recipe(recipe: str, path: str | None = None, ctx: Context = None) -> dict:
        """Write an installed ("mine") recipe as one .formrecipe file: its code, meta.json (parameters, author, tags,
        the code's SHA-256) and preview.png drawn from a real build at its defaults. Returns {file, bytes, sha256}.
        Nothing is uploaded; the person shares the file however they like."""
        from pathlib import Path as _P

        from . import recipe_share
        st = studio()
        out = _P(path).expanduser() if path else st.root / "shared-recipes"
        if not path:
            out.mkdir(parents=True, exist_ok=True)
        return await _run(_home, recipe_share.export, st, recipe, out)

    @mcp.tool(annotations=RW)
    async def design_as_recipe(project: str, title: str = "", summary: str = "",
                               ranges: dict[str, list[float]] | None = None) -> dict:
        """Turn a design's current code into a recipe whose defaults are the design's values; ranges narrow a
        parameter's range ({key: [min, max]}, never wider than the code's own). It is built once and compared with the
        design (check.same_volume). Returns the code and its SHA-256 for the person to review; installing it is their
        decision, in the app or with `form recipes derive <project> --install --sha256 <hex>`."""
        from . import recipe_share
        st = studio()
        rg = {k: (v[0], v[1]) for k, v in (ranges or {}).items() if len(v) == 2}
        d = await _run(_home, recipe_share.derive, st, project, title, summary, rg)
        return {k: d[k] for k in ("title", "summary", "kind", "sha256", "source", "check", "param_list", "problems")}

    @mcp.tool(annotations=RW)
    async def export_project(project: str, path: str | None = None, conversations: bool = True, ctx: Context = None) -> dict:
        """Write the project, its conversations and the code its revisions were built from to one .formstudio file
        (default: <projects folder>/<project>.formstudio). Returns {file, bytes}. Nothing is uploaded."""
        from pathlib import Path as _P

        from . import bundle
        st = studio()
        f = await _run(_home, bundle.export_project, st, project, _P(path).expanduser() if path else None, conversations)
        act(project, "project", f"Exported to {f.name}", ctx)
        return {"file": str(f), "bytes": f.stat().st_size}

    @mcp.tool(annotations=RW)
    async def import_project(path: str, ctx: Context = None) -> dict:
        """Import a .formstudio or .formproj archive (or a conversation .json) from an absolute path. The archive is
        checked first; a project or conversation id that already exists gets a new one. Returns the new ids."""
        from pathlib import Path as _P

        from . import bundle
        st = studio()
        res = await _run(_home, bundle.import_file, st, _P(path))
        if res.get("id"):
            act(res["id"], "project", f"Imported “{res['name']}”", ctx)
            if (st.root / str(res["id"]) / "project.json").is_file():     # a project, not a conversation
                _made(res["id"], "import_project")
        return res

    @mcp.tool(annotations=RO)
    async def export_conversation(conversation: str, format: str = "md") -> dict:
        """Export a conversation. A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again)."""
        from . import bundle
        st = studio()
        if format == "json":
            return await _run(_home, bundle.conversation_json, st.root, conversation)
        return {"markdown": await _run(_home, bundle.conversation_markdown, st.root, conversation)}

    # Blender as an editor and a baker (never the geometry authority): model_mesh streams each op's level-2 preview
    # into the app as a draft (Studio._draft_sink), game_asset derives LODs, UVs, bakes and collision from a design.
    from .adapters import blender_model
    from . import game
    blender_model.register(mcp, studio, _run)
    game.register(mcp, studio, _run)
    return mcp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="form-mcp", description="Form Studio MCP server (stdio)")
    ap.add_argument("--no-bench", action="store_true", help="do not serve the local bench web page")
    a = ap.parse_args(argv)
    mcp = build()
    st = studio()
    from .capabilities import migrate_safely
    migrate_safely(st.cfg)                               # once: people who already print keep printing
    if not a.no_bench:
        from .server import start_bench
        S["bench"] = start_bench(st)
    threading.Thread(target=lambda: _safe(st.kernel_id), daemon=True).start()   # warm the kernel
    try:
        mcp.run("stdio")
    finally:
        st.kernel.stop()
    return 0


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
