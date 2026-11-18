import QtQuick

// The opening screen while the CAD kernel starts: the mark is built the way a part is, the origin first, then the
// X arm, the Y stem and the middle arm, each sliding out of the origin; the wordmark follows and a thin line runs
// under it until the app is ready. Fades out when `done`.
Item {
    id: sp
    objectName: "splash"
    property bool done: false
    property string status: "Starting the CAD kernel…"
    readonly property int s: 96                       // mark height
    readonly property real u: s / 48
    readonly property bool calm: Theme.reduced
    opacity: done ? 0 : 1
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: Theme.move(420); easing.type: Easing.OutCubic } }

    Rectangle { anchors.fill: parent; color: Theme.plate }
    // a faint plate grid that breathes behind the mark
    Grid { id: grid; anchors.centerIn: parent; anchors.verticalCenterOffset: -20; columns: 13; rows: 9; spacing: 31; opacity: 0
        Repeater { model: 117; Rectangle { width: 1; height: 1; color: Theme.ink4 } }
        SequentialAnimation on opacity { running: !sp.calm; loops: 1
            NumberAnimation { to: 0.7; duration: 900; easing.type: Easing.OutCubic } } }
    // a soft glow: stacked faint discs fall off with no hard edge
    Item { id: glow; anchors.centerIn: grid; width: 1; height: 1; scale: sp.calm ? 1 : 0.6; opacity: sp.calm ? 1 : 0
        Repeater { model: 18
            Rectangle { required property int index; readonly property real d: 120 + index * 22
                x: -d / 2; y: -d / 2; width: d; height: d; radius: d / 2; color: Theme.alpha(Theme.datum, 0.009) } }
        NumberAnimation on scale { running: !sp.calm; to: 1.15; duration: 1800; easing.type: Easing.OutCubic }
        NumberAnimation on opacity { running: !sp.calm; to: 1; duration: 700 } }

    Column {
        anchors.centerIn: parent; anchors.verticalCenterOffset: -20; spacing: 26
        Item {
            id: mark; width: 40 * sp.u; height: sp.s; anchors.horizontalCenter: parent.horizontalCenter
            // origin
            Rectangle { id: org; width: 12 * sp.u; height: width; color: Theme.datum; scale: sp.calm ? 1 : 0; transformOrigin: Item.Center }
            // X: top arm, grows right out of the origin
            Rectangle { id: xa; x: 12 * sp.u + 2 * sp.u; height: 12 * sp.u; color: Theme.clay; width: sp.calm ? 26 * sp.u : 0 }
            // Y: stem, grows down
            Rectangle { id: ya; y: 12 * sp.u + 2 * sp.u; width: 12 * sp.u; color: Theme.clay; height: sp.calm ? 34 * sp.u : 0 }
            // the middle arm
            Rectangle { id: ma; x: 12 * sp.u; y: 20 * sp.u; height: 12 * sp.u; color: Theme.clay; width: sp.calm ? 20 * sp.u : 0 }
            SequentialAnimation {
                running: !sp.calm
                PauseAnimation { duration: 180 }
                NumberAnimation { target: org; property: "scale"; to: 1; duration: 340; easing.type: Easing.OutBack; easing.overshoot: 2.2 }
                ParallelAnimation {
                    NumberAnimation { target: xa; property: "width"; to: 26 * sp.u; duration: 520; easing.type: Easing.OutExpo }
                    SequentialAnimation { PauseAnimation { duration: 90 }
                        NumberAnimation { target: ya; property: "height"; to: 34 * sp.u; duration: 560; easing.type: Easing.OutExpo } } }
                ParallelAnimation {
                    NumberAnimation { target: ma; property: "width"; to: 20 * sp.u; duration: 420; easing.type: Easing.OutExpo }
                    ScriptAction { script: word.opacity = 1 } }
            }
        }
        Logo { id: word; mark: false; size: 30; anchors.horizontalCenter: parent.horizontalCenter
            opacity: sp.calm ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
            transform: Translate { y: word.opacity < 1 ? 8 * (1 - word.opacity) : 0 } }
        Column { spacing: 12; anchors.horizontalCenter: parent.horizontalCenter
            // an indeterminate line: a short datum segment sweeping a quiet rail
            Rectangle { id: rail; width: 160; height: 2; radius: 1; color: Theme.rule; clip: true; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { id: seg; width: 48; height: 2; radius: 1; color: Theme.datum; x: -width
                    SequentialAnimation on x { loops: Animation.Infinite; running: sp.visible && !sp.calm
                        NumberAnimation { from: -seg.width; to: rail.width; duration: 1100; easing.type: Easing.InOutCubic } PauseAnimation { duration: 120 } } } }
            Txt { objectName: "splashStatus"; kind: "fine"; tone: 3; text: sp.status; anchors.horizontalCenter: parent.horizontalCenter } }
    }
}
