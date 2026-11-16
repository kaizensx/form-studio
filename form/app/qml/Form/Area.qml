import QtQuick
import QtQuick.Controls

// Multi-line text. Emits `submit` on Enter when submitOnEnter is set (Shift+Enter makes a new line).
Rectangle {
    id: a
    property alias text: ta.text
    property string placeholder: ""
    property bool submitOnEnter: false
    property int minLines: 3
    property alias area: ta
    signal submit(string text)
    signal blurred(string text)
    implicitHeight: Math.min(220, Math.max(minLines * 19 + 16, ta.implicitHeight + 4)); radius: Theme.rMd
    color: Theme.well; border.width: 1; border.color: ta.activeFocus ? Theme.datum : Theme.rule2
    Behavior on border.color { ColorAnimation { duration: Theme.fast } }
    ScrollView {
        anchors.fill: parent; clip: true
        TextArea {
            id: ta
            wrapMode: TextArea.Wrap; color: Theme.ink; font.family: Theme.sans; font.pixelSize: 13
            placeholderText: a.placeholder; placeholderTextColor: Theme.ink4
            selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink; selectByMouse: true
            padding: 9; background: null; renderType: Text.NativeRendering
            Keys.onPressed: function (e) {
                if (a.submitOnEnter && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { e.accepted = true; a.submit(text) }
            }
            onActiveFocusChanged: if (!activeFocus) a.blurred(text)
        }
    }
}
