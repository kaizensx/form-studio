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

    Txt { tone: 2; width: parent.width; topPadding: 12
        text: "Intent and what is actually known. Anything not measured is carried as an assumption all the way to release." }

    Sec { title: "Intent"
        Area { id: intent; width: parent.width; minLines: 4
            placeholder: "What is it for? Where does it live? What must it hold, clear, or survive?"
            Component.onCompleted: text = root.brief.text || ""
            onBlurred: function (t) { if (Store.project && t !== (root.brief.text || "")) Store.settings({ brief: t }) }
            Connections { target: root
                function onBriefChanged() { if (!intent.area.activeFocus && intent.text !== (root.brief.text || "")) intent.text = root.brief.text || "" } } } }

    Sec { title: "Answers from the brief"; note: root.brief.preset_title || ""
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

    Sec { title: "Reference photos"; note: root.refs.length ? root.refs.length + " attached" : ""
        Txt { kind: "fine"; width: parent.width
            text: "A photo can give a rough dimension once you mark a known length in it. FORM treats photo values as ±0.6 mm or worse and never as a fit-critical measurement." }
        Column { width: parent.width; visible: root.refs.length > 0
            Repeater { model: root.refs
                KV { id: rr; required property var modelData; required property int index; first: index === 0
                    k: modelData.file
                    sub: modelData.scale_mm_per_px ? "scale set · " + F.plural((modelData.measurements || []).length, "measurement") : "no scale yet"
                    Btn { kind: "quiet"; small: true; icon: "ruler"; text: "Measure"; onClicked: Store.openSheet("photo", { ref: rr.modelData }) } } } }
        Btn { text: "Attach photo"; icon: "image"; onClicked: dlg.open() } }

    Sec { title: "Reference parts"; note: root.parts.length ? root.parts.length + " imported" : ""
        Txt { kind: "fine"; width: parent.width
            text: "A STEP or STL of something the design must fit around, such as a board from its maker. It is drawn in blueprint where its file places it. Designs written as code can cut around it with self.reference(\"name\")." }
        Column { width: parent.width; visible: root.parts.length > 0
            Repeater { model: root.parts
                KV { id: pr; required property var modelData; required property int index; first: index === 0
                    k: modelData.file
                    sub: modelData.format.toUpperCase() + (modelData.volume_mm3 ? " · " + F.fmt(modelData.volume_mm3 / 1000, 2) + " cm³" : "")
                    Txt { mono: true; tone: 2; text: root.size(pr.modelData.bbox) + " mm"; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
                    Tag { text: pr.modelData.evidence || "computed"; anchors.verticalCenter: parent.verticalCenter } } } }
        Btn { text: "Import part…"; icon: "box"; onClicked: partDlg.open() } }

    Sec { title: "Printer context"; tag: root.sl.available ? "specified" : ""
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
    Connections { target: Store; function onImportPartRequested() { partDlg.open() } }
}
