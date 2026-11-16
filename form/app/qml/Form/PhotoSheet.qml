import QtQuick
import "F.js" as F

// Measure from a reference photo: mark a known length to set the scale, then click two points to measure.
// Points are kept in image pixels. Perspective and lens distortion are not corrected; results are rough.
Column {
    id: ps
    property string title: "Measure from photo"
    property int sheetWidth: 900
    readonly property var ref: Store.sheet && Store.sheet.props && Store.sheet.props.ref ? Store.sheet.props.ref : ({ file: "", measurements: [] })
    property var pts: []               // 0–2 points, [x, y] in image pixels
    property real mmPerPx: 0
    property var list: []              // kept measurements: { a, b, mm, sigma, param? }
    property string mode: "scale"      // scale | measure
    property string target: ""
    readonly property real px: pts.length === 2 ? Math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]) : 0
    readonly property real mm: px * mmPerPx
    readonly property real sigma: Math.max(0.6, mm * 0.02 + 2 * mmPerPx)
    readonly property var targets: Store.recipe ? Store.recipe.params.filter(function (p) { return p.unit === "mm" && p.group === "brief" })
                                                       .map(function (p) { return { value: p.key, text: p.label } }) : []
    spacing: 12; bottomPadding: 20

    Component.onCompleted: {
        mmPerPx = ref.scale_mm_per_px || 0
        list = (ref.measurements || []).slice()
        mode = mmPerPx > 0 ? "measure" : "scale"
        target = targets.length ? targets[0].value : ""
        if (Store.sheet.props.pts) pts = Store.sheet.props.pts      // optional: open with points already placed
    }
    onPtsChanged: overlay.requestPaint()
    onListChanged: overlay.requestPaint()

    function save() {
        return Store.ppost("/reference_update", { file: ref.file, scale_mm_per_px: mmPerPx > 0 ? mmPerPx : null, measurements: list })
            .then(function () { return Store.refresh() }, Store.fail)
    }
    function setScale(t) {
        var len = parseFloat(t)
        if (!(len > 0) || !(px > 0)) return
        mmPerPx = len / px; pts = []; mode = "measure"; save()
    }
    function keep() {
        list = list.concat([{ a: pts[0], b: pts[1], mm: mm, sigma: sigma }]); pts = []; save()
    }
    function load() {
        var key = target, v = +mm.toFixed(1), sg = +sigma.toFixed(2)
        list = list.concat([{ a: pts[0], b: pts[1], mm: mm, sigma: sigma, param: key }])
        save()
        Store.openSheet(null)
        Store.setStage("brief")
        Store.setProv(key, { source: "photo", sigma: sg })
        Store.setParam(key, v, true)
        Store.toast("Loaded as a draft", "Marked “from photo”. Replace with a caliper measurement before trusting the fit.")
    }

    // the photo, with segments drawn over it
    Rectangle {
        width: parent.width; height: Math.max(160, frame.height); radius: Theme.rMd; color: Theme.well; border.color: Theme.rule; clip: true
        Item {
            id: frame
            readonly property real iw: img.sourceSize.width
            readonly property real ih: img.sourceSize.height
            readonly property real k: iw > 0 && ih > 0 ? Math.min(parent.width / iw, 520 / ih) : 0   // screen px per image px
            width: Math.round(iw * k); height: Math.round(ih * k)
            anchors.horizontalCenter: parent.horizontalCenter
            onKChanged: overlay.requestPaint()
            Image { id: img; anchors.fill: parent; source: ps.ref.file ? Store.file("references/" + ps.ref.file) : ""; asynchronous: true; cache: false; smooth: true }
            Canvas {
                id: overlay; anchors.fill: parent
                function seg(c, a, b, col, text) {
                    var k = frame.k
                    c.strokeStyle = col; c.fillStyle = col; c.lineWidth = 2
                    c.beginPath(); c.moveTo(a[0] * k, a[1] * k); c.lineTo(b[0] * k, b[1] * k); c.stroke()
                    dot(c, a, col); dot(c, b, col)
                    if (text) { c.font = "600 12px '" + Theme.mono + "'"; c.fillText(text, (a[0] + b[0]) / 2 * k + 8, (a[1] + b[1]) / 2 * k - 8) }
                }
                function dot(c, p, col) { c.fillStyle = col; c.beginPath(); c.arc(p[0] * frame.k, p[1] * frame.k, 4.5, 0, 2 * Math.PI); c.fill() }
                onPaint: {
                    var c = getContext("2d"); c.clearRect(0, 0, width, height)
                    if (frame.k <= 0) return
                    for (var i = 0; i < ps.list.length; i++) { var m = ps.list[i]; if (m.a && m.b) seg(c, m.a, m.b, Theme.blueprint, F.fmt(m.mm, 1) + " mm") }
                    if (ps.pts.length === 2) seg(c, ps.pts[0], ps.pts[1], Theme.signal, "")
                    else if (ps.pts.length === 1) dot(c, ps.pts[0], Theme.signal)
                }
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.CrossCursor; enabled: frame.k > 0
                onClicked: function (e) {
                    var p = [e.x / frame.k, e.y / frame.k]
                    ps.pts = ps.pts.length >= 2 ? [p] : ps.pts.concat([p])
                } }
        }
        Txt { anchors.centerIn: parent; visible: img.status !== Image.Ready; tone: 3
            text: img.status === Image.Loading ? "Loading photo…" : "The photo could not be loaded." }
    }

    // step 1 — scale
    Note { visible: ps.mode === "scale"; kind: "amber"; title: "Step 1 — set the scale"
        text: "Click both ends of something whose real length you know (a ruler, a card: 85.6 mm), lying in the same plane as the object." }
    Row { visible: ps.mode === "scale" && ps.px > 0; spacing: 8
        Txt { text: "That length is"; tone: 2; anchors.verticalCenter: parent.verticalCenter }
        Field { id: len; numeric: true; width: 96; unit: "mm"; placeholder: "0.0"; anchors.verticalCenter: parent.verticalCenter }
        Btn { text: "Set scale"; kind: "primary"; enabled: parseFloat(len.text) > 0; anchors.verticalCenter: parent.verticalCenter; onClicked: ps.setScale(len.text) } }

    // step 2 — measure
    Note { visible: ps.mode === "measure"; title: "Step 2 — measure"
        text: "Scale " + F.fmt(ps.mmPerPx, 4) + " mm per pixel. Click two points. Perspective and lens distortion are not corrected, so treat results as rough: ±0.6 mm or worse, never fit-critical." }
    Row { visible: ps.mode === "measure" && ps.px > 0; spacing: 8
        Txt { mono: true; font.weight: 600; text: F.fmt(ps.mm, 1) + " mm ±" + F.fmt(ps.sigma, 1); wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
        Tag { text: "photo"; kind: "photo"; anchors.verticalCenter: parent.verticalCenter }
        Txt { visible: ps.targets.length > 0; text: "use as"; tone: 2; anchors.verticalCenter: parent.verticalCenter }
        Pick { visible: ps.targets.length > 0; width: 220; model: ps.targets; value: ps.target; anchors.verticalCenter: parent.verticalCenter
            onPicked: function (v) { ps.target = v } }
        Btn { visible: ps.targets.length > 0; text: "Load as draft"; kind: "primary"; anchors.verticalCenter: parent.verticalCenter; onClicked: ps.load() }
        Btn { text: "Keep on photo"; kind: "quiet"; anchors.verticalCenter: parent.verticalCenter; onClicked: ps.keep() } }
    Btn { visible: ps.mode === "measure"; kind: "quiet"; small: true; icon: "rotate_ccw"; text: "Reset scale"; x: -8
        onClicked: { ps.mode = "scale"; ps.pts = [] } }
}
