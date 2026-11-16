import QtQuick
import "F.js" as F

// The measure tool's readout: what to click, and every measurement taken, until cleared.
// Numbers are computed from the part's surface; a hole diameter is exact when it comes from the CAD solid.
Rectangle {
    id: mp
    readonly property var list: Store.measures
    width: 318; height: col.implicitHeight + 20; radius: Theme.rMd
    color: Theme.alpha(Theme.plate1, 0.92); border.color: Theme.rule

    function hint() {
        if (!Store.measuring) return "Measuring is off. Press M to take more."
        if (Store.measureKind === "distance") return Store.measureFrom ? "Click the second point." : "Click two points on the part. Points snap to corners, edge midpoints and face centres when close."
        if (Store.measureKind === "face") return "Click a face for its area and its tilt to the bed."
        return "Click the wall or rim of a hole or round boss."
    }

    Column {
        id: col; x: 12; y: 10; width: parent.width - 24; spacing: 8
        Item { width: parent.width; height: 26
            Seg { anchors.verticalCenter: parent.verticalCenter
                model: [{ value: "distance", text: "Distance" }, { value: "face", text: "Face" }, { value: "diameter", text: "Diameter" }]
                value: Store.measuring ? Store.measureKind : ""
                onPicked: function (v) { Store.measureKind = v; Store.measureFrom = null; if (!Store.measuring) Store.setMeasuring(true) } }
            Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                Btn { small: true; kind: "quiet"; text: "Clear"; enabled: mp.list.length > 0 || !!Store.measureFrom; onClicked: Store.clearMeasures() }
                Btn { small: true; kind: "quiet"; icon: "x"; tip: "Close the measure tool (Esc). Measurements stay until cleared."
                    onClicked: { Store.setMeasuring(false); if (!mp.list.length) Store.measureOpen = false } } } }
        Txt { kind: "fine"; tone: 2; width: parent.width; text: mp.hint() }

        Column { width: parent.width; visible: mp.list.length > 0
            Repeater {
                model: mp.list
                Item { id: row
                    required property var modelData
                    required property int index
                    width: parent.width; height: rc.implicitHeight + 12
                    Rectangle { width: parent.width; height: 1; color: Theme.rule }
                    Txt { y: 7; mono: true; font.pixelSize: 10; tone: 4; text: String(row.index + 1) }
                    Column { id: rc; x: 18; y: 6; width: parent.width - 18 - 22; spacing: 2
                        Row { spacing: 8
                            Txt { mono: true; font.pixelSize: 14; font.weight: 600; color: Theme.datum; text: row.modelData.label; wrapMode: Text.NoWrap }
                            Tag { anchors.verticalCenter: parent.verticalCenter; text: row.modelData.how; kind: "computed" } }
                        Txt { kind: "fine"; tone: 2; mono: row.modelData.kind === "distance"; width: parent.width; text: row.modelData.detail } }
                    Btn { anchors.right: parent.right; y: 4; small: true; kind: "quiet"; icon: "x"; tip: "Remove"; onClicked: Store.dropMeasure(row.modelData.id) }
                }
            }
        }
        Txt { kind: "fine"; width: parent.width
            text: "Computed from the part’s surface, tessellated at 0.05 mm. Diameters marked exact come from the CAD solid; “fitted” means a circle fitted to mesh edges." }
    }
}
