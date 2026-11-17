import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Settings: everything you would otherwise edit in studio.toml, plus the Software tab (the installer registry).
// Edits collect in `edits` and are written by "Save changes": only the changed keys are rewritten, comments and
// other keys stay, and the previous file is kept as a backup next to it (form/config_edit.py).
// Open with Store.openSettings("general" | "printer" | "chat" | "apps" | "software").
Column {
    id: st
    property string title: "Settings"
    property int sheetWidth: Theme.sheetL
    property int sheetHeight: 520
    readonly property var tabs: [{ value: "general", text: "General" }, { value: "printer", text: "Printer and slicer" }, { value: "chat", text: "Chat" },
                                 { value: "apps", text: "Other apps" }, { value: "software", text: "Software", badge: Store.setupAttention && Store.setupAttention.length ? Store.setupAttention.length : 0 }]
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
    property string tab: props.tab || "general"
    property var edits: ({})                   // key → new value, not yet saved
    property int rev: 0                        // bumped on Revert and Save so the fields show the stored values again
    readonly property var cfg: Store.config
    readonly property int dirty: F.keys(edits).length
    readonly property var rows: cfg ? cfg.settings.filter(function (r) { return r.tab === st.tab }) : []
    spacing: 14
    Component.onCompleted: { if (!Store.config) Store.loadConfig(); if (!Store.software) Store.checkSoftware(); st.loadKeys() }

    // agent keys (Gemini): kept by FORM in a private file, never shown back; only "set" or "not set" comes from the engine
    property var keys: []
    function loadKeys() { Store.get("/secrets").then(function (r) { st.keys = r.keys }, function () {}) }
    function saveKey(name, value) {
        return Store.post("/secrets", { name: name, value: value }).then(function (r) {
            st.keys = r.keys; Store.toast(r.key.label + " saved", "Kept in a private file on this computer and given only to its agent.")
            Store.checkSoftware() }, Store.fail) }
    function clearKey(name) {
        return Store.post("/secrets", { name: name, clear: true }).then(function (r) {
            st.keys = r.keys; Store.toast(r.key.label + " removed", ""); Store.checkSoftware() }, Store.fail) }

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
        Txt { visible: !st.cfg; tone: 2; text: "Reading the settings…" }
        Note { visible: st.tab === "printer" && Store.slicer.available; kind: "plain"
            title: "The slicer decides the printer"
            text: "Form Studio follows the printer, filament and process selected in " + (Store.slicer.label || "the slicer") + " (now: " +
                  (Store.slicer.available ? Store.slicer.presets.machine.name : "") + "). The name and bed size below are used only when no slicer is available." }
        Note { visible: st.tab === "chat" && !Store.chat.available; kind: "amber"; title: "Chat is not available yet"
            text: (Store.chat.note || "") + " Install Claude Code and sign in under Software."
            Btn { small: true; text: "Open Software"; onClicked: st.tab = "software" } }
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
                        Column { id: left; x: 16; width: parent.width * 0.5 - 24; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Txt { text: row.r.label; width: parent.width; font.weight: Theme.wMedium }
                            Txt { kind: "fine"; visible: !!row.r.help; text: row.r.help || ""; width: parent.width }
                            Txt { kind: "fine"; tone: 4; mono: true; font.pixelSize: 10; text: row.r.key + (row.r.in_file ? "" : "  ·  default") } }
                        Row { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            // true / false
                            Row { visible: row.r.type === "bool"; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                                Txt { kind: "fine"; text: row.v ? "on" : "off"; anchors.verticalCenter: parent.verticalCenter }
                                Toggle { checked: !!row.v; anchors.verticalCenter: parent.verticalCenter; onToggled: function (on) { st.setEdit(row.r, on) } } }
                            // one of
                            Pick { visible: row.r.type === "choice"; width: 200; value: row.v
                                model: (row.r.choices || []).map(function (c) { return { value: c, text: ({ auto: "Automatic", bambu: "Bambu Studio", orca: "OrcaSlicer", prusa: "PrusaSlicer", superslicer: "SuperSlicer", qidi: "QIDISlicer", stable: "Stable", preview: "Preview" })[c] || c } })
                                onPicked: function (val) { st.setEdit(row.r, val) } }
                            // text and paths
                            Field { visible: row.r.type === "str" || row.r.type === "path"; width: row.r.type === "path" ? 270 : 300
                                text: (st.rev, row.r.type === "path" ? String(row.v === null || row.v === undefined ? "" : row.v) : String(row.r.value === null || row.r.value === undefined ? "" : row.r.value)); mono: row.r.type === "path"
                                placeholder: row.r.type === "path" && row.r.key !== "data.dir" ? "found automatically" : ""
                                onEdited: function (t) { st.setEdit(row.r, t) } }
                            Btn { visible: row.r.type === "path"; small: true; icon: "folder_open"; tip: "Choose…"; anchors.verticalCenter: parent.verticalCenter
                                onClicked: { st.pathRow = row.r; if (row.r.key === "data.dir") Store.ask(folderDlg); else Store.ask(fileDlg) } }
                            // numbers
                            Field { visible: row.r.type === "float" || row.r.type === "int"; width: 120; numeric: true; unit: row.r.unit || ""
                                text: (st.rev, String(row.r.value))
                                onEdited: function (t) { if (t !== "" && !isNaN(Number(t))) st.setEdit(row.r, Number(t)) } }
                            // bed size: three numbers
                            Repeater { model: row.r.type === "vec3" ? 3 : 0
                                Field { required property int index
                                    width: 82; numeric: true; unit: ["X", "Y", "Z"][index]; text: (st.rev, row.r.value ? String(row.r.value[index]) : "")
                                    onEdited: function (t) { if (t !== "" && !isNaN(Number(t))) { var a = row.v.slice(); a[index] = Number(t); st.setEdit(row.r, a) } } } }
                            Txt { visible: row.r.type === "vec3"; kind: "fine"; text: "mm"; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            } }
        // ── keys: one row per agent key ─────────────────────────
        Rectangle { visible: st.tab === "chat" && st.keys.length > 0; width: parent.width; height: keyList.implicitHeight; radius: Theme.rMd
            color: Theme.plate1; border.color: Theme.rule
            Column { id: keyList; width: parent.width
                Repeater {
                    model: st.tab === "chat" ? st.keys : []
                    Item {
                        id: krow
                        required property var modelData
                        required property int index
                        readonly property var k: modelData
                        objectName: "secretRow"
                        width: keyList.width; height: Math.max(kleft.implicitHeight, 28) + 26
                        Rectangle { visible: krow.index > 0; x: 16; width: parent.width - 32; height: 1; color: Theme.rule }
                        Column { id: kleft; x: 16; width: parent.width * 0.5 - 24; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Row { spacing: 6
                                Icon { name: "lock"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                                Txt { text: krow.k.label; font.weight: Theme.wMedium } }
                            Txt { kind: "fine"; text: krow.k.help; width: parent.width }
                            Txt { kind: "fine"; width: parent.width; color: krow.k.set || krow.k.from_env ? Theme.pass : Theme.ink3
                                text: krow.k.from_env ? "Set in the environment for this run. That one is used."
                                    : krow.k.set ? "Stored privately on this computer. It is not shown again." : "Not set." } }
                        Row { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            Field { id: kf; objectName: "secretField"; visible: !krow.k.set; width: 220; placeholder: "Paste the key"; mono: true
                                input.echoMode: TextInput.Password
                                onAccepted: function (t) { if (t.trim()) st.saveKey(krow.k.name, t).then(function () { kf.text = "" }) } }
                            Btn { visible: !krow.k.set; small: true; kind: "quiet"; icon: "external_link"; text: "Get a key"
                                anchors.verticalCenter: parent.verticalCenter; onClicked: Bridge.openLink(krow.k.url) }
                            Btn { visible: !krow.k.set; small: true; kind: "primary"; text: "Save key"; enabled: kf.text.trim().length > 0
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: st.saveKey(krow.k.name, kf.text).then(function () { kf.text = "" }) }
                            Btn { visible: krow.k.set; small: true; kind: "quiet"; icon: "trash_2"; text: "Remove"
                                anchors.verticalCenter: parent.verticalCenter; onClicked: st.clearKey(krow.k.name) } }
                    }
                }
            } }
        Row { visible: st.tab === "printer"; spacing: 8
            Btn { small: true; icon: "printer"; text: "Compare slicers…"; onClicked: Store.openSheet("slicer") }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: "Shows every slicer Form Studio knows and the presets each would use." } }
    }

    // ── software ───────────────────────────────────────────
    SoftwarePanel { visible: st.tab === "software"; width: parent.width; actions: false }
}
