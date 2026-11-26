import QtQuick

// The edge of a plate that shows something drawn square (the 3D view): rounds its corners with the frame's own
// colour, then draws the plate's hairline and the registration ticks of a drawing sheet in its corners. Put it over
// the content, filling it. It takes no input.
Item {
    id: f
    anchors.fill: parent
    property real radius: Theme.rPanel
    property color ground: Theme.frame
    property bool ticks: true
    readonly property int cover: 6
    // a thick border of the frame's colour, outside the plate: its inner edge is the plate's rounded corner
    Rectangle { anchors.fill: parent; anchors.margins: -f.cover; radius: f.radius + f.cover; color: "transparent"
        border.width: f.cover; border.color: f.ground; antialiasing: true }
    Rectangle { anchors.fill: parent; radius: f.radius; color: "transparent"; border.width: 1; border.color: Theme.panelEdge; antialiasing: true }
    // registration ticks: the corners of the sheet the part is drawn on
    Repeater {
        model: f.ticks ? 4 : 0
        Item {
            required property int index
            readonly property bool r: index % 2 === 1
            readonly property bool b: index >= 2
            x: r ? f.width - 14 - 12 : 14; y: b ? f.height - 14 - 12 : 14; width: 12; height: 12; opacity: 0.55
            Rectangle { x: parent.r ? parent.width - 1 : 0; width: 1; height: parent.height; color: Theme.rule3 }
            Rectangle { y: parent.b ? parent.height - 1 : 0; width: parent.width; height: 1; color: Theme.rule3 }
        }
    }
}
