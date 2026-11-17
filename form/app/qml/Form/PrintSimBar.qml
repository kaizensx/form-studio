import QtQuick
import "F.js" as F

// Transport for the print simulation: play, speed, loop, where the nozzle is, the scrubber within the layer,
// and the per-layer chart that scrubs by layer. `sim` is LayerView.
Rectangle {
    id: bar
    required property var sim
    readonly property var info: sim.info
    readonly property bool ready: !!info
    property string metric: "time"            // what the chart shows: time | length
    readonly property bool narrow: width < 580
    radius: Theme.rLg; color: Theme.alpha(Theme.plate1, 0.94); border.color: Theme.rule
    height: col.implicitHeight + 24
    function clock(s) {
        s = Math.max(0, Math.round(s))
        var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), ss = s % 60
        return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (ss < 10 ? "0" : "") + ss
    }

    Column {
        id: col; x: 14; y: 12; width: parent.width - 28; spacing: 10

        // ── play, speed, readouts ────────────────────────────
        Item { width: parent.width; height: bar.narrow ? 78 : 30
            Row { id: left; spacing: 8; height: 30
                Btn { kind: "primary"; icon: bar.sim.playing ? "pause" : "play"; text: bar.sim.playing ? "Pause" : bar.sim.finished ? "Play again" : "Play"
                    enabled: bar.ready; width: bar.narrow ? 88 : 104; anchors.verticalCenter: parent.verticalCenter; onClicked: bar.sim.toggle() }
                Seg { anchors.verticalCenter: parent.verticalCenter
                    model: [{ value: 1, text: "1×" }, { value: 4, text: "4×" }, { value: 16, text: "16×" }, { value: 64, text: "64×" }]
                    value: bar.sim.speed; onPicked: function (s) { bar.sim.speed = s } }
                Btn { kind: "quiet"; icon: "repeat"; active: bar.sim.loop; tip: "Loop: start again when the print is done"; onClicked: bar.sim.loop = !bar.sim.loop
                    anchors.verticalCenter: parent.verticalCenter }
            }
            Column { anchors.right: bar.narrow ? undefined : parent.right; anchors.verticalCenter: bar.narrow ? undefined : parent.verticalCenter
                anchors.left: bar.narrow ? parent.left : undefined; anchors.bottom: bar.narrow ? parent.bottom : undefined; spacing: 2; visible: bar.ready
                Row { anchors.right: bar.narrow ? undefined : parent.right; spacing: 8
                    Txt { mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                        text: bar.ready ? "Layer " + (bar.sim.cur + 1) + " / " + bar.sim.count + "  ·  z " + F.fmt(info.z[bar.sim.cur], 2) + " mm" : "" }
                    Rectangle { visible: !bar.sim.finished && !!bar.sim.here.type; width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                        color: bar.sim.typeColor(bar.sim.here.type || "") }
                    Txt { visible: !bar.sim.finished && !!bar.sim.here.type; font.pixelSize: 12; wrapMode: Text.NoWrap; text: bar.sim.here.type || ""; width: bar.narrow ? Math.min(implicitWidth, 110) : 132; elide: Text.ElideRight } }
                Row { anchors.right: bar.narrow ? undefined : parent.right; spacing: 8
                    Txt { mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                        text: !bar.ready ? "" : bar.sim.timed ? (bar.narrow ? bar.clock(bar.sim.elapsed) + " of " + bar.clock(info.total_time_s)
                                                                           : bar.clock(bar.sim.elapsed) + " elapsed  ·  " + bar.clock(info.total_time_s - bar.sim.elapsed) + " remaining")
                                                             : "the slicer gave no print time" }
                    Tag { visible: bar.ready && bar.sim.timed; anchors.verticalCenter: parent.verticalCenter
                        text: info && info.time_source === "interpolated" ? "interpolated" : "slicer estimate"; kind: "simulated"
                        MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true }
                        Tip { show: tm.containsMouse; text: info ? info.time_note : "" } } }
            }
        }

        // ── along the current layer ──────────────────────────
        Item { width: parent.width; height: 18; visible: bar.ready
            Txt { id: al; kind: "fine"; text: "Along the layer"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
            Beam { objectName: "simAlong"; anchors.left: al.right; anchors.leftMargin: 12; anchors.right: pc.left; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                from: 0; to: 1; step: 0.002; value: Math.min(1, bar.sim.frac); tint: Theme.datum
                onMoved: function (f) { bar.sim.pause(); bar.sim.setNow(bar.sim.cur + Math.min(f, 0.9999)) } }
            Txt { id: pc; mono: true; font.pixelSize: 11; tone: 3; width: 34; horizontalAlignment: Text.AlignRight; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                text: Math.round(Math.min(1, bar.sim.frac) * 100) + "%" }
        }

        // ── every layer: the chart is the scrubber ───────────
        PrintSimChart {
            objectName: "simLayers"
            width: parent.width; visible: bar.ready
            values: !bar.ready ? [] : bar.metric === "time" && bar.sim.timed ? info.time_s : info.length_mm
            bridges: bar.ready ? info.bridge_layers : []
            overhangs: bar.ready ? info.overhang_layers : []
            current: bar.sim.cur; fraction: Math.min(1, bar.sim.frac)
            bridgeColor: bar.sim.typeColor("Bridge"); overhangColor: Theme.amber
            onScrub: function (l) { bar.sim.pause(); bar.sim.setNow(l + 0.9999) }
            onHoverChanged: hov.l = hover
        }
        Item { width: parent.width; height: 24; visible: bar.ready
            Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Seg { model: bar.narrow ? [{ value: "time", text: "Time" }, { value: "length", text: "Path" }] : [{ value: "time", text: "Time per layer" }, { value: "length", text: "Path per layer" }]
                    value: bar.metric === "time" && bar.sim.timed ? "time" : "length"
                    onPicked: function (m) { bar.metric = m } }
                Txt { id: hov; property int l: -1; kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; visible: !bar.narrow
                    width: Math.min(implicitWidth, Math.max(40, col.width - 200 - jumps.width - 20)); elide: Text.ElideRight
                    readonly property int shown: l >= 0 ? l : bar.sim.cur
                    text: !bar.ready ? "" : "Layer " + (shown + 1) + ": " + (bar.sim.timed ? bar.clock(info.time_s[shown]) + " · " : "") + F.fmt(info.length_mm[shown] / 1000, 2) + " m of path"
                        + (info.bridge_layers.indexOf(shown) >= 0 ? " · bridge" : "") + (info.overhang_layers.indexOf(shown) >= 0 ? " · overhang wall" : "") } }
            Row { id: jumps; spacing: 6; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Btn { small: true; icon: "skip_forward"; text: bar.narrow ? "Bridge" : "Next bridge"; enabled: bar.ready && info.bridge_layers.length > 0
                    tip: bar.ready && info.bridge_layers.length ? F.plural(info.bridge_layers.length, "layer") + " with a bridge" : "This slice has no bridges"
                    onClicked: bar.sim.jump(info.bridge_layers) }
                Btn { small: true; icon: "skip_forward"; text: bar.narrow ? "Overhang" : "Next overhang wall"; enabled: bar.ready && info.overhang_layers.length > 0
                    tip: bar.ready && info.overhang_layers.length ? F.plural(info.overhang_layers.length, "layer") + " with an overhang wall" : "This slice has no overhang walls"
                    onClicked: bar.sim.jump(info.overhang_layers) } }
        }
        Txt { visible: !bar.ready; kind: "fine"; text: bar.sim.error !== "" ? bar.sim.error : "Reading the slicer's G-code…"; width: parent.width }
    }
}
