import QtQuick
import FormNative

// Add or edit a model provider by its address (Settings › Agents & models › Your providers). The person types a name
// (optional), the base URL and an API key (optional for a server on this computer); "Check connection" asks the
// engine to work out the rest (POST /providers/detect, form/agents/custom.py: wire format, models, tool support)
// and shows it before anything is saved. The key goes into Form Studio's private secrets file and is never shown again.
Rectangle {
    id: ed
    property var editing: null              // a provider from GET /providers when editing, else null (adding)
    signal closed()
    signal saved(var provider)
    property var result: null               // the last detect() answer for exactly these inputs
    property bool checking: false
    property bool saving: false
    readonly property bool ok: !!result && result.ok
    width: parent ? parent.width : 600
    height: col.implicitHeight + 32; radius: Theme.rMd
    color: Theme.plate2; border.color: Theme.rule2
    opacity: 0; scale: Theme.from(0.985)
    Component.onCompleted: { opacity = 1; scale = 1; uf.input.forceActiveFocus() }
    Behavior on opacity { NumberAnimation { duration: Theme.pop; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    Behavior on scale { NumberAnimation { duration: Theme.move(Theme.pop); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    Behavior on height { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    function inputs() { return { name: nf.text.trim(), url: uf.text.trim(), key: kf.text.trim(), id: ed.editing ? ed.editing.id : "" } }
    function stale() { ed.result = null }
    function check() {
        if (!uf.text.trim()) { uf.input.forceActiveFocus(); return }
        ed.checking = true; ed.result = null
        Store.post("/providers/detect", ed.inputs()).then(function (r) { ed.checking = false; ed.result = r.detected },
                                                          function (e) { ed.checking = false; Store.fail(e) })
    }
    function save() {
        ed.saving = true
        Store.post("/providers/save", ed.inputs()).then(function (r) {
            ed.saving = false; kf.text = ""
            Store.toast((ed.editing ? "Updated " : "Added ") + r.provider.name, r.detected.message + ". It is in the model menu now.")
            ed.saved(r.provider)
        }, function (e) { ed.saving = false; Store.fail(e) })
    }
    Keys.onEscapePressed: ed.closed()
    clip: true

    Column {
        id: col; x: 16; y: 16; width: parent.width - 32; spacing: 12
        Item { width: parent.width; height: 22
            Txt { text: ed.editing ? "Edit " + ed.editing.name : "Add a provider"; font.weight: Theme.wSemi; font.pixelSize: Theme.tLead
                anchors.verticalCenter: parent.verticalCenter }
            Btn { small: true; kind: "quiet"; icon: "x"; tip: "Close"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                onClicked: ed.closed() } }
        Txt { kind: "fine"; width: parent.width
            text: "Any server that speaks the OpenAI, Anthropic or Gemini format: a company gateway, LiteLLM, vLLM, a hosted model service. Form Studio works out the format and reads the models itself." }
        Grid { columns: 2; columnSpacing: 12; rowSpacing: 10; width: parent.width
            readonly property real lw: 92
            Txt { text: "Address"; width: parent.lw; height: Theme.hMd; verticalAlignment: Text.AlignVCenter; font.weight: Theme.wMedium }
            Field { id: uf; objectName: "providerUrl"; width: parent.width - parent.lw - 12; mono: true
                placeholder: "https://api.example.com/v1  or  http://localhost:8000"
                text: ed.editing ? (ed.editing.input || ed.editing.base) : ""
                onEdited: ed.stale(); onAccepted: ed.check() }
            Txt { text: "API key"; width: parent.lw; height: Theme.hMd; verticalAlignment: Text.AlignVCenter; font.weight: Theme.wMedium }
            Field { id: kf; objectName: "providerKey"; width: parent.width - parent.lw - 12; mono: true; input.echoMode: TextInput.Password
                placeholder: ed.editing && ed.editing.key_set ? "Stored privately. Paste a new key to replace it." : "Optional for a server on this computer or network"
                onEdited: ed.stale(); onAccepted: ed.check() }
            Txt { text: "Name"; width: parent.lw; height: Theme.hMd; verticalAlignment: Text.AlignVCenter; font.weight: Theme.wMedium }
            Field { id: nf; objectName: "providerName"; width: parent.width - parent.lw - 12
                placeholder: "Optional: shown in the model menu (the server's name otherwise)"
                text: ed.editing ? ed.editing.name : ""; onAccepted: ed.check() } }

        // what the server turned out to be, before anything is saved
        Note { objectName: "providerResult"; visible: !!ed.result; width: parent.width
            kind: !ed.result ? "plain" : !ed.result.ok ? "red" : ed.result.tools === "no" || (ed.result.warnings || []).length ? "amber" : "green"
            title: !ed.result ? "" : ed.result.ok ? ed.result.message : ed.result.message
            text: !ed.result ? "" : !ed.result.ok ? (ed.result.hint || "")
                : ed.result.base + (ed.result.images ? " · " + ed.result.images + " take images" : "")
            Column { visible: !!ed.result && ed.result.ok; width: parent.width; spacing: 4
                Repeater { model: ed.result && ed.result.warnings ? ed.result.warnings : []
                    Txt { required property string modelData; kind: "fine"; width: parent.width; color: Theme.amber; text: modelData } }
                Flow { width: parent.width; spacing: 4; topPadding: 2
                    Repeater { model: ed.result && ed.result.models ? ed.result.models.slice(0, 8) : []
                        Rectangle { required property var modelData
                            height: 20; radius: Theme.rXs; width: ml.implicitWidth + (modelData.tools === true ? 26 : 14); color: Theme.alpha(Theme.ink, 0.06)
                            Txt { id: ml; x: 7; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; mono: true; tone: 2; text: parent.modelData.id }
                            Icon { visible: parent.modelData.tools === true; name: "wrench"; size: 10; color: Theme.pass; anchors.right: parent.right
                                anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter } } }
                    Txt { visible: !!ed.result && ed.result.count > 8; kind: "fine"; height: 20; verticalAlignment: Text.AlignVCenter
                        text: ed.result ? "and " + (ed.result.count - 8) + " more" : "" } } }
            Txt { visible: !!ed.result && !ed.result.ok && (ed.result.tried || []).length > 0; kind: "fine"; tone: 4; mono: true; font.pixelSize: 10
                width: parent.width; wrapMode: Text.WrapAnywhere; text: ed.result && ed.result.tried ? "Tried " + ed.result.tried.join("  ·  ") : "" } }

        Item { width: parent.width; height: Theme.hMd
            Txt { kind: "fine"; tone: 3; width: parent.width - btns.width - 16; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                wrapMode: Text.NoWrap
                text: ed.ok ? "Nothing is saved until you press Save. The key stays in a private file on this computer."
                            : "Checking reads the server's model list; no model is called." }
            Row { id: btns; spacing: 8; anchors.right: parent.right
                Btn { kind: "quiet"; text: "Cancel"; onClicked: ed.closed() }
                Btn { objectName: "providerCheck"; kind: ed.ok ? "default" : "primary"; icon: "refresh_cw"; busy: ed.checking
                    text: ed.result ? "Check again" : "Check connection"; enabled: uf.text.trim().length > 0; onClicked: ed.check() }
                Btn { objectName: "providerSave"; visible: ed.ok; kind: "primary"; icon: "check"; busy: ed.saving
                    text: ed.editing ? "Save changes" : "Save provider"; onClicked: ed.save() } } }
    }
}
