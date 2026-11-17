import QtQuick
import FormNative
import "F.js" as F

// The printer a design is made for: every printer set up in every installed slicer (form/printers.py), with the
// filament and process to slice with. "Use for this design" stores the choice in the project; "Make default"
// writes it to studio.toml (after a backup) for every design without its own choice. Slicing, the bed size and
// the nozzle in the checks follow it; the slicer's own files are only read.
Column {
    id: ps
    objectName: "printerSheet"
    property string title: "Printer"
    property string note: Store.pid ? "Printer, filament and process for this design" : "The printer new designs use"
    property int sheetWidth: Theme.sheetL
    property var inv: null                    // GET /printers → { printers, slicers, default, project }
    property var error: null
    property bool loading: false
    property string busy: ""                  // "project" | "default" | "clear"
    property var pick: null                   // the printer row chosen in the list
    property var opts: null                   // GET /printers/options for `pick`
    property bool optsLoading: false
    property string filament: ""
    property string process: ""
    readonly property var current: inv && inv.project ? inv.project : null
    readonly property var groups: {
        if (!inv) return []
        return inv.slicers.filter(function (s) { return s.installed }).map(function (s) {
            return { slicer: s, rows: inv.printers.filter(function (p) { return p.kind === s.kind }) } })
    }
    readonly property var notInstalled: inv ? inv.slicers.filter(function (s) { return !s.installed }) : []
    spacing: 16

    function idOf(c) { return c ? c.kind + ":" + c.machine : "" }
    function load(refresh) {
        loading = true
        Store.get("/printers" + (Store.pid ? "?project=" + Store.pid : "?") + (refresh ? "&refresh=1" : "")).then(function (r) {
            ps.inv = r; ps.error = null; ps.loading = false
            if (!ps.pick) {
                var want = ps.current && ps.current.choice ? ps.idOf(ps.current.choice) : r.default ? ps.idOf(r.default) : ""
                var row = r.printers.filter(function (p) { return p.id === want })[0]
                    || r.printers.filter(function (p) { return p.selected && ps.current && p.kind === ps.current.slicer.kind })[0]
                if (row) ps.choose(row, ps.current && ps.current.choice && ps.idOf(ps.current.choice) === row.id ? ps.current.choice : null)
            }
        }, function (e) { ps.error = e; ps.loading = false })
    }
    function choose(row, keep) {
        pick = row; opts = null; optsLoading = true
        filament = keep ? keep.filament : row.filament; process = keep ? keep.process : row.process
        Store.get("/printers/options?kind=" + encodeURIComponent(row.kind) + "&machine=" + encodeURIComponent(row.name)).then(function (o) {
            if (!ps.pick || ps.pick.id !== row.id) return
            ps.opts = o; ps.optsLoading = false
            if (!ps.filament) ps.filament = o.default_filament
            if (!ps.process) ps.process = o.default_process
        }, function (e) { ps.optsLoading = false; Store.fail(e) })
    }
    function names(list, have) {
        var out = (list || []).map(function (r) { return { value: r.name, text: r.name + (r.source === "user" ? "  · yours" : "") + (r.checked ? "" : "  · not checked") } })
        if (have && !out.some(function (o) { return o.value === have })) out.unshift({ value: have, text: have })
        return out
    }
    function use(where) {
        if (where !== "clear" && !pick) return
        busy = where
        var body = where === "clear" ? { project: Store.pid, clear: true }
            : { kind: pick.kind, machine: pick.name, filament: filament, process: process }
        if (where === "default") body["default"] = true
        else if (where === "project") body.project = Store.pid
        Store.post("/printers/use", body).then(function (r) {
            return Store.reloadStudio().then(function () { return Store.pid ? Store.refresh() : null }).then(function () {
                ps.busy = ""; ps.load(false)
                Store.toast(where === "clear" ? "This design follows the default printer again"
                            : where === "default" ? "Default printer: " + ps.pick.name : "Printer for this design: " + ps.pick.name,
                            where === "default" ? "Saved in studio.toml" + (r.backup ? " (backup kept)." : ".") : "The slice and checks follow it on the next run.")
            })
        }, function (e) { ps.busy = ""; Store.fail(e) })
    }
    function size(e) { return e ? e.map(function (x) { return F.fmt(x, 0) }).join(" × ") + " mm" : "" }
    Component.onCompleted: load(false)

    property Component footerLeft: Row { spacing: 8
        Btn { visible: !!ps.current && ps.current.source === "project"; kind: "quiet"; icon: "rotate_ccw"; text: "Use the default"
            busy: ps.busy === "clear"; enabled: ps.busy === ""; tip: "Forget this design's own printer"; onClicked: ps.use("clear") }
        Btn { kind: "quiet"; icon: "refresh_cw"; text: "Look again"; busy: ps.loading; enabled: ps.busy === ""; onClicked: { ps.pick = null; ps.load(true) } } }
    property Component footer: Row { spacing: 8
        Btn { objectName: "printerMakeDefault"; kind: Store.pid ? "default" : "primary"; icon: "pin"; text: "Make default"
            enabled: !!ps.pick && !!ps.opts && ps.busy === ""; busy: ps.busy === "default"
            tip: "Every design without its own printer uses this one"; onClicked: ps.use("default") }
        Btn { objectName: "printerUseHere"; visible: !!Store.pid; kind: "primary"; icon: "check"; text: "Use for this design"; keys: "Return"
            enabled: !!ps.pick && !!ps.opts && ps.busy === ""; busy: ps.busy === "project"; onClicked: ps.use("project") } }
    function accept() { if (Store.pid && pick && opts && busy === "") use("project") }

    // what this design uses now
    Rectangle { visible: !!ps.current; width: parent.width; height: now.implicitHeight + 24; radius: Theme.rMd
        color: Theme.plate1; border.color: Theme.rule
        Column { id: now; x: 16; y: 12; width: parent.width - 32; spacing: 3
            Row { spacing: 8
                Icon { name: "printer"; size: 15; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
                Txt { font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter
                    text: !ps.current ? "" : ps.current.slicer.available ? ps.current.slicer.presets.machine.name : "No printer can be used yet" }
                Tag { anchors.verticalCenter: parent.verticalCenter
                    text: !ps.current ? "" : ps.current.source === "project" ? "this design" : ps.current.source === "default" ? "default" : "slicer selection" } }
            Txt { kind: "fine"; width: parent.width; visible: !!ps.current && ps.current.slicer.available
                text: ps.current && ps.current.slicer.available ? ps.current.slicer.presets.filament.name + "  ·  " + ps.current.slicer.presets.process.name
                      + "  ·  " + (ps.current.slicer.label || "") + "  ·  bed " + ps.size(ps.current.env.envelope) : "" }
            Txt { kind: "fine"; width: parent.width; visible: !!ps.current && !ps.current.slicer.available; color: Theme.amber
                text: ps.current ? ps.current.slicer.reason || "" : "" } } }

    // filament and process for the chosen printer
    Rectangle { visible: !!ps.pick; width: parent.width; height: fp.implicitHeight + 28; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
        Column { id: fp; x: 16; y: 14; width: parent.width - 32; spacing: 10
            Txt { font.weight: Theme.wSemi; text: ps.pick ? "Slice on " + ps.pick.name : "" }
            Row { spacing: 8; visible: ps.optsLoading
                Spinner { size: 12; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Reading its filaments and processes…"; anchors.verticalCenter: parent.verticalCenter } }
            Grid { visible: !!ps.opts; columns: 2; columnSpacing: 12; rowSpacing: 8; width: parent.width
                Txt { text: "Filament"; tone: 2; width: 70; height: Theme.hMd; verticalAlignment: Text.AlignVCenter }
                Pick { objectName: "printerFilament"; width: fp.width - 82; model: ps.opts ? ps.names(ps.opts.filaments, ps.filament) : []; value: ps.filament
                    onPicked: function (v) { ps.filament = v } }
                Txt { text: "Process"; tone: 2; width: 70; height: Theme.hMd; verticalAlignment: Text.AlignVCenter }
                Pick { objectName: "printerProcess"; width: fp.width - 82; model: ps.opts ? ps.names(ps.opts.processes, ps.process) : []; value: ps.process
                    onPicked: function (v) { ps.process = v } } }
            Txt { kind: "fine"; width: parent.width; visible: !!ps.opts
                text: ps.opts ? F.plural(ps.opts.filaments.length, "filament") + " and " + (ps.opts.processes.length === 1 ? "1 process" : ps.opts.processes.length + " processes")
                      + " in " + ps.opts.slicer + " fit this printer. The slicer's own files are only read, never changed." : "" } } }

    Row { visible: !ps.inv && !ps.error; spacing: 8; height: 40
        Spinner { anchors.verticalCenter: parent.verticalCenter }
        Txt { tone: 2; text: "Reading the printers in your slicers…"; anchors.verticalCenter: parent.verticalCenter } }
    Note { visible: !!ps.error; kind: "red"; title: ps.error ? ps.error.message || "Could not read the printers" : ""
        text: ps.error && ps.error.hint ? ps.error.hint : "Nothing was changed." }
    Note { visible: !!ps.inv && ps.inv.printers.length === 0; kind: "amber"; title: "No printers found"
        text: "Open your slicer once and add your printer there; Form Studio reads it from the slicer's own settings." }

    // every printer, grouped by slicer
    Repeater { model: ps.groups
        Column { id: grp; required property var modelData; width: ps.width; spacing: 6; visible: grp.modelData.rows.length > 0 || !!grp.modelData.slicer.reason
            Row { spacing: 8
                Txt { kind: "cap"; text: grp.modelData.slicer.label }
                Txt { kind: "fine"; text: grp.modelData.rows.length ? F.plural(grp.modelData.rows.length, "printer") : "" } }
            Txt { visible: grp.modelData.rows.length === 0; kind: "fine"; width: parent.width; text: grp.modelData.slicer.reason }
            Rectangle { visible: grp.modelData.rows.length > 0; width: parent.width; height: list.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule; clip: true
                Column { id: list; width: parent.width
                    Repeater { model: grp.modelData.rows
                        Rectangle { id: pr; required property var modelData; required property int index
                            objectName: "printerRow"; readonly property string pid_: modelData.id
                            readonly property bool on: !!ps.pick && ps.pick.id === modelData.id
                            width: list.width; height: 48
                            color: on ? Theme.alpha(Theme.datum, 0.07) : ph.hovered ? Theme.plate3 : "transparent"
                            Behavior on color { Tint {} }
                            Rectangle { visible: pr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                            HoverHandler { id: ph }
                            MouseArea { anchors.fill: parent; enabled: ps.busy === ""; onClicked: ps.choose(pr.modelData, null) }
                            Rectangle { x: 16; width: 16; height: 16; radius: 8; anchors.verticalCenter: parent.verticalCenter
                                color: "transparent"; border.width: pr.on ? 5 : 1.5; border.color: pr.on ? Theme.datum : Theme.rule3
                                Behavior on border.width { NumberAnimation { duration: Theme.fast } } }
                            Column { x: 44; width: parent.width - 44 - 190; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                Txt { width: parent.width; text: pr.modelData.name; font.weight: pr.on ? Theme.wSemi : Theme.wMedium; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                Txt { width: parent.width; kind: "fine"; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                    text: (pr.modelData.source === "user" ? "Your preset" : "System printer") + (pr.modelData.model ? " · " + pr.modelData.model : "")
                                          + (pr.modelData.selected ? " · selected in " + pr.modelData.slicer : "") } }
                            Row { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                                Txt { mono: true; kind: "fine"; text: pr.modelData.nozzle_mm ? F.fmt(pr.modelData.nozzle_mm, 1) + " mm nozzle" : ""; anchors.verticalCenter: parent.verticalCenter }
                                Txt { mono: true; kind: "fine"; tone: 2; text: ps.size(pr.modelData.envelope_mm); anchors.verticalCenter: parent.verticalCenter } } } } } } } }

    Txt { kind: "fine"; width: parent.width; visible: ps.notInstalled.length > 0
        text: "Not installed here: " + ps.notInstalled.map(function (s) { return s.label }).join(", ") + ". Add one under Settings, Software." }
}
