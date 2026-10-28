"""P5 (ADR 045 d): does the forecast survive investable prices?

The research panel values UST10 from monthly *average* yields (GS10) and energy / base metals from World
Bank monthly *averages*. Averages smooth and shift: a trend read from an average is not the trend of a
price anyone can trade (ADR 042). This script re-runs the pieces on tradable month-end prices from the
live store (data/raw/p5_live_monthend.csv.gz, extracted by p5_extract_live_monthend.py):

  A. UST10 from month-end DGS10 (same par-bond formula) instead of monthly-average GS10: return
     statistics, agreement with IEF (2002+), and the forecast's IC with the one replaced by the other
  B. energy / base metals: the 10-month trend label from World Bank averages against the label from
     futures (CL=F, HG=F) and ETFs (USO, DBC, CPER): agreement and the trend's forward hit rate on the
     tradable return
  C. gold / silver (LBMA month-end) and US_EQ (French) against GC=F, SI=F, GLD, SLV, SPY: plausibility

Everything ends 2018-12 (holdout untouched). Writes output/forecast/INVESTABILITY.md.

Aufruf: python scripts/forecast_investability.py
"""

from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.config.models import ForecastUniverseConfig, load_bundle  # noqa: E402
from rotationlab.core.types import Frequency, SeriesId, SeriesKind, SeriesSpec  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.data.catalog import build_catalog  # noqa: E402
from rotationlab.data.providers.static import bond_total_return  # noqa: E402
from rotationlab.data.view import StoreViewFactory, asset_roles  # noqa: E402
from rotationlab.engine.modes import averaged_assets  # noqa: E402
from rotationlab.forecast.evaluation import (  # noqa: E402
    assert_outside_holdout,
    mean_ci,
    spearman_rows,
    top_bottom,
    trend_label,
    trend_table,
    window,
)
from rotationlab.forecast.model import (  # noqa: E402
    BlockBootstrap,
    ForecastModel,
    complete_months,
    composite,
    feature_panel,
    forward_returns,
    ranks_of,
    relative,
)

OUT = os.path.join(ROOT, "output", "forecast")
SNAP = os.path.join(ROOT, "data", "raw", "p5_live_monthend.csv.gz")
END = pd.Timestamp("2018-12-31")
CONF = 0.90


def md(df: pd.DataFrame, fmt: str = "{:.4f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join([df.index.name or "", *map(str, cols)]) + " |", "|" + "---|" * (len(cols) + 1)]
    for i, row in df.iterrows():
        lines.append(
            "| "
            + " | ".join([str(i), *[fmt.format(v) if isinstance(v, float) else str(v) for v in row]])
            + " |"
        )
    return "\n".join(lines)


def main() -> None:  # noqa: PLR0915
    os.makedirs(OUT, exist_ok=True)
    b = load_bundle(os.path.join(ROOT, "configs"))
    fc = b.forecast
    assert fc is not None
    cal = make_calendar(b)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    snap = pd.read_csv(SNAP, index_col=0, parse_dates=True).loc[:END]
    boot = BlockBootstrap(fc.calibration.draws, fc.calibration.block_months, fc.calibration.seed)
    lines = [
        "# Investierbarkeit (P5): hält die Prognose mit handelbaren Preisen?",
        "",
        f"Stand {date.today().isoformat()}. Live-Daten: `data/raw/p5_live_monthend.csv.gz` (Monatsend-Schnitt des Live-Stores, Branch `data`, Stand 2026-10-26). Alles bis 2018-12.",
        "",
    ]

    # ---- A. UST10: average yield vs month-end yield --------------------------------------------------
    research = obs[obs["series_id"] == "static:UST10"].sort_values("obs_date")
    ust_avg = pd.Series(research["value"].to_numpy(float), index=pd.DatetimeIndex(research["obs_date"])).loc[
        :END
    ]
    dgs = snap["DGS10_ME"].dropna()
    r_me = bond_total_return(dgs, 10.0).dropna()
    ust_me = (100.0 * (1 + r_me).cumprod()).loc[:END]
    r_avg = ust_avg.pct_change().dropna()
    both = r_me.index.intersection(r_avg.index)
    both = both[(both >= pd.Timestamp("1973-01-31"))]
    ra, rm = r_avg.reindex(both), r_me.reindex(both)
    ief = snap["IEF_TR"].pct_change().dropna()
    tlt = snap["TLT_TR"].pct_change().dropna()
    stats = pd.DataFrame(
        {
            "UST10 (GS10-Mittel, Forschung)": {
                "ann_return": ra.mean() * 12,
                "ann_vol": ra.std() * np.sqrt(12),
                "autocorr_1": ra.autocorr(1),
            },
            "UST10 (DGS10-Monatsende)": {
                "ann_return": rm.mean() * 12,
                "ann_vol": rm.std() * np.sqrt(12),
                "autocorr_1": rm.autocorr(1),
            },
        }
    ).T
    stats.index.name = "Reihe 1973–2018"
    corr_avg_me = float(ra.corr(rm))
    c_ief = {
        k: float(v.reindex(ief.index).corr(ief))
        for k, v in (("GS10-Mittel", r_avg), ("DGS10-Monatsende", r_me))
    }
    c_tlt = {
        k: float(v.reindex(tlt.index).corr(tlt))
        for k, v in (("GS10-Mittel", r_avg), ("DGS10-Monatsende", r_me))
    }
    vol_ief = {
        "IEF": float(ief.std() * np.sqrt(12)),
        "TLT": float(tlt.std() * np.sqrt(12)),
        "UST10 Mittel (2002–18)": float(r_avg.reindex(ief.index).std() * np.sqrt(12)),
        "UST10 Monatsende (2002–18)": float(r_me.reindex(ief.index).std() * np.sqrt(12)),
    }
    lines += [
        "## A. UST10: Monatsmittel der Rendite (GS10) gegen Monatsend-Rendite (DGS10)",
        "",
        "Beide Indizes nutzen dieselbe Par-Bond-Formel (Swinkels 2019); nur die Rendite-Reihe unterscheidet sich.",
        "",
        md(stats),
        "",
        f"- Korrelation der Monatsrenditen Mittel vs. Monatsende 1973–2018: **{corr_avg_me:.3f}**",
        f"- Korrelation mit IEF (7–10 J., 2002–2018): Mittel {c_ief['GS10-Mittel']:.3f}, Monatsende **{c_ief['DGS10-Monatsende']:.3f}**; mit TLT (20+ J.): Mittel {c_tlt['GS10-Mittel']:.3f}, Monatsende {c_tlt['DGS10-Monatsende']:.3f}",
        f"- Volatilität p.a. 2002–2018: " + ", ".join(f"{k} {v:.3%}" for k, v in vol_ief.items()),
        "",
    ]

    # the forecast with UST10 replaced: synthetic series in a view factory, same model, same window
    sid = "p5:UST10_ME:tr"
    syn = pd.DataFrame(
        {
            "series_id": sid,
            "obs_date": ust_me.index,
            "vintage_date": ust_me.index,
            "value": ust_me.to_numpy(),
            "ingested_at": "p5",
        }
    )
    cat = dict(build_catalog(b))
    cat[sid] = SeriesSpec(SeriesId(sid), "static", "p5:UST10_ME", SeriesKind.TOTAL_RETURN, Frequency.MONTHLY)
    roles = asset_roles(b.universe)
    roles["UST10_ME"] = {"total_return": [sid]}
    first = pd.Timestamp("1972-12-01")
    obs_all = pd.concat([obs[pd.to_datetime(obs["obs_date"]) >= first], syn], ignore_index=True)
    fac = StoreViewFactory(obs_all, cat, roles, cal, chains=b.series.chains)
    u0 = fc.universe["long_history"]
    ranked_me = [("UST10_ME" if a == "UST10" else a) for a in u0.ranked]
    cfg_me = fc.model_copy(
        update={
            "universe": {
                "long_history": ForecastUniverseConfig(
                    ranked=ranked_me, trend_only=list(u0.trend_only), cash=u0.cash
                )
            }
        }
    )
    model0 = ForecastModel(fc, averaged=averaged_assets(b))
    model1 = ForecastModel(cfg_me, averaged=averaged_assets(b))
    first_d, last_d = window(fc, 1)
    end_view = fac.at((last_d + pd.offsets.MonthEnd(1)).date())
    assert end_view.date < fc.holdout.start
    rows = []
    ic_series = {}
    for label, model in (("Forschung (GS10-Mittel)", model0), ("Monatsende (DGS10)", model1)):
        feats = {k: feature_panel(end_view, k, model.ranked) for k in model.weights}
        sc = composite(feats, model.weights, model.clip).reindex(columns=model.ranked)
        sc = sc[(sc.index >= pd.Timestamp(first_d)) & (sc.index <= pd.Timestamp(last_d))]
        assert_outside_holdout(sc.index, fc, 1)
        lv = complete_months(
            end_view, end_view.total_return(model.ranked, "ME").reindex(columns=model.ranked)
        )
        rel = relative(forward_returns(lv, 1)).reindex(sc.index)
        ic = spearman_rows(sc, rel)
        tb = top_bottom(ranks_of(sc), rel)
        ic_series[label] = ic
        rows.append(
            {
                "Variante": label,
                "IC": mean_ci(ic, boot, CONF).mean,
                "IC low": mean_ci(ic, boot, CONF).low,
                "IC high": mean_ci(ic, boot, CONF).high,
                "Trefferquote": float(tb["hit"].dropna().mean()),
                "Monate": int(ic.notna().sum()),
            }
        )
        if label.startswith("Forschung"):
            ranks_a = ranks_of(sc)
        else:
            ranks_b = ranks_of(sc).rename(columns={"UST10_ME": "UST10"})
    d = mean_ci(ic_series["Monatsende (DGS10)"] - ic_series["Forschung (GS10-Mittel)"], boot, CONF)
    ok = ranks_a.notna().all(axis=1) & ranks_b.notna().all(axis=1)
    ra_, rb_ = ranks_a[ok].reindex(columns=ranks_b.columns), ranks_b[ok]
    same_rank = (ra_ == rb_).all(axis=1)
    same_top = ra_.idxmin(axis=1) == rb_.idxmin(axis=1)
    t = pd.DataFrame(rows).set_index("Variante")
    lines += [
        "Prognose mit UST10 aus Monatsend-Renditen statt Monatsmitteln (gleiches Modell, gleiche Stichprobe 1973–2018):",
        "",
        md(t),
        "",
        f"- gepaarte IC-Differenz Monatsende − Forschung: **{d.mean:+.4f}** [{d.low:+.4f}, {d.high:+.4f}]",
        f"- identische Rangfolge in {float(same_rank.mean()):.1%} der Monate, gleicher Rang 1 in {float(same_top.mean()):.1%}",
        "",
    ]

    # ---- B. energy / base metals: trend labels across price bases ---------------------------------
    lines += ["## B. Energie und Basismetalle: 10-Monats-Trend je Preisbasis", ""]
    wb = {}
    for a, sid_ in (
        ("WB_ENERGY", "static:WB_ENERGY"),
        ("WB_BASEMETALS", "static:WB_BASEMETALS"),
        ("WB_OIL", "static:WB_OIL"),
        ("WB_COPPER", "static:WB_COPPER"),
    ):
        s = obs[obs["series_id"] == sid_].sort_values("obs_date")
        wb[a] = pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["obs_date"])).loc[:END]
    groups = {
        "Energie": [
            ("WB_ENERGY (Mittel)", wb["WB_ENERGY"], True),
            ("WB_OIL (Mittel)", wb["WB_OIL"], True),
            ("CL=F Monatsende", snap["CL=F_CLOSE"], False),
            ("USO Monatsende", snap["USO_CLOSE"], False),
            ("DBC Monatsende", snap["DBC_CLOSE"], False),
        ],
        "Basismetalle": [
            ("WB_BASEMETALS (Mittel)", wb["WB_BASEMETALS"], True),
            ("WB_COPPER (Mittel)", wb["WB_COPPER"], True),
            ("HG=F Monatsende", snap["HG=F_CLOSE"], False),
            ("CPER Monatsende", snap["CPER_CLOSE"], False),
        ],
    }
    for g, items in groups.items():
        rows = []
        labels = {}
        for name, lvl, averaged in items:
            lvl = lvl.dropna().loc[:END]
            lab = trend_label(lvl)
            labels[name] = lab
            # honest forward return: averages one month later (decision 5), closes the next month
            fwd = (lvl.shift(-2) / lvl.shift(-1) - 1) if averaged else (lvl.shift(-1) / lvl - 1)
            rows.append(trend_table(lab, fwd, name, boot, CONF))
        t = pd.DataFrame(rows).set_index("basis")
        t.index.name = f"{g}: Basis"
        # agreement of labels with the World Bank index label on common months
        ref = labels[items[0][0]]
        agree = {}
        for name, lab in labels.items():
            common = ref.dropna().index.intersection(lab.dropna().index)
            agree[name] = (
                float((ref.reindex(common) == lab.reindex(common)).mean()),
                len(common),
                str(common.min().date()) if len(common) else "",
            )
        lines += [
            f"**{g}.** Trend = Niveau über seinem 10-Monats-Schnitt. Ziel: für Mittelwerte die Rendite Mittel(t+2)/Mittel(t+1) (Entscheid 5), für Monatsendkurse die Rendite t→t+1. `hit_up` = Anteil positiver Folgerenditen nach Trend „auf“, `hit_down` nach „ab“; `diff_pa` = Differenz der Mittel auf minus ab, p.a., mit 90-%-Block-Bootstrap-Intervall.",
            "",
            md(t, "{:.3f}"),
            "",
            "Übereinstimmung des Labels mit dem World-Bank-Index: "
            + "; ".join(
                f"{k} {v[0]:.1%} ({v[1]} Monate ab {v[2]})" for k, v in agree.items() if k != items[0][0]
            ),
            "",
        ]
        # the cross: WB label applied to the tradable return of the futures/ETF
        cross = []
        for name, lvl, averaged in items:
            if averaged:
                continue
            lvl = lvl.dropna().loc[:END]
            fwd = lvl.shift(-1) / lvl - 1
            cross.append(trend_table(ref.reindex(lvl.index), fwd, f"WB-Label → Rendite {name}", boot, CONF))
            cross.append(trend_table(labels[name], fwd, f"eigenes Label → Rendite {name}", boot, CONF))
        ct = pd.DataFrame(cross).set_index("basis")
        ct.index.name = f"{g}: Label → handelbare Rendite"
        lines += [md(ct, "{:.3f}"), ""]

    # ---- C. plausibility: gold / silver / US_EQ -----------------------------------------------------
    lines += ["## C. Plausibilität: Gold, Silber, US-Aktien", ""]
    pairs = []
    for a, sid_, cols in (
        ("GOLD", "static:GOLD", ["GC=F_CLOSE", "GLD_CLOSE"]),
        ("SILVER", "static:lbma:SILVER", ["SI=F_CLOSE", "SLV_CLOSE"]),
    ):
        s = obs[obs["series_id"] == sid_].sort_values("obs_date")
        lvl = pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["obs_date"])).loc[:END]
        if sid_ == "static:lbma:SILVER":
            lvl = lvl.resample("ME").last()
        r = lvl.pct_change()
        for c in cols:
            rc = snap[c].pct_change()
            common = r.dropna().index.intersection(rc.dropna().index)
            pairs.append(
                {
                    "Paar": f"{a} (Forschung) vs {c.replace('_CLOSE', '')}",
                    "Monate": len(common),
                    "ab": str(common.min().date()),
                    "Korrelation": float(r.reindex(common).corr(rc.reindex(common))),
                    "Vol-Verhältnis": float(rc.reindex(common).std() / r.reindex(common).std()),
                }
            )
    s = obs[obs["series_id"] == "static:FF_MKT"].sort_values("obs_date")
    ff = pd.Series(s["value"].to_numpy(float), index=pd.DatetimeIndex(s["obs_date"])).loc[:END]
    spy = snap["SPY_TR"].pct_change()
    common = ff.dropna().index.intersection(spy.dropna().index)
    pairs.append(
        {
            "Paar": "US_EQ (French Markt) vs SPY TR",
            "Monate": len(common),
            "ab": str(common.min().date()),
            "Korrelation": float(ff.reindex(common).corr(spy.reindex(common))),
            "Vol-Verhältnis": float(spy.reindex(common).std() / ff.reindex(common).std()),
        }
    )
    pt = pd.DataFrame(pairs).set_index("Paar")
    lines += [md(pt, "{:.3f}"), ""]

    with open(os.path.join(OUT, "INVESTABILITY.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
