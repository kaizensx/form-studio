"""Printables (printables.com): the public GraphQL API lists a model's files and hands out download links to visitors
who are not signed in, which is what the site's own Download button does for them."""
from __future__ import annotations

import re

from . import SourceError, blank, clean_text, post_json

NAME = "printables"
HOSTS = ("printables.com",)
API = "https://api.printables.com/graphql/"
_ID = re.compile(r"/model/(\d+)")

QUERY = ("query Print($id: ID!) { print(id: $id) { id name slug license { name abbreviation } "
         "user { publicUsername } image { filePath } stls { id name fileSize } otherFiles { id name fileSize } } }")
LINK = ("mutation Link($id: ID!, $printId: ID!, $fileType: DownloadFileTypeEnum!) { getDownloadLink(id: $id, "
        "printId: $printId, fileType: $fileType, source: model_detail) { ok output { link } } }")


def model_id(url: str) -> str | None:
    m = _ID.search(url)
    return m.group(1) if m else None


def _data(answer: dict) -> dict:
    if not isinstance(answer, dict) or answer.get("errors") or not isinstance(answer.get("data"), dict):
        raise SourceError("Printables did not share this model's files.",
                          "Open the page in a browser; if it downloads there, save the file and drop it here.")
    return answer["data"]


def resolve(url: str) -> dict:
    pid = model_id(url)
    r = blank(url, NAME)
    p = _data(post_json(API, {"query": QUERY, "variables": {"id": pid}})).get("print")
    if not p:
        raise SourceError("Printables has no public model with that number.", "Check the link.")
    lic = p.get("license") or {}
    r.update(title=clean_text(p.get("name")), author=clean_text((p.get("user") or {}).get("publicUsername")),
             license=clean_text(lic.get("name")) or clean_text(lic.get("abbreviation")), model_id=str(p.get("id") or pid))
    img = (p.get("image") or {}).get("filePath")
    if img:
        r["images"] = ["https://media.printables.com/" + img.lstrip("/")]
    files = [{"id": str(f["id"]), "name": f.get("name") or "file", "size": f.get("fileSize"), "type": "stl"}
             for f in p.get("stls") or [] if f.get("id")]
    files += [{"id": str(f["id"]), "name": f.get("name") or "file", "size": f.get("fileSize"), "type": "other"}
              for f in p.get("otherFiles") or [] if f.get("id")]
    r["files"] = files
    r["downloadable"] = bool(files)
    if not files:
        r["reason"] = "This model lists no files a visitor can download."
    return r


def file_url(r: dict, f: dict) -> str:
    ans = post_json(API, {"query": LINK, "variables": {"id": f["id"], "printId": r["model_id"], "fileType": f["type"]}})
    link = ((_data(ans).get("getDownloadLink") or {}).get("output") or {}).get("link")
    if not link:
        raise SourceError(f"Printables gave no download link for {f['name']}.",
                          "Open the page in a browser and download it there.")
    return link
