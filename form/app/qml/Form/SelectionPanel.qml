import QtQuick
import QtQuick.Controls
import "F.js" as F

// The Annotate tool's readout: what is selected and what the engine computed for it, then the annotations kept on
// this design. A selection can be kept (named, with a note, saved with the revision) or sent to the agent with its
// numbers. It lives in the viewport's dock (top right); collapsed it is its header.
Rectangle {
    id: sp
    objectName: "selectionPanel"
    property bool collapsed: false
    property real maxHeight: 560
    property bool keeping: false
    signal toggled()
    readonly property var sel: Store.selection
    readonly property var items: sel ? sel.items : []
    readonly property var anns: Store.annotations
    readonly property int head: Store.project ? Store.project.head : 0
    // a flat face or a point on one, picked on the solid: where text can go (TextSheet.qml)
    readonly property var flat: {
        for (var i = 0; i < items.length; i++) { var x = items[i]
            if ((x.kind === "face" || x.kind === "point") && x.on && x.normal && x.curvature && x.curvature.kind === "flat") return x }
        return null
    }
    // picked edges and a flat face: what a fillet, a chamfer, a hole or a shell is made on (ModelPanel.qml)
    readonly property var edgePicks: items.filter(function (x) { return x.kind === "edge" && x.edge && x.edge.midpoint })
                                          .map(function (x) { return { at: x.edge.midpoint } })
    property string modelling: ""            // "edges" | "face" while the picked-feature panel is open
    width: 300; radius: Theme.rMd
    readonly property real footH: !!modelling && !collapsed && !keeping ? actFoot.implicitHeight + 18 : 0
    height: collapsed ? 36 : Math.min(maxHeight, 36 + col.implicitHeight + 12 + footH)
    color: Theme.alpha(Theme.plate1, 0.96); border.color: Theme.rule
    onItemsChanged: { if (!items.length) { keeping = false; modelling = "" } }

    function featLabel(id) { var f = Store.featureById(id); return f ? f.label : id || "" }
    function partLabel(id) {
        var ps = Store.assembly ? Store.assembly.parts : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i].label
        return ""
    }
    function lines(x) {                        // [title, numbers, where]
        var where = [featLabel(x.feature), partLabel(x.part)].filter(function (t) { return !!t }).join(" · ")
        if (x.kind === "region") {
            var w = x.wall_thickness_mm
            return ["Region · " + F.fmt(x.area_mm2, x.area_mm2 < 100 ? 1 : 0) + " mm²",
                    F.fmt(x.mean_tilt_deg, 0) + "° from up · " + Math.round(100 * (x.overhang_share || 0)) + "% overhang" + (w ? " · wall ≥ " + F.fmt(w.min, 2) : ""),
                    (x.features || []).slice(0, 3).map(function (f) { return sp.featLabel(f.feature) }).join(", ") + (x.height_range_mm ? " · " + F.fmt(x.height_range_mm[0], 1) + "–" + F.fmt(x.height_range_mm[1], 1) + " mm up" : "")]
        }
        var f = x.face || {}
        if (x.kind === "edge" && x.edge) {
            var e = x.edge
            return ["Edge · " + e.type + " · " + F.fmt(e.length_mm, 2) + " mm",
                    (e.diameter_mm ? "Ø " + F.fmt(e.diameter_mm, 2) + " · " : "") + (e.faces_angle_deg !== undefined ? (e.smooth ? "smooth · " : "faces at " + F.fmt(e.faces_angle_deg, 0) + "° · ") : "")
                        + (Math.abs(e.height_range_mm[1] - e.height_range_mm[0]) < 0.05 ? F.fmt(e.height_range_mm[0], 1) : F.fmt(e.height_range_mm[0], 1) + "–" + F.fmt(e.height_range_mm[1], 1)) + " mm up",
                    where]
        }
        var head = (x.kind === "face" ? "Face · " : "Point · ") + f.type + (x.kind === "face" ? " · " + F.fmt(f.area_mm2, f.area_mm2 < 100 ? 2 : 1) + " mm²" : "")
        var nums = F.fmt(x.tilt_deg, 0) + "° from up" + (x.overhang ? " (overhang)" : "") + " · wall " + (x.wall_thickness_mm !== null && x.wall_thickness_mm !== undefined ? F.fmt(x.wall_thickness_mm, 2) : "–")
            + (f.diameter_mm ? " · Ø " + F.fmt(f.diameter_mm, 2) : "") + " · " + F.fmt(x.height_above_bed_mm, 1) + " mm up"
        return [head, nums, where]
    }

    Item { id: hd; width: parent.width; height: 36
        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: Theme.rSm; color: hm.containsMouse ? Theme.washHover : "transparent" }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: sp.toggled() }
        Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 7; height: 7; radius: 3.5; color: Theme.annotate }
        Txt { kind: "cap"; x: 28; anchors.verticalCenter: parent.verticalCenter; text: "Selection"; wrapMode: Text.NoWrap }
        Row { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Spinner { size: 12; visible: Store.selBusy > 0; anchors.verticalCenter: parent.verticalCenter; color: Theme.annotate }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: (sp.items.length ? F.plural(sp.items.length, "item") : "") + (sp.items.length && sp.anns.length ? " · " : "") + (sp.anns.length ? sp.anns.length + " kept" : "") }
            Icon { name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter; rotation: sp.collapsed ? -90 : 0
                Behavior on rotation { NumberAnimation { duration: Motion.move(140); easing.type: Easing.OutCubic } } } }
    }

    Flickable {
        visible: !sp.collapsed
        y: 36; width: parent.width; height: parent.height - 36 - 2 - sp.footH
        contentHeight: col.implicitHeight + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 5 }
        Column {
            id: col; x: 14; width: parent.width - 28; spacing: 10

            // ── the live selection ──
            Txt { visible: !sp.items.length && Store.selecting && !sp.anns.length; kind: "fine"; tone: 2; width: parent.width
                text: "Pick a face, an edge or a point, or paint a region. Shift adds to the selection. The numbers are computed on the CAD solid." }
            Column {
                visible: sp.items.length > 0; width: parent.width; spacing: 0
                Repeater {
                    model: sp.items
                    Item { id: row
                        required property var modelData
                        required property int index
                        readonly property var ln: sp.lines(modelData)
                        objectName: "selItem"
                        width: parent.width; height: rc.implicitHeight + 12
                        Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Rectangle { y: 9; width: 16; height: 16; radius: 8; color: Theme.alpha(Theme.annotate, 0.18)
                            Txt { anchors.centerIn: parent; mono: true; font.pixelSize: 9; color: Theme.annotate; text: String(row.index + 1) } }
                        Column { id: rc; x: 24; y: 6; width: parent.width - 24 - 22; spacing: 2
                            Txt { font.pixelSize: 13; font.weight: 600; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: row.ln[0] }
                            Txt { kind: "fine"; tone: 2; mono: true; width: parent.width; text: row.ln[1] }
                            Txt { kind: "fine"; tone: 3; width: parent.width; visible: !!row.ln[2]; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: row.ln[2] } }
                        Btn { anchors.right: parent.right; anchors.rightMargin: -6; y: 4; small: true; kind: "quiet"; icon: "x"; tip: "Remove from the selection"; onClicked: Store.selRemove(row.index) }
                        Btn { anchors.right: parent.right; anchors.rightMargin: -6; y: 30; small: true; kind: "quiet"; icon: "scissors"; visible: !!row.modelData.on && row.modelData.kind !== "region"
                            tip: "Cut the part open through this point, to see the wall here in section"; onClicked: Store.cutThrough(row.modelData) }
                    }
                }
            }
            Txt { visible: !!sp.sel && !!sp.sel.summary && sp.items.length > 1; kind: "fine"; tone: 2; width: parent.width
                text: { var m = sp.sel ? sp.sel.summary : null; if (!m) return ""
                    var t = []
                    if (m.area_mm2) t.push(F.fmt(m.area_mm2, 1) + " mm² selected")
                    if (m.thinnest_wall_mm !== null && m.thinnest_wall_mm !== undefined) t.push("thinnest wall " + F.fmt(m.thinnest_wall_mm, 2) + " mm")
                    if (m.distance_mm !== undefined) t.push(F.fmt(m.distance_mm, 2) + " mm apart")
                    return t.join(" · ") } }
            Flow {
                visible: sp.items.length > 0 && !sp.keeping; width: parent.width; spacing: 6
                Btn { objectName: "askSelection"; small: true; kind: "primary"; icon: "sparkles"; text: "Ask the agent"
                    tip: "Puts this selection and its numbers in the conversation; add your question and send."
                    onClicked: Store.askAboutSelection(sp.sel.text, "") }
                Btn { objectName: "keepSelection"; small: true; icon: "map_pin_plus"; text: "Keep…"; tip: "Name it and keep it with " + F.pad(sp.head)
                    onClicked: { sp.keeping = true; Qt.callLater(function () { nameField.input.forceActiveFocus() }) } }
                Btn { objectName: "textHere"; small: true; icon: "type"; text: "Text here…"; visible: !!sp.flat
                    tip: "Raise or sink lettering on this flat face, as a feature of the design"
                    onClicked: Store.openSheet("text", { item: sp.flat }) }
                Btn { objectName: "featureHere"; small: true; icon: "wrench"; text: "Feature here…"; visible: !!sp.flat
                    tip: "A screw boss or a snap-fit hook on this flat face, as a feature of the design"
                    onClicked: Store.openSheet("feature", { item: sp.flat }) }
                Btn { objectName: "partHere"; small: true; icon: "wrench"; text: "Part here…"
                    visible: sp.items.some(function (x) { return !!x.on })
                    tip: "A screw, insert, bearing or other bought part on this hole or face: its hole is cut and its fit checked"
                    onClicked: Store.openSheet("parts", { item: sp.items.filter(function (x) { return !!x.on })[0] }) }
                Btn { objectName: "roundEdges"; small: true; icon: "radius"; text: "Fillet or chamfer…"; visible: sp.edgePicks.length > 0 && !sp.modelling
                    tip: "Round or bevel the picked edges, as a feature of the design"; onClicked: sp.modelling = "edges" }
                Btn { objectName: "holeHere"; small: true; icon: "circle_dot"; text: "Hole or shell…"; visible: !!sp.flat && !sp.modelling
                    tip: "A hole into this face to a standard size, or the part hollowed out and open here"; onClicked: sp.modelling = "face" }
                Btn { objectName: "sketchHere"; small: true; icon: "pen_tool"; text: "Sketch here…"; visible: !!sp.flat && !sp.modelling
                    tip: "Draw a profile on this face and extrude it from it or cut it into the part"
                    onClicked: Store.ppost("/sketch_plane", { at: sp.flat.on }).then(function (r) {
                        Store.openSheet("handsketch", { mode: "add", plane: r.plane, outline: r.outline }) }, function (e) { Store.fail(e) }) }
                Btn { small: true; kind: "quiet"; text: "Clear"; onClicked: Store.selClear() }
            }
            ModelPanel {
                id: modelPanel
                visible: !!sp.modelling && !sp.keeping; width: parent.width
                kinds: sp.modelling === "edges" ? ["fillet", "chamfer"] : sp.modelling === "face" ? ["hole", "shell"] : []
                picks: sp.modelling === "edges" ? sp.edgePicks : sp.flat ? [{ at: sp.flat.on }] : []
                onDone: sp.modelling = ""
                actionsHere: false
            }
            Column {
                visible: sp.keeping; width: parent.width; spacing: 6
                Field { id: nameField; objectName: "annName"; width: parent.width; placeholder: "Name, e.g. Hose slot edge"; onAccepted: keepBtn.clicked() }
                Field { id: noteField; objectName: "annNote"; width: parent.width; placeholder: "Note (optional)"; onAccepted: keepBtn.clicked() }
                Row { spacing: 6
                    Btn { id: keepBtn; objectName: "keepConfirm"; small: true; kind: "primary"; text: "Keep"
                        onClicked: { Store.keepSelection(nameField.text, noteField.text); nameField.text = ""; noteField.text = ""; sp.keeping = false } }
                    Btn { small: true; kind: "quiet"; text: "Cancel"; onClicked: sp.keeping = false } }
            }

            // ── kept on this design ──
            Rectangle { visible: sp.anns.length > 0 && (sp.items.length > 0 || sp.keeping); width: parent.width; height: 1; color: Theme.rule }
            Txt { visible: sp.anns.length > 0; kind: "cap"; text: "Kept on this design" }
            Column {
                visible: sp.anns.length > 0; width: parent.width; spacing: 2
                Repeater {
                    model: sp.anns
                    Rectangle { id: ar
                        required property var modelData
                        required property int index
                        readonly property bool on: !!Store.annFocus && Store.annFocus.id === modelData.id
                        readonly property bool old: modelData.rev !== sp.head
                        objectName: "annotation-" + modelData.id
                        width: parent.width; height: ac.implicitHeight + 14; radius: Theme.rSm
                        color: on ? Theme.plate3 : am.containsMouse ? Theme.washHover : "transparent"
                        Behavior on color { Tint {} }
                        MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: Store.focusAnnotation(ar.on ? null : ar.modelData) }
                        Rectangle { x: 6; y: 9; width: 18; height: 18; radius: 9; color: ar.on ? Theme.annotate : Theme.alpha(Theme.annotate, 0.18)
                            Txt { anchors.centerIn: parent; mono: true; font.pixelSize: 10; color: ar.on ? Theme.datumInk : Theme.annotate; text: String(ar.index + 1) } }
                        Column { id: ac; x: 32; y: 7; width: parent.width - 40; spacing: 3
                            Row { spacing: 6; width: parent.width
                                Txt { font.pixelSize: 13; font.weight: 600; text: ar.modelData.name; width: Math.min(implicitWidth, parent.width - rt.width - 6); elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                Tag { id: rt; text: F.pad(ar.modelData.rev) + (ar.old ? " · older" : ""); kind: ar.old ? "WARN" : "computed"; anchors.verticalCenter: parent.verticalCenter } }
                            Txt { kind: "fine"; tone: 2; width: parent.width; visible: !!ar.modelData.note; text: ar.modelData.note; maximumLineCount: ar.on ? 8 : 2; elide: Text.ElideRight }
                            // opened: the numbers, and what to do with it
                            Column { visible: ar.on; width: parent.width; spacing: 6
                                Txt { kind: "fine"; tone: 3; width: parent.width; visible: ar.old
                                    text: "Made on " + F.pad(ar.modelData.rev) + "; the head is " + F.pad(sp.head) + ". The overlay and numbers below are computed again on the head." }
                                Spinner { size: 12; color: Theme.annotate; visible: !(Store.annFocus && Store.annFocus.analysis) }
                                Repeater {
                                    model: Store.annFocus && Store.annFocus.analysis ? Store.annFocus.analysis.items : []
                                    Column { required property var modelData; required property int index
                                        readonly property var ln: sp.lines(modelData)
                                        width: parent.width; spacing: 1
                                        Txt { font.pixelSize: 12; font.weight: 600; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: (index + 1) + ". " + parent.ln[0] }
                                        Txt { kind: "fine"; tone: 2; mono: true; width: parent.width; text: parent.ln[1] } }
                                }
                                Flow { width: parent.width; spacing: 6
                                    Btn { objectName: "askAnnotation"; small: true; kind: "primary"; icon: "sparkles"; text: "Ask the agent"
                                        onClicked: Store.askAboutSelection(Store.annFocus && Store.annFocus.analysis ? Store.annFocus.analysis.text : ar.modelData.text,
                                                                           "the annotation “" + ar.modelData.name + "”" + (ar.modelData.note ? " (" + ar.modelData.note + ")" : "")) }
                                    Btn { small: true; kind: "quiet"; icon: "trash_2"; text: "Delete"; onClicked: Store.deleteAnnotation(ar.modelData.id) } }
                            }
                        }
                    }
                }
            }
            Txt { kind: "fine"; width: parent.width; visible: sp.items.length > 0 || sp.anns.length > 0
                text: "Computed on the CAD solid: wall thickness along the surface normal, tilt and heights in the print orientation." }
        }
    }
    // Preview and Add to design, pinned at the foot while a picked feature is open (ModelPanel's actions)
    Item {
        objectName: "modelFoot"; visible: sp.footH > 0
        anchors.bottom: parent.bottom; width: parent.width; height: sp.footH
        Rectangle { x: 14; width: parent.width - 28; height: 1; color: Theme.rule }
        Loader { id: actFoot; x: 14; y: 9; width: parent.width - 28; sourceComponent: sp.modelling ? modelPanel.actionRow : null }
    }
}
