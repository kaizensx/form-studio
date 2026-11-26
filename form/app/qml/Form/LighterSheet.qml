import QtQuick
import QtQuick.Controls
import FormNative
import "F.js" as F

// Make it lighter (form/lighten.py). Search builds a ladder of thinner walls and bigger pockets in the kernel, takes
// the lightest through the real checks and slicer, and slices lower infill and one wall fewer. Only candidates that
// keep every passing check passing are listed, each with its computed mass and the slicer's grams before and after,
// and its checks. Apply keeps the chosen one: geometry as a new revision, print settings as this design's own.
Column {
    id: ls
    objectName: "lighterSheet"
    property string title: "Make it lighter"
    property string note: Store.project ? Store.project.name + " · " + F.pad(Store.project.head) : ""
    property int sheetWidth: Theme.sheetL
    property string chosen: ""
    readonly property var r: Store.lighter
    readonly property var cands: r ? r.candidates : []
    readonly property var pick: { for (var i = 0; i < cands.length; i++) if (cands[i].id === chosen) return cands[i]; return null }
    readonly property bool stale: !!r && !!Store.project && r.rev !== Store.project.head
    readonly property string key: Store.pid + ":" + (Store.project ? Store.project.head : 0)
    onKeyChanged: Store.loadLighter()
    Component.onCompleted: Store.loadLighter()
    onCandsChanged: chosen = cands.length ? cands[0].id : ""
    spacing: 14

    function g(x) { return x === null || x === undefined ? "–" : F.fmt(x, 1) + " g" }
    function describe(c) {
        var out = []
        for (var k in (c.changes || {})) out.push(((c.labels || {})[k] || k) + " " + F.fmt(c.changes[k], 2) + " mm")
        for (var s in (c.settings || {})) out.push(s === "infill" ? "infill " + F.fmt(c.was[s], 0) + " → " + F.fmt(c.settings[s], 0) + " %"
                                                   : F.fmt(c.was[s], 0) + " → " + F.fmt(c.settings[s], 0) + " walls")
        return out.join(" · ")
    }
    function accept() { if (pick && !stale) Store.applyLighter(pick); else Store.searchLighter() }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { objectName: "lighterSearch"; kind: ls.pick && !ls.stale ? "quiet" : "primary"; icon: "search"
            text: ls.r && !ls.stale ? "Search again" : "Search"; enabled: !Store.hasDraft
            busy: Store.lighterBusy; busyText: "Building candidates…"; onClicked: Store.searchLighter() }
        Btn { objectName: "lighterApply"; kind: "primary"; icon: "git_commit_horizontal"; visible: !!ls.pick && !ls.stale
            text: ls.pick && ls.pick.changes ? "Apply as a new revision" : "Use these print settings"
            onClicked: Store.applyLighter(ls.pick) } }

    // ── now ──
    Row { width: parent.width; spacing: 10
        Repeater {
            model: [{ k: "Computed mass", v: ls.r ? ls.g(ls.r.baseline.mass_g) : "–", d: ls.r ? "volume × " + F.fmt(ls.r.baseline.density, 2) + " g/cm³ (" + ls.r.baseline.density_source + ")" : "from the solid" },
                    { k: "Slicer filament", v: ls.r ? (ls.r.baseline.slice_g === null ? "not sliced" : ls.g(ls.r.baseline.slice_g)) : "–", d: ls.r && ls.r.baseline.settings && ls.r.baseline.settings.infill ? "infill " + ls.r.baseline.settings.infill + (ls.r.baseline.settings.walls ? " · " + ls.r.baseline.settings.walls + " walls" : "") : "the slicer's simulation" },
                    { k: "Checks passing", v: ls.r ? ls.r.baseline.passed + " of " + ls.r.baseline.checks.length : "–", d: "each must still pass" }]
            Rectangle { required property var modelData; width: (ls.width - 20) / 3; height: 88; radius: 14; color: Theme.glass
                Column { x: 14; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 28; spacing: 2
                    Txt { kind: "fine"; text: modelData.k }
                    Txt { mono: true; font.pixelSize: 17; font.weight: Theme.wSemi; text: modelData.v }
                    Txt { kind: "fine"; tone: 3; text: modelData.d; elide: Text.ElideRight; wrapMode: Text.NoWrap; width: parent.width } } } } }

    Txt { kind: "fine"; tone: 2; width: parent.width; visible: !ls.r && !Store.lighterBusy
        text: "Form Studio tries thinner walls and floors, larger lightening pockets where the design has them, and lower infill or one wall fewer in the slicer. Every candidate is built in the kernel; the lightest go through the real checks and slicer." }
    Row { spacing: 8; visible: Store.lighterBusy
        Spinner { size: 14; anchors.verticalCenter: parent.verticalCenter }
        Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; text: "Building candidates in the kernel, checking and slicing the lightest…" } }
    Txt { kind: "fine"; tone: 3; width: parent.width; visible: ls.stale; text: "This search was for " + (ls.r ? F.pad(ls.r.rev) : "") + ". Search again for this revision." }
    Note { visible: !!ls.r && !ls.cands.length && !Store.lighterBusy; kind: "plain"; title: "Nothing lighter keeps every check"
        text: ls.r ? ls.r.none_why : "" }

    // ── candidates ──
    Column { width: parent.width; spacing: 6; visible: ls.cands.length > 0
        Repeater {
            model: ls.cands
            Rectangle { id: cr
                required property var modelData
                required property int index
                readonly property bool on: ls.chosen === modelData.id
                property bool open: false
                objectName: "lighterCandidate"
                width: parent.width; height: cc.implicitHeight + 18; radius: Theme.rMd
                color: on ? Theme.alpha(Theme.datum, 0.08) : cm.containsMouse ? Theme.glass2 : Theme.glass
                border.color: on ? Theme.datum : Theme.rule
                Behavior on color { Tint {} }
                opacity: 0; Component.onCompleted: rise.start()
                ParallelAnimation { id: rise
                    SequentialAnimation { PauseAnimation { duration: Theme.move(cr.index * 50) } NumberAnimation { target: cr; property: "opacity"; to: 1; duration: Theme.base; easing.type: Easing.OutCubic } } }
                MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; onClicked: ls.chosen = cr.modelData.id }
                Column { id: cc; x: 12; y: 9; width: parent.width - 24; spacing: 6
                    Item { width: parent.width; height: 20
                        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                            Tag { text: cr.modelData.kind === "geometry" ? "geometry" : cr.modelData.kind === "settings" ? "print settings" : "both"; kind: cr.modelData.kind === "geometry" ? "computed" : "simulated" }
                            Txt { text: ls.describe(cr.modelData); font.weight: Theme.wSemi; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: cc.width - 230 } }
                        Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; mono: true; color: Theme.pass; font.weight: Theme.wSemi
                            text: "−" + F.fmt(cr.modelData.saves_slice_g !== null ? cr.modelData.saves_slice_g : cr.modelData.saves_mass_g, 1) + " g"
                                  + (cr.modelData.saves_slice_g !== null ? " filament" : " mass") } }
                    // before → after, both measures
                    Row { spacing: 22
                        Column { spacing: 1
                            Txt { kind: "fine"; text: "Computed mass" }
                            Txt { mono: true; font.pixelSize: 12; text: ls.g(ls.r.baseline.mass_g) + "  →  " + ls.g(cr.modelData.mass_g) } }
                        Column { spacing: 1
                            Txt { kind: "fine"; text: "Slicer filament" }
                            Txt { mono: true; font.pixelSize: 12
                                text: cr.modelData.slice_g === null ? (cr.modelData.slice_error ? "slice failed" : "not sliced") : ls.g(ls.r.baseline.slice_g) + "  →  " + ls.g(cr.modelData.slice_g) } }
                        Column { spacing: 1
                            Txt { kind: "fine"; text: "Checks" }
                            Txt { font.pixelSize: 12; color: Theme.pass
                                text: cr.modelData.checks.filter(function (x) { return x.after === "PASS" }).length + " pass · all that passed still pass" } } }
                    Txt { kind: "fine"; tone: cm.containsMouse ? 1 : 3; text: (cr.open ? "Hide" : "Show") + " the checks before and after"
                        MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: cr.open = !cr.open } }
                    Column { width: parent.width; spacing: 2; visible: cr.open
                        Repeater { model: cr.open ? cr.modelData.checks : []
                            Item { required property var modelData; width: cc.width; height: 18
                                Txt { width: parent.width * 0.44; text: modelData.label; font.pixelSize: 12; elide: Text.ElideRight; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
                                Txt { x: parent.width * 0.46; width: parent.width * 0.26; mono: true; font.pixelSize: 11; tone: 2; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                    text: modelData.before + " " + modelData.before_value; anchors.verticalCenter: parent.verticalCenter }
                                Txt { x: parent.width * 0.74; width: parent.width * 0.26; mono: true; font.pixelSize: 11; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                    color: modelData.after === "PASS" ? Theme.pass : modelData.after === "WARN" ? Theme.amber : modelData.after === "FAIL" ? Theme.signal : Theme.ink2
                                    text: modelData.after + " " + modelData.after_value; anchors.verticalCenter: parent.verticalCenter } } } }
                }
            }
        }
    }
    Txt { kind: "fine"; tone: 3; width: parent.width; visible: !!ls.r && ls.r.rejected.length > 0
        text: ls.r ? "Not shown, because they broke a passing check or were not lighter: " + ls.r.rejected.slice(0, 3).map(function (x) {
            return (x.values ? Object.keys(x.values).map(function (k) { return k + " " + x.values[k] }).join(", ") : Object.keys(x.settings).map(function (k) { return k + " " + x.settings[k] }).join(", ")) + " (" + x.why + ")" }).join("; ") + "." : "" }
    Txt { kind: "fine"; width: parent.width; visible: !!ls.r; text: ls.r ? ls.r.note : "" }
}
