"""Feature layer (docs/ARCHITECTURE.md §4): pure, registered functions `MarketView -> numbers`.

Importing this package registers every feature. Each one is defined by its panel formula (`_define.py`):
the pointwise value at D is the D-row of the same computation on the as-of panel, and every feature passes
the look-ahead harness (tests/lookahead) before a strategy may read it through the registry.

    price          mom_3_1 mom_6_1 mom_12_1 mom_12 trend_10m vol_12m inv_vol_12m drawdown excess_mom_12m
    equity         cape excess_cape_yield ecy_percentile
    macro          growth_dir inflation_dir quadrant commodity_state sahm d_real_yield_3m d_log_usd_3m
                   d_cpi_yoy_3m credit_spread d_credit_3m d_curve_3m d_fedfunds_3m tips_real_10y breakeven_10y
    risk_appetite  risk_appetite risk_appetite_pct
    ratio          gs_ratio gs_ratio_z60 gs_ratio_z120 gs_ratio_mom12 gs_hedge_ratio
    positioning    cot_spec_net_z
"""

from rotationlab.features import equity, macro, positioning, price, ratio, risk_appetite
from rotationlab.features._define import feature

__all__ = ["equity", "feature", "macro", "positioning", "price", "ratio", "risk_appetite"]
