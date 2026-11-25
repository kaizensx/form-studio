"""A small client for the Discord REST API (v10), used by the Form Studio bot in GitHub Actions.

The bot token comes from the DISCORD_BOT_TOKEN environment variable (a repository secret); it is never printed.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/kaizensx/form-studio, 1.0) FormStudio"


class DiscordError(RuntimeError):
    pass


def _token() -> str:
    t = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not t:
        raise DiscordError("DISCORD_BOT_TOKEN is not set (add it as a repository secret).")
    return t


def call(method: str, path: str, body=None, *, files: dict | None = None, reason: str = "") -> dict | list | None:
    """One request, retried on rate limits. files: {"name.png": bytes} sent as multipart with payload_json."""
    headers = {"Authorization": f"Bot {_token()}", "User-Agent": UA}
    if reason:
        headers["X-Audit-Log-Reason"] = reason[:500]
    if files:
        boundary = "formstudio" + os.urandom(8).hex()
        parts = []
        payload = dict(body or {})
        att = [{"id": i, "filename": n} for i, n in enumerate(files)]
        if "message" in payload:                       # a forum post: its first message carries the files
            payload["message"] = {**payload["message"], "attachments": att}
        else:
            payload["attachments"] = att
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                     f'Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n'.encode())
        for i, (name, data) in enumerate(files.items()):
            ctype = {"png": "image/png", "gif": "image/gif", "webp": "image/webp", "jpg": "image/jpeg",
                     "jpeg": "image/jpeg"}.get(
                name.rsplit(".", 1)[-1], "application/octet-stream")
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; filename="{name}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
    for attempt in range(6):
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429:
                try:
                    wait = float(json.loads(raw).get("retry_after", 1.0))
                except ValueError:
                    wait = 2.0
                time.sleep(min(wait, 30) + 0.25)
                continue
            if e.code >= 500 and attempt < 5:
                time.sleep(2 * (attempt + 1))
                continue
            raise DiscordError(f"{method} {path}: HTTP {e.code}: {raw[:400]}") from None
    raise DiscordError(f"{method} {path}: rate limited too long")


LIMIT = 2000                 # characters in one message
NO_LINK_PREVIEWS = 1 << 2    # the message flag SUPPRESS_EMBEDS: links stay links, no preview boxes under the text


def split_text(text: str, limit: int = 1900, lead: bool = False) -> list[str]:
    """Text as messages of at most `limit` characters, cut between paragraphs, never inside a code block. A "## "
    heading starts a new message once the current one is half full, so a section is not torn from its heading.
    lead: the text before the first "## " heading is a message of its own (a guide's title and introduction)."""
    blocks, cur, fenced = [], [], False
    for ln in text.strip().splitlines():
        if ln.lstrip().startswith("```"):
            fenced = not fenced
        if not ln.strip() and not fenced:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(ln.rstrip())
    if cur:
        blocks.append("\n".join(cur))
    out, buf, led = [], "", not lead
    for b in blocks:
        while len(b) > limit:                           # one paragraph longer than a message: cut at a line, then hard
            at = b.rfind("\n", 0, limit)
            at = at if at > 0 else limit
            head, b = b[:at], b[at:].lstrip("\n")
            if buf:
                out.append(buf)
                buf = ""
            out.append(head)
        heading = b.startswith("## ")
        first = heading and not led
        if buf and (len(buf) + 2 + len(b) > limit or first or (heading and len(buf) > limit // 2)):
            out.append(buf)
            buf = ""
        if heading:
            led = True
        buf = buf + "\n\n" + b if buf else b
    if buf:
        out.append(buf)
    return [x.strip() for x in out if x.strip()]


def send_text(channel_id: str, text: str, *, components: list | None = None, mentions: dict | None = None,
              files: dict | None = None) -> list[dict]:
    """Plain text as one message or several, in order. Buttons go under the last one, files on the first; links
    show no preview boxes. mentions: the allowed_mentions of the first message (nobody is pinged otherwise)."""
    parts = [p for seg in text.split("\n===\n") for p in split_text(seg)]
    sent = []
    for i, part in enumerate(parts):
        body = {"content": part, "flags": NO_LINK_PREVIEWS,
                "allowed_mentions": mentions if (mentions and i == 0) else {"parse": []}}
        if components and i == len(parts) - 1:
            body["components"] = components
        sent.append(call("POST", f"/channels/{channel_id}/messages", body, files=files if i == 0 else None))
    return sent


def link_button(label: str, url: str, emoji: str | None = None) -> dict:
    b = {"type": 2, "style": 5, "label": label[:80], "url": url}
    if emoji:
        b["emoji"] = {"name": emoji}
    return b


def row(*buttons) -> dict:
    return {"type": 1, "components": list(buttons)[:5]}
