import QtQuick

// Single-line text or number input. Inputs are inset wells: darker than their surroundings.
// `error` (a short sentence) turns the edge red and shows the sentence under the field; `busy` shows a spinner at the right.
Rectangle {
    id: f
    property alias text: input.text
    property string placeholder: ""
    property bool numeric: false
    property bool mono: numeric
    property alias input: input
    property string unit: ""
    property string error: ""
    property bool busy: false
    readonly property bool invalid: error !== ""
    property bool bare: false                // no well, no edge, no halo: the field is part of a larger surface (the palette)
    signal accepted(string text)
    signal edited(string text)
    implicitHeight: Theme.hMd; implicitWidth: 120; radius: Theme.rSm
    opacity: enabled ? 1 : 0.5
    color: bare ? "transparent" : Theme.well; border.width: bare ? 0 : 1
    border.color: invalid ? Theme.signal : input.activeFocus ? Theme.datum : hh.hovered ? Theme.rule3 : Theme.rule2
    Behavior on border.color { Tint {} }
    HoverHandler { id: hh; cursorShape: Qt.IBeamCursor }
    // the focus halo: a soft second edge, so focus reads from across the room
    Rectangle { visible: !f.bare; anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3
        border.color: Theme.alpha(f.invalid ? Theme.signal : Theme.datum, 0.16); opacity: input.activeFocus ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
    TextInput {
        id: input
        anchors.fill: parent; anchors.leftMargin: 9; anchors.rightMargin: (f.unit ? 9 + u.implicitWidth + 4 : 9) + (f.busy ? 20 : 0)
        verticalAlignment: TextInput.AlignVCenter; horizontalAlignment: f.numeric ? TextInput.AlignRight : TextInput.AlignLeft
        color: Theme.ink; selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink
        font.family: f.mono ? Theme.mono : Theme.sans; font.pixelSize: f.mono ? 12 : 13; clip: true; selectByMouse: true
        renderType: Text.NativeRendering; activeFocusOnTab: true
        inputMethodHints: f.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
        onAccepted: { f.accepted(text); if (f.numeric) focus = false }
        onTextEdited: f.edited(text)
        onActiveFocusChanged: if (!activeFocus && f.numeric) f.accepted(text)
        Text { visible: !input.text && !input.activeFocus || (!input.text && f.placeholder !== ""); text: f.placeholder; color: Theme.ink4; font: input.font
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: input.horizontalAlignment; elide: Text.ElideRight; renderType: Text.NativeRendering }
    }
    Txt { id: u; visible: f.unit !== ""; text: f.unit; kind: "fine"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }
    Spinner { visible: f.busy; size: 13; anchors.right: parent.right; anchors.rightMargin: f.unit ? 13 + u.implicitWidth : 8; anchors.verticalCenter: parent.verticalCenter }
    Txt { visible: f.invalid; kind: "fine"; color: Theme.signal; text: f.error; y: parent.height + 4; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
}
