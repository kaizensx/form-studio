"""Circuit boards and their enclosures (wave K): bring a board, get an enclosure that is proved to fit it.

    sexpr.py      Form Studio's own S-expression reader (KiCad's text formats)
    kicad.py      .kicad_pcb (KiCad 5 to 9) and the rules in its .kicad_pro; a synthetic fixture for tests
    idf.py        IDF 3.0 .emn with its .emp library
    model.py      the board model in the board frame: outline, holes, parts, connectors and their mating side
    enclosure.py  the enclosure as a design's code (one feature per step, every size a parameter)
    fit.py        kernel ops: the board against the enclosure on the solids; heights from a board STEP
    kicad_cli.py  the person's own KiCad: DRC, ERC, Gerbers, drill, pick-and-place, BOM, STEP
    fabs.py       JLCPCB, PCBWay and OSH Park's published limits, quoted with page and date
    api.py        the loop for a project, and the Bench entries

Nothing here imports OCCT at import time; fit.py's ops run in the kernel worker. Headless: MCP board_import,
board_check, board_fab and `form board ...` (JSON). docs/BOARDS.md has the whole loop and the K2 routing plan.
"""
from __future__ import annotations


def read(path, origin=None) -> dict:
    """The board model of a .kicad_pcb or an IDF .emn (form/board/model.py)."""
    from .api import read as _read
    return _read(path, origin)
