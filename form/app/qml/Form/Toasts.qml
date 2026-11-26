import QtQuick

// Toasts: bottom right, newest at the bottom. Each is a pane of glass with a state dot: green when it went well, red
// when it failed. They fade in and rise 8 px, wait (longer for a failure, and while the pointer rests on them), and
// leave faster than they came. Click to dismiss.
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
            // The list is replaced whenever a toast comes or goes, which rebuilds every card. A card that was already
            // on screen must neither rise in again nor start its wait over: both go by when the toast was made.
            readonly property int life: modelData.bad ? 7000 : 3400
            readonly property int age: Date.now() - (modelData.ts || Date.now())
            width: tc.width; height: card.height
            // a toast can sit on a button anywhere (a sheet's, a setup step's Continue): it always lets clicks through
            // and turns see-through under the pointer, so the button below is never blocked
            readonly property bool overSheet: true
            opacity: overSheet && hov.hovered ? 0.18 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            function leave() { if (leaving) return; leaving = true; out.start() }
            Glass {
                id: card
                source: Store.backdrop; shadow: false
                width: parent.width; height: tcol.implicitHeight + 26; radius: Theme.rLg
                opacity: t.age > 250 ? 1 : 0; y: t.age > 250 ? 0 : Theme.shift(Theme.rise)
                Shadow { radius: card.radius; spread: 20; drop: 9 }
                Rectangle { anchors.fill: parent; radius: card.radius; color: Theme.alpha(Theme.plate3, card.blurred ? 0.58 : 0.85) }
                Rectangle { x: 16; y: 20; width: 6; height: 6; radius: 3; color: t.modelData.bad ? Theme.signal : Theme.pass
                    Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Theme.alpha(parent.color, 0.18) } }
                Column { id: tcol; x: 32; y: 13; width: parent.width - 32 - 16; spacing: 2
                    Txt { text: t.modelData.msg; width: parent.width; font.weight: Theme.wSemi }
                    Txt { kind: "fine"; visible: t.modelData.hint !== ""; text: t.modelData.hint; width: parent.width; color: Theme.ink2 } }
                HoverHandler { id: hov }
                MouseArea { anchors.fill: parent; enabled: !t.overSheet; onClicked: t.leave() }
            }
            Component.onCompleted: if (t.age <= 250) inn.start()
            SequentialAnimation { id: inn
                ParallelAnimation {
                    Glide { target: card; property: "opacity"; to: 1; duration: Theme.base }
                    Glide { target: card; property: "y"; to: 0; duration: Theme.move(Theme.base) } }
                ScriptAction { script: card.place() } }
            SequentialAnimation { id: out
                ParallelAnimation {
                    NumberAnimation { target: card; property: "opacity"; to: 0; duration: Theme.exit }
                    NumberAnimation { target: card; property: "y"; to: Theme.shift(4); duration: Theme.exit } }
                ScriptAction { script: Store.dropToast(t.modelData.id) } }
            Timer { running: !hov.hovered && !t.leaving; interval: Math.max(600, t.life - t.age); onTriggered: t.leave() }
        }
    }
}
