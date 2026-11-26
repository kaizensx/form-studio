import QtQuick

// The build's ledger, pinned over the part while it is made: which feature is arriving, where the build is
// ("6 of 12"), and a hairline that fills as it goes. One line, one accent (datum). The parent places it and fades it.
Rectangle {
    id: bl
    property string label: ""                // the feature arriving, or the one that arrived last
    property int at: 0                       // 1-based step; 0 with `of` 0 = no count
    property int of: 0
    property bool running: true              // false once the build is in: "Built"
    property bool pulse: false               // the dot breathes (a build streamed from the agent)
    readonly property real frac: !running ? 1 : of > 0 ? Math.max(0, Math.min(1, at / of)) : 0
    width: Math.max(260, row.implicitWidth + 2 * Theme.s4 + (count.visible ? count.implicitWidth + Theme.s5 : 0)); height: 44; radius: Theme.rMd
    color: Theme.alpha(Theme.plate3, 0.96); border.color: Theme.rule2
    Shadow { radius: bl.radius; spread: 14; drop: 6 }
    Row {
        id: row; x: Theme.s4; y: 13; spacing: Theme.s2; height: 18
        Rectangle { width: 6; height: 6; radius: 3; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
            SequentialAnimation on opacity { running: bl.pulse && bl.visible && !Theme.reduced; loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
        Txt { kind: "cap"; color: Theme.datum; text: bl.running ? "Building" : "Built"; anchors.verticalCenter: parent.verticalCenter; rightPadding: Theme.s1 }
        Txt { objectName: "buildLedgerName"; kind: "lead"; font.weight: Theme.wMedium; text: bl.label; anchors.verticalCenter: parent.verticalCenter
            wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, 320) }
    }
    Txt { id: count; objectName: "buildLedgerCount"; visible: bl.of > 1; kind: "fine"; mono: true; tone: 2; wrapMode: Text.NoWrap
        anchors.right: parent.right; anchors.rightMargin: Theme.s4; anchors.verticalCenter: row.verticalCenter
        text: bl.at + " of " + bl.of }
    // progress: a 2 px hairline along the foot, filling from the left (scaled, so nothing is laid out again)
    Item { x: Theme.s4; width: parent.width - 2 * Theme.s4; y: parent.height - 9; height: 2
        Rectangle { anchors.fill: parent; radius: 1; color: Theme.rule2 }
        Rectangle { id: bar; objectName: "buildLedgerBar"; anchors.fill: parent; radius: 1; color: Theme.datum
            property real k: bl.frac
            Behavior on k { NumberAnimation { duration: Theme.cross; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
            transform: Scale { xScale: Math.max(0.001, bar.k) } }
    }
}
