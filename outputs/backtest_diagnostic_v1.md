# Backtest V1 — Resultats complets

Date: 2026-03-13
Donnees: Sierra Chart, 3 ans (2023-03-09 → 2026-03-13), 1min back-adjusted
Paires: 7 (GC/SI, GC/PA, NQ/RTY, YM/RTY, CL/HO, CL/NG, ZC/ZW)
Pipeline: step1 (5min) → step2 (I(1)) → step3 (cointeg) → step4 (OU) → step5 (Kalman+signal+risk+sizing)

---

## 1. Tableau comparatif — 4 configurations testees

### Config A — V1 baseline (30j, MacKinnon 5%, armement 2.5σ)

| Paire    | Sessions | Traded | Trades | Blocage principal           |
|----------|----------|--------|--------|-----------------------------|
| GC_SI    | 747      | 125    | 0      | cointegration_blocking (622)|
| GC_PA    | 747      | 83     | 0      | cointegration_blocking (629)|
| NQ_RTY   | 748      | 87     | 0      | cointegration_blocking (660)|
| YM_RTY   | 748      | 110    | 0      | cointegration_blocking (637)|
| CL_HO    | 747      | 89     | 0      | cointegration_blocking (658)|
| CL_NG    | 747      | 91     | 0      | cointegration_blocking (656)|
| ZC_ZW    | 726      | 232    | 0      | cointegration_blocking (494)|
| **Total**| **5210** | **817**| **0**  |                             |

Temps d'execution: 5m43s. Cache step2 refresh/10 sessions.

### Config B — Fenetre 60j (MacKinnon 5%, armement 2.5σ)

| Paire    | Sessions | Traded | Trades | Skip reasons                                         |
|----------|----------|--------|--------|------------------------------------------------------|
| GC_SI    | 717      | 137    | 0      | coint:529, stat:50, insuf:1                          |
| GC_PA    | 717      | 126    | 0      | coint:500, stat:40, insuf:51                         |
| NQ_RTY   | 718      | 125    | 0      | coint:521, stat:70, insuf:2                          |
| YM_RTY   | 718      | 193    | 0      | coint:513, stat:10, insuf:2                          |
| CL_HO    | 717      | 125    | 0      | coint:531, stat:60, insuf:1                          |
| CL_NG    | 717      | 121    | 0      | coint:545, stat:50, insuf:1                          |
| ZC_ZW    | 696      | 278    | 0      | coint:398, stat:20                                   |
| **Total**| **5000** |**1105**| **0**  |                                                      |

Temps d'execution: 8m31s.

Observation: `stationarity_blocking` apparait (10 a 70 sessions par paire).
Avec 60 sessions, les tests 60d s'executent et detectent parfois l'actif comme I(0).
NQ/RTY le plus touche (70 sessions bloquees par step2).

### Config C — 60j + armement 2.0σ (MacKinnon 5%)

| Paire    | Sessions | Traded | Trades | Skip reasons                                         |
|----------|----------|--------|--------|------------------------------------------------------|
| GC_SI    | 717      | 137    | 1      | coint:529, stat:50, insuf:1                          |
| GC_PA    | 717      | 126    | 1      | coint:500, stat:40, insuf:51                         |
| NQ_RTY   | 718      | 125    | 1      | coint:521, stat:70, insuf:2                          |
| YM_RTY   | 718      | 193    | 1      | coint:513, stat:10, insuf:2                          |
| CL_HO    | 717      | 125    | 2      | coint:531, stat:60, insuf:1                          |
| CL_NG    | 717      | 121    | 0      | coint:545, stat:50, insuf:1                          |
| ZC_ZW    | 696      | 278    | 3      | coint:398, stat:20                                   |
| **Total**| **5000** |**1105**| **9**  |                                                      |

Temps d'execution: 8m27s.

Metriques par paire (sur pnl_net_1x):

| Paire    | Sharpe | WR     | Avg Win | Avg Loss | MaxDD    |
|----------|--------|--------|---------|----------|----------|
| GC_SI    | -0.59  | 0.0%   | $0      | $702     | -$702    |
| GC_PA    | -0.59  | 0.0%   | $0      | $3252    | -$3252   |
| NQ_RTY   | +0.59  | 100.0% | TP      | -        | $0       |
| YM_RTY   | -0.59  | 0.0%   | $0      | $1090    | -$1090   |
| CL_HO    | -0.82  | 0.0%   | $0      | -        | -$958    |
| ZC_ZW    | -0.48  | 33.3%  | -       | -        | -$468    |

### Config D — 60j + armement 2.0σ + MacKinnon 10% (meilleur V1)

| Paire    | Sessions | Traded | Trades | Skip reasons                                         |
|----------|----------|--------|--------|------------------------------------------------------|
| GC_SI    | 717      | 229    | 1      | coint:437, stat:50, insuf:1                          |
| GC_PA    | 717      | 230    | 1      | coint:396, stat:40, insuf:51                         |
| NQ_RTY   | 718      | 232    | 1      | coint:414, stat:70, insuf:2                          |
| YM_RTY   | 718      | 297    | 1      | coint:409, stat:10, insuf:2                          |
| CL_HO    | 717      | 213    | 2      | coint:443, stat:60, insuf:1                          |
| CL_NG    | 717      | 237    | 0      | coint:429, stat:50, insuf:1                          |
| ZC_ZW    | 696      | 376    | 3      | coint:300, stat:20                                   |
| **Total**| **5000** |**1814**| **9**  |                                                      |

Temps d'execution: 8m25s.

Metriques identiques a Config C — memes 9 trades.
MacKinnon 10% augmente les sessions traded de +64% (1105 → 1814) mais ne genere pas de nouveaux trades.
Le goulet est le z-score, pas step3.

---

## 2. Test diagnostic — Armement 1.5σ (ZC/ZW seul)

Config: 60j + MacKinnon 10% + armement 1.5σ. ZC/ZW uniquement.

| # | Direction | Entry Z | Exit motif    | Exit Z | PnL brut | PnL net 1x |
|---|-----------|---------|---------------|--------|----------|------------|
| 1 | SHORT     | +1.71   | STOP_LOSS     | +3.05  | -$388    | -$457      |
| 2 | SHORT     | +1.60   | STOP_LOSS     | +3.02  | -$278    | -$321      |
| 3 | SHORT     | +1.55   | STOP_LOSS     | +3.12  | -$315    | -$358      |
| 4 | LONG      | -1.59   | TAKE_PROFIT   | -0.28  | +$238    | +$188      |
| 5 | SHORT     | +1.96   | STOP_LOSS     | +3.33  | -$220    | -$276      |
| 6 | SHORT     | +1.68   | STOP_LOSS     | +3.02  | -$168    | -$224      |
| 7 | SHORT     | +1.63   | TAKE_PROFIT   | +0.42  | +$185    | +$135      |
| 8 | SHORT     | +1.54   | TAKE_PROFIT   | +0.31  | +$182    | +$133      |
| 9 | SHORT     | +1.44   | STOP_LOSS     | +3.02  | -$255    | -$311      |
| 10| SHORT     | +1.99   | STOP_LOSS     | +3.01  | -$141    | -$191      |
| 11| SHORT     | +1.53   | TAKE_PROFIT   | +0.49  | +$140    | +$103      |

Breakdown motifs de sortie:

| Motif          | Count | %    |
|----------------|-------|------|
| STOP_LOSS      | 7     | 63.6%|
| TAKE_PROFIT    | 4     | 36.4%|
| SESSION_CLOSE  | 0     | 0.0% |
| SORTIE_FORCEE  | 0     | 0.0% |

Metriques: Sharpe = -1.08, WR = 36.4%, MaxDD = -$1684

---

## 3. Synthese des deux goulets identifies

### Goulet 1 — Step3 bloque trop (cointegration_blocking)

MacKinnon 5% sur fenetre rolling 30j rejette 83-88% des sessions.
Passer a 60j + MacKinnon 10% reduit a 43-62% de blocage.
ZC/ZW est la paire la plus cointegrante (300 sessions bloquees sur 696 = 43%).
CL/NG est la moins cointegrante (545/717 = 76% avec 30j, 429/717 = 60% avec MK10%).

Impact des leviers sur le % de sessions traded:

| Levier           | GC/SI | NQ/RTY | ZC/ZW | Moyenne 7p |
|------------------|-------|--------|-------|------------|
| 30j + MK5%       | 17%   | 12%    | 32%   | 16%        |
| 60j + MK5%       | 19%   | 17%    | 40%   | 22%        |
| 60j + MK10%      | 32%   | 32%    | 54%   | 36%        |

### Goulet 2 — Z-score trop compresse (σ_eq multi-jour)

Avec le meilleur parametrage V1 (Config D), 1814 sessions traded, 0 armement a 2.5σ.
Baisser l'armement a 2.0σ debloque 9 trades. Baisser a 1.5σ debloque 11 trades sur ZC/ZW seul.

Le probleme est structurel:
- σ_eq est calibre sur la distribution du spread multi-jour (30-60 sessions = 6-12 semaines)
- Le z-score intraday est compresse car σ_eq >> volatilite intraday du spread
- Baisser les seuils degrade la qualite d'entree (64% SL a 1.5σ vs 33% a 2.0σ)

Le cercle vicieux: σ_eq trop grand → z compresse → seuils baisses → faux signaux → SL

---

## 4. Diagnostic cle du test 1.5σ

Le test a 1.5σ sur ZC/ZW est le resultat le plus informatif:

1. **0 SESSION_CLOSE** — le spread a assez de volatilite intraday pour toucher TP ou SL
   dans chaque session. Le half-life de 200+ barres n'est pas un mur.

2. **64% STOP_LOSS** — les entrees a 1.5σ_eq sont majoritairement des faux signaux.
   Le spread n'est pas en mean-reversion, il trending. σ_eq ne capture pas
   la dynamique intraday.

3. **Avg loss ($305) > Avg win ($140)** — ratio risk/reward 2:1 negatif.
   Le SL a 3.0σ est a 1.5σ du point d'entree (1.5σ → 3.0σ = 1.5σ de distance),
   le TP a 0.5σ est a 1.0σ du point d'entree (1.5σ → 0.5σ = 1.0σ de distance).
   Mais en dollars le SL coute 2x plus que le TP rapporte car le spread
   accelere quand il diverge.

---

## 5. Conclusion V1

L'architecture V1 (OU stationnaire, σ_eq multi-jour, z-score fixe) est mathematiquement
coherente et techniquement validee end-to-end. Le pipeline fonctionne: les trades s'ouvrent,
se ferment, le PnL se calcule, les couts s'appliquent.

Mais le modele n'est pas adapte au trading intraday quotidien:
- σ_eq multi-jour compresse le z-score intraday
- Les seuils d'entree doivent etre baisses pour generer des trades
- Les entrees basses sont des faux signaux (spread trending, pas mean-reverting)
- Aucun parametrage V1 ne produit un Sharpe positif sur 3 ans

**Direction V2**: estimer un σ qui reflete la volatilite intraday du spread.
Le 0 SESSION_CLOSE prouve que l'intraday est viable.
Le 64% SL prouve que σ_eq est le mauvais normaliseur.

---

## Annexes

### A. Donnees brutes utilisees

| Contrat | Fichier                            | Lignes    | Debut      | Fin        |
|---------|------------------------------------|-----------|------------|------------|
| GC      | GCJ26_FUT_CME.scid_BarData.txt     | 1,019,831 | 2023/03/09 | 2026/03/13 |
| SI      | SIK26_FUT_CME.scid_BarData.txt     | 991,406   | 2023/03/09 | 2026/03/13 |
| PA      | PAM26_FUT_CME.scid_BarData.txt     | 490,623   | 2023/03/09 | 2026/03/13 |
| NQ      | NQH26_FUT_CME.scid_BarData.txt     | 1,019,780 | 2023/03/09 | 2026/03/13 |
| RTY     | RTYH26_FUT_CME.scid_BarData.txt    | 989,288   | 2023/03/09 | 2026/03/13 |
| YM      | YMH26_FUT_CME.scid_BarData.txt     | 1,007,611 | 2023/03/09 | 2026/03/13 |
| CL      | CLJ26_FUT_CME.scid_BarData.txt     | 1,010,379 | 2023/03/09 | 2026/03/13 |
| HO      | HOJ26_FUT_CME.scid_BarData.txt     | 753,977   | 2023/03/09 | 2026/03/13 |
| NG      | NGJ26_FUT_CME.scid_BarData.txt     | 917,720   | 2023/03/09 | 2026/03/13 |
| ZC      | ZCK26_FUT_CME.scid_BarData.txt     | 609,972   | 2023/03/09 | 2026/03/13 |
| ZW      | ZWK26_FUT_CME.scid_BarData.txt     | 610,992   | 2023/03/09 | 2026/03/13 |

### B. Sessions par actif apres step1

| Actif | Sessions | Barres 5min | Low liq days |
|-------|----------|-------------|--------------|
| GC    | 777      | 204,199     | 2            |
| SI    | 777      | 202,231     | 6            |
| NQ    | 777      | ~204,000    | -            |
| ZC    | ~750     | ~122,000    | -            |
| ZW    | ~750     | ~122,000    | -            |

### C. Parametres du modele V1

| Parametre                | Valeur V1 baseline | Meilleur V1     |
|--------------------------|--------------------|-----------------|
| Fenetre calibration      | 30 sessions        | 60 sessions     |
| MacKinnon level          | 5%                 | 10%             |
| Armement z-score         | +/- 2.5σ           | +/- 2.0σ        |
| Trigger z-score          | +/- 2.0σ           | +/- 2.0σ        |
| TP z-score               | +/- 0.5σ           | +/- 0.5σ        |
| SL z-score               | +/- 3.0σ           | +/- 3.0σ        |
| σ pour z-score           | σ_eq (multi-jour)  | σ_eq (multi-jour)|
| Cache step2              | refresh/10 sessions| refresh/10 sessions|
| dt                       | 1 (5min bar)       | 1 (5min bar)    |
