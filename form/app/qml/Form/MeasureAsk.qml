import QtQuick
import FormNative
import "F.js" as F

// "Measure this": the agent needs one real number (ask_measurement). The card shows where to measure, on a picture
// (the photo or a render the agent marked) or a drawn diagram of the shape and the axis; the unit, the tolerance
// that matters, and what the design assumes now. You type the number and say how you measured it; the engine commits
// it as a new revision with that provenance (calipers, ruler and tape are "measured", an estimate stays "assumed"),
// so the part on screen updates at once.
Rectangle {
    id: mc
    objectName: "measureCard"
    property var q: ({})
    readonly property bool open: !!q.open
    readonly property var ans: q.answer || null
    readonly property string unit: q.unit || "mm"
    property string method: "calipers"
    property bool sending: false
    readonly property real value: parseFloat(String(num.text).replace(",", "."))
    readonly property bool valid: !isNaN(value) && value > 0
    implicitHeight: col.implicitHeight + 28
    radius: Theme.rLg
    color: open ? Theme.plate2 : Theme.plate1
    border.color: open ? Theme.alpha(Theme.amber, 0.55) : Theme.rule
    Behavior on border.color { Tint {} }
    Rectangle { visible: mc.open; x: 0; y: 12; width: 3; height: parent.height - 24; radius: 2; color: Theme.amber }
    function send() {
        if (!valid || sending) return
        sending = true
        Store.answerMeasure(q.id, value, method)
    }
    Connections { target: Store; function onChatAskingChanged() { if (!Store.chatAsking || Store.chatAsking.id !== mc.q.id) mc.sending = false } }

    Column {
        id: col; x: 16; y: 14; width: parent.width - 30; spacing: 10
        Item { width: parent.width; height: 16
            Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
                Icon { name: "ruler"; size: 12; color: mc.open ? Theme.amber : Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "cap"; text: "Measure this"; anchors.verticalCenter: parent.verticalCenter } }
            Row { visible: mc.open; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity { running: mc.open; loops: Animation.Infinite; alwaysRunToEnd: true
                        NumberAnimation { to: 0.3; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                Txt { kind: "fine"; text: "Waiting for you"; color: Theme.amber } } }
        Txt { objectName: "measureQuestion"; width: parent.width; text: mc.q.question || ""; font.weight: Theme.wSemi; lineHeight: 1.35 }

        // where: the picture with the agent's mark, or a diagram of the shape with the dimension drawn on it
        Rectangle {
            width: parent.width; height: Math.round(width * 0.56); radius: Theme.rMd; color: Theme.well; border.color: Theme.rule; clip: true
            Image { id: pic; anchors.fill: parent; anchors.margins: 1; visible: !!mc.q.image_url; fillMode: Image.PreserveAspectFit; asynchronous: true
                source: mc.q.image_url ? Bridge.baseUrl + "/api" + String(mc.q.image_url).replace(/^\/api/, "") : "" }
            Canvas {   // the mark on the picture: a dimension line between the two points the agent gave
                anchors.fill: pic; visible: pic.visible && pic.status === Image.Ready && !!mc.q.mark && mc.q.mark.length === 4
                onVisibleChanged: requestPaint()
                onPaint: {
                    var c = getContext("2d"); c.reset(); if (!visible) return
                    var pw = pic.paintedWidth, ph = pic.paintedHeight, ox = (width - pw) / 2, oy = (height - ph) / 2, m = mc.q.mark
                    var x0 = ox + m[0] * pw, y0 = oy + m[1] * ph, x1 = ox + m[2] * pw, y1 = oy + m[3] * ph
                    c.strokeStyle = Theme.amber; c.fillStyle = Theme.amber; c.lineWidth = 2
                    c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke()
                    ;[[x0, y0], [x1, y1]].forEach(function (p) { c.beginPath(); c.arc(p[0], p[1], 4, 0, 2 * Math.PI); c.fill() })
                }
            }
            MeasureDiagram { anchors.fill: parent; visible: !mc.q.image_url; diagram: mc.q.diagram || ({ shape: "box", axis: "x" }); label: mc.open ? "?" : (mc.ans && mc.ans.value !== undefined ? F.fmt(mc.ans.value, 2) + " " + mc.unit : "") }
        }
        Txt { visible: !!mc.q.where; width: parent.width; tone: 2; text: mc.q.where || ""; lineHeight: 1.35 }
        Row { spacing: 16
            Column { spacing: 1; visible: mc.q.current !== null && mc.q.current !== undefined
                Txt { kind: "cap"; text: "Assumed now" }
                Txt { mono: true; font.pixelSize: 12; color: Theme.amber; text: F.fmt(mc.q.current, 2) + " " + mc.unit } }
            Column { spacing: 1; visible: mc.q.tolerance_mm !== null && mc.q.tolerance_mm !== undefined
                Txt { kind: "cap"; text: "Matters to" }
                Txt { mono: true; font.pixelSize: 12; text: "± " + F.fmt(mc.q.tolerance_mm, 2) + " mm" } }
            Column { spacing: 1; visible: !!mc.q.param
                Txt { kind: "cap"; text: "Sets" }
                Txt { mono: true; font.pixelSize: 12; tone: 2; text: mc.q.param || "" } } }

        // ── the answer: the number, and how it was measured ──
        Column { visible: mc.open; width: parent.width; spacing: 8
            Seg { objectName: "measureMethod"; value: mc.method; onPicked: function (v) { mc.method = v }
                model: [{ value: "calipers", text: "Calipers" }, { value: "ruler", text: "Ruler" }, { value: "tape", text: "Tape" },
                        { value: "estimate", text: "Estimate", tip: "Kept as assumed: an estimate is not a measurement" }] }
            Row { width: parent.width; spacing: 6
                Field { id: num; objectName: "measureValue"; width: parent.width - go.width - 6; numeric: true; unit: mc.unit
                    placeholder: mc.q.current !== null && mc.q.current !== undefined ? "e.g. " + F.fmt(mc.q.current, 1) : "The number you measured"
                    onAccepted: mc.send() }
                Btn { id: go; objectName: "measureSend"; kind: "primary"; icon: "check"; text: "Use it"; busy: mc.sending; enabled: mc.valid
                    tip: mc.method === "estimate" ? "Updates the design; the value stays assumed" : "Updates the design; recorded as measured with " + mc.method
                    onClicked: mc.send() } }
            Txt { kind: "fine"; tone: 3; width: parent.width
                text: mc.method === "calipers" ? "Calipers: about ±0.05 mm. Close the jaws gently; read twice." : mc.method === "ruler" ? "Ruler: about ±0.5 mm. Look straight down at the mark."
                    : mc.method === "tape" ? "Tape: about ±1 mm." : "An estimate is carried as assumed until it is measured." } }

        // ── afterwards ──
        Row { visible: !mc.open && !!mc.ans && !mc.ans.closed; width: parent.width; spacing: 7
            Icon { name: "circle_check"; size: 13; color: mc.ans && mc.ans.source === "measured" ? Theme.pass : Theme.amber; anchors.verticalCenter: parent.verticalCenter }
            Txt { objectName: "measureAnswer"; width: parent.width - 22; tone: 2
                text: !mc.ans ? "" : (mc.ans.value !== undefined && mc.ans.value !== null ? F.fmt(mc.ans.value, 2) + " " + mc.unit : mc.ans.text)
                      + (mc.ans.method ? " · " + (mc.ans.method === "estimate" ? "estimated, kept as assumed" : "measured with " + mc.ans.method) : "")
                      + (mc.ans.rev ? " · " + F.pad(mc.ans.rev) : "") } }
        Txt { visible: !mc.open && (!mc.ans || !!mc.ans.closed); width: parent.width; kind: "fine"
            text: !mc.ans ? "Not answered." : mc.ans.closed === "timeout" ? "Not answered in time. The value stays assumed." : "The reply ended before an answer." }
    }
}
