import QtQuick

// Evidence tag: how a number is known, or what happened to a feature. The colour is the evidence class
// (Theme.evidence); the tag never animates and never changes size on hover: it is a label, not a control.
Rectangle {
    id: r
    property string text: ""
    property string kind: text
    property color tint: Theme.evidence(kind)
    implicitHeight: 21; implicitWidth: lbl.implicitWidth + 16; radius: height / 2
    color: tint === Theme.ink2 ? Theme.alpha(Theme.lineBase, Theme.dark ? 0.14 : 0.07) : Theme.alpha(tint, 0.14); border.width: 0
    Text { id: lbl; anchors.centerIn: parent; text: r.text; color: r.tint
        font.family: Theme.mono; font.pixelSize: Theme.tEv; font.weight: Theme.wMedium; font.letterSpacing: Theme.tagTrack; font.capitalization: Font.AllUppercase; renderType: Theme.textRender }
}
