# Cost per process

Form Studio estimates what a design costs to make by FDM, resin (SLA), powder bed (SLS), Multi Jet Fusion, metal
printing (LPBF), 3-axis CNC milling, injection moulding and sheet metal, plus the parts you buy. Each estimate is built
from the design's own drivers and a table of rates. Every rate in the table is published, cited and dated, or it is a
process parameter labelled assumed. The result is a quote-style estimate (class C) for comparing designs and
processes. It is not a quote.

```
form cost compare <project>                                  # every process, cost per part against quantity
form cost <project> --process injection --qty 1000,10000     # one process, line by line
form cost rates                                              # the table, with sources
form cost rates --shop garage --rate labour=32 --use         # your own rate, in your own shop
```

MCP: `estimate_cost` (with `process` and `quantities`), `cost_compare`, `cost_rates`. The Bench lists **Cost per process** in
Make. Settings › Costs shows every rate with its source and takes your shop's own numbers.

## What a number is made of

Each process returns **lines**. A line is either **fixed** (once per order: tooling, setups, programming) or **per
part**. Every line shows its formula with the numbers filled in, and the evidence of each input:

| Evidence | Meaning |
|---|---|
| sourced | A published number: statistics office, vendor price page, paper or textbook. Each one has its URL, the date it was read, the period it applies to and the sentence that states it. |
| specified | Your number, for your shop or for this one estimate. |
| assumed | A process parameter that no source states, such as a setup time, a build rate or a machine's life in hours. Money is never assumed. |
| computed | Measured on the design's solid (volume, projected area, walls, faces, flat pattern) or worked out by a stated formula. |
| simulated | The slicer's grams and hours, or the cycle time of the current CAM simulation. |
| estimated | Worked out from an assumed rate because no slice or simulation exists yet. |
| missing | No published value and none from you. The line is left out of the totals and says what to set. |

`assumed_share` is the share of the counted amount (fixed costs plus one part) that sits in lines with at least one
assumed input. Cost per part at quantity *q* is `fixed / q + per part`.

## The models

| Process | Per part | Fixed | Drivers |
|---|---|---|---|
| FDM | filament (g × price/kg) + printer write-off (h × price / life) + electricity (W × h × price/kWh) + labour | job setup | the slicer's grams and hours when sliced (simulated); otherwise volume × an assumed solid fraction and an assumed deposition rate |
| SLA | resin (volume × support factor × price/L) + printer write-off + labour (wash, cure, supports) | job setup | B-rep volume |
| SLS, MJF | powder (mass × consumption factor × price/kg) + machine time + labour (depowder) | job setup | B-rep volume; the density of the design's polyamide, or PA's as a labelled stand-in |
| LPBF | powder + machine time (volume / build rate × rate) + labour | job setup | B-rep volume; the design's metal, or 316L |
| CNC | stock (bounding box + margin × density × price/kg) + cycle time × (machine + operator) + tool wear | setups × setup time; programming | the current CAM simulation's cycle time (simulated), or removed volume / an assumed removal rate; the fewest setups from manufacturability |
| Injection moulding | machine (cycle × rate / cavities) + resin | mould base + cavities and cores | projected area, thickest wall and side actions from manufacturability; depth along the pull |
| Sheet metal | sheet (flat area × t × nesting × density × price/kg) + laser (cut length / speed + pierces) + bends × time × (brake + operator) | batch setup | the unfold, proved by folding back: flat area, thickness, cut length, contours, bends |
| Purchased | quantity × your price | | the parts list, at prices you gave |

### Injection moulding

Injection moulding follows Boothroyd, Dewhurst and Knight, *Product Design for Manufacture and Assembly*, 2nd edition,
chapter 8. The chapter was read in the MIT 2.810 course copy, which is a scan.

- **Clamp force:** cavities × projected area × (1 + runner share) × half the resin's injection pressure. The machine is
  the smallest one in Table 8.4 that holds the clamp force and the shot.
- **Cycle:** fill t_f = 2 V_s p_j / P_j (Eq. 8.3), plus cooling, plus resetting.
  - Cooling (Eq. 8.5): t_c = h² / (π² α) · ln[(4/π)(T_i − T_m) / (T_x − T_m)]. This is the first-term solution BASF
    also gives.
  - Resetting (Eq. 8.7): t_r = 1 + 1.75 t_d √((2D + 5) / L_s).
- **Machine rate:** the chosen machine's operating cost in Table 8.4, in US dollars of the book's date.
- **Mould:**
  - Mould base: C_b = 1000 + 0.45 A_c h_p^0.4 (Eq. 8.8). The plate holds the cavities with 7.5 cm between them and to
    the edges, plus 7.5 cm per side action, and is the part depth + 15 cm thick.
  - Cavity and core hours:
    - ejection: 2.5 A_p^0.5 (Eq. 8.10)
    - complexity: 45 X^1.27 (Eq. 8.11). X is 0.01 per B-rep face; holes are not counted apart, which makes it an
      estimate.
    - area: 5 + 0.085 A_p^e (Eq. 8.13). The scanned copy prints e = ½. The exponent is a rate (`im.cavity_exponent`)
      you can set from your own edition.
    - side-pulls: 65 hours each.
    - finish: 15 % of the complexity and area hours (Table 8.6, opaque standard).
  - Cavity cost: the hours × the mould maker's rate ($40 per hour, the textbook point system's rate as Boothroyd
    Dewhurst Inc. states it).
  - More cavities: × n^0.7 (Eq. 8.16).
- **Checks against the book's own worked numbers** (tests/test_costing.py):
  - fill: 1.09 s
  - resetting: 12.0 s and 9.2 s
  - mould base: about $9,500
  - six 15 cm disks need the 8,500 kN machine
- **Not adjusted for inflation:** the mould and machine dollars are the book's. Set your own `im.mould_maker_per_h`,
  `im.k1` or a shop rate to use today's prices.

## Rates and their sources

The table is `form/costing/rates.toml`. All of its sources were read on 2026-11-28.

| Rate | Value | Source |
|---|---|---|
| Labour | 40.3 EUR/h (euro area, industry, 2025) | Eurostat, Hourly labour costs |
| Electricity | 0.18 EUR/kWh (EU non-household, 2026-H1) | Eurostat news, 4 Nov 2026 |
| PLA filament | 32.99 EUR/kg (list, incl. VAT) | Prusament PLA price page |
| FDM printer | 1,349 EUR, 90 W printing PLA | Prusa CORE One+ product page |
| SLA resin, printer | 79 USD/L; 2,625 USD | Formlabs Grey V5 and Form 4 pages |
| SLS powder, printer | 99 USD/kg; 24,649 USD | Formlabs Nylon 12 and Fuse 1+ 30W pages |
| MJF powder | 63.96 USD/kg (8,315 USD / 130 kg) | MatterHackers (HP publishes no price) |
| LPBF machine | 25.04 EUR/h without labour | Bareth et al., Applied Sciences 2026 |
| LPBF build rate | 6.3 cm³/h | NIST SP 1176 (2014), base model |
| 316L powder | 13.56 EUR/kg | Qualloy price page |
| Milling machine | 8.28 EUR/h without labour | Bareth et al. 2026 |
| 6061 aluminium stock | 36.74 USD/kg (24.00 USD for a 1.44 lb plate) | Speedy Metals price page |
| ABS, PP, HDPE granulate | 1.99, 1.321, 1.312 EUR/kg | PlasticPortal.eu, week 42/2026 |
| Moulding machines, resins | Tables 8.4 and 8.5 | Boothroyd, Dewhurst and Knight |
| Mould making | 40 USD/h | Boothroyd Dewhurst Inc., Structural Foam Molding Cost |
| Steel | 0.748 EUR/kg (HRC index; cut sheet costs more) | EUROMETAL / Fastmarkets |
| Aluminium | 2.983 USD/kg (LME cash; sheet costs more) | Westmetall LME data |
| Laser cutter | 27.55 EUR/h | An anonymous, undated document (a weak source, labelled so) |
| USD per EUR | 1.0957 (27 Nov 2026) | ECB reference rate |

**No published rate was found** for an MJF machine hour or a press-brake hour. Until you set them, those lines are
left out of the totals and say so. A CNC shop rate survey, a laser cost per metre and a cost per bend were not found
either. CNC uses the machine-only rate plus the labour rate. Sheet metal uses cutting time and bending time with
assumed speeds.

Vendor prices change and some are sale or list prices. Each rate says which. Run `form cost rates` to see every rate
with its quote.

## Your shop

A shop has a name, a currency, its own rates and its own exchange rates. It is kept in `<data dir>/cost.json`, next to
the print prices that `form cost <project>` uses. A rate you set is **specified** and replaces the published one.
Clearing it brings the published rate back. A rate given for one estimate (`--rate`, MCP `rates`) wins over the shop's
rate for that call only.

Amounts are shown in the shop's currency. Money published in another currency is converted only with a stated rate:
the ECB reference rate in the table, or the rate you set for the shop (`--fx GBP=0.85`, units per 1 EUR). Without a
stated rate the line is not converted and is not counted.

Purchased parts are costed only at prices you give (`--part-price "ISO 4762 M3×10=0.12"`). Form Studio never looks
up a price.

## Quantity curves and crossovers

`form cost compare` gives, for each process, the fixed cost, the cost per part and the cost per part at each quantity
(default 1, 10, 100, 1,000 and 10,000). It also gives:

- the cheapest process at each quantity, among processes whose lines are all counted;
- `switches`: where the cheapest process changes as the quantity grows;
- every pairwise crossover. Process B costs less per part than process A from
  q = (F_B − F_A) / (V_A − V_B), with the arithmetic and the evidence of the lines it rests on. A process with lines
  not counted says which.

### Example: an 80 × 60 × 30 mm tray

The tray has 2 mm walls and nothing is set for it. This is a real run in the published shop, in EUR. There is no
slice and no CAM simulation, so FDM and CNC use the estimated times.

| Process | Fixed | Per part | 1 | 10 | 100 | 1,000 | 10,000 | Not counted |
|---|---|---|---|---|---|---|---|---|
| FDM printing | 6.72 | 4.15 | 10.86 | 4.82 | 4.21 | 4.15 | 4.15 | |
| Resin printing (SLA) | 6.72 | 9.37 | 16.09 | 10.04 | 9.44 | 9.38 | 9.37 | |
| Powder bed (SLS) | 6.72 | 9.36 | 16.08 | 10.03 | 9.43 | 9.37 | 9.36 | |
| Multi Jet Fusion | 6.72 | 5.47 | 12.19 | 6.14 | 5.54 | 5.48 | 5.47 | machine time |
| Metal printing (LPBF) | 6.72 | 122.08 | 128.80 | 122.75 | 122.15 | 122.09 | 122.08 | |
| CNC milling, 3-axis | 80.60 | 38.48 | 119.08 | 46.54 | 39.29 | 38.56 | 38.49 | |
| Injection moulding | 2,523.95 | 0.13 | 2,524.08 | 252.53 | 25.37 | 2.66 | 0.38 | |

Injection moulding costs less per part than FDM printing from about 628 parts:
(2,523.95 − 6.72) / (4.1457 − 0.1315) = 627.1.

The moulding numbers come from a 276 kN clamp on the 300 kN machine and an 11.2 s cycle (1 s fill, 10.4 s cooling
for 2 mm of ABS, resetting). The mould is 1,543 EUR of mould base and 981 EUR of cavity and core, both in the book's
dollars. Labour dominates FDM at this size, and labour is a sourced rate times an assumed 5 minutes per part, so
FDM's assumed share is high. Set your own times to firm it up.

## For optimise and inverse design

```python
from form import costing
costing.cost(st, p, "injection", quantity=5000)      # per part, or None when a line is not counted
f = costing.objective("auto", 1000)                  # (st, p, candidate=None) -> the cheapest complete process's cost per part
f.point(st, p, {"volume_mm3": 5000, "size": [40, 30, 5]})   # the same, with its evidence, for an unsaved candidate
```

Inverse design uses it as the metric `cost.per_part` (`inverse_design(..., minimize=["mass_g", "cost.per_part"],
costing={"process": "auto", "quantity": 1000})`, or `form optimize pareto --cost-quantity 1000`). A candidate of a
search is built but never saved, so it has no slice, CAM simulation, manufacturability check or unfold: FDM, SLA, SLS,
MJF, LPBF and CNC are costed from its own volume and bounding box (CNC setups are the head revision's, said so), and
moulding and sheet metal are refused for a candidate rather than costed from the head's geometry. The axis is
labelled with the evidence classes of the counted lines and the largest assumed share.

`cost()` never returns a partial number unless asked (`complete_only=False`). An objective therefore never prefers a
design only because one of its costs is missing.

## What is not counted

The estimate leaves out:

- scrap and failed parts;
- regrind and colourant;
- packing and shipping;
- overhead and margin;
- finishing beyond the listed labour;
- inspection, tolerances and certification;
- fixtures;
- the runner material (taken as reground);
- inflation of the book's dollars.

For FDM, the slicer's numbers replace the estimated ones once the design is sliced. For CNC, the CAM simulation's cycle
time replaces the estimated one (`cam_plan`, `cam_post`). Neither is a measurement of a real part.
