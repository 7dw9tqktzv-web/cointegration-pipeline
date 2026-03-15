# ROADMAP V2.3+ — Plan Complet des Prochaines Versions

**Date** : 2026-03-14
**Contexte** : V2.2 en cours d'optimisation (Z intraday validé, 4000+ trades, NQ/RTY et GC/SI prometteurs)
**Source** : Discussion d'audit complète V2.1 → V2.2

---

## V2.2 — EN COURS (finir d'abord)

### Statut : implémenté, en phase d'optimisation SL

### Reste à faire

- Analyse MAE/MFE post-entrée sur NQ/RTY et GC/SI
- Série 2 SL (2.0σ, 2.5σ, 3.0σ) guidée par les données MAE
- Test Z = 2.5 sur GC/SI
- Ajouter scénario Sharpe_0.5x (demi-slippage) pour paires liquides en session US
- Verdict final : Sharpe positif ou pas

### Acquis V2.2

- Z intraday auto-cohérent : mean=0.02, std=1.29, borné ±4.2
- Architecture bi-couche validée (cointégration long terme + signal intraday)
- Sortie en spread-space avec références figées à l'entrée
- 4000+ trades sur 5 paires (vs 6 avant fix T_limite + filtre C)
- NQ/RTY : Sharpe -0.10, avgTP +$146 (quasi break-even)
- GC/SI : avgTP +$172, signal fort mais SL coûteux (-$290)

---

## V2.3 — FENÊTRES DÉCOUPLÉES + FILTRES + UNIVERS

### Objectif
Plus de sessions tradées par paire, plus de paires dans l'univers.
C'est le levier principal pour le volume de trades.

### Fenêtres découplées

**Fenêtre longue (130-260 sessions) :**
- Steps 2-3 : validation cointégration (I(1) + MacKinnon)
- Plus de puissance statistique → moins de faux positifs
- Recalcul hebdomadaire ou mensuel
- Justification : la cointégration est structurelle, ne change pas en 24h

**Fenêtre courte (30 sessions) :**
- OLS : β_OLS, α_OLS frais pour le calcul du spread
- OU : θ_OU, σ_eq frais pour le biais directionnel
- Recalcul chaque session (fenêtre glissante)

**Justification du découplage :**
β_OLS sur 60 sessions est stale. Bug observé en V2.2 : β_OLS = 0.19
vs réalité = 0.68 sur NQ/RTY. Le Kalman corrigeait massivement à la
barre 0, déclenchant le filtre C. 30 sessions donne un β plus frais,
130+ sessions donne un test de cointégration plus robuste. Chaque
fenêtre est optimisée pour sa question.

### Assouplissement MacKinnon

- MacKinnon 15% voire 20% sur fenêtre longue
- Justifié par la puissance statistique accrue (plus de données)
- Actuellement 60-70% des sessions bloquées par MacKinnon 10%
- Potentiel : récupérer 15-25% de sessions supplémentaires
- Tester d'abord sur GC/SI (la paire la plus prometteuse, 437/717 bloquées)
- Mesurer : est-ce que les sessions récupérées produisent des trades profitables ?

### Test du biais directionnel

- Actuellement élimine ~50% des signaux (par construction)
- Tester sans biais pour voir si les trades "dans le mauvais sens" sont vraiment perdants
- Peut-être que le biais est trop conservateur pour certaines paires
- Si les trades sans biais ont un Sharpe similaire → assouplir ou supprimer
- Si les trades sans biais ont un Sharpe nettement pire → garder le filtre

### Élargissement univers

**Nouvelles paires à tester :**
- Metals : GC/HG (or/cuivre)
- Energy : CL/RB (pétrole/essence)
- Indices : NQ/ES (Nasdaq/S&P)
- Grains : ZC/ZS (maïs/soja), ZW/ZS (blé/soja)
- Chaque paire passe le triple filtre : cointégration + HL_exploitable + sizing résidu
- Objectif : 15 paires × 100 trades > 5 paires × 200 trades

**Paires existantes en micro-contrats :**
- ZC/ZW en MZC/MZW : coûts RT ~$13 au lieu de $61, avgTP de -$39 → potentiellement +$9
- YM/RTY en MYM/M2K : avgTP de +$3 en standard → potentiellement viable en micro
- Tester si la réduction de coûts bascule la viabilité

### Recalibration HL_exploitable avec seuil 2σ

- On trade des excursions à 2σ, pas 1σ
- Le HL_exploitable actuel est mesuré sur des excursions de 1σ → 0.25σ
- Le HL à 2σ sera plus long → N plus grand → T_limite plus strict
- Les N actuels (20, 24, 40) sont peut-être sous-estimés
- À refaire avant de fixer les paramètres définitifs V2.3

---

## V2.4 — SIZING OPTIMISÉ

### Objectif
Réduire le résidu de sizing, réintégrer des paires exclues.

### Optimiseur de combinaison

Le sizing actuel est naïf : Leg A = 1 contrat standard, Leg B ajustée.
L'optimiseur teste toutes les combinaisons :

```
(Q_A_std, Q_A_micro, Q_B_std, Q_B_micro)
```

Minimise : |target_notional_B - actual_notional_B| / target_notional_B
Avec contrainte : notional_max (risque par trade)

Exemples :
- 2 CL vs 1 HO peut donner un meilleur ratio que 1 vs 1
- 1 GC + 1 MGC vs X SIL peut réduire le résidu GC/SI de 22% à 5%
- 2 GC vs 1 PA peut donner un résidu de 5% au lieu de 45%

### Paires réintégrables

| Paire | Résidu actuel | Résidu potentiel | Méthode |
|-------|--------------|------------------|---------|
| GC/PA | 45% | ~5% | Tester combinaison 2×1 ou 1 GC vs 1 PA |
| CL/HO | 148% | ~15% | Tester 2 CL vs 1 HO |
| GC/SI | 22% | ~8% | Utiliser micros MGC/SIL |

### Ratio multiplicatif

- Tester plusieurs multiples pour approcher 0% de résidu
- Pas de Leg A fixe à 1 standard — la meilleure combinaison gagne
- Contrainte : notional max pour le risque

### Sizing β_OLS vs β_Kalman

- Actuellement identiques (diff < 1.6%) sur toutes les paires testées
- Le switch adaptatif basé sur R² et CV(β) est inutile maintenant
- Règle prévue : R² > 0.95 et CV(β) < 5% → β_OLS, sinon β_Kalman
- À revisiter si nouvelles paires (V2.3) ont un β instable

---

## V2.5 — CALIBRATION Q/R DU FILTRE DE KALMAN

### Objectif
Q et R optimisés sur les données, pas fixés par classe d'actifs.

### Situation actuelle

```
Q = fixe par classe :
    Metals:       (1e-6, 1e-7)
    Equity Index: (2e-6, 2e-7)
    Grains:       (2e-6, 2e-7)
    Energy:       (5e-6, 5e-7)

R = resid_var de step3 (data-driven mais hors Kalman)
```

Q contrôle combien β_Kalman peut bouger d'une barre à l'autre.
- Q trop petit → β figé, Kalman n'adapte pas
- Q trop grand → β oscille, sizing bruité
- Valeurs actuelles choisies par ordre de grandeur, pas optimisées

### Méthode 1 — Algorithme EM (pykalman.em)

```python
from pykalman import KalmanFilter
kf = KalmanFilter(
    transition_matrices=np.eye(2),
    observation_matrices=obs_mat,
    initial_state_mean=[alpha_ols, beta_ols],
)
kf_em = kf.em(observations, n_iter=20)
# kf_em.transition_covariance = Q optimal
# kf_em.observation_covariance = R optimal
```

- Simple à implémenter
- Risque : convergence minimum local, Q aberrant

### Méthode 2 — MLE sur les innovations (RECOMMANDÉ)

```
LL(Q, R) = -0.5 × Σ [ln(S_t) + e_t² / S_t]
```

- Optimisation scipy.optimize.minimize
- Avantage : contraintes sur Q_min, Q_max, R > 0
- Plus contrôlé que l'EM
- Calibrer sur fenêtre courte (30 sessions de V2.3)

### Trigger

- β_Kalman trop figé (ne s'adapte pas aux changements)
- Ou β_Kalman trop réactif (oscille barre par barre)
- Actuellement non observé (β_Kalman ≈ β_OLS)
- Devient pertinent si univers élargi inclut des paires instables

---

## V2.6 — MLE POUR PARAMÈTRES OU

### Objectif
κ, θ, σ estimés par maximum de vraisemblance au lieu de la méthode des moments.

### Situation actuelle

Méthode des moments : régression AR(1) sur le spread, conversion φ = e^{-κdt}.
Approximation, potentiellement biaisée par l'autocorrélation des résidus 5min.

### MLE direct

Densité de transition OU analytique :
```
X_t | X_{t-1} ~ N(
    X_{t-1} × e^{-κdt} + θ(1 - e^{-κdt}),
    σ² / (2κ) × (1 - e^{-2κdt})
)
```

Log-vraisemblance analytique → scipy.optimize.minimize.
Initialisation par méthode des moments (stratégie hybride MoM → MLE).

### Utilité

- κ_intraday plus précis si estimé par MLE sur données empilées intra-session
- Alimente Bertram (V2.7) qui a besoin de κ et σ précis
- θ_OU plus précis pour le biais directionnel

### Priorité basse

La méthode des moments donne des résultats très proches du MLE
(vidéo de recherche : θ_MoM = 2.008, θ_MLE = 2.008).
Devient utile principalement si Bertram est implémenté.

---

## V2.7 — BERTRAM (SEUILS OPTIMAUX)

### Objectif
Seuils d'entrée/sortie mathématiquement optimaux par paire, par session.

### Formule Bertram

```
a_optimal = f(κ, σ, coûts_transaction)
```

Maximise le profit espéré par unité de temps pour un processus OU
avec des coûts de transaction. Solution analytique fermée.

### Prérequis

- κ_intraday fiable (V2.6 MLE ou HL_exploitable empirique)
- σ_rolling fiable (V2.2 résolu)
- Signal profitable (V2.2 en cours de validation)
- Point de cohérence : κ et σ doivent correspondre au même objet
  (κ_intraday pour un Z intraday, pas κ multi-jour)

### Ce qui change

- Seuils d'entrée variables par paire et par session
- Plus de ±2.0σ fixe pour tout le monde
- TP et SL deviennent dynamiques, adaptés aux caractéristiques de chaque paire

### Conditionnel

N'implémenter que si V2.2 a un setup profitable. Bertram optimise un
signal qui marche, il ne crée pas un signal à partir de rien.

---

## V3 — INFRASTRUCTURE AVANCÉE (POUR MÉMOIRE)

### Score de cointégration

- Agrégation multi-critères : p-value MacKinnon, CV(β), ratio variance, HL, θ_OU
- Score 0-100%
- 80%+ : taille pleine, 50-80% : taille réduite, <50% : watchlist
- Poids fixés a priori, pas optimisés sur les données (anti-overfitting)
- Garde-fou : un spread non-stationnaire ne se sauve pas avec un bon CV(β)
- La p-value reste binaire à un seuil, pas transformée en score continu

### Sizing par volatilité implicite

```
sizing_mult = 1 / (VI_ATM / VI_médiane_30j)
```

- Réduit la taille en régime haute vol, augmente en basse vol
- Prérequis : API IBKR TWS pour VI ATM des options sur futures
- Historique VI pour calculer la médiane 30j

### σ_spread_implicite

- VI des legs → diagnostic forward-looking
- Prérequis : IBKR API VI ATM

### Filtre C progressif

```
seuil_C_t = 4 × √(t × Q_β)
```

- Seuil croissant dans la session (t = numéro de barre)
- En début de session, seuil serré (β n'a pas eu le temps de dériver)
- En fin de session, seuil = celui de la V1
- Trigger : SORTIE_FORCEE > 15% en backtest (pas observé actuellement)

### HMM régimes

- Hidden Markov Models pour détecter changements Q/R en temps réel
- Anticiper les changements de régime (haute vol, basse vol)
- Prérequis : assez de trades pour calibrer les transitions

### Debounce sorties

- Z < 0.5 pendant 2-3 barres consécutives avant de confirmer le TP
- Évite les faux TP par oscillation autour du seuil
- Trigger : oscillations observées en backtest

### Scénario coûts réduits

- Sharpe_0.5x (demi-slippage) pour paires liquides en session US
- Les coûts actuels (2 ticks slippage par jambe) sont conservateurs
- NQ/RTY en session US : probablement 1 tick de slippage max
- Si Sharpe_0.5x > 0 sur NQ/RTY, la paire est viable en conditions réelles
- Aussi pertinent pour GC/SI en session US

### VWAP tick PA/PL

- Remplacer Typical Price par VWAP tick pour les actifs moins liquides
- Prérequis : export tick Sierra Chart
- Impact sur le spread calculé et donc sur le signal

### Processus de Lévy

- Sauts au lieu du brownien standard dans le modèle OU
- Capture les discontinuités de prix (annonces macro, etc.)
- Prérequis : queues épaisses observées en backtest (kurtosis élevé)

### Clustering paires

- ML pour sélection de paires non-linéaire
- Dépasse l'approche manuelle actuelle (7 paires choisies par secteur)
- Prérequis : univers élargi > 20 paires

---

## ORDRE D'EXÉCUTION GLOBAL

```
V2.2  Finir optimisation SL → verdict Sharpe      ← MAINTENANT
V2.3  Fenêtres + filtres + univers                 ← Prochain
V2.4  Sizing optimisé                              ← Quand paires exclues manquent
V2.5  Calibration Q/R Kalman                       ← Quand β pose problème
V2.6  MLE paramètres OU                            ← Quand Bertram est envisagé
V2.7  Bertram seuils optimaux                      ← Quand signal profitable confirmé
V3    Infrastructure avancée                        ← Quand pipeline stabilisé
```

Chaque version est testée isolément par backtest comparatif.
Un seul changement majeur par version.
Toujours comparer à la baseline de la version précédente.
