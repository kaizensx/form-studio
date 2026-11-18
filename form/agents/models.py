"""Model names people can read, from the ids the CLIs actually report.

No model id is made up here. `pretty()` only reformats an id a CLI printed ("claude-opus-5-5" -> "Opus 5.5"), and
`Learned` remembers which id each alias resolved to the last time it ran ("opus" -> "claude-opus-5-5"), so the
picker can say "Opus 5.5" before the next message instead of only "Opus". `Recent` remembers which models replied,
per agent, so the menu can put them first and an agent opens on the model last used with it.
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

    def decorate(self, status: dict, recent: "Recent | None" = None) -> dict:
        """Put what was learned into an agent's model list: labels with versions, the resolved id in the note, the
        models last used with this agent (`recent`, newest first) and `last_model` (what picking the agent selects).

        Default shows a version only from something this agent itself said: a run asked for Default reported it, or
        the CLI's own config names the model (`configured` on the row, set by the adapter). Never another agent's."""
        out_status = dict(status)
        if recent is not None:
            ids = {m.get("id") for m in status.get("models") or []}
            used = [r for r in recent.list(status.get("id")) if r != "default" and (r in ids or status.get("kind") != "api")]
            out_status["recent"] = used[:6]
            out_status["last_model"] = recent.last(status.get("id"), ids if status.get("kind") == "api" else None)
        if status.get("kind") == "api":
            return out_status             # an API agent names its models itself, from the provider's list, every time
        mine = self.all().get(status.get("id"), {})
        mine = mine if isinstance(mine, dict) else {}
        who = status.get("label")
        out = []
        for m in status.get("models") or []:
            m = dict(m)
            got = mine.get(m.get("id"))
            if m.get("id") == "default":
                conf = m.get("configured")
                # what the CLI's own config names wins: it is what the next run uses
                via = mine.get(conf) if conf else None          # the config names an alias that was resolved before
                if conf:
                    lab = (via or {}).get("label") or m.get("configured_label") or pretty(conf)
                    m["label"] = "Default · " + lab
                    m["resolved"] = (got or via or {}).get("id") if (got or via or {}).get("id") else conf
                    m["resolved_label"] = lab
                    last = (got or {}).get("id")
                    if last and last != conf and last != (via or {}).get("id"):
                        m["note"] = (m.get("note") or "") + f" · the last run with Default reported {last}"
                elif got:
                    m["label"] = "Default · " + got["label"]
                    m["resolved"], m["resolved_label"] = got["id"], got["label"]
                    m["note"] = f"Currently {got['id']}, as reported by {who} on its last run with Default"
            elif got:
                m["resolved"], m["resolved_label"] = got["id"], got["label"]
                if m.get("label", "").lower() == m["id"].lower() or m.get("alias"):
                    m["label"] = got["label"]
                    m["note"] = f"{got['id']} · the alias “{m['id']}”, resolved by {who} on its last run"
            out.append(m)
        out_status["models"] = out
        return out_status


class Recent:
    """{agent: [{"id", "ts"}]} in <data>/.conversations/recent.json: the models a reply came from, newest first, per
    agent. Picking an agent selects the model last used with it, a provider's Default is its last-used model, and the
    model menu pins these on top. Only replies that finished without an error count, so a model id that failed does
    not become anyone's default."""

    KEEP = 12

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / ".conversations" / "recent.json"

    def all(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def list(self, agent: str | None) -> list[str]:
        rows = self.all().get(agent or "") or []
        rows = [r for r in rows if isinstance(r, dict) and r.get("id")]
        return [r["id"] for r in sorted(rows, key=lambda r: -float(r.get("ts") or 0))]

    def last(self, agent: str | None, known=None) -> str | None:
        """The model last used with `agent` ("default" counts: it was a choice). known: only ids in this set."""
        for mid in self.list(agent):
            if known is None or mid in known or mid == "default":
                return mid
        return None

    def use(self, agent: str, model: str, ts: float | None = None) -> None:
        if not agent or not model:
            return
        with _LOCK:
            d = self.all()
            rows = [r for r in d.get(agent) or [] if isinstance(r, dict) and r.get("id") and r["id"] != model]
            d[agent] = ([{"id": model, "ts": ts or time.time()}] + rows)[: self.KEEP]
            self._save(d)

    def _save(self, d: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def seed(self, learned: Learned) -> None:
        """First read after an update: learn from the replies already saved (each "end" without an error, with the
        model its "start" was asked for) and from what models.json learned on runs. Does work at most once."""
        if self.path.exists():
            return
        found: dict = {}
        for evf in sorted(self.path.parent.glob("*/events.jsonl")):
            asked: dict = {}
            done = None                  # a finished reply; it counts unless an error follows it (chat stores it after)

            def commit():
                if done:
                    found[done[0]] = max(found.get(done[0], 0), done[1])
            try:
                with open(evf, encoding="utf-8") as fh:
                    for line in fh:
                        if '"start"' not in line and '"end"' not in line and '"error"' not in line:
                            continue
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if e.get("t") == "start" and e.get("agent") and e.get("asked"):
                            commit()
                            done, asked = None, {"agent": e["agent"], "model": e["asked"], "ts": e.get("ts", 0)}
                        elif e.get("t") == "error":
                            done, asked = None, {}
                        elif e.get("t") == "end" and asked and e.get("agent") == asked["agent"]:
                            done = ((asked["agent"], asked["model"]), e.get("ts") or asked["ts"] or 0)
                commit()
            except OSError:
                continue
        for agent, ms in learned.all().items():
            for alias, v in (ms.items() if isinstance(ms, dict) else []):
                if isinstance(v, dict) and v.get("src") == "run":
                    found.setdefault((agent, alias), v.get("ts") or 0)
        d: dict = {}
        for (agent, model), ts in found.items():
            d.setdefault(agent, []).append({"id": model, "ts": ts})
        for agent in d:
            d[agent] = sorted(d[agent], key=lambda r: -float(r["ts"] or 0))[: self.KEEP]
        with _LOCK:
            self._save(d)
