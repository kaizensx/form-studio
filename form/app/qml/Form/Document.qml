import QtQuick
import "F.js" as F

// The Document chapter of the Bench, docked: what can be handed to someone else about this design. One row each, in
// the Bench's row grammar. A row opens in place and says what you get, what it needs and the exact request it makes
// (the same engine call the CLI and MCP make), then runs it. Only what the engine can make today has a state; a
// document that is not built yet is dimmed and says so. Nothing here is invented: a row's number is the engine's.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var d: Store.data
    readonly property var p: d ? d.project : null
    readonly property string pid: Store.pid || "<project>"
    readonly property bool asm: !!Store.assembly && !Store.assembly.derived
    readonly property var ins: Store.instructions && p && Store.instructions.rev === p.head ? Store.instructions : null
    readonly property bool released: !!d && d.approval.state === "approved"
    readonly property string draftWhy: Store.hasDraft ? "commit or discard the draft" : ""
    topPadding: 6; bottomPadding: 8; spacing: 2
    Item { width: parent.width; height: 36
        Txt { x: 12; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wSemi; text: "Document" }
        Txt { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; tone: 3
            text: root.p ? F.pad(root.p.head) + " · " + (Store.documentCount ? F.plural(Store.documentCount, "document") : "none made yet") : "" } }
    BenchRow { objectName: "docDrawing"; name: "Drawing sheet"; dim: true; need: "not built yet" }
    BenchRow { objectName: "docInstructions"; name: "Assembly instructions"; state: root.ins ? "ok" : "none"
        dim: !root.asm; need: root.asm ? "" : "needs an assembly"
        value: root.ins ? F.plural(root.ins.pages || (root.ins.steps || []).length || 0, "page") : "not made"; evidence: root.ins ? "computed" : ""
        gets: root.asm ? "A PDF, one page per part going on, in the order the parts attach, at their exploded offset." : ""
        needs: root.asm ? "The design's own assembly() declaration. Nothing to install." : ""
        request: root.asm ? "assembly_instructions(project=\"" + root.pid + "\")" : ""
        action: root.ins ? "Make them again" : "Make"; busy: Store.instructionsBusy
        onRun: Store.makeInstructions() }
    BenchRow { objectName: "docReport"; name: "Report and files"; state: root.released ? "ok" : "none"
        value: root.released ? String(root.d.approval.release || "") : "not released"; evidence: root.released ? "computed" : ""
        gets: "The checks with their evidence, the files with their hashes and the views, in each release."
        needs: "A release of this revision. Only you approve one, in Make."
        action: "Go to Make"; onRun: Store.setStage("release") }
    BenchRow { objectName: "docShare"; name: "Share card"; dim: Store.hasDraft; need: root.draftWhy
        gets: "A 1600 × 900 image of this design with its size and what its checks found."
        request: "share_card(project=\"" + root.pid + "\")"; action: "Open"; onRun: Store.openSheet("share") }
    BenchRow { objectName: "docTurntable"; name: "Turntable"; dim: Store.hasDraft; need: root.draftWhy
        gets: "The part turning, as MP4, PNG frames, WebP or GIF."
        request: "turntable(project=\"" + root.pid + "\")"; action: "Open"; onRun: Store.openSheet("turntable") }
    BenchRow { objectName: "docRender"; name: "Photo render"; evidence: "illustration"; dim: Store.hasDraft; need: root.draftWhy
        gets: "A picture of the current revision. An illustration: it proves nothing about the part."
        needs: "Blender on this computer (Settings › Software)."
        request: "render_photo(project=\"" + root.pid + "\")"; action: "Open"; onRun: Store.openSheet("render") }
    Item { width: 1; height: 6 }
    Txt { x: 12; width: parent.width - 24; kind: "fine"; tone: 3
        text: "Drawings with dimensions, the parts list and the test plan are not built yet. They will be rows here, each with its state." }
}
