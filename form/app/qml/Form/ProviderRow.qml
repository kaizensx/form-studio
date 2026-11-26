import QtQuick
import FormNative

// One provider you added by URL, in Settings › Agents & models › Your providers. `p` is its entry from GET /providers (never
// the key), `a` its agent from GET /chat (models, availability). Test asks one model, on your click, whether it calls
// tools or takes images (POST /providers/probe: a few tokens); the answer is kept and shown in the model menu.
Item {
    id: pr
    property var p: ({})
    property var a: null
    property bool first: false
    signal edit()
    signal changed()
    property bool testing: false
    property bool confirm: false
    property string testModel: ""
    property var probe: null
    property bool busy: false
    readonly property var models: a && a.models ? a.models.filter(function (m) { return m.id !== "default" }) : []
    readonly property bool up: !!a && a.available
    width: parent ? parent.width : 600
    height: body.implicitHeight + 22
    clip: true
    Behavior on height { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    function test(what) {
        pr.busy = true; pr.probe = null
        Store.post("/providers/probe", { id: pr.p.id, model: pr.testModel || (pr.models[0] || {}).id, what: what }).then(function (r) {
            pr.busy = false; pr.probe = r.probe; Store.refreshAgents(); pr.changed()
        }, function (e) { pr.busy = false; Store.fail(e) })
    }
    Rectangle { x: 16; y: 17; width: 7; height: 7; radius: 3.5; color: pr.up ? Theme.pass : pr.a ? Theme.signal : Theme.ink4 }
    Column {
        id: body; x: 32; y: 11; width: parent.width - 48; spacing: 6
        Item { width: parent.width; height: Math.max(info.implicitHeight, 28)
            Column { id: info; width: parent.width - acts.width - 12; spacing: 2; anchors.verticalCenter: parent.verticalCenter
                Row { spacing: 8
                    Txt { text: pr.p.name || ""; font.weight: Theme.wMedium }
                    Tag { text: pr.p.format || ""; tint: Theme.blueprint; anchors.verticalCenter: parent.verticalCenter } }
                Txt { kind: "fine"; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight
                    color: pr.up ? Theme.pass : pr.a ? Theme.amber : Theme.ink3
                    text: pr.up ? pr.models.length + (pr.models.length === 1 ? " model" : " models")
                                  + ({ yes: " · tools supported", some: " · tools on some models", no: " · no tool support listed", unknown: " · tool support not listed" })[pr.p.tools || "unknown"]
                                  + (pr.p.key_set ? " · key stored privately, not shown again" : pr.p.local ? " · no key" : "")
                        : pr.a ? (pr.a.why || "Not answering.") : "Looking…" }
                Txt { kind: "fine"; tone: 4; mono: true; font.pixelSize: 10; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; text: pr.p.base || "" } }
            Row { id: acts; spacing: 6; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Btn { visible: !pr.confirm && pr.up; small: true; kind: "quiet"; icon: "flask_conical"; text: "Test"; active: pr.testing
                    objectName: "providerTest"; onClicked: pr.testing = !pr.testing }
                Btn { visible: !pr.confirm; small: true; kind: "quiet"; icon: "pencil"; text: "Edit"; objectName: "providerEdit"; onClicked: pr.edit() }
                Btn { visible: !pr.confirm; small: true; kind: "quiet"; icon: "trash_2"; tip: "Remove"; objectName: "providerRemove"; onClicked: pr.confirm = true }
                Txt { visible: pr.confirm; kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: "Remove it and its key?" }
                Btn { visible: pr.confirm; small: true; kind: "quiet"; text: "Keep"; onClicked: pr.confirm = false }
                Btn { visible: pr.confirm; small: true; kind: "danger"; text: "Remove"; objectName: "providerRemoveYes"
                    onClicked: Store.post("/providers/remove", { id: pr.p.id }).then(function () {
                        Store.toast("Removed " + pr.p.name, "Its key was deleted from this computer."); pr.confirm = false; Store.refreshAgents(); pr.changed() }, Store.fail) } } }
        // test one model: does it call tools, does it take images
        Rectangle { visible: pr.testing; width: parent.width; height: tcol.implicitHeight + 20; radius: Theme.rMd; color: Theme.glassWell; border.color: Theme.rule
            Column { id: tcol; x: 10; y: 10; width: parent.width - 20; spacing: 8
                Txt { kind: "fine"; width: parent.width
                    text: "Sends one short message to the model you pick (a few tokens, billed like any other). Form Studio's agent needs tool calls." }
                Row { spacing: 8
                    Pick { width: Math.min(320, tcol.width - 260); value: pr.testModel || (pr.models[0] || {}).id
                        model: pr.models.map(function (m) { return { value: m.id, text: m.label + (m.tools === true ? "  ✓ tools" : m.tools === false ? "  · no tools" : "") } })
                        onPicked: function (v) { pr.testModel = v; pr.probe = null } }
                    Btn { small: true; text: "Tool calls"; icon: "wrench"; busy: pr.busy; enabled: pr.models.length > 0; anchors.verticalCenter: parent.verticalCenter
                        objectName: "providerProbeTools"; onClicked: pr.test("tools") }
                    Btn { small: true; text: "Images"; icon: "image"; enabled: !pr.busy && pr.models.length > 0; anchors.verticalCenter: parent.verticalCenter
                        onClicked: pr.test("images") } }
                Txt { visible: !!pr.probe; kind: "fine"; width: parent.width
                    color: !pr.probe ? Theme.ink3 : pr.probe.result === true ? Theme.pass : pr.probe.result === false ? Theme.signal : Theme.amber
                    text: pr.probe ? pr.probe.model + ": " + pr.probe.message : "" } } }
    }
}
