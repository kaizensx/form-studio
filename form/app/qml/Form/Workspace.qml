import QtQuick
import QtQuick.Controls
import "F.js" as F

// A project: the part in the middle, the question being asked of it on the right.
Item {
    id: ws
    readonly property var d: Store.data
    function stageNote(id) {
        if (!d) return ["", ""]
        var roll = d.checks ? d.checks.rollup : null
        if (id === "brief") {
            var k = d.recipe.params.filter(function (p) { return p.group === "brief" })
            var m = k.filter(function (p) { var pv = Store.head.provenance[p.key]; return pv && pv.source === "measured" }).length
            return k.length ? [m + "/" + k.length + " measured", m === k.length ? "ok" : ""] : ["", ""]
        }
        if (id === "shape") return [Store.hasDraft ? "Draft open" : F.plural(d.recipe.features.length, "feature"), Store.hasDraft ? "draft" : ""]
        if (id === "fit") return d.fit ? [Math.round(d.fit.yield * 100) + "% modelled", d.fit.yield >= 0.95 ? "ok" : "warn"] : ["Calibration", ""]
        if (id === "prove") return !roll ? ["Not current", "warn"] : roll.FAIL ? [roll.FAIL + " failed", "fail"] : roll.WARN ? [roll.WARN + " to review", "warn"] : ["All pass", "ok"]
        if (id === "release") return d.approval.state === "approved" ? ["Released", "ok"] : d.gate.ready ? ["Ready to approve", ""] : ["Not ready", ""]
        return ["", ""]
    }
    function noteColor(c) { return c === "ok" ? Theme.pass : c === "warn" ? Theme.amber : c === "fail" ? Theme.signal : c === "draft" ? Theme.blueprint : Theme.ink3 }

    // ── centre: the part ─────────────────────────────────────
    Item {
        id: centre
        anchors.left: parent.left; anchors.right: insp.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        Viewport {
            id: vp
            anchors.fill: parent
            visible: !Store.layers
            asmMode: Store.asmMode; explode: Store.explode; pose: Store.pose
            Component.onCompleted: { Store.viewer = vp; if (Store.view) { Store.showHead(); vp.setView("iso", false) } }
            Component.onDestruction: if (Store.viewer === vp) Store.viewer = null
            onPicked: function (f) { Store.pick(f) }
            onHoveredFeature: function (f, x, y) { chip.feat = Store.featureById(f); chip.x = x + 14; chip.y = y + 14 }
            // analysis maps and measuring (maps describe the committed revision, so a draft hides them)
            analysis: Store.hasDraft || Store.compare ? null : Store.analysis
            measuring: Store.measuring; measures: Store.measures; measureFrom: Store.measureFrom
            onProbed: function (at, reach) { Store.measureClick(at, reach) }
            onHoveredValue: function (v, x, y, on) { vchip.on = on; vchip.v = v; vchip.x = x + 14; vchip.y = y + 14 }
        }
        Loader { anchors.fill: parent; active: !!Store.layers; source: "LayerView.qml" }
        // soft vignette so the plate falls away at the edges
        Rectangle { anchors.fill: parent; visible: !Store.layers
            gradient: Gradient { orientation: Gradient.Vertical
                GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.55) } GradientStop { position: 0.18; color: "transparent" }
                GradientStop { position: 0.8; color: "transparent" } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.7) } } }

        Rectangle { id: chip; property var feat: null; visible: !!feat && !Store.layers; z: 5
            width: ct.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.plate3; border.color: Theme.rule2
            Row { id: ct; anchors.centerIn: parent; spacing: 6
                Txt { text: chip.feat ? chip.feat.label : ""; font.pixelSize: 12; font.weight: 550 }
                Txt { text: chip.feat ? chip.feat.role : ""; kind: "fine" } } }

        // the map's value under the pointer
        Rectangle { id: vchip; property bool on: false; property real v: 0; z: 5
            readonly property var lg: Store.analysis ? Store.analysis.legend : null
            readonly property string say: !lg ? "" : isNaN(v) ? (lg.none || "") : String(lg.hover || "{v}").replace("{v}", F.fmt(v, Store.analysisMap === "thickness" || Store.analysisMap === "features" ? 2 : Store.analysisMap === "overhang" ? 0 : 0))
            visible: on && !Store.layers && say !== "" && !!vp.analysis
            width: vt.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.plate3; border.color: Theme.rule2
            Txt { id: vt; anchors.centerIn: parent; mono: true; font.pixelSize: 12; text: vchip.say; wrapMode: Text.NoWrap } }

        // HUD — top left: analyze and measure
        Column { id: tools; x: 16; spacing: 8; visible: !Store.layers && !!Store.view
            y: centre.width >= 1010 ? 14 : Store.assembly ? 82 : 48          // a narrow viewport: under the view controls
            Row { spacing: 8
                Seg { model: Store.analysisMaps; value: Store.analysisMap; onPicked: function (v) { Store.setAnalysis(v === Store.analysisMap ? "" : v) } }
                Btn { small: true; kind: "quiet"; active: Store.measuring; icon: "pencil_ruler"; height: 26; width: 30
                    tip: "Measure distances, faces and hole diameters (M). Values are computed from the part’s surface, tessellated at 0.05 mm; a hole diameter is exact when it comes from the CAD solid."
                    onClicked: Store.setMeasuring(!Store.measuring) } }
            Rectangle { visible: !!Store.analysisMap && (Store.hasDraft || !!Store.compare); width: mh.implicitWidth + 20; height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.amber, 0.12); border.color: Theme.alpha(Theme.amber, 0.3)
                Txt { id: mh; anchors.centerIn: parent; font.pixelSize: 12; color: Qt.lighter(Theme.amber, 1.3)
                    text: "The map describes " + (Store.project ? F.pad(Store.project.head) : "the head") + ". " + (Store.hasDraft ? "Commit or discard the draft to see it." : "Stop comparing to see it.") } }
            MeasurePanel { visible: Store.measureOpen } }
        AnalysisLegend { anchors.right: parent.right; anchors.rightMargin: 16; anchors.bottom: pipe.top; anchors.bottomMargin: 46; z: 4
            visible: !Store.layers && !!Store.analysisMap && !(Store.hasDraft || !!Store.compare)
            map: Store.analysis; busy: Store.analysisBusy; pending: Store.analysisLabel(Store.analysisMap); check: Store.analysis ? Store.analysisCheck() : null
            opacity: visible ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base; easing.type: Easing.OutCubic } } }
        Shortcut { sequence: "M"; enabled: !Store.sheet && !Store.paletteOpen && !Store.layers; onActivated: Store.setMeasuring(!Store.measuring) }

        // HUD — top left: state banners
        Column { x: 16; y: tools.y + 34; spacing: 6; visible: !Store.layers && !Store.measureOpen && !(Store.analysisMap && (Store.hasDraft || Store.compare))
            Rectangle { visible: Store.hasDraft && !!Store.preview; width: b1.implicitWidth + 20; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b1; anchors.centerIn: parent; font.pixelSize: 12; color: "#cdd9ff"
                    text: "Draft, not committed · blue lines are " + (Store.project ? F.pad(Store.project.head) : "") } }
            Rectangle { visible: !!Store.compare; width: b2.implicitWidth + 20; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b2; anchors.centerIn: parent; font.pixelSize: 12; color: "#cdd9ff"
                    text: Store.compare ? "Comparing · solid is " + F.pad(Store.project.head) + " (head), blue lines are " + F.pad(Store.compare.rev) : "" } } }
        // HUD — top right: views and section
        Row { anchors.right: parent.right; anchors.rightMargin: 16; y: 14; spacing: 8; visible: !Store.layers
            Rectangle { visible: !!Store.sectionNow(); width: 150; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
                Beam { anchors.centerIn: parent; width: parent.width - 20; from: 0.02; to: 0.98; step: 0.01
                    value: Store.section && Store.section.axis ? Store.section.t : (Store.sectionNow() ? Store.sectionNow().t : 0.5)
                    onMoved: function (v) { var s = Store.sectionNow(); Store.setSection(s ? s.axis : "y", v) } } }
            Seg { model: [{ value: "x", text: "Cut X" }, { value: "y", text: "Cut Y" }, { value: "z", text: "Cut Z" }]
                value: Store.sectionNow() ? Store.sectionNow().axis : ""
                onPicked: function (v) { var s = Store.sectionNow(); Store.setSection(s && s.axis === v ? "" : v, 0.5) } }
            Seg { model: ["iso", "front", "side", "top", "under"]; value: Store.viewName; onPicked: function (v) { Store.setView(v) } } }
        // HUD — top right, second row: assembly (only for designs that declare how their parts go together)
        Row { anchors.right: parent.right; anchors.rightMargin: 16; y: 48; spacing: 8; visible: !Store.layers && !!Store.assembly
            Repeater { model: Store.assembly && Store.asmMode !== "print" ? Store.assembly.joints : []
                Rectangle { id: jr; required property var modelData
                    readonly property string unit: modelData.kind === "hinge" ? "°" : " mm"
                    readonly property real val: Store.pose[modelData.id] || 0
                    width: jl.implicitWidth + 150; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
                    Txt { id: jl; x: 10; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap
                        text: jr.modelData.label + " " + Math.round(jr.val) + jr.unit }
                    Beam { x: jl.implicitWidth + 18; width: 120; anchors.verticalCenter: parent.verticalCenter
                        from: jr.modelData.range[0]; to: jr.modelData.range[1]; step: 1; value: jr.val; base: 0
                        onMoved: function (v) { Store.setPose(jr.modelData.id, v) } } } }
            Rectangle { visible: Store.asmMode === "exploded"; width: el.implicitWidth + 150; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
                Txt { id: el; x: 10; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; text: "Spread"; wrapMode: Text.NoWrap }
                Beam { x: el.implicitWidth + 18; width: 120; anchors.verticalCenter: parent.verticalCenter; from: 0; to: 1.6; step: 0.05; value: Store.explode; base: 1
                    onMoved: function (v) { Store.setExplode(v) } } }
            Seg { model: [{ value: "assembled", text: "Assembled" }, { value: "exploded", text: "Exploded" }, { value: "print", text: "Print layout" }]
                value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) } } }
        // HUD — bottom left: what you are looking at
        Row { x: 16; anchors.bottom: pipe.top; anchors.bottomMargin: 12; spacing: 8; visible: !Store.layers && !!Store.shown
            Rectangle { width: ro.implicitWidth + 20; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
                Row { id: ro; anchors.centerIn: parent; spacing: 8
                    Txt { mono: true; font.pixelSize: 12
                        readonly property var bb: Store.assembly && Store.asmMode === "assembled" ? Store.assembly.bbox : (Store.shown ? Store.shown.bbox : null)
                        text: bb ? F.fmt(bb[1][0] - bb[0][0], 1) + " × " + F.fmt(bb[1][1] - bb[0][1], 1) + " × " + F.fmt(bb[1][2] - bb[0][2], 1) + " mm" : "" }
                    Txt { text: "·"; tone: 4 }
                    Txt { mono: true; font.pixelSize: 12; text: Store.shown ? F.fmt(Store.shown.volume_mm3 / 1000, 1) + " cm³" : "" }
                    Txt { text: "·"; tone: 4 }
                    Txt { font.pixelSize: 12; tone: 3; text: Store.assembly && Store.asmMode === "assembled" ? "assembled" : Store.assembly && Store.asmMode === "exploded" ? "as printed" : "plate 180 × 180" } } }
            Btn { small: true; kind: "quiet"; active: Store.dims; icon: "ruler"; tip: "Overall dimensions"; onClicked: Store.toggleDims() }
            Btn { small: true; kind: "quiet"; active: Store.companions; icon: "box"; tip: "Show what the part holds"
                visible: !!(Store.shown && Store.shown.companions && Store.shown.companions.length); onClicked: Store.toggleCompanions() }
            Btn { small: true; kind: "quiet"; icon: "camera"; text: "Photo"; tip: "Render the current revision in Blender (an illustration)"
                enabled: !Store.hasDraft; onClicked: Store.openSheet("render") } }

        Pipeline { id: pipe; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 12 }
    }

    // ── right: the stage inspector ───────────────────────────
    Rectangle {
        id: insp
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 400
        color: Theme.plate1
        Rectangle { width: 1; height: parent.height; color: Theme.rule }
        // stage tabs
        Row { id: tabs; x: 8; y: 6; width: parent.width - 16; height: 52
            Repeater {
                model: Store.stages
                Item {
                    id: tab
                    required property var modelData
                    required property int index
                    readonly property bool on: Store.stage === modelData.id
                    readonly property var note: ws.stageNote(modelData.id)
                    width: tabs.width / 5; height: tabs.height
                    Rectangle { anchors.fill: parent; anchors.margins: 2; radius: Theme.rMd; color: tab.on ? Theme.plate3 : tm.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.fast } } }
                    Column { anchors.centerIn: parent; spacing: 2
                        Row { spacing: 5; anchors.horizontalCenter: parent.horizontalCenter
                            Txt { mono: true; font.pixelSize: 10; tone: 4; text: "0" + (tab.index + 1); anchors.baseline: tl.baseline }
                            Txt { id: tl; text: tab.modelData.title; font.weight: 600; font.pixelSize: 13; tone: tab.on ? 1 : 2 } }
                        Txt { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 10; text: tab.note[0]; color: ws.noteColor(tab.note[1]); wrapMode: Text.NoWrap } }
                    MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.setStage(tab.modelData.id) }
                    Tip { show: tm.containsMouse; text: tab.modelData.hint }
                }
            }
        }
        Rectangle { anchors.top: tabs.bottom; anchors.topMargin: 5; width: parent.width; height: 1; color: Theme.rule }
        Flickable {
            id: scroll
            objectName: "inspector"
            anchors.top: tabs.bottom; anchors.topMargin: 6; anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            contentHeight: body.implicitHeight + 40; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            Column {
                id: body; x: 20; y: 6; width: parent.width - 40; spacing: 14
                Loader { id: panel; width: parent.width; active: !!Store.data
                    source: ({ brief: "Brief.qml", shape: "Shape.qml", fit: "Fit.qml", prove: "Prove.qml", release: "Release.qml" })[Store.stage]
                    onLoaded: { scroll.contentY = 0; fadeIn.restart() }
                    NumberAnimation { id: fadeIn; target: panel; property: "opacity"; from: 0; to: 1; duration: 180; easing.type: Easing.OutCubic } }
                DraftCard { width: parent.width }
            }
        }
    }
}
