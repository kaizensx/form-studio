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
        """Remember what `alias` resolved to on a run of `agent` that just reported it."""
        if not model_id or not agent:
            return
        with _LOCK:
            d = self.all()
            d.setdefault(agent, {})[alias or "default"] = {"id": model_id, "label": label or pretty(model_id),
                                                         "ts": time.time(), "src": "run"}
            self._save(d)

    def _save(self, d: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _reported(self) -> dict:
        """{(agent, alias): (model id, ts)} from what each agent itself reported, in every saved conversation.

        Only a "start" or "end" event names the agent that ran and the alias it was asked for, so this is the one
        source that cannot mix agents up: a conversation's meta keeps the last model it saw even after its agent is
        switched (that is how a Claude model once ended up listed as Codex's default)."""
        found: dict = {}
        for evf in sorted(self.path.parent.glob("*/events.jsonl")):
            asked: dict = {}
            try:
                with open(evf, encoding="utf-8") as fh:
                    for line in fh:
                        if '"start"' not in line and '"end"' not in line:
                            continue
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if e.get("t") == "start" and e.get("agent"):
                            asked[e["agent"]] = e.get("asked")
                        if e.get("t") not in ("start", "end") or not e.get("agent") or not e.get("model"):
                            continue
                        alias = e.get("asked") if e.get("t") == "start" else asked.get(e["agent"])
                        if alias is None:
                            continue                      # saved before runs recorded what they were asked for
                        key = (e["agent"], alias or "default")
                        if key not in found or e.get("ts", 0) >= found[key][1]:
                            found[key] = (e["model"], e.get("ts", 0))
            except OSError:
                continue
        return found

    def seed(self) -> None:
        """Make the file trustworthy before it is shown. Called with every status read; does work at most once.

        - No file yet (conversations from before it existed): learn from what each agent reported in them.
        - Entries written by an earlier Form Studio (no "src"): keep only those an agent's own report confirms, so a
          model learned under the wrong agent is dropped and the picker shows that agent's real default again."""
        with _LOCK:
            exists = self.path.exists()
            d = self.all()
            legacy = [(a, k) for a, ms in d.items() if isinstance(ms, dict)
                      for k, v in ms.items() if isinstance(v, dict) and v.get("src") != "run"]
            if exists and not legacy:
                return
            reported = self._reported()
            if not exists:
                if not reported:
                    return
                for (agent, alias), (mid, ts) in reported.items():
                    d.setdefault(agent, {})[alias] = {"id": mid, "label": pretty(mid), "ts": ts or time.time(), "src": "run"}
                self._save(d)
                return
            for agent, alias in legacy:
                got = reported.get((agent, alias))
                if got and got[0] == d[agent][alias].get("id"):
                    d[agent][alias]["src"] = "run"
                else:
                    del d[agent][alias]
            for agent in [a for a, ms in d.items() if isinstance(ms, dict) and not ms]:
                del d[agent]
            self._save(d)

    def decorate(self, status: dict) -> dict:
        """Put what was learned into an agent's model list (labels with versions, the resolved id in the note)."""
        if status.get("kind") == "api":
            return status                 # an API agent names its models itself, from the provider's list, every time
        mine = self.all().get(status.get("id"), {})
        mine = mine if isinstance(mine, dict) else {}
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
