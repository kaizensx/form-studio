"""A provider added by its address, and a model menu with hundreds of models. A stand-in server
(tests/fixtures/fake_provider.py) plays an OpenAI-compatible gateway with 240 models from several vendors; Settings ›
Agents › Add a provider… detects it, shows what it found before saving, and saves it. In the model menu it is under
Your providers; with nothing used yet it has no Default, so the first message asks for a model: the search narrows
the list, ↓ and Return pick, and the message goes out with that model. Reopened, the menu pins it under Recent and
names it as the Default. A wrong address says so before anything is saved. No model is called and nothing leaves
this computer."""
import os
import sys
from pathlib import Path

DATA = "fresh"
ROOT = Path(__file__).resolve().parents[2]

VENDORS = [("acme", "Acme"), ("globex", "Globex"), ("initech", "Initech"), ("umbrella", "Umbrella"), ("hooli", "Hooli"), ("stark", "Stark")]


def models():
    out = []
    for vi, (slug, name) in enumerate(VENDORS):
        for i in range(40):
            mid = f"{slug}/{['coder', 'chat', 'vision', 'mini'][i % 4]}-{i // 4 + 1}"
            out.append({"id": mid, "name": f"{name}: {mid.split('/')[1].replace('-', ' ').title()}", "created": 1000 + vi * 100 + i,
                        "supported_parameters": ["tools"] if i % 7 else ["temperature"],
                        "pricing": {"prompt": "0" if i % 9 == 0 else "0.000001", "completion": "0" if i % 9 == 0 else "0.000002"},
                        "architecture": {"input_modalities": ["text", "image"] if i % 4 == 2 else ["text"]}})
        out.append({"id": f"{slug}/coder-1:batch", "name": f"{name}: Coder 1 (batch)", "supported_parameters": ["tools"]})
    return out


def run(ui):
    sys.path.insert(0, str(ROOT))
    from tests.fixtures.fake_provider import FakeProvider
    srv = FakeProvider(models=models(), key="sk-gateway-test", strict=True, script=[
        {"text": "Hello from the gateway. Looking at Form Studio first.", "tools": [("form_overview", {})]},
        {"text": "Form Studio has recipes for docks, hooks and more."}])
    try:
        os.environ["PYTHONPATH"] = str(ROOT)        # the MCP server the API agent starts imports this checkout
        ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")

        # ── a wrong address is said plainly, before anything is saved ──
        ui.run_js('Store.openSettings("chat")')
        ui.click(ui.item("addProvider", timeout=10))
        ui.fill("providerUrl", srv.root.rsplit(":", 1)[0] + ":9")
        ui.click("providerCheck")
        ui.wait_until(lambda: ui.sees("Could not connect"), 20, "the connection error")
        ui.check(ui.find(name="providerSave") is None or not ui.find(name="providerSave").property("visible"), "nothing to save")
        ui.shot("providers-error")

        # ── the right one: detected, shown, saved ──
        ui.fill("providerUrl", srv.root)                    # the bare address: /v1 is found by itself
        ui.fill("providerKey", "sk-gateway-test")
        ui.fill("providerName", "Studio gateway")
        ui.click("providerCheck")
        ui.wait_until(lambda: ui.sees("Connected: OpenAI-compatible, 240 models, tools supported by 204 of 240"), 30, "the detection")
        ui.check(ui.sees(srv.root + "/v1", within=None) or any(srv.root + "/v1" in t for t in ui.texts()), "the base URL it found")
        ui.settle(300)
        ui.shot("providers-detected")
        ui.click("providerSave")
        ui.wait_until(lambda: ui.find(name="providerRow") is not None, 20, "the saved provider")
        ui.wait_until(lambda: ui.js("(Store.agentInfo('custom-studio-gateway') || {}).available === true"), 20, "the agent")
        ui.check(not any("sk-gateway-test" in t for t in ui.texts()), "the key is never shown")
        ui.scroll_to(ui.find(name="providerRow"))
        ui.settle(400)
        ui.shot("providers-settings")
        ui.key("Escape")
        ui.settle(300)

        # ── the model menu: no Default yet, so the first message asks for a model ──
        ui.click("modelChip")
        ui.expect("Your providers", timeout=5)
        ui.click(ui.item("pickAgent_custom-studio-gateway", timeout=5))
        ui.wait_until(lambda: ui.store.get("chatAgent") == "custom-studio-gateway", 5, "the provider to be chosen")
        ui.eq(ui.store.get("chatModel"), "", "no model chosen for the person")
        ui.expect("has no default model yet", timeout=5)
        ui.settle(300)
        ui.shot("picker-vendors")
        ui.key("Escape")
        ui.settle(250)
        ui.check(ui.js("Store.modelShort(Store.chatAgent, Store.chatModel)") == "Choose a model", "the chip says so")
        ui.click("composer")
        ui.type("Hello gateway")
        ui.key("Return")
        ui.wait_until(lambda: ui.find(name="modelSearch") is not None, 5, "the menu to open for the pick")
        ui.click("modelSearch")
        ui.type("globex vision")
        ui.wait_until(lambda: ui.find(name="modelRow_globex/vision-1") is not None, 5, "the search to narrow the list")
        ui.check(ui.find(name="modelRow_acme/vision-1") is None, "other vendors are filtered out")
        ui.check(ui.find(name="modelRow_globex/coder-1:batch") is None, "batch variants are not offered")
        ui.shot("picker-search")
        ui.key("Down")
        ui.key("Down")
        ui.key("Return")
        ui.wait_until(lambda: ui.store.get("chatModel") not in ("", "default"), 5, "the model to be picked")
        picked = ui.store.get("chatModel")
        ui.check(picked.startswith("globex/vision-"), picked)
        ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("recipes for docks"), 240, "the reply")    # the tool server loads the CAD kernel first: slow on Windows runners
        ui.eq(srv.requests[0]["model"], picked, "the waiting message went out with the model picked")
        ui.check(any(m["role"] == "tool" for m in srv.requests[1]["messages"]), "through Form Studio's real tools")
        ui.settle(300)

        # ── reopened: Recent on top, and it is now the provider's Default ──
        ui.run_js("Store.refreshAgents()")
        ui.wait_until(lambda: ui.js("((Store.agentInfo('custom-studio-gateway') || {}).recent || [])[0] === '%s'" % picked), 10, "recent")
        ui.click("modelChip")
        ui.wait_until(lambda: ui.sees("Recent"), 5, "the Recent section")
        ui.check(any(t.startswith("Default · ") for t in ui.texts()), "Default names the model last used")
        ui.settle(300)
        ui.shot("picker-recent")
        ui.key("Escape")
    finally:
        srv.close()
