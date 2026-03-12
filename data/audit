# AUDIT CROISÉ V1 — AJOUTS À DOCUMENTER

## Résultat : 0 correction bloquante sur le V1 ou le code (steps 1-3)

Audit réalisé par 2 IA indépendantes sur les 5 axes (A→E), arbitré manuellement.
Toutes les formules, le code, et l'architecture sont validés.

Les points ci-dessous sont des **ajouts à intégrer dans les briefings des étapes à venir**, pas des corrections du V1 existant.

---

## 1. SESSION_CLOSE à 15h30 CT — 5ème motif de sortie

**Concerne :** step5_engine.py (machine à états) + backtester.py (boucle principale)

**Problème identifié :** Le V1 dit que les positions ouvertes après T_limite sont "gérées normalement" (TP/SL continuent). Mais il ne spécifie pas ce qui se passe à 15h30 CT (fin de session) si la position n'a touché ni TP ni SL.

**Règle à implémenter :**

```
Toute position encore ouverte à 15h30 CT est fermée au marché.
Motif : SESSION_CLOSE
PnL calculé sur le prix de clôture de la dernière barre 5min de la session.

MOTIF ∈ {ENTREE_ARMEE, TAKE_PROFIT, STOP_LOSS, SORTIE_FORCEE, SESSION_CLOSE}
```

**Dans le backtester :** après la dernière barre de la session (15h25-15h30 CT), si `position_open == True`, fermer au close avec motif SESSION_CLOSE. Comptabiliser dans les métriques séparément — un taux élevé de SESSION_CLOSE signale que le HL empirique est sous-estimé ou que T_limite est mal calibré.

**Priorité :** briefing step5 + step8.

---

## 2. Minimum 5 traversées pour HL empirique

**Concerne :** step4_ou.py (calcul HL empirique)

**Problème identifié :** Le HL empirique est la médiane des temps de retour |Z| > 2 → |Z| < 0.5. Sur une fenêtre 30j, le nombre de traversées complètes peut être faible (< 10). Une médiane sur 3-4 points n'est pas fiable.

**Règle à implémenter :**

```python
crossing_times = [...]  # temps de retour mesurés

if len(crossing_times) < 5:
    hl_empirical = None          # non fiable
    hl_status = "orange"         # avertissement
    # Fallback : utiliser HL_modèle = ln(2) / κ × 5 min
    hl_operational = hl_model    # avec flag d'avertissement
else:
    hl_empirical = float(np.median(crossing_times))
    hl_operational = hl_empirical
```

**Impact sur T_limite :** Si HL empirique = None, T_limite utilise HL_modèle comme fallback. Le score de confiance de la paire est réduit (orange sur le diagnostic HL).

**Priorité :** briefing step4 (déjà préparé, ajouter ce point).

---

## 3. Comportement double armement (edge case machine à états)

**Concerne :** step5_engine.py (Phase 2 — Signal Engine)

**Problème identifié :** Le V1 ne spécifie pas explicitement ce qui se passe si is_armed_short == True et que Z chute brutalement sous −2.5 (condition d'armement LONG).

**Règle à implémenter :**

```
is_armed_long et is_armed_short sont deux flags INDÉPENDANTS.
Un nouvel armement dans la direction opposée ne désarme PAS l'autre.

En pratique, les deux ne peuvent être True simultanément que si Z 
traverse toute la plage (+2.5 → −2.5) en quelques barres — événement
extrême qui sera capté par le Filtre A (NIS > 9) ou Filtre C (dérive β).

Si les deux sont armés et qu'un déclenchement se produit dans une
direction, l'autre armement reste actif mais sera probablement 
désarmé par le SL (|Z| > 3.0) avant de pouvoir se déclencher.
```

**Priorité :** briefing step5.

---

## 4. Points V2 identifiés par l'audit (PAS d'action V1)

Ces points ont été soulevés par les IA ou identifiés en revue interne. Ils ne sont pas des corrections V1. Ils sont documentés ici pour mémoire.

| Point | Description | Trigger V2 |
|-------|-----------|-----------|
| BarState_t frozen dataclass | Formaliser l'immutabilité avec @dataclass(frozen=True) | Si bugs de mutation détectés en step5 |
| Anti-look-ahead garde-fou | Ajouter current_session dans select_window pour empêcher l'inclusion de T | Implémenté dans backtester.py |
| Limite exposition par actif | GC/SI + GC/PA = double exposition GC | Si portefeuille multi-paires actif |
| Slippage ajusté par heure | Facteur de liquidité intra-session (03h vs 10h CT) | Si PnL dégradé sur heures creuses |
| Cooldown post TP/SL | N barres de pause après sortie | Si sur-trading détecté en backtest |
| Downsampling 10d puissance | 176 obs sur fréquence basse = peu de puissance ADF | Si taux rejet I(1) > 80% sur paires évidentes |
| DF pur sans lags augmentés (step3) | run_ar1_df_test fait DF sans lags — autocorrélation résiduelle 5min biaise t-stat vers le rejet (faux positifs cointégration). Cohérent avec conversion AR(1)→OU mais sous-estime SE(φ̂). | Si taux SL > 40% en backtest (spread diverge au lieu de reverter = faux positif step3). Correction : remplacer par adfuller avec autolag AIC. |

---

## Résumé des actions par étape

| Étape | Ajout | Statut |
|-------|-------|--------|
| step4_ou.py | Minimum 5 traversées pour HL empirique, fallback HL_modèle | À intégrer dans briefing |
| step5_engine.py | SESSION_CLOSE à 15h30 CT + double armement documenté | À intégrer dans briefing |
| backtester.py | Fermeture forcée 15h30 CT + anti-look-ahead dans la boucle | À intégrer dans briefing |