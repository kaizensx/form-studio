import QtQuick

// kind: plain | amber | red | green | blue. `title` is bold, `text` follows.
Rectangle {
    id: n
    property string kind: "plain"
    property string title: ""
    property string text: ""
    default property alias content: col.data
    readonly property color tint: kind === "amber" ? Theme.amber : kind === "red" ? Theme.signal : kind === "green" ? Theme.pass : kind === "blue" ? Theme.blueprint : Theme.ink
    width: parent ? parent.width : 0
    implicitHeight: col.implicitHeight + 20; radius: Theme.rMd
    color: Theme.alpha(tint, kind === "plain" ? 0.04 : 0.085)
    Column {
        id: col; x: 12; y: 10; width: parent.width - 24; spacing: 4
        Txt { visible: n.title !== ""; text: n.title; width: parent.width; font.weight: 600; color: n.kind === "plain" ? Theme.ink : (Theme.dark ? Qt.lighter(n.tint, 1.25) : Qt.darker(n.tint, 1.25)) }
        Txt { visible: n.text !== ""; text: n.text; width: parent.width; font.pixelSize: 13; color: n.kind === "plain" ? Theme.ink2 : (Theme.dark ? Qt.lighter(n.tint, 1.35) : Qt.darker(n.tint, 1.45)); lineHeight: 1.3 }
    }
}
