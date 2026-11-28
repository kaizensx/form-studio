import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Settings (direction I): a bare column of pages on the left under the word "Settings", one page on the right, on
// one deep pane of glass. No title bar and no action bar: the sheet lays out its whole card (bareHead, fillsBody:
// SheetHost.qml), the nav stays put and only the page scrolls.
//
//   General              what Form Studio is set up for (tiles with a switch), the engines (and mesh generators)
//                        with their licence, size and state, how designs are refined, the project folder
//   Agents & models      every way chat can reach a model, and the defaults for new conversations
//   Engines & software   the installer registry: installed or not, Install, and "Use in Form Studio" for each engine
//   Printing             only with the 3D printing capability: the default printer, the slicer, the plate
//   Costs                the cost models' rates: published (cited, dated), assumed parameters, or yours per shop
//   Other apps           where Blender, OpenSCAD and FreeCAD are, and what "Open in…" hands files to
//   Appearance           dark, light or the system's; Reduce motion
//   Backups              the schedule and destinations, the last backup, verify and restore, Recently deleted
//   Updates              update checks and the channel, the version you run
//   Advanced             limits and fallbacks, with the key each one has in studio.toml
//
// A page is titled groups of rows on thin glass. Rows that edit studio.toml collect in `edits`; while there are any, a
// bar floats at the foot of the page with what is saved where, Revert and Save: only the changed keys are rewritten,
// comments and other keys stay, and the previous file is kept as a backup next to it (form/config_edit.py). Things
// that apply at once say so and do not wait for Save: appearance, "Set up for" (form/capabilities.py: on installs
// what it needs, off hides it and never uninstalls), the default printer, and "Use in Form Studio".
// Open with Store.openSettings("general" | "printer" | "chat" | "costs" | "apps" | "appearance" | "backups" | "updates" | "advanced" | "software").
// The search under the title finds rows on every page.
Item {
    id: st
    objectName: "settingsSheet"
    property string title: "Settings"
    property int sheetWidth: Theme.sheetXxl
    property int sheetHeight: 780
    property bool fillsBody: true
    property bool bareHead: true              // no title bar: the word "Settings" stands over the nav (SheetHost.qml)
    implicitHeight: sheetHeight
    readonly property int railW: 208
    readonly property bool narrow: width < 860
    // a quieter plate than `glass`: every other row of a list, a tile that is off
    readonly property color glass3: Theme.dark ? Qt.rgba(1, 1, 1, 0.04) : Qt.rgba(1, 1, 1, 0.42)
    readonly property var sections: [
        { value: "general", text: "General", icon: "sliders_horizontal", group: "Studio" },
        { value: "chat", text: "Agents & models", icon: "sparkles", group: "Studio" },
        { value: "software", text: "Engines & software", icon: "package", group: "Studio",
          badge: Store.setupAttention && Store.setupAttention.length ? Store.setupAttention.length : 0 }]
        .concat(Store.printOn ? [{ value: "printer", text: "Printing", icon: "printer", group: "Making" }] : [])
        .concat([
        { value: "costs", text: "Costs", icon: "coins", group: "Making" },
        { value: "apps", text: "Other apps", icon: "layout_grid", group: "Making" },
        { value: "appearance", text: "Appearance", icon: "palette", group: "System" },
        { value: "backups", text: "Backups", icon: "archive", group: "System" },
        { value: "updates", text: "Updates", icon: "refresh_cw", group: "System" },
        { value: "advanced", text: "Advanced", icon: "wrench", group: "System" }])
    readonly property var tabNames: ({ general: "General", printer: "Printing", chat: "Agents & models", apps: "Other apps", costs: "Costs", appearance: "Appearance", backups: "Backups", updates: "Updates", advanced: "Advanced", software: "Engines & software" })
    readonly property var section: { for (var i = 0; i < sections.length; i++) if (sections[i].value === tab) return sections[i]; return sections[0] }
    readonly property string pageTitle: searching ? "Search" : section.text        // the page in front, by name
    function accept() { if (dirty > 0) save() }
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
            Store.checkSoftware(); Store.refreshAgents(); st.loadGenerators() }, Store.fail) }
    function clearKey(name) {
        return Store.post("/secrets", { name: name, clear: true }).then(function (r) {
            st.keys = r.keys; Store.toast(r.key.label + " removed", ""); Store.checkSoftware(); Store.refreshAgents(); st.loadGenerators() }, Store.fail) }
    readonly property var cliAgents: Store.chatAgents.filter(function (a) { return a.kind !== "api" })
    readonly property var apiAgents: Store.chatAgents.filter(function (a) { return a.kind === "api" && !a.local && !a.custom })
    readonly property var localAgents: Store.chatAgents.filter(function (a) { return a.kind === "api" && a.local && !a.custom })
    // providers you added by address (form/agents/custom.py): their settings from GET /providers, their models from /chat
    property var providers: []
    property var editingProvider: undefined      // undefined: no editor; null: adding; a provider: editing it
    function loadProviders() { Store.get("/providers").then(function (r) { st.providers = r.providers }, function () {}) }
    function agentOf(id) { return Store.agentInfo(id) }

    // mesh generators (form/generate): words or a picture to a mesh, rebuilt as CAD. Each is off until its switch
    // here is on; a hosted one also needs its key (Agents & models). Nothing is sent by turning one on.
    property var generators: []
    function loadGenerators() { Store.get("/generate/providers").then(function (r) { st.generators = r.providers || [] }, function () {}) }
    function setGenerator(id, on) { Store.post("/generate/enable", { provider: id, on: on }).then(function () { st.loadGenerators() }, Store.fail) }

    // the engines on General: everything Form Studio runs or hands a design to, agents apart (they have their page)
    readonly property var engineRows: Store.software ? Store.software.software.filter(function (r) {
        var g = st.groupOf(r.id)
        return r.id !== "claude.signin" && r.id !== "data" && !r.absent && g !== "ai" && g !== "agents" && (g !== "slicer" || Store.printOn) })
        .map(function (r) { return { r: r, name: st.shortName(r.label), why: st.shortWhy(r.why), meta: st.engineMeta(r) } }) : []
    // the mesh generators' rows, in the same few words
    readonly property var generatorRows: st.generators.map(function (g) {
        var lic = String(g.licence || "").split(/[;(:]/)[0].trim()
        return { g: g, name: st.shortName(g.title),
                 why: g.kind === "local" ? "a mesh from words or a picture, made here" : "a mesh from words or a picture, on your key",
                 meta: [/terms of service|licen[cs]e/i.test(lic) ? "" : lic, g.kind === "local" ? "on this computer" : "hosted"].filter(function (x) { return x }).join(" · ") } })
    // an engine's row says it in a few words: the registry's long sentences stay in the tip and on Engines & software
    function shortName(s) { return String(s || "").replace(/\s*\([^)]*\)\s*$/, "") }
    function shortWhy(s) {
        var t = String(s || "").replace(/^Optional[^:]*:\s*/, "").replace(/\s*\([^)]*\)/g, "").replace(/\.\s*$/, "")
        var cut = t.search(/\.\s/); if (cut > 0) t = t.slice(0, cut)
        var w = t.split(" ")[0]; return w.slice(1) === w.slice(1).toLowerCase() ? t[0].toLowerCase() + t.slice(1) : t }
    function shortLicence(s) {
        return String(s || "").replace(/\s*\([^)]*\)/g, "").split(/[;,]\s*/).map(function (x) { return x.trim() })
            .map(function (x) { return x.replace(/-Clause$/, "") }).filter(function (x, i, a) { return x && a.indexOf(x) === i }).join(", ") }
    function shortSize(r) {
        var g = st.groupOf(r.id)
        if (r.id === "kernel" || r.id === "parts") return "in the app"
        if (g === "cad" || g === "slicer") return "your copy"          // their own program, the person's copy
        var m = String(r.size || "").match(/(\d[\d.,]*)\s*(KB|MB|GB)/)
        return m ? m[1] + " " + m[2] : "" }
    function engineMeta(r) { return [st.shortLicence(r.licence), st.shortSize(r)].filter(function (x) { return x }).join(" · ") }
    function groupOf(id) {
        var gs = Store.software ? Store.software.groups : []
        for (var i = 0; i < gs.length; i++) if (gs[i].items.indexOf(id) >= 0) return gs[i].id
        return "" }

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
    function choosePath(r) { st.pathRow = r; if (r.key === "data.dir" || r.key === "backup.folder") Store.ask(folderDlg); else Store.ask(fileDlg) }
    FolderDialog { id: folderDlg; title: st.pathRow && st.pathRow.key === "backup.folder" ? "Choose the backup folder" : "Choose the project folder"; onAccepted: if (st.pathRow) st.setEdit(st.pathRow, st.localPath(selectedFolder)) }
    FileDialog { id: fileDlg; title: "Choose the program"; onAccepted: if (st.pathRow) st.setEdit(st.pathRow, st.localPath(selectedFile)) }

    // ── the nav: the word, the search, then the pages. Nothing is boxed: the one plate is the page you are on ────
    Item { id: rail; x: 17; width: st.railW; height: parent.height
        property Item cur: null                // the row of the page in front: the highlight sits behind it
        Txt { x: 12; y: 22; height: 36; verticalAlignment: Text.AlignVCenter; text: "Settings"; lineHeight: 1.0
            font.pixelSize: 24; font.weight: Theme.wSemi; font.letterSpacing: -0.7 }
        Field { id: search; objectName: "settingsSearch"; x: 0; y: 68; width: parent.width; placeholder: "Search settings"
            onEdited: function (t) { st.query = t; pane.contentY = 0 } }
        // the one highlight: it glides from page to page (it jumps with Reduce Motion)
        Rectangle { id: navHi; visible: !!rail.cur && !st.searching; radius: 12; color: Theme.glass2
            x: nav.x; width: nav.width; height: 36
            y: rail.cur && rail.cur.parent ? nav.y + rail.cur.parent.y + rail.cur.y : 0
            Rectangle { visible: Theme.dark; x: 12; width: parent.width - 24; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }
            property bool settled: false
            Component.onCompleted: Qt.callLater(function () { navHi.settled = true })
            Behavior on y { enabled: navHi.settled; Glide { duration: Theme.move(Theme.base) } } }
        Column { id: nav; objectName: "settingsNav"; x: 0; y: 114; width: parent.width; spacing: 2
            opacity: st.searching ? 0.55 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            Repeater {
                model: st.sections
                Column {
                    id: ni
                    required property var modelData
                    required property int index
                    readonly property bool on: modelData.value === st.tab && !st.searching
                    readonly property bool head: index > 0 && st.sections[index - 1].group !== modelData.group
                    readonly property int pending: st.dirtyIn(modelData.value)
                    width: nav.width
                    Item { visible: ni.head; width: 1; height: 10 }           // a breath between the groups, no caption
                    Rectangle { id: navRow; objectName: "settingsNav_" + ni.modelData.value; width: parent.width; height: 36; radius: 12
                        color: !ni.on && nm.containsMouse ? Theme.washHover : "transparent"
                        readonly property bool on: ni.on
                        onOnChanged: if (on) rail.cur = navRow
                        Component.onCompleted: if (on) rail.cur = navRow
                        activeFocusOnTab: true
                        Keys.onReturnPressed: st.go(ni.modelData.value)
                        Keys.onSpacePressed: st.go(ni.modelData.value)
                        Behavior on color { Tint {} }
                        FocusRing { on: parent.activeFocus; radius: parent.radius + 2 }
                        Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: ni.modelData.icon; size: 16; color: ni.on ? Theme.ink : Theme.ink3 }
                        Txt { x: 39; anchors.verticalCenter: parent.verticalCenter; text: ni.modelData.text; wrapMode: Text.NoWrap; lineHeight: 1.0
                            font.weight: ni.on ? Theme.wSemi : Font.Normal; color: ni.on ? Theme.ink : Theme.ink2 }
                        // unsaved changes on this page, or things that want attention
                        Rectangle { visible: ni.pending > 0; anchors.right: parent.right; anchors.rightMargin: 13; anchors.verticalCenter: parent.verticalCenter
                            width: 6; height: 6; radius: 3; color: Theme.blueprint }
                        Rectangle { visible: !!ni.modelData.badge && ni.pending === 0; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                            width: bt.implicitWidth + 10; height: 16; radius: 8; color: Theme.alpha(Theme.amber, 0.14)
                            Text { id: bt; anchors.centerIn: parent; text: ni.modelData.badge ? String(ni.modelData.badge) : ""; color: Theme.amber; font.family: Theme.mono; font.pixelSize: 11; renderType: Theme.textRender } }
                        MouseArea { id: nm; anchors.fill: parent; hoverEnabled: true; onClicked: st.go(ni.modelData.value) } }
                }
            }
        }
        // what you run
        Row { x: 12; anchors.bottom: parent.bottom; anchors.bottomMargin: 20; spacing: 6
            Txt { kind: "fine"; tone: 3; text: "Form Studio"; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; tone: 3; mono: true; text: Bridge.version; anchors.verticalCenter: parent.verticalCenter } }
    }
    function go(v) { search.text = ""; st.query = ""; st.tab = v }
    // Bring something that just appeared on the page (the provider editor) into view at once, so its first field is
    // under the pointer and never below the sheet's edge. The columns are laid out first: a new item has no place yet.
    function reveal(it) {
        if (!it) return
        for (var p = it.parent; p && p !== pane.contentItem; p = p.parent) if (p.forceLayout) p.forceLayout()
        var y = it.mapToItem(pane.contentItem, 0, 0).y
        if (y < pane.contentY + 8 || y + it.height > pane.contentY + pane.height - 24)
            pane.contentY = Math.max(0, Math.min(y - 20, Math.max(0, pane.contentHeight - pane.height)))
    }

    // ── the page ─────────────────────────────────────────────────────────────────────────────────────────────────
    Flickable {
        id: pane
        objectName: "settingsScroll"
        x: rail.x + st.railW + 12; width: parent.width - x; y: 1; height: parent.height - 2
        clip: true; boundsBehavior: Flickable.StopAtBounds
        contentHeight: page.implicitHeight + 28 + 40 + (saveBar.shown ? 56 : 0)
        ScrollBar.vertical: ScrollBar { width: 6; policy: pane.contentHeight > pane.height + 1 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
        Column {
            id: page; x: 18; y: 27; width: pane.width - 18 - 30; spacing: 22
            // a search says what it found; a page needs no title of its own: the nav names it
            Column { visible: st.searching; width: parent.width; spacing: 3
                Txt { objectName: "settingsTitle"; text: "Search"; font.pixelSize: 15; font.weight: Theme.wSemi; font.letterSpacing: -0.15 }
                Txt { tone: 2; width: parent.width; font.pixelSize: 12
                    text: st.found.length ? F.plural(st.found.length, "setting") + " on every page match “" + st.query.trim() + "”."
                                          : "No setting matches “" + st.query.trim() + "”." } }
            // a page is laid out once the settings are read, so nothing on it moves under the pointer when they arrive
            Txt { visible: !st.cfg; tone: 2; text: "Reading the settings…" }
            SettingsRows { visible: st.searching && st.found.length > 0; sheet: st; rows: st.searching ? st.found : [] }
            Loader { width: parent.width; active: !st.searching && st.tab === "general" && !!st.cfg; visible: active; sourceComponent: generalPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "chat" && !!st.cfg; visible: active; sourceComponent: agentsPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "software"; visible: active; sourceComponent: softwarePage }
            Loader { width: parent.width; active: !st.searching && st.tab === "printer" && !!st.cfg; visible: active; sourceComponent: printingPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "apps" && !!st.cfg; visible: active; sourceComponent: appsPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "costs"; visible: active; sourceComponent: costsPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "appearance"; visible: active; sourceComponent: appearancePage }
            Loader { width: parent.width; active: !st.searching && st.tab === "backups" && !!st.cfg; visible: active; sourceComponent: backupsPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "updates" && !!st.cfg; visible: active; sourceComponent: updatesPage }
            Loader { width: parent.width; active: !st.searching && st.tab === "advanced" && !!st.cfg; visible: active; sourceComponent: advancedPage }
        }
    }
    // the page slides under the sheet's edges
    Fade { x: pane.x; y: 1; width: pane.width - 1; height: 16; opacity: pane.atYBeginning ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        c0: Theme.alpha(Theme.shade, Theme.dark ? 0.26 : 0.07); c1: "transparent" }
    Fade { x: pane.x; y: parent.height - 17; width: pane.width - 1; height: 16; opacity: pane.atYEnd || pane.contentHeight <= pane.height ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        c0: "transparent"; c1: Theme.alpha(Theme.shade, Theme.dark ? 0.3 : 0.08) }

    // ── unsaved changes: a bar that floats at the foot of the page while there are any ──────────────────────────
    Item { id: saveBar; objectName: "settingsSaveBar"
        readonly property bool shown: st.dirty > 0
        x: pane.x + 18; width: pane.width - 18 - 30; height: 48; y: parent.height - height - 18
        opacity: shown ? 1 : 0; visible: opacity > 0.001
        Behavior on opacity { NumberAnimation { duration: Theme.base } }
        transform: Translate { y: saveBar.shown ? 0 : Theme.shift(8); Behavior on y { Glide { duration: Theme.base } } }
        Shadow { radius: 16; spread: 22; drop: 10; strength: Theme.dark ? 0.8 : 0.35 }
        Rectangle { anchors.fill: parent; radius: 16; color: Theme.glassSolid; border.width: 1; border.color: Theme.dark ? Theme.glassEdge : Theme.rule2 }
        Txt { x: 18; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36 - saveActs.width - 12; kind: "fine"; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
            color: st.cfg && st.cfg.env_overrides.length > 0 ? Theme.amber : Theme.ink2
            text: !st.cfg ? "" : st.cfg.env_overrides.length > 0 ? "Set outside the file for this run: " + st.cfg.env_overrides.join(", ") + ". Those win."
                : (st.cfg.exists ? "Saved to " : "Will create ") + st.cfg.path_short + " · a backup is kept on every save" }
        Row { id: saveActs; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Btn { objectName: "settingsRevert"; small: true; kind: "quiet"; text: "Revert"; onClicked: { st.edits = ({}); st.rev++ } }
            Btn { objectName: "settingsSave"; small: true; kind: "primary"; icon: "check"; keys: "Return"
                text: "Save " + F.plural(Math.max(1, st.dirty), "change"); onClicked: st.save() } } }

    // a titled group on a page: its title, a mono note for what applies at once, one quiet line, then its rows
    component Group: Column {
        id: grp
        property string title: ""
        property string sub: ""
        property string applies: ""          // "Applies at once" for things that do not wait for Save
        default property alias content: inner.data
        width: parent ? parent.width : 0; spacing: 12
        Column { width: parent.width; spacing: 3
            Row { spacing: 10
                Txt { text: grp.title; font.pixelSize: 15; font.weight: Theme.wSemi; font.letterSpacing: -0.15; lineHeight: 1.0; height: 20; verticalAlignment: Text.AlignVCenter }
                Txt { kind: "fine"; mono: true; tone: 3; visible: text !== ""; text: grp.applies; anchors.verticalCenter: parent.verticalCenter } }
            Txt { tone: 2; font.pixelSize: 12; width: Math.min(parent.width, 860); visible: text !== ""; text: grp.sub } }
        Column { id: inner; width: parent.width; spacing: 10 }
    }

    // ── General ──────────────────────────────────────────────────────────────────────────────────────────────────
    Component { id: generalPage
        Column { spacing: 26
            Component.onCompleted: st.loadGenerators()
            Group { title: "Set up for"
                sub: "What this copy of Form Studio is for. Each choice installs only what it needs, after you click. Off hides it and uninstalls nothing."
                Txt { visible: !Store.caps; kind: "fine"; tone: 3; text: "Reading what Form Studio is set up for…" }
                CapCards { objectName: "settingsCaps"; width: parent.width; settings: true; pick: Store.caps ? Store.caps.chosen : []
                    onToggled: function (id, on) { Store.setCap(id, on) } }
                InstallLog { width: parent.width } }
            // every engine by name, with its licence and size and where it stands. A switch says whether Form Studio
            // calls one that is installed; Install sets one up; the rest is on Engines & software.
            Group { title: "Engines"
                sub: "Named with their licence and size. Nothing is downloaded until you choose Install."
                Txt { visible: !Store.software; kind: "fine"; tone: 3; text: "Looking at what is installed…" }
                Column { id: engList; objectName: "settingsEngines"; width: parent.width; visible: st.engineRows.length > 0
                    Repeater { model: st.engineRows
                        Rectangle { id: er; required property var modelData; required property int index
                            readonly property var r: modelData.r
                            readonly property var step: Store.installStep(r.id)
                            readonly property bool queued: !!step && (step.state === "running" || step.state === "waiting")
                            readonly property bool ok: r.status === "ok"
                            readonly property bool locked: !!r.use && r.use.locked_by !== ""
                            readonly property real metaW: st.narrow ? 0 : Math.min(270, Math.round(width * 0.3))
                            readonly property real nameW: Math.min(220, Math.round(width * 0.21))
                            objectName: "engineRow"; readonly property string sid: r.id
                            width: engList.width; height: 44; radius: 12; color: index % 2 === 0 ? st.glass3 : "transparent"
                            Rectangle { x: 13; width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                                color: er.ok ? Theme.pass : "transparent"; border.width: er.ok ? 0 : 1.5; border.color: Theme.ink3 }
                            Txt { id: en; x: 34; width: er.nameW; anchors.verticalCenter: parent.verticalCenter; text: er.modelData.name; font.weight: Theme.wSemi; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1.0 }
                            Txt { x: 34 + er.nameW + 12; width: Math.max(0, parent.width - x - er.metaW - 12 - 128); anchors.verticalCenter: parent.verticalCenter; tone: 2; font.pixelSize: 12
                                text: er.modelData.why; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1.0 }
                            Txt { visible: er.metaW > 0; x: parent.width - 128 - er.metaW; width: er.metaW - 8; anchors.verticalCenter: parent.verticalCenter; mono: true; tone: 2; font.pixelSize: 11
                                text: er.modelData.meta; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1.0 }
                            MouseArea { id: erm; anchors.fill: parent; anchors.rightMargin: 128; hoverEnabled: true; onClicked: st.go("software") }
                            Tip { show: erm.containsMouse; text: er.r.label + ": " + er.r.why + (er.r.licence ? "\nLicence: " + er.r.licence : "") + (er.r.size ? "\nSize: " + er.r.size : "") }
                            // where it stands, and the one thing to do about it
                            Row { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                                Spinner { visible: er.queued; size: 12; anchors.verticalCenter: parent.verticalCenter }
                                Txt { visible: er.queued; kind: "fine"; tone: 2; text: er.step && er.step.state === "running" ? "Installing…" : "Waiting"; anchors.verticalCenter: parent.verticalCenter }
                                Txt { visible: !er.queued && er.ok && !!er.r.use; kind: "fine"; tone: 3; anchors.verticalCenter: parent.verticalCenter; text: Store.useOn(er.r) ? "In use" : "Off" }
                                Toggle { objectName: "engineUse"; readonly property string sid: er.r.id; visible: !er.queued && er.ok && !!er.r.use; anchors.verticalCenter: parent.verticalCenter
                                    checked: Store.useOn(er.r); enabled: !er.locked && !Store.installing
                                    onToggled: function (on) { Store.setUse(er.r, on) } }
                                Rectangle { visible: !er.queued && er.ok && !er.r.use; width: inT.implicitWidth + 22; height: 26; radius: 13; color: "transparent"; border.width: 1; border.color: Theme.rule2
                                    anchors.verticalCenter: parent.verticalCenter
                                    Txt { id: inT; anchors.centerIn: parent; font.pixelSize: 12; tone: 2; text: "Installed"; lineHeight: 1.0 } }
                                Btn { objectName: "engineInstall"; readonly property string sid: er.r.id; small: true; anchors.verticalCenter: parent.verticalCenter
                                    visible: !er.queued && !er.ok && er.r.status !== "info" && er.r.installable; text: "Install"; enabled: !Store.installing
                                    tip: er.r.noncommercial ? "Its licence wants a look first: Engines & software" : "Every command is shown in the log as it runs"
                                    onClicked: { if (er.r.noncommercial) st.go("software"); else Store.installSoftware([er.r.id]) } }
                                Btn { small: true; kind: "quiet"; anchors.verticalCenter: parent.verticalCenter
                                    visible: !er.queued && !er.ok && !(er.r.status !== "info" && er.r.installable); text: er.r.status === "info" ? "Details" : "Not found"
                                    tip: "Where it is looked for, and its page: Engines & software"; onClicked: st.go("software") } } } }
                    // the mesh generators (form/generate): words or a picture to a mesh, rebuilt as CAD. Each is off
                    // until its switch here is on; a hosted one also needs its key (Agents & models). A switch sends
                    // nothing: Home › Or make › More › Generate shows what a run sends before it sends it.
                    Repeater { model: st.generatorRows
                        Rectangle { id: gr; required property var modelData; required property int index
                            readonly property var g: modelData.g
                            readonly property real metaW: st.narrow ? 0 : Math.min(270, Math.round(width * 0.3))
                            readonly property real nameW: Math.min(220, Math.round(width * 0.21))
                            objectName: "generatorRow"; readonly property string sid: g.id
                            width: engList.width; height: 44; radius: 12; color: (st.engineRows.length + index) % 2 === 0 ? st.glass3 : "transparent"
                            Rectangle { x: 13; width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                                color: gr.g.ready ? Theme.pass : "transparent"; border.width: gr.g.ready ? 0 : 1.5; border.color: Theme.ink3 }
                            Txt { x: 34; width: gr.nameW; anchors.verticalCenter: parent.verticalCenter; text: gr.modelData.name; font.weight: Theme.wSemi; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1.0 }
                            Txt { x: 34 + gr.nameW + 12; width: Math.max(0, parent.width - x - gr.metaW - 12 - 128); anchors.verticalCenter: parent.verticalCenter; tone: 2; font.pixelSize: 12
                                text: gr.modelData.why; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1.0 }
                            Txt { visible: gr.metaW > 0; x: parent.width - 128 - gr.metaW; width: gr.metaW - 8; anchors.verticalCenter: parent.verticalCenter; mono: true; tone: 2; font.pixelSize: 11
                                text: gr.modelData.meta; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1.0 }
                            MouseArea { id: grm; anchors.fill: parent; anchors.rightMargin: 128; hoverEnabled: true }
                            Tip { show: grm.containsMouse; text: gr.g.title + ": " + gr.g.why + (gr.g.licence ? "\nLicence: " + gr.g.licence : "") }
                            Row { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                                Txt { kind: "fine"; tone: 3; anchors.verticalCenter: parent.verticalCenter
                                    text: !gr.g.implemented ? "Not yet" : gr.g.enabled ? (gr.g.ready ? "On" : "Needs set-up") : "Off" }
                                Toggle { objectName: "generatorUse"; readonly property string sid: gr.g.id; anchors.verticalCenter: parent.verticalCenter
                                    checked: !!gr.g.enabled; enabled: !!gr.g.implemented
                                    onToggled: function (on) { st.setGenerator(gr.g.id, on) } } } } } }
                Row { spacing: 8; height: 20
                    Icon { name: "lock"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                    Txt { tone: 2; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; lineHeight: 1.0
                        text: "Designs stay on this computer. Form Studio never starts a print, a machine or an upload by itself." } } }
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

    // ── Appearance: how it looks, and how much it moves ──────────────────────────────────────────────────────────
    Component { id: appearancePage
        Column { spacing: 26
            Group { title: "Appearance"; applies: "Applies at once"
                sub: Bridge.appearanceOverride ? "Set to " + Bridge.appearanceOverride + " for this run by FORM_APPEARANCE."
                   : Theme.appearance === "system" ? "Follows the system: " + (Theme.dark ? "dark" : "light") + " now." : "The same bench, at night or by day."
                Row { id: looks; objectName: "appearanceSeg"; spacing: 10; enabled: !Bridge.appearanceOverride; opacity: enabled ? 1 : 0.5
                    Repeater {
                        model: [{ value: "dark", text: "Dark" }, { value: "light", text: "Light" }, { value: "system", text: "Match system" }]
                        Rectangle {
                            id: look
                            required property var modelData
                            readonly property bool on: (Bridge.appearanceOverride || Theme.appearance) === modelData.value
                            objectName: "appearance_" + modelData.value
                            width: Math.floor((looks.parent.width - 20) / 3); height: 104; radius: 16
                            color: on ? Theme.glass2 : lm.containsMouse ? Theme.glass : st.glass3
                            border.width: 1; border.color: on ? Theme.alpha(Theme.datum, 0.45) : Theme.rule
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
                                        Rectangle { x: 42; y: 33; width: 22; height: 9; radius: 4.5; color: dk ? "#3ee6ff" : "#06708d" } } } }
                            Txt { x: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; text: look.modelData.text
                                font.weight: look.on ? Theme.wSemi : Theme.wMedium; color: look.on ? Theme.ink : Theme.ink2 }
                            Icon { visible: look.on; name: "circle_check"; size: 15; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 12
                                anchors.bottom: parent.bottom; anchors.bottomMargin: 12 }
                            MouseArea { id: lm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: Theme.setAppearance(look.modelData.value) } }
                    } } }
            // Reduce Motion: every movement becomes a short fade (Theme.move, Theme.shift). The system's own
            // setting turns it on too, and then this switch only says so.
            Group { title: "Motion"; applies: "Applies at once"
                Rectangle { objectName: "settingsReduceMotion"; width: parent.width; height: 62; radius: 16; color: Theme.glass
                    Column { x: 18; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36 - rmT.width - 16; spacing: 3
                        Txt { text: "Reduce motion"; font.weight: Theme.wMedium }
                        Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: Bridge.reducedMotion ? "On: this computer asks apps to reduce motion." : "Panes, the build and results arrive with a short fade instead of moving. Follows the system's setting too." } }
                    Toggle { id: rmT; objectName: "reduceMotionToggle"; anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter
                        checked: Theme.reduced; enabled: !Bridge.reducedMotion; opacity: enabled ? 1 : 0.5
                        onToggled: function (on) { Theme.reduceMotion = on } } } }
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
                                onInstall: st.go("software") }
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
                Loader { id: editorLd; visible: active; width: parent.width; active: st.editingProvider !== undefined
                    onLoaded: st.reveal(editorLd)
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
        Column { spacing: 26
            SoftwarePanel { }
        } }

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

    // ── Costs: the rates cost estimates use, per shop (form/costing/rates.py) ─────────────────────────────────────
    Component { id: costsPage
        Column { spacing: 26
            Group { title: "Rates"; applies: "Applies at once"
                sub: "Each rate is published (with its source and the date it was read), yours, or an assumed process parameter. Money is never assumed."
                CostRates { objectName: "settingsCostRates" } } } }

    // ── Other apps ───────────────────────────────────────────────────────────────────────────────────────────────
    Component { id: appsPage
        Column { spacing: 26
            Group { title: "Where they are"; sub: "Leave a path empty and Form Studio looks in the usual places. Whether Form Studio uses an app that is installed is its switch under Engines & software."
                SettingsRows { sheet: st; rows: st.rowsOf("apps", function (r) { return r.type === "path" }) } }
            Group { title: "Open in…"; sub: "What a file is handed to when you open it from Form Studio."
                SettingsRows { sheet: st; rows: st.rowsOf("apps", function (r) { return r.type !== "path" }) } }
        } }

    // ── Backups (form/backup.py): GET /backup is the status, the backups in the folder and Recently deleted ─────────
    property var bk: null
    function loadBackup() { Store.get("/backup").then(function (r) { st.bk = r }, function () {}) }
    Timer { interval: 1500; repeat: true; running: st.tab === "backups" && !!st.bk && st.bk.running; onTriggered: st.loadBackup() }
    readonly property bool bkSaved: !!st.bk && (!!st.bk.settings.folder || !!st.bk.settings.git_remote)
    function backupNow() {
        Store.post("/backup/run", {}).then(function () {
            Store.toast("Backing up", "Every design and conversation, then every file is read back and checked.")
            st.bk = Object.assign({}, st.bk, { running: true }) }, Store.fail) }
    function verifyBackup(name) {
        Store.post("/backup/verify", { name: name }).then(function (r) {
            Store.toast(r.ok ? "Backup verified" : "This backup is damaged",
                        r.ok ? F.plural(r.checked, "file") + " match their SHA-256"
                             : r.damaged.length + " damaged, " + r.missing.length + " missing, " + r.extra.length + " unexpected") }, Store.fail) }
    function restoreBackup(name) {
        Store.post("/backup/restore", { name: name }).then(function (r) {
            Store.toast(r.restored.length ? "Restored " + F.plural(r.restored.length, "design") : "Nothing to restore",
                        r.skipped.length ? F.plural(r.skipped.length, "design") + " already here, kept as they are." : "Every file was checked against the backup first.")
            Store.reloadStudio(); st.loadBackup() }, Store.fail) }
    function undelete(entry) {
        Store.post("/backup/undelete", { entry: entry }).then(function (r) {
            Store.toast("Put back", (r.renamed_from ? "As " + r.id + ": the name was taken. " : "")
                        + (r.conversations_reattached ? F.plural(r.conversations_reattached, "conversation") + " attached again." : ""))
            Store.reloadStudio(); st.loadBackup() }, Store.fail) }
    // one quiet row of a list on glass: a title, one fine line, its actions on the right
    component BkRow: Item {
        id: br
        property string title: ""
        property string line: ""
        property bool mono: false
        property color lineColor: Theme.ink3
        default property alias actions: acts.data
        width: parent ? parent.width : 0; height: 52
        Column { x: 18; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36 - acts.width - 12; spacing: 3
            Txt { text: br.title; mono: br.mono; font.weight: Theme.wMedium; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
            Txt { kind: "fine"; text: br.line; color: br.lineColor; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
        Row { id: acts; anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 6 }
    }
    Component { id: backupsPage
        Column { spacing: 26
            Component.onCompleted: st.loadBackup()
            Group { title: "Now"; sub: st.bk ? st.bk.note : ""
                Rectangle { id: bkNow; objectName: "settingsBackupStatus"; width: parent.width; height: 72; radius: 16; color: Theme.glass
                    readonly property var last: st.bk ? st.bk.last : null
                    readonly property var ok: st.bk ? st.bk.last_ok : null
                    Rectangle { x: 18; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: Theme.rMd; color: Theme.glass2
                        Icon { name: "archive"; size: 17; anchors.centerIn: parent; color: Theme.ink2 } }
                    Column { x: 70; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 70 - nowBtn.width - 36; spacing: 3
                        Txt { width: parent.width; font.weight: Theme.wMedium; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: !st.bk ? "Reading…" : st.bk.running ? "Backing up…"
                                : bkNow.ok ? "Last backup " + F.ago(bkNow.ok.ts)
                                    + (bkNow.ok.folder ? " · " + F.bytes(bkNow.ok.folder.bytes) + " · " + (bkNow.ok.folder.verified ? "every file verified" : "not verified") : "")
                                    + (bkNow.ok.git ? " · pushed to Git" : "")
                                : "No backup yet" }
                        Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            color: st.bk && (st.bk.problem || (bkNow.last && !bkNow.last.ok)) ? Theme.amber : Theme.ink3
                            text: !st.bk ? "" : st.bk.problem ? st.bk.problem.message + " " + st.bk.problem.hint
                                : bkNow.last && !bkNow.last.ok && bkNow.last.error ? "The last run did not finish: " + bkNow.last.error.message
                                : !st.bkSaved ? "Choose a backup folder below, then save."
                                : !st.bk.settings.enabled ? "Automatic backups are off: back up by hand, or turn them on below."
                                : st.bk.next ? (st.bk.due ? "Due now: the next one starts within minutes" : "Next in about " + F.dur(Math.max(60, st.bk.next - Date.now() / 1000))) + ", while Form Studio is open"
                                : "" } }
                    Btn { id: nowBtn; objectName: "backupNow"; anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter
                        small: true; kind: "primary"; icon: "archive"; text: "Back up now"; busy: !!st.bk && st.bk.running
                        enabled: st.bkSaved && !(st.bk && st.bk.running) && st.dirtyIn("backups") === 0
                        tip: st.dirtyIn("backups") ? "Save your changes first" : ""
                        onClicked: st.backupNow() } } }
            Group { title: "Schedule and folder"; sub: "Each backup is one .zip file with the SHA-256 of every file in it."
                SettingsRows { sheet: st; rows: st.rowsOf("backups", function (r) { return r.key.indexOf("backup.git") !== 0 }) } }
            Group { title: "Git repository"; sub: "Optional: a private repository you created. Pushed with your own Git sign-in; Form Studio never creates one and never stores a password."
                SettingsRows { sheet: st; rows: st.rowsOf("backups", function (r) { return r.key.indexOf("backup.git") === 0 }) } }
            Group { title: "Backups in the folder"; visible: !!st.bk && st.bk.count > 0
                sub: st.bk ? F.plural(st.bk.count, "backup") + " · " + F.bytes(st.bk.bytes) + ". Restore puts back the designs and conversations that are not here; nothing here is overwritten." : ""
                Rectangle { width: parent.width; height: bkList.implicitHeight + 8; radius: 16; color: Theme.glass
                    Column { id: bkList; y: 4; width: parent.width
                        Repeater { model: st.bk ? st.bk.backups.slice(0, 8) : []
                            BkRow { id: bkRow; required property var modelData
                                title: modelData.name; mono: true; line: F.bytes(modelData.bytes) + " · " + F.ago(modelData.mtime)
                                Btn { small: true; kind: "quiet"; icon: "shield_check"; text: "Verify"; onClicked: st.verifyBackup(bkRow.modelData.name) }
                                Btn { small: true; kind: "quiet"; icon: "history"; text: "Restore"; onClicked: st.restoreBackup(bkRow.modelData.name) } } } } } }
            Group { title: "Recently deleted"; sub: "Deleted designs stay here for 30 days. After that, one leaves only when a verified backup holds it."
                Txt { visible: !!st.bk && st.bk.deleted.length === 0; kind: "fine"; tone: 3; text: "Nothing deleted." }
                Rectangle { objectName: "backupDeleted"; visible: !!st.bk && st.bk.deleted.length > 0; width: parent.width; height: delList.implicitHeight + 8; radius: 16; color: Theme.glass
                    Column { id: delList; y: 4; width: parent.width
                        Repeater { model: st.bk ? st.bk.deleted : []
                            BkRow { id: delRow; required property var modelData
                                title: modelData.name
                                line: "Deleted " + F.ago(modelData.deleted_ts) + " · "
                                      + (modelData.expired ? "kept: no backup holds it yet" : F.plural(modelData.days_left, "day") + " left")
                                      + (modelData.backup ? " · in " + modelData.backup : "")
                                lineColor: modelData.expired ? Theme.amber : Theme.ink3
                                Btn { small: true; kind: "quiet"; icon: "rotate_ccw"; text: "Put back"; onClicked: st.undelete(delRow.modelData.entry) } } } } } }
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
