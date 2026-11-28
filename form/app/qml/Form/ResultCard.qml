import QtQuick
import "F.js" as F

// The result area of the Bench's opened row (BenchCard): what the study found, line by line, each with how it is
// known. A strength study shows its lines and the convergence plot; a manufacturability check its rules (the pointer
// on a rule lights its faces on the part, and a rule with a fix previews it as a ghost); a CNC route its operations;
// a flat pattern its bends; a motion study its joints. All of it is Results.r, the engine's description of the entry
// shown on the part. A row that is not current says so and draws nothing.
Column {
    id: rc
    objectName: "resultCard"
    property var e: null                  // the Bench entry of the card
    readonly property bool mine: !!e && Results.id === e.id && !!Results.r
    readonly property var r: mine ? Results.r : null
    readonly property string kind: r && r.state === "current" ? r.kind : ""
    visible: mine
    function count(status) { var n = 0, rows = kind === "dfm" ? r.rows : []; for (var i = 0; i < rows.length; i++) if (rows[i].status === status) n++; return n }
    // the number that stands large in the card, and the words beside it: the first line of the result
    readonly property var lead: kind === "field" && r.lines.length && r.lines[0].v !== "" ? [r.lines[0].v, r.lines[0].k.toLowerCase()]
        : kind === "dfm" ? [String(count("fail")), (count("fail") === 1 ? "rule fails" : "rules fail") + (count("warn") ? ", " + count("warn") + " warn" : "") + (count("not_checked") ? ", " + count("not_checked") + " not checked" : "")]
        : kind === "cam" ? [r.summary.cycle_time || "", "cycle time, " + r.summary.verdict] : kind === "flat" && r.size_mm ? [F.fmt(r.size_mm[0], 1) + " × " + F.fmt(r.size_mm[1], 1), "mm flat, " + r.bends.length + " bends"]
        : kind === "drawing" ? [r.name || "Sheet", r.dims.length + " dimensions, " + r.dims.filter(function (d) { return d.editable }).length + " bound to a parameter"]
        : kind === "stack" ? [Results.fmt(r.gap.nominal, ""), "mm gap, RSS " + Results.fmt(r.rss[0], "") + " to " + Results.fmt(r.rss[1], "mm")]
        : kind === "topology" ? [String(Math.max(0, (r.history || []).length - 1)), "iterations" + (r.converged ? ", converged" : ", stopped before converging")]
        : kind === "front" ? [String(r.front.length), r.app === "inverse" ? "variants on the front" : "orientations on the front"]
        : kind === "motion" && r.clearance && r.clearance.min ? [Results.fmt(r.clearance.min.clearance_mm, ""), "mm smallest gap, at " + Results.fmt(r.clearance.min.t, "s")] : null
    spacing: 10

    component Line: Item {
        property string k: ""
        property string v: ""
        property string ev: ""
        property string note: ""
        width: rc.width; height: Math.max(20, 20 + (nt.visible ? nt.implicitHeight + 1 : 0))
        Txt { id: kt; text: parent.k; tone: 2; y: 1; width: Math.min(implicitWidth, parent.width * 0.5); elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Ev { id: et; text: parent.ev; anchors.right: parent.right; anchors.baseline: kt.baseline }
        Txt { objectName: "resultValue"; text: parent.v; mono: true; anchors.right: et.left; anchors.rightMargin: et.text !== "" ? 10 : 0; anchors.baseline: kt.baseline; wrapMode: Text.NoWrap }
        Txt { id: nt; visible: text !== ""; text: parent.note; kind: "fine"; tone: 3; y: 20; width: parent.width }
    }

    // nothing to draw: the state, in words (never a number that was not computed)
    Txt { objectName: "resultNone"; visible: rc.mine && rc.kind === "" && !Results.busy; width: parent.width; kind: "fine"; tone: 2
        text: !rc.r ? "" : (rc.r.state === "stale" ? "Stale: nothing is drawn on the part. " : rc.r.state === "current" ? "" : "Not run: nothing is drawn on the part. ") + (rc.r.why || "") }

    // ── strength ──
    Txt { visible: text !== ""; width: parent.width; kind: "fine"; tone: 2
        text: rc.kind === "field" && rc.lead && rc.r.lines[0].note ? rc.r.lines[0].note : "" }
    Seg { objectName: "studySeg"; visible: rc.mine && !!rc.r.studies && rc.r.studies.length > 1; height: 26; width: Math.min(implicitWidth, parent.width)
        model: rc.mine && rc.r.studies ? rc.r.studies.map(function (s) { return { value: s.id, text: s.name } }) : []
        value: rc.mine ? rc.r.study || "" : ""; onPicked: function (v) { Results.setStudy(v) } }
    Txt { objectName: "notConverged"; visible: rc.kind === "field" && rc.r.converged !== true; width: parent.width; color: Theme.signal
        text: rc.kind === "field" ? "Did not converge: " + (rc.r.why || "no reason given") : "" }
    // the verdict in one sentence, and the load scale of a linear static study (StudyVerdict.qml)
    StudyVerdict { width: parent.width; r: rc.kind === "field" && rc.r.converged === true ? rc.r : null }
    Column { width: parent.width; spacing: 2; visible: rc.kind === "field"
        Repeater { model: rc.kind === "field" ? rc.r.lines.slice(rc.lead ? 1 : 0) : []
            Line { required property var modelData; objectName: "resultLine"; k: modelData.k; v: modelData.v; ev: modelData.ev; note: modelData.note || "" } } }
    // the convergence plot: the deciding quantity on each mesh, against the unknowns solved; dashed to the extrapolation
    Item { id: conv; objectName: "convergence"; width: parent.width; height: 96
        readonly property var c: rc.kind === "field" ? rc.r.convergence : null
        readonly property var pts: c ? c.points : []
        visible: pts.length >= 2
        Canvas { id: cv; width: parent.width; height: 62
            readonly property var pts: conv.pts
            readonly property var ext: conv.c ? conv.c.extrapolated : null
            onPtsChanged: requestPaint(); onWidthChanged: requestPaint(); Component.onCompleted: requestPaint()
            Connections { target: Theme; function onDarkChanged() { cv.requestPaint() } }
            function px(i, n) { return 6 + (width - 12 - (ext !== null && ext !== undefined ? 34 : 0)) * (n > 1 ? i / (n - 1) : 0) }
            onPaint: { var g = getContext("2d"); g.reset(); var n = pts.length; if (n < 2) return
                var lo = Infinity, hi = -Infinity, i, hasExt = ext !== null && ext !== undefined
                for (i = 0; i < n; i++) { lo = Math.min(lo, pts[i].value); hi = Math.max(hi, pts[i].value) }
                if (hasExt) { lo = Math.min(lo, ext); hi = Math.max(hi, ext) }
                var span = Math.max(hi - lo, Math.abs(hi) * 1e-6, 1e-12), H = height
                function py(v) { return H - 10 - (H - 22) * (v - lo) / span }
                g.strokeStyle = Theme.rule2; g.lineWidth = 1; g.beginPath(); g.moveTo(0, H - 0.5); g.lineTo(width, H - 0.5); g.stroke()
                g.strokeStyle = Theme.ink2; g.lineWidth = 1.25; g.beginPath()
                for (i = 0; i < n; i++) { if (i) g.lineTo(px(i, n), py(pts[i].value)); else g.moveTo(px(i, n), py(pts[i].value)) }
                g.stroke()
                if (hasExt) { g.strokeStyle = Theme.datum; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(px(n - 1, n), py(pts[n - 1].value)); g.lineTo(width - 6, py(ext)); g.stroke(); g.setLineDash([])
                    g.fillStyle = Theme.datum; g.beginPath(); g.arc(width - 6, py(ext), 3, 0, 2 * Math.PI); g.fill() }
                for (i = 0; i < n; i++) { g.fillStyle = i === n - 1 ? Theme.datum : Theme.ink; g.beginPath(); g.arc(px(i, n), py(pts[i].value), 2.5, 0, 2 * Math.PI); g.fill() } } }
        Repeater { model: conv.pts.length
            Txt { required property int index; y: 68; mono: true; font.pixelSize: 11; tone: index === conv.pts.length - 1 ? 1 : 3; wrapMode: Text.NoWrap
                text: Results.fmt(conv.pts[index].value, "")
                x: Math.round(Math.max(0, Math.min(conv.width - width, cv.px(index, conv.pts.length) - width / 2))) } }
        Txt { y: 82; kind: "fine"; tone: 3; width: parent.width; wrapMode: Text.NoWrap; elide: Text.ElideRight
            text: conv.c ? conv.c.quantity + ", by mesh" + (conv.pts.length ? ": " + conv.pts.map(function (p) { return F.thousands ? F.thousands(p.unknowns) : p.unknowns }).join(", ") + " unknowns" : "") : "" }
    }

    // ── manufacturability: the rules ──
    Column { width: parent.width; spacing: 0; visible: rc.kind === "dfm"
        Repeater { model: rc.kind === "dfm" ? rc.r.rows : []
            Item { id: rule; required property var modelData
                objectName: "rule-" + modelData.id
                readonly property bool lit: Results.litRule === modelData.id
                readonly property var fx: (Results.r, Results.fixFor(modelData.id))
                readonly property color c: modelData.status === "fail" ? Theme.signal : modelData.status === "warn" ? Theme.amber : modelData.status === "pass" ? Theme.pass : Theme.ink3
                width: rc.width; height: Math.max(26, rt.implicitHeight + 10)
                Rectangle { anchors.fill: parent; anchors.leftMargin: -6; anchors.rightMargin: -6; radius: 7; color: rule.lit ? Theme.washOn : hh.hovered ? Theme.washHover : "transparent" }
                Rectangle { x: 1; y: 10; width: 6; height: 6; radius: 3; color: rule.modelData.status === "not_checked" || rule.modelData.status === "n/a" || rule.modelData.status === "info" ? "transparent" : rule.c; border.width: 1; border.color: rule.c }
                Txt { id: rt; x: 16; y: 5; width: parent.width - 16 - rv.width - 8; font.pixelSize: 12; tone: rule.modelData.status === "n/a" ? 3 : 1; text: rule.modelData.title }
                Txt { id: rv; anchors.right: parent.right; y: 5; mono: true; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; opacity: fb.visible ? 0 : 1
                    text: rule.modelData.status === "not_checked" ? "not checked" : rule.modelData.status === "n/a" ? "n/a"
                        : rule.modelData.value !== null && rule.modelData.value !== undefined ? Results.fmt(Number(rule.modelData.value), rule.modelData.unit) : rule.modelData.status }
                HoverHandler { id: hh; onHoveredChanged: { if (hovered && rule.modelData.faces.length) Results.litRule = rule.modelData.id; else if (!hovered && Results.litRule === rule.modelData.id) Results.litRule = "" } }
                Tip { show: hh.hovered && !fb.hovered; text: (rule.modelData.reason || rule.modelData.why || "") + (rule.modelData.faces.length ? " Lit on the part: " + rule.modelData.faces.length + " face" + (rule.modelData.faces.length > 1 ? "s." : ".") : "") }
                Btn { id: fb; objectName: "fix-" + rule.modelData.id; visible: !!rule.fx && (rule.modelData.status === "fail" || rule.modelData.status === "warn") && hh.hovered && !Results.fix
                    small: true; height: 22; anchors.right: parent.right; y: 2; text: "Preview the fix"; autoBusy: false; onClicked: Results.previewFix(rule.fx.id) }
            } } }
    // a fix, previewed: built and checked, not saved. Before and after on the part; Apply saves it and checks again.
    Rectangle { objectName: "fixPreview"; visible: rc.kind === "dfm" && !!Results.fix; width: parent.width; height: fxc.implicitHeight + 20; radius: 10; color: Theme.glassWell; border.color: Theme.rule
        Column { id: fxc; x: 10; y: 10; width: parent.width - 20; spacing: 7
            Txt { width: parent.width; font.weight: Theme.wSemi; font.pixelSize: 12; text: Results.fix ? (Results.fix.busy && !Results.fix.preview ? "Building the fix without saving it…" : Results.fix.summary || "Fix") : "" }
            Repeater { model: Results.fix && Results.fix.preview ? Results.fix.preview : []
                Item { required property var modelData; width: fxc.width; height: 18
                    Txt { font.pixelSize: 12; tone: 2; text: modelData.rule || modelData.id || ""; width: parent.width * 0.5; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    Txt { anchors.right: parent.right; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                        text: (modelData.before !== undefined ? modelData.before : modelData.status_before || "") + " → " + (modelData.after !== undefined ? modelData.after : modelData.status_after || "") } } }
            Txt { width: parent.width; kind: "fine"; tone: 3; visible: text !== ""; text: Results.fix && !Results.fix.busy ? Results.fix.why || "" : "" }
            Row { spacing: 8; visible: !!Results.fix && !(Results.fix.busy && !Results.fix.preview)
                Seg { objectName: "fixSide"; height: 24; visible: !!Results.fix && !!Results.fix.view
                    model: [{ value: false, text: "Before" }, { value: true, text: "After" }]; value: Results.fix ? !!Results.fix.after : false; onPicked: function (v) { Results.fixSide(v) } }
                Btn { objectName: "fixApply"; small: true; height: 24; kind: "primary"; visible: !!Results.fix && !!Results.fix.ok; text: "Apply fix"; busy: !!Results.fix && !!Results.fix.busy; autoBusy: false; onClicked: Results.applyFix() }
                Btn { objectName: "fixCancel"; small: true; height: 24; kind: "quiet"; text: "Cancel"; autoBusy: false; onClicked: Results.dropFix() } } } }

    // ── CNC: the operations of the setup shown ──
    Column { width: parent.width; spacing: 2; visible: rc.kind === "cam"
        Repeater { model: rc.kind === "cam" && rc.r.setups[Results.setup] ? rc.r.setups[Results.setup].ops.filter(function (o) { return o.kind === "feed" }) : []
            Item { required property var modelData; objectName: "camOp"; width: rc.width; height: 22
                Rectangle { y: 8; width: 10; height: 4; radius: 2; color: modelData.color }
                Txt { x: 18; font.pixelSize: 12; text: (modelData.label || modelData.operation || "operation") ; width: parent.width - 18 - ot.width - 8; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    tone: Results.t >= modelData.t0 ? 1 : 3 }
                Txt { id: ot; anchors.right: parent.right; mono: true; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; text: (modelData.tool || "") + "  " + Results.clock(modelData.t1 - modelData.t0) }
                MouseArea { anchors.fill: parent; onClicked: Results.scrub(modelData.t1) } } }
        Line { k: "Gouge, deepest"; v: rc.kind === "cam" ? rc.r.summary.gouge_max_mm + " mm" : ""; ev: "simulated" }
        Line { k: "Leftover"; v: rc.kind === "cam" ? rc.r.summary.leftover_mm3 + " mm³" : ""; ev: "simulated" }
        Line { k: "Cycle time"; v: rc.kind === "cam" ? rc.r.summary.cycle_time || "" : ""; ev: "simulated"; note: rc.kind === "cam" ? rc.r.label : "" }
    }

    // ── sheet metal: the bends ──
    Column { width: parent.width; spacing: 2; visible: rc.kind === "flat"
        Repeater { model: rc.kind === "flat" ? rc.r.bends : []
            Line { required property var modelData; required property int index; objectName: "bendLine"
                k: "Bend " + (index + 1); v: Math.round(modelData.angle * 10) / 10 + "° " + modelData.direction + " · R " + Math.round(modelData.r * 100) / 100; ev: "computed"
                note: "" } }
        Line { objectName: "kFactor"; k: "K-factor"; v: rc.kind === "flat" && rc.r.bends.length ? String(Math.round(rc.r.bends[0].K * 100) / 100) : ""; ev: "specified"
            note: rc.kind === "flat" && rc.r.bends.length ? rc.r.bends[0].k_source : "" }
        Line { k: "Flat size"; v: rc.kind === "flat" && rc.r.size_mm ? F.fmt(rc.r.size_mm[0], 1) + " × " + F.fmt(rc.r.size_mm[1], 1) + " mm" : ""; ev: "computed" }
    }

    // ── motion: the joints, at the moment shown ──
    Column { width: parent.width; spacing: 2; visible: rc.kind === "motion"
        Repeater { model: rc.kind === "motion" ? rc.r.joints : []
            Line { required property var modelData; objectName: "jointLine"
                k: (modelData.label || modelData.joint) + (modelData.role === "driven" ? ", driven" : "")
                v: modelData.value && modelData.value.length ? F.fmt(modelData.value[Math.min(Results.frame, modelData.value.length - 1)], 1) + " " + (modelData.unit || "") : ""
                ev: modelData.role === "driven" ? "specified" : "computed" } }
        Line { k: "Smallest gap"; v: rc.kind === "motion" && rc.r.clearance ? rc.r.clearance.value : "not checked"; ev: rc.kind === "motion" && rc.r.clearance ? "computed" : "" }
        Line { k: "First contact"; v: rc.kind === "motion" && rc.r.clearance ? (rc.r.clearance.first_contact_t !== null && rc.r.clearance.first_contact_t !== undefined ? Results.fmt(rc.r.clearance.first_contact_t, "s") : "none") : ""; ev: "computed" }
    }

    // ── tolerance stack-up: the gap's numbers and the largest shares ──
    Column { width: parent.width; spacing: 2; visible: rc.kind === "stack"
        Line { k: "Worst case"; v: rc.kind === "stack" ? Results.fmt(rc.r.worst_case[0], "") + " to " + Results.fmt(rc.r.worst_case[1], "mm") : ""; ev: "computed" }
        Line { k: "RSS"; v: rc.kind === "stack" ? Results.fmt(rc.r.rss[0], "") + " to " + Results.fmt(rc.r.rss[1], "mm") : ""; ev: "computed" }
        Line { k: "Cpk"; v: rc.kind === "stack" && rc.r.cpk !== null && rc.r.cpk !== undefined ? rc.r.cpk.toFixed(2) : "no spec"; ev: rc.kind === "stack" ? Results.evWord(rc.r.spec.evidence) : "" }
        Repeater { model: rc.kind === "stack" ? rc.r.chart : []
            Line { required property var modelData; objectName: "stackShare"; k: modelData.label; v: F.fmt(modelData.percent, 1) + " %"; ev: "computed" } }
    }

    // ── topology: the run, iteration by iteration ──
    Column { width: parent.width; spacing: 2; visible: rc.kind === "topology"
        readonly property var h: rc.kind === "topology" ? (rc.r.history || []) : []
        readonly property var at: h.length ? h[Math.min(h.length - 1, Results.iteration)] : null
        Line { k: "Iteration"; v: rc.kind === "topology" ? Results.iteration + " of " + Results.duration : ""; ev: "simulated" }
        Line { k: "Compliance"; v: parent.at && parent.at.compliance ? Results.fmt(parent.at.compliance, "N·mm") : "the even start"; ev: "simulated" }
        Line { k: "Material kept"; v: parent.at && parent.at.volume !== null && parent.at.volume !== undefined ? F.fmt(100 * parent.at.volume, 1) + " %" : ""; ev: "computed"
            note: rc.kind === "topology" ? rc.r.resolution : "" }
    }

    // ── a front (inverse design, print orientation): the Pareto chart; a point opens its variant ──
    FrontChart { objectName: "frontChart"; visible: rc.kind === "front"; width: parent.width; height: 168; r: rc.kind === "front" ? rc.r : null }
    Column { width: parent.width; spacing: 2; visible: rc.kind === "front" && Results.point >= 0
        readonly property var pt: { if (rc.kind !== "front") return null; var ps = rc.r.points; for (var i = 0; i < ps.length; i++) if (ps[i].index === Results.point) return ps[i]; return null }
        Repeater { model: parent.pt ? rc.r.axes : []
            Line { required property var modelData; required property int index; k: modelData.label; v: Results.fmt(parent.pt.at[index], modelData.unit); ev: rc.r.app === "inverse" ? "simulated" : index === 0 ? "computed" : "modelled" } }
        Line { visible: !!parent.pt && rc.r.app === "printOrient"; k: "Tips over at"; v: parent.pt && parent.pt.tip_over_deg !== undefined && parent.pt.tip_over_deg !== null ? F.fmt(parent.pt.tip_over_deg, 0) + "°" : ""; ev: "computed"
            note: parent.pt ? (parent.pt.label || "") : "" }
    }
    Txt { visible: rc.kind === "front"; width: parent.width; kind: "fine"; tone: 3; text: rc.kind === "front" ? rc.r.open + " " + rc.r.note : "" }

    // ── the drawing: what is selected on the sheet ──
    Txt { visible: rc.kind === "drawing"; width: parent.width; kind: "fine"; tone: 2
        text: rc.kind === "drawing" ? rc.r.dims.length + " dimensions on the sheet, " + rc.r.dims.filter(function (d) { return d.editable }).length + " bound to a parameter: double-click one to change the design. P switches night and paper." : "" }
}
