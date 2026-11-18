import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Home. The composer is in the agent column on the left; this pane is everything else about starting and finding work:
//   · ways to start (describe it, a recipe, a brief, an import)
//   · starters learned from what this person designs, which they can pin, edit, remove and add to (form/starters.py)
//   · brief templates in the order they use them, their own saved templates first
//   · on a new install: live recipes on their plates; afterwards: every design as a live object
// No example projects are created; "Open an example" adds one only when asked.
Item {
    id: home
    objectName: "homeView"
    clip: true
    property string filter: "all"             // all | released | open
    property string order: "recent"           // recent | name
    property string renaming: ""
    property string renameDraft: ""      // what has been typed so far: kept here so a list refresh that rebuilds the card does not wipe it
    property string confirming: ""
    property string editingStarter: ""   // id of the starter being edited in place; "+" while a new one is typed
    property var menuFor: null
    readonly property var everything: Store.studio ? Store.studio.projects.filter(function (p) { return !p.error }) : []
    readonly property var broken: Store.studio ? Store.studio.projects.filter(function (p) { return !!p.error }) : []
    readonly property bool fresh: everything.length === 0
    readonly property var projects: {
        var l = everything.filter(function (p) { return home.filter === "all" || (home.filter === "released") === (p.approved_rev === p.head) })
        return l.sort(function (a, b) { return home.order === "name" ? String(a.name).localeCompare(String(b.name)) : b.updated - a.updated })
    }
    readonly property int released: everything.filter(function (p) { return p.approved_rev === p.head }).length
    readonly property var prompts: Store.starters ? Store.starters.prompts.slice(0, fresh ? 6 : 3) : []
    readonly property var briefs: Store.starters ? Store.starters.briefs.slice(0, 7) : []
    readonly property real cw: Math.min(width - 80, 1240)          // content width: a long line stays readable on a wide screen
    // newest Blender render of each project's current geometry (form/photo.py)
    property var photos: ({})
    function loadPhotos() { Store.get("/photos").then(function (r) { home.photos = r.latest }, function () {}) }
    Component.onCompleted: { loadPhotos(); Store.loadStarters() }
    // Everything rises in once, when Home appears. Sorting, filtering or a reload afterwards puts things in place at once:
    // a grid you work in all day does not replay its entrance.
    property bool entered: false
    Timer { interval: 40 + 9 * Theme.stagger + Theme.slow; running: true; onTriggered: home.entered = true }
    Connections { target: Store; function onStudioChanged() { home.loadPhotos() } }
    function recipeTitle(id) {
        if (!Store.studio) return ""
        if (String(id).indexOf("src:") === 0 || String(id).indexOf("scad:") === 0) return "Designed as code"
        for (var i = 0; i < Store.studio.recipes.length; i++) if (Store.studio.recipes[i].id === id) return Store.studio.recipes[i].title
        var t = Store.studio.recipe_titles                 // retired recipes are not listed, but older designs name them
        return t && t[id] ? t[id] : id
    }
    function greeting() {
        var h = new Date().getHours()
        return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"
    }
    function exportProject(p) { saveDlg.pid = p.id; saveDlg.currentFile = Bridge.downloads() + "/" + p.id + ".formstudio"; Store.ask(saveDlg) }
    function menu(p) {
        return [
            { icon: "arrow_up_right", text: "Open", run: function () { Store.open(p.id) } },
            { sep: true },
            { icon: "pencil", text: "Rename", run: function () { home.confirming = ""; home.renameDraft = p.name; home.renaming = p.id } },
            { icon: "copy_plus", text: "Duplicate", run: function () { Store.duplicateProject(p.id) } },
            { icon: "archive", text: "Export…", run: function () { home.exportProject(p) } },
            { icon: "wand", text: "Turn into a recipe…", run: function () { Store.openSheet("designRecipe", { project: p.id }) } },
            { sep: true },
            { icon: "trash_2", text: "Move to trash…", danger: true, run: function () { home.renaming = ""; home.confirming = p.id } }
        ]
    }
    FileDialog { id: saveDlg; property string pid: ""; title: "Export the design"; fileMode: FileDialog.SaveFile; nameFilters: ["Form Studio projects (*.formstudio)"]
        onAccepted: { if (Bridge.save("/archive/" + pid + ".formstudio", selectedFile)) Store.toast("Exported", "The design, its history, its conversations and its code are in one file. Outputs are rebuilt where it is opened.")
                      else Store.toast("Could not write that file", "Choose another place.", true) } }
    PopMenu { id: pm; model: home.menuFor ? home.menu(home.menuFor) : [] }
    function openMenu(p, item, x, y) { menuFor = p; pm.parent = item; pm.openAt(item, x, y) }
    property var briefFor: null
    PopMenu { id: bm; model: home.briefFor ? [
            { icon: "arrow_up_right", text: "Open the questions", run: function () { Store.useBrief(home.briefFor) } },
            { icon: home.briefFor.pinned ? "pin_off" : "pin", text: home.briefFor.pinned ? "Unpin" : "Pin to the front", run: function () { Store.pinStarter(home.briefFor.id, !home.briefFor.pinned) } },
            { sep: true },
            { icon: "x", text: home.briefFor.kind === "template" ? "Delete this template" : "Hide", danger: home.briefFor.kind === "template", run: function () { Store.removeStarter(home.briefFor.id) } }] : [] }

    // a faint datum wash behind the header: the bench under a lamp. It scrolls away with the header.
    Rectangle { width: parent.width; height: 360; y: -flick.contentY * 0.5
        gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0.035) } GradientStop { position: 1; color: Theme.alpha(Theme.datum, 0.0) } } }

    Flickable {
        id: flick
        anchors.fill: parent; contentHeight: col.implicitHeight + 80; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: col; x: Math.round((parent.width - width) / 2); y: home.fresh ? Math.max(36, Math.min(72, home.height * 0.07)) : 30; width: home.cw; spacing: 0

            // ── header ──
            Item { id: header; width: parent.width; height: hcol.implicitHeight
                opacity: 0; Component.onCompleted: hIn.start()
                ParallelAnimation { id: hIn; Glide { target: header; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: htr; property: "y"; from: Theme.shift(10); to: 0; duration: Theme.slow } }
                transform: Translate { id: htr }
                Column { id: hcol; width: parent.width - acts.width - 20; spacing: 6
                    Txt { kind: "cap"; color: Theme.datum; text: home.fresh ? "Form Studio " + Bridge.version : home.greeting() }
                    Txt { kind: "h1"; font.pixelSize: home.fresh ? (home.cw > 860 ? 40 : 34) : 30; font.letterSpacing: -0.6; lineHeight: 1.05; width: parent.width
                        text: home.fresh ? "Design your first part" : "Your designs" }
                    Txt { tone: 2; width: Math.min(parent.width, 640); lineHeight: 1.4; font.pixelSize: home.fresh ? Theme.tLead : Theme.tBody
                        text: home.fresh ? "Describe it to the agent on the left, answer a short brief, or start from a parametric recipe. Every part is built in a real CAD kernel, checked, and sliced before you print it."
                              : F.plural(home.everything.length, "design") + "  ·  " + home.released + " released" + (home.everything.length ? "  ·  last change " + F.ago(Math.max.apply(null, home.everything.map(function (p) { return p.updated })))
                                : "") } }
                Row { id: acts; anchors.right: parent.right; anchors.bottom: parent.bottom; spacing: 8
                    Btn { kind: "quiet"; icon: "import"; text: "Import…"; tip: "A .formstudio project, a .formproj, or a conversation"; onClicked: Store.openSheet("new", { tab: "import" }) }
                    Btn { kind: "quiet"; icon: "folder_open"; tip: "Open the projects folder: " + Bridge.dataDirShort; onClicked: Bridge.openDataFolder() }
                    Btn { kind: "primary"; icon: "plus"; text: "New design"; keys: "Ctrl+N"; tip: "Describe it, a recipe, a brief or an import"; onClicked: Store.openSheet("new") } } }

            Item { width: 1; height: home.fresh ? 30 : 22 }
            Note { visible: !!Store.fatal; width: parent.width; kind: "red"; title: Store.fatal ? Store.fatal.message : ""; text: Store.fatal ? (Store.fatal.hint || "") : "" }
            Note { visible: home.broken.length > 0; width: parent.width; kind: "amber"; title: F.plural(home.broken.length, "folder") + " could not be read"
                text: home.broken.map(function (p) { return p.id }).join(", ") + ". Nothing was changed; open the projects folder to look." }

            // ── ways to start (a new install: large; afterwards the New design button does it) ──
            Grid {
                id: ways
                visible: home.fresh
                width: parent.width; columns: home.cw > 900 ? 4 : 2; spacing: 12
                readonly property real tw: Math.floor((width - (columns - 1) * spacing) / columns)
                Repeater {
                    model: [{ icon: "message_square", title: "Describe it", text: "Tell the agent what it holds and where it goes. It writes the design as code.", run: function () { Store.newChat(); Store.chatFocus++ } },
                            { icon: "sliders_horizontal", title: "Start from a recipe", text: "A parametric design with engineering checks: change numbers, see the part.", run: function () { Store.openSheet("new", { tab: "recipe" }) } },
                            { icon: "file_text", title: "Start from a brief", text: "Answer the questions that decide fit, material and mounting.", run: function () { Store.openSheet("new", { tab: "brief" }) } },
                            { icon: "import", title: "Import a project", text: "A .formstudio file from another computer, with its history and conversations.", run: function () { Store.openSheet("new", { tab: "import" }) } }]
                    Rectangle {
                        id: way
                        required property var modelData
                        required property int index
                        width: ways.tw; height: 132; radius: Theme.rLg
                        color: wm.pressed ? Theme.plate1 : wm.containsMouse ? Theme.plate3 : Theme.plate2
                        border.color: wm.containsMouse ? Theme.rule3 : Theme.rule
                        Behavior on color { Tint {} }
                        scale: wm.pressed ? Theme.from(0.985) : 1
                        Behavior on scale { Glide { duration: Theme.press } }
                        opacity: 0; Component.onCompleted: wIn.start()
                        SequentialAnimation { id: wIn; PauseAnimation { duration: 60 + way.index * Theme.stagger }
                            ParallelAnimation { Glide { target: way; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: wtr; property: "y"; from: Theme.shift(10); to: 0; duration: Theme.slow } } }
                        transform: Translate { id: wtr }
                        Rectangle { x: 16; y: 16; width: 34; height: 34; radius: Theme.rMd; color: way.index === 0 ? Theme.alpha(Theme.datum, 0.14) : Theme.plate4
                            Icon { anchors.centerIn: parent; name: way.modelData.icon; size: 16; color: way.index === 0 ? Theme.datum : Theme.ink2 } }
                        Icon { name: "arrow_up_right"; size: 14; color: wm.containsMouse ? Theme.datum : Theme.ink4; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16 }
                        Column { x: 16; y: 62; width: parent.width - 32; spacing: 3
                            Txt { text: way.modelData.title; font.weight: Theme.wSemi }
                            Txt { kind: "fine"; width: parent.width; text: way.modelData.text; maximumLineCount: 2; elide: Text.ElideRight } }
                        MouseArea { id: wm; anchors.fill: parent; hoverEnabled: true; onClicked: way.modelData.run() } } } }
            Item { visible: home.fresh; width: 1; height: 34 }

            // ── starters, learned from what this person designs ──
            Item { width: parent.width; height: 30; visible: home.prompts.length > 0 || home.editingStarter === "+"
                Row { spacing: 10; anchors.verticalCenter: parent.verticalCenter
                    Txt { kind: "h3"; text: home.fresh ? "Starters" : "Start something new"; font.letterSpacing: -0.2 }
                    Txt { kind: "fine"; tone: 3; anchors.baseline: parent.children[0].baseline
                        text: Store.starters && Store.starters.history ? "learned from your designs, your printer and your material" : "suggestions until you have designs of your own" } }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    Btn { visible: !!Store.starters && Store.starters.hidden > 0; small: true; kind: "quiet"; icon: "rotate_ccw"; text: "Restore suggestions"; onClicked: Store.restoreStarters() }
                    Btn { objectName: "starterAdd"; small: true; kind: "quiet"; icon: "plus"; text: "Add a starter"; onClicked: home.editingStarter = "+" } } }
            Item { width: 1; height: 12; visible: home.prompts.length > 0 || home.editingStarter === "+" }
            Grid {
                id: sgrid
                width: parent.width; columns: home.cw > 900 ? 3 : 2; spacing: 12
                visible: home.prompts.length > 0 || home.editingStarter === "+"
                readonly property real tw: Math.floor((width - (columns - 1) * spacing) / columns)
                Repeater { model: home.prompts
                    StarterCard {
                        required property var modelData
                        required property int index
                        item: modelData; index: index; width: sgrid.tw; entered: home.entered
                        editing: home.editingStarter === modelData.id
                        onEditRequested: home.editingStarter = modelData.id
                        onEditCancelled: home.editingStarter = ""
                        onEditDone: function (t) { home.editingStarter = ""; if (t.trim() && t.trim() !== modelData.text) Store.editStarter(modelData.id, t.trim()) } } }
                StarterCard {
                    visible: home.editingStarter === "+"; width: sgrid.tw; item: ({ id: "+", text: "", source: "mine" }); editing: visible
                    onEditCancelled: home.editingStarter = ""
                    onEditDone: function (t) { home.editingStarter = ""; if (t.trim()) Store.addStarter(t.trim()) } } }
            Item { width: 1; height: 18; visible: home.briefs.length > 0 }

            // ── brief templates, in the order this person uses them ──
            Flow { width: parent.width; spacing: 8; visible: home.briefs.length > 0
                Txt { kind: "cap"; text: "Or answer a few questions"; height: 30; verticalAlignment: Text.AlignVCenter; rightPadding: 6 }
                Repeater { model: home.briefs
                    Rectangle { id: bc; objectName: "briefChip"; required property var modelData; required property int index
                        readonly property bool mine: modelData.kind === "template"
                        width: brow.implicitWidth + 24; height: 30; radius: 15
                        color: bmouse.pressed ? Theme.washPress : bmouse.containsMouse ? Theme.plate3 : Theme.alpha(Theme.plate2, 0.6)
                        border.color: bc.mine || bc.modelData.pinned ? Theme.alpha(Theme.datum, 0.45) : bmouse.containsMouse ? Theme.rule3 : Theme.rule2
                        Behavior on color { Tint {} }
                        Row { id: brow; anchors.centerIn: parent; spacing: 6
                            Icon { visible: bc.mine || bc.modelData.pinned; name: bc.modelData.pinned ? "pin" : "bookmark"; size: 12; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
                            Txt { font.pixelSize: 12; text: bc.modelData.title; tone: bmouse.containsMouse ? 1 : 2; anchors.verticalCenter: parent.verticalCenter } }
                        MouseArea { id: bmouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function (e) { if (e.button === Qt.RightButton) { home.briefFor = bc.modelData; bm.parent = bc; bm.openAt(bc, e.x, e.y) } else Store.useBrief(bc.modelData) } }
                        Tip { show: bmouse.containsMouse; text: bc.modelData.summary || "" } } } }

            // ── a new install: the recipes, live on their plates ──
            Item { visible: home.fresh && !!Store.studio; width: 1; height: 40 }
            Item { visible: home.fresh && !!Store.studio; width: parent.width; height: 30
                Txt { kind: "h3"; text: "Recipes"; font.letterSpacing: -0.2; anchors.verticalCenter: parent.verticalCenter }
                Btn { small: true; kind: "quiet"; icon: "arrow_right"; text: "All recipes"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    onClicked: Store.openSheet("new", { tab: "recipe" }) } }
            Item { visible: home.fresh && !!Store.studio; width: 1; height: 12 }
            Grid {
                id: rgrid
                visible: home.fresh && !!Store.studio
                width: parent.width; columns: home.cw > 900 ? 4 : 3; spacing: 12
                readonly property real tw: Math.floor((width - (columns - 1) * spacing) / columns)
                Repeater {
                    model: ["gridfinity_bin", "device_stand", "pegboard", "storage_box"].slice(0, rgrid.columns)
                    Rectangle {
                        id: rc
                        objectName: "recipeCard"
                        required property string modelData
                        required property int index
                        readonly property var r: { var l = Store.studio ? Store.studio.recipes : []; for (var i = 0; i < l.length; i++) if (l[i].id === modelData) return l[i]; return { title: modelData, summary: "" } }
                        width: rgrid.tw; height: Math.round(rgrid.tw * 0.62) + 62; radius: Theme.rLg
                        color: Theme.plate1; border.color: rcm.containsMouse ? Theme.rule3 : Theme.rule
                        Behavior on border.color { Tint {} }
                        y: rcm.containsMouse && !rcm.pressed ? Theme.shift(-3) : 0
                        Behavior on y { Glide { duration: Theme.base } }
                        opacity: 0; Component.onCompleted: rIn.start()
                        SequentialAnimation { id: rIn; PauseAnimation { duration: 260 + rc.index * Theme.stagger }
                            Glide { target: rc; property: "opacity"; to: 1; duration: Theme.slow } }
                        Shadow { radius: parent.radius; spread: 26; drop: 12; opacity: rcm.containsMouse ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
                        Item { x: 1; y: 1; width: parent.width - 2; height: parent.height - 63; clip: true
                            RecipeView { anchors.fill: parent; recipeId: rc.modelData; turning: rcm.containsMouse } }
                        Rectangle { y: parent.height - 62; x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
                        Column { x: 14; y: parent.height - 50; width: parent.width - 28; spacing: 2
                            Txt { text: rc.r.title; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                            Txt { kind: "fine"; text: rc.r.summary; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                        MouseArea { id: rcm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.openSheet("new", { tab: "recipe", section: "builtin", pick: rc.modelData }) }
                        Tip { show: rcm.containsMouse; text: "Built at its default values, live. Click to start from it." } } } }
            Item { visible: home.fresh && !!Store.studio; width: 1; height: 26 }
            Row { visible: home.fresh && !!Store.studio; spacing: 6; anchors.horizontalCenter: parent.horizontalCenter
                Btn { kind: "quiet"; icon: "box"; text: "Open an example"; onClicked: Store.openSheet("new", { tab: "import", examples: true }) }
                Txt { kind: "fine"; tone: 4; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; width: Math.min(implicitWidth, home.cw - 200)
                    text: "·   Designs are saved in " + Bridge.dataDirShort } }

            // ── the designs ──
            Item { visible: !home.fresh; width: 1; height: 40 }
            Item { width: parent.width; height: 34; visible: !home.fresh
                Row { spacing: 12; anchors.verticalCenter: parent.verticalCenter
                    Txt { kind: "h3"; text: "Designs"; font.letterSpacing: -0.2 }
                    Txt { mono: true; tone: 3; font.pixelSize: 12; text: home.everything.length; anchors.baseline: parent.children[0].baseline } }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Seg { visible: home.everything.length > 6; anchors.verticalCenter: parent.verticalCenter; value: home.filter; onPicked: function (v) { home.filter = v }
                        model: [{ value: "all", text: "All" }, { value: "open", text: "In progress" }, { value: "released", text: "Released" }] }
                    Btn { visible: home.everything.length > 6; kind: "quiet"; icon: "arrow_up_down"; text: home.order === "recent" ? "Last changed" : "Name"; tip: "Sort order"
                        onClicked: home.order = home.order === "recent" ? "name" : "recent" } } }
            Item { visible: !home.fresh; width: 1; height: 14 }
            Grid {
                id: grid; width: parent.width; visible: !home.fresh
                columns: Math.max(1, Math.floor((width + 18) / 300)); spacing: 18
                readonly property real cw: Math.floor((width - (columns - 1) * 18) / columns)
                Repeater {
                    model: home.projects
                    Item {
                        id: card
                        required property var modelData
                        required property int index
                        readonly property var p: modelData
                        objectName: "projectCard"
                        readonly property string title: p.name
                        readonly property bool hot: cm.containsMouse || more.hovered || (pm.opened && home.menuFor === p)
                        readonly property bool editing: home.renaming === p.id
                        readonly property bool asking: home.confirming === p.id
                        readonly property var ph: home.photos[p.id] || null
                        readonly property int foot: 64
                        width: grid.cw; height: Math.round(grid.cw * 0.7) + foot
                        opacity: 0
                        Component.onCompleted: { if (home.entered) opacity = 1; else appear.start() }
                        SequentialAnimation { id: appear; PauseAnimation { duration: 120 + Math.min(card.index, 9) * Theme.stagger }
                            ParallelAnimation { Glide { target: card; property: "opacity"; to: 1; duration: Theme.slow }
                                Glide { target: rise; property: "y"; from: Theme.shift(12); to: 0; duration: Theme.slow } } }
                        transform: Translate { id: rise; y: 0 }
                        Rectangle {
                            id: face
                            width: parent.width; height: parent.height; radius: Theme.rLg
                            y: card.hot && !cm.pressed ? Theme.shift(-3) : 0
                            scale: cm.pressed ? Theme.from(0.985) : 1
                            color: Theme.plate1; border.color: card.asking ? Theme.alpha(Theme.signal, 0.5) : card.hot ? Theme.rule3 : Theme.rule
                            Behavior on y { Glide { duration: Theme.base } }
                            Behavior on scale { Glide { duration: Theme.press } }
                            Behavior on border.color { Tint {} }
                            Shadow { radius: parent.radius; spread: 26; drop: 12; opacity: card.hot ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
                            // the part on its plate
                            Item { id: stage; x: 1; y: 1; width: parent.width - 2; height: parent.height - card.foot - 1; clip: true
                                MiniView { anchors.fill: parent; projectId: card.p.id; turning: card.hot && !card.asking } }
                            // a render of this revision, if one was made: a small proof in the corner, large on click
                            Rectangle { visible: !!card.ph && pim.status === Image.Ready; anchors.right: stage.right; anchors.bottom: stage.bottom; anchors.margins: 10
                                width: 58; height: 44; radius: Theme.rSm; color: Theme.plate; border.color: phm.containsMouse ? Theme.rule3 : Theme.rule2; clip: true; z: 2
                                scale: phm.containsMouse ? 1.06 : 1; Behavior on scale { Glide { duration: Theme.fast } }
                                Image { id: pim; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                                    source: card.ph ? Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.ph.key + ".png" : "" }
                                MouseArea { id: phm; anchors.fill: parent; hoverEnabled: true
                                    onClicked: Store.showImage(Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.ph.key + ".png", card.p.name, "Blender render · an illustration, not evidence") }
                                Tip { show: phm.containsMouse; text: "Blender render of this revision · illustration" } }
                            Rectangle { y: parent.height - card.foot; x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
                            // name, kind, last change — revision and status on the right
                            Column { visible: !card.editing && !card.asking; x: 16; y: parent.height - card.foot + 13; width: parent.width - 32 - side.width - 10; spacing: 3
                                Txt { text: card.p.name; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                    text: home.recipeTitle(card.p.recipe) + "  ·  " + F.ago(card.p.updated) } }
                            Column { id: side; visible: !card.editing && !card.asking; anchors.right: parent.right; anchors.rightMargin: 16; y: parent.height - card.foot + 13; spacing: 5
                                Txt { mono: true; font.pixelSize: 12; text: F.pad(card.p.head); anchors.right: parent.right; tone: 2 }
                                Tag { anchors.right: parent.right; visible: !!card.p.approved_rev
                                    text: card.p.approved_rev === card.p.head ? "released" : card.p.approved_rev ? F.pad(card.p.approved_rev) + " released" : ""
                                    kind: card.p.approved_rev === card.p.head ? "PASS" : card.p.approved_rev ? "WARN" : "" } }
                            MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; enabled: !card.editing && !card.asking
                                onClicked: function (e) {
                                    if (e.button === Qt.RightButton) home.openMenu(card.p, card, e.x, e.y)
                                    else Store.open(card.p.id) } }
                            Btn { id: more; objectName: "cardMore"; kind: "quiet"; icon: "ellipsis"; tip: "Rename, duplicate, export, delete"; x: parent.width - width - 8; y: 8; z: 3
                                opacity: card.hot && !card.asking && !card.editing ? 1 : 0; visible: opacity > 0
                                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                                onClicked: home.openMenu(card.p, card, more.x, more.y + more.height + 4) }
                            // rename in place
                            Field { id: rf; visible: card.editing; x: 12; y: parent.height - card.foot + 18; width: parent.width - 24
                                // The card menu gives focus back to whatever had it when it closes, a moment after this
                                // field appears. Taking focus at once lost that race on a slow machine and the rename
                                // was cancelled as "clicked elsewhere". Take it, take it again once the menu is gone,
                                // and only then treat losing it as a cancel.
                                property bool armed: false
                                function grab() { input.forceActiveFocus(); if (text === card.p.name) input.selectAll(); else input.cursorPosition = text.length }
                                function begin() { text = home.renameDraft; grab(); arm.restart() }
                                Component.onCompleted: if (visible) begin()      // the card was rebuilt in the middle of a rename
                                onEdited: function (t) { home.renameDraft = t }
                                Timer { id: arm; interval: 140; onTriggered: { if (!rf.input.activeFocus) rf.grab(); rf.armed = true } }
                                onVisibleChanged: { armed = false; if (visible) begin(); else arm.stop() }
                                onAccepted: function (t) { if (!card.editing) return; home.renaming = ""; if (t.trim() && t.trim() !== card.p.name) Store.renameProject(card.p.id, t.trim()) }
                                Keys.onEscapePressed: home.renaming = ""
                                Connections { target: rf.input; function onActiveFocusChanged() {
                                    // switching to another app is not "clicked elsewhere": the name stays open
                                    if (rf.armed && !rf.input.activeFocus && card.editing && rf.Window.window && rf.Window.window.active) home.renaming = "" } }
                                Connections { target: rf.Window.window; enabled: card.editing
                                    function onActiveChanged() { if (rf.Window.window.active && card.editing && !rf.input.activeFocus) rf.input.forceActiveFocus() } } }
                            // move to trash?
                            Rectangle { visible: card.asking; x: 1; y: 1; width: parent.width - 2; height: parent.height - card.foot - 1; radius: Theme.rLg - 1; color: Theme.alpha(Theme.plate, 0.72) }
                            Item { visible: card.asking; x: 16; y: parent.height - card.foot; width: parent.width - 32; height: card.foot
                                Column { anchors.verticalCenter: parent.verticalCenter; width: parent.width - tacts.width - 10; spacing: 2
                                    Txt { text: "Move to the trash?"; font.weight: Theme.wMedium; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                    Txt { kind: "fine"; text: card.p.name + " · kept in .trash"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                                Row { id: tacts; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                                    Btn { small: true; kind: "quiet"; text: "Keep"; onClicked: home.confirming = "" }
                                    Btn { small: true; kind: "danger"; text: "Move to trash"; onClicked: { home.confirming = ""; Store.deleteProject(card.p.id) } } } }
                        }
                    }
                }
            }
            Txt { visible: home.everything.length > 0 && home.projects.length === 0; tone: 3; text: home.filter === "released" ? "Nothing is released yet. A design is released from its Release stage." : "Every design here is released." }
        }
    }
}
