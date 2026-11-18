"""Find the recipe in a recipe issue: the "Recipe source" field, a link to the file, or an attached file.

    python scripts/ci/issue_recipe.py extract --event "$GITHUB_EVENT_PATH" --out DIR [--no-download]
    python scripts/ci/issue_recipe.py extract --issue 42 --out DIR          # reads the issue through the API

The same works for a discussion event (show-and-tell.yml): a pasted recipe or an attached archive is found the same way.

The issue body is data. It is parsed here and never reaches a shell. Downloads are limited to GitHub's own hosts
(issue attachments, raw.githubusercontent.com, gists, github.com blob links), follow redirects only to GitHub's
content hosts, and are size-limited. Nothing found is executed by this script.

DIR/submission.json:
    {"found": bool, "wants_check": bool, "mode": "source" | "archive" | null, "language": "python" | "openscad",
     "file": "recipe.py" | "recipe.scad" | "design.formstudio", "origin": "field" | "link" | "attachment" | "body",
     "origin_url": str | null, "sha256": hex of the file, "recipe_id": str | null, "id_problem": str | null,
     "tags": [str], "issue": {"number", "title", "author"}, "notes": [str]}
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GitHub, log, set_output  # noqa: E402

# Issue form labels (.github/ISSUE_TEMPLATE/3-recipe.yml). The body renders each field as "### <label>".
F_KIND = "This is"
F_ID = "Recipe id"
F_TAGS = "Tags"
F_SOURCE = "Recipe source"
F_LINK = "Link to the recipe file"
CHECK_CHOICE = "build and check it here"

MAX_SOURCE = 200_000
MAX_ARCHIVE = 25_000_000
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}[a-z0-9]$")
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com", "gist.githubusercontent.com", "gist.github.com",
                 "objects.githubusercontent.com", "github-production-user-asset-6210df.s3.amazonaws.com",
                 "private-user-images.githubusercontent.com"}
REDIRECT_HOSTS = ALLOWED_HOSTS
ATTACH_RE = re.compile(r"https://github\.com/(?:user-attachments/files/\d+|[\w.-]+/[\w.-]+/files/\d+)/[^\s)\]\"'<>]+")
EMPTY = {"", "_No response_", "None"}


def sections(body: str) -> dict[str, str]:
    """Issue-form body to {label: value}."""
    out, cur, buf = {}, None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return {k: ("" if v in EMPTY else v) for k, v in out.items()}


def fenced(text: str) -> list[tuple[str, str]]:
    """Fenced code blocks as (info string, code)."""
    return [(m.group(2).strip().lower(), m.group(3)) for m in
            re.finditer(r"^(`{3,}|~{3,})[ \t]*([^\n`]*)\n(.*?)^\1[ \t]*$", text or "", re.S | re.M)]


def looks_python_recipe(code: str) -> bool:
    return bool(re.search(r"^class\s+\w+\s*\([^)]*\bRecipe\b", code, re.M))


def looks_scad(code: str) -> bool:
    return bool(re.search(r"^\s*(module|function)\s+\w+\s*\(|\b(cube|cylinder|difference|union)\s*\(", code, re.M)) \
        and not looks_python_recipe(code)


def source_from_field(value: str) -> tuple[str, str] | None:
    blocks = fenced(value)
    code = blocks[0][1] if blocks else value
    code = code.strip("\n") + "\n"
    if looks_python_recipe(code):
        return code, "python"
    if looks_scad(code):
        return code, "openscad"
    return None


def raw_link(url: str) -> str | None:
    """A GitHub link to a file, as a URL that returns the file itself; None if the host is not allowed."""
    u = urllib.parse.urlparse(url.strip())
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        return None
    parts = [p for p in u.path.split("/") if p]
    if u.hostname == "github.com" and len(parts) >= 5 and parts[2] == "blob":
        return f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{'/'.join(parts[3:])}"
    if u.hostname == "gist.github.com" and len(parts) == 2:
        return f"https://gist.githubusercontent.com/{parts[0]}/{parts[1]}/raw"
    if u.hostname == "github.com" and not ATTACH_RE.match(url.strip()):
        return None
    return url.strip()


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlparse(newurl).hostname or ""
        if urllib.parse.urlparse(newurl).scheme != "https" or not (host in REDIRECT_HOSTS or host.endswith(".githubusercontent.com")):
            raise urllib.error.HTTPError(newurl, code, f"redirect to {host} is not allowed", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, limit: int) -> bytes:
    opener = urllib.request.build_opener(_Redirects)
    req = urllib.request.Request(url, headers={"User-Agent": "form-studio-automation"})
    with opener.open(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"larger than {limit // 1000} kB")
    return data


def from_bytes(name: str, data: bytes) -> dict:
    """Classify a downloaded file: a recipe source, a .formstudio/.formproj archive, or a zip with a recipe inside."""
    low = name.lower()
    if data[:4] == b"PK\x03\x04":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = [i.filename for i in z.infolist() if not i.is_dir()]
            if sum(i.file_size for i in z.infolist()) > 200_000_000:
                return {"error": "The archive unpacks to more than 200 MB."}
            if "manifest.json" in names or "project.json" in names:
                return {"mode": "archive", "data": data}
            cands = [n for n in names if n.rsplit("/", 1)[-1] in ("recipe.py", "recipe.scad")] or \
                    [n for n in names if n.endswith((".py", ".scad")) and "/." not in n and not n.startswith((".", "__"))]
            if len(cands) != 1:
                return {"error": f"The zip has {len(cands)} candidate recipe files; it should have one (recipe.py or recipe.scad)."}
            info = z.getinfo(cands[0])
            if info.file_size > MAX_SOURCE:
                return {"error": "The recipe file in the zip is larger than 200 kB."}
            name, data = cands[0], z.read(cands[0])
            low = name.lower()
        except zipfile.BadZipFile:
            return {"error": "The attachment is not a readable zip."}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": f"{name} is not UTF-8 text."}
    if len(data) > MAX_SOURCE:
        return {"error": "The recipe file is larger than 200 kB."}
    if low.endswith(".scad") or (not looks_python_recipe(text) and looks_scad(text)):
        return {"mode": "source", "language": "openscad", "text": text}
    if looks_python_recipe(text):
        return {"mode": "source", "language": "python", "text": text}
    return {"error": f"{name} does not define a subclass of Recipe."}


def extract(issue: dict, out: Path, allow_download: bool = True) -> dict:
    body = issue.get("body") or ""
    sec = sections(body)
    res = {"found": False, "wants_check": CHECK_CHOICE in sec.get(F_KIND, ""), "mode": None, "language": None,
           "file": None, "origin": None, "origin_url": None, "sha256": None, "recipe_id": None, "id_problem": None,
           "tags": [], "notes": [],
           "issue": {"number": issue.get("number"), "title": issue.get("title") or "",
                     "author": (issue.get("user") or {}).get("login")}}
    rid = sec.get(F_ID, "").strip().strip("`").lower()
    if rid:
        res["recipe_id"] = rid
        if not ID_RE.match(rid):
            res["id_problem"] = "The recipe id must be 3 to 42 lowercase letters, digits and hyphens, starting and ending with a letter or digit."
    tags = [t.strip().lower() for t in re.split(r"[,\n]", sec.get(F_TAGS, "")) if t.strip()]
    res["tags"] = [t[:30] for t in tags if re.fullmatch(r"[a-z0-9][a-z0-9 +&-]{0,29}", t)][:8]

    found = None
    if sec.get(F_SOURCE):
        got = source_from_field(sec[F_SOURCE])
        if got:
            found = {"mode": "source", "text": got[0], "language": got[1], "origin": "field"}
        else:
            res["notes"].append("The Recipe source field has no class that subclasses Recipe, and does not look like OpenSCAD.")
    urls = []
    if not found and sec.get(F_LINK):
        link = raw_link(sec[F_LINK].split()[0]) if sec[F_LINK].split() else None
        if link:
            urls.append(("link", link))
        else:
            res["notes"].append("The link is not a GitHub file, gist or issue attachment, so it was not fetched.")
    if not found:
        urls += [("attachment", u) for u in ATTACH_RE.findall(body)
                 if u.lower().endswith((".py", ".scad", ".txt", ".zip", ".formstudio", ".formproj"))]
    for origin, url in urls[:3]:
        if found:
            break
        if not allow_download:
            res["notes"].append("Download skipped.")
            break
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        try:
            data = download(url, MAX_ARCHIVE)
        except Exception as e:
            res["notes"].append(f"Could not fetch {name}: {e}")
            continue
        got = from_bytes(name, data)
        if got.get("error"):
            res["notes"].append(got["error"])
            continue
        found = {**got, "origin": origin, "origin_url": url}
    if not found:                                         # an older issue: a recipe pasted anywhere in the body
        for info, code in fenced(body):
            if looks_python_recipe(code):
                found = {"mode": "source", "text": code.strip("\n") + "\n", "language": "python", "origin": "body"}
                break
    if not found:
        return res
    out.mkdir(parents=True, exist_ok=True)
    if found["mode"] == "archive":
        f = out / "design.formstudio"
        f.write_bytes(found["data"])
        res["language"] = None
    else:
        f = out / ("recipe.scad" if found["language"] == "openscad" else "recipe.py")
        f.write_text(found["text"], encoding="utf-8")
        res["language"] = found["language"]
    res.update({"found": True, "mode": found["mode"], "file": f.name, "origin": found["origin"],
                "origin_url": found.get("origin_url"), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    src = e.add_mutually_exclusive_group(required=True)
    src.add_argument("--event", help="the issues event payload ($GITHUB_EVENT_PATH)")
    src.add_argument("--issue", type=int, help="read this issue through the API")
    e.add_argument("--out", required=True)
    e.add_argument("--no-download", action="store_true")
    a = ap.parse_args(argv)
    if a.event:
        ev = json.loads(Path(a.event).read_text(encoding="utf-8"))
        issue = ev.get("issue") or ev.get("discussion") or {}
    else:
        issue = GitHub().issue(a.issue)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res = extract(issue, out, not a.no_download)
    (out / "submission.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    log(json.dumps({k: res[k] for k in ("found", "wants_check", "mode", "origin", "file", "recipe_id", "notes")}))
    set_output("found", "true" if res["found"] else "false")
    set_output("wants_check", "true" if res["wants_check"] else "false")
    set_output("mode", res["mode"] or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
