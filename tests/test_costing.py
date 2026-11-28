"""Cost per process (form/costing): every model against a hand calculation, the crossover math, overrides, and the
rule that nothing is labelled sourced without a source.

* **Models by hand**: FDM, SLA, SLS, MJF, LPBF, CNC, injection moulding (BDK ch. 8, including the book's own worked
  numbers: fill 1.09 s, resetting 12.0 s, mould base ≈ 9,500 USD, the 8,500 kN machine), sheet metal and purchased
  parts, each line recomputed here from the published rates.
* **Crossovers**: (ΔF / ΔV) for two processes, none when one is cheaper at every quantity, and the lower envelope.
* **Overrides**: a shop's rate is "specified" and replaces the published one; a rate for one call wins over the
  shop; clearing an override brings the published rate back; currencies convert with the ECB rate or the shop's
  own, and without a stated rate the line is not counted. form/cost.py's print prices keep the shops.
* **Sources**: every sourced rate names a source with a URL, a read date and a quote; a table that does not is
  refused; money is never assumed; a money rate nobody published has no value.
* **A project**: compare() on a real design, cost() and objective() for optimise, the MCP tools and the CLI.
"""
import asyncio
import copy
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-costing-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import config, costing  # noqa: E402
from form.costing import models, rates  # noqa: E402
from form.costing.models import drv  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

LAB = 40.3                      # Eurostat, euro area industry, 2025
USD = 1.0957                    # ECB, 27 Nov 2026: USD per EUR


def amounts(res: dict) -> dict:
    return {ln["item"]: ln["amount"] for ln in res["lines"]}


def R(**kw):
    return rates.Rates(None, **kw)


class Models(unittest.TestCase):
    """Each model's lines, recomputed by hand from the published table."""

    def test_fdm(self):
        d = {"grams": drv("grams", 50, "g", "simulated"), "hours": drv("hours", 2.5, "h", "simulated"),
             "volume_mm3": drv("v", 40000, "mm³", "computed"), "material_key": "PLA"}
        a = amounts(models.fdm(d, R()))
        self.assertAlmostEqual(a["Filament"], 50 / 1000 * 32.99, 6)
        self.assertAlmostEqual(a["Printer time (write-off)"], 2.5 * 1349 / 5000, 6)
        self.assertAlmostEqual(a["Electricity"], 90 / 1000 * 2.5 * 0.18, 6)
        self.assertAlmostEqual(a["Labour per part (supports, check)"], 5 / 60 * LAB, 6)
        self.assertAlmostEqual(a["Build job setup"], 10 / 60 * LAB, 6)

    def test_fdm_other_filament_needs_a_price(self):
        d = {"grams": drv("grams", 50, "g", "simulated"), "hours": drv("hours", 2.5, "h", "simulated"),
             "volume_mm3": drv("v", 40000, "mm³", "computed"), "material_key": "PETG"}
        res = models.fdm(d, R())
        ln = next(x for x in res["lines"] if x["item"] == "Filament")
        self.assertIsNone(ln["amount"])
        self.assertIn("fdm.material.PETG", ln["needs"])
        self.assertIn("Filament", models.totals(res, [1])["not_counted"])

    def test_sla_converts_dollars_with_the_ecb_rate(self):
        res = models.sla({"volume_mm3": drv("v", 30000, "mm³", "computed")}, R())
        a = amounts(res)
        self.assertAlmostEqual(a["Resin"], 30 / 1000 * 1.15 * 79 / USD, 6)
        self.assertAlmostEqual(a["Printer time (write-off)"], 30 / 20 * (2625 / USD) / 5000, 6)
        resin = next(x for x in res["lines"] if x["item"] == "Resin")
        conv = next(i for i in resin["inputs"] if i["id"] == "sla.resin_per_l")
        self.assertEqual(conv["currency_original"], "USD")
        self.assertEqual(conv["converted"]["evidence"], "sourced")

    def test_sls_and_mjf(self):
        d = {"volume_mm3": drv("v", 20000, "mm³", "computed"), "density_g_cm3": drv("rho", 1.0, "g/cm³", "assumed")}
        a = amounts(models.sls(d, R()))
        self.assertAlmostEqual(a["Powder"], 20 * 1.0 / 1000 * 1.5 * 99 / USD, 6)
        self.assertAlmostEqual(a["Printer time (write-off)"], 20 / 25 * (24649 / USD) / 10000, 6)
        res = models.mjf(d, R())
        a = amounts(res)
        self.assertAlmostEqual(a["Powder"], 20 / 1000 * 1.3 * 63.96 / USD, 6)
        self.assertIsNone(a["Machine time"])                       # no published MJF machine rate: not counted
        self.assertEqual(models.totals(res, [1])["not_counted"], ["Machine time"])

    def test_lpbf(self):
        d = {"volume_mm3": drv("v", 12600, "mm³", "computed"), "density_g_cm3": drv("rho", 8.0, "g/cm³", "specified")}
        a = amounts(models.lpbf(d, R()))
        self.assertAlmostEqual(a["Powder"], 12.6 * 8.0 / 1000 * 1.2 * 13.56, 6)
        self.assertAlmostEqual(a["Machine time"], 12.6 / 6.3 * 25.04, 6)          # 2 h at the M290's rate
        self.assertAlmostEqual(a["Labour per part (plate, supports, handling)"], 0.5 * LAB, 6)

    def test_cnc(self):
        d = {"stock_mm3": drv("s", 100000, "mm³", "computed"), "density_g_cm3": drv("rho", 2.7, "g/cm³", "specified"),
             "material_key": "AL-6061", "cycle_s": drv("c", 1800, "s", "simulated"), "setups": drv("n", 2, "", "computed")}
        a = amounts(models.cnc(d, R()))
        self.assertAlmostEqual(a["Stock"], 100 * 2.7 / 1000 * 36.74 / USD, 6)
        run = 0.5 * (8.28 + LAB)
        self.assertAlmostEqual(a["Machining"], run, 6)
        self.assertAlmostEqual(a["Tool wear"], 0.1 * run, 6)
        self.assertAlmostEqual(a["Setups"], 2 * 30 / 60 * LAB, 6)
        self.assertAlmostEqual(a["Programming (once)"], LAB, 6)
        res = models.cnc({**d, "material_key": "TITANIUM"}, R())          # no published titanium stock price
        self.assertIsNone(amounts(res)["Stock"])

    def test_sheet_metal(self):
        d = {"flat_mm2": drv("a", 20000, "mm²", "computed"), "t_mm": drv("t", 2, "mm", "computed"),
             "density_g_cm3": drv("rho", 7.85, "g/cm³", "specified"), "material_key": "steel",
             "cut_mm": drv("c", 900, "mm", "computed"), "pierces": drv("p", 3, "", "computed"),
             "bends": drv("b", 2, "", "computed")}
        res = models.sheet_metal(d, R())
        a = amounts(res)
        self.assertAlmostEqual(a["Sheet"], 20000 * 2 / 1000 * 1.25 * 7.85 / 1000 * 0.74833, 6)
        self.assertAlmostEqual(a["Laser cutting"], (900 / 3000 * 60 + 3 * 1.0) / 3600 * 27.55, 6)
        self.assertIsNone(a["Bending"])                             # no published press-brake rate
        self.assertAlmostEqual(a["Batch setup"], 30 / 60 * LAB, 6)
        flat = models.sheet_metal({**d, "bends": drv("b", 0, "", "computed")}, R())
        self.assertEqual(amounts(flat)["Bending"], 0.0)
        self.assertTrue(models.totals(flat, [1])["complete"])

    def test_purchased_only_at_prices_given(self):
        res = models.purchased([{"designation": "ISO 4762 M3×10", "quantity": 4}], R())
        self.assertIsNone(res["lines"][0]["amount"])
        self.assertIn("only prices you give", res["lines"][0]["needs"])


class Moulding(unittest.TestCase):
    """Boothroyd, Dewhurst and Knight, ch. 8: the book's worked numbers, then the model by hand."""

    T = rates.table()

    def test_book_examples(self):
        m8500 = next(m for m in self.T["im_machine"] if m["clamp_kN"] == 8500)
        self.assertAlmostEqual(models.reset_s(20, m8500["dry_cycle_s"], m8500["stroke_cm"]), 12.0, 1)   # "12.0 s"
        self.assertAlmostEqual(models.reset_s(10, m8500["dry_cycle_s"], m8500["stroke_cm"]), 9.2, 1)    # "9.2 s"
        self.assertAlmostEqual(models.fill_s(489, 1000, 90), 1.09, 2)                                   # "1.09 s"
        self.assertAlmostEqual(models.mould_base_usd(4500, 37.5) / 1000, 9.6, 1)  # Fig. 8.7 reads "approximately $9,500"
        # six 15 cm disks in ABS: 6 × 1.15 × 177 cm² at half of 1000 bar needs the 8,500 kN machine
        clamp = 6 * 1.15 * 177 * 500 / 100
        self.assertEqual(models.im_machine(self.T["im_machine"], clamp, 489)["clamp_kN"], 8500)

    def test_cooling_formula(self):
        abs_ = self.T["im_resin"]["ABS"]
        tc = models.cooling_s(4, abs_["alpha"], abs_["Ti"], abs_["Tm"], abs_["Tx"])
        hand = 16 / (math.pi ** 2 * 0.13) * math.log(4 / math.pi * (260 - 54) / (82 - 54))
        self.assertAlmostEqual(tc, hand, 9)
        self.assertAlmostEqual(tc, 27.9, 1)
        self.assertAlmostEqual(models.cooling_s(2, 0.13, 260, 54, 82), tc / 4, 9)      # t ∝ h²

    def test_model_by_hand(self):
        d = {"projected_mm2": drv("ap", 10000, "mm²", "computed"), "volume_mm3": drv("v", 20000, "mm³", "computed"),
             "wall_max_mm": drv("h", 2, "mm", "computed"), "depth_mm": drv("d", 30, "mm", "computed"),
             "plan_mm": [100, 100], "side_actions": drv("s", 0, "", "computed"), "faces": drv("f", 100, "", "computed"),
             "resin": "ABS", "cavities": 1}
        res = models.injection(d, R(), self.T["im_resin"], self.T["im_machine"])
        a = amounts(res)
        clamp = 100 * 1.15 * 1000 * 0.5 / 100                            # 575 kN -> the 800 kN machine
        self.assertAlmostEqual(res["clamp_kN"], round(clamp, 1), 6)
        self.assertEqual(res["machine"]["clamp_kN"], 800)
        shot = 20 * 1.15
        cyc = (models.fill_s(shot, 1000, 18.5) + models.cooling_s(2, 0.13, 260, 54, 82) + models.reset_s(3, 3.3, 32))
        self.assertAlmostEqual(res["cycle_s"], round(cyc, 3), 3)
        self.assertAlmostEqual(a["Moulding machine"], res["cycle_s"] / 3600 * 33 / USD, 6)
        self.assertAlmostEqual(a["Resin"], 20 * 1.05 / 1000 * 1.99, 6)
        A = (10 + 15) * (10 + 15)                                         # one cavity, 7.5 cm all round
        self.assertAlmostEqual(a["Mould base"], (1000 + 0.45 * A * (3 + 15) ** 0.4) / USD, 4)
        ap = 100
        mx, mpo = 45 * 1.0 ** 1.27, 5 + 0.085 * ap ** 0.5
        pts = 2.5 * ap ** 0.5 + mx + mpo + 0.15 * (mx + mpo)
        self.assertAlmostEqual(a["Cavities and cores"], pts * 40 / USD, 4)
        two = models.injection({**d, "cavities": 2}, R(), self.T["im_resin"], self.T["im_machine"])
        self.assertAlmostEqual(amounts(two)["Cavities and cores"], pts * 40 / USD * 2 ** 0.7, 4)    # 62 % more
        self.assertEqual(two["machine"]["clamp_kN"], 1600)               # 1150 kN for two cavities
        self.assertAlmostEqual(amounts(two)["Moulding machine"], two["cycle_s"] / 3600 * 41 / USD / 2, 6)

    def test_unknown_resin_is_said(self):
        d = {"projected_mm2": drv("ap", 10000, "mm²", "computed"), "volume_mm3": drv("v", 20000, "mm³", "computed"),
             "wall_max_mm": drv("h", 2, "mm", "computed"), "depth_mm": drv("d", 30, "mm", "computed"),
             "plan_mm": [100, 100], "side_actions": drv("s", 0, "", "computed"), "faces": drv("f", 100, "", "computed"),
             "resin": "PEEK", "cavities": 1}
        res = models.injection(d, R(), self.T["im_resin"], self.T["im_machine"])
        self.assertIsNone(amounts(res)["Moulding machine"])
        self.assertTrue(any("PEEK" in n for n in res["notes"]))


class Crossover(unittest.TestCase):
    def test_math(self):
        a = {"fixed": 10.0, "per_part_variable": 5.0}
        b = {"fixed": 1000.0, "per_part_variable": 0.5}
        q = models.crossover(a, b)
        self.assertAlmostEqual(q, 990 / 4.5)
        self.assertAlmostEqual(a["fixed"] / q + a["per_part_variable"], b["fixed"] / q + b["per_part_variable"])
        self.assertIsNone(models.crossover(b, a))            # a never overtakes b at volume
        self.assertIsNone(models.crossover(a, {"fixed": 5.0, "per_part_variable": 1.0}))   # cheaper from the start

    def test_envelope_and_totals(self):
        res = {"lines": [{"item": "tool", "basis": "fixed", "amount": 100.0, "evidence": ["sourced"]},
                         {"item": "part", "basis": "part", "amount": 2.0, "evidence": ["assumed", "sourced"]},
                         {"item": "x", "basis": "part", "amount": None, "evidence": ["missing"]}]}
        t = models.totals(res, [1, 10, 100])
        self.assertEqual([c["per_part"] for c in t["curve"]], [102.0, 12.0, 3.0])
        self.assertEqual(t["not_counted"], ["x"])
        self.assertAlmostEqual(t["assumed_share"], 2 / 102, 4)
        env = models.envelope({"print": {"fixed": 5, "per_part_variable": 10}, "cnc": {"fixed": 100, "per_part_variable": 4},
                               "mould": {"fixed": 3000, "per_part_variable": 0.5}})
        self.assertEqual([(a, b) for a, b, _q in env], [("print", "cnc"), ("cnc", "mould")])
        self.assertAlmostEqual(env[0][2], 95 / 6)
        self.assertAlmostEqual(env[1][2], 2900 / 3.5)


class Overrides(unittest.TestCase):
    def setUp(self):
        self.cfg = {"data": {"dir": tempfile.mkdtemp(prefix="form-costing-shop-")}}

    def test_shop_rate_is_specified_and_clears(self):
        rates.update_shop(self.cfg, "garage", label="Garage", rates={"labour": 25}, activate=True)
        r = rates.Rates(self.cfg)
        lab = r.get("labour")
        self.assertEqual((lab["value"], lab["evidence"]), (25.0, "specified"))
        self.assertIn("Garage", lab["source"])
        self.assertEqual(rates.Rates(self.cfg, overrides={"labour": 30}).get("labour")["value"], 30.0)   # this call wins
        self.assertEqual(rates.Rates(self.cfg, shop="default").get("labour")["value"], LAB)
        rates.update_shop(self.cfg, "garage", rates={"labour": None})
        self.assertEqual(rates.Rates(self.cfg).get("labour")["evidence"], "sourced")

    def test_override_applies_in_a_model(self):
        rates.update_shop(self.cfg, "", rates={"labour": 60, "mjf.machine_per_h": 30})
        d = {"volume_mm3": drv("v", 20000, "mm³", "computed"), "density_g_cm3": drv("rho", 1.0, "g/cm³", "assumed")}
        a = amounts(models.mjf(d, rates.Rates(self.cfg)))
        self.assertAlmostEqual(a["Machine time"], 20 / 40 * 30, 6)
        self.assertAlmostEqual(a["Labour per part (depowder, blast)"], 5 / 60 * 60, 6)

    def test_currency(self):
        rates.update_shop(self.cfg, "us", currency="USD", activate=True)
        r = rates.Rates(self.cfg)
        self.assertAlmostEqual(r.get("labour")["value"], LAB * USD, 9)          # EUR -> USD with the ECB rate
        self.assertEqual(r.get("sla.resin_per_l")["value"], 79)                 # published in dollars: unchanged
        gbp = rates.Rates(self.cfg, currency="GBP").get("labour")              # no GBP rate stated: not converted
        self.assertIsNone(gbp["value"])
        self.assertIn("exchange rate", gbp["needs"])
        rates.update_shop(self.cfg, "us", fx={"GBP": 0.85})
        self.assertAlmostEqual(rates.Rates(self.cfg, currency="GBP").get("labour")["value"], LAB * 0.85, 9)
        with self.assertRaises(StudioError):
            rates.update_shop(self.cfg, "us", currency="XYZ")

    def test_print_prices_keep_the_shops(self):
        from form import cost
        rates.update_shop(self.cfg, "garage", rates={"labour": 25})
        cost.save_prefs(self.cfg, {"kwh_price": 0.3})
        self.assertEqual(rates.shops(self.cfg)["shops"]["garage"]["rates"], {"labour": 25.0})
        self.assertEqual(cost.load_prefs(self.cfg)["kwh_price"], 0.3)

    def test_part_prices(self):
        rates.update_shop(self.cfg, "", part_prices={"ISO 4762 M3×10": 0.12})
        res = models.purchased([{"designation": "ISO 4762 M3×10", "quantity": 4}], rates.Rates(self.cfg))
        self.assertAlmostEqual(res["lines"][0]["amount"], 0.48)
        self.assertIn("specified", res["lines"][0]["evidence"])

    def test_unknown_rate_refused(self):
        with self.assertRaises(StudioError):
            rates.update_shop(self.cfg, "", rates={"nonsense": 1})


class Sources(unittest.TestCase):
    def test_every_sourced_rate_has_its_source(self):
        t = rates.table()
        for r in t["rates_by_id"].values():
            x = rates.Rates(None).get(r["id"])
            if x["evidence"] == "sourced":
                s = t["sources_by_id"][r["source"]]
                self.assertTrue(s["url"].startswith("http"), r["id"])
                self.assertTrue(s["read"], r["id"])
                self.assertTrue(r.get("quote") and r.get("applies"), r["id"])
                self.assertIn(s["url"], x["source"])
            elif x["evidence"] == "assumed":
                self.assertIsNone(rates.money_unit(r["unit"]), f"{r['id']}: money is never assumed")
                self.assertTrue(r.get("why"), r["id"])
            else:
                self.assertEqual(x["evidence"], "missing", r["id"])
                self.assertIsNone(x["value"], r["id"])

    def test_a_table_without_sources_is_refused(self):
        raw = copy.deepcopy({k: v for k, v in rates.table().items() if k not in ("sources_by_id", "rates_by_id")})
        bad = copy.deepcopy(raw)
        bad["rate"][0].pop("source")                              # a value with no source and not marked assumed
        with self.assertRaises(ValueError):
            rates.validate(bad)
        bad = copy.deepcopy(raw)
        bad["rate"].append({"id": "x", "value": 9, "unit": "EUR/h", "assumed": True, "why": "made up"})
        with self.assertRaises(ValueError):                       # an assumed price
            rates.validate(bad)
        bad = copy.deepcopy(raw)
        bad["rate"].append({"id": "y", "value": 9, "unit": "EUR/h", "source": "nowhere", "quote": "q", "applies": "2026"})
        with self.assertRaises(ValueError):
            rates.validate(bad)
        bad = copy.deepcopy(raw)
        bad["source"][0]["url"] = ""
        with self.assertRaises(ValueError):
            rates.validate(bad)

    def test_lines_carry_evidence(self):
        d = {"grams": drv("grams", 50, "g", "simulated"), "hours": drv("hours", 2.5, "h", "simulated"),
             "volume_mm3": drv("v", 1, "mm³", "computed"), "material_key": "PLA"}
        for ln in models.fdm(d, R())["lines"]:
            self.assertTrue(ln["evidence"])
            for i in ln["inputs"]:
                self.assertIn(i["evidence"], ("sourced", "specified", "assumed", "simulated", "computed", "missing"))
                if i["evidence"] == "sourced":
                    self.assertTrue(i.get("source") and i.get("quote"))


CUP = '''
from build123d import Box, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Tray"
    params = [Param("wall", "Wall", 2.0, 0.8, 6, 0.1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        w = v["wall"]
        return Box(80, 60, 30) - Pos(0, 0, w) * Box(80 - 2 * w, 60 - 2 * w, 30)
'''


class Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        cls.p = cls.st.create_design("Tray", CUP, purpose="model")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_compare(self):
        r = costing.compare(self.st, self.p, None, [1, 10, 100, 1000, 10000])
        self.assertEqual(set(r["processes"]), {"fdm", "sla", "sls", "mjf", "lpbf", "cnc", "injection"})
        for pr, x in r["processes"].items():
            self.assertNotIn("error", x, pr)
        inj = r["processes"]["injection"]
        self.assertEqual(inj["drivers"]["projected_mm2"]["evidence"], "computed (B-rep)")
        self.assertAlmostEqual(inj["drivers"]["projected_mm2"]["value"], 80 * 60, delta=80 * 60 * 0.01)
        self.assertAlmostEqual(inj["drivers"]["wall_max_mm"]["value"], 2.0, 3)
        self.assertEqual(r["processes"]["cnc"]["drivers"]["setups"]["evidence"], "computed (manufacturability, B-rep)")
        self.assertEqual(r["processes"]["fdm"]["drivers"]["grams"]["evidence"], "estimated")      # not sliced
        self.assertEqual(r["cheapest"][-1]["process"], "injection")
        sw = r["switches"]
        self.assertTrue(sw and sw[-1]["cheaper_above"] == "injection")
        # the switch is where the two curves meet
        a, b = r["processes"][sw[-1]["than"]]["totals"], inj["totals"]
        q = sw[-1]["quantity"]
        self.assertAlmostEqual(a["fixed"] / q + a["per_part_variable"], b["fixed"] / q + b["per_part_variable"], 3)
        self.assertIn("costs less per part than", costing.headline(r))
        json.dumps(costing.brief(r))

    def test_cost_callable(self):
        c = costing.cost(self.st, self.p, "injection", 10000)
        r = costing.estimate(self.st, self.p, "injection", [10000])
        self.assertAlmostEqual(c, r["totals"]["curve"][0]["per_part"])
        self.assertIsNone(costing.cost(self.st, self.p, "mjf", 10))           # a line not counted: no number
        f = costing.objective("auto", 1)
        self.assertAlmostEqual(f(self.st, self.p), costing.compare(self.st, self.p, None, [1])["cheapest"][0]["per_part"])

    def test_options(self):
        r1 = costing.estimate(self.st, self.p, "injection", [1000], {"injection": {"cavities": 2}})
        self.assertEqual(r1["cavities"], 2)
        self.assertEqual(costing.estimate(self.st, self.p, "injection", [1], {"injection": {"resin": "PC"}})["resin"], "PC")
        with self.assertRaises(StudioError):
            costing.estimate(self.st, self.p, "welding")

    def test_sheet_not_a_sheet_part(self):
        r = costing.estimate(self.st, self.p, "sheet_metal", [1])
        self.assertFalse(r["totals"]["complete"])


class Interfaces(unittest.TestCase):
    def test_mcp(self):
        from form import mcp_server
        st = mcp_server.studio()                     # the server's own Studio (its data folder, whichever test set it)
        p = st.create_design("Block", CUP.replace('"Tray"', '"Block"'), purpose="model")

        async def go():
            srv = mcp_server.build()
            r = await srv.call_tool("cost_compare", {"project": p["id"], "quantities": [1, 1000]})
            out = r.structuredContent if getattr(r, "structuredContent", None) else json.loads(r.content[0].text)
            out = out.get("result", out)
            self.assertIn("switches", out)
            r = await srv.call_tool("estimate_cost", {"project": p["id"], "process": "cnc", "quantities": [5]})
            out = r.structuredContent if getattr(r, "structuredContent", None) else json.loads(r.content[0].text)
            out = out.get("result", out)
            self.assertEqual(out["process"], "cnc")
            r = await srv.call_tool("cost_rates", {"action": "list"})
            out = r.structuredContent if getattr(r, "structuredContent", None) else json.loads(r.content[0].text)
            out = out.get("result", out)
            self.assertTrue(any(x["id"] == "labour" for x in out["rates"]))
        asyncio.run(go())

    def test_cli(self):
        env = {**os.environ, "FORM_DATA": tempfile.mkdtemp(prefix="form-costing-cli-"), "PYTHONPATH": str(ROOT)}
        out = subprocess.run([sys.executable, "-m", "form", "cost", "rates", "--shop", "a", "--rate", "labour=50", "--use"],
                             capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        d = json.loads(out.stdout)
        self.assertEqual(d["active"], "a")
        self.assertEqual(next(r for r in d["rates"] if r["id"] == "labour")["evidence"], "specified")


if __name__ == "__main__":
    unittest.main()
