"""An agent that hit its plan's usage limit, said calmly: which agent, until when, what to do, what was kept.

The CLIs report it in their own words, often with an upsell ("Upgrade to Pro (https://...), visit https://... to
purchase more credits or try again at 9:34 PM"). Form Studio shows none of that text: only the facts.

    from form.agents import limits
    card = limits.usage_limit("You've hit your usage limit. Upgrade to Pro (...) or try again at 9:34 PM.", "Codex")
    card == {"kind": "usage_limit", "agent": "Codex", "until": "9:34 PM", "again": "at 9:34 PM",
             "message": "Codex has reached its usage limit; it can work again at 9:34 PM. ...", "hint": "..."}

Only a usage limit of the person's plan is one: an API's short rate limit ("too many requests", "rate limited") is
an ordinary error that a retry fixes, and the app shows the card only for an event of kind "usage_limit".
"""
from __future__ import annotations

import re
import time

_LIMIT = re.compile(
    r"usage limit|usage limit reached|reached (your|the) (usage |message )?limit|"
    r"hit your (usage |5-hour |weekly )?limit|quota (exceeded|exhausted)|insufficient[_ ]quota|credit balance is too low|"
    r"out of (credits|messages)|5-hour limit|weekly limit",
    re.I)
_UNTIL = [
    re.compile(r"try again (at|after|in) ([^.,;()\n]{1,40})", re.I),
    re.compile(r"resets? (at |on |in )?([^.,;()\n]{1,40})", re.I),      # "resets 11pm (Europe/Zurich)"
    re.compile(r"(?:available|back) (?:again )?(at|after|in) ([^.,;()\n]{1,40})", re.I),
]
_EPOCH = re.compile(r"limit reached\|(\d{10})")
_DURATION = re.compile(r"^(?:about |around |roughly )?(?:an?|\d+(?:\.\d+)?|a few)\s*"
                       r"(?:h|hrs?|hours?|m|mins?|minutes?|s|secs?|seconds?|days?|weeks?)\b", re.I)
_DAYWORD = re.compile(r"^(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|tomorrow)", re.I)


def _when(text: str) -> tuple[str | None, str | None]:
    """(the time as the agent said it, the words for it after "can work again").
    "try again in 2 hours" -> ("2 hours", "in about 2 hours"); "try again at 9:34 PM" -> ("9:34 PM", "at 9:34 PM");
    an epoch -> ("21:05", "at 21:05") today, ("09:00", "at 09:00 on Sat 22 Nov") on another day."""
    m = _EPOCH.search(text or "")
    if m:
        try:
            t = time.localtime(int(m.group(1)))
            hm = time.strftime("%H:%M", t)
            if time.strftime("%Y-%m-%d", t) == time.strftime("%Y-%m-%d"):
                return hm, f"at {hm}"
            day = time.strftime("%a ", t) + str(t.tm_mday) + time.strftime(" %b", t)
            return hm, f"at {hm} on {day}"
        except (ValueError, OverflowError, OSError):
            pass
    for rx in _UNTIL:
        m = rx.search(text or "")
        if m:
            prep = (m.group(1) or "").strip().lower()
            when = m.group(2).strip().rstrip(".")
            if prep == "in" or _DURATION.match(when):
                return when, "in about " + re.sub(r"^(?:about|around|roughly) ", "", when, flags=re.I)
            if prep == "on" or _DAYWORD.match(when):
                return when, f"on {when}"
            return when, f"{'after' if prep == 'after' else 'at'} {when}"
    return None, None


def until(text: str) -> str | None:
    """When the limit lifts, as the agent said it (a time like "9:34 PM", or "2 hours"), or from an epoch."""
    return _when(text)[0]


def is_usage_limit(text: str) -> bool:
    return bool(_LIMIT.search(text or ""))


def usage_limit(text: str, agent: str, saved: list[str] | None = None, others: list[str] | None = None) -> dict | None:
    """A calm card for a usage-limit error, or None when the text is not one. saved: names of designs this run made
    (they are kept); others: other agents that are available now."""
    if not is_usage_limit(text):
        return None
    when, again = _when(text)
    # the app's card (Talk.qml, Store.usageLimit) shows `again`: "in about 2 hours", "at 9:34 PM"
    msg = f"{agent} has reached its usage limit" + (f"; it can work again {again}" if when else " for now") + "."
    kept = "This conversation is saved"
    if saved:
        kept += "; so are the designs made before it stopped (" + ", ".join(saved[:4]) + (", ..." if len(saved) > 4 else "") + ")"
    msg += f" {kept}."
    alt = (f"Switch to {', '.join(others[:2])} in the agent menu to carry on now" if others else
           "Switch to another agent in the agent menu to carry on now")
    hint = alt + (f", or send the message again {again}." if when else ", or send the message again later.")
    return {"kind": "usage_limit", "agent": agent, "until": when, "again": again, "message": msg, "hint": hint}
