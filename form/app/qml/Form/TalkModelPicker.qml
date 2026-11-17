import QtQuick
import QtQuick.Controls

// Which agent answers, with which model and effort. Agents are the CLIs FORM can drive on your own account; the
// model names are the ones each CLI documents (FORM does not make any up), plus whatever id you type.
Column {
    id: mp
    spacing: 4
    signal done()
    readonly property var agent: Store.chatAgentInfo
    readonly property var models: agent ? agent.models : []
    readonly property bool custom: {
        for (var i = 0; i < models.length; i++) if (models[i].id === Store.chatModel) return false
        return Store.chatModel !== "" && Store.chatModel !== "default"
    }
    readonly property var efforts: {
        if (!agent) return []
        for (var i = 0; i < models.length; i++) if (models[i].id === Store.chatModel && models[i].efforts && models[i].efforts.length) return models[i].efforts
        return agent.efforts || []
    }

    Txt { kind: "cap"; text: "Agent"; x: 8; topPadding: 4; bottomPadding: 2 }
    Repeater {
        model: Store.chatAgents
        Rectangle {
            id: ar
            required property var modelData
            readonly property bool on: modelData.id === Store.chatAgent
            width: mp.width; height: modelData.available ? 32 : Math.max(44, ac.implicitHeight + 12); radius: Theme.rSm
            color: !modelData.available ? "transparent" : am.pressed ? Theme.washPress : am.containsMouse ? Theme.washHover : "transparent"
            opacity: modelData.available ? 1 : 0.55
            Rectangle { x: 10; width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter; color: "transparent"
                border.width: ar.on ? 4 : 1; border.color: ar.on ? Theme.datum : Theme.ink4 }
            Column { id: ac; x: 32; width: parent.width - 42; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Row { spacing: 8
                    Txt { text: ar.modelData.label; font.weight: ar.on ? 600 : 500 }
                    Txt { kind: "fine"; visible: ar.modelData.available; anchors.baseline: parent.children[0].baseline
                        text: "your account" + (ar.modelData.reports_cost ? "" : " · no cost figure") } }
                Txt { kind: "fine"; visible: !ar.modelData.available; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight; text: ar.modelData.why || "Not installed" } }
            MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; onClicked: if (ar.modelData.available && !ar.on) Store.setChatChoice(ar.modelData.id) }
        }
    }
    Note { visible: !!mp.agent && String(mp.agent.verified).indexOf("not run") === 0; kind: "amber"; width: mp.width
        text: "This adapter was written from the CLI's documentation and has not been run. Treat the first message as a test." }

    Rectangle { width: mp.width; height: 1; color: Theme.rule }
    Txt { kind: "cap"; text: "Model"; x: 8; topPadding: 6; bottomPadding: 2 }
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
        text: "Passed to " + Store.chatAgentLabel + " as typed. If it is not a model the CLI knows, the message fails and says so." }

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
               ? "Last reply came from " + Store.conv.resolved_model + " (reported by the CLI). " : "")
            + "New conversations start with this choice." }
}
