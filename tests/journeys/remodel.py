"""Meshes made editable: a faceted solid is drawn smooth with lines only at its creases, and Describe › Reference parts
offers Rebuild as editable CAD, which starts a conversation with the staged remodel brief. No model is called (the
stand-in agent answers)."""
import base64
import math
import sys
from pathlib import Path

import numpy as np

from _lib import open_project, wait_job

DATA = "fresh"

SOURCE = '''
from build123d import *
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Embedded mesh"
    summary = "A mesh used as the design (what a remodel replaces)"
    params = [Param("scale_pct", "Scale", 100, 10, 200, 1, "%", "form", "body", "")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", self.reference("puck.stl"))]
'''


def puck(path: Path, n: int = 64, r: float = 20.0, h: float = 8.0):
    """A faceted cylinder: n facets round the side (5.6° apart), fan caps."""
    from form.recon.mesh import write_stl
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    ring = np.c_[r * np.cos(a), r * np.sin(a)]
    V = np.vstack([np.c_[ring, np.zeros(n)], np.c_[ring, np.full(n, h)], [[0, 0, 0], [0, 0, h]]])
    F = []
    for i in range(n):
        j = (i + 1) % n
        F += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    write_stl(path, V, np.array(F), "puck")
    return path


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    stl = puck(Path(__import__("os").environ.get("FORM_UITEST_TMP", ".")) / "puck.stl")
    st = ui.studio
    p = st.create_design("Embedded puck", SOURCE, references=[str(stl)], purpose="model")
    pid = p["id"]
    st.run(pid)
    wait_job(ui, pid)
    open_project(ui, pid)

    # ── the faceted solid is drawn smooth, with lines only on its two rims ──
    v = st.view(st.load(pid))
    E = np.frombuffer(base64.b64decode(v["edges"]), dtype=np.float32).reshape(-1, 6)
    mid = (E[:, :3] + E[:, 3:]) / 2
    ui.check(len(E) <= 2 * 64 + 4, f"only the rims are drawn ({len(E)} segments, the mesh has {64 * 4 * 3 // 2} triangle edges)")
    ui.check(bool(np.all((np.abs(mid[:, 2]) < 1e-3) | (np.abs(mid[:, 2] - 8) < 1e-3))), "every drawn line is on a rim")
    tri = sum(len(base64.b64decode(m["indices"])) // 12 for m in v["mesh"])
    verts = sum(len(base64.b64decode(m["positions"])) // 12 for m in v["mesh"])
    ui.check(verts < 3 * tri / 2, f"facets share their vertices, so they shade smooth ({verts} vertices for {tri} triangles)")
    ui.shot("remodel-faceted-smooth")

    # ── Describe › Reference parts: Rebuild as editable CAD starts the remodel conversation ──
    ui.run_js("Store.setStage('brief')")
    ui.settle(600)
    ui.wait_until(lambda: ui.exists("rebuildCad"), 10, "the Rebuild as editable CAD button")
    b = ui.item("rebuildCad")
    ui.scroll_to(b, 0.5)
    ui.settle(300)
    ui.shot("remodel-brief")
    ui.wait_until(lambda: ui.js("Store.chat.available && Store.chatReady"), 20, "the stand-in agent to be connected")
    ui.click(b)
    ui.wait_until(lambda: any(i.get("t") == "user" and "Rebuild puck.stl as clean, fully editable CAD" in (i.get("text") or "")
                              for i in (ui.js("Store.chatItems") or [])), 15, "the remodel brief to be sent")
    msg = next(i["text"] for i in ui.js("Store.chatItems") if i.get("t") == "user")
    for word in ("Never embed the meshes", "analyze_reference", "compare_to_reference", "0.1 mm"):
        ui.check(word in msg, f"the brief says {word!r}")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 30, "the stand-in agent's reply")
    ui.shot("remodel-conversation")
