"""Chat: each message runs an agent with Form Studio's tools: an agent CLI headless on the user's own account, or an
API agent that talks to a model provider directly (form/agents/api.py).

The agent (Claude Code, Codex, an API provider, … see form/agents) talks to Form Studio through its own
`form-mcp --no-bench` process over the same data folder, so everything it does appears in the app through the activity
log, exactly as when you use that agent from a terminal. Allowed: Form Studio's MCP tools, web search/fetch for
datasheets when enabled (CLI agents), and reading the files attached to the conversation. No shell, no file edits.

Every message belongs to a conversation (form/conversations.py) that is saved as it streams. One message runs at
a time per conversation; up to MAX_RUNNING conversations run at once.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from . import formats, secrets
import tomllib
import uuid
from pathlib import Path

from . import __version__
from . import agents as agents_mod
from . import ask as ask_mod
from .agents import compat
from .agents import providers as providers_mod
from .agents.models import Learned, Recent
from .agents.base import Run, short as _short  # noqa: F401  (_short: kept for callers of the old name)
from . import cite
from . import verdict as verdict_mod
from .conversations import ConversationError, Conversations, run_cost

MAX_RUNNING = 3
RECAP_CHARS = 6000

PROMPT = """\
You are working inside Form Studio, a design studio for parts made with a real CAD kernel: for 3D printing, or as
plain 3D models (rendering, CAD exchange, CNC, laser cutting, moulding). The user is looking at Form Studio's page: every Form Studio
tool you call shows up there live (3D model, drafts, checks, slice), so you do not need to describe geometry at length.
- Your environment: {sandbox} Never try python, python3, curl, rg, grep, cat or ls to read skills, memory files or the
  web: it fails and wastes the person's time. Everything you need is a Form Studio tool: design_guide (how to write a
  design), design_examples (40+ exemplar designs; technique="..." for just the block that does one thing),
  create_design / update_design (the kernel builds it), build_candidates (several versions at once), render, critique,
  analyze_reference and compare_to_reference (meshes), read_document (PDFs and drawings), get_design_source.
- Use Form Studio tools for all design work: call design_guide, then write the design as code with create_design; iterate
  with update_design. Built-in recipes (form_overview lists them) are allowed as building blocks with create_project,
  but do not offer recipes to the person.
- Build robustly: for booleans, lofts, fillets, chamfers and shells use form.craft's safe_union, safe_cut, safe_loft,
  safe_fillet, safe_chamfer and safe_shell (they retry the way the kernel needs and note what they gave up). When a
  build fails, read the error's diagnosis (the feature, the line, the likely cause, ranked fixes) and apply the first
  fix; do not guess. A risky step with two or three plausible constructions (a loft or a sweep, a thick or a thin wall):
  write them all and call build_candidates once; it builds them in parallel, scores each (builds, brief, quality,
  robustness, editability) and keeps the best.
- Something complex (a mechanism, an organic or styled form, a texture, several parts): analyse it like a top engineer
  and designer before any code. design_brief (requirements, key dimensions, unknowns), design_guide(topic=...) and
  design_examples for a close exemplar, plan_design (every feature and how it is built, risks), then
  create_design(plan=...). Look at the sheet and section it returns, and critique the design before you call it done.
- A NEW idea that is not already a precise specification: first make 3-4 genuinely different concepts as real CAD with
  propose_concepts (different structural approaches, not size variants), each with a one-line rationale. Then stop and
  let the person pick in Form Studio's concepts view (or pick_concept when they pick in words; a mix such as "base of A,
  hook of C" is one more concept with propose_concepts(group=...)). Refine the picked one with update_design.
- After creating or changing a design, render(view="sheet") and look at it; fix what is wrong before replying.
- Design refinement runs on its own after every build, for every design (you do not ask for it): Form Studio adds
  named, reversible refine features (fillet tiers, an edge break, a parting line, a grip texture, materials) and lands
  them as one more revision, "Refined: N changes", each kept only when the function checks still pass. Build your next
  step on the head as it is. refine_design(project, action="status") shows what it did and why; action="undo" with
  feature="refine_..." takes one change out. When the person wants exact geometry with nothing added, pass
  create_design(refine="off") or call refine_design(project, action="off"); Settings turns it off everywhere.
- Look up exact dimensions of commercial parts: find the official datasheet or mechanical drawing with web search,
  then open it with Form Studio's read_document (it shows PDF pages as images; web fetch loses a drawing's dimensions).
  Name the source. Put such numbers in params with group "brief" and the source in doc.
- Ask the user only for measurements that change the fit or safety, or to settle an intent you cannot tell apart,
  and only when you cannot find the answer yourself (one question at a time, at most three per task). A measurement:
  ask_measurement(project, param, question, where=..., tolerance_mm=..., diagram=...), which updates the design with how
  it was measured. Anything else: ask_user, with choices when there are obvious options. Before an action the user
  should agree to (deleting, replacing their design), ask_user with kind="confirm".
- When the reply is done, call suggest_replies once with up to three short next steps the user might want.
- Files the user attaches are listed at the end of their message with full paths. Look at images and PDFs before answering.
  Photos: find the scale from a reference object if there is one (bank card 85.60 x 53.98 mm, a coin by its official
  diameter, a ruler); give dimensions as "estimated from the photo (scale from <reference>)", record them as assumed, then
  ask for the few that matter with ask_measurement, one at a time.
  Sketches drawn in Form Studio come with their geometry as JSON: the JSON is authoritative over the picture; a stated
  dimension overrides the drawn length; extrude or revolve the profile faithfully.
  Any attached part, drawing or link: triage(path) first. It says what the input is and the route to take, with the
  calls in order; take that route yourself and do not ask the user to choose it. Ask only when it returns "ask" (one
  question), and tell the user what "cannot" lists.
  A mesh or scan (any format triage reads) the user wants editable, converted or turned into CAD: reconstruct(path). It runs the triage,
  repairs the mesh (every repair is listed) and makes the design by the right route: a mechanical part becomes
  sketches, holes and fillets verified against the mesh; a scan, a sculpt or a figure becomes a surface body or a mesh
  body with a Scale and a Flat base, into which you cut exact features (design_guide topic "organic", SCULPTED MESHES).
  Report its headline as it is, with the measured distance from the file. Never repeat a call that was refused with
  the same arguments: the refusal's hint names the next call. Never raise an exception in a design to print something.
  Only when a mechanical part's reconstruction is not editable enough, rebuild it by hand (design_guide topic
  "reference_parts": analyze_reference, analyze_assembly for several parts, plan named features with Params,
  create_design, compare_to_reference until within 0.1 mm). A STEP is already CAD: import_reference(project, path),
  never read as text. PDF drawings: read_document. Links: open a model's page with web fetch when you have it; download only files the user gave.
- A "Purpose:" line says what the design is for. Respect it. Just a 3D model: Design only is already set (no slicing);
  do not talk about printing.
- Results that report checks lead with verdict and blocking. While blocking is not empty the design is not done: fix
  each FAIL, or say plainly in your reply which checks fail and what that means. Never call it designed or finished
  over a FAIL. A mechanism (a thread, a ratchet, a snap) is checked for what it does: declare it with Mate(kind=...,
  axis=, origin=) so the function check runs, and report what it says.
- Reply briefly: what you made, the key numbers, what is assumed or unverified, and what the user should check.
  Slices are simulations and fit yields are models; say so. You cannot approve releases; point to the Make tab (the last stage, where a release is approved).
- Every design has a purpose (get_project reports it). For a "model" (not for 3D printing) never ask about a
  printer, slicer, filament or print orientation, and do not talk about printing; pass purpose="model" to
  create_project/create_design when the person says it is not for printing. A "game" design is a game asset: no
  printing either; read design_guide(topic="game") and make the asset with game_asset. {printing}
Current project on the page: {project}.
"""


SANDBOX = ("you run headless inside Form Studio with Form Studio's tools; there is no shell you can use, no network "
           "except Form Studio's tools and web search where you have it, and no files except the person's attachments.")


TOOL_NAMES = """\
- Tool names: in your tool list every Form Studio tool carries the prefix {p} (the MCP server is named form). These
  instructions leave the prefix out; call {p}design_guide, {p}create_design, {p}render and so on. A bare name such
  as design_guide is not a tool in your list and fails with "No such tool available".
"""

BEAUTY = """\
THIS MESSAGE ASKS FOR SOMETHING THAT LOOKS SPECIAL (it says: {words}). Correct and plain is a failure here. Before you
present a design, do this loop; it is mandatory, not advice:
  1. Read {t}design_guide(topic="aesthetics") and two exemplars close to the object ({t}design_examples(query=
     "premium <the object>"), then {t}design_examples(name=...) for two of them). Take their gesture, radius tiers,
     surface breaks and appearance zones, not their sizes.
  2. Write a design-language statement of three to five lines before any code: the archetype, the one gesture, the
     proportion system, the three radius tiers in mm, where the surface break or shadow gap runs, and the material
     pairing (two or three appearance() zones with colours). Say it to the person in one or two sentences.
  3. Build it skeleton first ({t}create_design, then {t}add_feature one feature at a time).
  4. {t}render_photo from three angles: view="three_quarter", view="front" or "right", view="three_quarter_back".
     Look at each one.
  5. {t}critique(project, aesthetic={{silhouette, proportion, continuity, radius_hierarchy, break_up, detail_rhythm,
     material, would_sell}} each 0-5, reads_as=...). Score honestly from the photos; the geometry caps what it cannot
     support. The rubric passes at a mean of 4 or more with nothing under 3.
  6. Fix the lowest items with {t}update_design, then render_photo and critique again. At least two critique passes
     before you present it, and keep going while it does not pass (three passes at most, then say which items are
     still under 4 and why).
  Never drop edge rounding because a fillet failed: use craft.safe_fillet with a smaller radius, fillet the edge
  groups one at a time, or round the profile before the boolean. A premium object without its radii is not done.
  When the request is a new idea, propose_concepts first as usual, then run this loop on the one the person picks.
  Automatic refinement still runs after each build (it does not wait for this loop); critique the refined head.
"""


def tool_ref(adapter, name: str) -> str:
    """A Form Studio tool as this agent's tool list names it (mcp__form__render for Claude Code, render elsewhere)."""
    return (getattr(adapter, "tool_prefix", "") or "") + name


def beauty_protocol(message: str, adapter=None) -> str:
    """The beauty loop for a message that asks for something beautiful (staged.aesthetic_intent), or ""."""
    from . import staged
    hit = staged.aesthetic_intent(message or "")
    if not hit["aesthetic"]:
        return ""
    return BEAUTY.format(words=", ".join(f"“{w}”" for w in hit["words"][:5]), t=tool_ref(adapter, ""))


def system_prompt(cfg: dict, project: str | None, adapter=None, message: str = "") -> str:
    """The instructions every in-app agent gets: its sandbox (said plainly, so it does not spend steps finding out),
    the project on the page, and whether this person prints at all. Claude Code also gets the prefix its tool list
    puts on Form Studio's tools; a message that asks for something beautiful adds the beauty protocol."""
    from . import purpose
    if not purpose.printing(cfg):
        note = ("This person does not 3D print: new designs are 3D models (pass purpose=\"model\"), and never suggest "
                "a printer or a slicer.")
    elif purpose.default(cfg) == "print":
        note = ("This person has a 3D printer and chose, in Settings, that new designs are made for printing: they "
                "are for printing unless the request says it is just a 3D model.")
    else:
        note = ("New designs are 3D models (purpose=\"model\") unless the request says they are for printing (then "
                "pass purpose=\"print\"). For context only: this person also has a 3D printer, so do not bring up "
                "printing, slicing or filament unless they ask.")
    box = getattr(adapter, "sandbox", "") or SANDBOX
    text = PROMPT.format(project=project or "none (start a new one if asked)", printing=note, sandbox=box)
    if getattr(adapter, "tool_prefix", ""):
        text += TOOL_NAMES.format(p=adapter.tool_prefix)
    return text + beauty_protocol(message, adapter)


def _adapters(cfg: dict) -> dict:
    return cfg.get("_adapters") or agents_mod.ADAPTERS


def defaults(cfg: dict, agent_status: list[dict] | None = None) -> dict:
    """The agent, model and effort a new conversation starts with ([chat] in studio.toml)."""
    c = cfg.get("chat", {})
    agent = c.get("agent") or ""
    st = agent_status if agent_status is not None else [a.status(cfg) for a in _adapters(cfg).values()]
    ok = [a["id"] for a in st if a["available"]]
    if agent not in ok and ok:
        agent = ok[0]
    return {"agent": agent, "model": str(c.get("model") or "default"), "effort": str(c.get("effort") or "")}


def status(cfg: dict) -> dict:
    c = cfg.get("chat", {})
    on = c.get("enabled", True)
    if on and c.get("api_agents", True):
        agents_mod.refresh(_adapters(cfg))               # providers the person added, edited or removed
    ads = list(_adapters(cfg).values()) if on else []
    if any(getattr(a, "inline", False) for a in ads) and c.get("api_agents", True):
        providers_mod.warm(cfg, {a.id for a in ads if getattr(a, "inline", False)})     # all at once, not one by one
    if not c.get("api_agents", True):
        ads = [a for a in ads if not getattr(a, "inline", False)]
    learned = recent = None
    if cfg.get("data", {}).get("dir"):                    # the versions each alias resolved to on its last run
        learned, recent = Learned(Path(cfg["data"]["dir"])), Recent(Path(cfg["data"]["dir"]))
        learned.seed()
        recent.seed(learned)                              # before the statuses: a provider's Default is its last-used model
    ags = [a.status(cfg) for a in ads]
    if learned is not None:
        ags = [learned.decorate(a, recent) for a in ags]
    d = defaults(cfg, ags)
    cur = next((a for a in ags if a["id"] == d["agent"] and a["available"]), None)
    note = None
    if not on:
        note = "Chat is off in studio.toml."
    elif not cur:
        note = ("Connect an agent to chat here: an agent CLI such as Claude Code, Codex or Gemini CLI, an API key from a "
                "model provider, or a local model server such as Ollama. Everything else works without one.")
    return {"available": bool(cur), "cli": cur["cli"] if cur else None, "model": d["model"], "web": bool(c.get("web", True)),
            "note": note, "agents": ags, "default": d, "max_running": MAX_RUNNING,
            "label": cur["label"] if cur else "your agent"}


def set_defaults_text(text: str, values: dict) -> str:
    """Set keys in the [chat] table of TOML text; every other line stays as it was."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start = next((i for i, ln in enumerate(lines) if re.match(r"^\s*\[chat\]\s*(#.*)?$", ln)), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append("[chat]\n")
        start = len(lines) - 1
    for key, val in values.items():
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
        new = f"{key} = {json.dumps(str(val), ensure_ascii=False)}"
        for i in range(start + 1, end):
            m = re.match(rf"^(\s*){re.escape(key)}\s*=\s*(\"[^\"]*\"|'[^']*'|[^#\s]+)(\s*#.*)?(\r?\n)?$", lines[i])
            if m:
                lines[i] = f"{m.group(1)}{new}{m.group(3) or ''}{m.group(4) or chr(10)}"
                break
        else:
            lines.insert(start + 1, new + "\n")
    return "".join(lines)


def set_defaults(cfg: dict, agent: str | None = None, model: str | None = None, effort: str | None = None) -> dict:
    """Remember the choice for new conversations: in memory at once, and in [chat] of studio.toml when it can be
    written (the file is backed up once, as studio.toml.bak-form-chat; nothing else in it changes)."""
    vals = {k: str(v) for k, v in (("agent", agent), ("model", model), ("effort", effort)) if v is not None}
    if "agent" in vals and vals["agent"] not in _adapters(cfg):
        raise ValueError(f"Unknown agent “{vals['agent']}”.")
    cfg.setdefault("chat", {}).update(vals)
    from .slicer import config_target
    path, saved, why = config_target(cfg), False, None
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        new = set_defaults_text(old or "# Form Studio configuration (written by Form Studio)\n", vals)
        before, after = (tomllib.loads(old) if old else {}), tomllib.loads(new)
        a, b = dict(after), dict(before)
        a_c, b_c = dict(a.pop("chat", {})), dict(b.pop("chat", {}))
        for k in vals:
            a_c.pop(k, None), b_c.pop(k, None)
        if a != b or a_c != b_c or any(after["chat"].get(k) != v for k, v in vals.items()):
            raise ValueError("the file would change in other places")
        backup = path.with_name(path.name + ".bak-form-chat")
        if path.exists() and not backup.exists():
            shutil.copyfile(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        saved = True
    except (OSError, ValueError) as e:
        why = f"Kept for this session only: {path} could not be updated ({e})."
    return {"default": defaults(cfg), "saved": saved, "path": str(path), "note": why}



_UNAVAILABLE = re.compile(r"model_not_found|model[^.]{0,80}\b(is not supported|does not exist|not available|not found|"
                          r"no access|not have access)|unknown model|invalid model", re.I)


_BUDGET = re.compile(r"error_max_budget_usd|max[_ -]?budget|budget[_ ]exceeded|exceeded (?:the )?(?:usd |spending )?budget", re.I)

#: where the cap lives in the app (form/config_edit.py SCHEMA "chat.budget_usd_per_message")
BUDGET_SETTING = "Settings › Chat › Spending cap per message"


def is_budget_stop(err: str) -> bool:
    """The agent stopped because the reply reached the per-message spending cap (Claude Code: error_max_budget_usd)."""
    return bool(_BUDGET.search(err or ""))


def budget_card(cap_usd: float | None, cost_usd: float | None = None, made: list | None = None,
                change: dict | None = None) -> dict:
    """The per-message spending cap, said plainly: what stopped, what was kept, where to change the cap."""
    cap = f"${float(cap_usd):.2f}" if cap_usd else "the cap"
    spent = f" (this reply cost ${float(cost_usd):.2f})" if isinstance(cost_usd, (int, float)) and cost_usd else ""
    kept = []
    if made:
        kept.append(("the new design " if len(made) == 1 else "the new designs ") + ", ".join(made))
    if change and change.get("project") and change.get("to") is not None:
        kept.append(f"{change['project']} at revision {change['to']}")
    what = ("Everything it saved is kept: " + " and ".join(kept) + "." if kept else
            "Everything it saved before that point is kept in the project.")
    return {"message": f"This reply stopped at the spending cap of {cap} per message{spent}. {what}",
            "hint": f"Send “continue” to carry on from there, or raise the cap in {BUDGET_SETTING}.",
            "kind": "budget"}


def _model_unavailable(err: str) -> bool:
    """The agent refused the model itself (not the account, the network or the request): a different model works."""
    return bool(_UNAVAILABLE.search(err or ""))

class ChatJob:
    def __init__(self, message: str, project: str | None, session: str | None, conversation: str | None = None,
                 agent: str = "claude", model: str = "default", effort: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.message, self.project, self.session, self.conversation = message, project, session, conversation
        self.agent, self.model, self.effort = agent, model, effort
        self.events: list[dict] = [{"t": "user", "text": message, "ts": time.time()}]
        self.state, self.cost, self.proc, self.error = "running", None, None, None
        self.started = time.time()
        self.live: dict | None = None          # what the agent is producing right now (streamed), for the page
        self.parser = None
        self.tools: dict = {}                  # tool call id -> name, to recognise what a result belongs to
        self.steps = 0
        self.inputs: dict = {}                 # tool call id -> its input, as the agent's parser shortened it
        self.before: set | None = None         # project ids that existed when the message was sent
        self.attachments: list[dict] = []
        self.stop_asked = False
        self.thread: threading.Thread | None = None
        self.ask = False                       # someone can answer ask_user (the app, or a terminal)
        self.asked: set = set()                # question ids already shown in the conversation
        self.waiting: dict | None = None       # the open question, while the agent waits for an answer
        self.unread = 0                        # output lines that were not the CLI's event format
        self.model_id: str | None = None       # the model the CLI reported for this run
        self.head0: int | None = None          # the project's head revision when the message was sent
        self.purpose: str | None = None        # "print" | "model" | "game": what the design is for (form/start.py)
        self.session0: str | None = None       # the session this run resumed (its total before the run: cost)
        # end-of-run gate (form/verdict.py): {project: [FAIL rows]} from the latest report of each design's checks,
        # and the agent text said after each report; one continuation at most when a reply ends on unreported FAILs
        self.fails: dict = {}
        self.said_since: dict = {}
        self.gated = False
        self.gating = False

    def public(self, start: int = 0) -> dict:
        return {"id": self.id, "state": self.state, "session": self.session, "cost_usd": self.cost,
                "events": self.events[start:], "next": len(self.events), "error": self.error, "live": self.live,
                "conversation": self.conversation, "agent": self.agent, "asking": self.waiting,
                "seconds": round(time.time() - self.started, 1)}


class Chat:
    def __init__(self, cfg: dict, data_dir: Path, mcp_command: str, adapters: dict | None = None):
        self.cfg, self.data, self.mcp = cfg, Path(data_dir), mcp_command
        self.adapters = adapters or _adapters(cfg)
        self.store = Conversations(self.data)
        self.learned = Learned(self.data)
        self.recent = Recent(self.data)
        self.jobs: dict[str, ChatJob] = {}
        self._lock = threading.Lock()
        self.studio = None                     # the app's engine, when there is one: names the printer for "Purpose:"

    # ---- state -------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        return status(dict(self._cfgd(), _adapters=self.adapters))

    def _cfgd(self) -> dict:
        """The configuration with this chat's data folder, where models.json and recent.json are read from."""
        return dict(self.cfg, data=dict(self.cfg.get("data") or {}, dir=str(self.data)))

    def running(self, cid: str | None = None) -> list[ChatJob]:
        return [j for j in self.jobs.values() if j.state == "running" and (cid is None or j.conversation == cid)]

    def job_for(self, cid: str) -> ChatJob | None:
        """The conversation's running job, or else its most recent one in this process."""
        js = [j for j in self.jobs.values() if j.conversation == cid]
        return next((j for j in js if j.state == "running"), js[-1] if js else None)

    def conversation(self, cid: str, start: int = 0) -> dict:
        """A conversation with its events from `start`, plus what is streaming right now."""
        out = self.store.get(cid, start)
        out["designs"] = self.store.designs(cid)        # each with its state now (live, trashed, gone) and name
        j = self.job_for(cid)
        run = bool(j and j.state == "running")
        out.update({"state": "running" if run else "idle", "live": j.live if run else None, "job": j.id if run else None,
                    "seconds": round(time.time() - j.started, 1) if run else None,
                    "asking": j.waiting if run else None})
        ad = self.adapters.get(out.get("agent"))
        for ev in out.get("items", []):                  # conversations saved before model names were shown
            if ev.get("t") == "start" and ev.get("model") and not ev.get("label"):
                ev["label"] = ad.model_label(ev["model"]) if ad else ev["model"]
        if out.get("resolved_model") and not out.get("resolved_agent"):     # saved before the agent was recorded with it
            out["resolved_agent"] = next((e.get("agent") for e in reversed(self.store.events(cid))
                                          if e.get("t") in ("start", "end") and e.get("model")), None)
        if out.get("resolved_model") and (out.get("resolved_agent") or out.get("agent")) != out.get("agent"):
            out["resolved_model"] = None              # saved under the agent used before; not this one's model
        if out.get("resolved_model"):
            out["resolved_label"] = ad.model_label(out["resolved_model"]) if ad else out["resolved_model"]
        return out

    def list(self, project: str | None = None, q: str | None = None, thread: str | None = None,
             involving: str | None = None) -> list[dict]:
        busy = {j.conversation: ("asking" if j.waiting else "running") for j in self.running()}
        return [dict(m, state=busy.get(m["id"], "idle"))
                for m in self.store.list(project, q, thread=thread, involving=involving)]

    def delete(self, cid: str) -> None:
        for j in self.running(cid):
            self.stop(j.id)
        self.store.delete(cid)

    # ---- sending -----------------------------------------------------------------------------------------------
    def send(self, message: str, conversation: str | None = None, project: str | None = None, agent: str | None = None,
             model: str | None = None, effort: str | None = None, attachments: list[str] | None = None,
             ask: bool = True, purpose: str | None = None, note: str = "") -> ChatJob:
        """ask: a person can answer the agent's questions (the app; `form chat` in a terminal).
        purpose: "print", "model" or "game" (form/start.py); kept in the conversation, so later messages keep it.
        note: for the agent only, not shown as part of the person's message (what the engine fetched from links)."""
        message = (message or "").strip()
        if not message:
            raise RuntimeError("Write a message first.")
        from .start import PURPOSES
        if purpose is not None and purpose not in PURPOSES:
            raise RuntimeError(f"Unknown purpose “{purpose}”: use print, model or game.")
        st = self.status()
        if not self.cfg.get("chat", {}).get("enabled", True):
            raise RuntimeError(st["note"])
        with self._lock:
            if conversation:
                meta = self.store.meta(conversation)
                if self.running(conversation):
                    raise RuntimeError("This conversation is still answering the previous message. Wait, or press Stop.")
            else:
                meta = None
            if len(self.running()) >= MAX_RUNNING:
                raise RuntimeError(f"{MAX_RUNNING} conversations are already running. Wait for one to finish, or stop one.")
            d = st["default"]
            agent = agent or (meta["agent"] if meta else d["agent"])
            adapter = self.adapters.get(agent)
            if not adapter:
                raise RuntimeError(f"Unknown agent “{agent}”. Known: {', '.join(self.adapters)}.")
            exe = adapter.executable(self.cfg)
            if not exe:
                raise RuntimeError(adapter.install_hint or f"{adapter.label} is not installed.")
            # the configured default model and effort belong to the default agent: "opus" means nothing to Codex
            mine = agent == d["agent"]
            model = model or (meta["model"] if meta else (d["model"] if mine else "")) or "default"
            effort = effort if effort is not None else (meta["effort"] if meta else (d["effort"] if mine else ""))
            if meta is None:
                meta = self.store.create(project, agent, model, effort or "")
            fields = {"agent": agent, "model": model, "effort": effort or ""}
            if project and not meta.get("project"):
                fields["project"] = project
            if purpose:
                fields["purpose"] = purpose
            meta = self.store.update(meta["id"], **fields)
            cid = meta["id"]
            session = meta.get("session") if meta.get("session_agent") == agent else None
            job = ChatJob(message, meta.get("project") or project, session, cid, agent, model, effort or "")
            job.attachments = self.store.attachments(cid, attachments or [])
            job.note = note or ""
            try:                               # what the person changed by hand since the last reply goes with the message
                by_hand = cite.hand_note(self.store.events(cid))
            except ConversationError:
                by_hand = ""
            if by_hand:
                job.note = (job.note + "\n\n" if job.note else "") + by_hand
            job.before = self._project_ids()
            job.ask = bool(ask)
            job.head0 = self._head(job.project)
            job.purpose = meta.get("purpose") if meta.get("purpose") in PURPOSES else None
            user = {"t": "user", "text": message}
            if job.attachments:
                user["attachments"] = job.attachments
            job.events[0] = self.store.append(cid, user)
            self.jobs[job.id] = job
        job.thread = threading.Thread(target=self._run, args=(job, adapter, exe), daemon=True, name=f"form-chat-{job.id}")
        job.thread.start()
        return job

    def shutdown(self, seconds: float = 15.0) -> None:
        """The app is quitting: stop every running message and wait (up to `seconds`) until each has ended with the
        agent and its tool server, so nothing keeps running in a conversation's folder after Form Studio is gone."""
        jobs = list(self.jobs.values())
        for j in jobs:
            if j.state == "running":
                self.stop(j.id)
        end = time.time() + seconds
        for j in jobs:
            t = getattr(j, "thread", None)
            if t is not None and t.is_alive():
                t.join(max(0.0, end - time.time()))

    def start(self, message: str, project: str | None = None, session: str | None = None) -> ChatJob:
        """The older entry point (web bench): continue the conversation that owns `session`, or start a new one."""
        cid = None
        if session:
            cid = next((m["id"] for m in self.store.list() if m.get("session") == session), None)
        try:
            return self.send(message, cid, project)
        except ConversationError as e:
            raise RuntimeError(str(e))

    def stop(self, jid: str) -> bool:
        """Stop a running message, by job id or conversation id."""
        j = self.jobs.get(jid) or next(iter(self.running(jid)), None)
        if not j or j.state != "running":
            return False
        j.stop_asked = True
        if j.conversation:
            ask_mod.close_all(self.ask_dir(j.conversation), "stopped")
        if j.proc and j.proc.poll() is None:
            try:
                j.proc.terminate()
            except OSError:
                pass
        return True

    def note(self, cid: str, by: str, text: str) -> dict:
        """Record what another agent did while this conversation was open (shown as a quiet line)."""
        return self.store.append(cid, {"t": "act", "by": str(by)[:60], "text": str(text)[:400]})

    # ---- questions from the agent (ask_user) -------------------------------------------------------------------
    def ask_dir(self, cid: str) -> Path:
        return self.store.dir(cid) / "ask"

    def ask_image(self, cid: str, qid: str) -> Path:
        """The picture a measurement question points at (copied into the ask folder by ask_measurement)."""
        folder = self.ask_dir(cid)
        q = ask_mod.read_question(folder, qid)
        name = (q or {}).get("image")
        f = folder / name if name and re.fullmatch(r"[0-9a-f]{10}\.(png|jpg|jpeg)", name) else None
        if f is None or not f.is_file():
            raise ConversationError("That question has no picture.")
        return f

    def answer(self, cid: str, qid: str, text: str = "", choices: list | None = None, extra: dict | None = None) -> dict:
        """The person's answer to the agent's question: handed to the waiting tool and kept in the conversation.
        extra: what answering did besides words (a measurement: value, method, source, rev; form/start.answer)."""
        try:
            a = ask_mod.answer(self.ask_dir(cid), qid, text, choices, extra)
        except ask_mod.AskError as e:
            raise ConversationError(str(e))
        j = self.job_for(cid)
        ev = {"t": "answer", "id": qid, "text": a["text"], "choices": a["choices"], **(extra or {})}
        if j and j.state == "running":
            if j.waiting and j.waiting.get("id") == qid:
                j.waiting = None
            self._add(j, ev)
            return ev
        return self.store.append(cid, ev)

    def _watch_asks(self, job: ChatJob) -> None:
        """While the agent runs: show each new question in the conversation, and close the ones nobody answered."""
        folder = self.ask_dir(job.conversation)
        while job.state == "running":
            try:
                for q in ask_mod.questions(folder):
                    if q["id"] not in job.asked and q["state"] == "open":
                        job.asked.add(q["id"])
                        ev = {"t": "ask", "id": q["id"], "question": q["question"], "choices": q["choices"],
                              "multi": q["multi"], "free": q["free"], "why": q["why"], "kind": q["kind"],
                              "timeout": q.get("timeout")}
                        if q["kind"] == "measure":              # a guided measurement card (ask_measurement)
                            ev.update({k: q.get(k) for k in ask_mod.MEASURE_FIELDS})
                            if q.get("image"):
                                ev["image_url"] = f"/api/conversations/{job.conversation}/ask/{q['id']}/image"
                        self._add(job, ev)
                        job.waiting = {k: v for k, v in ev.items() if k not in ("t", "timeout")}
                    elif q["id"] in job.asked and q["state"] == "closed" and job.waiting and job.waiting["id"] == q["id"]:
                        job.waiting = None
                        self._add(job, {"t": "answer", "id": q["id"], "closed": q.get("reason") or "timeout"})
            except (OSError, ConversationError):
                pass
            time.sleep(0.2)

    def _close_asks(self, job: ChatJob) -> None:
        if not job.conversation:
            return
        reason = "stopped" if job.stop_asked else "ended"
        ask_mod.close_all(self.ask_dir(job.conversation), reason)
        if job.waiting:
            self._add(job, {"t": "answer", "id": job.waiting["id"], "closed": reason})
            job.waiting = None

    # ---- one run -----------------------------------------------------------------------------------------------
    def _head(self, pid: str | None) -> int | None:
        if not pid:
            return None
        try:
            return int(json.loads((self.data / pid / "project.json").read_text(encoding="utf-8")).get("head"))
        except (OSError, ValueError, TypeError):
            return None

    def _project_ids(self) -> set:
        try:
            return {d.name for d in self.data.iterdir() if (d / "project.json").exists()}
        except OSError:
            return set()

    def _mcp(self, job: ChatJob | None = None) -> dict:
        # the launcher path may contain spaces ("Application Support"): never split it
        if getattr(sys, "frozen", False):           # the packaged app is its own MCP server; never a form-mcp on PATH
            cmd0, args0 = sys.executable, ["-m", "form.mcp_server"]
        else:
            cmd0, args0 = (self.mcp, []) if Path(self.mcp).exists() else (sys.executable, ["-m", "form.mcp_server"])
        env = {"FORM_DATA": str(self.data)}
        if self.cfg.get("_path") and Path(str(self.cfg["_path"])).exists():
            env["FORM_CONFIG"] = self.cfg["_path"]
        if job is not None and job.ask and job.conversation:          # ask_user reaches this conversation
            env[ask_mod.ENV_DIR] = str(self.ask_dir(job.conversation))
            env[ask_mod.ENV_TIMEOUT] = str(int(self._ask_timeout()))
        if job is not None and job.conversation:                      # what the agent saves can name its conversation
            env["FORM_CONVERSATION"] = job.conversation
        if job is not None and job.purpose:                           # designs created in this run get this purpose
            from .start import ENV_PURPOSE
            env[ENV_PURPOSE] = job.purpose
        return {"command": cmd0, "args": args0 + ["--no-bench"], "env": env}

    def _ask_timeout(self) -> float:
        try:
            return max(30.0, float(self.cfg.get("chat", {}).get("ask_timeout_s", ask_mod.DEFAULT_TIMEOUT)))
        except (TypeError, ValueError):
            return ask_mod.DEFAULT_TIMEOUT

    def _system(self, job: ChatJob) -> str:
        return system_prompt(self.cfg, job.project, self.adapters.get(job.agent), job.message)

    def _prompt(self, job: ChatJob, with_recap: bool) -> str:
        parts = []
        if with_recap and job.conversation:
            lines = []
            for e in self.store.events(job.conversation)[:-1]:
                if e.get("t") == "user":
                    lines.append("User: " + str(e.get("text", "")))
                elif e.get("t") == "text":
                    lines.append("Assistant: " + str(e.get("text", "")))
            recap = "\n".join(lines)[-RECAP_CHARS:]
            try:
                forked = bool(self.store.meta(job.conversation).get("parent"))
            except ConversationError:
                forked = False
            if recap.strip() and forked:
                parts.append("This conversation continues from an earlier one (a branch of it; its agent session is not "
                             "carried over, so this is a transcript; check the project with Form Studio's tools rather "
                             "than trusting it):\n" + recap + "\n\nNow:")
            elif recap.strip():
                parts.append("Earlier in this conversation (the earlier agent session is not available, so this is a "
                             "transcript; check the project with Form Studio's tools rather than trusting it):\n" + recap + "\n\nNow:")
        parts.append(job.message)
        if job.gating:                         # the gate's continuation: its message only, no attachments again
            return "\n\n".join(parts)
        line = self._purpose_line(job.purpose)
        if line:
            parts.append(line)
        if getattr(job, "note", ""):
            parts.append(job.note)
        if job.attachments:
            d = self.store.files_dir(job.conversation)
            what = {"image": "image", "pdf": "PDF; read_document(path) also opens it page by page",
                    "cad": "CAD part, mesh or scan; triage(path) says what it is and the route; reconstruct(path) makes "
                           "a mesh editable; import_reference(project, path) keeps it as a reference",
                    "sketch": "sketch drawn in Form Studio; its geometry is below"}

            def hint(a):
                h = what.get(a["kind"], a["kind"])
                k = formats.kind_of(a["file"])
                if a["file"].lower().endswith(".3mf"):          # read with lib3mf: named parts, placed as in the slicer
                    h = "3MF with named parts, Bambu, Orca and MakerWorld layouts included; use import_reference(project, path)"
                elif k == "pointcloud":
                    h = ("point cloud from a scanner; triage(path) makes a surface from the points first and routes it "
                         "like a mesh; reconstruct(path) and import_reference(project, path) take it as it is")
                elif k == "2d":
                    h = "2D drawing; triage(path) gives its outlines and sizes (route profile)"
                elif k == "archive":
                    h = "zip; triage(path) unpacks it safely and gives each file inside its route and path"
                if a["kind"] == "cad" and (a.get("mesh") or {}).get("class") in ("heavy", "very heavy"):
                    h += f"; a {a['mesh']['class']} mesh: triage(path) and reconstruct(path) handle its size themselves"
                src = a.get("source") or {}
                if src.get("url"):
                    h += f"; from {src['url']}" + (f", licence: {src['license']}" if src.get("license") else "")
                return h
            parts.append("Attached files:\n" + "\n".join(f"- {d / a['file']} ({hint(a)})" for a in job.attachments))
            for a in job.attachments:
                if a["kind"] == "sketch":
                    parts.append(self._sketch_block(d / a["file"]))
        return "\n\n".join(parts)

    SKETCH_HEADING = "Sketch drawn in Form Studio (structured geometry, mm, y up):"
    SKETCH_CHARS = 12000

    def _sketch_block(self, f: Path) -> str:
        """A sketch's JSON inline, compact, so the agent reads exact numbers; cut by whole primitives when long."""
        from . import sketch as sketch_mod
        try:
            s = sketch_mod.validate(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            return f"{self.SKETCH_HEADING} {f.name}\n(could not be read: {e})"
        try:
            summary = sketch_mod.summarize(s)["text"]
        except ValueError:
            summary = ""
        dump = lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False)  # noqa: E731
        text = dump(s)
        if len(text) > self.SKETCH_CHARS:
            n, total = len(s["primitives"]), len(s["primitives"])
            while n > 0 and len(text) > self.SKETCH_CHARS:
                n = n * 3 // 4
                text = dump(dict(s, primitives=s["primitives"][:n], truncated=True, primitives_total=total))
        return f"{self.SKETCH_HEADING} {f.name}\n{text}" + (f"\nSummary: {summary}" if summary else "")

    def _purpose_line(self, purpose: str | None) -> str:
        if not purpose:
            return ""
        from . import start
        printer = None
        if purpose == "print":
            st = getattr(self, "studio", None)
            try:
                printer = start.state(st)["printer"]["name"] if st is not None else start.printer_name_cfg(self.cfg)
            except Exception:
                printer = None
        return start.purpose_line(purpose, printer)

    def _run(self, job: ChatJob, adapter, exe: str) -> None:
        if getattr(adapter, "inline", False):
            return self._run_inline(job, adapter)
        c = self.cfg.get("chat", {})
        cwd = self.store.dir(job.conversation) if job.conversation else self.data
        had_history = bool(job.conversation) and self.store.meta(job.conversation).get("messages", 0) > 1
        if job.conversation:
            threading.Thread(target=self._watch_asks, args=(job,), daemon=True, name=f"form-ask-{job.id}").start()
        try:
            while True:                                 # a second pass only for the end-of-run gate
                for attempt in (1, 2):
                    job.session0 = job.session
                    tmp = Path(tempfile.mkdtemp(prefix="form-chat-"))
                    fdir = self.store.files_dir(job.conversation) if job.conversation else cwd
                    files = [fdir / a["file"] for a in job.attachments]
                    run = Run(message=self._prompt(job, with_recap=had_history and not job.session),
                              system=self._system(job),
                              model=job.model, effort=self._effort(job, adapter, exe), session=job.session, cwd=cwd, scratch=tmp, mcp=self._mcp(job),
                              tool_timeout_s=self._ask_timeout() + 300, tool_search=str(c.get("tool_search", "auto")),
                              web=bool(c.get("web", True)), budget_usd=float(c.get("budget_usd_per_message", 3.0)),
                              images=[f for f, a in zip(files, job.attachments) if a["kind"] == "image"], files=files)
                    job.parser = adapter.parser()
                    n0, err_text = len(job.events), ""
                    saved0 = self.store.meta(job.conversation).get("events", 0) if job.conversation else 0
                    try:
                        cmd = adapter.command(run, exe)
                        job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                                    text=True, encoding="utf-8", errors="replace", cwd=str(cwd), bufsize=1,
                                                    env=dict(os.environ, **getattr(adapter, "env", {}), **secrets.agent_env(adapter.id),
                                                             **adapter.run_env(run)))
                        err_buf: list[str] = []
                        drain = threading.Thread(target=lambda p=job.proc: err_buf.extend(p.stderr), daemon=True)
                        drain.start()
                        for line in job.proc.stdout:
                            if line.strip() and not line.lstrip().startswith(("{", "[")):
                                job.unread += 1
                            self._event(job, line)
                        job.proc.wait()
                        self._event(job, None)                      # what the parser still owes (CLIs without an end event)
                        drain.join(timeout=2)
                        err_text = "".join(err_buf)
                        for pipe in (job.proc.stdout, job.proc.stderr):
                            try:
                                pipe.close()
                            except (OSError, ValueError):
                                pass
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                    rc = job.proc.returncode
                    said = any(e["t"] in ("text", "tool") for e in job.events[n0:])
                    if (attempt == 1 and job.session and not job.stop_asked and rc != 0 and not said
                            and adapter.resume_failed(err_text + " " + (job.error or ""), job.events[n0:])):
                        # the CLI no longer has that session: say so, then send again with a transcript instead
                        job.session, job.error = None, None
                        del job.events[n0:]
                        if job.conversation:
                            self.store.truncate(job.conversation, saved0)
                            self.store.update(job.conversation, session=None, session_agent=None)
                        continue
                    break
                self._close_asks(job)                           # before the state changes: a reader sees it with the end
                ended = any(e["t"] == "end" for e in job.events[n0:])
                # Save the last events first and only then say the job is over: a reader that sees "failed" or
                # "stopped" must also find its error or end event (found on a slow Windows runner).
                if job.stop_asked:
                    if not ended:
                        self._add(job, {"t": "end", "stopped": True, "cost_usd": None, "steps": job.steps,
                                        "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                    job.state = "stopped"
                elif rc == 0 and not job.error:
                    if self._gate(job):
                        had_history = True
                        continue
                    job.state = "done"
                else:
                    if not job.error:
                        job.error = err_text.strip()[-800:] or f"{adapter.label} exited with code {rc}"
                        known = self._limit(job, job.error + " " + err_text) or adapter.explain(job.error) or compat.diagnose(
                            adapter.id, adapter.label, exe, rc, err_text, job.unread,
                            sum(1 for e in job.events[n0:] if e["t"] in ("start", "text", "tool", "end")), __version__)
                        if known:                                   # a known failure, said plainly with the fix inside FORM
                            job.error = known["message"]
                            self._add(job, {"t": "error", "text": known["message"], "hint": known.get("hint", ""),
                                            **({k: known[k] for k in ("kind", "agent", "until") if known.get(k)}
                                               if known.get("kind") == "usage_limit" else {})})
                        else:
                            self._add(job, {"t": "error", "text": job.error})
                    job.state = "failed"
                break
        except (OSError, ConversationError) as e:
            job.error = str(e)
            self._add(job, {"t": "error", "text": job.error})
            job.state = "failed"
        finally:
            job.live = None
            self._close_asks(job)

    def _run_inline(self, job: ChatJob, adapter, again: bool = False) -> None:
        """An API agent: the loop runs in this thread (form/agents/api.py); its events take the same path as a CLI's.
        again: the end-of-run gate's continuation (the question watcher is already running)."""
        from .agents.api import Control, SessionGone
        c = self.cfg.get("chat", {})
        cwd = self.store.dir(job.conversation) if job.conversation else self.data
        had_history = again or (bool(job.conversation) and self.store.meta(job.conversation).get("messages", 0) > 1)
        if job.conversation and not again:
            threading.Thread(target=self._watch_asks, args=(job,), daemon=True, name=f"form-ask-{job.id}").start()
        failure = None
        try:
            for attempt in (1, 2):
                fdir = self.store.files_dir(job.conversation) if job.conversation else cwd
                files = [fdir / a["file"] for a in job.attachments]
                run = Run(message=self._prompt(job, with_recap=had_history and not job.session),
                          system=self._system(job),
                          model=job.model, effort=job.effort, session=job.session, cwd=cwd, scratch=cwd, mcp=self._mcp(job),
                          tool_timeout_s=self._ask_timeout() + 300, web=False,
                          budget_usd=float(c.get("budget_usd_per_message", 3.0)),
                          images=[f for f, a in zip(files, job.attachments) if a["kind"] == "image"], files=files)
                job.parser = None
                job.proc = Control()
                try:
                    failure = adapter.execute(run, self._cfgd(), lambda evs: self._events(job, evs), job.proc)
                except SessionGone:
                    if attempt == 1 and job.session:      # the saved history is gone: send again with a transcript
                        job.session = None
                        if job.conversation:
                            self.store.update(job.conversation, session=None, session_agent=None)
                        continue
                    raise
                break
            self._close_asks(job)
            if job.stop_asked:
                if not any(e["t"] == "end" for e in job.events[1:]):
                    self._add(job, {"t": "end", "stopped": True, "cost_usd": None, "steps": job.steps,
                                    "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                job.state = "stopped"
            elif failure:
                job.error = failure["message"]
                self._add(job, {"t": "error", "text": failure["message"], "hint": failure.get("hint", "")})
                job.state = "failed"
            elif self._gate(job):
                return self._run_inline(job, adapter, again=True)
            else:
                job.state = "done"
        except (OSError, ConversationError, RuntimeError, ValueError) as e:
            job.error = str(e) or type(e).__name__
            self._add(job, {"t": "error", "text": job.error})
            job.state = "failed"
        finally:
            job.live = None
            self._close_asks(job)

    def _add(self, job: ChatJob, ev: dict) -> None:
        if job.conversation:
            try:
                ev = self.store.append(job.conversation, ev)
            except ConversationError:
                ev = dict(ev, ts=time.time())       # the conversation was deleted while it ran
        else:
            ev = dict(ev, ts=time.time())
        job.events.append(ev)

    def _event(self, job: ChatJob, line: str) -> None:
        """One line of the CLI's output: update what is live, save what is finished."""
        if job.parser is None:
            job.parser = self.adapters[job.agent].parser()
        self._events(job, job.parser.finish() if line is None else job.parser.feed(line))

    def _events(self, job: ChatJob, evs: list[dict]) -> None:
        """FORM events from an agent (a CLI's parsed output, or an API agent directly): update what is live, save the rest."""
        adapter = self.adapters[job.agent]
        for ev in evs:
            t = ev["t"]
            if t == "live":
                job.live = ev["live"]
                continue
            if ev.get("session"):
                if job.session != ev["session"]:
                    job.session = ev["session"]
                    if job.conversation:
                        try:
                            self.store.update(job.conversation, session=job.session, session_agent=job.agent)
                        except ConversationError:
                            pass
            if t == "session":
                continue
            ev = {k: v for k, v in ev.items() if k != "session"}
            if t == "start":
                ev["agent"] = job.agent
                ev["asked"] = job.model
                if getattr(job, "_effort_why", ""):
                    ev["effort"], ev["effort_why"] = job._effort_picked, job._effort_why
                if ev.get("model"):               # learned once the reply finishes: a model that fails is not kept
                    job.model_id = ev["model"]
                    ev["label"] = adapter.model_label(ev["model"])
            elif t == "tool":
                job.steps += 1
                job.tools[ev.get("id")] = ev.get("name", "")
                job.inputs[ev.get("id")] = ev.get("input", "")
            elif t == "result":
                full = ev.pop("full", "") or ""
                self._enrich(job, ev, full)
                # what the reply rests on is read here, from the call and its result (form/cite.py)
                src = cite.source_of(ev.get("name", ""), job.inputs.get(ev.get("id")), full, bool(ev.get("ok")))
                if src:
                    ev["source"] = src
                if ev.get("name") == "plan_design" and ev.get("ok"):
                    steps = cite.plan_steps(full)
                    if steps:
                        ev["plan"] = steps
                self._note_verdicts(job, ev, full)
                if ev.get("name") == "suggest_replies" and ev.get("ok"):
                    opts = self._suggestions(full)
                    self._add(job, ev)
                    if opts:
                        self._add(job, {"t": "suggest", "options": opts})
                    continue
            elif t == "error" and self._limit(job, str(ev.get("text", ""))):
                card = self._limit(job, str(ev.get("text", "")))   # the CLI's own words carry an upsell: replace them
                job.error = card["message"]
                ev = {"t": "error", "text": card["message"], "hint": card["hint"], "kind": "usage_limit",
                      "agent": card["agent"], "until": card["until"], "again": card.get("again")}
            elif t == "end":
                if ev.get("cost_scope") == "session" and ev.get("cost_total_usd") is not None:
                    # a running session total: the store keeps each session's last total and saves this run's own
                    ev["cost_session"], ev["cost_resumed"] = job.session, job.session0
                    if not job.conversation:
                        ev["cost_usd"] = run_cost(ev["cost_total_usd"], None)
                job.cost = ev.get("cost_usd")
                err = ev.pop("error", None)
                ev.update({"steps": job.steps, "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                self._end_model(job, adapter, ev)
                pid = job.project
                h1 = self._head(pid)
                if pid and h1 is not None and h1 != job.head0:
                    ev["change"] = {"project": pid, "from": job.head0, "to": h1}
                self._add(job, ev)
                job.cost = job.events[-1].get("cost_usd")       # the run's own spend, worked out by the store
                if err and _model_unavailable(str(err)):
                    job.error = self._drop_model(job, str(err))
                    self._add(job, {"t": "error", "text": job.error})
                elif err and is_budget_stop(str(err)):         # never the raw "error_max_budget_usd"
                    card = self._budget(job, ev)
                    job.error = card["message"]
                    self._add(job, {"t": "error", "text": card["message"], "hint": card["hint"], "kind": "budget"})
                elif err and self._limit(job, str(err)):       # a usage limit: a calm card, no upsell text
                    card = self._limit(job, str(err))
                    said = job.error == card["message"]          # the stream already said it as an error event
                    job.error = card["message"]
                    if not said:
                        self._add(job, {"t": "error", "text": card["message"], "hint": card["hint"], "kind": "usage_limit",
                                    "agent": card["agent"], "until": card["until"], "again": card.get("again")})
                elif err:
                    job.error = str(err)
                    self._add(job, {"t": "error", "text": job.error})
                else:
                    if job.model_id and job.model_id != job.model:
                        self.learned.learn(job.agent, job.model, job.model_id, adapter.model_label(job.model_id))                          # a reply came: this model goes first in the menu and is the agent's last
                    used = job.model or "default"
                    if used == "default" and getattr(adapter, "inline", False) and job.model_id:
                        used = job.model_id           # an API provider's Default is its last-used model: name it
                    self.recent.use(job.agent, used)
                continue
            if t == "text":
                for pid in job.said_since:
                    job.said_since[pid] += "\n" + str(ev.get("text", ""))
            self._add(job, ev)

    # ---- end-of-run gate ---------------------------------------------------------------------------------------
    def _note_verdicts(self, job: ChatJob, ev: dict, full: str) -> None:
        """A tool result that reports checks: remember each design's FAIL rows (the latest report wins, so a fix
        clears them) and start listening for the agent to report them."""
        if not ev.get("ok"):
            return
        for rep in verdict_mod.fails(full):
            pid = rep["project"] or job.project or ""
            if rep["rows"]:
                job.fails[pid] = rep["rows"]
                job.said_since[pid] = ""
                ev.setdefault("verdict", {"project": pid, "verdict": rep["verdict"], "blocking": rep["rows"]})
            else:
                job.fails.pop(pid, None)
                job.said_since.pop(pid, None)

    def unreported(self, job: ChatJob) -> dict:
        """{project: FAIL rows} the agent's reply has not reported since the result that showed them."""
        return {pid: rows for pid, rows in job.fails.items()
                if not verdict_mod.acknowledged(rows, job.said_since.get(pid, ""))}

    def _gate(self, job: ChatJob) -> bool:
        """A reply that ends on FAIL rows it did not report gets one continuation that asks the agent to fix them or
        say so; never a second one ([chat] fail_gate = false turns the gate off). True when the continuation starts:
        the caller runs the agent again with job.message."""
        if job.gated or job.stop_asked or not self.cfg.get("chat", {}).get("fail_gate", True):
            return False
        open_ = self.unreported(job)
        if not open_:
            return False
        job.gated = job.gating = True
        job.message = verdict_mod.continuation(open_)
        n = sum(len(r) for r in open_.values())
        self._add(job, {"t": "gate", "fails": open_, "text": job.message,
                        "note": f"The reply ended with {n} failing check{'s' if n != 1 else ''} it did not report; "
                                "Form Studio asked the agent once to fix or report them."})
        for pid in open_:                      # what the agent says now is what counts
            job.said_since[pid] = ""
        return True

    def _effort(self, job: ChatJob, adapter, exe: str) -> str:
        """The effort this message runs at: the conversation's, raised for a hard task (a mesh to make editable, a
        mechanism, a styled form, several parts) when [chat] auto_effort is on (the default). Said in the
        reply's start event when it changes."""
        if not self.cfg.get("chat", {}).get("auto_effort", True) or getattr(job, "_effort_picked", None) is not None:
            return getattr(job, "_effort_picked", None) or job.effort
        from .agents import effort as effort_mod
        try:
            levels = adapter.efforts(self.cfg, exe) or []
        except Exception:
            levels = []
        eff, why = effort_mod.pick(job.message, job.attachments, job.effort, levels)
        job._effort_picked = eff
        job._effort_why = why                          # shown on the reply's start event
        return eff

    def _budget(self, job: ChatJob, end: dict | None = None) -> dict:
        try:
            cap = float(self.cfg.get("chat", {}).get("budget_usd_per_message", 3.0))
        except (TypeError, ValueError):
            cap = None
        try:
            made = sorted(self._project_ids() - (job.before or set())) if getattr(job, "before", None) is not None else []
        except Exception:
            made = []
        return budget_card(cap, job.cost, made, (end or {}).get("change"))

    def _limit(self, job: ChatJob, text: str) -> dict | None:
        """The agent hit its plan's usage limit: {kind, agent, until, message, hint} without the CLI's upsell text,
        naming the designs this run made (they are kept). None when the error is something else."""
        from .agents import limits
        if not limits.is_usage_limit(text):
            return None
        who = getattr(self.adapters.get(job.agent), "label", None) or job.agent
        try:
            made = sorted(self._project_ids() - (job.before or set()))
        except Exception:
            made = []
        return limits.usage_limit(text, who, made)

    def _drop_model(self, job: ChatJob, err: str) -> str:
        """The account cannot use the model this conversation asked for. Forget it (so it is no one's default) and
        switch the conversation to Default, so the next message is answered instead of failing the same way."""
        bad = job.model if job.model and job.model != "default" else job.model_id
        self.learned.forget(job.agent, job.model or "default")
        if bad:
            self.recent.drop(job.agent, bad)
        if job.conversation and job.model and job.model != "default":
            try:
                self.store.update(job.conversation, model="default")
            except ConversationError:
                pass
        who = getattr(self.adapters.get(job.agent), "label", None) or job.agent
        return (f"{who} cannot use the model “{bad}” with this account, so nothing was sent to it. "
                "This conversation now uses Default; send the message again, or pick another model in the menu.")

    def _end_model(self, job: ChatJob, adapter, ev: dict) -> None:
        """Name the model on the reply's footer: from the stream, or from the CLI's own files when it did not say."""
        model = ev.pop("model", None) or job.model_id
        if not model:
            try:
                model = adapter.resolve_model(job.session)
            except Exception:
                model = None
            if model and job.conversation:
                try:
                    self.store.update(job.conversation, resolved_model=model, resolved_agent=job.agent)
                except ConversationError:
                    pass
        if model:
            job.model_id = model
            ev["model"], ev["label"] = model, adapter.model_label(model)

    @staticmethod
    def _suggestions(full: str) -> list[str]:
        try:
            d = json.loads(full)
            opts = d.get("shown") if isinstance(d, dict) else None
        except ValueError:
            opts = None
        if opts is None:
            m = re.search(r"\[.*\]", full, re.S)
            try:
                opts = json.loads(m.group(0)) if m else []
            except ValueError:
                opts = []
        return ask_mod.clean_suggestions(opts if isinstance(opts, list) else [])

    def _enrich(self, job: ChatJob, ev: dict, full: str) -> None:
        """Make a tool result useful to the page: the render it produced, the project it created."""
        name = job.tools.get(ev.get("id"), "")
        ev["name"] = name
        m = re.search(r"File: (.+?\.png)\s*$", full.strip())
        if m and ev.get("ok"):
            try:
                f = Path(m.group(1)).resolve()
                rel = f.relative_to(self.data.resolve())
                if len(rel.parts) == 4 and rel.parts[1:3] == ("artifacts", "renders") and f.is_file():
                    ev["img"] = {"project": rel.parts[0], "file": rel.parts[3]}
            except (OSError, ValueError):
                pass
        if name in ("create_design", "update_design", "build_candidates") and ev.get("ok"):
            left = left_out(full)                   # features a partial build left out: a calm line, not an error
            if left:
                ev["left_out"] = left
        if name == "propose_concepts" and ev.get("ok"):         # the app opens the concepts view for this group
            m = re.search(r'"id"\s*:\s*"([0-9a-f]{10})"', full)
            if m:
                ev["concepts"] = {"group": m.group(1)}
                if job.conversation:            # the pick (form/concepts.py) finds this conversation by the group
                    try:
                        groups = list(self.store.meta(job.conversation).get("concepts") or [])
                        if m.group(1) not in groups:
                            self.store.update(job.conversation, concepts=groups + [m.group(1)])
                    except ConversationError:
                        pass
        if job.conversation:
            # Form Studio's MCP server records every design a tool makes, picks, copies or reconstructs in this
            # conversation the moment it does (conversations.made, from $FORM_CONVERSATION) and puts it in front. The
            # result that did it carries the project, and the conversation follows it: the next message is about
            # that design (the ones before stay listed in `designs` and `projects`).
            try:
                front = self.store.meta(job.conversation).get("project")
            except ConversationError:
                front = None
            if front and front != job.project:
                ev["project"] = front
                job.project = front


def left_out(full: str) -> list:
    """The features a design tool's result says it left out (a partial build, form/featureprog.py), each with the
    reason the build measured: [{"feature", "reason"}]. Read from the result's JSON; [] when there is none."""
    i = full.find("{")
    if i < 0 or '"partial"' not in full:
        return []
    try:
        d, _ = json.JSONDecoder().raw_decode(full[i:])
    except ValueError:
        return []
    part = d.get("partial") if isinstance(d, dict) else None
    if not isinstance(part, dict) and isinstance(d, dict) and isinstance(d.get("project"), dict):
        part = d["project"].get("partial")
    if not isinstance(part, dict):
        return []

    def why(x: dict) -> str:
        diag = x.get("diagnosis") if isinstance(x.get("diagnosis"), dict) else {}
        r = " ".join(str(diag.get("summary") or x.get("message") or "").split())
        if len(r) <= 240:
            return r
        cut = r[:240]                              # whole sentences: never stop mid-sentence
        end = max(cut.rfind(". "), cut.rfind("; "))
        return cut[:end + 1] if end > 40 else cut[:cut.rfind(" ")].rstrip(" ,;:") + "\u2026"
    rows = [{"feature": str(x.get("feature") or ""), "reason": why(x)} for x in part.get("skipped") or [] if isinstance(x, dict)]
    if not rows and part.get("failed"):
        rows = [{"feature": str(part["failed"]), "reason": why(part)}]
    return [r for r in rows if r["feature"]][:8]


# ---- command line: `form chat …`, `form conversations …` ----------------------------------------------------------

def main_chat(argv: list[str]) -> int:
    """form chat "message" [--project ID] [--conversation ID] [--model X] [--agent ID] [--effort L]
    [--attach FILE ...] [--json]: send one message, stream the reply, save the conversation."""
    import argparse
    from . import config
    ap = argparse.ArgumentParser(prog="form chat", description="Send one message to an agent with Form Studio's tools; the conversation is saved.")
    ap.add_argument("message")
    ap.add_argument("--project")
    ap.add_argument("--conversation", help="continue this conversation (id from `form conversations list`)")
    ap.add_argument("--agent", help="an agent CLI (claude, codex, gemini, cursor, opencode, qwen, copilot) or an API provider "
                                    "(anthropic, openai, google, openrouter, mistral, xai, deepseek, groq, ollama, lmstudio, "
                                    "llamacpp), or a provider you added (custom-<name>, see `form providers list`); default: [chat] agent")
    ap.add_argument("--model", help="a model alias or id the agent accepts (default: [chat] model)")
    ap.add_argument("--effort")
    ap.add_argument("--attach", action="append", default=[], metavar="FILE", help="image, PDF, part, mesh, scan or zip (any format `form formats` lists; repeat)")
    ap.add_argument("--json", action="store_true", help="print one JSON event per line instead of text")
    a = ap.parse_args(argv)
    cfg = config.load()
    from .setup import mcp_command
    chat = Chat(cfg, Path(cfg["data"]["dir"]), mcp_command())

    def fail(msg: str) -> int:
        print(json.dumps({"error": {"message": msg}}, ensure_ascii=False), file=sys.stderr if not a.json else sys.stdout)
        return 2
    try:
        cid = a.conversation
        if a.attach:
            if not cid:
                d = chat.status()["default"]
                ag = a.agent or d["agent"]
                mine = ag == d["agent"]                    # defaults for model and effort are the default agent's
                cid = chat.store.create(a.project, ag, a.model or (d["model"] if mine else "default"),
                                        a.effort or (d["effort"] if mine else ""))["id"]
            ids = [chat.store.attach(cid, Path(f))["id"] for f in a.attach]
        else:
            ids = []
        interactive = not a.json and sys.stdin.isatty()     # someone at this terminal can answer the agent's questions
        job = chat.send(a.message, cid, a.project, a.agent, a.model, a.effort, ids, ask=interactive)
    except (RuntimeError, ConversationError) as e:
        return fail(str(e))
    return stream(chat, job, a.json, interactive)


def stream(chat: "Chat", job: ChatJob, as_json: bool, interactive: bool) -> int:
    """Print a running message until it ends: text as it streams, steps and questions on stderr; or JSON events.
    Shared by `form chat` and `form start`."""
    seen, shown_live = 1, 0
    if as_json:
        print(json.dumps({"t": "conversation", "id": job.conversation, "job": job.id, "agent": job.agent, "model": job.model}), flush=True)
    try:
        while True:
            running = job.state == "running"
            evs = job.events[seen:]
            seen += len(evs)
            for ev in evs:
                if as_json:
                    print(json.dumps(ev, ensure_ascii=False, default=str), flush=True)
                    continue
                t = ev["t"]
                if t == "start":
                    name = ev.get("label") or ev.get("model") or "not reported"
                    print(f"[{ev.get('agent')} · model {name}]", file=sys.stderr, flush=True)
                elif t == "ask" and interactive:
                    _ask_terminal(chat, job, ev)
                elif t == "suggest":
                    print("  next: " + " | ".join(ev.get("options", [])), file=sys.stderr, flush=True)
                elif t == "text":
                    print(ev["text"][shown_live:] if shown_live else ev["text"], flush=True)
                    shown_live = 0
                elif t == "tool":
                    print(f"  · {ev['name']} {ev.get('input', '')}", file=sys.stderr, flush=True)
                elif t == "error":
                    print(f"error: {ev['text']}", file=sys.stderr, flush=True)
                elif t == "end":
                    cost = ("cost not reported" if ev.get("cost_usd") is None else "under $0.01" if ev["cost_usd"] < 0.01 else f"${ev['cost_usd']:.2f}")
                    print(f"[{ev.get('steps', 0)} steps · {cost} · {ev.get('seconds')} s"
                          + (" · stopped" if ev.get("stopped") else "") + f" · conversation {job.conversation}]", file=sys.stderr, flush=True)
            L = job.live
            if not as_json and L and L.get("kind") == "text" and len(L.get("text", "")) > shown_live and len(L["text"]) < 20000:
                sys.stdout.write(L["text"][shown_live:])
                sys.stdout.flush()
                shown_live = len(L["text"])
            if not running and seen >= len(job.events):
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        chat.stop(job.id)
        time.sleep(0.5)
    if as_json:
        print(json.dumps({"t": "done", "state": job.state, "conversation": job.conversation, "session": job.session,
                          "cost_usd": job.cost, "error": job.error}, ensure_ascii=False), flush=True)
    return 0 if job.state == "done" else 1


def ask_parse(reply: str, q: dict) -> tuple[list[str], str]:
    """A terminal answer: numbers pick choices ("1" or "1,3"), anything else is the answer in words."""
    cs, r = q.get("choices") or [], reply.strip()
    nums = [x for x in re.split(r"[,\s]+", r) if x]
    if cs and nums and all(x.isdigit() and 1 <= int(x) <= len(cs) for x in nums):
        picked = [cs[int(x) - 1] for x in nums]
        return (picked if q.get("multi") else picked[:1]), ""
    if cs and r in cs:
        return [r], ""
    return [], r


def _ask_terminal(chat: "Chat", job: ChatJob, q: dict) -> None:
    if q.get("kind") == "measure":
        return _measure_terminal(chat, job, q)
    print("\n? " + q.get("question", ""), file=sys.stderr, flush=True)
    if q.get("why"):
        print("  (" + q["why"] + ")", file=sys.stderr, flush=True)
    for i, c in enumerate(q.get("choices") or [], 1):
        print(f"  {i}. {c}", file=sys.stderr, flush=True)
    hint = ("numbers, comma-separated" if q.get("multi") else "a number") if q.get("choices") else ""
    hint += (" or " if hint else "") + "your answer" if q.get("free") else ""
    while True:
        try:
            reply = input(f"  answer ({hint}): ")
        except EOFError:
            return
        picked, text = ask_parse(reply, q)
        if not picked and not text:
            continue
        try:
            chat.answer(job.conversation, q["id"], text, picked)
            return
        except ConversationError as e:
            print(f"  {e}", file=sys.stderr, flush=True)
            if "Pick" not in str(e):
                return


def _measure_terminal(chat: "Chat", job: ChatJob, q: dict) -> None:
    """A measurement question in a terminal: the number, then how it was measured. The MCP tool commits it."""
    unit = q.get("unit") or "mm"
    print("\n? " + q.get("question", ""), file=sys.stderr, flush=True)
    for line in (q.get("where"), q.get("why")):
        if line:
            print("  (" + line + ")", file=sys.stderr, flush=True)
    if q.get("tolerance_mm"):
        print(f"  to within ±{q['tolerance_mm']:g} mm", file=sys.stderr, flush=True)
    while True:
        try:
            value = ask_mod.parse_number(input(f"  value ({unit}): "))
            if value is None:
                continue
            m = input("  measured with (calipers, ruler, tape, estimate): ").strip().lower()
        except EOFError:
            return
        if m not in ask_mod.METHODS:
            continue
        try:
            chat.answer(job.conversation, q["id"], f"{value:g}", [m], extra={"value": value, "method": m})
            return
        except ConversationError as e:
            print(f"  {e}", file=sys.stderr, flush=True)
            return


def main_conversations(argv: list[str]) -> int:
    """form conversations list [--project ID] [--thread ID] [--search TEXT] | show ID | delete ID | rename ID TITLE
    | pin ID [--off] | fork ID [--at N] [--project ID] [--reason TEXT] | designs ID | migrate [--dry-run] [--no-families]"""
    import argparse
    from . import config
    ap = argparse.ArgumentParser(prog="form conversations", description="Saved conversations (JSON).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--project")
    ls.add_argument("--involving", help="every conversation that made or touched this design")
    ls.add_argument("--search")
    ls.add_argument("--thread")
    ds = sub.add_parser("designs", help="the designs a conversation made or touched, in order, with role and state")
    ds.add_argument("id")
    mg = sub.add_parser("migrate", help="rebuild `designs` for older conversations, clear empty ones, join each "
                                        "request's designs into one family")
    mg.add_argument("--dry-run", action="store_true", help="say what would change; write nothing")
    mg.add_argument("--no-families", action="store_true", help="leave the designs' families as they are")
    fk = sub.add_parser("fork")
    fk.add_argument("id")
    fk.add_argument("--at", type=int)
    fk.add_argument("--project")
    fk.add_argument("--reason", default="")
    for name in ("show", "delete", "pin"):
        p = sub.add_parser(name)
        p.add_argument("id")
        if name == "pin":
            p.add_argument("--off", action="store_true")
    rn = sub.add_parser("rename")
    rn.add_argument("id")
    rn.add_argument("title")
    a = ap.parse_args(argv)
    cfg = config.load()
    store = Conversations(Path(cfg["data"]["dir"]))

    def out(obj):
        print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))
    try:
        if a.cmd == "list":
            out(store.list(a.project, a.search, thread=a.thread, involving=a.involving))
        elif a.cmd == "designs":
            out({"conversation": a.id, "project": store.meta(a.id).get("project"), "designs": store.designs(a.id)})
        elif a.cmd == "migrate":
            out(store.migrate(dry_run=a.dry_run, families=not a.no_families))
        elif a.cmd == "fork":
            out(store.fork(a.id, a.at, a.project, a.reason))
        elif a.cmd == "show":
            out(store.get(a.id))
        elif a.cmd == "delete":
            store.delete(a.id)
            out({"deleted": a.id})
        elif a.cmd == "rename":
            out(store.rename(a.id, a.title))
        elif a.cmd == "pin":
            out(store.pin(a.id, not a.off))
    except ConversationError as e:
        out({"error": {"message": str(e)}})
        return 2
    return 0
