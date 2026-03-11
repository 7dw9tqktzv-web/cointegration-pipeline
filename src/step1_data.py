"""
Étape 1 — Data Validation & Cleaning.

Ingestion CSV Sierra Chart 1min → DataFrame 5min propre par session CME.
Chaque barre est validée ou flaggée. Aucune suppression silencieuse.

Inputs:
    - Fichier CSV Sierra Chart (1min, export BarData.txt)
    - Symbole de l'actif (ex: "GC", "SI")

Outputs:
    - DataFrame 5min avec colonnes: datetime, open, high, low, close, volume,
      price (Close ou Typical Price selon config), session_id, session_break,
      log_return, flags (gap_detected, duplicate, outlier, rollover_discontinuity,
      low_liquidity_day)

Source de vérité : docs/recherche/modele_cointegration_v1_FINAL.docx — Section 4.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ajouter la racine du projet au path pour les imports config
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.contracts import PRICE_TYPE, LOW_LIQ_PCT


# ---------------------------------------------------------------------------
# 1. Ingestion CSV Sierra Chart
# ---------------------------------------------------------------------------

def load_sierra_csv(filepath: str | Path) -> pd.DataFrame:
    """Charge un CSV Sierra Chart 1min et parse les timestamps.

    Input:  filepath — chemin vers le fichier .txt Sierra Chart
    Output: DataFrame indexé par datetime (CT), colonnes brutes nettoyées.
            Les timestamps sont en exchange time (CT) tel qu'exporté par Sierra.
    """
    df = pd.read_csv(filepath, skipinitialspace=True)
    # Normaliser les noms de colonnes (Sierra met des espaces)
    df.columns = df.columns.str.strip().str.lower()
    # Sierra utilise "last" au lieu de "close"
    df.rename(columns={"last": "close"}, inplace=True)

    # Combiner date + time en datetime
    df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
    df.drop(columns=["date", "time"], inplace=True)
    df.set_index("datetime", inplace=True)
    df.sort_index(inplace=True)
    return df


# ---------------------------------------------------------------------------
# 2. Filtrage out_of_session + assignation session_id
# ---------------------------------------------------------------------------

def assign_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Filtre les barres hors session et assigne session_id + session_break.

    Session CME : 17h30 CT → 15h30 CT (jour suivant).
    session_id = date du jour de clôture (YYYYMMDD).
    Barres entre 15:31 et 17:29 exclues (out_of_session).

    Input:  DataFrame 1min avec index datetime
    Output: DataFrame filtré avec colonnes session_id (str) et session_break (bool)
    """
    hours = df.index.hour
    minutes = df.index.minute
    time_minutes = hours * 60 + minutes  # minutes depuis minuit

    open_min = 17 * 60 + 30   # 17:30 = 1050
    close_min = 15 * 60 + 30  # 15:30 = 930

    # In-session : [17:30–23:59] OU [00:00–15:30]
    in_session = (time_minutes >= open_min) | (time_minutes <= close_min)
    n_excluded = (~in_session).sum()
    if n_excluded > 0:
        print(f"  out_of_session: {n_excluded} barres exclues (15:31–17:29 CT)")
    df = df[in_session].copy()

    # Session ID = date de clôture
    # Barres 17:30+ → session = date du lendemain
    # Barres 00:00–15:30 → session = même date
    time_min_filtered = df.index.hour * 60 + df.index.minute
    is_evening = time_min_filtered >= open_min
    # Convertir dates en Timestamps pour pouvoir ajouter un jour
    session_ts = pd.to_datetime(df.index.date)
    session_ts = session_ts.where(~is_evening, session_ts + pd.Timedelta(days=1))
    df["session_id"] = session_ts.strftime("%Y%m%d")

    # Session break = première barre de chaque session
    df["session_break"] = df["session_id"] != df["session_id"].shift(1)

    return df


# ---------------------------------------------------------------------------
# 3. Flags de validation
# ---------------------------------------------------------------------------

def flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Détecte et supprime les timestamps dupliqués. Log le nombre supprimé.

    Input:  DataFrame 1min
    Output: DataFrame sans doublons, avec compteur loggé
    """
    n_dupes = df.index.duplicated().sum()
    if n_dupes > 0:
        print(f"  duplicate: {n_dupes} barres dupliquées supprimées")
        df = df[~df.index.duplicated(keep="first")].copy()
    return df


def flag_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Détecte les trous > 1min dans une session. Met log_return à NaN.

    Input:  DataFrame 1min avec session_id
    Output: DataFrame avec colonne gap_detected (bool)
    """
    dt_diff = df.index.to_series().diff()
    # Gap = écart > 1min DANS la même session (pas sur session_break)
    gap = (dt_diff > pd.Timedelta(minutes=1)) & (~df["session_break"])
    df["gap_detected"] = gap
    n_gaps = gap.sum()
    if n_gaps > 0:
        print(f"  gap_detected: {n_gaps} trous > 1min détectés")
    return df


def compute_log_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule log_return sur close. NaN obligatoire sur session_break et gaps.

    Input:  DataFrame 1min avec session_break et gap_detected
    Output: DataFrame avec colonne log_return
    """
    df["log_return"] = np.log(df["close"] / df["close"].shift(1))
    # RÈGLE ABSOLUE : NaN sur session_break
    df.loc[df["session_break"], "log_return"] = np.nan
    # NaN sur gaps
    df.loc[df["gap_detected"], "log_return"] = np.nan
    return df


def flag_rollover_discontinuity(df: pd.DataFrame) -> pd.DataFrame:
    """Détecte les discontinuités de rollover.

    Condition (V1 §3.2) : |log_return| > 3 × médiane(|log_returns|)
    ET session_break == True.

    Input:  DataFrame 1min avec log_return et session_break
    Output: DataFrame avec colonne rollover_discontinuity (bool)
    """
    abs_lr = df["log_return"].abs()
    median_abs_lr = abs_lr.median()

    rollover = df["session_break"] & (abs_lr > 3 * median_abs_lr)
    df["rollover_discontinuity"] = rollover
    # NaN sur rollover
    df.loc[rollover, "log_return"] = np.nan
    n = rollover.sum()
    if n > 0:
        print(f"  rollover_discontinuity: {n} barres flaggées")
    return df


def flag_outliers(df: pd.DataFrame, k: float = 10.0) -> pd.DataFrame:
    """Détecte les outliers intra-session via MAD robuste.

    Condition : |log_return| > k × MAD(log_returns), hors session_break.
    MAD = Median Absolute Deviation, estimateur robuste (Bandi & Russell 2008).
    k=10 calibré pour futures intraday (k=5 trop agressif, flag ~5% des barres).

    Input:  DataFrame 1min avec log_return, k multiplicateur MAD
    Output: DataFrame avec colonne outlier (bool)
    """
    lr = df["log_return"].dropna()
    mad = (lr - lr.median()).abs().median()
    # Éviter division par zéro
    if mad < 1e-12:
        df["outlier"] = False
        return df

    threshold = k * mad
    outlier = (df["log_return"].abs() > threshold) & (~df["session_break"])
    df["outlier"] = outlier
    # NaN sur outliers
    df.loc[outlier, "log_return"] = np.nan
    n = outlier.sum()
    if n > 0:
        print(f"  outlier: {n} barres flaggées (seuil = {k}xMAD = {threshold:.6f})")
    return df


def flag_low_liquidity_days(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Marque les sessions à faible liquidité.

    Condition (V1 §3.1) : volume_session < pct × médiane(volumes_sessions).
    pct dépend de la classe de l'actif (30% standard, 50% PA).

    Input:  DataFrame 1min avec session_id et volume, symbole de l'actif
    Output: DataFrame avec colonne low_liquidity_day (bool)
    """
    pct = LOW_LIQ_PCT.get(symbol, 0.30)
    session_vol = df.groupby("session_id")["volume"].sum()
    median_vol = session_vol.median()
    low_liq_sessions = session_vol[session_vol < pct * median_vol].index

    df["low_liquidity_day"] = df["session_id"].isin(low_liq_sessions)
    n = len(low_liq_sessions)
    if n > 0:
        print(f"  low_liquidity_day: {n} sessions < {pct*100:.0f}% médiane "
              f"(seuil = {pct * median_vol:,.0f}, médiane = {median_vol:,.0f})")
    return df


# ---------------------------------------------------------------------------
# 4. Price Type — Close ou Typical Price
# ---------------------------------------------------------------------------

def compute_price(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Calcule la colonne 'price' selon le price_type configuré pour l'actif.

    Close pour actifs liquides, Typical Price (H+L+C)/3 sinon.
    Doit être appelée sur les barres 5min (après agrégation) pour que
    le Typical Price utilise les OHLC 5min, pas le dernier 1min.

    Input:  DataFrame avec colonnes high, low, close; symbole de l'actif
    Output: DataFrame avec colonne price
    """
    ptype = PRICE_TYPE.get(symbol, "close")
    if ptype == "typical":
        df["price"] = (df["high"] + df["low"] + df["close"]) / 3
    else:
        df["price"] = df["close"]
    print(f"  price_type: {ptype} pour {symbol}")
    return df


# ---------------------------------------------------------------------------
# 5. Agrégation 5min session-aware
# ---------------------------------------------------------------------------

def aggregate_5min(df: pd.DataFrame) -> pd.DataFrame:
    """Agrège 1min → 5min avec groupby('session_id') OBLIGATOIRE.

    INTERDIT : df.resample('5min') sans groupby session_id.
    Barres incomplètes (< 3 barres 1min sur 5) supprimées.

    Input:  DataFrame 1min avec session_id et toutes les colonnes
    Output: DataFrame 5min propre
    """
    # Flags à propager (OR sur la fenêtre 5min)
    flag_cols = ["gap_detected", "outlier", "rollover_discontinuity",
                 "low_liquidity_day"]

    agg_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "numberoftrades": "sum",
        "session_id": "first",
    }
    for flag in flag_cols:
        if flag in df.columns:
            agg_dict[flag] = "any"

    # Resample session-aware
    groups = []
    for sid, group in df.groupby("session_id"):
        resampled = group.resample("5min").agg(agg_dict)
        # Compteur de barres 1min par bucket pour filtrage des incomplètes
        resampled["_bar_count"] = group.resample("5min")["close"].count()
        resampled["session_id"] = sid
        groups.append(resampled)

    if not groups:
        return pd.DataFrame()

    df5 = pd.concat(groups)
    df5.sort_index(inplace=True)

    # Supprimer barres vides (aucune barre 1min)
    df5 = df5.dropna(subset=["close"])

    # Supprimer barres incomplètes < 3 barres 1min sur 5
    n_incomplete = (df5["_bar_count"] < 3).sum()
    if n_incomplete > 0:
        print(f"  barres_incompletes: {n_incomplete} barres 5min supprimées (< 3/5)")
    df5 = df5[df5["_bar_count"] >= 3].copy()
    df5.drop(columns=["_bar_count"], inplace=True)

    # Recalculer session_break sur les barres 5min
    df5["session_break"] = df5["session_id"] != df5["session_id"].shift(1)

    # Recalculer log_return sur les barres 5min
    df5["log_return"] = np.log(df5["close"] / df5["close"].shift(1))
    df5.loc[df5["session_break"], "log_return"] = np.nan

    # Propager NaN log_return si flags actifs sur la barre
    flag_mask = pd.Series(False, index=df5.index)
    for flag in ["gap_detected", "outlier", "rollover_discontinuity"]:
        if flag in df5.columns:
            flag_mask = flag_mask | df5[flag]
    df5.loc[flag_mask, "log_return"] = np.nan

    return df5


# ---------------------------------------------------------------------------
# 6. Pipeline complet étape 1
# ---------------------------------------------------------------------------

def run_step1(filepath: str | Path, symbol: str) -> pd.DataFrame:
    """Pipeline complet étape 1 : CSV 1min → DataFrame 5min propre.

    Input:  filepath — chemin CSV Sierra Chart
            symbol — symbole de l'actif (ex: "GC")
    Output: DataFrame 5min validé, prêt pour étape 2
    """
    print(f"=== STEP 1 — {symbol} ===")
    print(f"  fichier: {filepath}")

    # 1. Charger
    df = load_sierra_csv(filepath)
    print(f"  barres 1min chargées: {len(df)}")

    # 2. Doublons
    df = flag_duplicates(df)

    # 3. Sessions
    df = assign_sessions(df)
    n_sessions = df["session_id"].nunique()
    print(f"  sessions détectées: {n_sessions}")

    # 4. Gaps
    df = flag_gaps(df)

    # 5. Log returns (1min) — pour détection outliers/rollover
    df = compute_log_returns(df)

    # 6. Rollover
    df = flag_rollover_discontinuity(df)

    # 7. Outliers
    df = flag_outliers(df)

    # 8. Low liquidity
    df = flag_low_liquidity_days(df, symbol)

    # 9. Agrégation 5min
    df5 = aggregate_5min(df)
    print(f"  barres 5min finales: {len(df5)}")

    # 10. Price type — calculé sur OHLC 5min (pas 1min)
    df5 = compute_price(df5, symbol)

    # Résumé des flags
    for flag in ["gap_detected", "outlier", "rollover_discontinuity",
                 "low_liquidity_day"]:
        if flag in df5.columns:
            n = df5[flag].sum()
            if n > 0:
                print(f"  [5min] {flag}: {n}")

    print(f"  sessions finales: {df5['session_id'].nunique()}")
    print(f"  plage: {df5.index.min()} -> {df5.index.max()}")
    print()

    return df5


# ---------------------------------------------------------------------------
# Main — test isolé
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    data_dir = _PROJECT_ROOT / "data" / "raw"

    # Tester sur GC
    gc_files = list(data_dir.glob("GC*"))
    if gc_files:
        df_gc = run_step1(gc_files[0], "GC")
        print("Colonnes:", list(df_gc.columns))
        print("Premières barres:")
        print(df_gc.head(10))
        print()
        print("Stats log_return (5min):")
        print(df_gc["log_return"].describe())

    # Tester sur SI
    si_files = list(data_dir.glob("SI*"))
    if si_files:
        df_si = run_step1(si_files[0], "SI")
        print("Colonnes:", list(df_si.columns))
        print("Premières barres:")
        print(df_si.head(10))
