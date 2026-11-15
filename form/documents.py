"""Read reference documents (datasheets, mechanical drawings) as images an agent can look at.

Web fetch tools turn a PDF into text, and a mechanical drawing's dimensions are graphics, so they vanish.
This renders the pages instead. Files are kept in <data>/.references so the evidence stays with the designs.
"""
from __future__ import annotations

import hashlib
import io
import urllib.request
from pathlib import Path

MAX_BYTES = 25_000_000


def fetch(src: str, store: Path) -> Path:
    if src.startswith(("http://", "https://")):
        if not src.startswith("https://"):
            raise ValueError("Only https URLs are fetched.")
        req = urllib.request.Request(src, headers={"User-Agent": "FORM-studio/7 (reference fetch)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Document is larger than 25 MB.")
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
