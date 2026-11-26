DESIGN FOR 3D PRINTING (purpose: print)
  * Lay the part as it prints: the biggest flat face on z = 0. Overhangs <= 45 deg, or chamfer instead of fillet on
    bottom edges; bridges <= 20 mm; teardrop or diamond holes when horizontal and > 8 mm.
  * Walls >= 3 perimeters (1.2 mm on a 0.4 nozzle); ribs 50-70 % of the wall they stiffen. A structural wall under
    that FAILS the Thinnest-wall check (decorative ridges and fins between 2 and 3 perimeters stay a warning).
  * Decorative cuts (flutes, grooves, panels) go last and need wall >= 1.2 mm + their depth behind them.
  * Clearances per side: press 0.05-0.1, sliding 0.2-0.3, print-in-place 0.35-0.5 mm. Calibrate with a coupon.
  * Layers are the weak direction: snap beams, hooks and pins in XY; screw bosses with heat-set inserts (form.parts).
  * Texture survives only above about 2 nozzle widths in plan and 0.3 mm in depth.
  * Large shells (a helmet) do not fit most beds in one piece: split them with alignment keys or say what bed it needs.
