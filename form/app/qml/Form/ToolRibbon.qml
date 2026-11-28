import QtQuick

// The tools of the mode you are in, labelled and grouped, in one slim band of glass at the head of the stage
// (docs/design/directions/i/IA.md, "Built so far": the pro frame). Each group has a caption lettered like a
// drawing's; each tool an icon and its label. Nothing ever wraps: when the stage is narrow the groups give up their
// labels one by one from the right (icons only, the label in the tooltip), then the captions go, and only then do
// the last tools move into More. The band ends with Hide, which folds it back into the icon dock (remembered).
//
//   groups  [{ id, caption, tools: [{ id, icon, label, keys, hint }] }], already cut to what this design can use
//   host    toolState(id) -> { active, marked, enabled, toggle, label, hint }; toolRun(id)
Glass {
    id: rb
    objectName: "toolRibbon"
    property var groups: []
    property Item host: null
    property real maxWidth: 800
    property string modeKey: ""                // the mode: the tools cross-fade when it changes
    signal hideAsked()
    height: 38; radius: 19

    // ── how much fits: labels, then captions, then More ──
    FontMetrics { id: fmLabel; font.family: Theme.sans; font.pixelSize: 12; font.weight: Theme.wMedium }
    FontMetrics { id: fmCap; font.family: Theme.mono; font.pixelSize: Theme.tCap; font.weight: Theme.wMedium; font.letterSpacing: 1.1; font.capitalization: Font.AllUppercase }
    readonly property int pad: 4
    readonly property int sp: 2               // between tools
    readonly property int sepW: 17            // a group's rule and the room either side of it
    readonly property int tail: 32 + 4        // Hide
    function _full(t) { return Math.ceil(fmLabel.advanceWidth(t.label)) + 44 }
    function _capW(g) { return Math.ceil(fmCap.advanceWidth(g.caption.toUpperCase()) + 1.1 * g.caption.length) + 10 }
    function _width(gs, compact, caps, keep, more) {
        var w = 2 * pad + tail, n = 0
        for (var i = 0; i < gs.length; i++) {
            var k = keep[i]
            if (!k) continue
            if (n) w += sepW
            n++
            if (caps) w += _capW(gs[i])
            for (var j = 0; j < k; j++) w += (compact[i] ? 32 : _full(gs[i].tools[j])) + (j ? sp : 0)
        }
        if (more) w += (n ? sepW : 0) + 32
        return w
    }
    readonly property var plan: {
        var gs = groups || [], room = maxWidth, n = gs.length
        var compact = gs.map(function () { return false }), keep = gs.map(function (g) { return g.tools.length })
        var caps = true
        if (_width(gs, compact, caps, keep, false) > room) {
            for (var i = n - 1; i >= 0 && _width(gs, compact, caps, keep, false) > room; i--) compact[i] = true
            if (_width(gs, compact, caps, keep, false) > room) caps = false
            // still too wide: the last tools go into More, from the end
            var more = []
            var over = _width(gs, compact, caps, keep, false) > room
            while (over && _width(gs, compact, caps, keep, true) > room) {
                var g = -1
                for (var q = n - 1; q >= 0; q--) if (keep[q] > 0) { g = q; break }
                if (g < 0) break
                keep[g]--
                more.unshift({ group: gs[g].caption, tool: gs[g].tools[keep[g]] })
            }
            return { compact: compact, caps: caps, keep: keep, more: more }
        }
        return { compact: compact, caps: caps, keep: keep, more: [] }
    }
    width: Math.round(Math.min(maxWidth, _width(groups || [], plan.compact, plan.caps, plan.keep, plan.more.length > 0)))
    Behavior on width { enabled: rb.settled; NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    property bool settled: false
    Component.onCompleted: Qt.callLater(function () { rb.settled = true })

    // the mode changed: the new tools fade in where the old ones stood (180 ms, as the dock)
    onModeKeyChanged: if (settled && !Theme.reduced) fadeIn.restart()
    NumberAnimation { id: fadeIn; target: body; property: "opacity"; from: 0; to: 1; duration: Theme.base; easing.type: Easing.OutCubic }

    Item {
        id: body; objectName: "ribbonBody"; anchors.fill: parent; clip: true
        Row {
            id: row; x: rb.pad; height: parent.height; spacing: 0
            Repeater {
                model: rb.groups
                Row {
                    id: grp
                    required property var modelData
                    required property int index
                    readonly property int keep: rb.plan.keep[index] || 0
                    readonly property bool first: { for (var i = 0; i < index; i++) if (rb.plan.keep[i]) return false; return true }
                    objectName: "ribbonGroup-" + modelData.id
                    visible: keep > 0
                    height: parent.height; spacing: 0
                    Item { visible: !grp.first; width: rb.sepW; height: parent.height
                        Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 1; height: 18; color: Theme.rule } }
                    Item { visible: rb.plan.caps; width: rb._capW(grp.modelData); height: parent.height
                        Txt { objectName: "ribbonCaption-" + grp.modelData.id; kind: "cap"; text: grp.modelData.caption; x: 6
                            anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } }
                    Row {
                        spacing: rb.sp; anchors.verticalCenter: parent.verticalCenter
                        Repeater {
                            model: grp.modelData.tools.slice(0, grp.keep)
                            RibbonBtn { tipTo: rb
                                required property var modelData
                                readonly property var st: rb.host ? rb.host.toolState(modelData.id) : ({})
                                objectName: "ribbon-" + modelData.id
                                icon: modelData.icon; label: st.label || modelData.label; keys: modelData.keys || ""
                                hint: st.hint !== undefined ? st.hint : (modelData.hint || "")
                                compact: !!rb.plan.compact[grp.index]
                                active: !!st.active; marked: !!st.marked; toggle: !!st.toggle; enabled: st.enabled !== false
                                onClicked: if (rb.host) rb.host.toolRun(modelData.id)
                            }
                        }
                    }
                }
            }
            // More: the tools that did not fit, by group
            Item { visible: rb.plan.more.length > 0; width: rb.sepW; height: parent.height
                Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 1; height: 18; color: Theme.rule } }
            RibbonBtn {
                id: moreBtn; objectName: "ribbonMore"; tipTo: rb; visible: rb.plan.more.length > 0; anchors.verticalCenter: parent.verticalCenter
                icon: "ellipsis"; label: "More"; compact: true; hint: rb.plan.more.map(function (m) { return m.tool.label }).join(", ")
                active: moreMenu.opened
                marked: { if (!rb.host) return false; for (var i = 0; i < rb.plan.more.length; i++) if (rb.host.toolState(rb.plan.more[i].tool.id).active) return true; return false }
                onClicked: moreMenu.opened ? moreMenu.close() : moreMenu.open()
                PopMenu { id: moreMenu; y: parent.height + 10; x: Math.min(0, rb.width - moreBtn.x - width); width: 240
                    model: {
                        var out = [], last = ""
                        for (var i = 0; i < rb.plan.more.length; i++) {
                            var m = rb.plan.more[i], s = rb.host ? rb.host.toolState(m.tool.id) : ({})
                            if (last && m.group !== last) out.push({ sep: true })
                            last = m.group
                            out.push({ name: "ribbonMore-" + m.tool.id, icon: m.tool.icon, text: s.label || m.tool.label, keys: m.tool.keys || "",
                                       enabled: s.enabled !== false, checked: !!s.active, run: (function (id) { return function () { rb.host.toolRun(id) } })(m.tool.id) })
                        }
                        return out
                    } }
            }
        }
        // Hide: the band folds back into the icon dock
        RibbonBtn {
            objectName: "ribbonHide"; tipTo: rb; anchors.right: parent.right; anchors.rightMargin: rb.pad; anchors.verticalCenter: parent.verticalCenter
            icon: "eye_off"; label: "Hide tools"; compact: true
            hint: "Fold the tools into the dock at the stage’s edge. The stage gains the band’s height."
            onClicked: rb.hideAsked()
        }
    }

    // ── the tooltip of the tool under the pointer: under the band, its key beside the name ──
    // The first waits for the pointer to rest; moving along the band the next ones show at once (as in the dock).
    property Item tipBtn: null
    function tipFor(btn, on) {
        if (on) { tipBtn = btn; tipCool.stop(); if (tip.on) return; tipRest.restart() }
        else if (tipBtn === btn) { tipRest.stop(); if (tip.on) tipCool.restart(); tip.on = false; tipBtn = null }
    }
    Timer { id: tipRest; interval: Ws.tipWarm ? 0 : 380; onTriggered: { tip.on = true; Ws.tipWarm = true } }
    Timer { id: tipCool; interval: 420; onTriggered: Ws.tipWarm = false }
    Rectangle {
        id: tip; objectName: "ribbonTip"
        property bool on: false
        readonly property real cx: rb.tipBtn ? rb.tipBtn.mapToItem(rb, rb.tipBtn.width / 2, 0).x : 0
        x: Math.round(Math.max(0, Math.min(rb.width - width, cx - width / 2))); y: rb.height + 8; z: 20
        width: Math.min(tc.implicitWidth + 22, 320); height: tc.implicitHeight + 14; radius: Theme.rMd
        color: Theme.plate3; border.color: Theme.rule2
        visible: on && !!rb.tipBtn
        Column { id: tc; x: 11; y: 7; spacing: 2
            Row { spacing: 8
                Txt { text: rb.tipBtn ? rb.tipBtn.label : ""; font.pixelSize: 12; font.weight: Theme.wSemi; wrapMode: Text.NoWrap }
                Kbd { visible: !!rb.tipBtn && rb.tipBtn.keys !== ""; keys: rb.tipBtn ? rb.tipBtn.keys : ""; quiet: true; anchors.verticalCenter: parent.verticalCenter } }
            Txt { visible: !!rb.tipBtn && rb.tipBtn.hint !== ""; text: rb.tipBtn ? rb.tipBtn.hint : ""; kind: "fine"; tone: 2
                width: Math.min(implicitWidth, 298) } }
    }
}
