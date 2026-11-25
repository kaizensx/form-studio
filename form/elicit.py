"""Asking the person through the MCP client itself (elicitation, form mode).

A tool that needs the person (ask_user, ask_measurement, delete_project, install_software, a large fetch_link) tries
three channels, in this order:

1. Form Studio's own chat: the conversation's ask folder (form/ask.py, FORM_ASK_DIR). The in-app agent always has
   it, so in-app nothing changes.
2. The client's own form (MCP elicitation, form mode), when the client declared the capability
   (`elicitation: {form: {}}`; a bare `elicitation: {}` means form only). URL mode has no use here.
3. Today's result: ask_user and ask_measurement say nobody can answer here ("no_user"), delete_project deletes as it
   always did, install_software wants confirm=True, fetch_link downloads.

The client protocol decides how a form is sent:

* 2026-07-28 and later: the server may not send requests of its own. The tool returns an `InputRequiredResult` whose
  `inputRequests` holds one `elicitation/create`, with a `requestState` the SDK seals (form/mcp_server.py sets the
  key and lifetime). The client asks the person and calls the tool again with the same arguments plus
  `inputResponses`; the tool runs again from the top and this module hands it the answer. An answer is taken only
  together with the sealed state this server minted, so a client cannot skip the form by sending a made-up answer
  on the first call.
* Earlier, handshake-era versions: `elicitation/create` goes to the client as a request on the open session (the
  SDK's `ctx.elicit`, here `session.elicit_form` with a hand-written schema so enums carry titles).

Schemas are flat objects of string, number, boolean and enum (`oneOf` with `const`/`title`); the only arrays are
multi-select enums. Declining or dismissing a form is an answer, not an error: the tool returns `{answered: false}`
or a refusal, and nothing is changed.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio

from . import ask as ask_mod

STATE = "form-elicit/1:"                  # the plaintext of the requestState this server mints (sealed by the SDK)
STATE_TTL_S = 3600.0                      # how long a person may take to fill in a form before the retry is refused
FETCH_CONFIRM_BYTES = 100_000_000         # fetch_link asks before downloading more than this (when it can ask)
MEASURE_METHODS = {"caliper": "calipers", "ruler": "ruler", "datasheet": "datasheet"}   # form choice -> how it was taken


@dataclass
class Reply:
    """What the person did with a form: action "accept" (with content), "decline" or "cancel"."""
    action: str
    content: dict = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.action == "accept"


# -- channels ----------------------------------------------------------------------------------------------------
def in_app() -> bool:
    """Form Studio's own chat is attached: questions go to its ask folder (channel 1)."""
    return bool(os.environ.get(ask_mod.ENV_DIR))


def _modern(ctx) -> bool:
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS
    try:
        return ctx.protocol_version in MODERN_PROTOCOL_VERSIONS
    except Exception:
        return False


def supported(ctx) -> bool:
    """The client declared form elicitation, and this request can carry one."""
    if ctx is None:
        return False
    try:
        caps = ctx.client_capabilities
    except Exception:                                    # outside a request (a direct call in a test)
        return False
    el = getattr(caps, "elicitation", None) if caps is not None else None
    if el is None:
        return False
    if getattr(el, "form", None) is None and getattr(el, "url", None) is not None:
        return False                                     # URL mode only
    if _modern(ctx):
        return True
    try:
        return bool(ctx.session.can_send_request)
    except Exception:
        return False


def available(ctx) -> bool:
    """Channel 2 applies: no Form Studio chat, and the client can show a form."""
    return not in_app() and supported(ctx)


def _reply(r) -> Reply:
    if isinstance(r, dict):
        action, content = r.get("action"), r.get("content")
    else:
        action, content = getattr(r, "action", None), getattr(r, "content", None)
    action = action if action in ("accept", "decline", "cancel") else "cancel"
    return Reply(action, dict(content or {}) if action == "accept" else {})


async def form(ctx, key: str, message: str, schema: dict):
    """Ask through the client's form. Returns a Reply, an InputRequiredResult the tool must return as it is
    (2026-07-28 and later, first round), or None when the client cannot be asked (use channel 3)."""
    if not supported(ctx):
        return None
    if _modern(ctx):
        import mcp_types as t
        try:
            state, responses = ctx.request_state, ctx.input_responses or {}
        except Exception:
            state, responses = None, {}
        if state == STATE + key and key in responses:
            return _reply(responses[key])
        req = t.ElicitRequest(method="elicitation/create",
                              params=t.ElicitRequestFormParams(message=message, requested_schema=schema))
        return t.InputRequiredResult(input_requests={key: req}, request_state=STATE + key)
    from mcp.shared.exceptions import MCPError, NoBackChannelError
    try:
        r = await ctx.session.elicit_form(message, schema, related_request_id=ctx.request_id)
    except NoBackChannelError:
        return None
    except MCPError:                                     # the client refused the request itself (not the person)
        return None
    return _reply(r)


def pending(r) -> bool:
    """r is the first round of a 2026-07-28 form: return it from the tool unchanged."""
    import mcp_types as t
    return isinstance(r, t.InputRequiredResult)


# -- channel 1: the ask folder (form/ask.py), unchanged ----------------------------------------------------------
async def wait_folder(folder: Path, qid: str, timeout: float) -> tuple[str, dict | None]:
    """Wait for the person to answer question qid in Form Studio's chat; close it on timeout or when the agent
    that asked has gone."""
    parent, t0 = os.getppid(), time.time()
    while True:
        st_, extra = ask_mod.state(folder, qid)
        if st_ != "open":
            return st_, extra
        if time.time() - t0 > timeout:
            ask_mod.close(folder, qid, "timeout")
        elif os.getppid() != parent:                      # the agent that asked is gone
            ask_mod.close(folder, qid, "ended")
        await anyio.sleep(0.25)


# -- ask_user ----------------------------------------------------------------------------------------------------
def _enum(choices: list[str]) -> list[dict]:
    return [{"const": c, "title": c} for c in choices]


def question_schema(q: dict) -> dict:
    """{answer: oneOf | multi-select array, text?: string}."""
    props: dict[str, Any] = {}
    required: list[str] = []
    cs = q.get("choices") or []
    if cs:
        if q.get("multi"):
            props["answer"] = {"type": "array", "title": "Answer", "items": {"anyOf": _enum(cs)}}
        else:
            props["answer"] = {"type": "string", "title": "Answer", "oneOf": _enum(cs)}
            if q.get("default"):
                props["answer"]["default"] = q["default"]
    if q.get("free") or not cs:
        props["text"] = {"type": "string", "title": "Your own answer" if cs else "Answer", "maxLength": 2000}
    if cs and not q.get("free"):
        required.append("answer")
    elif not cs:
        required.append("text")
    return {"type": "object", "properties": props, "required": required}


def question_message(q: dict) -> str:
    return q["question"] + (f"\n\n{q['why']}" if q.get("why") else "")


def _no_answer(reason: str) -> dict:
    why = {"declined": "The person declined to answer.",
           "cancelled": "The person closed the question without answering.",
           "empty": "The person sent the form without an answer."}.get(reason, "No answer was given.")
    return {"answered": False, "reason": reason,
            "note": why + " Continue only with what is safe to assume, mark those values assumed, and say in your "
                          "reply which answer would change the design."}


def _declined(r: Reply) -> str:
    return "declined" if r.action == "decline" else "cancelled"


def question_result(q: dict, r: Reply) -> dict:
    """What ask_user returns for an answer given in the client's form (the same keys as form/ask.py's result)."""
    if not r.accepted:
        return _no_answer(_declined(r))
    raw = r.content.get("answer")
    raw = raw if isinstance(raw, list) else [raw] if raw not in (None, "") else []
    picked = [c for c in (str(x) for x in raw) if c in (q.get("choices") or [])]
    if not q.get("multi"):
        picked = picked[:1]
    text = str(r.content.get("text") or "").strip()[:2000] if (q.get("free") or not q.get("choices")) else ""
    if not picked and not text:
        return _no_answer("empty")
    a = {"choices": picked, "text": text}
    return {"answered": True, "answer": ask_mod.answer_text(a), "choices": picked, "text": text,
            "note": "The person answered in your client's form. A number they type is what they told you; record it "
                    "as measured only if they say they measured it."}


async def ask(ctx, q: dict) -> Any:
    """ask_user: Form Studio's chat, then the client's form, then "nobody can answer here"."""
    folder = os.environ.get(ask_mod.ENV_DIR)
    if folder:
        timeout = ask_mod.timeout_from_env()
        qid = ask_mod.post(Path(folder), q, timeout)
        st_, extra = await wait_folder(Path(folder), qid, timeout)
        return ask_mod.result(q, st_, extra)
    r = await form(ctx, "answer", question_message(q), question_schema(q))
    if r is None:
        return ask_mod.unreachable(q)
    if pending(r):
        return r
    return question_result(q, r)


# -- ask_measurement ---------------------------------------------------------------------------------------------
def measurement_schema(q: dict, lo: float | None = None, hi: float | None = None) -> dict:
    """{value: number(min, max), method: caliper | ruler | datasheet, skipped: boolean}."""
    value: dict[str, Any] = {"type": "number", "title": f"Value ({q.get('unit') or 'mm'})"}
    if lo is not None and math.isfinite(lo):
        value["minimum"] = lo
    if hi is not None and math.isfinite(hi):
        value["maximum"] = hi
    return {"type": "object", "properties": {
        "value": value,
        "method": {"type": "string", "title": "How you got the number",
                   "oneOf": [{"const": "caliper", "title": "Calipers"}, {"const": "ruler", "title": "Ruler"},
                             {"const": "datasheet", "title": "Datasheet or drawing"}]},
        "skipped": {"type": "boolean", "title": "I can't measure this now", "default": False}},
        "required": []}


def measurement_message(q: dict) -> str:
    parts = [q["question"]]
    if q.get("where"):
        parts.append(f"Where: {q['where']}.")
    if q.get("tolerance_mm"):
        parts.append(f"Precision that matters: ±{q['tolerance_mm']:g} mm.")
    if q.get("current") is not None:
        parts.append(f"The design uses {q['current']:g} {q.get('unit') or 'mm'} now (assumed until measured).")
    return " ".join(parts)


def _measure_none(q: dict, reason: str, note: str | None = None) -> dict:
    out = _no_answer(reason) if note is None else {"answered": False, "reason": reason, "note": note}
    return {**out, "value": None, "unit": q.get("unit", "mm"), "method": None, "source": None, "rev": None}


def measurement_reply(q: dict, r: Reply, lo: float | None = None, hi: float | None = None):
    """(value, method) to commit, or the result to return when there is nothing to commit."""
    if not r.accepted:
        return _measure_none(q, _declined(r))
    c = r.content
    if c.get("skipped") is True:
        return _measure_none(q, "skipped", "The person could not measure it now. Keep the value assumed and say in "
                                           "your reply that measuring it would change the design.")
    method = MEASURE_METHODS.get(str(c.get("method") or ""))
    try:
        value = float(c.get("value"))
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or method is None:
        return _measure_none(q, "empty", "The person sent the form without a number and how they got it. Nothing "
                                         "was changed; the value stays assumed.")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        return _measure_none(q, "out_of_range", f"The person gave {value:g}, outside the parameter's range "
                                                f"({lo:g} to {hi:g}). Nothing was changed; ask again or check the unit.")
    return value, method


def record_measurement(st, project: str, param: str, value: float, method: str) -> dict:
    """Commit a measurement given in the client's form: calipers and ruler as measured (form/start.py), a datasheet
    value as specified."""
    from . import start
    if method != "datasheet":
        return start.apply_measurement(st, project, param, value, method)
    from .studio import StudioError
    p = st.load(project)
    try:
        spec = st.recipe(p).spec(param)
        unit, label = spec.unit, spec.label
    except Exception:
        unit, label = "mm", param
    prov = {"source": "specified", "note": "From a datasheet or drawing, given by the person"}
    try:
        p = st.commit(p, {param: value}, "From a datasheet", "user", {param: prov})
    except StudioError as e:
        if str(e) != "Nothing changed.":
            raise
        p = st.load(project)
    st.activity(project, "commit", f"r{p['head']:02d}: {label} {value:g} {unit}, from a datasheet", by="you")
    return {"rev": p["head"], "param": param, "value": value, "method": method, "source": "specified"}


def measurement_result(q: dict, rec: dict) -> dict:
    src, method, rev = rec["source"], rec["method"], rec["rev"]
    note = {"measured": f"The person measured it with {method}; the design was updated in r{rev}.",
            "specified": f"The person took it from a datasheet or drawing; recorded as specified in r{rev}.",
            "assumed": f"The person estimated it; it stays assumed. The design was updated in r{rev}."}[src]
    return {"answered": True, "value": rec["value"], "unit": q.get("unit", "mm"), "method": method, "source": src,
            "rev": rev, "text": "", "note": note}


# -- confirmations -----------------------------------------------------------------------------------------------
CONFIRM_DELETE = {"type": "object", "properties": {
    "confirm": {"type": "boolean", "title": "Move this project to the trash folder", "default": False}},
    "required": ["confirm"]}


def delete_message(name: str, pid: str, trash: Path) -> str:
    return (f"Delete the project “{name}” ({pid})? Its whole folder moves to {trash}/{pid}-<UTC time>. Nothing is "
            f"erased: moving the folder back restores it.")


def install_schema(licence: str = "") -> dict:
    title = f"Install and accept the licence ({licence})" if licence else "Install it"
    return {"type": "object", "properties": {"accept_licence": {"type": "boolean", "title": title, "default": False}},
            "required": ["accept_licence"]}


def install_message(plan: dict, licence: str = "", licence_url: str = "", noncommercial: bool = False) -> str:
    lines = [f"Install {plan['label']}" + (f" ({plan['size']})" if plan.get("size") else "") + "?",
             plan.get("why") or "", "It runs:", *[f"  {c}" for c in plan.get("commands") or []]]
    if plan.get("edits_a_file"):
        lines.append(str(plan["edits_a_file"]))
    if licence:
        lines.append(f"Licence: {licence}" + (f" ({licence_url})" if licence_url else "") + "."
                     + (" Non-commercial use only: installing accepts it." if noncommercial else ""))
    return "\n".join(x for x in lines if x)


DOWNLOAD_SCHEMA = {"type": "object", "properties": {
    "download": {"type": "boolean", "title": "Download it", "default": False}}, "required": ["download"]}


def download_message(url: str, size: int) -> str:
    return (f"Download {size / 1e6:,.0f} MB from {url}? Form Studio's engine saves it on this computer, under its "
            f"data folder.")


def link_size(url: str) -> int | None:
    """The bytes a fetch_link of url would download, when the link says so without downloading: a file link's
    Content-Length (HEAD), or the listed size of a model page's part files. None when it cannot be told."""
    from . import net, sources
    from . import start as start_mod
    try:
        kind = sources.classify(url)
        if kind == "page":
            return None
        if kind == "file":
            req = sources._request(url)
            req.method = "HEAD"
            with net.urlopen(req, timeout=15) as r:
                n = r.headers.get("Content-Length")
            return int(n) if n and str(n).isdigit() else None
        r = sources.resolve(url, generic=False)
        sizes = [f.get("size") for f in sources.model_files(r)[:start_mod.MAX_MODEL_FILES]]
        known = [int(s) for s in sizes if isinstance(s, (int, float)) and s > 0]
        return sum(known) if known else None
    except Exception:                                    # no answer is "do not know": the download goes ahead as today
        return None
