"""Synthetic boards and libraries for tests, demos and the router's own numbers. Every size here is made up for
testing; none is a real product, and none is read from KiCad's libraries.

    header_to_ic(path)     a pin header, an SOIC-16 and eight 0603 parts on a 40 x 30 mm two-layer board: 17 nets
                           that cross, so the router needs both layers and vias
    rooms(path)            one layer, walls with one-track gaps: the shortest net takes the only way another net
                           has, so it routes only after a rip-up
    channel(path, n)       n nets through a channel that holds exactly n tracks
    symbol_library(path)   a small .kicad_sym (R, C, a regulator, a connector, power symbols) in KiCad 8's format
    footprint_library(dir) the matching .pretty folder
"""
from __future__ import annotations

from pathlib import Path

from . import pcb

O = 100.0          # where the outline's corner is in the file


def _smd(doc, ref, x, y, net, size=(1.0, 1.0)):
    pcb.add_part(doc, ref, (O + x, O + y), [{"num": "1", "at": (0, 0), "size": size, "net": net}])


def header_to_ic(path=None, unrouted_extra: bool = False) -> pcb.Pcb:
    doc = pcb.blank(40.0, 30.0)
    hdr = [{"num": str(i + 1), "at": (0, i * 2.54), "size": (1.7, 1.7), "shape": "circle", "kind": "thru_hole", "drill": 1.0,
            "net": ("GND" if i == 0 else "VCC" if i == 1 else f"D{i - 2}")} for i in range(8)]
    pcb.add_part(doc, "J1", (O + 4.0, O + 6.0), hdr, lib="Form:PinHeader_1x08", height=8.5)
    # SOIC-16: pins 1-8 down the left, 9-16 up the right; the data nets are wired in a shuffled order
    order = [3, 0, 5, 1, 4, 2]
    pads = []
    for i in range(8):
        net = "GND" if i == 7 else "VCC" if i == 0 else f"D{order[i - 1]}"
        pads.append({"num": str(i + 1), "at": (-2.7, -4.445 + i * 1.27), "size": (1.5, 0.6), "net": net})
    for i in range(8):
        pads.append({"num": str(9 + i), "at": (2.7, 4.445 - i * 1.27), "size": (1.5, 0.6), "net": f"Q{i}"})
    pcb.add_part(doc, "U1", (O + 18.0, O + 15.0), pads, lib="Form:SOIC-16", height=1.75)
    for i in range(8):
        y = 4.0 + i * 3.0
        pcb.add_part(doc, f"R{i + 1}", (O + 30.0, O + y),
                     [{"num": "1", "at": (-0.8, 0), "size": (0.8, 0.95), "net": f"Q{7 - i}"},
                      {"num": "2", "at": (0.8, 0), "size": (0.8, 0.95), "net": "GND" if i % 2 else "VCC"}],
                     lib="Form:R_0603", height=0.55)
    pcb.add_part(doc, "C1", (O + 18.0, O + 4.0),
                 [{"num": "1", "at": (-0.8, 0), "size": (0.8, 0.95), "net": "VCC"},
                  {"num": "2", "at": (0.8, 0), "size": (0.8, 0.95), "net": "GND"}], lib="Form:C_0603", height=0.9)
    if unrouted_extra:                      # a pad walled in by a keep-out: it cannot be reached, and must be reported
        _smd(doc, "TP1", 36.0, 27.0, "D0")
        pcb.add_keepout(doc, [(O + 34, O + 25), (O + 38, O + 25), (O + 38, O + 29), (O + 34, O + 29)], tracks=False,
                        vias=False, name="walled")
    if path:
        doc.save(path)
        doc.path = Path(path)
    return doc


def _wall(doc, x0, y0, x1, y1, name):
    pcb.add_keepout(doc, [(O + x0, O + y0), (O + x1, O + y0), (O + x1, O + y1), (O + x0, O + y1)], layers=("F.Cu",),
                    tracks=False, vias=False, name=name)


def rooms(path=None) -> pcb.Pcb:
    """A top room and two bottom rooms. Gaps one track wide: G1 into the left room, G2 into the right room, G3
    between the bottom rooms. Net A (shortest, routed first) goes top -> G1 -> G3 -> right room, which closes both
    of net B's ways into the left room. Rip-up removes A, routes B through G1, and A then goes through G2."""
    doc = pcb.blank(30.0, 20.0)
    gap = 0.5
    for i, (a, b) in enumerate(((0.0, 8.0 - gap / 2), (8.0 + gap / 2, 27.0 - gap / 2), (27.0 + gap / 2, 30.0))):
        _wall(doc, a, 9.5, b, 10.5, f"wall-h{i}")
    _wall(doc, 14.5, 10.5, 15.5, 15.0 - gap / 2, "wall-v0")
    _wall(doc, 14.5, 15.0 + gap / 2, 15.5, 20.0, "wall-v1")
    _smd(doc, "A1", 10.0, 7.0, "A")
    _smd(doc, "A2", 17.5, 15.0, "A")
    _smd(doc, "B1", 25.0, 3.0, "B")
    _smd(doc, "B2", 3.0, 17.0, "B")
    if path:
        doc.save(path)
        doc.path = Path(path)
    return doc


def channel(path=None, n: int = 5, slack: float = 0.12) -> pcb.Pcb:
    """n nets, pads in a column on the left and in the reverse column on the right, through a channel in a wall
    whose width holds n tracks of the default class (0.2 mm wide, 0.2 mm apart) and `slack` more."""
    doc = pcb.blank(30.0, 24.0)
    width = n * 0.2 + (n - 1) * 0.2 + 0.2 + slack
    _wall(doc, 14.5, 0.0, 15.5, 12.0 - width / 2, "wall-top")
    _wall(doc, 14.5, 12.0 + width / 2, 15.5, 24.0, "wall-bottom")
    for i in range(n):
        y = 12.0 + (i - (n - 1) / 2) * 3.0
        _smd(doc, f"L{i + 1}", 4.0, y, f"N{i + 1}")
        _smd(doc, f"R{i + 1}", 26.0, y, f"N{i + 1}")
    if path:
        doc.save(path)
        doc.path = Path(path)
    return doc


# ---- libraries in KiCad's formats (their content is made up) -------------------------------------------------------------
def _sym(name, ref, pins, power=False, extends=None, body=(-2.54, -2.54, 2.54, 2.54)) -> str:
    if extends:
        return (f'\t(symbol "{name}" (extends "{extends}")\n'
                f'\t\t(property "Reference" "{ref}" (at 0 5.08 0) (effects (font (size 1.27 1.27))))\n'
                f'\t\t(property "Value" "{name}" (at 0 -5.08 0) (effects (font (size 1.27 1.27))))\n\t)\n')
    out = [f'\t(symbol "{name}"' + (" (power)" if power else "") + " (pin_names (offset 0.254)) (exclude_from_sim no) (in_bom yes) (on_board yes)",
           f'\t\t(property "Reference" "{ref}" (at 0 5.08 0) (effects (font (size 1.27 1.27))' + (" (hide yes)" if power else "") + "))",
           f'\t\t(property "Value" "{name}" (at 0 -5.08 0) (effects (font (size 1.27 1.27))))',
           '\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           '\t\t(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           f'\t\t(symbol "{name}_0_1"',
           f'\t\t\t(rectangle (start {body[0]} {body[1]}) (end {body[2]} {body[3]}) (stroke (width 0.254) (type default)) (fill (type none)))',
           "\t\t)", f'\t\t(symbol "{name}_1_1"']
    for num, pname, etype, x, y, ang in pins:
        out.append(f'\t\t\t(pin {etype} line (at {x} {y} {ang}) (length 2.54)' + (" (hide yes)" if power and etype == "power_in" else "") +
                   f' (name "{pname}" (effects (font (size 1.27 1.27)))) (number "{num}" (effects (font (size 1.27 1.27)))))')
    out += ["\t\t)", "\t)"]
    return "\n".join(out) + "\n"


def symbol_library(path) -> Path:
    """Form.kicad_sym: R, C, LED, REG (in, gnd, out), CONN2, MCU (two outputs, an input, power), and the power
    symbols GND, +5V, +3V3 and PWR_FLAG. KiCad 8's library format; the parts are made up."""
    body = ['(kicad_symbol_lib (version 20231120) (generator "form_studio_fixture") (generator_version "8.0")\n']
    body.append(_sym("R", "R", [("1", "~", "passive", 0, 5.08, 270), ("2", "~", "passive", 0, -5.08, 90)]))
    body.append(_sym("C", "C", [("1", "~", "passive", 0, 5.08, 270), ("2", "~", "passive", 0, -5.08, 90)]))
    body.append(_sym("R_Small", "R", [], extends="R"))
    body.append(_sym("LED", "D", [("1", "K", "passive", -5.08, 0, 0), ("2", "A", "passive", 5.08, 0, 180)]))
    body.append(_sym("REG", "U", [("1", "VIN", "power_in", -5.08, 0, 0), ("2", "GND", "power_in", 0, -5.08, 90),
                                  ("3", "VOUT", "power_out", 5.08, 0, 180)]))
    body.append(_sym("CONN2", "J", [("1", "Pin_1", "passive", -5.08, 1.27, 0), ("2", "Pin_2", "passive", -5.08, -1.27, 0)]))
    body.append(_sym("MCU", "U", [("1", "VDD", "power_in", 0, 7.62, 270), ("2", "GND", "power_in", 0, -7.62, 90),
                                  ("3", "PA0", "output", 7.62, 2.54, 180), ("4", "PA1", "output", 7.62, 0, 180),
                                  ("5", "PA2", "input", 7.62, -2.54, 180), ("6", "NC", "no_connect", -7.62, 0, 0)],
                     body=(-5.08, -5.08, 5.08, 5.08)))
    body.append(_sym("GND", "#PWR", [("1", "GND", "power_in", 0, 0, 270)], power=True))
    body.append(_sym("+5V", "#PWR", [("1", "+5V", "power_in", 0, 0, 90)], power=True))
    body.append(_sym("+3V3", "#PWR", [("1", "+3V3", "power_in", 0, 0, 90)], power=True))
    body.append(_sym("PWR_FLAG", "#FLG", [("1", "pwr", "power_out", 0, 0, 90)], power=True))
    body.append(")\n")
    path = Path(path)
    path.write_text("".join(body), encoding="utf-8")
    return path


def footprint_library(folder) -> Path:
    """Form.pretty: R_0603, C_0603, LED_0603, SOT-223 (three pins and a tab), Header_1x02, QFN-ish MCU_6."""
    d = Path(folder) / "Form.pretty"
    d.mkdir(parents=True, exist_ok=True)

    def fp(name, pads, court, height=None):
        lines = [f'(footprint "{name}" (version 20240108) (generator "form_studio_fixture") (layer "F.Cu")',
                 '\t(property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))',
                 f'\t(property "Value" "{name}" (at 0 2 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))']
        if height is not None:
            lines.append(f'\t(property "Height" "{height}" (at 0 0 0) (layer "F.Fab") (effects (font (size 1 1)) (hide yes)))')
        lines.append(f'\t(fp_rect (start {court[0]} {court[1]}) (end {court[2]} {court[3]}) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))')
        for num, kind, shape, x, y, w, h, drill in pads:
            lay = '"*.Cu" "*.Mask"' if kind == "thru_hole" else '"F.Cu" "F.Paste" "F.Mask"'
            dr = f" (drill {drill})" if drill else ""
            rr = " (roundrect_rratio 0.25)" if shape == "roundrect" else ""
            lines.append(f'\t(pad "{num}" {kind} {shape} (at {x} {y}) (size {w} {h}){dr} (layers {lay}){rr})')
        lines.append(")")
        (d / f"{name}.kicad_mod").write_text("\n".join(lines) + "\n", encoding="utf-8")
    two = lambda: [("1", "smd", "roundrect", -0.8, 0, 0.8, 0.95, None), ("2", "smd", "roundrect", 0.8, 0, 0.8, 0.95, None)]
    fp("R_0603", two(), (-1.5, -0.75, 1.5, 0.75), 0.55)
    fp("C_0603", two(), (-1.5, -0.75, 1.5, 0.75), 0.9)
    fp("LED_0603", two(), (-1.5, -0.75, 1.5, 0.75), 0.8)
    fp("SOT-223", [("1", "smd", "rect", -2.3, 3.15, 1.0, 2.0, None), ("2", "smd", "rect", 0, 3.15, 1.0, 2.0, None),
                   ("3", "smd", "rect", 2.3, 3.15, 1.0, 2.0, None)], (-3.6, -4.4, 3.6, 4.4), 1.8)
    fp("Header_1x02", [("1", "thru_hole", "rect", 0, 0, 1.7, 1.7, 1.0), ("2", "thru_hole", "circle", 0, 2.54, 1.7, 1.7, 1.0)],
       (-1.8, -1.8, 1.8, 4.35), 8.5)
    fp("MCU_6", [(str(i + 1), "smd", "rect", (-1.9 if i < 3 else 1.9), ((i % 3) - 1) * 1.27 * (1 if i < 3 else -1), 1.2, 0.6, None)
                 for i in range(6)], (-2.8, -2.2, 2.8, 2.2), 1.1)
    return d
