"""Model names people can read, from the ids the CLIs actually report.

No model id is made up here. `pretty()` only reformats an id a CLI printed ("claude-opus-5-5" -> "Opus 5.5"), and
`Learned` remembers which id each alias resolved to the last time it ran ("opus" -> "claude-opus-5-5"), so the
picker can say "Opus 5.5" before the next message instead of only "Opus".
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

_UPPER = {"gpt": "GPT", "glm": "GLM", "oss": "OSS", "ai": "AI", "xl": "XL", "r1": "R1", "v3": "V3", "mini": "mini"}
_LOCK = threading.Lock()


def _word(w: str) -> str:
    lw = w.lower()
    if lw in _UPPER:
        return _UPPER[lw]
    return w[:1].upper() + w[1:] if w[:1].isalpha() else w


def pretty(model_id: str | None) -> str:
    """A readable name for a model id the CLI reported. Unknown shapes are tidied, never renamed."""
    s = str(model_id or "").strip()
    if not s:
        return ""
    if " " in s:                                  # already a display name (Cursor reports those)
        return s
    ctx = ""
    m = re.search(r"\[(\d+)([km])\]$", s, re.I)
    if m:
        ctx = f" ({m.group(1)}{m.group(2).upper()})"
        s = s[:m.start()]
    if "/" in s:                                  # provider/model (OpenCode, OpenRouter)
        s = s.rsplit("/", 1)[1]
    s = re.sub(r"^(?:[a-z]{2}\.)?anthropic\.", "", s)          # Bedrock: us.anthropic.claude-…-v1:0
    s = re.sub(r"-v\d+(?::\d+)?$", "", s)
    s = re.sub(r"@\d{8}$", "", s)                               # Vertex: claude-…@20250514
    if s.lower().startswith("claude-"):
        toks = [t for t in s.split("-")[1:] if t and not re.fullmatch(r"\d{8}|latest", t)]
        fam = [t for t in toks if not t.isdigit()]
        ver = [t for t in toks if t.isdigit() and len(t) <= 2]
        if fam:
            name = " ".join(_word(f) for f in fam)
            return (name + (" " + ".".join(ver) if ver else "")) + ctx
    if s.lower().startswith("gpt-"):
        rest = s[4:].split("-")
        return ("GPT-" + rest[0] + "".join(" " + _word(t) for t in rest[1:] if t)) + ctx
    toks = [t for t in re.split(r"[-_]", s) if t and not re.fullmatch(r"\d{8}|latest", t)]
    return " ".join(_word(t) for t in toks) + ctx


class Learned:
    """{agent: {alias: {"id", "label", "ts"}}} in <data>/.conversations/models.json."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / ".conversations" / "models.json"

    def all(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, agent: str, alias: str) -> dict | None:
        return self.all().get(agent, {}).get(alias or "default")

    def learn(self, agent: str, alias: str, model_id: str, label: str = "") -> None:
        if not model_id:
            return
        with _LOCK:
            d = self.all()
            d.setdefault(agent, {})[alias or "default"] = {"id": model_id, "label": label or pretty(model_id),
                                                         "ts": time.time()}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass

    def seed(self) -> None:
        """Once, for a data folder that has conversations from before this file existed: learn from their last reply."""
        if self.path.exists():
            return
        found: dict = {}
        for meta in sorted(self.path.parent.glob("*/meta.json")):
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if m.get("resolved_model") and m.get("agent"):
                key = (m["agent"], m.get("model") or "default")
                if key not in found or m.get("updated", 0) > found[key][1]:
                    found[key] = (m["resolved_model"], m.get("updated", 0))
        if not found:
            return
        for (agent, alias), (mid, _) in found.items():
            self.learn(agent, alias, mid)

    def decorate(self, status: dict) -> dict:
        """Put what was learned into an agent's model list (labels with versions, the resolved id in the note)."""
        mine = self.all().get(status.get("id"), {})
        out = []
        for m in status.get("models") or []:
            m = dict(m)
            got = mine.get(m.get("id"))
            if got:
                m["resolved"], m["resolved_label"] = got["id"], got["label"]
                if m["id"] == "default":
                    m["label"] = "Default · " + got["label"]
                    m["note"] = f"Currently {got['id']}, as reported by {status.get('label')} on its last run"
                elif m.get("label", "").lower() == m["id"].lower() or m.get("alias"):
                    m["label"] = got["label"]
                    m["note"] = f"{got['id']} · the alias “{m['id']}”, resolved by {status.get('label')} on its last run"
            out.append(m)
        return dict(status, models=out)
