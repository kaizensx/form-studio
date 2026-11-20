import QtQuick
import "F.js" as F

// Measure from a reference photo: mark a known length to set the scale, then click two points to measure.
// Points are kept in image pixels. Perspective and lens distortion are not corrected; results are rough.
Column {
    id: ps
    property string title: "Measure from photo"
    property string note: mode === "scale" ? "Step 1 of 2 · set the scale" : "Step 2 of 2 · measure · rough, never fit-critical"
    property int sheetWidth: Theme.sheetL
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
    readonly property bool photoReady: img.status === Image.Ready
    // the photo gives way to a short window, so the readout and the actions stay on screen
    readonly property int photoMax: Math.max(220, Math.min(520, (Window.height > 0 ? Window.height : 900) - 88 - 58 - 60 - 28 - 150))
    property Item firstFocus: mode === "scale" && px > 0 ? len.input : null
    spacing: 14

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
    function accept() {
        if (mode === "scale") setScale(len.text)
        else if (px > 0) { if (targets.length > 0) load(); else keep() }
    }

    // the action bar follows the step
    property Component footerLeft: ps.mode === "measure" ? leftMeasure : leftScale
    property Component footer: ps.mode === "measure" ? rightMeasure : rightScale
    Component { id: leftScale; Txt { kind: "fine"; elide: Text.ElideRight; wrapMode: Text.NoWrap; verticalAlignment: Text.AlignVCenter
        text: !ps.photoReady ? "" : ps.px > 0 ? "Type the real length of the red line, then set the scale." : ps.pts.length === 1 ? "Now click the other end." : "Click both ends of a known length on the photo." } }
    Component { id: rightScale; Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { kind: "primary"; icon: "ruler"; text: "Set scale"; enabled: ps.px > 0 && parseFloat(len.text) > 0; keys: "Return"; onClicked: ps.setScale(len.text) } } }
    Component { id: leftMeasure; Row { spacing: 4
        Btn { kind: "quiet"; icon: "rotate_ccw"; text: "Reset scale"; onClicked: { ps.mode = "scale"; ps.pts = [] } } } }
    Component { id: rightMeasure; Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { kind: ps.targets.length > 0 ? "default" : "primary"; icon: "pin"; text: "Keep on photo"; enabled: ps.px > 0; onClicked: ps.keep() }
        Btn { visible: ps.targets.length > 0; kind: "primary"; icon: "arrow_down_to_line"; text: "Load as draft"; enabled: ps.px > 0; keys: "Return"; onClicked: ps.load() } } }

    // the photo, with segments drawn over it
    Rectangle {
        width: parent.width; height: ps.photoReady ? Math.max(160, frame.height) : 220; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule; clip: true
        Item {
            id: frame
            readonly property real iw: img.sourceSize.width
            readonly property real ih: img.sourceSize.height
            readonly property real k: iw > 0 && ih > 0 ? Math.min(parent.width / iw, ps.photoMax / ih) : 0   // screen px per image px
            width: Math.round(iw * k); height: Math.round(ih * k)
            anchors.horizontalCenter: parent.horizontalCenter
            onKChanged: overlay.requestPaint()
            Image { id: img; anchors.fill: parent; source: ps.ref.file ? Store.file("references/" + ps.ref.file) : ""; asynchronous: true; cache: false; smooth: true
                opacity: status === Image.Ready ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
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
        // loading, and the photo that is not there
        Column { anchors.centerIn: parent; spacing: 8; visible: !ps.photoReady
            Spinner { visible: img.status === Image.Loading; size: 18; anchors.horizontalCenter: parent.horizontalCenter }
            Icon { visible: img.status !== Image.Loading; name: "image"; size: 24; color: Theme.ink4; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { tone: 2; anchors.horizontalCenter: parent.horizontalCenter
                text: img.status === Image.Loading ? "Loading photo…" : "The photo could not be loaded." }
            Txt { kind: "fine"; visible: img.status !== Image.Loading; anchors.horizontalCenter: parent.horizontalCenter
                text: ps.ref.file ? "Attach it again under Describe › Reference photos." : "Attach a photo under Describe › Reference photos, then press Measure." } }
        // kept measurements, counted on the photo
        Rectangle { visible: ps.photoReady && ps.list.length > 0; x: 10; y: 10; width: kept.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.alpha(Theme.plate, 0.78)
            Txt { id: kept; anchors.centerIn: parent; kind: "fine"; tone: 2; text: F.plural(ps.list.length, "measurement") + " kept" } }
    }

    // step 1 — scale
    Note { visible: ps.mode === "scale"; kind: "amber"; title: "Step 1 — set the scale"
        text: "Click both ends of something whose real length you know (a ruler, a card: 85.6 mm), lying in the same plane as the object." }
    Column { visible: ps.mode === "scale" && ps.px > 0; spacing: 6
        Txt { kind: "cap"; text: "That length is" }
        Row { spacing: 10
            Field { id: len; numeric: true; width: 120; unit: "mm"; placeholder: "0.0" }
            Txt { kind: "fine"; mono: true; anchors.verticalCenter: parent.verticalCenter; text: F.fmt(ps.px, 0) + " px on the photo" } } }
    // Enter in the length field sets the scale (the field's own `accepted` also fires when it loses focus, so it is not used)
    Connections { target: len.input; function onAccepted() { ps.setScale(len.text) } }

    // step 2 — measure
    Note { visible: ps.mode === "measure"; title: "Step 2 — measure"
        text: "Scale " + F.fmt(ps.mmPerPx, 4) + " mm per pixel. Click two points. Perspective and lens distortion are not corrected, so treat results as rough: ±0.6 mm or worse, never fit-critical." }
    // the reading: the one number this sheet is for
    Rectangle { visible: ps.mode === "measure" && ps.px > 0; width: parent.width; height: 60; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
        Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Txt { mono: true; kind: "h2"; font.weight: Theme.wMedium; text: F.fmt(ps.mm, 1); wrapMode: Text.NoWrap; anchors.baseline: unit.baseline }
            Txt { id: unit; mono: true; tone: 2; text: "mm ±" + F.fmt(ps.sigma, 1); wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
            Tag { text: "photo"; kind: "photo"; anchors.verticalCenter: parent.verticalCenter } }
        Row { visible: ps.targets.length > 0; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Txt { kind: "cap"; text: "Use as"; anchors.verticalCenter: parent.verticalCenter }
            Pick { width: 240; model: ps.targets; value: ps.target; anchors.verticalCenter: parent.verticalCenter
                onPicked: function (v) { ps.target = v } } } }
}
