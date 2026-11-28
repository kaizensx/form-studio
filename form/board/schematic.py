"""KiCad schematics (.kicad_sch, KiCad 6 to 9) read, changed and written by Form Studio's own code; no KiCad.

    sch = Schematic.load("board.kicad_sch")        # or Schematic.new("board")
    sch.netlist()                                  # nets with their pins, parts with value and footprint
    sch.erc()                                      # Form Studio's electrical checks (a subset; not KiCad's ERC)
    sch.apply([{"op": "place", "lib_id": "Device:R", "ref": "R1", "value": "10k", "at": [100, 50]},
               {"op": "net", "name": "VBUS", "pins": ["R1.1", "J1.1"]}, {"op": "annotate"}], libs)
    sch.save(path)

The file is kept as the tree it was read into and written back atom for atom, so what this module does not
understand (graphics, text, simulation fields, sheet frames) is kept as it was.

How a net is found (this sheet; coordinates in mm, y down, compared at 0.1 micrometre):

- a pin's connection point is its symbol's position plus the pin's library position turned by the symbol's
  rotation and mirror, with the library's y axis (up) flipped to the sheet's (down);
- a wire joins everything at its two ends; a pin, a label, a junction or another wire's end lying anywhere on a wire
  joins it; two wires that only cross do not join without a junction;
- labels with the same text name one net; a power symbol (a library symbol marked `power` with a power-input pin)
  names a global net by its Value; names take precedence global, power, hierarchical, local;
- an unnamed net is called Net-(REF-PadN) from its first pin, or unconnected-(REF-PadN) when it has one pin.

Not done, and said in the result: sub-sheets are listed but not opened (the netlist is this sheet's), buses are
not expanded.
"""
from __future__ import annotations

import copy
import math
import re
import uuid
from pathlib import Path

from .sexpr import Sym, atoms, children, dump, first, head, num, parse, sym, value

ERC_BY = "Form Studio ERC (a subset of electrical checks; not KiCad's ERC)"
ERC_NOT_CHECKED = ["sub-sheets and hierarchical pins", "buses and bus entries", "footprint filters and library "
                   "mismatches", "KiCad's full pin-conflict matrix and its per-project severities", "off-grid pins and "
                   "wires", "simulation models"]
GRID = 1.27
NS = uuid.UUID("2b1f6f0a-7f0e-4b7b-9d55-0d6f2a1c9e42")
DRIVERS = {"output", "power_out", "passive", "tri_state", "bidirectional", "open_collector", "open_emitter"}
# pairs of pin types on one net that Form Studio reports; everything else is not judged here
CONFLICT = {frozenset(("output",)): "error", frozenset(("output", "power_out")): "error",
            frozenset(("power_out",)): "error", frozenset(("output", "open_collector")): "error",
            frozenset(("output", "open_emitter")): "error", frozenset(("power_out", "open_collector")): "error",
            frozenset(("power_out", "open_emitter")): "error", frozenset(("output", "tri_state")): "warning",
            frozenset(("power_out", "tri_state")): "warning", frozenset(("power_out", "bidirectional")): "warning"}


def _k(x: float, y: float) -> tuple[int, int]:
    return int(round(x * 10000)), int(round(y * 10000))


def _nat(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _xform(p, rot: float, mirror: str):
    """A library point (y up) on the sheet (y down), about the symbol's position: KiCad's orientation matrices
    (0: x, -y; 90: -y, -x; 180: -x, y; 270: y, x), then the mirror applied on the sheet."""
    x, y = p
    r = int(round(rot)) % 360
    if r == 0:
        sx, sy = x, -y
    elif r == 90:
        sx, sy = -y, -x
    elif r == 180:
        sx, sy = -x, y
    elif r == 270:
        sx, sy = y, x
    else:
        a = math.radians(rot)
        sx, sy = x * math.cos(a) - (-y) * -math.sin(a), -(x * math.sin(a)) - y * math.cos(a)
    if mirror == "x":
        sy = -sy
    elif mirror == "y":
        sx = -sx
    return sx, sy


# ---- symbol libraries ----------------------------------------------------------------------------------------------
class Libraries:
    """The person's .kicad_sym files: KiCad's standard libraries where it is installed (form.board.pcb.library_dirs),
    and any files or folders given. A symbol is read by finding its block in the file, so a large library costs
    only the symbol asked for."""

    def __init__(self, paths: list | None = None, cfg: dict | None = None, standard: bool = True):
        from .pcb import library_dirs
        self.files: dict[str, Path] = {}
        dirs = list(library_dirs(cfg, "symbols")) if standard else []
        for p in paths or []:
            p = Path(p).expanduser()
            if p.is_dir():
                dirs.insert(0, p)
            elif p.is_file():
                self.files[p.stem] = p
        for d in dirs:
            for f in sorted(d.glob("*.kicad_sym")):
                self.files.setdefault(f.stem, f)
        self.dirs = dirs
        self._text: dict[str, str] = {}

    def status(self) -> dict:
        return {"libraries": len(self.files), "folders": [str(d) for d in self.dirs],
                "available": bool(self.files),
                "note": "" if self.files else "No KiCad symbol libraries were found on this computer. Install KiCad "
                        "(Settings > Engines & software > KiCad), or give libraries=[...] with your .kicad_sym files."}

    def _read(self, lib: str) -> str:
        if lib not in self._text:
            self._text[lib] = self.files[lib].read_text(encoding="utf-8", errors="replace")
        return self._text[lib]

    def names(self, lib: str) -> list[str]:
        if lib not in self.files:
            return []
        return re.findall(r'^(?:\t|  )\(symbol "([^"]+)"', self._read(lib), re.M)

    def search(self, query: str, limit: int = 40) -> list[dict]:
        q = [t for t in query.lower().replace(":", " ").split() if t]
        out = []
        for lib in sorted(self.files):
            if len(out) >= limit:
                break
            for name in self.names(lib):
                hay = f"{lib}:{name}".lower()
                if all(t in hay for t in q):
                    out.append({"lib_id": f"{lib}:{name}", "library": lib, "file": str(self.files[lib])})
                    if len(out) >= limit:
                        break
        return out

    def _block(self, lib: str, name: str) -> list | None:
        text = self._read(lib)
        m = re.search(r'^(?:\t|  )\(symbol "' + re.escape(name) + r'"', text, re.M)
        if not m:
            return None
        i = text.index("(", m.start())
        depth, j, n, q = 0, i, len(text), False
        while j < n:
            ch = text[j]
            if q:
                if ch == "\\":
                    j += 1
                elif ch == '"':
                    q = False
            elif ch == '"':
                q = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        return parse(text[i:j + 1])

    def symbol(self, lib_id: str) -> list:
        """The library symbol as it is embedded in a schematic: named "Lib:Name", an `extends` parent resolved."""
        lib, _, name = lib_id.partition(":")
        if not name or lib not in self.files:
            raise KeyError(f"Symbol library “{lib}” is not among the libraries found ({len(self.files)}).")
        node = self._block(lib, name)
        if node is None:
            raise KeyError(f"“{name}” is not in {self.files[lib].name}.")
        ext = value(node, "extends")
        if ext is not None:
            parent = self._block(lib, str(ext))
            if parent is None:
                raise KeyError(f"“{name}” extends “{ext}”, which is not in {self.files[lib].name}.")
            base = copy.deepcopy(parent)
            props = {str(atoms(p)[0]): p for p in children(node, "property") if atoms(p)}
            for i, c in enumerate(base):
                if isinstance(c, list) and head(c) == "property" and atoms(c) and str(atoms(c)[0]) in props:
                    base[i] = props.pop(str(atoms(c)[0]))
                elif isinstance(c, list) and head(c) == "symbol" and atoms(c):
                    c[1] = str(c[1]).replace(str(ext), name, 1)
            base += list(props.values())
            node = base
        node = copy.deepcopy(node)
        node[1] = f"{lib}:{name}"
        return node


def lib_pins(libsym: list, unit: int = 1) -> list[dict]:
    """The pins of a library symbol for one unit (those common to all units included), in the library's frame."""
    out = []
    for sub in children(libsym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", str(sub[1]))
        u, style = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
        if u not in (0, unit) or style not in (0, 1):
            continue
        for p in children(sub, "pin"):
            a = atoms(p)
            at = first(p, "at")
            aa = atoms(at) if at is not None else []
            nm, nb = first(p, "name"), first(p, "number")
            out.append({"type": str(a[0]) if a else "unspecified", "x": num(aa[0], 0.0) if aa else 0.0,
                        "y": num(aa[1], 0.0) if len(aa) > 1 else 0.0,
                        "name": str(atoms(nm)[0]) if nm is not None and atoms(nm) else "",
                        "number": str(atoms(nb)[0]) if nb is not None and atoms(nb) else "",
                        "hidden": Sym("hide") in p or (first(p, "hide") is not None)})
    return out


class Schematic:
    def __init__(self, tree: list, path: Path | None = None):
        if head(tree) != "kicad_sch":
            raise ValueError(f"Not a KiCad schematic (it starts with “{head(tree) or '?'}”, not kicad_sch).")
        self.tree = tree
        self.path = Path(path) if path else None
        self._n = 0

    @classmethod
    def load(cls, path) -> "Schematic":
        p = Path(path)
        return cls(parse(p.read_text(encoding="utf-8", errors="replace")), p)

    @classmethod
    def new(cls, name: str = "board") -> "Schematic":
        S = Sym
        root = str(uuid.uuid5(NS, "sheet:" + name))
        return cls([S("kicad_sch"), [S("version"), sym(20231120)], [S("generator"), "form_studio"],
                    [S("generator_version"), "8.0"], [S("uuid"), root], [S("paper"), "A4"], [S("lib_symbols")],
                    [S("sheet_instances"), [S("path"), "/", [S("page"), "1"]]]])

    def text(self) -> str:
        return dump(self.tree)

    def save(self, path) -> Path:
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(self.text(), encoding="utf-8")
        tmp.replace(path)
        return path

    # ---- reading ---------------------------------------------------------------------------------------------------
    def root_uuid(self) -> str:
        return str(value(self.tree, "uuid") or "")

    def lib_symbols(self) -> dict[str, list]:
        ls = first(self.tree, "lib_symbols")
        return {str(s[1]): s for s in children(ls, "symbol")} if ls is not None else {}

    def symbols(self) -> list[dict]:
        libs = self.lib_symbols()
        out = []
        for s in children(self.tree, "symbol"):
            lib_id = str(value(s, "lib_name") or value(s, "lib_id") or "")
            at = first(s, "at")
            aa = atoms(at) if at is not None else []
            x, y = (num(aa[0], 0.0), num(aa[1], 0.0)) if len(aa) >= 2 else (0.0, 0.0)
            rot = num(aa[2], 0.0) if len(aa) >= 3 else 0.0
            mirror = str(value(s, "mirror") or "")
            unit = int(num(value(s, "unit"), 1) or 1)
            props = {str(atoms(p)[0]): str(atoms(p)[1]) for p in children(s, "property") if len(atoms(p)) >= 2}
            lib = libs.get(lib_id) or libs.get(str(value(s, "lib_id") or ""))
            pins = []
            for p in (lib_pins(lib, unit) if lib is not None else []):
                dx, dy = _xform((p["x"], p["y"]), rot, mirror)
                pins.append({**p, "at": (round(x + dx, 4), round(y + dy, 4))})
            power = lib is not None and (first(lib, "power") is not None or Sym("power") in lib)
            out.append({"ref": props.get("Reference", ""), "value": props.get("Value", ""),
                        "footprint": props.get("Footprint", ""), "lib_id": str(value(s, "lib_id") or ""), "at": (x, y),
                        "rot": rot, "mirror": mirror, "unit": unit, "pins": pins, "power": power,
                        "missing_lib": lib is None, "on_board": str(value(s, "on_board") or "yes") != "no",
                        "dnp": str(value(s, "dnp") or "no") == "yes", "props": props, "node": s})
        return out

    def wires(self) -> list[tuple]:
        out = []
        for w in children(self.tree, "wire"):
            pts = first(w, "pts")
            p = [(num(atoms(q)[0]), num(atoms(q)[1])) for q in children(pts, "xy")] if pts is not None else []
            out += [(p[i], p[i + 1]) for i in range(len(p) - 1)]
        return out

    def labels(self) -> list[dict]:
        out = []
        for kind in ("label", "global_label", "hierarchical_label"):
            for l in children(self.tree, kind):
                at = first(l, "at")
                aa = atoms(at) if at is not None else []
                if len(aa) >= 2 and atoms(l):
                    out.append({"kind": {"label": "local", "global_label": "global", "hierarchical_label": "hierarchical"}[kind],
                                "name": str(atoms(l)[0]), "at": (num(aa[0]), num(aa[1])), "node": l})
        return out

    def _points(self, name: str) -> list[tuple]:
        out = []
        for j in children(self.tree, name):
            at = first(j, "at")
            aa = atoms(at) if at is not None else []
            if len(aa) >= 2:
                out.append((num(aa[0]), num(aa[1])))
        return out

    def sheets(self) -> list[dict]:
        out = []
        for s in children(self.tree, "sheet"):
            props = {str(atoms(p)[0]): str(atoms(p)[1]) for p in children(s, "property") if len(atoms(p)) >= 2}
            out.append({"name": props.get("Sheetname") or props.get("Sheet name", ""),
                        "file": props.get("Sheetfile") or props.get("Sheet file", "")})
        return out

    # ---- the netlist -----------------------------------------------------------------------------------------------
    def netlist(self) -> dict:
        syms = self.symbols()
        wires = self.wires()
        labels = self.labels()
        juncs = self._points("junction")
        ncs = {_k(*p) for p in self._points("no_connect")}
        parent: list[int] = []

        def new() -> int:
            parent.append(len(parent))
            return len(parent) - 1

        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def join(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        at_point: dict = {}                 # exact point -> a node there
        wnodes = []
        cell = 5.08
        wgrid: dict = {}
        for i, (a, b) in enumerate(wires):
            w = new()
            wnodes.append(w)
            for gx in range(int(math.floor(min(a[0], b[0]) / cell)), int(math.floor(max(a[0], b[0]) / cell)) + 1):
                for gy in range(int(math.floor(min(a[1], b[1]) / cell)), int(math.floor(max(a[1], b[1]) / cell)) + 1):
                    wgrid.setdefault((gx, gy), []).append(i)

        def on_wires(p) -> list[int]:
            hit = []
            for i in wgrid.get((int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))), ()):
                a, b = wires[i]
                vx, vy = b[0] - a[0], b[1] - a[1]
                L = vx * vx + vy * vy
                if L == 0:
                    d = math.hypot(p[0] - a[0], p[1] - a[1])
                else:
                    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
                    d = math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)
                if d < 5e-5:
                    hit.append(wnodes[i])
            return hit

        def attach(p) -> int:
            """A node for something at point p, joined to whatever is at p and to every wire through p."""
            k = _k(*p)
            if k not in at_point:
                at_point[k] = new()
                for w in on_wires(p):
                    join(at_point[k], w)
            return at_point[k]

        for (a, b), w in zip(wires, wnodes):
            join(w, attach(a))
            join(w, attach(b))
        for p in juncs:
            attach(p)
        pins = []
        power_names: dict = {}
        for s in syms:
            for p in s["pins"]:
                node = attach(p["at"])
                if s["power"] and p["type"] == "power_in":
                    power_names.setdefault(s["value"], []).append(node)
                elif s["ref"] and not s["ref"].startswith("#"):
                    pins.append({"ref": s["ref"], "pin": p["number"], "pin_name": p["name"], "type": p["type"],
                                 "at": p["at"], "node": node, "nc_mark": _k(*p["at"]) in ncs})
                elif s["power"]:                     # a power symbol's other pins (PWR_FLAG drives the net)
                    pins.append({"ref": s["ref"] or "#FLG", "pin": p["number"], "pin_name": p["name"], "type": p["type"],
                                 "at": p["at"], "node": node, "nc_mark": False, "flag": True})
        named: dict = {}
        lnodes = []
        for l in labels:
            node = attach(l["at"])
            lnodes.append(node)
            named.setdefault((l["kind"], l["name"]), []).append(node)
        for nodes in list(named.values()) + list(power_names.values()):
            for x in nodes[1:]:
                join(nodes[0], x)
        for name, nodes in power_names.items():      # a power symbol and a global label of the same name are one net
            for k in (("global", name),):
                if k in named:
                    join(nodes[0], named[k][0])
        rank = {"global": 0, "power": 1, "hierarchical": 2, "local": 3}
        names: dict = {}
        for (kind, name), nodes in named.items():
            names.setdefault(find(nodes[0]), []).append((rank[kind], name))
        for name, nodes in power_names.items():
            names.setdefault(find(nodes[0]), []).append((rank["power"], name))
        groups: dict = {}
        for p in pins:
            groups.setdefault(find(p["node"]), []).append(p)
        nets = []
        for root, ps in groups.items():
            real = [p for p in ps if not p.get("flag")]
            real.sort(key=lambda p: (_nat(p["ref"]), _nat(p["pin"])))
            if root in names:
                nm = sorted(names[root])[0][1]
                also = sorted({n for _r, n in names[root]} - {nm})
            elif real:
                f = real[0]
                tag = f["pin_name"] if f["pin_name"] not in ("", "~") else f"Pad{f['pin']}"
                nm = ("unconnected-(" if len(real) == 1 else "Net-(") + f"{f['ref']}-{tag})"
                also = []
            else:
                continue
            nets.append({"name": nm, "also": also, "named": root in names,
                         "nodes": [{"ref": p["ref"], "pin": p["pin"], "pin_name": p["pin_name"], "type": p["type"]} for p in real],
                         "flags": [p["type"] for p in ps if p.get("flag")], "_pins": ps})
        for root, nm in names.items():
            if root not in groups:
                nets.append({"name": sorted(nm)[0][1], "also": [], "named": True, "nodes": [], "flags": [], "_pins": []})
        nets.sort(key=lambda n: _nat(n["name"]))
        comps: dict = {}
        for s in syms:
            if s["ref"] and not s["ref"].startswith("#") and not s["power"]:
                comps.setdefault(s["ref"], {"ref": s["ref"], "value": s["value"], "footprint": s["footprint"],
                                            "lib_id": s["lib_id"], "on_board": s["on_board"], "dnp": s["dnp"], "units": 0})
                comps[s["ref"]]["units"] += 1
        notes = []
        sh = self.sheets()
        if sh:
            notes.append(f"{len(sh)} sub-sheet(s) are not opened: this is the netlist of this sheet only.")
        if children(self.tree, "bus") or children(self.tree, "bus_entry"):
            notes.append("Buses are not expanded.")
        miss = sorted({s["lib_id"] for s in syms if s["missing_lib"]})
        if miss:
            notes.append("No library symbol in the file for: " + ", ".join(miss) + " (their pins are not known).")
        self._last = {"pins": pins, "labels": labels, "lnodes": lnodes, "find": find, "ncs": ncs, "syms": syms,
                      "groups": groups}
        return {"by": "Form Studio (read from the schematic file)", "nets": nets, "sheets": sh, "notes": notes,
                "components": sorted(comps.values(), key=lambda c: _nat(c["ref"]))}

    @staticmethod
    def public(netlist: dict) -> dict:
        """The netlist without its working fields, for JSON."""
        return {**netlist, "nets": [{k: v for k, v in n.items() if not k.startswith("_")} for n in netlist["nets"]]}

    # ---- electrical checks ---------------------------------------------------------------------------------------------
    def erc(self) -> dict:
        nl = self.netlist()
        w = self._last
        rows = []

        def row(kind, sev, desc, items):
            rows.append({"type": kind, "severity": sev, "description": desc, "items": items})

        def it(p):
            return {"ref": p["ref"], "pin": p["pin"], "pin_name": p["pin_name"], "x": p["at"][0], "y": p["at"][1]}
        for net in nl["nets"]:
            ps = net["_pins"]
            real = [p for p in ps if not p.get("flag")]
            types = [p["type"] for p in ps]
            if len(real) == 1 and not net["named"] and not net["flags"]:
                p = real[0]
                if p["type"] != "no_connect" and not p["nc_mark"]:
                    row("pin_not_connected", "error", f"{p['ref']} pin {p['pin']} ({p['pin_name'] or p['type']}) is not connected",
                        [it(p)])
            for p in real:
                if p["nc_mark"] and len(real) > 1:
                    row("no_connect_connected", "warning", f"{p['ref']} pin {p['pin']} has a no-connect mark but is connected", [it(p)])
                if p["type"] == "no_connect" and len(real) > 1:
                    row("no_connect_pin_connected", "warning", f"{p['ref']} pin {p['pin']} is a no-connect pin but is connected", [it(p)])
            if len(real) + len(net["flags"]) < 2 and not (len(real) == 1 and net["named"]):
                continue
            if "power_in" in types and "power_out" not in types:
                pin = next(p for p in real if p["type"] == "power_in")
                row("power_pin_not_driven", "error", f"Net {net['name']}: power input {pin['ref']} pin {pin['pin']} is not "
                    "driven by a power output (a regulator's output or a PWR_FLAG)", [it(p) for p in real if p["type"] == "power_in"])
            if "input" in types and not (set(types) & DRIVERS):
                row("input_not_driven", "error", f"Net {net['name']}: input pins with nothing driving them",
                    [it(p) for p in real if p["type"] == "input"])
            seen = set()
            for i in range(len(ps)):
                for j in range(i + 1, len(ps)):
                    pair = frozenset((ps[i]["type"], ps[j]["type"]))
                    sev = CONFLICT.get(pair)
                    if sev and pair not in seen:
                        seen.add(pair)
                        a, b = ps[i], ps[j]
                        row("conflicting_drivers", sev, f"Net {net['name']}: {a['ref']} pin {a['pin']} ({a['type']}) and "
                            f"{b['ref']} pin {b['pin']} ({b['type']}) both drive it", [it(a), it(b)])
        find, groups = w["find"], w["groups"]
        by_name: dict = {}
        for l in w["labels"]:
            by_name.setdefault((l["kind"], l["name"]), []).append(l)
        for l, node in zip(w["labels"], w["lnodes"]):
            has_pins = bool([p for p in groups.get(find(node), []) if not p.get("flag")])
            if not has_pins:
                row("label_dangling", "warning", f"Label “{l['name']}” is not connected to any pin",
                    [{"x": l["at"][0], "y": l["at"][1]}])
        refs: dict = {}
        for s in w["syms"]:
            if s["power"] or s["ref"].startswith("#"):
                continue
            if not s["ref"] or s["ref"].endswith("?"):
                row("not_annotated", "error", f"A {s['lib_id']} has no reference number ({s['ref'] or 'empty'})",
                    [{"x": s["at"][0], "y": s["at"][1]}])
                continue
            refs.setdefault((s["ref"], s["unit"]), []).append(s)
        for (ref, unit), ss in refs.items():
            if len(ss) > 1:
                row("duplicate_reference", "error", f"{len(ss)} symbols are called {ref}" + (f" (unit {unit})" if unit > 1 else ""),
                    [{"x": s["at"][0], "y": s["at"][1]} for s in ss])
        counts: dict = {}
        for r in rows:
            counts[r["severity"]] = counts.get(r["severity"], 0) + 1
        return {"by": ERC_BY, "evidence": "computed from the schematic file", "rows": rows, "total": len(rows),
                "counts": counts, "nets": len(nl["nets"]), "components": len(nl["components"]),
                "not_checked": ERC_NOT_CHECKED, "notes": nl["notes"],
                "headline": (f"{len(rows)} " + ("finding" if len(rows) == 1 else "findings") if rows else "no findings") +
                            " from Form Studio's ERC subset (not KiCad's ERC)"}

    # ---- changing ------------------------------------------------------------------------------------------------------
    def _uuid(self, *key) -> list:
        self._n += 1
        base = sum(1 for _ in self.tree)
        return [Sym("uuid"), str(uuid.uuid5(NS, f"{self.root_uuid()}|{base}|{self._n}|" + "|".join(str(k) for k in key)))]

    def _insert(self, node: list) -> None:
        """Before sheet_instances and the like, which KiCad writes last."""
        tail = ("sheet_instances", "symbol_instances", "embedded_fonts")
        i = next((k for k, c in enumerate(self.tree) if isinstance(c, list) and head(c) in tail), len(self.tree))
        self.tree.insert(i, node)

    @staticmethod
    def _fx(hide: bool = False, justify: str = "") -> list:
        fx = [Sym("effects"), [Sym("font"), [Sym("size"), sym(1.27), sym(1.27)]]]
        if justify:
            fx.append([Sym("justify"), *[Sym(j) for j in justify.split()]])
        if hide:
            fx.append([Sym("hide"), Sym("yes")])
        return fx

    def pin_at(self, pin: str) -> tuple:
        """Where "R1.2" (reference.pin number, or reference.pin name) connects."""
        ref, _, n = pin.partition(".")
        for s in self.symbols():
            if s["ref"] != ref:
                continue
            for p in s["pins"]:
                if p["number"] == n or (p["name"] == n and n not in ("", "~")):
                    return p["at"]
        raise KeyError(f"No pin “{pin}” in the schematic (write it as REF.PIN, for example R1.2).")

    def place(self, libs: Libraries, lib_id: str, at, ref: str = "", value_: str = "", footprint: str = "",
              rot: float = 0.0, mirror: str = "", unit: int = 1, props: dict | None = None) -> dict:
        """Place a symbol from the person's libraries; its library symbol is copied into the file (as KiCad does)."""
        S = Sym
        ls = first(self.tree, "lib_symbols")
        if ls is None:
            ls = [S("lib_symbols")]
            self.tree.insert(min(len(self.tree), 6), ls)
        have = self.lib_symbols()
        if lib_id not in have:
            ls.append(libs.symbol(lib_id))
        lib = self.lib_symbols()[lib_id]
        if int(round(rot)) % 90:
            raise ValueError("A symbol's rotation is 0, 90, 180 or 270.")
        if mirror not in ("", "x", "y"):
            raise ValueError('mirror is "x", "y" or empty.')
        x, y = round(round(at[0] / GRID) * GRID, 4), round(round(at[1] / GRID) * GRID, 4)
        lp = {str(atoms(p)[0]): p for p in children(lib, "property") if atoms(p)}
        prefix = str(atoms(lp["Reference"])[1]) if "Reference" in lp else "U"
        power = first(lib, "power") is not None or S("power") in lib
        ref = ref or (prefix + "?")
        vals = {"Reference": ref, "Value": value_ or (str(atoms(lp["Value"])[1]) if "Value" in lp else lib_id.split(":")[-1]),
                "Footprint": footprint or (str(atoms(lp["Footprint"])[1]) if "Footprint" in lp else ""),
                "Datasheet": str(atoms(lp["Datasheet"])[1]) if "Datasheet" in lp else ""}
        vals.update({str(k): str(v) for k, v in (props or {}).items()})
        node = [S("symbol"), [S("lib_id"), lib_id], [S("at"), sym(x), sym(y), sym(int(round(rot)) % 360)]]
        if mirror:
            node.append([S("mirror"), S(mirror)])
        node += [[S("unit"), sym(int(unit))], [S("exclude_from_sim"), S("no")], [S("in_bom"), S("yes")],
                 [S("on_board"), S("yes")], [S("dnp"), S("no")], self._uuid("symbol", lib_id, x, y, ref)]
        for name, val in vals.items():
            src = lp.get(name)
            sa = atoms(first(src, "at")) if src is not None and first(src, "at") is not None else []
            ox, oy = (num(sa[0], 0.0), num(sa[1], 0.0)) if len(sa) >= 2 else (0.0, 0.0)
            hidden = name in ("Footprint", "Datasheet") or (power and name == "Reference") or (
                src is not None and "hide" in dump(src))
            node.append([S("property"), name, val, [S("at"), sym(round(x + ox, 4)), sym(round(y - oy, 4)), sym(0)],
                         self._fx(hide=hidden)])
        pins = lib_pins(lib, unit)
        for p in pins:
            node.append([S("pin"), p["number"], self._uuid("pin", ref, p["number"])])
        node.append([S("instances"), [S("project"), self.path.stem if self.path else "board",
                                      [S("path"), "/" + self.root_uuid(), [S("reference"), ref], [S("unit"), sym(int(unit))]]]])
        self._insert(node)
        return {"ref": ref, "lib_id": lib_id, "at": [x, y],
                "pins": {p["number"]: [round(x + _xform((p["x"], p["y"]), rot, mirror)[0], 4),
                                       round(y + _xform((p["x"], p["y"]), rot, mirror)[1], 4)] for p in pins}}

    def wire(self, points: list) -> None:
        S = Sym
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            if _k(*a) == _k(*b):
                continue
            self._insert([S("wire"), [S("pts"), [S("xy"), sym(float(a[0])), sym(float(a[1]))], [S("xy"), sym(float(b[0])), sym(float(b[1]))]],
                          [S("stroke"), [S("width"), sym(0)], [S("type"), S("default")]], self._uuid("wire", a, b)])

    def connect(self, a: str, b: str) -> list:
        """A wire from pin a to pin b: straight when they line up, otherwise across then down."""
        pa, pb = self.pin_at(a), self.pin_at(b)
        if _k(*pa)[0] == _k(*pb)[0] or _k(*pa)[1] == _k(*pb)[1]:
            ways = [[pa, pb]]
        else:
            ways = [[pa, (pb[0], pa[1]), pb], [pa, (pa[0], pb[1]), pb]]
        others = [p["at"] for s in self.symbols() for p in s["pins"] if _k(*p["at"]) not in (_k(*pa), _k(*pb))]

        def crosses(pts) -> bool:           # a wire over another pin would join that pin too
            for i in range(len(pts) - 1):
                (x0, y0), (x1, y1) = pts[i], pts[i + 1]
                for ox, oy in others:
                    if min(x0, x1) - 1e-4 <= ox <= max(x0, x1) + 1e-4 and min(y0, y1) - 1e-4 <= oy <= max(y0, y1) + 1e-4 \
                            and abs((x1 - x0) * (oy - y0) - (y1 - y0) * (ox - x0)) < 1e-6:
                        return True
            return False
        pts = next((w for w in ways if not crosses(w)), None)
        if pts is None:
            raise ValueError(f"A straight or one-corner wire from {a} to {b} would run over another pin; use "
                             '{"op": "net", "name": ..., "pins": [...]} to join them by a label, or wire with points')
        self.wire(pts)
        return [list(p) for p in pts]

    def label(self, name: str, at=None, pin: str = "", kind: str = "local", rot: float = 0.0) -> None:
        S = Sym
        if not name:
            raise ValueError("A label needs a name.")
        p = self.pin_at(pin) if pin else tuple(at)
        if kind == "global":
            node = [S("global_label"), name, [S("shape"), S("passive")], [S("at"), sym(float(p[0])), sym(float(p[1])), sym(float(rot))],
                    self._fx(justify="left"), self._uuid("glabel", name, p)]
        elif kind == "local":
            node = [S("label"), name, [S("at"), sym(float(p[0])), sym(float(p[1])), sym(float(rot))],
                    self._fx(justify="left bottom"), self._uuid("label", name, p)]
        else:
            raise ValueError('A label is "local" or "global".')
        self._insert(node)

    def junction(self, at) -> None:
        S = Sym
        self._insert([S("junction"), [S("at"), sym(float(at[0])), sym(float(at[1]))], [S("diameter"), sym(0)],
                      [S("color"), sym(0), sym(0), sym(0), sym(0)], self._uuid("junction", at)])

    def no_connect(self, pin: str) -> None:
        p = self.pin_at(pin)
        self._insert([Sym("no_connect"), [Sym("at"), sym(float(p[0])), sym(float(p[1]))], self._uuid("nc", p)])

    def set_property(self, ref: str, name: str, val: str) -> None:
        hit = False
        for s in self.symbols():
            if s["ref"] != ref:
                continue
            hit = True
            for p in children(s["node"], "property"):
                if atoms(p) and str(atoms(p)[0]) == name:
                    p[2] = str(val)
                    break
            else:
                s["node"].append([Sym("property"), name, str(val), [Sym("at"), sym(s["at"][0]), sym(s["at"][1]), sym(0)],
                                  self._fx(hide=True)])
            if name == "Reference":
                self._set_instance_ref(s["node"], str(val))
        if not hit:
            raise KeyError(f"No symbol “{ref}” in the schematic.")

    @staticmethod
    def _set_instance_ref(node: list, ref: str) -> None:
        inst = first(node, "instances")
        for proj in children(inst, "project") if inst is not None else []:
            for path in children(proj, "path"):
                r = first(path, "reference")
                if r is not None:
                    r[1:] = [ref]

    def remove(self, ref: str) -> int:
        gone = [s["node"] for s in self.symbols() if s["ref"] == ref]
        if not gone:
            raise KeyError(f"No symbol “{ref}” in the schematic.")
        self.tree[:] = [c for c in self.tree if not any(c is g for g in gone)]
        return len(gone)

    def annotate(self) -> dict:
        """Number every reference that ends in "?" (R? -> R1), lowest free number first, in reading order."""
        used: dict = {}
        syms = self.symbols()
        for s in syms:
            m = re.fullmatch(r"(#?[A-Za-z_]+)(\d+)", s["ref"])
            if m:
                used.setdefault(m.group(1), set()).add(int(m.group(2)))
        out = {}
        for s in sorted([s for s in syms if s["ref"].endswith("?")], key=lambda s: (s["at"][1], s["at"][0])):
            pre = s["ref"][:-1]
            n = 1
            while n in used.setdefault(pre, set()):
                n += 1
            used[pre].add(n)
            new = f"{pre}{n}"
            for p in children(s["node"], "property"):
                if atoms(p) and str(atoms(p)[0]) == "Reference":
                    p[2] = new
            self._set_instance_ref(s["node"], new)
            out[f"{s['lib_id']} at {s['at'][0]:g}, {s['at'][1]:g}"] = new
        return out

    def apply(self, ops: list, libs: Libraries | None = None) -> list:
        """Operations an agent sends, in order; all or nothing (the tree is put back when one fails).
        place {lib_id, at, ref?, value?, footprint?, rot?, mirror?, unit?} · wire {points} · connect {from, to} ·
        net {name, pins: [REF.PIN, ...], kind?: local|global} (a label on each pin) · label {name, at | pin, kind?} ·
        power {lib_id, pin} (a power symbol on a pin) · junction {at} · no_connect {pin} ·
        set {ref, name, value} · remove {ref} · annotate {}"""
        keep = copy.deepcopy(self.tree)
        done = []
        try:
            for i, op in enumerate(ops):
                k = str(op.get("op", ""))
                if k == "place":
                    if libs is None:
                        raise ValueError("Placing a symbol needs symbol libraries.")
                    done.append({"op": k, **self.place(libs, op["lib_id"], op["at"], op.get("ref", ""), op.get("value", ""),
                                                       op.get("footprint", ""), op.get("rot", 0.0), op.get("mirror", ""),
                                                       int(op.get("unit", 1)), op.get("props"))})
                elif k == "wire":
                    self.wire([tuple(p) for p in op["points"]])
                    done.append({"op": k, "segments": len(op["points"]) - 1})
                elif k == "connect":
                    done.append({"op": k, "points": self.connect(op["from"], op["to"])})
                elif k == "net":
                    for pin in op["pins"]:
                        self.label(op["name"], pin=pin, kind=op.get("kind", "local"))
                    done.append({"op": k, "name": op["name"], "pins": list(op["pins"])})
                elif k == "label":
                    self.label(op["name"], op.get("at"), op.get("pin", ""), op.get("kind", "local"), op.get("rot", 0.0))
                    done.append({"op": k, "name": op["name"]})
                elif k == "power":
                    if libs is None:
                        raise ValueError("A power symbol needs symbol libraries.")
                    at = self.pin_at(op["pin"])
                    done.append({"op": k, **self.place(libs, op["lib_id"], at, ref="#PWR?", rot=op.get("rot", 0.0))})
                elif k == "junction":
                    self.junction(op["at"])
                    done.append({"op": k})
                elif k == "no_connect":
                    self.no_connect(op["pin"])
                    done.append({"op": k, "pin": op["pin"]})
                elif k == "set":
                    self.set_property(op["ref"], op["name"], op["value"])
                    done.append({"op": k, "ref": op["ref"]})
                elif k == "remove":
                    done.append({"op": k, "ref": op["ref"], "removed": self.remove(op["ref"])})
                elif k == "annotate":
                    done.append({"op": k, "named": self.annotate()})
                else:
                    raise ValueError(f"Unknown operation “{k}” (operation {i + 1}): place, wire, connect, net, label, "
                                     "power, junction, no_connect, set, remove or annotate.")
        except (KeyError, ValueError, TypeError, IndexError) as e:
            self.tree[:] = keep
            msg = e.args[0] if e.args else str(e)
            raise ValueError(f"Operation {len(done) + 1} ({ops[len(done)].get('op', '?')}) failed: {msg}. Nothing was changed.") from e
        return done
