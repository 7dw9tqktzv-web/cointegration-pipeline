# BRIEFING V2.2 — Z-Score Intraday : Architecture Bi-Couche

**Date** : 2026-03-14
**Source de vérité** : Discussion d'audit V2.1 + `docs/v2/roadmap_v2.md`
**Baseline** : V2.1 (σ_rolling window=20) — 45 trades, 1 paire Sharpe positif (GC/PA +0.32)
**Problème résolu** : Incohérence structurelle du Z-score V1/V2.1

---

## DIAGNOSTIC V2.1 — POURQUOI ON CHANGE

### Le Z-score V2.1 est structurellement cassé

La formule V2.1 :

```
Z_t = (Spread_t − θ_OU) / σ_rolling_t
```

Mélange deux échelles temporelles incompatibles :

- **Numérateur** : `Spread_t − θ_OU` mesure la distance à l'équilibre **multi-semaines** (θ_OU calibré sur 60 sessions = 12 semaines)
- **Dénominateur** : `σ_rolling_t` mesure la volatilité **des 100 dernières minutes** (20 barres × 5min)

### Conséquences observées en backtest

**Z-scores explosifs** : trade #29 ZC/ZW atteint Z = +22.4. Le spread n'a pas bougé — c'est σ_rolling qui collapse (de 0.0058 à 0.0007, facteur 8×). Le spread est stable loin de θ_OU, les 20 dernières barres sont quasi-constantes → std → 0 → Z → ∞.

**Faux SL** : des trades touchent le SL à 3.0σ non pas parce que le spread diverge, mais parce que σ_rolling collapse et le Z gonfle artificiellement.

**MFE/MAE non fiables** : le MFE médian de 3.7σ et le MAE médian de 5.1σ sont gonflés par le même mécanisme. Les chiffres en σ_rolling ne sont pas comparables entre trades.

**Z d'entrée dégradé** : Z médian d'entrée à -0.72 au lieu de -2.0. Le arm-then-trigger laisse le spread revert de 1.3σ avant l'entrée. Combiné aux coûts de transaction, les TP sont négatifs en dollars (-$32 en moyenne sur ZC/ZW).

### Diagnostic V1 aggravant

Le Z-score V1 (`Z = (Spread − θ_OU) / σ_eq`) passe 40% du temps au-dessus de |Z| ≥ 3 sur ZC/ZW. Moyenne à -12.5, minimum à -79. La distribution n'est pas N(0,1) — c'est un spread qui dérive structurellement loin de θ_OU pendant des semaines. Le modèle OU est vrai sur 60 jours (le spread revient) mais faux sur 1 jour (le spread reste coincé d'un côté).

### Conclusion

L'hypothèse centrale V1 — "si la paire est cointégrée sur 60 jours, le spread mean-reverte assez vite pour être tradé en intraday" — est invalidée. La cointégration garantit le retour, pas la vitesse du retour. Le signal intraday doit vivre dans un espace complètement séparé du modèle OU long terme.

---

## ARCHITECTURE V2.2 — DEUX COUCHES

### Principe

Séparer explicitement deux fonctions :

1. **Couche 1 — Éligibilité** (horizon semaines) : "cette paire a-t-elle une relation d'équilibre structurelle ?"
2. **Couche 2 — Signal intraday** (horizon heures) : "le spread vient-il de faire un mouvement anormal qui va se corriger ?"

Les deux couches utilisent des paramètres à des échelles temporelles différentes. Aucun paramètre ne traverse les couches sauf le biais directionnel (liaison couche 1 → couche 2).

---

## COUCHE 1 — ÉLIGIBILITÉ DE LA PAIRE

### Ce qui existe et reste inchangé

| Composant | Rôle | Statut V2.2 |
|-----------|------|-------------|
| Step 2 (I(1)) | Vérifier que chaque actif est I(1) | **Inchangé** |
| Step 3 — OLS | β_OLS, α_OLS, stabilité β | **Inchangé** |
| Step 3 — AR(1) + t_DF | Test de cointégration MacKinnon | **Inchangé** |
| Step 4 — paramètres OU | κ, θ_OU, σ_eq, HL | **Rôle réduit** (voir ci-dessous) |

### Changement de rôle des paramètres OU

| Paramètre | Rôle V1/V2.1 | Rôle V2.2 |
|-----------|-------------|-----------|
| φ, t_DF | Test de cointégration | **Inchangé** — filtre d'éligibilité |
| β_OLS | Ancrage sizing + spread | **Inchangé** — calcul du spread |
| θ_OU | Centre du Z-score | **Biais directionnel** — filtre de direction |
| σ_eq | Dénominateur du Z-score | **Diagnostic** — référence de volatilité |
| κ, HL | T_limite + seuils Bertram | **Garde-fou** — remplacé par HL_intraday |

### Nouveau composant : validation intraday (couche intermédiaire)

La cointégration sur 60 jours ne garantit pas la mean-reversion intraday. Un nouveau diagnostic est nécessaire.

**HL_empirique_intraday** : pour chaque session, centrer le spread par sa moyenne de session, mesurer les temps de traversée de zéro. La médiane donne le HL intraday réel.

```
Pour chaque session s des 20 dernières sessions :
    spread_centré_s = spread_s − mean(spread_s)
    traversées_s = temps entre chaque franchissement de zéro
HL_intraday = médiane(toutes les traversées)
```

**Filtre go/no-go** : si HL_intraday > 132 barres (demi-session, ~11 heures), la paire ne mean-reverte pas assez vite en intraday. Pas de trading.

**Filtre de sizing réalisable** : vérifier que le résidu du sizing beta-neutral est acceptable.

```
résidu_sizing = |target_notional_B − actual_notional_B| / target_notional_B
Si résidu_sizing > 20% → paire dégradée
```

Les paires sans micro-contrat sur une leg (PA, HO) sont structurellement contraintes.

### Fréquence de recalcul

Hebdomadaire. La cointégration sur 60 jours ne change pas en 24 heures. Recalculer chaque lundi donne un "bulletin de santé" stable par paire.

---

## COUCHE 2 — SIGNAL INTRADAY

### Le Z-score intraday

```
μ_rolling_t = moyenne(Spread sur les N dernières barres de la session)
σ_rolling_t = écart-type(Spread sur les N dernières barres de la session)
Z_intraday_t = (Spread_t − μ_rolling_t) / σ_rolling_t
```

**Propriétés clés :**

- μ et σ sont estimés sur **la même fenêtre** → Z auto-cohérent
- Z mécaniquement borné — si le spread dérive, μ_rolling suit, le numérateur reste petit
- Z = ±2.0 est un événement à ~5% (distribution approximativement normale par construction)
- Pas de dépendance à θ_OU, σ_eq, ou tout paramètre OU
- Pas d'hypothèse de modèle (non-paramétrique)

### Paramètre N (fenêtre rolling)

| N | Horizon | Caractère |
|---|---------|-----------|
| 12 barres | 1 heure | Très réactif, beaucoup de signaux, bruités |
| 20 barres | 1h40 | Compromis (baseline V2.1) |
| 24 barres | 2 heures | Plus stable, moins de signaux, plus fiables |

À tester. Le choix de N ne casse pas le modèle (contrairement à V2.1) — il change l'horizon du signal.

### Burn-in

Pendant les N premières barres de session, pas assez d'historique. Deux options :

- **Pas de signal** pendant le burn-in (le trader n'intervient qu'à 01h00 CT = barre ~90, bien après le burn-in)
- **σ_eq comme fallback** pour σ_rolling + **μ_rolling calculé sur ce qui est disponible**

Option recommandée : pas de signal pendant le burn-in. Simplification maximale, aucun risque de faux signal.

### Biais directionnel (liaison couche 1 → couche 2)

À l'ouverture de session, calculer :

```
Z_LT = (Spread_ouverture − θ_OU) / σ_eq
```

Ce Z_LT utilise les paramètres OU de la couche 1 (calibrés sur 60 sessions). Il mesure le positionnement structurel du spread.

| Z_LT | Interprétation | Filtre |
|------|----------------|--------|
| Z_LT > 0 | Spread au-dessus de l'équilibre long terme | **SHORT seulement** |
| Z_LT < 0 | Spread en dessous de l'équilibre long terme | **LONG seulement** |

Seules les excursions intraday dans le sens du retour long terme sont tradées. Un Z_intraday SHORT quand le spread est structurellement bas (Z_LT < 0) est ignoré — il va contre la tendance de fond.

### Règles d'entrée

**Entrée directe au premier franchissement de Z_intraday = ±2.0.** Pas de double-check arm-then-trigger.

Justification : l'analyse MFE a montré que le Z d'entrée médian était à -0.72 avec le arm-then-trigger. Le spread avait déjà revert de 1.3σ avant l'entrée, consommant la majorité du profit. L'entrée directe capture le mouvement dès qu'il se produit.

Le risque (entrée dans un spread qui continue à diverger) est borné par le SL.

```
Conditions d'entrée :
1. Session passée en couche 1 (cointégration validée)
2. HL_intraday < 132 barres (mean-reversion intraday confirmée)
3. Biais directionnel respecté (Z_LT filtre la direction)
4. |Z_intraday| ≥ 2.0 (excursion locale significative)
5. Barre actuelle < T_limite (basé sur HL_intraday)
6. Filtres risque A/B/C OK
7. Sizing valide (résidu < 20%)
```

### Règles de sortie

**Pour les premiers tests — règles simples :**

| Motif | Condition | Justification |
|-------|-----------|---------------|
| **TAKE_PROFIT** | Z_intraday repasse 0 | Full mean-reversion locale |
| **STOP_LOSS** | \|Z_intraday\| ≥ 3.0 depuis l'entrée | Excursion adverse extrême |
| **SESSION_CLOSE** | Barre ≥ 15h25 CT | Fin de session |

Le TP à Z = 0 (au lieu de 0.5) capture le retour complet à la moyenne locale. C'est la sortie naturelle d'une stratégie de mean-reversion : on entre quand le spread s'écarte, on sort quand il revient.

Le SL à 3.0σ_intraday est un vrai 3σ cette fois — un événement à ~0.3%, pas un artefact de σ_rolling collapse.

**Après les premiers tests**, les seuils seront affinés par l'analyse MFE/MAE sur le Z intraday propre (données fiables cette fois).

### T_limite

```
T_limite = min(T_close_session − HL_intraday × 5min, T_close_pit)
```

Basé sur HL_intraday (mesuré en couche intermédiaire), pas sur HL multi-jour.

### Sizing

β_Kalman pour le hedge dynamique (inchangé). Le switch éventuel vers β_OLS quand β est stable est reporté à V2.4 selon la roadmap.

---

## CE QUI CHANGE DANS LE CODE

### `src/step5_engine.py` — compute_signal

**AVANT (V2.1) :**
```python
z = (spread - theta_ou) / sigma_rolling
```

**APRÈS (V2.2) :**
```python
spread_history = session_state["spread_history"]
window = session_state["sigma_rolling_window"]

if len(spread_history) >= window:
    mu_rolling = float(np.mean(spread_history[-window:]))
    sigma_rolling = float(np.std(spread_history[-window:], ddof=1))
    sigma_rolling = max(sigma_rolling, 1e-10)
    z = (spread - mu_rolling) / sigma_rolling
else:
    z = 0.0  # burn-in : pas de signal
```

### `src/step5_engine.py` — machine à états

Suppression du arm-then-trigger. Entrée directe au franchissement.

**AVANT (V2.1) :**
```python
# Armement à ±2.0, puis trigger au retour
if z < -2.0 and z >= -3.0:
    session_state["is_armed_long"] = True
# ... puis déclenchement quand z > -2.0 et is_armed_long
```

**APRÈS (V2.2) :**
```python
# Entrée directe au franchissement
if position is None and not session_killed:
    if z <= -2.0 and bias == "LONG":
        signal = "ENTRY_LONG"
    elif z >= 2.0 and bias == "SHORT":
        signal = "ENTRY_SHORT"
```

### `src/step5_engine.py` — init_session

Ajout du biais directionnel et suppression des flags d'armement.

```python
# Biais directionnel
spread_open = log(price_a_open) - alpha_ols - beta_ols * log(price_b_open)
z_lt = (spread_open - theta_ou) / sigma_eq
session_state["bias"] = "SHORT" if z_lt > 0 else "LONG"

# Supprimé : is_armed_long, is_armed_short
```

### `src/step5_engine.py` — seuil de sortie TP

**AVANT :** `abs(z) < 0.5`
**APRÈS :** Z repasse 0 dans le sens du retour

```python
if position == "LONG" and z >= 0.0:
    signal = "TP"
elif position == "SHORT" and z <= 0.0:
    signal = "TP"
```

### Nouveau diagnostic : HL_intraday

Nouveau fichier ou ajout dans step4_ou.py :

```python
def compute_hl_intraday(df_a_calib, df_b_calib, step3_result, n_recent=20):
    """Mesure le HL empirique intraday sur les N sessions récentes.

    Pour chaque session :
    1. Calculer le spread
    2. Centrer par la moyenne de session
    3. Compter les traversées de zéro
    4. Mesurer les temps entre traversées

    Output: HL_intraday en barres (médiane des temps de traversée)
    """
```

---

## CE QUI NE CHANGE PAS

- Steps 1-2-3 : data, stationnarité, cointégration
- Step 4 : paramètres OU (rôle réduit mais calcul inchangé)
- Filtre de Kalman : β dynamique pour le sizing
- Filtres de risque A/B/C
- Sizing beta-neutral (step5_sizing.py)
- Backtester : PnL, coûts, métriques
- Les 7 interdictions (sauf #2 mise à jour)
- Les 7 invariants

### Mise à jour Interdiction #2

**AVANT :** "Jamais σ_diffusion comme dénominateur du Z-score — utiliser σ_eq (V1) ou σ_rolling (V2)"
**APRÈS :** "Jamais σ_diffusion ni σ_eq comme dénominateur du Z-score intraday — utiliser σ_rolling calculé sur la même fenêtre que μ_rolling"

---

## TESTS À ÉCRIRE

### Tests unitaires Z-score intraday

- Z = 0 quand spread = μ_rolling (par construction)
- |Z| borné : sur un spread OU simulé, vérifier que |Z| < 5 sur 99%+ des barres
- Burn-in : Z = 0 quand historique < window
- σ_rolling et μ_rolling calculés sur la même fenêtre

### Tests du biais directionnel

- Z_LT > 0 → bias = "SHORT"
- Z_LT < 0 → bias = "LONG"
- Entrée LONG bloquée quand bias = "SHORT"

### Tests d'entrée directe

- Entrée se déclenche au premier franchissement de Z = ±2.0 (pas de double-check)
- Pas d'entrée quand biais directionnel interdit la direction

### Tests de sortie

- TP quand Z repasse 0 (pas 0.5)
- SL quand |Z| ≥ 3.0
- SESSION_CLOSE à 15h25 CT

### Tests de non-régression

- Kalman non affecté (P reste PSD)
- Sizing inchangé
- Coûts inchangés

### Test de distribution Z

- Sur 1000+ barres simulées, vérifier que mean(Z) ≈ 0 et std(Z) ≈ 1
- Vérifier que P(|Z| > 2) ≈ 5% et P(|Z| > 3) ≈ 0.3%

---

## PARAMÈTRES À TESTER

### Phase 1 — ZC/ZW et GC/PA × 3 fenêtres

```
Test 1 : N = 12 barres (1h)
Test 2 : N = 20 barres (1h40)
Test 3 : N = 24 barres (2h)
```

Seuils fixes : entrée ±2.0, TP à 0, SL à ±3.0.

### Phase 2 — 7 paires × meilleure fenêtre

Si les résultats Phase 1 sont positifs.

---

## CRITÈRES DE SUCCÈS

| Métrique | Cible V2.2 | V2.1 référence |
|----------|-----------|----------------|
| Distribution Z | mean ≈ 0, std ≈ 1, \|Z\|>3 < 1% | mean = -12.5, \|Z\|>3 = 40% |
| Trades par paire (3 ans) | > 50 | 0-33 |
| avgTP en dollars | > 0 sur ≥ 3 paires | -$32 (ZC/ZW), +$212 (GC/PA) |
| Sharpe_1x | > 0 sur ≥ 3 paires | 1 paire (GC/PA non fiable) |
| SESSION_CLOSE rate | documenté | 0% (mais TP à 0.5 très facile) |

---

## SÉQUENCE D'IMPLÉMENTATION

```
1. Mesurer HL_intraday sur 7 paires (script d'analyse, pas de modif pipeline)
2. Modifier compute_signal : μ_rolling + σ_rolling même fenêtre
3. Modifier machine à états : entrée directe, suppression arm-then-trigger
4. Ajouter biais directionnel dans init_session
5. Modifier seuil TP : 0 au lieu de 0.5
6. Écrire les tests V2.2
7. Phase 1 : ZC/ZW + GC/PA × 3 fenêtres
8. Analyser distribution Z (vérifier normalité)
9. MFE/MAE sur Z intraday propre
10. Phase 2 : 7 paires × meilleure fenêtre
```

L'étape 1 (HL_intraday) est un pré-requis bloquant. Si une paire ne mean-reverte pas en intraday, elle est exclue avant les étapes 2-10.

---

## RISQUES IDENTIFIÉS

| Risque | Impact | Mitigation |
|--------|--------|------------|
| μ_rolling réactif → Z oscille autour de 0, peu de signaux | Trop peu de trades | Tester N plus grand (24-48 barres) |
| Perte du lien théorique OU | Signal non-paramétrique, moins "élégant" | Cointégration reste le filtre d'éligibilité |
| SESSION_CLOSE élevé avec TP à 0 | Profits capturés mais non réalisés | SESSION_CLOSE profitable si spread a partiellement revert |
| HL_intraday > 1 session sur certaines paires | Paire exclue de l'univers intraday | Mieux vaut exclure que trader une paire non viable |
| Entrée directe = plus de faux signaux | SL plus fréquents | SL à 3.0σ intraday borne le risque |
