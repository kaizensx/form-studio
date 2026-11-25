import QtQuick

// "Beta" beside something that works but is still being improved (game assets). Calm on purpose: a hairline pill in
// the quiet ink, never a colour that reads as a warning. Its tip says what Beta means here.
Rectangle {
    id: b
    objectName: "betaTag"
    property string text: "Beta"
    property string tip: "Game assets are in Beta: they work, and their visual quality is still improving."
    implicitHeight: 16; implicitWidth: lbl.implicitWidth + 10; radius: height / 2
    color: Theme.washOn; border.width: 1; border.color: Theme.rule2
    Text { id: lbl; anchors.centerIn: parent; text: b.text; color: Theme.ink2
        font.family: Theme.sans; font.pixelSize: 10; font.weight: Theme.wSemi; font.letterSpacing: 0.4; renderType: Text.NativeRendering }
    MouseArea { id: bm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
    Tip { show: bm.containsMouse && b.tip !== ""; text: b.tip }
}
