.pragma library

// One line of Python, coloured for Qt's StyledText: keywords, strings, numbers, comments, decorators and the names a
// design calls (build123d and form). A plain tokenizer, not a parser: a string that spans lines is coloured on its
// first line only. The colours are the app's own (the accent, amber, the pass green, the muted ink), one set per light.

var KW = ["False", "None", "True", "and", "as", "assert", "break", "class", "continue", "def", "del", "elif", "else",
          "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "not", "or", "pass",
          "raise", "return", "try", "while", "with", "yield", "self"]

function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/ /g, "&nbsp;") }

function palette(dark) {
    return dark ? { kw: "#3ee6ff", str: "#f2c36b", num: "#c7b2ff", com: "#74736f", deco: "#7bd88f", def: "#f4f3f1", base: "#d6d5d2" }
                : { kw: "#06708d", str: "#9a5f00", num: "#6f49cc", com: "#8b8a86", deco: "#1a7a3a", def: "#161616", base: "#2c2b29" }
}

function span(c, s) { return "<font color=\"" + c + "\">" + esc(s) + "</font>" }

function colour(line, dark) {
    var P = palette(dark), out = "", i = 0, n = line.length, afterDef = false
    while (i < n) {
        var ch = line[i], rest = line.slice(i), m
        if (ch === "#") { out += span(P.com, rest); break }
        if (ch === "@" && /^\s*$/.test(line.slice(0, i))) { m = /^@[\w.]+/.exec(rest); out += span(P.deco, m[0]); i += m[0].length; continue }
        if (ch === "\"" || ch === "'") {
            m = /^([rbfu]{0,2})?("""|'''|"(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?)/.exec(rest)
            var s = m ? m[0] : ch
            out += span(P.str, s); i += s.length; continue
        }
        if (/[0-9]/.test(ch) && !/[\w]/.test(line[i - 1] || "")) { m = /^\d[\d_]*(\.\d+)?([eE][+-]?\d+)?/.exec(rest); out += span(P.num, m[0]); i += m[0].length; continue }
        if (/[A-Za-z_]/.test(ch)) {
            m = /^[A-Za-z_]\w*/.exec(rest)
            var w = m[0]
            if (KW.indexOf(w) >= 0) { out += span(P.kw, w); afterDef = w === "def" || w === "class" }
            else if (afterDef) { out += "<b>" + span(P.def, w) + "</b>"; afterDef = false }
            else out += span(P.base, w)
            i += w.length; continue
        }
        out += span(P.base, ch); i++
    }
    return out
}
