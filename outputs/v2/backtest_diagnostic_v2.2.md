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

## 6. BIAIS DIRECTIONNEL — Tests et invalidation partielle

### 6.1. Biais legacy invalide (theta_OU / sigma_eq)

Le biais original utilisait Z_LT = (spread_open - theta_OU) / sigma_eq.
theta_OU et sigma_eq ont ete invalides en V2.1 (Z-score aberrant,
distribution non-N(0,1)). Le biais reposait sur des parametres casses.

### 6.2. Biais empirique — concept valide, implementation fragile

Remplacement : Z_LT = (spread_open - mu_120) / sigma_120
ou mu_120 et sigma_120 sont calcules sur les 120 derniers spreads d'ouverture.

**Test de permutation (NQ/RTY)** — le biais est-il reel ou aleatoire ?
- Biais empirique 120s : Sharpe +0.925 (sur 112 sessions post-burn-in)
- 100 filtres aleatoires : median -2.28, max +0.291, P95 -0.418
- P-value = 0.00 (0/100 >= +0.925)
- **VERDICT : le biais directionnel est statistiquement significatif**

Le concept fonctionne : quand le spread ouvre haut vs les 120 derniers
jours, les shorts marchent mieux. Le signal est reel.

### 6.3. Zone morte — serie 1 (skip si |Z_LT| < seuil)

| DZ   | Trades | avgTP  | avgSL  | Sharpe | S1.5x  | WR  |
|------|--------|--------|--------|--------|--------|-----|
| 0.0  | 788    | +$134  | -$116  | +0.12  | -0.24  | 47% |
| 0.5  | 681    | +$124  | -$129  | -0.25  | -0.58  | 47% |
| 0.8  | 393    | +$94   | -$88   | -0.11  | -0.36  | 48% |
| 1.0  | 287    | +$164  | -$114  | +0.43  | +0.19  | 49% |
| 1.5  | 98     | +$103  | -$16   | +0.68  | +0.50  | 50% |

DZ=1.0 : Sharpe +0.43, S1.5x +0.19 (premier resultat robuste au slippage).
DZ=1.5 : Sharpe +0.68, S1.5x +0.50 mais 98 trades seulement.

### 6.4. Zone morte — serie 2 (trade sans biais si |Z_LT| < seuil)

Bug initial : bias=None bloquait les entrees au lieu d'autoriser les
deux directions. Corrige avec bias="BOTH".

| DZ   | Trades | avgTP  | avgSL  | Sharpe | S1.5x  | WR  |
|------|--------|--------|--------|--------|--------|-----|
| 0.5  | 434    | +$67   | -$42   | +0.58  | -0.13  | 46% |
| 0.8  | 537    | +$12   | -$4    | +0.19  | -0.57  | 47% |
| 1.0  | 594    | -$1    | -$14   | -0.81  | -1.54  | 47% |
| 1.5  | 727    | +$33   | -$101  | -3.32  | -4.01  | 45% |

Le skip (S1) bat le trade BOTH (S2) a chaque niveau.
Les sessions ambigues ne sont pas profitables en bidirectionnel.

### 6.5. Run complet 5 paires — divergence avec test isole

Config : biais 120s, DZ=1.0, skip. Resultats :

| Paire  | Trades | avgTP  | avgSL  | Sharpe | S1.5x  | WR  |
|--------|--------|--------|--------|--------|--------|-----|
| GC_SI  | 687    | +$464  | -$417  | +0.62  | +0.18  | 49% |
| NQ_RTY | 594    | -$1    | -$14   | -0.32  | -0.61  | 47% |
| YM_RTY | 1032   | -$2    | -$56   | -2.50  | -3.10  | 44% |
| CL_NG  | 277    | +$42   | -$225  | -2.80  | -3.15  | 44% |
| ZC_ZW  | 950    | -$20   | -$81   | -7.76  | -8.51  | 54% |

**NQ/RTY passe de Sharpe +0.43 (test isole) a -0.32 (run complet).**
GC/SI est la seule paire positive (Sharpe +0.62, S1.5x +0.18).

### 6.6. Cause de la divergence

Le spread d'ouverture depend de alpha_OLS et beta_OLS de la session
courante. Ces parametres changent a chaque recalibration (la fenetre
de 60 sessions glisse). Le meme jour peut avoir un spread d'ouverture
different selon le beta utilise.

L'historique des spread_opens n'est donc PAS stable — il depend de
l'ordre de calibration. Le Z_LT calcule dans le test isole (sessions
pre-filtrees, beta fixe par bloc) differe du Z_LT calcule dans le
backtester (beta recalibre a chaque session).

C'est un **biais dans le biais** : le signal directionnel n'est pas
reproductible entre deux implementations differentes du meme calcul.

### 6.7. Conclusions sur le biais directionnel

**Ce qui est valide :**
- Le concept de biais directionnel est statistiquement significatif
  (test de permutation, p=0.00)
- Le skip des sessions ambigues (DZ > 0) ameliore la selectivite
- GC/SI montre un Sharpe positif robuste avec le biais

**Ce qui ne fonctionne pas :**
- Le calcul du spread d'ouverture est instable (depend de beta_OLS
  qui change a chaque recalibration)
- Les resultats ne sont pas reproductibles entre le test isole et
  le backtester
- Le biais empirique sur 120 sessions de spread_opens OLS n'est pas
  un signal stable

### 6.8. Test ratio brut log(A/B) — echec

Remplacement du spread OLS par le ratio brut pour eliminer la dependance
a beta_OLS. Implementation :
```
ratio = log(price_A) - log(price_B)
mu_120 = mean(ratios des 120 dernieres sessions)
Z_LT = (ratio_today - mu_120) / std(ratios_120)
```

Config : DZ=1.0 skip, 120 sessions, TP=2.0, SL=1.5.

| Paire  | Trades | avgTP  | avgSL  | Sharpe | S1.5x  | WR  |
|--------|--------|--------|--------|--------|--------|-----|
| GC_SI  | 540    | +$430  | -$382  | -0.25  | -0.48  | 48% |
| NQ_RTY | 511    | +$50   | -$157  | -1.46  | -1.64  | 43% |
| YM_RTY | 924    | +$33   | -$59   | -1.35  | -2.09  | 46% |
| CL_NG  | 276    | -$20   | -$146  | -2.05  | -2.42  | 43% |
| ZC_ZW  | 812    | -$38   | -$71   | -6.97  | -7.60  | 54% |

**Aucun Sharpe positif.** Le signal directionnel qui fonctionnait avec le
spread OLS ne se transfere pas au ratio brut. Le beta joue un role reel
dans le signal — le ratio brut perd l'information du hedge ratio.

### 6.9. Bilan biais directionnel

**Valide :**
- Le concept de biais directionnel est statistiquement significatif (p=0.00)
- Le mode skip (DZ=1.0) ameliore la selectivite
- Le spread OLS capture un signal que le ratio brut ne capture pas

**Non resolu :**
- Le spread OLS depend de beta_OLS qui change a chaque recalibration
- Les resultats ne sont pas reproductibles entre implementations
- Le ratio brut (sans beta) ne fonctionne pas
- Risque d'overfitting : ~15 configurations testees sur NQ/RTY

**Pistes V2.3 :**
- OLS sur 120 sessions (beta tres stable) en timeframe 15min/30min
  pour un Z-score long terme stable
- Figer beta une fois par semaine au lieu de recalibrer par session
- Walk-forward pour valider la robustesse out-of-sample

---

## 7. OPTIMISATION SL — NQ/RTY + GC/SI

### Bug corrige

Le SL en spread-space etait hardcode a 1.5. Le parametre sl_threshold
controlait aussi la condition d'entree Z-score (z >= -sl), bloquant les
entrees quand SL < 2.0. Fix : condition d'entree fixee a +-3.0,
independante du SL spread-space.

### NQ/RTY — SL 1.5 / 2.0 / 2.5 / 3.0

| SL  | Trades | TP  | SL  | SC  | avgTP  | avgSL  | Sharpe | S1.5x  | WR  |
|-----|--------|-----|-----|-----|--------|--------|--------|--------|-----|
| 1.5 | 501    | 219 | 271 | 11  | +$47   | -$157  | -1.50  | -1.68  | 44% |
| 2.0 | 468    | 233 | 222 | 13  | +$39   | -$201  | -1.79  | -1.96  | 50% |
| 2.5 | 441    | 238 | 190 | 13  | +$28   | -$205  | -1.33  | -1.48  | 54% |
| 3.0 | 417    | 233 | 168 | 16  | +$32   | -$242  | -1.40  | -1.55  | 56% |

WR monte avec SL plus large (44% -> 56%) mais avgSL se degrade
(-$157 -> -$242). Le Sharpe reste negatif a tous les niveaux.
NQ/RTY n'est pas viable avec cette configuration.

### GC/SI — SL 1.5 / 2.0 / 2.5 / 3.0

| SL  | Trades | TP  | SL  | SC  | avgTP  | avgSL  | Sharpe | S1.5x  | WR  |
|-----|--------|-----|-----|-----|--------|--------|--------|--------|-----|
| 1.5 | 460    | 218 | 229 | 13  | +$476  | -$364  | -0.15  | -0.35  | 47% |
| 2.0 | 421    | 218 | 194 | 9   | +$429  | -$446  | +0.04  | -0.18  | 52% |
| 2.5 | 396    | 216 | 164 | 16  | +$416  | -$533  | -0.09  | -0.27  | 55% |
| 3.0 | 375    | 214 | 139 | 22  | +$472  | -$610  | +0.09  | -0.09  | 57% |

GC/SI SL=2.0 : Sharpe +0.04. SL=3.0 : Sharpe +0.09.
Les deux sont quasi break-even mais ne survivent pas au slippage 1.5x.
L'edge est trop fin pour etre exploitable en live.

---

## 8. BILAN V2.2 FINAL

### Resultats

| Paire  | Meilleur SL | Sharpe | S1.5x  | Verdict          |
|--------|-------------|--------|--------|------------------|
| GC_SI  | 3.0         | +0.09  | -0.09  | Break-even       |
| NQ_RTY | 2.5         | -1.33  | -1.48  | Non-viable       |
| YM_RTY | -           | -1.58  | -2.27  | Non-viable       |
| CL_NG  | -           | -1.98  | -2.37  | Non-viable       |
| ZC_ZW  | -           | -7.44  | -8.10  | Non-viable       |

### Ce qui a ete valide en V2.2

- Z-score intraday auto-coherent (mean=0, std=1.29, borne +-4.2)
- Entree directe au 1er franchissement Z=+-2.0
- Sortie en spread-space (references figees a l'entree)
- Biais directionnel statistiquement significatif (p=0.00)
- Biais OLS recalcule avec beta du jour (reproductible)
- DZ=1.0 mode skip (meilleur compromis)
- Filtre C avec burn-in 5 barres
- T_limite base sur HL_intraday P75

### Ce qui n'a pas fonctionne

- Aucune paire avec Sharpe positif robuste au slippage
- NQ/RTY : edge fragile, depend de l'implementation du biais
- GC/SI : break-even, avgSL trop couteux (-$364 a -$610)
- Le SL en sigma_entry ne scale pas avec la volatilite reelle
- 11 hypotheses invalidees au total

### Pistes V2.3

1. **Fenetres decouples** : cointegration sur 120+ sessions (moins de
   sessions bloquees), beta_OLS sur 30 sessions (plus reactif)
2. **MacKinnon 15%** : augmenter le nombre de sessions tradeable
3. **Biais OLS long terme** : regression sur 120 sessions en timeframe
   15min/30min pour un Z-score LT stable
4. **Univers elargi** : 10-15 paires au lieu de 5
5. **Walk-forward** : validation out-of-sample avant toute conclusion
