import QtQuick

// All text in the app. kind: body | fine | cap | lead | h3 | h2 | h1 | hero ; mono for numbers.
// The scale steps by about 1.2 from 13 px. Hierarchy comes from weight and tone before size: a value is 620 / tone 1,
// a label 520 / tone 2, a note 420 / tone 3. Large type is set tighter; small caps are set wider.
Text {
    property string kind: "body"
    property bool mono: false
    property int tone: 1                 // 1 primary … 4 muted
    color: kind === "cap" ? Theme.ink3 : kind === "fine" ? (tone === 1 ? Theme.ink3 : [Theme.ink, Theme.ink2, Theme.ink3, Theme.ink4][tone - 1])
         : [Theme.ink, Theme.ink2, Theme.ink3, Theme.ink4][tone - 1]
    font.family: mono || kind === "cap" ? Theme.mono : Theme.sans      // captions are lettered like a drawing's: mono capitals
    font.pixelSize: ({ body: Theme.tBody, fine: Theme.tFine, cap: Theme.tCap, lead: Theme.tLead, h3: Theme.tH3, h2: Theme.tH2, h1: Theme.tH1, hero: Theme.tHero })[kind] || Theme.tBody
    font.weight: kind === "cap" ? Theme.wMedium : (kind === "h1" || kind === "h2" || kind === "h3" || kind === "hero") ? Theme.wSemi : Theme.wBody
    font.letterSpacing: kind === "cap" ? 1.2 : kind === "hero" ? -1.8 : kind === "h1" ? -1.0 : kind === "h2" ? -0.5 : kind === "h3" ? -0.3 : mono ? -0.1 : kind === "lead" ? -0.1 : 0
    font.capitalization: kind === "cap" ? Font.AllUppercase : Font.MixedCase
    lineHeight: kind === "fine" || kind === "body" ? 1.25 : kind === "lead" ? 1.3 : 1.1
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    elide: Text.ElideNone
    renderType: Text.NativeRendering
}
