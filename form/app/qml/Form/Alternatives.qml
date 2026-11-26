import QtQuick
import "F.js" as F

// Compare alternatives: vary one or two parameters, build every candidate in the kernel, rank against weighted objectives.
Column {
    id: alt
    property string title: "Compare alternatives"
    property string note: "Vary one or two parameters; every candidate is built in the kernel"
    property int sheetWidth: Theme.sheetXl
    property Item firstFocus: v1.input
    spacing: 16

    readonly property var v: Store.head ? Store.head.values : ({})
    readonly property var cand: Store.recipe ? Store.recipe.params.filter(function (p) { return p.group !== "brief" }) : []
    readonly property var picks: cand.map(function (p) { return { value: p.key, text: p.label } })
    readonly property var defaults: Store.recipe && Store.recipe.id === "dock" ? ["depth", "lean"] : [cand.length ? cand[0].key : "", cand.length > 1 ? cand[1].key : (cand.length ? cand[0].key : "")]
    property string ax1: defaults[0]
    property string ax2: defaults[1]
    property var weights: ({ material: 1, stability: 2, fit: 0, footprint: 1 })
    readonly property var names: [["material", "Less material"], ["stability", "Harder to tip"], ["fit", "Fit yield"], ["footprint", "Smaller footprint"]]
    property bool busy: false
    property var result: null            // engine reply: { axes, rows, note }
    property var error: null
    property real elapsed: 0
    readonly property var okRows: result ? result.rows.filter(function (x) { return x.ok }) : []
    // one camera distance for every thumbnail, so sizes compare honestly
    readonly property real frame: Math.max.apply(null, okRows.map(function (x) {
        return Math.hypot(x.bbox[1][0] - x.bbox[0][0], x.bbox[1][1] - x.bbox[0][1], x.bbox[1][2] - x.bbox[0][2]) / 2 }).concat([12]))
    readonly property int cols: result && result.axes.length > 1 && result.rows.length % 3 === 0 && result.rows.length % 4 !== 0 ? 3 : 4
    readonly property int gap: 12
    readonly property real cardW: Math.floor((width - (cols - 1) * gap) / cols)
    readonly property bool hasTip: okRows.some(function (x) { return x.metrics.stability !== null && x.metrics.stability !== undefined })
    readonly property bool hasFit: okRows.some(function (x) { return x.metrics.fit !== null && x.metrics.fit !== undefined })
    // how many candidates the fields ask for (shown before building)
    readonly property int planned: { var a = parse(v1.text).length, b = ax2 !== ax1 ? parse(v2.text).length : 0; return b > 0 ? a * b : a }

    function span(key) {
        var p = Store.spec(key); if (!p) return ""
        var x = v[key], dlt = Math.max(p.step * 2, Math.abs(x) * 0.18)
        function r(n) { return Math.round(Math.min(p.max, Math.max(p.min, n)) / p.step) * p.step }
        return [r(x - dlt), r(x), r(x + dlt)].map(function (n) { return F.trim(n, 3) }).join(", ")
    }
    function unitOf(key) { var p = Store.spec(key); return p && p.unit ? p.unit : "" }
    function parse(t) { return t.split(/[,\s]+/).filter(function (s) { return s !== "" }).map(Number).filter(function (n) { return isFinite(n) }) }
    function nameOf(x) { return result.axes.map(function (a) { return a.label.split(" ")[0] + " " + F.trim(x.changes[a.key]) }).join(" · ") }
    function build() {
        if (busy || ax1 === "") return
        var axes = [{ key: ax1, values: parse(v1.text) }]
        if (ax2 !== ax1) axes.push({ key: ax2, values: parse(v2.text) })
        busy = true; error = null
        var t0 = Date.now()
        Store.ppost("/alternatives", { axes: axes, weights: weights }).then(function (r) {
            alt.elapsed = (Date.now() - t0) / 1000; alt.result = r; alt.busy = false
        }, function (e) { alt.result = null; alt.error = e; alt.busy = false })
    }
    function load(x) {
        var vals = Object.assign({}, Store.head.values, x.changes)
        Store.openSheet(null); Store.setStage("shape"); Store.loadDraft(vals)
    }
    function accept() { build() }

    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "layout_grid"; text: "Open the variants board"; onClicked: Store.openSheet("variants") } }
    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { kind: "primary"; icon: "boxes"; enabled: alt.ax1 !== "" && alt.planned > 0; busy: alt.busy; keys: "Return"
            text: alt.busy ? "Building candidates…" : alt.result ? "Build again" : alt.planned > 1 ? "Build " + alt.planned + " candidates" : "Build candidates"
            onClicked: alt.build() } }

    // ── what to vary, and what counts ───────────────────────
    Rectangle { width: parent.width; height: setup.implicitHeight + 32; radius: 14; color: Theme.glass
        Row { id: setup; x: 16; y: 16; width: parent.width - 32; spacing: 40
            Column { width: (parent.width - 40) * 0.56; spacing: 8
                Txt { kind: "cap"; text: "Vary" }
                Row { width: parent.width; spacing: 8
                    Pick { width: 200; model: alt.picks; value: alt.ax1; onPicked: function (k) { alt.ax1 = k } }
                    Field { id: v1; width: parent.width - 208; mono: true; text: alt.span(alt.ax1); unit: alt.unitOf(alt.ax1); onAccepted: alt.build() } }
                Row { width: parent.width; spacing: 8
                    Pick { width: 200; model: alt.picks; value: alt.ax2; onPicked: function (k) { alt.ax2 = k } }
                    Field { id: v2; width: parent.width - 208; mono: true; text: alt.span(alt.ax2); unit: alt.unitOf(alt.ax2); enabled: alt.ax2 !== alt.ax1; onAccepted: alt.build() } }
                Txt { kind: "fine"; width: parent.width; text: "Up to five values per parameter, comma-separated. Interfaces stay as committed unless you vary them." }
            }
            Column { width: (parent.width - 40) * 0.44; spacing: 8
                Item { width: parent.width; height: wcap.implicitHeight
                    Txt { id: wcap; kind: "cap"; text: "Weight the objectives" }
                    Txt { kind: "fine"; text: "0 = ignore"; anchors.right: parent.right; anchors.baseline: wcap.baseline } }
                Column { width: parent.width
                    Repeater { model: alt.names
                        Item { id: wr; required property var modelData
                            readonly property int w: alt.weights[modelData[0]]
                            width: parent.width; height: 28
                            Txt { text: wr.modelData[1]; tone: wr.w > 0 ? 1 : 3; anchors.verticalCenter: parent.verticalCenter }
                            Beam { width: 150; anchors.right: num.left; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                                from: 0; to: 3; step: 1; value: wr.w
                                onMoved: function (x) { var w = Object.assign({}, alt.weights); w[wr.modelData[0]] = x; alt.weights = w } }
                            Txt { id: num; mono: true; width: 14; horizontalAlignment: Text.AlignRight; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                text: String(wr.w); tone: wr.w > 0 ? 1 : 4 } } } }
            }
        } }

    Note { visible: !!alt.error; kind: "red"; title: alt.error ? alt.error.message || "Could not build the candidates" : ""; text: alt.error && alt.error.hint ? alt.error.hint : "" }

    // ── before the first build, and while the kernel works ──
    Rectangle { visible: !alt.result && !alt.error; width: parent.width; height: 150; radius: Theme.rMd; color: "transparent"; border.color: Theme.rule
        Column { anchors.centerIn: parent; spacing: 8
            Spinner { visible: alt.busy; size: 18; anchors.horizontalCenter: parent.horizontalCenter }
            Icon { visible: !alt.busy; name: "boxes"; size: 24; color: Theme.ink4; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { tone: 2; anchors.horizontalCenter: parent.horizontalCenter
                text: alt.busy ? "Building " + F.plural(alt.planned, "candidate") + " in the kernel…" : "Nothing built yet." }
            Txt { kind: "fine"; anchors.horizontalCenter: parent.horizontalCenter
                text: alt.busy ? "Each one is a real solid, so this takes a few seconds." : "Choose what to vary, weight what matters, then build. The current design is not changed." } } }

    // ── candidates ──────────────────────────────────────────
    Column { width: parent.width; spacing: 12; visible: !!alt.result
        opacity: alt.busy ? 0.45 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        Item { width: parent.width; height: 18
            Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Txt { kind: "cap"; text: alt.result ? alt.okRows.length + " built · " + (alt.result.rows.length - alt.okRows.length) + " infeasible" : ""; anchors.verticalCenter: parent.verticalCenter }
                Spinner { visible: alt.busy; size: 12; anchors.verticalCenter: parent.verticalCenter } }
            Txt { kind: "fine"; mono: true; text: alt.elapsed.toFixed(1) + " s"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
        Grid { width: parent.width; columns: alt.cols; spacing: alt.gap
            Repeater { model: alt.result ? alt.result.rows : []
                Rectangle { id: card; required property var modelData
                    readonly property var c: modelData
                    readonly property var m: c.ok ? c.metrics : ({})
                    width: alt.cardW; height: 12 + 17 + 8 + 132 + 10 + 20 + 4 + (2 + (alt.hasTip ? 1 : 0) + (alt.hasFit ? 1 : 0)) * 22 + 10 + 3 + 14
                    radius: Theme.rMd
                    color: !c.ok ? Theme.alpha(Theme.signal, 0.05) : cm.pressed ? Theme.washPress : cm.containsMouse || keep.hovered ? Theme.glass2 : Theme.glass
                    border.color: !c.ok ? Theme.alpha(Theme.signal, 0.3) : c.best ? Theme.alpha(Theme.datum, 0.6) : cm.containsMouse || keep.hovered ? Theme.rule2 : Theme.rule
                    Behavior on color { Tint {} }
                    // infeasible
                    Column { visible: !card.c.ok; x: 12; y: 12; width: parent.width - 24; spacing: 8
                        Tag { text: "infeasible"; kind: "FAIL" }
                        Txt { text: alt.nameOf(card.c); font.weight: Theme.wSemi; width: parent.width }
                        Txt { kind: "fine"; width: parent.width; color: Theme.signal; text: card.c.ok ? "" : (card.c.error && card.c.error.message ? card.c.error.message : "Did not build.") } }
                    // built
                    Column { visible: !!card.c.ok; x: 12; y: 12; width: parent.width - 24
                        Row { height: 17; spacing: 4
                            Tag { visible: !!card.c.best; text: "best score"; kind: "interface" }
                            Tag { visible: !!card.c.is_current; text: "current" }
                            Tag { visible: !!card.c.pareto && !card.c.best; text: "frontier" } }
                        Item { width: 1; height: 8 }
                        Rectangle { width: parent.width; height: 132; radius: 10; color: Theme.plate; clip: true
                            Loader { anchors.fill: parent; active: !!card.c.ok
                                sourceComponent: Viewport { id: vp; selected: "-"; lite: true; interactive: false; showDims: false; showCompanions: false
                                    Component.onCompleted: {
                                        setModel({ mesh: [{ feature: "", positions: card.c.mesh.positions, indices: card.c.mesh.indices }], bbox: card.c.bbox, edges: "", companions: [] })
                                        setView("iso", false)
                                        dist = Qt.binding(function () { return alt.frame / Math.sin(13 * Math.PI / 180) * 0.72 })
                                    } } } }
                        Item { width: 1; height: 10 }
                        Txt { text: alt.nameOf(card.c); font.weight: Theme.wSemi; width: parent.width; height: 20; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Item { width: 1; height: 4 }
                        Repeater {
                            model: card.c.ok ? [["Material", F.fmt(card.m.material, 1) + " cm³", true], ["Tip force", F.fmt(card.m.stability) + " N", alt.hasTip],
                                ["Fit yield, modelled", F.fmt(card.m.fit, 0) + " %", alt.hasFit], ["Footprint", F.fmt(card.m.footprint, 0) + " cm²", true]].filter(function (r) { return r[2] }) : []
                            Item { required property var modelData; width: parent.width; height: 22
                                Txt { text: modelData[0]; tone: 2; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                                Txt { text: modelData[1]; mono: true; font.pixelSize: 12; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } } }
                        Item { width: 1; height: 10 }
                        Rectangle { width: parent.width; height: 3; radius: 2; color: Theme.rule2
                            Rectangle { height: 3; radius: 2; width: parent.width * Math.max(0, Math.min(1, card.c.score || 0)); color: card.c.best ? Theme.datum : Theme.ink2 } } }
                    MouseArea { id: cm; anchors.fill: parent; enabled: !!card.c.ok && !alt.busy; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: alt.load(card.c) }
                    // design tools: keep a candidate as a named variant
                    Btn { id: keep; small: true; icon: "layout_grid"; text: "Save as variant"
                        anchors.right: parent.right; anchors.rightMargin: 8; y: 8
                        visible: opacity > 0; opacity: !!card.c.ok && !card.c.is_current && (cm.containsMouse || hovered) ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                        onClicked: Store.saveVariant(alt.nameOf(card.c), card.c.changes, "alternative") }
                    Tip { text: card.c.pareto && !card.c.best ? "Frontier: no other candidate is better on every weighted objective" : "Bar: weighted score"; show: cm.containsMouse }
                } } }
        Txt { kind: "fine"; width: parent.width; text: alt.result ? alt.result.note + " Click a candidate to load it as a draft, or save it as a variant." : "" }
    }
}
