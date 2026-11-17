import QtQuick
import FormNative

// A run of tool calls, folded into one tidy group: "7 steps". The steps that change or show the design
// (new design, code rewrite, commit, a render with its picture) are always visible; the rest unfold on click.
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
        case "create_project": return ["cuboid", "Started a design from the " + (arg(s, "recipe") || "chosen") + " recipe"]
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
    readonly property var shown: steps.filter(function (s, i) {
        if (sg.expanded) return true
        var r = sg.res(s)
        return !!sg.rich(s) || (r && !r.ok) || (!r && sg.running && i === sg.steps.length - 1)
    })

    // header
    Item {
        width: sg.width; height: 24
        Rectangle { anchors.fill: parent; radius: Theme.rXs; color: hm.pressed ? Theme.washPress : hm.containsMouse ? Theme.washHover : "transparent" }
        Icon { x: 2; name: sg.expanded ? "chevron_down" : "chevron_right"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
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
            readonly property var how: sg.rich(modelData)
            width: sg.width; spacing: 4
            Item {
                width: parent.width; height: 22
                Rectangle { x: 8; width: 1; height: parent.height; color: Theme.rule2 }
                Icon { x: 18; anchors.verticalCenter: parent.verticalCenter; size: 12
                    name: !st.r ? "loader_circle" : !st.r.ok ? "x" : st.how ? st.how[0] : "check"
                    color: !st.r ? Theme.datum : !st.r.ok ? Theme.signal : st.how ? Theme.ink2 : Theme.ink4
                    RotationAnimation on rotation { running: !st.r && sg.running; from: 0; to: 360; duration: 900; loops: Animation.Infinite } }
                Txt { id: lbl; x: 38; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                    mono: !st.how; font.pixelSize: st.how ? 12 : 11; tone: st.how ? 2 : 3
                    text: st.how ? st.how[1] : st.modelData.tool }
                // a step still running says for how long (pipelines, renders and questions can take a while)
                Txt { id: el; objectName: "stepElapsed"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    visible: !st.r && sg.running && !!st.modelData.ts && text !== ""; mono: true; font.pixelSize: 11; tone: 3
                    text: { var t = (Store.chatSeconds, Date.now() / 1000 - (st.modelData.ts || 0))
                            return t < 3 ? "" : t < 90 ? Math.round(t) + " s" : Math.floor(t / 60) + " min " + Math.round(t % 60) + " s" } }
                Txt { anchors.left: lbl.right; anchors.leftMargin: 8; anchors.right: el.visible ? el.left : parent.right; anchors.rightMargin: el.visible ? 8 : 0; anchors.verticalCenter: parent.verticalCenter
                    visible: !st.how || sg.expanded; mono: true; font.pixelSize: 11; tone: 4; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: st.how ? st.modelData.tool : (st.modelData.input || "") }
            }
            Txt { visible: !!st.r && !st.r.ok && !!st.r.text; x: 38; width: parent.width - 38; kind: "fine"; color: Qt.lighter(Theme.signal, 1.2)
                text: st.r && st.r.text ? st.r.text : ""; maximumLineCount: sg.expanded ? 8 : 2; elide: Text.ElideRight }
            // the picture the agent looked at
            Rectangle {
                visible: !!st.r && !!st.r.img; x: 38; width: Math.min(parent.width - 38, 300)
                height: visible ? (im.status === Image.Ready ? Math.round(width * im.implicitHeight / Math.max(1, im.implicitWidth)) : Math.round(width * 0.7)) : 0
                radius: Theme.rMd; color: Theme.plate2; border.color: tm.containsMouse ? Theme.rule3 : Theme.rule; clip: true
                Behavior on border.color { Tint {} }
                Image { id: im; anchors.fill: parent; anchors.margins: 1; asynchronous: true; fillMode: Image.PreserveAspectFit; sourceSize.width: 640; mipmap: true
                    source: st.r && st.r.img ? Bridge.baseUrl + "/api/conversations/render/" + st.r.img.project + "/" + st.r.img.file : "" }
                Txt { anchors.centerIn: parent; kind: "fine"; visible: im.status === Image.Error; text: "This render is no longer on disk" }
                // click: the picture, large. The corner button turns the 3D view to the same angle instead.
                MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true
                    onClicked: Store.showImage(im.source, st.how ? st.how[1] : "Render", "Rendered by Form Studio from the kernel geometry") }
                Rectangle { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6; width: 26; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate, 0.8); border.color: Theme.rule2
                    opacity: tm.containsMouse || vb.hovered ? 1 : 0; visible: opacity > 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                    Btn { id: vb; anchors.centerIn: parent; small: true; kind: "quiet"; icon: st.r && st.r.img && st.r.img.project !== Store.pid ? "arrow_up_right" : "rotate_3d"
                        tip: st.r && st.r.img && st.r.img.project !== Store.pid ? "Open this design" : "Show this view in 3D"
                        onClicked: if (st.r.img.project !== Store.pid) Store.open(st.r.img.project); else if (sg.arg(st.modelData, "view") && Store._viewMap[sg.arg(st.modelData, "view")]) Store.setView(Store._viewMap[sg.arg(st.modelData, "view")]) } }
                Rectangle { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 6; width: 24; height: 24; radius: Theme.rSm; color: Theme.alpha(Theme.plate, 0.8)
                    opacity: tm.containsMouse ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                    Icon { anchors.centerIn: parent; name: "expand"; size: 12; color: Theme.ink } }
            }
            Item { visible: !!st.r && !!st.r.img; width: 1; height: 2 }
        }
    }
}
