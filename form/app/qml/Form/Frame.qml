pragma Singleton
import QtQuick
import QtCore

// The window's frame around a design (the pro frame): its document tabs and the project rail. Interface state only;
// nothing here describes the design. Both are remembered between runs: the tabs per design, the rail open or not.
//
// A tab is one open thing of the design: the model itself (always first, never closed), each study result drawn on
// the part, the drawing sheet, the results report, a version compare, a CNC job. Opening one anywhere (a Bench row,
// the ribbon, the palette) opens its tab; the tab in front is whatever is on the stage, so nothing here can disagree
// with the stage. Switching a tab puts its thing on the stage again the way a person would: the mode, then the row.
QtObject {
    id: fr

    // ── the rail ──
    property bool railOpen: false
    onRailOpenChanged: _mem.railOpen = railOpen
    // where the workspace's dock ends and its size line begins: the folded rail stands between them (Workspace sets these)
    property real dockFoot: 0
    property real footTop: 0

    // ── the tabs ──
    property var tabs: []                  // [{ key, kind, id, title, full, icon }] of the design in front; the model is not in it
    property string _pid: ""
    property string _pending: ""           // the tab that was in front when the design was last open, put back once the Bench is in
    readonly property string active: {
        if (Store.compare) return "compare:" + Store.compare.rev
        if (Results.on && Results.id) return "result:" + Results.id
        if (Store.mode === "document" && (Store.benchSel.document || "") === "report") return "doc:report"
        return "design"
    }
    readonly property var all: [{ key: "design", kind: "design", title: "Model", icon: "box" }].concat(tabs)
    readonly property int index: { for (var i = 0; i < all.length; i++) if (all[i].key === active) return i; return 0 }

    function _icon(e) {
        var a = e && e.app || ""
        return ({ strength: "gauge", dfm: "factory", cam: "drill", sheet: "fold_horizontal", drawing: "drafting_compass", motion: "orbit",
                  stack: "align_vertical_space_around", topology: "sparkles", inverse: "sparkles", printOrient: "rotate_3d" })[a] || "file_check"
    }
    // a tab's name is short enough to stand whole in the row ("CNC check", "Strength", "Drawing"); the entry's full
    // name is its tooltip
    readonly property var _dfm: ({ cnc: "CNC", injection: "Moulding", fdm: "FDM", sla: "SLA", sls: "SLS", mjf: "MJF", lpbf: "LPBF" })
    function _short(id, e) {
        if (id.indexOf("dfm_") === 0) return (_dfm[id.slice(4)] || id.slice(4).toUpperCase()) + " check"
        if (id === "report") return "Report"
        var a = e && e.app || ""
        var s = ({ strength: "Strength", cam: "CAM", sheet: "Flat pattern", drawing: "Drawing", motion: "Motion", stack: "Stack-up",
                   topology: "Topology", inverse: "Variants", printOrient: "Orientation" })[a]
        return s || (e ? e.label : id)
    }
    function _describe(key) {
        if (key.indexOf("compare:") === 0) { var r = parseInt(key.slice(8)); return { key: key, kind: "compare", id: String(r), title: "Compare " + Store.revWord(r), full: "Compare with " + Store.revWord(r), icon: "git_compare" } }
        var id = key.slice(key.indexOf(":") + 1), e = Store.benchEntry(id)
        return { key: key, kind: key.indexOf("doc:") === 0 ? "doc" : "result", id: id, title: _short(id, e), full: e ? e.label : id, icon: _icon(e) }
    }
    onActiveChanged: {
        if (active === "design" || !Store.pid || _pid !== Store.pid) return
        for (var i = 0; i < tabs.length; i++) if (tabs[i].key === active) { _save(); return }
        tabs = tabs.concat([_describe(active)])
        _save()
    }
    function find(key) { for (var i = 0; i < all.length; i++) if (all[i].key === key) return all[i]; return null }

    // put a tab's thing on the stage
    function activate(key) {
        if (key === active) return
        if (key === "design") {
            if (Store.compare) Store.endCompare()
            var ch = Results.chapter, m = Object.assign({}, Store.benchSel), changed = false
            for (var c in m) { var e = Store.benchEntry(m[c]); if (e && (Results.draws(e) || e.id === "report")) { m[c] = ""; changed = true } }
            if (changed) Store.benchSel = m
            return
        }
        if (key.indexOf("compare:") === 0) {
            var rev = parseInt(key.slice(8))
            if (Store.mode !== "release") Store.setStage("release")
            if (!Store.compare || Store.compare.rev !== rev) Store.compareWith(rev)
            return
        }
        var en = Store.benchEntry(key.slice(key.indexOf(":") + 1))
        if (!en) return
        if (Store.compare) Store.endCompare()
        var chap = Store.benchChapter(en), mode = Store.benchModeOf(chap)
        if (Store.mode !== mode) Store.setStage(mode)
        Store.benchPick(chap, en)
    }
    function activateIndex(i) { var a = all; if (!a.length) return; activate(a[Math.max(0, Math.min(a.length - 1, i))].key) }
    function close(key) {
        if (key === "design") return
        var was = active === key
        tabs = tabs.filter(function (t) { return t.key !== key })
        if (was) activate("design")
        _save()
    }
    // move a tab (indices in `all`; the model stays first)
    function move(from, to) {
        from = from - 1; to = Math.max(0, Math.min(tabs.length - 1, to - 1))
        if (from < 0 || from >= tabs.length || from === to) return
        var t = tabs.slice(), x = t.splice(from, 1)[0]
        t.splice(to, 0, x)
        tabs = t
        _save()
    }

    // ── remembered: the tabs of every design, and which was in front ──
    property var _mem: Settings { category: "frame"; property string tabs: "{}"; property bool railOpen: false }
    function _read() { try { return JSON.parse(_mem.tabs) || {} } catch (e) { return {} } }
    function _save() {
        if (!_pid) return
        var all = _read()
        all[_pid] = { tabs: tabs.map(function (t) { return { key: t.key, kind: t.kind, id: t.id, title: t.title, full: t.full || t.title, icon: t.icon } }), active: active }
        _mem.tabs = JSON.stringify(all)
    }
    property var _watch: Connections {
        target: Store
        function onPidChanged() {
            fr._pid = Store.pid || ""
            var s = fr._pid ? fr._read()[fr._pid] : null
            fr.tabs = s && s.tabs ? s.tabs : []
            fr._pending = s && s.active && s.active !== "design" ? s.active : ""
        }
        function onBenchChanged() {                     // the Bench of the design is in: its titles, and the tab to put back
            if (!Store.bench || !fr._pid) return
            var t = fr.tabs.map(function (x) { var d = x.kind === "compare" ? x : fr._describe(x.key); return d })
            if (JSON.stringify(t) !== JSON.stringify(fr.tabs)) fr.tabs = t
            if (fr._pending) { var k = fr._pending; fr._pending = ""; if (fr.find(k)) fr.activate(k) }
        }
    }
    Component.onCompleted: { railOpen = _mem.railOpen; _pid = Store.pid || ""; var s = _pid ? _read()[_pid] : null; tabs = s && s.tabs ? s.tabs : [] }
}
