.pragma library
// Formatting shared by every screen.
function fmt(v, d) { if (d === undefined) d = 2; return (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(d) }
function trim(v, d) { if (d === undefined) d = 3; return (v === null || v === undefined) ? "—" : String(parseFloat(Number(v).toFixed(d))) }
function pad(n) { var s = String(n); return "r" + (s.length < 2 ? "0" + s : s) }
function dur(s) {
    if (s === null || s === undefined) return "—"
    var m = Math.round(s / 60)
    return m >= 60 ? Math.floor(m / 60) + " h " + (m % 60 < 10 ? "0" : "") + (m % 60) + " min" : m + " min"
}
function ago(ts) {
    var s = Date.now() / 1000 - ts
    if (s < 90) return "just now"
    if (s < 3600) return Math.round(s / 60) + " min ago"
    if (s < 86400) return Math.round(s / 3600) + " h ago"
    return new Date(ts * 1000).toLocaleDateString(Qt.locale(), "d MMM")
}
function keys(o) { return o ? Object.keys(o) : [] }
function vals(o) { var r = []; for (var k in o) r.push(o[k]); return r }
function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s") }
