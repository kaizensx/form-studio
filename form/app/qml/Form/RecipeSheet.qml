import QtQuick
import QtQuick.Controls
import FormNative
import "F.js" as F

// Review a recipe before it is installed, or look at one that is. A recipe is code: the whole source and its SHA-256
// are on screen, a community recipe's download has been checked against the checksum in the index, and nothing is
// installed until Install is pressed. Installing only copies the file; it runs when a design is created from it.
//   Store.openSheet("recipe", { mode: "file" | "community" | "package" | "derived" | "installed", info: {...} })
// package: a .formrecipe someone shared (form/recipe_share.py), checked against the SHA-256 in its meta.json, with its
// preview. derived: one of your designs rewritten as a recipe, built once and compared with the design.
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
              : mode === "package" ? Store.post("/recipes/package/install", { sha256: info.sha256 })
              : mode === "derived" ? Store.post("/recipes/derive/install", { sha256: info.sha256, kind: info.kind, title: info.title, summary: info.summary, project: info.project, rev: info.rev })
                                   : Store.post("/recipes/install", { source: info.source, kind: info.kind, sha256: info.sha256, title: info.title, summary: info.summary })
        return p.then(function (m) {
            busy = false
            if (rs.mode === "derived") {
                Store.toast("“" + m.title + "” is in My recipes", "Share it as a file or with the community.")
                Store.openSheet("shareRecipe", { id: m.id })
                return
            }
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
        Btn { visible: rs.mode === "installed"; objectName: "recipeShare"; icon: "share_2"; text: "Share…"; onClicked: Store.openSheet("shareRecipe", { id: rs.entry.id }) }
        Btn { visible: rs.mode === "installed"; objectName: "recipeCreate"; kind: "primary"; icon: "plus"; text: "Create a design"
            onClicked: Store.openSheet("new", { tab: "recipe", section: "mine", pick: rs.entry.id }) }
        Btn { visible: rs.mode !== "installed"; kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(rs.mode === "derived" ? null : "new", { tab: "recipe" }) }
        Btn { visible: rs.mode !== "installed"; objectName: "recipeInstall"; kind: "primary"; icon: "download"; text: rs.mode === "derived" ? "Install in My recipes" : "Install"
            busyText: "Installing…"; enabled: !rs.bad; busy: rs.busy; onClicked: rs.install() } }
    spacing: 14

    Row { width: parent.width; spacing: 14
        Rectangle { width: 44; height: 44; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule2
            Icon { anchors.centerIn: parent; name: rs.mode === "community" ? "globe" : rs.mode === "package" ? "package" : rs.mode === "derived" ? "wand" : "file_code"; size: 20; color: Theme.ink2 } }
        Column { width: parent.width - 58; spacing: 3; anchors.verticalCenter: parent.verticalCenter
            Txt { text: rs.entry.summary || rs.info.summary || "No description in the file."; tone: rs.entry.summary || rs.info.summary ? 1 : 3; width: parent.width }
            Txt { kind: "fine"; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                text: [rs.entry.author ? "by " + rs.entry.author : "", rs.mode === "file" || rs.mode === "package" ? rs.info.filename : rs.mode === "community" ? rs.entry.url : rs.mode === "derived" ? "from “" + rs.info.project + "” " + F.pad(rs.info.rev) : "",
                       (rs.info.params || rs.entry.params) ? (rs.info.params || rs.entry.params) + " parameters" : ""].filter(function (x) { return x }).join("  ·  ") } } }

    // the checksum: what was shown is exactly what gets installed
    Rectangle { width: parent.width; height: shaCol.implicitHeight + 20; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule
        Column { id: shaCol; x: 12; y: 10; width: parent.width - 24 - copySha.width; spacing: 4
            Row { spacing: 8
                Txt { kind: "cap"; text: "SHA-256" }
                Tag { visible: rs.mode === "community"; text: "matches the index"; kind: "PASS" }
                Tag { visible: rs.mode === "file"; text: "of the file you chose"; kind: "computed" }
                Tag { visible: rs.mode === "package" && !!rs.info.verified; text: "matches meta.json"; kind: "PASS" }
                Tag { visible: rs.mode === "package" && !rs.info.verified; text: "does not match meta.json"; kind: "FAIL" }
                Tag { visible: rs.mode === "derived"; text: "of the rewritten code"; kind: "computed" }
                Tag { visible: rs.mode === "installed" && rs.info.sha256_now === rs.info.sha256; text: "unchanged since install"; kind: "PASS" }
                Tag { visible: rs.mode === "installed" && !!rs.info.sha256_now && rs.info.sha256_now !== rs.info.sha256; text: "changed on disk"; kind: "FAIL" } }
            Txt { mono: true; font.pixelSize: 12; text: rs.info.sha256 || ""; width: parent.width; wrapMode: Text.WrapAnywhere; tone: 2 } }
        Btn { id: copySha; kind: "quiet"; small: true; icon: "copy"; tip: "Copy the checksum"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
            onClicked: { Bridge.copy(rs.info.sha256 || ""); Store.toast("Checksum copied") } } }

    // a shared package's picture, and the check that a recipe made from a design reproduces it
    Rectangle { visible: rs.mode === "package" && !!rs.info.preview; width: parent.width; height: 180; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule; clip: true
        Image { objectName: "recipePreview"; readonly property bool ready: status === Image.Ready; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectFit; asynchronous: true
            source: rs.mode === "package" && rs.info.preview ? Bridge.baseUrl + rs.info.preview : "" }
        Txt { kind: "fine"; tone: 3; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; text: "Preview from the package. It is a picture: nothing has been built." } }
    Note { visible: rs.mode === "derived" && !!rs.info.check; kind: rs.info.check && rs.info.check.same_volume ? "green" : "amber"
        title: rs.info.check && rs.info.check.same_volume ? "Builds the same solid as the design" : "Built, but not the same volume as the design"
        text: rs.info.check ? "At its defaults the recipe has a volume of " + F.fmt(rs.info.check.recipe_volume_mm3 / 1000, 3) + " cm³; the design at " + F.pad(rs.info.check.rev)
              + " has " + F.fmt(rs.info.check.design_volume_mm3 / 1000, 3) + " cm³. Computed by the CAD kernel." + (rs.info.check.same_volume ? "" : " Designs that read imported parts or labels can differ; check it before sharing.") : "" }
    Note { visible: rs.bad; kind: "red"; title: "This is not a recipe Form Studio can use"; text: (rs.info.problems || []).join(" ") }
    Note { visible: rs.mode !== "installed" && rs.mode !== "derived" && !rs.bad; kind: "amber"; title: "A recipe is code"
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
