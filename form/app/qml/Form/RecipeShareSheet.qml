import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Share one of your recipes (form/recipe_share.py). Two ways, both started here and nowhere else:
//   As a file       one .formrecipe: the code, meta.json with the code's SHA-256 and its parameters, and a preview
//                   drawn from a real build. Whoever opens it reviews the code and checksum before installing.
//   The community   the gallery's folder (community/recipes/<id>/) saved where you choose, and a link that opens
//                   GitHub's recipe form with the fields filled in. Nothing is sent: you submit it on GitHub, or not.
//   Store.openSheet("shareRecipe", { id: "my-recipe", tab: "file" | "community" })
Column {
    id: sr
    objectName: "shareRecipeSheet"
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    readonly property string rid: props.id || ""
    property string title: "Share “" + (r ? r.meta.title : props.title || "recipe") + "”"
    property string note: r ? (r.meta.kind === "scad" ? "OpenSCAD" : "Python, build123d") + " · " + F.plural(r.meta.params_count, "parameter") : "Preparing…"
    property int sheetWidth: Theme.sheetXl
    readonly property var tabs: [{ value: "file", text: "As a file" }, { value: "community", text: "To the community" }]
    property string tab: props.tab || "file"
    property var r: null               // POST /recipes/share/prepare
    property var err: null
    property bool dirty: false
    readonly property var sub: r ? r.submission : null
    readonly property bool ready: !!r && !dirty
    spacing: 16

    function edits() { return { title: titleF.text, summary: sumF.text, author: authorF.text, tags: tagsF.text } }
    function load(withEdits) {
        err = null
        var p = Store.post("/recipes/share/prepare", { id: rid, edits: withEdits ? edits() : null })
        p.then(function (x) { sr.r = x; sr.dirty = false; sr.fill() }, function (e) { sr.err = e })
        return p
    }
    function fill() {
        titleF.text = r.meta.title; sumF.text = r.meta.summary; authorF.text = r.meta.author; tagsF.text = (r.meta.tags || []).join(", ")
        ;[titleF, sumF, authorF, tagsF].forEach(function (f) { f.input.cursorPosition = 0 })
        pv.tick++
    }
    Component.onCompleted: load(false)
    function savePkg() { pkgDlg.currentFile = Bridge.downloads() + "/" + r.package.name; Store.ask(pkgDlg) }
    function openIssue() {
        Bridge.openLink(sub.issue.url)
        Store.toast("Opened GitHub in your browser", "The form is filled in. Nothing is posted until you press Submit new issue there.")
    }
    function accept() { if (!ready) return; if (tab === "file") savePkg(); else if (sub && !sub.problems.length) openIssue() }

    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "arrow_left"; text: "Library"; onClicked: Store.openSheet("new", { tab: "recipe", section: "mine", pick: sr.rid }) }
        Btn { visible: sr.dirty; kind: "quiet"; icon: "check"; text: "Apply changes"; busyText: "Applying…"; onClicked: run(function () { return sr.load(true) }) }
        Btn { visible: sr.tab === "community" && !!sr.sub; kind: "quiet"; icon: "copy"; text: "Copy meta.json"; enabled: sr.ready
            onClicked: { Bridge.copy(sr.sub.meta_json); Store.toast("meta.json copied") } } }
    property Component footer: Row { spacing: 8
        Btn { visible: sr.tab === "file"; objectName: "sharePkgSave"; kind: "primary"; icon: "download"; text: "Save .formrecipe…"; enabled: sr.ready; keys: "Return"
            onClicked: sr.savePkg() }
        Btn { visible: sr.tab === "community"; objectName: "shareFolder"; icon: "folder"; text: "Save the submission folder…"; enabled: sr.ready
            tip: "For a pull request: community/recipes/" + (sr.sub ? sr.sub.meta.id : "") + "/ with the recipe, meta.json and preview.png"
            onClicked: Store.ask(folderDlg) }
        Btn { visible: sr.tab === "community"; objectName: "shareIssue"; kind: "primary"; icon: "external_link"; text: "Open a pre-filled GitHub issue in your browser"
            enabled: sr.ready && sr.sub.problems.length === 0; keys: "Return"; onClicked: sr.openIssue() } }

    // ── the recipe: its preview, and what it says about itself ──
    Row { width: parent.width; spacing: 20
        Rectangle {
            id: pvBox
            width: Math.round(parent.width * 0.48); height: Math.round(width * 560 / 960); radius: Theme.rLg; color: Theme.plate1; border.color: Theme.rule; clip: true
            Image { id: pv; objectName: "sharePreview"; property int tick: 0; readonly property bool ready: status === Image.Ready
                anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false
                source: sr.r ? Bridge.baseUrl + sr.r.preview + "?v=" + sr.r.meta.sha256 + "-" + tick : ""
                opacity: status === Image.Ready ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.slow } } }
            // a skeleton while the kernel builds it: the shape of what is coming, not an empty box
            Item { anchors.fill: parent; visible: pv.status !== Image.Ready && !sr.err; clip: true
                Rectangle { id: shim; width: parent.width * 0.6; height: parent.height
                    gradient: Gradient { orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.5; color: Theme.alpha(Theme.ink, 0.045) } GradientStop { position: 1; color: "transparent" } }
                    NumberAnimation on x { running: pv.status !== Image.Ready; from: -shim.width; to: pvBox.width; duration: 1300; loops: Animation.Infinite } }
                Column { anchors.centerIn: parent; spacing: 8
                    Spinner { size: 16; anchors.horizontalCenter: parent.horizontalCenter }
                    Txt { kind: "fine"; tone: 2; anchors.horizontalCenter: parent.horizontalCenter; text: "Building it in the CAD kernel to draw the preview…" } } }
            Column { anchors.centerIn: parent; spacing: 6; width: parent.width - 40; visible: !!sr.err
                Icon { name: "circle_alert"; size: 20; color: Theme.signal; anchors.horizontalCenter: parent.horizontalCenter }
                Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: sr.err ? sr.err.message : "" }
                Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; kind: "fine"; text: sr.err ? sr.err.hint || "" : "" }
                Btn { small: true; icon: "refresh_cw"; text: "Try again"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: sr.load(false) } }
        }
        Column { width: parent.width - pvBox.width - 20; spacing: 10
            Txt { kind: "fine"; width: parent.width; text: "What others see. The code is not changed." }
            Lbl { text: "Title" } Field { id: titleF; objectName: "shareTitle"; width: parent.width; onEdited: sr.dirty = true }
            Lbl { text: "Summary" } Field { id: sumF; width: parent.width; placeholder: "What it is and what makes it fit"; onEdited: sr.dirty = true }
            Row { width: parent.width; spacing: 10
                Column { width: (parent.width - 10) / 2; spacing: 4
                    Lbl { text: "Author" } Field { id: authorF; objectName: "shareAuthor"; width: parent.width; placeholder: "your GitHub username"; onEdited: sr.dirty = true } }
                Column { width: (parent.width - 10) / 2; spacing: 4
                    Lbl { text: "Tags" } Field { id: tagsF; objectName: "shareTags"; width: parent.width; placeholder: "desk, cables"; onEdited: sr.dirty = true } } }
            Txt { kind: "fine"; tone: 3; width: parent.width; visible: sr.dirty; color: Theme.amber; text: "Apply the changes to update the file and the submission." }
        }
    }

    // ── as a file ──
    Column { width: parent.width; spacing: 10; visible: sr.tab === "file"
        Rectangle { width: parent.width; height: fileCol.implicitHeight + 20; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule
            Column { id: fileCol; x: 12; y: 10; width: parent.width - 24; spacing: 6
                Row { spacing: 8
                    Icon { name: "package"; size: 14; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                    Txt { font.weight: Theme.wSemi; text: sr.r ? sr.r.package.name : "…" }
                    Txt { kind: "fine"; tone: 3; anchors.verticalCenter: parent.verticalCenter; text: sr.r ? F.fmt(sr.r.package.bytes / 1024, 1) + " kB" : "" } }
                Txt { kind: "fine"; width: parent.width; text: "recipe" + (sr.r && sr.r.meta.kind === "scad" ? ".scad" : ".py") + " · meta.json (title, summary, author, tags, every parameter with its range, the code’s SHA-256) · preview.png" }
                Row { spacing: 8; width: parent.width
                    Txt { kind: "cap"; text: "SHA-256"; anchors.verticalCenter: parent.verticalCenter }
                    Txt { mono: true; font.pixelSize: 12; tone: 2; text: sr.r ? sr.r.meta.sha256 : ""; width: parent.width - 120; elide: Text.ElideMiddle; wrapMode: Text.NoWrap } } } }
        Txt { kind: "fine"; width: parent.width
            text: "Send the file however you like. Whoever opens it in Form Studio sees the whole code and this checksum before anything is installed, and the code runs only when they create a design from it." }
    }

    // ── to the community ──
    Column { width: parent.width; spacing: 10; visible: sr.tab === "community"
        Note { visible: !!sr.sub && sr.sub.problems.length > 0; kind: "amber"; title: "Before it can go to the gallery"
            text: sr.sub ? sr.sub.problems.join(" ") : "" }
        Note { visible: !!sr.sub && sr.sub.notes.length > 0; kind: "blue"; text: sr.sub ? sr.sub.notes.join(" ") : "" }
        Rectangle { width: parent.width; height: sumCol.implicitHeight + 20; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule
            Column { id: sumCol; x: 12; y: 10; width: parent.width - 24; spacing: 5
                Txt { kind: "cap"; text: "What the GitHub form will show, filled in" }
                Repeater { model: sr.sub ? [["Title", sr.sub.issue.fields.title], ["Recipe id", sr.sub.meta.id], ["The object", sr.sub.meta.summary || "—"],
                                             ["meta.json", sr.sub.meta.tags.length + " tags, " + sr.sub.meta.params_count + " parameters, by " + (sr.sub.meta.author || "—")],
                                             ["Parameters", sr.sub.issue.omitted.indexOf("params") >= 0 ? "left out: the link would be too long" : sr.sub.meta.params_count + " lines"],
                                             ["Recipe code", sr.sub.issue.omitted.indexOf("recipe_code") >= 0 ? "too long for a link: drag the file from the saved folder" : "the whole file"]] : []
                    Row { required property var modelData; spacing: 10; width: sumCol.width
                        Txt { kind: "fine"; tone: 3; text: modelData[0]; width: 96 }
                        Txt { kind: "fine"; tone: 1; text: modelData[1]; width: parent.width - 106; elide: Text.ElideRight; wrapMode: Text.NoWrap } } }
                Txt { kind: "fine"; tone: 4; mono: true; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                    text: sr.sub ? sr.sub.issue.url.slice(0, 92) + "…  (" + sr.sub.issue.chars + " characters)" : "" } } }
        Txt { kind: "fine"; width: parent.width
            text: "The button opens github.com in your browser with the recipe form filled in. Nothing is sent from Form Studio: you read it there, drag preview.png in from the submission folder, choose “This is”, and submit it, or close the tab. "
                + "If you prefer a pull request, save the submission folder into community/recipes/ of your fork; it is exactly what the gallery reads." }
        Btn { kind: "quiet"; small: true; icon: "book_open"; text: "How the gallery works"; x: -8; onClicked: Bridge.openLink(sr.sub ? sr.sub.guide : "https://github.com/kaizensx/form-studio/tree/main/community/recipes") }
    }

    component Lbl: Txt { kind: "cap" }

    FileDialog { id: pkgDlg; title: "Save the recipe package"; fileMode: FileDialog.SaveFile; nameFilters: ["Form Studio recipes (*.formrecipe)"]
        onAccepted: {
            if (Bridge.save(sr.r.package.api, selectedFile)) { Store.toast("Saved " + sr.r.package.name, "Anyone with Form Studio can open it with New design › Install from a file."); Bridge.reveal(selectedFile) }
            else Store.toast("Could not write that file", "Choose another place.", true)
        } }
    FolderDialog { id: folderDlg; title: "Save the submission folder into…"
        onAccepted: {
            var dir = decodeURIComponent(String(String(selectedFolder) ? selectedFolder : currentFolder).replace(/^file:\/\//, "").replace(/^\/([A-Za-z]:)/, "$1"))
            Store.post("/recipes/share/submission", { id: sr.rid, dir: dir }).then(function (x) {
                Store.toast("Submission folder saved", x.dir + ": the recipe, meta.json and preview.png")
                Bridge.reveal(Bridge.fileUrl(x.files[x.files.length - 1]))
            }, Store.fail)
        } }
}
