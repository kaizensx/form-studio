import QtQuick

// Single-line text or number input. Inputs are inset wells: darker than their surroundings.
Rectangle {
    id: f
    property alias text: input.text
    property string placeholder: ""
    property bool numeric: false
    property bool mono: numeric
    property alias input: input
    property string unit: ""
    signal accepted(string text)
    signal edited(string text)
    implicitHeight: 28; implicitWidth: 120; radius: Theme.rSm
    color: Theme.well; border.width: 1; border.color: input.activeFocus ? Theme.datum : Theme.rule2
    Behavior on border.color { ColorAnimation { duration: Theme.fast } }
    TextInput {
        id: input
        anchors.fill: parent; anchors.leftMargin: 9; anchors.rightMargin: f.unit ? 9 + u.implicitWidth + 4 : 9
        verticalAlignment: TextInput.AlignVCenter; horizontalAlignment: f.numeric ? TextInput.AlignRight : TextInput.AlignLeft
        color: Theme.ink; selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink
        font.family: f.mono ? Theme.mono : Theme.sans; font.pixelSize: f.mono ? 12 : 13; clip: true; selectByMouse: true
        renderType: Text.NativeRendering
        inputMethodHints: f.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
        onAccepted: { f.accepted(text); if (f.numeric) focus = false }
        onTextEdited: f.edited(text)
        onActiveFocusChanged: if (!activeFocus && f.numeric) f.accepted(text)
        Text { visible: !input.text && !input.activeFocus || (!input.text && f.placeholder !== ""); text: f.placeholder; color: Theme.ink4; font: input.font
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: input.horizontalAlignment; elide: Text.ElideRight; renderType: Text.NativeRendering }
    }
    Txt { id: u; visible: f.unit !== ""; text: f.unit; kind: "fine"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }
}
