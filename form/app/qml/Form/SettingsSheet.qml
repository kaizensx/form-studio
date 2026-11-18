import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Settings: everything you would otherwise edit in studio.toml, plus the Software tab (the installer registry).
// Edits collect in `edits` and are written by "Save changes": only the changed keys are rewritten, comments and
// other keys stay, and the previous file is kept as a backup next to it (form/config_edit.py).
// Open with Store.openSettings("general" | "printer" (Printing) | "chat" (Agents) | "apps" | "updates" | "advanced" | "software").
// "I have a 3D printer" applies at once (it changes what the app shows); the printer itself is chosen in the printer
// picker, which writes the default printer; everything else collects in `edits`. A search filters every tab.
Column {
    id: st
    property string title: "Settings"
    property int sheetWidth: Theme.sheetL
    property int sheetHeight: 520
    readonly property var tabs: [{ value: "general", text: "General" }].concat(Store.prints ? [{ value: "printer", text: "Printing" }] : [])
        .concat([{ value: "chat", text: "Agents" }, { value: "apps", text: "Other apps" }, { value: "updates", text: "Updates" },
                 { value: "advanced", text: "Advanced" },
                 { value: "software", text: "Software", badge: Store.setupAttention && Store.setupAttention.length ? Store.setupAttention.length : 0 }])
    readonly property var tabNames: ({ general: "General", printer: "Printing", chat: "Agents", apps: "Other apps", updates: "Updates", advanced: "Advanced" })
    function accept() { if (tab !== "software" && dirty > 0) save() }
    // the action bar: what is saved where on the left, the actions on the right
    property Component footerLeft: Txt { kind: "fine"; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; verticalAlignment: Text.AlignVCenter
        color: st.tab !== "software" && st.cfg && st.cfg.env_overrides.length > 0 ? Theme.amber : Theme.ink3
        text: st.tab === "software" ? (Store.installing ? "Installing. Each command is in the log." : Store.softwareChecking ? "Looking at what is installed…" : "Nothing is installed until you press Install.")
            : !st.cfg ? ""
            : st.cfg.env_overrides.length > 0 ? "Set outside the file for this run: " + st.cfg.env_overrides.join(", ") + ". Those win."
            : (st.cfg.exists ? "Saved to " : "Will create ") + st.cfg.path_short + " · a backup is kept on every save" }
    property Component footer: Row { spacing: 8
        Btn { visible: st.tab !== "software" && st.dirty > 0; kind: "quiet"; text: "Revert"; onClicked: { st.edits = ({}); st.rev++ } }
        Btn { visible: st.tab !== "software"; kind: "primary"; icon: "check"; enabled: st.dirty > 0; keys: "Return"
            text: st.dirty ? "Save " + F.plural(st.dirty, "change") : "Saved"; onClicked: st.save() }
        Btn { visible: st.tab === "software" && Store.installing; icon: "x"; text: "Cancel"; onClicked: Store.cancelInstall() }
        Btn { visible: st.tab === "software"; icon: "refresh_cw"; text: "Check again"; busy: Store.softwareChecking; enabled: !Store.installing
            onClicked: { Store.checkSoftware(); Store.checkSetup() } }
        Btn { visible: st.tab === "software"; kind: "primary"; icon: "download"; enabled: Store.installChosen.length > 0; busy: Store.installing
            text: Store.installing ? "Installing…" : Store.installChosen.length ? "Install " + Store.installChosen.length + " selected" : "Install selected"
            onClicked: Store.installSoftware() } }
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    property string tab: props.tab === "printer" && !Store.prints ? "general" : (props.tab || "general")
    property string query: ""                  // Settings search: rows from every tab whose label, help or key match
    property var edits: ({})                   // key → new value, not yet saved
    property int rev: 0                        // bumped on Revert and Save so the fields show the stored values again
    readonly property var cfg: Store.config
    readonly property int dirty: F.keys(edits).length
    readonly property bool searching: query.trim() !== ""
    function matches(r) { var q = query.trim().toLowerCase(); return (r.label + " " + (r.help || "") + " " + r.key + " " + (st.tabNames[r.tab] || "")).toLowerCase().indexOf(q) >= 0 }
    readonly property var rows: cfg ? cfg.settings.filter(function (r) {
        if (r.hidden || r.key === "general.printing") return false
        if (r.tab === "printer" && !Store.prints) return false
        return st.searching ? st.matches(r) : r.tab === st.tab }) : []
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
    spacing: 14
    Component.onCompleted: { if (!Store.config) Store.loadConfig(); if (!Store.software) Store.checkSoftware(); st.loadKeys(); st.loadProviders()
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
    FolderDialog { id: folderDlg; title: "Choose the project folder"; onAccepted: if (st.pathRow) st.setEdit(st.pathRow, st.localPath(selectedFolder)) }
    FileDialog { id: fileDlg; title: "Choose the program"; onAccepted: if (st.pathRow) st.setEdit(st.pathRow, st.localPath(selectedFile)) }


    // ── settings tabs ───────────────────────────────────────
    Column { visible: st.tab !== "software"; width: parent.width; spacing: 14
        Field { id: search; objectName: "settingsSearch"; width: parent.width; placeholder: "Search settings"
            onEdited: function (t) { st.query = t } }
        Txt { visible: !st.cfg; tone: 2; text: "Reading the settings…" }
        Txt { visible: st.searching && st.rows.length === 0 && !!st.cfg; tone: 3; text: "No setting matches “" + st.query.trim() + "”." }
        // ── General: how this person uses Form Studio; applied at once ──
        Column { visible: st.tab === "general" && !st.searching; width: parent.width; spacing: 8
            Txt { kind: "cap"; text: "How you use Form Studio" }
            Row { id: useRow; width: parent.width; spacing: 10
                Repeater { model: [{ on: true, icon: "printer", title: "I have a 3D printer", sub: "Designs are checked against your printer and sliced. Settings › Printing appears." },
                                   { on: false, icon: "pencil", title: "I just design", sub: "No printer or slicer is needed or suggested. New designs start as 3D models." }]
                    Rectangle { id: uc; required property var modelData
                        readonly property bool sel: Store.prints === modelData.on
                        objectName: modelData.on ? "settingsPrinter" : "settingsJustDesign"   // objectName: "settingsPrinter" / objectName: "settingsJustDesign"
                        width: (useRow.width - 10) / 2; height: ut.implicitHeight + 24; radius: Theme.rMd
                        color: sel ? Theme.alpha(Theme.datum, 0.07) : um2.containsMouse ? Theme.washHover : Theme.plate1
                        border.color: sel ? Theme.datum : Theme.rule; border.width: sel ? 1.5 : 1
                        Column { id: ut; x: 14; y: 12; width: parent.width - 28; spacing: 4
                            Row { spacing: 8
                                Icon { name: uc.modelData.icon; size: 15; color: uc.sel ? Theme.datum : Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                                Txt { text: uc.modelData.title; font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter } }
                            Txt { kind: "fine"; tone: 2; width: parent.width; text: uc.modelData.sub } }
                        MouseArea { id: um2; anchors.fill: parent; hoverEnabled: true; enabled: !uc.sel; onClicked: Store.setPrinting(uc.modelData.on) } } } }
            Txt { kind: "fine"; width: parent.width
                text: "This is the default for new designs. Each design can still be made for 3D printing or as a 3D model in its Brief." } }
        // ── Printing: the default printer, picked from the printers set up in your slicers ──
        Rectangle { visible: st.tab === "printer" && !st.searching; objectName: "settingsDefaultPrinter"
            width: parent.width; height: dp.implicitHeight + 24; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
            readonly property var sl: Store.slicer || ({ available: false })
            Column { id: dp; x: 16; y: 12; width: parent.width - 32 - chooseBtn.width - 12; spacing: 3
                Txt { kind: "cap"; text: "Default printer" }
                Txt { objectName: "settingsPrinterName"; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: adopt.sl.available ? adopt.sl.presets.machine.name : "No slicer can be read" }
                Txt { kind: "fine"; width: parent.width; wrapMode: Text.Wrap
                    text: adopt.sl.available ? adopt.sl.presets.filament.name + "  ·  " + adopt.sl.presets.process.name + "  ·  " + (adopt.sl.label || "")
                          + (Store.studio && Store.studio.env.printer && Store.studio.env.printer.slicer ? "  ·  chosen in Form Studio" : "  ·  as selected in the slicer")
                        : (adopt.sl.reason || "Install a slicer under Software, or set the bed size below.") } }
            Btn { id: chooseBtn; objectName: "settingsChoosePrinter"; icon: "printer"; text: "Choose printer…"
                anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
                tip: "Every printer set up in your slicers, with its filaments and processes"; onClicked: Store.openSheet("printer") } }
        // the slicer's own selection is not chosen in Form Studio yet: one click makes the checks use its bed
        Note { id: adopt; objectName: "settingsAdoptPrinter"; width: parent.width; kind: "plain"
            readonly property var sl: Store.slicer || ({ available: false })
            readonly property var pr: Store.studio ? Store.studio.env.printer : null
            visible: st.tab === "printer" && !st.searching && !!sl.available && !!pr && !pr.machine && !!sl.envelope_mm
                     && sl.envelope_mm.map(Math.round).join() !== pr.envelope_mm.map(Math.round).join()
            title: "The checks use " + (pr ? pr.envelope_mm.join(" × ") : "") + " mm"
            text: visible ? sl.label + " slices on " + sl.presets.machine.name + " (" + sl.envelope_mm.map(function (x) { return Math.round(x) }).join(" × ") + " mm). Make it the default so the checks use the same bed." : ""
            Btn { small: true; icon: "pin"; text: "Make it the default"
                onClicked: Store.post("/printers/use", { "default": true, kind: adopt.sl.kind, machine: adopt.sl.presets.machine.name,
                                                         filament: adopt.sl.presets.filament.name, process: adopt.sl.presets.process.name })
                    .then(function () { return Store.reloadStudio() }).then(function () { Store.loadConfig(); if (Store.pid) Store.refresh().then(function () { Store.rerunIfStale() }) }, Store.fail) } }
        Note { visible: st.tab === "chat" && !st.searching && !Store.chat.available; kind: "amber"; title: "No agent is connected yet"
            text: "Chat works with the agent you choose: an agent app installed here, a model provider's API key, or a model running on this computer." }
        // ── agents: every way chat can reach a model, set up or not (agents workstream) ──
        Txt { visible: st.tab === "chat" && !st.searching; kind: "cap"; text: "Agent apps on this computer" }
        Txt { visible: st.tab === "chat" && !st.searching; kind: "fine"; width: parent.width
            text: "Each runs on its own account with Form Studio's tools. Install more under Software." }
        Rectangle { visible: st.tab === "chat" && !st.searching && st.cliAgents.length > 0; width: parent.width; height: agList.implicitHeight; radius: Theme.rMd
            color: Theme.plate1; border.color: Theme.rule
            Column { id: agList; width: parent.width
                Repeater {
                    model: st.tab === "chat" ? st.cliAgents : []
                    AgentRow { width: agList.width; a: modelData; first: index === 0; objectName: "agentRow"
                        required property var modelData
                        required property int index
                        onInstall: st.tab = "software" }
                }
            } }
        Txt { visible: st.tab === "chat" && !st.searching; kind: "cap"; text: "Model provider APIs"; topPadding: 6 }
        Txt { visible: st.tab === "chat" && !st.searching; kind: "fine"; width: parent.width
            text: "Form Studio talks to the provider directly, with its own tools; no other app is needed. A key set in your environment is found by itself. Keys you add are kept in a private file on this computer and sent only to their provider." }
        Rectangle { visible: st.tab === "chat" && !st.searching && st.apiAgents.length > 0; width: parent.width; height: apList.implicitHeight; radius: Theme.rMd
            color: Theme.plate1; border.color: Theme.rule
            Column { id: apList; width: parent.width
                Repeater {
                    model: st.tab === "chat" ? st.apiAgents : []
                    AgentRow { width: apList.width; a: modelData; first: index === 0; k: st.keyFor(modelData.key || "")
                        objectName: "secretRow"                 // every provider API row takes a key
                        required property var modelData
                        required property int index
                        onSaveKey: function (v) { return st.saveKey(modelData.key, v) }
                        onClearKey: st.clearKey(modelData.key) }
                }
            } }
        // ── providers you added by address: any server in a format Form Studio speaks ──
        Item { visible: st.tab === "chat" && !st.searching; width: parent.width; height: 30
            Txt { kind: "cap"; text: "Your providers"; anchors.bottom: parent.bottom; anchors.bottomMargin: 2 }
            Btn { objectName: "addProvider"; small: true; icon: "plus"; text: "Add a provider…"; anchors.right: parent.right
                anchors.bottom: parent.bottom; visible: st.editingProvider !== null; onClicked: st.editingProvider = null } }
        Txt { visible: st.tab === "chat" && !st.searching; kind: "fine"; width: parent.width
            text: "A model service that is not listed above, a company gateway or a server on your network. Give its address; Form Studio finds the format, the models and whether they call tools." }
        Loader { visible: st.tab === "chat" && !st.searching && active; width: parent.width; active: st.tab === "chat" && st.editingProvider !== undefined
            sourceComponent: ProviderEditor { width: parent ? parent.width : 600; editing: st.editingProvider
                onClosed: st.editingProvider = undefined
                onSaved: function (p) { st.editingProvider = undefined; st.loadProviders(); st.loadKeys(); Store.refreshAgents() } } }
        Rectangle { visible: st.tab === "chat" && !st.searching && st.providers.length > 0; width: parent.width; height: cpList.implicitHeight; radius: Theme.rMd
            color: Theme.plate1; border.color: Theme.rule
            Column { id: cpList; width: parent.width
                Repeater {
                    model: st.tab === "chat" ? st.providers : []
                    ProviderRow { width: cpList.width; p: modelData; a: st.agentOf(modelData.id); first: index === 0; objectName: "providerRow"
                        required property var modelData
                        required property int index
                        onEdit: st.editingProvider = modelData
                        onChanged: st.loadProviders() }
                }
            } }
        Item { visible: st.tab === "chat" && !st.searching; width: parent.width; height: 30
            Txt { kind: "cap"; text: "Local models"; anchors.bottom: parent.bottom; anchors.bottomMargin: 2 }
            Btn { small: true; kind: "quiet"; icon: "refresh_cw"; text: "Look again"; busy: Store.agentsChecking; anchors.right: parent.right
                anchors.bottom: parent.bottom; onClicked: Store.refreshAgents() } }
        Txt { visible: st.tab === "chat" && !st.searching; kind: "fine"; width: parent.width
            text: "Servers on this computer, found on their usual ports. Nothing leaves this computer. The model must support tool calls." }
        Rectangle { visible: st.tab === "chat" && !st.searching && st.localAgents.length > 0; width: parent.width; height: loList.implicitHeight; radius: Theme.rMd
            color: Theme.plate1; border.color: Theme.rule
            Column { id: loList; width: parent.width
                Repeater {
                    model: st.tab === "chat" ? st.localAgents : []
                    AgentRow { width: loList.width; a: modelData; first: index === 0; objectName: "localRow"
                        required property var modelData
                        required property int index }
                }
            } }
        Txt { visible: st.tab === "chat" && !st.searching && st.rows.length > 0; kind: "cap"; text: "Defaults for new conversations" }
        Rectangle { visible: st.rows.length > 0; width: parent.width; height: list.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
            Column { id: list; width: parent.width
                Repeater {
                    model: st.rows
                    Item {
                        id: row
                        required property var modelData
                        required property int index
                        readonly property var r: modelData
                        readonly property var v: st.current(r)
                        readonly property bool changed: st.edits[r.key] !== undefined
                        width: list.width; height: Math.max(left.implicitHeight, 28) + 26
                        Rectangle { visible: row.index > 0; x: 16; width: parent.width - 32; height: 1; color: Theme.rule }
                        Rectangle { visible: row.changed; x: 5; y: 14; width: 3; height: parent.height - 28; radius: 2; color: Theme.blueprint }
                        readonly property bool hasPath: typeof row.r.detected === "string"
                        readonly property string found: row.hasPath ? row.r.detected : ""
                        Column { id: left; x: 16; width: parent.width * 0.5 - 24; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Txt { text: (st.searching ? (st.tabNames[row.r.tab] || "") + "  ›  " : "") + row.r.label; width: parent.width; font.weight: Theme.wMedium }
                            Txt { kind: "fine"; visible: !!row.r.unlocks; text: "Unlocks: " + (row.r.unlocks || ""); width: parent.width; color: Theme.ink2 }
                            Txt { kind: "fine"; visible: !!row.r.help; text: row.r.help || ""; width: parent.width }
                            Txt { kind: "fine"; visible: row.hasPath; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                                color: row.found ? Theme.pass : Theme.ink3; text: row.found ? "Found: " + row.found : "Not found on this computer" }
                            Txt { visible: row.r.tab === "advanced"; kind: "fine"; tone: 4; mono: true; font.pixelSize: 10; text: row.r.key } }   // the file key only where people edit the file itself
                        Row { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            // true / false
                            Row { visible: row.r.type === "bool"; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                                Txt { kind: "fine"; text: row.v ? "on" : "off"; anchors.verticalCenter: parent.verticalCenter }
                                Toggle { checked: !!row.v; anchors.verticalCenter: parent.verticalCenter; onToggled: function (on) { st.setEdit(row.r, on) } } }
                            // reset to the default
                            Btn { visible: !st.isDefault(row.r) && row.r["default"] !== undefined && row.r["default"] !== null && row.r.key !== "data.dir"
                                small: true; kind: "quiet"; icon: "rotate_ccw"; tip: "Reset to the default (" + (Array.isArray(row.r["default"]) ? row.r["default"].join(" × ") : String(row.r["default"]) || "empty") + ")"
                                anchors.verticalCenter: parent.verticalCenter; onClicked: { st.setEdit(row.r, row.r["default"]); st.rev++ } }
                            // one of
                            Pick { visible: row.r.type === "choice"; width: 220; value: row.v
                                model: (row.r.choices || []).map(function (c) {
                                    var t = ({ auto: "Automatic", bambu: "Bambu Studio", orca: "OrcaSlicer", prusa: "PrusaSlicer", superslicer: "SuperSlicer", qidi: "QIDISlicer", elegoo: "ElegooSlicer", snapmaker: "Snapmaker Orca", stable: "Stable", preview: "Preview" })[c] || c
                                    return { value: c, text: t + (row.r.detected && typeof row.r.detected !== "string" && row.r.detected.indexOf(c) >= 0 ? "  · installed" : "") } })
                                onPicked: function (val) { st.setEdit(row.r, val) } }
                            // agents, models and efforts: picked from what is set up here
                            Pick { visible: row.r.type === "agent"; width: 300; value: row.v || ""; model: row.r.type === "agent" ? st.agentChoices() : []
                                onPicked: function (val) { st.setEdit(row.r, val) } }
                            Pick { visible: row.r.type === "model"; width: 300; value: row.v || "default"; model: row.r.type === "model" ? st.modelChoices(row.v) : []
                                onPicked: function (val) { st.setEdit(row.r, val) } }
                            Pick { visible: row.r.type === "effort"; width: 300; value: row.v || ""; model: row.r.type === "effort" ? st.effortChoices(row.v) : []
                                onPicked: function (val) { st.setEdit(row.r, val) } }
                            // text and paths
                            Field { visible: row.r.type === "str" || row.r.type === "path"; width: row.r.type === "path" ? 270 : 300
                                text: (st.rev, String(row.v === null || row.v === undefined ? "" : row.v)); mono: row.r.type === "path"
                                placeholder: row.r.type === "path" && row.r.key !== "data.dir" ? (row.found ? row.found : "not found: choose…") : ""
                                onEdited: function (t) { st.setEdit(row.r, t) } }
                            Btn { visible: row.r.type === "path"; small: true; icon: "folder_open"; tip: "Choose…"; anchors.verticalCenter: parent.verticalCenter
                                onClicked: { st.pathRow = row.r; if (row.r.key === "data.dir") Store.ask(folderDlg); else Store.ask(fileDlg) } }
                            // numbers
                            Field { visible: row.r.type === "float" || row.r.type === "int"; width: 120; numeric: true; unit: row.r.unit || ""
                                text: (st.rev, String(row.v))
                                onEdited: function (t) { error = st.rangeError(row.r, t); if (!error) st.setEdit(row.r, Number(t)) } }
                            // bed size: three numbers
                            Repeater { model: row.r.type === "vec3" ? 3 : 0
                                Field { required property int index
                                    width: 82; numeric: true; unit: ["X", "Y", "Z"][index]; text: (st.rev, row.v ? String(row.v[index]) : "")
                                    onEdited: function (t) { error = st.rangeError(row.r, t); if (!error) { var a = row.v.slice(); a[index] = Number(t); st.setEdit(row.r, a) } } } }
                            Txt { visible: row.r.type === "vec3"; kind: "fine"; text: "mm"; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            } }
        Row { visible: st.tab === "printer" && !st.searching; spacing: 8
            Btn { small: true; icon: "printer"; text: "Compare slicers…"; onClicked: Store.openSheet("slicer") }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: "Shows every slicer Form Studio knows and the presets each would use." } }
    }

    // ── software ───────────────────────────────────────────
    SoftwarePanel { visible: st.tab === "software"; width: parent.width; actions: false }
}
