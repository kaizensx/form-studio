import QtQuick

// Segmented control. model: [{ value, text }] or [string]
Rectangle {
    id: g
    property var model: []
    property var value: null
    signal picked(var value)
    implicitHeight: 26; implicitWidth: row.implicitWidth + 4; radius: Theme.rSm
    color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
    Row {
        id: row; x: 2; y: 2; spacing: 0
        Repeater {
            model: g.model
            Rectangle {
                required property var modelData
                readonly property var v: modelData.value !== undefined ? modelData.value : modelData
                readonly property bool on: v === g.value
                width: l.implicitWidth + 16; height: 22; radius: Theme.rXs
                color: on ? Theme.plate4 : sm.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent"
                Text { id: l; anchors.centerIn: parent; text: modelData.text !== undefined ? modelData.text : modelData; renderType: Text.NativeRendering
                    font.family: Theme.sans; font.pixelSize: 12; font.weight: 550; color: parent.on ? Theme.ink : Theme.ink3 }
                MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: g.picked(parent.v) }
            }
        }
    }
}
