import QtQuick

// The options of the active tool: one capsule of glass at the head of the stage, always in the same place, so the
// hand learns it (docs/design/directions/i/IA.md, decision 9). Its title names the tool; what follows are that tool's
// options. The content changes with the tool at once, with no animation: it is used all day.
// Children are laid out in a row that wraps when the stage is narrow; the capsule grows downward, never sideways
// past `maxWidth`.
Glass {
    id: tc
    property string title: ""
    property real maxWidth: 600
    default property alias items: flow.data
    readonly property real lead: ttl.visible ? Math.ceil(ttl.implicitWidth) + 26 : 6
    radius: 20
    width: Math.round(Math.min(maxWidth, lead + flow.childrenRect.width + 6))
    height: Math.max(40, Math.round(flow.childrenRect.height + 12))
    Txt { id: ttl; objectName: "toolCapsuleTitle"; x: 14; height: 40; verticalAlignment: Text.AlignVCenter; visible: tc.title !== ""
        text: tc.title; font.pixelSize: 13; font.weight: Theme.wSemi; wrapMode: Text.NoWrap }
    Flow { id: flow; x: tc.lead; y: 6; width: Math.max(80, tc.maxWidth - tc.lead - 6); spacing: 4 }
}
