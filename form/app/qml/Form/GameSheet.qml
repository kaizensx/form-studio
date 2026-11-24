import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// The design as a game asset (form/game, form/game/app.py): LODs at triangle budgets, UVs, baked maps and collision,
// for an engine preset. Built in Blender from the design (a subdivision cage's levels first, else the CAD mesh
// decimated: automatic retopology, and said so). The viewport shows one LOD at a time (LodBar), shaded with its baked
// maps, as a UV checker or one map as stored, with its wireframe; every check comes from the written GLB.
// Export builds for the preset picked and saves every file as one zip. No Blender: the one-click install card.
Column {
    id: gs
    objectName: "gameSheet"
    property string title: "Game asset"
    property string note: Store.project ? Store.project.name + " · " + F.pad(Store.project.head) + (Store.gameDesign ? "" : " · its purpose is not “Game asset”; the asset is made all the same") : ""
    property int sheetWidth: Theme.sheetXl
    property string preset: "gltf"
    property int texturePx: 1024
    property bool wire: false
    property bool normalMap: true            // shaded: the baked normal map on (off shows the LOD's own normals)
    property string mode: "shaded"           // shaded | checker | channel
    property string channel: "base_color"
    readonly property var g: Store.game
    readonly property var a: Store.gameAsset
    readonly property var sw: g ? g.software : null
    readonly property bool canBuild: !!sw && sw.blender
    readonly property var lod: a ? Store.gameLods[a.key + ":" + Store.gameLod] || null : null
    readonly property var presetLabel: ({ gltf: "glTF / Godot", godot: "Godot", unity: "Unity", unreal: "Unreal" })
    spacing: 14
    Component.onCompleted: { Store.loadGame(); if (!Store.software) Store.checkSoftware() }
    // the viewport draws the LOD (Viewport.game) and, as the model's edges, its wireframe; the camera keeps its place
    // when only the LOD or the wireframe changes (the bounding box is the asset's)
    function show() {
        if (!lod) return
        view.game = lod
        var first = !view.model
        view.setModel({ mesh: [], edges: wire ? lod.wire : "", bbox: lod.bbox })
        if (first) view.setView("iso", false)
    }
    onLodChanged: show()
    onWireChanged: show()

    function build() { if (canBuild) Store.buildGame({ preset: preset, texture_px: texturePx }) }
    function accept() { if (a) exportNow(); else build() }
    function exportNow() {
        if (!canBuild || Store.gameBusy) return
        Store.buildGame({ preset: preset, texture_px: texturePx, action: "export" }).then(function (r) {
            if (!r) return
            dlg.key = r.key
            dlg.currentFolder = Bridge.downloads()
            dlg.currentFile = Bridge.downloads() + "/" + Store.pid + "-" + r.preset.id + ".zip"
            Store.ask(dlg)
        })
    }
    FileDialog { id: dlg; property string key: ""; title: "Export the game asset"; fileMode: FileDialog.SaveFile
        nameFilters: ["Zip (*.zip)", "All files (*)"]
        onAccepted: { if (Bridge.save("/projects/" + Store.pid + "/game/" + key + ".zip", selectedFile)) Store.toast("Game asset exported", String(selectedFile).replace(/^.*\//, "") + " · every LOD, the maps and the collision")
                      else Store.toast("Could not save the file", "Check that the folder is writable.", true) } }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { objectName: "gameBuild"; kind: gs.a ? "quiet" : "primary"; icon: "gamepad_2"; enabled: gs.canBuild
            text: gs.a ? "Build again" : "Build game asset"; busy: Store.gameBusy; busyText: "Baking in Blender…"; onClicked: gs.build() }
        Btn { objectName: "gameExport"; kind: "primary"; icon: "download"; enabled: gs.canBuild && !Store.gameBusy
            text: "Export for " + (gs.presetLabel[gs.preset] || gs.preset) + "…"; onClicked: gs.exportNow() } }

    // ── no Blender: the install card (Settings › Software's row, one click) ──
    Column { objectName: "gameInstall"; width: parent.width; spacing: 8; visible: !!gs.sw && !gs.sw.blender
        Note { kind: "amber"; title: "Blender bakes the game asset"
            text: "LODs, UVs and baked maps are made in Blender 4.2 or newer, run in the background by Form Studio. Install it once; nothing else changes." }
        SetupList { width: parent.width; ids: ["blender"] } }

    // ── what to make: the engine and the texture size ──
    Row { width: parent.width; spacing: 16
        Column { spacing: 4
            Txt { kind: "fine"; text: "Engine" }
            Seg { objectName: "gamePreset"; value: gs.preset; onPicked: function (v) { gs.preset = v }
                model: (gs.g ? gs.g.engines : [{ id: "gltf", label: "glTF / Godot" }, { id: "unity", label: "Unity" }, { id: "unreal", label: "Unreal" }])
                       .map(function (e) { return { value: e.id, text: e.label, tip: e.detail || "" } }) } }
        Column { spacing: 4
            Txt { kind: "fine"; text: "Textures" }
            Seg { objectName: "gameTexture"; value: gs.texturePx; onPicked: function (v) { gs.texturePx = v }
                model: [{ value: 1024, text: "1k" }, { value: 2048, text: "2k" }, { value: 4096, text: "4k" }] } }
        Column { spacing: 4
            Txt { kind: "fine"; text: "Budgets (triangles, LOD0 to LOD3)" }
            Txt { mono: true; tone: 2; text: (gs.a && gs.a.lods ? gs.a.lods.map(function (r) { return r.budget }) : (gs.g ? gs.g.budgets : [])).join(" · ") } } }

    // ── the asset: one LOD at a time ──
    Rectangle { width: parent.width; height: 380; radius: Theme.rMd; color: Theme.well; clip: true; border.color: Theme.rule2
        Viewport { id: view; objectName: "gameViewport"; anchors.fill: parent; anchors.margins: 1; showDims: false; showCompanions: false
            visible: !!gs.lod; gameMode: gs.mode; gameChannel: gs.channel; gameNormalMap: gs.normalMap
            gameTex: gs.a ? { base_color: Store.gameTexUrl("base_color"), normal: Store.gameTexUrl("normal"), orm: Store.gameTexUrl("orm"), ao: Store.gameTexUrl("ao"), emissive: Store.gameTexUrl("emissive") } : ({}) }
        Spinner { anchors.centerIn: parent; size: 28; visible: Store.gameBusy }
        Txt { anchors.centerIn: parent; width: parent.width - 80; horizontalAlignment: Text.AlignHCenter; kind: "fine"; tone: 3
            visible: !Store.gameBusy && !gs.a
            text: gs.canBuild ? "Build the asset: four LODs at their budgets, UVs, baked base colour, normal, ORM and AO maps, and collision." : "Install Blender above to build the asset." }
        LodBar { x: 10; y: 10; visible: !!gs.a; lods: gs.a && gs.a.lods ? gs.a.lods : []; value: Store.gameLod; onPicked: function (i) { Store.showGameLod(i) } }
        Column { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 6; visible: !!gs.a
            Seg { objectName: "gameView"; anchors.right: parent.right; value: gs.mode; onPicked: function (v) { gs.mode = v }
                model: [{ value: "shaded", text: "Shaded", tip: "The baked base colour, ORM, normal and emissive maps" }, { value: "checker", text: "UV checker", tip: "Even squares mean even texel density; a stretched or mirrored square is a UV problem" },
                        { value: "channel", text: "Maps", tip: "One baked map, as it is stored" }] }
            Seg { objectName: "gameChannel"; anchors.right: parent.right; visible: gs.mode === "channel"; value: gs.channel; onPicked: function (v) { gs.channel = v }
                model: [{ value: "base_color", text: "Base" }, { value: "normal", text: "Normal" }, { value: "orm", text: "ORM" }, { value: "ao", text: "AO" }] }
            Btn { objectName: "gameNormalMap"; anchors.right: parent.right; small: true; kind: "quiet"; icon: "layers"; active: gs.normalMap
                visible: gs.mode === "shaded" && !!(gs.a && gs.a.textures && gs.a.textures.normal)
                text: gs.normalMap ? "Normal map on" : "Normal map off"; onClicked: gs.normalMap = !gs.normalMap }
            Btn { objectName: "gameWire"; anchors.right: parent.right; small: true; kind: "quiet"; icon: "grid_3x3"; active: gs.wire
                text: gs.wire ? "Hide wireframe" : "Wireframe"; onClicked: gs.wire = !gs.wire } }
        Txt { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 12; kind: "fine"; tone: 3; visible: !!gs.lod
            text: gs.lod ? "LOD" + gs.lod.lod + " · " + F.trim(gs.lod.triangles) + " triangles · " + F.trim(gs.lod.edges) + " edges · " + gs.lod.source : "" } }

    // ── what was measured ──
    Txt { objectName: "gameStatus"; width: parent.width; visible: !!gs.a || !!Store.gameError
        color: Store.gameError ? Theme.signal : gs.a && gs.a.validation.ok ? Theme.pass : Theme.amber
        text: Store.gameError ? Store.gameError
              : gs.a ? (gs.a.validation.ok ? "Every check passed" : gs.a.validation.failed.length + " check(s) failed: " + gs.a.validation.failed.map(function (c) { return c.label + " (" + c.value + ")" }).join("; "))
                       + " · " + gs.a.preset.label + (gs.a.current === false ? " · built from an older revision: build again" : "") : "" }
    Txt { kind: "fine"; width: parent.width; visible: !!gs.a
        text: gs.a ? "Bake " + (gs.a.bake ? F.fmt(gs.a.bake.total_seconds, 1) + " s on " + gs.a.bake.device + " at " + gs.a.bake.px + " px" : "skipped")
                     + " · UVs " + (gs.a.uv ? gs.a.uv.method : "") + " · collision " + (gs.a.collision ? F.plural(gs.a.collision.parts, "hull") + " (" + (gs.a.collision.names || []).slice(0, 2).join(", ") + (gs.a.collision.parts > 2 ? ", …" : "") + ")" : "")
                     + " · size " + (gs.a.size_mm || []).map(function (x) { return F.trim(x, 1) }).join(" × ") + " mm" : "" }
    Txt { kind: "fine"; width: parent.width; visible: !!gs.a
        text: (gs.a && gs.a.retopology_note ? gs.a.retopology_note + " " : "") + "Checks are computed from the written GLB; budgets and thresholds are proposed values, not engine rules." }
    Fold { title: "Collision by convex decomposition"; key: "game.coacd"; visible: !!gs.sw && !gs.sw.coacd
        note: "optional · CoACD"
        Txt { kind: "fine"; width: parent.width
            text: "A convex hull per part is the default. CoACD splits a concave part into several hulls; it runs in its own Python, set up in one click." }
        SetupList { width: parent.width; ids: ["game.coacd"] } }
}
