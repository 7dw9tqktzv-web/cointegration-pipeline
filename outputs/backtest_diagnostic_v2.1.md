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
- **GC/PA : premier Sharpe positif du projet (+0.32)**, robuste au slippage
- **0 SESSION_CLOSE** : le spread a assez de volatilite intraday pour toucher TP ou SL

### Ce qui ne fonctionne pas encore
- **ZC/ZW : 33 trades mais Sharpe -2.20** — WR 52% mais ratio W/L = 0.6 (les SL coutent plus que les TP)
- **3 paires a 0 trades** (GC/SI, NQ/RTY, CL/HO) — le spread intraday reste trop stable meme normalise par sigma_rolling
- **Blocage principal : cointegration_blocking** (MacKinnon) — 60-70% des sessions skippees

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
| Sharpe positif       | 0 paires      | 1 (GC/PA)   |
| SESSION_CLOSE rate   | 0%            | 0%          |

---

## 4. Pistes pour la suite

- **V2.2 Bertram** : seuils optimaux par paire (a_optimal = f(kappa, sigma, couts)) — potentiellement mieux que 2.0 sigma fixe
- **Investiguer le ratio W/L sur ZC/ZW** : les SL coutent 1.7x plus que les TP en moyenne
- **cointegration_blocking** : MacKinnon 10% reste trop restrictif pour GC/SI, NQ/RTY, CL/HO — a revisiter ?
