# BRIEFING V2.1 — σ_rolling : Normalisation Adaptative du Z-Score

**Source de vérité** : `docs/v2/roadmap_v2.md` + `docs/recherche/modele_cointegration_v1_FINAL.docx`
**Baseline** : `outputs/backtest_diagnostic_v1.md` — Config D (60j, MK10%, 2.0σ) = 9 trades, Sharpe négatif

---

## OBJECTIF

Remplacer σ_eq (fixe, calibré multi-jour) par σ_rolling (dynamique, recalculé chaque barre)
dans le dénominateur du Z-score. Un seul changement, un seul fichier modifié.

```
V1 : Z_t = (Spread_t − θ_OU) / σ_eq            ← σ_eq fixe toute la session
V2 : Z_t = (Spread_t − θ_OU) / σ_rolling_t      ← σ_rolling recalculé chaque barre
```

---

## POURQUOI

σ_eq est l'écart-type de la distribution stationnaire du processus OU, calibré sur 60 jours
(~15 800 barres 5min). Pour ZC/ZW, σ_eq ≈ 0.007. En intraday, le spread bouge de ±0.001-0.004.
Le Z-score reste compressé entre −0.5 et +0.5 — il n'atteint jamais ±2.0σ_eq.

σ_rolling mesure la volatilité locale du spread (20-60 dernières barres). Pour ZC/ZW
en matinée calme, σ_rolling ≈ 0.001. Un mouvement de 0.002 donne Z = 2.0 avec σ_rolling
mais Z = 0.29 avec σ_eq. Le signal devient visible.

---

## CE QUI CHANGE — `src/step5_engine.py` UNIQUEMENT

### 1. Nouvelle fonction : calcul de σ_rolling

```python
def compute_sigma_rolling(spread_history: list[float], window: int,
                          sigma_eq_fallback: float) -> float:
    """Calcule l'écart-type glissant du spread sur les N dernières barres.

    Burn-in : si len(spread_history) < window, utilise σ_eq comme fallback.
    En pratique, le trader n'intervient qu'à barre ~90 (01h00 CT),
    donc le burn-in est naturellement résolu.

    Input:
        spread_history:   liste des spreads de la session en cours (barres 0 à t)
        window:           nombre de barres pour le calcul (paramètre à tester)
        sigma_eq_fallback: σ_eq de step4, utilisé pendant le burn-in

    Output:
        σ_rolling (float, toujours > 0)
    """
    if len(spread_history) < window:
        # Burn-in : pas assez de barres, utiliser σ_eq
        if len(spread_history) < 2:
            return sigma_eq_fallback
        # Alternative : calculer sur ce qu'on a si > min_bars
        min_bars = max(10, window // 4)  # au moins 10 barres ou 25% de la fenêtre
        if len(spread_history) >= min_bars:
            sigma = float(np.std(spread_history, ddof=1))
            return max(sigma, 1e-10)  # guard division par zéro
        return sigma_eq_fallback

    sigma = float(np.std(spread_history[-window:], ddof=1))
    return max(sigma, 1e-10)  # guard division par zéro
```

### 2. Modification de `init_session` : ajouter l'état rolling

```python
# Dans init_session(), ajouter :
session_state["spread_history"] = []          # historique spread de la session
session_state["sigma_rolling_window"] = 20    # paramètre (20, 40, 60 à tester)
```

### 3. Modification de `compute_signal` : utiliser σ_rolling

```python
def compute_signal(row, session_state: dict, step4_result: dict,
                   current_time_min: int) -> tuple[str | None, float, float, float]:
    """Calcule le spread, σ_rolling, Z-score et détermine le signal.

    CHANGEMENT V2 : le Z-score utilise σ_rolling au lieu de σ_eq.
    σ_eq reste disponible dans step4_result pour diagnostic.

    Output:
        (signal, spread, z, sigma_rolling) — ajout de sigma_rolling dans le tuple
    """
    alpha_ols = step4_result["alpha_ols"]
    beta_ols = step4_result["beta_ols"]
    theta_ou = step4_result["theta_ou"]
    sigma_eq = step4_result["sigma_eq"]

    log_a = np.log(row["price_a"])
    log_b = np.log(row["price_b"])
    spread = log_a - alpha_ols - beta_ols * log_b

    # Ajouter le spread à l'historique de session
    session_state["spread_history"].append(spread)

    # V2 : σ_rolling au lieu de σ_eq
    sigma_rolling = compute_sigma_rolling(
        session_state["spread_history"],
        session_state["sigma_rolling_window"],
        sigma_eq,  # fallback pendant le burn-in
    )

    z = (spread - theta_ou) / sigma_rolling

    # ... reste de la machine à états INCHANGÉ ...
    # (time-lock, SL, TP, désarmement, déclenchement, armement)

    return (signal, float(spread), float(z), float(sigma_rolling))
```

### 4. Modification de `run_session` : propager σ_rolling dans BarState_t

```python
# Dans la boucle de run_session :
signal, spread_val, z_val, sigma_rolling_val = compute_signal(
    row, session_state, step4_result, current_time_min
)

bar_state = {
    "timestamp": idx,
    "raw_price_a": float(row["price_a"]),
    "raw_price_b": float(row["price_b"]),
    "spread": spread_val,
    "z_score": z_val,
    "sigma_rolling": sigma_rolling_val,    # NOUVEAU V2
    "signal": signal,
    "beta_kalman": kalman["beta_kalman"],
    "alpha_kalman": kalman["alpha_kalman"],
    "nis": kalman["nis"],
}
```

### 5. Modification de `init_session` : paramètre configurable

```python
def init_session(step4_result: dict, pair_config: dict,
                 sigma_rolling_window: int = 20) -> dict:
    """Phase 1 — Initialise tous les états de session.

    CHANGEMENT V2 : ajout du paramètre sigma_rolling_window.
    """
    # ... tout le reste inchangé ...

    session_state["spread_history"] = []
    session_state["sigma_rolling_window"] = sigma_rolling_window

    return session_state
```

### 6. Modification de `run_session` : passer le paramètre

```python
def run_session(df_session: pd.DataFrame, step4_result: dict,
                pair_config: dict,
                sigma_rolling_window: int = 20) -> dict:
    """Exécute les phases 1-5 sur une session complète.

    CHANGEMENT V2 : ajout du paramètre sigma_rolling_window.
    """
    session_state = init_session(step4_result, pair_config, sigma_rolling_window)
    # ... reste inchangé ...
```

### 7. Modification du backtester : passer le paramètre

```python
def run_backtest(df_a: pd.DataFrame, df_b: pd.DataFrame,
                 symbol_a: str, symbol_b: str,
                 pair_name: str,
                 verbose: bool = True,
                 s2_refresh_interval: int = 10,
                 sigma_rolling_window: int = 20) -> dict:
    """Boucle principale.

    CHANGEMENT V2 : ajout du paramètre sigma_rolling_window,
    passé à run_session.
    """
    # ... dans la boucle :
    result = run_session(df_session, s4, pair_config, sigma_rolling_window)
```

---

## CE QUI NE CHANGE PAS

- Steps 1-2-3-4 : calibration, stationnarité, cointégration, paramètres OU
- σ_eq reste calculé dans step4 et passe dans le dict step4_result (diagnostic)
- Filtre de Kalman (Phase 3) : tourne sur les log-prix, pas sur le z-score
- Filtres A/B/C (Phase 4) : lisent BarState_t, pas σ_rolling directement
- Sizing (Phase 5) : utilise β_Kalman et raw_prices, pas le z-score
- PnL et coûts dans le backtester : inchangés
- Les 7 interdictions : toutes respectées
- Les 7 invariants : tous respectés

---

## PARAMÈTRES À TESTER

Le backtester doit être lancé plusieurs fois avec différents sigma_rolling_window.
Un seul paramètre change par run. Seuils d'armement fixes à 2.0σ.

```
Test 1 : sigma_rolling_window = 20  (100 min, ~1.5h)
Test 2 : sigma_rolling_window = 40  (200 min, ~3.3h)
Test 3 : sigma_rolling_window = 60  (300 min, ~5h)
```

Pour chaque test, lancer sur les 7 paires avec verbose=False.
Reporter le tableau : sessions tradées, trades, TP/SL/SESSION_CLOSE breakdown, Sharpe.

### EWMA (test séparé, APRÈS les 3 tests std)

Si les résultats std sont prometteurs mais bruités, tester une variante EWMA :

```python
def compute_sigma_ewma(spread_history: list[float], span: int,
                       sigma_eq_fallback: float) -> float:
    """EWMA de la volatilité du spread.

    L'EWMA pondère les barres récentes plus fortement, ce qui capte
    mieux les changements de régime intraday qu'un std plat.
    """
    if len(spread_history) < 2:
        return sigma_eq_fallback

    series = pd.Series(spread_history)
    ewm_std = series.ewm(span=span, min_periods=max(10, span // 4)).std()
    sigma = float(ewm_std.iloc[-1])

    if np.isnan(sigma) or sigma <= 0:
        return sigma_eq_fallback
    return sigma
```

L'EWMA est un test SÉPARÉ — ne pas mélanger avec les tests std.

---

## TESTS À ÉCRIRE

### test_v2_sigma_rolling.py

**Tests unitaires :**
- σ_rolling sur historique constant = 0 → retourne guard (1e-10), pas crash
- σ_rolling sur historique croissant linéaire → > 0
- Burn-in : historique < window → retourne σ_eq fallback
- Burn-in partiel : historique >= min_bars mais < window → calcule sur ce qu'on a
- σ_rolling fenêtre 20 < σ_eq sur un spread OU typique (vérifie que rolling < stationnaire)
- compute_signal retourne un tuple de 4 éléments (pas 3 comme en V1)

**Tests d'intégration :**
- run_session avec σ_rolling produit des BarState_t avec champ sigma_rolling
- σ_rolling est toujours > 0 sur une session complète
- Plus de trades qu'en V1 sur les mêmes données (σ_rolling < σ_eq → z plus grand → plus d'armements)
- P_t reste PSD (le Kalman n'est pas affecté par σ_rolling)

**Tests de non-régression V1 :**
- Avec sigma_rolling_window = très grand (ex: 99999), σ_rolling ≈ σ_eq sur toute la session
  → comportement doit converger vers V1 (mêmes trades, mêmes métriques)
- Les 7 invariants vérifiés : anti-look-ahead, Kalman reset, immutabilité BarState_t, etc.

---

## CRITÈRES DE SUCCÈS

| Métrique | Cible V2.1 | V1 reference |
|----------|-----------|-------------|
| Trades par paire (3 ans) | > 50 | 0-3 |
| Ratio TP/SL | > 1.0 | 0.57 (ZC/ZW 1.5σ) |
| Sharpe_1.5x | > 0 sur ≥ 3 paires | négatif partout |
| SESSION_CLOSE rate | < 30% | 0% (mais 0 trades) |

Si les critères ne sont pas atteints avec aucune fenêtre (20, 40, 60), le diagnostic
sera dans la distribution des motifs de sortie (TP/SL/SESSION_CLOSE) — comme on l'a
fait pour le test 1.5σ en V1.

---

## SÉQUENCE D'IMPLÉMENTATION

1. Ajouter `compute_sigma_rolling` dans step5_engine.py
2. Modifier `compute_signal` : 4 retours au lieu de 3
3. Modifier `init_session` : spread_history + window param
4. Modifier `run_session` : passer le paramètre
5. Modifier BarState_t : ajouter sigma_rolling
6. Modifier `run_backtest` : passer sigma_rolling_window
7. Écrire les tests
8. Lancer les 3 backtests (window 20, 40, 60)
9. Reporter les résultats
