import QtQuick
import QtQuick.Controls

// Which agent answers, with which model and effort. Agents are the agent apps (CLIs) on this computer, the model
// provider APIs with a key, providers you added by URL, and local model servers; the model names are the ones each
// lists (Form Studio does not make any up), plus whatever id you type. Agents that are not set up are named once at
// the end, with where to add them.
//
// A provider can list hundreds of models (OpenRouter), so the list is virtual (a ListView), searchable, grouped by
// vendor, with the models you used recently pinned on top. Keys: type to search, ↑ ↓ to move, Return to pick.
Column {
    id: mp
    spacing: 4
    signal done()
    readonly property var agent: Store.chatAgentInfo
    readonly property var allModels: agent ? agent.models : []
    property string filter: ""
    property int cursor: -1                      // keyboard position in `rows` (a model row), -1: none yet
    readonly property bool big: allModels.length > 8
    readonly property int total: agent && agent.count ? agent.count : allModels.filter(function (m) { return m.id !== "default" }).length
    // the rows the list shows: section headers and models, in order
    readonly property var rows: {
        var out = [], all = mp.allModels, f = mp.filter.trim().toLowerCase(), byId = ({}), i
        for (i = 0; i < all.length; i++) byId[all[i].id] = all[i]
        var words = f ? f.split(/\s+/) : []
        function hit(m) {
            var hay = (m.id + " " + m.label + " " + (m.vendor_label || "") + " " + (m.free ? "free" : "")).toLowerCase()
            for (var w = 0; w < words.length; w++) if (hay.indexOf(words[w]) < 0) return false
            return true
        }
        function head(t, n) { out.push({ head: true, title: t, n: n || 0 }) }
        function add(m, sec) { out.push({ head: false, m: m, sec: sec || "" }) }
        var rest = all.filter(function (m) { return m.id !== "default" })
        if (!f) {
            if (byId["default"]) add(byId["default"])
            var recent = (mp.agent && mp.agent.recent || []).filter(function (id) { return !!byId[id] })
            if (mp.big && recent.length) {
                head("Recent")
                recent.forEach(function (id) { add(byId[id], "recent") })
            }
        } else rest = rest.filter(hit)
        var vendors = rest.some(function (m) { return !!m.vendor_label })
        var cur = null, count = ({})
        rest.forEach(function (m) { var v = m.vendor_label || "Other"; count[v] = (count[v] || 0) + 1 })
        for (i = 0; i < rest.length; i++) {
            var v = rest[i].vendor_label || "Other"
            if (vendors && v !== cur) { head(v, count[v]); cur = v }
            else if (!vendors && i === 0 && mp.big && !f && out.length) head("All models", rest.length)
            add(rest[i])
        }
        return out
    }
    readonly property int matches: rows.filter(function (r) { return !r.head }).length
    onRowsChanged: mp.cursor = -1
    function step(d) {
        var i = mp.cursor
        for (var k = 0; k < mp.rows.length; k++) {
            i = i < 0 ? (d > 0 ? 0 : mp.rows.length - 1) : i + d
            if (i < 0 || i >= mp.rows.length) return
            if (!mp.rows[i].head) { mp.cursor = i; lv.positionViewAtIndex(i, ListView.Contain); return }
        }
    }
    function choose(m) { Store.setChatChoice(undefined, m.id); mp.done() }
    function pickCursor() {
        if (mp.cursor >= 0 && !mp.rows[mp.cursor].head) return mp.choose(mp.rows[mp.cursor].m)
        var first = mp.rows.filter(function (r) { return !r.head })[0]
        if (first && mp.filter.trim()) mp.choose(first.m)
    }
    // the search field has the keys as soon as the menu opens (Talk.qml calls this)
    function reset() { mp.filter = ""; sf.text = ""; mp.cursor = -1; lv.positionViewAtBeginning() }     // as the menu starts to show
    function opened() { if (mp.big && !sf.input.activeFocus) sf.input.forceActiveFocus() }               // once it is there
    readonly property bool custom: {
        for (var i = 0; i < allModels.length; i++) if (allModels[i].id === Store.chatModel) return false
        return Store.chatModel !== "" && Store.chatModel !== "default"
    }
    readonly property bool needsPick: !!agent && (Store.chatModel === "" || (Store.chatModel === "default" && !!agent.pick))
    readonly property var efforts: {
        if (!agent) return []
        for (var i = 0; i < allModels.length; i++) if (allModels[i].id === Store.chatModel && allModels[i].efforts && allModels[i].efforts.length) return allModels[i].efforts
        return agent.efforts || []
    }
    readonly property var groups: {
        var on = Store.chatAgents.filter(function (a) { return a.available })
        return [{ title: "Agent apps", items: on.filter(function (a) { return a.kind !== "api" }) },
                { title: "Model APIs", items: on.filter(function (a) { return a.kind === "api" && !a.local && !a.custom }) },
                { title: "Your providers", items: on.filter(function (a) { return a.custom }) },
                { title: "Local models", items: on.filter(function (a) { return a.kind === "api" && a.local && !a.custom }) }].filter(function (g) { return g.items.length > 0 })
    }
    readonly property var notSetUp: Store.chatAgents.filter(function (a) { return !a.available && !a.custom }).map(function (a) { return a.label })

    Txt { visible: Store.retryAfterPick; kind: "fine"; x: 8; width: mp.width - 16; topPadding: 4; color: Theme.datum
        text: "Pick a model: your last message is sent again with it." }
    Repeater {
        model: mp.groups
        Column {
            id: grp
            required property var modelData
            width: mp.width
            Txt { kind: "cap"; text: grp.modelData.title; x: 8; topPadding: 4; bottomPadding: 2 }
            Repeater {
                model: grp.modelData.items
                Rectangle {
                    id: ar
                    required property var modelData
                    readonly property bool on: modelData.id === Store.chatAgent
                    objectName: "pickAgent_" + modelData.id
                    width: mp.width; height: 30; radius: Theme.rSm
                    color: am.pressed ? Theme.washPress : am.containsMouse ? Theme.washHover : "transparent"
                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                    Rectangle { x: 10; width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter; color: "transparent"
                        border.width: ar.on ? 4 : 1; border.color: ar.on ? Theme.datum : Theme.ink4
                        Behavior on border.width { NumberAnimation { duration: Theme.press } } }
                    Row { x: 32; width: parent.width - 42; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                        Txt { id: an; text: ar.modelData.label; font.weight: ar.on ? Theme.wSemi : Theme.wMedium }
                        Txt { kind: "fine"; anchors.baseline: an.baseline; width: parent.width - an.width - 8; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: ar.modelData.custom ? (ar.modelData.count ? ar.modelData.count + " models" : "") + (ar.modelData.local ? " · on this network" : "")
                                : ar.modelData.kind === "api" ? (ar.modelData.local ? "on this computer" : (ar.modelData.reports_cost ? "your key · reports cost" : "your key"))
                                : "your account" + (ar.modelData.reports_cost ? "" : " · no cost figure") } }
                    MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; onClicked: if (!ar.on) Store.setChatChoice(ar.modelData.id) }
                }
            }
        }
    }
    Rectangle { objectName: "pickAddAgent"; width: mp.width; height: 30; radius: Theme.rSm
        color: sm.pressed ? Theme.washPress : sm.containsMouse ? Theme.washHover : "transparent"
        Icon { x: 10; name: "plus"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
        Txt { x: 32; width: parent.width - 42; kind: "fine"; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: "Add an agent, an API key, a provider or a local model…" }
        Tip { show: sm.containsMouse && mp.notSetUp.length > 0; text: "Not set up yet: " + mp.notSetUp.join(", ") }
        MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: { mp.done(); Store.openSettings("chat") } } }
    Note { visible: !!mp.agent && String(mp.agent.verified).indexOf("not run") === 0; kind: "amber"; width: mp.width
        text: "Not yet verified with a live reply from this agent. If the first reply goes wrong, report it on GitHub." }

    Rectangle { width: mp.width; height: 1; color: Theme.rule }
    Item { width: mp.width; height: 24
        Txt { kind: "cap"; text: "Model"; x: 8; anchors.bottom: parent.bottom; anchors.bottomMargin: 3 }
        Txt { kind: "fine"; tone: 4; anchors.right: parent.right; anchors.rightMargin: 10; anchors.bottom: parent.bottom; anchors.bottomMargin: 3
            visible: mp.big; text: mp.filter.trim() ? mp.matches + " of " + mp.total : mp.total + " models" } }
    Note { objectName: "pickModelNote"; visible: mp.needsPick; kind: "blue"; width: mp.width
        text: (mp.agent ? mp.agent.label : "This provider") + " has no default model yet. Pick one: it becomes the default for "
              + (mp.agent ? mp.agent.label : "it") + " next time." }
    Item { visible: mp.big; width: mp.width; height: 36
        Field { id: sf; objectName: "modelSearch"; x: 6; width: parent.width - 12; anchors.verticalCenter: parent.verticalCenter
            placeholder: "Search " + mp.total + " models, vendors, “free”…"
            onEdited: function (t) { mp.filter = t }
            onAccepted: mp.pickCursor()
            Keys.onDownPressed: mp.step(1)
            Keys.onUpPressed: mp.step(-1)
            Icon { name: "search"; size: 13; color: Theme.ink4; anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter } } }
    ListView {
        id: lv
        objectName: "modelList"
        width: mp.width; clip: true; boundsBehavior: Flickable.StopAtBounds
        height: Math.min(contentHeight, mp.big ? 340 : 100000)
        interactive: contentHeight > height
        model: mp.rows
        cacheBuffer: 400
        ScrollBar.vertical: ScrollBar { width: 6; policy: lv.contentHeight > lv.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
        delegate: Item {
            id: row
            required property var modelData
            required property int index
            readonly property var m: modelData.m || ({})
            readonly property bool on: !modelData.head && (m.id === Store.chatModel || (m.id === "default" && !Store.chatModel && !(mp.agent && mp.agent.pick)))
            readonly property bool cur: index === mp.cursor
            objectName: modelData.head ? "modelHead" : "modelRow_" + m.id
            width: lv.width; height: modelData.head ? 26 : Math.max(row.m.note ? 40 : 32, mc.implicitHeight + 10)
            // section header: vendor, Recent
            Row { visible: row.modelData.head; x: 10; anchors.bottom: parent.bottom; anchors.bottomMargin: 4; spacing: 6
                Icon { visible: row.modelData.title === "Recent"; name: "history"; size: 11; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "cap"; text: row.modelData.title || "" }
                Txt { kind: "fine"; tone: 4; visible: row.modelData.n > 0; text: String(row.modelData.n) } }
            Rectangle { visible: !row.modelData.head; anchors.fill: parent; radius: Theme.rSm
                color: mm.pressed ? Theme.washPress : (mm.containsMouse || row.cur) ? Theme.washHover : "transparent"
                border.width: row.cur ? 1 : 0; border.color: Theme.rule2
                Behavior on color { ColorAnimation { duration: Theme.fast } } }
            Column { id: mc; visible: !row.modelData.head; x: 10; width: parent.width - 20 - tags.width - (row.on ? 22 : 0)
                anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Txt { text: row.m.label || ""; font.weight: row.on ? Theme.wSemi : Theme.wMedium; color: row.on ? Theme.datum : Theme.ink
                    width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                Txt { kind: "fine"; visible: text !== ""; width: parent.width; maximumLineCount: 1; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: row.m.note || "" } }
            Row { id: tags; visible: !row.modelData.head; spacing: 4; anchors.right: parent.right; anchors.rightMargin: row.on ? 32 : 10
                anchors.verticalCenter: parent.verticalCenter
                Tag { visible: !!row.m.free; text: "free"; tint: Theme.pass }
                Tag { visible: row.m.tools === false; text: "no tools"; tint: Theme.amber }
                Icon { visible: row.m.images === true; name: "image"; size: 12; color: Theme.ink4; anchors.verticalCenter: parent.verticalCenter } }
            Icon { visible: row.on; name: "check"; size: 14; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
            MouseArea { id: mm; visible: !row.modelData.head; anchors.fill: parent; hoverEnabled: true; onClicked: mp.choose(row.m) }
        }
    }
    Txt { visible: mp.big && mp.matches === 0; kind: "fine"; x: 10; width: mp.width - 20; topPadding: 6; bottomPadding: 6
        text: "No model matches “" + mp.filter.trim() + "”. Type a full id below to use one this list does not show." }
    Item { width: mp.width; height: 36
        Field { id: cf; x: 6; width: parent.width - 12; anchors.verticalCenter: parent.verticalCenter; mono: true
            placeholder: "Custom model id"; text: mp.custom ? Store.chatModel : ""
            onAccepted: function (t) { if (t.trim()) { Store.setChatChoice(undefined, t.trim()); mp.done() } } } }
    Txt { kind: "fine"; x: 10; width: mp.width - 20; visible: mp.custom
        text: "Passed to " + Store.chatAgentLabel + " as typed. If it is not a model it knows, the message fails and says so." }

    Rectangle { visible: mp.efforts.length > 0; width: mp.width; height: 1; color: Theme.rule }
    Txt { visible: mp.efforts.length > 0; kind: "cap"; text: "Effort"; x: 8; topPadding: 6; bottomPadding: 2 }
    Flow { visible: mp.efforts.length > 0; x: 8; width: mp.width - 16; spacing: 4
        Repeater {
            model: [""].concat(mp.efforts)
            Rectangle {
                required property string modelData
                readonly property bool on: modelData === Store.chatEffort
                width: el.implicitWidth + 18; height: 24; radius: Theme.rSm
                color: on ? Theme.plate4 : em.pressed ? Theme.washPress : em.containsMouse ? Theme.washHover : "transparent"; border.color: on ? Theme.rule2 : Theme.rule
                Txt { id: el; anchors.centerIn: parent; font.pixelSize: 12; text: parent.modelData || "default"; tone: parent.on ? 1 : 2 }
                MouseArea { id: em; anchors.fill: parent; hoverEnabled: true; onClicked: Store.setChatChoice(undefined, undefined, parent.modelData) }
            }
        }
    }
    Item { width: 1; height: 4 }
    Rectangle { width: mp.width; height: 1; color: Theme.rule }
    Txt { kind: "fine"; x: 10; width: mp.width - 20; topPadding: 6; bottomPadding: 4
        text: (Store.conv && Store.conv.resolved_model && Store.conv.agent === Store.chatAgent
               ? "Last reply came from " + Store.conv.resolved_model + " (as the agent reported it). " : "")
            + (mp.big ? "↑ ↓ to move, Return to pick. " : "") + "New conversations start with this choice." }
}
