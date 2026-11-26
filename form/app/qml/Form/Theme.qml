pragma Singleton
import QtQuick
import QtCore
import FormNative

// Form Studio — Lightdesk (docs/design/DIRECTION.md).
// The window is a photo studio: the part alone in a pool of warm light, every control a pane of glass over it.
// One signal colour, electric cyan (`datum`), with one meaning: this is where you are. Green only means pass, amber
// only means review, signal only means fail. Geist for words, Geist Mono for numbers and lettering.
QtObject {
    id: theme
    // ── appearance: dark (the default, the bench at night) or light (the same bench by day) ──
    // "dark" | "light" | "system". Kept between runs; FORM_APPEARANCE overrides it for one run (screenshots, tests).
    // Every colour below is a pair, so a screen that only uses tokens is correct in both.
    property string appearance: "dark"
    readonly property bool dark: Bridge.appearanceOverride ? Bridge.appearanceOverride !== "light"
                               : appearance === "light" ? false : appearance === "system" ? Bridge.systemDark : true
    property Settings _mem: Settings { category: "look"; property alias appearance: theme.appearance }
    function setAppearance(a) { appearance = a === "light" || a === "system" ? a : "dark" }

    // surfaces. Dark: lowest is darkest and each step up is lighter. Light: the bench is the quiet grey and each
    // step up is whiter, so "higher = nearer the light" holds in both.
    readonly property color frame: dark ? "#0b0b0c" : "#eeece8"   // the room: the window itself, and the 3D view's own ground
    readonly property color well: dark ? "#0e0e10" : "#ffffff"   // inset: inputs receive content
    readonly property color plate: dark ? "#0b0b0c" : "#eeece8"   // the room (the 3D view clears to this)
    readonly property color plate1: dark ? "#161617" : "#f4f2ef"   // a solid pane: what glass falls back to
    readonly property color plate2: dark ? "#1c1c1e" : "#f9f8f6"   // raised: cards
    readonly property color plate3: dark ? "#252527" : "#ffffff"   // highest: menus, buttons
    readonly property color plate4: dark ? "#313134" : "#e9e6e1"   // a raised control under the pointer
    // the workspace is plates on the frame: one radius, one gutter, a hairline, a line of light on the top edge
    readonly property int rPanel: 22
    readonly property int gap: 12
    readonly property color panelEdge: alpha(lineBase, dark ? 0.11 : 0.1)
    // glass: every pane over the room. `glass` is laid over the blurred room; `glass2` is a raised or selected thing
    // inside a pane; `glassEdge` is the 1 px edge of light; `glassSolid` is the pane when nothing can be blurred.
    readonly property bool blur: !Bridge.solidGlass
    readonly property color glass: dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(1, 1, 1, 0.62)
    readonly property color glass2: dark ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.95)
    readonly property color glassEdge: dark ? Qt.rgba(1, 1, 1, 0.11) : Qt.rgba(1, 1, 1, 0.9)
    readonly property color glassTint: dark ? Qt.rgba(0.04, 0.04, 0.045, 0.3) : Qt.rgba(0.96, 0.95, 0.93, 0.5)   // under `glass`, over the blur: keeps text legible on a bright part
    readonly property color glassSolid: dark ? Qt.rgba(0.098, 0.098, 0.106, 0.94) : Qt.rgba(0.972, 0.965, 0.953, 0.95)
    readonly property color glassWell: dark ? Qt.rgba(0.043, 0.043, 0.047, 0.66) : Qt.rgba(1, 1, 1, 0.82)        // the prompt inside the bar
    readonly property color send: dark ? "#f4f3f1" : "#161616"       // the one filled button: send, Design it, the active tool
    readonly property color sendInk: dark ? "#0b0b0c" : "#ffffff"
    readonly property color sendHi: dark ? "#ffffff" : "#2c2c2c"
    readonly property color key: dark ? "#ffe9cf" : "#ffffff"        // the key light, warm
    // the room behind everything: top, upper wall, the lit floor, the foot
    readonly property var room: dark ? ["#0a0a0b", "#131314", "#1b1b1c", "#0d0d0e"] : ["#e6e3de", "#efede9", "#f6f5f2", "#e4e1dc"]
    readonly property color vignette: dark ? Qt.rgba(0, 0, 0, 0.78) : Qt.rgba(0.47, 0.41, 0.35, 0.16)
    readonly property int edge: 20          // panes sit this far from the window's edge
    readonly property int rPane: 22         // panes; capsules are fully round
    // ink
    readonly property color ink: dark ? "#f4f3f1" : "#161616"
    readonly property color ink2: dark ? "#a9a8a5" : "#5d5c59"
    readonly property color ink3: dark ? "#74736f" : "#8b8a86"
    readonly property color ink4: dark ? "#4d4c4a" : "#b3b1ac"
    readonly property color lineBase: dark ? "#ffffff" : "#14110e"   // what edges and washes are an alpha of
    readonly property color rule: alpha(lineBase, dark ? 0.09 : 0.09)
    readonly property color rule2: alpha(lineBase, dark ? 0.13 : 0.13)
    readonly property color rule3: alpha(lineBase, dark ? 0.2 : 0.26)           // emphasis: a hovered or raised edge
    // interaction washes laid over any plate
    readonly property color washHover: alpha(lineBase, dark ? 0.07 : 0.05)
    readonly property color washPress: alpha(lineBase, dark ? 0.12 : 0.095)
    readonly property color washOn: alpha(lineBase, dark ? 0.14 : 0.08)
    readonly property color scrim: dark ? Qt.rgba(0.02, 0.02, 0.024, 0.62) : Qt.rgba(0.2, 0.17, 0.14, 0.3)   // behind sheets and the lightbox
    readonly property color shade: dark ? Qt.rgba(0, 0, 0, 0.5) : Qt.rgba(0.24, 0.2, 0.16, 0.16)   // drop shadow under floating layers
    readonly property real shadow: dark ? 1 : 0.3                              // how strong Shadow.qml draws
    readonly property color gleam: Qt.rgba(1, 1, 1, dark ? 0.08 : 0.9)   // the hairline of light on a raised top edge
    // meaning. Dark: pale tints that glow on graphite. Light: the same hues, deep enough to read on paper.
    readonly property color datum: dark ? "#3ee6ff" : "#06708d"
    readonly property color datumInk: dark ? "#03222a" : "#ffffff"
    readonly property color blueprint: dark ? "#3ee6ff" : "#06708d"
    readonly property color amber: dark ? "#f2c36b" : "#a86a00"
    readonly property color signal: dark ? "#ff6f51" : "#cf3a1c"
    readonly property color pass: dark ? "#7bd88f" : "#1a7a3a"
    readonly property color annotate: dark ? "#c7b2ff" : "#6f49cc"              // selections and annotations on the part
    readonly property color clay: "#d8d3c8"   // the part itself, the same in both
    // the mark, as brand/README.md sets it on graphite and on a light ground
    readonly property color markPart: dark ? clay : "#0e1113"
    readonly property color markOrigin: dark ? "#1fcff2" : "#0a8fb3"              // the mark's origin square: the accent as the brand sets it at small sizes
    readonly property color markInk: dark ? "#f4f3f1" : "#161616"   // "Form"
    readonly property color markInk2: dark ? "#a9a8a5" : "#5d5c59"   // "Studio"
    readonly property color datumHi: dark ? "#7ff0ff" : "#055d76"   // the accent, hovered
    readonly property color focus: alpha(datum, 0.6)                            // keyboard focus ring (datum)
    // the 3D bench (Viewport.qml): the ground to the horizon, the build plate on it, its 10 mm grid and its outline
    readonly property color benchGround: dark ? "#070708" : "#e9e6e1"
    readonly property color benchPool: dark ? "#2a231c" : "#fdfcfa"   // the floor where the key light falls, under the part: warm
    readonly property color benchLine: alpha(lineBase, dark ? 0.07 : 0.14)   // the floor's 10 mm grid, when it is asked for
    readonly property color benchPlate: dark ? "#232324" : "#cfcbc5"
    readonly property color benchGrid: dark ? "#2f2f31" : "#bfbab3"
    readonly property color benchEdge: dark ? "#5c5b58" : "#8a867f"

    readonly property string sans: "Geist"
    readonly property string mono: "Geist Mono"
    readonly property string icons: "lucide"
    // How glyphs are drawn. On macOS the system's own rasteriser thickens every stem ("font smoothing"), which set the
    // whole interface about one weight heavier than it is drawn in the mockups; Qt's own renderer draws the outlines
    // as they are. Elsewhere the system's hinted glyphs stay: they are the sharper ones on a 1x display.
    readonly property int textRender: Bridge.platform === "darwin" ? Text.QtRendering : Text.NativeRendering
    readonly property real lineBox: 1.3     // Geist and Geist Mono: ascent + descent, in em (1005 + 295 units of 1000)

    // type scale (ratio ~1.2 from 13)
    readonly property int tCap: 10
    readonly property int tFine: 11
    readonly property int tBody: 13
    readonly property int tLead: 15
    readonly property int tH3: 18
    readonly property int tH2: 22
    readonly property int tH1: 30
    readonly property int tHero: 44
    readonly property int tDisplay: 68     // one line per screen at most: Home's question
    readonly property int tCue: 54         // the build's lower third: the feature being made

    readonly property int rXs: 6
    readonly property int rSm: 9
    readonly property int rMd: 12
    readonly property int rLg: 18
    readonly property int rXl: 26   // sheets. Nested radii are concentric: inner = outer - padding

    // sheet widths: pick one, do not invent a fifth
    readonly property int sheetS: 480      // a question, a notice
    readonly property int sheetM: 640      // a form
    readonly property int sheetL: 840      // settings, lists with detail
    readonly property int sheetXl: 1080    // a canvas beside controls (render, variants, share)

    // weights (Instrument Sans is variable)
    readonly property int wBody: 400
    readonly property int wMedium: 500
    readonly property int wSemi: 600
    readonly property int wBold: 700

    // control heights
    readonly property int hSm: 26
    readonly property int hMd: 30
    readonly property int hLg: 38

    // spacing: 4px base
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24
    readonly property int s8: 32
    readonly property int s10: 40
    readonly property int s12: 48
    readonly property int s16: 64          // between the bands of a page (hero, lists)

    // motion
    readonly property int fast: 120
    readonly property int base: 180
    readonly property int slow: 320
    // the workspace: tool options and inspector sections, cross-fades of the part, the camera, assembly parts travelling
    readonly property int ui: 170
    readonly property int cross: 240
    readonly property int camera: 420
    readonly property int part: 300
    readonly property var easeOut: [0.23, 1, 0.32, 1, 1, 1]
    readonly property var easeMove: [0.77, 0, 0.175, 1, 1, 1]
    readonly property var easeDrawer: [0.32, 0.72, 0, 1, 1, 1]    // panels that slide (the agent column)
    // Motion tokens. Use them as: NumberAnimation { duration: Theme.pop; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
    //   press 110  a control answering a press        pop 150    menus, popovers, tooltips
    //   fast 120   hover and colour                    base 180   sheets, toasts
    //   exit 110   anything leaving (faster than it came)        slow 320   first-run and entrance moments
    //   stagger 45 between items of an entrance cascade
    // `reduced` is read once at start (OS "reduce motion", or FORM_REDUCED_MOTION=1). When set, movement and scale are
    // dropped (Theme.move(ms) returns 0, Theme.shift(px) returns 0) and only opacity/colour still animate.
    readonly property bool reduced: Bridge.reducedMotion
    readonly property int press: 110
    readonly property int pop: 150
    readonly property int exit: 110
    readonly property int stagger: 45
    //   screen 380 one screen handing over to the next (Home -> workspace -> designing)
    //   panel 300  the panels of a screen arriving after it, `stagger` apart
    //   rise 8     how far a message or row rises as it arrives
    readonly property int screen: 240      // was 380: a screen change is used all day, so it is brief
    readonly property int sheet: 200       // a sheet arriving; it leaves in `exit`
    readonly property int panel: 300
    readonly property int rise: 8
    readonly property var easeSpring: [0.2, 0.9, 0.25, 1.04, 1, 1]   // arrival with the faintest settle, for a pass
    // a pane arriving: fade and an 8 px rise, 180 ms; the transcript sheet and a built line land with a spring
    readonly property real springK: 5.2
    readonly property real springDamp: 0.42
    function move(ms) { return reduced ? 0 : ms }
    function shift(px) { return reduced ? 0 : px }
    function from(scale) { return reduced ? 1 : scale }

    // tooltips: the moment the last one closed, so the next one opens without a delay (see Tip.qml)
    property real tipSeen: 0
    readonly property bool mac: Bridge.platform === "darwin"
    // "Ctrl+Shift+O" → ["⇧", "⌘", "O"] on macOS, ["Ctrl", "Shift", "O"] elsewhere. Shortcuts are written the Qt way everywhere.
    function keyCaps(seq) {
        var parts = String(seq).split("+"), out = []
        var glyph = { Ctrl: "⌘", Shift: "⇧", Alt: "⌥", Meta: "⌃", Return: "↵", Enter: "↵", Esc: "esc", Escape: "esc", Up: "↑", Down: "↓", Left: "←", Right: "→", Backspace: "⌫", Delete: "⌦", Tab: "⇥", Space: "space" }
        var order = { "⌃": 0, "⌥": 1, "⇧": 2, "⌘": 3 }
        for (var i = 0; i < parts.length; i++) {
            var k = parts[i]
            if (mac) out.push(glyph[k] || k)
            else out.push(k === "Return" || k === "Enter" ? "Enter" : k === "Escape" ? "Esc" : k)
        }
        if (mac) out.sort(function (a, b) { return (order[a] === undefined ? 9 : order[a]) - (order[b] === undefined ? 9 : order[b]) })
        return out
    }
    function keyText(seq) { return keyCaps(seq).join(mac ? "" : "+") }

    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    // a meaning colour as text on its own tint: a step brighter on graphite, a step deeper on paper
    function strong(c) { return dark ? Qt.lighter(c, 1.25) : Qt.darker(c, 1.3) }
    // how a number is known → colour
    function evidence(kind) {
        switch (kind) {
        case "measured": case "physical": case "calibrated": case "PASS": return pass
        case "specified": case "computed": case "interface": case "geometry": return datum
        case "assumed": case "photo": case "WARN": case "simulated": case "modelled": case "model": case "partial":
        case "left out": return amber
        case "FAIL": return signal
        // what a draft does to a feature is a change to compare, not a failure: the draft's own colour
        case "resized": case "moved": case "added": case "removed": case "trimmed": case "draft": return blueprint
        }
        return ink2
    }
}
