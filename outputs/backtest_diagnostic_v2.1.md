# Backtest Diagnostic V2.1 — sigma_rolling

**Date** : 2026-03-14
**Baseline** : V1 Config D (60j, MacKinnon 10%, arming 2.0 sigma_eq) = 9 trades, Sharpe negatif
**Changement V2.1** : Z_t = (Spread_t - theta_OU) / sigma_rolling_t (au lieu de sigma_eq)
**Donnees** : 3 ans (2023-03 -> 2026-03), 7 paires CME, barres 5min

---

## 1. Phase 1 — ZC/ZW x 3 fenetres sigma_rolling

Parametres fixes : calibration 60j, MacKinnon 10%, arming 2.0 sigma, TP 0.5 sigma, SL 3.0 sigma.

| Window | Trades | TP | SL | SC | SF | Sharpe_1x | WR  |
|--------|--------|----|----|----|-----|-----------|-----|
| **20** | 33     | 17 | 16 | 0  | 0   | **-2.20** | 52% |
| 40     | 39     | 17 | 22 | 0  | 0   | -2.41     | 44% |
| 60     | 41     | 20 | 21 | 0  | 0   | -2.48     | 49% |

**Observations :**
- Window 20 = meilleure (Sharpe le moins negatif)
- Fenetres plus larges generent plus de trades mais aussi plus de SL
- 0 SESSION_CLOSE sur toutes les fenetres : le spread revient toujours avant la cloture
- WR ~50% sur window 20, degrade sur fenetres plus larges

**Fenetre retenue pour Phase 2 : window=20 (100 min)**

---

## 2. Phase 2 — 7 paires x window=20

| Paire  | Traded    | Trades | TP | SL | SC | SF | Sharpe_1x | WR  | W/L | MaxDD ($) |
|--------|-----------|--------|----|----|----|-----|-----------|-----|-----|-----------|
| GC_SI  | 229/717   | 0      | 0  | 0  | 0  | 0   | n/a       | -   | -   | -         |
| GC_PA  | 230/717   | 8      | 4  | 4  | 0  | 0   | **+0.32** | 50% | 1.1 | -1 115    |
| NQ_RTY | 232/718   | 0      | 0  | 0  | 0  | 0   | n/a       | -   | -   | -         |
| YM_RTY | 297/718   | 3      | 1  | 2  | 0  | 0   | -0.59     | 33% | 0.0 | -362      |
| CL_HO  | 213/717   | 0      | 0  | 0  | 0  | 0   | n/a       | -   | -   | -         |
| CL_NG  | 237/717   | 1      | 0  | 1  | 0  | 0   | -0.59     | 0%  | 0.0 | -116      |
| ZC_ZW  | 376/696   | 33     | 17 | 16 | 0  | 0   | -2.20     | 52% | 0.6 | -1 797    |

### Robustesse slippage (paires avec trades)

| Paire  | Sharpe_1x | Sharpe_1.5x | Sharpe_2x |
|--------|-----------|-------------|-----------|
| GC_PA  | +0.32     | +0.22       | +0.11     |
| YM_RTY | -0.59     | -0.59       | -0.59     |
| CL_NG  | -0.59     | -0.59       | -0.59     |
| ZC_ZW  | -2.20     | -2.25       | -2.27     |

### Skip reasons

| Paire  | cointegration_blocking | stationarity_blocking | insufficient_clean |
|--------|------------------------|----------------------|-------------------|
| GC_SI  | 437                    | 50                   | 1                 |
| GC_PA  | 396                    | 40                   | 51                |
| NQ_RTY | 414                    | 70                   | 2                 |
| YM_RTY | 409                    | 10                   | 2                 |
| CL_HO  | 443                    | 60                   | 1                 |
| CL_NG  | 429                    | 50                   | 1                 |
| ZC_ZW  | 300                    | 20                   | 0                 |

---

## 3. Analyse

### Ce qui fonctionne
- **sigma_rolling debloque le z-score** : ZC/ZW passe de 0-9 trades (V1) a 33 trades
- **0 SESSION_CLOSE** : le spread a assez de volatilite intraday pour toucher TP ou SL

### Ce qui ne fonctionne pas
- **ZC/ZW : 33 trades mais Sharpe -2.20** — WR 52% mais ratio W/L = 0.6 (les SL coutent plus que les TP)
- **GC/PA : Sharpe +0.32 invalide** — repose sur 2 jours sur 3 ans (voir section 5)
- **3 paires a 0 trades** (GC/SI, NQ/RTY, CL/HO) — le spread intraday reste trop stable meme normalise par sigma_rolling
- **Blocage principal : cointegration_blocking** (MacKinnon) — 60-70% des sessions skippees
- **Zero paire viable a ce stade**

### Seuils Z-score utilises
- Armement : +/-2.0 sigma_rolling
- Trigger : +/-2.0 sigma_rolling (retour)
- Take Profit : |z| < 0.5 sigma_rolling
- Stop Loss : |z| > 3.0 sigma_rolling
- Desarmement : z en zone SL sans position

### Comparaison V1 vs V2.1

| Metrique             | V1 (Config D) | V2.1 (w=20) |
|----------------------|---------------|-------------|
| Paires avec trades   | 1 (ZC/ZW)     | 4           |
| Total trades (7p)    | 9             | 45          |
| Sharpe positif       | 0 paires      | 0 (GC/PA invalide, voir S5) |
| SESSION_CLOSE rate   | 0%            | 0%          |

---

## 4. Test SL 2.5 vs 3.0 — Diagnostic placement de SL

**Question** : le ratio W/L defavorable est-il un probleme de placement de SL ou un probleme structurel ?
**Methode** : un seul parametre change (SL 3.0 -> 2.5), window=20, sur ZC/ZW et GC/PA.

### ZC/ZW

| SL  | Trades | TP | SL  | SC | Sharpe_1x | WR  | W/L | avgTP ($) | avgSL ($) |
|-----|--------|----|-----|----|-----------|-----|-----|-----------|-----------|
| 3.0 | 33     | 17 | 16  | 0  | -2.20     | 52% | 0.6 | -32       | -75       |
| 2.5 | 27     | 14 | 13  | 0  | -2.04     | 52% | 0.5 | -31       | -82       |

### GC/PA

| SL  | Trades | TP | SL  | SC | Sharpe_1x | WR  | W/L | avgTP ($) | avgSL ($) |
|-----|--------|----|-----|----|-----------|-----|-----|-----------|-----------|
| 3.0 | 8      | 4  | 4   | 0  | +0.32     | 50% | 1.1 | +212      | +144      |
| 2.5 | 6      | 3  | 3   | 0  | +0.27     | 50% | 0.7 | +92       | +287      |

### Diagnostic

**ZC/ZW — probleme structurel, pas de placement de SL :**
- avgTP = -$32 : les TP eux-memes perdent de l'argent en net. Le cout de transaction
  (spread_cost_rt) est superieur au profit brut moyen d'un TP.
- Resserrer le SL a 2.5 reduit le nombre de trades (-6) sans ameliorer le ratio.
- Le WR reste a 52% dans les deux cas — la qualite d'entree ne change pas.
- **Conclusion : le probleme n'est pas le SL mais l'amplitude du TP trop faible
  relativement aux couts de transaction.**

**GC/PA — SL 3.0 est optimal :**
- avgTP = +$212, avgSL = +$144 : les deux sont positifs (trades profitables net).
- SL 2.5 degrade la performance (perd 2 trades, W/L 1.1 -> 0.7).
- Le spread GC/PA a plus d'amplitude que ZC/ZW, permettant des TP rentables.

### Implications pour V2.2

Le probleme de ZC/ZW n'est pas le placement de SL ni le sigma_rolling.
C'est le ratio amplitude_TP / couts_transaction qui est trop faible.
Deux leviers possibles :
1. **V2.2 Bertram** : seuils d'entree optimaux qui maximisent le profit espere
   PAR UNITE DE TEMPS, en tenant compte des couts. Un seuil d'entree plus
   eloigne de la moyenne = TP plus profitable, mais trades moins frequents.
2. **Micro-contrats** : reduire les couts de transaction via sizing micro
   (ZC n'a pas de micro, mais le diagnostic s'applique aux autres paires).

---

## 5. Detail trade-by-trade GC/PA — Invalidation du Sharpe +0.32

### Les 8 trades

| # | Session  | Dir   | Entree | Sortie | Dur  | Motif        | Z_in  | Z_out | PnL brut | PnL net | Cost |
|---|----------|-------|--------|--------|------|--------------|-------|-------|----------|---------|------|
| 1 | 20240110 | LONG  | 02:05  | 03:05  | 12b  | TAKE_PROFIT  | -0.93 | -0.40 | -$440    | -$568   | $128 |
| 2 | 20240130 | LONG  | 06:05  | 06:55  | 10b  | TAKE_PROFIT  | -1.64 | -0.09 | +$90     | -$38    | $128 |
| 3 | 20240207 | SHORT | 06:10  | 07:20  | 14b  | STOP_LOSS    | +1.20 | +4.08 | -$380    | -$508   | $128 |
| 4 | 20240212 | SHORT | 04:05  | 04:30  | 5b   | TAKE_PROFIT  | +1.53 | +0.47 | +$1010   | +$882   | $128 |
| 5 | 20240212 | SHORT | 07:20  | 07:35  | 3b   | TAKE_PROFIT  | +1.01 | -0.39 | +$703    | +$575   | $128 |
| 6 | 20240212 | LONG  | 08:25  | 09:25  | 12b  | STOP_LOSS    | -1.98 | -3.81 | +$460    | +$332   | $128 |
| 7 | 20240704 | LONG  | 01:50  | 03:30  | 20b  | STOP_LOSS    | -1.68 | -5.34 | -$743    | -$872   | $128 |
| 8 | 20260109 | LONG  | 00:45  | 02:00  | 15b  | STOP_LOSS    | -1.89 | -4.03 | +$1753   | +$1625  | $128 |

### Sigma au moment de l'entree

| # | Session  | sigma_rolling | sigma_eq  | ratio r/eq | GC     | PA     | beta   | HL    |
|---|----------|---------------|-----------|------------|--------|--------|--------|-------|
| 1 | 20240110 | 0.000971      | 0.008097  | 0.12       | $2 391 | $1 106 | 0.0440 | 148b  |
| 2 | 20240130 | 0.000477      | 0.005453  | 0.09       | $2 385 | $1 105 | 0.0632 | 102b  |
| 3 | 20240207 | 0.000361      | 0.004428  | 0.08       | $2 381 | $1 061 | 0.0919 | 102b  |
| 4 | 20240212 | 0.001133      | 0.004260  | 0.27       | $2 367 | $992   | 0.1085 | 69b   |
| 5 | 20240212 | 0.000717      | 0.004260  | 0.17       | $2 370 | $1 014 | 0.1085 | 69b   |
| 6 | 20240212 | 0.001482      | 0.004260  | 0.35       | $2 361 | $1 012 | 0.1085 | 69b   |
| 7 | 20240704 | 0.000508      | 0.006352  | 0.08       | $2 653 | $1 124 | 0.1132 | 134b  |
| 8 | 20260109 | 0.003270      | 0.007697  | 0.42       | $4 522 | $1 954 | 0.2464 | 140b  |

### Contexte marche

| # | Session  | Dir   | GC move      | PA move        | Motif       | PnL net |
|---|----------|-------|--------------|----------------|-------------|---------|
| 1 | 20240110 | LONG  | +0.07%       | +0.54%         | TAKE_PROFIT | -$568   |
| 2 | 20240130 | LONG  | +0.08%       | +0.09%         | TAKE_PROFIT | -$38    |
| 3 | 20240207 | SHORT | +0.10%       | -0.14%         | STOP_LOSS   | -$508   |
| 4 | 20240212 | SHORT | +0.02%       | +1.06%         | TAKE_PROFIT | +$882   |
| 5 | 20240212 | SHORT | -0.03%       | +0.62%         | TAKE_PROFIT | +$575   |
| 6 | 20240212 | LONG  | +0.00%       | -0.44%         | STOP_LOSS   | +$332   |
| 7 | 20240704 | LONG  | -0.04%       | +0.56%         | STOP_LOSS   | -$872   |
| 8 | 20260109 | LONG  | -0.13%       | -1.19%         | STOP_LOSS   | +$1625  |

**Concentration temporelle** : 6 trades sur 8 en jan-fev 2024. Le trade #7
est le 4 juillet 2024 (ferie US, liquidite reduite). Le trade #8 est en
janvier 2026 — 18 mois plus tard.

**Heures** : entre 00h45 et 08h25 CT. Session asiatique/europeenne,
avant l'ouverture US.

**Le 12 fevrier 2024** porte 3 trades (37.5% du PnL) — veille du CPI US.
PA a bouge de +1% a -0.4% dans la meme session. Seul jour avec assez de
volatilite pour generer 3 signaux.

### Hypotheses invalidees

**Hypothese 1 : "GC/PA est structurellement different de ZC/ZW."**

INVALIDE. Le Sharpe +0.32 repose sur 2 jours sur 3 ans :
- 12 fevrier 2024 (veille CPI US) : 3 trades, PnL net = +$1 789
- 9 janvier 2026 : 1 trade, PnL net = +$1 625

Sans ces 2 jours, les 4 autres trades cumulent -$1 976. Le Sharpe serait
largement negatif. C'est du bruit sur un petit echantillon amplifie par
2 jours de volatilite exceptionnelle.

**Hypothese 2 : "Un TP en Z-score = un profit en dollars."**

INVALIDE. C'est le point le plus grave.
- Trade #1 : touche le TP (Z revient vers 0) mais perd $568
- Trade #8 : touche le SL (Z diverge a -4.03) mais gagne $1 625

Le Z-score et le PnL en dollars sont DECORRELES.

**Pourquoi cette decorrelation :**
- Le Z-score vit dans l'espace du spread : log_A - alpha - beta * log_B
- Le PnL vit dans l'espace dollar : delta_price_A * Q_A * mult_A
  - delta_price_B * Q_B * mult_B
- Le passage de l'un a l'autre depend du sizing beta-neutral, des
  multipliers, et de comment chaque leg bouge individuellement
- Un TP en Z-score signifie que le spread s'est resserre. Mais si GC monte
  de 2% et PA monte de 2.5%, le spread se resserre (TP touche) tandis que
  les deux legs ont bouge massivement — le PnL dollar depend de l'asymetrie
  des multipliers et du sizing, pas du mouvement du spread
- PA a un multiplier de 100 et un slippage RT de $100 (le plus eleve du
  portefeuille). Le cout RT du spread GC/PA est ~$128. Pour qu'un TP soit
  profitable, le mouvement de spread en dollars doit depasser $128

---

## 6. Bilan V2.1 et prochaine etape

### Ce qui fonctionne dans le pipeline

- Steps 2-3-4 : identification correcte des paires cointegrees
- Filtre de Kalman : beta dynamique, forme de Joseph, NIS stable
- Signal engine : arme, declenche, ferme mecaniquement
- sigma_rolling : debloque le Z-score (V2.1)

### Ce qui ne fonctionne pas

- La couche qui transforme un signal Z-score en un trade dollar-profitable
- Le Z-score est un bon detecteur d'excursions du spread, mais il n'a
  AUCUNE information sur le profit en dollars
- Le modele est aveugle aux couts et au dollar-move

### Prochaine etape : diagnostic "dollar viability"

Avant de continuer a optimiser des seuils (Bertram ou autre), il faut
repondre a la question fondamentale :

**Pour chaque paire, quel est le profit brut en dollars d'un aller-retour
typique du spread (entree a 2 sigma, sortie a 0.5 sigma) compare au cout RT ?**

- Si ratio < 1 : aucun seuil ne rendra la paire profitable
- Si ratio > 2 : il y a de la marge pour les couts et les faux signaux

Ce diagnostic "dollar viability" manque dans le pipeline. C'est un pre-filtre
qui doit etre construit AVANT toute optimisation de seuils.
