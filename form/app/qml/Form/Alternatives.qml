import QtQuick
import "F.js" as F

// Compare alternatives: vary one or two parameters, build every candidate in the kernel, rank against weighted objectives.
Column {
    id: alt
    property string title: "Compare alternatives"
    property int sheetWidth: 980
    spacing: 14; bottomPadding: 20

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
    readonly property real cardW: Math.floor((width - (cols - 1) * 10) / cols)
    readonly property bool hasTip: okRows.some(function (x) { return x.metrics.stability !== null && x.metrics.stability !== undefined })
    readonly property bool hasFit: okRows.some(function (x) { return x.metrics.fit !== null && x.metrics.fit !== undefined })

    function span(key) {
        var p = Store.spec(key); if (!p) return ""
        var x = v[key], dlt = Math.max(p.step * 2, Math.abs(x) * 0.18)
        function r(n) { return Math.round(Math.min(p.max, Math.max(p.min, n)) / p.step) * p.step }
        return [r(x - dlt), r(x), r(x + dlt)].map(function (n) { return F.trim(n, 3) }).join(", ")
    }
    function parse(t) { return t.split(/[,\s]+/).filter(function (s) { return s !== "" }).map(Number).filter(function (n) { return isFinite(n) }) }
    function nameOf(x) { return result.axes.map(function (a) { return a.label.split(" ")[0] + " " + F.trim(x.changes[a.key]) }).join(" · ") }
    function build() {
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

    Row { width: parent.width; spacing: 32
        Column { width: (parent.width - 32) / 2; spacing: 8
            Cap { text: "Vary" }
            Row { width: parent.width; spacing: 8
                Pick { width: 190; model: alt.picks; value: alt.ax1; onPicked: function (k) { alt.ax1 = k } }
                Field { id: v1; width: parent.width - 198; mono: true; text: alt.span(alt.ax1) } }
            Row { width: parent.width; spacing: 8
                Pick { width: 190; model: alt.picks; value: alt.ax2; onPicked: function (k) { alt.ax2 = k } }
                Field { id: v2; width: parent.width - 198; mono: true; text: alt.span(alt.ax2); opacity: alt.ax2 === alt.ax1 ? 0.4 : 1 } }
            Txt { kind: "fine"; width: parent.width; text: "Up to five values per parameter, comma-separated. Interfaces stay as committed unless you vary them." }
        }
        Column { width: (parent.width - 32) / 2; spacing: 8
            Cap { text: "Weight the objectives"; note: "0 = ignore" }
            Column { width: parent.width
                Repeater { model: alt.names
                    Item { id: wr; required property var modelData
                        width: parent.width; height: 26
                        Txt { text: wr.modelData[1]; tone: 2; anchors.verticalCenter: parent.verticalCenter }
                        Beam { width: 150; anchors.right: num.left; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                            from: 0; to: 3; step: 1; value: alt.weights[wr.modelData[0]]
                            onMoved: function (x) { var w = Object.assign({}, alt.weights); w[wr.modelData[0]] = x; alt.weights = w } }
                        Txt { id: num; mono: true; width: 14; horizontalAlignment: Text.AlignRight; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            text: String(alt.weights[wr.modelData[0]]); tone: alt.weights[wr.modelData[0]] > 0 ? 1 : 4 } } } }
            Btn { kind: "primary"; icon: "boxes"; enabled: !alt.busy && alt.ax1 !== ""
                text: alt.busy ? "Building candidates…" : "Build candidates"; onClicked: alt.build() }
        }
    }

    Note { visible: !!alt.error; kind: "red"; title: alt.error ? alt.error.message || "Could not build the candidates" : ""; text: alt.error && alt.error.hint ? alt.error.hint : "" }

    Column { width: parent.width; spacing: 10; visible: !!alt.result
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Cap { text: alt.result ? alt.okRows.length + " built · " + (alt.result.rows.length - alt.okRows.length) + " infeasible" : ""
            note: alt.elapsed.toFixed(1) + " s" }
        Grid { width: parent.width; columns: alt.cols; spacing: 10
            Repeater { model: alt.result ? alt.result.rows : []
                Rectangle { id: card; required property var modelData
                    readonly property var c: modelData
                    readonly property var m: c.ok ? c.metrics : ({})
                    width: alt.cardW; height: 12 + 17 + 6 + 132 + 8 + 20 + 4 + (2 + (alt.hasTip ? 1 : 0) + (alt.hasFit ? 1 : 0)) * 20 + 8 + 3 + 12
                    radius: Theme.rMd
                    color: !c.ok ? Theme.alpha(Theme.signal, 0.05) : cm.containsMouse ? Theme.plate3 : Theme.plate1
                    border.color: !c.ok ? Theme.alpha(Theme.signal, 0.3) : c.best ? Theme.alpha(Theme.datum, 0.6) : Theme.rule
                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                    // infeasible
                    Column { visible: !card.c.ok; x: 12; y: 12; width: parent.width - 24; spacing: 6
                        Tag { text: "infeasible"; kind: "FAIL" }
                        Txt { text: alt.nameOf(card.c); font.weight: 600; width: parent.width }
                        Txt { kind: "fine"; width: parent.width; color: Theme.signal; text: card.c.ok ? "" : (card.c.error && card.c.error.message ? card.c.error.message : "Did not build.") } }
                    // built
                    Column { visible: !!card.c.ok; x: 12; y: 12; width: parent.width - 24
                        Row { height: 17; spacing: 5
                            Tag { visible: !!card.c.best; text: "best score"; kind: "interface" }
                            Tag { visible: !!card.c.is_current; text: "current" }
                            Tag { visible: !!card.c.pareto && !card.c.best; text: "frontier" } }
                        Item { width: 1; height: 6 }
                        Rectangle { width: parent.width; height: 132; radius: Theme.rSm; color: Theme.plate; clip: true
                            Loader { anchors.fill: parent; active: !!card.c.ok
                                sourceComponent: Viewport { id: vp; selected: "-"; lite: true; interactive: false; showDims: false; showCompanions: false
                                    Component.onCompleted: {
                                        setModel({ mesh: [{ feature: "", positions: card.c.mesh.positions, indices: card.c.mesh.indices }], bbox: card.c.bbox, edges: "", companions: [] })
                                        setView("iso", false)
                                        dist = Qt.binding(function () { return alt.frame / Math.sin(13 * Math.PI / 180) * 0.72 })
                                    } } } }
                        Item { width: 1; height: 8 }
                        Txt { text: alt.nameOf(card.c); font.weight: 600; width: parent.width; height: 20; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Item { width: 1; height: 4 }
                        Repeater {
                            model: card.c.ok ? [["Material", F.fmt(card.m.material, 1) + " cm³", true], ["Tip force", F.fmt(card.m.stability) + " N", alt.hasTip],
                                ["Fit yield, modelled", F.fmt(card.m.fit, 0) + " %", alt.hasFit], ["Footprint", F.fmt(card.m.footprint, 0) + " cm²", true]].filter(function (r) { return r[2] }) : []
                            Item { required property var modelData; width: parent.width; height: 20
                                Txt { text: modelData[0]; tone: 2; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                                Txt { text: modelData[1]; mono: true; font.pixelSize: 12; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } } }
                        Item { width: 1; height: 8 }
                        Rectangle { width: parent.width; height: 3; radius: 1.5; color: Theme.rule2
                            Rectangle { height: 3; radius: 1.5; width: parent.width * Math.max(0, Math.min(1, card.c.score || 0)); color: card.c.best ? Theme.datum : Theme.ink2 } } }
                    MouseArea { id: cm; anchors.fill: parent; enabled: !!card.c.ok; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: alt.load(card.c) }
                    Tip { text: card.c.pareto && !card.c.best ? "Frontier: no other candidate is better on every weighted objective" : "Bar: weighted score"; show: cm.containsMouse }
                } } }
        Txt { kind: "fine"; width: parent.width; text: alt.result ? alt.result.note + " Click a candidate to load it as a draft." : "" }
    }
}
