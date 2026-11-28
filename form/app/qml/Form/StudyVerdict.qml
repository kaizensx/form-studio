import QtQuick
import "F.js" as F

// A strength study's verdict, in one sentence, and the load-scale slider (ResultCard's strength section).
// The sentence is the safety factor with its stated-error bound, never one without the other: "Holds the load with a
// safety factor of 5.4 (at least 5.3 with the stated error)". The slider multiplies every load of a linear static
// study: stress and displacement scale with the load exactly in a linear model, so the factor divides by it and the
// card can say what holds at k times the load without solving again. It is labelled so ("linear: exact for this
// model") and it is not shown for any other study (thermal stress, modes, buckling, heat). The map on the part and
// its legend stay at 1 ×: the card says the scaled numbers, and that it did not solve again.
Column {
    id: sv
    objectName: "studyVerdict"
    property var r: null                          // Results.r of a current strength study
    readonly property bool lin: !!r && r.linear === true && !!r.safety && r.safety.value !== null && r.safety.value !== undefined
    property real k: 1
    readonly property real sf: r && r.safety ? Number(r.safety.value) / k : NaN
    readonly property real lo: r && r.safety ? Number(r.safety.low !== null && r.safety.low !== undefined ? r.safety.low : r.safety.value) / k : NaN
    readonly property string load: k === 1 ? "the load" : F.trim(k, 2) + " × the load"
    // one decimal from 2 up, two below (where the margin is the point); a lower bound is rounded down, never up
    function digits(x) { return x >= 2 ? 1 : 2 }
    function down(x) { var d = Math.pow(10, digits(x)); return (Math.floor(x * d + 1e-9) / d).toFixed(digits(x)) }
    readonly property string sentence: !r || !r.safety || r.safety.value === null || r.safety.value === undefined ? ""
        : lo >= 1 ? "Holds " + load + " with a safety factor of " + F.fmt(sf, digits(sf)) + " (at least " + down(lo) + " with the stated error)."
        : sf >= 1 ? "Not proven at " + load + ": a safety factor of " + F.fmt(sf, 2) + ", but only " + down(lo) + " with the stated error."
        : "Too weak at " + load + ": it holds up to " + down(sf) + " × that (" + down(lo) + " × with the stated error)."
    readonly property color tint: lo >= 1 ? Theme.pass : sf >= 1 ? Theme.amber : Theme.signal
    visible: sentence !== ""
    spacing: 8
    onRChanged: k = 1

    Row { width: parent.width; spacing: 9
        Rectangle { width: 7; height: 7; radius: 3.5; color: sv.tint; y: 8 }
        Txt { objectName: "verdictText"; width: parent.width - 16; font.pixelSize: 13; font.weight: Theme.wMedium; text: sv.sentence } }
    Column { visible: sv.lin; width: parent.width; spacing: 4
        Item { width: parent.width; height: 18
            Txt { kind: "fine"; tone: 2; text: "Load scale"; anchors.verticalCenter: parent.verticalCenter }
            Txt { objectName: "loadScaleValue"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                text: F.fmt(sv.k, 2) + " ×" } }
        Item { id: track; objectName: "loadScale"; width: parent.width; height: 22
            readonly property real lo: 0.25
            readonly property real hi: 4
            // a log scale: 1 × sits in the middle, a quarter and four times at the ends
            function at(x) { var t = Math.max(0, Math.min(1, x / width)); return Math.round(Math.exp(Math.log(lo) + t * (Math.log(hi) - Math.log(lo))) * 100) / 100 }
            readonly property real pos: (Math.log(sv.k) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)) * width
            Rectangle { y: 10; width: parent.width; height: 2; radius: 1; color: Theme.rule2 }
            Rectangle { x: parent.width / 2 - 0.5; y: 6; width: 1; height: 10; color: Theme.ink3 }
            Rectangle { y: 10; x: Math.min(track.pos, parent.width / 2); width: Math.abs(track.pos - parent.width / 2); height: 2; radius: 1; color: Theme.datum }
            Rectangle { x: track.pos - 7; y: 4; width: 14; height: 14; radius: 7; color: Theme.plate3; border.color: Theme.datum; border.width: 1.5 }
            MouseArea { anchors.fill: parent; anchors.topMargin: -4; anchors.bottomMargin: -4; preventStealing: true; cursorShape: Qt.SizeHorCursor
                onPressed: function (m) { sv.k = track.at(m.x) }
                onPositionChanged: function (m) { if (pressed) sv.k = track.at(m.x) }
                onDoubleClicked: sv.k = 1 } }
        Item { width: parent.width; height: 16
            Txt { kind: "fine"; tone: 3; text: "0.25 ×" }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; tone: 3; text: "1 ×" }
            Txt { anchors.right: parent.right; kind: "fine"; tone: 3; text: "4 ×" } }
        Txt { objectName: "loadScaleNote"; width: parent.width; kind: "fine"; tone: 3
            text: "linear: exact for this model. Every load × " + F.fmt(sv.k, 2) + ": peak stress " + Results.fmt(sv.r && sv.r.peak ? sv.r.peak.value * sv.k : 0, "MPa")
                  + ", largest displacement " + Results.fmt(sv.r && sv.r.max_displacement ? sv.r.max_displacement.value * sv.k : 0, "mm") + ". Not solved again: the map and its legend stay at 1 ×. Double-click for 1 ×." } }
}
