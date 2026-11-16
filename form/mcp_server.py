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
FORM designs 3D-printable parts from parametric recipes and keeps an honest record of what is known.

Workflow: form_overview -> describe_recipe -> create_project (or get_project) -> preview_change ->
render (look at it) -> commit_change -> run_pipeline -> get_project (gate, checks, next actions) ->
request_release (a person approves on the bench).

Rules:
- Units are mm, degrees, grams. Only change parameters that describe_recipe lists.
- Always preview_change before commit_change; pass expect_head so you never overwrite a newer revision.
- Provenance is evidence. Mark a value "measured" only when the user measured it and told you the number.
  Never invent physical results; record_physical_result is only for what the user reports.
- A slice is a simulation, not a print. Fit yield is a model. Say so when you report them.
- You cannot approve a release. request_release returns a bench link for the user.
- Nothing here starts a print or sends files anywhere.
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
    mcp = MCPServer("form", title="FORM print-design studio", version=__version__, instructions=INSTRUCTIONS)
    RO = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    RW = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

    @mcp.tool(annotations=RO)
    async def form_overview() -> dict:
        """Start here. Engine, slicer, printer, available recipes, existing projects and the bench URL."""
        st = studio()
        def go():
            env = st.environment()
            return {
                "version": env["version"], "kernel": env["kernel"], "printer": env["printer"],
                "slicer": {k: env["slicer"].get(k) for k in ("kind", "available", "reason", "version")} |
                          {"presets": {k: v["name"] for k, v in env["slicer"].get("presets", {}).items()}},
                "calibration_profile": env["profile"],
                "recipes": [{"id": r.id, "title": r.title, "summary": r.summary} for r in st.recipes.builtins().values()],
                "projects": [{k: q.get(k) for k in ("id", "name", "recipe", "head", "approved_rev")} for q in st.list()],
                "data_dir": env["data_dir"], "bench": _bench(),
            }
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def setup_status() -> dict:
        """What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap.
        Never run a fix without asking the user; the simplest path is to ask them to run `form setup` in a terminal."""
        def go():
            from . import setup
            return {"items": [i.public() for i in setup.check(studio().cfg)],
                    "tell_the_user": "Run `form setup` in a terminal to fix these interactively."}
        return await _run(go)

    @mcp.tool(annotations=RO)
    async def describe_recipe(recipe: str) -> dict:
        """Parameters (unit, range, group, the feature each one drives), features and what the recipe checks."""
        st = studio()
        if recipe not in st.recipes:
            raise ToolError(f"Unknown recipe “{recipe}”. Known: {', '.join(st.recipes)}.")
        r = st.recipes[recipe]
        pub = r.public()
        return {"id": r.id, "title": r.title, "summary": r.summary,
                "parameters": [{k: pp[k] for k in ("key", "label", "unit", "default", "min", "max", "group", "feature", "doc") if k in pp}
                               for pp in pub["params"]],
                "features": [{"id": f.id, "label": f.label, "role": f.role} for f in r.features],
                "fit_interface": r.fit,
                "groups": {"brief": "facts about the world (measure these)", "interface": "how parts meet",
                           "form": "free design choices"}}

    @mcp.tool(annotations=RO)
    async def design_guide() -> dict:
        """Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter,
        holder, mechanism...). Returns the contract for a design written as code, the rules, and a complete example
        that builds. Then call create_design."""
        from .design_guide import EXAMPLE, GUIDE
        return {"guide": GUIDE, "example_source": EXAMPLE,
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
                            ctx: Context = None) -> dict:
        """Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass,
        built with build123d. FORM builds it, and with run=True exports, checks and slices it. Load or build errors come
        back with the line and a hint; fix and call again. Then render(view="sheet") and look at it.
        language="openscad": source is an OpenSCAD file; parameters come from Customizer comments (`w = 40; // [20:1:120]`).
        OpenSCAD output is a mesh: no STEP, no B-rep checks (reported as not available, never faked).
        references: absolute paths of STEP/STL parts to import first, so a Python design can use self.reference("name.step")."""
        st = studio()
        act(None, "design", f"Writing a new design: {name}", ctx)
        p = await _run(st.create_design, name, source, brief, values, language, references)
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
        project's current one ("python" or "openscad")."""
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
                             run: bool = True, ctx: Context = None) -> dict:
        """Create a project from a built-in recipe (dock, gridfinity, hook, planter, coupon, enclosure, gear_pair, knob).
        For anything else, write a design: design_guide, then create_design. values override recipe defaults (all start as 'assumed').
        With run=True the solid, exports and checks are built (and sliced if a slicer is available)."""
        st = studio()
        p = await _run(st.create, name, recipe, brief, values)
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
        view: iso, iso_back, front, back, left, right, top, bottom, or "sheet" (four views at once).
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
            views = ["iso", "front", "top", "right"] if view == "sheet" else [view]
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
    async def checkout_revision(project: str, rev: int) -> dict:
        """Make an earlier revision the head again (nothing is deleted). Outputs for it are reused if still cached."""
        st = studio()
        await _run(lambda: st.checkout(st.load(project), rev))
        jid = st.run(project)
        await _wait_job(st, jid, 45)
        return await _run(digest, st, project)

    @mcp.tool(annotations=RW)
    async def set_print_setup(project: str, orientation: str | None = None, fit_gap_min_mm: float | None = None,
                              fit_gap_max_mm: float | None = None, auto_slice: bool | None = None) -> dict:
        """Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted), the acceptable total fit gap
        window, and whether the pipeline slices automatically. The checks include an orientation comparison table."""
        st = studio()
        body: dict[str, Any] = {}
        if orientation is not None:
            body["orientation"] = orientation
        if fit_gap_min_mm is not None or fit_gap_max_mm is not None:
            cur = (await _run(st.load, project))["fit"]
            body["fit"] = {"gap_min": fit_gap_min_mm if fit_gap_min_mm is not None else cur["gap_min"],
                           "gap_max": fit_gap_max_mm if fit_gap_max_mm is not None else cur["gap_max"]}
        if auto_slice is not None:
            body["auto_slice"] = auto_slice
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
        st = studio()
        def go():
            p = st.load(project)
            info = st.side_slice(p, "test_piece")
            d = st.dir(p["id"]) / "artifacts" / "side" / info["key"]
            return {"piece": info["piece"]["label"], "stl": str(d / info["stl"]), "gcode": str(d / info["gcode"]),
                    "time_min": round(info["time_s"] / 60), "filament_g": info["filament_g"], "evidence": "simulated slice"}
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
        Agents cannot approve: approval happens on the bench, where the user reviews checks and acknowledges warnings."""
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
                                    "FORM writes a release folder with STEP, STL, 3MF, G-code, MANIFEST.json and REPORT.md.")
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
        """Brief templates for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure,
        car accessory): the questions worth asking, environment defaults (temperature, humidity, UV, load), a material to
        start from and the checks to plan for. Defaults are assumptions to confirm with the user, never measurements."""
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
                "evidence": "computed (read by FORM's kernel from the file)",
                "use_in_design": f'self.reference("{rec["file"]}") returns it as a build123d shape in the same coordinates.',
                "note": "The part is drawn where its file puts it. Model your design around those coordinates, or move "
                        "the reference inside your design code (Pos(...) * self.reference(...))."}

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
                    "note": "The spreadsheet records values; the STEP is a frozen solid. Edit the design in FORM and export again."}
        return await _run(go)

    @mcp.prompt(title="Design a printable part")
    def design_part(goal: str) -> str:
        """A guided FORM session for a printable part."""
        return (f"Goal: {goal}\n\n"
                "Use the FORM tools. 1) form_overview, then describe_recipe for the closest recipe. "
                "2) Ask me for any 'brief' dimensions you would otherwise assume, and how I measured them. "
                "3) create_project, then render(view='sheet') and look at it. "
                "4) For each change: preview_change, render with values=..., then commit_change with expect_head. "
                "5) run_pipeline and read the checks, fit model and next_best_actions. Prefer cheap evidence "
                "(measure, coupon, test piece) over guessing. 6) request_release and give me the bench link. "
                "Report slices as simulated and fit as modelled; never claim a print succeeded.")

    # ---- print simulation, cost, plate packing -------------------------------------------------
    @mcp.tool(annotations=RO, structured_output=False)
    async def print_simulation(project: str, layer: int | None = None, only: list[str] | None = None,
                               ctx: Context = None) -> list:
        """Look at the sliced print as it would stand at the end of `layer` (1-based; default: finished). Returns a
        picture drawn from the slicer's G-code toolpaths, coloured by line type, plus statistics: z, line types in
        that layer, whether it has bridges or overhang walls, slicer time elapsed and remaining, and the list of
        bridge and overhang layers. only: draw just these line types (e.g. ["Bridge", "Overhang wall"]).
        Needs a current slice (run_pipeline). This is a simulation of the slice, not a print: say so."""
        st = studio()
        def go():
            from . import simulate, toolpath
            p = st.load(project)
            tp = toolpath.for_project(st, p)
            n = tp.layers if layer is None else max(1, min(tp.layers, int(layer)))
            bad = [t for t in (only or []) if t not in tp.types]
            if bad:
                raise StudioError(f"Unknown line type “{bad[0]}”.", "This slice has: " + ", ".join(tp.types))
            cache = st.dir(p["id"]) / "artifacts" / "renders"
            cache.mkdir(parents=True, exist_ok=True)
            f = cache / f"sim-{st.keys(p)['slice']}-{n}-{H(sorted(only or []))}.png"
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
    async def pack_plate(project: str, copies: int = 1, spacing_mm: float | None = None) -> dict:
        """Do `copies` of this design fit on one plate? Bounding-box packing with a gap (default 6 mm) and 90° turns,
        on the selected printer's bed. Returns the layout and the most copies this packer can place. Computed by FORM;
        the slicer arranges again when it slices, and FORM's export stays one plate."""
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

    return mcp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="form-mcp", description="FORM MCP server (stdio)")
    ap.add_argument("--no-bench", action="store_true", help="do not serve the local bench web page")
    a = ap.parse_args(argv)
    mcp = build()
    st = studio()
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
