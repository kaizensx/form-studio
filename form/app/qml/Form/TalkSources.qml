import QtQuick

// What a reply rests on. Every row is one tool call of that turn whose result says how its content is known
// (form/cite.py reads it from the call and its result, never from the reply's words): its number, what it is, and the
// evidence word. A number in the reply carries the same index only when that number stands in the row's result.
TalkCard {
    id: src
    objectName: "sourcesCard"
    property var list: []                    // [{ n, title, how }]
    title: "Sources"
    note: list.length + " · from the tool log"
    Repeater {
        model: src.list
        Item {
            id: row; objectName: "sourceRow"
            required property var modelData
            readonly property string how: modelData.how
            width: parent.width; height: Math.max(26, name.implicitHeight + 8)
            Txt { x: 0; anchors.baseline: name.baseline; width: 16; mono: true; font.pixelSize: 12; font.weight: Theme.wMedium; color: Theme.datum; text: row.modelData.n }
            Txt { id: name; x: 26; y: 4; width: parent.width - 26 - ev.implicitWidth - 10; tone: 2; font.pixelSize: 13; lineHeight: 1.3
                wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; text: row.modelData.title }
            Ev { id: ev; objectName: "sourceHow"; anchors.right: parent.right; anchors.baseline: name.baseline; text: row.modelData.how }
            HoverHandler { id: hh }
            Tip { show: hh.hovered; text: ({ simulated: "Simulated: a model of what would happen, not a measurement of it.",
                    computed: "Computed by the kernel or the engine from the design itself.",
                    specified: "Specified: from a standard, a datasheet or the material library.",
                    opened: "Opened this turn: the agent read this file or page.",
                    measured: "Measured: a number you measured and gave.",
                    assumed: "Assumed: not measured and not specified." })[row.modelData.how] || "The tool result names this as how it is known." }
        }
    }
}
