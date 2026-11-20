"""Thingiverse (thingiverse.com): files come through its API, which needs an app token. Its pages and zip downloads
turn away programs, so without a token the person downloads the files in a browser.

FORM_THINGIVERSE_TOKEN: an app token the person registered at thingiverse.com/developers. It identifies the app, not
the person, and is sent only to api.thingiverse.com (never on a redirect to the file host)."""
from __future__ import annotations

import json
import os
import re

from . import SourceError, blank, clean_text, get

NAME = "thingiverse"
HOSTS = ("thingiverse.com",)
API = "https://api.thingiverse.com"
_ID = re.compile(r"thing:(\d+)")
ENV_TOKEN = "FORM_THINGIVERSE_TOKEN"

REASON = "Thingiverse gives files only to browsers and registered apps; it turns away other programs."
HOW = ("Open the page, press Download All Files, unzip it and drop the STL or 3MF files here. Or set "
       "FORM_THINGIVERSE_TOKEN to a Thingiverse app token and paste the link again.")


def model_id(url: str) -> str | None:
    m = _ID.search(url)
    return m.group(1) if m else None


def token() -> str:
    return os.environ.get(ENV_TOKEN, "").strip()


def _api(path: str):
    body, _url, _ct = get(API + path, accept="application/json", headers={"Authorization": f"Bearer {token()}"})
    try:
        return json.loads(body)
    except ValueError:
        raise SourceError("Thingiverse sent an answer Form Studio cannot read.")


def resolve(url: str) -> dict:
    tid = model_id(url)
    r = blank(url, NAME)
    r["model_id"] = tid
    r["zip"] = f"https://www.thingiverse.com/thing:{tid}/zip"
    if not token():
        r.update(reason=REASON, how=HOW)
        return r
    thing = _api(f"/things/{tid}")
    files = _api(f"/things/{tid}/files")
    r.update(title=clean_text(thing.get("name")), author=clean_text((thing.get("creator") or {}).get("name")),
             license=clean_text(thing.get("license")))
    if thing.get("thumbnail"):
        r["images"] = [thing["thumbnail"]]
    r["files"] = [{"id": str(f["id"]), "name": f.get("name") or "file", "size": f.get("size"),
                   "api_url": f.get("download_url")} for f in files if isinstance(f, dict) and f.get("id")]
    r["downloadable"] = bool(r["files"])
    if not r["files"]:
        r["reason"] = "This thing lists no files."
    return r


def file_url(r: dict, f: dict) -> str:
    """The file's address. The API's download_url answers with a redirect to the file host; the token goes only to the
    API (an unredirected header), so the download itself carries nothing."""
    return f.get("api_url") or f"{API}/files/{f['id']}/download"


def headers_for(url: str) -> dict:
    """Headers for a download from this site: the app token, only for api.thingiverse.com."""
    return {"Authorization": f"Bearer {token()}"} if url.startswith(API + "/") and token() else {}
