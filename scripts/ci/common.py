"""Shared helpers for Form Studio's GitHub automation. Standard library only, so the privileged jobs that post
results never install or import anything from the code under test.

Everything a job reads from an artifact made by another job is untrusted data: read it with `load_json` (size and
type limits), check images with `png_info`, and put text into Markdown only through `md`/`code`.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "kaizensx/form-studio")
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
ASSETS_BRANCH = "ci-assets"
SIGNATURE = "Form Studio automation"
BOT_NAME = "Form Studio automation"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

MAX_JSON = 4_000_000
MAX_PNG = 3_000_000
MAX_GIF = 8_000_000


# ---- output ------------------------------------------------------------------------------------------------------

def log(*a) -> None:
    print(*a, file=sys.stderr, flush=True)


def set_output(name: str, value) -> None:
    """A step output (GITHUB_OUTPUT); printed when run locally."""
    value = value if isinstance(value, str) else json.dumps(value)
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        delim = f"EOF_{os.urandom(8).hex()}"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}<<{delim}\n{value}\n{delim}\n")
    else:
        log(f"output {name}={value}")


def summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def run_url() -> str:
    rid = os.environ.get("GITHUB_RUN_ID")
    return f"{SERVER}/{REPO}/actions/runs/{rid}" if rid else f"{SERVER}/{REPO}/actions"


# ---- untrusted data ------------------------------------------------------------------------------------------------

def load_json(path, limit: int = MAX_JSON, kind=dict):
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        raise ValueError(f"{p.name}: missing")
    if p.stat().st_size > limit:
        raise ValueError(f"{p.name}: larger than {limit} bytes")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, kind):
        raise ValueError(f"{p.name}: not a JSON {kind.__name__}")
    return data


def png_info(path, limit: int = MAX_PNG) -> tuple[int, int] | None:
    """(width, height) when the file is a real PNG within limits; None otherwise."""
    p = Path(path)
    try:
        if not p.is_file() or p.is_symlink() or p.stat().st_size > limit:
            return None
        with open(p, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return (w, h) if 0 < w <= 6000 and 0 < h <= 6000 else None


def gif_info(path, limit: int = MAX_GIF) -> tuple[int, int] | None:
    p = Path(path)
    try:
        if not p.is_file() or p.is_symlink() or p.stat().st_size > limit:
            return None
        with open(p, "rb") as f:
            head = f.read(10)
    except OSError:
        return None
    if head[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w, h = struct.unpack("<HH", head[6:10])
    return (w, h) if 0 < w <= 4000 and 0 < h <= 4000 else None


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-!|~])")


def md(value, limit: int = 300) -> str:
    """Untrusted text as inert Markdown: one line, escaped, no HTML, no mentions, no links."""
    s = "" if value is None else str(value)
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = "".join(ch for ch in s if ch.isprintable())
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    s = _MD_SPECIAL.sub(r"\\\1", s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("@", "@​")                           # never a mention
    s = re.sub(r"(?i)(https?|ftp|www)", lambda m: m.group(0)[0] + "​" + m.group(0)[1:], s)   # never a link
    return s


def code(value, limit: int = 120) -> str:
    """Untrusted text as inline code."""
    s = re.sub(r"[\r\n\t`]+", " ", "" if value is None else str(value))
    s = "".join(ch for ch in s if ch.isprintable())[:limit]
    return f"`{s}`" if s.strip() else ""


def num(value, fmt: str = "{:.1f}", default: str = "—") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return default
    return fmt.format(value)


def safe_name(name: str) -> str | None:
    """A plain file name: letters, digits, dot, dash, underscore; no path."""
    return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name or "") and ".." not in name else None


# ---- GitHub REST -------------------------------------------------------------------------------------------------

class GitHub:
    """A small REST client. The token comes from the environment (GITHUB_TOKEN or GH_TOKEN), never from arguments."""

    def __init__(self, token: str | None = None, repo: str = REPO, dry_run: bool = False):
        self.token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
        self.repo = repo
        self.dry_run = dry_run
        self.calls: list[tuple[str, str, object]] = []

    def request(self, method: str, path: str, body=None, accept: str = "application/vnd.github+json", ok404: bool = False):
        url = path if path.startswith("http") else f"{API}{path}"
        if self.dry_run and method != "GET" and path != "/graphql":
            self.calls.append((method, path, body))
            log(f"[dry-run] {method} {path}")
            return {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", accept)
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "form-studio-automation")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 404 and ok404:
                    return None
                if e.code in (502, 503, 504) or (e.code in (403, 429) and e.headers.get("Retry-After")):
                    time.sleep(min(int(e.headers.get("Retry-After") or 5 * (attempt + 1)), 60))
                    continue
                detail = e.read()[:500].decode("utf-8", "replace")
                raise RuntimeError(f"GitHub API {method} {path}: HTTP {e.code} {detail}") from None
            except urllib.error.URLError:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"GitHub API {method} {path}: gave up")

    def r(self, path: str) -> str:
        return f"/repos/{self.repo}{path}"

    def paginate(self, path: str, limit: int = 1000) -> list:
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while len(out) < limit:
            chunk = self.request("GET", f"{path}{sep}per_page=100&page={page}")
            if not isinstance(chunk, list) or not chunk:
                break
            out.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return out[:limit]

    # issues and comments
    def issue(self, n: int) -> dict:
        return self.request("GET", self.r(f"/issues/{int(n)}"))

    def upsert_comment(self, n: int, marker: str, body: str) -> dict:
        """One comment per marker per issue or pull request: edited in place on every run."""
        body = f"{body}\n\n<!-- {marker} -->"
        for c in self.paginate(self.r(f"/issues/{int(n)}/comments"), 500):
            user = (c.get("user") or {}).get("login", "")
            if f"<!-- {marker} -->" in (c.get("body") or "") and user.endswith("[bot]"):
                return self.request("PATCH", self.r(f"/issues/comments/{c['id']}"), {"body": body})
        return self.request("POST", self.r(f"/issues/{int(n)}/comments"), {"body": body})

    def ensure_label(self, name: str, color: str, description: str) -> None:
        if self.request("GET", self.r(f"/labels/{urllib.parse.quote(name, safe='')}"), ok404=True) is None:
            self.request("POST", self.r("/labels"), {"name": name, "color": color, "description": description})

    def add_labels(self, n: int, names: list[str]) -> None:
        if names:
            self.request("POST", self.r(f"/issues/{int(n)}/labels"), {"labels": names})

    def remove_label(self, n: int, name: str) -> None:
        self.request("DELETE", self.r(f"/issues/{int(n)}/labels/{urllib.parse.quote(name, safe='')}"), ok404=True)

    def graphql(self, query: str, variables: dict) -> dict:
        if self.dry_run and query.lstrip().startswith("mutation"):
            self.calls.append(("GRAPHQL", query, variables))
            log("[dry-run] graphql mutation")
            return {}
        r = self.request("POST", "/graphql", {"query": query, "variables": variables})
        if r.get("errors"):
            raise RuntimeError(f"GraphQL: {r['errors']}")
        return r.get("data") or {}

    def permission(self, login: str) -> str:
        r = self.request("GET", self.r(f"/collaborators/{urllib.parse.quote(login)}/permission"), ok404=True)
        return (r or {}).get("permission", "none")


def raw_url(path: str, branch: str = ASSETS_BRANCH, repo: str = REPO) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{urllib.parse.quote(path)}"


def checks_table(checks: list) -> list[str]:
    """A design's checks as a Markdown table, every value escaped."""
    rows = ["| Result | Check | Value | Evidence |", "|---|---|---|---|"]
    for c in checks[:30]:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status", ""))
        status = {"PASS": "Pass", "WARN": "**Warning**", "FAIL": "**Fail**"}.get(status, md(status, 10))
        rows.append(f"| {status} | {md(c.get('label'), 80)} | {md(c.get('value'), 60)} | {md(c.get('evidence'), 20)} |")
    return rows


def fmt_time(seconds) -> str:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return "—"
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"
