import QtQuick
import "F.js" as F

// Prove → Every printer (form/slicecompare.py). The design's exported model sliced for real on each printer set up in
// each installed slicer: the slicer's own time and filament, the cost from your prices, a bar per printer for the
// time, and which one is fastest, uses least filament, costs least. A printer whose bed is too small is said so, not
// sliced; a failed slice says why. Nothing here is estimated by Form Studio itself.
Column {
    id: root
    objectName: "printerCompare"
    width: parent ? parent.width : 0
    spacing: 0
    readonly property var r: Store.printerCompare
    readonly property var rows: r ? r.rows : []
    readonly property bool stale: !!r && !!Store.project && r.rev !== Store.project.head
    readonly property real maxT: { var m = 0; for (var i = 0; i < rows.length; i++) if (rows[i].time_s) m = Math.max(m, rows[i].time_s); return m }
    readonly property string cur: r && r.currency ? " " + r.currency : ""
    readonly property string key: Store.pid + ":" + (Store.project ? Store.project.head : 0)
    onKeyChanged: Store.loadPrinterCompare()
    Component.onCompleted: Store.loadPrinterCompare()

    Sec { title: "Every printer"; note: root.r ? F.plural(root.rows.filter(function (x) { return x.status === "ok" }).length, "slice") + " · r" + String(root.r.rev).padStart(2, "0") : ""

        Txt { kind: "fine"; width: parent.width
            text: "Slice this revision on every printer set up in your slicers, each with its own process and filament, and compare the time, the filament and what it costs." }
        Row { spacing: 8
            Btn { objectName: "comparePrinters"; icon: "gauge"; text: root.r ? "Compare again" : "Compare printers"
                busy: Store.printerCompareBusy; busyText: "Slicing on each printer…"; enabled: !Store.hasDraft
                onClicked: Store.comparePrinters(8) }
            Spinner { size: 14; visible: Store.printerCompareBusy; anchors.verticalCenter: parent.verticalCenter } }
        Txt { kind: "fine"; tone: 3; width: parent.width; visible: root.stale; text: "These are from an older revision. Compare again for this one." }

        Column { width: parent.width; spacing: 2; visible: root.rows.length > 0; topPadding: 4
            Item { width: parent.width; height: 20
                Txt { kind: "fine"; text: "Printer"; anchors.verticalCenter: parent.verticalCenter }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    Repeater { model: ["time", "grams", "cost"]
                        Txt { required property string modelData; kind: "fine"; text: modelData; width: 64; horizontalAlignment: Text.AlignRight } } } }
            Repeater {
                model: root.rows
                Rectangle { id: pr
                    required property var modelData
                    required property int index
                    readonly property bool ok: modelData.status === "ok"
                    readonly property var tags: {
                        var t = [], b = root.r ? root.r.best : {}
                        if (b.fastest === modelData.id) t.push("fastest")
                        if (b.least_filament === modelData.id) t.push("least filament")
                        if (b.cheapest === modelData.id) t.push("cheapest")
                        return t
                    }
                    objectName: "printerRow"
                    width: parent.width; height: pc.implicitHeight + 12; radius: 10
                    color: tags.length ? Theme.alpha(Theme.datum, 0.07) : "transparent"
                    opacity: 0
                    Component.onCompleted: rise.start()
                    ParallelAnimation { id: rise
                        PauseAnimation { duration: Theme.move(Math.min(pr.index, 10) * 40) }
                        NumberAnimation { target: pr; property: "opacity"; to: 1; duration: Theme.base; easing.type: Easing.OutCubic } }
                    Column { id: pc; x: 6; y: 6; width: parent.width - 12; spacing: 3
                        Item { width: parent.width; height: 18
                            Txt { width: parent.width - 3 * 64 - 14; text: pr.modelData.printer; font.weight: pr.tags.length ? 600 : 420; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                anchors.verticalCenter: parent.verticalCenter }
                            Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; visible: pr.ok
                                Repeater { model: [F.dur(pr.modelData.time_s), pr.modelData.filament_g === null ? "–" : F.fmt(pr.modelData.filament_g, 1),
                                                   pr.modelData.cost === null || pr.modelData.cost === undefined ? "–" : F.fmt(pr.modelData.cost, 2) + root.cur]
                                    Txt { required property string modelData; mono: true; font.pixelSize: 12; text: modelData; width: 64; horizontalAlignment: Text.AlignRight
                                        wrapMode: Text.NoWrap } } } }
                        Txt { kind: "fine"; tone: 3; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: pr.modelData.slicer + (pr.modelData.nozzle_mm ? " · " + pr.modelData.nozzle_mm + " mm nozzle" : "") + (pr.modelData.process ? " · " + pr.modelData.process : "") }
                        // the time, as a bar against the slowest printer
                        Rectangle { visible: pr.ok && root.maxT > 0; width: parent.width; height: 4; radius: 2; color: Theme.rule
                            Rectangle { height: parent.height; radius: 2; color: pr.tags.indexOf("fastest") >= 0 ? Theme.pass : Theme.datum
                                width: pr.ok && root.maxT > 0 ? parent.width * pr.modelData.time_s / root.maxT : 0
                                Behavior on width { NumberAnimation { duration: Theme.move(Theme.slow); easing.type: Easing.OutCubic } } } }
                        Flow { width: parent.width; spacing: 4; visible: pr.tags.length > 0
                            Repeater { model: pr.tags; Tag { required property string modelData; text: modelData; kind: "PASS" } } }
                        Txt { kind: "fine"; width: parent.width; visible: !pr.ok; color: pr.modelData.status === "too_big" ? Theme.ink3 : Theme.amber
                            text: (pr.modelData.status === "too_big" ? "Too small: " : pr.modelData.status === "unavailable" ? "Cannot slice here: " : "Slice failed: ") + pr.modelData.reason }
                        Txt { kind: "fine"; tone: 3; width: parent.width; visible: pr.ok && pr.modelData.cost === null && (pr.modelData.not_counted || []).indexOf("filament") >= 0
                            text: "No price for this filament: set one in Cost above." }
                    }
                }
            }
        }
        Txt { kind: "fine"; width: parent.width; visible: !!root.r; text: root.r ? root.r.note + (root.r.parts_note ? " " + root.r.parts_note : "") : "" }
    }
}
