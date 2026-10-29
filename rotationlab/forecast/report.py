"""The monthly forecast report (step P6): one Markdown page per decision month.

Ranking with probability, score, expected relative return and band, trend; the trend-only classes; the
3- and 6-month side forecasts; the track record so far; the last settled month. The status is descriptive
(ADR 045 c) and is labelled as such. No number in the report is computed here: everything comes from the
journal and the forecast objects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from rotationlab.forecast.journal import Outcome
from rotationlab.forecast.model import ForecastModel
from rotationlab.forecast.types import Forecast

STATUS_TEXT = {
    "signal": "mindestens eine Wahrscheinlichkeit weicht um mehr als die Marge von 50 % ab",
    "no_clear_signal": "alle Wahrscheinlichkeiten liegen innerhalb der Marge um 50 %",
    "warmup": "noch nicht genug Geschichte für Rangfolge oder Wahrscheinlichkeiten",
}


EVIDENCE_R1 = (
    "Die Rangfolge ist der im Backtest geprüfte Teil (`output/forecast/EVALUATION.md`, in-sample 1973–2018); im "
    "Pseudo-Holdout 2019–2025 hat sie sich **nicht** repliziert (`output/forecast/HOLDOUT.md`); "
)
EVIDENCE_FED = (
    "Rangfolge = Komposit von Runde 1 plus Fed-Kategorie (Zinsentscheide, realer Leitzins, Inflation, Arbeitsmarkt, "
    "Zinskurve; ADR 063); geprüft in Runde 5 (`output/forecast_fed/ROUND5.md`); zweite Liveprognose neben Runde 1; "
)


def _pct(x: float | None, digits: int = 0) -> str:
    return "–" if x is None else f"{x * 100:.{digits}f} %"


def _num(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:+.{digits}f}"


def _band(c: Any) -> str:
    if c.expected is None or c.band is None:
        return "–"
    return f"{c.expected * 100:+.2f} % [{c.band[0] * 100:+.2f}, {c.band[1] * 100:+.2f}]"


def _trend(c: Any) -> str:
    if c.trend is None:
        return "–"
    arrow = "auf ▲" if c.trend == "up" else "ab ▼"
    return f"{arrow} ({c.trend_value * 100:+.1f} % zum 10M-Schnitt)" if c.trend_value is not None else arrow


def ranking_table(f: Forecast) -> list[str]:
    ranked = sorted((c for c in f.classes if c.ranked), key=lambda c: (c.rank is None, c.rank or 0, c.asset))
    with_w = f.weights is not None
    head = (
        "| Rang | Klasse | P(obere Hälfte) | Score | Mittel des Rangs bisher [90-%-KI des Mittels] | Trend |"
    )
    sep = "|---|---|---|---|---|---|"
    if with_w:
        head += " Gewicht (Paper-Regel) |"
        sep += "---|"
    lines = [head, sep]
    for c in ranked:
        row = f"| {c.rank if c.rank is not None else '–'} | {c.asset} | {_pct(c.probability)} | {_num(c.score)} | {_band(c)} | {_trend(c)} |"
        if with_w:
            row += f" {_pct(float((f.weights or {}).get(c.asset, 0.0)))} |"
        lines.append(row)
    if with_w:
        invested = sum(float(v) for v in (f.weights or {}).values())
        lines.append(f"| – | Cash | | | | | {_pct(1.0 - invested)} |")
    return lines


def trend_table(f: Forecast) -> list[str]:
    rows = [c for c in f.classes if not c.ranked]
    if not rows:
        return []
    lines = ["| Klasse | Trend |", "|---|---|"]
    lines += [f"| {c.asset} | {_trend(c)} |" for c in rows]
    return lines


def track_lines(tracks: Mapping[int, Mapping[str, Any]]) -> list[str]:
    lines = [
        "| Horizont | abgerechnet | Rang-IC (Mittel) | IC > 0 | Rang 1 schlägt letzten | Brier (Modell / 0.5) | Vormonatsrang-IC |",
        "|---|---|---|---|---|---|---|",
    ]
    excluded = {h: int(t.get("backfilled", 0)) for h, t in tracks.items() if t.get("backfilled")}
    for h, t in sorted(tracks.items()):
        if t.get("n", 0) == 0:
            lines.append(f"| {h} M | 0 | – | – | – | – | – |")
            continue
        ic = f"{t['ic_mean']:+.3f}"
        if "ic_low" in t:
            ic += f" [{t['ic_low']:+.3f}, {t['ic_high']:+.3f}]"
        lines.append(
            f"| {h} M | {t['n']} | {ic} | {_pct(t['ic_share_positive'])} | {_pct(t['hit_rate'])} | {t['brier']:.4f} / {t['brier_const']:.4f} | {t['ic_prev_month']:+.3f} |"
        )
    if excluded:
        lines += [
            "",
            "Nicht in der Bilanz (nachgeholt, ADR 050 – mehr als "
            "die erlaubte Frist nach dem Entscheidungsdatum geschrieben): "
            + ", ".join(f"{h} M: {n}" for h, n in sorted(excluded.items())),
        ]
    t1 = tracks.get(1, {})
    if t1.get("paper_n"):
        lines += [
            "",
            f"Paper-Regel (ADR 048; Monatsende zu Monatsende, vor Kosten; historisch **nicht belegt** gegen Equal Weight, "
            f"`output/forecast/PORTFOLIO.md`, im Pseudo-Holdout 2019–2025 dahinter, `HOLDOUT.md`): {t1['paper_n']} Monate, "
            f"kumuliert Regel {_pct(t1['paper_cum'], 2)} "
            f"gegen Equal Weight {_pct(t1['ew_cum'], 2)}; mittlere Monatsdifferenz {_pct(t1['paper_excess_mean'], 2)}.",
        ]
    th = tracks.get(1, {}).get("trend_hit", {})
    if th:
        n = tracks[1].get("trend_n", {})
        lines += [
            "",
            "Trend-Klassen (1 M, Anteil der Monate, in denen die eigene Rendite das Vorzeichen des Trends hatte): "
            + ", ".join(f"{a} {v * 100:.0f} % ({n.get(a, 0)})" for a, v in th.items()),
        ]
    return lines


def last_settled_lines(last: tuple[Forecast, Outcome] | None) -> list[str]:
    if last is None:
        return ["Noch keine Prognose abgerechnet."]
    f, o = last
    by = f.by_asset()
    tag = " – nachgeholt, nicht in der Bilanz" if any(n.startswith("backfilled") for n in f.notes) else ""
    lines = [
        f"Prognose vom {f.decision_date} (1 M), abgerechnet per {o.settled_through}{tag}:",
        "",
        "| Klasse | prognostizierter Rang | P(obere Hälfte) | realisierte relative Rendite | realisierter Rang | obere Hälfte |",
        "|---|---|---|---|---|---|",
    ]
    for a in sorted(o.realised_rank, key=lambda k: o.realised_rank[k]):
        c = by.get(a)
        lines.append(
            f"| {a} | {c.rank if c and c.rank is not None else '–'} | {_pct(c.probability) if c else '–'} | {o.relative[a] * 100:+.2f} % | {o.realised_rank[a]} | {'ja' if o.hit[a] else 'nein'} |"
        )
    parts = [f"Rang-IC {o.ic:+.2f}" if o.ic is not None else "Rang-IC –"]
    if o.top_beats_bottom is not None:
        parts.append("Rang 1 schlug den letzten" if o.top_beats_bottom else "Rang 1 schlug den letzten nicht")
    if o.brier is not None and o.brier_const is not None:
        parts.append(f"Brier {o.brier:.4f} (0.5: {o.brier_const:.4f})")
    if o.ic_prev_month is not None:
        parts.append(f"Vormonatsrang-IC {o.ic_prev_month:+.2f}")
    if o.trend_hit:
        parts.append(
            "Trend: " + ", ".join(f"{a} {'richtig' if v else 'falsch'}" for a, v in o.trend_hit.items())
        )
    if o.portfolio_return is not None and o.ew_return is not None:
        parts.append(
            f"Paper-Regel {o.portfolio_return * 100:+.2f} % gegen Equal Weight {o.ew_return * 100:+.2f} %"
        )
    lines += ["", "; ".join(parts) + "."]
    return lines


def render_month(
    d: date,
    forecasts: Sequence[Forecast],
    tracks: Mapping[int, Mapping[str, Any]],
    last: tuple[Forecast, Outcome] | None,
    skipped: str | None,
    model: ForecastModel,
    snapshot: str,
    run_date: date,
) -> str:
    by_h = {f.horizon_months: f for f in forecasts}
    lines = [f"# Prognose der Anlageklassen – Entscheidung {d:%Y-%m-%d}", ""]
    lines.append(
        f"Erstellt {run_date} · Modell `{model.model_id}` v{model.version} · Datenstand `{snapshot}` · gerankt {', '.join(model.ranked)} · nur Trend {', '.join(model.trend_only) or '–'} · Cash {model.cash}"
    )
    lines.append("")
    if skipped:
        lines += [f"**Keine Prognose geschrieben:** {skipped}", ""]
    main = by_h.get(1)
    if main is not None:
        lines += [
            f"## 1 Monat (Hauptprognose) – Status: `{main.status}` ({STATUS_TEXT[main.status]}; beschreibend, kein Verlässlichkeitsmass)",
            "",
        ]
        lines += ranking_table(main)
        if any(n.startswith("backfilled") for n in main.notes):
            lines += [
                "",
                "**Nachgeholt (ADR 050):** Diese Prognose wurde mehr als die erlaubte Frist nach dem Entscheidungsdatum "
                "geschrieben. Sie ist korrekt aus der Sicht am Entscheidungsdatum berechnet, zählt aber nicht zur Live-Bilanz.",
            ]
        if main.notes:
            lines += ["", *[f"- {n}" for n in main.notes]]
        tt = trend_table(main)
        if tt:
            lines += ["", "Nur Trend (beschreibend, kein belegter Prognosevorteil – P5):", "", *tt]
        lines.append("")
        lines.append(
            "Lesart: P(obere Hälfte) = Wahrscheinlichkeit, dass die Klasse über den Horizont zu den besseren zwei der vier gehört "
            "(kalibriert auf der Geschichte bis zum Entscheidungsdatum). "
            + (EVIDENCE_FED if getattr(model, "macro", None) is not None else EVIDENCE_R1)
            + "ob sie live hält, zeigt allein die Bilanz unten. "
            "„Mittel des Rangs bisher“ = mittlere relative Rendite, die dieser Rang in den bis dahin bekannten Monaten erzielte, "
            "mit dem Block-Bootstrap-Intervall dieses Mittels – kein Vorhersageintervall für den kommenden Monat, dessen Streuung um ein Vielfaches grösser ist."
        )
        lines.append("")
    for h in sorted(by_h):
        if h == 1:
            continue
        f = by_h[h]
        lines += [f"## {h} Monate (Nebenauswertung) – Status `{f.status}`", "", *ranking_table(f), ""]
    lines += ["## Bilanz bisher (abgerechnete Prognosen)", "", *track_lines(tracks), ""]
    lines += ["## Letztes Ergebnis", "", *last_settled_lines(last), ""]
    lines += [
        "Journal: `journal/forecast/forecasts.jsonl` und `outcomes.jsonl` (append-only, Hash-Kette; `rotationlab forecast verify`; "
        "die Kette erkennt Änderungen im Innern der Datei, eine Kürzung am Ende nur gegen den Anker aus dem Actions-Log).",
        "",
    ]
    return "\n".join(lines)


def render_latest(name: str, text: str) -> str:
    return f"<!-- copy of {name} -->\n" + text
