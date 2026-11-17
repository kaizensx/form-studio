"""The app shell's contract, checked without starting Qt: the design system's tokens and components exist and are
registered, every sheet is a real file on the sheet system, and no Store function other screens rely on was removed.
"""
import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "form" / "app" / "qml" / "Form"

# every function Store.qml had before the shell redesign; other screens call these
STORE_FUNCTIONS = [
    "_addMeasure", "_chatTick", "_installTick", "_loginTick", "_morphStep", "_setupTick", "_showScrub", "_take",
    "_tick", "_useDefaults", "addExample", "agentInfo", "analysisCheck", "analysisLabel", "applySetup",
    "applyStageView", "askAbout", "askImportPart", "askReview", "asmFor", "attachFiles", "attachmentUrl", "boot",
    "bootSetup", "branchFrom", "cancelClaudeLogin", "cancelInstall", "checkSetup", "checkSoftware", "checkUpdates",
    "checkout", "clearMeasures", "closeWelcome", "commit", "compareWith", "convTitle", "copyDims", "create",
    "deleteConv", "deleteVariant", "discard", "dropAttachment", "dropMeasure", "dropToast", "endScrub", "fail",
    "featureById", "featureDims", "featureText", "file", "findOrientation", "follow", "frameSelection", "get",
    "home", "hover", "importArchive", "importPart", "installSoftware", "installStep", "lastUserText", "loadConfig",
    "loadConvs", "loadDraft", "loadRev", "marker", "measureClick", "modelLabel", "newChat", "noteAct", "open",
    "openConv", "openIn", "openSettings", "openSetup", "openSheet", "overallText", "pget", "pick", "pinConv",
    "playMorph", "post", "ppost", "promoteVariant", "recallChat", "refresh", "reloadStudio", "renameConv",
    "resetView", "retryChat", "reviewPrompt", "revision", "run", "runPreview", "saveConfig", "saveVariant",
    "sectionNow", "select", "send", "sendClaudeCode", "setAck", "setAnalysis", "setAsmMode", "setChatChoice",
    "setExplode", "setInstallPick", "setLayer", "setMeasuring", "setOnboardStep", "setParam", "setPick", "setPose",
    "setProv", "setSection", "setStage", "setView", "settings", "setupItem", "showAll", "showHead", "showLayers",
    "showRev", "simulate", "softwareItem", "spec", "startClaudeLogin", "stopChat", "stopMorph", "thumb", "toast",
    "toggleCompanions", "toggleDims", "toggleHidden", "toggleSection", "track", "upload", "who",
]


def read(name: str) -> str:
    return (QML / name).read_text(encoding="utf-8")


class DesignSystem(unittest.TestCase):
    def test_theme_has_the_tokens_the_shell_uses(self):
        theme = read("Theme.qml")
        for token in ("well", "plate", "plate1", "plate2", "plate3", "plate4", "ink", "ink2", "ink3", "ink4", "rule", "rule2",
                      "rule3", "washHover", "washPress", "washOn", "scrim", "focus", "datum", "datumHi", "rXs", "rSm", "rMd",
                      "rLg", "rXl", "wBody", "wMedium", "wSemi", "wBold", "hSm", "hMd", "hLg", "sheetS", "sheetM", "sheetL",
                      "sheetXl", "press", "pop", "fast", "base", "exit", "slow", "stagger", "easeOut", "easeMove",
                      "easeDrawer", "reduced"):
            self.assertRegex(theme, r"property \w+ %s\b" % token, token)
        for fn in ("move", "shift", "from", "alpha", "evidence", "keyCaps", "keyText"):
            self.assertIn("function %s(" % fn, theme, fn)

    def test_reduced_motion_is_read_once_from_the_bridge(self):
        self.assertIn("readonly property bool reduced: Bridge.reducedMotion", read("Theme.qml"))
        bridge = (QML.parent.parent / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("reducedMotion = Property(bool", bridge)
        self.assertIn("FORM_REDUCED_MOTION", bridge)

    def test_components_exist_and_are_registered(self):
        qmldir = read("qmldir")
        for c in ("Btn", "Txt", "Field", "Area", "Tag", "Cap", "Seg", "Sec", "KV", "Delta", "Note", "Pick", "Beam", "Check",
                  "Tip", "Icon", "Toggle", "Tabs", "Pop", "PopMenu", "Kbd", "Spinner", "Shadow", "FocusRing", "Glide", "Tint",
                  "Lightbox", "MacMenu", "SheetHost", "Palette", "Toasts", "TopBar", "Home", "Talk"):
            self.assertTrue((QML / (c + ".qml")).exists(), c)
            self.assertRegex(qmldir, r"(?m)^%s 1\.0 %s\.qml$" % (c, c), c + " is not in qmldir")

    def test_controls_keep_their_old_properties(self):
        for name, props in (("Btn.qml", ("text", "icon", "kind", "small", "active", "tip")),
                            ("Field.qml", ("placeholder", "numeric", "unit")),
                            ("Area.qml", ("placeholder", "submitOnEnter", "minLines")),
                            ("Pick.qml", ("model", "value")), ("Seg.qml", ("model", "value")),
                            ("Check.qml", ("checked",)), ("Tip.qml", ("text", "show")), ("Tag.qml", ("text", "kind"))):
            src = read(name)
            for p in props:
                self.assertRegex(src, r"property \w+ %s\b" % p, "%s lost %s" % (name, p))
        self.assertIn("signal clicked()", read("Btn.qml"))
        self.assertIn("property bool busy", read("Btn.qml"))
        self.assertIn("property string error", read("Field.qml"))

    def test_shell_files_do_not_hard_code_colours(self):
        for name in ("Btn.qml", "Field.qml", "Pick.qml", "Seg.qml", "Tabs.qml", "Toggle.qml", "Check.qml", "Tip.qml",
                     "Pop.qml", "PopMenu.qml", "Toasts.qml", "SheetHost.qml", "TopBar.qml", "StatusChips.qml", "Home.qml",
                     "Palette.qml", "Lightbox.qml", "Talk.qml", "ConversationList.qml", "AboutSheet.qml"):
            self.assertIsNone(re.search(r'"#[0-9a-fA-F]{6}"', read(name)), name + " hard-codes a colour")


class Sheets(unittest.TestCase):
    def files(self):
        m = re.search(r"readonly property var files: \(\{(.*?)\}\)", read("SheetHost.qml"), re.S)
        return dict(re.findall(r'"?(\w+)"?: "(\w+\.qml)"', m.group(1)))

    def test_every_registered_sheet_is_a_file_with_a_title(self):
        files = self.files()
        for kind in ("new", "alternatives", "photo", "ring", "setup", "settings", "update", "slicer", "render", "variants",
                     "share", "shortcuts", "about"):
            self.assertIn(kind, files)
        for kind, name in files.items():
            self.assertTrue((QML / name).exists(), name)
            self.assertRegex(read(name), r"property string title\b", name)

    def test_sheets_use_the_width_tiers(self):
        for name in set(self.files().values()):
            m = re.search(r"property int sheetWidth: ([^\n;]+)", read(name))
            if m:
                self.assertRegex(m.group(1), r"Theme\.sheet(S|M|L|Xl)\b", name + " invents a sheet width")

    def test_no_sheet_hand_rolls_its_bottom_padding(self):
        for name in set(self.files().values()):
            self.assertNotIn("bottomPadding: 20", read(name), name)


class Store(unittest.TestCase):
    def test_no_store_function_was_removed(self):
        have = set(re.findall(r"(?m)^    function (\w+)", read("Store.qml")))
        missing = [f for f in STORE_FUNCTIONS if f not in have]
        self.assertEqual(missing, [])

    def test_project_housekeeping_calls_the_engine_routes(self):
        store = read("Store.qml")
        for fn, route in (("renameProject", "/rename"), ("duplicateProject", "/duplicate"), ("deleteProject", "/delete")):
            self.assertRegex(store, r"function %s\(" % fn)
            self.assertIn('"%s"' % route, store)

    def test_palette_reaches_every_tool(self):
        pal = read("Palette.qml")
        for needle in ("Store.setAnalysis(", "Store.setMeasuring(", "Store.simulate(", 'openSheet("variants")', 'openSheet("share")',
                       "Store.timelineOpen", "Store.findOrientation(", "Store.openSetup(", "Store.openSettings(", "Store.newChat(",
                       "Store.setChatChoice(", 'openSheet("about")', 'openSheet("shortcuts")', "Store.openConv("):
            self.assertIn(needle, pal, needle)
        self.assertNotIn("Behavior on", pal, "the palette does not animate: it is used all day")


if __name__ == "__main__":
    unittest.main()
