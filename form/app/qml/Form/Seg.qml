import QtQuick

// Segmented control. model: [{ value, text, off, tip, badge }] or [string]. Left/Right move when it has keyboard focus.
// An item with off: true is shown but cannot be picked; its tip says why. badge: a small calm tag after the text
// ("Beta").
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
    function _step(d) {
        for (var i = 0; i < model.length; i++) if (_v(model[i]) === value) {
            for (var k = i + d; k >= 0 && k < model.length; k += d) if (!model[k].off) { picked(_v(model[k])); return }
            return
        }
    }
    Keys.onLeftPressed: _step(-1)
    Keys.onRightPressed: _step(1)
    FocusRing { on: g.activeFocus; radius: g.radius + 3 }
    Row {
        id: row; x: 2; anchors.verticalCenter: parent.verticalCenter; spacing: 0     // centred whatever height the caller gives
        Repeater {
            model: g.model
            Rectangle {
                required property var modelData
                readonly property var v: g._v(modelData)
                readonly property bool on: v === g.value
                readonly property bool off: !!modelData.off
                width: lr.implicitWidth + 16; height: g.height - 4; radius: Theme.rXs       // concentric: 6 − 2
                color: on ? Theme.plate4 : off ? "transparent" : sm.pressed ? Theme.washPress : sm.containsMouse ? Theme.washHover : "transparent"
                border.width: on ? 1 : 0; border.color: Theme.rule
                Behavior on color { Tint {} }
                Row { id: lr; anchors.centerIn: parent; spacing: 5
                    Text { id: l; anchors.verticalCenter: parent.verticalCenter; text: modelData.text !== undefined ? modelData.text : modelData; renderType: Text.NativeRendering
                        font.family: Theme.sans; font.pixelSize: 12; font.weight: Theme.wMedium; color: lr.parent.on ? Theme.ink : lr.parent.off ? Theme.ink4 : sm.containsMouse ? Theme.ink2 : Theme.ink3 }
                    BetaTag { visible: !!modelData.badge; text: modelData.badge || ""; tip: ""; anchors.verticalCenter: parent.verticalCenter; implicitHeight: 15 } }
                MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; cursorShape: parent.off ? Qt.ArrowCursor : Qt.PointingHandCursor
                    onClicked: if (!parent.off) g.picked(parent.v) }
                Tip { show: sm.containsMouse && !!modelData.tip; text: modelData.tip || "" }
            }
        }
    }
}
