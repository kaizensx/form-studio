"""Markdown, as agents write it, to the HTML subset Qt's rich text draws.

Qt can draw Markdown itself (`Text.MarkdownText`), but its lists have a fixed 40 px indent and loose spacing that
nothing in QML can change. Here every list item is a two-cell table row: the marker in a narrow first cell and the
text in the second, so bullets and numbers sit on the text column's 8 px grid, a long item wraps with a hanging
indent, and a nested list steps in by exactly one marker column. Pure text in, text out: no Qt, so it is unit-tested.

Handled: paragraphs, headings, bullet / numbered / task lists (nested, loose or tight), fenced and indented code,
tables, block quotes, rules, and inline code, bold, italic, strikethrough, links and hard breaks. Anything unfinished
(a reply is drawn while it is being written) degrades to plain text or to an open code block, never to an error.
"""
from __future__ import annotations

import html
import re

STEP = 16          # px: bullet column, and so the indent of a nested list
GAP = 8            # px between blocks
ITEM_GAP = 4       # px between list items

DEFAULT_STYLE = {"mono": "monospace", "code_bg": "#14181b", "rule": "#2a3136", "muted": "#8b949b", "code_px": 12, "head_px": 15}

_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})\s*([^`]*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*)|[ \t]*)$")
_TASK = re.compile(r"^\[([ xX])\][ \t]+(.*)$")
_QUOTE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
_TABLE_SEP = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def _attr(s: str) -> str:
    return html.escape(s, quote=True)


# ── inline ───────────────────────────────────────────────────────────────────────────────────────────────────────
_INLINE = re.compile(
    r"(?P<esc>\\[\\`*_{}\[\]()#+\-.!|~<>])"
    r"|(?P<code>(?<!`)(?P<tick>`+)(?!`)(?P<codebody>.+?)(?<!`)(?P=tick)(?!`))"
    r"|(?P<link>\[(?P<label>(?:[^\[\]]|\[[^\[\]]*\])+)\]\(\s*<?(?P<href>[^\s<>)]+)>?(?:\s+\"[^\"]*\")?\s*\))"
    r"|(?P<auto><(?P<autourl>(?:https?://|mailto:)[^\s<>]+)>)"
    r"|(?P<bare>(?<![\w/\"=])https?://[^\s<>]*[^\s<>.,;:!?)\]'\"])"
    r"|(?P<strong>(?P<sm>\*\*|__)(?=\S)(?P<strongbody>.+?)(?<=\S)(?P=sm))"
    r"|(?P<em>(?<![\w*])\*(?=[^\s*])(?P<em1>.+?)(?<=[^\s*])\*(?!\*)|(?<![\w_])_(?=[^\s_])(?P<em2>.+?)(?<=[^\s_])_(?![\w_]))"
    r"|(?P<del>~~(?=\S)(?P<delbody>.+?)(?<=\S)~~)"
    r"|(?P<br>(?: {2,}|\\)\n)",
    re.S)


def _link(href: str, label: str, st: dict) -> str:
    colour = ' style="color:%s;"' % st["link"] if st.get("link") else ""
    return '<a href="%s"%s>%s</a>' % (_attr(href), colour, label)


def inline(text: str, style: dict | None = None) -> str:
    """One paragraph's text → HTML. Unclosed markers stay as the characters they are."""
    st = style or DEFAULT_STYLE
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(_esc(text[pos:m.start()]))
        pos = m.end()
        if m.group("esc"):
            out.append(_esc(m.group("esc")[1]))
        elif m.group("code"):
            body = m.group("codebody").replace("\n", " ")
            if len(body) > 2 and body[0] == " " and body[-1] == " " and body.strip():
                body = body[1:-1]
            out.append('<span style="font-family:\'%s\'; font-size:%dpx; background-color:%s;">&nbsp;%s&nbsp;</span>'
                       % (st["mono"], st["code_px"], st["code_bg"], _esc(body).replace(" ", "&nbsp;") if len(body) < 40 else _esc(body)))
        elif m.group("link"):
            out.append(_link(m.group("href"), inline(m.group("label"), st), st))
        elif m.group("auto"):
            out.append(_link(m.group("autourl"), _esc(m.group("autourl")), st))
        elif m.group("bare"):
            out.append(_link(m.group("bare"), _esc(m.group("bare")), st))
        elif m.group("strong"):
            out.append("<b>%s</b>" % inline(m.group("strongbody"), st))
        elif m.group("em"):
            out.append("<i>%s</i>" % inline(m.group("em1") or m.group("em2"), st))
        elif m.group("del"):
            out.append("<s>%s</s>" % inline(m.group("delbody"), st))
        elif m.group("br"):
            out.append("<br/>")
    out.append(_esc(text[pos:]))
    return "".join(out).replace("\n", " ")


# ── blocks ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse(text: str) -> list[dict]:
    """Markdown → a list of blocks (dicts with a `t`): the structure the tests check, and what `to_html` draws."""
    return _blocks(text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n"))


def _blocks(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    para: list[str] = []
    i, n = 0, len(lines)

    def flush():
        if para:
            out.append({"t": "p", "text": "\n".join(para)})
            para.clear()

    while i < n:
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        m = _FENCE.match(line)
        if m:                                                   # fenced code; an open fence runs to the end (streaming)
            flush()
            pad, mark, lang = len(m.group(1)), m.group(2), m.group(3).strip()
            body = []
            i += 1
            while i < n and not re.match(r"^ {0,3}" + re.escape(mark[0]) + "{%d,}\\s*$" % len(mark), lines[i]):
                body.append(lines[i][min(pad, _indent(lines[i])):])
                i += 1
            i += 1
            out.append({"t": "code", "lang": lang.split()[0] if lang else "", "text": "\n".join(body)})
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            out.append({"t": "h", "level": len(m.group(1)), "text": m.group(2)})
            i += 1
            continue
        if _RULE.match(line) and not (para and re.match(r"^ {0,3}-+\s*$", line)):
            flush()
            out.append({"t": "hr"})
            i += 1
            continue
        if para and re.match(r"^ {0,3}(=+|-{3,})\s*$", line):   # setext heading (three dashes: one is a bullet being typed)
            text = "\n".join(para)
            para.clear()
            out.append({"t": "h", "level": 1 if line.strip()[0] == "=" else 2, "text": text})
            i += 1
            continue
        if _QUOTE.match(line):
            flush()
            body = []
            while i < n and lines[i].strip() and (_QUOTE.match(lines[i]) or body):
                q = _QUOTE.match(lines[i])
                body.append(q.group(1) if q else lines[i])
                i += 1
            out.append({"t": "quote", "blocks": _blocks(body)})
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1] and len(_cells(line)) == len(_cells(lines[i + 1])):
            flush()
            head, seps = _cells(line), _cells(lines[i + 1])
            align = ["center" if s.startswith(":") and s.endswith(":") else "right" if s.endswith(":") else "left" for s in seps]
            rows = []
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                r = _cells(lines[i])
                rows.append((r + [""] * len(head))[:len(head)])
                i += 1
            out.append({"t": "table", "head": head, "align": align, "rows": rows})
            continue
        m = _ITEM.match(line)
        if m and (not para or m.group(2) in "-*+" or m.group(2)[:-1] == "1") and (m.group(3) or not para):
            flush()
            lst, i = _list(lines, i)
            out.append(lst)
            continue
        if not para and _indent(line) >= 4:                     # indented code
            body = []
            while i < n and (not lines[i].strip() or _indent(lines[i]) >= 4):
                body.append(lines[i][4:])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            out.append({"t": "code", "lang": "", "text": "\n".join(body)})
            continue
        para.append(line.strip())
        i += 1
    flush()
    return out


def _list(lines: list[str], i: int) -> tuple[dict, int]:
    first = _ITEM.match(lines[i])
    base, ordered = len(first.group(1)), first.group(2)[0].isdigit()
    start = int(first.group(2)[:-1]) if ordered else 1
    items, loose, n = [], False, len(lines)
    while i < n:
        m = _ITEM.match(lines[i])
        if not m or len(m.group(1)) > base + 1 or len(m.group(1)) < base - 1 or m.group(2)[0].isdigit() != ordered:
            break
        content = len(m.group(1)) + len(m.group(2)) + 1         # the column the item's text starts in
        body, blank = [m.group(3) or ""], False
        i += 1
        while i < n:
            ln = lines[i]
            if not ln.strip():
                blank = True
                body.append("")
                i += 1
                continue
            ind = _indent(ln)
            if ind >= min(content, base + 2):                   # belongs to this item (a nested list, a second paragraph)
                body.append(ln[min(ind, content):])
            elif blank or _ITEM.match(ln) or _FENCE.match(ln) or _HEADING.match(ln) or _RULE.match(ln):
                break
            else:
                body.append(ln.strip())                         # lazy continuation of the paragraph
            blank = False
            i += 1
        while body and not body[-1].strip():
            body.pop()
            nxt = _ITEM.match(lines[i]) if i < n else None
            if nxt and abs(len(nxt.group(1)) - base) <= 1 and nxt.group(2)[0].isdigit() == ordered:
                loose = True                                    # a blank line between two items
        task = None
        t = _TASK.match(body[0]) if body else None
        if t:
            task, body[0] = t.group(1) != " ", t.group(2)
        blocks = _blocks(body)
        if any(not b and k < len(body) - 1 for k, b in enumerate(body)) and len([b for b in blocks if b["t"] == "p"]) > 1:
            loose = True
        items.append({"blocks": blocks, "task": task})
    return {"t": "list", "ordered": ordered, "start": start, "loose": loose, "items": items}, i


# ── HTML ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _render(blocks: list[dict], st: dict, top: bool = True, tight: bool = False) -> str:
    out = []
    for k, b in enumerate(blocks):
        gap = 0 if k == 0 else (ITEM_GAP if tight else GAP)
        t = b["t"]
        if t == "p":
            out.append('<p style="margin-top:%dpx; margin-bottom:0px;">%s</p>' % (gap, inline(b["text"], st)))
        elif t == "h":
            big = b["level"] <= 2
            out.append('<p style="margin-top:%dpx; margin-bottom:0px; font-size:%dpx; font-weight:600;">%s</p>'
                       % (0 if k == 0 else (16 if big else 12), st["head_px"] if big else st["head_px"] - 2, inline(b["text"], st)))
        elif t == "code":
            body = _esc(b["text"]) or "&nbsp;"
            out.append('<table width="100%%" cellspacing="0" cellpadding="10" bgcolor="%s" style="margin-top:%dpx; margin-bottom:0px;">'
                       '<tr><td><pre style="margin:0px; white-space:pre-wrap; font-family:\'%s\'; font-size:%dpx;">%s</pre></td></tr></table>'
                       % (st["code_bg"], gap, st["mono"], st["code_px"], body))
        elif t == "hr":
            out.append('<table width="100%%" cellspacing="0" cellpadding="0" bgcolor="%s" style="margin-top:%dpx; margin-bottom:0px;">'
                       '<tr><td height="1" style="font-size:1px;"></td></tr></table>' % (st["rule"], GAP if k else 0))
        elif t == "quote":
            out.append('<table width="100%%" cellspacing="0" cellpadding="0" style="margin-top:%dpx; margin-bottom:0px;"><tr>'
                       '<td width="2" bgcolor="%s"></td><td width="%d"></td><td style="color:%s;">%s</td></tr></table>'
                       % (gap, st["rule"], STEP - 2, st["muted"], _render(b["blocks"], st, False)))
        elif t == "table":
            cell = ' style="border-width:1px; border-style:solid; border-color:%s; padding:5px 8px;"' % st["rule"]
            rows = ["<tr>" + "".join('<th align="%s"%s>%s</th>' % (a, cell, inline(c, st)) for c, a in zip(b["head"], b["align"])) + "</tr>"]
            for r in b["rows"]:
                rows.append("<tr>" + "".join('<td align="%s"%s>%s</td>' % (a, cell, inline(c, st)) for c, a in zip(r, b["align"])) + "</tr>")
            out.append('<table cellspacing="0" cellpadding="0" style="margin-top:%dpx; margin-bottom:0px; border-collapse:collapse; border-width:1px; border-style:solid; border-color:%s;">%s</table>'
                       % (gap, st["rule"], "".join(rows)))
        elif t == "list":
            # the marker column: one step for a bullet, wider only as far as the longest number needs
            last = b["start"] + len(b["items"]) - 1
            col = STEP if not b["ordered"] else STEP + 8 * max(0, len(str(last)) - 1) + (8 if b["ordered"] else 0)
            rows = []
            for j, it in enumerate(b["items"]):
                mark = ("%d." % (b["start"] + j)) if b["ordered"] else ("☑" if it["task"] else "☐") if it["task"] is not None else "•"
                pad = 0 if j == 0 else (GAP if b["loose"] else ITEM_GAP)
                style = ' style="padding-top:%dpx;"' % pad if pad else ""
                rows.append('<tr><td width="%d" valign="top"%s><span style="color:%s;">%s</span></td><td valign="top"%s>%s</td></tr>'
                            % (col, style, st["muted"], mark, style, _render(it["blocks"], st, False, not b["loose"]) or "&nbsp;"))
            # full width: Qt sizes a table to its content otherwise, and a nested list would wrap after a word or two
            out.append('<table width="100%%" cellspacing="0" cellpadding="0" style="margin-top:%dpx; margin-bottom:0px;">%s</table>' % (gap, "".join(rows)))
    return "".join(out)


def to_html(text: str, style: dict | None = None) -> str:
    """Markdown → HTML for a Qt `Text { textFormat: Text.RichText }`."""
    st = dict(DEFAULT_STYLE)
    st.update({k: v for k, v in (style or {}).items() if v is not None})
    return _render(parse(text or ""), st)
