"""Questions from the agent to the person, across processes.

The agent CLI runs Form Studio's MCP server as its own child process; the chat that started the agent (the app's
engine, or `form chat` in a terminal) is a different process. They meet in a folder of the conversation, given to
the MCP server as FORM_ASK_DIR:

    <qid>.q.json   the question, written by the MCP tool ask_user
    <qid>.a.json   the answer, written by the chat when the person answers
    <qid>.x.json   closed without an answer: {"reason": "timeout" | "stopped" | "ended"}

Without FORM_ASK_DIR nobody is reachable (an external agent using the MCP server directly): the tool says so and
the agent asks in its own interface. Nothing here guesses an answer.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

ENV_DIR = "FORM_ASK_DIR"
ENV_TIMEOUT = "FORM_ASK_TIMEOUT"
DEFAULT_TIMEOUT = 900.0            # seconds the agent waits for an answer
MAX_CHOICES = 8
QID_RE = re.compile(r"[0-9a-f]{10}")


class AskError(ValueError):
    pass


def question(question: str, choices: list | None = None, multi: bool = False, free: bool = True, why: str = "",
             kind: str = "question", default: str | None = None) -> dict:
    """A checked question record. kind "confirm" is an approval card: the first choice is the primary action."""
    q = re.sub(r"\s+", " ", str(question or "")).strip()
    if not q:
        raise AskError("ask_user needs a question.")
    cs = []
    for c in choices or []:
        c = re.sub(r"\s+", " ", str(c)).strip()[:80]
        if c and c not in cs:
            cs.append(c)
    if len(cs) > MAX_CHOICES:
        raise AskError(f"Offer at most {MAX_CHOICES} choices.")
    kind = kind if kind in ("question", "confirm") else "question"
    if kind == "confirm" and not cs:
        cs = ["Yes", "No"]
    if not cs:
        free = True                                      # an open question is answered in words
    return {"question": q[:600], "choices": cs, "multi": bool(multi) and len(cs) > 1, "free": bool(free),
            "why": re.sub(r"\s+", " ", str(why or "")).strip()[:300], "kind": kind,
            "default": default if default in cs else None}


def _write(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def post(folder: Path, q: dict, timeout: float = DEFAULT_TIMEOUT) -> str:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    qid = uuid.uuid4().hex[:10]
    _write(folder / f"{qid}.q.json", dict(q, id=qid, ts=time.time(), timeout=float(timeout)))
    return qid


def state(folder: Path, qid: str) -> tuple[str, dict | None]:
    """("open", None) | ("answered", answer) | ("closed", {"reason"})."""
    folder = Path(folder)
    a = _read(folder / f"{qid}.a.json")
    if a is not None:
        return "answered", a
    x = _read(folder / f"{qid}.x.json")
    if x is not None:
        return "closed", x
    return "open", None


def close(folder: Path, qid: str, reason: str) -> bool:
    """Close an open question without an answer. False if it was already answered or closed."""
    folder = Path(folder)
    if state(folder, qid)[0] != "open" or not (folder / f"{qid}.q.json").exists():
        return False
    _write(folder / f"{qid}.x.json", {"reason": reason, "ts": time.time()})
    return True


def answer(folder: Path, qid: str, text: str = "", choices: list | None = None) -> dict:
    """Record the person's answer. Choices must be among the offered ones; free text only if allowed."""
    folder = Path(folder)
    if not QID_RE.fullmatch(str(qid or "")):
        raise AskError("Unknown question.")
    q = _read(folder / f"{qid}.q.json")
    if q is None:
        raise AskError("Unknown question.")
    st, _ = state(folder, qid)
    if st != "open":
        raise AskError("This question was already answered or has closed." if st == "answered"
                       else "The agent stopped waiting for this answer.")
    picked = [c for c in (choices or []) if c in q.get("choices", [])]
    if not q.get("multi"):
        picked = picked[:1]
    text = str(text or "").strip()[:2000]
    if text and not q.get("free"):
        raise AskError("Pick one of the choices.")
    if not picked and not text:
        raise AskError("Pick a choice or write an answer.")
    a = {"choices": picked, "text": text, "ts": time.time()}
    _write(folder / f"{qid}.a.json", a)
    return a


def questions(folder: Path) -> list[dict]:
    """Every question in the folder, oldest first, with its state."""
    folder = Path(folder)
    out = []
    if not folder.is_dir():
        return out
    for f in folder.glob("*.q.json"):
        q = _read(f)
        if not q or not QID_RE.fullmatch(str(q.get("id", ""))):
            continue
        st, extra = state(folder, q["id"])
        out.append(dict(q, state=st, answer=extra if st == "answered" else None,
                        reason=(extra or {}).get("reason") if st == "closed" else None))
    out.sort(key=lambda q: q.get("ts", 0))
    return out


def close_all(folder: Path, reason: str) -> list[str]:
    return [q["id"] for q in questions(folder) if q["state"] == "open" and close(folder, q["id"], reason)]


def answer_text(a: dict) -> str:
    parts = []
    if a.get("choices"):
        parts.append(", ".join(a["choices"]))
    if a.get("text"):
        parts.append(a["text"])
    return " — ".join(parts)


def result(q: dict, st: str, extra: dict | None) -> dict:
    """What ask_user returns to the agent."""
    if st == "answered":
        return {"answered": True, "answer": answer_text(extra or {}), "choices": (extra or {}).get("choices", []),
                "text": (extra or {}).get("text", ""),
                "note": "The person answered in Form Studio. A number they type is what they told you; record it as "
                        "measured only if they say they measured it."}
    reason = (extra or {}).get("reason", "timeout")
    why = {"timeout": "The person did not answer in time.",
           "stopped": "The person stopped this reply.",
           "ended": "The conversation ended before an answer."}.get(reason, "No answer was given.")
    return {"answered": False, "reason": reason,
            "note": why + " Continue only with what is safe to assume, mark those values assumed, and say in your "
                          "reply which answer would change the design."}


def unreachable(q: dict) -> dict:
    return {"answered": False, "reason": "no_user",
            "note": "No Form Studio chat is attached to this session, so nobody can answer here. Ask the person this "
                    "question in your own interface, then continue with their answer.",
            "question": q["question"], "choices": q["choices"]}


def timeout_from_env() -> float:
    try:
        return max(5.0, float(os.environ.get(ENV_TIMEOUT) or DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def clean_suggestions(options) -> list[str]:
    out = []
    for o in options or []:
        o = re.sub(r"\s+", " ", str(o)).strip()[:140]
        if o and o not in out:
            out.append(o)
    return out[:3]
