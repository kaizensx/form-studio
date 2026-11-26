import QtQuick
import "F.js" as F

// Variants board: the head and every named variant side by side, each built by the kernel.
// A variant is a name and a full set of values kept in the project. Size and volume are computed; print time and
// grams appear only for a variant that is a revision with a current slice (simulated); fit yield is modelled.
Column {
    id: vs
    property string title: "Variants"
    property string note: "The head and every named variant, each built by the kernel"
    property int sheetWidth: Theme.sheetXl
    property Item firstFocus: nameField.input
    spacing: 16

    property var board: null             // engine reply: { head, cards, differs, note }
    property var error: null
    property bool busy: false
    property bool nameMissing: false
    readonly property var cards: board ? board.cards : []
    readonly property var differs: board ? board.differs : []
    readonly property bool empty: !!board && cards.length < 2     // only the head: nothing saved yet
    readonly property int cols: Math.max(2, Math.min(3, cards.length))
    readonly property int gap: 12
    readonly property real cardW: Math.floor((width - (cols - 1) * gap) / cols)
    // one camera distance for every card, so sizes compare honestly
    readonly property real frame: Math.max.apply(null, cards.map(function (c) {
        var b = c.metrics ? c.metrics.bbox_mm : null
        return b ? Math.hypot(b[0], b[1], b[2]) / 2 : 12 }).concat([12]))
    readonly property var draftChanges: Store.draftValues
    readonly property bool fromDraft: F.keys(draftChanges).length > 0

    function load() {
        busy = true
        Store.pget("/variants").then(function (r) { var first = !vs.board; vs.board = r; vs.error = null; vs.busy = false
                                                    if (first) Qt.callLater(function () { nameField.input.forceActiveFocus() }) },
                                     function (e) { vs.error = e; vs.busy = false })
    }
    function save() {
        var n = nameField.text.trim()
        if (!n) { nameMissing = true; nameField.input.forceActiveFocus(); Store.toast("Give the variant a name", "For example “Travel version” or “Thick walls”.", true); return }
        var p = Store.saveVariant(n, fromDraft ? draftChanges : null, fromDraft ? "draft" : "revision", noteField.text.trim())
        if (p) p.then(function () { nameField.text = ""; noteField.text = ""; vs.load() })
    }
    function hi(key) { return differs.indexOf(key) >= 0 }
    function accept() { save() }
    Component.onCompleted: load()
    Connections { target: Store; function onDataChanged() { if (!vs.busy) vs.load() } }

    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "boxes"; text: "Compare alternatives"; enabled: !Store.hasDraft
            tip: Store.hasDraft ? "Commit or discard the draft first" : ""; onClicked: Store.openSheet("alternatives") } }
    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { kind: "primary"; icon: "plus"; keys: "Return"; visible: !vs.empty      // with nothing saved the action is in the body
            text: vs.fromDraft ? "Save the draft as a variant" : "Save " + (Store.project ? F.pad(Store.project.head) : "the head") + " as a variant"
            onClicked: vs.save() } }

    // ── save the design on screen ──
    // With variants on the board this is a strip above them. With none it moves into the empty place beside the head
    // (see `slot`), so the sheet has one thing to look at and one thing to do.
    Rectangle { id: strip; visible: !!vs.board && !vs.empty
        width: parent.width; height: stripBody.height + 32; radius: 14; color: Theme.glass
        Item { id: stripBody; x: 16; y: 16; width: parent.width - 32; height: form.implicitHeight } }
    Column { id: form; parent: vs.empty ? slotForm : stripBody; width: parent ? parent.width : 0; spacing: vs.empty ? 12 : 10
        Grid { width: parent.width; columns: vs.empty ? 1 : 2; spacing: 12
            Column { width: vs.empty ? parent.width : 280; spacing: 6
                Txt { kind: "cap"; text: "Name this design" }
                Field { id: nameField; width: parent.width; placeholder: "e.g. Thick walls"; error: vs.nameMissing ? " " : ""
                    onEdited: function (t) { if (t.trim()) vs.nameMissing = false } } }     // Enter: the sheet's accept()
            Column { width: vs.empty ? parent.width : parent.width - 292; spacing: 6
                Txt { kind: "cap"; text: "Note" }
                Field { id: noteField; width: parent.width; placeholder: "Optional" } } }
        Txt { kind: "fine"; width: parent.width; visible: !vs.empty
            text: vs.fromDraft ? "Your open draft (" + F.plural(F.keys(vs.draftChanges).length, "change") + ") is saved as it is. It stays a draft: nothing is committed."
                               : "Saves the current head under a name. To save something different, change parameters first (a draft), or use Compare alternatives." } }

    Note { visible: !!vs.error; kind: "red"; title: vs.error ? vs.error.message || "Could not load the variants" : ""; text: vs.error && vs.error.hint ? vs.error.hint : ""
        Btn { small: true; icon: "refresh_cw"; text: "Try again"; onClicked: vs.load() } }

    // ── the first load ──
    Rectangle { visible: !vs.board && !vs.error; width: parent.width; height: 180; radius: Theme.rMd; color: "transparent"; border.color: Theme.rule
        Column { anchors.centerIn: parent; spacing: 8
            Spinner { size: 18; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { tone: 2; text: "Building each variant…"; anchors.horizontalCenter: parent.horizontalCenter } } }

    Item { width: parent.width; height: grid.height; visible: vs.cards.length > 0
    Grid { id: grid; width: parent.width; columns: vs.cols; spacing: vs.gap
        Repeater { model: vs.cards
            Rectangle { id: card; required property var modelData
                readonly property var c: modelData
                readonly property var m: c.metrics || null
                readonly property bool head: c.id === "@head"
                width: vs.cardW; height: inner.implicitHeight + 28; radius: Theme.rMd
                color: ch.hovered ? Theme.glass2 : Theme.glass
                border.color: card.head ? Theme.alpha(Theme.datum, 0.55) : ch.hovered ? Theme.rule2 : Theme.rule
                Behavior on color { Tint {} }
                HoverHandler { id: ch }
                Column { id: inner; x: 14; y: 14; width: parent.width - 28; spacing: 0
                    Row { height: 18; spacing: 4
                        Tag { visible: card.head; text: "head"; kind: "interface" }
                        Tag { visible: !card.head && card.c.rev !== null && card.c.rev !== undefined; text: card.c.rev ? F.pad(card.c.rev) : ""; kind: "computed" }
                        Tag { visible: !card.head && !card.c.rev; text: "saved draft"; kind: "draft" }
                        Tag { visible: !card.head && !!card.c.is_head; text: "same as head" } }
                    Item { width: 1; height: 8 }
                    Rectangle { width: parent.width; height: 150; radius: 10; color: Theme.plate; clip: true
                        Viewport { id: mini; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; selected: "-"; spin: ch.hovered
                            property bool ready: false
                            opacity: ready ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.slow } }
                            Component.onCompleted: Store.pget("/variants/" + card.c.id + "/view").then(function (v) {
                                v.companions = []; v.assembly = null
                                mini.setModel(v); mini.setView("iso", false)
                                mini.dist = Qt.binding(function () { return vs.frame / Math.sin(13 * Math.PI / 180) * 0.8 })
                                mini.ready = true }, function () {}) }
                        Spinner { visible: !mini.ready && !card.c.error; anchors.centerIn: parent; color: Theme.ink4 }
                        Txt { visible: !!card.c.error; anchors.centerIn: parent; width: parent.width - 20; horizontalAlignment: Text.AlignHCenter; kind: "fine"; color: Theme.signal
                            text: card.c.error ? card.c.error.message : "" } }
                    Item { width: 1; height: 12 }
                    Txt { text: card.c.name; kind: "lead"; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    Item { width: 1; height: 2 }
                    Txt { kind: "fine"; width: parent.width; height: 16; elide: Text.ElideRight; wrapMode: Text.NoWrap
                        text: card.c.note || (card.head ? "The current design" : card.c.by ? "Saved by " + card.c.by : "") }
                    Item { width: 1; height: 8 }
                    // metrics, each with how it is known; a value that differs between cards is highlighted
                    Repeater {
                        model: card.m ? [
                            { k: "Size, mm", v: card.m.bbox_mm.map(function (x) { return F.fmt(x, 1) }).join(" × "), tag: "computed", d: "size" },
                            { k: "Volume", v: F.fmt(card.m.volume_cm3, 1) + " cm³", tag: "computed", d: "volume" },
                            { k: "Filament", v: card.m.slice ? F.fmt(card.m.slice.filament_g, 1) + " g" : "not sliced", tag: card.m.slice ? "simulated" : "", d: "grams" },
                            { k: "Print time", v: card.m.slice ? F.dur(card.m.slice.time_s) : "not sliced", tag: card.m.slice ? "simulated" : "", d: "time" },
                            { k: "Fit yield", v: card.m.fit ? Math.round(card.m.fit.yield * 100) + " %" : "no fit interface", tag: card.m.fit ? "modelled" : "", d: "fit" },
                            { k: "Checks", v: card.m.checks ? card.m.checks.PASS + " pass · " + card.m.checks.WARN + " review · " + card.m.checks.FAIL + " fail" : "not run", tag: "", d: "" }] : []
                        Item { id: mr; required property var modelData; required property int index
                            width: inner.width; height: 28
                            Txt { id: mk; text: mr.modelData.k; tone: 2; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                            Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                                Txt { text: mr.modelData.v; mono: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                                    width: Math.min(implicitWidth, mr.width - mk.width - 12 - (mtag.visible ? mtag.width + 6 : 0)); elide: Text.ElideRight; wrapMode: Text.NoWrap
                                    color: mr.modelData.tag === "" ? Theme.ink3 : vs.hi(mr.modelData.d) && !card.head ? Theme.blueprint : Theme.ink }
                                Tag { id: mtag; visible: mr.modelData.tag !== ""; text: mr.modelData.tag; anchors.verticalCenter: parent.verticalCenter } } } }
                    Item { width: 1; height: 12 }
                    Cap { text: card.head ? "Baseline" : card.c.differences.length ? "Differs from the head" : "No differences"; width: parent.width
                        note: card.head ? "" : card.c.differences.length ? F.plural(card.c.differences.length, "parameter") : "" }
                    Item { width: 1; height: 4 }
                    Repeater { model: card.head ? [] : card.c.differences.slice(0, 6)
                        Delta { required property var modelData; width: inner.width
                            label: modelData.label; from: F.trim(modelData.from); to: F.trim(modelData.to); unit: modelData.unit; tint: Theme.blueprint } }
                    Txt { visible: !card.head && card.c.differences.length > 6; kind: "fine"; text: "and " + (card.c.differences.length - 6) + " more" }
                    Txt { visible: card.head; kind: "fine"; width: parent.width; text: "Every variant is compared with this." }
                    Item { visible: !card.head; width: 1; height: 12 }
                    Row { spacing: 4; visible: !card.head
                        Btn { small: true; icon: "arrow_up"; text: "Promote to head"; enabled: !card.c.is_head && !card.c.error && !Store.hasDraft
                            tip: Store.hasDraft ? "Commit or discard the draft first" : card.c.rev ? "Checks out " + F.pad(card.c.rev) : "Commits these values as a new revision"
                            onClicked: { var p = Store.promoteVariant(card.c.id); if (p) p.then(function () { Store.openSheet(null) }) } }
                        Btn { small: true; kind: "quiet"; icon: "pencil_ruler"; text: "Open as draft"; enabled: !card.c.error && !card.c.is_head
                            onClicked: { Store.openSheet(null); Store.setStage("shape"); Store.loadDraft(card.c.values) } }
                        Btn { small: true; kind: "quiet"; icon: "trash_2"; tip: "Delete this variant (the revisions are not touched)"
                            onClicked: { var p = Store.deleteVariant(card.c.id); if (p) p.then(function () { vs.load() }) } } }
                }
            } } }
        // ── no variants yet: the place the first one will take, with the one thing to do ──
        Rectangle { id: slot; visible: vs.empty; x: vs.cardW + vs.gap; width: vs.cardW; height: grid.height
            radius: Theme.rMd; color: "transparent"; border.color: Theme.rule
            Column { anchors.centerIn: parent; width: Math.min(340, parent.width - 48); spacing: 0
                Icon { name: "copy_plus"; size: 22; color: Theme.ink3 }
                Item { width: 1; height: 16 }
                Txt { kind: "h3"; font.weight: Theme.wSemi; text: "No variants yet"; width: parent.width }
                Item { width: 1; height: 8 }
                Txt { tone: 2; width: parent.width; lineHeight: 1.3
                    text: "A variant is a named set of this design’s values, kept beside the head so the two can be compared and either promoted." }
                Item { width: 1; height: 24 }
                Item { id: slotForm; width: parent.width; height: form.implicitHeight }
                Item { width: 1; height: 16 }
                Btn { kind: "primary"; icon: "plus"; keys: "Return"; objectName: "saveFirstVariant"
                    text: vs.fromDraft ? "Save the draft as a variant" : "Save " + (Store.project ? F.pad(Store.project.head) : "the head") + " as a variant"
                    onClicked: vs.save() }
                Item { width: 1; height: 12 }
                Txt { kind: "fine"; width: parent.width
                    text: vs.fromDraft ? "Your open draft (" + F.plural(F.keys(vs.draftChanges).length, "change") + ") is saved as it is. It stays a draft: nothing is committed."
                                       : "Saves " + (Store.project ? F.pad(Store.project.head) : "the head") + " as it is. For something different, change parameters first, or use Compare alternatives." } } } }
    Txt { kind: "fine"; width: parent.width; visible: !!vs.board; text: vs.board ? vs.board.note : "" }
}
