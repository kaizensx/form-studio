import QtQuick
import QtQuick.Controls

// Tooltip that appears after a short rest and never steals focus.
Item {
    id: t
    property string text: ""
    property bool show: false
    anchors.fill: parent
    ToolTip {
        visible: t.show && t.text !== ""; delay: 450; timeout: 6000; text: t.text; padding: 7
        contentItem: Text { text: t.text; color: Theme.ink; font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap; width: Math.min(implicitWidth, 280); renderType: Text.NativeRendering }
        background: Rectangle { color: Theme.plate3; radius: Theme.rSm; border.color: Theme.rule2 }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
    }
}
