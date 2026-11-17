import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Stage 01 — Brief. Intent, what is actually known about the object, reference photos, printer context.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var brief: Store.project && Store.project.brief ? Store.project.brief : ({ text: "", references: [] })
    readonly property var refs: (brief.references || []).filter(function (r) { return r.kind !== "part" })
    readonly property var parts: (brief.references || []).filter(function (r) { return r.kind === "part" })
    function size(b) { return [0, 1, 2].map(function (i) { return F.fmt(b[1][i] - b[0][i], 1) }).join(" × ") }
    readonly property var known: Store.recipe ? Store.recipe.params.filter(function (p) { return p.group === "brief" }) : []
    readonly property var sl: Store.slicer || ({ available: false })
    property bool busy: false

    function attach(fileUrl) {
        var data = Bridge.dataUrl(fileUrl)
        if (!data) { Store.toast("Could not read that file", "Use a PNG, JPEG or WebP image.", true); return }
        Store.ppost("/reference", { data: data }).then(function () {
            return Store.refresh()
        }).then(function () {
            Store.toast("Photo attached", "Mark a known length in it to measure from it.")
        }, Store.fail)
    }
    function reread() {
        busy = true
        Store.post("/studio/refresh", {}).then(function () {
            return Store.reloadStudio()
        }).then(function () {
            return Store.refresh()
        }).then(function () {
            root.busy = false; Store.toast("Presets re-read from " + (root.sl.label || "the slicer"))
        }, function (e) { root.busy = false; Store.fail(e) })
    }

    // how the object's dimensions are known: one segment per dimension, coloured by its source
    readonly property var sources: known.map(function (p) {
        var pv = Object.assign({ source: "assumed" }, Store.head && Store.head.provenance[p.key] || {}, Store.draftProv[p.key] || {})
        return { label: p.label, source: pv.source } })
    readonly property int measured: sources.filter(function (x) { return x.source === "measured" }).length
    function mix() {
        var n = ({}), order = ["measured", "specified", "assumed", "photo"]
        sources.forEach(function (x) { n[x.source] = (n[x.source] || 0) + 1 })
        return order.filter(function (k) { return n[k] }).map(function (k) { return n[k] + " " + (k === "photo" ? "from photo" : k) }).join(" · ")
    }
    Column { visible: root.known.length > 0; width: parent.width; topPadding: 14; spacing: 10
        Row { spacing: 10
            Txt { id: big; kind: "hero"; mono: true; wrapMode: Text.NoWrap; text: root.measured + "/" + root.known.length
                color: root.measured === root.known.length ? Theme.pass : Theme.ink }
            Column { anchors.verticalCenter: big.verticalCenter; spacing: 4
                Txt { tone: 2; text: "dimensions of the object measured" }
                Txt { kind: "fine"; text: root.mix() } } }
        Row { width: parent.width; height: 6; spacing: 3
            Repeater { model: root.sources
                Rectangle { required property var modelData
                    width: (parent.width - 3 * (root.sources.length - 1)) / root.sources.length; height: 6; radius: 3
                    color: Theme.alpha(Theme.evidence(modelData.source), modelData.source === "measured" ? 1 : 0.55)
                    Behavior on color { ColorAnimation { duration: Motion.ui } } } } }
    }

    Sec { title: "Intent"
        Area { id: intent; width: parent.width; minLines: 4
            placeholder: "What is it for? Where does it live? What must it hold, clear, or survive?"
            Component.onCompleted: text = root.brief.text || ""
            onBlurred: function (t) { if (Store.project && t !== (root.brief.text || "")) Store.settings({ brief: t }) }
            Connections { target: root
                function onBriefChanged() { if (!intent.area.activeFocus && intent.text !== (root.brief.text || "")) intent.text = root.brief.text || "" } } } }

    Item { width: 1; height: 10 }
    Fold { title: "Answers from the brief"; note: root.brief.preset_title || ""; key: "brief.answers"
        visible: !!root.brief.answers && root.brief.answers.length > 0
        Column { width: parent.width
            Repeater { model: root.brief.answers || []
                KV { required property var modelData; required property int index; first: index === 0
                    k: modelData.label
                    value: modelData.kind === "number" ? F.trim(modelData.value) + " " + modelData.unit : ""
                    sub: modelData.kind === "number" ? "" : String(modelData.value)
                    tag: modelData.source || "" } } }
        Txt { kind: "fine"; width: parent.width; visible: !!root.brief.material
            text: "Template defaults (assumed): " + (root.brief.material || "") + "; " + (root.brief.environment ? root.brief.environment.setting + ", "
                  + root.brief.environment.temperature_c[0] + " to " + root.brief.environment.temperature_c[1] + " °C" : "") + "." } }

    Sec { title: "Known about the object"; note: "value · source · ±1σ"
        visible: root.known.length > 0
        Column { width: parent.width
            Repeater { model: root.known
                ParamRow { required property var modelData; p: modelData; prov: true } } } }

    Fold { title: "Reference photos"; note: root.refs.length ? root.refs.length + " attached" : "none"; key: "brief.photos"; openByDefault: root.refs.length > 0
        Txt { kind: "fine"; width: parent.width
            text: "A photo can give a rough dimension once you mark a known length in it. Form Studio treats photo values as ±0.6 mm or worse and never as a fit-critical measurement." }
        Column { width: parent.width; visible: root.refs.length > 0
            Repeater { model: root.refs
                KV { id: rr; required property var modelData; required property int index; first: index === 0
                    k: modelData.file
                    sub: modelData.scale_mm_per_px ? "scale set · " + F.plural((modelData.measurements || []).length, "measurement") : "no scale yet"
                    Btn { kind: "quiet"; small: true; icon: "ruler"; text: "Measure"; onClicked: Store.openSheet("photo", { ref: rr.modelData }) } } } }
        Btn { text: "Attach photo"; icon: "image"; onClicked: Store.ask(dlg) } }

    Fold { title: "Reference parts"; note: root.parts.length ? root.parts.length + " imported" : "none"; key: "brief.parts"; openByDefault: root.parts.length > 0
        Txt { kind: "fine"; width: parent.width
            text: "A STEP or STL of something the design must fit around, such as a board from its maker. It is drawn in blueprint where its file places it. Designs written as code can cut around it with self.reference(\"name\")." }
        Column { width: parent.width; visible: root.parts.length > 0
            Repeater { model: root.parts
                KV { id: pr; required property var modelData; required property int index; first: index === 0
                    k: modelData.file
                    sub: modelData.format.toUpperCase() + (modelData.volume_mm3 ? " · " + F.fmt(modelData.volume_mm3 / 1000, 2) + " cm³" : "")
                    Txt { mono: true; tone: 2; text: root.size(pr.modelData.bbox) + " mm"; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
                    Tag { text: pr.modelData.evidence || "computed"; anchors.verticalCenter: parent.verticalCenter } } } }
        Btn { text: "Import part…"; icon: "box"; onClicked: Store.ask(partDlg) } }

    Fold { title: "Printer context"; key: "brief.printer"; openByDefault: !root.sl.available
        note: root.sl.available ? root.sl.presets.machine.name : "slicer unavailable"; noteColor: root.sl.available ? Theme.ink3 : Theme.signal
        Tag { visible: !!root.sl.available; text: "specified" }
        Column { width: parent.width; visible: !!root.sl.available
            KV { first: true; k: "Printer"; value: root.sl.available ? root.sl.presets.machine.name : "" }
            KV { k: "Material"; value: root.sl.available ? root.sl.presets.filament.name : "" }
            KV { k: "Process"; value: root.sl.available ? root.sl.presets.process.name : "" }
            KV { k: "Walls · infill · supports"
                value: root.sl.available ? root.sl.summary.walls + " · " + root.sl.summary.infill + " · " + (String(root.sl.summary.supports) === "1" ? "on" : "off") : "" } }
        Txt { kind: "fine"; width: parent.width; visible: !!root.sl.available
            text: root.sl.available ? "Read from " + (root.sl.label || "Bambu Studio") + " " + root.sl.version + " (" + root.sl.source.machine + "). Change the selection there, or pin presets in studio.toml; the slice goes stale when they change." : "" }
        Note { visible: !root.sl.available; kind: "red"; title: "Slicer unavailable"; text: root.sl.reason || "" }
        Row { spacing: 4; x: -8
            Btn { visible: !!root.sl.available; kind: "quiet"; icon: "refresh_cw"; text: root.busy ? "Re-reading…" : "Re-read presets"; enabled: !root.busy
                onClicked: root.reread() }
            // slicer picker (slicer workstream)
            Btn { kind: "quiet"; icon: "printer"; text: "Slicer: " + (root.sl.label || "none") + "…"; onClicked: Store.openSheet("slicer") } } }

    Item { width: 1; height: 20 }

    FileDialog { id: dlg; title: "Attach a reference photo"; nameFilters: ["Images (*.png *.jpg *.jpeg *.webp)"]
        onAccepted: root.attach(selectedFile) }
    FileDialog { id: partDlg; title: "Import a reference part"; nameFilters: ["STEP or STL (*.step *.stp *.stl)"]
        onAccepted: Store.importPart(selectedFile) }
    Connections { target: Store; function onImportPartRequested() { Ws.setOpen("brief.parts", true); Store.ask(partDlg) } }
}
