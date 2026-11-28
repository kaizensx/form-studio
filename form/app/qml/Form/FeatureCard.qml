import QtQuick
import "F.js" as F
import "FeatureKinds.js" as K

// The property card of one feature made by hand (the reference's property manager, in our grammar): its sections
// per kind (FeatureKinds.js), each field writing the feature's own parameter. A field change is a draft: the kernel
// builds it at once (Store.setParam → POST /preview), the part shows it over a ghost of the head, and the card says
// the computed change in volume. OK commits one revision; Cancel leaves the head as it was. What a field cannot
// change (the picked edges, the standard a hole's size came from, a pattern's direction) is said, read from the
// feature's code, with the way to change it.
Column {
    id: fc
    objectName: "featureCard"
    property string fid: ""
    property var params: []                 // the recipe's params whose feature is fid
    property string code: ""                // the feature's method, from GET /tree (its source lines)
    readonly property string kind: K.kindOf(fid)
    readonly property var spec: K.KINDS[kind] || null
    readonly property var keys: params.map(function (p) { return p.key })
    function param(s) { var k = fid + "_" + s; for (var i = 0; i < params.length; i++) if (params[i].key === k) return params[i]; return null }
    function val(p) { return Store.values[p.key] !== undefined ? Store.values[p.key] : p.default }
    readonly property bool mine: keys.some(function (k) { return Store.draftValues[k] !== undefined })
    readonly property bool others: F.keys(Store.draftValues).some(function (k) { return fc.keys.indexOf(k) < 0 })
    readonly property var vol: { var pv = Store.preview; if (!pv || !pv.impact) return null
        var m = pv.impact.metrics.filter(function (x) { return x.key === "volume" })[0]; return m ? (m.to - m.from) * 1000 : null }
    visible: !!spec
    spacing: 10

    // a cut's "through all" is a depth of 0 until the engine has an end condition of its own
    function endOf() {
        var ep = param("end"); if (ep) return Math.round(val(ep))
        var d = param("depth"); return kind === "cut" && d && val(d) === 0 ? 1 : 0
    }
    function setEnd(v) {
        var ep = param("end"); if (ep) { Store.setParam(ep.key, v, true); return }
        var d = param("depth"); if (!d || kind !== "cut") return
        Store.setParam(d.key, v === 1 ? 0 : (val(d) > 0 ? val(d) : Math.max(1, Math.min(10, d.max))), true)
    }
    function info(what) {
        var c = code
        if (what === "edges") { var n = (c.match(/"owners"/g) || []).length; return n ? F.plural(n, "picked edge") + ", found again on each rebuild by what made them" : "the picked edges" }
        if (what === "faces") return /shell\([^)]*None/.test(c.replace(/\s+/g, " ")) ? "closed: no face open" : "one picked face open, the rest walls"
        if (what === "standard") { var p = param("d"); return p && p.doc ? p.doc : "a plain diameter" }
        if (what === "axis") {
            var m = /\[(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\]/.exec(c), polar = /"polar"/.test(c)
            if (!m) return polar ? "around an axis" : "along a direction"
            var a = [Number(m[1]), Number(m[2]), Number(m[3])], names = ["x", "y", "z"], i = a.map(Math.abs).indexOf(Math.max.apply(null, a.map(Math.abs)))
            var simple = a.filter(function (x) { return Math.abs(x) > 1e-6 }).length === 1
            return (polar ? "around " : "along ") + (simple ? (a[i] < 0 ? "−" : "") + names[i] : "(" + a.map(function (x) { return F.trim(x, 3) }).join(", ") + ")") + (polar ? ", polar" : ", linear")
        }
        if (what === "sketch") { var dims = params.filter(function (p) { return !/_(depth|angle|end|reverse|draft|depth2|thin)$/.test(p.key) }).length
            var pl = /"datum": "(XY|XZ|YZ)"/.exec(c)
            return F.plural(dims, "dimension") + " as parameters, on " + (pl ? "the " + pl[1] + " plane" : "a picked face") }
        return ""
    }

    Item { width: parent.width; height: 26
        Txt { kind: "cap"; text: fc.spec ? fc.spec.name + " · property card" : ""; anchors.verticalCenter: parent.verticalCenter }
        Ev { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: "computed"; visible: fc.mine && fc.vol !== null; lit: true } }

    Repeater { model: fc.spec ? fc.spec.sections : []
        Column { id: sec; required property var modelData; width: fc.width; spacing: 6
            objectName: "cardSection-" + modelData.title
            readonly property var fields: (modelData.fields || []).filter(function (f) { return f.ends ? fc.kind === "extrude" || fc.kind === "cut" : !!fc.param(f.s) && !(f.hideAtEnd !== undefined && fc.endOf() === f.hideAtEnd) })
            visible: modelData.info ? true : modelData.later ? !!fc.param(modelData.later) : fields.length > 0
            Rectangle { width: parent.width; height: 1; color: Theme.rule }
            Txt { text: sec.modelData.title; font.weight: Theme.wSemi; font.pixelSize: 12; topPadding: 4 + lead }
            Txt { visible: !!sec.modelData.info; width: parent.width; kind: "fine"; tone: 2; text: sec.modelData.info ? fc.info(sec.modelData.info) : "" }
            Btn { visible: sec.modelData.info === "sketch"; small: true; kind: "quiet"; icon: "pen_tool"; text: "Edit sketch"; objectName: "cardEditSketch"
                onClicked: Store.pget("/sketch?feature=" + fc.fid).then(function (r) { Store.openSheet("handsketch", { mode: "edit", feature: fc.fid, sketch: r.sketch, values: r.values }) }, function (e) { Store.fail(e) }) }
            Repeater { model: sec.fields
                Item { id: fl; required property var modelData; width: sec.width; height: 30
                    readonly property var p: modelData.ends ? null : fc.param(modelData.s)
                    objectName: "cardField-" + modelData.s
                    Txt { anchors.verticalCenter: parent.verticalCenter; tone: 2; text: fl.modelData.t; wrapMode: Text.NoWrap; width: parent.width * 0.42; elide: Text.ElideRight }
                    Seg { objectName: "cardEnd"; visible: !!fl.modelData.ends; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; height: 26
                        model: fl.modelData.ends ? K.ENDS.filter(function (e) { return fl.modelData.ends.indexOf(e.value) >= 0 }) : []
                        value: fc.endOf(); onPicked: function (v) { fc.setEnd(v) } }
                    Toggle { visible: !!fl.modelData.toggle && !!fl.p; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        checked: !!fl.p && fc.val(fl.p) > 0.5; onToggled: function (c) { Store.setParam(fl.p.key, c ? 1 : 0, true) } }
                    Field { id: fv; objectName: "cardValue-" + fl.modelData.s; visible: !fl.modelData.ends && !fl.modelData.toggle && !!fl.p
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: Math.min(132, parent.width * 0.5); height: 28; numeric: true
                        unit: fl.modelData.unit !== undefined ? fl.modelData.unit : (fl.p ? fl.p.unit : "mm")
                        readonly property real cur: fl.p ? fc.val(fl.p) : 0
                        text: fl.p ? F.trim(cur, 3) : ""
                        onCurChanged: if (!input.activeFocus || (fl.p && Store.draftValues[fl.p.key] === undefined)) text = F.trim(cur, 3)
                        error: fl.p && text !== "" && (Number(text) < fl.p.min || Number(text) > fl.p.max) ? "Between " + F.trim(fl.p.min) + " and " + F.trim(fl.p.max) : ""
                        onEdited: function (t) { var x = Number(t); if (t !== "" && isFinite(x) && x >= fl.p.min && x <= fl.p.max) Store.setParam(fl.p.key, fl.modelData.int ? Math.round(x) : x) }
                        onAccepted: function (t) { var x = Number(t); if (isFinite(x)) Store.setParam(fl.p.key, Math.max(fl.p.min, Math.min(fl.p.max, fl.modelData.int ? Math.round(x) : x)), true) } } } } } }

    // the draft's computed change, or why the kernel refused it
    Rectangle { objectName: "cardImpact"; visible: fc.mine; width: parent.width; height: ic.implicitHeight + 18; radius: 12; color: Theme.glass
        Column { id: ic; x: 12; y: 9; width: parent.width - 24; spacing: 3
            Txt { objectName: "cardVolume"; visible: !Store.draftError; width: parent.width; mono: true; font.pixelSize: 12
                text: fc.vol === null ? "Building in the kernel…" : (fc.vol >= 0 ? "+" : "−") + F.fmt(Math.abs(fc.vol), 1) + " mm³ of material" }
            Txt { visible: !Store.draftError && fc.vol !== null; kind: "fine"; tone: 3; text: "computed (B-rep), on the draft; nothing is saved until OK" }
            Txt { visible: !!Store.draftError; width: parent.width; kind: "fine"; color: Theme.amber; text: Store.draftError ? (Store.draftError.message || "The kernel refused it.") + (Store.draftError.hint ? " " + Store.draftError.hint : "") : "" }
            Txt { visible: fc.others; width: parent.width; kind: "fine"; tone: 2; text: "The draft also changes values of other features; OK saves them together." } } }
    Row { spacing: 8
        Btn { objectName: "cardOk"; small: true; kind: "primary"; text: "OK"; enabled: fc.mine && !Store.draftError && !!Store.preview
            tip: "Save the change as one revision; the checks run again"; onClicked: Store.commit() }
        Btn { objectName: "cardCancel"; small: true; kind: "quiet"; text: "Cancel"; enabled: F.keys(Store.draftValues).length > 0
            tip: "Back to the head as it is"; onClicked: Store.discard() } }
}
