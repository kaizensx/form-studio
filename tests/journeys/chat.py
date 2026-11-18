"""Conversations with a stand-in agent CLI (tests/fixtures/fake_agent.py): send, streamed text, grouped steps,
stop, new conversation, rename, pin, delete, the model picker, an attachment. No model is called."""
import struct
import zlib

DATA = "fresh"


def convs(ui):
    return ui.api("/conversations")["conversations"]


def send(ui, text):
    ui.click("composer")
    ui.type(text)
    ui.eq(ui.item("composer").property("text"), text, "typing reaches the composer")
    ui.key("Return")


def png(path):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x60\x80\xa0" * 8 for _ in range(8))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.wait_until(lambda: ui.js("Store.chat.available && Store.chatReady"), 20, "the stand-in agent to be connected")
    ui.eq(ui.store.get("chatAgent"), "fake")
    ui.expect("Test agent · Default")

    # ── send: the reply streams in and is saved ──
    send(ui, "Hello there")
    ui.wait_until(lambda: ui.store.get("chatBusy") is True or len(convs(ui)) == 1, 5, "the message to be sent")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("You said: Hello there"), 30, "the reply on screen")
    c = convs(ui)
    ui.eq(len(c), 1, "one saved conversation")
    ui.eq((c[0]["messages"], c[0]["agent"]), (1, "fake"))
    ui.eq(ui.item("composer").property("text"), "", "the composer is empty after sending")
    ui.settle(300)
    ui.shot("chat-reply")


    # ── tool steps are grouped; the project the agent made is followed ──
    send(ui, "make a part and render it")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("You said: make a part and render it"), 30, "the second reply")
    groups = ui.wait_until(lambda: ui.find_all(name="stepGroup"), 5, "the agent's steps as a group")
    g = groups[-1]
    ui.check(len(ui.js("Store.chatItems.filter(function (i) { return i.t === 'tool' })")) >= 2, "two tool calls were recorded")
    n_closed = len(ui.texts(g))
    ui.click(g, 0.3, 12.0 / max(24.0, g.height()))
    ui.wait_until(lambda: g.property("expanded") is True, 3, "the step group to unfold")
    ui.settle(300)
    ui.check(len(ui.texts(g)) > n_closed, "the unfolded group lists its steps")
    ui.shot("chat-steps")

    # ── stop a reply that is still being written ──
    send(ui, "slow please")
    ui.wait_until(lambda: ui.store.get("chatBusy") is True and ui.sees("Working"), 20, "the slow reply to start streaming")
    ui.shot("chat-streaming")
    ui.click("sendBtn")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 20, "Stop to end the reply")
    first = [x for x in convs(ui)][0]
    ui.check(first["state"] != "running", f"the engine stopped the run: {first['state']}")
    first_id = ui.store.get("convId")

    # ── a new conversation, with another model ──
    ui.key("Ctrl+Shift+O")
    ui.wait_until(lambda: ui.store.get("convId") == "", 3, "a new conversation with the shortcut")
    ui.click("modelChip")
    ui.settle(300)
    ui.click_text("Small")
    ui.wait_until(lambda: ui.store.get("chatModel") == "small", 3, "the model picker to change the model")
    ui.expect("Test agent · Small")
    ui.settle(300)
    send(ui, "Second conversation")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("You said: Second conversation"), 30, "the reply in the new conversation")
    ui.wait_until(lambda: len(convs(ui)) == 2, 5, "two saved conversations")
    second_id = ui.store.get("convId")
    second = [x for x in convs(ui) if x["id"] == second_id][0]
    ui.eq((second["model"], second["resolved_model"]), ("small", "fake-small-1"), "the chosen model was used")
    # ── a reply in Markdown: lists sit on the text column, not 40 px in (in the conversation that is deleted later,
    # so the long reply does not push the first one out of the feed) ──
    send(ui, "outline the plan")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("You said: outline the plan"), 30, "the Markdown reply")
    md = [m for m in ui.find_all(name="replyText") if "outline the plan" in m.property("text")][-1]
    rich = md.property("text")
    ui.check("<ul" not in rich and "<ol" not in rich and "<li" not in rich, "lists are not left to Qt's list layout")
    ui.check(rich.count("<table") >= 6, "list items, the code block and the table are laid out as tables")
    ui.check(ui.sees("a nested point", md) and ui.sees("form.run()", md) and ui.sees("<b>bold</b>", md), "the words of the reply are all there")
    raw = [i for i in ui.store.get("chatItems") if i["t"] == "text"][-1]["text"]
    ui.check("1. First step" in raw and "<table" not in raw, "the saved reply (what Copy copies) is still the Markdown")
    ui.check(md.property("contentWidth") <= md.width() + 1, "the reply stays inside the column")
    ui.settle(300)
    ui.shot("chat-markdown")

    # ── attach a file: the chip shows, the agent gets it ──
    pic = png(ui.files / "sketch.png")
    ui.pick_file(pic)
    ui.click_text("Attach a photo, sketch, PDF, or a STEP/STL part. You can also drop files here.")
    chip = ui.wait_until(lambda: ui.find(name="attachChip"), 10, "the attachment chip")
    ui.check(ui.sees("sketch.png", chip), "the chip names the file")
    ui.eq(len(ui.store.get("chatAttach")), 1)
    ui.settle(300)
    ui.shot("chat-attachment")
    send(ui, "what is in the sketch")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("You said: what is in the sketch"), 30, "the reply to the message with a file")
    ui.eq(ui.store.get("chatAttach"), [], "the attachment went with the message")
    att = [i for i in ui.store.get("chatItems") if i["t"] == "user" and i.get("attachments")]
    ui.check(att and att[-1]["attachments"][0]["name"] == "sketch.png", "the sent message carries the attachment")

    # ── the list: open, rename, pin, delete ──
    ui.click("convSwitch")
    ui.settle(350)
    rows = ui.wait_until(lambda: len(ui.find_all(name="convRow")) >= 2 and ui.find_all(name="convRow"), 5, "the conversation list")
    row = [r for r in rows if ui.sees("Hello there", r)][0]
    ui.hover(row)
    ui.click(ui.item("convRename", within=row))
    ui.wait_until(lambda: ui.find(name="convRenameField", within=row) is not None, 3, "the rename field")
    ui.clear()
    ui.type("Dock ideas")
    ui.key("Return")
    ui.wait_until(lambda: any(x["title"] == "Dock ideas" for x in convs(ui)), 5, "the new title in the engine")
    row = ui.wait_until(lambda: next((r for r in ui.find_all(name="convRow") if ui.sees("Dock ideas", r)), None), 5, "the renamed row")
    ui.hover(row)
    ui.click(ui.item("convPin", within=row))
    ui.wait_until(lambda: [x for x in convs(ui) if x["id"] == first_id][0]["pinned"] is True, 5, "the pin in the engine")
    ui.wait_until(lambda: convs(ui)[0]["id"] == first_id, 3, "a pinned conversation lists first")
    ui.settle(300)
    ui.shot("chat-list")
    # open the pinned one by clicking it
    row = ui.wait_until(lambda: next((r for r in ui.find_all(name="convRow") if ui.sees("Dock ideas", r)), None), 5, "the pinned row")
    ui.click(row, 0.3, 0.5)
    ui.wait_until(lambda: ui.store.get("convId") == first_id, 5, "the conversation to open")
    ui.expect("You said: Hello there")
    # delete the other one
    ui.click("convSwitch")
    ui.settle(350)
    row = ui.wait_until(lambda: next((r for r in ui.find_all(name="convRow") if ui.sees("Second conversation", r)), None), 5, "the second row")
    for _ in range(5):                    # the delete button shows on hover; a pointer already resting there sends none
        ui.hover((4, 4))
        ui.settle(100)
        ui.hover(row)
        ui.settle(250)
        d = ui.find("convDelete", within=row)
        if d is not None and d.property("visible"):
            break
    ui.click(ui.item("convDelete", within=row))
    ui.click(ui.item("convDeleteYes", within=row))
    ui.wait_until(lambda: len(convs(ui)) == 1 and convs(ui)[0]["id"] == first_id, 5, "the conversation to be deleted in the engine")
    ui.key("Escape")
    ui.settle(300)
