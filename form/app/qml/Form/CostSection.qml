import QtQuick
import "F.js" as F

// Prove → Cost. What the sliced plate would cost in filament, electricity and machine time, what N copies would,
// and the same volume in other materials. Grams and hours are the slicer's simulation; prices are yours
// (or the one in the slicer's filament preset). Nothing is assumed: an unknown price shows as "set a price".
Column {
    id: root
    width: parent ? parent.width : 0
    spacing: 0
    property var sl: null                     // the current slice (Store.data.slice)
    property var c: null                      // the engine's cost reply
    property int copies: 1
    readonly property string cur: c && c.currency ? " " + c.currency : ""
    readonly property string sliceKey: sl ? String(sl.gcode_sha256 || sl.rev) : ""
    function has(v) { return v !== null && v !== undefined }
    function money(v) { return v === null || v === undefined ? "" : F.fmt(v, 2) + cur }
    function num(v) { return v === null || v === undefined ? "" : F.trim(v, 3) }
    function load() {
        if (!sl) { c = null; return }
        var key = sliceKey
        Store.pget("/cost?copies=" + copies).then(function (r) { if (root && root.sliceKey === key) root.c = r }, function () {})
    }
    function save(body) {
        body.copies = copies
        Store.ppost("/cost", body).then(function (r) { if (root) root.c = r }, Store.fail)
    }
    function parse(t) { t = String(t).trim().replace(",", "."); return t === "" ? null : parseFloat(t) }
    function set(key, text, was) {            // a field was left: save only a real change
        var v = parse(text)
        if (v !== null && (isNaN(v) || v < 0)) { Store.toast("That is not a number.", "Use digits, for example 24.50.", true); return }
        if (v === was || (v === null && (was === null || was === undefined))) return
        var b = {}; b[key] = v
        if (key === "price_per_kg") b.filament_type = c.filament.filament_type || ""
        save(b)
    }
    onSliceKeyChanged: load()
    Component.onCompleted: load()

    Sec { visible: !!root.c
        title: "Cost"
        Row { spacing: 6
            Tag { text: "simulated" } Txt { kind: "fine"; text: "grams, hours"; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; text: "×"; anchors.verticalCenter: parent.verticalCenter }
            Tag { text: "specified" } Txt { kind: "fine"; text: "prices, power"; anchors.verticalCenter: parent.verticalCenter } }
        Txt { kind: "fine"; width: parent.width
            text: "Grams and hours are the slicer's simulation. Prices and power are yours; FORM does not guess them." }

        // ── what you tell it ─────────────────────────────────
        Column { width: parent.width
            KV { first: true; k: "Filament price"
                sub: !root.c ? "" : root.c.filament.price_source ? (root.c.filament.filament_type || "") + " · " + root.c.filament.price_source
                                                               : "Not known for " + (root.c.filament.filament_type || "this filament")
                Field { width: 112; numeric: true; unit: "/ kg"; placeholder: "set a price"
                    text: root.c ? root.num(root.c.filament.price_per_kg) : ""
                    onAccepted: function (t) { root.set("price_per_kg", t, root.c.filament.price_per_kg) } }
                Tag { text: "specified"; visible: !!root.c && root.has(root.c.filament.price_per_kg); anchors.verticalCenter: parent.verticalCenter } }
            KV { k: "Printer power"; sub: "Average draw while printing"
                Field { width: 112; numeric: true; unit: "W"; placeholder: "not set"
                    text: root.c ? root.num(root.c.electricity.watts) : ""
                    onAccepted: function (t) { root.set("watts", t, root.c.electricity.watts) } } }
            KV { k: "Electricity price"
                Field { width: 112; numeric: true; unit: "/ kWh"; placeholder: "not set"
                    text: root.c ? root.num(root.c.electricity.kwh_price) : ""
                    onAccepted: function (t) { root.set("kwh_price", t, root.c.electricity.kwh_price) } } }
            KV { k: "Machine rate"; sub: "Optional: what an hour of the printer is worth to you"
                Field { width: 112; numeric: true; unit: "/ h"; placeholder: "not set"
                    text: root.c ? root.num(root.c.machine.rate_per_h) : ""
                    onAccepted: function (t) { root.set("machine_rate_per_h", t, root.c.machine.rate_per_h) } } }
            KV { k: "Currency"; sub: "Only a label; nothing is converted"
                Field { width: 112; placeholder: "none"; text: root.c ? root.c.currency : ""
                    onAccepted: function (t) { if (t.trim() !== root.c.currency) root.save({ currency: t.trim() }) }
                    input.onActiveFocusChanged: if (!input.activeFocus && root.c && text.trim() !== root.c.currency) root.save({ currency: text.trim() }) } }
        }

        // ── what it comes to ─────────────────────────────────
        Rectangle { width: parent.width; height: res.implicitHeight + 20; radius: Theme.rMd; color: Theme.plate2
            Column { id: res; x: 12; y: 10; width: parent.width - 24; spacing: 0
                Repeater {
                    model: !root.c ? [] : [
                        { k: "Filament", how: F.fmt(root.c.filament.grams, 1) + " g", v: root.c.filament.cost, need: "set a price" },
                        { k: "Electricity", how: root.has(root.c.electricity.kwh) ? F.fmt(root.c.electricity.kwh, 2) + " kWh" : F.dur(root.sl.time_s), v: root.c.electricity.cost, need: "set power and price" },
                        { k: "Machine time", how: F.dur(root.sl.time_s), v: root.c.machine.cost, need: "no rate set" }]
                    Item { required property var modelData; required property int index
                        width: parent.width; height: 26
                        Txt { text: modelData.k; tone: 2; anchors.verticalCenter: parent.verticalCenter }
                        Txt { x: 108; mono: true; font.pixelSize: 12; tone: 3; text: modelData.how; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                        Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                            mono: root.has(modelData.v); text: root.has(modelData.v) ? root.money(modelData.v) : modelData.need
                            color: root.has(modelData.v) ? Theme.ink : Theme.amber; font.pixelSize: root.has(modelData.v) ? 13 : 12 } } }
                Rectangle { width: parent.width; height: 1; color: Theme.rule2 }
                Item { width: parent.width; height: 34
                    Column { anchors.verticalCenter: parent.verticalCenter; spacing: 1
                        Txt { text: "This plate"; font.weight: 600 }
                        Txt { kind: "fine"; visible: text !== ""
                            text: root.c && root.c.per_plate_as_sliced.not_counted.length && root.has(root.c.per_plate_as_sliced.cost)
                                  ? "without " + root.c.per_plate_as_sliced.not_counted.join(" and ") : "" } }
                    Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                        Txt { mono: root.c && root.has(root.c.per_plate_as_sliced.cost); font.pixelSize: 16; font.weight: 600; anchors.verticalCenter: parent.verticalCenter
                            text: !root.c ? "" : root.has(root.c.per_plate_as_sliced.cost) ? root.money(root.c.per_plate_as_sliced.cost) : "set a price"
                            color: root.c && root.has(root.c.per_plate_as_sliced.cost) ? Theme.ink : Theme.amber } } }
            }
        }

        // ── copies ───────────────────────────────────────────
        Item { width: parent.width; height: 30
            Txt { text: "Copies on one plate"; tone: 2; anchors.verticalCenter: parent.verticalCenter }
            Row { anchors.right: parent.right; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                Field { width: 52; numeric: true; text: String(root.copies)
                    onAccepted: function (t) { var n = parseInt(t); if (n > 0 && n <= 200 && n !== root.copies) { root.copies = n; root.load() } } }
                Btn { icon: "layout_grid"; text: "Preview layout"; tip: "Lay the copies out on the plate (a computed arrangement)"
                    onClicked: Store.simulate({ copies: root.copies }) } } }
        Note { visible: !!root.c && !!root.c.per_plate_of_copies; kind: "plain"
            title: !root.c || !root.c.per_plate_of_copies ? "" : root.copies + " copies: "
                + (root.has(root.c.per_plate_of_copies.cost) ? root.money(root.c.per_plate_of_copies.cost) + " · " : "")
                + F.fmt(root.c.per_plate_of_copies.filament_g, 0) + " g · " + F.dur(root.c.per_plate_of_copies.time_s)
            text: root.c && root.c.per_plate_of_copies ? "Estimated as " + root.copies + " × this plate. Copies share start-up and travel, so slice the full plate to confirm. FORM exports one part per plate." : "" }

        // ── other materials ──────────────────────────────────
        Column { width: parent.width; visible: !!root.c && !!root.c.materials && root.c.materials.rows.length > 0; topPadding: 6
            Item { width: parent.width; height: 22
                Txt { kind: "cap"; text: "In another material"; anchors.verticalCenter: parent.verticalCenter }
                Tag { text: "estimated"; kind: "assumed"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
            Item { width: parent.width; height: 20
                Row { anchors.right: parent.right
                    Repeater { model: ["g/cm³", "grams", "per kg", "filament"]
                        Txt { required property string modelData; kind: "fine"; text: modelData; width: 62; horizontalAlignment: Text.AlignRight; wrapMode: Text.NoWrap } } } }
            Repeater {
                model: root.c && root.c.materials ? root.c.materials.rows.slice(0, 8) : []
                Rectangle { id: mr; required property var modelData
                    width: parent.width; height: 26; radius: Theme.rXs; color: modelData.current ? Theme.alpha(Theme.datum, 0.07) : "transparent"
                    Txt { x: 6; text: mr.modelData.type; anchors.verticalCenter: parent.verticalCenter; font.weight: mr.modelData.current ? 600 : 420
                        color: mr.modelData.current ? Theme.datum : Theme.ink; width: 84; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        Repeater { model: [F.fmt(mr.modelData.density_g_cm3, 2), F.fmt(mr.modelData.grams, 1),
                                           root.has(mr.modelData.price_per_kg) ? F.trim(mr.modelData.price_per_kg, 2) : "–",
                                           root.has(mr.modelData.cost) ? F.fmt(mr.modelData.cost, 2) : "–"]
                            Txt { required property string modelData; mono: true; font.pixelSize: 12; text: modelData; width: 62; horizontalAlignment: Text.AlignRight
                                wrapMode: Text.NoWrap; tone: 2 } } } } }
            Item { width: parent.width; height: 6 }
            Txt { kind: "fine"; width: parent.width
                text: root.c && root.c.materials ? "Estimated from volume (" + F.fmt(root.c.materials.volume_cm3, 1) + " cm³ of filament × each density from the slicer's installed presets"
                      + (root.c.materials.rows.length > 8 ? "; " + (root.c.materials.rows.length - 8) + " more types not shown" : "")
                      + "). The highlighted row is the slicer's own figure. Re-slice to confirm: another material needs other settings." : "" }
        }
        Txt { kind: "fine"; width: parent.width; visible: !!root.c && !!root.c.materials && root.c.materials.rows.length === 0 && root.c.materials.reason !== ""
            text: root.c && root.c.materials ? "No material comparison: " + root.c.materials.reason : "" }
        Txt { kind: "fine"; width: parent.width
            text: "Not included: failed prints, supports you throw away, wear, your time. Not a quote." }
    }
}
