"""Read reference documents (datasheets, mechanical drawings) as images an agent can look at.

Web fetch tools turn a PDF into text, and a mechanical drawing's dimensions are graphics, so they vanish.
This renders the pages instead. Files are kept in <data>/.references so the evidence stays with the designs.
"""
from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from pathlib import Path

from . import net

MAX_BYTES = 25_000_000


def fetch(src: str, store: Path) -> Path:
    if src.startswith(("http://", "https://")):
        data = _download(src)
    else:
        p = Path(src).expanduser()
        if not p.is_file():
            raise ValueError(f"No such file: {src}")
        data = p.read_bytes()[: MAX_BYTES + 1]
    kind = "pdf" if data[:5] == b"%PDF-" else _image_kind(data)
    if not kind:
        raise ValueError("Not a PDF or an image (PNG, JPEG, WebP).")
    store.mkdir(parents=True, exist_ok=True)
    out = store / f"{hashlib.sha256(data).hexdigest()[:16]}.{kind}"
    if not out.exists():
        out.write_bytes(data)
    return out


def _download(src: str) -> bytes:
    """A public document over the web. Manufacturers often still link http://: try the https address first, and
    fall back to the plain one only when the site has no working https (it is read, never sent anything)."""
    tries = [src] if src.startswith("https://") else ["https://" + src[len("http://"):], src]
    last = None
    for url in tries:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Form-Studio; reference fetch)",
                                                   "Accept": "application/pdf,image/*;q=0.9,*/*;q=0.5"})
        try:
            with net.urlopen(req, timeout=30) as r:
                data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Document is larger than 25 MB.")
            return data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise ValueError(f"The site refused the download ({e.code}): it only serves browsers. Download the file "
                                 "in your browser and attach it to the conversation.") from None
            raise ValueError(f"The site answered {e.code} {e.reason}.") from None
        except (urllib.error.URLError, OSError) as e:
            last = e
    reason = getattr(last, "reason", last)
    raise ValueError(f"Could not reach the site: {reason}.")


def _image_kind(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _pages(spec: str, n: int) -> list[int]:
    out = []
    for part in (spec or "1").split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return [p for p in out if 1 <= p <= n][:4]


def render(path: Path, pages: str = "1", max_px: int = 2000) -> dict:
    """Returns {"images": [png bytes], "text": str, "pages": [n], "page_count": n}."""
    from PIL import Image
    if path.suffix != ".pdf":
        im = Image.open(path).convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return {"images": [buf.getvalue()], "text": "", "pages": [1], "page_count": 1}
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    want = _pages(pages, len(pdf))
    imgs, texts = [], []
    for n in want:
        page = pdf[n - 1]
        w, h = page.get_size()
        scale = min(3.0, max_px / max(w, h))
        im = page.render(scale=scale).to_pil().convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        imgs.append(buf.getvalue())
        try:
            texts.append(page.get_textpage().get_text_range()[:6000])
        except Exception:
            texts.append("")
    return {"images": imgs, "text": "\n\n".join(t for t in texts if t.strip()), "pages": want, "page_count": len(pdf)}
