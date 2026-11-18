"""Questions from the agent to the person, across processes.

The agent CLI runs Form Studio's MCP server as its own child process; the chat that started the agent (the app's
engine, or `form chat` in a terminal) is a different process. They meet in a folder of the conversation, given to
the MCP server as FORM_ASK_DIR:

    <qid>.q.json   the question, written by the MCP tool ask_user
    <qid>.a.json   the answer, written by the chat when the person answers
    <qid>.x.json   closed without an answer: {"reason": "timeout" | "stopped" | "ended"}
    <qid>.<ext>    the picture a measurement question points at (kind "measure", from ask_measurement)

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
KINDS = ("question", "confirm", "measure")
METHODS = ("calipers", "ruler", "tape", "estimate")      # how a measurement was taken; the choices of a "measure" card
SHAPES = ("box", "cylinder", "hole", "gap", "thickness")
AXES = ("x", "y", "z", "d")
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
    kind = kind if kind in KINDS else "question"
    if kind == "confirm" and not cs:
        cs = ["Yes", "No"]
    if kind == "measure":                                # the choices say how it was measured; the number is typed
        cs, multi, free = list(METHODS), False, True
    if not cs:
        free = True                                      # an open question is answered in words
    return {"question": q[:600], "choices": cs, "multi": bool(multi) and len(cs) > 1, "free": bool(free),
            "why": re.sub(r"\s+", " ", str(why or "")).strip()[:300], "kind": kind,
            "default": default if default in cs else None}


def measure_question(question_text: str, project: str, param: str, where: str = "", unit: str = "mm",
                     tolerance_mm=None, diagram=None, image: str | None = None, mark=None, current=None,
                     why: str = "") -> dict:
    """A guided measurement card: what to measure, where, how precisely, with a diagram or a marked picture.
    The person types the number and says how they measured it (METHODS)."""
    q = question(question_text, None, False, True, why, "measure")
    tol = None
    if tolerance_mm is not None:
        try:
            tol = float(tolerance_mm)
        except (TypeError, ValueError):
            raise AskError("tolerance_mm must be a number of millimetres.")
        if not 0 < tol < 1000:
            raise AskError("tolerance_mm must be greater than 0.")
    dia = None
    if diagram:
        if not isinstance(diagram, dict) or diagram.get("shape") not in SHAPES or diagram.get("axis", "x") not in AXES:
            raise AskError(f"diagram is {{\"shape\": {' | '.join(SHAPES)}, \"axis\": {' | '.join(AXES)}}}.")
        dia = {"shape": diagram["shape"], "axis": diagram.get("axis", "x")}
    mk = None
    if mark is not None:
        try:
            mk = [round(min(1.0, max(0.0, float(v))), 4) for v in mark]
        except (TypeError, ValueError):
            mk = []
        if len(mk) != 4:
            raise AskError("mark is [x0, y0, x1, y1], each between 0 and 1 on the image.")
    cur = None
    if current is not None:
        try:
            cur = float(current)
        except (TypeError, ValueError):
            cur = None
    q.update(project=str(project or "") or None, param=str(param or "") or None,
             unit=re.sub(r"\s+", " ", str(unit or "mm")).strip()[:12] or "mm", tolerance_mm=tol,
             where=re.sub(r"\s+", " ", str(where or "")).strip()[:300], diagram=dia,
             image=image if image and re.fullmatch(r"[0-9a-f]{10}\.(png|jpg|jpeg)", str(image)) else None,
             mark=mk, current=cur)
    return q


MEASURE_FIELDS = ("project", "param", "unit", "tolerance_mm", "where", "diagram", "image", "mark", "current")


def _write(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def post(folder: Path, q: dict, timeout: float = DEFAULT_TIMEOUT, qid: str | None = None) -> str:
    """Write the question. qid: one made with new_id() beforehand, when a file named after it (the picture of a
    measurement question) must be in the folder before the question appears."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    qid = qid if qid and QID_RE.fullmatch(qid) else new_id()
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


def read_question(folder: Path, qid: str) -> dict | None:
    if not QID_RE.fullmatch(str(qid or "")):
        return None
    return _read(Path(folder) / f"{qid}.q.json")


def answer(folder: Path, qid: str, text: str = "", choices: list | None = None, extra: dict | None = None) -> dict:
    """Record the person's answer. Choices must be among the offered ones; free text only if allowed.
    extra: what the answer did besides words (a measurement: value, method, source and the revision it made)."""
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
    a = {"choices": picked, "text": text, **(extra or {}), "ts": time.time()}
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


def measure_result(q: dict, st: str, extra: dict | None) -> dict:
    """What ask_measurement returns to the agent."""
    if st != "answered":
        return {**result(q, st, extra), "value": None, "unit": q.get("unit", "mm"), "method": None, "source": None, "rev": None}
    a = extra or {}
    method = a.get("method") or next((c for c in a.get("choices", []) if c in METHODS), None)
    value = a.get("value")
    if value is None:
        value = parse_number(a.get("text", ""))
    source = a.get("source") or (None if value is None else "assumed" if method in (None, "estimate") else "measured")
    note = {"measured": f"The person measured it with {method}" + (f"; the design was updated in r{a['rev']}."
                                                                     if a.get("rev") else "."),
            "assumed": "The person estimated it; it stays assumed."
                       + (f" The design was updated in r{a['rev']}." if a.get("rev") else "")}.get(
        source, "The person answered without a number: " + (a.get("text") or "") + ". Nothing was changed.")
    return {"answered": True, "value": value, "unit": q.get("unit", "mm"), "method": method, "source": source,
            "rev": a.get("rev"), "text": a.get("text", ""), "note": note}


def parse_number(text) -> float | None:
    """The number in an answer like "52.3", "52,3 mm" or "about 52"; None when there is none or more than one."""
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", str(text or ""))
    if len(nums) != 1:
        return None
    try:
        return float(nums[0].replace(",", "."))
    except ValueError:
        return None


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
