.pragma library
// Where the viewport's 2D labels go, so none sits on another. Pure arithmetic on screen rectangles: the Viewport
// projects the 3D points, this decides. Three kinds, by what they are worth to the reader:
//   pin   a finding or a measurement (an analysis marker, a check, a measured distance). Never hidden.
//   dim   an overall dimension. Lives at the middle of its dimension line; slides along it to get out of the way.
//   ref   a note on a reference outline (what the part holds). First to go when there is no room.
//   keep  something already drawn that no label may cover (a marker, a ring): its one candidate is where it is.
// Each item: { kind, w, h, cands: [{x, y}, …], prev } where cands are top-left corners in order of preference and
// prev is the candidate it had last frame (-1: none). Returns, per item, { x, y, visible, c } (c: candidate used).
var GAP = 4            // px kept clear between two labels
var HOLD = 10          // px: a label that moved away last frame comes home only when home is clear by this much more,
                       // so a label on the edge of a collision does not jump back and forth while the view turns

function hit(a, b, gap) {
    return a.x < b.x + b.w + gap && b.x < a.x + a.w + gap && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap
}
function inside(r, v) { return !v || (r.x >= v.l && r.y >= v.t && r.x + r.w <= v.r && r.y + r.h <= v.b) }
function clamp(r, v) {
    if (!v) return r
    return { x: Math.max(v.l, Math.min(r.x, v.r - r.w)), y: Math.max(v.t, Math.min(r.y, v.b - r.h)), w: r.w, h: r.h }
}

function place(items, view) {
    var out = [], taken = [], i, k
    for (i = 0; i < items.length; i++) out.push({ x: 0, y: 0, visible: false, c: -1 })
    function rect(it, k) { return { x: it.cands[k].x, y: it.cands[k].y, w: it.w, h: it.h } }
    function clear(r, gap) {
        for (var j = 0; j < taken.length; j++) if (hit(taken[j].r, r, gap + taken[j].hold)) return false
        return true
    }
    function order(it) {                 // candidates to try: home first, unless it only just became free
        var o = [], n = it.cands.length, p = it.prev === undefined ? -1 : it.prev
        if (p > 0 && p < n && !(clear(rect(it, 0), HOLD))) o.push(p)
        for (var j = 0; j < n; j++) if (o.indexOf(j) < 0) o.push(j)
        return o
    }
    function put(i, r, c) {              // a dimension sitting at home that was pushed off it last frame keeps a wider berth
        out[i] = { x: r.x, y: r.y, visible: true, c: c }
        taken.push({ i: i, r: r, hold: items[i].kind === "dim" && c === 0 && items[i].prev !== 0 && items[i].prev !== undefined && items[i].prev !== -1 ? HOLD : 0 })
    }
    function seat(i, needView) {         // the first candidate that is free (and in view, when asked); false if none
        var it = items[i], o = order(it)
        for (var j = 0; j < o.length; j++) {
            var r = rect(it, o[j])
            if ((!needView || inside(r, view)) && clear(r, GAP)) { put(i, r, o[j]); return true }
        }
        return false
    }
    // 0. what is already drawn holds its place
    for (i = 0; i < items.length; i++) if (items[i].kind === "keep" && items[i].cands.length) put(i, rect(items[i], 0), 0)
    // 1. dimensions take their places
    for (i = 0; i < items.length; i++) if (items[i].kind === "dim" && items[i].cands.length) seat(i, false)
    // 2. findings: beside their point, on the first side that is free. With no free side a finding still shows,
    //    and whatever dimension it lands on gives way (3).
    var forced = []
    for (i = 0; i < items.length; i++) {
        var it = items[i]
        if (it.kind !== "pin" || !it.cands.length) continue
        if (seat(i, true)) continue
        var r = null
        for (k = 0; k < it.cands.length && !r; k++) if (inside(rect(it, k), view)) r = rect(it, k)
        r = r || clamp(rect(it, 0), view)
        forced.push(r)
        put(i, r, 0)
    }
    // 3. a dimension under a finding slides along its line, or hides
    for (k = 0; k < forced.length; k++) {
        for (var j = taken.length - 1; j >= 0; j--) {
            var t = taken[j]
            if (items[t.i].kind !== "dim" || !hit(t.r, forced[k], GAP + t.hold)) continue
            taken.splice(j, 1)
            out[t.i] = { x: 0, y: 0, visible: false, c: -1 }
            seat(t.i, false)
        }
    }
    // 4. notes on reference outlines, where there is room
    for (i = 0; i < items.length; i++) if (items[i].kind === "ref" && items[i].cands.length) seat(i, true)
    return out
}
