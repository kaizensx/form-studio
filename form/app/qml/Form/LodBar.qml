import QtQuick
import "F.js" as F

// The LOD switcher over the game asset's viewport: one chip per level of detail with its triangle count against its
// budget (form/game: a LOD passes with up to 2% over), the one drawn raised. Left and Right move between them.
// lods: the asset's report rows [{ lod, triangles, budget, source }]; value: the LOD drawn.
Rectangle {
    id: lb
    objectName: "lodBar"
    property var lods: []
    property int value: 0
    signal picked(int lod)
    implicitWidth: row.implicitWidth + 4; implicitHeight: 44; radius: Theme.rSm
    color: Theme.alpha(Theme.plate1, 0.9); border.color: Theme.rule
    activeFocusOnTab: true
    Keys.onLeftPressed: if (value > 0) picked(value - 1)
    Keys.onRightPressed: if (value < lods.length - 1) picked(value + 1)
    FocusRing { on: lb.activeFocus; radius: lb.radius + 3 }
    function over(r) { return !!r.budget && r.triangles > r.budget * 1.02 }
    Row {
        id: row; x: 2; y: 2; spacing: 0
        Repeater {
            model: lb.lods
            Rectangle {
                id: chip
                required property var modelData
                required property int index
                readonly property bool on: modelData.lod === lb.value
                objectName: "lod" + modelData.lod
                width: Math.max(78, col.implicitWidth + 20); height: 40; radius: Theme.rXs
                color: on ? Theme.plate4 : ma.pressed ? Theme.washPress : ma.containsMouse ? Theme.washHover : "transparent"
                border.width: on ? 1 : 0; border.color: Theme.rule
                Behavior on color { Tint {} }
                Column { id: col; anchors.centerIn: parent; spacing: 1
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "LOD" + chip.modelData.lod; renderType: Text.NativeRendering
                        font.family: Theme.sans; font.pixelSize: 12; font.weight: Theme.wSemi; color: chip.on ? Theme.ink : Theme.ink2 }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; renderType: Text.NativeRendering
                        text: F.trim(chip.modelData.triangles) + (chip.modelData.budget ? " / " + F.trim(chip.modelData.budget) : "") + " tris"
                        font.family: Theme.mono; font.pixelSize: 10; color: lb.over(chip.modelData) ? Theme.signal : chip.on ? Theme.ink2 : Theme.ink3 } }
                MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: lb.picked(chip.modelData.lod) }
                Tip { show: ma.containsMouse; text: chip.modelData.source || "" }
            }
        }
    }
}
