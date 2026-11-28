import QtQuick

// A card in the conversation: a quiet well with a hairline, a caption in mono capitals at the left of its head and a
// note at the right. Sources, the plan and a revision are all this card; what differs is what stands under the head.
Rectangle {
    id: card
    property string title: ""
    property string note: ""
    property color noteColor: Theme.ink3
    property bool lit: false                 // it waits for the person: the hairline takes the accent
    default property alias content: body.data
    readonly property real pad: 13
    implicitHeight: body.y + body.implicitHeight + 11
    radius: 14
    color: Theme.alpha(Theme.dark ? "#000000" : "#ffffff", Theme.dark ? 0.20 : 0.55)
    border.width: 1; border.color: lit ? Theme.alpha(Theme.datum, 0.45) : Theme.rule
    Behavior on border.color { Tint {} }
    Txt { id: cap; objectName: "cardTitle"; x: card.pad; y: 11; kind: "cap"; text: card.title; wrapMode: Text.NoWrap }
    Txt { objectName: "cardNote"; anchors.right: parent.right; anchors.rightMargin: card.pad; anchors.baseline: cap.baseline
        mono: true; font.pixelSize: Theme.tCap; color: card.noteColor; text: card.note; wrapMode: Text.NoWrap
        width: Math.min(implicitWidth, card.width - 2 * card.pad - cap.implicitWidth - 12); elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
    Column { id: body; x: card.pad; y: 32; width: card.width - 2 * card.pad }
}
