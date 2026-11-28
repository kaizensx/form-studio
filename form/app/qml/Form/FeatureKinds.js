.pragma library

// What each kind of hand feature shows in its property card (FeatureCard.qml), section by section, and the parameter
// each field writes. A field names its parameter by suffix: "<feature id>_<suffix>" (form/modelling.py writes them).
//
// The hook for the engine's later features (branch more-features: extrude end conditions, reverse, a second
// direction, draft, thin wall). A field marked `later` is drawn only when the design has its parameter, so the card
// shows exactly what the engine builds today and nothing it cannot: once modelling.plan writes, say,
// `extrude_1_draft`, the Draft field appears with no change here. `ends` lists the end conditions the engine builds
// for a kind; `endParam` is the parameter that will carry the choice (0 blind, 1 through all, 2 up to next, 3 up to
// a face, 4 mid-plane) when the engine has one. Until then a cut's "through all" is its depth of 0, as today.

var ENDS = [{ value: 0, text: "Blind" }, { value: 1, text: "Through all" }, { value: 2, text: "Up to next" },
            { value: 3, text: "Up to face" }, { value: 4, text: "Mid-plane" }]

var KINDS = {
    extrude: { name: "Extrude", sections: [
        { title: "Section", info: "sketch" },
        { title: "Direction 1", fields: [{ s: "end", t: "End condition", ends: [0], endParam: "end" },
                                         { s: "depth", t: "Depth" }, { s: "reverse", t: "Reverse", toggle: true, later: true },
                                         { s: "draft", t: "Draft", unit: "°", later: true }] },
        { title: "Direction 2", later: "depth2", fields: [{ s: "depth2", t: "Depth", later: true }] },
        { title: "Thin feature", later: "thin", fields: [{ s: "thin", t: "Wall", later: true }] }] },
    cut: { name: "Cut", sections: [
        { title: "Section", info: "sketch" },
        { title: "Direction 1", fields: [{ s: "end", t: "End condition", ends: [0, 1], endParam: "end" },
                                         { s: "depth", t: "Depth", hideAtEnd: 1 }, { s: "reverse", t: "Reverse", toggle: true, later: true },
                                         { s: "draft", t: "Draft", unit: "°", later: true }] },
        { title: "Direction 2", later: "depth2", fields: [{ s: "depth2", t: "Depth", later: true }] },
        { title: "Thin feature", later: "thin", fields: [{ s: "thin", t: "Wall", later: true }] }] },
    revolve: { name: "Revolve", sections: [
        { title: "Section", info: "sketch" },
        { title: "Angle", fields: [{ s: "angle", t: "Angle", unit: "°" }] }] },
    fillet: { name: "Fillet", sections: [
        { title: "Edges", info: "edges" },
        { title: "Size", fields: [{ s: "r", t: "Radius" }] }] },
    chamfer: { name: "Chamfer", sections: [
        { title: "Edges", info: "edges" },
        { title: "Size", fields: [{ s: "d", t: "Length" }] }] },
    hole: { name: "Hole", sections: [
        { title: "Standard", info: "standard" },
        { title: "Size", fields: [{ s: "d", t: "Ø" }, { s: "head_d", t: "Head Ø" }, { s: "head_depth", t: "Counterbore depth" }] },
        { title: "Depth", fields: [{ s: "depth", t: "Depth (0 = through)" }] }] },
    pattern: { name: "Pattern", sections: [
        { title: "Direction", info: "axis" },
        { title: "Instances", fields: [{ s: "n", t: "Count", unit: "", int: true }, { s: "pitch", t: "Spacing" }, { s: "angle", t: "Angle step", unit: "°" }] }] },
    shell: { name: "Shell", sections: [
        { title: "Faces", info: "faces" },
        { title: "Thickness", fields: [{ s: "t", t: "Wall" }] }] }
}

// the kind of a feature written by hand, from its id (extrude_1, hole_2, ...); "" for any other feature
function kindOf(fid) {
    var m = /^(extrude|cut|revolve|fillet|chamfer|hole|pattern|shell)_\d+$/.exec(fid || "")
    return m ? m[1] : ""
}
