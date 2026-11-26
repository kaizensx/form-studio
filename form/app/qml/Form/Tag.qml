import QtQuick

// Evidence tag: how a number is known, or what happened to a feature. The colour is the evidence class
// (Theme.evidence); the tag never animates and never changes size on hover: it is a label, not a control.
Rectangle {
    id: r
    property string text: ""
    property string kind: text
    property color tint: Theme.evidence(kind)
    implicitHeight: 17; implicitWidth: lbl.implicitWidth + 12; radius: Theme.rXs
    color: Theme.alpha(tint, 0.1); border.width: 1; border.color: Theme.alpha(tint, 0.16)
    Text { id: lbl; anchors.centerIn: parent; text: r.text; color: r.tint
        font.family: Theme.mono; font.pixelSize: 10; font.weight: Theme.wMedium; font.letterSpacing: 0.4; font.capitalization: Font.AllUppercase; renderType: Text.NativeRendering }
}
