.pragma library
// Formatting shared by every screen.
function fmt(v, d) { if (d === undefined) d = 2; return (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(d) }
function trim(v, d) { if (d === undefined) d = 3; return (v === null || v === undefined) ? "—" : String(parseFloat(Number(v).toFixed(d))) }
function bytes(n) { n = Number(n) || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : n >= 1e3 ? Math.round(n / 1e3) + " kB" : n + " B" }
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

// What a tool call is, in the design's words: the conversation's live line and the Designing screen say the same.
var TOOL_SAYS = { design_guide: "Reading the design contract", create_design: "Writing the design as code", update_design: "Changing the code",
    edit_design: "Editing a feature", propose_concepts: "Building concepts side by side", render: "Looking at the part", read_document: "Reading the drawing",
    import_reference: "Importing the reference part", ask_user: "Asking you", ask_measurement: "Asking you to measure",
    create_project: "Starting from a building block", describe_recipe: "Reading a building block", preview_change: "Trying a change",
    commit_change: "Keeping a change", run_pipeline: "Building, checking and slicing", get_project: "Reading the design",
    plan_design: "Planning the features", design_brief: "Writing the brief", fetch_link: "Opening a link", strength_study: "Running the strength study",
    get_strength_study: "Reading the strength study", run_study: "Running a study", measure: "Measuring the solid", mass_properties: "Working out the mass",
    reconstruct: "Rebuilding the mesh as CAD", critique: "Reviewing its own design", optimize: "Searching for a better design",
    manufacturability: "Checking it can be made" }
function toolSay(name) { var n = String(name || "").replace(/^mcp__form__/, ""); return TOOL_SAYS[n] || ("Calling " + n) }
