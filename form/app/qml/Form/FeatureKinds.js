.pragma library

// What each kind of hand feature shows in its property card (FeatureCard.qml), section by section.
//
// A field is one of:
//   num     a number. `s` names its parameter by suffix ("<feature id>_<s>", as form/modelling.py and
//           form/modelling_more.py write them); `opt` (when given) is the option that makes the parameter when the
//           design does not have it yet (a draft, a thin wall, an offset): typing it rewrites the feature's call.
//   menu    one choice of several, written in the feature's call (an end condition): `opt`, `choices`.
//   seg     the same as a segmented control, for two to four short choices.
//   toggle  a choice that is on or off (reverse, mid-plane, flip, ruled).
//   pick    a face (or a point) picked on the stage for an end condition: `opt` is the option the pick fills
//           ("to_at"), `has` the option that says the feature already has one ("has_to").
// `when(o)` shows a field or a section only when it applies, read from the feature's options as the card holds them
// (the head's, from GET /tree `options`, with the card's pending changes over them). Choices change the feature's
// code (POST /redefine, form/feature_redefine.py); numbers that are already parameters change as values.

var ENDS = [{ value: "blind", text: "Blind" }, { value: "through", text: "Through all" }, { value: "next", text: "Up to next" },
            { value: "face", text: "Up to face" }, { value: "vertex", text: "Up to vertex" },
            { value: "offset", text: "Offset from face" }, { value: "mid", text: "Mid-plane" }]
var ENDS2 = [{ value: "", text: "None" }].concat(ENDS.filter(function (e) { return e.value !== "mid" }))
var REV_ENDS = [{ value: "angle", text: "Angle" }, { value: "face", text: "Up to face" }]
var THIN = [{ value: "one", text: "One side" }, { value: "mid", text: "Mid" }, { value: "two", text: "Two sides" }]

function endOf(o) { return o.end || o.end_shown || "blind" }
function faceEnd(e) { return e === "face" || e === "offset" }

var SKETCH = [
    { title: "Section", info: "sketch" },
    { title: "Direction 1", fields: [
        { kind: "menu", opt: "end", t: "End condition", choices: ENDS, value: endOf },
        { kind: "pick", opt: "to_at", has: "has_to", t: "Up to", what: "face", when: function (o) { return faceEnd(endOf(o)) } },
        { kind: "pick", opt: "to", has: "has_to", t: "Up to", what: "point", when: function (o) { return endOf(o) === "vertex" } },
        { kind: "num", s: "depth", t: "Depth", when: function (o) { var e = endOf(o); return e === "blind" || e === "mid" } },
        { kind: "num", s: "offset", opt: "offset", t: "Offset", when: function (o) { return endOf(o) === "offset" } },
        { kind: "toggle", opt: "reverse", t: "Reverse direction", when: function (o) { return endOf(o) !== "mid" } },
        { kind: "num", s: "draft", opt: "draft", t: "Draft", unit: "°" }] },
    { title: "Direction 2", when: function (o) { return endOf(o) !== "mid" }, fields: [
        { kind: "menu", opt: "end2", t: "End condition", choices: ENDS2, value: function (o) { return o.end2 || "" } },
        { kind: "pick", opt: "to2_at", has: "has_to2", t: "Up to", what: "face", when: function (o) { return faceEnd(o.end2) } },
        { kind: "num", s: "depth2", opt: "depth2", t: "Depth", when: function (o) { return o.end2 === "blind" } },
        { kind: "num", s: "offset2", opt: "offset2", t: "Offset", when: function (o) { return o.end2 === "offset" } }] },
    { title: "Thin feature", fields: [
        { kind: "toggle", opt: "thin", t: "Thin wall", on: 1, value: function (o) { return !!o.thin } },
        { kind: "num", s: "thin", opt: "thin", t: "Wall", when: function (o) { return !!o.thin } },
        { kind: "seg", opt: "thin_mode", t: "Wall goes", choices: THIN, value: function (o) { return o.thin_mode || "one" }, when: function (o) { return !!o.thin } },
        { kind: "num", s: "thin2", opt: "thin2", t: "Inside wall", when: function (o) { return !!o.thin && o.thin_mode === "two" } }] }]

var KINDS = {
    extrude: { name: "Extrude", sections: SKETCH },
    cut: { name: "Cut", sections: SKETCH },
    revolve: { name: "Revolve", sections: [
        { title: "Section", info: "sketch" },
        { title: "Angle", fields: [
            { kind: "menu", opt: "end", t: "End condition", choices: REV_ENDS, value: function (o) { return o.end || "angle" } },
            { kind: "pick", opt: "to_at", has: "has_to", t: "Up to", what: "face", when: function (o) { return o.end === "face" } },
            { kind: "num", s: "angle", t: "Angle", unit: "°", when: function (o) { return o.end !== "face" } },
            { kind: "toggle", opt: "mid", t: "Mid-plane" },
            { kind: "num", s: "angle2", opt: "angle2", t: "Other way", unit: "°", when: function (o) { return !o.mid } },
            { kind: "toggle", opt: "reverse", t: "Reverse direction" }] }] },
    fillet: { name: "Fillet", sections: [
        { title: "Edges", info: "edges" },
        { title: "Size", fields: [{ kind: "num", s: "r", t: "Radius" }] }] },
    chamfer: { name: "Chamfer", sections: [
        { title: "Edges", info: "edges" },
        { title: "Size", fields: [{ kind: "num", s: "d", t: "Length" }] }] },
    hole: { name: "Hole", sections: [
        { title: "Standard", info: "standard" },
        { title: "Size", fields: [{ kind: "num", s: "d", t: "Ø" }, { kind: "num", s: "head_d", t: "Head Ø" }, { kind: "num", s: "head_depth", t: "Counterbore depth" }] },
        { title: "Depth", fields: [{ kind: "num", s: "depth", t: "Depth (0 = through)" }] }] },
    pattern: { name: "Pattern", sections: [
        { title: "Direction", info: "axis" },
        { title: "Instances", fields: [{ kind: "num", s: "n", t: "Count", unit: "", int: true }, { kind: "num", s: "pitch", t: "Spacing" }, { kind: "num", s: "angle", t: "Angle step", unit: "°" }] }] },
    shell: { name: "Shell", sections: [
        { title: "Faces", info: "faces" },
        { title: "Thickness", fields: [{ kind: "num", s: "t", t: "Wall" }] }] },
    sweep: { name: "Sweep", sections: [
        { title: "Profile and path", info: "sweep" },
        { title: "Options", fields: [{ kind: "num", s: "twist", t: "Twist", unit: "°" }, { kind: "toggle", opt: "frenet", t: "Follow the path's turning (Frenet)" }] }] },
    loft: { name: "Loft", sections: [
        { title: "Sections", info: "loft" },
        { title: "Options", fields: [{ kind: "toggle", opt: "ruled", t: "Ruled (straight between sections)" }] }] },
    rib: { name: "Rib", sections: [
        { title: "Line", info: "sketch" },
        { title: "Rib", fields: [{ kind: "num", s: "t", t: "Thickness" },
                                 { kind: "seg", opt: "direction", t: "Grows", choices: [{ value: "parallel", text: "In the sketch plane" }, { value: "normal", text: "Out of it" }] },
                                 { kind: "toggle", opt: "flip", t: "Flip the side" }] }] },
    mirror: { name: "Mirror", sections: [
        { title: "What", info: "mirror" },
        { title: "Plane", fields: [{ kind: "seg", opt: "plane", t: "Mirror plane", choices: ["XY", "XZ", "YZ"], when: function (o) { return /^(XY|XZ|YZ)$/.test(o.plane || "") } }] }] },
    draft: { name: "Draft", sections: [
        { title: "Faces", info: "draftfaces" },
        { title: "Angle", fields: [{ kind: "num", s: "angle", t: "Angle", unit: "°" }, { kind: "toggle", opt: "flip", t: "Pull the other way" }] }] },
    move_face: { name: "Move face", sections: [
        { title: "Faces", info: "movefaces" },
        { title: "Distance", fields: [{ kind: "num", s: "d", t: "Along the normal" }] }] },
    thicken: { name: "Thicken", sections: [
        { title: "Surface", info: "thicken" },
        { title: "Thickness", fields: [{ kind: "num", s: "t", t: "Thickness" }, { kind: "toggle", opt: "both", t: "Half each side" }] }] },
    boolean: { name: "Boolean", sections: [
        { title: "Bodies", info: "bodies" },
        { title: "Operation", fields: [{ kind: "seg", opt: "op", t: "Operation", choices: [{ value: "combine", text: "Combine" }, { value: "subtract", text: "Subtract" }, { value: "intersect", text: "Intersect" }] }] }] },
    split: { name: "Split", sections: [
        { title: "Plane", fields: [{ kind: "seg", opt: "plane", t: "Split plane", choices: ["XY", "XZ", "YZ"], when: function (o) { return /^(XY|XZ|YZ)$/.test(o.plane || "") } }] },
        { title: "Keep", fields: [{ kind: "seg", opt: "keep", t: "Keep", choices: [{ value: "both", text: "Both" }, { value: "above", text: "Above" }, { value: "below", text: "Below" }] }] }] },
    variable_fillet: { name: "Variable fillet", sections: [
        { title: "Edges", info: "edges" },
        { title: "Radius", fields: [{ kind: "num", s: "r0", t: "At the start" }, { kind: "num", s: "r1", t: "At the end" }] }] },
    datum_plane: { name: "Datum plane", sections: [
        { title: "Base", info: "datum" },
        { title: "Place", fields: [{ kind: "num", s: "offset", t: "Offset" }, { kind: "num", s: "angle", t: "Angle", unit: "°" }] }] },
    datum_axis: { name: "Datum axis", sections: [
        { title: "Axis", info: "datum" }] }
}

var RE = /^(extrude|cut|revolve|fillet|chamfer|hole|pattern|shell|sweep|loft|rib|mirror|draft|move_face|thicken|boolean|split|variable_fillet|datum_plane|datum_axis)_\d+$/

// the kind of a feature written by hand, from its id (extrude_1, hole_2, move_face_1, ...); "" for any other feature
function kindOf(fid) {
    var m = RE.exec(fid || "")
    return m ? m[1] : ""
}
