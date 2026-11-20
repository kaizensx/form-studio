pragma Singleton
import QtQuick
import QtCore
import FormNative

// FORM — a metrology bench at night.
// Graphite build plate, one pale-mint datum colour, clay for the part itself.
// Colour is evidence: datum = settled, blueprint = draft/compare, amber = review, signal = fail.
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
    readonly property color well: dark ? "#0a0c0e" : "#ffffff"        // inset: inputs receive content
    readonly property color plate: dark ? "#0e1113" : "#eceeed"       // the bench
    readonly property color plate1: dark ? "#13171a" : "#f4f5f4"      // panels resting on the bench
    readonly property color plate2: dark ? "#191e22" : "#fafbfa"      // raised: cards
    readonly property color plate3: dark ? "#21282d" : "#ffffff"      // highest: menus, buttons
    readonly property color plate4: dark ? "#2a3238" : "#e9eceb"      // a raised control under the pointer
    // ink
    readonly property color ink: dark ? "#e8edeb" : "#151a1b"
    readonly property color ink2: dark ? "#a8b2af" : "#465150"
    readonly property color ink3: dark ? "#717b78" : "#727d7a"
    readonly property color ink4: dark ? "#49524f" : "#a7b0ad"
    readonly property color lineBase: dark ? "#ffffff" : "#0b1512"    // what edges and washes are an alpha of
    readonly property color rule: alpha(lineBase, dark ? 0.07 : 0.09)
    readonly property color rule2: alpha(lineBase, dark ? 0.12 : 0.14)
    readonly property color rule3: alpha(lineBase, dark ? 0.2 : 0.26)           // emphasis: a hovered or raised edge
    // interaction washes laid over any plate
    readonly property color washHover: alpha(lineBase, dark ? 0.055 : 0.05)
    readonly property color washPress: alpha(lineBase, dark ? 0.1 : 0.095)
    readonly property color washOn: alpha(lineBase, dark ? 0.085 : 0.075)
    readonly property color scrim: dark ? Qt.rgba(0.016, 0.022, 0.027, 0.62) : Qt.rgba(0.09, 0.11, 0.11, 0.34) // behind sheets and the lightbox
    readonly property color shade: Qt.rgba(0, 0, 0, dark ? 0.5 : 0.16)          // drop shadow under floating layers
    readonly property real shadow: dark ? 1 : 0.3                              // how strong Shadow.qml draws
    readonly property color gleam: Qt.rgba(1, 1, 1, dark ? 0.05 : 0.7)          // the hairline of light on a raised top edge
    // meaning. Dark: pale tints that glow on graphite. Light: the same hues, deep enough to read on paper.
    readonly property color datum: dark ? "#b9e8d7" : "#17806a"
    readonly property color datumInk: dark ? "#0d1a16" : "#ffffff"
    readonly property color blueprint: dark ? "#86a8ff" : "#2f5ec9"
    readonly property color amber: dark ? "#e9b860" : "#a16207"
    readonly property color signal: dark ? "#ff6f51" : "#cf3a1c"
    readonly property color pass: dark ? "#86d9ad" : "#1c8553"
    readonly property color annotate: dark ? "#c7b2ff" : "#6f49cc"              // selections and annotations on the part
    readonly property color clay: "#d8d3c8"                                     // the part itself, the same in both
    // the mark, as brand/README.md sets it on graphite and on a light ground
    readonly property color markPart: dark ? clay : "#0e1113"
    readonly property color markOrigin: dark ? "#b9e8d7" : "#2f8a6c"
    readonly property color markInk: dark ? "#e8edeb" : "#0e1113"               // "Form"
    readonly property color markInk2: dark ? "#a8b2af" : "#5b6562"              // "Studio"
    readonly property color datumHi: dark ? "#cdf2e4" : "#1b9179"               // primary button, hovered
    readonly property color focus: alpha(datum, 0.6)                            // keyboard focus ring (datum)
    // the 3D bench (Viewport.qml): the ground to the horizon, the build plate on it, its 10 mm grid and its outline
    readonly property color benchGround: dark ? "#1d2327" : "#e6e9e7"
    readonly property color benchPlate: dark ? "#262d32" : "#c2c8c5"
    readonly property color benchGrid: dark ? "#2e363b" : "#b4bbb7"
    readonly property color benchEdge: dark ? "#55616a" : "#7f8985"

    readonly property string sans: "Instrument Sans"
    readonly property string mono: "Geist Mono"
    readonly property string icons: "lucide"

    // type scale (ratio ~1.2 from 13)
    readonly property int tCap: 10
    readonly property int tFine: 11
    readonly property int tBody: 13
    readonly property int tLead: 15
    readonly property int tH3: 18
    readonly property int tH2: 22
    readonly property int tH1: 30
    readonly property int tHero: 44
    readonly property int tDisplay: 52     // one line per screen at most: Home's question

    readonly property int rXs: 4
    readonly property int rSm: 6
    readonly property int rMd: 9
    readonly property int rLg: 14
    readonly property int rXl: 18          // sheets. Nested radii are concentric: inner = outer - padding

    // sheet widths: pick one, do not invent a fifth
    readonly property int sheetS: 480      // a question, a notice
    readonly property int sheetM: 640      // a form
    readonly property int sheetL: 840      // settings, lists with detail
    readonly property int sheetXl: 1080    // a canvas beside controls (render, variants, share)

    // weights (Instrument Sans is variable)
    readonly property int wBody: 420
    readonly property int wMedium: 520
    readonly property int wSemi: 620
    readonly property int wBold: 700

    // control heights
    readonly property int hSm: 24
    readonly property int hMd: 28
    readonly property int hLg: 34

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
    readonly property var easeSpring: [0.2, 0.9, 0.25, 1.04, 1, 1]  // arrival with the faintest settle, for a pass
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
        case "assumed": case "photo": case "WARN": case "simulated": case "modelled": case "model": return amber
        case "FAIL": case "resized": case "moved": case "added": case "removed": return signal
        case "trimmed": case "draft": return blueprint
        }
        return ink2
    }
}
