import QtQuick
import "F.js" as F

// Mass and inertia of what is on screen (form/massprops.py, Store.mass): a compact pane of glass over the room,
// above the size line. The mass with how it is known (B-rep volume × the material's density, and where that density
// was read), the centre of mass in the frame drawn (as built, or assembled at the pose), the principal moments, and
// one line per part. A part without a material has no mass here: the pane says so instead of assuming one. The
// centre and the principal axes are drawn on the part while it is open (MassLayer).
Glass {
    id: mr
    objectName: "massReadout"
    property var m: Store.mass
    readonly property var t: m ? m.total : null
    readonly property var mats: {
        var out = [], seen = ({}), ps = m ? m.parts : []
        for (var i = 0; i < ps.length; i++) if (ps[i].material && !seen[ps[i].material.id]) { seen[ps[i].material.id] = true; out.push(ps[i].material) }
        return out
    }
    readonly property bool printed: mats.some(function (x) { return x.kind === "filament" })
    radius: Theme.rLg + 2
    width: 300; height: body.implicitHeight + 24

    // grams below a kilogram, kilograms above; inertia in g·mm² until it is large, then kg·m²
    function grams(g) { return g >= 1000 ? F.fmt(g / 1000, g >= 10000 ? 1 : 2) + " kg" : F.fmt(g, g < 10 ? 2 : g < 100 ? 1 : 0) + " g" }
    function inertia(v) { return v >= 1e7 ? F.fmt(v * 1e-9, 4) + " kg·m²" : Math.round(v).toLocaleString(Qt.locale("en_US"), "f", 0) + " g·mm²" }
    function n1(v) { return F.fmt(Math.abs(v) < 0.05 ? 0 : v, 1) }        // never "-0.0"
    function pt(c) { return c ? n1(c[0]) + ", " + n1(c[1]) + ", " + n1(c[2]) : "—" }
    function frameText() {
        if (!m) return ""
        if (m.frame !== "assembled") return "as built"
        var ks = Object.keys(m.pose || {})
        if (!ks.length) return "assembled, joints at 0"
        return "assembled · " + ks.map(function (k) {
            var j = (m.joints || []).filter(function (x) { return x.id === k })[0]
            return (j ? j.label : k) + " " + F.trim(m.pose[k]) + (j && j.kind === "slide" ? " mm" : "°") }).join(", ")
    }

    Column {
        id: body; x: 14; y: 12; width: parent.width - 28; spacing: 8
        Row {
            width: parent.width; spacing: 8
            Txt { id: ttl; text: "Mass & inertia"; font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter }
            Tag { text: mr.m && mr.m.evidence === "computed (closed mesh)" ? "computed · mesh" : "computed"; kind: "computed"; anchors.verticalCenter: parent.verticalCenter }
            Item { width: parent.width - ttl.implicitWidth - 120 - 30; height: 1 }
            Btn { objectName: "massClose"; small: true; kind: "quiet"; icon: "x"; width: 26; height: 26; tip: "Hide the centre of mass"
                anchors.verticalCenter: parent.verticalCenter; onClicked: Store.massOn = false }
        }
        // the mass, and what it is made of
        Row {
            spacing: 10; visible: !!mr.t
            Txt { id: grams; objectName: "massGrams"; mono: true; font.pixelSize: 22; font.weight: Theme.wSemi; wrapMode: Text.NoWrap
                text: mr.t ? mr.grams(mr.t.mass_g) : "" }
            Txt { kind: "fine"; tone: 2; text: "if printed solid"; visible: mr.printed; wrapMode: Text.NoWrap; anchors.baseline: grams.baseline }
        }
        Txt { kind: "fine"; tone: 2; width: parent.width; visible: !!mr.m
            text: !mr.m ? "" : !mr.mats.length ? "No material is chosen, so there is no mass: choose one in Colour and material. The centre below is the volume's."
                : mr.mats.length === 1 ? mr.mats[0].label + " · " + F.fmt(mr.mats[0].density_kg_m3, 0) + " kg/m³ × B-rep volume"
                    + (String(mr.mats[0].why).indexOf("assumed") === 0 ? " (assumed)" : "")
                : mr.mats.length + " materials · each part's density × its volume" }
        Txt { kind: "fine"; tone: 3; width: parent.width; visible: mr.mats.length > 0; maximumLineCount: 2; elide: Text.ElideRight
            text: "Density: " + mr.mats.map(function (x) { return x.density_source + (x.density_evidence.indexOf("specified") === 0 ? "" : " (typical)") }).join("; ") }
        Item { width: 1; height: 2 }
        KV { first: true; k: mr.t ? "Centre of mass" : "Centre of volume"; sub: mr.frameText(); value: mr.pt(mr.t ? mr.t.com_mm : (mr.m ? mr.m.volume_centroid_mm : null)) + " mm" }
        KV { visible: !!mr.t; k: "Principal moments"; sub: "about the centre; axes drawn on the part, longest = smallest"
            value: mr.t ? mr.t.principal.moments_g_mm2.map(function (v) { return mr.inertia(v) }).join("\n") : "" }
        // one line per part, when there are several
        Column {
            width: parent.width; spacing: 2; visible: !!mr.m && mr.m.parts.length > 1
            Txt { kind: "cap"; text: "Parts" }
            Repeater {
                model: mr.m ? mr.m.parts.slice(0, 6) : []
                Row {
                    required property var modelData
                    width: parent.width; spacing: 8
                    Txt { text: modelData.label; width: parent.width - 150; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 12 }
                    Txt { mono: true; font.pixelSize: 12; width: 64; horizontalAlignment: Text.AlignRight; text: modelData.mass_g !== undefined ? mr.grams(modelData.mass_g) : "—" }
                    Txt { kind: "fine"; tone: 3; width: 70; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: modelData.material ? modelData.material.id : "no material" }
                }
            }
        }
        Txt { kind: "fine"; tone: 3; width: parent.width; visible: mr.printed
            text: "Taken as solid (100 % infill) and isotropic." + (mr.m && mr.m.slice_filament_g ? " The slicer's estimate for the print: " + F.fmt(mr.m.slice_filament_g, 1) + " g (simulated)." : " The slicer's grams are the print's.") }
    }
}
