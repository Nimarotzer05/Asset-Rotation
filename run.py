"""Schneller Backtest-Lauf: Daten → Features → Signal → Backtest → Kennzahlen.

python run.py                   # Langfrist-Panel 1973–2025 (offline, data/assets_monthly.csv)
python run.py --dataset etf     # ETF-Universum (nach scripts/collect_data.py, Internet)
python run.py --dataset synthetic   # Smoke-Test mit Zufallsdaten

Die vollständige Studie (Regime, Regressionen, ICs, Sensitivität, Report) liefert scripts/run_analysis.py.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

import config as C
from src import analysis, backtest, data, features, metrics, signals

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def build_strategy(params: dict, monthly: pd.DataFrame, regime: pd.DataFrame | None, cash_ret: pd.Series | None):
    """Eine Parametrisierung → Backtest-Ergebnis. Wird auch vom Walk-forward benutzt."""
    feats = features.asset_features(monthly)
    score = signals.composite_score(feats, params["weights"], regime.reindex(monthly.index) if regime is not None else None, params.get("tilts"))
    w = signals.build_weights(score, monthly, top_n=params["top_n"], trend_filter=params["trend_filter"])
    return backtest.run_backtest(w, monthly, cash_ret, cost_bps=C.TRANSACTION_COST_BPS), w


def load(dataset: str) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, str]:
    if dataset == "long":
        assets, macro = data.load_long_history()
        monthly = assets[list(C.LONG_UNIVERSE)].loc[C.LONG_START:]
        cash = assets[C.LONG_CASH].pct_change().loc[C.LONG_START:]
        return monthly, cash, macro, "long"
    if dataset == "etf":
        monthly_all, macro = data.load_etf_dataset()
        tickers = [t for t in C.UNIVERSE if t in monthly_all.columns]
        monthly = monthly_all[tickers].dropna(how="all")
        cash = monthly_all[C.CASH].pct_change() if C.CASH in monthly_all else pd.Series(0.0, index=monthly.index)
        return monthly, cash, macro, "etf"
    tickers = list(C.UNIVERSE)
    prices = data.synthetic_prices(tickers + [C.CASH], C.START)
    monthly_all = data.to_monthly(prices)
    return monthly_all[tickers], monthly_all[C.CASH].pct_change(), data.synthetic_macro(prices.index), "synthetic"


def main(dataset: str) -> None:
    monthly, cash, macro, tag = load(dataset)
    out = os.path.join(OUT, tag)
    os.makedirs(out, exist_ok=True)
    regime = features.macro_regime(macro).reindex(monthly.index).ffill()

    base = {"weights": C.FEATURE_WEIGHTS, "tilts": None, "top_n": C.TOP_N, "trend_filter": C.TREND_FILTER}
    bt, w = build_strategy(base, monthly, regime, cash)
    bt_reg, _ = build_strategy({**base, "tilts": C.REGIME_TILTS}, monthly, regime, cash)

    grid = [{**base, "top_n": n, "trend_filter": tf} for n in (2, 3, 4) for tf in (True, False)]
    min_train = 120 if tag == "long" else 60
    oos, chosen = backtest.walk_forward(lambda p, m: build_strategy(p, m, regime, cash)[0], monthly, grid,
                                        min_train_months=min_train, refit_every=12, cash_returns=cash)

    rets = monthly.pct_change()
    ew = rets.mean(axis=1)
    eq_col, bond_col = ("US_EQ", "UST10") if tag == "long" else ("SPY", "IEF")
    bal = 0.6 * rets[eq_col] + 0.4 * rets[bond_col] if eq_col in rets and bond_col in rets else ew
    start = bt["net"].first_valid_index()

    table = metrics.summary_table(
        {
            "Rotation (in-sample)": bt["net"],
            "Rotation + Regime-Tilts": bt_reg["net"],
            "Rotation walk-forward (OOS)": oos,
            "Equal Weight": ew.loc[start:],
            "60/40": bal.loc[start:],
        },
        {"Rotation (in-sample)": bt["turnover"], "Rotation + Regime-Tilts": bt_reg["turnover"]},
        cash=cash,
    )
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(f"\n=== Kennzahlen [{tag}] {start:%Y-%m} – {monthly.index.max():%Y-%m} ===")
    print(table.round(3))
    excess = rets.sub(cash, axis=0)
    print("\n=== Überschussrendite je Regime (ann., in-sample) ===")
    print(analysis.regime_pivot(analysis.returns_by_regime(excess, regime["regime"])).round(3))
    print("\n=== Walk-forward: gewählte Parameter (Anzahl Jahre) ===")
    print(chosen.groupby(["top_n", "trend_filter"]).size().to_string())

    table.to_csv(os.path.join(out, "summary.csv"))
    w.to_csv(os.path.join(out, "weights.csv"))
    eq = pd.DataFrame({"Rotation": bt["net"], "OOS": oos, "EW": ew, "60/40": bal}).loc[start:]
    eq.to_csv(os.path.join(out, "returns.csv"))

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ax = (1 + eq.fillna(0)).cumprod().plot(figsize=(10, 5), logy=True, title=f"Kumulierte Nettorendite (log) – {tag}")
        ax.set_ylabel("Wachstum von 1")
        plt.tight_layout()
        plt.savefig(os.path.join(out, "equity.png"), dpi=130)
        print(f"\nPlot gespeichert: {os.path.join(out, 'equity.png')}")
    except ImportError:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["long", "etf", "synthetic"], default="long")
    ap.add_argument("--synthetic", action="store_true", help="Kurzform für --dataset synthetic")
    args = ap.parse_args()
    main("synthetic" if args.synthetic else args.dataset)
