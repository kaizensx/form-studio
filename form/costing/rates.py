"""The rates the cost models use: the sourced table (rates.toml), the person's shops, and currency conversion.

A rate resolves to one of three evidence classes, and only these:

* ``sourced``: the table's number, with its source (publisher, URL, date read) and the quote that states it;
* ``specified``: the person's own number for the active shop (Settings > Costs, ``form cost rates --set``);
* ``assumed``: a process parameter no source states (a time, a build rate, a fraction). Money is never assumed: a
  price or an hourly rate without a source and without the person's number has no value, and the line that needs it
  is left out with what to set.

Money is converted to the shop's currency only with a stated rate: the person's (``fx``, specified) or the ECB
reference rate in the table (sourced). Without one the amount stays unconverted and the line says so.

Shops live in ``<data dir>/cost.json`` beside the print prices form/cost.py keeps there:
``{"shop": "default", "shops": {"default": {"label": ..., "currency": "EUR", "rates": {id: value}, "fx": {"USD": 1.1}}},
"part_prices": {designation: {"price": 0.12, "currency": "EUR", "date": ...}}}``.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import time
import tomllib
from pathlib import Path

TABLE = Path(__file__).with_name("rates.toml")
CURRENCIES = ("EUR", "USD", "GBP", "CHF", "JPY", "CNY", "CAD", "AUD", "SEK", "PLN", "CZK", "DKK", "NOK")
DEFAULT_SHOP = {"label": "Published rates", "currency": "EUR", "rates": {}, "fx": {}}


def _err(msg: str, hint: str = ""):
    from ..studio import StudioError
    return StudioError(msg, hint)


@functools.lru_cache(maxsize=1)
def table() -> dict:
    return validate(tomllib.loads(TABLE.read_text(encoding="utf-8")))


def validate(t: dict) -> dict:
    """Index a parsed table and refuse one that labels anything sourced without a source: a sourced rate names a
    known source with a URL and the date it was read, and quotes it; a rate with a value and no source says assumed;
    money (a price or an hourly rate) is never assumed."""
    t["sources_by_id"] = {s["id"]: s for s in t.get("source", [])}
    t["rates_by_id"] = {r["id"]: r for r in t.get("rate", [])}
    for s in t["sources_by_id"].values():
        if not (s.get("url", "").startswith(("http://", "https://")) and s.get("read") and s.get("title")):
            raise ValueError(f"source {s['id']} needs a title, a URL and the date it was read")
    for r in t["rates_by_id"].values():
        if r.get("source"):
            if r["source"] not in t["sources_by_id"]:
                raise ValueError(f"rate {r['id']} names an unknown source {r['source']}")
            if not r.get("quote") or not r.get("applies") or r.get("value") is None:
                raise ValueError(f"rate {r['id']} is sourced but has no value, quote or period it applies to")
            if r.get("assumed"):
                raise ValueError(f"rate {r['id']} cannot be both sourced and assumed")
        elif r.get("value") is not None and not r.get("assumed"):
            raise ValueError(f"rate {r['id']} has a value but neither a source nor assumed = true")
        if r.get("assumed") and money_unit(r["unit"]):
            raise ValueError(f"rate {r['id']} is money ({r['unit']}) and assumed: money is sourced or set by the person")
    for cur, fx in (t.get("fx") or {}).items():
        if fx.get("source") not in t["sources_by_id"] or not fx.get("quote"):
            raise ValueError(f"exchange rate {cur} needs a known source and its quote")
    return t


def digest() -> str:
    return hashlib.sha256(TABLE.read_bytes()).hexdigest()[:16]


def money_unit(unit: str) -> str | None:
    """The currency of a money unit ("EUR/h" -> "EUR", "USD" -> "USD"), else None."""
    head = str(unit or "").split("/")[0].strip()
    return head if head in CURRENCIES else None


def source_text(s: dict) -> str:
    bits = [s.get("publisher", ""), f"“{s.get('title', '')}”", s.get("url", "")]
    when = f"published {s['published']}, read {s.get('read', '')}" if s.get("published") else f"read {s.get('read', '')}"
    return ", ".join(b for b in bits if b) + f" ({when})"


# ---- shops (the person's numbers) -------------------------------------------------------------------------------

def _prefs_path(cfg: dict) -> Path:
    return Path(cfg["data"]["dir"]) / "cost.json"


def _read_all(cfg: dict) -> dict:
    try:
        got = json.loads(_prefs_path(cfg).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_all(cfg: dict, data: dict) -> None:
    from .. import fsutil
    path = _prefs_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    fsutil.replace(tmp, path)


def shops(cfg: dict) -> dict:
    """{"active": id, "shops": {id: shop}}; the default shop always exists (the published rates, in EUR)."""
    d = _read_all(cfg)
    out = {k: _clean_shop(v) for k, v in (d.get("shops") or {}).items() if isinstance(v, dict)}
    out.setdefault("default", dict(DEFAULT_SHOP))
    active = d.get("shop") if d.get("shop") in out else "default"
    return {"active": active, "shops": out, "part_prices": d.get("part_prices") or {}}


def _clean_shop(s: dict) -> dict:
    cur = str(s.get("currency") or "EUR").upper()
    return {"label": str(s.get("label") or "")[:60] or "Shop", "currency": cur if cur in CURRENCIES else "EUR",
            "rates": {str(k): float(v) for k, v in (s.get("rates") or {}).items() if _num(v) is not None},
            "fx": {str(k).upper(): float(v) for k, v in (s.get("fx") or {}).items() if _num(v) and float(v) > 0}}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def update_shop(cfg: dict, shop: str = "", label: str | None = None, currency: str | None = None,
                rates: dict | None = None, fx: dict | None = None, activate: bool = False, delete: bool = False,
                part_prices: dict | None = None) -> dict:
    """Change a shop (created when new): its label, currency, rate overrides (a value of None or "" forgets one, so
    the published rate applies again), exchange rates (units of that currency per 1 EUR, as the ECB quotes them)
    and the purchased parts' prices (in the shop's currency unless given). Returns shops()."""
    from .. import cost as _legacy
    t = table()
    sid = (shop or "").strip() or None
    with _legacy._lock:
        d = _read_all(cfg)
        all_ = d.setdefault("shops", {})
        if sid is None:
            sid = d.get("shop") if d.get("shop") in all_ else "default"
        if delete:
            if sid == "default":
                raise _err("The default shop cannot be deleted; clear its overrides instead.")
            all_.pop(sid, None)
            if d.get("shop") == sid:
                d["shop"] = "default"
        else:
            s = _clean_shop(all_.get(sid) or ({**DEFAULT_SHOP} if sid == "default" else {"label": sid}))
            if label is not None:
                s["label"] = str(label)[:60] or s["label"]
            if currency is not None:
                c = str(currency).upper().strip()
                if c not in CURRENCIES:
                    raise _err(f"Unknown currency “{currency}”.", "One of " + ", ".join(CURRENCIES) + ".")
                s["currency"] = c
            for k, v in (rates or {}).items():
                if k not in t["rates_by_id"] and not k.startswith(("fdm.material.", "cnc.stock.", "im.resin.",
                                                                   "sheet.material.", "lpbf.powder.")):
                    raise _err(f"Unknown rate “{k}”.", "form cost rates lists them.")
                if v in (None, ""):
                    s["rates"].pop(k, None)
                elif _num(v) is None:
                    raise _err(f"{k} must be a number, zero or more.")
                else:
                    s["rates"][k] = float(v)
            for k, v in (fx or {}).items():
                k = str(k).upper()
                if k not in CURRENCIES:
                    raise _err(f"Unknown currency “{k}”.")
                if v in (None, ""):
                    s["fx"].pop(k, None)
                elif not _num(v):
                    raise _err(f"The exchange rate for {k} must be a number above zero.")
                else:
                    s["fx"][k] = float(v)
            all_[sid] = s
            if activate:
                d["shop"] = sid
        for dsg, v in (part_prices or {}).items():
            pp = d.setdefault("part_prices", {})
            if v in (None, ""):
                pp.pop(dsg, None)
                continue
            if isinstance(v, dict):
                price, cur = _num(v.get("price")), str(v.get("currency") or "").upper()
            else:
                price, cur = _num(v), ""
            if price is None:
                raise _err(f"The price of {dsg} must be a number, zero or more.")
            pp[str(dsg)] = {"price": price, "currency": cur if cur in CURRENCIES else
                            _clean_shop(all_.get(d.get("shop") or "default") or DEFAULT_SHOP)["currency"],
                            "date": time.strftime("%Y-%m-%d"), "by": "person"}
        _write_all(cfg, d)
    return shops(cfg)


# ---- resolving a rate ---------------------------------------------------------------------------------------------

class Rates:
    """The rates of one shop in its currency. r = Rates(cfg); r.get("labour") -> a resolved rate (dict)."""

    def __init__(self, cfg: dict | None = None, shop: str | None = None, currency: str | None = None,
                 overrides: dict | None = None):
        self.t = table()
        sh = shops(cfg) if cfg else {"active": "default", "shops": {"default": dict(DEFAULT_SHOP)}, "part_prices": {}}
        self.shop_id = shop or sh["active"]
        if self.shop_id not in sh["shops"]:
            raise _err(f"No shop “{self.shop_id}”.", "Shops: " + ", ".join(sh["shops"]) + ".")
        self.shop = sh["shops"][self.shop_id]
        self.currency = (currency or self.shop["currency"]).upper()
        if self.currency not in CURRENCIES:
            raise _err(f"Unknown currency “{currency}”.")
        self.part_prices = sh["part_prices"]
        self.call = {str(k): v for k, v in (overrides or {}).items() if _num(v) is not None}
        self.used: dict = {}

    # exchange: units of currency per 1 EUR
    def _per_eur(self, cur: str):
        if cur == "EUR":
            return 1.0, {"evidence": "identity"}
        if cur in self.shop["fx"]:
            return self.shop["fx"][cur], {"evidence": "specified", "source": f"your rate for {cur} in shop “{self.shop['label']}”"}
        fx = (self.t.get("fx") or {}).get(cur)
        if fx:
            s = self.t["sources_by_id"][fx["source"]]
            return fx["per_eur"], {"evidence": "sourced", "source": source_text(s), "applies": fx["applies"],
                                   "quote": fx["quote"]}
        return None, None

    def fx(self, cur_from: str, cur_to: str | None = None):
        """Factor to multiply an amount in cur_from by to get cur_to, and how it is known (None when no rate)."""
        cur_to = cur_to or self.currency
        if cur_from == cur_to:
            return 1.0, None
        a, ea = self._per_eur(cur_from)
        b, eb = self._per_eur(cur_to)
        if a is None or b is None:
            return None, {"needs": f"an exchange rate between {cur_from} and {cur_to} (set it for your shop)"}
        how = [e for e in (ea, eb) if e and e.get("evidence") != "identity"]
        return b / a, {"rate": f"1 {cur_from} = {b / a:.6g} {cur_to}", "via": how,
                       "evidence": "specified" if any(e["evidence"] == "specified" for e in how) else "sourced"}

    def get(self, rid: str, default_unit: str = "") -> dict:
        """A rate in the shop's currency: {id, label, value, unit, evidence, source|why, quote, converted?, needs?}."""
        base = self.t["rates_by_id"].get(rid)
        unit = (base or {}).get("unit") or default_unit
        out = {"id": rid, "label": (base or {}).get("label", rid), "unit": unit}
        if rid in self.call:
            out.update(value=float(self.call[rid]), evidence="specified", source="given for this estimate")
            unit_cur = self.currency if money_unit(unit) else None
        elif rid in self.shop["rates"]:
            out.update(value=self.shop["rates"][rid], evidence="specified",
                       source=f"your rate in shop “{self.shop['label']}”")
            unit_cur = self.currency if money_unit(unit) else None      # the person's money is in the shop's currency
        elif base is not None and base.get("value") is not None:
            out["value"] = float(base["value"])
            if base.get("source"):
                s = self.t["sources_by_id"][base["source"]]
                out.update(evidence="sourced", source=source_text(s), url=s.get("url"), applies=base.get("applies"),
                           quote=base.get("quote"), **({"source_note": s["note"]} if s.get("note") else {}))
            else:
                out.update(evidence="assumed", why=base.get("why", ""))
            unit_cur = money_unit(unit)
        else:
            out.update(value=None, evidence="missing",
                       needs=(base or {}).get("why") or f"No published rate for {rid}: set your shop's.")
            unit_cur = None
        if out.get("value") is not None and unit_cur and unit_cur != self.currency:
            f, how = self.fx(unit_cur)
            if f is None:
                out.update(value_original=out["value"], currency_original=unit_cur, value=None,
                           needs=how["needs"], evidence=out["evidence"])
            else:
                out.update(value_original=out["value"], currency_original=unit_cur, value=out["value"] * f,
                           converted=how)
        if money_unit(unit):
            out["unit"] = unit.replace(money_unit(unit), self.currency, 1)
        self.used[rid] = out
        return out

    def material(self, prefix: str, key: str | None) -> dict:
        """A material price (prefix "fdm.material." + "PLA"): the person's, else the table's, else missing."""
        rid = prefix + (key or "")
        r = self.get(rid, default_unit="EUR/kg")
        if r["value"] is None and not r.get("currency_original"):
            r["needs"] = f"No published price for {key or 'this material'} here: set {rid} for your shop."
        return r

    def part_price(self, designation: str) -> dict:
        got = self.part_prices.get(designation)
        if not got:
            return {"id": f"part:{designation}", "value": None, "evidence": "missing",
                    "needs": f"Set a price for {designation} (only prices you give are used)."}
        out = {"id": f"part:{designation}", "value": got["price"], "evidence": "specified",
               "source": f"your price, {got.get('date', '')}", "unit": f"{got.get('currency', self.currency)}/each"}
        cur = got.get("currency") or self.currency
        if cur != self.currency:
            f, how = self.fx(cur)
            out.update(value_original=got["price"], currency_original=cur, value=None if f is None else got["price"] * f,
                       **({"needs": how["needs"]} if f is None else {"converted": how}))
        out["unit"] = f"{self.currency}/each"
        return out


def listing(cfg: dict, shop: str | None = None) -> dict:
    """Every rate as the shop resolves it, with the published value beside the shop's own."""
    r = Rates(cfg, shop)
    t = table()
    rows = []
    for rid, base in t["rates_by_id"].items():
        x = r.get(rid)
        rows.append({**x, "published": base.get("value"), "published_unit": base.get("unit"),
                     "overridden": rid in r.shop["rates"]})
    extra = [k for k in r.shop["rates"] if k not in t["rates_by_id"]]
    for rid in extra:
        rows.append({**r.get(rid, "EUR/kg"), "published": None, "overridden": True})
    sh = shops(cfg)
    return {"shop": r.shop_id, "label": r.shop["label"], "currency": r.currency, "shops": {k: v["label"] for k, v in sh["shops"].items()},
            "active": sh["active"], "fx": {**{k: {"per_eur": v["per_eur"], "evidence": "sourced", "applies": v["applies"],
                                                 "source": source_text(t["sources_by_id"][v["source"]])}
                                             for k, v in (t.get("fx") or {}).items()},
                                          **{k: {"per_eur": v, "evidence": "specified"} for k, v in r.shop["fx"].items()}},
            "rates": rows, "part_prices": sh["part_prices"], "table": str(TABLE), "table_digest": digest(),
            "sources": [{**s, "text": source_text(s)} for s in t.get("source", [])],
            "rule": "Every rate is sourced (published, cited and dated), specified (yours) or assumed (a process "
                    "parameter no source states). Money is never assumed."}
