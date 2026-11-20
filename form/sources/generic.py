"""Any other web page: its OpenGraph title, description and pictures (and <title>), as a visual reference. One GET of
the page; no link on it is followed."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

from . import SourceError, blank, clean_text, get


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.title, self._in_title = {}, "", False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, []).append(a["content"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "head":
            raise StopIteration

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(html: str, base: str) -> dict:
    p = _Meta()
    try:
        p.feed(html)
    except StopIteration:
        pass
    m = p.meta
    first = lambda *keys: next((m[k][0] for k in keys if m.get(k)), None)   # noqa: E731
    images = []
    for k in ("og:image", "og:image:url", "twitter:image"):
        for v in m.get(k, []):
            u = urljoin(base, v)
            if u.startswith(("http://", "https://")) and u not in images:
                images.append(u)
    return {"title": clean_text(first("og:title", "twitter:title") or p.title),
            "description": clean_text(first("og:description", "description", "twitter:description"), 600),
            "site_name": clean_text(first("og:site_name")), "images": images[:6]}


def read(url: str) -> dict:
    body, final, ctype = get(url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5", timeout=10)
    if ctype not in ("text/html", "application/xhtml+xml"):
        raise SourceError("That link is not a web page.")
    return parse(body.decode("utf-8", "replace"), final)


def resolve(url: str) -> dict:
    r = blank(url, "page")
    try:
        page = read(url)
        r.update(title=page["title"], images=page["images"], description=page["description"])
    except SourceError as e:
        r["page_error"] = str(e)
    r["reason"] = "A web page, not a file. Its title and pictures can serve as a visual reference."
    r["how"] = "If the page offers the model for download, download it and drop the file here, or paste the file's own link."
    return r
