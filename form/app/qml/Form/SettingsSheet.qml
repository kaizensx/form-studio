import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Settings: a navigation rail on the left, one page on the right.
//
//   General              appearance, what Form Studio is set up for, how designs are refined, the project folder
//   Agents & models      every way chat can reach a model, and the defaults for new conversations
//   Engines & software   the installer registry: installed or not, Install, and "Use in Form Studio" for each engine
//   Printing             only with the 3D printing capability: the default printer, the slicer, the plate
//   Other apps           where Blender, OpenSCAD and FreeCAD are, and what "Open in…" hands files to
//   Updates              update checks and the channel, the version you run
//   Advanced             limits and fallbacks, with the key each one has in studio.toml
//
// Every page has the same shape: a mono overline, a title and one line on what it holds, then titled cards of rows on
// thin glass. The rail's pages are capsule rows; one highlight glides to the page you are on. Rows that edit
// studio.toml collect in `edits` and are written by "Save changes": only the changed keys are rewritten, comments and
// other keys stay, and the previous file is kept as a backup next to it (form/config_edit.py). Things that apply at
// once say so and do not wait for Save: appearance, "Set up for" (form/capabilities.py: on installs what it needs,
// off hides it and never uninstalls), the default printer, and "Use in Form Studio".
// Open with Store.openSettings("general" | "printer" | "chat" | "apps" | "updates" | "advanced" | "software").
// The search in the rail finds rows on every page. The sheet lays out its own body (fillsBody, SheetHost.qml): the
// rail stays put and only the page scrolls.
Item {
    id: st
    property string title: "Settings"
    property int sheetWidth: Theme.sheetXl
    property int sheetHeight: 620
    property bool fillsBody: true
    implicitHeight: sheetHeight
    readonly property int railW: 224
    readonly property var sections: [
        { value: "general", text: "General", icon: "sliders_horizontal", group: "Studio",
          sub: "How Form Studio looks, what it is set up for and where your designs are kept." },
        { value: "chat", text: "Agents & models", icon: "bot", group: "Studio",
          sub: "Every way chat can reach a model: agent apps, provider APIs and models on this computer." },
        { value: "software", text: "Engines & software", icon: "package", group: "Studio",
          badge: Store.setupAttention && Store.setupAttention.length ? Store.setupAttention.length : 0,
          sub: "What Form Studio uses on this computer. Install what you want, then choose whether Form Studio uses it." }]
        .concat(Store.printOn ? [{ value: "printer", text: "Printing", icon: "printer", group: "Making",
          sub: "The printer the checks and slices use, and how parts are laid out on its bed." }] : [])
        .concat([
        { value: "apps", text: "Other apps", icon: "layout_grid", group: "Making",
          sub: "Where the apps Form Studio works with are, and what “Open in…” hands a file to." },
        { value: "updates", text: "Updates", icon: "refresh_cw", group: "System",
          sub: "How Form Studio finds out about a newer version. Nothing is downloaded or installed by itself." },
        { value: "advanced", text: "Advanced", icon: "wrench", group: "System",
          sub: "Limits and fallbacks. Each row shows its key in studio.toml." }])
    readonly property var tabNames: ({ general: "General", printer: "Printing", chat: "Agents & models", apps: "Other apps", updates: "Updates", advanced: "Advanced", software: "Engines & software" })
    readonly property var section: { for (var i = 0; i < sections.length; i++) if (sections[i].value === tab) return sections[i]; return sections[0] }
    readonly property bool onSoftware: tab === "software" && !searching      // the action bar installs; elsewhere it saves
    function accept() { if (!onSoftware && dirty > 0) save() }
    // the action bar: what is saved where on the left, the actions on the right
    property Component footerLeft: Txt { kind: "fine"; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; verticalAlignment: Text.AlignVCenter
        color: !st.onSoftware && st.cfg && st.cfg.env_overrides.length > 0 ? Theme.amber : Theme.ink3
        text: st.onSoftware ? (Store.installing ? "Installing. Each command is in the log." : Store.softwareChecking ? "Looking at what is installed…" : "Nothing is installed until you press Install. “Use in Form Studio” applies at once.")
            : !st.cfg ? ""
            : st.cfg.env_overrides.length > 0 ? "Set outside the file for this run: " + st.cfg.env_overrides.join(", ") + ". Those win."
            : (st.cfg.exists ? "Saved to " : "Will create ") + st.cfg.path_short + " · a backup is kept on every save" }
    property Component footer: Row { spacing: 8
        Btn { visible: !st.onSoftware && st.dirty > 0; kind: "quiet"; text: "Revert"; onClicked: { st.edits = ({}); st.rev++ } }
        Btn { visible: !st.onSoftware; kind: "primary"; icon: "check"; enabled: st.dirty > 0; keys: "Return"
            text: st.dirty ? "Save " + F.plural(st.dirty, "change") : "Saved"; onClicked: st.save() }
        Btn { visible: st.onSoftware && Store.installing; icon: "x"; text: "Cancel"; onClicked: Store.cancelInstall() }
        Btn { visible: st.onSoftware; icon: "refresh_cw"; text: "Check again"; busy: Store.softwareChecking; enabled: !Store.installing
            onClicked: { Store.checkSoftware(); Store.checkSetup() } }
        Btn { visible: st.onSoftware; kind: "primary"; icon: "download"; enabled: Store.installChosen.length > 0; busy: Store.installing
            text: Store.installing ? "Installing…" : Store.installChosen.length ? "Install " + Store.installChosen.length + " selected" : "Install selected"
            onClicked: Store.installSoftware() } }
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    property string tab: props.tab === "printer" && !Store.printOn ? "general" : (props.tab || "general")
    onTabChanged: pane.contentY = 0
    property string query: ""                  // Settings search: rows from every page whose label, help or key match
    property var edits: ({})                   // key → new value, not yet saved
    property int rev: 0                        // bumped on Revert and Save so the fields show the stored values again
    readonly property var cfg: Store.config
    readonly property int dirty: F.keys(edits).length
    readonly property bool searching: query.trim() !== ""
    function matches(r) { var q = query.trim().toLowerCase(); return (r.label + " " + (r.help || "") + " " + r.key + " " + (st.tabNames[r.tab] || "")).toLowerCase().indexOf(q) >= 0 }
    readonly property var shownRows: cfg ? cfg.settings.filter(function (r) { return !r.hidden && !(r.tab === "printer" && !Store.printOn) }) : []
    readonly property var found: searching ? shownRows.filter(st.matches) : []
    function rowsOf(tab, pick) { return shownRows.filter(function (r) { return r.tab === tab && (!pick || pick(r)) }) }
    function isDefaultsRow(r) { return ["chat.agent", "chat.model", "chat.effort", "chat.auto_effort"].indexOf(r.key) >= 0 }
    function dirtyIn(tab) { var n = 0; if (cfg) cfg.settings.forEach(function (r) { if (r.tab === tab && st.edits[r.key] !== undefined) n++ }); return n }
    function isDefault(r) { return st.same(st.current(r), r["default"]) }
    function rangeError(r, t) {
        if (t === "" || isNaN(Number(t))) return "A number"
        var v = Number(t)
        if ((r.min !== undefined && v < r.min) || (r.max !== undefined && v > r.max)) return "Between " + r.min + " and " + r.max + (r.unit ? " " + r.unit : "")
        return "" }
    function agentChoices() {
        return [{ value: "", text: "Automatic: the first one available" }].concat(Store.chatAgents.map(function (a) {
            return { value: a.id, text: a.label + (a.available ? "" : "  · not set up") } })) }
    function agentFor() { var id = st.edits["chat.agent"] !== undefined ? st.edits["chat.agent"] : (Store.chatDefault.agent || ""); return Store.agentInfo(id) }
    function modelChoices(v) {
        var a = st.agentFor(), out = (a && a.models ? a.models : []).map(function (m) { return { value: m.id, text: m.label || m.id } })
        if (!out.some(function (o) { return o.value === "default" })) out.unshift({ value: "default", text: "Default" })
        if (v && !out.some(function (o) { return o.value === v })) out.push({ value: v, text: v })
        return out }
    function effortChoices(v) {
        var a = st.agentFor(), e = a && a.efforts ? a.efforts : []
        var out = [{ value: "", text: "The agent's default" }].concat(e.map(function (x) { return { value: x, text: x } }))
        if (v && e.indexOf(v) < 0) out.push({ value: v, text: v })
        return out }
    Component.onCompleted: { if (!Store.config) Store.loadConfig(); if (!Store.software) Store.checkSoftware(); if (!Store.caps) Store.loadCaps(); st.loadKeys(); st.loadProviders()
        if (props.addProvider) st.editingProvider = null }

    // API keys: kept by Form Studio in a private file, never shown back; only "set" or "not set" comes from the engine
    property var keys: []
    function loadKeys() { Store.get("/secrets").then(function (r) { st.keys = r.keys }, function () {}) }
    function keyFor(name) { for (var i = 0; i < st.keys.length; i++) if (st.keys[i].name === name) return st.keys[i]; return null }
    function saveKey(name, value) {
        return Store.post("/secrets", { name: name, value: value }).then(function (r) {
            st.keys = r.keys; Store.toast(r.key.label + " saved", "Kept in a private file on this computer and sent only to its provider.")
            Store.checkSoftware(); Store.refreshAgents() }, Store.fail) }
    function clearKey(name) {
        return Store.post("/secrets", { name: name, clear: true }).then(function (r) {
            st.keys = r.keys; Store.toast(r.key.label + " removed", ""); Store.checkSoftware(); Store.refreshAgents() }, Store.fail) }
    readonly property var cliAgents: Store.chatAgents.filter(function (a) { return a.kind !== "api" })
    readonly property var apiAgents: Store.chatAgents.filter(function (a) { return a.kind === "api" && !a.local && !a.custom })
    readonly property var localAgents: Store.chatAgents.filter(function (a) { return a.kind === "api" && a.local && !a.custom })
    // providers you added by address (form/agents/custom.py): their settings from GET /providers, their models from /chat
    property var providers: []
    property var editingProvider: undefined      // undefined: no editor; null: adding; a provider: editing it
    function loadProviders() { Store.get("/providers").then(function (r) { st.providers = r.providers }, function () {}) }
    function agentOf(id) { return Store.agentInfo(id) }

    function same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }
    function current(r) { return st.edits[r.key] !== undefined ? st.edits[r.key] : r.value }
    function setEdit(r, v) {
        var e = Object.assign({}, st.edits)
        if (st.same(v, r.value)) delete e[r.key]; else e[r.key] = v
        st.edits = e
    }
    function save() { Store.saveConfig(st.edits).then(function (r) { if (r) { st.edits = ({}); st.rev++ } }) }
    function localPath(url) {
        var s = decodeURIComponent(String(url))
        if (Bridge.platform.indexOf("win") === 0) return s.replace(/^file:\/\/\//, "").replace(/\//g, "\\")
        return s.replace(/^file:\/\//, "")
    }
    property var pathRow: null
    function choosePath(r) { st.pathRow = r; if (r.key === "data.dir") Store.ask(folderDlg); else Store.ask(fileDlg) }
    FolderDialog { id: folderDlg; title: "Choose the project folder"; onAccepted: if (st.pathRow) st.setEdit(st.pathRow, st.localPath(selectedFolder)) }
    FileDialog { id: fileDlg; title: "Choose the program"; onAccepted: if (st.pathRow) st.setEdit(st.pathRow, st.localPath(selectedFile)) }

    // ── the rail: search, then the pages in their groups ─────────────────────────────────────────────────────────
    Item { id: rail; width: st.railW; height: parent.height
        property Item cur: null                // the row of the page in front: the highlight sits behind it
        Rectangle { x: 12; y: 2; width: parent.width - 16; height: parent.height - 6; radius: 16; color: Theme.glass }
        Field { id: search; objectName: "settingsSearch"; x: 22; y: 14; width: parent.width - 36; placeholder: "Search settings"
            onEdited: function (t) { st.query = t; pane.contentY = 0 } }
        // the one highlight: it glides from page to page (it jumps with Reduce Motion)
        Rectangle { id: navHi; visible: !!rail.cur && !st.searching; radius: height / 2; color: Theme.glass2
            x: nav.x; width: nav.width; height: 32
            y: rail.cur && rail.cur.parent ? nav.y + rail.cur.parent.y + rail.cur.y : 0
            property bool settled: false
            Component.onCompleted: Qt.callLater(function () { navHi.settled = true })
            Behavior on y { enabled: navHi.settled; Glide { duration: Theme.move(Theme.base) } } }
        Column { id: nav; objectName: "settingsNav"; x: 20; y: 58; width: parent.width - 32; spacing: 2
            opacity: st.searching ? 0.55 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            Repeater {
                model: st.sections
                Column {
                    id: ni
                    required property var modelData
                    required property int index
                    readonly property bool on: modelData.value === st.tab && !st.searching
                    readonly property bool head: index === 0 || st.sections[index - 1].group !== modelData.group
                    readonly property int pending: st.dirtyIn(modelData.value)
                    width: nav.width
                    Txt { visible: ni.head; kind: "cap"; text: ni.modelData.group; leftPadding: 12; topPadding: ni.index === 0 ? 2 : 14; bottomPadding: 6 }
                    Rectangle { id: navRow; objectName: "settingsNav_" + ni.modelData.value; width: parent.width; height: 32; radius: height / 2
                        color: !ni.on && nm.containsMouse ? Theme.washHover : "transparent"
                        readonly property bool on: ni.on
                        onOnChanged: if (on) rail.cur = navRow
                        Component.onCompleted: if (on) rail.cur = navRow
                        activeFocusOnTab: true
                        Keys.onReturnPressed: st.go(ni.modelData.value)
                        Keys.onSpacePressed: st.go(ni.modelData.value)
                        Behavior on color { Tint {} }
                        FocusRing { on: parent.activeFocus; radius: parent.radius + 2 }
                        Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: ni.modelData.icon; size: 15; color: ni.on ? Theme.datum : Theme.ink3 }
                        Txt { x: 37; anchors.verticalCenter: parent.verticalCenter; text: ni.modelData.text; wrapMode: Text.NoWrap
                            font.weight: ni.on ? Theme.wSemi : Theme.wMedium; color: ni.on ? Theme.ink : Theme.ink2 }
                        // unsaved changes on this page, or things that want attention
                        Rectangle { visible: ni.pending > 0; anchors.right: parent.right; anchors.rightMargin: 13; anchors.verticalCenter: parent.verticalCenter
                            width: 6; height: 6; radius: 3; color: Theme.blueprint }
                        Rectangle { visible: !!ni.modelData.badge && ni.pending === 0; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                            width: bt.implicitWidth + 10; height: 16; radius: 8; color: Theme.alpha(Theme.amber, 0.14)
                            Text { id: bt; anchors.centerIn: parent; text: ni.modelData.badge ? String(ni.modelData.badge) : ""; color: Theme.amber; font.family: Theme.mono; font.pixelSize: 10; renderType: Text.NativeRendering } }
                        MouseArea { id: nm; anchors.fill: parent; hoverEnabled: true; onClicked: st.go(ni.modelData.value) } }
                }
            }
        }
        // what you run
        Row { x: 32; anchors.bottom: parent.bottom; anchors.bottomMargin: 18; spacing: 6
            Txt { kind: "fine"; tone: 3; text: "Form Studio"; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; tone: 3; mono: true; text: Bridge.version; anchors.verticalCenter: parent.verticalCenter } }
    }
    function go(v) { search.text = ""; st.query = ""; st.tab = v }

    // ── the page ─────────────────────────────────────────────────────────────────────────────────────────────────
    Flickable {
        id: pane
        objectName: "settingsScroll"
        x: st.railW; width: parent.width - st.railW; height: parent.height
        clip: true; boundsBehavior: Flickable.StopAtBounds
        contentHeight: page.implicitHeight + 56
        ScrollBar.vertical: ScrollBar { width: 6; policy: pane.contentHeight > pane.height + 1 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
        Column {
            id: page; x: 28; y: 14; width: pane.width - 60; spacing: 22
            // the page's title and one line on what it holds
            Column { width: parent.width; spacing: 6
                Txt { kind: "cap"; color: Theme.datum; text: st.searching ? "Settings" : st.section.group }
                Txt { objectName: "settingsTitle"; kind: "h2"; text: st.searching ? "Search" : st.section.text }
                Txt { tone: 2; width: parent.width; lineHeight: 1.35
                    text: st.searching ? (st.found.length ? F.plural(st.found.length, "setting") + " on every page match “" + st.query.trim() + "”."
                                                           : "No setting matches “" + st.query.trim() + "”.")
                                       : st.section.sub } }
            Txt { visible: !st.cfg; tone: 2; text: "Reading the settings…" }
            SettingsRows { visible: st.searching && st.found.length > 0; sheet: st; rows: st.searching ? st.found : [] }
            Loader { width: parent.width; active: !st.searching && st.tab === "general"; visible: active; sourceComponent: generalPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "chat"; visible: active; sourceComponent: agentsPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "software"; visible: active; sourceComponent: softwarePage }
            Loader { width: parent.width; active: !st.searching && st.tab === "printer"; visible: active; sourceComponent: printingPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "apps"; visible: active; sourceComponent: appsPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "updates"; visible: active; sourceComponent: updatesPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "advanced"; visible: active; sourceComponent: advancedPage }
        }
    }
    // the page slides under the title bar and the action bar
    Rectangle { x: st.railW; width: pane.width; height: 16; opacity: pane.atYBeginning ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.shade, Theme.dark ? 0.26 : 0.07) } GradientStop { position: 1; color: "transparent" } } }
    Rectangle { x: st.railW; y: parent.height - 16; width: pane.width; height: 16; opacity: pane.atYEnd || pane.contentHeight <= pane.height ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Theme.alpha(Theme.shade, Theme.dark ? 0.3 : 0.08) } } }

    // a titled group on a page: its title, a mono note for what applies at once, one quiet line, then its card
    component Group: Column {
        id: grp
        property string title: ""
        property string sub: ""
        property string applies: ""          // "Applies at once" for things that do not wait for Save
        default property alias content: inner.data
        width: parent ? parent.width : 0; spacing: 9
        Column { width: parent.width; spacing: 2
            Row { spacing: 10
                Txt { text: grp.title; font.weight: Theme.wSemi; font.letterSpacing: -0.1 }
                Txt { kind: "fine"; mono: true; tone: 3; visible: text !== ""; text: grp.applies; anchors.verticalCenter: parent.verticalCenter } }
            Txt { kind: "fine"; tone: 3; width: Math.min(parent.width, 640); visible: text !== ""; text: grp.sub } }
        Column { id: inner; width: parent.width; spacing: 10 }
    }

    // ── General ──────────────────────────────────────────────────────────────────────────────────────────────────
    Component { id: generalPage
        Column { spacing: 26
            Group { title: "Appearance"; applies: "Applies at once"
                sub: Bridge.appearanceOverride ? "Set to " + Bridge.appearanceOverride + " for this run by FORM_APPEARANCE."
                   : Theme.appearance === "system" ? "Follows the system: " + (Theme.dark ? "dark" : "light") + " now." : "The same bench, at night or by day."
                Row { id: looks; objectName: "appearanceSeg"; spacing: 12; enabled: !Bridge.appearanceOverride; opacity: enabled ? 1 : 0.5
                    Repeater {
                        model: [{ value: "dark", text: "Dark" }, { value: "light", text: "Light" }, { value: "system", text: "Match system" }]
                        Rectangle {
                            id: look
                            required property var modelData
                            readonly property bool on: (Bridge.appearanceOverride || Theme.appearance) === modelData.value
                            objectName: "appearance_" + modelData.value
                            width: Math.floor((looks.parent.width - 24) / 3); height: 104; radius: 16
                            color: on ? Theme.glass2 : lm.containsMouse ? Theme.washHover : Theme.glass
                            Behavior on color { Tint {} }
                            // a small picture of the bench in that appearance
                            Item { id: pic; x: 12; y: 12; width: parent.width - 24; height: 52; clip: true
                                Repeater {
                                    model: look.modelData.value === "system" ? [true, false] : [look.modelData.value === "dark"]
                                    Rectangle {
                                        required property bool modelData
                                        required property int index
                                        readonly property bool dk: modelData
                                        x: index * pic.width / 2; width: look.modelData.value === "system" ? pic.width / 2 : pic.width; height: pic.height
                                        radius: Theme.rSm; color: dk ? "#0b0b0c" : "#eeece8"; border.color: dk ? "#2a2a2c" : "#d9d6d1"; clip: true
                                        Rectangle { x: 8; y: 8; width: 26; height: parent.height - 16; radius: 5; color: dk ? "#1c1c1e" : "#ffffff" }
                                        Rectangle { x: 42; y: 10; width: Math.max(10, parent.width - 62); height: 5; radius: 2.5; color: dk ? "#f4f3f1" : "#161616"; opacity: 0.8 }
                                        Rectangle { x: 42; y: 21; width: Math.max(8, parent.width - 84); height: 4; radius: 2; color: dk ? "#74736f" : "#8b8a86"; opacity: 0.7 }
                                        Rectangle { x: 42; y: 33; width: 22; height: 9; radius: 4.5; color: dk ? "#a9b8ff" : "#3d55d6" } } } }
                            Txt { x: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; text: look.modelData.text
                                font.weight: look.on ? Theme.wSemi : Theme.wMedium; color: look.on ? Theme.ink : Theme.ink2 }
                            Icon { visible: look.on; name: "circle_check"; size: 15; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 12
                                anchors.bottom: parent.bottom; anchors.bottomMargin: 12 }
                            MouseArea { id: lm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: Theme.setAppearance(look.modelData.value) } }
                    } } }
            Group { title: "Set up for"; applies: "Applies at once"
                sub: "Turning one on installs only what it needs, with every command in the log. Turning one off hides it; nothing is uninstalled."
                Txt { visible: !Store.caps; kind: "fine"; tone: 3; text: "Reading what Form Studio is set up for…" }
                CapCards { objectName: "settingsCaps"; width: parent.width; settings: true; pick: Store.caps ? Store.caps.chosen : []
                    onToggled: function (id, on) { Store.setCap(id, on) } }
                InstallLog { width: parent.width } }
            Group { title: "Designing"; sub: "What happens to a design after it builds."
                SettingsRows { sheet: st; rows: st.rowsOf("general", function (r) { return r.key.indexOf("refine.") === 0 }) }
                // what design refinement learned on this computer (form/refine/ledger.py)
                Rectangle { objectName: "settingsRefineLedger"; width: parent.width; height: 62; radius: 16; color: Theme.glass
                    Column { x: 18; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36 - resetLedger.width - 12; spacing: 3
                        Txt { text: "What refinement learned"; font.weight: Theme.wMedium }
                        Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: "Which refinements helped which kinds of design, kept on this computer only" } }
                    Btn { id: resetLedger; objectName: "refineLedgerReset"; anchors.right: parent.right; anchors.rightMargin: 18
                        anchors.verticalCenter: parent.verticalCenter; small: true; icon: "rotate_ccw"; text: "Reset"
                        onClicked: Store.resetRefineLedger() } } }
            Group { title: "Your designs"; sub: "Designs, their history and releases are plain files in one folder."
                SettingsRows { sheet: st; rows: st.rowsOf("general", function (r) { return r.key.indexOf("refine.") !== 0 }) }
                Row { spacing: 8
                    Btn { small: true; icon: "folder_open"; text: "Open the project folder"; onClicked: Bridge.openDataFolder() } } }
        } }

    // ── Agents & models: every way chat can reach a model, set up or not ─────────────────────────────────────────
    Component { id: agentsPage
        Column { spacing: 26
            Note { visible: !Store.chat.available; kind: "amber"; title: "No agent is connected yet"
                text: "Chat works with the agent you choose: an agent app installed here, a model provider's API key, or a model running on this computer." }
            Group { title: "Defaults for new conversations"; sub: "Each conversation can also pick its own agent and model."
                visible: st.rowsOf("chat").length > 0
                SettingsRows { sheet: st; rows: st.rowsOf("chat", st.isDefaultsRow) } }
            Group { title: "Agent apps on this computer"
                sub: "Each runs on its own account with Form Studio's tools. Install more under Engines & software."
                Rectangle { visible: st.cliAgents.length > 0; width: parent.width; height: agList.implicitHeight; radius: 16
                    color: Theme.glass
                    Column { id: agList; width: parent.width
                        Repeater {
                            model: st.cliAgents
                            AgentRow { width: agList.width; a: modelData; first: index === 0; objectName: "agentRow"
                                required property var modelData
                                required property int index
                                onInstall: st.tab = "software" }
                        } } } }
            Group { title: "Model provider APIs"
                sub: "Form Studio talks to the provider directly, with its own tools; no other app is needed. A key set in your environment is found by itself. Keys you add are kept in a private file on this computer and sent only to their provider."
                Rectangle { visible: st.apiAgents.length > 0; width: parent.width; height: apList.implicitHeight; radius: 16
                    color: Theme.glass
                    Column { id: apList; width: parent.width
                        Repeater {
                            model: st.apiAgents
                            AgentRow { width: apList.width; a: modelData; first: index === 0; k: st.keyFor(modelData.key || "")
                                objectName: "secretRow"                 // every provider API row takes a key
                                required property var modelData
                                required property int index
                                onSaveKey: function (v) { return st.saveKey(modelData.key, v) }
                                onClearKey: st.clearKey(modelData.key) }
                        } } } }
            // providers you added by address: any server in a format Form Studio speaks
            Group { title: "Your providers"
                sub: "A model service that is not listed above, a company gateway or a server on your network. Give its address; Form Studio finds the format, the models and whether they call tools."
                Loader { visible: active; width: parent.width; active: st.editingProvider !== undefined
                    sourceComponent: ProviderEditor { width: parent ? parent.width : 600; editing: st.editingProvider
                        onClosed: st.editingProvider = undefined
                        onSaved: function (p) { st.editingProvider = undefined; st.loadProviders(); st.loadKeys(); Store.refreshAgents() } } }
                Rectangle { visible: st.providers.length > 0; width: parent.width; height: cpList.implicitHeight; radius: 16
                    color: Theme.glass
                    Column { id: cpList; width: parent.width
                        Repeater {
                            model: st.providers
                            ProviderRow { width: cpList.width; p: modelData; a: st.agentOf(modelData.id); first: index === 0; objectName: "providerRow"
                                required property var modelData
                                required property int index
                                onEdit: st.editingProvider = modelData
                                onChanged: st.loadProviders() }
                        } } }
                Btn { objectName: "addProvider"; small: true; icon: "plus"; text: "Add a provider…"; visible: st.editingProvider !== null
                    onClicked: st.editingProvider = null } }
            Group { title: "Local models"
                sub: "Servers on this computer, found on their usual ports. Nothing leaves this computer. The model must support tool calls."
                Rectangle { visible: st.localAgents.length > 0; width: parent.width; height: loList.implicitHeight; radius: 16
                    color: Theme.glass
                    Column { id: loList; width: parent.width
                        Repeater {
                            model: st.localAgents
                            AgentRow { width: loList.width; a: modelData; first: index === 0; objectName: "localRow"
                                required property var modelData
                                required property int index }
                        } } }
                Btn { small: true; kind: "quiet"; icon: "refresh_cw"; text: "Look again"; busy: Store.agentsChecking; onClicked: Store.refreshAgents() } }
            Group { title: "What agents may do"; sub: "Chat itself, the web, spending and the page outside agents open."
                visible: st.rowsOf("chat").length > 0
                SettingsRows { sheet: st; rows: st.rowsOf("chat", function (r) { return !st.isDefaultsRow(r) }) } }
        } }

    // ── Engines & software ───────────────────────────────────────────────────────────────────────────────────────
    Component { id: softwarePage
        SoftwarePanel { actions: false; intro: false } }

    // ── Printing: the default printer, picked from the printers set up in your slicers ───────────────────────────
    Component { id: printingPage
        Column { spacing: 26
            Group { title: "Default printer"; applies: "Applies at once"
                Rectangle { id: dpCard; objectName: "settingsDefaultPrinter"
                    width: parent.width; height: Math.max(dp.implicitHeight + 30, 72); radius: 16; color: Theme.glass
                    readonly property var sl: Store.slicer || ({ available: false })
                    Rectangle { x: 18; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: Theme.rMd
                        color: dpCard.sl.available ? Theme.alpha(Theme.datum, 0.12) : Theme.glass2
                        Icon { anchors.centerIn: parent; name: "printer"; size: 17; color: dpCard.sl.available ? Theme.datum : Theme.ink3 } }
                    Column { id: dp; x: 70; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 70 - 18 - chooseBtn.width - 12; spacing: 3
                        Txt { objectName: "settingsPrinterName"; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: dpCard.sl.available ? dpCard.sl.presets.machine.name : "No slicer can be read" }
                        Txt { kind: "fine"; width: parent.width; wrapMode: Text.Wrap
                            text: dpCard.sl.available ? dpCard.sl.presets.filament.name + "  ·  " + dpCard.sl.presets.process.name + "  ·  " + (dpCard.sl.label || "")
                                  + (Store.studio && Store.studio.env.printer && Store.studio.env.printer.slicer ? "  ·  chosen in Form Studio" : "  ·  as selected in the slicer")
                                : (dpCard.sl.reason || "Install a slicer under Engines & software, or set the bed size under Advanced.") } }
                    Btn { id: chooseBtn; objectName: "settingsChoosePrinter"; icon: "printer"; text: "Choose printer…"
                        anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter
                        tip: "Every printer set up in your slicers, with its filaments and processes"; onClicked: Store.openSheet("printer") } }
                // the slicer's own selection is not chosen in Form Studio yet: one click makes the checks use its bed
                Note { id: adopt; objectName: "settingsAdoptPrinter"; width: parent.width; kind: "plain"
                    readonly property var sl: Store.slicer || ({ available: false })
                    readonly property var pr: Store.studio ? Store.studio.env.printer : null
                    visible: !!sl.available && !!pr && !pr.machine && !!sl.envelope_mm
                             && sl.envelope_mm.map(Math.round).join() !== pr.envelope_mm.map(Math.round).join()
                    title: "The checks use " + (pr ? pr.envelope_mm.join(" × ") : "") + " mm"
                    text: visible ? sl.label + " slices on " + sl.presets.machine.name + " (" + sl.envelope_mm.map(function (x) { return Math.round(x) }).join(" × ") + " mm). Make it the default so the checks use the same bed." : ""
                    Btn { small: true; icon: "pin"; text: "Make it the default"
                        onClicked: Store.post("/printers/use", { "default": true, kind: adopt.sl.kind, machine: adopt.sl.presets.machine.name,
                                                                 filament: adopt.sl.presets.filament.name, process: adopt.sl.presets.process.name })
                            .then(function () { return Store.reloadStudio() }).then(function () { Store.loadConfig(); if (Store.pid) Store.refresh().then(function () { Store.rerunIfStale() }) }, Store.fail) } } }
            Group { title: "Slicing and plates"; sub: "Which slicer makes the slices, and how parts sit on the bed."
                SettingsRows { sheet: st; rows: st.rowsOf("printer") }
                Row { spacing: 10
                    Btn { small: true; icon: "printer"; text: "Compare slicers…"; onClicked: Store.openSheet("slicer") }
                    Btn { small: true; kind: "quiet"; icon: "package"; text: "Slicers under Engines & software"; onClicked: st.tab = "software" } } }
        } }

    // ── Other apps ───────────────────────────────────────────────────────────────────────────────────────────────
    Component { id: appsPage
        Column { spacing: 26
            Group { title: "Where they are"; sub: "Leave a path empty and Form Studio looks in the usual places. Whether Form Studio uses an app that is installed is its switch under Engines & software."
                SettingsRows { sheet: st; rows: st.rowsOf("apps", function (r) { return r.type === "path" }) } }
            Group { title: "Open in…"; sub: "What a file is handed to when you open it from Form Studio."
                SettingsRows { sheet: st; rows: st.rowsOf("apps", function (r) { return r.type !== "path" }) } }
        } }

    // ── Updates ──────────────────────────────────────────────────────────────────────────────────────────────────
    Component { id: updatesPage
        Column { spacing: 26
            Group { title: "This version"
                Rectangle { objectName: "settingsVersion"; width: parent.width; height: 72; radius: 16; color: Theme.glass
                    Rectangle { x: 18; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: Theme.rMd; color: Theme.glass2
                        Logo { word: false; size: 17; anchors.centerIn: parent; anchors.horizontalCenterOffset: 1 } }
                    Column { x: 70; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                        Row { spacing: 8
                            Txt { text: "Form Studio"; font.weight: Theme.wSemi }
                            Txt { mono: true; tone: 2; text: Bridge.version; anchors.verticalCenter: parent.verticalCenter } }
                        Txt { kind: "fine"
                            text: Store.update && Store.update.available ? "Form Studio " + Store.update.latest + " is out."
                                : Store.update && Store.update.enabled === false ? "Update checks are off." : "Looked for once a day, from public release information on GitHub." } }
                    Row { anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                        Btn { small: true; kind: "quiet"; icon: "sparkle"; text: "What’s new"; onClicked: Store.showWhatsNew() }
                        Btn { small: true; kind: "quiet"; icon: "info"; text: "About"; onClicked: Store.openSheet("about") }
                        Btn { small: true; icon: "refresh_cw"; text: "Check now"
                            onClicked: run(function () { return Store.checkUpdates(true).then(function (u) {
                                if (u && u.available) { Store.updateHidden = false; Store.openSheet("update") }
                                else if (u && !u.enabled) Store.toast("Update checks are off", "[updates] check = false or FORM_NO_UPDATE_CHECK=1")
                                else if (u && u.latest) Store.toast("Form Studio " + u.current + " is up to date")
                                else Store.toast("Could not reach GitHub", "Nothing changed. Try again later.") }) }) } } } }
            Group { title: "Update checks"
                SettingsRows { sheet: st; rows: st.rowsOf("updates") } }
        } }

    // ── Advanced ─────────────────────────────────────────────────────────────────────────────────────────────────
    Component { id: advancedPage
        Column { spacing: 26
            Group { title: "Limits and fallbacks"
                SettingsRows { sheet: st; rows: st.rowsOf("advanced") } }
            Group { title: "The file"; sub: "Everything here is kept in one text file. Form Studio rewrites only the keys you change and keeps a backup."
                Rectangle { width: parent.width; height: 48; radius: 16; color: Theme.glass
                    Txt { x: 18; anchors.verticalCenter: parent.verticalCenter; mono: true; kind: "fine"; tone: 2; width: parent.width - 36 - cpPath.width - 8
                        elide: Text.ElideMiddle; wrapMode: Text.NoWrap; text: st.cfg ? st.cfg.path_short + (st.cfg.exists ? "" : "   (not written yet)") : "" }
                    Btn { id: cpPath; small: true; kind: "quiet"; icon: "copy"; text: "Copy path"; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                        onClicked: { Bridge.copy(st.cfg.path); Store.toast("Copied the path") } } } }
        } }
}
