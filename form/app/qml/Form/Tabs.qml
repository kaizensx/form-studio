import QtQuick

// Tabs for the sections of a sheet or panel. model: [{ value, text, badge? }] or [string]. Left/Right move when focused.
// The marker under the current tab slides between tabs.
Item {
    id: g
    property var model: []
    property var value: null
    signal picked(var value)
    implicitHeight: 34; implicitWidth: row.implicitWidth
    width: parent ? parent.width : implicitWidth
    activeFocusOnTab: true
    function _v(m) { return m.value !== undefined ? m.value : m }
    function _index() { for (var i = 0; i < model.length; i++) if (_v(model[i]) === value) return i; return -1 }
    function _step(d) { var i = _index() + d; if (i >= 0 && i < model.length) picked(_v(model[i])) }
    Keys.onLeftPressed: _step(-1)
    Keys.onRightPressed: _step(1)
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
    Row {
        id: row; spacing: 22; height: parent.height
        Repeater {
            id: rep; model: g.model
            Item {
                id: tab
                required property var modelData
                required property int index
                readonly property var v: g._v(modelData)
                readonly property bool on: v === g.value
                width: tr.implicitWidth; height: row.height
                Row { id: tr; spacing: 6; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: -1
                    Text { text: tab.modelData.text !== undefined ? tab.modelData.text : tab.modelData; renderType: Text.NativeRendering
                        font.family: Theme.sans; font.pixelSize: 13; font.weight: Theme.wMedium
                        color: tab.on ? Theme.ink : tm.containsMouse ? Theme.ink2 : Theme.ink3
                        Behavior on color { Tint {} } }
                    Rectangle { visible: !!tab.modelData.badge; width: bt.implicitWidth + 10; height: 16; radius: 8; color: Theme.alpha(Theme.amber, 0.14); anchors.verticalCenter: parent.verticalCenter
                        Text { id: bt; anchors.centerIn: parent; text: tab.modelData.badge ? String(tab.modelData.badge) : ""; color: Theme.amber; font.family: Theme.mono; font.pixelSize: 10; renderType: Text.NativeRendering } } }
                MouseArea { id: tm; anchors.fill: parent; anchors.leftMargin: -11; anchors.rightMargin: -11; hoverEnabled: true; onClicked: g.picked(tab.v) }
            }
        }
    }
    Rectangle {
        id: mark
        readonly property int i: g._index()
        readonly property Item at: i >= 0 && rep.count > i ? rep.itemAt(i) : null
        property bool settled: false
        visible: !!at; anchors.bottom: parent.bottom; height: 2; radius: 1; color: Theme.datum
        x: at ? at.x : 0; width: at ? at.width : 0
        Component.onCompleted: Qt.callLater(function () { mark.settled = true })
        Behavior on x { enabled: mark.settled; NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMove } }
        Behavior on width { enabled: mark.settled; NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMove } }
    }
    FocusRing { on: g.activeFocus; radius: Theme.rSm; gap: 3 }
}
