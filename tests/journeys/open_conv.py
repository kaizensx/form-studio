"""Conversations lead to their designs. Opening a conversation from Home lands on its design within a second; one that
made three shows a strip of three under its title, and each opens; one that made none says "No design yet" and never
shows the Home question; one whose design is in the trash says so. An agent working on another design never takes the
view away once the person is working: it is named, with Show. Talk's attach dialog takes every file type Form Studio
reads, and a file link pasted into Talk is fetched into an attachment chip.

The conversations' design lists are written straight into the record (`designs`, as the engine keeps them), so this
journey does not depend on which agent made them."""
import http.server
import os
import threading
import time
from pathlib import Path

from _lib import make, toasts_gone

DATA = "fresh"
S = {}


def conv(ui, title, designs, project):
    m = ui.api("/conversations", {"project": project, "agent": "fake"})
    store = ui.studio.chat.store
    store.append(m["id"], {"t": "user", "text": title})
    store.append(m["id"], {"t": "end", "steps": 1, "seconds": 1})
    store.update(m["id"], title=title, title_auto=False, messages=1, events=2, project=project,
                 designs=[{"project": p, "role": "made", "ts": time.time(), "state": "live"} for p in designs])
    return m["id"]


def open_from_home(ui, cid):
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home")
    ui.run_js("Store.loadConvs()")
    card = ui.wait_until(lambda: next((c for c in ui.find_all(name="homeConversation") if c.property("convId") == cid), None),
                         15, "the conversation's card on Home")
    ui.settle(300)
    t0 = time.time()
    ui.click(card)
    return t0


def journey_conversation_with_three_designs(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["a"] = make(ui, "coupon", "Wallet base", open=False)
    S["b"] = make(ui, "coupon", "Wallet slider", open=False)
    S["c"] = make(ui, "coupon", "Wallet cascade", open=False)
    S["three"] = conv(ui, "Make this wallet editable", [S["a"], S["b"], S["c"]], S["c"])
    S["none"] = conv(ui, "Ideas for a lamp", [], None)
    ui.run_js("Store.reloadStudio(); Store.loadConvs()")
    ui.settle(600)
    ui.wait_until(lambda: len(ui.find_all(name="homeConversation")) >= 2, 10, "the conversations on Home")
    ui.wait_until(lambda: ui.find(name="conversationDesigns") is not None, 10, "a conversation card with its designs")
    ui.shot("open-conv-home")
    t0 = open_from_home(ui, S["three"])
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == S["c"], 5, "the conversation's design")
    took = time.time() - t0
    ui.check(took < 1.5, f"landed on the design in {took:.2f} s")
    items = ui.wait_until(lambda: (lambda x: x if len(x) == 3 else None)(ui.find_all(name="designStripItem")), 5, "three designs in the strip")
    ui.eq([i.property("title") for i in items], ["Wallet base", "Wallet slider", "Wallet cascade"], "in the order they were made")
    ui.settle(800)
    ui.shot("open-conv-strip")
    for pid, name in ((S["a"], "Wallet base"), (S["b"], "Wallet slider"), (S["c"], "Wallet cascade")):
        it = next(i for i in ui.find_all(name="designStripItem") if i.property("title") == name)
        ui.click(it)
        ui.wait_until(lambda: ui.store.get("pid") == pid and ui.js("!!Store.data && Store.data.project.id === %r" % pid), 10, f"{name} to open")
        ui.eq(ui.store.get("convId"), S["three"], "the conversation stays open")


def journey_follow_never_hijacks(ui):
    toasts_gone(ui)
    ui.run_js("Store.select(Store.data.recipe.features[0].id)")        # the person is working on this design
    ui.check(ui.js("Store.steered") is True, "working on the open design")
    here = ui.store.get("pid")
    ui.run_js("Store.follow({ kind: 'commit', project: %r, by: 'Codex', text: 'r02', ts: Date.now() / 1000 })" % S["a"])
    ui.wait_until(lambda: ui.exists("agentElsewhere"), 5, "the agent named, not followed")
    ui.settle(1500)
    ui.eq(ui.store.get("pid"), here, "the view stayed on the design being worked on")
    ui.check(ui.sees("Codex is working on Wallet base", "agentElsewhere"), "says which design")
    ui.shot("open-conv-agent-elsewhere")
    ui.click("agentElsewhereShow")
    ui.wait_until(lambda: ui.store.get("pid") == S["a"], 10, "Show opens it")


def journey_conversation_with_no_design(ui):
    toasts_gone(ui)
    open_from_home(ui, S["none"])
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the conversation's own state")
    ui.wait_until(lambda: ui.sees("No design yet", "designingCaption"), 5, "No design yet")
    ui.check(not ui.exists("homeTitle"), "never the Home question")
    ui.item("designingContinue")
    ui.settle(600)
    ui.shot("open-conv-no-design")
    # its design moved to the trash: said, not hidden
    ui.api("/projects/" + S["b"] + "/delete", {})
    S["trashed"] = conv(ui, "A slider on its own", [S["b"]], S["b"])
    ui.run_js("Store.reloadStudio(); Store.loadConvs()")
    ui.settle(500)
    open_from_home(ui, S["trashed"])
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "no live design")
    ui.wait_until(lambda: ui.sees("is in the trash"), 5, "the trashed design named")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def journey_talk_takes_every_file_and_links(ui):
    filters = " ".join(ui.item("talk").property("attachFilters"))
    for ext in ("*.3mf", "*.obj", "*.step", "*.stl", "*.pdf", "*.png"):
        ui.check(ext in filters, f"the attach dialog lists {ext}: {filters}")
    # a file link pasted into Talk is fetched and becomes an attachment chip (a loopback server stands in for the web)
    root = Path(os.environ["FORM_UITEST_TMP"]) / "web"
    root.mkdir(exist_ok=True)
    (root / "bracket.stl").write_text("solid b\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
                                      "endloop\nendfacet\nendsolid b\n", encoding="utf-8")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: _Quiet(*a, directory=str(root), **k))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ui.run_js("Store.newChat()")
        ui.settle(300)
        url = "http://127.0.0.1:%d/bracket.stl" % srv.server_address[1]
        ui.run_js("Bridge.copy(%r)" % url)
        ui.click("composer")
        ui.key("Ctrl+V")
        chip = ui.wait_until(lambda: ui.find(name="attachChip"), 20, "the fetched file as an attachment chip")
        ui.check(ui.sees("bracket.stl", chip), "the chip names the file")
        ui.eq(ui.js("Store.chatAttach.length"), 1, "attached, not typed")
        ui.shot("open-conv-pasted-link")
    finally:
        srv.shutdown()
    ui.no_warnings()
