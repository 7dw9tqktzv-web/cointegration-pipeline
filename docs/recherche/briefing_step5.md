# BRIEFING STEP 5 — KALMAN FILTER, RISK MANAGEMENT & EXECUTION

**Source de vérité** : `docs/recherche/modele_cointegration_v1_FINAL.docx` — Section 8.
**Ne jamais improviser une formule, un seuil, ou un paramètre.**

---

## ARCHITECTURE GÉNÉRALE

3 fichiers, 5 phases, exécutés **barre par barre** sur un DataFrame 5min d'une session.

```
src/step5_engine.py   → Phase 1 (init) + Phase 2 (signal) + Phase 3 (Kalman)
src/step5_risk.py     → Phase 4 (filtres A/B/C)
src/step5_sizing.py   → Phase 5 (sizing beta-neutral)
```

Flux par barre :
```
BarClose(t)
  ├── [PARALLÈLE] Phase 2 (Signal Engine) + Phase 3 (Kalman Engine)
  ├── [BARRIÈRE]  → BarState_t IMMUABLE
  ├── [SÉQUENTIEL] Phase 4 (Risk Manager) → FilterVerdict_t
  └── [CONDITIONNEL] Phase 5 (Sizing) si signal entrée + filtres OK
```

---

## INPUTS (depuis step4)

Tout vient du dict `step4_result`. Step5 ne remonte JAMAIS à step3.

```python
# Paramètres fixes pour toute la session
alpha_ols   = step4_result["alpha_ols"]
beta_ols    = step4_result["beta_ols"]
theta_ou    = step4_result["theta_ou"]
sigma_eq    = step4_result["sigma_eq"]
kappa       = step4_result["kappa"]
hl_operational = step4_result["hl_operational"]   # PAS hl_empirical (peut être None)
se_alpha    = step4_result["se_alpha"]
se_beta     = step4_result["se_beta"]
resid_var   = step4_result["resid_var"]           # R du Kalman = variance résidus OLS
mu_b        = step4_result["mu_b"]
direction   = step4_result["direction"]           # "A_B" ou "B_A"
symbol_a    = step4_result["symbol_a"]
symbol_b    = step4_result["symbol_b"]
```

Depuis `config/contracts.py` :
```python
Q_KALMAN[classe]     # tuple (q_alpha, q_beta) — table fixe par classe
PAIRS[pair_name]     # t_close_pit, classe
CONTRACTS[symbol]    # multiplier pour sizing
SESSION_CLOSE_CT     # "15:30"
```

---

## OBJETS DE TRANSFERT

### BarState_t — créé à la barrière, IMMUABLE

```python
BarState_t = {
    "timestamp":    datetime,
    "raw_price_a":  float,      # prix brut en $ (pas log) — pour sizing Phase 5
    "raw_price_b":  float,      # prix brut en $ (pas log)
    "spread":       float,      # Spread_t = log(A) − α_OLS − β_OLS × log(B)
    "z_score":      float,      # Z_t = (Spread_t − θ_OU) / σ_eq  ← formule COMPLÈTE avec θ_OU
    "signal":       str | None, # "ENTRY_LONG" | "ENTRY_SHORT" | "TP" | "SL" | "SESSION_CLOSE" | None
    "beta_kalman":  float,      # β_Kalman_t → sizing Phase 5
    "alpha_kalman": float,      # α_Kalman_t (diagnostic)
    "nis":          float,      # NIS_t = e_t² / S_t → Filtre A Phase 4
}
```

### FilterVerdict_t — créé par Phase 4, objet SÉPARÉ

```python
FilterVerdict_t = {
    "filtre_a_ok":        bool,        # NIS_t < 9.0 ET rolling_NIS_20 < 3.0
    "filtre_b_ok":        bool,        # |Δβ|/|β_{t-1}| < 0.005
    "filtre_c_ok":        bool,        # |β_Kalman − β_OLS| < seuil_C_abs
    "is_session_killed":  bool,        # True si Filtre C déclenché (IRRÉVERSIBLE)
    "motif_blocage":      str | None,  # pour logging
}
```

Phase 4 NE MODIFIE JAMAIS le BarState_t.

---

## FICHIER 1 : `src/step5_engine.py`

Contient Phase 1 + Phase 2 + Phase 3 + la boucle principale par barre.

### Phase 1 — Initialisation de Session (appelée UNE fois à 17h30 CT)

```python
def init_session(step4_result: dict, pair_config: dict) -> dict:
    """Initialise tous les états de session.
    
    Input: step4_result, pair_config depuis config/contracts.py
    Output: dict session_state mutable (modifié barre par barre)
    """
```

Variables à initialiser :
```python
session_state = {
    # Signal Engine
    "is_armed_long":  False,
    "is_armed_short": False,
    "position":       None,      # None | "LONG" | "SHORT"
    "entry_bar":      None,      # BarState_t de l'entrée (pour PnL)
    
    # Kalman Engine
    "x": np.array([alpha_ols, beta_ols]),           # état [α_t, β_t]  (2,)
    "P": np.diag([
        max(se_alpha**2, 1e-4),
        max(se_beta**2, 1e-4),
    ]),                                              # covariance (2,2)
    
    # Risk Manager
    "is_session_killed": False,
    "rolling_nis":       [],       # liste des 20 derniers NIS
    "beta_kalman_prev":  beta_ols, # évite faux Filtre B sur 1ère barre
    
    # Kalman fixed params
    "Q": np.diag([q_alpha, q_beta]),  # depuis Q_KALMAN[classe]
    "R": resid_var,                   # scalaire, variance résidus OLS
    
    # Time-lock
    "t_limite": _compute_t_limite(hl_operational, pair_config),
    
    # Trades log
    "trades": [],
}
```

**Calcul de T_limite :**
```python
def _compute_t_limite(hl_operational: float, pair_config: dict) -> int:
    """T_limite en minutes depuis minuit CT.
    
    T_close_session = 15:30 CT = 930 min
    T_close_pit = pair_config["t_close_pit"] ou 15:30 par défaut
    T_limite = min(T_close_session - hl_operational*5, T_close_pit)
    
    hl_operational est en barres de 5min → multiplier par 5 pour avoir des minutes.
    """
    t_close_session = 15 * 60 + 30  # 930 min
    
    pit = pair_config.get("t_close_pit")
    if pit is None:
        t_close_pit = t_close_session
    else:
        h, m = map(int, pit.split(":"))
        t_close_pit = h * 60 + m
    
    t_lim_from_hl = t_close_session - hl_operational * 5  # en minutes
    return min(int(t_lim_from_hl), t_close_pit)
```

### Phase 2 — Signal Engine (monde STATIQUE)

```python
def compute_signal(row, session_state: dict, step4_result: dict, 
                   current_time_min: int) -> str | None:
    """Calcule le Z-score et détermine le signal.
    
    RÈGLE ABSOLUE : σ_eq FIXE toute la session.
    Le Signal Engine n'accède JAMAIS à β_Kalman.
    
    Input:  row (barre 5min courante), session_state, step4_result
    Output: signal string ou None, modifie session_state in-place
    """
```

**Z-score — formule COMPLÈTE (avec θ_OU) :**
```python
log_a = np.log(row["price_a"])  
log_b = np.log(row["price_b"])
spread = log_a - alpha_ols - beta_ols * log_b
z = (spread - theta_ou) / sigma_eq      # θ_OU inclus, JAMAIS σ_diffusion
```

**Time-Lock :**
```python
if current_time_min >= session_state["t_limite"]:
    session_state["is_armed_long"] = False
    session_state["is_armed_short"] = False
    # Pas de nouvelle entrée, mais TP/SL/SESSION_CLOSE continuent
```

**Machine à états — PRIORITÉ DES SIGNAUX (évaluer dans cet ordre) :**

```python
signal = None
position = session_state["position"]

# 1. SESSION_CLOSE — 5ème motif (audit #1)
#    Dernière barre de la session (15:25-15:30 CT) ou barre >= 15:30
if current_time_min >= 15*60 + 25 and position is not None:
    signal = "SESSION_CLOSE"
    return signal

# 2. STOP LOSS — priorité sur tout le reste
if position == "LONG" and z < -3.0:
    signal = "SL"
elif position == "SHORT" and z > 3.0:
    signal = "SL"

# 3. TAKE PROFIT
elif position is not None and abs(z) < 0.5:
    signal = "TP"

# 4. DÉSARMEMENT sans position sur SL zone
elif position is None and session_state["is_armed_long"] and z < -3.0:
    session_state["is_armed_long"] = False
elif position is None and session_state["is_armed_short"] and z > 3.0:
    session_state["is_armed_short"] = False

# 5. DÉCLENCHEMENT (seulement si pas en time-lock et pas de position ouverte)
elif position is None and current_time_min < session_state["t_limite"]:
    if session_state["is_armed_long"] and z > -2.0:
        signal = "ENTRY_LONG"
        session_state["is_armed_long"] = False
    elif session_state["is_armed_short"] and z < 2.0:
        signal = "ENTRY_SHORT"
        session_state["is_armed_short"] = False

# 6. ARMEMENT (seulement si pas de position et pas en time-lock)
if position is None and current_time_min < session_state["t_limite"]:
    if z < -2.5:
        session_state["is_armed_long"] = True
    if z > 2.5:
        session_state["is_armed_short"] = True
    # NOTE AUDIT #3 : is_armed_long et is_armed_short sont INDÉPENDANTS
    # Un armement dans une direction ne désarme PAS l'autre

return signal
```

**IMPORTANT — L'armement (étape 6) est évalué APRÈS le déclenchement (étape 5).** Cela permet qu'une barre qui arme dans une direction puisse aussi déclencher dans l'autre direction si les conditions sont réunies. L'armement ne dépend pas du signal — il s'accumule.

### Phase 3 — Kalman Engine (tourne à CHAQUE barre)

```python
def kalman_update(row, session_state: dict) -> dict:
    """Mise à jour Kalman pour une barre.
    
    Tourne à CHAQUE barre, pas seulement quand il y a signal.
    
    Input:  row (barre 5min), session_state
    Output: dict avec alpha_kalman, beta_kalman, nis
            Modifie session_state["x"], session_state["P"] in-place
    """
```

**7 étapes — PROHIBITION #5 : Joseph form obligatoire :**

```python
x = session_state["x"]       # (2,)
P = session_state["P"]       # (2,2)
Q = session_state["Q"]       # (2,2) diag fixe
R = session_state["R"]       # scalaire

log_a = np.log(row["price_a"])
log_b = np.log(row["price_b"])

# Étape 1 — Vecteur d'observation
H = np.array([1.0, log_b])                    # (2,)

# Étape 2 — Prédiction a priori (random walk sur état)
x_pred = x.copy()
P_pred = P + Q

# Étape 3 — Innovation
e = log_a - H @ x_pred                        # scalaire

# Étape 4 — Variance de l'innovation
S = H @ P_pred @ H + R                        # scalaire

# Étape 5 — Kalman Gain
K = P_pred @ H / S                             # (2,)

# Étape 6 — Mise à jour (FORME DE JOSEPH — PROHIBITION #5)
x_new = x_pred + K * e
I_KH = np.eye(2) - np.outer(K, H)             # (2,2)
P_new = I_KH @ P_pred @ I_KH.T + np.outer(K, K) * R   # (2,2)

# Étape 7 — NIS
nis = (e ** 2) / S                             # scalaire

# Mettre à jour l'état
session_state["x"] = x_new
session_state["P"] = P_new

return {
    "alpha_kalman": float(x_new[0]),
    "beta_kalman":  float(x_new[1]),
    "nis":          float(nis),
    "innovation":   float(e),
    "S":            float(S),
}
```

### Boucle principale par session

```python
def run_session(df_session: pd.DataFrame, step4_result: dict,
                pair_config: dict) -> dict:
    """Exécute les phases 1-5 sur une session complète.
    
    Input:  DataFrame 5min d'UNE session, step4_result, pair_config
    Output: dict avec bar_states (liste), trades (liste), diagnostics
    """
```

Structure de la boucle :
```python
session_state = init_session(step4_result, pair_config)
bar_states = []

for idx, row in df_session.iterrows():
    current_time_min = idx.hour * 60 + idx.minute
    
    # Phase 2 + Phase 3 (conceptuellement parallèles)
    signal = compute_signal(row, session_state, step4_result, current_time_min)
    kalman = kalman_update(row, session_state)
    
    # Barrière → BarState_t IMMUABLE
    bar_state = {
        "timestamp":    idx,
        "raw_price_a":  float(row["price_a"]),
        "raw_price_b":  float(row["price_b"]),
        "spread":       float(np.log(row["price_a"]) - alpha_ols 
                              - beta_ols * np.log(row["price_b"])),
        "z_score":      float((spread - theta_ou) / sigma_eq),
        "signal":       signal,
        "beta_kalman":  kalman["beta_kalman"],
        "alpha_kalman": kalman["alpha_kalman"],
        "nis":          kalman["nis"],
    }
    
    # Phase 4 — Risk Manager (fichier séparé)
    verdict = evaluate_filters(bar_state, session_state, step4_result)
    
    # Phase 5 — Sizing + exécution (conditionnel)
    _execute_signal(bar_state, verdict, session_state, step4_result)
    
    # Mettre à jour beta_kalman_prev pour Filtre B de la barre suivante
    session_state["beta_kalman_prev"] = kalman["beta_kalman"]
    
    bar_states.append(bar_state)

return {
    "bar_states": bar_states,
    "trades": session_state["trades"],
    "diagnostics": _compute_session_diagnostics(bar_states, session_state),
}
```

**`_execute_signal` — logique d'exécution :**
```python
def _execute_signal(bar_state, verdict, session_state, step4_result):
    signal = bar_state["signal"]
    if signal is None:
        return
    
    # SORTIES — toujours exécutées (Filtres A/B ne bloquent JAMAIS les sorties)
    if signal in ("TP", "SL", "SESSION_CLOSE"):
        _close_position(bar_state, signal, session_state)
        return
    
    # SORTIE FORCÉE — Filtre C
    if verdict["is_session_killed"] and session_state["position"] is not None:
        _close_position(bar_state, "SORTIE_FORCEE", session_state)
        return
    
    # ENTRÉES — vérifier les 3 filtres
    if signal in ("ENTRY_LONG", "ENTRY_SHORT"):
        if verdict["filtre_a_ok"] and verdict["filtre_b_ok"] and not verdict["is_session_killed"]:
            sizing = compute_sizing(bar_state, step4_result)  # Phase 5
            _open_position(bar_state, signal, sizing, session_state)
```

---

## FICHIER 2 : `src/step5_risk.py`

### Phase 4 — Risk Manager

```python
def evaluate_filters(bar_state: dict, session_state: dict,
                     step4_result: dict) -> dict:
    """Évalue les 3 filtres et produit FilterVerdict_t.
    
    Le Risk Manager lit le BarState_t et produit un FilterVerdict_t SÉPARÉ.
    Il ne génère jamais de signal et ne calcule jamais de Kalman.
    
    Input:  bar_state (immuable), session_state, step4_result
    Output: FilterVerdict_t dict
    """
```

#### Filtre A — Qualité de l'Innovation (NIS)

```python
def check_filter_a(nis: float, session_state: dict) -> bool:
    """NIS_t < 9.0 ET rolling_NIS_20 < 3.0
    
    Type : SUSPENSION TEMPORAIRE — ne bloque JAMAIS une sortie TP/SL.
    """
    # Mettre à jour rolling NIS (fenêtre glissante de 20)
    session_state["rolling_nis"].append(nis)
    if len(session_state["rolling_nis"]) > 20:
        session_state["rolling_nis"] = session_state["rolling_nis"][-20:]
    
    rolling_mean = np.mean(session_state["rolling_nis"])
    
    return (nis < 9.0) and (rolling_mean < 3.0)
```

#### Filtre B — Vitesse Beta (Seuil Relatif)

```python
def check_filter_b(beta_kalman: float, beta_kalman_prev: float) -> bool:
    """|Δβ| / |β_{t-1}| < 0.005
    
    Guard : si |β_{t-1}| < 1e-6 → False (division par quasi-zéro)
    Type : SUSPENSION TEMPORAIRE — ne bloque JAMAIS une sortie TP/SL.
    
    beta_kalman_prev est initialisé à β_OLS en Phase 1 — pas 0, pas None.
    """
    if abs(beta_kalman_prev) < 1e-6:
        return False    # guard
    
    delta_ratio = abs(beta_kalman - beta_kalman_prev) / abs(beta_kalman_prev)
    return delta_ratio < 0.005
```

#### Filtre C — Dérive Macro (Seuil Adaptatif Absolu)

```python
def check_filter_c(beta_kalman: float, beta_ols: float,
                   classe: str) -> tuple[bool, float]:
    """|β_Kalman_t − β_OLS| < seuil_C_abs
    
    σ_dérive = √(264 × Q_β_classe)
    seuil_C_abs = 4 × σ_dérive
    
    Le seuil est ABSOLU — jamais un % relatif.
    Type : COUPE-CIRCUIT DÉFINITIF — irréversible sur la session.
    
    Valeurs numériques de référence :
        Metals:       Q_β = 1e-7,  seuil_C_abs = 0.02056
        Equity Index: Q_β = 2e-7,  seuil_C_abs = 0.02906
        Grains:       Q_β = 2e-7,  seuil_C_abs = 0.02906
        Energy:       Q_β = 5e-7,  seuil_C_abs = 0.04597
    """
    q_beta = Q_KALMAN[classe][1]      # 2ème élément du tuple
    sigma_derive = np.sqrt(264 * q_beta)
    seuil_c_abs = 4 * sigma_derive
    
    drift_abs = abs(beta_kalman - beta_ols)
    ok = drift_abs < seuil_c_abs
    
    return ok, seuil_c_abs
```

#### Assemblage Phase 4

```python
def evaluate_filters(bar_state, session_state, step4_result):
    # Si déjà killed, reste killed (IRRÉVERSIBLE)
    if session_state["is_session_killed"]:
        return {
            "filtre_a_ok": False,
            "filtre_b_ok": False,
            "filtre_c_ok": False,
            "is_session_killed": True,
            "motif_blocage": "session_killed_previous",
        }
    
    a_ok = check_filter_a(bar_state["nis"], session_state)
    b_ok = check_filter_b(bar_state["beta_kalman"], session_state["beta_kalman_prev"])
    c_ok, seuil = check_filter_c(
        bar_state["beta_kalman"], step4_result["beta_ols"],
        PAIRS[pair_name]["classe"],
    )
    
    # Filtre C déclenché → session killed
    if not c_ok:
        session_state["is_session_killed"] = True
    
    motif = None
    if not a_ok:
        motif = "filtre_a"
    elif not b_ok:
        motif = "filtre_b"
    elif not c_ok:
        motif = f"filtre_c_drift={abs(bar_state['beta_kalman'] - step4_result['beta_ols']):.4f}_seuil={seuil:.4f}"
    
    return {
        "filtre_a_ok": a_ok,
        "filtre_b_ok": b_ok,
        "filtre_c_ok": c_ok,
        "is_session_killed": session_state["is_session_killed"],
        "motif_blocage": motif,
    }
```

---

## FICHIER 3 : `src/step5_sizing.py`

### Phase 5 — Execution Sizing Beta-Neutral

```python
def compute_sizing(bar_state: dict, step4_result: dict) -> dict:
    """Calcul du sizing beta-neutral avec découpage Standard + Micro.
    
    PROHIBITION #3 : utiliser multiplier, PAS tick_value.
    
    Input:  bar_state (pour raw_price et beta_kalman), step4_result
    Output: dict avec Q_A, Q_B, notionnels, résidu
    """
```

**Algorithme :**
```python
symbol_a = step4_result["symbol_a"]
symbol_b = step4_result["symbol_b"]
direction = step4_result["direction"]

# Déterminer dep/indep selon direction
if direction == "A_B":
    dep_sym, indep_sym = symbol_a, symbol_b
    raw_price_dep = bar_state["raw_price_a"]
    raw_price_indep = bar_state["raw_price_b"]
else:
    dep_sym, indep_sym = symbol_b, symbol_a
    raw_price_dep = bar_state["raw_price_b"]
    raw_price_indep = bar_state["raw_price_a"]

# Étape 1 — Notionnel Leg A (dep)
Q_A_std = 1         # taille de base fixée par le trader
Q_A_micro = 0
multiplier_A = CONTRACTS[dep_sym]["multiplier"]
notional_A = raw_price_dep * Q_A_std * multiplier_A
assert notional_A > 0, "Leg A vide — sizing impossible"

# Étape 2 — Notionnel cible Leg B (indep)
beta_kalman = bar_state["beta_kalman"]
assert beta_kalman > 0, "β_Kalman négatif — Filtre C aurait dû intercepter"
target_notional_B = notional_A * abs(beta_kalman)

# Étape 3 — Découpage Standard + Micro
multiplier_B_std = CONTRACTS[indep_sym]["multiplier"]

# Chercher le micro correspondant
micro_sym = _find_micro(indep_sym)   # ex: "SI" → "SIL", "NQ" → "MNQ"

if micro_sym is not None:
    multiplier_B_micro = CONTRACTS[micro_sym]["multiplier"]
    ratio_B = multiplier_B_std / multiplier_B_micro
    Q_B_total_micros_th = target_notional_B / (raw_price_indep * multiplier_B_micro)
    Q_B_total_micros = max(round(Q_B_total_micros_th), 1)
    Q_B_std = int(Q_B_total_micros // ratio_B)
    Q_B_micro = int(Q_B_total_micros % ratio_B)
    actual_notional_B = (Q_B_std * multiplier_B_std + Q_B_micro * multiplier_B_micro) * raw_price_indep
else:
    # PAS DE MICRO DISPONIBLE — arrondi en std uniquement
    Q_B_std = max(round(target_notional_B / (raw_price_indep * multiplier_B_std)), 1)
    Q_B_micro = 0
    micro_sym = None
    actual_notional_B = Q_B_std * multiplier_B_std * raw_price_indep

residual = target_notional_B - actual_notional_B

return {
    "Q_A_std": Q_A_std,
    "Q_A_micro": Q_A_micro,
    "Q_B_std": Q_B_std,
    "Q_B_micro": Q_B_micro,
    "micro_sym_B": micro_sym,
    "notional_A": notional_A,
    "target_notional_B": target_notional_B,
    "actual_notional_B": actual_notional_B,
    "residual": residual,
    "beta_kalman_entry": beta_kalman,
}
```

**Mapping Standard → Micro (à ajouter dans config ou dans step5_sizing.py) :**
```python
MICRO_MAP = {
    "GC": "MGC",  "SI": "SIL",  "HG": "MHG",
    "NQ": "MNQ",  "YM": "MYM",  "ES": "MES",
    "RTY": "M2K",
    "CL": "MCL",  "NG": "QG",
    "ZC": "MZC",  "ZW": "MZW",  "ZS": "MZS",
    "HO": None,   "RB": None,
    "PA": None,   "PL": None,   "BZ": None,
}

def _find_micro(symbol: str) -> str | None:
    return MICRO_MAP.get(symbol)
```

---

## MOTIFS DE SORTIE (5 motifs)

```python
MOTIFS = {"ENTREE_ARMEE", "TAKE_PROFIT", "STOP_LOSS", "SORTIE_FORCEE", "SESSION_CLOSE"}
```

Correspondance signal → motif :
- `"ENTRY_LONG"` / `"ENTRY_SHORT"` → motif `"ENTREE_ARMEE"` dans le trade log
- `"TP"` → `"TAKE_PROFIT"`
- `"SL"` → `"STOP_LOSS"`
- `"SESSION_CLOSE"` → `"SESSION_CLOSE"` (audit #1)
- Filtre C + position ouverte → `"SORTIE_FORCEE"`

---

## RÈGLES CRITIQUES (à ne PAS oublier)

1. **Signal Engine n'accède JAMAIS à β_Kalman** — séparation monde statique / dynamique
2. **Kalman tourne à CHAQUE barre** — pas seulement quand il y a signal
3. **BarState_t est IMMUABLE** — Phase 4 ne le modifie jamais
4. **Joseph form OBLIGATOIRE pour P_t** (prohibition #5) — `P = (I-KH) @ P_pred @ (I-KH).T + outer(K,K) * R`
5. **Filtres A/B ne bloquent JAMAIS les sorties** (TP, SL, SESSION_CLOSE)
6. **Filtre C est IRRÉVERSIBLE** — `is_session_killed` ne revient jamais à False
7. **β_Kalman_prev initialisé à β_OLS** en Phase 1 — pas 0, pas None
8. **Z_score = (Spread − θ_OU) / σ_eq** — formule complète avec θ_OU, dénominateur σ_eq (prohibition #2)
9. **multiplier pour notionnel, PAS tick_value** (prohibition #3)
10. **PnL calculé sur β_Kalman_ENTRÉE** — β_Kalman_SORTIE logué mais pas utilisé
11. **T_limite utilise `hl_operational`** de step4, pas `hl_empirical` (peut être None)
12. **SESSION_CLOSE** = 5ème motif de sortie à 15:30 CT si position encore ouverte (audit #1)
13. **Micro non disponible** pour certains actifs (HO, RB, PA, PL, BZ) → sizing en std uniquement, résidu plus gros

---

## STRUCTURE DES TRADES (pour le backtester)

```python
trade = {
    # Entrée
    "entry_timestamp":   datetime,
    "entry_motif":       "ENTREE_ARMEE",
    "direction":         "LONG" | "SHORT",
    "entry_z":           float,
    "beta_kalman_entry": float,
    "sizing":            dict,   # output de compute_sizing
    
    # Sortie (rempli à la fermeture)
    "exit_timestamp":    datetime,
    "exit_motif":        str,    # "TAKE_PROFIT" | "STOP_LOSS" | "SORTIE_FORCEE" | "SESSION_CLOSE"
    "exit_z":            float,
    "beta_kalman_exit":  float,  # logué seulement, PAS utilisé pour PnL
    "exit_price_a":      float,
    "exit_price_b":      float,
}
```

---

## TESTS À ÉCRIRE

### test_step5_engine.py (synthétique)
- Kalman sur spread OU synthétique → β converge vers β_OLS
- Joseph form : P reste symétrique et PSD après 500 itérations
- NIS moyen ≈ 1.0 sur bruit calibré
- Signal machine : armement → déclenchement → TP sur trajectoire synthétique
- Time-lock : pas d'armement après T_limite
- SESSION_CLOSE : position fermée à 15:30

### test_step5_risk.py (synthétique)
- Filtre A : NIS = 10 → bloque entrée, ne bloque pas TP/SL
- Filtre B : Δβ/β = 0.01 → bloque, guard |β|<1e-6 → bloque
- Filtre C : dérive > seuil → session killed, irréversible
- Filtre C ne bloque pas les sorties mais force SORTIE_FORCEE si position ouverte

### test_step5_sizing.py (déterministe)
- GC/SI : 1 GC std → target notional → découpage SI + SIL correct
- YM/RTY : 1 YM std → target notional → découpage RTY std + M2K micro correct
- CL/HO : HO pas de micro → arrondi std uniquement, résidu documenté
- multiplier utilisé, pas tick_value (vérification croisée)
- assert β_Kalman > 0

### test_integration_step5.py (sur données réelles YM/RTY)
- Pipeline step1→step5 bout en bout
- Session complète sans crash
- Nombre de signaux raisonnable
- P_t reste PSD sur toute la session
