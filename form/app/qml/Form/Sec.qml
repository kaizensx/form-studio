import QtQuick

// A titled group in an inspector. Children stack in a column.
Column {
    id: c
    property string title: ""
    property string note: ""
    property string tag: ""
    width: parent ? parent.width : 0
    spacing: 8
    topPadding: 16; bottomPadding: 4
    Cap { visible: c.title !== ""; text: c.title; note: c.note; tag: c.tag; width: c.width }
}
