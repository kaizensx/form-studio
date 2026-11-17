import QtQuick
import QtQuick.Controls
import FormNative

// Review a recipe before it is installed, or look at one that is. A recipe is code: the whole source and its SHA-256
// are on screen, a community recipe's download has been checked against the checksum in the index, and nothing is
// installed until Install is pressed. Installing only copies the file; it runs when a design is created from it.
//   Store.openSheet("recipe", { mode: "file" | "community" | "installed", info: {...} })
Column {
    id: rs
    objectName: "recipeSheet"
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    readonly property string mode: props.mode || "file"
    readonly property var info: props.info || ({})
    readonly property var entry: info.entry || info
    readonly property bool bad: (info.problems || []).length > 0
    property bool busy: false
    property string title: mode === "installed" ? entry.title || "Recipe" : "Install “" + (entry.title || info.title || "recipe") + "”?"
    property string note: (info.kind === "scad" ? "OpenSCAD" : "Python, build123d") + " · " + (info.lines || String(info.source || "").split("\n").length) + " lines"
    property int sheetWidth: Theme.sheetL
    function install() {
        if (busy || bad) return
        busy = true
        var p = mode === "community" ? Store.post("/recipes/community/install", { id: entry.id, sha256: info.sha256 })
                                     : Store.post("/recipes/install", { source: info.source, kind: info.kind, sha256: info.sha256, title: info.title, summary: info.summary })
        p.then(function (m) {
            busy = false
            Store.toast("Installed “" + m.title + "”", "It is in My recipes. Its code runs when you create a design from it.")
            Store.openSheet("new", { tab: "recipe", section: "mine", pick: m.id })
        }, function (e) { busy = false; Store.fail(e) })
    }
    function uninstall() {
        Store.post("/recipes/uninstall", { id: entry.id }).then(function (r) {
            Store.toast("Uninstalled “" + r.title + "”", "Designs made from it keep their own copy of the code.")
            Store.openSheet("new", { tab: "recipe", section: "mine" })
        }, Store.fail)
    }
    function accept() { if (mode !== "installed") install() }
    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "arrow_left"; text: "Library"; onClicked: Store.openSheet("new", { tab: "recipe", section: rs.mode === "community" ? "community" : "mine" }) }
        Btn { kind: "quiet"; icon: "copy"; text: "Copy the source"; onClicked: { Bridge.copy(rs.info.source || ""); Store.toast("Source copied") } } }
    property Component footer: Row { spacing: 8
        Btn { visible: rs.mode === "installed"; kind: "danger"; icon: "trash_2"; text: "Uninstall"; onClicked: rs.uninstall() }
        Btn { visible: rs.mode === "installed"; objectName: "recipeCreate"; kind: "primary"; icon: "plus"; text: "Create a design"
            onClicked: Store.openSheet("new", { tab: "recipe", section: "mine", pick: rs.entry.id }) }
        Btn { visible: rs.mode !== "installed"; kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet("new", { tab: "recipe" }) }
        Btn { visible: rs.mode !== "installed"; objectName: "recipeInstall"; kind: "primary"; icon: "download"; text: "Install"
            enabled: !rs.bad; busy: rs.busy; onClicked: rs.install() } }
    spacing: 14

    Row { width: parent.width; spacing: 14
        Rectangle { width: 44; height: 44; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule2
            Icon { anchors.centerIn: parent; name: rs.mode === "community" ? "globe" : "file_code"; size: 20; color: Theme.ink2 } }
        Column { width: parent.width - 58; spacing: 3; anchors.verticalCenter: parent.verticalCenter
            Txt { text: rs.entry.summary || rs.info.summary || "No description in the file."; tone: rs.entry.summary || rs.info.summary ? 1 : 3; width: parent.width }
            Txt { kind: "fine"; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                text: [rs.entry.author ? "by " + rs.entry.author : "", rs.mode === "file" ? rs.info.filename : rs.mode === "community" ? rs.entry.url : "",
                       (rs.info.params || rs.entry.params) ? (rs.info.params || rs.entry.params) + " parameters" : ""].filter(function (x) { return x }).join("  ·  ") } } }

    // the checksum: what was shown is exactly what gets installed
    Rectangle { width: parent.width; height: shaCol.implicitHeight + 20; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule
        Column { id: shaCol; x: 12; y: 10; width: parent.width - 24 - copySha.width; spacing: 4
            Row { spacing: 8
                Txt { kind: "cap"; text: "SHA-256" }
                Tag { visible: rs.mode === "community"; text: "matches the index"; kind: "PASS" }
                Tag { visible: rs.mode === "file"; text: "of the file you chose"; kind: "computed" }
                Tag { visible: rs.mode === "installed" && rs.info.sha256_now === rs.info.sha256; text: "unchanged since install"; kind: "PASS" }
                Tag { visible: rs.mode === "installed" && !!rs.info.sha256_now && rs.info.sha256_now !== rs.info.sha256; text: "changed on disk"; kind: "FAIL" } }
            Txt { mono: true; font.pixelSize: 12; text: rs.info.sha256 || ""; width: parent.width; wrapMode: Text.WrapAnywhere; tone: 2 } }
        Btn { id: copySha; kind: "quiet"; small: true; icon: "copy"; tip: "Copy the checksum"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
            onClicked: { Bridge.copy(rs.info.sha256 || ""); Store.toast("Checksum copied") } } }

    Note { visible: rs.bad; kind: "red"; title: "This is not a recipe Form Studio can use"; text: (rs.info.problems || []).join(" ") }
    Note { visible: rs.mode !== "installed" && !rs.bad; kind: "amber"; title: "A recipe is code"
        text: "Read it before you install it. Installing copies the file into your projects folder and runs nothing. It runs on this computer, with your permissions, when you create a design from it." }

    // the source, with line numbers
    Rectangle {
        width: parent.width; height: 300; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule; clip: true
        Flickable {
            id: code
            anchors.fill: parent; anchors.margins: 1; contentWidth: Math.max(width, srcRow.implicitWidth + 24); contentHeight: srcRow.implicitHeight + 20
            clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            ScrollBar.horizontal: ScrollBar { height: 6 }
            Row { id: srcRow; x: 10; y: 10; spacing: 12
                Text { color: Theme.ink4; font.family: Theme.mono; font.pixelSize: 11; lineHeight: 1.35; horizontalAlignment: Text.AlignRight
                    text: { var n = String(rs.info.source || "").split("\n").length, out = []; for (var i = 1; i <= Math.min(n, 4000); i++) out.push(i); return out.join("\n") } }
                Text { objectName: "recipeSource"; color: Theme.ink2; font.family: Theme.mono; font.pixelSize: 11; lineHeight: 1.35; textFormat: Text.PlainText
                    text: String(rs.info.source || "") } } } }
}
