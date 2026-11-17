import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "F.js" as F
import "." as Tools      // Timeline and ContextMenu are also Qt type names; qualify ours

// A project: the part in the middle, the question being asked of it on the right.
//
// The viewport has one tool system. A rail on its left edge holds the tools (one active at a time), the things
// that open elsewhere (print simulation, photo render) and what the view shows. The active tool's options sit
// beside the rail and nowhere else. Legends and measurements dock top right and fold to their header. The readout
// is one quiet line bottom left; notices about what is on screen stack above it. The bottom strip is the pipeline
// ("now") with the revision timeline ("history") as a second row when asked for. The camera is told how much of
// the view these cover and keeps the part in the rest.
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
        if (id === "release") return d.approval.state === "approved" ? ["Released", "ok"] : d.gate.ready ? ["Ready", ""] : ["Not ready", ""]
        return ["", ""]
    }
    function noteColor(c) { return c === "ok" ? Theme.pass : c === "warn" ? Theme.amber : c === "fail" ? Theme.signal : c === "draft" ? Theme.blueprint : Theme.ink3 }
    // the stage's status, as one sentence under the tabs
    function stageSay(id) {
        if (!d || !Store.head) return ["", ""]
        var head = F.pad(d.project.head), roll = d.checks ? d.checks.rollup : null
        if (id === "brief") {
            var k = d.recipe.params.filter(function (p) { return p.group === "brief" })
            var m = k.filter(function (p) { var pv = Store.head.provenance[p.key]; return pv && pv.source === "measured" }).length
            return !k.length ? ["What it is for, and what is known about the things it must fit.", ""]
                : m === k.length ? ["Every dimension of the object is measured.", "ok"]
                : ["Anything not measured is carried as an assumption, all the way to release.", m ? "" : "warn"]
        }
        if (id === "shape") {
            var ft = Store.featureById(Store.feature), n = F.keys(Store.draftValues).length
            if (Store.hasDraft) return ["Draft open: " + F.plural(n, "parameter") + " changed, not committed.", "draft"]
            return ft ? ["Editing one feature of " + head + ". Changes rebuild the solid as a draft.", ""]
                : [F.plural(d.recipe.features.length, "feature") + " in build order. Select one here or on the model to change it.", ""]
        }
        if (id === "fit") return d.fit ? [Math.round(d.fit.yield * 100) + "% of prints are modelled to fit, from what is known today.", d.fit.yield >= 0.95 ? "ok" : "warn"]
            : ["How accurate this printer is on this profile.", ""]
        if (id === "prove") {
            if (!roll) return ["The checks do not describe " + head + " yet.", "warn"]
            var all = roll.PASS + roll.WARN + roll.FAIL
            return roll.FAIL ? [F.plural(roll.FAIL, "check") + " of " + all + " failed for " + head + ".", "fail"]
                : roll.WARN ? [F.plural(roll.WARN, "check") + " of " + all + " " + (roll.WARN === 1 ? "needs" : "need") + " a look for " + head + ". None failed.", "warn"]
                : ["All " + all + " checks pass for " + head + ".", "ok"]
        }
        if (id === "release") return d.approval.state === "approved" ? [F.pad(d.approval.rev) + " is released.", "ok"]
            : d.gate.ready ? [head + " is ready to approve." + (d.gate.warnings && d.gate.warnings.length ? " " + F.plural(d.gate.warnings.length, "warning") + " to acknowledge first." : ""), ""]
            : [head + " is not ready to release.", "warn"]
        return ["", ""]
    }

    // ── tools ────────────────────────────────────────────────
    readonly property string tool: Ws.tool
    readonly property bool compact: centre.width < 640              // a narrow viewport: controls shorten, docks fold
    readonly property bool sim: !!Store.layers
    readonly property bool mapBlocked: !!Store.analysisMap && (Store.hasDraft || !!Store.compare)
    function setTool(t) {
        if (ws.sim) Store.showLayers(false)
        if (t === Ws.tool && t !== "select") t = "select"           // the active tool, clicked again, hands back to Select
        var was = Ws.tool
        if (was === t) return
        Ws.tool = t
        if (was === "measure") Store.setMeasuring(false)
        if (was === "history") { Store.timelineOpen = false; Store.endScrub() }
        if (t === "measure") Store.setMeasuring(true)
        if (t === "history") Store.timelineOpen = true
        if (t === "section" && !Store.sectionNow()) Store.setSection("y", 0.5)
    }
    // the store can change these from the palette, a key, a check's marker or Esc: the rail follows
    Connections {
        target: Store
        function onMeasuringChanged() { if (Store.measuring) Ws.tool = "measure"; else if (Ws.tool === "measure") Ws.tool = "select" }
        function onTimelineOpenChanged() { if (Store.timelineOpen) Ws.tool = "history"; else if (Ws.tool === "history") Ws.tool = "select" }
        function onSectionChanged() {
            var on = !!(Store.section && Store.section.axis)
            if (on && Ws.tool === "select") Ws.tool = "section"; else if (!on && Ws.tool === "section") Ws.tool = "select"
        }
        function onAnalysisMapChanged() { if (Store.analysisMap && Ws.tool === "select") Ws.tool = "analyze" }
        function onAsmModeChanged() { if (Store.asmMode !== "print" && Ws.tool === "select" && Store.assembly) Ws.tool = "assembly" }
        function onPidChanged() { Ws.tool = "select" }
        function onFadeTo(apply) { vp.swap(apply) }                 // the timeline and anything else that swaps the geometry
    }
    Component.onCompleted: Ws.tool = Store.measuring ? "measure" : Store.timelineOpen ? "history" : "select"

    readonly property Item focusItem: Window.activeFocusItem
    readonly property bool keys: Store.screen === "work" && !Store.sheet && !Store.paletteOpen && !(focusItem && focusItem.cursorPosition !== undefined)
    Shortcut { sequence: "V"; enabled: ws.keys; onActivated: ws.setTool("select") }
    Shortcut { sequence: "M"; enabled: ws.keys; onActivated: ws.setTool("measure") }
    Shortcut { sequence: "A"; enabled: ws.keys; onActivated: ws.setTool("analyze") }
    Shortcut { sequence: "E"; enabled: ws.keys && !!Store.assembly; onActivated: ws.setTool("assembly") }
    Shortcut { sequence: "T"; enabled: ws.keys; onActivated: ws.setTool("history") }

    // ── centre: the part ─────────────────────────────────────
    Item {
        id: centre
        anchors.left: parent.left; anchors.right: insp.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        Viewport {
            id: vp
            objectName: "viewport"
            anchors.fill: parent
            visible: !Store.layers
            asmMode: Store.asmMode; explode: Store.explode; pose: Store.pose
            hiddenFeatures: Store.hidden                                             // design tools: quick actions
            // what the HUD covers: the rail and options, the dock when it is open, the strip and the readout
            insetLeft: ws.compact ? 76 : 60; insetTop: 46
            insetRight: dock.open && !ws.compact ? dock.width + 20 : 0
            insetBottom: centre.height - strip.y + 30
            onContextRequested: function (f, x, y) { Store.ctxMenu = { feature: f, x: x, y: y } }
            Component.onCompleted: { Store.viewer = vp; if (Store.view) { Store.showHead(); vp.setView("iso", false) }; glide.start() }
            Component.onDestruction: if (Store.viewer === vp) Store.viewer = null
            Timer { id: glide; interval: 400; onTriggered: vp.insetGlide = true }
            onPicked: function (f) { Store.pick(f) }
            onHoveredFeature: function (f, x, y) { chip.feat = Store.featureById(f); chip.x = Math.min(x + 14, centre.width - chip.width - 8); chip.y = y + 14 }
            // analysis maps and measuring (maps describe the committed revision, so a draft hides them)
            analysis: Store.hasDraft || Store.compare ? null : Store.analysis
            measuring: Store.measuring; measures: Store.measures; measureFrom: Store.measureFrom
            onProbed: function (at, reach) { Store.measureClick(at, reach) }
            onHoveredValue: function (v, x, y, on) { vchip.on = on; vchip.v = v; vchip.x = Math.min(x + 14, centre.width - vchip.width - 8); vchip.y = y + 14 }
        }
        Loader { id: lv; anchors.fill: parent; active: !!Store.layers; source: "LayerView.qml"
            onLoaded: { item.leftInset = 56; item.stripHeight = Qt.binding(function () { return strip.height + 12 }) } }
        // soft vignette so the bench falls away towards the top and under the strip
        Rectangle { anchors.fill: parent; visible: !Store.layers
            gradient: Gradient { orientation: Gradient.Vertical
                GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.5) } GradientStop { position: 0.16; color: "transparent" }
                GradientStop { position: 0.82; color: "transparent" } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.75) } } }

        // what is under the pointer: appears at once, no delay
        Rectangle { id: chip; property var feat: null; visible: !!feat && !Store.layers; z: 5
            width: ct.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.plate3; border.color: Theme.rule2
            Row { id: ct; anchors.centerIn: parent; spacing: 6
                Txt { text: chip.feat ? chip.feat.label : ""; font.pixelSize: 12; font.weight: 550 }
                Txt { text: chip.feat ? chip.feat.role : ""; kind: "fine" } } }
        // the map's value under the pointer
        Rectangle { id: vchip; property bool on: false; property real v: 0; z: 5
            readonly property var lg: Store.analysis ? Store.analysis.legend : null
            readonly property string say: !lg ? "" : isNaN(v) ? (lg.none || "") : String(lg.hover || "{v}").replace("{v}", F.fmt(v, Store.analysisMap === "thickness" || Store.analysisMap === "features" ? 2 : 0))
            visible: on && !Store.layers && say !== "" && !!vp.analysis
            width: vt.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.plate3; border.color: Theme.rule2
            Txt { id: vt; anchors.centerIn: parent; mono: true; font.pixelSize: 12; text: vchip.say; wrapMode: Text.NoWrap } }

        // ── the rail ─────────────────────────────────────────
        Rectangle {
            id: rail
            x: 12; y: 12; z: 6; width: 40; height: railCol.implicitHeight + 8; radius: Theme.rMd
            color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.rule
            visible: !!Store.view
            Column {
                id: railCol; x: 4; y: 4; spacing: 1
                RailBtn { icon: "rotate_3d"; label: "Select"; keys: "V"; hint: "Click a feature to edit it. Drag to orbit, shift-drag to pan."
                    active: ws.tool === "select" && !ws.sim; onClicked: ws.setTool("select") }
                RailBtn { icon: "pencil_ruler"; label: "Measure"; keys: "M"; hint: "Distances, faces and hole diameters, computed from the part’s surface."
                    active: ws.tool === "measure" && !ws.sim; marked: Store.measures.length > 0; onClicked: ws.setTool("measure") }
                RailBtn { icon: "scissors"; label: "Section"; keys: "X"; hint: "Cut the part open along X, Y or Z."
                    active: ws.tool === "section" && !ws.sim; marked: !!Store.sectionNow(); onClicked: ws.setTool("section") }
                RailBtn { icon: "scan_line"; label: "Analyze"; keys: "A"; hint: "Colour the part by wall thickness, overhang, section area or small features."
                    active: ws.tool === "analyze" && !ws.sim; marked: !!Store.analysisMap; onClicked: ws.setTool("analyze") }
                RailBtn { icon: "boxes"; label: "Assembly"; keys: "E"; hint: "Assembled, exploded or as printed. Move the joints."
                    visible: !!Store.assembly
                    active: ws.tool === "assembly" && !ws.sim; marked: Store.asmMode !== "print"; onClicked: ws.setTool("assembly") }
                RailBtn { icon: "history"; label: "History"; keys: "T"; hint: "Scrub through the revisions. Looking changes nothing."
                    active: ws.tool === "history" && !ws.sim; marked: !!Store.scrub; onClicked: ws.setTool("history") }
                Item { width: 32; height: 9; Rectangle { x: 6; y: 4; width: 20; height: 1; color: Theme.rule2 } }
                RailBtn { icon: "layers"; label: "Simulate the print"; hint: ws.d && ws.d.slice ? "Play the slicer’s toolpaths. Simulated, not a print." : "Needs a current slice of this revision."
                    enabled: !!ws.d && !!ws.d.slice; active: ws.sim
                    onClicked: { if (ws.sim) Store.showLayers(false); else Store.simulate({ at: 0, play: true }) } }
                RailBtn { icon: "camera"; label: "Photo render"; hint: Store.hasDraft ? "Commit or discard the draft first." : "Render the current revision in Blender (an illustration)."
                    enabled: !Store.hasDraft; onClicked: Store.openSheet("render") }
                Item { width: 32; height: 9; Rectangle { x: 6; y: 4; width: 20; height: 1; color: Theme.rule2 } }
                RailBtn { icon: "maximize_2"; label: Store.feature ? "Frame the selection" : "Frame the part"; keys: "F"; enabled: !ws.sim
                    onClicked: Store.frameSelection() }
                RailBtn { icon: "ruler"; toggle: true; label: Store.dims ? "Hide overall dimensions" : "Show overall dimensions"; active: Store.dims; enabled: !ws.sim; onClicked: Store.toggleDims() }
                RailBtn { icon: "box"; toggle: true; label: Store.companions ? "Hide what the part holds" : "Show what the part holds"; hint: "The object or reference part, drawn in blueprint."
                    visible: !!(Store.shown && Store.shown.companions && Store.shown.companions.length)
                    active: vp.showCompanions; enabled: !ws.sim; onClicked: Store.toggleCompanions() }
            }
        }

        // ── options of the active tool (one place, one row) ──
        Item {
            id: opts
            x: 60; y: 14; z: 5; visible: !ws.sim && !!Store.view
            readonly property real room: Math.max(160, centre.width - 60 - 12 - viewCtl.width - 12)
            height: Math.max(sectionBar.shown ? sectionBar.height : 0, analyzeBar.shown ? analyzeBar.height : 0,
                             measureBar.shown ? measureBar.height : 0, asmBar.shown ? asmBar.height : 0)

            HudBar { id: measureBar; objectName: "measureBar"; shown: ws.tool === "measure"; maxWidth: opts.room
                Seg { model: [{ value: "distance", text: "Distance" }, { value: "face", text: "Face" }, { value: "diameter", text: "Diameter" }]
                    value: Store.measureKind
                    onPicked: function (v) { Store.measureKind = v; Store.measureFrom = null } }
                Rectangle { height: 26; width: Math.min(mh.implicitWidth + 20, opts.room); radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.9); border.color: Theme.rule
                    Txt { id: mh; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        text: Store.measureKind === "distance" ? (Store.measureFrom ? "Click the second point" : ws.compact ? "Click two points; they snap" : "Click two points. They snap to corners, edge midpoints and face centres")
                            : Store.measureKind === "face" ? (ws.compact ? "Click a face: area and tilt" : "Click a face for its area and its tilt to the bed")
                            : ws.compact ? "Click a hole or round boss" : "Click the wall or rim of a hole or round boss" }
                    MouseArea { id: mhm; anchors.fill: parent; hoverEnabled: true }
                    Tip { show: mhm.containsMouse; text: "Values are computed from the part’s surface, tessellated at 0.05 mm; a hole diameter is exact when it comes from the CAD solid. Points snap to corners, edge midpoints and face centres when close." } }
                Btn { small: true; height: 26; text: "Clear"; visible: Store.measures.length > 0 || !!Store.measureFrom; onClicked: Store.clearMeasures() }
            }
            HudBar { id: sectionBar; objectName: "sectionBar"; shown: ws.tool === "section"; maxWidth: opts.room
                readonly property var now: Store.sectionNow()
                Seg { model: [{ value: "x", text: "X" }, { value: "y", text: "Y" }, { value: "z", text: "Z" }]
                    value: sectionBar.now ? sectionBar.now.axis : ""
                    onPicked: function (v) { Store.setSection(v, sectionBar.now && sectionBar.now.axis === v ? sectionBar.now.t : 0.5) } }
                HudSlider { label: "Position"; from: 0.02; to: 0.98; step: 0.01; percent: true; visible: !!sectionBar.now
                    value: sectionBar.now ? sectionBar.now.t : 0.5
                    onMoved: function (v) { Store.setSection(sectionBar.now ? sectionBar.now.axis : "y", v) } }
                Btn { small: true; height: 26; text: "Remove cut"; visible: !!sectionBar.now; onClicked: Store.setSection("", 0.5) }
            }
            HudBar { id: analyzeBar; objectName: "analyzeBar"; shown: ws.tool === "analyze"; maxWidth: opts.room
                Seg { visible: !ws.compact; model: Store.analysisMaps.slice(1); value: Store.analysisMap
                    onPicked: function (v) { Store.setAnalysis(v === Store.analysisMap ? "" : v) } }
                Pick { visible: ws.compact; width: 150; height: 26; model: Store.analysisMaps; value: Store.analysisMap; onPicked: function (v) { Store.setAnalysis(v) } }
                Btn { small: true; height: 26; text: "Clear map"; visible: !!Store.analysisMap && !ws.compact; onClicked: Store.setAnalysis("") }
            }
            HudBar { id: asmBar; objectName: "asmBar"; shown: ws.tool === "assembly" && !!Store.assembly; maxWidth: opts.room
                Seg { visible: !ws.compact; model: [{ value: "assembled", text: "Assembled" }, { value: "exploded", text: "Exploded" }, { value: "print", text: "Print layout" }]
                    value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) } }
                Pick { visible: ws.compact; width: 150; height: 26; value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) }
                    model: [{ value: "assembled", text: "Assembled" }, { value: "exploded", text: "Exploded" }, { value: "print", text: "Print layout" }] }
                HudSlider { visible: Store.asmMode === "exploded"; label: "Spread"; from: 0; to: 1.6; step: 0.05; base: 1; percent: true
                    value: Store.explode; onMoved: function (v) { Store.setExplode(v) } }
                Repeater { model: Store.assembly && Store.asmMode !== "print" ? Store.assembly.joints : []
                    HudSlider { required property var modelData
                        label: modelData.label; unit: modelData.kind === "hinge" ? "°" : " mm"
                        from: modelData.range[0]; to: modelData.range[1]; step: 1; base: 0
                        value: Store.pose[modelData.id] || 0
                        onMoved: function (v) { Store.setPose(modelData.id, v) } } }
            }
        }

        // ── top right: where you look from ───────────────────
        Item {
            id: viewCtl
            anchors.right: parent.right; anchors.rightMargin: 12; y: 14; z: 5; visible: !ws.sim && !!Store.view
            width: ws.compact ? cyc.width : vseg.width; height: 26
            readonly property var names: [{ value: "iso", text: "Iso" }, { value: "front", text: "Front" }, { value: "side", text: "Side" }, { value: "top", text: "Top" }, { value: "under", text: "Under" }]
            Seg { id: vseg; visible: !ws.compact; model: viewCtl.names; value: Store.viewName; onPicked: function (v) { Store.setView(v) } }
            Btn { id: cyc; visible: ws.compact; small: true; height: 26; icon: "move_3d"; tip: "Next view (keys 1 to 5)"
                text: Store.viewName.charAt(0).toUpperCase() + Store.viewName.slice(1)
                onClicked: { var o = ["iso", "front", "side", "top", "under"]; Store.setView(o[(o.indexOf(Store.viewName) + 1) % o.length]) } }
        }

        // ── the dock: legends and readouts, top right, never over the middle of the part ──
        Column {
            id: dock
            anchors.right: parent.right; anchors.rightMargin: 12; y: 48; z: 4; spacing: 8; visible: !ws.sim
            readonly property bool folded: Ws.dockTouched ? Ws.dockCollapsed : ws.compact
            readonly property bool showMap: !!Store.analysisMap && !ws.mapBlocked
            readonly property bool showMeasures: Store.measures.length > 0
            readonly property bool open: (showMap || showMeasures) && !folded
            readonly property real room: Math.max(120, strip.y - y - 46)
            function flip() { var now = folded; Ws.dockTouched = true; Ws.dockCollapsed = !now }
            AnalysisLegend { objectName: "analysisLegend"; visible: opacity > 0.01; opacity: dock.showMap ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.ui; easing.type: Easing.OutCubic } }
                map: Store.analysis; busy: Store.analysisBusy; pending: Store.analysisLabel(Store.analysisMap); check: Store.analysis ? Store.analysisCheck() : null
                collapsed: dock.folded || (dock.showMeasures && ws.tool === "measure")
                maxHeight: dock.room - (dock.showMeasures ? 44 : 0); onToggled: dock.flip() }
            MeasurePanel { objectName: "measurePanel"; visible: dock.showMeasures
                collapsed: dock.folded || (dock.showMap && ws.tool !== "measure")
                maxHeight: dock.room - (dock.showMap ? 44 : 0); onToggled: dock.flip() }
        }

        // ── bottom left: what you are looking at ─────────────
        Column {
            id: status
            x: 16; anchors.bottom: strip.top; anchors.bottomMargin: 10; z: 4; spacing: 6; visible: !ws.sim && !!Store.shown
            // notices: the picture is not simply "the head revision"
            Rectangle { visible: !!Store.scrub; width: sn.implicitWidth + 16; height: 28; radius: Theme.rSm
                color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.alpha(Theme.blueprint, 0.4)
                Row { id: sn; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Txt { mono: true; font.pixelSize: 12; color: Theme.blueprint; text: Store.scrub ? F.pad(Store.scrub.rev) : ""; anchors.verticalCenter: parent.verticalCenter }
                    Txt { font.pixelSize: 12; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                        text: Store.morphing ? "Playing the history · head is " + (Store.project ? F.pad(Store.project.head) : "") : "Viewing only · head is still " + (Store.project ? F.pad(Store.project.head) : "") }
                    Btn { small: true; kind: "quiet"; text: "Back to head"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.endScrub() } } }
            Rectangle { visible: Store.hasDraft && !!Store.preview && !Store.scrub; width: b1.implicitWidth + 20; height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b1; anchors.centerIn: parent; font.pixelSize: 12; color: Qt.lighter(Theme.blueprint, 1.25); wrapMode: Text.NoWrap
                    text: "Draft, not committed · blue lines are " + (Store.project ? F.pad(Store.project.head) : "") } }
            Rectangle { visible: !!Store.compare; width: b2.implicitWidth + 20; height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b2; anchors.centerIn: parent; font.pixelSize: 12; color: Qt.lighter(Theme.blueprint, 1.25); wrapMode: Text.NoWrap
                    text: Store.compare ? "Comparing · solid is " + F.pad(Store.project.head) + " (head), blue lines are " + F.pad(Store.compare.rev) : "" } }
            Rectangle { visible: ws.mapBlocked; width: Math.min(mb.implicitWidth + 20, centre.width - 32); height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.amber, 0.12); border.color: Theme.alpha(Theme.amber, 0.3)
                Txt { id: mb; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; color: Qt.lighter(Theme.amber, 1.3); wrapMode: Text.NoWrap; elide: Text.ElideRight
                    text: "The map describes " + (Store.project ? F.pad(Store.project.head) : "the head") + ". " + (Store.hasDraft ? "Commit or discard the draft to see it." : "Stop comparing to see it.") } }
            // the readout: size, volume, and which arrangement the size belongs to
            Row { id: ro; spacing: 7; height: 18
                readonly property bool asm: !!Store.assembly && Store.asmMode !== "print"
                readonly property var bb: asm ? Store.assembly.bbox : (Store.shown ? Store.shown.bbox : null)
                Tick { font.pixelSize: 12; tone: 2; value: ro.bb ? ro.bb[1][0] - ro.bb[0][0] : 0; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: "×"; tone: 4; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                Tick { font.pixelSize: 12; tone: 2; value: ro.bb ? ro.bb[1][1] - ro.bb[0][1] : 0; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: "×"; tone: 4; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                Tick { font.pixelSize: 12; tone: 2; value: ro.bb ? ro.bb[1][2] - ro.bb[0][2] : 0; unit: " mm"; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: "·"; tone: 4; anchors.verticalCenter: parent.verticalCenter }
                Tick { font.pixelSize: 12; tone: 2; value: Store.shown ? Store.shown.volume_mm3 / 1000 : 0; unit: " cm³"; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: "·"; tone: 4; anchors.verticalCenter: parent.verticalCenter; visible: !ws.compact }
                Txt { font.pixelSize: 12; tone: 3; anchors.verticalCenter: parent.verticalCenter; visible: !ws.compact; wrapMode: Text.NoWrap
                    text: !Store.assembly ? "plate 180 × 180" : Store.asmMode === "assembled" ? "assembled" : Store.asmMode === "exploded" ? "assembled size, shown exploded" : "as printed, " + F.plural(Store.assembly.parts.length, "part") } }
        }

        // ── bottom: history above now ────────────────────────
        Rectangle {
            id: strip
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 12; z: 7
            height: stripCol.height; radius: Theme.rLg
            color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.rule
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }   // the strip is not the viewport
            Column {
                id: stripCol; width: parent.width
                Tools.Timeline { id: tline; width: parent.width; height: 40; visible: Store.timelineOpen && !!Store.project && !ws.sim; z: 2 }
                Rectangle { visible: tline.visible; x: 12; width: parent.width - 24; height: 1; color: Theme.rule }
                Pipeline { id: pipe; flat: true; width: parent.width; height: implicitHeight }
            }
        }
        Tools.ContextMenu { anchors.fill: parent; z: 8 }
    }

    // ── right: the stage inspector ───────────────────────────
    Rectangle {
        id: insp
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 400
        color: Theme.plate1
        readonly property int at: { for (var i = 0; i < Store.stages.length; i++) if (Store.stages[i].id === Store.stage) return i; return 0 }
        Rectangle { width: 1; height: parent.height; color: Theme.rule }
        // stage tabs: the lit tab slides to the stage you pick
        Item { id: tabs; x: 8; y: 6; width: parent.width - 16; height: 52
            Rectangle { y: 2; width: tabs.width / 5 - 4; height: tabs.height - 4; radius: Theme.rMd; color: Theme.plate3
                x: insp.at * tabs.width / 5 + 2
                Behavior on x { NumberAnimation { duration: Motion.move(200); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
            Row { anchors.fill: parent
                Repeater {
                    model: Store.stages
                    Item {
                        id: tab
                        objectName: "stage-" + modelData.id
                        required property var modelData
                        required property int index
                        readonly property bool on: Store.stage === modelData.id
                        readonly property var note: ws.stageNote(modelData.id)
                        width: tabs.width / 5; height: tabs.height
                        Rectangle { anchors.fill: parent; anchors.margins: 2; radius: Theme.rMd; color: !tab.on && tm.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent" }
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
        }
        // the stage's status in a sentence: stays put while the panel scrolls
        Item {
            id: stageHead
            anchors.top: tabs.bottom; anchors.topMargin: 5; width: parent.width; height: say.implicitHeight + 24; z: 2
            readonly property var s: ws.stageSay(Store.stage)
            Rectangle { x: 1; width: parent.width - 1; height: parent.height; color: Theme.plate1 }
            Rectangle { width: parent.width; height: 1; color: Theme.rule }
            Rectangle { x: 20; y: 17; width: 6; height: 6; radius: 3; color: ws.noteColor(stageHead.s[1]) }
            Txt { id: say; x: 36; y: 11; width: parent.width - 56; text: stageHead.s[0]; tone: 2 }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule; opacity: scroll.contentY > 2 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.quick } } }
        }
        Flickable {
            id: scroll
            objectName: "inspector"
            anchors.top: stageHead.bottom; anchors.bottom: foot.top; anchors.left: parent.left; anchors.right: parent.right
            contentHeight: body.implicitHeight + 32; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            Connections { target: Store; function onRevealInspector(y) { scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, y)) } }
            Column {
                id: body; x: 20; y: 2; width: parent.width - 40; spacing: 14
                Loader { id: panel; width: parent.width; active: !!Store.data
                    property int was: insp.at
                    source: ({ brief: "Brief.qml", shape: "Shape.qml", fit: "Fit.qml", prove: "Prove.qml", release: "Release.qml" })[Store.stage]
                    // the new stage comes in from the side it lies on
                    onLoaded: { scroll.contentY = 0; slide.x = Motion.shift(insp.at >= was ? 18 : -18); was = insp.at; enter.restart() }
                    transform: Translate { id: slide }
                    ParallelAnimation { id: enter
                        NumberAnimation { target: panel; property: "opacity"; from: 0; to: 1; duration: Motion.ui; easing.type: Easing.OutCubic }
                        NumberAnimation { target: slide; property: "x"; to: 0; duration: Motion.move(220); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
            }
        }
        // the open draft and its Commit stay in reach at the foot of the inspector, whatever the panel's length
        Item {
            id: foot
            anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            readonly property bool on: Store.hasDraft || !!Store.draftError
            height: on ? Math.min(draft.implicitHeight + 24, Math.round(insp.height * 0.46)) : 0
            Rectangle { anchors.fill: parent; color: Theme.plate1; visible: foot.on }
            Rectangle { width: parent.width; height: 1; color: Theme.rule; visible: foot.on }
            Flickable {
                anchors.fill: parent; anchors.topMargin: 12; anchors.bottomMargin: 12; clip: true; visible: foot.on
                contentHeight: draft.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { width: 6 }
                DraftCard { id: draft; x: 12; width: parent.width - 24 }
            }
        }
    }
}
