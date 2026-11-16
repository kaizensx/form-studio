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
    property int sheetWidth: 820
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    property string tab: props.tab || "general"
    property var edits: ({})                   // key → new value, not yet saved
    property int rev: 0                        // bumped on Revert and Save so the fields show the stored values again
    readonly property var cfg: Store.config
    readonly property int dirty: F.keys(edits).length
    readonly property var rows: cfg ? cfg.settings.filter(function (r) { return r.tab === st.tab }) : []
    spacing: 14; bottomPadding: 20
    Component.onCompleted: { if (!Store.config) Store.loadConfig(); if (!Store.software) Store.checkSoftware() }

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

    Seg { value: st.tab; onPicked: function (v) { st.tab = v }
        model: [{ value: "general", text: "General" }, { value: "printer", text: "Printer and slicer" }, { value: "chat", text: "Chat" },
                { value: "apps", text: "Other apps" }, { value: "software", text: "Software" }] }

    // ── settings tabs ───────────────────────────────────────
    Column { visible: st.tab !== "software"; width: parent.width; spacing: 14
        Txt { visible: !st.cfg; tone: 2; text: "Reading the settings…" }
        Note { visible: st.tab === "printer" && Store.slicer.available; kind: "plain"
            title: "The slicer decides the printer"
            text: "FORM follows the printer, filament and process selected in " + (Store.slicer.label || "the slicer") + " (now: " +
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
                        width: list.width; height: Math.max(left.implicitHeight, 28) + 24
                        Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Rectangle { visible: row.changed; x: 0; y: 10; width: 2; height: parent.height - 20; color: Theme.blueprint }
                        Column { id: left; x: 16; width: parent.width * 0.5 - 24; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Txt { text: row.r.label; width: parent.width; font.weight: 550 }
                            Txt { kind: "fine"; visible: !!row.r.help; text: row.r.help || ""; width: parent.width }
                            Txt { kind: "fine"; tone: 4; mono: true; font.pixelSize: 10; text: row.r.key + (row.r.in_file ? "" : "  ·  default") } }
                        Row { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            // true / false
                            Row { visible: row.r.type === "bool"; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                                Txt { kind: "fine"; text: row.v ? "on" : "off"; anchors.verticalCenter: parent.verticalCenter }
                                Check { checked: !!row.v; anchors.verticalCenter: parent.verticalCenter; onToggled: function (on) { st.setEdit(row.r, on) } } }
                            // one of
                            Pick { visible: row.r.type === "choice"; width: 200; value: row.v
                                model: (row.r.choices || []).map(function (c) { return { value: c, text: ({ auto: "Automatic", bambu: "Bambu Studio", orca: "OrcaSlicer", prusa: "PrusaSlicer", superslicer: "SuperSlicer", qidi: "QIDI Studio" })[c] || c } })
                                onPicked: function (val) { st.setEdit(row.r, val) } }
                            // text and paths
                            Field { visible: row.r.type === "str" || row.r.type === "path"; width: row.r.type === "path" ? 270 : 300
                                text: (st.rev, row.r.type === "path" ? String(row.v === null || row.v === undefined ? "" : row.v) : String(row.r.value === null || row.r.value === undefined ? "" : row.r.value)); mono: row.r.type === "path"
                                placeholder: row.r.type === "path" && row.r.key !== "data.dir" ? "found automatically" : ""
                                onEdited: function (t) { st.setEdit(row.r, t) } }
                            Btn { visible: row.r.type === "path"; small: true; icon: "folder_open"; tip: "Choose…"; anchors.verticalCenter: parent.verticalCenter
                                onClicked: { st.pathRow = row.r; if (row.r.key === "data.dir") folderDlg.open(); else fileDlg.open() } }
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
        Row { visible: st.tab === "printer"; spacing: 8
            Btn { small: true; icon: "printer"; text: "Compare slicers…"; onClicked: Store.openSheet("slicer") }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: "Shows every slicer FORM knows and the presets each would use." } }
        // save bar
        Item { width: parent.width; height: 30
            Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Btn { kind: "primary"; icon: "check"; enabled: st.dirty > 0; text: st.dirty ? "Save changes (" + st.dirty + ")" : "Save changes"; onClicked: st.save() }
                Btn { kind: "quiet"; text: "Revert"; visible: st.dirty > 0; onClicked: { st.edits = ({}); st.rev++ } } }
            Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; width: parent.width - 300; horizontalAlignment: Text.AlignRight
                elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                text: st.cfg ? (st.cfg.exists ? "Saved to " : "Will create ") + st.cfg.path_short + "  ·  a backup copy is kept on every save" : "" } }
        Txt { visible: !!st.cfg && st.cfg.env_overrides.length > 0; kind: "fine"; width: parent.width; color: Theme.amber
            text: st.cfg ? "Set outside the file for this run: " + st.cfg.env_overrides.join(", ") + ". Those win over the values here." : "" }
    }

    // ── software ───────────────────────────────────────────
    SoftwarePanel { visible: st.tab === "software"; width: parent.width }
}
