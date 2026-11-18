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

# Form Studio's palette (form/app/qml/Form/Theme.qml), as Discord colour integers
PLATE = 0x0E1113
DATUM = 0xB9E8D7
BLUEPRINT = 0x86A8FF
AMBER = 0xE9B860
SIGNAL = 0xFF6F51
PASS = 0x86D9AD
VIOLET = 0xC7B2FF
CLAY = 0xD8D3C8


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
            ctype = {"png": "image/png", "gif": "image/gif", "webp": "image/webp", "jpg": "image/jpeg"}.get(
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


def send(channel_id: str, content: str = "", embeds: list | None = None, components: list | None = None,
         files: dict | None = None) -> dict:
    body = {"content": content[:2000], "embeds": embeds or [], "allowed_mentions": {"parse": []}}
    if components:
        body["components"] = components
    return call("POST", f"/channels/{channel_id}/messages", body, files=files)


def footer(section: str, sig: str = "") -> dict:
    """The footer every Form Studio embed carries: the mark and "Form Studio · Section".
    sig (a hash of the post) rides on the icon's address, invisible, so setup can tell a post is current."""
    from server import ICON
    return {"text": f"Form Studio · {section}", "icon_url": ICON + (f"?v={sig}" if sig else "")}


def link_button(label: str, url: str, emoji: str | None = None) -> dict:
    b = {"type": 2, "style": 5, "label": label[:80], "url": url}
    if emoji:
        b["emoji"] = {"name": emoji}
    return b


def row(*buttons) -> dict:
    return {"type": 1, "components": list(buttons)[:5]}
