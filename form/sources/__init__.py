"""Model links: turn a link someone pastes into the file it points to, when the site lets a logged-out visitor have it.

    resolve(url)          what the link is: a file, a model page on a site Form Studio knows, or any other page.
                          {"url", "site", "title", "author", "license", "images", "files", "downloadable", "reason", "how"}
    file_url(r, f)        the download address of one listed file (Printables hands one out per file)
    classify(url)         "file", a known site's name, or "page", without any network call

Sites:
    printables.py    Printables: its public GraphQL API lists a model's files and gives download links without an
                     account, the same calls its own pages make for a visitor who is not signed in.
    thingiverse.py   Thingiverse: its API needs an app token (FORM_THINGIVERSE_TOKEN, an application key the person
                     registers, sent only to api.thingiverse.com). Without one the files cannot be fetched: the site
                     turns away programs; the person downloads them in a browser.
    makerworld.py    MakerWorld: files are only given to a signed-in person. Form Studio does not sign in or borrow
                     browser cookies; it says so, reads the public page's title when the site allows it, and fetches a
                     signed download link the person pastes (they expire in minutes).
    generic.py       any other page: its OpenGraph title, description and pictures, as a visual reference. Nothing else
                     on the page is followed.

Rules every resolver keeps: only what a logged-out visitor can download; one generic user agent that names the app and
nothing about the person; no cookies (urllib keeps none), no credentials except Thingiverse's app token, never sent
anywhere else; nothing is crawled.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from .. import __version__, net

USER_AGENT = f"FormStudio/{__version__} (open-source CAD app; fetches a model link a person pasted)"
from ..formats import PART_KINDS as _PK, extensions as _exts     # noqa: E402

MODEL_EXT = _exts(*_PK, "2d", "archive")      # every part, scan, drawing and zip Form Studio reads (form/formats.py)
FILE_EXT = MODEL_EXT + _exts("document", "photo")
PAGE_LIMIT = 3_000_000                 # bytes of a web page or API answer read at most
TIMEOUT = 20


class SourceError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def _request(url: str, data: bytes | None = None, headers: dict | None = None, accept: str = "*/*"):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": accept})
    for k, v in (headers or {}).items():
        req.add_unredirected_header(k, v)          # never carried to another host on a redirect
    return req


def get(url: str, accept: str = "*/*", headers: dict | None = None, limit: int = PAGE_LIMIT, timeout: float = TIMEOUT
        ) -> tuple[bytes, str, str]:
    """(body, final url, content type) of a small GET. Raises SourceError with the site's answer."""
    host = urlparse(url).hostname or url
    try:
        with net.urlopen(_request(url, headers=headers, accept=accept), timeout=timeout) as r:
            body = r.read(limit + 1)
            return body[:limit], r.geturl(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:
        raise SourceError(f"{host} answered {e.code}.")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise SourceError(net.plain_error(e, host))


def post_json(url: str, obj: dict, timeout: float = TIMEOUT) -> dict:
    host = urlparse(url).hostname or url
    req = _request(url, json.dumps(obj).encode(), accept="application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with net.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(PAGE_LIMIT))
    except urllib.error.HTTPError as e:
        raise SourceError(f"{host} answered {e.code}.")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise SourceError(net.plain_error(e, host))
    except ValueError:
        raise SourceError(f"{host} sent an answer Form Studio cannot read.")


def file_name(url: str) -> str:
    return unquote(PurePosixPath(urlparse(url).path).name)


def _sites():
    from . import makerworld, printables, thingiverse
    return (printables, thingiverse, makerworld)


def site_for(url: str):
    host = (urlparse(url).hostname or "").lower()
    for s in _sites():
        if any(host == h or host.endswith("." + h) for h in s.HOSTS):
            return s
    return None


def classify(url: str) -> str:
    """"file" (a direct link to a file), a known site's name, or "page". No network."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise SourceError("Only http and https links can be opened.", "Paste a link that starts with https://.")
    site = site_for(url)
    if site is not None and site.model_id(url):
        return site.NAME
    if file_name(url).lower().endswith(FILE_EXT):
        return "file"
    return "page"


def blank(url: str, site: str) -> dict:
    return {"url": url, "site": site, "title": None, "author": None, "license": None, "images": [], "files": [],
            "downloadable": False, "reason": None, "how": None}


def resolve(url: str, generic: bool = True) -> dict:
    """What a link is and what can be fetched from it. generic=False: an unknown page is not read at all."""
    url = str(url or "").strip()
    kind = classify(url)
    if kind == "file":
        r = blank(url, "file")
        r.update(title=file_name(url), files=[{"name": file_name(url), "url": url}], downloadable=True)
        return r
    if kind == "page":
        if not generic:
            r = blank(url, "page")
            r["reason"] = "A web page, not a file; it was not read."
            return r
        from . import generic as gen
        return gen.resolve(url)
    return site_for(url).resolve(url)


def file_url(r: dict, f: dict) -> str:
    """The address to download one file of a resolved model from."""
    if f.get("url"):
        return f["url"]
    site = site_for(r["url"])
    if site is None or not hasattr(site, "file_url"):
        raise SourceError("That file has no download address.")
    return site.file_url(r, f)


def model_files(r: dict) -> list[dict]:
    """The listed files that are parts, scans, drawings or zips of them (form/formats.py), in the site's order."""
    return [f for f in r.get("files") or [] if str(f.get("name", "")).lower().endswith(MODEL_EXT)]


def clean_text(s, limit: int = 300) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[:limit] or None
