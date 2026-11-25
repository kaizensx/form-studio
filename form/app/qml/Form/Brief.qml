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
    readonly property var meshes: parts.filter(function (r) { return r.format !== "step" }).map(function (r) { return r.file })
    readonly property var recon: Store.project && Store.project.reconstruction ? (Store.project.reconstruction.summary || null) : null
    function size(b) { return [0, 1, 2].map(function (i) { return F.fmt(b[1][i] - b[0][i], 1) }).join(" × ") }
    // where a reference came from and under which licence. The engine keeps it per attachment as `source`: a link, or
    // { url, site, title, author, licence } (form/conversations.py sources); older rows may carry licence beside it.
    function origin(r) {
        if (!r) return ""
        var s = r.source, o = s && typeof s === "object" ? s : ({ url: s ? String(s) : "" }), out = []
        var url = String(o.url || ""), m = url.match(/^https?:\/\/([^\/?#]+)/i)
        var site = o.site || (m ? m[1].replace(/^www\./, "") : url)
        if (site) out.push("from " + site + (o.author ? " by " + o.author : ""))
        var lic = o.licence || o.license || r.licence || r.license
        if (lic) out.push(String(lic))
        return out.join(" · ")
    }
    readonly property var known: Store.recipe ? Store.recipe.params.filter(function (p) { return p.group === "brief" }) : []
    // the printer this design uses (its own choice, the default, or the slicer's selection: form/printers.py)
    readonly property var pr: Store.data && Store.data.printer ? Store.data.printer : null
    readonly property var sl: pr ? pr.slicer : (Store.slicer || ({ available: false }))
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

    // what the design is for (form/purpose.py): a print is checked against a printer and sliced; a model is not
    // with 3D printing off every design is a 3D model: only how it will be made is asked
    Sec { id: purposeSec; title: "Purpose"; objectName: "briefPurpose"
        readonly property var pu: Store.data && Store.data.purpose ? Store.data.purpose : ({ purpose: "print" })
        Seg { objectName: "purposeSeg"; value: purposeSec.pu.purpose; enabled: !Store.job
            model: (Store.printOn || purposeSec.pu.purpose === "print" ? [{ value: "print", text: "For 3D printing" }] : [])
                   .concat([{ value: "model", text: "Just a 3D model" }, { value: "game", text: "Game asset", badge: "Beta",
                              tip: "In Beta: game assets work end to end, and their visual quality is still improving." }])
            onPicked: function (v) { if (v !== Store.purpose) Store.setPurpose(v) } }
        Txt { kind: "fine"; width: parent.width
            text: purposeSec.pu.purpose === "game"
                ? "For a game engine: levels of detail at triangle budgets, UVs, baked base colour, normal, ORM and AO maps, and collision, exported for Godot, Unity or Unreal. Not sliced; print checks do not apply. The design stays the CAD it is made from. In Beta: visual quality is still improving."
                : purposeSec.pu.purpose === "model"
                ? "For rendering, CAD exchange, CNC, laser cutting, moulding or visualisation. No printer or slicer is used; print checks such as overhangs, plate contact and the build volume do not apply. Releases carry STEP, STL, 3MF, OBJ, GLB and rendered views."
                : "Checked against your printer (build volume, walls for the nozzle, overhangs, plate contact) and sliced when a slicer is installed." }
        Btn { objectName: "briefGame"; visible: purposeSec.pu.purpose === "game"; small: true; icon: "gamepad_2"; text: "Game asset…"; onClicked: Store.openSheet("game") }
        Row { visible: purposeSec.pu.purpose === "model"; spacing: 10
            Txt { text: "Made by"; tone: 2; anchors.verticalCenter: parent.verticalCenter }
            Pick { objectName: "processPick"; width: 260; value: purposeSec.pu.process || ""
                model: Store.purposeInfo.processes.map(function (x) { return { value: x.id, text: x.label + (x.min_feature_mm ? "  · min " + x.min_feature_mm + " mm" : "") } })
                onPicked: function (v) { Store.setPurpose("model", v) } } }
        Txt { kind: "fine"; width: parent.width; visible: purposeSec.pu.purpose === "model"
            text: "Naming the process lets the checks flag features thinner than it usually holds (a rule of thumb)." } }

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
                    sub: (modelData.scale_mm_per_px ? "scale set · " + F.plural((modelData.measurements || []).length, "measurement") : "no scale yet") + (root.origin(modelData) ? " · " + root.origin(modelData) : "")
                    Btn { kind: "quiet"; small: true; icon: "ruler"; text: "Measure"; onClicked: Store.openSheet("photo", { ref: rr.modelData }) } } } }
        Btn { text: "Attach photo"; icon: "image"; onClicked: Store.ask(dlg) } }

    Fold { title: "Reference parts"; note: root.parts.length ? root.parts.length + " imported" : "none"; key: "brief.parts"; openByDefault: root.parts.length > 0
        Txt { kind: "fine"; width: parent.width
            text: "A STEP or STL of something the design must fit around, such as a board from its maker. It is drawn in blueprint where its file places it. Designs written as code can cut around it with self.reference(\"name\")." }
        Column { width: parent.width; visible: root.parts.length > 0
            Repeater { model: root.parts
                KV { id: pr; required property var modelData; required property int index; first: index === 0
                    k: modelData.file
                    sub: modelData.format.toUpperCase() + (modelData.volume_mm3 ? " · " + F.fmt(modelData.volume_mm3 / 1000, 2) + " cm³" : "") + (root.origin(modelData) ? " · " + root.origin(modelData) : "")
                    Txt { mono: true; tone: 2; text: root.size(pr.modelData.bbox) + " mm"; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
                    Tag { text: pr.modelData.evidence || "computed"; anchors.verticalCenter: parent.verticalCenter }
                    Btn { kind: "quiet"; small: true; icon: "box"; text: "Make editable"; visible: pr.modelData.format !== "step"
                          anchors.verticalCenter: parent.verticalCenter; onClicked: Store.makeEditable(pr.modelData.file) } } } }
        // the deterministic reconstruction did not reach a verified feature recipe: say so, and offer the agent remodel
        Txt { kind: "fine"; width: parent.width; tone: 2; visible: root.recon !== null && !root.recon.recipe_verified
              text: root.recon ? "Make editable reached Layer " + root.recon.layer + " (" + F.fmt(root.recon.frozen_area_pct, 0)
                                 + "% frozen facets, no verified feature recipe). Rebuild as editable CAD has the agent model it again "
                                 + "with named features and Params, compared with the mesh until it is within 0.1 mm." : "" }
        Row { spacing: 8
            Btn { text: "Import part…"; icon: "box"; onClicked: Store.ask(partDlg) }
            Btn { objectName: "rebuildCad"; text: "Rebuild as editable CAD"; icon: "sparkles"; visible: root.meshes.length > 0
                  kind: root.recon !== null && !root.recon.recipe_verified ? "primary" : "default"
                  onClicked: Store.rebuildAsCad(root.meshes) } } }

    Fold { title: "Printer context"; key: "brief.printer"; openByDefault: !root.sl.available && Store.prints
        visible: Store.printUi                         // a 3D model, or printing off: no printer
        note: root.sl.available ? root.sl.presets.machine.name : Store.prints ? "no slicer" : "no printer"; noteColor: root.sl.available || !Store.prints ? Theme.ink3 : Theme.amber
        Tag { visible: !!root.sl.available; text: "specified" }
        Column { width: parent.width; visible: !!root.sl.available
            KV { first: true; k: "Printer"; value: root.sl.available ? root.sl.presets.machine.name : "" }
            KV { k: "Material"; value: root.sl.available ? root.sl.presets.filament.name : "" }
            KV { k: "Process"; value: root.sl.available ? root.sl.presets.process.name : "" }
            KV { k: "Walls · infill · supports"
                value: root.sl.available ? root.sl.summary.walls + " · " + root.sl.summary.infill + " · " + (String(root.sl.summary.supports) === "1" ? "on" : "off") : "" } }
        Txt { kind: "fine"; width: parent.width; visible: !!root.sl.available
            text: !root.sl.available ? "" : root.pr && root.pr.source !== "slicer"
                ? "Presets from " + (root.sl.label || "the slicer") + " " + (root.sl.version || "") + ", chosen as " + (root.pr.source === "project" ? "this design's printer" : "the default printer") + " in Form Studio. Bed " + root.pr.env.envelope.map(function (x) { return F.fmt(x, 0) }).join(" × ") + " mm. The slice goes stale when they change."
                : "Read from " + (root.sl.label || "Bambu Studio") + " " + root.sl.version + " (" + root.sl.source.machine + "). Choose another printer below, or change the selection there; the slice goes stale when it changes." }
        Note { visible: !root.sl.available; kind: Store.prints ? "amber" : "plain"; title: Store.prints ? "No slicer" : "No printer"
            text: Store.prints ? (root.sl.reason || "") + " Checks use the bed size in Settings › Printing until one is set up."
                : "3D printing is off, so this design is checked against the bed size in Settings and not sliced. To make it a 3D model instead, choose “Just a 3D model” above." }
        Row { spacing: 4; x: -8
            Btn { visible: !!root.sl.available; kind: "quiet"; icon: "refresh_cw"; text: root.busy ? "Re-reading…" : "Re-read presets"; enabled: !root.busy
                onClicked: root.reread() }
            // slicer picker (slicer workstream)
            Btn { objectName: "briefPrinter"; kind: "quiet"; icon: "printer"; text: "Printer…"; tip: "Every printer in your slicers; pick one for this design"
                onClicked: Store.openSheet("printer") }
            Btn { kind: "quiet"; icon: "settings"; text: "Slicer: " + (root.sl.label || "none") + "…"; onClicked: Store.openSheet("slicer") } } }

    Item { width: 1; height: 20 }

    FileDialog { id: dlg; title: "Attach a reference photo"; nameFilters: ["Images (*.png *.jpg *.jpeg *.webp)"]
        onAccepted: root.attach(selectedFile) }
    FileDialog { id: partDlg; title: "Import a reference part"; nameFilters: ["STEP or mesh (*.step *.stp *.stl *.obj *.3mf)"]
        onAccepted: Store.importPart(selectedFile) }
    Connections { target: Store; function onImportPartRequested() { Ws.setOpen("brief.parts", true); Store.ask(partDlg) } }
}
