import QtQuick

// The options of the active tool: one capsule of glass at the head of the stage, always in the same place, so the
// hand learns it (docs/design/directions/i/IA.md, decision 9). Its title names the tool; what follows are that tool's
// options. The content changes with the tool at once, with no animation: it is used all day.
// Children are laid out in a row that wraps when the stage is narrow; the capsule grows downward, never sideways
// past `maxWidth`. A capsule that must stay one line (`wrap: false`: the sketch's) is given only what fits by its
// owner, which puts the rest behind a "More" chip; `room` is the width its children have.
Glass {
    id: tc
    property string title: ""
    property real maxWidth: 600
    property bool wrap: true
    property real titleMax: 220              // a long title (a feature's name) is cut with an ellipsis
    default property alias items: flow.data
    readonly property real lead: ttl.visible ? Math.ceil(ttl.width) + 26 : 6
    readonly property real room: Math.max(80, maxWidth - lead - 6)
    radius: 20
    // what is shown in it (childrenRect counts hidden children too: a hidden bar made it stage-wide and two lines tall)
    readonly property var shownRect: { var w = 0, h = 0, c = flow.children
        for (var i = 0; i < c.length; i++) if (c[i].visible && c[i].width > 0) { w = Math.max(w, c[i].x + c[i].width); h = Math.max(h, c[i].y + c[i].height) }
        return { w: w, h: h } }
    readonly property bool empty: shownRect.w <= 0
    width: Math.round(Math.min(maxWidth, lead + shownRect.w + 6))
    height: Math.max(40, Math.round(shownRect.h + 12))
    Txt { id: ttl; objectName: "toolCapsuleTitle"; x: 14; height: 40; verticalAlignment: Text.AlignVCenter; visible: tc.title !== ""
        text: tc.title; font.pixelSize: 13; font.weight: Theme.wSemi; wrapMode: Text.NoWrap
        width: Math.min(implicitWidth, tc.titleMax); elide: Text.ElideRight }
    Flow { id: flow; x: tc.lead; y: 6; width: tc.wrap ? tc.room : 100000; spacing: 4 }
}
