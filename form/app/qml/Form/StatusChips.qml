import QtQuick

// Quiet notices in the top bar: setup needs attention, a newer FORM exists. Each opens its sheet.
// `compact` shrinks each to a dot or an arrow with a tooltip; the bar sets it when it runs out of room.
Row {
    id: sc
    spacing: 6
    property bool compact: Store.screen === "work"
    readonly property var st: Store.setup
    readonly property int need: st ? st.attention.length : 0
    readonly property bool setupShown: !!st && (need > 0 || !st.required_ok) && !Store.welcome
    readonly property bool updateShown: !!Store.update && Store.update.available && !Store.updateHidden
    Rectangle { visible: sc.setupShown; height: 24; width: sc.compact ? 24 : sl.implicitWidth + 34; radius: height / 2; anchors.verticalCenter: parent.verticalCenter
        color: sm.pressed ? Theme.alpha(Theme.amber, 0.22) : sm.containsMouse ? Theme.alpha(Theme.amber, 0.15) : sc.compact ? "transparent" : Theme.alpha(Theme.amber, 0.08)
        Behavior on color { Tint {} }
        Rectangle { visible: !sc.compact; x: 11; width: 6; height: 6; radius: 3; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter }
        Icon { visible: sc.compact; anchors.centerIn: parent; name: "triangle_alert"; size: 13; color: Theme.amber }
        Txt { id: sl; visible: !sc.compact; x: 24; kind: "fine"; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
            text: sc.st && !sc.st.required_ok ? "Setup needed" : "Setup: " + sc.need + " to check" }
        MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.openSetup() }
        Tip { show: sm.containsMouse; text: sc.st && !sc.st.required_ok ? "Setup: a required item is missing" : sc.need ? "Setup: " + sc.need + " to check" : "Open setup" } }
    Rectangle { visible: sc.updateShown; height: 24; width: sc.compact ? 24 : ul.implicitWidth + 38; radius: height / 2; anchors.verticalCenter: parent.verticalCenter
        color: um.pressed ? Theme.washPress : um.containsMouse ? Theme.washHover : sc.compact ? "transparent" : Theme.glass; border.width: 0
        Behavior on color { Tint {} }
        Icon { x: sc.compact ? 6 : 10; name: "arrow_down_to_line"; size: 12; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
        Txt { id: ul; visible: !sc.compact; x: 28; kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
            text: Store.update && Store.update.latest ? "Form Studio " + Store.update.latest : "" }
        MouseArea { id: um; anchors.fill: parent; hoverEnabled: true; onClicked: Store.openSheet("update") }
        Tip { show: um.containsMouse; text: Store.update && Store.update.latest ? "Form Studio " + Store.update.latest + " is available" : "" } }
}
