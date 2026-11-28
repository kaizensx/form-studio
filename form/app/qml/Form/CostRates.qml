import QtQuick
import "F.js" as F

// Settings › Costs. The rates the cost models use (form/costing/rates.toml), one row each: what it is, the published
// value with its source and date (or "assumed" for a process parameter no source states, or "no published rate"),
// and your shop's own number beside it. A number you type is yours ("specified") and applies at once; clearing it
// brings the published rate back. Shops keep their own rates and currency; money is converted only with a stated
// rate (the ECB reference rate, or the one you set). GET/POST /api/cost/rates.
Column {
    id: root
    width: parent ? parent.width : 0
    spacing: 12
    property var d: null
    property string query: ""
    property string newShop: ""
    function load(shop) {
        Store.get("/cost/rates" + (shop ? "?shop=" + encodeURIComponent(shop) : "")).then(function (r) { root.d = r }, function () {})
    }
    function post(body) {
        body.shop = body.shop !== undefined ? body.shop : (root.d ? root.d.shop : "")
        Store.post("/cost/rates", body).then(function (r) { root.d = r }, Store.fail)
    }
    function parse(t) { t = String(t).trim().replace(",", "."); return t === "" ? null : parseFloat(t) }
    function setRate(r, text) {
        var v = parse(text)
        if (v !== null && (isNaN(v) || v < 0)) { Store.toast("That is not a number.", "Use digits, for example 42.50.", true); return }
        if (!r.overridden && v === null) return
        if (r.overridden && v === r.value) return
        var b = {}; b[r.id] = v
        post({ rates: b })
    }
    readonly property var rows: !d ? [] : d.rates.filter(function (r) {
        var q = root.query.trim().toLowerCase()
        return q === "" || (r.id + " " + r.label + " " + (r.source || "")).toLowerCase().indexOf(q) >= 0 })
    Component.onCompleted: load("")

    // the shop: which one costs use, its currency
    Rectangle { width: parent.width; height: shopCol.implicitHeight + 24; radius: 16; color: Theme.glass
        Column { id: shopCol; x: 18; y: 12; width: parent.width - 36; spacing: 8
            KV { first: true; k: "Shop"; sub: root.d ? (root.d.shop === root.d.active ? "Costs use this shop" : "Not the shop costs use") : ""
                Seg { objectName: "costShop"; model: root.d ? Object.keys(root.d.shops).map(function (k) { return { value: k, text: root.d.shops[k] } }) : []
                    value: root.d ? root.d.shop : ""; onPicked: function (v) { root.load(v) } }
                Btn { small: true; kind: "quiet"; text: "Use for costs"; visible: !!root.d && root.d.shop !== root.d.active
                    onClicked: root.post({ activate: true }) } }
            KV { k: "Currency"; sub: "Amounts are shown in it; other currencies are converted only with a stated rate"
                Seg { objectName: "costCurrency"; model: ["EUR", "USD", "GBP", "CHF"]; value: root.d ? root.d.currency : "EUR"
                    onPicked: function (v) { root.post({ currency: v }) } } }
            KV { k: "Exchange rates"; sub: !root.d ? "" : Object.keys(root.d.fx).map(function (k) {
                    var x = root.d.fx[k]; return "1 EUR = " + F.trim(x.per_eur, 4) + " " + k + " (" + x.evidence + (x.applies ? ", " + x.applies : "") + ")" }).join(" · ") }
            KV { k: "New shop"; sub: "Its own rates and currency, starting from the published ones"
                Field { objectName: "costNewShop"; width: 160; placeholder: "name"; text: root.newShop; onAccepted: function (t) { root.newShop = t } }
                Btn { small: true; icon: "plus"; text: "Add"; enabled: root.newShop.trim() !== ""
                    onClicked: { var id = root.newShop.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-"); root.post({ shop: id, label: root.newShop.trim() }); root.newShop = "" } } }
        } }

    Field { objectName: "costRateSearch"; width: Math.min(parent.width, 320); placeholder: "Find a rate"; text: root.query
        onAccepted: function (t) { root.query = t }; input.onTextChanged: root.query = input.text }

    Rectangle { width: parent.width; height: list.implicitHeight + 8; radius: 16; color: Theme.glass
        Column { id: list; y: 4; width: parent.width
            Repeater {
                model: root.rows
                Item {
                    id: rr
                    required property var modelData
                    readonly property var r: modelData
                    width: list.width; height: Math.max(info.implicitHeight, 30) + 18
                    Rectangle { visible: rr.r.overridden; x: 7; y: 12; width: 3; height: parent.height - 24; radius: 2; color: Theme.blueprint }
                    Column { id: info; x: 18; width: parent.width - 36 - ctl.width - 16; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                        Txt { text: rr.r.label; width: parent.width; font.weight: Theme.wMedium }
                        Txt { kind: "fine"; width: parent.width; wrapMode: Text.Wrap
                            text: rr.r.evidence === "sourced" ? "Published: " + F.trim(rr.r.published, 4) + " " + rr.r.published_unit + (rr.r.applies ? " (" + rr.r.applies + ")" : "") + " · " + (rr.r.source || "")
                                : rr.r.evidence === "assumed" ? "Assumed: " + (rr.r.why || "no published figure")
                                : rr.r.evidence === "specified" ? (rr.r.published !== null && rr.r.published !== undefined ? "Published: " + F.trim(rr.r.published, 4) + " " + rr.r.published_unit + " · " : "") + (rr.r.source || "")
                                : (rr.r.needs || "No published rate: set your shop's.") }
                        Txt { kind: "fine"; tone: 4; mono: true; font.pixelSize: 10; text: rr.r.id } }
                    Row { id: ctl; anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                        Tag { text: rr.r.evidence === "missing" ? "not set" : rr.r.evidence; kind: rr.r.evidence === "assumed" || rr.r.evidence === "missing" ? "assumed" : ""
                            anchors.verticalCenter: parent.verticalCenter }
                        Field { width: 120; numeric: true; unit: rr.r.unit || ""; placeholder: rr.r.value !== null && rr.r.value !== undefined ? F.trim(rr.r.value, 4) : "set"
                            text: rr.r.overridden ? F.trim(rr.r.value, 6) : ""
                            onAccepted: function (t) { root.setRate(rr.r, t) } } }
                } } } }
    Txt { kind: "fine"; width: parent.width; tone: 3
        text: !root.d ? "" : root.d.rule + " The table: " + root.d.table + "." }
}
