import QtQuick

// Segmented control. model: [{ value, text }] or [string]. Left/Right move when it has keyboard focus.
Rectangle {
    id: g
    property var model: []
    property var value: null
    signal picked(var value)
    implicitHeight: 26; implicitWidth: row.implicitWidth + 4; radius: Theme.rSm
    opacity: enabled ? 1 : 0.5
    color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
    activeFocusOnTab: true
    function _v(m) { return m.value !== undefined ? m.value : m }
    function _step(d) { for (var i = 0; i < model.length; i++) if (_v(model[i]) === value) { var n = model[i + d]; if (n !== undefined) picked(_v(n)); return } }
    Keys.onLeftPressed: _step(-1)
    Keys.onRightPressed: _step(1)
    FocusRing { on: g.activeFocus; radius: g.radius + 3 }
    Row {
        id: row; x: 2; y: 2; spacing: 0
        Repeater {
            model: g.model
            Rectangle {
                required property var modelData
                readonly property var v: g._v(modelData)
                readonly property bool on: v === g.value
                width: l.implicitWidth + 16; height: 22; radius: Theme.rXs       // concentric: 6 − 2
                color: on ? Theme.plate4 : sm.pressed ? Theme.washPress : sm.containsMouse ? Theme.washHover : "transparent"
                border.width: on ? 1 : 0; border.color: Theme.rule
                Text { id: l; anchors.centerIn: parent; text: modelData.text !== undefined ? modelData.text : modelData; renderType: Text.NativeRendering
                    font.family: Theme.sans; font.pixelSize: 12; font.weight: Theme.wMedium; color: parent.on ? Theme.ink : sm.containsMouse ? Theme.ink2 : Theme.ink3 }
                MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: g.picked(parent.v) }
            }
        }
    }
}
