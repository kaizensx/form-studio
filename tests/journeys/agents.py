"""API agents in the app: a local model server is found (a stand-in, tests/fixtures/fake_provider.py, on a free port),
picked in the model menu, and answers through Form Studio's real tools with steps, follow-ups and a token count on
the footer. A failed reply offers "Try another model…", which resends with the model picked. Settings › Agents lists
it under Local models. No model is called and nothing leaves this computer.

The test suite sets FORM_UITEST_API_AGENTS=1 (the API agents next to the stand-in CLI agent)."""
import os
import sys
from pathlib import Path

DATA = "fresh"
ROOT = Path(__file__).resolve().parents[2]


def send(ui, text):
    ui.click("composer")
    ui.type(text)
    ui.key("Return")


def run(ui):
    sys.path.insert(0, str(ROOT))
    from tests.fixtures.fake_provider import FakeProvider
    srv = FakeProvider(models=[{"id": "tool-model:8b"}, {"id": "other-model:3b"}], script=[
        {"text": "Looking at what Form Studio has.", "tools": [("form_overview", {})]},
        {"tools": [("suggest_replies", {"options": ["Make a hook", "Show the recipes"]})]},
        {"text": "Form Studio has built-in recipes for docks, hooks and more.",
         "usage": {"prompt_tokens": 2400, "completion_tokens": 120}},
        {"status": 404, "error": "model 'tool-model:8b' not found"},
        {"text": "Answered by the other model."}])
    try:
        os.environ["OLLAMA_HOST"] = srv.url.rsplit("/v1", 1)[0]
        os.environ["PYTHONPATH"] = str(ROOT)        # the MCP server the API agent starts imports this checkout
        ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
        ui.run_js("Store.refreshAgents()")
        ui.wait_until(lambda: ui.js("(Store.agentInfo('ollama') || {}).available === true"), 20, "the local server to be found")

        # ── pick it in the model menu: grouped under Local models ──
        ui.click("modelChip")
        ui.expect("Local models", timeout=5)
        ui.click(ui.item("pickAgent_ollama", timeout=5))
        ui.wait_until(lambda: ui.store.get("chatAgent") == "ollama", 5, "Ollama to be chosen")
        ui.expect("Default · tool-model:8b", timeout=5)
        ui.shot("agents-picker")
        ui.click_text("other-model:3b")                 # picking a model closes the menu
        ui.wait_until(lambda: ui.store.get("chatModel") == "other-model:3b", 5, "the model to change")
        ui.wait_until(lambda: ui.find(name="pickAgent_ollama") is None, 5, "the menu to close")
        ui.click("modelChip")
        ui.click_text("Default · tool-model:8b")
        ui.wait_until(lambda: ui.store.get("chatModel") == "default", 5, "back to the default model")
        ui.settle(400)
        ui.check(ui.find(name="pickAgent_ollama") is None, "the menu is closed")

        # ── a reply through the real tools ──
        send(ui, "What can you make?")
        # generous: the agent's tool server starts its own CAD kernel, which a software-rendered Windows runner
        # imports in well over a minute while the app's kernel loads too
        ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("built-in recipes for docks"), 240, "the reply")
        ui.check(ui.find(name="stepGroup") is not None, "the tool call is shown as a step")
        ui.wait_until(lambda: len(ui.find_all(name="suggestChip")) == 2, 10, "the two follow-ups")
        ui.check(ui.sees("tokens", within=None), "the footer counts tokens when the provider reports no price")
        tool = next(m for m in srv.requests[1]["messages"] if m["role"] == "tool")
        ui.check("recipes" in tool["content"], "the model received the real tool output")
        ui.settle(300)
        ui.shot("agents-reply")

        # ── a failure says what happened and offers another model ──
        send(ui, "Again please")
        ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.find(text="Try another model…") is not None, 240,
                      "the error with its actions")
        ui.check(any("no model “tool-model:8b” loaded" in t for t in ui.texts()), "the error names the model problem")
        ui.shot("agents-error")
        ui.click_text("Try another model…")
        ui.expect("your last message is sent again", timeout=5)
        ui.click_text("other-model:3b")
        ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("Answered by the other model."), 240, "the resent reply")
        ui.eq(srv.requests[-1]["model"], "other-model:3b", "sent again with the model picked")

        # ── Settings › Agents lists it ──
        ui.run_js('Store.openSettings("chat")')
        ui.wait_until(lambda: ui.find(name="localRow") is not None, 10, "the local models section")
        ui.expect("Local models")
        ui.shot("agents-settings")
        ui.key("Escape")
    finally:
        srv.close()
