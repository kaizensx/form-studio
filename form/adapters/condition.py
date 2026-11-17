"""The compatibility conditions slicer presets carry (compatible_printers_condition, compatible_prints_condition).

PrusaSlicer, its forks and OrcaSlicer write them in one small expression language (src/libslic3r/PlaceholderParser.cpp):

    printer_notes=~/.*PRINTER_VENDOR_PRUSA3D.*/ and nozzle_diameter[0]==0.4 and ! (printer_model=="MK4S")

This evaluates the part of it that presets actually use: and / or / not / !, parentheses, == != < > <= >=,
=~ and !~ against /regex/, numbers, "strings", true/false, and option names with an optional [index]. Anything
else raises Unknown, and the caller treats the preset as "not checked" rather than guessing either way.
"""
from __future__ import annotations

import re


class Unknown(ValueError):
    """The expression uses something this evaluator does not handle."""


_TOKEN = re.compile(r"""\s*(?:
    (?P<num>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<re>/(?:[^/\\]|\\.)*/)
  | (?P<op>==|!=|=~|!~|<=|>=|<|>|\(|\)|!|\[|\])
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
)""", re.X)


def _tokens(text: str) -> list:
    out, i = [], 0
    text = text.strip()
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m or m.end() == i:
            raise Unknown(f"cannot read “{text[i:i + 20]}”")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
        while i < len(text) and text[i].isspace():
            i += 1
    return out


def _values(raw) -> list:
    """An option's values as a list of strings (JSON lists, or PrusaSlicer's comma / semicolon separated text)."""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    s = "" if raw is None else str(raw)
    if s.startswith('"') or ";" in s and not s.startswith("["):
        parts = [p.strip().strip('"') for p in s.split(";")]
        return parts if len(parts) > 1 else [s.strip('"')]
    if "," in s and all(re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", p) for p in s.split(",")):
        return [p.strip() for p in s.split(",")]
    return [s]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class _P:
    def __init__(self, toks, cfg):
        self.t, self.i, self.cfg = toks, 0, cfg

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expr(self):
        v = self.conj()
        while self.peek() == ("id", "or"):
            self.take()
            rhs = self.conj()
            v = v or rhs
        return v

    def conj(self):
        v = self.neg()
        while self.peek() == ("id", "and"):
            self.take()
            rhs = self.neg()
            v = v and rhs
        return v

    def neg(self):
        if self.peek() in (("id", "not"), ("op", "!")):
            self.take()
            return not self.neg()
        return self.cmp()

    def cmp(self):
        a = self.atom()
        kind, op = self.peek()
        if kind == "op" and op in ("==", "!=", "<", ">", "<=", ">="):
            self.take()
            b = self.atom()
            na, nb = _num(a), _num(b)
            if na is not None and nb is not None:
                a, b = na, nb
            elif op not in ("==", "!="):
                raise Unknown("ordering of text")
            else:
                a, b = str(a), str(b)
            return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        if kind == "op" and op in ("=~", "!~"):
            self.take()
            k, pat = self.take()
            if k != "re":
                raise Unknown("=~ without a /regex/")
            try:
                hit = re.fullmatch(pat[1:-1], str(a), re.S) is not None
            except re.error as e:
                raise Unknown(f"regex: {e}")
            return hit if op == "=~" else not hit
        if isinstance(a, bool):
            return a
        raise Unknown("a value where a condition was expected")

    def atom(self):
        kind, val = self.take()
        if kind == "op" and val == "(":
            v = self.expr()
            if self.take() != ("op", ")"):
                raise Unknown("unbalanced parentheses")
            return v
        if kind == "num":
            return float(val)
        if kind == "str":
            return val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if kind == "id":
            if val in ("true", "false"):
                return val == "true"
            if val not in self.cfg:
                raise Unknown(f"unknown option {val}")
            vals = _values(self.cfg[val])
            idx = 0
            if self.peek() == ("op", "["):
                self.take()
                k, n = self.take()
                if k != "num" or self.take() != ("op", "]"):
                    raise Unknown("index")
                idx = int(float(n))
            if idx >= len(vals):
                raise Unknown(f"{val}[{idx}] out of range")
            v = vals[idx]
            if v in ("0", "1") and val.startswith(("is_", "use_", "enable_")):
                return v == "1"
            return v
        raise Unknown(f"unexpected {val!r}")


def evaluate(condition: str, cfg: dict) -> bool:
    """True / False for a condition against a flattened preset. Raises Unknown when it cannot tell."""
    if not condition or not str(condition).strip():
        return True
    p = _P(_tokens(str(condition)), cfg)
    v = p.expr()
    if p.i != len(p.t):
        raise Unknown("text after the condition")
    return bool(v)
