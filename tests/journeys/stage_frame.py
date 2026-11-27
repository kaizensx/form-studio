"""A tall part stands whole in the free stage: under the top row, above the bar and its suggestions, clear of the tools
and the pane, with its dimension lines and their numbers.

- A vase, a wall hook, and a hinged box assembled with its lid open and pulled apart, with the conversation folded to
  the bar and its suggestions showing.
- The same with the pane folded, and with the conversation as a column (where the window has room for one).
- The bar grows when its suggestions arrive: the part is framed again, with a glide, and never ends under it.
- A part that fits keeps its framing when the bar shrinks back and grows again (no pumping)."""
import json

from _lib import make

DATA = "fresh"
TALK = [{"t": "user", "text": "make it a little taller", "local": True},
        {"t": "text", "text": "Done as revision 2.", "local": True}]

# the part's box (8 corners) and the dimension lines' ends, against the free stage (a part pulled apart has no lines)
SPREAD = """(function(){var v=Store.viewer,b=v.bounds,r={l:v.insetLeft,t:v.insetTop,r:v.width-v.insetRight,b:v.height-v.insetBottom},bad=[];
function chk(what,x,y){if(x<r.l-1||x>r.r+1||y<r.t-1||y>r.b+1)bad.push(what+' at '+Math.round(x)+','+Math.round(y))}
for(var i=0;i<8;i++){var q=v._px(Qt.vector3d(i&1?b.hi.x:b.lo.x,i&2?b.hi.y:b.lo.y,i&4?b.hi.z:b.lo.z));if(!q){bad.push('corner behind the camera');continue}chk('corner '+i,q.x,q.y)}
var d=v.showDims&&!(v.asmOn&&v.asmMode==='exploded')?(v.dimPx||[]):[];for(var k=0;k<d.length;k++)if(d[k]){chk('dimension line '+k,d[k][0],d[k][1]);chk('dimension line '+k,d[k][2],d[k][3])}
return {bad:bad,rect:[r.l,r.t,r.r,r.b],dist:v.dist}})()"""


def _inside(ui, what):
    # the view glides to its new framing: where frames are slow (a runner drawing in software) the glide is still
    # on its way after the settle, so the framing is waited for, then judged
    try:
        ui.wait_until(lambda: not ui.js(SPREAD)["bad"], 6, "the framing to come to rest")
    except Exception:                                  # noqa: BLE001 - the check below says what is outside
        pass
    s = ui.js(SPREAD)
    ui.check(not s["bad"], "%s: the part and its dimension lines stand inside the free stage %s (%s)"
             % (what, [round(x) for x in s["rect"]], "; ".join(s["bad"][:4])))
    rect = s["rect"]
    vp = ui.item("viewport")
    from PySide6.QtCore import QPointF
    for i in range(3):
        it = ui.find("dimLabel", nth=i)
        if it is None or not it.property("shown"):
            continue
        p = it.mapToItem(vp, QPointF(0, 0))
        ui.check(p.x() >= rect[0] - 1 and p.y() >= rect[1] - 1 and p.x() + it.width() <= rect[2] + 1 and p.y() + it.height() <= rect[3] + 1,
                 "%s: dimension number %d stands inside the free stage (%d, %d)" % (what, i, p.x(), p.y()))
    return s


def _bar(ui, suggestions):
    """The conversation folded to the bar; with suggestions (nothing said yet) or with a short talk."""
    ui.run_js("Store.talkOpen = true; Store.talkCalm = true; Store.chatItems = %s" % ("[]" if suggestions else json.dumps(TALK)))
    ui.settle(1400)
    if suggestions:
        ui.check(ui.exists("talkSuggestion"), "the bar shows its suggestions")


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    wide = ui.win.width() >= 1200
    tag = "%dx%d" % (ui.win.width(), ui.win.height())
    parts = [("vase", "Vase", None, None), ("desk_hanger", "Wall hook", None, None),
             ("hinged_box", "Hinged box", "assembled", 110), ("hinged_box", "Hinged box", "exploded", 0)]
    made = {}
    for recipe, name, mode, lid in parts:
        if recipe not in made:
            made[recipe] = make(ui, recipe, name, purpose="print" if recipe == "hinged_box" else None)
        else:
            ui.run_js("Store.open(%r)" % made[recipe]); ui.settle(1200)
        what = name + (" (%s, lid %d°)" % (mode, lid) if mode else "")
        _bar(ui, True)
        if mode:
            ui.run_js("Store.setAsmMode(%r)" % mode); ui.settle(900)
            joint = ui.js("(function(){var a=Store.viewer.asm;var j=a&&a.joints.filter(function(j){return j.kind==='hinge'})[0];return j?j.id:''})()")
            ui.check(bool(joint), "the hinged box has its lid's hinge")
            ui.run_js("Store.pose = %s" % json.dumps({joint: lid})); ui.settle(1400)
        _inside(ui, what + ", the bar with its suggestions")
        ui.shot("stage-frame-%s-%s%s" % (tag, recipe, "-" + mode if mode else ""))
        ui.run_js("Store.paneFolded = true"); ui.settle(1400)
        _inside(ui, what + ", the pane folded")
        ui.run_js("Store.paneFolded = false"); ui.settle(1400)
        if wide:
            ui.run_js("Store.chatItems = %s; Store.talkCalm = false" % json.dumps(TALK)); ui.settle(1400)
            ui.check(ui.js("Store.talkCol") > 0, "the conversation is a column")
            _inside(ui, what + ", the conversation as a column")
        if mode:
            ui.run_js("Store.pose = ({}); Store.setAsmMode('print')"); ui.settle(900)

    # ── the bar grows as its suggestions arrive: the vase is framed again, gliding, and ends above it ──
    ui.run_js("Store.open(%r)" % made["vase"]); ui.settle(1200)
    _bar(ui, False)
    ui.check(not ui.exists("talkSuggestion"), "a talk in the bar: no suggestions")
    d0 = _inside(ui, "the vase over a one-line bar")["dist"]
    ui.run_js("Store.chatItems = []")
    ui.wait(_half_glide(ui))
    mid = ui.js("Store.viewer.dist")
    ui.settle(1400)
    d1 = _inside(ui, "the vase once the suggestions are in")["dist"]
    ui.check(d1 > d0 * 1.02, "the camera pulled back for the taller bar (%.0f, %.0f)" % (d0, d1))
    if not ui.js("Theme.reduced"):
        ui.check(d0 * 0.999 < mid < d1 * 1.001, "it glides there (%.0f half way between %.0f and %.0f)" % (mid, d0, d1))
    # and back, and again: the same two framings, no creep
    _bar(ui, False)
    ui.check(abs(ui.js("Store.viewer.dist") - d0) < 0.02 * d0, "the bar shrinks back: the vase is framed as before")
    _bar(ui, True)
    ui.check(abs(ui.js("Store.viewer.dist") - d1) < 0.02 * d1, "the suggestions again: the same framing")
    ui.no_warnings()


def _half_glide(ui):
    """Half the camera's glide, in ms."""
    return max(40, int(ui.js("Motion.camera") or 400) // 2)
