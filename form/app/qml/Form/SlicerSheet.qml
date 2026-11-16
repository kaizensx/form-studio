import QtQuick
import FormNative
import "F.js" as F

// Which slicer program FORM drives: every one FORM knows, whether it is installed, and the presets it would use.
// Switching writes only [slicer].kind to studio.toml (after a backup). The slice then goes stale.
Column {
    id: ss
    property string title: "Slicer"
    property int sheetWidth: 640
    property var info: null                     // GET /studio/slicers → { chosen, config, slicers: [...] }
    property string busy: ""                    // kind being switched to
    readonly property var all: info ? info.slicers : []
    readonly property var main: all.filter(function (s) { return s.installed || ["bambu", "orca", "prusa"].indexOf(s.kind) >= 0 })
    readonly property var rest: all.filter(function (s) { return main.indexOf(s) < 0 })
    readonly property var active: all.filter(function (s) { return s.active })[0] || null
    readonly property bool isAuto: !!info && info.chosen === "auto"
    spacing: 12; bottomPadding: 20

    function load() { Store.get("/studio/slicers").then(function (r) { ss.info = r }, Store.fail) }
    function choose(kind) {
        busy = kind
        Store.post("/studio/slicer", { kind: kind }).then(function (r) {
            return Store.reloadStudio().then(function () { return Store.pid ? Store.refresh() : null }).then(function () {
                ss.busy = ""; ss.load()
                Store.toast(kind === "auto" ? "Slicer: automatic" : "Slicer: " + ss.labelOf(kind),
                            "Saved in " + r.path.split(/[\\/]/).pop() + (r.backup ? " (backup kept)" : "") + ". The slice is stale until the pipeline runs again.")
            })
        }, function (e) { ss.busy = ""; Store.fail(e) })
    }
    function labelOf(kind) { for (var i = 0; i < all.length; i++) if (all[i].kind === kind) return all[i].label; return kind }
    function presetLine(s) { return [s.presets.machine, s.presets.filament, s.presets.process].filter(function (x) { return !!x }).join("  /  ") }

    Component.onCompleted: load()

    Txt { tone: 2; width: parent.width
        text: "FORM slices with one slicer program on this computer and reads the printer, filament and process presets selected in it. Changing the slicer makes the current slice stale; nothing is sliced until the pipeline runs." }

    Txt { kind: "fine"; visible: !ss.info; text: "Looking for slicers…" }

    Column { width: parent.width; spacing: 8; visible: !!ss.info
        Repeater { model: ss.main
            Rectangle { id: card; required property var modelData
                readonly property var s: modelData
                width: parent.width; radius: Theme.rMd
                implicitHeight: body.implicitHeight + 24
                color: s.active ? Theme.alpha(Theme.datum, 0.06) : Theme.plate1
                border.color: s.active ? Theme.alpha(Theme.datum, 0.5) : Theme.rule
                Column { id: body; x: 14; y: 12; width: parent.width - 28; spacing: 6
                    Item { width: parent.width; height: 28
                        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                            Icon { name: "printer"; size: 15; color: card.s.installed ? Theme.ink2 : Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
                            Txt { text: card.s.label; font.weight: 600; tone: card.s.installed ? 1 : 3; anchors.verticalCenter: parent.verticalCenter }
                            Txt { visible: !!card.s.version; mono: true; kind: "fine"; text: card.s.version || ""; anchors.verticalCenter: parent.verticalCenter }
                            Tag { anchors.verticalCenter: parent.verticalCenter
                                kind: card.s.active && card.s.available ? "PASS" : card.s.active ? "WARN" : card.s.installed ? "specified" : ""
                                text: card.s.active ? (ss.isAuto ? "in use · automatic" : "in use") : card.s.installed ? "installed" : "not installed" } }
                        Btn { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; small: true
                            visible: card.s.installed && !(card.s.active && !ss.isAuto)
                            kind: card.s.active ? "quiet" : "default"
                            text: ss.busy === card.s.kind ? "Switching…" : card.s.active ? "Pin this one" : "Use " + card.s.label
                            tip: card.s.active ? "Keep using it even if another slicer is installed later" : ""
                            enabled: ss.busy === ""; onClicked: ss.choose(card.s.kind) } }
                    Column { width: parent.width; spacing: 2; visible: card.s.available
                        Txt { width: parent.width; text: ss.presetLine(card.s); wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Txt { kind: "fine"; width: parent.width
                            text: "Printer · filament · process, from " + ((card.s.source && card.s.source.machine) || "the slicer") +
                                  (card.s.envelope_mm ? " · bed " + card.s.envelope_mm.map(function (x) { return F.fmt(x, 0) }).join(" × ") + " mm" : "") } }
                    Txt { kind: "fine"; width: parent.width; visible: card.s.installed && !card.s.available; color: Theme.amber; text: card.s.reason || "" }
                    Column { width: parent.width; spacing: 3; visible: !card.s.installed && !!card.s.install
                        Txt { kind: "fine"; width: parent.width; text: card.s.install ? "Not found on this computer. " + card.s.install.note + "." : "" }
                        Repeater { model: card.s.install ? card.s.install.cmds : []
                            Txt { required property var modelData; mono: true; font.pixelSize: 11; tone: 3; text: modelData } } } } } } }

    Txt { kind: "fine"; width: parent.width; visible: ss.rest.length > 0
        text: "Also supported, not installed: " + ss.rest.map(function (s) { return s.label }).join(", ") + " (same formats as PrusaSlicer)." }

    Item { width: parent.width; height: 30; visible: !!ss.info
        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
            Check { checked: ss.isAuto; enabled: ss.busy === "" && !ss.isAuto; anchors.verticalCenter: parent.verticalCenter
                onToggled: function (c) { if (c) ss.choose("auto") } }
            Txt { text: "Automatic"; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter
                text: "uses the first installed of Bambu Studio, OrcaSlicer, PrusaSlicer" } } }

    Txt { kind: "fine"; width: parent.width; visible: !!ss.info
        text: ss.info ? "Choosing writes only [slicer].kind to " + ss.info.config + ", after a backup. Presets are chosen in the slicer itself, or pinned in studio.toml." : "" }
}
