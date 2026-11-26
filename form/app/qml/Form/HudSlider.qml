import QtQuick
import "F.js" as F

// A labelled slider for the viewport's tool options: name, caliper beam, the value in mono.
Rectangle {
    id: s
    property string label: ""
    property string unit: ""
    property int decimals: 0
    property real from: 0
    property real to: 1
    property real step: 0.01
    property real value: 0
    property real base: NaN
    property bool percent: false
    signal moved(real value)
    width: lab.implicitWidth + 118 + val.width + 34; height: 28; radius: height / 2
    color: Theme.glassSolid; border.color: Theme.dark ? Theme.glassEdge : Theme.rule
    Txt { id: lab; x: 12; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; text: s.label; wrapMode: Text.NoWrap }
    Beam { x: lab.x + lab.implicitWidth + 10; width: 110; anchors.verticalCenter: parent.verticalCenter
        from: s.from; to: s.to; step: s.step; value: s.value; base: s.base; onMoved: function (v) { s.moved(v) } }
    Txt { id: val; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
        width: Math.max(26, implicitWidth); horizontalAlignment: Text.AlignRight; mono: true; font.pixelSize: 11; wrapMode: Text.NoWrap
        text: s.percent ? Math.round(s.value * 100) + "%" : F.fmt(s.value, s.decimals) + s.unit }
}
