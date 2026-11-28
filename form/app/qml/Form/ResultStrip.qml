import QtQuick
import "F.js" as F

// The legend strip under the part (direction I, decision 7): a result lives on the part, and this strip is its legend.
// It always carries three things: the scale, how the result is known, and what it does not tell. `map` is the engine's
// analysis result (form/analysis.py: legend { title, stops, what, not }, stats, rev); `busy` while it is computed.
// It arrives with a fade and an 8 px rise (Theme.strip); Reduce Motion keeps the fade.
Glass {
    id: rs
    objectName: "resultStrip"
    property var map: null
    property bool busy: false
    property string pending: ""          // the name of the map being computed
    property var check: null             // the matching pipeline check, when there is one
    property bool on: false
    property bool detail: false          // how it was computed, unfolded
    readonly property var legend: map ? map.legend : null
    readonly property var st: map && map.stats ? map.stats : ({})
    readonly property var stops: legend ? legend.stops || [] : []
    radius: 22
    // what the map does not tell, in the legend's own first sentence ("Not a strength analysis.")
    readonly property string limits: legend ? String(legend.not).split(". ")[0].replace(/\.$/, "") + "." : ""
    function esc(t) { return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    height: Math.round(col.implicitHeight + 27)
    opacity: on ? 1 : 0; visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: rs.on ? Theme.strip : Theme.exit; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    property real lift: on ? 0 : Theme.shift(Theme.rise)
    Behavior on lift { NumberAnimation { duration: Theme.move(Theme.strip); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    transform: Translate { y: rs.lift }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }   // the strip is not the viewport

    // the first number worth reading, beside the title
    readonly property string fact: {
        if (!map) return ""
        if (map.map === "thickness") return st.min_mm !== undefined ? "thinnest " + F.fmt(st.min_mm, 2) + " mm" : ""
        if (map.map === "overhang") return st.steep_mm2 !== undefined ? F.fmt(st.steep_mm2, 0) + " mm² unsupported" : ""
        if (map.map === "section") return st.max_mm2 !== undefined ? "largest slice " + F.fmt(st.max_mm2, 0) + " mm²" : ""
        return st.small_holes !== undefined ? st.small_holes + " of " + st.holes + " holes small" : ""
    }
    Column {
        id: col; x: 18; y: 14; width: parent.width - 36; spacing: 9
        Item { width: parent.width; height: 18
            Txt { id: ttl; objectName: "stripTitle"; font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: rs.legend ? rs.legend.title : rs.pending }
            Txt { anchors.left: ttl.right; anchors.leftMargin: 10; anchors.baseline: ttl.baseline; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight
                width: Math.max(0, how.x - x - 10)
                text: rs.map ? [rs.fact, F.pad(rs.map.rev)].filter(function (x) { return !!x }).join(" · ") : rs.busy ? "casting rays through the solid…" : "" }
            Ev { id: how; objectName: "stripEvidence"; anchors.right: fold.left; anchors.rightMargin: 8; anchors.baseline: ttl.baseline; color: Theme.ink2
                text: rs.busy && !rs.map ? "computing" : rs.map ? "computed · " + rs.map.tessellation_mm + " mm" : "" }
            Item { id: fold; objectName: "legendDetail"; anchors.right: parent.right; anchors.rightMargin: -6; width: 24; height: 24; anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.fill: parent; radius: 12; color: fm.containsMouse ? Theme.washHover : "transparent" }
                Icon { anchors.centerIn: parent; name: "chevron_down"; size: 12; color: Theme.ink3; rotation: rs.detail ? 180 : 0 }
                MouseArea { id: fm; anchors.fill: parent; hoverEnabled: true; onClicked: rs.detail = !rs.detail }
                Tip { show: fm.containsMouse; text: rs.detail ? "Fold the method away" : "How this is computed" } } }
        // the scale: one band per stop, in the map's own colours, and its words under it
        Row { id: bar; width: parent.width; height: 10; spacing: 2; visible: rs.stops.length > 0
            Repeater { model: rs.stops
                Rectangle { required property var modelData; required property int index
                    width: (bar.width - 2 * (rs.stops.length - 1)) / Math.max(1, rs.stops.length); height: 10
                    radius: 5
                    gradient: Gradient { orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: modelData.color } GradientStop { position: 1; color: modelData.to || modelData.color } } } } }
        Row { width: parent.width; height: 13; spacing: 2; visible: rs.stops.length > 0
            Repeater { model: rs.stops
                Txt { required property var modelData
                    width: (bar.width - 2 * (rs.stops.length - 1)) / Math.max(1, rs.stops.length)
                    mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: 3; lineHeight: 1; topPadding: 0; bottomPadding: 0
                    text: modelData.label; wrapMode: Text.NoWrap; elide: Text.ElideRight } } }
        // the matching check, and what the map does not tell: always in sight
        Txt { objectName: "stripLimits"; width: parent.width; font.pixelSize: 12; tone: 2; visible: !!rs.legend; lineHeight: 1.4
            textFormat: Text.StyledText
            text: rs.legend ? (rs.check ? "<font color=\"" + Theme.ink + "\">" + rs.esc(rs.check.label) + " " + rs.esc(String(rs.check.value)) + "</font>, from the checks. " : "")
                + rs.esc(rs.limits) : "" }
        Txt { width: parent.width; font.pixelSize: 12; tone: 3; visible: !!rs.legend && rs.detail; lineHeight: 1.4
            text: rs.legend ? rs.legend.what + " " + rs.legend.not : "" }
        Txt { width: parent.width; font.pixelSize: 12; tone: 2; visible: rs.busy && !rs.map
            text: "A few seconds the first time; kept for this revision afterwards." }
    }
}
