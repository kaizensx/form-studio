import QtQuick
import FormNative

// A run of tool calls, folded into one tidy group: "7 steps". A step that changes the design (a new design, a code
// rewrite, a commit) is a compact card: an icon, one sentence, and the 64 px picture of the render the agent took of
// it, which opens large. A render on its own is the same card. The rest are one-line rows that unfold on click.
Column {
    id: sg
    property var steps: []                 // [{ id, tool, input, ts }]
    property bool running: false           // this group is still being added to
    property bool expanded: false
    signal toggle()
    spacing: 2

    function res(s) { return Store.chatTools[s.id] || null }
    function arg(s, key) { var m = new RegExp("(?:^| )" + key + "=(\\S+)").exec(s.input || ""); return m ? m[1] : "" }
    // the steps worth a sentence: [icon, text]
    function rich(s) {
        switch (s.tool) {
        case "create_design": return ["cuboid", "Wrote a new design"]
        case "create_project": return ["cuboid", "Started a design from a building block"]
        case "update_design": return ["pencil_ruler", "Rewrote the design code"]
        case "commit_change": return ["git_commit_horizontal", "Committed a revision"]
        case "render": return ["eye", "Looked at the " + (arg(s, "view") || "iso").replace("_", " ") + " view" + (arg(s, "highlight") ? ", " + arg(s, "highlight") : "")]
        case "render_photo": return ["camera", "Rendered an illustration in Blender"]
        case "import_reference": return ["box", "Imported a reference part"]
        case "read_document": return ["file_text", "Read a document"]
        case "Read": return ["paperclip", "Looked at an attached file"]
        case "WebSearch": case "web_search": return ["search", "Searched the web"]
        case "ask_user": return ["message_square", "Asked you a question"]
        case "run_pipeline": return ["play", "Ran the pipeline"]
        }
        return null
    }
    readonly property int failed: steps.filter(function (s) { var r = sg.res(s); return r && !r.ok }).length
    function changes(s) { return s.tool === "create_design" || s.tool === "create_project" || s.tool === "update_design" || s.tool === "commit_change" }
    function pic(s) { var r = sg.res(s); return r && r.ok && r.img ? r.img : null }
    // The picture of a change is the first render taken after it, before the next change. That render is then part
    // of the card and does not get a row of its own while the group is folded.
    readonly property var plan: {
        var own = {}, taken = {}
        for (var i = 0; i < steps.length; i++) {
            if (!sg.changes(steps[i])) continue
            for (var j = i + 1; j < steps.length && !sg.changes(steps[j]); j++)
                if (steps[j].tool === "render" && sg.pic(steps[j])) { own[steps[i].id] = steps[j]; taken[steps[j].id] = true; break }
        }
        return { own: own, taken: taken }
    }
    readonly property var shown: steps.filter(function (s, i) {
        if (sg.expanded) return true
        var r = sg.res(s)
        if (sg.plan.taken[s.id]) return false
        return !!sg.rich(s) || (r && !r.ok) || (!r && sg.running && i === sg.steps.length - 1)
    })

    // header
    Item {
        width: sg.width; height: 24
        Rectangle { anchors.fill: parent; radius: Theme.rXs; color: hm.pressed ? Theme.washPress : hm.containsMouse ? Theme.washHover : "transparent" }
        Icon { x: 2; name: "chevron_right"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter
            rotation: sg.expanded ? 90 : 0; Behavior on rotation { Glide { duration: Theme.move(Theme.ui) } } }
        Row { x: 20; spacing: 8; anchors.verticalCenter: parent.verticalCenter
            Txt { kind: "fine"; tone: 2; font.weight: 550; text: sg.steps.length + (sg.steps.length === 1 ? " step" : " steps") }
            Txt { kind: "fine"; visible: sg.failed > 0; color: Theme.signal; text: sg.failed + " failed" }
            Txt { kind: "fine"; tone: 4; visible: !sg.expanded && sg.shown.length < sg.steps.length; text: (sg.steps.length - sg.shown.length) + " folded" } }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; onClicked: sg.toggle() }
    }
    Repeater {
        model: sg.shown
        Column {
            id: st
            required property var modelData
            readonly property var r: sg.res(modelData)
            required property int index
            readonly property var how: sg.rich(modelData)
            // the render whose picture this step shows: its own, or the one taken of the change it made
            readonly property var shot: sg.pic(modelData) ? modelData : (sg.plan.own[modelData.id] || null)
            readonly property var img: shot ? sg.pic(shot) : null
            readonly property bool card: (!st.r || st.r.ok) && !!st.how && (sg.changes(modelData) || !!st.img)
            readonly property string imgUrl: img ? Bridge.baseUrl + "/api/conversations/render/" + img.project + "/" + img.file : ""
            readonly property string elapsed: { var t = (Store.chatSeconds, Date.now() / 1000 - (modelData.ts || 0))
                return st.r || !sg.running || !modelData.ts || t < 3 ? "" : t < 90 ? Math.round(t) + " s" : Math.floor(t / 60) + " min " + Math.round(t % 60) + " s" }
            width: sg.width; spacing: 4
            topPadding: card ? 3 : 0; bottomPadding: card ? 3 : 0
            // unfolded steps cascade in under the header; a step the agent just took fades in where it lands
            opacity: 0; transform: Translate { id: stIn; y: Theme.shift(-4) }
            SequentialAnimation { running: true
                PauseAnimation { duration: Math.min(st.index, 10) * (Theme.stagger / 2) }
                ParallelAnimation { Glide { target: st; property: "opacity"; to: 1; duration: Theme.ui }
                    Glide { target: stIn; property: "y"; to: 0; duration: Theme.move(Theme.ui) } } }
            // ── a change to the design, or a look at it: the compact card ──
            Rectangle {
                id: cd; objectName: "stepCard"; visible: st.card
                width: parent.width; height: visible ? (st.img ? 80 : 44) : 0; radius: Theme.rMd
                color: Theme.plate2; border.color: Theme.rule
                Rectangle { id: tile; x: 8; y: st.img ? 8 : 8; width: 28; height: 28; radius: Theme.rSm; color: Theme.washOn
                    Icon { anchors.centerIn: parent; size: 14; visible: !!st.r; name: st.how ? st.how[0] : "check"; color: Theme.ink2 }
                    Spinner { anchors.centerIn: parent; size: 13; visible: !st.r && sg.running; color: Theme.datum } }
                Column { x: 46; width: parent.width - 46 - (st.img ? 80 : 10) - (el.visible ? el.width + 8 : 0); spacing: 2
                    y: st.img ? 10 : Math.round((parent.height - height) / 2)
                    Txt { width: parent.width; font.weight: Theme.wMedium; maximumLineCount: st.img ? 2 : 1; elide: Text.ElideRight; lineHeight: 1.25
                        wrapMode: st.img ? Text.WordWrap : Text.NoWrap; text: st.how ? st.how[1] : "" }
                    Txt { width: parent.width; visible: st.img || sg.expanded; mono: true; font.pixelSize: Theme.tCap; tone: 3; elide: Text.ElideRight; wrapMode: Text.NoWrap
                        text: sg.expanded || !st.shot || st.shot === st.modelData ? st.modelData.tool : "then looked at the " + (sg.arg(st.shot, "view") || "iso").replace("_", " ") + " view" } }
                Txt { id: el; objectName: "stepElapsed"; visible: st.card && text !== ""; mono: true; font.pixelSize: 11; tone: 3
                    anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: st.elapsed }
                // the picture: 64 px, the whole render one click away
                Rectangle { id: th; objectName: "stepThumb"; visible: !!st.img; x: parent.width - 72; y: 8; width: 64; height: 64; radius: Theme.rSm; clip: true
                    color: Theme.plate; border.color: tm.containsMouse ? Theme.rule3 : Theme.rule2
                    scale: tm.pressed ? Theme.from(0.97) : 1
                    Behavior on scale { Glide { duration: Theme.press } }
                    Behavior on border.color { Tint {} }
                    Image { id: im; anchors.fill: parent; anchors.margins: 1; asynchronous: true; fillMode: Image.PreserveAspectCrop; sourceSize.width: 256; mipmap: true
                        source: st.imgUrl; opacity: status === Image.Ready ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.cross } } }
                    Icon { anchors.centerIn: parent; visible: im.status === Image.Error; name: "circle_alert"; size: 14; color: Theme.ink4 }
                    MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; enabled: im.status === Image.Ready
                        onClicked: Store.showImage(st.imgUrl, st.how ? st.how[1] : "Render", "Rendered by Form Studio from the kernel geometry") }
                    Tip { show: tm.containsMouse; text: im.status === Image.Error ? "This render is no longer on disk" : "Open the render" } }
                // turn the 3D view to the same angle, or open the design it shows
                Btn { id: vb; visible: !!st.img && (ch.hovered || hovered); x: parent.width - 72 - width - 6; y: parent.height - height - 8; small: true; kind: "quiet"
                    icon: st.img && st.img.project !== Store.pid ? "arrow_up_right" : "rotate_3d"
                    tip: st.img && st.img.project !== Store.pid ? "Open this design" : "Show this view in 3D"
                    onClicked: if (st.img.project !== Store.pid) Store.open(st.img.project); else if (sg.arg(st.shot, "view") && Store._viewMap[sg.arg(st.shot, "view")]) Store.setView(Store._viewMap[sg.arg(st.shot, "view")]) }
                HoverHandler { id: ch }
            }
            // ── any other step: one line ──
            Item {
                visible: !st.card
                width: parent.width; height: visible ? 22 : 0
                Rectangle { x: 8; width: 1; height: parent.height; color: Theme.rule2 }
                Icon { x: 18; anchors.verticalCenter: parent.verticalCenter; size: 12
                    name: !st.r ? "loader_circle" : !st.r.ok ? "x" : st.how ? st.how[0] : "check"
                    color: !st.r ? Theme.datum : !st.r.ok ? Theme.signal : st.how ? Theme.ink2 : Theme.ink4
                    RotationAnimation on rotation { running: !st.r && sg.running && !st.card; from: 0; to: 360; duration: 900; loops: Animation.Infinite } }
                Txt { id: lbl; x: 38; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                    mono: !st.how; font.pixelSize: st.how ? 12 : 11; tone: st.how ? 2 : 3
                    text: st.how ? st.how[1] : st.modelData.tool }
                // a step still running says for how long (pipelines, renders and questions can take a while)
                Txt { id: el2; objectName: "stepElapsed"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    visible: !st.card && text !== ""; mono: true; font.pixelSize: 11; tone: 3; text: st.elapsed }
                Txt { anchors.left: lbl.right; anchors.leftMargin: 8; anchors.right: el2.visible ? el2.left : parent.right; anchors.rightMargin: el2.visible ? 8 : 0; anchors.verticalCenter: parent.verticalCenter
                    visible: !st.how || sg.expanded; mono: true; font.pixelSize: 11; tone: 4; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: st.how ? st.modelData.tool : (st.modelData.input || "") }
            }
            Txt { visible: !!st.r && !st.r.ok && !!st.r.text; x: 38; width: parent.width - 38; kind: "fine"; color: Theme.strong(Theme.signal)
                text: st.r && st.r.text ? st.r.text : ""; maximumLineCount: sg.expanded ? 8 : 2; elide: Text.ElideRight }
            // features a partial build left out for now (form/chat.py left_out): one calm line each, with the reason
            // the build measured; the design itself was saved
            Repeater { model: st.r && st.r.left_out ? st.r.left_out : []
                Row { required property var modelData; objectName: "leftOut"; x: st.card ? 10 : 38; width: st.width - x; spacing: 6
                    Icon { name: "circle_dashed"; size: 12; color: Theme.ink3; y: 2 }
                    // the whole reason (form/chat.py left_out keeps it to whole sentences): never cut mid-sentence
                    Txt { objectName: "leftOutReason"; width: parent.width - 18; kind: "fine"; tone: 2; wrapMode: Text.WordWrap
                        text: "Left out for now: " + parent.modelData.feature + (parent.modelData.reason ? " · " + parent.modelData.reason : "") } } }
        }
    }
}
