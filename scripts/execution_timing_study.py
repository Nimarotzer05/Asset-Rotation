"""What does the execution timing cost? Every module's golden run under the three execution conventions.

    same_close        trade at the decision close (research convention, the goldens)
    next_close        trade at the next session's close (production, ADR 011)
    next_tradable     next session for assets with closing prices, next decision date for assets valued at
                      monthly averages (World Bank commodities): the honest timing of the research universe
    next_month_close  every asset at the next decision date: a full month of delay (pessimistic bound)

Writes output/execution/TIMING.md + timing.csv. Context: second look-ahead review, finding D
(docs/AUDIT_phase2_lookahead.md).

Aufruf: python scripts/execution_timing_study.py
"""

from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rotationlab.config.models import load_bundle  # noqa: E402
from rotationlab.data import make_calendar, open_store  # noqa: E402
from rotationlab.engine.modes import golden, walkforward_golden  # noqa: E402

OUT = os.path.join(ROOT, "output", "execution")
MODES = ("same_close", "next_close", "next_tradable", "next_month_close")


def averaged_share(bundle, sid: str) -> str:
    """How many traded assets of the long-history universe are valued at monthly averages (price_basis)."""
    assets = bundle.universe.assets
    uni = [a for a in bundle.strategies[sid].long_history_universe if assets[a].asset_class != "cash"]
    avg = [a for a in uni if assets[a].price_basis == "monthly_average"]
    return f"{len(avg)}/{len(uni)}"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    b = load_bundle(os.path.join(ROOT, "configs"))
    cal = make_calendar(b)
    obs = open_store(b, ROOT).observations()
    obs = obs[obs["series_id"].str.startswith("static:")]
    rows = []
    for sid in b.strategies:
        r = {"Modul": sid, "Mittelwert-Assets": averaged_share(b, sid)}
        for m in MODES:
            rep = golden(b, obs, sid, cal, m)
            r[m] = rep.measured["sharpe_ex_cash"]
            r[f"{m} p.a."] = rep.measured.get("ann_return", float("nan"))
        r["Forschung"] = b.strategies[sid].golden.get("sharpe_ex_cash", float("nan"))
        rows.append(r)
        print(sid, {m: round(r[m], 4) for m in MODES})
    sid = "multi_asset_rotation"
    r = {"Modul": f"{sid} (walk-forward OOS)", "Mittelwert-Assets": averaged_share(b, sid)}
    for m in MODES:
        rep = walkforward_golden(b, obs, sid, cal, m)
        r[m] = rep.measured["sharpe_ex_cash"]
        r[f"{m} p.a."] = rep.measured.get("ann_return", float("nan"))
    r["Forschung"] = b.strategies[sid].walkforward.golden.get("sharpe_ex_cash", float("nan"))
    rows.append(r)
    print(r["Modul"], {m: round(r[m], 4) for m in MODES})
    t = pd.DataFrame(rows).set_index("Modul")
    t["Δ ehrlich vs Studie"] = t["next_tradable"] - t["same_close"]
    t.to_csv(os.path.join(OUT, "timing.csv"))
    head = (
        "| Modul | Mittelwert-Assets | Forschung | same_close | next_close | **next_tradable** | next_month_close"
        " | Δ next_tradable − same_close |"
    )
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    for i, x in t.iterrows():
        lines.append(
            f"| {i} | {x['Mittelwert-Assets']} | {x['Forschung']:.4f} | {x['same_close']:.4f} | {x['next_close']:.4f} "
            f"| **{x['next_tradable']:.4f}** | {x['next_month_close']:.4f} | {x['Δ ehrlich vs Studie']:+.4f} |"
        )
    text = "\n".join(
        [
            "# Ausführungszeitpunkt: was kostet ehrliches Timing?",
            "",
            "Golden-Läufe aller Module (Forschungspanel, Stichprobe und Kosten wie im Golden), Sharpe ex Cash, unter vier",
            "Konventionen: `same_close` = Umsetzung zum Entscheidungsschluss (Studien), `next_close` = Folgetag (Produktion,",
            "ADR 011), `next_tradable` = Folgetag für Assets mit Schlusskursen, nächstes Entscheidungsdatum für Assets zu",
            "Monatsmitteln (ADR 042, die ehrliche Zahl), `next_month_close` = alles einen Monat später (pessimistische",
            "Schranke). „Mittelwert-Assets“ = gehandelte Assets des Langfrist-Universums mit `price_basis: monthly_average`.",
            "",
            *lines,
            "",
            "Lesart: Für Monatsmittel ist `next_close` rechnerisch gleich `same_close` (derselbe Mittelwert); erst ein Kauf",
            "im Folgemonat nutzt einen Preis, dessen Mittelungsfenster nach der Entscheidung liegt. Ein Signal aus einem",
            "Monatsmittel, umgesetzt zum selben Mittel, erntet die künstliche Autokorrelation gemittelter Reihen (Working",
            "1960): im Aufwärtstrend liegt das Mittel unter dem Monatsendkurs. Wo `next_tradable` von `same_close`",
            "abweicht, misst die Differenz genau diesen Effekt; Module ohne Mittelwert-Assets bleiben unverändert.",
            "",
            "Walk-forward: `next_tradable` (0.69) liegt unter `next_month_close` (0.72). Zwei Gründe: Bei einem Wechsel von",
            "einem Mittelwert-Asset in ein Asset mit Schlusskurs wird das neue sofort gekauft, das alte erst einen Monat später",
            "verkauft; die Überlappung ist in Cash finanziert (Brutto bis 2) und verstärkt in diesem Monat Gewinn wie Verlust.",
            "Und die Kandidatenwahl beruht auf Schattenrenditen in der Studienkonvention (ADR 039), nicht auf dem Timing des",
            "Laufs. Die Spanne 0.69–0.72 statt 0.77 ist die ehrliche Aussage.",
        ]
    )
    with open(os.path.join(OUT, "TIMING.md"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(t.to_string(float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
