# CLAUDE.md

Ce fichier guide Claude Code (claude.ai/code) pour travailler sur ce repository.

## Projet

Pipeline de backtesting pour le spread trading mean-reversion sur futures CME.
Barres 5min intraday. Trading manuel. Calibration OLS/OU + filtre de Kalman dynamique.
7 paires : GC/SI, GC/PA, NQ/RTY, YM/RTY, CL/HO, CL/NG, ZC/ZW.

**Statut actuel : V1 complète (214+ tests). V2 en cours — voir `docs/v2/`.**

## Documents de Référence

- Spécification V1 : `docs/recherche/modele_cointegration_v1_FINAL.docx`
- Résultats backtest V1 : `outputs/backtest_diagnostic_v1.md`
- Roadmap et briefings V2 : `docs/v2/`
- Notes de recherche : `docs/recherche/`

Ne jamais improviser une formule ou un paramètre. Vérifier dans les docs d'abord.

## Commandes

```bash
# Activer le venv (Windows/Git Bash)
source venv/Scripts/activate

# Lancer les tests
python -m pytest tests/
python -m pytest tests/test_step1.py -k "test_name"

# Backtest complet (~6min avec cache s2)
# Utiliser verbose=False pour les runs batch
```

## Architecture

```
data/raw/*.csv (Sierra Chart 1min)
    → src/step1_data.py        : découpage session, flags, agrégation 5min
    → src/step2_stationarity.py: tests ADF+KPSS, downsampling, multi-scale
    → src/step3_cointegration.py: OLS, AR(1), MacKinnon, stabilité β
    → src/step4_ou.py          : κ, σ_eq, half-life, paramètres OU
    → src/step5_engine.py      : filtre Kalman, NIS, machine à états (phases 1-3)
    → src/step5_risk.py        : filtres de risque A/B/C (phase 4)
    → src/step5_sizing.py      : sizing beta-neutral, multipliers (phase 5)
    → src/backtester.py        : boucle backtest, anti-look-ahead, PnL, Sharpe
```

Config dans `config/` (contrats, coûts, Q_Kalman, mapping micro, paires).

## Conventions Python

- Python 3.10+, style fonctionnel (fonctions pures, pas de classes sauf nécessité)
- Type hints obligatoires sur toutes les fonctions
- Docstrings avec inputs/outputs sur chaque fonction

## Règles Critiques (Les 7 Interdictions)

1. **Pas de `df.resample()` sans `groupby('session_id')`** — crée des barres fantômes overnight
2. **Jamais σ_diffusion comme dénominateur du Z-score** — utiliser σ_eq (V1) ou σ_rolling (V2)
3. **Utiliser `multiplier` pour le notionnel, pas `tick_value`** — sizing faux ×10
4. **Jamais Q_OU comme Q_Kalman** — le filtre explose
5. **Forme de Joseph obligatoire pour P** — la forme standard est numériquement instable
6. **Valeurs critiques MacKinnon pour le test DF** — les valeurs standard donnent des faux positifs
7. **`spread_cost_rt` appliqué UNE fois par trade** — pas de double comptage

## Invariants (valides pour TOUTES les versions)

1. Anti-look-ahead : la session T n'est JAMAIS dans sa propre fenêtre de calibration
2. Kalman réinitialisé à chaque session (pas de carry-over)
3. Le Signal Engine n'accède JAMAIS à β_Kalman (séparation des mondes)
4. BarState_t est immuable
5. Les sorties (TP/SL/SESSION_CLOSE) ne sont JAMAIS bloquées par les Filtres A/B
6. Le Filtre C est irréversible dans une session
7. Le PnL est calculé sur le sizing de l'ENTRÉE, pas de la sortie

## Conventions Temporelles

- `dt = 1` (une barre de 5min). κ en barres, half-life en barres × 5min.
- Session CME : 17h30–15h30 CT. Trader actif à partir de 01h00 CT (08h00 FR).
- ZC/ZW : clôture pit à 13h20 CT.

## Données

- Export CSV Sierra Chart, 1min, contrat continu (Volume Based + Back Adjusted additif)
- 3 ans d'historique disponible (2023-03 → 2026-03)
- `data/raw/` et `outputs/` sont gitignorés
