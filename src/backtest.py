"""Backtest-Engine: Gewichte zum Monatsende t werden im Monat t+1 gehalten."""
from __future__ import annotations

import numpy as np
import pandas as pd


def run_backtest(
    weights: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    cash_returns: pd.Series | None = None,
    cost_bps: float = 15.0,
) -> pd.DataFrame:
    """Gibt DataFrame mit gross, cost, net, turnover zurück (monatlich)."""
    rets = monthly_prices.pct_change()
    if cash_returns is None:
        cash_returns = pd.Series(0.0, index=rets.index)
    rets = rets.copy()
    rets["CASH"] = cash_returns.reindex(rets.index).fillna(0.0)

    # Gewichte von t gelten für Rendite von t+1 → shift(1)
    w_held = weights.shift(1).reindex(rets.index).fillna(0.0)
    gross = (w_held * rets[w_held.columns]).sum(axis=1)

    # Turnover: Summe absoluter Gewichtsänderungen (einseitig)
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0) / 2
    cost = turnover.shift(1).reindex(rets.index).fillna(0.0) * cost_bps / 1e4
    net = gross - cost
    out = pd.DataFrame({"gross": gross, "cost": cost, "net": net, "turnover": turnover.reindex(rets.index)})
    return out.dropna(subset=["net"])


def benchmark_equal_weight(monthly_prices: pd.DataFrame) -> pd.Series:
    return monthly_prices.pct_change().mean(axis=1)


def benchmark_60_40(monthly_prices: pd.DataFrame, eq: str = "SPY", bond: str = "IEF") -> pd.Series:
    r = monthly_prices.pct_change()
    return 0.6 * r[eq] + 0.4 * r[bond]


def walk_forward(
    build_fn,
    monthly_prices: pd.DataFrame,
    param_grid: list[dict],
    min_train_months: int = 60,
    refit_every: int = 12,
    cash_returns: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Expanding-Window Walk-forward.

    build_fn(params, prices_until_t) → DataFrame von run_backtest (mit 'net').
    Alle refit_every Monate wird auf den bisherigen Daten der beste Parametersatz
    (höchster Sharpe der Überschussrendite über Cash, falls cash_returns gegeben)
    gewählt und für die nächsten refit_every Monate angewendet.
    Gibt (OOS-Nettorenditen, Tabelle der gewählten Parameter) zurück.
    """
    from .metrics import sharpe

    idx = monthly_prices.index
    oos = pd.Series(dtype=float)
    chosen = []
    t = min_train_months
    while t < len(idx):
        train = monthly_prices.iloc[:t]
        best, best_val = None, -np.inf
        for params in param_grid:
            bt = build_fn(params, train)
            net = bt["net"]
            if cash_returns is not None:
                net = net - cash_returns.reindex(net.index).fillna(0)
            val = sharpe(net)
            if val > best_val:
                best, best_val = params, val
        # Anwenden auf das nächste Fenster (mit voller Historie, damit Features berechenbar)
        end = min(t + refit_every, len(idx))
        full = build_fn(best, monthly_prices.iloc[:end])
        seg = full["net"].loc[idx[t]:idx[end - 1]]
        oos = pd.concat([oos, seg])
        chosen.append({"from": idx[t], "to": idx[end - 1], **best, "train_sharpe": best_val})
        t = end
    return oos, pd.DataFrame(chosen)
