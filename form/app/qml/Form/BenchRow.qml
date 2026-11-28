import QtQuick

// One row of the Bench (direction I, decision 4): the same grammar for a feature, a study, a route and a document.
//   a state dot · a name · a number · the word that says how the number is known
// state: "ok" | "warn" | "fail" | "none" (not run: a ring) | "stale" (an amber ring) | "live" (running, cyan).
// A row with no number says its state in words in the number's place (`word`: not run, describes r05, needs joints);
// a row that cannot run is `dim`. The selected row is on raised glass with its evidence word lit; what it opens is
// drawn under the list (BenchCard), never inside the row. While the pointer is on a row, the feature or region it is
// about (`lights`) is lit on the part, and its run mark stands in the tail (`runIcon`; empty: none).
Item {
    id: br
    property string state: "none"
    property string name: ""
    property string sub: ""              // a second line under the name (the Bench sheet's rows); empty: one line
    property string value: ""
    property string evidence: ""
    property string word: ""             // the state in words, when there is no number to show
    property color wordColor: Theme.ink3
    property bool dim: false
    property bool selected: false
    property bool chevron: false         // the row leads back: a ‹ in the gutter
    property string lights: ""           // a feature id: lit on the part while the pointer is on the row
    property string runIcon: ""          // the run mark under the pointer
    property string runTip: ""
    property string tip: ""
    property int gutter: 28              // where the dot's column begins
    readonly property bool hovered: bm.containsMouse || gm.containsMouse
    readonly property int line: sub !== "" ? 50 : 32
    signal clicked()
    signal run()
    width: parent ? parent.width : 0
    height: line
    readonly property color dot: state === "ok" ? Theme.pass : state === "warn" || state === "stale" ? Theme.amber : state === "fail" ? Theme.signal : state === "live" ? Theme.datum : Theme.ink3
    readonly property bool ring: state === "none" || state === "stale"
    Rectangle { anchors.fill: parent; radius: 10
        color: br.selected ? Theme.glass2 : bm.pressed ? Theme.washPress : br.hovered ? Theme.washHover : "transparent"
        Behavior on color { Tint {} } }
    Item { x: br.gutter; width: 22; height: br.line; opacity: br.dim ? 0.5 : 1
        Icon { visible: br.chevron; anchors.centerIn: parent; name: "chevron_left"; size: 13; color: Theme.ink3 }
        Rectangle { id: mark; objectName: "benchDot"; visible: !br.chevron; anchors.centerIn: parent; width: 7; height: 7; radius: 3.5
            color: br.ring ? "transparent" : br.dot; border.width: br.ring ? 1.5 : 0; border.color: br.dot
            Glow { color: Theme.datum; blur: 8; strength: 0.8; on: br.state === "live" }
            SequentialAnimation on opacity { running: br.state === "live" && !Theme.reduced && br.visible; loops: Animation.Infinite
                NumberAnimation { to: 0.45; duration: 620; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 620; easing.type: Easing.InOutSine } } } }
    Column { x: br.gutter + 30; anchors.verticalCenter: parent.verticalCenter; width: Math.max(40, tail.x - x - 8); spacing: 1; opacity: br.dim ? 0.5 : 1
        Txt { id: nm; width: parent.width; text: br.name; font.weight: br.selected ? Theme.wSemi : Theme.wMedium; elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Txt { visible: br.sub !== ""; width: parent.width; text: br.sub; kind: "fine"; tone: 3; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
    // the tail: the number and how it is known, or the state in words. In the sheet's two-line rows they stack.
    Grid { id: tail; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
        columns: br.sub !== "" ? 1 : 3; columnSpacing: 9; rowSpacing: 2; horizontalItemAlignment: Grid.AlignRight; verticalItemAlignment: Grid.AlignVCenter
        opacity: go.visible ? 0 : 1
        readonly property real room: Math.max(60, br.width - br.gutter - 30 - Math.min(Math.ceil(nm.implicitWidth) + 2, br.width * 0.5) - 30)      // the name first: the number takes what is left
        Txt { objectName: "benchValue"; visible: text !== ""; mono: true; font.pixelSize: br.sub !== "" ? 12 : 11; font.weight: Theme.wMedium; tone: br.sub !== "" ? 1 : 2
            text: br.word !== "" ? "" : br.value; opacity: br.dim ? 0.5 : 1; wrapMode: Text.NoWrap; elide: Text.ElideRight
            width: Math.min(implicitWidth, tail.room - (br.sub !== "" ? 0 : ev.implicitWidth + 9)) }
        Ev { id: ev; visible: text !== ""; text: br.word !== "" ? "" : br.evidence; lit: br.selected }
        Txt { objectName: "benchState"; visible: text !== ""; font.pixelSize: 11; color: br.wordColor; opacity: br.dim ? 0.75 : 1
            text: br.word; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, tail.room) } }
    MouseArea { id: bm; anchors.fill: parent; hoverEnabled: true; onClicked: br.clicked()
        onContainsMouseChanged: if (br.lights !== "" && Store.viewer) Store.viewer.hovered = containsMouse ? br.lights : (Store.viewer.hovered === br.lights ? "" : Store.viewer.hovered) }
    Item { id: go; objectName: "benchRun"; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter; width: 24; height: 24
        visible: br.runIcon !== "" && br.hovered && br.word !== ""
        Rectangle { anchors.fill: parent; radius: 7; color: gm.containsMouse ? Theme.plate4 : Theme.plate3 }
        Icon { anchors.centerIn: parent; size: 12; color: Theme.ink; name: br.runIcon }
        MouseArea { id: gm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: br.run() } }
    Tip { show: bm.containsMouse && !gm.containsMouse && br.tip !== ""; text: br.tip }
    Tip { show: gm.containsMouse && br.runTip !== ""; text: br.runTip }
}
