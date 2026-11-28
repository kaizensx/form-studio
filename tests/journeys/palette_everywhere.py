"""The palette's previews and "Tab: search everywhere": a row shows its own figure at the right edge (a feature's
value, another design's revision), Tab widens the search to what was said inside the conversations (the engine reads
every message and answers with the line around the words) and to every setting by name, and Tab again goes back."""
from _lib import make

DATA = "fresh"


def shown(ui):
    """The rows on screen, headers apart: id, group, the name as shown, its quiet line and the figure at its right edge."""
    v = ui.item("palette").property("listed")
    return list(v.toVariant() if hasattr(v, "toVariant") else v)


def open_palette(ui, words):
    if not ui.store.get("paletteOpen"):
        ui.run_js("Store.paletteOpen = true")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "the palette")
    ui.settle(200)
    ui.clear()
    ui.type(words)
    ui.settle(350)


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    other = make(ui, "hook", "Zebra hook", open=False)
    pid = make(ui, "shelf_bracket", "Motor mount")
    # two messages in one conversation: its title comes from the first, the word looked for is only in the second
    job = ui.api("/conversations/send", {"message": "Would a larger radius at the root move the peak stress?", "project": pid, "agent": "fake"})
    cid = job["conversation"]
    ui.wait_until(lambda: ui.api("/conversations/" + cid)["state"] == "idle", 30, "the first answer")
    ui.api("/conversations/" + cid + "/send", {"message": "Then make the quokka pocket two millimetres deeper."})
    ui.wait_until(lambda: ui.api("/conversations/" + cid)["state"] == "idle", 30, "the second answer")
    title = ui.api("/conversations/" + cid)["title"]
    ui.check("quokka" not in title.lower(), f"the word is not in the title: {title}")
    ui.run_js("Store.newChat()")                       # the conversation is not the one in front
    ui.settle(300)

    # ── previews: a feature of the open design with its value, another design with its revision ──
    feat = ui.js("Store.recipe.features[0]")
    open_palette(ui, feat["label"])
    hit = [r for r in shown(ui) if r["id"] == "feature." + feat["id"]]
    ui.check(hit and hit[0]["g"] == "In design" and hit[0]["text"].startswith("01 "), f"the feature is a row of the open design: {hit}")
    ui.check(ui.sees("In Motor mount", ui.item("palette")), "under the design's own name")
    ui.check(any(v.property("text") == hit[0]["value"] and hit[0]["value"] for v in ui.find_all(name="paletteValue")),
             f"its value stands at the row's right edge: {hit[0]['value']!r}")
    ui.shot("palette-feature-preview")
    open_palette(ui, "Zebra hook")
    hit = [r for r in shown(ui) if r["id"] == "p." + other]
    ui.check(hit and hit[0]["value"].startswith("r01"), f"another design previews its revision and checks: {hit}")

    # ── Tab: search everywhere ──
    open_palette(ui, "quokka")
    ui.eq(shown(ui), [], "the word is in no command, design or title")
    ui.expect("search everywhere", within=ui.item("paletteTab"))
    ui.key("Tab")
    ui.wait_until(lambda: ui.item("palette").property("everywhere") is True, 3, "everywhere")
    ui.wait_until(lambda: [r for r in shown(ui) if r["id"] == "found." + cid], 10, "the conversation that said it")
    row = [r for r in shown(ui) if r["id"] == "found." + cid][0]
    ui.check("quokka pocket" in row["text"] and row["g"] == "Everywhere", f"the row quotes the line around the word: {row['text']}")
    ui.check(title in row["hint"], f"and names the conversation: {row['hint']}")
    ui.check("You said" not in row["text"], f"your own message is quoted, not the reply that repeats it: {row['text']}")
    ui.check(ui.sees("Everywhere", ui.item("paletteScope")), "the scope says Everywhere")
    ui.settle(300)
    ui.shot("palette-everywhere")
    # a setting by name opens its page
    ui.clear()
    ui.type("spending cap")
    ui.wait_until(lambda: [r for r in shown(ui) if r["id"].startswith("set.")], 5, "a setting by name")
    ui.check(any("Settings › Agents & models › " in r["text"] for r in shown(ui)), f"the row says where the setting is: {[r['text'] for r in shown(ui)]}")
    # Tab again: back to the commands and the open design
    ui.key("Tab")
    ui.wait_until(lambda: ui.item("palette").property("everywhere") is False, 3, "back")
    ui.check(not [r for r in shown(ui) if r["g"] == "Everywhere"], "no Everywhere rows outside it")
    # Enter on the quoted line opens that conversation
    ui.clear()
    ui.type("quokka")
    ui.key("Tab")
    ui.wait_until(lambda: "quokka" in str(ui.item("palette").property("selText")), 10, "the quoted line to be the one the keys are on")
    ui.key("Return")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is False and ui.store.get("convId") == cid, 10, "the conversation to open")
    ui.check(ui.js("Store.talkOpen") is True, "in the conversation column")
