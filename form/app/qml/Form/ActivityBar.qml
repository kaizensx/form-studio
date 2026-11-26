import QtQuick

// What the engine is working on, under the top bar: a hairline of progress across the window and, at the right, a
// small card that names the work, how long it has run and, where the engine knows it, how far it is (the pipeline's
// steps). It appears only for work that takes longer than 300 ms (Store.activity), so quick answers never flash it.
Item {
    id: ab
    objectName: "activityBar"
    height: 0
    readonly property var items: Store.activity
    readonly property var newest: items.length ? items[items.length - 1] : null
    property var lead: null                    // the newest is named; kept while the pill fades, so it never empties first
    onNewestChanged: if (newest) lead = newest
    readonly property bool on: items.length > 0
    readonly property real progress: lead && lead.progress >= 0 ? lead.progress : -1
    property real now: Date.now()
    Timer { running: ab.on; interval: 100; repeat: true; onTriggered: ab.now = Date.now() }
    // Start-up: Home loads every card's geometry at once, which is not news. For the first seconds after the app
    // opens the card waits until the work has run 1.2 s; the hairline still shows at once. Later work names itself
    // as soon as it is listed (Store.activity already waits 300 ms).
    property real born: Date.now()
    readonly property bool starting: now - born < 6000
    readonly property bool named: on && (!starting || items.some(function (i) { return i.click }) || now - items[0].t0 >= 1200)     // work you clicked for is named at once

    // the hairline: a filled share when the progress is known, a travelling segment when it is not
    Item { id: line; width: parent.width; height: 2; clip: true
        opacity: ab.on ? 1 : 0; Behavior on opacity { NumberAnimation { duration: ab.on ? Theme.fast : Theme.slow } }
        Rectangle { anchors.fill: parent; color: Theme.alpha(Theme.datum, 0.12) }
        Rectangle { visible: ab.progress >= 0; height: parent.height; color: Theme.datum
            width: parent.width * Math.max(0.04, ab.progress); Behavior on width { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } } }
        Rectangle { id: run; visible: ab.progress < 0; height: parent.height; width: parent.width * 0.28
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Theme.datum } GradientStop { position: 1; color: "transparent" } }
            NumberAnimation on x { running: ab.on && ab.progress < 0; loops: Animation.Infinite; from: -run.width; to: line.width; duration: Theme.reduced ? 2400 : 1200 } } }

    // The work, named in the middle of the top bar (where a pro app keeps its activity): one line, a pill, so it never
    // sits on the stage tabs or the inspector. When the bar has no room for it, it drops just under the bar's right end.
    property real barH: 44
    property real slotX: 0
    property real slotW: 0
    readonly property bool inBar: slotW >= 240
    Rectangle {
        id: card
        objectName: "activityCard"
        readonly property real want: row.implicitWidth + 26
        width: Math.min(want, ab.inBar ? ab.slotW : 360); height: 26; radius: 13
        x: ab.inBar ? Math.round(Math.max(ab.slotX, Math.min(ab.slotX + ab.slotW - width, (ab.width - width) / 2))) : ab.width - width - 14
        y: (ab.inBar ? -ab.barH + Math.round((ab.barH - height) / 2) : 10) + (ab.named ? 0 : Theme.shift(-3))
        color: Theme.plate3; border.color: Theme.rule2
        opacity: ab.named ? 1 : 0; visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: ab.named ? Theme.base : Theme.slow } }
        Behavior on y { Glide { duration: Theme.base } }
        Shadow { visible: !ab.inBar; radius: parent.radius; spread: 14; drop: 6 }
        Row { id: row; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 7
            Item { width: 13; height: 13; anchors.verticalCenter: parent.verticalCenter
                Spinner { anchors.fill: parent; size: 13; visible: ab.lead && !ab.lead.done }
                Icon { anchors.centerIn: parent; size: 13; visible: !!ab.lead && ab.lead.done; name: ab.lead && !ab.lead.ok ? "circle_alert" : "circle_check"
                    color: ab.lead && !ab.lead.ok ? Theme.signal : Theme.pass } }
            Txt { objectName: "activityLabel"; text: ab.lead ? ab.lead.label + (ab.lead.done ? "" : "…") : ""; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap
                elide: Text.ElideRight; width: Math.min(implicitWidth, 230); anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; tone: 3; visible: text !== "" && card.width >= card.want; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, 200); anchors.verticalCenter: parent.verticalCenter
                text: !ab.lead ? "" : (ab.lead.detail || "") + (ab.items.length > 1 ? (ab.lead.detail ? " · " : "") + "and " + (ab.items.length - 1) + " more" : "") }
            Txt { kind: "fine"; mono: true; tone: 3; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: ab.lead ? (ab.progress >= 0 && !ab.lead.done ? Math.round(ab.progress * 100) + "% · " : "") + ((ab.now - ab.lead.t0) / 1000).toFixed(1) + " s" : "" } }
    }
}
