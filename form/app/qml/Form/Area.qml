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
    opacity: enabled ? 1 : 0.5
    color: Theme.well; border.width: 1; border.color: ta.activeFocus ? Theme.datum : hh.hovered ? Theme.rule3 : Theme.rule2
    Behavior on border.color { Tint {} }
    HoverHandler { id: hh }
    Rectangle { anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3
        border.color: Theme.alpha(Theme.datum, 0.16); opacity: ta.activeFocus ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
    ScrollView {
        anchors.fill: parent; clip: true
        TextArea {
            id: ta
            wrapMode: TextArea.Wrap; color: Theme.ink; font.family: Theme.sans; font.pixelSize: 13
            placeholderText: a.placeholder; placeholderTextColor: Theme.ink4
            selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink; selectByMouse: true
            padding: 9; background: null; renderType: Text.NativeRendering
            // Tab moves on to the next control instead of typing a tab
            Keys.onTabPressed: function (e) { var n = nextItemInFocusChain(true); if (n) n.forceActiveFocus(Qt.TabFocusReason) }
            Keys.onBacktabPressed: function (e) { var n = nextItemInFocusChain(false); if (n) n.forceActiveFocus(Qt.BacktabFocusReason) }
            Keys.onPressed: function (e) {
                if (a.submitOnEnter && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { e.accepted = true; a.submit(text) }
            }
            onActiveFocusChanged: if (!activeFocus) a.blurred(text)
        }
    }
}
