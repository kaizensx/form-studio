import QtQuick

// One tool of the ribbon (ToolRibbon.qml): an icon and its label on one line, or the icon alone when the stage is
// narrow (`compact`). The tooltip under it names the tool, says what it does and gives its key.
// `active` is the tool in use (the one filled disc of the stage, as in the dock); `marked` a state left on.
Item {
    id: b
    property string icon: ""
    property string label: ""
    property string keys: ""
    property string hint: ""
    property bool compact: false
    property bool active: false
    property bool marked: false
    property bool toggle: false           // a view switch: on is bright ink, never the filled disc
    signal clicked()
    readonly property real full: Math.ceil(lt.implicitWidth) + 16 + 6 + 22
    width: compact ? 32 : full; height: 30
    opacity: enabled ? 1 : 0.38
    activeFocusOnTab: true
    Keys.onSpacePressed: if (b.enabled) b.clicked()
    Keys.onReturnPressed: if (b.enabled) b.clicked()
    readonly property bool lit: active && !toggle
    Rectangle {
        anchors.fill: parent; radius: height / 2
        color: b.lit ? Theme.send : ma.pressed && b.enabled ? Theme.washPress : (b.toggle && b.active) ? Theme.washOn : ma.containsMouse && b.enabled ? Theme.washHover : "transparent"
        scale: ma.pressed && b.enabled ? Theme.from(0.96) : 1
        Behavior on scale { Glide { duration: Theme.press } }
        Behavior on color { Tint {} }
    }
    Row {
        anchors.centerIn: parent; spacing: 6
        Icon { name: b.icon; size: 16; anchors.verticalCenter: parent.verticalCenter
            color: b.lit ? Theme.sendInk : (b.toggle && b.active) || (ma.containsMouse && b.enabled) ? Theme.ink : Theme.ink2 }
        Txt { id: lt; visible: !b.compact; text: b.label; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap
            anchors.verticalCenter: parent.verticalCenter
            color: b.lit ? Theme.sendInk : (b.toggle && b.active) || (ma.containsMouse && b.enabled) ? Theme.ink : Theme.ink2 }
    }
    Rectangle { visible: b.marked && !b.lit; width: 5; height: 5; radius: 2.5; color: Theme.datum
        x: b.compact ? parent.width - 8 : 8; y: 4 }
    FocusRing { on: b.activeFocus; radius: b.height / 2 + 3 }
    // the tooltip is the band's own (ToolRibbon.qml): one pane under the tools that moves to the one under the
    // pointer, drawn in the scene and not as a popup, so a press never lands on a tooltip that has just opened
    property Item tipTo: null
    readonly property string tipText: hint ? (compact ? label + ". " : "") + hint : label
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: if (b.enabled) b.clicked()
        onContainsMouseChanged: if (b.tipTo) b.tipTo.tipFor(b, containsMouse) }
    Component.onDestruction: if (b.tipTo) b.tipTo.tipFor(b, false)
}
