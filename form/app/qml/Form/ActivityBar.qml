import QtQuick

// What the engine is working on, under the top bar: a hairline of progress across the window and, at the right, a
// small card that names the work, how long it has run and, where the engine knows it, how far it is (the pipeline's
// steps). It appears only for work that takes longer than 300 ms (Store.activity), so quick answers never flash it.
Item {
    id: ab
    objectName: "activityBar"
    height: 0
    readonly property var items: Store.activity
    readonly property var lead: items.length ? items[items.length - 1] : null      // the newest is named
    readonly property bool on: items.length > 0
    readonly property real progress: lead && lead.progress >= 0 ? lead.progress : -1
    property real now: Date.now()
    Timer { running: ab.on; interval: 100; repeat: true; onTriggered: ab.now = Date.now() }

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

    // the card
    Rectangle {
        id: card
        objectName: "activityCard"
        anchors.right: parent.right; anchors.rightMargin: 14; y: ab.on ? 10 : 2
        width: Math.min(360, col.implicitWidth + 44); height: col.implicitHeight + 16; radius: Theme.rMd
        color: Theme.plate3; border.color: Theme.rule2
        opacity: ab.on ? 1 : 0; visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: ab.on ? Theme.base : Theme.slow } }
        Behavior on y { Glide { duration: Theme.base } }
        Shadow { radius: parent.radius; spread: 14; drop: 6 }
        Spinner { x: 12; y: 11; size: 13; visible: ab.lead && !ab.lead.done }
        Icon { x: 12; y: 11; size: 13; visible: !!ab.lead && ab.lead.done; name: ab.lead && !ab.lead.ok ? "circle_alert" : "circle_check"
            color: ab.lead && !ab.lead.ok ? Theme.signal : Theme.pass }
        Column { id: col; x: 32; y: 8; spacing: 1
            Row { spacing: 6
                Txt { objectName: "activityLabel"; text: ab.lead ? ab.lead.label + (ab.lead.done ? "" : "…") : ""; font.weight: Theme.wSemi; wrapMode: Text.NoWrap
                    elide: Text.ElideRight; width: Math.min(implicitWidth, 230) }
                Txt { kind: "fine"; mono: true; tone: 3; anchors.verticalCenter: parent.verticalCenter
                    text: ab.lead ? (ab.progress >= 0 && !ab.lead.done ? Math.round(ab.progress * 100) + "% · " : "") + ((ab.now - ab.lead.t0) / 1000).toFixed(1) + " s" : "" } }
            Txt { kind: "fine"; tone: 3; visible: text !== ""; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, 300)
                text: !ab.lead ? "" : (ab.lead.detail || "") + (ab.items.length > 1 ? (ab.lead.detail ? " · " : "") + "and " + (ab.items.length - 1) + " more" : "") } }
    }
}
