# CLAUDE.md

Ce fichier guide Claude Code (claude.ai/code) pour travailler sur ce repository.

## Projet

Pipeline de backtesting pour le spread trading mean-reversion sur futures CME.
Barres 5min intraday. Trading manuel. Architecture bi-couche V2.2.
5 paires eligibles : GC/SI, NQ/RTY, YM/RTY, CL/NG, ZC/ZW.
Paires exclues : GC/PA (sizing residuel 45%), CL/HO (sizing residuel 148%).

**Statut actuel : V2.2 en cours d'optimisation — NQ/RTY quasi break-even (Sharpe -0.10, avgTP +$146), GC/SI signal fort (avgTP +$172). Prochaine etape : analyse MAE/MFE pour calibrer le SL optimal.**

## Architecture V2.2 — Bi-couche

**Couche 1 — Eligibilite (hebdomadaire, 60 sessions)**
- Steps 2-3-4 : I(1), cointegration, beta_OLS, parametres OU
- theta_OU et sigma_eq servent au biais directionnel et au diagnostic (PAS au Z-score)
- HL_intraday P75 par paire (config/contracts.py) determine le T_limite

**Couche 2 — Signal intraday (barre par barre)**
- Z = (Spread - mu_rolling) / sigma_rolling, mu et sigma sur la MEME fenetre N
- N variable par paire : ZC_ZW=20, GC_SI=20, NQ_RTY=24, YM_RTY=24, CL_NG=40
- Entree directe au 1er franchissement Z = +-2.0 (pas de arm-then-trigger)
- Biais directionnel : Z_LT = (spread_ouverture - theta_OU) / sigma_eq
- Sortie en spread-space : references figees a l'entree (spread_entry + sigma_entry)

## Documents de Reference

- Specification V1 : `docs/recherche/modele_cointegration_v1_FINAL.docx`
- Resultats V1 : `outputs/v1/backtest_diagnostic_v1.md`
- Resultats V2.1 : `outputs/v2/backtest_diagnostic_v2.1.md`
- Resultats V2.2 : `outputs/v2/backtest_diagnostic_v2.2.md`
- Briefings V2 : `docs/v2/briefing_v2_2_z_intraday.md`
- Roadmap future : `docs/roadmap/roadmap_v2.md` (V2.3-V2.7, items V3)
- Notes de recherche : `docs/recherche/`

Ne jamais improviser une formule ou un parametre. Verifier dans les docs d'abord.

## Commandes

```bash
# Activer le venv (Windows/Git Bash)
source venv/Scripts/activate

# Lancer les tests (240 passed + 7 skipped)
python -m pytest tests/
python -m pytest tests/test_step1.py -k "test_name"

# Backtest V2.2 (~7min par paire avec cache s2)
python run_backtest_v2_2.py
```

## Architecture Code

```
data/raw/*.csv (Sierra Chart 1min)
    -> src/step1_data.py        : decoupage session, flags, agregation 5min
    -> src/step2_stationarity.py: tests ADF+KPSS, downsampling, multi-scale
    -> src/step3_cointegration.py: OLS, AR(1), MacKinnon, stabilite beta
    -> src/step4_ou.py          : kappa, sigma_eq, half-life, parametres OU
    -> src/step5_engine.py      : Z intraday, Kalman, machine a etats V2.2
    -> src/step5_risk.py        : filtres de risque A/B/C (phase 4)
    -> src/step5_sizing.py      : sizing beta-neutral, multipliers (phase 5)
    -> src/backtester.py        : boucle backtest, anti-look-ahead, PnL, Sharpe
```

Config dans `config/` (contrats, couts, Q_Kalman, HL_INTRADAY_P75, mapping micro, paires).

## Regles Critiques (Les 7 Interdictions)

1. **Pas de `df.resample()` sans `groupby('session_id')`** — cree des barres fantomes overnight
2. **Jamais theta_OU ni sigma_eq dans le Z-score intraday** — utiliser mu_rolling + sigma_rolling meme fenetre N
3. **Utiliser `multiplier` pour le notionnel, pas `tick_value`** — sizing faux x10
4. **Jamais Q_OU comme Q_Kalman** — le filtre explose
5. **Forme de Joseph obligatoire pour P** — la forme standard est numeriquement instable
6. **Valeurs critiques MacKinnon pour le test DF** — les valeurs standard donnent des faux positifs
7. **`spread_cost_rt` applique UNE fois par trade** — pas de double comptage

## Invariants (valides pour TOUTES les versions)

1. Anti-look-ahead : la session T n'est JAMAIS dans sa propre fenetre de calibration
2. Kalman reinitialise a chaque session (pas de carry-over)
3. Le Signal Engine n'accede JAMAIS a beta_Kalman (separation des mondes)
4. BarState_t est immuable
5. Les sorties (TP/SL/SESSION_CLOSE) ne sont JAMAIS bloquees par les Filtres A/B
6. Le Filtre C est irreversible dans une session (reference = beta_Kalman apres burn-in 5 barres en V2.2)
7. Le PnL est calcule sur le sizing de l'ENTREE, pas de la sortie

## Bugs corriges V2.2

- **T_limite** : utilisait HL multi-jour (-> negatif pour NQ/RTY). Fix : HL_INTRADAY_P75 par paire dans config
- **Filtre C** : comparait beta_Kalman a beta_OLS stale (deviation 9x le seuil a barre 0). Fix : burn-in 5 barres, reference = beta_Kalman post-burn-in

## Conventions Temporelles

- `dt = 1` (une barre de 5min). kappa en barres, half-life en barres x 5min.
- Session CME : 17h30-15h30 CT. Trader actif a partir de 01h00 CT (08h00 FR).
- ZC/ZW : cloture pit a 13h20 CT.
- T_limite par paire : ZC_ZW 12:00, GC_SI 12:05, NQ_RTY 11:35, YM_RTY 11:30, CL_NG 10:20 CT.

## Donnees

- Export CSV Sierra Chart, 1min, contrat continu (Volume Based + Back Adjusted additif)
- 3 ans d'historique disponible (2023-03 -> 2026-03)
- `data/raw/` et `outputs/` sont gitignores
