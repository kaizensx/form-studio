import QtQuick

// Single-line text or number input. Inputs are wells set into the glass: Theme.glassWell, a 1 px edge, the accent on focus.
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
    implicitHeight: Theme.hMd; implicitWidth: 120; radius: Math.min(Theme.rMd, height / 2)
    opacity: enabled ? 1 : 0.5
    // the well keeps its quiet edge under the pointer (the fill lifts a wash instead), so a form of fields stays
    // calm on a sheet; the edge changes only for meaning: focus (datum) and a mistake (signal)
    color: bare ? "transparent" : hh.hovered && !input.activeFocus ? Qt.tint(Theme.glassWell, Theme.washHover) : Theme.glassWell
    border.width: bare ? 0 : 1
    border.color: invalid ? Theme.signal : input.activeFocus ? Theme.datum : Theme.rule
    Behavior on color { Tint {} }
    Behavior on border.color { Tint {} }
    HoverHandler { id: hh; cursorShape: Qt.IBeamCursor }
    // the focus halo: a soft second edge, so focus reads from across the room
    Rectangle { visible: !f.bare; anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3
        border.color: Theme.alpha(f.invalid ? Theme.signal : Theme.datum, 0.18); opacity: input.activeFocus ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
    TextInput {
        id: input
        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: (f.unit ? 10 + u.implicitWidth + 4 : 10) + (f.busy ? 20 : 0)
        verticalAlignment: TextInput.AlignVCenter; horizontalAlignment: f.numeric ? TextInput.AlignRight : TextInput.AlignLeft
        color: Theme.ink; selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink
        font.family: f.mono ? Theme.mono : Theme.sans; font.pixelSize: f.mono ? 12 : 13; clip: true; selectByMouse: true
        renderType: Theme.textRender; activeFocusOnTab: true
        cursorDelegate: Caret {}
        inputMethodHints: f.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
        onAccepted: { f.accepted(text); if (f.numeric) focus = false }
        onTextEdited: f.edited(text)
        onActiveFocusChanged: if (!activeFocus && f.numeric) f.accepted(text)
        Text { visible: !input.text && !input.activeFocus || (!input.text && f.placeholder !== ""); text: f.placeholder; color: Theme.ink4; font: input.font
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: input.horizontalAlignment; elide: Text.ElideRight; renderType: Theme.textRender }
    }
    Txt { id: u; visible: f.unit !== ""; text: f.unit; kind: "fine"; mono: true; anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter }
    Spinner { visible: f.busy; size: 13; anchors.right: parent.right; anchors.rightMargin: f.unit ? 13 + u.implicitWidth : 8; anchors.verticalCenter: parent.verticalCenter }
    Txt { visible: f.invalid; kind: "fine"; color: Theme.signal; text: f.error; y: parent.height + 4; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
}
