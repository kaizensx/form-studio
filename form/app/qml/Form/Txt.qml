import QtQuick

// All text in the app. kind: body | fine | cap | lead | h3 | h2 | h1 | hero ; mono for numbers.
Text {
    property string kind: "body"
    property bool mono: false
    property int tone: 1                 // 1 primary … 4 muted
    color: kind === "cap" ? Theme.ink3 : kind === "fine" ? (tone === 1 ? Theme.ink3 : [Theme.ink, Theme.ink2, Theme.ink3, Theme.ink4][tone - 1])
         : [Theme.ink, Theme.ink2, Theme.ink3, Theme.ink4][tone - 1]
    font.family: mono ? Theme.mono : Theme.sans
    font.pixelSize: ({ body: Theme.tBody, fine: Theme.tFine, cap: Theme.tCap, lead: Theme.tLead, h3: Theme.tH3, h2: Theme.tH2, h1: Theme.tH1, hero: Theme.tHero })[kind] || Theme.tBody
    font.weight: kind === "cap" ? 650 : (kind === "h1" || kind === "h2" || kind === "h3" || kind === "hero") ? 600 : 420
    font.letterSpacing: kind === "cap" ? 0.9 : kind === "hero" ? -1.2 : kind === "h1" ? -0.6 : kind === "h2" ? -0.3 : mono ? -0.1 : 0
    font.capitalization: kind === "cap" ? Font.AllUppercase : Font.MixedCase
    lineHeight: kind === "fine" || kind === "body" ? 1.25 : 1.1
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    elide: Text.ElideNone
    renderType: Text.NativeRendering
}
