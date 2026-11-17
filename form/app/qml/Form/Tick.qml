import QtQuick
import "F.js" as F

// A number that ticks over to its new value instead of being replaced. Mono, so the digits do not shift.
Txt {
    id: t
    property real value: 0
    property int decimals: 1
    property string unit: ""
    property real shown: value
    property bool live: false               // the first value is simply shown
    mono: true; wrapMode: Text.NoWrap
    text: F.fmt(shown, decimals) + unit
    Behavior on shown { enabled: t.live && !Motion.reduced; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Component.onCompleted: Qt.callLater(function () { t.live = true })
}
