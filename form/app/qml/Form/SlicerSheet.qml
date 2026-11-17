import QtQuick
import FormNative
import "F.js" as F

// Which slicer program FORM drives: every one FORM knows, whether it is installed, and the presets it would use.
// Switching writes only [slicer].kind to studio.toml (after a backup). The slice then goes stale.
Column {
    id: ss
    property string title: "Slicer"
    property string note: "The program FORM slices with on this computer"
    property int sheetWidth: Theme.sheetM
    property var info: null                     // GET /studio/slicers → { chosen, config, slicers: [...] }
    property var error: null
    property bool loading: false
    property string busy: ""                    // kind being switched to
    readonly property var all: info ? info.slicers : []
    readonly property var main: all.filter(function (s) { return s.installed || ["bambu", "orca", "prusa"].indexOf(s.kind) >= 0 })
    readonly property var rest: all.filter(function (s) { return main.indexOf(s) < 0 })
    readonly property var active: all.filter(function (s) { return s.active })[0] || null
    readonly property bool isAuto: !!info && info.chosen === "auto"
    spacing: 14

    function load() {
        loading = true
        Store.get("/studio/slicers").then(function (r) { ss.info = r; ss.error = null; ss.loading = false },
                                          function (e) { ss.error = e; ss.loading = false; if (ss.info) Store.fail(e) })
    }
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

    // where the choice is written, and a way to look again after installing a slicer
    property Component footerLeft: Txt { kind: "fine"; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; verticalAlignment: Text.AlignVCenter
        text: ss.info ? "Choosing writes only [slicer].kind to " + ss.info.config + ", after a backup." : ss.loading ? "Looking for slicers…" : "" }
    property Component footer: Row { spacing: 8
        Btn { icon: "refresh_cw"; text: "Look again"; busy: ss.loading; enabled: ss.busy === ""; onClicked: ss.load() } }

    Txt { tone: 2; width: parent.width
        text: "FORM slices with one slicer program on this computer and reads the printer, filament and process presets selected in it. Changing the slicer makes the current slice stale; nothing is sliced until the pipeline runs." }

    // loading and error
    Row { visible: !ss.info && !ss.error; spacing: 8; height: 40
        Spinner { anchors.verticalCenter: parent.verticalCenter }
        Txt { tone: 2; text: "Looking for slicers…"; anchors.verticalCenter: parent.verticalCenter } }
    Note { visible: !ss.info && !!ss.error; kind: "red"; title: ss.error ? ss.error.message || "Could not look for slicers" : ""
        text: ss.error && ss.error.hint ? ss.error.hint : "Nothing was changed."
        Btn { small: true; icon: "refresh_cw"; text: "Try again"; onClicked: ss.load() } }

    Column { width: parent.width; spacing: 8; visible: !!ss.info
        Repeater { model: ss.main
            Rectangle { id: card; required property var modelData
                readonly property var s: modelData
                width: parent.width; radius: Theme.rMd
                implicitHeight: body.implicitHeight + 24
                color: s.active ? Theme.alpha(Theme.datum, 0.06) : ch.hovered && s.installed ? Theme.plate3 : Theme.plate1
                border.color: s.active ? Theme.alpha(Theme.datum, 0.5) : ch.hovered && s.installed ? Theme.rule2 : Theme.rule
                Behavior on color { Tint {} }
                HoverHandler { id: ch }
                Column { id: body; x: 16; y: 12; width: parent.width - 32; spacing: 6
                    Item { width: parent.width; height: 28
                        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                            Icon { name: "printer"; size: 15; color: card.s.active ? Theme.datum : card.s.installed ? Theme.ink2 : Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
                            Txt { text: card.s.label; font.weight: Theme.wSemi; tone: card.s.installed ? 1 : 3; anchors.verticalCenter: parent.verticalCenter }
                            Txt { visible: !!card.s.version; mono: true; kind: "fine"; text: card.s.version || ""; anchors.verticalCenter: parent.verticalCenter }
                            Tag { anchors.verticalCenter: parent.verticalCenter
                                kind: card.s.active && card.s.available ? "PASS" : card.s.active ? "WARN" : card.s.installed ? "specified" : ""
                                text: card.s.active ? (ss.isAuto ? "in use · automatic" : "in use") : card.s.installed ? "installed" : "not installed" } }
                        Btn { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; small: true
                            visible: card.s.installed && !(card.s.active && !ss.isAuto)
                            kind: card.s.active ? "quiet" : "default"
                            icon: card.s.active ? "pin" : ""
                            text: card.s.active ? "Pin this one" : "Use " + card.s.label
                            busy: ss.busy === card.s.kind
                            tip: card.s.active ? "Keep using it even if another slicer is installed later" : ""
                            enabled: ss.busy === "" || ss.busy === card.s.kind; onClicked: ss.choose(card.s.kind) } }
                    Column { width: parent.width; spacing: 2; visible: card.s.available
                        Txt { width: parent.width; text: ss.presetLine(card.s); wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Txt { kind: "fine"; width: parent.width
                            text: "Printer · filament · process, from " + ((card.s.source && card.s.source.machine) || "the slicer") +
                                  (card.s.envelope_mm ? " · bed " + card.s.envelope_mm.map(function (x) { return F.fmt(x, 0) }).join(" × ") + " mm" : "") } }
                    Txt { kind: "fine"; width: parent.width; visible: card.s.installed && !card.s.available; color: Theme.amber; text: card.s.reason || "" }
                    Column { width: parent.width; spacing: 6; visible: !card.s.installed && !!card.s.install
                        Txt { kind: "fine"; width: parent.width; text: card.s.install ? "Not found on this computer. " + card.s.install.note + "." : "" }
                        Rectangle { visible: !!card.s.install && card.s.install.cmds.length > 0; width: parent.width; height: cmds.implicitHeight + 16; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
                            Column { id: cmds; x: 10; y: 8; width: parent.width - 20; spacing: 3
                                Repeater { model: card.s.install ? card.s.install.cmds : []
                                    Txt { required property var modelData; mono: true; font.pixelSize: 11; tone: 3; width: parent.width; wrapMode: Text.WrapAnywhere; text: modelData } } } } } } } }

        // automatic: takes effect at once. Turning it off pins the slicer in use.
        Rectangle { width: parent.width; height: 52; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
            Column { x: 16; width: parent.width - 32 - 46; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Txt { text: "Automatic"; font.weight: Theme.wMedium }
                Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: "Uses the first installed of Bambu Studio, OrcaSlicer, PrusaSlicer." } }
            Toggle { checked: ss.isAuto; enabled: ss.busy === "" && (!ss.isAuto || !!ss.active)
                anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
                onToggled: function (c) { if (c) ss.choose("auto"); else if (ss.active) ss.choose(ss.active.kind) } } }
    }

    Txt { kind: "fine"; width: parent.width; visible: ss.rest.length > 0
        text: "Also supported, not installed: " + ss.rest.map(function (s) { return s.label }).join(", ") + " (same formats as PrusaSlicer)." }

    Txt { kind: "fine"; width: parent.width; visible: !!ss.info
        text: "Presets are chosen in the slicer itself, or pinned in studio.toml." }
}
