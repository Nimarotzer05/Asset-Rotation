# Ausführungszeitpunkt: was kostet ehrliches Timing?

Golden-Läufe aller Module (Forschungspanel, Stichprobe und Kosten wie im Golden), Sharpe ex Cash, unter vier
Konventionen: `same_close` = Umsetzung zum Entscheidungsschluss (Studien), `next_close` = Folgetag (Produktion,
ADR 011), `next_tradable` = Folgetag für Assets mit Schlusskursen, nächstes Entscheidungsdatum für Assets zu
Monatsmitteln (ADR 042, die ehrliche Zahl), `next_month_close` = alles einen Monat später (pessimistische
Schranke). „Mittelwert-Assets“ = gehandelte Assets des Langfrist-Universums mit `price_basis: monthly_average`.

| Modul | Mittelwert-Assets | Forschung | same_close | next_close | **next_tradable** | next_month_close | Δ next_tradable − same_close |
|---|---|---|---|---|---|---|---|
| commodity_trend | 9/9 | 0.7400 | 0.7421 | 0.7421 | **0.4225** | 0.4225 | -0.3196 |
| multi_asset_rotation | 2/6 | 0.5700 | 0.5713 | 0.5855 | **0.5574** | 0.5337 | -0.0138 |
| precious_metals | 0/2 | 0.2200 | 0.2192 | 0.2103 | **0.2103** | 0.2354 | -0.0089 |
| us_equity_exposure | 0/1 | 0.5730 | 0.5732 | 0.5732 | **0.5732** | 0.4952 | -0.0000 |
| us_sector_rotation | 0/10 | 0.5910 | 0.5904 | 0.5904 | **0.5904** | 0.5212 | +0.0000 |
| multi_asset_rotation (walk-forward OOS) | 2/6 | 0.7720 | 0.7721 | 0.7859 | **0.6913** | 0.7152 | -0.0809 |

Lesart: Für Monatsmittel ist `next_close` rechnerisch gleich `same_close` (derselbe Mittelwert); erst ein Kauf
im Folgemonat nutzt einen Preis, dessen Mittelungsfenster nach der Entscheidung liegt. Ein Signal aus einem
Monatsmittel, umgesetzt zum selben Mittel, erntet die künstliche Autokorrelation gemittelter Reihen (Working
1960): im Aufwärtstrend liegt das Mittel unter dem Monatsendkurs. Wo `next_tradable` von `same_close`
abweicht, misst die Differenz genau diesen Effekt; Module ohne Mittelwert-Assets bleiben unverändert.

Walk-forward: `next_tradable` (0.69) liegt unter `next_month_close` (0.72). Zwei Gründe: Bei einem Wechsel von
einem Mittelwert-Asset in ein Asset mit Schlusskurs wird das neue sofort gekauft, das alte erst einen Monat später
verkauft; die Überlappung ist in Cash finanziert (Brutto bis 2) und verstärkt in diesem Monat Gewinn wie Verlust.
Und die Kandidatenwahl beruht auf Schattenrenditen in der Studienkonvention (ADR 039), nicht auf dem Timing des
Laufs. Die Spanne 0.69–0.72 statt 0.77 ist die ehrliche Aussage.
