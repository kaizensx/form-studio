import QtQuick

// The cue: the build's lower third, a film title over the room. "BUILDING 6 OF 12", the feature being made in large
// type with its place in the build order, a track with one segment per step (the current one glowing), and the
// feature before and after. Every value is given by the caller from the real build (the stages the kernel streams, or
// the steps of the viewport's build-up); nothing here counts on its own.
//
// A new feature slides up into place as the last one leaves; the track fills smoothly. Reduce Motion: cross-fades.
Item {
    id: cue
    property string label: ""                // the feature arriving, or the one that arrived last
    property int at: 0                       // 1-based step; 0 with `of` 0 = no count
    property int of: 0
    property bool running: true              // false once the build is in: "Built"
    property bool pulse: false               // the dot breathes (a build streamed from the agent)
    property string before: ""               // the feature built just before this one, "" when there is none
    property string after: ""                // the one that comes next
    readonly property real frac: !running ? 1 : of > 0 ? Math.max(0, Math.min(1, at / of)) : 0
    readonly property bool segmented: of > 1 && of <= 32
    function nn(i) { return (i < 10 ? "0" : "") + i }
    width: 600
    implicitHeight: col.implicitHeight; height: implicitHeight

    Column {
        id: col; width: parent.width; spacing: 0
        // BUILDING  6 OF 12
        Row { id: over; anchors.horizontalCenter: parent.horizontalCenter; spacing: 10; height: 16
            Item { width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Theme.alpha(Theme.datum, 0.22)
                    SequentialAnimation on scale { running: cue.pulse && cue.visible && !Theme.reduced; loops: Animation.Infinite
                        NumberAnimation { to: 1.35; duration: 800; easing.type: Easing.InOutSine } NumberAnimation { to: 1; duration: 800; easing.type: Easing.InOutSine } } }
                Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: Theme.datum } }
            Text { objectName: "buildLedgerState"; anchors.verticalCenter: parent.verticalCenter; text: cue.running ? "BUILDING" : "BUILT"; color: Theme.datum; renderType: Text.NativeRendering
                font.family: Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.8 }
            Text { objectName: "buildLedgerCount"; visible: cue.of > 1; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink2; renderType: Text.NativeRendering
                // read as "6 of 12" by tests and screen readers; set in capitals by the font
                text: cue.at + " of " + cue.of; font.capitalization: Font.AllUppercase
                font.family: Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.8 } }
        Item { width: 1; height: 12 }
        // 06 Board screw holes — two lines of type hand over to each other
        Item { id: title; width: parent.width; height: 60; clip: false
            property string shown: ""
            property int shownAt: 0
            property string leaving: ""
            property int leavingAt: 0
            function take() {
                if (cue.label === shown && cue.at === shownAt) return
                if (shown !== "") { leaving = shown; leavingAt = shownAt; out.restart() }
                shown = cue.label; shownAt = cue.at
                if (cue.label !== "") come.restart()
            }
            Connections { target: cue; function onLabelChanged() { title.take() } function onAtChanged() { title.take() } }
            Component.onCompleted: take()
            Row { id: now; objectName: "buildLedgerName"; property string text: title.shown; transform: Translate { id: nowY }
                spacing: 14; anchors.horizontalCenter: parent.horizontalCenter
                Text { visible: title.shownAt > 0; text: cue.nn(title.shownAt); color: Theme.datum; y: 8; renderType: Text.NativeRendering
                    font.family: Theme.mono; font.pixelSize: 20; font.weight: Theme.wMedium }
                Text { text: title.shown; color: Theme.ink; renderType: Text.NativeRendering
                    width: Math.min(implicitWidth, cue.width + 220 - (title.shownAt > 0 ? 44 : 0)); elide: Text.ElideRight
                    font.family: Theme.sans; font.pixelSize: String(title.shown).length > 24 ? 38 : Theme.tCue; font.weight: Theme.wSemi; font.letterSpacing: -2 } }
            Row { id: old; opacity: 0; transform: Translate { id: oldY }
                spacing: 14; anchors.horizontalCenter: parent.horizontalCenter
                Text { visible: title.leavingAt > 0; text: cue.nn(title.leavingAt); color: Theme.datum; y: 8; renderType: Text.NativeRendering
                    font.family: Theme.mono; font.pixelSize: 20; font.weight: Theme.wMedium }
                Text { text: title.leaving; color: Theme.ink; renderType: Text.NativeRendering
                    width: Math.min(implicitWidth, cue.width + 220 - (title.leavingAt > 0 ? 44 : 0)); elide: Text.ElideRight
                    font.family: Theme.sans; font.pixelSize: String(title.leaving).length > 24 ? 38 : Theme.tCue; font.weight: Theme.wSemi; font.letterSpacing: -2 } }
            ParallelAnimation { id: come
                NumberAnimation { target: now; property: "opacity"; from: 0; to: 1; duration: Theme.cross; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
                NumberAnimation { target: nowY; property: "y"; from: Theme.shift(22); to: 0; duration: Theme.move(360); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
            ParallelAnimation { id: out
                NumberAnimation { target: old; property: "opacity"; from: 1; to: 0; duration: Theme.base; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
                NumberAnimation { target: oldY; property: "y"; from: 0; to: -Theme.shift(18); duration: Theme.move(Theme.cross); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        }
        Item { width: 1; height: 22 }
        // the track: one segment per step; a long build is one bar
        Item { id: track; width: parent.width; height: 5
            readonly property color rest: Theme.alpha(Theme.lineBase, Theme.dark ? 0.13 : 0.12)
            Row { visible: cue.segmented; anchors.fill: parent; spacing: 5
                Repeater { model: cue.segmented ? cue.of : 0
                    Rectangle { id: seg; required property int index
                        readonly property bool done: !cue.running || index + 1 < cue.at
                        readonly property bool current: cue.running && index + 1 === cue.at
                        width: (track.width - 5 * (cue.of - 1)) / cue.of; height: 5; radius: 2.5; color: track.rest
                        // the glow under the segment being built
                        Rectangle { visible: seg.current; anchors.centerIn: parent; width: parent.width + 14; height: 19; radius: 9.5; color: Theme.alpha(Theme.datum, 0.16)
                            SequentialAnimation on opacity { running: seg.current && cue.visible && !Theme.reduced; loops: Animation.Infinite
                                NumberAnimation { to: 0.45; duration: 900; easing.type: Easing.InOutSine } NumberAnimation { to: 1; duration: 900; easing.type: Easing.InOutSine } } }
                        Rectangle { height: 5; radius: 2.5; color: seg.done ? Theme.ink : Theme.datum
                            width: parent.width * k
                            // a segment fills when its step starts (to a little over half: the step is under way) and to the end when it is built
                            property real k: seg.done ? 1 : seg.current ? 0.55 : 0
                            Behavior on k { NumberAnimation { duration: Theme.reduced ? 0 : 220; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
                            Behavior on color { ColorAnimation { duration: Theme.cross } } } } } }
            Rectangle { visible: !cue.segmented; anchors.fill: parent; radius: 2.5; color: track.rest
                Rectangle { objectName: cue.segmented ? "" : "buildLedgerBar"; height: 5; radius: 2.5; color: cue.running ? Theme.datum : Theme.ink; width: parent.width * k
                    property real k: cue.of > 0 || !cue.running ? cue.frac : 0.12
                    Behavior on k { NumberAnimation { duration: Theme.cross; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } } }
            // what tests and the tree read: how far the build is, 0..1
            Item { objectName: cue.segmented ? "buildLedgerBar" : ""; property real k: cue.frac; width: 1; height: 1 }
        }
        Item { width: 1; height: 14 }
        // built 05 PCB standoffs                                  next 07 USB-C openings
        Item { width: parent.width; height: 16; visible: cue.before !== "" || cue.after !== ""
            Row { visible: cue.before !== ""; spacing: 8
                Text { text: "built"; color: Theme.ink3; font.family: Theme.sans; font.pixelSize: 13; renderType: Text.NativeRendering }
                Text { text: cue.nn(cue.at - 1); color: Theme.ink2; font.family: Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium; anchors.baseline: parent.children[0].baseline; renderType: Text.NativeRendering }
                Text { objectName: "cueBefore"; text: cue.before; color: Theme.ink3; font.family: Theme.sans; font.pixelSize: 13; renderType: Text.NativeRendering
                    width: Math.min(implicitWidth, cue.width / 2 - 90); elide: Text.ElideRight } }
            Row { visible: cue.after !== ""; spacing: 8; anchors.right: parent.right
                Text { text: "next"; color: Theme.ink3; font.family: Theme.sans; font.pixelSize: 13; renderType: Text.NativeRendering }
                Text { text: cue.nn(cue.at + 1); color: Theme.ink2; font.family: Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium; anchors.baseline: parent.children[0].baseline; renderType: Text.NativeRendering }
                Text { objectName: "cueAfter"; text: cue.after; color: Theme.ink3; font.family: Theme.sans; font.pixelSize: 13; renderType: Text.NativeRendering
                    width: Math.min(implicitWidth, cue.width / 2 - 90); elide: Text.ElideRight } } }
    }
}
