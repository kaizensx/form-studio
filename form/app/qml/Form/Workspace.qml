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
            return ft ? ["A change here opens a draft of " + head + ". Nothing is kept until you commit it.", ""]
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
    // a design that declares how its parts go together: assembled / exploded / as printed. Separate bodies
    // with no declaration (form/recipes/assembly.py from_solids): as modelled / pulled apart.
    // A design with separate bodies and no declaration is shown as modelled, or pulled apart; Assembled is there but
    // off, and says what it needs: the design has to say where each part goes (assembly() in its source).
    readonly property bool asmDerived: !!Store.assembly && !!Store.assembly.derived
    readonly property var asmModes: asmDerived
        ? [{ value: "assembled", text: "Assembled", off: true, tip: "This design does not say how its parts go together, so Form Studio cannot place them. Ask the agent to add that to the design." },
           { value: "exploded", text: "Exploded" }, { value: "print", text: "As modelled" }]
        : [{ value: "assembled", text: "Assembled" }, { value: "exploded", text: "Exploded" }, { value: "print", text: "Print layout" }]
    function askAssembly() {
        var a = Store.assembly, n = a ? a.parts.length : 0
        Store.talkOpen = true
        Store.recallChat("This design prints " + n + " separate parts but does not say how they go together. "
            + "Add assembly() to the design source (design_guide, ASSEMBLIES) so Form Studio can show it assembled and check it: "
            + "place each part, give it an exploded offset and an assembly step, and declare the joints and any hardware. "
            + "Keep the print layout as it is.")
    }
    // the bed of the printer this design uses (form/printers.py), for the plate caption
    readonly property string bed: d && d.printer ? d.printer.env.envelope.slice(0, 2).map(function (x) { return F.fmt(x, 0) }).join(" × ") : "180 × 180"
    readonly property bool mapBlocked: !!Store.analysisMap && (Store.hasDraft || !!Store.compare)
    function setTool(t) {
        if (ws.sim) Store.showLayers(false)
        if (t === Ws.tool && t !== "select") t = "select"           // the active tool, clicked again, hands back to Select
        var was = Ws.tool
        if (was === t) return
        Ws.tool = t
        if (was === "measure") Store.setMeasuring(false)
        if (was === "annotate") Store.setSelecting(false)
        if (t === "annotate") Store.setSelecting(true)
        if (was === "history") { Store.timelineOpen = false; Store.endScrub() }
        if (t === "measure") Store.setMeasuring(true)
        if (t === "history") Store.timelineOpen = true
        if (t === "section" && !Store.sectionNow()) Store.setSection("y", 0.5)
    }
    // the store can change these from the palette, a key, a check's marker or Esc: the rail follows
    Connections {
        target: Store
        function onMeasuringChanged() { if (Store.measuring) Ws.tool = "measure"; else if (Ws.tool === "measure") Ws.tool = "select" }
        function onSelectingChanged() { if (Store.selecting) Ws.tool = "annotate"; else if (Ws.tool === "annotate") Ws.tool = "select" }
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
    // a design that has just opened has the keyboard on the part, not in the conversation box Home left it in
    Component.onCompleted: { Ws.tool = Store.measuring ? "measure" : Store.timelineOpen ? "history" : "select"; vp.forceActiveFocus() }

    readonly property Item focusItem: Window.activeFocusItem
    readonly property bool keys: Store.screen === "work" && !Store.sheet && !Store.paletteOpen && !(focusItem && focusItem.cursorPosition !== undefined)
    Shortcut { sequence: "V"; enabled: ws.keys; onActivated: ws.setTool("select") }
    Shortcut { sequence: "M"; enabled: ws.keys; onActivated: ws.setTool("measure") }
    Shortcut { sequence: "N"; enabled: ws.keys; onActivated: ws.setTool("annotate") }
    // inside a tool: its modes by key (measure: distance, face, diameter; annotate: point, edge, face, brush, lasso)
    Shortcut { sequence: "D"; enabled: ws.keys && ws.tool === "measure"; onActivated: { Store.measureKind = "distance"; Store.measureFrom = null } }
    Shortcut { sequence: "G"; enabled: ws.keys && ws.tool === "measure"; onActivated: { Store.measureKind = "face"; Store.measureFrom = null } }
    Shortcut { sequence: "O"; enabled: ws.keys && ws.tool === "measure"; onActivated: { Store.measureKind = "diameter"; Store.measureFrom = null } }
    Shortcut { sequence: "P"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "point" }
    Shortcut { sequence: "G"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "face" }
    Shortcut { sequence: "R"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "edge" }
    Shortcut { sequence: "B"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "brush" }
    Shortcut { sequence: "L"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "lasso" }
    Shortcut { sequence: "["; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.brushMm = Math.max(0.5, Store.brushMm / 1.25) }
    Shortcut { sequence: "]"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.brushMm = Math.min(25, Store.brushMm * 1.25) }
    Shortcut { sequence: "A"; enabled: ws.keys; onActivated: ws.setTool("analyze") }
    Shortcut { sequence: "E"; enabled: ws.keys && !!Store.assembly; onActivated: ws.setTool("assembly") }
    Shortcut { sequence: "T"; enabled: ws.keys; onActivated: ws.setTool("history") }

    // ── the build-up: a new build from the agent (or a pick, or a measurement) grows in feature by feature, in build
    //    order, each one named as it arrives, so you watch the part being made. It is the real geometry of this
    //    revision revealed stage by stage (Viewport's build-up, started by Store.showHead); no extra builds run. ──
    QtObject {
        id: build
        property string label: ""
        property string sub: ""
        property int at: 0
        property int of: 0
        property bool running: false
        function step(ids, at, count) {
            if (Store.building) return            // a streamed stage names itself (Store.buildingText)
            var names = ids.map(function (id) { var f = Store.featureById(id); return f && f.label ? f.label : id }).filter(function (n) { return !!n })
            label = names.length > 2 ? names.slice(0, 2).join(", ") + " and " + (names.length - 2) + " more" : names.join(", ")
            sub = count > 1 ? (at + 1) + " of " + count : ""
            build.at = at + 1; build.of = count; running = true
            Store.revealing = ids                 // the Design list marks the rows being built
            flash.stop()
        }
        function done() { Store.revealing = []; if (Store.building) return; sub = ""; running = false; flash.restart() }
    }
    Timer { id: flash; interval: 1400; onTriggered: { build.label = ""; build.sub = "" } }
    Component.onDestruction: Store.revealing = []

    // ── centre: the part ─────────────────────────────────────
    Item {
        id: centre
        anchors.left: parent.left; anchors.right: insp.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        anchors.leftMargin: Theme.gap; anchors.rightMargin: Theme.gap; anchors.bottomMargin: Theme.gap
        PlateFrame { z: 9 }
        Viewport {
            id: vp
            objectName: "viewport"
            labelRight: dock.open ? dock.x : width
            anchors.fill: parent
            visible: !Store.layers
            asmMode: Store.asmMode; explode: Store.explode; pose: Store.pose
            stageMode: Store.stageMode                                            // the studio floor; the build plate only where the printer matters
            plateSize: ws.d && ws.d.printer ? Math.max(60, Math.max(ws.d.printer.env.envelope[0], ws.d.printer.env.envelope[1])) : 180
            hiddenFeatures: Store.hidden                                           // design tools: quick actions
            order: ws.d && ws.d.recipe && ws.d.recipe.features ? ws.d.recipe.features.map(function (f) { return f.id }) : []
            onRevealStep: function (ids, at, count) { build.step(ids, at, count) }
            onRevealDone: { build.done(); Store.reconSettle() }
            // another revision as a solid: right of Compare's wipe line, or cross-faded in while Before is held
            alt: Store.compare ? Store.compare.view : Store.peek ? Store.peek.view : null
            altK: !Store.compare && Store.peek && Store.peek.on ? 1 : 0
            wipeX: Store.compare ? wipe.at : -1
            // colours and materials: re-made whenever the design's appearance or the catalogue changes
            colorOf: { var a = Store.appearance, c = Store.materialCat; return function (part) { return Store.look(part).color || "" } }
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
            onProbed: function (hit, reach) { Store.measureClick(hit, reach) }
            // selecting and annotations (form/selection.py)
            selecting: Store.selecting; selectMode: Store.selMode; brushMm: Store.brushMm
            selection: Store.selection ? Store.selection.items : []
            focusItems: Store.annFocus && Store.annFocus.analysis ? Store.annFocus.analysis.items : []
            annotations: Store.hasDraft || Store.scrub ? [] : Store.annotations
            headRev: Store.project ? Store.project.head : 0
            annFocusId: Store.annFocus ? Store.annFocus.id : ""
            onSelPicked: function (items, add) { Store.selAdd(items, add) }
            onSelMissed: Store.selNote("Nothing there. Pick on the part’s surface.")
            onAnnotationClicked: function (id) { Store.focusAnnotation(Store.annFocus && Store.annFocus.id === id ? null : Store.annotationById(id)) }
            onProbeMissed: Store.measureNote("Nothing there. Click on the part’s surface.")
            onHoveredValue: function (v, x, y, on) { vchip.on = on; vchip.v = v; vchip.x = Math.min(x + 14, centre.width - vchip.width - 8); vchip.y = y + 14 }
        }
        Loader { id: lv; anchors.fill: parent; active: !!Store.layers; source: "LayerView.qml"
            onLoaded: { item.leftInset = 56; item.stripHeight = Qt.binding(function () { return strip.height + 12 }) } }
        // soft vignette so the bench falls away towards the top and under the strip
        Rectangle { anchors.fill: parent; visible: !Store.layers
            gradient: Gradient { orientation: Gradient.Vertical
                GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.5) } GradientStop { position: 0.16; color: "transparent" }
                GradientStop { position: 0.82; color: "transparent" } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.75) } } }

        // the build's ledger: which feature is arriving, how far the build is
        Item {
            id: buildCap; objectName: "buildCaption"; z: 6
            // pinned top centre over the part, but never under the dock's panels (top right: refinement, legends): it
            // moves left of them, and below them when there is no room beside them
            readonly property bool dockShown: dock.visible && dock.width > 0 && dock.height > 0
            readonly property real centred: (parent.width - width) / 2
            readonly property real room: dockShown ? dock.x - 12 - width : centred
            readonly property bool beside: room >= 12
            x: Math.round(beside ? Math.min(centred, room) : centred)
            y: beside ? 58 : Math.round(dock.y + dock.height + 10)
            width: ledger.width; height: ledger.height
            // a stage streamed while the agent rewrites the design: "Building Rim (3 of 5)"
            readonly property var st: Store.building && Store.building.project === Store.pid ? Store.building : null
            readonly property string caption: st ? Store.buildingText : build.label ? (build.running ? "Building " : "Built ") + build.label + (build.sub ? " " + build.sub : "") : ""
            opacity: build.label || st ? 1 : 0; visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: build.label || buildCap.st ? Theme.fast : 420 } }
            BuildLedger { id: ledger
                label: buildCap.st ? buildCap.st.label : build.label
                at: buildCap.st ? buildCap.st.at : build.at; of: buildCap.st ? buildCap.st.of : build.of
                running: !!buildCap.st || build.running; pulse: !!buildCap.st } }

        // a mesh made editable: how far the CAD is from the mesh at most, counted up as the CAD grows inside the mesh's lines
        Rectangle {
            id: reconCap; objectName: "reconReadout"; z: 6
            readonly property var rc: Store.recon && Store.recon.project === Store.pid ? Store.recon : null
            x: Math.round(Math.max(60, Math.min(parent.width - width - 12, buildCap.x + (buildCap.width - width) / 2))); y: buildCap.y + buildCap.height + Theme.s2
            width: rcr.implicitWidth + 2 * Theme.s3; height: 30; radius: Theme.rSm
            color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.alpha(Theme.blueprint, 0.35)
            opacity: rc ? 1 : 0; visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: reconCap.rc ? Theme.fast : Theme.cross } }
            Row { id: rcr; x: Theme.s3; anchors.verticalCenter: parent.verticalCenter; spacing: Theme.s2
                Txt { mono: true; kind: "fine"; tone: 2; text: "max deviation"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                Loader { active: !!reconCap.rc; anchors.verticalCenter: parent.verticalCenter       // made anew for each reconstruction, so it counts from zero
                    sourceComponent: Tick { countIn: true; countMs: 1600; decimals: 3; unit: " mm"; font.pixelSize: Theme.tBody; font.weight: Theme.wMedium
                        value: reconCap.rc ? reconCap.rc.mm : 0; color: reconCap.rc && !reconCap.rc.within ? Theme.amber : Theme.ink } }
                Tag { text: "computed"; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; tone: 3; visible: !!reconCap.rc && !reconCap.rc.within; text: "outside the tolerance"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } } }

        // Compare's wipe: the head left of the line, the other revision right of it. Drag the line; a tag on each side
        // says which revision it is.
        Item {
            id: wipe; objectName: "compareWipe"; z: 3
            property real frac: 0.5                 // across the free area of the view
            readonly property real lo: vp.insetLeft + 24
            readonly property real hi: Math.max(lo + 40, vp.width - vp.insetRight - 24)
            readonly property real at: Math.round(lo + (hi - lo) * frac)
            readonly property bool on: vp.wipeOn && !ws.sim
            visible: on; x: at; y: 0; width: 1; height: strip.y
            Rectangle { x: 0; y: 44; width: 1; height: parent.height - 56; color: Theme.alpha(Theme.blueprint, 0.7) }
            Rectangle { id: grip; anchors.horizontalCenter: parent.left; y: Math.round(parent.height / 2) - 18; width: 14; height: 36; radius: 7
                color: wm.pressed ? Theme.plate4 : Theme.plate3; border.color: Theme.alpha(Theme.blueprint, wm.containsMouse || wm.pressed ? 0.9 : 0.55)
                scale: wm.pressed ? Theme.from(0.96) : 1
                Behavior on scale { Glide { duration: Theme.press } } Behavior on border.color { Tint {} }
                Column { anchors.centerIn: parent; spacing: 3
                    Repeater { model: 3; Rectangle { width: 2; height: 2; radius: 1; color: Theme.blueprint } } } }
            Tag { objectName: "wipeTagHead"; anchors.right: parent.left; anchors.rightMargin: Theme.s2; y: 52; tint: Theme.ink2
                color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.rule2
                text: Store.project ? F.pad(Store.project.head) + " · head" : "" }
            Tag { objectName: "wipeTagOther"; anchors.left: parent.right; anchors.leftMargin: Theme.s2; y: 52; kind: "draft"
                color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.alpha(Theme.blueprint, 0.4)
                text: Store.compare ? F.pad(Store.compare.rev) : "" }
            MouseArea { id: wm; x: -22; width: 44; y: 44; height: parent.height - 56; hoverEnabled: true; cursorShape: Qt.SplitHCursor
                preventStealing: true
                onPositionChanged: function (e) { if (pressed) { var p = mapToItem(centre, e.x, e.y).x; wipe.frac = Math.max(0, Math.min(1, (p - wipe.lo) / Math.max(1, wipe.hi - wipe.lo))) } }
                onDoubleClicked: wipe.frac = 0.5 }
            Tip { show: wm.containsMouse && !wm.pressed; text: "Drag to wipe between the two revisions" }
            Connections { target: Store; function onCompareChanged() { if (!Store.compare) wipe.frac = 0.5 } }
        }

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
            color: Theme.alpha(Theme.plate2, 0.94); border.color: Theme.rule2
            Shadow { radius: parent.radius; spread: 14; drop: 5; strength: 0.7 }
            visible: !!Store.view
            Column {
                id: railCol; x: 4; y: 4; spacing: 1
                RailBtn { icon: "mouse_pointer_2"; label: "Select"; keys: "V"; hint: "Click a feature to edit it. Drag to orbit, shift-drag to pan."
                    active: ws.tool === "select" && !ws.sim; onClicked: ws.setTool("select") }
                RailBtn { icon: "pencil_ruler"; label: "Measure"; keys: "M"; hint: "Distances, faces and hole diameters, computed from the part’s surface."
                    active: ws.tool === "measure" && !ws.sim; marked: Store.measures.length > 0; onClicked: ws.setTool("measure") }
                RailBtn { icon: "map_pin"; label: "Annotate"; keys: "N"; hint: "Pick faces, edges and points or paint a region; see what the solid says there, keep it with a note, ask the agent about it."
                    active: ws.tool === "annotate" && !ws.sim; marked: Store.annotations.length > 0 || Store.selItems.length > 0; onClicked: ws.setTool("annotate") }
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
                RailBtn { objectName: "railGame"; icon: "gamepad_2"; label: "Game asset"; hint: Store.hasDraft ? "Commit or discard the draft first." : "LODs at triangle budgets, UVs, baked maps and collision, for Godot, Unity or Unreal (built in Blender)."
                    visible: Store.gameDesign; enabled: !Store.hasDraft; onClicked: Store.openSheet("game") }
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
                             measureBar.shown ? measureBar.height : 0, asmBar.shown ? asmBar.height : 0, annotateBar.shown ? annotateBar.height : 0)

            HudBar { id: annotateBar; objectName: "annotateBar"; shown: ws.tool === "annotate"; maxWidth: opts.room
                Seg { model: [{ value: "face", text: "Face", tip: "G" }, { value: "edge", text: "Edge", tip: "R" }, { value: "point", text: "Point", tip: "P" },
                              { value: "brush", text: "Brush", tip: "B: paint a region on the surface" }, { value: "lasso", text: "Lasso", tip: "L: draw around what you see" }]
                    value: Store.selMode; onPicked: function (v) { Store.selMode = v } }
                HudSlider { visible: Store.selMode === "brush"; label: "Size"; unit: " mm"; decimals: 1; from: 0.5; to: 15; step: 0.5
                    value: Store.brushMm; onMoved: function (v) { Store.brushMm = v } }
                Rectangle { objectName: "annotateHint"; height: 26; width: Math.min(sh.implicitWidth + 20 + (sspin.visible ? 20 : 0), opts.room); radius: Theme.rSm
                    color: Store.selSay ? Theme.alpha(Theme.amber, 0.12) : Theme.alpha(Theme.plate1, 0.9); border.color: Store.selSay ? Theme.alpha(Theme.amber, 0.35) : Theme.rule
                    Behavior on color { Tint {} }
                    Spinner { id: sspin; x: 9; anchors.verticalCenter: parent.verticalCenter; size: 12; visible: Store.selBusy > 0; color: Theme.annotate }
                    Txt { id: sh; x: sspin.visible ? 28 : 10; width: parent.width - x - 10; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        color: Store.selSay ? Theme.strong(Theme.amber) : Theme.ink2
                        text: Store.selSay ? Store.selSay : Store.selBusy > 0 ? "Analysing on the solid…"
                            : Store.selMode === "brush" ? (ws.compact ? "Drag to paint" : "Drag to paint a region · Alt-drag orbits · Shift adds")
                            : Store.selMode === "lasso" ? (ws.compact ? "Drag around it" : "Draw around what you see · Alt-drag orbits · Shift adds")
                            : ws.compact ? "Click to pick" : "Click to pick a " + Store.selMode + " · Shift-click adds" } }
                Btn { small: true; height: 26; text: "Clear"; visible: Store.selItems.length > 0; onClicked: Store.selClear() }
            }

            HudBar { id: measureBar; objectName: "measureBar"; shown: ws.tool === "measure"; maxWidth: opts.room
                Seg { model: [{ value: "distance", text: "Distance" }, { value: "face", text: "Face" }, { value: "diameter", text: "Diameter" }]
                    value: Store.measureKind
                    onPicked: function (v) { Store.measureKind = v; Store.measureFrom = null } }
                Rectangle { objectName: "measureHint"; height: 26; width: Math.min(mh.implicitWidth + 20 + (mspin.visible ? 20 : 0), opts.room); radius: Theme.rSm
                    color: Store.measureSay ? Theme.alpha(Theme.amber, 0.12) : Theme.alpha(Theme.plate1, 0.9); border.color: Store.measureSay ? Theme.alpha(Theme.amber, 0.35) : Theme.rule
                    Behavior on color { Tint {} }
                    Spinner { id: mspin; x: 9; anchors.verticalCenter: parent.verticalCenter; size: 12; visible: Store.measureBusy > 0 }
                    Txt { id: mh; x: mspin.visible ? 28 : 10; width: parent.width - x - 10; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        color: Store.measureSay ? Theme.strong(Theme.amber) : Theme.ink2
                        text: Store.measureSay ? Store.measureSay : Store.measureBusy > 0 ? "Measuring on the solid…"
                            : Store.measureKind === "distance" ? (Store.measureFrom ? "Click the second point" : ws.compact ? "Click two points; they snap" : "Click two points. They snap to corners, midpoints and centres")
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
                Seg { visible: !ws.compact; model: ws.asmModes
                    value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) } }
                Pick { visible: ws.compact; width: 150; height: 26; value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) }
                    model: ws.asmModes.filter(function (m) { return !m.off }) }
                Rectangle { objectName: "asmDerivedNote"; visible: ws.asmDerived; height: 26; width: Math.min(an.implicitWidth + 20, opts.room); radius: Theme.rSm
                    color: Theme.alpha(Theme.plate1, 0.9); border.color: Theme.rule
                    Txt { id: an; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 3; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        text: ws.compact ? "Placement not declared" : "Not assembled: the design does not say where each part goes" } }
                Btn { visible: ws.asmDerived; small: true; height: 26; icon: "sparkles"; text: ws.compact ? "Ask the agent" : "Ask the agent to add it"
                    tip: "Puts a request in the conversation for you to send: describe how the parts go together in the design."
                    onClicked: ws.askAssembly() }
                HudSlider { visible: Store.asmMode === "exploded"; label: "Spread"; from: 0; to: 1.6; step: 0.05; base: 1; percent: true
                    value: Store.explode; onMoved: function (v) { Store.setExplode(v) } }
                Repeater { model: Store.assembly && Store.asmMode !== "print" ? Store.assembly.joints.filter(function (j) { return j.kind !== "fixed" }) : []
                    HudSlider { required property var modelData
                        label: modelData.label; unit: modelData.kind === "hinge" ? "°" : " mm"
                        objectName: "jointSlider_" + modelData.id
                        from: modelData.range[0]; to: modelData.range[1]; step: modelData.step > 0 ? modelData.step : 1; base: 0
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
        // a design made for printing, while Describe or Design is open: it stands on the build plate; this hides it
        // (Fit, Review and Make show it anyway)
        Btn { objectName: "showPlate"; z: 5; small: true; kind: "quiet"; height: 26; icon: "grid_3x3"; active: Store.showPlate
            anchors.right: viewCtl.left; anchors.rightMargin: 6; y: viewCtl.y
            visible: !ws.sim && !!Store.view && Store.printUi && (Store.stage === "brief" || Store.stage === "shape")
            tip: Store.showPlate ? "Hide the build plate" : "Show the build plate" + (Store.printing.available ? ": " + Store.printing.presets.machine.name : "")
            onClicked: Store.showPlate = !Store.showPlate }

        // an agent is working on another design than this one: named, never jumped to once you are working here
        Rectangle {
            id: elsewhere; objectName: "agentElsewhere"; z: 6
            anchors.horizontalCenter: parent.horizontalCenter; y: 58
            visible: !!Store.agentElsewhere && !build.label && !ws.sim
            width: er.implicitWidth + 20; height: 32; radius: 16; color: Theme.alpha(Theme.plate3, 0.96); border.color: Theme.rule2
            Row { id: er; x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity { running: elsewhere.visible && !Theme.reduced; loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                Txt { anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; font.pixelSize: 12
                    width: Math.min(implicitWidth, centre.width - 220); elide: Text.ElideRight
                    text: Store.agentElsewhere ? Store.agentElsewhere.by + " is working on " + Store.agentElsewhere.name
                                                 + (Store.agentElsewhere.title && Store.agentElsewhere.name.indexOf("“") !== 0 ? " in “" + Store.agentElsewhere.title + "”" : "") : "" }
                Btn { objectName: "agentElsewhereShow"; small: true; kind: "quiet"; text: "Show"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.showElsewhere() }
                Btn { small: true; kind: "quiet"; icon: "x"; tip: "Stay here"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.agentElsewhere = null } } }

        // ── the dock: legends and readouts, top right, never over the middle of the part ──
        Column {
            id: dock
            anchors.right: parent.right; anchors.rightMargin: 12; y: 48; z: 4; spacing: 8; visible: !ws.sim
            readonly property bool folded: Ws.dockTouched ? Ws.dockCollapsed : ws.compact
            readonly property bool showMap: !!Store.analysisMap && !ws.mapBlocked
            readonly property bool showMeasures: Store.measures.length > 0
            readonly property bool showSel: ws.tool === "annotate" || Store.selItems.length > 0 || !!Store.annFocus
            // refinement: while it runs, and while the head carries refine changes (or the last run failed)
            readonly property bool showRefine: !!Store.refine && !Store.scrub && (Store.refine.state === "running"
                || (Store.refine.changes || []).length > 0 || Store.refine.state === "failed")
            readonly property bool open: (showMap || showMeasures || showSel || showRefine) && !folded
            readonly property real room: Math.max(120, strip.y - y - 46)
            function flip() { var now = folded; Ws.dockTouched = true; Ws.dockCollapsed = !now }
            AnalysisLegend { objectName: "analysisLegend"; visible: opacity > 0.01; opacity: dock.showMap ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.ui; easing.type: Easing.OutCubic } }
                map: Store.analysis; busy: Store.analysisBusy; pending: Store.analysisLabel(Store.analysisMap); check: Store.analysis ? Store.analysisCheck() : null
                collapsed: dock.folded || (dock.showMeasures && ws.tool === "measure")
                maxHeight: dock.room - (dock.showMeasures ? 44 : 0); onToggled: dock.flip() }
            SelectionPanel { visible: dock.showSel
                collapsed: dock.folded || ((dock.showMap || dock.showMeasures) && ws.tool !== "annotate" && !Store.annFocus)
                maxHeight: dock.room - (dock.showMap ? 44 : 0) - (dock.showMeasures ? 44 : 0); onToggled: dock.flip() }
            MeasurePanel { objectName: "measurePanel"; visible: dock.showMeasures
                collapsed: dock.folded || (dock.showMap && ws.tool !== "measure")
                maxHeight: dock.room - (dock.showMap ? 44 : 0); onToggled: dock.flip() }
            RefinePanel { visible: opacity > 0.01; opacity: dock.showRefine ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.ui; easing.type: Easing.OutCubic } }
                collapsed: dock.folded || dock.showMap || dock.showMeasures || dock.showSel
                maxHeight: dock.room - (dock.showMap ? 44 : 0) - (dock.showMeasures ? 44 : 0) - (dock.showSel ? 44 : 0)
                onToggled: dock.flip() }
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
                Txt { id: b1; anchors.centerIn: parent; font.pixelSize: 12; color: Theme.strong(Theme.blueprint); wrapMode: Text.NoWrap
                    text: "Draft, not committed · blue lines are " + (Store.project ? F.pad(Store.project.head) : "") } }
            Rectangle { objectName: "compareChip"; visible: !!Store.compare; width: b2.implicitWidth + 20; height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Row { id: b2; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Txt { font.pixelSize: 12; color: Theme.strong(Theme.blueprint); wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                        text: !Store.compare || !Store.project ? ""
                            : vp.wipeOn ? "Comparing · " + F.pad(Store.project.head) + " (head) left, " + F.pad(Store.compare.rev) + " right · blue lines are " + F.pad(Store.compare.rev)
                            : "Comparing · solid is " + F.pad(Store.project.head) + " (head), blue lines are " + F.pad(Store.compare.rev) }
                    Btn { objectName: "compareDone"; small: true; kind: "quiet"; text: "Done"; tip: "Stop comparing (Esc)"
                        anchors.verticalCenter: parent.verticalCenter; onClicked: Store.endCompare() } } }
            Rectangle { visible: ws.mapBlocked; width: Math.min(mb.implicitWidth + 20, centre.width - 32); height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.amber, 0.12); border.color: Theme.alpha(Theme.amber, 0.3)
                Txt { id: mb; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; color: Theme.strong(Theme.amber); wrapMode: Text.NoWrap; elide: Text.ElideRight
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
                Txt { text: "·"; tone: 4; anchors.verticalCenter: parent.verticalCenter; visible: !ws.compact && (Store.plateWanted || !!Store.assembly) }
                Txt { font.pixelSize: 12; tone: 3; anchors.verticalCenter: parent.verticalCenter; visible: !ws.compact && (Store.plateWanted || !!Store.assembly); wrapMode: Text.NoWrap
                    text: !Store.assembly ? "plate " + ws.bed : Store.asmMode === "assembled" ? "assembled" : Store.asmMode === "exploded" ? (Store.assembly.derived ? "as modelled, shown pulled apart" : "assembled size, shown exploded")
                        : (Store.assembly.derived || !Store.printUi ? "as modelled, " : "as printed, ") + F.plural(Store.assembly.parts.length, "part") } }
        }

        // ── bottom: history above now ────────────────────────
        Rectangle {
            id: strip
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 12; z: 7
            height: stripCol.height; radius: Theme.rLg
            color: Theme.alpha(Theme.plate2, 0.94); border.color: Theme.rule2
            Shadow { radius: parent.radius; spread: 16; drop: 6; strength: 0.7 }
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
        anchors.rightMargin: Theme.gap; anchors.bottomMargin: Theme.gap
        color: Theme.plate1; radius: Theme.rPanel; border.width: 1; border.color: Theme.panelEdge
        // arriving with the workspace: the inspector slides in from its own edge, a beat after the screen
        transform: Translate { id: inspIn }
        SequentialAnimation { id: inspArrive
            PropertyAction { target: inspIn; property: "x"; value: Theme.shift(28) }
            PropertyAction { target: insp; property: "opacity"; value: 0 }
            PauseAnimation { duration: Theme.stagger * 2 }
            ParallelAnimation {
                NumberAnimation { target: insp; property: "opacity"; to: 1; duration: Theme.panel; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
                NumberAnimation { target: inspIn; property: "x"; to: 0; duration: Theme.move(Theme.panel + 60); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
        Component.onCompleted: inspArrive.start()
        readonly property int at: { for (var i = 0; i < Store.stages.length; i++) if (Store.stages[i].id === Store.stage) return i; return 0 }
        // stage tabs: the lit tab slides to the stage you pick
        // each tab is as wide as its words plus an equal share of the slack, so "Release" has the same air as "Fit"
        Item { id: tabs; objectName: "stageTabs"; x: 8; y: 6; width: parent.width - 16; height: 52
            property var needs: [0, 0, 0, 0, 0]
            function setNeed(i, w) { if (needs[i] === w) return; var n = needs.slice(); n[i] = w; needs = n }
            readonly property real needSum: { var t = 0; for (var i = 0; i < needs.length; i++) t += needs[i]; return t }
            Rectangle { id: lit; y: 2; height: tabs.height - 4; radius: Theme.rMd; color: Theme.plate3
                readonly property Item at: stageRep.count > insp.at ? stageRep.itemAt(insp.at) : null
                property bool settled: false
                x: at ? at.x + 2 : 0; width: at ? at.width - 4 : 0
                Component.onCompleted: Qt.callLater(function () { lit.settled = true })
                Behavior on x { enabled: lit.settled; NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
                Behavior on width { enabled: lit.settled; NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
                border.width: 1; border.color: Theme.rule
                // the datum mark under the stage you are in: it travels with the lit tab
                Rectangle { anchors.bottom: parent.bottom; anchors.bottomMargin: -1; anchors.horizontalCenter: parent.horizontalCenter; width: 22; height: 2; radius: 1; color: Theme.datum } }
            Row { anchors.fill: parent
                Repeater {
                    id: stageRep
                    model: Store.stages
                    Item {
                        id: tab
                        objectName: "stage-" + modelData.id
                        required property var modelData
                        required property int index
                        readonly property bool on: Store.stage === modelData.id
                        readonly property var note: ws.stageNote(modelData.id)
                        readonly property real need: Math.ceil(Math.max(tr.implicitWidth, tn.implicitWidth))
                        onNeedChanged: tabs.setNeed(index, need)
                        Component.onCompleted: tabs.setNeed(index, need)
                        width: tabs.needSum > 0 && tabs.needSum < tabs.width ? need + (tabs.width - tabs.needSum) / 5 : tabs.width / 5
                        height: tabs.height
                        Rectangle { anchors.fill: parent; anchors.margins: 2; radius: Theme.rMd; color: tab.on ? "transparent" : tm.pressed ? Theme.washPress : tm.containsMouse ? Theme.washHover : "transparent"
                            Behavior on color { Tint {} } }
                        Column { anchors.centerIn: parent; spacing: 2
                            Row { id: tr; spacing: 5; anchors.horizontalCenter: parent.horizontalCenter
                                Txt { mono: true; font.pixelSize: Theme.tFine; color: tab.on ? Theme.datum : Theme.ink4; text: "0" + (tab.index + 1); anchors.baseline: tl.baseline
                                    Behavior on color { Tint {} } }
                                Txt { id: tl; text: tab.modelData.title; font.weight: Theme.wSemi; font.pixelSize: 13; tone: tab.on ? 1 : 2 } }
                            Txt { id: tn; anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: Theme.tFine; text: tab.note[0]; color: ws.noteColor(tab.note[1]); wrapMode: Text.NoWrap } }
                        MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.setStage(tab.modelData.id) }
                        Tip { show: tm.containsMouse; below: true; text: tab.modelData.hint; keys: "Ctrl+" + Store.stageKey[tab.modelData.id] }
                    }
                }
            }
        }
        // the stage's status in a sentence: stays put while the panel scrolls
        Item {
            id: stageHead
            anchors.top: tabs.bottom; anchors.topMargin: 5; width: parent.width; height: say.implicitHeight + 24; z: 2
            readonly property var s: ws.stageSay(Store.stage)
            Rectangle { x: 1; width: parent.width - 2; height: parent.height; color: Theme.plate1 }
            Rectangle { x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
            Rectangle { x: 20; y: 17; width: 6; height: 6; radius: 3; color: ws.noteColor(stageHead.s[1]) }
            Txt { id: say; x: 36; y: 11; width: parent.width - 56; text: stageHead.s[0]; tone: 2 }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule; opacity: scroll.contentY > 2 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.quick } } }
        }
        Flickable {
            id: scroll
            objectName: "inspector"
            anchors.top: stageHead.bottom; anchors.bottom: foot.top; anchors.left: parent.left; anchors.right: parent.right
            // while a toast is up, the last rows can still be scrolled clear of it
            contentHeight: body.implicitHeight + 32 + (Store.toasts.length ? 24 + 72 * Store.toasts.length : 0); clip: true; boundsBehavior: Flickable.StopAtBounds
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
                        NumberAnimation { target: slide; property: "x"; to: 0; duration: Theme.move(Theme.cross); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
            }
        }
        // the open draft and its Commit stay in reach at the foot of the inspector, whatever the panel's length
        Item {
            id: foot
            anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            readonly property bool on: Store.hasDraft || !!Store.draftError
            height: on ? Math.min(draft.implicitHeight + 24, Math.round(insp.height * 0.46)) : 0
            Rectangle { anchors.fill: parent; anchors.margins: 1; anchors.topMargin: 0; color: Theme.plate1; visible: foot.on; radius: Theme.rPanel - 1
                Rectangle { width: parent.width; height: parent.radius; color: parent.color } }
            Rectangle { x: 1; width: parent.width - 2; height: 1; color: Theme.rule; visible: foot.on }
            Flickable {
                anchors.fill: parent; anchors.topMargin: 12; anchors.bottomMargin: 12; clip: true; visible: foot.on
                contentHeight: draft.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { width: 6 }
                DraftCard { id: draft; x: 12; width: parent.width - 24 }
            }
        }
    }
}
