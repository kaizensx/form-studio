import QtQuick
import "F.js" as F

// Variants board: the head and every named variant side by side, each built by the kernel.
// A variant is a name and a full set of values kept in the project. Size and volume are computed; print time and
// grams appear only for a variant that is a revision with a current slice (simulated); fit yield is modelled.
Column {
    id: vs
    property string title: "Variants"
    property int sheetWidth: 1180
    spacing: 14; bottomPadding: 22

    property var board: null             // engine reply: { head, cards, differs, note }
    property var error: null
    property bool busy: false
    readonly property var cards: board ? board.cards : []
    readonly property var differs: board ? board.differs : []
    readonly property int cols: Math.max(2, Math.min(4, cards.length))
    readonly property real cardW: Math.floor((width - (cols - 1) * 12) / cols)
    // one camera distance for every card, so sizes compare honestly
    readonly property real frame: Math.max.apply(null, cards.map(function (c) {
        var b = c.metrics ? c.metrics.bbox_mm : null
        return b ? Math.hypot(b[0], b[1], b[2]) / 2 : 12 }).concat([12]))
    readonly property var draftChanges: Store.draftValues
    readonly property bool fromDraft: F.keys(draftChanges).length > 0

    function load() {
        busy = true
        Store.pget("/variants").then(function (r) { vs.board = r; vs.error = null; vs.busy = false },
                                     function (e) { vs.error = e; vs.busy = false })
    }
    function save() {
        var n = nameField.text.trim()
        if (!n) { Store.toast("Give the variant a name", "For example “Travel version” or “Thick walls”.", true); return }
        var p = Store.saveVariant(n, fromDraft ? draftChanges : null, fromDraft ? "draft" : "revision", noteField.text.trim())
        if (p) p.then(function () { nameField.text = ""; noteField.text = ""; vs.load() })
    }
    function hi(key) { return differs.indexOf(key) >= 0 }
    Component.onCompleted: load()
    Connections { target: Store; function onDataChanged() { if (!vs.busy) vs.load() } }

    // ── save the design on screen ──
    Row { width: parent.width; spacing: 8
        Field { id: nameField; width: 240; placeholder: "Name, e.g. Thick walls"; onAccepted: vs.save() }
        Field { id: noteField; width: Math.max(160, parent.width - 240 - saveBtn.width - 16); placeholder: "Note (optional)"; onAccepted: vs.save() }
        Btn { id: saveBtn; kind: "primary"; icon: "plus"
            text: vs.fromDraft ? "Save the draft as a variant" : "Save " + (Store.project ? F.pad(Store.project.head) : "the head") + " as a variant"
            onClicked: vs.save() } }
    Txt { kind: "fine"; width: parent.width
        text: vs.fromDraft ? "Your open draft (" + F.plural(F.keys(vs.draftChanges).length, "change") + ") is saved as it is. It stays a draft: nothing is committed."
                           : "Saves the current head under a name. To save something different, change parameters first (a draft), or use Compare alternatives." }

    Note { visible: !!vs.error; kind: "red"; title: vs.error ? vs.error.message || "Could not load the variants" : ""; text: vs.error && vs.error.hint ? vs.error.hint : "" }
    Rectangle { width: parent.width; height: 1; color: Theme.rule }

    Grid { width: parent.width; columns: vs.cols; spacing: 12
        Repeater { model: vs.cards
            Rectangle { id: card; required property var modelData
                readonly property var c: modelData
                readonly property var m: c.metrics || null
                readonly property bool head: c.id === "@head"
                width: vs.cardW; height: inner.implicitHeight + 24; radius: Theme.rMd
                color: Theme.plate1; border.color: card.head ? Theme.alpha(Theme.datum, 0.55) : Theme.rule
                Column { id: inner; x: 12; y: 12; width: parent.width - 24; spacing: 0
                    Row { height: 18; spacing: 5
                        Tag { visible: card.head; text: "head"; kind: "interface" }
                        Tag { visible: !card.head && card.c.rev !== null && card.c.rev !== undefined; text: card.c.rev ? F.pad(card.c.rev) : ""; kind: "computed" }
                        Tag { visible: !card.head && !card.c.rev; text: "saved draft"; kind: "draft" }
                        Tag { visible: !card.head && !!card.c.is_head; text: "same as head" } }
                    Item { width: 1; height: 6 }
                    Rectangle { width: parent.width; height: 150; radius: Theme.rSm; color: Theme.plate; clip: true
                        Viewport { id: mini; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; selected: "-"; spin: cm.containsMouse
                            property bool ready: false
                            opacity: ready ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.slow } }
                            Component.onCompleted: Store.pget("/variants/" + card.c.id + "/view").then(function (v) {
                                v.companions = []; v.assembly = null
                                mini.setModel(v); mini.setView("iso", false)
                                mini.dist = Qt.binding(function () { return vs.frame / Math.sin(13 * Math.PI / 180) * 0.8 })
                                mini.ready = true }, function () {}) }
                        Txt { visible: !!card.c.error; anchors.centerIn: parent; width: parent.width - 20; horizontalAlignment: Text.AlignHCenter; kind: "fine"; color: Theme.signal
                            text: card.c.error ? card.c.error.message : "" }
                        MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true } }
                    Item { width: 1; height: 10 }
                    Txt { text: card.c.name; font.weight: 600; font.pixelSize: 15; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
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
                            width: inner.width; height: 26
                            Rectangle { visible: mr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                            Txt { text: mr.modelData.k; tone: 2; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                            Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                                Txt { text: mr.modelData.v; mono: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                                    color: mr.modelData.tag === "" ? Theme.ink3 : vs.hi(mr.modelData.d) && !card.head ? Theme.blueprint : Theme.ink }
                                Tag { visible: mr.modelData.tag !== ""; text: mr.modelData.tag; anchors.verticalCenter: parent.verticalCenter } } } }
                    Item { width: 1; height: 10 }
                    Cap { text: card.head ? "Baseline" : card.c.differences.length ? "Differs from the head" : "No differences"; width: parent.width
                        note: card.head ? "" : card.c.differences.length ? F.plural(card.c.differences.length, "parameter") : "" }
                    Item { width: 1; height: 4 }
                    Repeater { model: card.head ? [] : card.c.differences.slice(0, 6)
                        Delta { required property var modelData; width: inner.width
                            label: modelData.label; from: F.trim(modelData.from); to: F.trim(modelData.to); unit: modelData.unit; tint: Theme.blueprint } }
                    Txt { visible: !card.head && card.c.differences.length > 6; kind: "fine"; text: "and " + (card.c.differences.length - 6) + " more" }
                    Txt { visible: card.head; kind: "fine"; width: parent.width; text: "Every variant is compared with this." }
                    Item { width: 1; height: 12 }
                    Row { spacing: 4; x: -4; visible: !card.head
                        Btn { small: true; icon: "arrow_up"; text: "Promote to head"; enabled: !card.c.is_head && !card.c.error && !Store.hasDraft
                            tip: Store.hasDraft ? "Commit or discard the draft first" : card.c.rev ? "Checks out " + F.pad(card.c.rev) : "Commits these values as a new revision"
                            onClicked: { var p = Store.promoteVariant(card.c.id); if (p) p.then(function () { Store.openSheet(null) }) } }
                        Btn { small: true; kind: "quiet"; icon: "pencil_ruler"; text: "Open as draft"; enabled: !card.c.error && !card.c.is_head
                            onClicked: { Store.openSheet(null); Store.setStage("shape"); Store.loadDraft(card.c.values) } }
                        Btn { small: true; kind: "quiet"; icon: "trash_2"; tip: "Delete this variant (the revisions are not touched)"
                            onClicked: { var p = Store.deleteVariant(card.c.id); if (p) p.then(function () { vs.load() }) } } }
                }
            } } }
    Txt { visible: !!vs.board && vs.cards.length < 2; tone: 2; width: parent.width
        text: "No variants yet. Name the current design above, or save a candidate from Compare alternatives." }
    Row { spacing: 8
        Btn { kind: "quiet"; icon: "boxes"; text: "Compare alternatives"; enabled: !Store.hasDraft; onClicked: Store.openSheet("alternatives") }
        Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: vs.board ? vs.board.note : "Building each variant…"; width: vs.width - 190 } }
}
