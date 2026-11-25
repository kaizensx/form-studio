"""The item tree dump (form/app/uitest.py tree()): what is on screen as data, never a password field's text.

journey_tree: Settings › Chat, a provider key typed into its password field, then the dump: the key is nowhere in it
(not on the field, not on the Field around it), the field is there with its bounds, the source file and the focus.
deliberate_failure is not a journey: tests/test_ui_journeys.py runs it alone to see that a failure writes the tree
beside its screenshot.
"""
import json

KEY = "sk-tree-secret-4242"


def _all(n):
    yield n
    for c in n.get("children") or []:
        yield from _all(c)


def journey_tree(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.run_js('Store.openSettings("chat")')
    ui.click(ui.item("addProvider", timeout=10))
    ui.fill("providerKey", KEY)
    out = ui.out / "ui-tree.json"
    t = ui.tree(out)
    text = out.read_text(encoding="utf-8")
    ui.check(KEY not in text and KEY not in json.dumps(t), "the password field's text is not in the dump")
    nodes = list(_all(t["root"]))
    key = [n for n in nodes if n["objectName"] == "providerKey"]
    ui.check(key, "the key field is in the tree")
    k = key[0]
    ui.eq(len(k["bounds"]), 4, "bounds are x, y, w, h")
    ui.check(k["bounds"][2] > 0 and k["bounds"][3] > 0, "the field has a size")
    ui.check(k.get("source", "").endswith(".qml"), f"the QML file is named: {k.get('source')}")
    ui.check(any(n.get("activeFocus") for n in _all(k)), "the focused input is marked")
    ui.check(any("••••••••" == (n.get("text") or {}).get("text") for n in _all(k)), "the field's text is masked")
    ui.check(all(len(v) <= t["max_text"] for n in nodes for v in (n.get("text") or {}).values()), "texts are capped")
    ui.check(any((n.get("text") or {}).get("text") for n in nodes), "visible texts are there")
    ui.check(all(n.get("enabled") in (True, False) for n in nodes), "enabled on every node")
    ui.key("Escape")


def deliberate_failure(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.check(False, "this journey fails on purpose")
