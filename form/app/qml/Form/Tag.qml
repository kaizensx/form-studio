import QtQuick

// Evidence tag: how a number is known, or what happened to a feature.
Rectangle {
    id: r
    property string text: ""
    property string kind: text
    property color tint: Theme.evidence(kind)
    implicitHeight: 17; implicitWidth: lbl.implicitWidth + 12; radius: 3
    color: Theme.alpha(tint, 0.11)
    Text { id: lbl; anchors.centerIn: parent; text: r.text; color: r.tint
        font.family: Theme.sans; font.pixelSize: 10; font.weight: 650; font.letterSpacing: 0.6; font.capitalization: Font.AllUppercase; renderType: Text.NativeRendering }
}
