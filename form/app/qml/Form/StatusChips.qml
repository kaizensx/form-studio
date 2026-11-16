import QtQuick

// Quiet notices in the top bar: setup needs attention, a newer FORM exists. Each opens its sheet.
Row {
    id: sc
    spacing: 8
    property bool compact: Store.screen === "work"     // the bar is busy with the project there
    readonly property var st: Store.setup
    readonly property int need: st ? st.attention.length : 0
    readonly property bool setupShown: !!st && (need > 0 || !st.required_ok) && !Store.welcome
    readonly property bool updateShown: !!Store.update && Store.update.available && !Store.updateHidden
    Rectangle { visible: sc.setupShown; height: 24; width: sl.implicitWidth + 28; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
        color: sm.containsMouse ? Theme.alpha(Theme.amber, 0.16) : Theme.alpha(Theme.amber, 0.09)
        Rectangle { x: 10; width: 6; height: 6; radius: 3; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter }
        Txt { id: sl; x: 22; kind: "fine"; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
            text: sc.st && !sc.st.required_ok ? (sc.compact ? "Setup needed" : "Setup: required item missing")
                : sc.compact ? "Setup" : "Setup: " + sc.need + " to check" }
        MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.openSetup() }
        Tip { show: sm.containsMouse; text: sc.need ? "Setup: " + sc.need + " to check" : "Open setup" } }
    Rectangle { visible: sc.updateShown; height: 24; width: ul.implicitWidth + 32; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
        color: um.containsMouse ? Theme.plate3 : "transparent"; border.color: Theme.rule2
        Icon { x: 9; name: "arrow_down_to_line"; size: 12; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
        Txt { id: ul; x: 25; kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
            text: Store.update && Store.update.latest ? "FORM " + Store.update.latest + (sc.compact ? "" : " is available") : "" }
        MouseArea { id: um; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.openSheet("update") }
        Tip { show: um.containsMouse; text: "A newer FORM is available" } }
}
