# BRIEFING BACKTESTER — Boucle Multi-Session, PnL, Coûts, Métriques

**Source de vérité** : `docs/recherche/modele_cointegration_v1_FINAL.docx` — Sections 9 et 10.
**Ne jamais improviser une formule, un seuil, ou un paramètre.**

---

## OBJECTIF

Le backtester orchestre le pipeline complet sur N sessions consécutives
avec recalibration rolling. Pour chaque session T, il calibre sur les 30
sessions précédentes propres (anti-look-ahead), puis exécute step5 sur
la session T. Il produit un journal de trades, un PnL net avec 3
scénarios de slippage, et les métriques de performance V1.

**Fichier** : `src/backtester.py`

---

## ARCHITECTURE — Boucle Principale

```
Pour chaque session T dans [T_start ... T_end] :

    1. FENÊTRE CALIBRATION (anti-look-ahead)
       calib_sessions = les 30 dernières sessions PROPRES avant T
       Exclure : low_liquidity_day, rollover ± N sessions
       La session T elle-même n'est JAMAIS dans la fenêtre

    2. CALIBRATION (steps 2-3-4)
       Construire les DataFrames de la paire sur calib_sessions
       → run_step2 sur chaque actif → vérifier I(1)
       → run_step3 sur la paire → vérifier stationnarité
       → run_step4 → paramètres OU
       Si bloquant à n'importe quelle étape → skip session T, loguer raison

    3. EXÉCUTION (step 5)
       Préparer le DataFrame de session T avec price_a, price_b
       → run_session(df_session_T, step4_result, pair_config)
       → récupérer trades et diagnostics

    4. PnL
       Pour chaque trade complété (exit_timestamp non None) :
       → calculer PnL brut
       → calculer coûts (3 scénarios slippage)
       → PnL net = brut - coûts

    5. AGRÉGATION
       Accumuler les trades, PnL quotidiens, diagnostics
```

---

## RÈGLES ANTI-LOOK-AHEAD (V1 §9.1) — STRICTES

```python
# RÈGLE 1 — Fenêtre calibration
# [T−30 sessions propres ... T−1 à 15h30 CT]
# Exclure : low_liquidity_day + rollover ± N sessions
# La session T est EXCLUE de la calibration

# RÈGLE 2 — Paramètres figés
# OLS/OU figés AVANT le premier tick de session T
# Pas de recalibration intra-session

# RÈGLE 3 — Kalman réinitialisé
# x_0 = [α_OLS, β_OLS] à 17h30 CT de chaque session T
# Pas de carry-over du Kalman d'une session à l'autre

# RÈGLE 4 — Fenêtre de trading
# [T à 17h30 CT ... T à 15h30 CT]
# Burn-in implicite : ~90 barres (17h30 → 01h00 CT)
# Le trader n'intervient qu'à partir de 01h00 CT (08h00 FR)
# Mais le Kalman tourne dès 17h30 pour converger

# RÈGLE 5 — PnL sur sizing ENTRÉE
# β_Kalman_SORTIE logué mais PAS utilisé pour PnL
# Le sizing est fixé à l'entrée et ne change pas

# RÈGLE 6 — Trois colonnes PnL_net
# 1x, 1.5x, 2x de slippage
# Sharpe reporté UNIQUEMENT sur PnL_net (jamais PnL_brut)
```

---

## SÉLECTION DES SESSIONS — Fenêtre Calibration

```python
def select_calibration_window(df_a: pd.DataFrame, df_b: pd.DataFrame,
                              target_session: str,
                              pair_config: dict,
                              n_sessions: int = 30) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Sélectionne les n sessions propres AVANT target_session.

    ANTI-LOOK-AHEAD : target_session est strictement exclue.
    Exclusion rollover : ±N sessions autour de chaque rollover détecté,
    avec N = pair_config["rollover_excl"] (3 pour GC/SI, 1 pour CL/HO, 0 pour NQ/RTY).

    Input:
        df_a, df_b:       DataFrames 5min complets (step1)
        target_session:   session_id de la session à trader (YYYYMMDD)
        pair_config:      PairConfig (rollover_excl, etc.)
        n_sessions:       nombre de sessions de calibration (30)

    Output:
        (df_a_calib, df_b_calib) DataFrames filtrés, ou None si insuffisant
    """
```

Logique :
```python
rollover_excl = pair_config["rollover_excl"]

# 1. Lister toutes les sessions disponibles (intersection A ∩ B)
sessions_a = sorted(df_a["session_id"].unique())
sessions_b = sorted(df_b["session_id"].unique())
all_sessions = sorted(set(sessions_a) & set(sessions_b))

# 2. Filtrer : prendre uniquement les sessions STRICTEMENT AVANT target
prior_sessions = [s for s in all_sessions if s < target_session]

# 3. Identifier les sessions rollover sur l'un ou l'autre actif
rollover_sessions: set[str] = set()
for flag_col, df in [("rollover_discontinuity", df_a), ("rollover_discontinuity", df_b)]:
    if flag_col in df.columns:
        flagged = df[df[flag_col]]["session_id"].unique()
        rollover_sessions.update(flagged)

# 4. Construire le set complet des sessions exclues (rollover ± N)
excluded: set[str] = set()
for roll_sid in rollover_sessions:
    if roll_sid not in prior_sessions:
        continue
    roll_idx = prior_sessions.index(roll_sid)
    for offset in range(-rollover_excl, rollover_excl + 1):
        idx = roll_idx + offset
        if 0 <= idx < len(prior_sessions):
            excluded.add(prior_sessions[idx])

# 5. Exclure aussi les sessions low_liquidity
for df in [df_a, df_b]:
    if "low_liquidity_day" in df.columns:
        low_liq = df[df["low_liquidity_day"]]["session_id"].unique()
        excluded.update(low_liq)

# 6. Sessions propres = prior \ excluded
clean_sessions = [s for s in prior_sessions if s not in excluded]

# 7. Prendre les 30 dernières propres
if len(clean_sessions) < n_sessions:
    return None
selected = set(clean_sessions[-n_sessions:])

# 8. Filtrer les DataFrames
df_a_calib = df_a[df_a["session_id"].isin(selected)].copy()
df_b_calib = df_b[df_b["session_id"].isin(selected)].copy()
return (df_a_calib, df_b_calib)
```

---

## PRÉPARATION DataFrame SESSION T

```python
def prepare_session_df(df_a: pd.DataFrame, df_b: pd.DataFrame,
                       session_id: str) -> pd.DataFrame | None:
    """Prépare le DataFrame pour run_session sur la session T.

    Output: DataFrame avec colonnes price_a, price_b, DatetimeIndex.
            Inner join sur les timestamps communs de la session.
    """
```

Colonnes requises par `run_session` :
```python
# price_a = colonne "price" de df_a pour cette session (Close ou TP selon config)
# price_b = colonne "price" de df_b pour cette session
# Index = DatetimeIndex (timestamps des barres 5min)
```

---

## CALCUL PnL BRUT

Le V1 dit : "PnL calculé sur sizing réel de l'ENTRÉE — β_Kalman_SORTIE non utilisé."

```python
def compute_pnl_brut(trade: dict, step4_result: dict) -> float:
    """PnL brut en dollars d'un trade complété.

    Le PnL est calculé par leg, en utilisant le sizing fixé à l'entrée.
    Le sizing utilise les MULTIPLIERS (prohibition #3).

    Input:
        trade:         dict trade complété (entry/exit prices + sizing)
        step4_result:  pour symbol_a, symbol_b, direction

    Output:
        PnL brut en dollars (positif = gain, négatif = perte)
    """
```

**Formule — LONG spread (acheter dep, vendre indep) :**
```python
symbol_a = step4_result["symbol_a"]
symbol_b = step4_result["symbol_b"]
ols_direction = step4_result["direction"]

# Identifier dep/indep
if ols_direction == "A_B":
    dep_sym, indep_sym = symbol_a, symbol_b
    entry_price_dep  = trade["entry_price_a"]
    entry_price_indep = trade["entry_price_b"]
    exit_price_dep   = trade["exit_price_a"]
    exit_price_indep  = trade["exit_price_b"]
else:
    dep_sym, indep_sym = symbol_b, symbol_a
    entry_price_dep  = trade["entry_price_b"]
    entry_price_indep = trade["entry_price_a"]
    exit_price_dep   = trade["exit_price_b"]
    exit_price_indep  = trade["exit_price_a"]

sizing = trade["sizing"]
mult_dep_std   = CONTRACTS[dep_sym]["multiplier"]
mult_indep_std = CONTRACTS[indep_sym]["multiplier"]

# Micro pour Leg B (indep)
micro_sym_b = sizing["micro_sym_B"]
mult_indep_micro = CONTRACTS[micro_sym_b]["multiplier"] if micro_sym_b else 0

# Micro pour Leg A (dep) — Q_A_micro = 0 en V1, mais code générique
from src.step5_sizing import _find_micro
micro_sym_a = _find_micro(dep_sym)
mult_dep_micro = CONTRACTS[micro_sym_a]["multiplier"] if micro_sym_a else 0

# PnL Leg dep (LONG dans un LONG spread)
delta_dep = exit_price_dep - entry_price_dep
pnl_dep = (delta_dep * sizing["Q_A_std"] * mult_dep_std
           + delta_dep * sizing["Q_A_micro"] * mult_dep_micro)

# PnL Leg indep (SHORT dans un LONG spread)
delta_indep = entry_price_indep - exit_price_indep   # SHORT → inversé
pnl_indep = (delta_indep * sizing["Q_B_std"] * mult_indep_std
             + delta_indep * sizing["Q_B_micro"] * mult_indep_micro)

if trade["direction"] == "LONG":
    pnl_brut = pnl_dep + pnl_indep
else:  # SHORT spread → inverser les signes
    # SHORT = vendre dep, acheter indep
    pnl_brut = -pnl_dep - pnl_indep
```

**ATTENTION — La direction du trade (LONG/SHORT spread) est définie par la machine à états (Phase 2), pas par la direction OLS.** LONG spread = acheter dep + vendre indep. SHORT spread = vendre dep + acheter indep.

---

## COÛTS DE TRANSACTION (V1 §9.2) — PROHIBITION #7

```python
def compute_spread_cost_rt(trade: dict, step4_result: dict,
                           slippage_mult: float = 1.0) -> float:
    """Coût total round-trip du spread trade.

    PROHIBITION #7 : appelé UNE SEULE FOIS par trade, pas par side.
    Le multiplicateur de sensibilité s'applique UNIQUEMENT au slippage,
    pas aux commissions (coûts fixes).

    Input:
        trade:          dict trade avec sizing
        step4_result:   pour symbol_a, symbol_b, direction
        slippage_mult:  1.0 (base), 1.5 (robustesse), 2.0 (pessimiste)

    Output:
        Coût en dollars (toujours positif)
    """
```

**Formule :**
```python
sizing = trade["sizing"]
ols_direction = step4_result["direction"]

if ols_direction == "A_B":
    dep_sym, indep_sym = step4_result["symbol_a"], step4_result["symbol_b"]
else:
    dep_sym, indep_sym = step4_result["symbol_b"], step4_result["symbol_a"]

micro_sym_b = sizing["micro_sym_B"]

# Lookup micro Leg A (générique, même si Q_A_micro = 0 en V1)
from src.step5_sizing import _find_micro
micro_sym_a = _find_micro(dep_sym)

# Coût Leg A std
cost_dep = 0
if sizing["Q_A_std"] > 0:
    cost_dep += sizing["Q_A_std"] * (
        COSTS_RT[dep_sym]["comm_rt"]
        + COSTS_RT[dep_sym]["slip_rt"] * slippage_mult
    )

# Coût Leg A micro (générique)
if sizing["Q_A_micro"] > 0 and micro_sym_a is not None:
    cost_dep += sizing["Q_A_micro"] * (
        COSTS_RT[micro_sym_a]["comm_rt"]
        + COSTS_RT[micro_sym_a]["slip_rt"] * slippage_mult
    )

# Coût Leg B std (indep)
cost_indep = 0
if sizing["Q_B_std"] > 0:
    cost_indep += sizing["Q_B_std"] * (
        COSTS_RT[indep_sym]["comm_rt"]
        + COSTS_RT[indep_sym]["slip_rt"] * slippage_mult
    )

# Coût Leg B micro (indep)
if sizing["Q_B_micro"] > 0 and micro_sym_b is not None:
    cost_indep += sizing["Q_B_micro"] * (
        COSTS_RT[micro_sym_b]["comm_rt"]
        + COSTS_RT[micro_sym_b]["slip_rt"] * slippage_mult
    )

total = cost_dep + cost_indep
return total
```

**Les 3 scénarios de sensibilité :**
```python
cost_1x   = compute_spread_cost_rt(trade, step4_result, 1.0)
cost_1_5x = compute_spread_cost_rt(trade, step4_result, 1.5)
cost_2x   = compute_spread_cost_rt(trade, step4_result, 2.0)

pnl_net_1x   = pnl_brut - cost_1x
pnl_net_1_5x = pnl_brut - cost_1_5x
pnl_net_2x   = pnl_brut - cost_2x
```

---

## MÉTRIQUES DE PERFORMANCE (V1 §10)

```python
def compute_metrics(trades: list[dict], daily_pnl: pd.DataFrame) -> dict:
    """Calcule les métriques de performance V1.

    daily_pnl: DataFrame avec index=date, colonnes pnl_net_1x, pnl_net_1_5x, pnl_net_2x

    Output: dict avec toutes les métriques V1 §10
    """
```

**Métriques requises :**

```python
# 1. Sharpe Ratio — PRINCIPALE MÉTRIQUE
# Sharpe = mean(PnL_net_daily) / std(PnL_net_daily) × √252
# Calculé sur CHAQUE scénario de slippage
# Seuil V1 : > 1.0 à 1.5x slip
sharpe_1x   = mean(daily_1x) / std(daily_1x, ddof=1) * np.sqrt(252) if std > 0 else 0
sharpe_1_5x = mean(daily_1_5x) / std(daily_1_5x, ddof=1) * np.sqrt(252) if std > 0 else 0
sharpe_2x   = mean(daily_2x) / std(daily_2x, ddof=1) * np.sqrt(252) if std > 0 else 0

# 2. Win Rate
# Trades TP / (TP + SL + SORTIE_FORCEE + SESSION_CLOSE)
# Seuil V1 : > 55%
n_wins = count(trade["exit_motif"] == "TAKE_PROFIT")
n_total = count(trade["exit_motif"] is not None)
win_rate = n_wins / n_total if n_total > 0 else 0

# 3. Avg Win / Avg Loss
# Gain moyen sur TP / Perte moyenne sur SL
# Seuil V1 : > 1.2
avg_win = mean(pnl_net where exit_motif == "TAKE_PROFIT" and pnl_net > 0)
avg_loss = abs(mean(pnl_net where exit_motif in ("STOP_LOSS",) and pnl_net < 0))
win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else inf

# 4. Max Drawdown
# Pire creux intra-période sur PnL cumulé
# Reporté en DOLLARS uniquement (pas de capital de référence en V1)
# Le trader calcule le % par rapport à son capital réel
cumulative = daily_pnl.cumsum()
rolling_max = cumulative.cummax()
drawdown = cumulative - rolling_max
max_dd_dollars = float(drawdown.min())    # toujours ≤ 0
# Pourcentage avec guard (informatif, pas de seuil V1)
max_dd_pct = float(drawdown.min() / rolling_max.max()) if rolling_max.max() > 0 else 0.0

# 5. Fréquence Sorties Forcées
# Sorties Forcées / Total sorties
# Seuil V1 : < 15%
n_forced = count(exit_motif == "SORTIE_FORCEE")
forced_rate = n_forced / n_total if n_total > 0 else 0

# 6. Slippage Robustness
# Sharpe_1.5x > 0 → condition production
# Sharpe_2.0x > 0 → condition résilience
slippage_robust = sharpe_1_5x > 0
slippage_resilient = sharpe_2x > 0
```

**Métriques additionnelles (diagnostics, pas seuils V1) :**
```python
# Nombre total de trades
# Nombre de sessions tradées / sessions totales
# Nombre de sessions skippées (bloquant calibration)
# Taux de SESSION_CLOSE (position non fermée avant 15:30)
# NIS moyen par session
# Nombre de sessions killed (Filtre C)
```

---

## AGRÉGATION PnL QUOTIDIEN

```python
def aggregate_daily_pnl(all_trades: list[dict],
                        all_session_ids: list[str]) -> pd.DataFrame:
    """Agrège le PnL par session_id (= jour de trading).

    Un session_id peut avoir 0 ou N trades. Les sessions sans trade ont PnL = 0
    (pas de ligne manquante — le Sharpe en a besoin).

    Input:
        all_trades:      liste de tous les trades complétés
        all_session_ids: liste de tous les session_ids de la période backtestée
                         (tradées + skippées)

    Output: DataFrame index=session_id, colonnes pnl_net_1x, pnl_net_1_5x, pnl_net_2x
    """
```

**Convention session_id :** Le PnL d'un trade est attribué au `session_id` du trade (stocké dans `trade["session_id"]`). Une session CME qui commence vendredi 17h30 et finit samedi 15h30 a un session_id unique — pas de risque de split weekend.

**Sessions sans trade :** PnL = 0.0 sur les 3 colonnes. Ne pas les exclure — ils comptent dans le Sharpe (ils réduisent la moyenne et la volatilité, ce qui est correct : un modèle qui ne trade pas 50% du temps doit être pénalisé).

**√252 pour annualisation :** Correct car chaque session_id = un jour de trading. ~252 jours de trading par an. Le Sharpe est `mean(daily) / std(daily) × √252`.

---

## STRUCTURE DE SORTIE DU BACKTESTER

```python
def run_backtest(df_a: pd.DataFrame, df_b: pd.DataFrame,
                 symbol_a: str, symbol_b: str,
                 pair_name: str,
                 verbose: bool = True) -> dict:
    """Boucle principale de backtest.

    Input:
        df_a, df_b:  DataFrames 5min complets (step1)
        symbol_a/b:  symboles des actifs
        pair_name:   clé dans PAIRS (ex: "YM_RTY")
        verbose:     True = log par session, False = silencieux (tests)

    Output:
        {
            "pair": str,
            "n_sessions_total": int,
            "n_sessions_traded": int,
            "n_sessions_skipped": int,
            "skip_reasons": dict,        # compteur par raison de skip
            "trades": list[dict],        # tous les trades complétés
            "daily_pnl": pd.DataFrame,   # index=session_id, 3 colonnes PnL net
            "metrics": dict,             # métriques V1 §10
            "session_diagnostics": list,  # diagnostics par session
        }
    """
```

---

## GESTION DES SESSIONS — Itération

```python
# Lister toutes les sessions disponibles (intersection A et B)
sessions_a = sorted(df_a["session_id"].unique())
sessions_b = sorted(df_b["session_id"].unique())
all_sessions = sorted(set(sessions_a) & set(sessions_b))

pair_config = PAIRS[pair_name]

# On ne peut commencer qu'à partir de la 31ème session
# (30 pour calibration + 1 pour trading)
tradeable_sessions = all_sessions[30:]  # minimum, peut être plus si sessions exclues

for target_session in tradeable_sessions:
    # 1. Sélectionner fenêtre calibration (avec rollover ±N)
    calib = select_calibration_window(
        df_a, df_b, target_session, pair_config, n_sessions=30
    )
    if calib is None:
        log_skip(target_session, "insufficient_clean_sessions")
        continue
    df_a_calib, df_b_calib = calib

    # 2. Step 2 — Stationnarité (sur chaque actif séparément)
    # NOTE: avec 30 sessions, la fenêtre 60d = None → is_blocking ne se
    # déclenche effectivement jamais. Acceptable car I(1) est structurel
    # pour les futures CME (marche aléatoire). Garde de sécurité conservée.
    s2_a = run_step2(df_a_calib, symbol_a)
    s2_b = run_step2(df_b_calib, symbol_b)
    if s2_a["is_blocking"] or s2_b["is_blocking"]:
        log_skip(target_session, "stationarity_blocking")
        continue

    # 3. Step 3 — Cointegration
    s3 = run_step3(df_a_calib, df_b_calib, symbol_a, symbol_b)
    if s3["is_blocking"]:
        log_skip(target_session, "cointegration_blocking")
        continue

    # 4. Step 4 — OU
    s4 = run_step4(s3, df_a_calib, df_b_calib)
    if s4["is_blocking"]:
        log_skip(target_session, "ou_blocking")
        continue

    # 5. Préparer la session T
    df_session = prepare_session_df(df_a, df_b, target_session)
    if df_session is None or len(df_session) < 10:
        log_skip(target_session, "session_too_short")
        continue

    # 6. Step 5 — Exécution
    result = run_session(df_session, s4, pair_config)

    # 7. Calculer PnL pour chaque trade
    for trade in result["trades"]:
        if trade["exit_timestamp"] is None:
            continue  # trade non complété (ne devrait pas arriver avec SESSION_CLOSE)
        trade["pnl_brut"] = compute_pnl_brut(trade, s4)
        trade["cost_1x"]   = compute_spread_cost_rt(trade, s4, 1.0)
        trade["cost_1_5x"] = compute_spread_cost_rt(trade, s4, 1.5)
        trade["cost_2x"]   = compute_spread_cost_rt(trade, s4, 2.0)
        trade["pnl_net_1x"]   = trade["pnl_brut"] - trade["cost_1x"]
        trade["pnl_net_1_5x"] = trade["pnl_brut"] - trade["cost_1_5x"]
        trade["pnl_net_2x"]   = trade["pnl_brut"] - trade["cost_2x"]
        trade["session_id"] = target_session

    all_trades.extend(result["trades"])
    session_diagnostics.append(result["diagnostics"])
```

---

## LOGGING — Format par Session

```python
# Pour chaque session tradée (if verbose) :
if verbose:
    print(f"=== SESSION {target_session} ===")
    print(f"  Calibration: {n_calib} sessions propres")
    print(f"  Step3: stat={s3['is_stationary_30d']}, β={s3['beta_ols']:.4f}")
    print(f"  Step4: σ_eq={s4['sigma_eq']:.6f}, HL_op={s4['hl_operational']:.0f}b")
    print(f"  Trades: {len(result['trades'])}")
    for t in result["trades"]:
        print(f"    {t['direction']} | entry Z={t['entry_z']:.2f} "
              f"| exit {t['exit_motif']} Z={t['exit_z']:.2f} "
              f"| PnL_brut=${t['pnl_brut']:.0f} "
              f"| net_1x=${t['pnl_net_1x']:.0f}")
```

---

## RÈGLES CRITIQUES

1. **La session T n'est JAMAIS dans la fenêtre de calibration** — violation = look-ahead bias fatal
2. **spread_cost_rt appelé UNE SEULE FOIS par trade** (prohibition #7) — pas à l'entrée ET à la sortie
3. **Le multiplicateur de sensibilité s'applique au SLIP uniquement** — COMM est fixe
4. **PnL sur sizing de l'ENTRÉE** — β_Kalman_SORTIE logué mais pas utilisé (règle 5)
5. **Sharpe sur PnL_net, JAMAIS sur PnL_brut** (règle 6)
6. **Kalman réinitialisé à chaque session** — pas de carry-over (règle 3)
7. **Jours sans trade = PnL 0** dans le daily aggregation — pas de lignes manquantes
8. **Recalibration step2→step4 à CHAQUE session** — les paramètres changent
9. **Session skippée si bloquant** à n'importe quelle étape — ne pas forcer

---

## SEUILS DE PERFORMANCE (V1 §10) — Résumé

```
Sharpe Ratio (1.5x slip)  > 1.0     → Principale métrique
Win Rate                   > 55%     → Par motif de sortie
Avg Win / Avg Loss         > 1.2     → Risque/récompense
Max Drawdown               en $      → Reporté en dollars (pas de capital V1)
Freq. Sorties Forcées      < 15%     → Diagnostic Filtre C
Sharpe_1.5x > 0                      → Condition production
Sharpe_2.0x > 0                      → Condition résilience
```

---

## TESTS À ÉCRIRE

### test_backtester.py (synthétique + réel)

**Synthétique :**
- Fenêtre calibration exclut strictement target_session (`<` strict)
- Rollover ±N exclusion : session rollover + N voisines exclues de calibration
- Rollover excl=0 (NQ/RTY) : seule la session rollover exclue, pas les voisines
- Session avec 0 trades → PnL = 0 dans daily (session_id présent avec 0.0)
- Trade LONG : PnL brut = (exit_dep - entry_dep) × Q × mult + (entry_indep - exit_indep) × Q × mult
- Trade SHORT : signe inversé
- PnL formule gère Q_A_micro > 0 (code générique même si 0 en V1)
- spread_cost_rt avec slippage_mult=2 > slippage_mult=1 (monotone)
- spread_cost_rt appelé 1 fois → le doubler donne 2× le coût (test prohibition #7)
- COMM fixe quel que soit le slippage_mult
- Sharpe calculé sur PnL_net, pas PnL_brut
- daily_pnl indexé par session_id, pas par date calendaire

**Sur données réelles (YM/RTY) :**
- Pipeline bout en bout step1→backtest sur 40+ sessions
- Au moins 1 session tradée (non skippée)
- Toutes les sessions skippées ont une raison loguée
- PnL_net_2x < PnL_net_1.5x < PnL_net_1x pour chaque trade (monotonie)
- Pas de trade avec exit_timestamp = None (SESSION_CLOSE attrape tout)
- Metrics dict contient tous les champs requis
- verbose=False ne produit aucun print
