import QtQuick
import QtQuick.Controls

// Which agent answers, with which model and effort. Agents are the agent apps (CLIs) on this computer, the model
// provider APIs with a key, and local model servers; the model names are the ones each lists (Form Studio does not
// make any up), plus whatever id you type. Agents that are not set up are named once at the end, with where to add them.
Column {
    id: mp
    spacing: 4
    signal done()
    readonly property var agent: Store.chatAgentInfo
    readonly property var allModels: agent ? agent.models : []
    property string filter: ""
    readonly property var models: {
        var f = mp.filter.trim().toLowerCase()
        if (!f) return allModels
        return allModels.filter(function (m) { return m.id === "default" || (m.id + " " + m.label).toLowerCase().indexOf(f) >= 0 })
    }
    readonly property bool custom: {
        for (var i = 0; i < allModels.length; i++) if (allModels[i].id === Store.chatModel) return false
        return Store.chatModel !== "" && Store.chatModel !== "default"
    }
    readonly property var efforts: {
        if (!agent) return []
        for (var i = 0; i < allModels.length; i++) if (allModels[i].id === Store.chatModel && allModels[i].efforts && allModels[i].efforts.length) return allModels[i].efforts
        return agent.efforts || []
    }
    readonly property var groups: {
        var on = Store.chatAgents.filter(function (a) { return a.available })
        return [{ title: "Agent apps", items: on.filter(function (a) { return a.kind !== "api" }) },
                { title: "Model APIs", items: on.filter(function (a) { return a.kind === "api" && !a.local }) },
                { title: "Local models", items: on.filter(function (a) { return a.kind === "api" && a.local }) }].filter(function (g) { return g.items.length > 0 })
    }
    readonly property var notSetUp: Store.chatAgents.filter(function (a) { return !a.available }).map(function (a) { return a.label })

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
                    Rectangle { x: 10; width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter; color: "transparent"
                        border.width: ar.on ? 4 : 1; border.color: ar.on ? Theme.datum : Theme.ink4 }
                    Row { x: 32; width: parent.width - 42; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                        Txt { id: an; text: ar.modelData.label; font.weight: ar.on ? 600 : 500 }
                        Txt { kind: "fine"; anchors.baseline: an.baseline; width: parent.width - an.width - 8; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: ar.modelData.kind === "api" ? (ar.modelData.local ? "on this computer" : (ar.modelData.reports_cost ? "your key · reports cost" : "your key"))
                                : "your account" + (ar.modelData.reports_cost ? "" : " · no cost figure") } }
                    MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; onClicked: if (!ar.on) Store.setChatChoice(ar.modelData.id) }
                }
            }
        }
    }
    Rectangle { visible: mp.notSetUp.length > 0; width: mp.width; height: 30; radius: Theme.rSm
        color: sm.pressed ? Theme.washPress : sm.containsMouse ? Theme.washHover : "transparent"
        Icon { x: 10; name: "plus"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
        Txt { x: 32; width: parent.width - 42; kind: "fine"; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: "Add an agent, an API key or a local model…" }
        Tip { show: sm.containsMouse; text: "Not set up yet: " + mp.notSetUp.join(", ") }
        MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: { mp.done(); Store.openSettings("chat") } } }
    Note { visible: !!mp.agent && String(mp.agent.verified).indexOf("not run") === 0; kind: "amber"; width: mp.width
        text: "Not yet verified with a live reply from this agent. If the first reply goes wrong, report it on GitHub." }

    Rectangle { width: mp.width; height: 1; color: Theme.rule }
    Txt { kind: "cap"; text: "Model"; x: 8; topPadding: 6; bottomPadding: 2 }
    Item { visible: mp.allModels.length > 12; width: mp.width; height: 34
        Field { id: ff; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; placeholder: "Filter " + mp.allModels.length + " models"
            onEdited: function (t) { mp.filter = t } } }
    Repeater {
        model: mp.models
        Rectangle {
            id: mr
            required property var modelData
            readonly property bool on: modelData.id === Store.chatModel || (modelData.id === "default" && !Store.chatModel)
            width: mp.width; height: Math.max(40, mc.implicitHeight + 10); radius: Theme.rSm
            color: mm.pressed ? Theme.washPress : mm.containsMouse ? Theme.washHover : "transparent"
            Column { id: mc; x: 10; width: parent.width - 44; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Txt { text: mr.modelData.label; font.weight: mr.on ? 600 : 500; color: mr.on ? Theme.datum : Theme.ink
                    width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                Txt { kind: "fine"; visible: text !== ""; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight; text: mr.modelData.note || "" } }
            Icon { visible: mr.on; name: "check"; size: 14; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
            MouseArea { id: mm; anchors.fill: parent; hoverEnabled: true; onClicked: { Store.setChatChoice(undefined, mr.modelData.id); mp.done() } }
        }
    }
    Item { width: mp.width; height: 36
        Field { id: cf; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; mono: true
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
            + "New conversations start with this choice." }
}
