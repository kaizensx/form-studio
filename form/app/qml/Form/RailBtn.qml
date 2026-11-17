import QtQuick

// One button of the viewport's tool rail: an icon, a label and key that appear beside it on hover.
// `active` is the tool in use; `marked` is a state that is on while another tool is in use (a section cut, a map).
Item {
    id: b
    property string icon: ""
    property string label: ""
    property string keys: ""
    property string hint: ""              // a second, quieter line: why it is off, or what it does
    property bool active: false
    property bool marked: false
    property bool toggle: false           // a view switch, not a tool: on is a bright icon, off a dim one
    signal clicked()
    width: 32; height: 30
    opacity: enabled ? 1 : 0.35
    Rectangle {
        anchors.fill: parent; anchors.margins: 1; radius: Theme.rSm
        color: b.active && !b.toggle ? Theme.alpha(Theme.datum, 0.14) : ma.pressed && b.enabled ? Theme.washPress : ma.containsMouse && b.enabled ? Theme.washHover : "transparent"
        scale: ma.pressed && b.enabled ? Theme.from(0.94) : 1
        Behavior on scale { Glide { duration: Theme.press } }
        Behavior on color { Tint {} }
        Icon { anchors.centerIn: parent; name: b.icon; size: 16
            color: b.toggle ? (b.active ? Theme.ink : Theme.ink4) : b.active ? Theme.datum : ma.containsMouse && b.enabled ? Theme.ink : Theme.ink2 }
        Rectangle { visible: b.marked && !b.active; width: 5; height: 5; radius: 2.5; color: Theme.datum
            anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 3 }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true
        onClicked: if (b.enabled) b.clicked()
        onContainsMouseChanged: { if (containsMouse) { cool.stop(); rest.restart() } else { rest.stop(); if (tip.on) cool.restart(); tip.on = false } } }
    // the first label waits for the pointer to rest; moving along the rail shows the next ones at once
    Timer { id: rest; interval: Ws.tipWarm ? 0 : 380; onTriggered: { tip.on = true; Ws.tipWarm = true } }
    Timer { id: cool; interval: 420; onTriggered: Ws.tipWarm = false }
    Rectangle {
        id: tip
        property bool on: false
        x: b.width + 10; anchors.verticalCenter: parent.verticalCenter; z: 20
        width: tc.implicitWidth + 18; height: tc.implicitHeight + 12; radius: Theme.rSm
        color: Theme.plate3; border.color: Theme.rule2
        visible: opacity > 0.01; opacity: on && b.label !== "" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: tip.on && !Ws.tipWarm ? Theme.fast : 0 } }
        Column { id: tc; x: 9; y: 6; spacing: 2
            Row { spacing: 8
                Txt { text: b.label; font.pixelSize: 12; font.weight: 550; wrapMode: Text.NoWrap }
                Txt { visible: b.keys !== ""; text: b.keys; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap; anchors.baseline: parent.children[0].baseline } }
            Txt { visible: b.hint !== ""; text: b.hint; kind: "fine"; tone: 2; width: Math.min(implicitWidth, 250) } }
    }
}
