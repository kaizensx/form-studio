import QtQuick
import "F.js" as F

// A number that ticks over to its new value instead of being replaced. Mono, so the digits do not shift.
Txt {
    id: t
    property real value: 0
    property int decimals: 1
    property string unit: ""
    property bool countIn: false            // count up from zero on arrival (a score), instead of showing the first value
    property int countMs: Theme.slow * 2
    property real shown: countIn ? 0 : value
    property bool live: false               // the first value is simply shown
    mono: true; wrapMode: Text.NoWrap
    text: F.fmt(shown, decimals) + unit
    Behavior on shown { enabled: t.live && !Motion.reduced; NumberAnimation { duration: t.countIn ? t.countMs : Theme.cross; easing.type: Easing.OutCubic } }
    Component.onCompleted: Qt.callLater(function () { t.live = true; if (t.countIn) t.shown = Qt.binding(function () { return t.value }) })
}
