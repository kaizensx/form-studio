"""A small typesetter for Form Studio's documents: vector PDF pages set in Geist, the app's own type.

The test plan and the results report (form/reports.py) are documents a person prints, fills in, signs and files, so
they are real PDF text (selectable, searchable, sharp at any zoom), not pictures of text. Geist and Geist Mono ship
with the app (form/app/assets/fonts, SIL OFL 1.1); the variable fonts are cut to the weights a page uses with
fontTools (already installed with build123d), subset to the glyphs the document uses and embedded, so the file looks
the same on every computer. Nothing is downloaded.

    doc = Doc("Test plan", stamp="Bracket · r03")
    doc.overline("Form Studio · test plan")
    doc.title("Bracket")
    doc.table([Col("Test", 0.4), Col("Limits", 0.3, mono=True), Col("Status", 0.3)], rows)
    data = doc.pdf()                     # bytes

The page is the light Lightdesk sheet: warm paper, ink in three tones, one accent, the evidence colours, mono capitals
for labels and evidence classes (docs/design/DIRECTION.md). A4 portrait, 18 mm margins.
"""
from __future__ import annotations

import io
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

FONTS = Path(__file__).resolve().parent / "app" / "assets" / "fonts"
MM = 72 / 25.4
A4 = (595.28, 841.89)
MARGIN = 18 * MM

# Lightdesk, light: docs/design/directions/i/style.css (html.light)
INK = (0x16, 0x16, 0x16)
INK2 = (0x56, 0x55, 0x4f)
INK3 = (0x7d, 0x7c, 0x77)
RULE = (0xdd, 0xda, 0xd4)
WASH = (0xf3, 0xf1, 0xec)
PAPER = (0xfb, 0xfa, 0xf7)
ACCENT = (0x06, 0x70, 0x8d)
PASS = (0x1a, 0x7a, 0x3a)
WARN = (0x9a, 0x61, 0x00)
FAIL = (0xb3, 0x30, 0x1f)
TONES = {"ink": INK, "ink2": INK2, "ink3": INK3, "accent": ACCENT, "pass": PASS, "warn": WARN, "fail": FAIL}

# characters Geist does not draw, written with ones it does
SUBST = {"≤": "<=", "≥": ">=", "⌀": "Ø", "→": "->", "✓": "", "Δ": "delta ", "Σ": "sum ", "□": "", "■": "", "\t": " "}


# ---- fonts ---------------------------------------------------------------------------------------------------------
_CACHE: dict = {}


class Face:
    """One weight of one family, instanced from the variable font, with its metrics in 1/1000 em."""

    def __init__(self, family: str, weight: int):
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
        key = (family, weight)
        if key not in _CACHE:
            f = TTFont(FONTS / f"{family}.ttf")
            if "fvar" in f:
                f = instancer.instantiateVariableFont(f, {"wght": weight})
            buf = io.BytesIO()
            f.save(buf)
            _CACHE[key] = buf.getvalue()
        from fontTools.ttLib import TTFont as _T
        self.family, self.weight, self.data = family, weight, _CACHE[key]
        self.font = _T(io.BytesIO(self.data))
        upm = self.font["head"].unitsPerEm
        self.scale = 1000.0 / upm
        self.cmap = self.font.getBestCmap()
        self.order = self.font.getGlyphOrder()
        self.gid = {n: i for i, n in enumerate(self.order)}
        self.hmtx = self.font["hmtx"].metrics
        os2 = self.font["OS/2"]
        self.ascent = os2.sTypoAscender * self.scale
        self.descent = os2.sTypoDescender * self.scale
        self.cap = getattr(os2, "sCapHeight", 700) * self.scale
        h = self.font["head"]
        self.bbox = [h.xMin * self.scale, h.yMin * self.scale, h.xMax * self.scale, h.yMax * self.scale]
        self.used: dict[int, str] = {}

    def glyphs(self, text: str) -> list[int]:
        out = []
        for ch in text:
            name = self.cmap.get(ord(ch))
            g = self.gid.get(name, 0) if name else 0
            if g and ch not in "\n":
                self.used.setdefault(g, ch)
            out.append(g)
        return out

    def advance(self, g: int) -> float:
        return self.hmtx[self.order[g]][0] * self.scale

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        gs = self.glyphs(text)
        return sum(self.advance(g) for g in gs) * size / 1000.0 + tracking * size * max(0, len(gs))

    def subset(self) -> bytes:
        import logging
        from fontTools import subset as fsub
        from fontTools.ttLib import TTFont
        logging.getLogger("fontTools").setLevel(logging.WARNING)      # its subsetter reports every table at INFO
        f = TTFont(io.BytesIO(self.data))
        opt = fsub.Options()
        opt.retain_gids = True                 # the page addresses glyphs by their id in the full font
        opt.notdef_outline = True
        opt.layout_features = []
        opt.name_IDs = ["*"]                   # the OFL asks the font's name and notices to stay with it
        opt.drop_tables += ["GSUB", "GPOS", "GDEF", "STAT", "MVAR", "HVAR"]
        s = fsub.Subsetter(opt)
        s.populate(gids=sorted(set(self.used) | {0}))
        s.subset(f)
        buf = io.BytesIO()
        f.save(buf)
        return buf.getvalue()


def clean(text) -> str:
    s = "" if text is None else str(text)
    for a, b in SUBST.items():
        s = s.replace(a, b)
    return s


# ---- layout primitives ---------------------------------------------------------------------------------------------
@dataclass
class Col:
    title: str
    frac: float                      # share of the text width
    align: str = "left"              # left | right
    mono: bool = False


@dataclass
class Style:
    face: str = "regular"            # regular | semi | mono | monosemi
    size: float = 9.0
    tone: str = "ink"
    tracking: float = 0.0            # in em
    caps: bool = False
    leading: float = 1.38


class Doc:
    def __init__(self, title: str, stamp: str = "", author: str = "Form Studio", subject: str = ""):
        self.meta = {"title": title, "author": author, "subject": subject}
        self.stamp = stamp
        self.faces = {"regular": Face("Geist", 400), "semi": Face("Geist", 600),
                      "mono": Face("GeistMono", 400), "monosemi": Face("GeistMono", 600)}
        self.W, self.H = A4
        self.left, self.right = MARGIN, self.W - MARGIN
        self.top, self.bottom = self.H - MARGIN, MARGIN + 14
        self.width = self.right - self.left
        self.pages: list[list[str]] = []
        self._into: int | None = None        # the page drawing goes to (None: the last one)
        self.images: list[tuple] = []        # (name, w, h, rgb bytes)
        self.page_images: list[set] = []
        self.new_page()

    # -- pages
    def new_page(self) -> None:
        self.pages.append([])
        self.page_images.append(set())
        self.y = self.top
        self._rect(0, 0, self.W, self.H, fill=PAPER)

    def ensure(self, h: float) -> None:
        if self.y - h < self.bottom:
            self.new_page()

    def space(self, pts: float) -> None:
        self.y -= pts

    # -- drawing
    def _op(self, s: str) -> None:
        self.pages[-1 if self._into is None else self._into].append(s)

    @staticmethod
    def _c(rgb) -> str:
        return " ".join(f"{v / 255:.4f}" for v in rgb)

    def _rect(self, x, y, w, h, fill=None, stroke=None, lw=0.6, r=0.0) -> None:
        if r > 0:
            k = 0.5523 * r
            p = (f"{x + r:.2f} {y:.2f} m {x + w - r:.2f} {y:.2f} l "
                 f"{x + w - r + k:.2f} {y:.2f} {x + w:.2f} {y + r - k:.2f} {x + w:.2f} {y + r:.2f} c "
                 f"{x + w:.2f} {y + h - r:.2f} l {x + w:.2f} {y + h - r + k:.2f} {x + w - r + k:.2f} {y + h:.2f} {x + w - r:.2f} {y + h:.2f} c "
                 f"{x + r:.2f} {y + h:.2f} l {x + r - k:.2f} {y + h:.2f} {x:.2f} {y + h - r + k:.2f} {x:.2f} {y + h - r:.2f} c "
                 f"{x:.2f} {y + r:.2f} l {x:.2f} {y + r - k:.2f} {x + r - k:.2f} {y:.2f} {x + r:.2f} {y:.2f} c h")
        else:
            p = f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re"
        ops = []
        if fill:
            ops.append(f"{self._c(fill)} rg")
        if stroke:
            ops.append(f"{self._c(stroke)} RG {lw:.2f} w")
        ops.append(p + (" B" if fill and stroke else " f" if fill else " S"))
        self._op(" ".join(ops))

    def line(self, x0, y0, x1, y1, color=RULE, lw=0.6) -> None:
        self._op(f"{self._c(color)} RG {lw:.2f} w {x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S")

    def text(self, x: float, y: float, s: str, st: Style, color=None) -> float:
        """Draw one line with its baseline at y. Returns its width."""
        s = clean(s)
        if st.caps:
            s = s.upper()
        f = self.faces[st.face]
        gs = f.glyphs(s)
        if not gs:
            return 0.0
        hexs = "".join(f"{g:04x}" for g in gs)
        tc = st.tracking * st.size
        name = {"regular": "F1", "semi": "F2", "mono": "F3", "monosemi": "F4"}[st.face]
        self._op(f"BT /{name} {st.size:.2f} Tf {tc:.3f} Tc {self._c(color or TONES[st.tone])} rg "
                 f"{x:.2f} {y:.2f} Td <{hexs}> Tj ET")
        return f.width(s, st.size, st.tracking)

    def measure(self, s: str, st: Style) -> float:
        s = clean(s)
        return self.faces[st.face].width(s.upper() if st.caps else s, st.size, st.tracking)

    def wrap(self, s: str, st: Style, width: float) -> list[str]:
        out = []
        for para in clean(s).split("\n"):
            words, cur = para.split(" "), ""
            for w in words:
                trial = (cur + " " + w) if cur else w
                if self.measure(trial, st) <= width:
                    cur = trial
                    continue
                if cur:
                    out.append(cur)
                cur = w
                while self.measure(cur, st) > width and len(cur) > 1:      # a token longer than the line: break it
                    k = len(cur)
                    while k > 1 and self.measure(cur[:k], st) > width:
                        k -= 1
                    out.append(cur[:k])
                    cur = cur[k:]
            out.append(cur)
        return out

    # -- blocks
    def overline(self, s: str, tone: str = "ink3") -> None:
        st = Style("mono", 7.2, tone, 0.08, caps=True)
        self.ensure(12)
        self.text(self.left, self.y - 7.2, s, st)
        self.y -= 14

    def title(self, s: str, sub: str = "") -> None:
        st = Style("semi", 21, "ink", -0.012)
        for ln in self.wrap(s, st, self.width):
            self.ensure(26)
            self.text(self.left, self.y - 19, ln, st)
            self.y -= 26
        if sub:
            self.para(sub, Style("regular", 10, "ink2"))
        self.y -= 4

    def h2(self, s: str, note: str = "") -> None:
        self.ensure(40)
        self.y -= 10
        self.line(self.left, self.y, self.right, self.y, INK, 0.8)
        self.y -= 15
        w = self.text(self.left, self.y, s, Style("semi", 11.5, "ink", -0.005))
        if note:
            st = Style("mono", 7.2, "ink3", 0.06, caps=True)
            self.text(self.right - self.measure(note, st), self.y + 0.5, note, st)
        _ = w
        self.y -= 10

    def para(self, s: str, st: Style | None = None, indent: float = 0.0) -> None:
        st = st or Style("regular", 9, "ink2")
        lh = st.size * st.leading
        for ln in self.wrap(s, st, self.width - indent):
            self.ensure(lh)
            self.text(self.left + indent, self.y - st.size, ln, st)
            self.y -= lh
        self.y -= 3

    def kv(self, rows: list[tuple], label_w: float = 0.24) -> None:
        """Label and value pairs: the label in mono capitals, the value set as text."""
        ls = Style("mono", 7, "ink3", 0.06, caps=True)
        vs = Style("regular", 9, "ink")
        lw = self.width * label_w
        for k, v, *mono in rows:
            st = Style("mono", 8.4, "ink") if mono and mono[0] else vs
            lines = self.wrap(str(v), st, self.width - lw)
            h = max(1, len(lines)) * st.size * 1.38 + 3
            self.ensure(h)
            self.text(self.left, self.y - 8.4, k, ls)
            yy = self.y
            for ln in lines:
                self.text(self.left + lw, yy - st.size, ln, st)
                yy -= st.size * 1.38
            self.y -= h

    def pill(self, x: float, y: float, s: str, tone: str, filled: bool = False) -> float:
        """A status word in mono capitals inside a capsule; (x, y) is its lower left. Returns its width."""
        st = Style("monosemi", 6.8, tone, 0.06, caps=True)
        w = self.measure(s, st) + 9
        c = TONES[tone]
        if filled:
            self._rect(x, y, w, 11, fill=c, r=5.5)
            self.text(x + 4.5, y + 3.2, s, st, color=PAPER)
        else:
            self._rect(x, y, w, 11, stroke=c, lw=0.7, r=5.5)
            self.text(x + 4.5, y + 3.2, s, st)
        return w

    def verdict(self, word: str, tone: str, line: str, detail: str = "") -> None:
        st = Style("regular", 9.5, "ink")
        col = max(140.0, 18 + self.measure(word, Style("semi", 20, tone, -0.01)) + 22)
        lines = self.wrap(line, st, self.width - col - 14)
        dl = self.wrap(detail, Style("regular", 8.5, "ink2"), self.width - col - 14) if detail else []
        h = max(46, 18 + len(lines) * 13 + len(dl) * 11.5)
        self.ensure(h + 8)
        y0 = self.y - h
        self._rect(self.left, y0, self.width, h, fill=WASH, r=8)
        self._rect(self.left, y0, 4, h, fill=TONES[tone])
        self.text(self.left + 18, self.y - 30, word, Style("semi", 20, tone, -0.01))
        yy = self.y - 18
        for ln in lines:
            self.text(self.left + col, yy, ln, st)
            yy -= 13
        for ln in dl:
            self.text(self.left + col, yy, ln, Style("regular", 8.5, "ink2"))
            yy -= 11.5
        self.y = y0 - 10

    def table(self, cols: list[Col], rows: list[list], size: float = 8.4) -> None:
        """Rows of cells under a mono header; a cell is text, or {"text", "tone", "pill", "mono", "semi"}. A row too
        long for the page goes to the next one with the header again."""
        hs = Style("mono", 6.6, "ink3", 0.07, caps=True)
        pad = 5.0
        xs, x = [], self.left
        for c in cols:
            xs.append(x)
            x += c.frac * self.width

        def header():
            self.ensure(18)
            for c, cx in zip(cols, xs):
                w = c.frac * self.width - pad
                tx = cx + (w - self.measure(c.title, hs) if c.align == "right" else 0)
                self.text(tx, self.y - 8, c.title, hs)
            self.y -= 12
            self.line(self.left, self.y, self.right, self.y, INK3, 0.5)
            self.y -= 2

        header()
        for row in rows:
            cells = []
            for c, cell in zip(cols, row):
                d = cell if isinstance(cell, dict) else {"text": cell}
                st = Style("monosemi" if d.get("semi") and (d.get("mono") or c.mono) else "mono" if (d.get("mono") or c.mono)
                           else "semi" if d.get("semi") else "regular", size * (0.94 if (d.get("mono") or c.mono) else 1.0),
                           d.get("tone") or "ink")
                w = c.frac * self.width - pad
                lines = [] if d.get("pill") else self.wrap(str(d.get("text") if d.get("text") is not None else ""), st, w)
                sub = self.wrap(str(d["sub"]), Style("regular", size * 0.88, "ink3"), w) if d.get("sub") else []
                cells.append((d, st, lines, sub, w))
            lh = size * 1.36
            h = max(max(len(ln) * lh + len(sb) * lh * 0.9 for _, _, ln, sb, _ in cells), 12) + 7
            if self.y - h < self.bottom:
                self.new_page()
                header()
            yy = self.y - 4
            for (d, st, lines, sub, w), c, cx in zip(cells, cols, xs):
                if d.get("pill"):
                    tone = d.get("tone") or "ink2"
                    pw = self.measure(d["pill"], Style("monosemi", 6.8, tone, 0.06, caps=True)) + 9
                    self.pill(cx + (w - pw if c.align == "right" else 0), yy - 10.5, d["pill"], tone, d.get("filled", False))
                    continue
                ly = yy - size
                for ln in lines:
                    tx = cx + (w - self.measure(ln, st) if c.align == "right" else 0)
                    self.text(tx, ly, ln, st)
                    ly -= lh
                for ln in sub:
                    self.text(cx, ly, ln, Style("regular", size * 0.88, "ink3"))
                    ly -= lh * 0.9
            self.y -= h
            self.line(self.left, self.y + 1, self.right, self.y + 1, RULE, 0.4)
        self.y -= 6

    def field(self, x: float, y: float, w: float, label: str = "") -> None:
        """A blank to write on: a thin box, its label in small mono capitals inside, top left."""
        self._rect(x, y, w, 20, stroke=INK3, lw=0.5, r=3)
        if label:
            self.text(x + 4, y + 13.2, label, Style("mono", 5.4, "ink3", 0.06, caps=True))

    def box(self, x: float, y: float, label: str) -> float:
        """A tick box with its word beside it. Returns the width used."""
        self._rect(x, y, 8.5, 8.5, stroke=INK2, lw=0.6, r=1.5)
        return 12 + self.text(x + 12, y + 1.5, label, Style("regular", 8, "ink2"))

    def image(self, png: bytes, width: float, caption: str = "") -> None:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = im.size
        dh = width * h / w
        self.ensure(dh + (14 if caption else 4))
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, w, h, im.tobytes()))
        self.page_images[-1].add(name)
        self._op(f"q {width:.2f} 0 0 {dh:.2f} {self.left:.2f} {self.y - dh:.2f} cm /{name} Do Q")
        self.y -= dh + 4
        if caption:
            self.text(self.left, self.y - 7, caption, Style("mono", 6.6, "ink3", 0.06, caps=True))
            self.y -= 12

    # -- output
    def _footer(self, i: int, n: int) -> None:
        self._into = i
        st = Style("mono", 6.6, "ink3", 0.05)
        y = MARGIN - 2
        self.line(self.left, y + 10, self.right, y + 10, RULE, 0.4)
        self.text(self.left, y, self.stamp, st)
        right = f"page {i + 1} of {n}"
        self.text(self.right - self.measure(right, st), y, right, st)
        self._into = None

    def pdf(self) -> bytes:
        n = len(self.pages)
        for i in range(n):
            self._footer(i, n)
        streams = self.pages
        objs: list[bytes] = []

        def add(b) -> int:
            objs.append(b if isinstance(b, bytes) else b.encode("latin-1"))
            return len(objs)

        def stream(data: bytes, extra: str = "") -> int:
            z = zlib.compress(data, 9)
            return add(f"<< /Length {len(z)} /Filter /FlateDecode {extra}>>\nstream\n".encode() + z + b"\nendstream")

        fonts = {}
        for key, name in (("regular", "F1"), ("semi", "F2"), ("mono", "F3"), ("monosemi", "F4")):
            f = self.faces[key]
            if not f.used and key != "regular":
                continue
            font_file = f.subset()
            ff = stream(font_file, f"/Length1 {len(font_file)} ")
            psname = f"{'FSAAAA' if key == 'regular' else 'FSAAAB' if key == 'semi' else 'FSAAAC' if key == 'mono' else 'FSAAAD'}+" \
                     f"{f.family}-{'SemiBold' if f.weight >= 600 else 'Regular'}"
            desc = add(f"<< /Type /FontDescriptor /FontName /{psname} /Flags 32 /FontBBox [{' '.join(f'{v:.0f}' for v in f.bbox)}] "
                       f"/ItalicAngle 0 /Ascent {f.ascent:.0f} /Descent {f.descent:.0f} /CapHeight {f.cap:.0f} "
                       f"/StemV {120 if f.weight >= 600 else 80} /FontFile2 {ff} 0 R >>")
            gids = sorted(f.used)
            w = " ".join(f"{g} [{f.advance(g):.0f}]" for g in gids)
            cid = add(f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{psname} /CIDSystemInfo << /Registry (Adobe) "
                      f"/Ordering (Identity) /Supplement 0 >> /FontDescriptor {desc} 0 R /CIDToGIDMap /Identity "
                      f"/DW 500 /W [{w}] >>")
            cmap = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
                    "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
                    "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def", "1 begincodespacerange", "<0000> <FFFF>",
                    "endcodespacerange"]
            items = [(g, f.used[g]) for g in gids]
            for i in range(0, len(items), 100):
                chunk = items[i:i + 100]
                cmap.append(f"{len(chunk)} beginbfchar")
                for g, ch in chunk:
                    u = ch.encode("utf-16-be").hex()
                    cmap.append(f"<{g:04x}> <{u}>")
                cmap.append("endbfchar")
            cmap += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
            tu = stream("\n".join(cmap).encode())
            fonts[name] = add(f"<< /Type /Font /Subtype /Type0 /BaseFont /{psname} /Encoding /Identity-H "
                              f"/DescendantFonts [{cid} 0 R] /ToUnicode {tu} 0 R >>")
        imgs = {}
        for name, w, h, rgb in self.images:
            imgs[name] = stream(rgb, f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 ")
        font_res = " ".join(f"/{k} {v} 0 R" for k, v in fonts.items())
        pages_id = len(objs) + 1 + 2 * n            # reserved below
        kids = []
        for i, ops in enumerate(streams):
            c = stream("\n".join(ops).encode("latin-1"))
            xo = " ".join(f"/{k} {imgs[k]} 0 R" for k in sorted(self.page_images[i]))
            kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {self.W:.2f} {self.H:.2f}] "
                            f"/Resources << /Font << {font_res} >>" + (f" /XObject << {xo} >>" if xo else "") +
                            f" >> /Contents {c} 0 R >>"))
        assert len(objs) + 1 == pages_id, "page tree id"
        add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {n} >>")
        cat = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

        def s(v: str) -> str:
            return "<FEFF" + v.encode("utf-16-be").hex() + ">"
        stamp = time.strftime("D:%Y%m%d%H%M%SZ", time.gmtime())
        info = add(f"<< /Title {s(self.meta['title'])} /Author {s(self.meta['author'])} /Subject {s(self.meta['subject'])} "
                   f"/Creator {s('Form Studio')} /Producer {s('Form Studio pdfdoc')} /CreationDate ({stamp}) >>")
        out = io.BytesIO()
        out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offs = []
        for i, b in enumerate(objs, 1):
            offs.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + b + b"\nendobj\n")
        x = out.tell()
        out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
        for o in offs:
            out.write(f"{o:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(objs) + 1} /Root {cat} 0 R /Info {info} 0 R >>\nstartxref\n{x}\n%%EOF\n".encode())
        return out.getvalue()
