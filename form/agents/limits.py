"""An agent that hit its plan's usage limit, said calmly: which agent, until when, what to do, what was kept.

The CLIs report it in their own words, often with an upsell ("Upgrade to Pro (https://...), visit https://... to
purchase more credits or try again at 9:34 PM"). Form Studio shows none of that text: only the facts.

    from form.agents import limits
    card = limits.usage_limit("You've hit your usage limit. Upgrade to Pro (...) or try again at 9:34 PM.", "Codex")
    card == {"kind": "usage_limit", "agent": "Codex", "until": "9:34 PM",
             "message": "Codex has reached its usage limit; it can work again at 9:34 PM. ...", "hint": "..."}
"""
from __future__ import annotations

import re
import time

_LIMIT = re.compile(
    r"usage limit|rate[ -]?limit(ed)?\b|limit (has been )?reached|reached (your|the) (usage |message )?limit|"
    r"hit your (usage )?limit|quota (exceeded|exhausted)|insufficient[_ ]quota|credit balance is too low|"
    r"out of (credits|messages)|too many requests|resource[_ ]exhausted|5-hour limit|weekly limit",
    re.I)
_UNTIL = [
    re.compile(r"try again (?:at|after|in) ([^.,;()\n]{1,40})", re.I),
    re.compile(r"resets? (?:at |on |in )?([^.,;()\n]{1,40})", re.I),      # "resets 11pm (Europe/Zurich)"
    re.compile(r"(?:available|back) (?:again )?(?:at|after) ([^.,;()\n]{1,40})", re.I),
]
_EPOCH = re.compile(r"limit reached\|(\d{10})")


def until(text: str) -> str | None:
    """When the limit lifts, as the agent said it (a time like "9:34 PM", or "in 2 hours"), or from an epoch."""
    m = _EPOCH.search(text or "")
    if m:
        try:
            return time.strftime("%H:%M", time.localtime(int(m.group(1))))
        except (ValueError, OverflowError):
            pass
    for rx in _UNTIL:
        m = rx.search(text or "")
        if m:
            return m.group(1).strip().rstrip(".")
    return None


def is_usage_limit(text: str) -> bool:
    return bool(_LIMIT.search(text or ""))


def usage_limit(text: str, agent: str, saved: list[str] | None = None, others: list[str] | None = None) -> dict | None:
    """A calm card for a usage-limit error, or None when the text is not one. saved: names of designs this run made
    (they are kept); others: other agents that are available now."""
    if not is_usage_limit(text):
        return None
    when = until(text)
    # "can work again at <time>": the app's card (Talk.qml, Store.usageLimit) reads the time from these words
    msg = f"{agent} has reached its usage limit" + (f"; it can work again at {when}" if when else " for now") + "."
    kept = "This conversation is saved"
    if saved:
        kept += "; so are the designs made before it stopped (" + ", ".join(saved[:4]) + (", ..." if len(saved) > 4 else "") + ")"
    msg += f" {kept}."
    alt = (f"Switch to {', '.join(others[:2])} in the agent menu to carry on now" if others else
           "Switch to another agent in the agent menu to carry on now")
    hint = alt + (f", or send the message again after {when}." if when else ", or send the message again later.")
    return {"kind": "usage_limit", "agent": agent, "until": when, "message": msg, "hint": hint}
