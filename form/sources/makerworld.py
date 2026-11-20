"""MakerWorld (makerworld.com): downloads are only given to a signed-in person, and the site blocks automated access.
Form Studio does not sign in, ask for a password or borrow the browser's cookies. It reads the public page's title
and picture when the site serves them to a visitor, says why the file cannot be fetched, and tells the person how to
get it: download it in the browser, or paste the download link the browser produces (it is signed and expires in
minutes; the engine fetches it at once, as a direct file link)."""
from __future__ import annotations

import re

from . import SourceError, blank

NAME = "makerworld"
HOSTS = ("makerworld.com",)
_ID = re.compile(r"/models/(\d+)")

REASON = ("MakerWorld only gives files to a signed-in person, and Form Studio does not sign in for you or use your "
          "browser's cookies.")
HOW = ("Open the page in your browser, sign in and press Download (3MF or STL), then drop the file here. Or copy the "
       "download link your browser gets and paste it here within a few minutes: those links expire quickly.")


def model_id(url: str) -> str | None:
    m = _ID.search(url)
    return m.group(1) if m else None


def resolve(url: str) -> dict:
    r = blank(url, NAME)
    r.update(model_id=model_id(url), reason=REASON, how=HOW)
    from . import generic
    try:                                             # the public page only; often refused to programs, which is fine
        page = generic.read(url)
        r.update(title=page.get("title"), images=page.get("images") or [], description=page.get("description"))
    except SourceError:
        pass
    return r
