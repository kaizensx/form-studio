import QtQuick

// Toasts: bottom right, newest at the bottom. They rise in, wait (longer for a failure, and while the pointer rests on
// them), and leave faster than they came. Click to dismiss.
Column {
    id: tc
    spacing: 8; width: 348
    move: Transition { NumberAnimation { properties: "y"; duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    Repeater {
        model: Store.toasts
        Item {
            id: t
            required property var modelData
            property bool leaving: false
            width: tc.width; height: card.height
            function leave() { if (leaving) return; leaving = true; out.start() }
            Rectangle {
                id: card
                width: parent.width; height: tcol.implicitHeight + 22; radius: Theme.rMd + 2
                color: Theme.plate3; border.color: Theme.rule2
                opacity: 0; y: Theme.shift(10)
                Shadow { radius: parent.radius; spread: 18; drop: 8 }
                Rectangle { x: 12; y: 13; width: 6; height: 6; radius: 3; color: t.modelData.bad ? Theme.signal : Theme.pass }
                Column { id: tcol; x: 28; y: 11; width: parent.width - 28 - 14; spacing: 2
                    Txt { text: t.modelData.msg; width: parent.width; font.weight: Theme.wSemi }
                    Txt { kind: "fine"; visible: t.modelData.hint !== ""; text: t.modelData.hint; width: parent.width; color: Theme.ink2 } }
                HoverHandler { id: hov }
                MouseArea { anchors.fill: parent; onClicked: t.leave() }
            }
            Component.onCompleted: inn.start()
            ParallelAnimation { id: inn
                Glide { target: card; property: "opacity"; to: 1; duration: Theme.base }
                Glide { target: card; property: "y"; to: 0; duration: Theme.base } }
            SequentialAnimation { id: out
                ParallelAnimation {
                    NumberAnimation { target: card; property: "opacity"; to: 0; duration: Theme.exit }
                    NumberAnimation { target: card; property: "scale"; to: Theme.from(0.97); duration: Theme.exit } }
                ScriptAction { script: Store.dropToast(t.modelData.id) } }
            Timer { running: !hov.hovered && !t.leaving; interval: t.modelData.bad ? 7000 : 3400; onTriggered: t.leave() }
        }
    }
}
