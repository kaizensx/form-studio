import QtQuick
import FormNative

// One card of settings rows in Settings, on thin glass: a label and what it does on the left, its control on the
// right; rows are set apart by their own air. `rows` are entries of GET /config (form/config_edit.py describe); `sheet` is the Settings sheet, which
// keeps the pending edits (current, setEdit, isDefault, rangeError, the choices of agents, models and efforts, and the
// file and folder pickers). A row with an unsaved change carries a blue bar at its left edge.
Rectangle {
    id: rc
    property var rows: []
    property var sheet: null
    visible: !!rows && rows.length > 0
    width: parent ? parent.width : 0
    height: list.implicitHeight + 8; radius: 16; color: Theme.glass
    Column { id: list; y: 4; width: parent.width
        Repeater {
            model: rc.rows
            Item {
                id: row
                required property var modelData
                required property int index
                readonly property var r: modelData
                readonly property var v: rc.sheet.current(r)
                readonly property bool changed: rc.sheet.edits[r.key] !== undefined
                readonly property bool wide: r.type === "path" || r.type === "str" || r.type === "agent" || r.type === "model" || r.type === "effort" || r.type === "vec3"
                width: list.width; height: Math.max(left.implicitHeight, 28) + 24
                Rectangle { visible: row.changed; x: 7; y: 14; width: 3; height: parent.height - 28; radius: 2; color: Theme.blueprint }
                readonly property bool hasPath: typeof row.r.detected === "string"
                readonly property string found: row.hasPath ? row.r.detected : ""
                Column { id: left; x: 18; width: parent.width - 36 - ctl.width - 20; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                    Txt { text: (rc.sheet.searching ? (rc.sheet.tabNames[row.r.tab] || "") + "  ›  " : "") + row.r.label; width: parent.width; font.weight: Theme.wMedium }
                    Txt { kind: "fine"; visible: !!row.r.unlocks; text: "Unlocks: " + (row.r.unlocks || ""); width: parent.width; color: Theme.ink2 }
                    Txt { kind: "fine"; visible: !!row.r.help; text: row.r.help || ""; width: parent.width }
                    Txt { kind: "fine"; visible: row.hasPath; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                        color: row.found ? Theme.pass : Theme.ink3; text: row.found ? "Found: " + row.found : "Not found on this computer" }
                    Txt { visible: row.r.tab === "advanced"; kind: "fine"; tone: 4; mono: true; font.pixelSize: 11; text: row.r.key } }   // the file key only where people edit the file itself
                Row { id: ctl; anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    // reset to the default
                    Btn { visible: !rc.sheet.isDefault(row.r) && row.r["default"] !== undefined && row.r["default"] !== null && row.r.key !== "data.dir"
                        small: true; kind: "quiet"; icon: "rotate_ccw"; tip: "Reset to the default (" + (Array.isArray(row.r["default"]) ? row.r["default"].join(" × ") : String(row.r["default"]) || "empty") + ")"
                        anchors.verticalCenter: parent.verticalCenter; onClicked: { rc.sheet.setEdit(row.r, row.r["default"]); rc.sheet.rev++ } }
                    // true / false
                    Toggle { visible: row.r.type === "bool"; checked: !!row.v; anchors.verticalCenter: parent.verticalCenter; onToggled: function (on) { rc.sheet.setEdit(row.r, on) } }
                    // one of
                    Pick { visible: row.r.type === "choice"; width: 220; value: row.v
                        model: (row.r.choices || []).map(function (c) {
                            var t = ({ auto: "Automatic", bambu: "Bambu Studio", orca: "OrcaSlicer", prusa: "PrusaSlicer", superslicer: "SuperSlicer", qidi: "QIDISlicer", elegoo: "ElegooSlicer", snapmaker: "Snapmaker Orca", stable: "Stable", preview: "Preview", model: "A 3D model", print: "3D printing", hourly: "Every hour", daily: "Every day", weekly: "Every week" })[c] || c
                            return { value: c, text: t + (row.r.detected && typeof row.r.detected !== "string" && row.r.detected.indexOf(c) >= 0 ? "  · installed" : "") } })
                        onPicked: function (val) { rc.sheet.setEdit(row.r, val) } }
                    // agents, models and efforts: picked from what is set up here
                    Pick { visible: row.r.type === "agent"; width: 280; value: row.v || ""; model: row.r.type === "agent" ? rc.sheet.agentChoices() : []
                        onPicked: function (val) { rc.sheet.setEdit(row.r, val) } }
                    Pick { visible: row.r.type === "model"; width: 280; value: row.v || "default"; model: row.r.type === "model" ? rc.sheet.modelChoices(row.v) : []
                        onPicked: function (val) { rc.sheet.setEdit(row.r, val) } }
                    Pick { visible: row.r.type === "effort"; width: 280; value: row.v || ""; model: row.r.type === "effort" ? rc.sheet.effortChoices(row.v) : []
                        onPicked: function (val) { rc.sheet.setEdit(row.r, val) } }
                    // text and paths
                    Field { visible: row.r.type === "str" || row.r.type === "path"; width: row.r.type === "path" ? 250 : 280
                        text: (rc.sheet.rev, String(row.v === null || row.v === undefined ? "" : row.v)); mono: row.r.type === "path"
                        placeholder: row.r.key === "backup.folder" ? "choose a folder…" : row.r.type === "path" && row.r.key !== "data.dir" ? (row.found ? row.found : "not found: choose…") : ""
                        onEdited: function (t) { rc.sheet.setEdit(row.r, t) } }
                    Btn { visible: row.r.type === "path"; small: true; icon: "folder_open"; tip: "Choose…"; anchors.verticalCenter: parent.verticalCenter
                        onClicked: rc.sheet.choosePath(row.r) }
                    // numbers
                    Field { visible: row.r.type === "float" || row.r.type === "int"; width: 120; numeric: true; unit: row.r.unit || ""
                        text: (rc.sheet.rev, String(row.v))
                        onEdited: function (t) { error = rc.sheet.rangeError(row.r, t); if (!error) rc.sheet.setEdit(row.r, Number(t)) } }
                    // bed size: three numbers
                    Repeater { model: row.r.type === "vec3" ? 3 : 0
                        Field { required property int index
                            width: 82; numeric: true; unit: ["X", "Y", "Z"][index]; text: (rc.sheet.rev, row.v ? String(row.v[index]) : "")
                            onEdited: function (t) { error = rc.sheet.rangeError(row.r, t); if (!error) { var a = row.v.slice(); a[index] = Number(t); rc.sheet.setEdit(row.r, a) } } } }
                    Txt { visible: row.r.type === "vec3"; kind: "fine"; text: "mm"; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }
    }
}
