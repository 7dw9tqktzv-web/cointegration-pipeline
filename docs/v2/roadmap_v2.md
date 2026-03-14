# ROADMAP V2 — Pipeline Cointégration Mean Reversion

**Date** : 2026-03-13
**Prérequis** : V1 complète (214+ tests, pipeline step1→backtester validé)
**Données** : 3 ans d'historique (2023-03 → 2026-03), 7 paires CME

---

## BILAN V1 — Diagnostic

### Résultats Backtests Comparatifs

| Run | Calibration | MacKinnon | Armement | Sessions tradées | Trades | Sharpe |
|-----|------------|-----------|----------|-----------------|--------|--------|
| V1 baseline | 30j | 5% | 2.5σ | ~15% | 0 | — |
| Étape 2 | 60j | 5% | 2.5σ | ~20% | 0 | — |
| Étape 3 | 60j | 5% | 2.0σ | ~20% | 9 | négatif |
| Étape 4 | 60j | 10% | 2.0σ | ~53% | 9 | négatif |
| ZC/ZW 1.5σ | 60j | 10% | 1.5σ | — | 11 | -1.08 |

### Cause Racine Identifiée

σ_eq (écart-type stationnaire du processus OU) est calibré sur 60 jours de données
multi-session. Il capte la "respiration" multi-semaines du spread (~0.007 pour ZC/ZW).
En intraday, le spread bouge ~0.001-0.004 — le Z-score reste compressé entre -0.5 et
+0.5 toute la session. Les seuils d'armement à ±2.0σ_eq sont structurellement
inatteignables en une session.

### Insight Clé

**0 SESSION_CLOSE** sur le test ZC/ZW 1.5σ. Le spread BOUGE assez en intraday pour
toucher soit le TP soit le SL à chaque trade. Le problème n'est pas la vitesse de
retour (HL) mais la **qualité des entrées** (64% SL = faux signaux de mean reversion).

### Meilleurs Paramètres V1

```
calibration_window = 60 sessions
mackinnon_level = "10%"
armement = 2.0σ_eq
trigger = 2.0σ_eq
tp = 0.5σ_eq
sl = 3.0σ_eq
```

---

## V2.1 — σ_rolling : Normalisation Adaptative Intraday

**Priorité** : IMMÉDIATE
**Impact attendu** : Résout le goulet principal (Z-score compressé)
**Fichiers modifiés** : `src/step5_engine.py` uniquement

### Principe

Remplacer σ_eq (fixe pour toute la session) par un estimateur de volatilité
glissant recalculé à chaque barre :

```
V1 : Z_t = (Spread_t − θ_OU) / σ_eq           ← fixe, calibré sur 60j
V2 : Z_t = (Spread_t − θ_OU) / σ_rolling_t     ← dynamique, recalculé chaque barre
```

### Ce qui change

- `compute_signal()` dans step5_engine.py utilise σ_rolling au lieu de σ_eq
- σ_rolling = std(spread) sur les N dernières barres de la session en cours
- Nouvelle donnée dans BarState_t : `sigma_rolling`

### Ce qui NE change PAS

- Calibration steps 2-3-4 (OLS, AR(1), paramètres OU)
- Filtre de Kalman (Phase 3)
- Filtres A/B/C (Phase 4)
- Sizing beta-neutral (Phase 5)
- Backtester (PnL, coûts, métriques)
- σ_eq reste dans le dict step4 pour diagnostic

### Paramètres à tester

- Fenêtre rolling : 20, 40, 60 barres (std plat)
- Alternative : EWMA avec span 20, 40, 60
- Seuils d'armement : garder 2.0σ initialement (le σ a changé, pas les seuils)

### Burn-in en début de session

Les premières barres n'ont pas assez d'historique pour un std fiable.
Le trader n'intervient qu'à 01h00 CT (barre ~90). À ce stade, σ_rolling
a 90 barres d'historique — suffisant. Utiliser σ_eq comme fallback avant
d'avoir N barres.

### Critère de succès

- Nombre de trades > 50 sur 3 ans par paire (vs 0-3 en V1)
- Ratio TP/SL > 1.0 (vs 0.57 en V1 à 1.5σ)
- Sharpe_1.5x > 0 sur au moins 3 paires

---

## V2.2 — Frontières de Bertram : Seuils Optimaux

**Priorité** : HAUTE (après V2.1)
**Impact attendu** : Remplace les seuils heuristiques par des seuils mathématiquement optimaux
**Prérequis** : V2.1 doit produire assez de trades pour valider l'amélioration

### Principe

Bertram (2010) résout le problème d'arrêt optimal pour un processus OU :
trouver le seuil d'entrée `a` qui maximise le profit espéré par unité de temps.

```
a_optimal = f(κ, σ, coûts_transaction)
```

Le seuil optimal dépend de la paire (via κ et σ) et des coûts. Il n'est plus
heuristique (2.0σ pour tout le monde) mais adapté à chaque paire à chaque session.

### Ce qui change

- Calcul de `a_optimal` dans step4_ou.py ou dans un nouveau module
- Seuils d'armement, trigger, TP, SL deviennent dynamiques par paire/session
- La machine à états dans step5_engine.py lit les seuils depuis step4 au lieu de constantes

### Références

- Bertram, W. (2010) — "Analytic solutions for optimal statistical arbitrage trading"
- PDF de référence du projet : section "Frontière de Bertram"

---

## V2.3 — MLE pour Paramètres OU

**Priorité** : MOYENNE
**Impact attendu** : Estimation plus précise de κ, θ, σ → HL potentiellement différent
**Fichiers modifiés** : `src/step4_ou.py`

### Principe

Remplacer la conversion AR(1) → OU (méthode des moments) par une estimation
directe par maximum de vraisemblance sur la densité de transition OU :

```
X_t | X_{t-1} ~ N(X_{t-1} × e^{-κdt} + θ(1 - e^{-κdt}), σ²/(2κ) × (1 - e^{-2κdt}))
```

La log-vraisemblance est analytique. Optimisation via `scipy.optimize.minimize`.

### Motivation

La méthode des moments (AR(1)) est biaisée par l'autocorrélation des résidus
sur barres 5min (point identifié en V1). Le MLE est moins sensible à ce biais.
Si κ_MLE > κ_moments → HL plus court → potentiellement plus compatible avec l'intraday.

### Ce qui NE change PAS

- Steps 1-3 (data, stationnarité, cointégration)
- Step 5 (engine, risk, sizing)
- La conversion AR(1) reste disponible comme fallback/comparaison

---

## V2.4 — Sizing OLS vs Kalman selon R²

**Priorité** : BASSE
**Impact attendu** : Réduction du bruit de sizing quand β est stable
**Fichiers modifiés** : `src/step5_sizing.py`

### Principe

Si R² > seuil (ex: 0.95) et CV(β) < seuil (ex: 5%), utiliser β_OLS fixe
pour le sizing au lieu de β_Kalman (bruité barre par barre).

```python
if step4_result["r_squared"] > 0.95 and stability["cv_beta"] < 0.05:
    beta_sizing = step4_result["beta_ols"]
else:
    beta_sizing = bar_state["beta_kalman"]
```

### Motivation

Le Kalman est utile quand β dérive. Quand β est stable, il ajoute du bruit
sans valeur ajoutée. Le sizing serait plus propre avec β_OLS fixe.

---

## V2.5 — Calibration Q/R via Algorithme EM

**Priorité** : BASSE, RISQUÉE
**Impact attendu** : Q et R optimisés sur les données au lieu de tables fixes
**Fichiers modifiés** : `config/contracts.py` (ou nouveau module calibration)

### Principe

Utiliser `pykalman.em()` pour estimer Q et R simultanément à partir des données
de calibration au lieu des valeurs fixes par classe.

### Risques

- Convergence vers un minimum local
- Q estimé très différent de la table → filtre instable
- Nécessite des contraintes (bornes sur Q, R borné par resid_var)

### Trigger

β_Kalman trop figé (ne s'adapte pas) ou trop réactif (oscille) en backtest.
Actuellement non observé — 0 SORTIE_FORCEE en V1.

---

## V2.6 — Sizing par Volatilité Implicite

**Priorité** : REPORTÉE (dépendance infrastructure)
**Impact attendu** : Sizing réduit en régime de haute volatilité

### Principe

```
sizing_mult = 1 / (VI_ATM / VI_médiane_30j)
```

Réduit la taille quand la VI est haute (marché stressé), augmente quand elle
est basse (marché calme).

### Prérequis

- API IBKR TWS pour récupérer la VI ATM des options sur futures
- Historique VI pour calculer la médiane 30j
- Infrastructure de collecte de données en temps réel

### Trigger

Drawdown en régime de haute volatilité détecté en backtest.

---

## V2.7 — Filtre C Progressif (Barre par Barre)

**Priorité** : REPORTÉE
**Impact attendu** : Moins de sessions tuées en début de session

### Principe

```
seuil_C_t = 4 × √(t × Q_β)    # t = numéro de barre dans la session
```

Le seuil grandit avec le temps dans la session. En début de session (t petit),
le seuil est serré — normal car β_Kalman n'a pas encore eu le temps de dériver.
En fin de session (t = 264), le seuil est celui de la V1.

### Trigger

Taux de SORTIE_FORCEE > 15% en backtest. Non observé en V1 (0 SORTIE_FORCEE).

---

## ITEMS V3 (POUR MÉMOIRE, PAS D'ACTION)

| Item | Description | Prérequis |
|------|------------|-----------|
| σ_spread_implicite | VI des legs → diagnostic forward-looking | IBKR API VI ATM |
| VWAP tick PA/PL | Remplacer Typical Price par VWAP tick | Export tick Sierra Chart |
| Debounce sorties | Z < 0.5 pendant 2-3 barres avant TP | Oscillations en backtest |
| HMM régimes | Hidden Markov pour détecter changements Q/R | Assez de trades pour calibrer |
| Processus de Lévy | Sauts au lieu du brownien standard | Tails observées en backtest |
| Clustering paires | ML pour sélection de paires non-linéaire | Univers élargi > 20 paires |

---

## ORDRE D'EXÉCUTION

```
V2.1 σ_rolling     → MAINTENANT
V2.2 Bertram        → quand V2.1 produit des trades
V2.3 MLE OU         → quand on veut affiner κ/HL
V2.4 Sizing OLS/KF  → quand on veut réduire le bruit de sizing
V2.5 EM Q/R         → quand le Kalman pose problème
V2.6 Sizing VI      → quand l'infra IBKR est prête
V2.7 Filtre C prog  → quand SORTIE_FORCEE > 15%
```

Chaque item est testé isolément par backtest comparatif.
Un seul changement par backtest. Toujours comparer à la baseline précédente.
