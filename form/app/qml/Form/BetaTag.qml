import QtQuick

// "Beta" beside something that works but is still being improved (game assets). Calm on purpose: small mono capitals
// in the accent on the faintest tint of it, never a colour that reads as a warning. Its tip says what Beta means here.
Rectangle {
    id: b
    objectName: "betaTag"
    property string text: "Beta"
    property string tip: "Game assets are in Beta: they work, and their visual quality is still improving."
    implicitHeight: 16; implicitWidth: lbl.implicitWidth + 12; radius: height / 2
    color: Theme.alpha(Theme.datum, 0.12)
    Text { id: lbl; anchors.centerIn: parent; text: b.text; color: Theme.datum; font.capitalization: Font.AllUppercase
        font.family: Theme.mono; font.pixelSize: 10; font.weight: Theme.wMedium; font.letterSpacing: 0.8; renderType: Theme.textRender }
    MouseArea { id: bm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
    Tip { show: bm.containsMouse && b.tip !== ""; text: b.tip }
}
