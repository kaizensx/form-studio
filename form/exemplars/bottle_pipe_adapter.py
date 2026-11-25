"""Bottle-to-pipe adapter: a cap that screws onto a standard soda bottle (PCO 1881 neck thread) and carries a socket
for 3/4" schedule 40 PVC pipe, with a gasket seat and grip ribs. For drip waterers, rain-barrel overflows and bottle
funnels. The bottle-thread and pipe-socket exemplar. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cone, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Soda-bottle to PVC pipe adapter",
    "category": "consumer",
    "tags": ["bottle", "cap", "soda bottle", "pet", "pco1881", "pco 1881", "28 mm", "bottle thread", "thread",
             "pipe", "pvc", "socket", "3/4 inch", "adapter", "fitting", "waterer", "funnel", "gasket", "grip ribs"],
    "techniques": ["parts.bottle_thread('PCO1881', external=False) turned over with Rot(180, 0, 0) so the cap prints "
                   "open end down", "parts.pipe_socket('3/4', depth) with a stop at the pipe's bore",
                   "a cone shoulder between the cap and the socket boss so nothing overhangs past 45 deg",
                   "grip ribs as a ring of filleted boxes fused to the skirt"],
    "lessons": [
        "Use the bottle's real thread: PCO 1881 is the 28 mm neck of most soda bottles, and bottle_thread builds the "
        "cap's thread from the standard with a named clearance, so it screws onto a bottle from the shop.",
        "A cap's thread cutter opens at z = 0 going down; turn it over (Rot(180, 0, 0)) to print the cap open end "
        "down: a rotation keeps the thread right-handed, a mirror would not.",
        "A socket for stock pipe is the pipe's published OD plus a clearance, with a stop at the bottom bored to the "
        "pipe's own bore, so the flow is not stepped and the pipe has a seat.",
        "Seal with a gasket on the neck's lip, not with the thread: leave a flat land above the thread for it.",
    ],
}


class Design(Recipe):
    title, summary = "Bottle-to-pipe adapter", "A PCO 1881 bottle cap with a socket for 3/4\" PVC pipe."
    solids = 1
    params = [
        Param("cap_d", "Cap outside diameter", 36, 33, 44, 0.5, "mm", "form", "cap"),
        Param("clearance", "Thread clearance (diametral)", 0.4, 0.1, 0.8, 0.05, "mm", "interface", "thread"),
        Param("socket_depth", "Pipe socket depth", 22, 12, 40, 0.5, "mm", "brief", "socket"),
        Param("pipe_clearance", "Pipe clearance (diametral)", 0.3, 0.1, 0.8, 0.05, "mm", "interface", "socket",
              "On the published 26.67 mm OD; 0.3 slides a PVC pipe in for gluing."),
        Param("ribs", "Grip ribs", 18, 0, 30, 1, "", "form", "grip"),
    ]
    features = [Feature("cap", "Cap skirt", "structure"), Feature("thread", "PCO 1881 thread", "interface"),
                Feature("gasket", "Gasket land", "interface"), Feature("socket", "Pipe socket", "interface"),
                Feature("grip", "Grip ribs", "finish")]

    LAND = 2.0                 # flat above the thread for a gasket on the bottle's lip
    WALL = 3.0

    def _dims(self, v):
        th = parts.bottle_thread("PCO1881", external=False, clearance=v["clearance"])
        sock = parts.pipe_socket("3/4", v["socket_depth"], clearance=v["pipe_clearance"])
        L = th["thread_length"] + 1.0                            # thread zone, with 1 mm of lead-in below it
        z_land = L + self.LAND
        boss_r = sock["socket_d"] / 2 + self.WALL
        shoulder = max(v["cap_d"] / 2 - boss_r, 0.0)            # 45 deg cone from the cap to the boss
        z_boss = z_land + 2.5 + shoulder
        return th, sock, L, z_land, boss_r, z_boss

    def constraints(self, v):
        th, sock, L, z_land, boss_r, z_boss = self._dims(v)
        if v["cap_d"] / 2 - th["modelled_major_d"] / 2 < 2.0:
            return [RecipeError("The cap wall around the thread is under 2 mm", "cap", "Make the cap wider.", ["cap_d"])]
        return []

    def build(self, v):
        th, sock, L, z_land, boss_r, z_boss = self._dims(v)
        R = v["cap_d"] / 2
        H = z_boss + v["socket_depth"]
        skirt = Cylinder(R, z_land + 2.5, align=BOTTOM)
        cone = Pos(0, 0, z_land + 2.5) * Cone(R, boss_r, R - boss_r, align=BOTTOM) if R > boss_r else None
        boss = Pos(0, 0, z_boss - 0.01) * Cylinder(boss_r, H - z_boss + 0.01, align=BOTTOM)
        body = skirt + boss + cone if cone is not None else skirt + boss
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 1.0)
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[0], 0.6)
        stages = [Stage("cap", body)]
        # --- snippet: a bottle cap's thread, printed open end down
        # bottle_thread's cutter opens at z = 0 and goes down; Rot(180, 0, 0) turns it to open at z = 0 going up
        # (a rotation, so the thread stays right-handed). The 1 mm below it is a plain lead-in at the major diameter.
        body = body - Pos(0, 0, 1.0) * Rot(180, 0, 0) * th.shape
        body = body - Pos(0, 0, -0.1) * Cylinder(th["modelled_major_d"] / 2, 1.2, align=BOTTOM)
        # --- end snippet
        stages.append(Stage("thread", body))
        # gasket land: a flat ring above the thread for a silicone gasket on the bottle's lip, bored to the neck's ID
        body = body - Pos(0, 0, L - 0.01) * Cylinder(th["modelled_major_d"] / 2, self.LAND + 0.01, align=BOTTOM)
        body = body - Pos(0, 0, z_land - 0.01) * Cylinder(sock["bore_d"] / 2, z_boss - z_land + 0.02, align=BOTTOM)
        stages.append(Stage("gasket", body))
        body = body - Pos(0, 0, H) * sock.shape
        stages.append(Stage("socket", body))
        n = int(v["ribs"])
        if n:
            rib = Box(2.4, 2.2, z_land - 1.0, align=BOTTOM)          # half sunk into the skirt
            rib = craft.safe_fillet(rib, rib.edges().filter_by(Axis.Z), 0.8)
            ring = None
            for i in range(n):
                r = Rot(0, 0, 360 * i / n) * Pos(R - 0.3, 0, 0.5) * rib
                ring = r if ring is None else ring + r
            body = craft.fuse(body, ring)
        stages.append(Stage("grip", body))
        return parts.checked(stages)

    def derived(self, v):
        th, sock, L, z_land, boss_r, z_boss = self._dims(v)
        return (th.derived("thread", "thread.", ("modelled_major_d", "clearance"))
                + sock.derived("socket", "socket.", ("socket_d",)))

    def appearance(self, v):
        return [{"features": ["cap", "thread", "gasket", "socket", "grip"], "finish": "petg", "color": "#3f7fbf"}]
