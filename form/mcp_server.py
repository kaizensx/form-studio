"""FORM over the Model Context Protocol.

Any MCP client (Claude Code, Codex, Gemini CLI, Cursor, ...) drives the same
deterministic engine the bench uses. The agent proposes; FORM builds, measures,
checks, slices and keeps the record. Release approval is deliberately not a
tool: it needs a person, on the bench.

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
and keeps an honest record of what is known. 3D printing is one optional way to make a design; it is off unless the
person turned it on (form_overview: has_printer).

Workflow: form_overview -> describe_recipe -> create_project (or get_project) -> preview_change ->
render (look at it) -> commit_change -> run_pipeline -> get_project (gate, checks, next actions) ->
request_release (a person approves in Form Studio).

Rules:
- Units are mm, degrees, grams. Only change parameters that describe_recipe lists.
- Always preview_change before commit_change; pass expect_head so you never overwrite a newer revision.
- Provenance is evidence. Mark a value "measured" only when the user measured it and told you the number.
  Never invent physical results; record_physical_result is only for what the user reports.
- A slice is a simulation, not a print. Fit yield is a model. Say so when you report them.
- You cannot approve a release. request_release returns a link that opens the release in Form Studio for the user.
- Nothing here starts a print or sends files anywhere.
- Every design has a purpose: "print" (for 3D printing) or "model" (just a 3D model: rendering, CAD exchange, CNC,
  laser cutting, moulding). get_project reports it. For a model never ask about a printer, slicer, filament or
  orientation; print checks and slicing do not apply. Pass purpose to create_project/create_design when the person
  says what it is for; otherwise Form Studio uses their default (form_overview: purpose_default).
- Ask the person only what changes fit, load or safety and you cannot look up: ask_user, one question at a time,
  at most three per task. Outside Form Studio's chat it tells you to ask in your own interface. For a dimension the
  person can measure, use ask_measurement (where to measure, tolerance, a diagram); it updates the design with how
  it was measured.
- A new idea that is not already a precise specification: propose_concepts with 3-4 genuinely different structural
  approaches as real designs (not size variants), a one-line rationale each; then stop and let the person pick.
  Refine the picked one with update_design. Recipes may be used as building blocks; do not offer them to the person.
- Photos: find the scale from a reference object (bank card 85.60 x 53.98 mm, a coin's official diameter, a ruler);
  dimensions read off a photo are "estimated from the photo (scale from <reference>)" and stay assumed until measured.
  Sketches from Form Studio carry structured JSON: it is authoritative over the picture; stated dimensions override
  drawn lengths. STEP/STL: import_reference. PDF drawings: read_document. Download only files the person gave you.
- If the message has a "Purpose:" line, respect it: "just a 3D model" means no slicing and no print talk.
"""

S: dict[str, Any] = {"studio": None, "bench": {"url": None}, "lock": threading.Lock()}


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
    try:
        info = ctx.session.client_params.client_info
        return f"agent:{info.name}"
    except Exception:
        return "agent"


def act(pid, kind: str, text: str, ctx=None, **extra):
    """Tell the bench what the agent is doing; open it the first time there is something to show."""
    st = studio()
    st.activity(pid, kind, text, by=_origin(ctx).replace("agent:", "") or "agent", **extra)
    url = S["bench"].get("url")
    if url and pid and not S.get("opened") and st.cfg.get("bench", {}).get("auto_open", True):
        S["opened"] = True
        try:
            webbrowser.open(f"{url}/#p={pid}")
        except Exception:
            pass


def _purpose(purpose: str | None) -> str | None:
    """The purpose a design gets: the agent's, else the one the person chose on Home for this chat run (FORM_PURPOSE),
    else None (the person's default, form/purpose.py)."""
    if purpose:
        return purpose
    from . import start
    return start.env_purpose()


# Tools that only make sense for someone who prints (form/capabilities.py "print"). With printing off they are left out
# of form_overview and refuse with PRINTING_OFF: Form Studio is for making things; printing is opt-in.
PRINT_TOOLS = ("choose_printer", "plate_plan", "pack_plate", "print_simulation", "slice_test_piece", "set_print_setup")
PRINTING_OFF = ("printing is off; enable it in Settings (Set up for › 3D printing). Form Studio still designs, checks "
                "and exports this as a 3D model (STEP, STL, 3MF, OBJ, GLB).")


def _printing_on() -> bool:
    from . import purpose as purpose_mod
    return purpose_mod.printing(studio().cfg)


def _need_printing() -> None:
    if not _printing_on():
        raise ToolError(PRINTING_OFF)


def digest(st: Studio, pid: str) -> dict:
    return _digest(st, pid, S["bench"].get("url"))


async def _wait_job(st: Studio, jid: str, wait_s: float) -> dict:
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if st.jobs[jid]["state"] != "running":
            break
        await anyio.sleep(0.25)
    return st.jobs[jid]


# ---- server ---------------------------------------------------------------

def build() -> MCPServer:
    mcp = MCPServer("form", title="Form Studio AI CAD studio", version=__version__, instructions=INSTRUCTIONS)
    RO = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    RW = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

    @mcp.tool(annotations=RO)
    async def form_overview() -> dict:
        """Start here. Engine, slicer, printer, available recipes, existing projects and the bench URL."""
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
        """What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap.
        Never run a fix without asking the user; the simplest path is to ask them to run `form setup` in a terminal."""
        def go():
            from . import installer, setup
            rows = installer.survey(studio().cfg)
            return {"items": [i.public() for i in setup.check(studio().cfg)],
                    # the installer registry: what each thing is for, whether it was found, and the exact commands
                    "software": [{k: r[k] for k in ("id", "label", "why", "level", "status", "detail", "size", "installable", "manual")}
                                 | {"commands": (r["plan"] or {}).get("commands", [])} for r in rows],
                    **installer.summary(rows),
                    "tell_the_user": "Form Studio's app installs these under Settings, Software. Headless: `form install <id>`, "
                                     "or install_software(id, confirm=True) after the user agrees to the command shown."}
        return await _run(go)

    @mcp.tool()
    async def install_software(id: str, confirm: bool = False, method: str | None = None) -> dict:
        """Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude",
        "slicer.orca". Without confirm=True nothing runs: you get the exact commands to show the user. Ask the user
        first, then call again with confirm=True. Never asks for a password; sign-in is not an install."""
        def go():
            from . import installer
            cfg = studio().cfg
            inst = installer.Installer(cfg)
            try:
                pairs = inst.prepare([id], None, {id: method} if method else None)
            except installer.InstallError as e:
                return {"installed": False, "error": e.public()}
            sw, m = pairs[0]
            plan = {"id": sw.id, "label": sw.label, "why": sw.why, "size": sw.size, "method": m.label, "commands": m.commands,
                    **({"edits_a_file": m.note} if m.kind == "action" else {})}
            if confirm is not True:
                return {"installed": False, "refused": "confirm=True is required.", "would_run": plan,
                        "tell_the_user": "Show these commands and ask before installing."}
            job = installer.run_blocking(cfg, [id], {id: method} if method else None)
            lines = [l["text"] for l in job.public(0)["log"]]
            return {"installed": job.state == "done", "state": job.state, "ran": plan, "steps": job.steps,
                    "log_tail": lines[-40:], "after": {k: {"status": v["status"], "detail": v["detail"]} for k, v in job.after.items()}}
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def describe_recipe(recipe: str) -> dict:
        """Parameters (unit, range, group, the feature each one drives), features and what the recipe checks."""
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

    @mcp.tool(annotations=RO)
    async def design_guide(purpose: str | None = None) -> dict:
        """Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter,
        holder, mechanism...). Returns the contract for a design written as code, the rules, and a complete example
        that builds. Then call create_design. purpose: "print" or "model" (default: the person's default, see
        form_overview); the print rules (bed orientation, overhangs, nozzle walls) are only in the guide for "print"."""
        from . import purpose as purpose_mod
        from .design_guide import EXAMPLE, guide
        pur = purpose_mod.normalise(_purpose(purpose)) or purpose_mod.default(studio().cfg)
        return {"guide": guide(pur), "purpose": pur, "example_source": EXAMPLE,
                "built_in_recipes": "dock, gridfinity, hook, planter, coupon, enclosure, gear_pair, knob (use create_project for these)"}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True), structured_output=False)
    async def read_document(source: str, pages: str = "1") -> list:
        """Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). PDF pages come
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

    @mcp.tool(annotations=RW)
    async def create_design(name: str, source: str, brief: str = "", values: dict[str, float] | None = None,
                            run: bool = True, language: str = "python", references: list[str] | None = None,
                            purpose: str | None = None, process: str | None = None, ctx: Context = None) -> dict:
        """Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass,
        built with build123d. FORM builds it, and with run=True exports, checks and slices it. Load or build errors come
        back with the line and a hint; fix and call again. Then render(view="sheet") and look at it.
        Several parts: declare assembly() (design_guide, ASSEMBLIES): parts with attach=, joints with parent= (chains: a
        joint moves everything attached below it), Mate() for pins and threads. A declaration that cannot be used
        (unknown part, a loop, two parents) is refused with the reason; the assembly checks then run in their own time
        budget and say which joint ranges they reached.
        language="openscad": source is an OpenSCAD file; parameters come from Customizer comments (`w = 40; // [20:1:120]`).
        OpenSCAD output is a mesh: no STEP, no B-rep checks (reported as not available, never faked).
        references: absolute paths of STEP/STL parts to import first, so a Python design can use self.reference("name.step").
        purpose: "print" (for 3D printing) or "model" (just a 3D model; not sliced, no print checks). Omitted: the
        person's default. process (models only): cnc, laser, injection, casting, sheet_metal, render, cad, other."""
        st = studio()
        act(None, "design", f"Writing a new design: {name}", ctx)
        p = await _run(st.create_design, name, source, brief, values, language, references, _purpose(purpose), process)
        act(p["id"], "commit", f"Created {name} (r01)", ctx)
        if run:
            jid = st.run(p["id"])
            await _wait_job(st, jid, 50)
        return await _run(digest, st, p["id"])

    @mcp.tool(annotations=RW)
    async def update_design(project: str, source: str, note: str = "", values: dict[str, float] | None = None,
                            expect_head: int | None = None, run: bool = True, language: str | None = None,
                            ctx: Context = None) -> dict:
        """Replace a design's code as a new revision (history keeps every version). Existing parameter values carry over;
        changing a default does not change a saved value, so pass values={...} to change them. New parameters start at
        their defaults. Use preview_change/commit_change instead when only values change. language defaults to the
        project's current one ("python" or "openscad"). An unusable assembly() declaration is refused with the reason,
        and no revision is made."""
        st = studio()
        p = await _run(lambda: st.update_design(st.load(project), source, note, values, _origin(ctx), expect_head, language))
        act(project, "commit", f"r{p['head']:02d}: {note or 'design code updated'}", ctx)
        res: dict[str, Any] = {"head": p["head"]}
        if run:
            jid = st.run(project)
            res["pipeline"] = job_digest(await _wait_job(st, jid, 45))
        res["project"] = await _run(digest, st, project)
        return res

    @mcp.tool(annotations=RO)
    async def get_design_source(project: str, rev: int | None = None) -> dict:
        """The exact code a revision was built from (built-in recipes return their recipe file)."""
        st = studio()
        def go():
            p = st.load(project)
            return {"project": project, "rev": rev or p["head"], "recipe": st.rid(p, rev), "source": st.source_text(p, rev)}
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
        if run:
            jid = st.run(p["id"])
            await _wait_job(st, jid, 50)
        return await _run(digest, st, p["id"])

    @mcp.tool(annotations=RO)
    async def get_project(project: str) -> dict:
        """Current revision with every parameter and its provenance, output status (current/stale/failed/missing),
        checks, fit model, next best actions, simulated slice, file paths, release gate and bench link."""
        st = studio()
        return await _run(digest, st, project)

    @mcp.tool(annotations=RO)
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

    @mcp.tool(annotations=RW)
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

    @mcp.tool(annotations=RO)
    async def get_job(project: str, job: str, wait_s: float = 30) -> dict:
        """Status of a pipeline job started by run_pipeline/commit_change; waits up to wait_s for it to finish."""
        st = studio()
        if job not in st.jobs:
            raise ToolError("Unknown job (jobs live only as long as this server process).")
        return job_digest(await _wait_job(st, job, max(0.0, min(wait_s, 300))))

    @mcp.tool(annotations=RO, structured_output=False)
    async def render(project: str, view: str = "iso", highlight: str | None = None, rev: int | None = None,
                     values: dict[str, float] | None = None, ctx: Context = None) -> list:
        """Look at the part. Returns a PNG rendered from the real kernel geometry, coloured by feature.
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
            if values:
                v = st.preview(p, values)
                title, key = f"{p['name']} - r{p['head']:02d} + DRAFT (not saved)", "pv-" + H(st.rid(p), v["values"])
            else:
                n = rev or p["head"]
                v = st.view(p, n)
                title, key = f"{p['name']} - r{n:02d}", st.keys(p, n)["geometry"]
            if view in rendering.POSES:
                try:
                    v = rendering.posed(v, view)
                except ValueError as e:
                    raise StudioError(str(e))
            views = ["iso", "front", "top", "right"] if view == "sheet" else ["iso"] if view in rendering.POSES else [view]
            cache = st.dir(p["id"]) / "artifacts" / "renders"
            cache.mkdir(parents=True, exist_ok=True)
            f = cache / f"{key}-{view}-{highlight or 'all'}-v{rendering.VERSION}.png"
            if not f.exists():
                size = (640, 460) if view == "sheet" else (960, 680)
                try:
                    pngs = [rendering.render_png(v, feats, vw, highlight, size=size, title=title) for vw in views]
                except ValueError as e:
                    raise StudioError(str(e))
                f.write_bytes(pngs[0] if len(pngs) == 1 else rendering.contact_sheet(pngs))
            caption = (f"{title}. Rendered from the kernel tessellation ({v['triangles']} triangles), "
                       f"bounding box {' x '.join(f'{b - a:.1f}' for a, b in zip(*v['bbox']))} mm. File: {f}")
            return f, caption
        f, caption = await _run(go)
        act(project, "look", f"Looking at the {view} view" + (f", {highlight}" if highlight else "")
            + (" of a draft" if values else ""), ctx, view=view, highlight=highlight, values=values)
        return [Image(path=f), caption]

    @mcp.tool(annotations=RO, structured_output=False)
    async def animate(project: str, kind: str = "turntable", from_rev: int | None = None, to_rev: int | None = None,
                      to_values: dict[str, float] | None = None, frames: int = 24, fmt: str = "gif") -> list:
        """Make motion from real geometry. kind="turntable" spins the head revision. kind="morph" builds every in-between
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
        """What changed between two revisions: parameters, features, interfaces, stability, fit."""
        st = studio()
        def go():
            p = st.load(project)
            cand = st.head_summary(p, b)
            return {"a": a, "b": b, "note_a": st.rev(p, a)["note"], "note_b": st.rev(p, b)["note"],
                    **impact_digest(st.impact(p, st.rev(p, b)["values"], cand, base_rev=a))}
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def geometry_diff(project: str, a: int, b: int | None = None) -> dict:
        """What changed in the solid between revision a and b (default the head): material added (b minus a) and removed
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

    @mcp.tool(annotations=RW)
    async def add_feature(project: str, kind: str, at: list[float], normal: list[float], size: str = "M3",
                          hole: str = "tapped", height: float | None = None, outer_d: float | None = None,
                          hole_d: float | None = None, hole_depth: float | None = None, length: float | None = None,
                          thickness: float | None = None, width: float | None = None, lip: float | None = None,
                          lip_height: float | None = None, up: list[float] | None = None, allow_strain: float | None = None,
                          expect_head: int | None = None) -> dict:
        """Add a standard feature on a flat face of a Python design, written into its source as a feature block and built
        in the kernel as a new revision. kind="boss": a screw boss (size M2..M5; hole tapped = ISO tap drill, clearance =
        ISO 273, insert = a typical heat-set insert hole; height, outer_d, hole_d, hole_depth in mm). kind="snap_hook":
        a cantilever snap-fit hook (length, thickness, width, lip = undercut, lip_height; up = the lip's direction).
        at / normal: a point on the face and its outward normal (analyze_selection gives them). Returns the new head, the
        features and check rows: boss wall vs the nozzle; hook strain 1.5·t·y/L² vs allow_strain (a rule of thumb when
        not given). Remove one with remove_feature."""
        st = studio()
        o = {k: v for k, v in dict(size=size, hole=hole, height=height, outer_d=outer_d, hole_d=hole_d, hole_depth=hole_depth,
                                   length=length, thickness=thickness, width=width, lip=lip, lip_height=lip_height, up=up).items()
             if v is not None}
        def go():
            from . import feature_helpers as fh
            p = st.load(project)
            out = fh.add(st, p, kind, at, normal, expect_head, "agent", **o)
            out["checks"] = fh.checks(out["features"][-1], st.slicer_info(p=p).get("nozzle_mm"), allow_strain)
            return out
        return await _run(go)

    @mcp.tool(annotations=RW)
    async def remove_feature(project: str, feature_id: str, expect_head: int | None = None) -> dict:
        """Remove a feature added with add_feature (feature_id like "boss_1" or "hook_1"). A new revision."""
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
        """How to design a replacement for a broken part from the person's photo: find the scale from a reference
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
        """Assembly instructions as a PDF from the design's assembly declaration: a parts page with computed volumes, then
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
        """Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from
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
        """Goal seek: search parameter ranges for the best design that meets constraints. Every candidate is built by the kernel.
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
    async def open_bench(project: str | None = None, open_browser: bool = True) -> dict:
        """The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases."""
        url = _bench(f"#p={project}" if project else "")
        if not url:
            raise ToolError("The bench is not running in this server (started with --no-bench, or no free port).")
        if open_browser:
            webbrowser.open(url)
        return {"url": url, "opened": open_browser}

    @mcp.tool(annotations=RO)
    async def brief_presets(preset: str = "") -> dict:
        """Intake guidance for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure,
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
    async def reconstruct(project_or_file: str, tolerance: float = 0.02, layer: int = 2, name: str | None = None,
                          reference: str | None = None, ctx: Context = None) -> dict:
        """Turn a mesh (STL, OBJ or 3MF) into editable CAD as a new design. project_or_file: an absolute path to the
        mesh, or a project id whose imported mesh reference to use (reference: which one; default the first mesh).
        Layer 0 is always built: the mesh as an exact solid (Hausdorff at float precision). Layer 1 (beta) replaces
        facets with planes, cylinders, cones, spheres and tori where they fit within `tolerance` mm; the rest stay
        frozen facets. Layer 2 (beta) writes a build123d recipe with Params (one extrusion or revolution, holes
        snapped to standard sizes, patterns) and is used only if its rebuild is within the limit. Returns the new
        project and the verification (two-sided Hausdorff, volume delta, % parametric area). Values are computed from
        the mesh; nothing is decimated and every repair is listed. Large meshes take minutes."""
        st = studio()
        progress = None
        if ctx is not None:
            def progress(d):
                try:
                    anyio.from_thread.run(ctx.report_progress, float(d.get("fraction", 0)), 1.0, str(d.get("text", "")))
                except Exception:
                    pass

        def go():
            kw = {"tolerance": tolerance, "layer": layer, "on_progress": progress}
            if name:
                kw["name"] = name
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
        act(out["project"], "design", f"Reconstructed a mesh as CAD (Layer {out['summary']['layer']})", ctx)
        return {**out, "evidence": "computed (Form Studio's kernel compared the result with the mesh)",
                "next": "get_project to read the design; get_design_source to edit the recipe or add features."}

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
        """An analysis map of the part, computed from the real geometry: a picture with its legend, and the statistics.
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
        """Measure the part. Points are [x, y, z] in millimetres in the design frame.
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
                raise StudioError("Give from_point and to_point, or at.", "Each is [x, y, z] in millimetres.")
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
        """The selections the person named and kept on this design (annotations): name, note, the revision they were
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
        """Colour (#rrggbb) and material of the whole design (part="") or of one part (an assembly part id from
        get_project / render). Materials: PLA, PETG, ABS, ASA, TPU, PA (nylon), PC, PLA-CF, PETG-CF, PA-CF. Form Studio draws the
        colour, writes it into its 3MF and adds material notes to the checks (heat, sunlight, warping, flexible, fibre-filled);
        stored in the same fields set_part_print uses (project material, parts.<id>.material), so the slicer picks the matching filament. Leave an argument out to keep it; clear=True removes both."""
        st = studio()
        from . import materials
        def go():
            had = materials.fingerprint(st.load(project))
            out = materials.set_appearance(st, project, part, None if clear else (color if color is not None else "keep"),
                                           None if clear else (material if material is not None else "keep"), by=_origin(ctx))
            if materials.fingerprint(st.load(project)) != had and st.load(project).get("auto_run", True):
                st.run(project)
            return {"appearance": out, "materials": [{"id": k, "label": v["label"], "heat_c": v["heat_c"]} for k, v in materials.MATERIALS.items()]}
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

    @mcp.prompt(title="Design a printable part")
    def design_part(goal: str) -> str:
        """A guided FORM session for a printable part."""
        return (f"Goal: {goal}\n\n"
                "Use the Form Studio tools. 1) form_overview, then describe_recipe for the closest recipe. "
                "2) Ask me for any 'brief' dimensions you would otherwise assume, and how I measured them. "
                "3) create_project, then render(view='sheet') and look at it. "
                "4) For each change: preview_change, render with values=..., then commit_change with expect_head. "
                "5) run_pipeline and read the checks, fit model and next_best_actions. Prefer cheap evidence "
                "(measure, coupon, test piece) over guessing. 6) request_release and give me the bench link. "
                "Report slices as simulated and fit as modelled; never claim a print succeeded.")

    # ---- print simulation, cost, plate packing -------------------------------------------------
    @mcp.tool(annotations=RO, structured_output=False)
    async def print_simulation(project: str, layer: int | None = None, only: list[str] | None = None,
                               plate: int | None = None, ctx: Context = None) -> list:
        """Look at the sliced print as it would stand at the end of `layer` (1-based; default: finished). Returns a
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
        """Filament, electricity and machine-time cost of the current slice, per plate and for `copies`, plus the same
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
        """How the design's printed parts go onto plates: each part as it lies on its own (orientation, size, material),
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
        """Print settings for one printed part of a multi-part design (part ids from plate_plan): orientation (a named
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
        """Do `copies` of this design fit on one plate? Bounding-box packing with a gap (default 6 mm) and 90° turns,
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
                           fast: bool = False, layer_lines: bool = True, ctx: Context = None) -> list:
        """A realistic-looking render of the current revision's exported STL, made by Blender headless (if installed).
        preset: studio (soft box, light backdrop) | desk (wooden desk) | dark (graphite, rim light).
        material: matte (PLA) | petg (gloss) | silk (silk PLA). color: hex, e.g. "#3d6fb6".
        layer_lines draws faint lines at the slicer's layer height when a process preset is selected.
        fast=True uses EEVEE instead of Cycles. Cached per geometry and settings. This is an illustration with
        invented light and material, not a photo of a print: never present it as evidence of anything."""
        st = studio()
        from . import photo
        m = await _run(lambda: photo.render(st, st.load(project), preset, material, color, fast, layer_lines))
        f = st.dir(project) / "artifacts" / "photo" / m["file"]
        act(project, "look", f"Rendered in Blender ({m['preset_label']}, {m['finish_label']})", ctx)
        lh = m["layer"]
        caption = (f"{m['label']}. r{m['rev']:02d}, {m['preset_label']} · {m['finish_label']} {m['color']}, "
                   f"{m['engine']} on {m['device']}, {m['samples']} samples, Blender {m['blender']}"
                   + (f", layer lines at {lh['mm']:g} mm ({lh['note']})" if lh.get("mm") else "")
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
        """The head and every saved variant side by side: size and volume (computed), print time and grams (simulated,
        only when the variant is a revision with a current slice), fit yield (modelled), checks, and each variant's
        differences from the head."""
        st = studio()
        from . import variants
        return await _run(lambda: variants.board(st, st.load(project)))

    @mcp.tool(annotations=RO, structured_output=False)
    async def share_card(project: str, picture: str = "model", ctx: Context = None) -> list:
        """A 1600 x 900 share image of the head revision: the part with dimension lines, its name, size and volume
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
        return row

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False))
    async def delete_project(project: str, ctx: Context = None) -> dict:
        """Delete a project by moving its whole folder to the trash folder inside the projects folder
        (<projects folder>/.trash/<id>-<UTC time>). Nothing is erased, and moving the folder back restores it, but the
        project disappears from FORM. Ask the user first and only call this after they said yes to deleting this
        project. Returns {ok, id, trash}: tell the user the trash path."""
        st = studio()
        res = await _run(st.delete_project, project)
        act(None, "project", f"Moved {project} to the trash folder", ctx)
        return res

    # ---- printers: every printer the user set up in any installed slicer (engine workstream, form/printers.py) ----
    @mcp.tool(annotations=RO)
    async def list_printers(project: str | None = None, printer: str | None = None) -> dict:
        """Every printer set up in every installed slicer (the user's own presets and the system printers they enabled),
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
    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def ask_user(question: str, choices: list[str] | None = None, multi_select: bool = False,
                       allow_text: bool = True, why: str = "", kind: str = "question") -> dict:
        """Ask the person one question and wait for the answer. Use it only when the answer changes the design
        and you cannot find it yourself: a measurement that sets a fit or a load, or an intent you cannot tell
        apart (which device, which side opens). At most a few questions per task; ask them one at a time.
        choices: up to 8 short options shown as buttons (multi_select lets the person pick several);
        allow_text lets them type their own answer; why: one line on what the answer changes.
        kind="confirm" shows an approval card (choices default to Yes / No) before an action the person
        should agree to. Returns {answered, answer, choices, text} or, when nobody answered, {answered: false,
        reason, note}: then continue with safe assumptions marked assumed. Outside Form Studio's chat nobody
        can answer here and the result tells you to ask in your own interface."""
        from . import ask as ask_mod
        import os as _os
        try:
            q = ask_mod.question(question, choices, multi_select, allow_text, why, kind)
        except ask_mod.AskError as e:
            raise ToolError(str(e))
        folder = _os.environ.get(ask_mod.ENV_DIR)
        if not folder:
            return ask_mod.unreachable(q)
        timeout = ask_mod.timeout_from_env()
        qid = ask_mod.post(Path(folder), q, timeout)
        parent, t0 = _os.getppid(), time.time()
        while True:
            st_, extra = ask_mod.state(Path(folder), qid)
            if st_ != "open":
                return ask_mod.result(q, st_, extra)
            if time.time() - t0 > timeout:
                ask_mod.close(Path(folder), qid, "timeout")
            elif _os.getppid() != parent:            # the agent that asked is gone
                ask_mod.close(Path(folder), qid, "ended")
            await anyio.sleep(0.25)

    @mcp.tool(annotations=RW)
    async def ask_measurement(project: str, param: str, question: str, where: str = "", unit: str = "mm",
                              tolerance_mm: float | None = None, diagram: dict | None = None, image: str | None = None,
                              mark: list[float] | None = None) -> dict:
        """Ask the person to measure one dimension of the design, and wait. Form Studio shows a measurement card:
        the question, where to measure (where, e.g. "across the widest part of the phone, without the case"), the
        precision that matters (tolerance_mm), a diagram ({"shape": "box"|"cylinder"|"hole"|"gap"|"thickness",
        "axis": "x"|"y"|"z"|"d"}) and optionally a picture: image is an absolute path to a PNG or JPEG (a render, or
        the person's photo) with mark = [x0, y0, x1, y1] (0..1) outlining where to measure. The person types the
        number and says how they measured it (calipers, ruler, tape, or estimate). The answer becomes a new revision
        of the design with provenance measured (calipers sigma 0.05 mm, ruler 0.5, tape 1.0) or, for an estimate,
        assumed. One question at a time. Returns {answered, value, unit, method, source, rev}; when nobody answered,
        {answered: false, reason, note}. Outside Form Studio's chat it tells you to ask in your own interface."""
        from . import ask as ask_mod
        from . import start
        import os as _os
        import shutil as _sh
        st = studio()

        def check():
            p = st.load(project)
            head = st.rev(p)
            if param not in head["values"]:
                raise StudioError(f"“{param}” is not a parameter of {project}.", "get_project lists the parameters.")
            return head["values"][param]
        current = await _run(check)
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
            return {**ask_mod.unreachable(q), "param": param, "current": current, "where": q["where"]}
        Path(folder).mkdir(parents=True, exist_ok=True)
        if ext:
            _sh.copyfile(Path(image).expanduser(), Path(folder) / f"{qid}.{ext}")   # before the question appears
        timeout = ask_mod.timeout_from_env()
        ask_mod.post(Path(folder), q, timeout, qid=qid)
        parent, t0 = _os.getppid(), time.time()
        while True:
            st_, extra = ask_mod.state(Path(folder), qid)
            if st_ != "open":
                break
            if time.time() - t0 > timeout:
                ask_mod.close(Path(folder), qid, "timeout")
            elif _os.getppid() != parent:
                ask_mod.close(Path(folder), qid, "ended")
            await anyio.sleep(0.25)
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
        """For a new idea: build 2-4 genuinely different concepts as real designs, so the person can pick one.
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
        res["note"] = ("Stop here and let the person pick in Form Studio's concepts view. If they pick in words, call "
                       "pick_concept(group, project). If they ask for a mix (\"the base of A with the hook of C\"), call "
                       "propose_concepts(name, [one mixed concept], group=\"" + res["id"] + "\").")
        return res

    @mcp.tool(annotations=RW)
    async def pick_concept(group: str, project: str, keep_others: bool = False, ctx: Context = None) -> dict:
        """The person picked a concept (in words; in the app they pick on the board). The picked project takes the
        group's name and records the choice; the other concepts move to the trash (recoverable) unless keep_others.
        Then refine the picked design with update_design. Only call this when the person said which one."""
        from . import concepts as concepts_mod
        st = studio()
        return await _run(concepts_mod.pick, st, group, project, keep_others, _origin(ctx).replace("agent:", "") or "agent")

    @mcp.tool(annotations=RW)
    async def dismiss_concepts(group: str, keep: str = "all", ctx: Context = None) -> dict:
        """The person wants none of the concepts picked: close the group without a pick. keep="all" keeps every
        concept as an ordinary design; keep="none" moves them all to the trash (recoverable). Only call this when
        the person said so."""
        from . import concepts as concepts_mod
        st = studio()
        return await _run(concepts_mod.dismiss, st, group, keep, _origin(ctx).replace("agent:", "") or "agent")

    @mcp.tool(annotations=RO)
    async def list_concepts(group: str = "") -> dict:
        """Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>."""
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
        """Ideas for what this person might design next, ranked from what they already design (the building blocks
        and kinds of part in their projects, their printer and material, what they pinned or used):
        {prompts: [{id, text, source, pinned}], briefs: [...]}. Offer them as suggestions when the person asks what to
        make; they edit the list with `form starters`."""
        from . import starters
        st = studio()
        return await _run(starters.for_studio, st)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    async def recipe_library(q: str = "", section: str = "", tag: str = "") -> dict:
        """Search the recipe library: built-in recipes, recipes the person installed ("mine") and the community index
        on the project website, to find a building block to start a design from. section: builtin | mine | community.
        Installing code is the person's decision and happens only with `form recipes install`, after they review the
        source and its SHA-256."""
        from . import recipe_lib
        st = studio()
        def go():
            lib = recipe_lib.everything(st.root, st.recipes.builtins())
            return {"recipes": recipe_lib.search(lib["items"], q, section, tag), "community_error": lib["community_error"]}
        return await _run(go)

    # ---- recipe sharing (form/recipe_share.py): packages and submissions are written locally; nothing is posted ----
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
    async def prepare_recipe_submission(recipe: str, folder: str | None = None) -> dict:
        """Prepare an installed recipe for the community gallery: the community/recipes/<id>/ folder (written into
        `folder` when given), what the gallery's checks would refuse, and the link to GitHub's recipe issue form with
        the fields filled in. Never open or post it: give the link to the person, who submits it themselves."""
        from . import recipe_share
        st = studio()
        def go():
            r = recipe_share.prepare(st, recipe)
            out = {k: r["submission"][k] for k in ("folder", "meta", "problems", "notes")}
            out["issue_url"], out["omitted_from_link"] = r["submission"]["issue"]["url"], r["submission"]["issue"]["omitted"]
            if folder:
                out["saved"] = recipe_share.save_submission(st, recipe, folder)
            return out
        return await _run(_home, go)

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
        return res

    @mcp.tool(annotations=RO)
    async def export_conversation(conversation: str, format: str = "md") -> dict:
        """A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again)."""
        from . import bundle
        st = studio()
        if format == "json":
            return await _run(_home, bundle.conversation_json, st.root, conversation)
        return {"markdown": await _run(_home, bundle.conversation_markdown, st.root, conversation)}

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
