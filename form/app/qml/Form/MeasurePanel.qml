import QtQuick
import QtQuick.Controls
import "F.js" as F

// The measure tool's readout: every measurement taken, until cleared. What to click is said in the tool's options.
// Numbers are computed from the part's surface; a hole diameter is exact when it comes from the CAD solid.
// It lives in the viewport's dock (top right); collapsed it is its header with the last measurement.
Rectangle {
    id: mp
    readonly property var list: Store.measures
    property bool collapsed: false
    property real maxHeight: 520
    signal toggled()
    width: 252; radius: Theme.rMd
    height: collapsed ? 36 : Math.min(maxHeight, 36 + col.implicitHeight + 12)
    color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.rule

    Item { id: head; width: parent.width; height: 36
        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: Theme.rSm; color: hm.containsMouse ? Theme.washHover : "transparent" }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: mp.toggled() }
        Txt { kind: "cap"; x: 14; anchors.verticalCenter: parent.verticalCenter; text: "Measurements"; wrapMode: Text.NoWrap }
        Row { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Txt { visible: mp.collapsed && mp.list.length > 0; mono: true; font.pixelSize: 11; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: mp.list.length ? mp.list[mp.list.length - 1].label : "" }
            Txt { visible: !mp.collapsed; kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: String(mp.list.length) }
            Tag { text: "computed"; anchors.verticalCenter: parent.verticalCenter }
            Icon { name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter; rotation: mp.collapsed ? -90 : 0
                Behavior on rotation { NumberAnimation { duration: Motion.move(140); easing.type: Easing.OutCubic } } } }
    }

    Flickable {
        visible: !mp.collapsed
        y: 36; width: parent.width; height: parent.height - 36 - 2
        contentHeight: col.implicitHeight + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 5 }
        Column {
            id: col; x: 14; width: parent.width - 28; spacing: 8
            Column { width: parent.width
                Repeater {
                    model: mp.list
                    Item { id: row
                        required property var modelData
                        required property int index
                        width: parent.width; height: rc.implicitHeight + 12
                        Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Txt { y: 8; mono: true; font.pixelSize: 10; tone: 4; text: String(row.index + 1) }
                        Column { id: rc; x: 18; y: 6; width: parent.width - 18 - 22; spacing: 2
                            Row { spacing: 8
                                Txt { mono: true; font.pixelSize: 14; font.weight: 600; color: Theme.datum; text: row.modelData.label; wrapMode: Text.NoWrap }
                                Tag { anchors.verticalCenter: parent.verticalCenter; text: row.modelData.how; kind: "computed" } }
                            Txt { kind: "fine"; tone: 2; mono: row.modelData.kind === "distance"; width: parent.width; text: row.modelData.detail } }
                        Btn { anchors.right: parent.right; anchors.rightMargin: -6; y: 4; small: true; kind: "quiet"; icon: "x"; tip: "Remove"; onClicked: Store.dropMeasure(row.modelData.id) }
                    }
                }
            }
            Txt { kind: "fine"; width: parent.width
                text: "Computed from the part’s surface, tessellated at 0.05 mm. Diameters marked exact come from the CAD solid; “fitted” means a circle fitted to mesh edges." }
        }
    }
}
