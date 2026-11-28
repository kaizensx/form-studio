"""A small S-expression reader for KiCad's text formats (.kicad_pcb, .kicad_sch, .kicad_mod).

Form Studio's own code; no KiCad and no third-party parser. A list is a Python list whose first item is its head
(a bare symbol); atoms are strings (quoted strings keep their text without the quotes, escapes resolved) and numbers
stay strings until a reader asks for one (`num`). Iterative, so a deep or large board cannot overflow the stack.

    tree = parse(text)                 # ["kicad_pcb", ["version", "20240108"], ...]
    for fp in children(tree, "footprint"): ...
    first(fp, "at")                    # ["at", "100", "80", "90"]
"""
from __future__ import annotations

MAX_BYTES = 200_000_000


class SexprError(ValueError):
    pass


class Sym(str):
    """A bare (unquoted) symbol, so `layer F.Cu` and `layer "F.Cu"` read the same but a quoted "" stays a string."""
    __slots__ = ()


_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


def parse(text: str) -> list:
    """The first top-level list of text. Raises SexprError with the line on a syntax error."""
    if len(text) > MAX_BYTES:
        raise SexprError("The file is larger than 200 MB.")
    stack: list[list] = []
    out = None
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif c == "(":
            node: list = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            i += 1
        elif c == ")":
            if not stack:
                raise SexprError(f"Unbalanced ')' on line {line}.")
            node = stack.pop()
            i += 1
            if not stack:
                out = node
                break
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(_ESC.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                if text[j] == "\n":
                    line += 1
                buf.append(text[j])
                j += 1
            if j >= n:
                raise SexprError(f"A quoted string is not closed (line {line}).")
            if not stack:
                raise SexprError(f"Text outside a list on line {line}.")
            stack[-1].append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            if not stack:
                raise SexprError(f"Text outside a list on line {line}.")
            stack[-1].append(Sym(text[i:j]))
            i = j
    if out is None:
        raise SexprError("No complete list in the file (it ends before its last ')').")
    return out


def head(node) -> str:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else ""


def children(node, name: str) -> list:
    return [c for c in node[1:] if isinstance(c, list) and head(c) == name] if isinstance(node, list) else []


def first(node, name: str):
    for c in node[1:] if isinstance(node, list) else []:
        if isinstance(c, list) and head(c) == name:
            return c
    return None


def atoms(node) -> list:
    return [c for c in node[1:] if not isinstance(c, list)] if isinstance(node, list) else []


def value(node, name: str, default=None):
    """The first atom of the first child named `name`: value(fp, "layer") -> "F.Cu"."""
    c = first(node, name)
    a = atoms(c) if c is not None else []
    return a[0] if a else default


def num(x, default: float | None = None) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def xy(node, name: str) -> tuple[float, float] | None:
    """(x, y) of a child such as (start 1 2) or (at 1 2 90)."""
    c = first(node, name)
    a = atoms(c) if c is not None else []
    if len(a) < 2:
        return None
    x, y = num(a[0]), num(a[1])
    return None if x is None or y is None else (x, y)


def walk(node):
    """Every list in the tree, depth first (iterative)."""
    st = [node]
    while st:
        x = st.pop()
        if isinstance(x, list):
            yield x
            st.extend(reversed([c for c in x if isinstance(c, list)]))


# ---- writing -------------------------------------------------------------------------------------------------------
def sym(x) -> Sym:
    """A bare atom: a keyword, or a number written the way KiCad writes it (no trailing zeros, no exponent)."""
    if isinstance(x, bool):
        return Sym("yes" if x else "no")
    if isinstance(x, int):
        return Sym(str(x))
    if isinstance(x, float):
        s = f"{x:.6f}".rstrip("0").rstrip(".")
        return Sym("0" if s in ("-0", "") else s)
    return Sym(str(x))


def quote(s: str) -> str:
    return '"' + (s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
                  .replace("\t", "\\t")) + '"'


def _atom(a) -> str:
    if isinstance(a, Sym) and a and not any(ch in ' \t\r\n()"' for ch in a):
        return str(a)
    return quote(str(a))


def _flat(node, limit: int) -> str | None:
    """node on one line, or None when that line would pass limit characters."""
    buf, n = [], 0
    st: list = [node]
    while st:
        x = st.pop()
        if x is None:
            buf.append(")")
            n += 1
        elif isinstance(x, list):
            buf.append("(")
            n += 1
            st.append(None)
            st.extend(reversed(x))
        else:
            s = _atom(x)
            buf.append(s)
            n += len(s) + 1
        if n > limit:
            return None
    return " ".join(buf).replace("( ", "(").replace(" )", ")")


def dump(tree: list, indent: str = "\t", width: int = 100) -> str:
    """The tree as text KiCad reads. A quoted string stays quoted and a bare symbol stays bare, so
    parse(dump(parse(text))) is the tree of text, atom for atom (`same`). A list that fits on one line is written
    on one; otherwise its leading atoms stay on the opening line and every later item starts its own line."""
    out: list[str] = []
    st: list = [(tree, 0)]
    while st:
        node, d = st.pop()
        if node is None:
            out.append(indent * d + ")")
            continue
        if not isinstance(node, list):
            out.append(indent * d + _atom(node))
            continue
        one = _flat(node, width)
        if one is not None:
            out.append(indent * d + one)
            continue
        i = 0
        while i < len(node) and not isinstance(node[i], list):
            i += 1
        out.append(indent * d + "(" + " ".join(_atom(a) for a in node[:i]))
        st.append((None, d))
        st.extend((c, d + 1) for c in reversed(node[i:]))
    return "\n".join(out) + "\n"


def same(a, b) -> bool:
    """Two trees equal atom for atom, quoted against quoted and bare against bare."""
    st = [(a, b)]
    while st:
        x, y = st.pop()
        if isinstance(x, list) != isinstance(y, list):
            return False
        if isinstance(x, list):
            if len(x) != len(y):
                return False
            st.extend(zip(x, y))
        elif x != y or isinstance(x, Sym) != isinstance(y, Sym):
            return False
    return True


def set_value(node: list, name: str, *vals) -> list:
    """Replace (or add) the child (name v...) of node; returns the child."""
    c = first(node, name)
    if c is None:
        c = [Sym(name)]
        node.append(c)
    c[1:] = list(vals)
    return c
