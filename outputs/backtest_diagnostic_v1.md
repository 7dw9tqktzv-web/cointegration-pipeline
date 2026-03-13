# Diagnostic Backtest V1 — 2026-03-13

## Résultat : 0 trades sur 7 paires

| Paire    | Traded/Total | Trades | Blocage principal            |
|----------|-------------|--------|------------------------------|
| CL_HO    | 10/76       | 0      | cointegration_blocking: 66   |
| CL_NG    | 26/76       | 0      | cointegration_blocking: 50   |
| GC_PA    | 9/55        | 0      | cointegration_blocking: 45   |
| GC_SI    | 10/55       | 0      | cointegration_blocking: 45   |
| NQ_RTY   | 0/76        | 0      | cointegration_blocking: 76   |
| YM_RTY   | 5/76        | 0      | cointegration_blocking: 71   |
| ZC_ZW    | 31/73       | 0      | cointegration_blocking: 42   |

## Données

- Source : Sierra Chart, contrats H26/J26/K26/M26 (Oct 2025 — Mars 2026)
- ~106 sessions par actif, ~85 pour GC (contrat plus court)
- 30 sessions de calibration rolling

## Analyse

### Problème 1 : Step3 bloque massivement (cointégration)

Le test de stationnarité du spread (DF + MacKinnon 5%) sur fenêtre rolling 30j
échoue sur 42 à 76 sessions selon la paire. La cointégration est instable
sur cette période de 5 mois.

Causes possibles :
- Période de marché défavorable (tendance forte, corrélations cassées)
- Fenêtre 30j trop courte pour capturer la relation long-terme
- Seuil MacKinnon 5% trop conservateur pour le rolling

### Problème 2 : Sessions tradées mais 0 trades

Même quand step3 passe, le z-score n'atteint jamais les seuils d'armement (±2.5).
Avec σ_eq ~ 0.007 et HL > 200 barres, les excursions au-delà de 2.5σ sont
statistiquement rares sur une seule session de trading (260 barres actives max).

### Problème 3 : Données limitées

5 mois de données sur un seul contrat. Les paires de commodités ont des cycles
de cointégration plus longs. Un backtest sur 2+ ans de données continues
donnerait un échantillon plus représentatif.

## Pistes V2

1. **Fenêtre calibration** : tester 60j au lieu de 30j (plus stable, moins réactif)
2. **Seuil armement** : tester 2.0σ au lieu de 2.5σ (plus de signaux, plus de risque)
3. **Seuil MacKinnon** : tester 10% au lieu de 5% (plus permissif)
4. **Données plus longues** : contrats continus back-adjusted sur 2-5 ans
5. **Fréquence** : tester 15min au lieu de 5min (plus de données par fenêtre)

## Conclusion

Le pipeline fonctionne correctement — il est conservateur par design.
Le résultat 0-trade est une information de calibrage, pas un bug.
Le modèle V1 avec ces paramètres et cette période n'identifie pas
d'opportunités suffisamment claires pour trader.
