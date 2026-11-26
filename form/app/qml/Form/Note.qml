import QtQuick

// kind: plain | amber | red | green | blue. `title` is bold, `text` follows.
// A note is a thin pane of tinted glass; one that carries a meaning has that meaning's dot before its words.
Rectangle {
    id: n
    property string kind: "plain"
    property string title: ""
    property string text: ""
    default property alias content: col.data
    readonly property color tint: kind === "amber" ? Theme.amber : kind === "red" ? Theme.signal : kind === "green" ? Theme.pass : kind === "blue" ? Theme.blueprint : Theme.ink
    readonly property bool dotted: kind !== "plain"
    width: parent ? parent.width : 0
    implicitHeight: col.implicitHeight + 24; radius: 14
    color: kind === "plain" ? Theme.glass : Theme.alpha(tint, Theme.dark ? 0.09 : 0.075)
    Rectangle { visible: n.dotted; x: 14; y: 19; width: 6; height: 6; radius: 3; color: n.tint }
    Column {
        id: col; x: n.dotted ? 30 : 14; y: 12; width: parent.width - x - 14; spacing: 4
        Txt { visible: n.title !== ""; text: n.title; width: parent.width; font.weight: Theme.wSemi; color: Theme.ink }
        Txt { visible: n.text !== ""; text: n.text; width: parent.width; font.pixelSize: 13; color: Theme.ink2; lineHeight: 1.3 }
    }
}
