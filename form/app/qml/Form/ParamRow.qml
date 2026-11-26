import QtQuick
import "F.js" as F

// One parameter: its name, the number, a caliper-beam slider. Changes go to the draft and rebuild live.
// With prov: true it also shows how the value is known (source and ±1σ).
Item {
    id: r
    property var p                       // param spec from the recipe
    property bool prov: false
    objectName: "param-" + (p ? p.key : "")
    readonly property real v: Store.values[p.key] !== undefined ? Store.values[p.key] : p.default
    readonly property bool changed: Store.draftValues[p.key] !== undefined
    readonly property bool bad: !!(Store.draftError && Store.draftError.params && Store.draftError.params.indexOf(p.key) >= 0)
    readonly property var pr: Object.assign({ source: "assumed" }, Store.head && Store.head.provenance[p.key] || {}, Store.draftProv[p.key] || {})
    readonly property var sigmas: ({ measured: 0.03, specified: 0.1, assumed: 0.3, photo: 0.6 })
    width: parent ? parent.width : 0
    implicitHeight: col.implicitHeight + 14
    Rectangle { visible: r.changed || r.bad; x: -12; y: 8; width: 2; height: parent.height - 14; radius: 1; color: r.bad ? Theme.signal : Theme.blueprint }
    Column {
        id: col; y: 9; width: parent.width; spacing: 5
        Item {
            width: parent.width; height: 26
            Txt { text: r.p.label; anchors.left: parent.left; anchors.right: num.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight; wrapMode: Text.NoWrap; color: r.bad ? Theme.signal : r.changed ? Theme.blueprint : Theme.ink }
            Field { id: num; objectName: "paramField"; numeric: true; width: 86; height: 26; anchors.right: parent.right; unit: r.p.unit
                text: F.trim(r.v, 4)
                onAccepted: function (t) {
                    var x = parseFloat(t)
                    if (!isFinite(x)) { text = F.trim(r.v, 4); return }
                    x = Math.min(r.p.max, Math.max(r.p.min, x))
                    if (Math.abs(x - r.v) > 1e-9) Store.setParam(r.p.key, x, true)
                    text = Qt.binding(function () { return F.trim(r.v, 4) })
                } }
        }
        Beam { objectName: "paramBeam"; width: parent.width; from: r.p.min; to: r.p.max; step: r.p.step; value: r.v
            base: Store.head ? Store.head.values[r.p.key] : NaN
            tint: r.bad ? Theme.signal : r.changed ? Theme.blueprint : Theme.ink
            onMoved: function (v) { Store.setParam(r.p.key, v) } }
        Txt { kind: "fine"; visible: !!r.p.doc; text: r.p.doc || ""; width: parent.width }
        Row {
            visible: r.prov; spacing: 6; height: visible ? 26 : 0
            Tag { text: r.pr.source === "photo" ? "from photo" : r.pr.source; kind: r.pr.source; anchors.verticalCenter: parent.verticalCenter }
            Pick { width: 112; height: 24; anchors.verticalCenter: parent.verticalCenter; value: r.pr.source
                model: [{ value: "measured", text: "Measured" }, { value: "specified", text: "Specified" }, { value: "assumed", text: "Assumed" }, { value: "photo", text: "From photo" }]
                onPicked: function (v) { Store.setProv(r.p.key, { source: v, sigma: r.sigmas[v] }) } }
            Txt { text: "±"; tone: 3; anchors.verticalCenter: parent.verticalCenter }
            Field { numeric: true; width: 74; height: 24; unit: r.p.unit; anchors.verticalCenter: parent.verticalCenter
                text: F.trim(r.pr.sigma !== undefined ? r.pr.sigma : (r.sigmas[r.pr.source] || 0.3), 3)
                onAccepted: function (t) { var x = Math.max(0, parseFloat(t) || 0); if (Math.abs(x - (r.pr.sigma || 0)) > 1e-9) Store.setProv(r.p.key, { source: r.pr.source, sigma: x }) } }
        }
    }
}
