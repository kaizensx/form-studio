import QtQuick
import QtQuick.Dialogs
import QtQuick.Effects
import FormNative
import "F.js" as F

// Stage 04 — Prove. What has been established about this revision, and by what kind of evidence.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var d: Store.data
    readonly property var ch: d ? d.checks : null
    readonly property var sl: d ? d.slice : null
    readonly property var st: d ? d.status : null
    readonly property var cn: st ? st.checks : null          // checks node of the pipeline
    readonly property var sn: st ? st.slice : null           // slice node of the pipeline
    readonly property string head: d ? F.pad(d.project.head) : ""
    readonly property bool busy: Store.job !== ""
    readonly property bool sliceFailed: !!sn && sn.state === "failed"
    readonly property bool sliceOff: !!sn && sn.state === "off" && Store.printUi      // Design only
    readonly property bool model: !Store.printUi                                        // a 3D model or printing off: no print rows
    readonly property var plates: Store.plates                                          // several plates (form/plates.py)
    readonly property var pl: plates.length ? plates[Store.plateShown - 1] : null        // the plate on screen
    readonly property var shownSlice: pl ? Object.assign({}, sl, pl) : sl                // that plate, or the one slice
    readonly property var colw: [54, 70, 78, 70]            // orientation table: numeric column widths
    function uniq(a) { return a.filter(function (x, i) { return a.indexOf(x) === i }) }

    // ── checks: not current ──────────────────────────────────
    Sec { title: "Checks"; visible: !root.ch
        Note { kind: "amber"
            text: !root.cn ? "Checks have not been produced for this revision."
                : root.cn.state === "failed" ? (root.cn.error ? root.cn.error.message : "The checks failed.")
                : root.cn.state === "stale" ? "The last checks were made for " + F.pad(root.cn.last_rev) + " and do not describe " + root.head + "."
                : "Checks have not been produced for this revision." }
        Row { spacing: 8
            Btn { kind: "primary"; icon: "play"; text: "Run pipeline"; busyText: "Running…"; busy: root.busy; onClicked: Store.run() }
            FixBtn { visible: !!root.cn && root.cn.state === "failed" && Store.chatReady && !!Store.chat.available; small: false
                subject: "the checks could not be produced for " + root.head
                details: root.cn && root.cn.error ? "Error: " + root.cn.error.message + (root.cn.error.hint ? "\nHint: " + root.cn.error.hint : "") : "" } }
    }

    // ── checks: the score first ──────────────────────────────
    readonly property var all: ch ? ch.checks : []
    readonly property var open: all.filter(function (c) { return c.status === "FAIL" || c.status === "WARN" })
    readonly property var unknown: all.filter(function (c) { return c.status !== "PASS" && c.status !== "FAIL" && c.status !== "WARN" })
    readonly property var passed: all.filter(function (c) { return c.status === "PASS" })
    readonly property var roll: ch ? ch.rollup : ({ PASS: 0, WARN: 0, FAIL: 0 })
    readonly property int total: Math.max(1, roll.PASS + roll.WARN + roll.FAIL)
    property int shown: -1                                   // index of the passed check whose detail is open
    function evidenceMix(list) {                             // "8 computed · 1 heuristic"
        var n = ({}), order = []
        list.forEach(function (c) { var e = c.evidence || "unlabelled"; if (!n[e]) { n[e] = 0; order.push(e) } n[e]++ })
        return order.map(function (e) { return n[e] + " " + e }).join(" · ")
    }
    Column { visible: !!root.ch; width: parent.width; topPadding: 14; spacing: 12
        Row { width: parent.width
            Repeater {
                model: [{ n: root.roll.PASS, l: "pass", c: Theme.pass }, { n: root.roll.WARN, l: "to review", c: Theme.amber }, { n: root.roll.FAIL, l: "failed", c: Theme.signal }]
                Column { required property var modelData; required property int index
                    width: parent.width / 3; spacing: 0
                    Tick { decimals: 0; value: modelData.n; countIn: true; font.pixelSize: Theme.tH1; font.weight: 600; font.letterSpacing: -0.6
                        color: modelData.n > 0 ? modelData.c : Theme.ink4 }
                    Txt { kind: "cap"; text: modelData.l; color: modelData.n > 0 ? Theme.ink2 : Theme.ink4 } }
            }
        }
        // the same three numbers as one bar: how much of the evidence is settled
        Row { width: parent.width; height: 4; spacing: 2
            Repeater { model: [[root.roll.PASS, Theme.pass], [root.roll.WARN, Theme.amber], [root.roll.FAIL, Theme.signal]]
                Rectangle { required property var modelData; required property int index
                    visible: modelData[0] > 0; height: 4; radius: 2; color: modelData[1]
                    width: Math.max(4, (parent.width - 4) * modelData[0] / root.total)
                    // the bar fills from the left as the numbers count up (a scale, not the width: no layout per frame)
                    transform: Scale { id: grow; origin.x: 0; xScale: 1 }
                    SequentialAnimation { id: fill
                        PropertyAction { target: grow; property: "xScale"; value: Motion.reduced ? 1 : 0 }
                        PauseAnimation { duration: Theme.move(120 + index * Theme.stagger * 2) }
                        NumberAnimation { target: grow; property: "xScale"; to: 1; duration: Theme.move(Theme.slow * 2); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
                    Component.onCompleted: fill.start() } } }
        Txt { kind: "fine"; width: parent.width
            text: root.ch ? "Checks for " + F.pad(root.ch.rev) + " · " + root.evidenceMix(root.all) + ". Each says how it is known." : "" }
    }

    // ── what needs a look: failures and reviews, in full ─────
    function checkText(c) {
        return "- " + c.status + " · " + c.label + (c.value !== undefined && c.value !== null && c.value !== "" ? " = " + c.value : "")
            + (c.evidence ? " (" + c.evidence + ")" : "") + (c.detail ? ": " + c.detail : "") + (c.id ? " [check " + c.id + "]" : "")
            + (c.feature ? " [feature " + c.feature + "]" : "")
    }
    readonly property var failing: all.filter(function (c) { return c.status === "FAIL" })
    Sec { visible: root.open.length > 0
        title: root.roll.FAIL ? "Failed and to review" : "To review"
        FixBtn { visible: root.failing.length > 0 && Store.chatReady && !!Store.chat.available
            subject: root.failing.length === 1 ? "a check fails on " + root.head + ": " + root.failing[0].label : F.plural(root.failing.length, "check") + " fail on " + root.head
            details: "Failing checks:\n" + root.failing.map(root.checkText).join("\n") }
        Column { x: -8; width: parent.width + 16
            Repeater {
                model: root.open
                Rectangle {
                    id: cr
                    required property var modelData
                    required property int index
                    readonly property bool link: !!(modelData.at || modelData.feature)
                    width: parent.width; height: cc.implicitHeight + 18; radius: Theme.rMd
                    color: link && cm.containsMouse ? Theme.washHover : "transparent"
                    Behavior on color { Tint {} }
                    // rows tick in one after another as the stage opens
                    opacity: 0; transform: Translate { id: crIn; y: Theme.shift(Theme.rise) }
                    SequentialAnimation { running: true
                        PauseAnimation { duration: 160 + Math.min(cr.index, 8) * Theme.stagger }
                        ParallelAnimation { Glide { target: cr; property: "opacity"; to: 1; duration: Theme.panel }
                            Glide { target: crIn; property: "y"; to: 0; duration: Theme.move(Theme.panel) } } }
                    Rectangle { visible: cr.index > 0; x: 8; width: parent.width - 16; height: 1; color: Theme.rule }
                    Column { id: cc; x: 8; y: 9; width: parent.width - 16; spacing: 5
                        Item { width: parent.width; height: Math.max(lab.implicitHeight, 17)
                            Tag { text: cr.modelData.status; y: 1 }
                            Txt { id: lab; x: 50; width: parent.width - 50 - val.width - 10; text: cr.modelData.label; font.weight: 550 }
                            Txt { id: val; mono: true; anchors.right: parent.right; text: String(cr.modelData.value === undefined || cr.modelData.value === null ? "" : cr.modelData.value)
                                wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, 170); horizontalAlignment: Text.AlignRight } }
                        Tag { x: 50; text: cr.modelData.evidence || ""; visible: text !== "" }
                        Txt { kind: "fine"; x: 50; width: parent.width - 50; text: cr.modelData.detail || ""; visible: text !== "" }
                        Row { x: 50; spacing: 5; visible: cr.link
                            Icon { name: "crosshair"; size: 11; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                            Txt { kind: "fine"; text: "Click to see where on the part" } }
                    }
                    MouseArea { id: cm; objectName: "openCheckArea"; anchors.fill: parent; enabled: cr.link; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: Store.marker(cr.modelData) }
                    HoverHandler { id: crh }
                    // one failing check: fix just this one (shown on hover, so the list stays quiet)
                    FixBtn { objectName: "fixCheck"; compact: true; anchors.right: parent.right; anchors.rightMargin: 8; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
                        visible: cr.modelData.status === "FAIL" && Store.chatReady && !!Store.chat.available && (crh.hovered || hovered)
                        subject: "the check “" + cr.modelData.label + "” fails on " + root.head; details: root.checkText(cr.modelData) }
                }
            }
        }
    }
    Item { width: 1; height: 6; visible: !!root.ch }

    // ── a 3D model: which print checks do not apply, and the way back to printing ──
    Note { objectName: "modelChecksNote"; visible: Store.printOn && root.model && !!root.ch; kind: "plain"; title: "3D model: print checks do not apply"
        text: root.ch && root.ch.not_applicable ? "Not run, because this design is not for 3D printing: " + root.ch.not_applicable.join(", ") + "." : "" }
    Row { visible: Store.printOn && root.model && !!root.ch; spacing: 8; topPadding: 6
        Btn { objectName: "makePrintable"; small: true; icon: "printer"; text: "Make it for 3D printing"; enabled: !root.busy
            tip: "Run the print checks and slice it (when a slicer is installed)"; onClicked: Store.setPurpose("print") } }
    Txt { kind: "fine"; tone: 2; width: parent.width; visible: Store.printOn && root.model && !!root.ch
        text: "Then “Open in " + Store.slicerName + "” opens it sliced, with settings chosen for this part." }

    // ── what could not be checked (mesh designs, a model with no stated process): never counted as a pass ──
    Fold { visible: root.unknown.length > 0; key: "prove.unknown"; openByDefault: true
        title: "Not checked"; note: root.unknown.length + " · not counted as passed"
        Column { width: parent.width; spacing: 6
            Repeater { model: root.unknown
                Column { required property var modelData; width: parent.width; spacing: 2
                    Item { width: parent.width; height: 18
                        Tag { text: "N/A"; y: 1 }
                        Txt { x: 50; width: parent.width - 50 - nv.width - 10; text: parent.parent.modelData.label; font.weight: 550; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Txt { id: nv; mono: true; anchors.right: parent.right; text: String(parent.parent.modelData.value || ""); wrapMode: Text.NoWrap } }
                    Txt { kind: "fine"; x: 50; width: parent.width - 50; text: parent.modelData.detail || "" } } } } }

    // ── passes: one line each, the evidence class first; a click opens the detail ──
    Fold { visible: root.passed.length > 0; key: "prove.passed"; openByDefault: root.open.length === 0 && root.passed.length <= 6
        title: "Passed"; note: root.passed.length + " · " + root.evidenceMix(root.passed)
        Column { x: -8; width: parent.width + 16
            Repeater {
                model: root.passed
                Rectangle {
                    id: pr
                    objectName: "passedCheck"
                    required property var modelData
                    required property int index
                    readonly property bool link: !!(modelData.at || modelData.feature)
                    readonly property bool on: root.shown === index
                    width: parent.width; height: on ? 30 + pd.implicitHeight + 8 : 30; radius: Theme.rSm
                    color: pm.containsMouse || on ? Theme.washHover : "transparent"
                    Behavior on color { Tint {} }
                    // a pass ticks in: the row rises into place and lands with the faintest settle
                    opacity: 0; transform: Translate { id: prIn; y: Theme.shift(Theme.rise) }
                    SequentialAnimation { running: true
                        PauseAnimation { duration: 200 + Math.min(pr.index, 10) * Theme.stagger }
                        ParallelAnimation { Glide { target: pr; property: "opacity"; to: 1; duration: Theme.panel }
                            NumberAnimation { target: prIn; property: "y"; to: 0; duration: Theme.move(Theme.panel + 80); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeSpring } } }
                    Tag { x: 8; y: 7; text: pr.modelData.evidence || "pass"; kind: pr.modelData.evidence ? pr.modelData.evidence : "PASS" }
                    Txt { x: 92; y: 6; width: parent.width - 92 - pv.width - 16; text: pr.modelData.label; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Txt { id: pv; mono: true; font.pixelSize: 12; tone: 2; anchors.right: parent.right; anchors.rightMargin: 8; y: 7
                        text: String(pr.modelData.value === undefined || pr.modelData.value === null ? "" : pr.modelData.value)
                        wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, 128); horizontalAlignment: Text.AlignRight }
                    Txt { id: pd; visible: pr.on; kind: "fine"; x: 92; y: 30; width: parent.width - 100
                        text: (pr.modelData.label.length > 22 ? pr.modelData.label + ". " : "") + (pr.modelData.detail || "") + (pr.link ? " Shown on the part." : "") }
                    MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var was = pr.on              // read first: setting `shown` flips `on` at once
                            root.shown = was ? -1 : pr.index
                            if (!was && pr.link) Store.marker(pr.modelData)
                            else if (was && Store.viewer) Store.viewer.setMarker(null) } }
                }
            }
        }
    }

    // ── orientation ──────────────────────────────────────────
    Fold { title: "Print orientation"; key: "prove.orient"; visible: !!root.ch && !root.model
        note: { var t = root.ch ? root.ch.orientation_table : []
                for (var i = 0; i < t.length; i++) if (root.d && t[i].id === root.d.project.orientation) return t[i].label
                return "" }
        Row { spacing: 6
            Tag { text: "computed" } Txt { kind: "fine"; text: "from the solid, for each way it can lie"; anchors.verticalCenter: parent.verticalCenter } }
        Column { x: -8; width: parent.width + 16
            Item { width: parent.width; height: 22
                Txt { kind: "cap"; x: 8; text: "Lay it"; anchors.verticalCenter: parent.verticalCenter }
                Row { anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                    Repeater { model: ["Height", "On plate", "Overhang", "Ceilings"]
                        Txt { required property string modelData; required property int index; kind: "cap"; text: modelData; width: root.colw[index]; horizontalAlignment: Text.AlignRight; wrapMode: Text.NoWrap } } } }
            Repeater {
                model: root.ch ? root.ch.orientation_table : []
                Rectangle {
                    id: orow
                    required property var modelData
                    readonly property bool on: !!root.d && modelData.id === root.d.project.orientation
                    readonly property color ink: on ? Theme.datum : Theme.ink2
                    width: parent.width; height: 30; radius: Theme.rSm
                    color: on ? Theme.alpha(Theme.datum, 0.07) : om.containsMouse ? Theme.washHover : "transparent"
                    Rectangle { visible: !orow.on; x: 8; width: parent.width - 16; height: 1; color: Theme.rule }
                    Txt { x: 8; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 16 - nums.width - 6
                        text: orow.modelData.label; color: orow.on ? Theme.datum : Theme.ink; font.weight: orow.on ? 600 : 420; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Row { id: nums; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                        Repeater { model: [orow.modelData.height_mm, orow.modelData.contact_mm2, orow.modelData.steep_mm2, orow.modelData.ceiling_mm2]
                            Txt { required property var modelData; required property int index; mono: true; text: F.fmt(modelData, 0); color: orow.ink; width: root.colw[index]; horizontalAlignment: Text.AlignRight; wrapMode: Text.NoWrap } } }
                    MouseArea { id: om; anchors.fill: parent; hoverEnabled: true; cursorShape: orow.on ? Qt.ArrowCursor : Qt.PointingHandCursor
                        onClicked: if (!orow.on && !root.busy) Store.settings({ orientation: orow.modelData.id }) }
                    Tip { show: om.containsMouse && !orow.on; text: "Use this orientation (re-exports the STL and re-slices)" }
                }
            }
        }
        OrientFinder {}
        Txt { kind: "fine"; width: parent.width
            text: "Areas in mm², computed from the solid. Overhang is surface steeper than 45°; ceilings are flat faces that must bridge or be supported. Changing orientation makes the exports, checks and slice stale." }
    }

    // ── slice ────────────────────────────────────────────────
    Sec { visible: !!root.sl && !root.model
        title: root.sl ? "Slice of " + F.pad(root.sl.rev) + (root.plates.length > 1 ? " · " + root.plates.length + " plates" : "") : ""; tag: "simulated"
        Row { width: parent.width; topPadding: 4; bottomPadding: 2
            Repeater {
                model: root.sl ? [
                    { big: F.dur(root.sl.time_s), small: root.plates.length > 1 ? "print time, all plates" : "estimated print time" },
                    { big: F.fmt(root.sl.filament_g, 1) + " g", small: root.plates.length > 1 ? "filament, all plates" : F.fmt(root.sl.filament_mm / 1000, 1) + " m filament" },
                    root.plates.length > 1 ? { big: String(root.plates.length), small: "plates, one after another" }
                        : { big: String(root.sl.layers), small: "layers to " + F.fmt(root.sl.max_z_mm, 1) + " mm" }] : []
                Column { required property var modelData; width: parent.width / 3; spacing: 3
                    Txt { mono: true; font.pixelSize: Theme.tH3; font.weight: 600; font.letterSpacing: -0.3; text: modelData.big; width: parent.width - 8; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Txt { kind: "fine"; text: modelData.small; width: parent.width - 8 } }
            }
        }
        // several plates: the design did not fit one plate (or its parts differ in material); each plate sliced on its own
        Column { visible: root.plates.length > 1; width: parent.width; spacing: 8
            Seg { objectName: "provePlates"; value: Store.plateShown
                model: root.plates.map(function (x) { return { value: x.n, text: "Plate " + x.n } })
                onPicked: function (n) { Store.setPlate(n) } }
            Rectangle { width: parent.width; height: pc.implicitHeight + 20; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                Column { id: pc; x: 12; y: 10; width: parent.width - 24; spacing: 4
                    Item { width: parent.width; height: 20
                        Txt { text: root.pl ? root.pl.parts.map(function (q) { return q.label }).join(", ") : ""; font.weight: 600
                            width: parent.width - pst.width - 10; wrapMode: Text.NoWrap; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
                        Txt { id: pst; mono: true; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                            text: root.pl ? F.dur(root.pl.time_s) + " · " + F.fmt(root.pl.filament_g, 1) + " g · " + root.pl.layers + " layers" : "" } }
                    Txt { kind: "fine"; width: parent.width; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        text: root.pl ? (root.pl.filament || "") + (root.pl.material ? " · " + root.pl.material : "") : "" }
                    Txt { kind: "fine"; tone: 2; width: parent.width; visible: text !== ""
                        text: root.pl ? [root.pl.filament_note || "", root.pl.plate_note || ""].filter(function (x) { return x }).join(" ") : "" } } }
            Txt { kind: "fine"; width: parent.width
                text: "Form Studio laid the parts out from their bounding boxes (computed), " + (root.sl && root.sl.plan ? F.trim(root.sl.plan.spacing_mm) : 6)
                    + " mm apart, one material per plate. Times and grams are the slicer's, per plate and added up." }
        }
        Txt { kind: "fine"; tone: 2; width: parent.width; visible: !!root.sl && !root.plates.length && !!root.sl.material && !!root.sl.material.text
            text: root.sl && root.sl.material ? "Filament: " + root.sl.material.text : "" }
        Flow { spacing: 8; topPadding: 2; width: parent.width
            Btn { objectName: "openInSlicer"; kind: "primary"; icon: "external_link"; text: "Open in " + Store.slicerName
                busyText: "Choosing settings…"; busy: Store.slicerOpenBusy; enabled: !root.busy
                tip: "Choose settings for this part on this printer, slice it for real and open the project in " + Store.slicerName
                onClicked: Store.openInSlicer() }
            Btn { visible: !Store.layers; icon: "play"; text: "Watch it print"; tip: "Play the slicer's toolpaths in 3D (a simulation, not a print)"
                onClicked: Store.simulate({ at: 0, play: true }) }
            Btn { icon: Store.layers ? "arrow_left" : "layers"; text: Store.layers ? "Back to the design" : "Inspect layers"
                onClicked: { if (Store.layers) Store.showLayers(false); else Store.simulate({ mode: "2d", layer: 4 }) } }
            Btn { kind: "quiet"; icon: "download"; text: root.plates.length > 1 ? "Save plate " + Store.plateShown + " 3MF…" : "Save sliced 3MF…"
                visible: !!root.shownSlice && !!root.shownSlice.threemf
                onClicked: { save.selectedFile = Bridge.downloads() + "/" + (root.plates.length > 1 ? Store.pid + "_plate" + Store.plateShown + ".3mf" : root.sl.threemf); Store.ask(save) } } }
        // what Open in <Slicer> chose, one line each, with how it is known
        Fold { objectName: "slicerChoices"; visible: !!Store.slicerOpened; key: "prove.slicerOpen"; openByDefault: true
            title: "Settings chosen for this part"
            note: Store.slicerOpened ? Store.slicerOpened.printer + " · " + F.dur(Store.slicerOpened.time_s) + " · " + F.fmt(Store.slicerOpened.filament_g, 1) + " g" : ""
            Column { width: parent.width; spacing: 6
                Repeater { model: Store.slicerOpened ? Store.slicerOpened.decisions : []
                    Column { required property var modelData; width: parent.width; spacing: 1
                        Item { width: parent.width; height: 18
                            Txt { width: parent.width - dv.width - dt.width - 16; text: parent.parent.modelData.label; font.weight: 550; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                            Txt { id: dv; mono: true; anchors.right: dt.left; anchors.rightMargin: 8; text: String(parent.parent.modelData.value); wrapMode: Text.NoWrap
                                width: Math.min(implicitWidth, parent.width * 0.5); elide: Text.ElideLeft }
                            Tag { id: dt; anchors.right: parent.right; y: 1; text: parent.parent.modelData.evidence } }
                        Txt { kind: "fine"; tone: 2; width: parent.width; text: parent.modelData.why } } }
                Txt { kind: "fine"; width: parent.width
                    text: Store.slicerOpened ? (Store.slicerOpened.settings_in_file ? "Every setting was read back from the project file. " : "Some settings were not found in the project file. ")
                        + "Time and grams are " + Store.slicerOpened.slicer + "'s simulation, not a print." : "" } } }
        Txt { kind: "fine"; width: parent.width
            text: "A slice shows the toolpaths " + ((root.sl && root.sl.slicer_name) || "Bambu Studio") + " would send with these presets. It is not a print: adhesion, warping and fit are only known after printing." }
        Fold { title: "Slice details"; key: "prove.slice"
            note: root.sl ? "supports " + (root.sl.support_used ? "generated" : "none") + " · " + (root.sl.slicer_name || "Bambu Studio") + " " + root.sl.slicer_version : ""
            Column { width: parent.width
                KV { first: true; k: "Supports generated"; value: root.sl ? (root.sl.support_used ? "yes" : "none") : "" }
                KV { k: "Presets"
                    Column { spacing: 2; anchors.verticalCenter: parent.verticalCenter
                        Repeater { model: root.sl ? F.vals(root.sl.presets) : []
                            Txt { required property var modelData; kind: "fine"; tone: 2; text: modelData.name; width: 250; horizontalAlignment: Text.AlignRight
                                wrapMode: Text.NoWrap; elide: Text.ElideLeft } } } }
                KV { k: "Slicer"; value: root.sl ? (root.sl.slicer_name || "Bambu Studio") + " " + root.sl.slicer_version + " · " + root.sl.seconds + "s" : "" }
            }
            Txt { kind: "fine"; width: parent.width
                visible: !!root.sl && (root.sl.plate_warnings || []).length > 0
                text: root.sl ? "Slicer notes: " + root.uniq(root.sl.plate_warnings || []).join(", ") : "" }
            Item { id: plate
                readonly property string pic: root.pl ? (root.pl.thumbnail || "") : (root.sl && (root.sl.images || []).indexOf("plate_1.png") >= 0 ? "plate_1.png" : "")
                visible: !!root.sl && pic !== ""
                width: parent.width
                height: visible ? (img.status === Image.Ready ? Math.round(width * img.sourceSize.height / img.sourceSize.width) : Math.round(width * 0.75)) : 0
                Rectangle { id: mask; anchors.fill: parent; radius: Theme.rMd; visible: false; layer.enabled: true }
                Rectangle { anchors.fill: parent; radius: Theme.rMd; color: Theme.well }
                Image { id: img; anchors.fill: parent; asynchronous: true; fillMode: Image.PreserveAspectFit; mipmap: true
                    source: plate.visible && root.sn ? Store.file("slice/current/" + plate.pic) + "?k=" + root.sn.key : ""
                    layer.enabled: true
                    layer.effect: MultiEffect { maskEnabled: true; maskSource: mask } }
                Rectangle { anchors.fill: parent; radius: Theme.rMd; color: "transparent"; border.width: 1; border.color: Theme.rule2 }
            }
            Txt { kind: "fine"; visible: plate.visible; text: "Plate preview rendered by " + ((root.sl && root.sl.slicer_name) || "Bambu Studio") + "." }
        }
    }

    // ── cost, copies, other materials (CostSection.qml) ──────
    CostSection { sl: root.sl; visible: !root.model }
    // ── every printer you have, sliced for real (PrinterCompare.qml) ──
    PrinterCompare { visible: !root.model && !root.sliceOff }
    Item { width: 1; height: 16 }

    // ── slice: not current ───────────────────────────────────
    // ── Design only: slicing is off for this design, for every design, or no slicer is installed ──
    Sec { title: "Slice"; visible: root.sliceOff
        Note { objectName: "designOnlyNote"; kind: "plain"; title: "Design only"
            text: root.sliceOff ? root.sn.off.text + " Checks, exports, renders and releases work as usual; a release says that it was not sliced." : "" }
        Txt { kind: "fine"; width: parent.width; visible: root.sliceOff && root.sn.off.why !== "project"; text: root.sliceOff ? root.sn.off.how : "" }
        Row { spacing: 8
            Btn { objectName: "sliceOn"; visible: root.sliceOff && root.sn.off.why === "project"; icon: "layers"; text: "Slice this design"
                enabled: !root.busy; onClicked: Store.settings({ design_only: false }) }
            Btn { visible: root.sliceOff && root.sn.off.why === "settings"; icon: "settings"; text: "Turn slicing on"
                enabled: !root.busy; onClicked: Store.designOnlyEverywhere(false) }
            Btn { visible: root.sliceOff && root.sn.off.why === "no_slicer"; icon: "download"; text: "Set up a slicer…"
                onClicked: Store.openSheet("setup") } }
    }
    Sec { title: "Slice"; visible: !root.sl && !root.sliceOff && !root.model
        Note { kind: "red"; visible: !!root.sn && !!root.sn.unavailable; title: "Blocked"; text: root.sn && root.sn.unavailable ? String(root.sn.unavailable) : "" }
        Note { kind: "amber"; visible: !(root.sn && root.sn.unavailable)
            title: root.sliceFailed && root.sn.error ? root.sn.error.message : ""
            text: !root.sn ? "Not sliced yet."
                : root.sliceFailed ? (root.sn.error && root.sn.error.hint || "")
                : root.sn.state === "stale" ? "The last slice was of " + F.pad(root.sn.last_rev) + "; it does not describe " + root.head + "."
                : "Not sliced yet." }
        Row { spacing: 8
            Btn { icon: "layers"; text: root.sliceFailed ? "Try again" : "Slice now"; busyText: "Slicing…"; busy: root.busy
                enabled: !(root.sn && root.sn.unavailable)
                onClicked: Store.run(["geometry", "exports", "checks", "slice"], root.sliceFailed) }
            Btn { kind: "quiet"; icon: "external_link"; text: "Open in " + Store.slicerName; visible: !(root.sn && root.sn.unavailable)
                busyText: "Choosing settings…"; busy: Store.slicerOpenBusy; enabled: !root.busy && !!root.d && !!root.d.exports && !!root.d.exports.files.stl
                tip: "Choose settings for this part, slice it and open the project in " + Store.slicerName; onClicked: Store.openInSlicer() }
            Btn { objectName: "designOnly"; kind: "quiet"; text: "Design only"; enabled: !root.busy
                tip: "Do not slice this design. Checks, exports and release still work; the release says it was not sliced."
                onClicked: Store.settings({ design_only: true }) }
            FixBtn { visible: root.sliceFailed && Store.chatReady && !!Store.chat.available; small: false
                subject: "the slice failed for " + root.head
                details: root.sn && root.sn.error ? "Slicer: " + (Store.slicer.label || "the configured slicer") + "\nError: " + root.sn.error.message
                    + (root.sn.error.hint ? "\nHint: " + root.sn.error.hint : "") : "" } }
    }

    FileDialog {
        id: save
        title: "Save sliced 3MF"; fileMode: FileDialog.SaveFile; nameFilters: ["3MF (*.3mf)"]; defaultSuffix: "3mf"
        currentFolder: Bridge.downloads()
        onAccepted: {
            if (Bridge.save("/projects/" + Store.pid + "/file/slice/current/" + root.shownSlice.threemf, selectedFile)) Bridge.reveal(selectedFile)
            else Store.toast("The sliced 3MF could not be saved.", "Check that the folder is writable and try again.", true)
        }
    }
}
