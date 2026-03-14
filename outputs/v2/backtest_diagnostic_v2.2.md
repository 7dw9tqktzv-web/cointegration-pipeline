# Backtest Diagnostic V2.2 — Z Intraday + Sorties Spread-Space

**Date** : 2026-03-14
**Donnees** : 3 ans (2023-03 -> 2026-03), 5 paires CME eligibles, barres 5min

---

## 1. CONTEXTE

### Baseline V2.1

V2.1 (sigma_rolling window=20) : 45 trades, Z-score structurellement casse.
- Z = (Spread - theta_OU) / sigma_rolling melange deux echelles temporelles
  (theta_OU multi-semaines, sigma_rolling 100 min)
- Z-scores de +-8 a +-22, distribution non-N(0,1)
- GC/PA exclu (residu sizing $75-100k, pas de micro PA)
- Voir `outputs/v2/backtest_diagnostic_v2.1.md` pour le detail

### Changements V2.2

**Z-score intraday auto-coherent :**
```
mu_rolling_t    = moyenne(Spread sur N dernieres barres de la session)
sigma_rolling_t = ecart-type(Spread sur N dernieres barres de la session)
Z_intraday_t    = (Spread_t - mu_rolling_t) / sigma_rolling_t
```
mu et sigma de la meme fenetre -> Z mecaniquement borne, interpretable.

**Entree directe** au premier franchissement de Z = +-2.0 (pas de
arm-then-trigger). Le arm-then-trigger V1 entrait a Z median = -0.72,
consommant 60% du mouvement avant l'entree.

**Biais directionnel** (confluence couche 1 -> couche 2) :
```
Z_LT = (Spread_ouverture - theta_OU) / sigma_eq
Z_LT > 0 -> SHORT seulement | Z_LT < 0 -> LONG seulement
```

**Sorties spread-space** (references figees a l'entree) :
- TP quand spread bouge de X * sigma_entry dans le sens favorable
- SL quand spread bouge de 1.5 * sigma_entry dans le sens adverse
- SESSION_CLOSE a 15h25 CT

### Bugs corriges

**T_limite** : utilisait HL multi-jour (hl_operational de step4).
Pour NQ/RTY, HL multi-jour = 296 barres -> T_limite = -548 -> toute la
session time-locked. Fix : utiliser HL_intraday P75 par paire depuis
la config (42b ZC/ZW, 47b NQ/RTY, etc.).

**Filtre C** : comparait beta_Kalman a beta_OLS. Le Kalman, initialise
avec beta_OLS stale (calibre sur 60 sessions), corrigeait massivement
a la barre 0 (de 0.19 a 0.47 pour NQ/RTY). Le filtre C interpretait
cette correction comme une derive et tuait la session immediatement.
Fix : burn-in de 5 barres, reference beta_Kalman apres burn-in au lieu
de beta_OLS.

---

## 2. VALIDATION Z-SCORE

Distribution sur toutes les sessions tradeable, hors burn-in.

| Metrique        | V1 (sigma_eq) | V2.1 (sigma_rolling) | V2.2 (mu+sigma) | N(0,1) |
|-----------------|---------------|---------------------|-----------------|--------|
| mean            | -12.53        | aberrant            | +0.02           | 0      |
| std             | 20.01         | aberrant            | 1.29            | 1      |
| min / max       | -79 / +4      | -8 / +22            | -4.2 / +4.2     | ~+-3.5 |
| skew            | massif neg    | -                   | -0.02           | 0      |
| kurtosis        | -             | -                   | -0.77           | 0      |
| \|z\| >= 2.0    | 45.9%         | aberrant            | 10.4%           | 4.6%   |
| \|z\| >= 3.0    | 40.3%         | aberrant            | 0.7%            | 0.3%   |

**Conclusion** : Z V2.2 est centre (mean=0.02), symetrique (skew=-0.02),
borne (+-4.2), avec des queues legerement plus epaisses qu'une gaussienne
(ratio observe/theorique = 2.3x a +-2.0). Distribution quasi-identique
entre ZC/ZW et GC/SI.

ZC/ZW (N=20) : 376 sessions, 48 073 barres, P5=-2.00, P95=+2.03
GC/SI (N=20) : 229 sessions, 55 168 barres, P5=-2.01, P95=+2.04

---

## 3. RESULTATS PAR PAIRE

5 paires x 3 niveaux de TP, SL = 1.5 sigma_entry, entree directe +-2.0,
biais directionnel, T_limite base sur HL_intraday P75.

### Tableau complet

| Paire  | N  | TP   | Trades | TP  | SL  | SC  | avgTP  | avgSL  | avgSC  | Sharpe | WR  |
|--------|----|------|--------|-----|-----|-----|--------|--------|--------|--------|-----|
| ZC_ZW  | 20 | 1.0s | 923    | 611 | 312 | 0   | -$46   | -$74   | -      | -8.11  | 66% |
| ZC_ZW  | 20 | 1.5s | 859    | 497 | 362 | 0   | -$43   | -$73   | -      | -7.62  | 58% |
| ZC_ZW  | 20 | 2.0s | 810    | 419 | 391 | 0   | -$39   | -$71   | -      | -7.10  | 52% |
| GC_SI  | 20 | 1.0s | 937    | 565 | 365 | 7   | +$172  | -$290  | -$4    | -0.26  | 60% |
| GC_SI  | 20 | 1.5s | 889    | 463 | 407 | 18  | +$220  | -$273  | -$291  | -0.18  | 52% |
| GC_SI  | 20 | 2.0s | 849    | 376 | 443 | 29  | +$284  | -$275  | -$329  | -0.45  | 44% |
| NQ_RTY | 24 | 1.0s | 875    | 526 | 344 | 5   | +$54   | -$127  | -$186  | -1.01  | 60% |
| NQ_RTY | 24 | 1.5s | 833    | 444 | 378 | 11  | +$95   | -$136  | -$95   | -0.52  | 53% |
| NQ_RTY | 24 | 2.0s | 798    | 376 | 403 | 19  | +$146  | -$136  | -$126  | -0.10  | 47% |
| YM_RTY | 24 | 1.0s | 1212   | 690 | 514 | 8   | -$12   | -$44   | -$115  | -2.79  | 57% |
| YM_RTY | 24 | 1.5s | 1163   | 584 | 564 | 15  | -$4    | -$43   | -$191  | -2.39  | 50% |
| YM_RTY | 24 | 2.0s | 1117   | 493 | 597 | 27  | +$3    | -$39   | -$106  | -1.83  | 44% |
| CL_NG  | 40 | 1.0s | 390    | 227 | 161 | 2   | -$1    | -$183  | -$591  | -3.07  | 58% |
| CL_NG  | 40 | 1.5s | 377    | 196 | 176 | 5   | +$21   | -$184  | -$287  | -2.66  | 52% |
| CL_NG  | 40 | 2.0s | 350    | 155 | 188 | 7   | +$48   | -$186  | -$203  | -2.54  | 44% |

### Verdict par paire

| Paire  | Verdict       | Meilleur TP | Sharpe | Commentaire |
|--------|---------------|-------------|--------|-------------|
| NQ_RTY | **PROMETTEUR** | 2.0s       | -0.10  | avgTP +$146, quasi break-even. SL a optimiser |
| GC_SI  | **PROMETTEUR** | 1.0s       | -0.26  | avgTP +$172, signal fort mais SL couteux (-$290) |
| YM_RTY | MARGINAL      | 2.0s       | -1.83  | avgTP +$3, break-even exact. Couts trop proches |
| CL_NG  | NON-VIABLE    | 2.0s       | -2.54  | avgSL -$186 trop couteux, NG volatile |
| ZC_ZW  | NON-VIABLE    | 2.0s       | -7.10  | avgTP negatif a tous les niveaux, couts > profit |

---

## 4. DIAGNOSTIC ENTONNOIR

### Filtres pipeline (sessions bloquees)

| Paire  | Total | Stationarity | Cointegration | OU params | **Traded** | % traded |
|--------|-------|-------------|---------------|-----------|-----------|----------|
| ZC_ZW  | 696   | 20          | 300           | -         | **376**   | 54%      |
| GC_SI  | 717   | 50          | 437           | -         | **229**   | 32%      |
| NQ_RTY | 718   | 70          | 414           | -         | **232**   | 32%      |
| YM_RTY | 718   | 10          | 409           | -         | **297**   | 41%      |
| CL_NG  | 717   | 50          | 429           | -         | **237**   | 33%      |

### Filtres signal (barres bloquees) — |Z_intraday| >= 2.0

| Paire  | Barres \|Z\|>=2.0 | Biais OK | % kill biais | Time OK | % kill time |
|--------|-------------------|----------|-------------|---------|------------|
| ZC_ZW  | 4 988             | 2 488    | 50%         | 2 147   | 14%        |
| GC_SI  | 5 804             | 2 987    | 49%         | 1 912   | 36%        |
| NQ_RTY | 6 778             | 3 361    | 50%         | 2 271   | 32%        |
| YM_RTY | 8 610             | 4 324    | 50%         | 2 950   | 32%        |
| CL_NG  | 6 664             | 3 325    | 50%         | 2 589   | 22%        |

Le biais directionnel filtre ~50% des signaux (par construction).
Le T_limite filtre 14-36% supplementaires.

### Bugs corriges — impact sur le volume

| Paire  | Trades AVANT fix | Trades APRES fix | Facteur |
|--------|-----------------|------------------|---------|
| ZC_ZW  | 128             | 810              | 6x      |
| GC_SI  | 6               | 937              | 156x    |
| NQ_RTY | 0               | 798              | inf     |
| YM_RTY | 2               | 1117             | 558x    |
| CL_NG  | 0               | 350              | inf     |

---

## 5. CONCLUSIONS

### NQ/RTY est le plus prometteur

- Sharpe -0.10 a TP=2.0 sigma (quasi break-even)
- avgTP = +$146 (couvre largement les couts RT ~$28)
- 798 trades sur 3 ans (volume suffisant)
- Le SL a 1.5 sigma_entry est le goulet — a optimiser via analyse MAE

### GC/SI a le signal le plus fort mais SL trop couteux

- avgTP = +$172 a TP=1.0 (le plus eleve)
- Mais avgSL = -$290 — chaque SL annule ~1.7 TP
- 937 trades (volume excellent apres fix)
- Optimiser le SL est la priorite : si avgSL passe de -$290 a -$150,
  la paire devient profitable

### ZC/ZW et CL/NG sont non-viables

- ZC/ZW : avgTP negatif a tous les niveaux, couts RT $61 > profit
- CL/NG : avgSL = -$186, NG trop volatile

### YM/RTY est marginal

- avgTP = +$3 a TP=2.0 — exactement au break-even des couts
- 1117 trades (le plus de volume) mais Sharpe -1.83
- Pourrait basculer en positif avec un SL mieux calibre

### Diagnostic beta_Kalman vs beta_OLS

beta_Kalman et beta_OLS sont quasi-identiques (diff < 1.6%).
Le V2.4 (switch sizing) est inutile sur ces paires.

---

## 6. PROCHAINES ETAPES

1. **Analyse MAE/MFE post-entree sur NQ/RTY et GC/SI**
   Mesurer l'excursion adverse reelle pour calibrer le SL optimal.
   Si MAE median = 0.8 sigma, SL a 1.0 suffit.
   Si MAE median = 2.5 sigma, SL a 1.5 coupe des trades viables.

2. **Serie 2 SL basee sur les donnees MAE**
   Tester SL = 2.0, 2.5, 3.0 sigma_entry sur NQ/RTY et GC/SI.
   Objectif : Sharpe > 0 sur au moins 2 paires.

3. **Test Z = 2.5 sur GC/SI**
   Entrees plus selectives. Si avgTP augmente sans perdre trop de
   volume, la selectivite paie.

4. **Memo V2.3 (si necessaire)**
   Fenetres de calibration decouples (cointegration 130-260 sessions,
   beta_OLS 30 sessions). MacKinnon 15%. Univers elargi 10-15 paires.
   A envisager si les series 2-3 ne donnent pas de Sharpe positif.
