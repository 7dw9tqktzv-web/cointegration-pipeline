# Analyse Approfondie : Cointegration et Trading de Paires
## Synthese Croisee PDF + 5 Videos + Analyse des Slides

**Sources analysees :**
- PDF : "Modelisation Avancee de la Cointegration en Trading de Paires" (24 pages)
- V1 : "Comprendre le Processus d'Ornstein-Uhlenbeck" (FrenchQuant, 32min) - 25 frames analysees
- V2 : "Introduction to Pairs Trading" (Quantopian, 47min) - 17 frames analysees
- V3 : "Integration, Cointegration, and Stationarity" (Quantopian, 21min) - 13 frames analysees
- V4 : "Overfitting" (Quantopian, 18min) - 22 frames analysees
- V5 : "Kalman Filters" (Quantopian, 11min) - 31 frames analysees

---

# TABLE DES MATIERES

1. [Fondations Statistiques](#1-fondations-statistiques)
2. [Cointegration : Theorie et Tests](#2-cointegration)
3. [Modele AR(1) Discret](#3-modele-ar1---autoregressive-dordre-1)
4. [Processus d'Ornstein-Uhlenbeck](#4-processus-dornstein-uhlenbeck-ou)
5. [Filtre de Kalman](#5-filtre-de-kalman)
6. [Isomorphisme AR(1) <-> OU](#6-isomorphisme-ar1----ornstein-uhlenbeck)
7. [Synergie Hybride Kalman + OU](#7-synergie-hybride--kalman--ou)
8. [Construction et Gestion du Spread](#8-construction-et-gestion-du-spread)
9. [Overfitting et Biais Statistiques](#9-overfitting-et-biais-statistiques)
10. [Optimisation des Seuils (Bertram)](#10-optimisation-des-seuils--frontieres-de-bertram)
11. [Considerations Pratiques](#11-considerations-pratiques)
12. [Synthese Comparative des Modeles](#12-synthese-comparative-des-modeles)

---

# 1. FONDATIONS STATISTIQUES

## 1.1 Stationnarite (V3, PDF p.3)

### Intuition : qu'est-ce que la stationnarite ?

**Analogie :** Imaginez un thermometre dans une piece climatisee. La temperature fluctue legerement autour de 20°C mais revient toujours autour de cette valeur. Le thermometre vous donne des lectures differentes a chaque instant, mais les PROPRIETES de ces lectures (la moyenne ~20°C, l'amplitude des fluctuations ~1°C) restent les memes. C'est un processus stationnaire. Maintenant imaginez le meme thermometre dans une piece dont le chauffage augmente progressivement : la temperature monte de 15°C a 30°C sur la journee. Les proprietes changent au fil du temps. C'est un processus NON stationnaire.

### Definition rigoureuse (wide-sense stationarity)

Une serie temporelle {X_t} est stationnaire au sens large si :

```
1. E[X_t] = mu,  pour tout t              (moyenne constante)
2. Var(X_t) = sigma^2,  pour tout t       (variance constante)
3. Cov(X_t, X_{t+h}) = gamma(h),          (autocovariance ne depend que du decalage h, pas de t)
```

**Slide V3 (00:28)** -- Le notebook Jupyter affiche :
> "A commonly untested assumption in time series analysis is the stationarity of the data. Data are stationary when the parameters of the data generating process do not change over time."

**Code visible sur le slide V3 (00:28) :**
```python
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint, adfuller
import matplotlib.pyplot as plt

def generate_datapoint(params):
    mu = params[0]
    sigma = params[1]
    return np.random.normal(mu, sigma)

# Serie stationnaire : params = (0, 1), T = 100
params = (0, 1)
T = 100
A = pd.Series(index=range(T))
for t in range(T):
    A[t] = generate_datapoint(params)
```

### Pourquoi c'est fondamental pour le quant

**V3 :** "All of our statistical tests and models -- autoregressive models, moving average models -- are based on this idea of stationarity. You're fitting to a probability distribution, and you want those characteristics to stay the same."

**Consequence concrete :** Si vous calibrez un modele de pairs trading sur une periode ou le spread est stationnaire, et que la stationnarite se brise (regime shift), votre modele va PERDRE de l'argent systematiquement parce que ses predictions sont basees sur une distribution qui n'existe plus.

**V3 :** "Our typical descriptive statistics just don't mean anything" sur une serie non-stationnaire. La moyenne, l'ecart-type, la correlation -- tout est inutile si la distribution sous-jacente change.

### Le piege des tests

**Slide V3 (10:58)** -- Graphe montrant une serie temporelle volatile (rendements), oscillant entre -400 et +500, de fev a dec 2014. En dessous, la note :
> "IMPORTANT NOTE: As always, you should not naively assume that because a time series is stationary in the past it will continue to be stationary in the future."

**V3 :** Un processus avec une tendance subtile comme sin(t) peut tromper le test ADF. "This kind of illustrates the limitations of these tests... looking at graphs to tell us whether we are wrong, not whether we are right."

**Regle du quant :** Ne JAMAIS se fier a un seul test ou a l'inspection visuelle. Croiser ADF + KPSS + Hurst + inspection des residus.

## 1.2 Ordres d'Integration (V3, PDF p.2-3)

### Intuition

**Analogie :** Pensez aux ordres d'integration comme a des "niveaux de lissage" :
- **I(0)** : Un signal brut stationnaire (bruit blanc). C'est le sable sur une plage plate.
- **I(1)** : La somme cumulee d'un I(0). C'est comme une marche aleatoire : vous faites un pas a gauche ou a droite au hasard, et votre POSITION cumule ces pas. Le prix d'une action est typiquement I(1).
- **I(2)** : La somme cumulee d'un I(1). C'est encore plus lisse, comme une courbe parabolique avec du bruit.

### Formalisation

```
I(0) : serie stationnaire (ex: rendements d'actions, bruit blanc)
I(1) : serie dont la PREMIERE difference est stationnaire (ex: prix d'actions)
I(d) : serie necessitant d differenciation pour devenir stationnaire
```

**Construction :**
- Somme cumulative d'un I(0) -> I(1)
- Differenciation d'un I(1) -> I(0) (rendements a partir des prix)

**Notation (V3) :** Operateur de retard L : L(X_t) = X_{t-1}
Differences premieres : (1 - L) * X_t = X_t - X_{t-1}

**Application financiere (V3) :** Les prix sont generalement I(1), les rendements sont I(0). Le notebook V3 le demontre sur des donnees Microsoft 2014-2015 : le test ADF rejette la stationnarite pour les prix, mais l'accepte pour les rendements (additifs et multiplicatifs).

## 1.3 Test ADF - Augmented Dickey-Fuller (V3, PDF p.3)

### Intuition

**Analogie :** Le test ADF est comme un "detecteur de marche aleatoire". Il pose la question : "Est-ce que cette serie se comporte comme un ivrogne qui titube au hasard (marche aleatoire), ou comme un chien en laisse qui revient toujours vers son maitre (mean-reverting) ?"

### Hypotheses et interpretation

```
H0 : la serie a une racine unitaire (non-stationnaire, marche aleatoire)
H1 : la serie est stationnaire

p-value < 0.05 => on REJETTE H0 => serie probablement stationnaire
p-value >= 0.05 => pas de preuve suffisante de stationnarite
```

**Slide V3 (19:20) -- Resultat du test coint :**
```python
from statsmodels.tsa.stattools import coint
coint(X1, X2)
# Output: (-4.0059, p_value, [-3.05, -2.88, -2.57])
# Valeurs critiques a 1%, 5%, 10%
```

### Limites identifiees (V3, PDF p.3)

1. Sensible a la longueur de l'echantillon
2. Peut echouer sur des tendances subtiles (sin, cycles lents)
3. Le choix du nombre de lags augmentes affecte le resultat
4. Risque de faux positifs a 5% par construction

**Complement (PDF p.3) :** L'exposant de Hurst est un outil complementaire :
- H < 0.5 : anti-persistant (mean-reverting) -> favorable au pairs trading
- H = 0.5 : marche aleatoire
- H > 0.5 : persistant (trending)

---

# 2. COINTEGRATION

## 2.1 Definition Formelle (V3, PDF p.2)

### Intuition : la metaphore du chien en laisse

**Analogie (V2) :** Imaginez un homme promenant son chien en laisse dans un parc. L'homme suit un chemin (serie I(1)). Le chien zigzague autour (aussi I(1)). Pris individuellement, aucun des deux ne revient a une position fixe. MAIS la DISTANCE entre l'homme et le chien (le spread, la longueur de la laisse) est bornee et oscille autour d'une moyenne. Cette distance est I(0) -- stationnaire. L'homme et le chien sont COINTEGRES.

### Formalisation

**Slide V3 (14:16) :**
> "For some set of time series (X_1, X_2, ..., X_k), if all series are I(1), and some linear combination of them is I(0), we say the set of time series is cointegrated."

La combinaison lineaire est definie comme :

```
Y = b_1 * X_1 + b_2 * X_2 + ... + b_k * X_k
```

Si Y est I(0) (stationnaire), alors {X_1, ..., X_k} est un ensemble cointegre.

**Slide V3 (14:16) -- Intuition du notebook :**
> "The intuition here is that for some linear combination of the series, the result lacks much auto-covariance and is mostly noise. This is useful for cases such as pairs trading, in which we find two assets whose prices are cointegrated."

### ATTENTION - Cointegration =/= Correlation (V2, PDF p.1)

C'est l'erreur la plus repandue et la plus dangereuse en finance quantitative.

| Propriete | Correlation | Cointegration |
|-----------|------------|---------------|
| Mesure | Co-mouvement des RENDEMENTS | Stationnarite du SPREAD des prix |
| Temporalite | Instantanee, peut etre ephemere | Relation de long terme |
| Implication | "Ils bougent ensemble" | "Ils REVIENNENT l'un vers l'autre" |
| Contre-exemple (V2) | 2 series divergentes : corr ~1, pas cointegrees | 2 series non-correlees mais cointegrees |

**V2 :** "Cointegration is not correlation. This is a really important thing, a lot of people confuse the two."

**Demonstration sur les slides V2 :** Le notebook montre deux exemples :
1. Deux series avec correlation ~1 mais PAS cointegrees (elles divergent)
2. Deux series avec correlation ~0 MAIS cointegrees (la difference mean-reverts)

## 2.2 Methode d'Engle-Granger (PDF p.2-3, V3)

### Intuition

**Analogie :** C'est comme trouver le "taux de change" entre deux actifs. Si 1 unite d'actif A vaut beta unites d'actif B, alors le spread (A - beta*B) devrait etre ~ constant. Engle-Granger trouve ce beta par regression, puis verifie que le spread est bien stationnaire.

### Procedure en 2 etapes

**Etape 1 :** Regression MCO (OLS)
```
Y_t = beta * X_t + epsilon_t
```

- beta = hedge ratio (ratio de couverture)
- epsilon_t = residus = spread

**Etape 2 :** Test ADF sur les residus epsilon_t
- Si ADF rejette H0 => residus stationnaires => X et Y sont cointegres

**Slide V3 (19:20) -- Implementation Python :**
```python
from statsmodels.tsa.stattools import coint
# Test direct de cointegration
coint(X1, X2)
# Retourne : (test_statistic, p_value, critical_values)
```

**Slide V2 (30:23) -- Heatmap des p-values :**
Le notebook affiche une heatmap Seaborn coloree (RdYlGn_r) montrant les p-values du test de cointegration pour toutes les paires parmi {ABGB, ASTI, CSUN, DQ, FSLR, SPY}. Seule la paire **(ABGB, FSLR)** est identifiee comme cointegree (p-value < 0.05).

```python
scores, pvalues, pairs = find_cointegrated_pairs(prices_df)
seaborn.heatmap(pvalues, xticklabels=symbol_list, yticklabels=symbol_list,
                cmap='RdYlGn_r', mask=(pvalues >= 0.05))
# Output: [('ABGB', 'FSLR')]
```

### Beta et hedge ratio (V2, V3)

**V2 :** Le beta de regression = 1.536 dans l'exemple. Cela signifie que pour chaque unite de ABGB, il faut shorter 1.536 unites de FSLR pour construire un spread market-neutral.

**Pourquoi ne pas prendre simplement Y - X ? (V2) :** Si les deux actifs sont a des echelles differentes (ABGB ~21$, FSLR ~60$), la difference brute est dominee par l'actif le plus cher. Le beta normalise.

```
Spread = Y_t - beta * X_t
```

### Limites critiques (PDF p.3-4)

1. **Beta STATIQUE** : estime sur une fenetre historique fixe, ne s'adapte pas
2. **Lookback window arbitraire** : 6 mois ? 12 mois ? Le choix est empirique
3. **Deterioration progressive** : les relations fondamentales evoluent (M&A, reglementation, etc.)
4. **Drawdowns massifs** quand la stationnarite du spread se brise

=> C'est EXACTEMENT ce qui motive la transition vers AR(1), Kalman, et OU.

---

# 3. MODELE AR(1) - AUTOREGRESSIVE D'ORDRE 1

## 3.1 Formalisation (PDF p.4-5)

### Intuition

**Analogie :** L'AR(1) est comme un ressort attache a un mur. La position du ressort a l'instant t+1 depend de sa position a l'instant t, avec une force de rappel proportionnelle a l'ecart par rapport a l'equilibre. Plus phi est proche de 1, plus le ressort est "mou" (retour lent). Plus phi est petit, plus le ressort est "raide" (retour rapide).

### Equation

```
S_t = c + phi * S_{t-1} + epsilon_t
```

ou :
- S_t : valeur du spread a l'instant t
- c : constante (drift)
- phi : coefficient autoregressif (persistance)
- epsilon_t ~ N(0, sigma^2) : bruit blanc (innovation)

**Condition de stationnarite :** |phi| < 1 (strictement)

- Si |phi| -> 1 : processus hautement persistant, quasi-marche aleatoire => mean reversion trop lente pour etre profitable
- Si |phi| << 1 : mean reversion rapide, exploitable

**Moyenne d'equilibre a long terme :**
```
mu = E[S_t] = c / (1 - phi)
```

## 3.2 Demi-Vie (Half-Life) (PDF p.5-6)

### Intuition

**Analogie :** La demi-vie est le temps qu'il faut pour que le "ressort" revienne a MI-CHEMIN de sa position d'equilibre. Si un spread est a +10 points au-dessus de sa moyenne, apres une demi-vie, il sera a ~+5 points.

### Formule

```
t_{1/2} = -ln(2) / ln(phi) = ln(2) / ln(1/phi)
```

**Interpretation pour le trading (PDF p.6) :**
- Half-life COURTE (quelques jours) : rotation rapide du capital, faible exposition au risque
- Half-life LONGUE (plusieurs mois) : capital immobilise, risque de structural break

**Filtre pre-trade :** Les algorithmes imposent typiquement :
```
quelques jours < t_{1/2} < quelques semaines
```
Les paires hors de cette plage sont REJETEES.

## 3.3 Signal de Trading : Z-Score (PDF p.6, V2)

### Intuition

**Analogie :** Le z-score est comme un "radar de deviation". Il repond a la question : "A quel point le spread actuel est-il anormal par rapport a son comportement recent ?" Un z-score de +2 signifie que le spread est a 2 ecarts-types AU-DESSUS de sa moyenne historique -- c'est une situation "extreme" qui a de bonnes chances de se corriger.

### Procedure standard

```
1. Calculer mu_hat (moyenne glissante) et sigma_hat (ecart-type glissant) du spread
2. Normaliser : z_t = (S_t - mu_hat) / sigma_hat
3. Regles de trading :
   - z_t > +2.0  : SHORT le spread (sureevaluation relative)
   - z_t < -2.0  : LONG le spread (sous-evaluation relative)
   - z_t croise 0 : CLOTURE (retour a l'equilibre)
```

### Le piege du look-ahead bias (V2)

**V2 :** "The spread is based on this estimation of beta, but beta's computation is based on ALL of the data... it's an inaccurate representation of predictions we would have been able to make."

**Slide V2 (43:40) -- Solution : rolling statistics :**
```python
# Rolling beta sur 30 jours
rolling_beta = pd.ols(y=S1, x=S2, window_type='rolling', window=30)
spread = S2 - rolling_beta.beta['x'] * S1

# Moving averages
spread_mavg1 = pd.rolling_mean(spread, window=1)    # valeur actuelle
spread_mavg30 = pd.rolling_mean(spread, window=30)   # moyenne 30 jours
```

**V2 :** "This is now no longer using information from the future... often times you'll compute this and you'll be like 'oh well this doesn't look as good' -- well yeah, because the stuff that looked really good was using information from the future."

## 3.4 Limites de l'AR(1) (PDF p.6-7)

1. **Temps discret vs marche continue** : ordres traites en continu (nanosecondes), signal genere entre 2 pas de temps => slippage
2. **Homoscedasticite** : suppose sigma constant, or les marches ont du volatility clustering
3. **Seuils heuristiques** : le choix de +/-2 sigma est ARBITRAIRE, sans fondement d'optimisation mathematique
4. **Beta statique** : meme probleme qu'Engle-Granger

---

# 4. PROCESSUS D'ORNSTEIN-UHLENBECK (OU)

## 4.1 Equation Differentielle Stochastique (V1, PDF p.11)

### Intuition : les deux forces en equilibre

**Analogie (V1) :** Imaginez une bouee dans un lac attachee par un elastique au fond. Le VENT (dW_t, aleatoire) pousse la bouee dans des directions imprevisibles. L'ELASTIQUE (theta * (mu - X_t)) la ramene toujours vers sa position d'equilibre. Plus la bouee s'eloigne, plus l'elastique tire fort (force proportionnelle a l'ecart). C'est exactement le processus OU : une competition entre bruit aleatoire et force de rappel.

### EDS (telle que visible sur le slide V1 a 00:00)

**Slide V1 (00:00) -- Definition complete :**
```
dX_t = theta * (mu - X_t) * dt + sigma * dW_t
```

Ou :
- **X_t** : valeur du processus a l'instant t
- **theta** (> 0) : vitesse de retour a la moyenne (mean reversion speed)
- **mu** : moyenne a long terme vers laquelle le processus revient
- **sigma** : volatilite du processus
- **dW_t** : increment du mouvement brownien (Wiener)

### Decomposition du terme de drift (V1)

**Terme deterministe :** theta * (mu - X_t) * dt

La force de rappel est PROPORTIONNELLE a l'ecart : si X_t est loin de mu, le rappel est fort. Si X_t est proche de mu, le rappel est faible.

**V1 :** "C'est deux forces en quelque sorte qui s'equilibrent -- plus theta grand, plus le processus retournera vers sa moyenne, mais aussi plus sigma est grand, plus il aura tendance a s'ecarter de cette moyenne."

## 4.2 Resolution Analytique (V1, PDF p.12)

### Methode (visible sur les slides V1 de 00:00 a 06:24)

Le slide V1 presente la resolution COMPLETE en 5 etapes :

**Etape 1 - Changement de variable :**
```
Y_t = X_t - mu  =>  dY_t = dX_t  (car mu est constant)
```

**Etape 2 - Substitution dans l'EDS :**
```
dY_t = -theta * Y_t * dt + sigma * dW_t
```

**Etape 3 - Facteur d'integration :** Multiplier par e^(theta*t)
```
e^(theta*t) * dY_t = -e^(theta*t) * theta * Y_t * dt + sigma * e^(theta*t) * dW_t
```

**Etape 4 - Integration stochastique sur [0, t] :**

**Etape 5 - Solution pour Y_t :**
```
Y_t = Y_0 * e^(-theta*t) + sigma * integral_0^t e^(-theta*(t-s)) dW_s
```

**Retour a la variable originale (slide V1 06:24) :**
```
X_t = X_0 * e^(-theta*t) + mu * (1 - e^(-theta*t)) + sigma * integral_0^t e^(-theta*(t-s)) dW_s
```

### Interpretation de la solution

**Decomposition :**
- `X_0 * e^(-theta*t)` : influence DECROISSANTE de la condition initiale (oubli exponentiel)
- `mu * (1 - e^(-theta*t))` : convergence vers mu (le processus "apprend" ou est la moyenne)
- Integrale stochastique : fluctuations aleatoires accumulees

**V1 :** "Cette solution n'est pas tres pratique parce qu'on a quand meme une integrale a resoudre numeriquement."

## 4.3 Discretisation d'Euler (V1)

### L'approximation pratique

**Slide V1 (11:12) -- Formule de mise a jour :**
```
X_{t+1} = X_t + theta * (mu - X_t) * Delta_t + sigma * sqrt(Delta_t) * epsilon_t
```

ou epsilon_t ~ N(0, 1) est un bruit gaussien standard.

**Slide V1 (11:12) -- Note importante (en rouge) :**
> "Il est important de noter que l'approximation d'Euler est une methode d'approximation, ce qui signifie qu'elle peut ne pas etre exacte, en particulier pour de grands pas de temps Delta_t. Cependant, elle est souvent suffisamment precise pour de nombreuses applications pratiques."

### Code de simulation (slide V1 12:00)

```python
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm
from scipy.optimize import minimize
from statsmodels.api import OLS

def simulate_ou_process(theta, mu, sigma, X0, T, dt):
    N = int(T / dt)
    X = np.zeros(N)
    X[0] = X0
    for i in range(1, N):
        dW = np.sqrt(dt) * np.random.randn()
        X[i] = X[i-1] + theta * (mu - X[i-1]) * dt + sigma * dW
    return X
```

### Graphes de simulation (slides V1)

Les slides V1 montrent plusieurs simulations avec differents parametres :

| Parametres | Comportement observe |
|-----------|---------------------|
| theta=3, mu=2, sigma=1 | Mean-reverting modere autour de mu=2, range ~[0.5, 2.0] |
| theta=3, mu=0.3, sigma=1 | Plus volatile, ecarts significatifs (-1.5 a 2.0) |
| theta=3, mu=3, sigma=2 | Forte volatilite, convergence depuis X0=0 vers mu=3 |
| theta=2, mu=2, sigma=0.3 | Tres "serre" autour de mu=2, range ~[1.8, 2.4] |

**Observation cle (V1) :** theta grand + sigma petit = processus tres concentre autour de mu. theta petit + sigma grand = grandes excursions.

## 4.4 Distribution de Transition (PDF p.12)

La loi conditionnelle est gaussienne :

```
X_t | X_s ~ N(
    X_s * e^{-theta*(t-s)} + mu * (1 - e^{-theta*(t-s)}),
    sigma^2 / (2*theta) * (1 - e^{-2*theta*(t-s)})
)
```

C'est cette distribution qui permet l'estimation par MLE.

## 4.5 Demi-Vie en Temps Continu (PDF p.11)

```
t_{1/2} = ln(2) / theta
```

**Lien avec l'AR(1) :** t_{1/2} = -ln(2) / ln(phi), via la relation phi = e^{-theta*dt}

## 4.6 Estimation des Parametres (V1, PDF p.12)

### Methode des Moments (V1) -- "Tres peu demandeuse en calcul"

**Slide V1 (06:24) -- Procedure complete :**

**1. Estimation de mu :**
```
mu_hat = (1/N) * sum(X_t)   (moyenne empirique)
```

**2. Estimation de theta** (par regression lineaire) :

On discretise l'EDS :
```
Delta_X_t = theta * (mu - X_{t-1}) * Delta_t + sigma * sqrt(Delta_t) * epsilon_t
```

Puis on effectue une regression lineaire de Delta_X_t sur (mu - X_{t-1}) * Delta_t.
Le coefficient de la regression donne theta.

**3. Estimation de sigma :**
```
sigma = std(residus) / sqrt(Delta_t)
```

**Code visible sur les slides V1 (23:12-27:12) :**
```python
def method_moments(X, dt):
    dX = np.diff(X)
    K = X[:-1]
    mu = X.mean()
    exog = (mu - K) * dt
    model = OLS(dX, exog)
    res = model.fit()
    theta = res.params[0]
    resid = dX - theta * exog
    sigma = resid.std() / np.sqrt(dt)
    return theta, mu, sigma
```

### Maximum de Vraisemblance - MLE (V1, PDF p.12)

**Slide V1 (09:36) -- Densite conditionnelle :**
```
f(Delta_X_t | X_{t-1}) = (1 / (sigma * sqrt(2*pi*Delta_t))) *
    exp(-(Delta_X_t - theta*(mu - X_{t-1})*Delta_t)^2 / (2*sigma^2*Delta_t))
```

**Vraisemblance :**
```
L(theta, mu, sigma) = product_{t=2}^{T} f(Delta_X_t | X_{t-1})
```

**Procedure (V1) :**
1. Initialiser les parametres avec la methode des moments
2. Maximiser la log-vraisemblance (ou minimiser -log L) via scipy.optimize.minimize
3. Les estimateurs MLE sont asymptotiquement normaux, convergents, et efficaces

**Code visible sur le slide V1 (17:36-24:00) :**
```python
def ll(params, X, dt):
    theta, mu, sigma = params
    dX = np.diff(X)
    X_prev = X[:-1]
    f = np.sum(np.log(sigma * np.sqrt(2 * np.pi * dt)) +
               (dX - theta * (mu - X_prev) * dt)**2 / (2 * sigma**2 * dt))
    if np.isinf(f) or not np.isfinite(f):
        return 1e10
    return f

# Strategie hybride : MoM pour initialiser, puis MLE pour affiner
init_params = method_moments(X, dt)
res = minimize(ll, init_params, args=(X, dt), method='Nelder-Mead')
```

### Resultats experimentaux (V1)

**Slide V1 (26:24-27:12) -- Estimations sur simulation :**

| Methode | theta_hat | mu_hat | sigma_hat |
|---------|-----------|--------|-----------|
| Valeurs vraies | 5.0 | 2.0 | 0.5 |
| Methode des Moments | 4.96 | 2.008 | 0.507 |
| MLE (Nelder-Mead) | 4.37 | 2.008 | 0.508 |

**V1 :** "La methode des moments est tres tres peu demandeuse en calcul mais donne des resultats tres tres bons."

**Strategie recommandee (V1) :** "J'utilise la methode des moments pour initialiser mes parametres et on reajuste avec le maximum de vraisemblance."

---

# 5. FILTRE DE KALMAN

## 5.1 Concept Fondamental (V5, PDF p.7-9)

### Intuition : le detective bayesien

**Analogie :** Le filtre de Kalman est comme un detective qui a une THEORIE sur ce qui se passe (son etat de croyance), et qui recoit des TEMOIGNAGES bruites (les observations). A chaque nouveau temoignage :
- Si le temoignage est COHERENT avec sa theorie : il renforce sa confiance et ajuste peu
- Si le temoignage CONTREDIT sa theorie : il remet en question sa croyance et ajuste beaucoup
- La qualite du temoignage (fiable ou pas) influence le poids qu'il lui donne

**V5 :** "I have a data stream, it's noisy, and I want to know what the true underlying state is."

**Slide V5 (00:02) -- Definition du notebook :**
> "The Kalman filter is an algorithm that uses noisy observations of a system over time to estimate the parameters of the system (some of which are unobservable) and predict future observations. At each time step, it makes a prediction, takes in a measurement, and updates itself based on how the prediction and measurement compare."

### Pourquoi pas une simple moyenne mobile ? (V5)

**Slide V5 (09:39) -- Graphe comparatif "Kalman filter estimate of average" :**
Le slide montre un graphe avec 5 courbes superposees :
- **Kalman Estimate** (bleu) : tres reactif, suit le prix sans lag
- **Donnees brutes x** (vert) : serie de prix bruitee, de ~60$ a ~140$
- **Moving Average 30 jours** (rouge) : lag modere
- **Moving Average 60 jours** : lag plus important
- **Moving Average 90 jours** : lag le plus important

**Observation cle :** Le filtre de Kalman s'adapte DYNAMIQUEMENT a la reactivite necessaire, alors que les moving averages sont fixes.

**V5 :** "You don't have to worry about adjusting window length... a Kalman filter will tell you that, it will do that work for you."

## 5.2 Representation Espace-Etat (PDF p.8)

### Intuition

**Analogie :** C'est comme piloter un avion dans le brouillard. Vous avez :
- Un **modele de vol** (equation d'etat) qui predit ou l'avion DEVRAIT etre (basee sur la vitesse, le cap, etc.)
- Des **instruments** (equation de mesure) qui vous donnent des lectures BRUITEES (radar, GPS avec erreur)

Le filtre de Kalman combine le modele et les instruments pour donner la MEILLEURE estimation de la position reelle.

### Equations

**Equation de mesure (observation) :**
```
Y_t = H * X_t + v_t,   v_t ~ N(0, R)
```
- Y_t : prix observe (bruite)
- X_t : etat cache (vrai beta, vraie position)
- R : variance du bruit de mesure

**Equation d'etat (transition) :**
```
X_t = F * X_{t-1} + w_t,   w_t ~ N(0, Q)
```
- F : matrice de transition (comment l'etat evolue)
- Q : variance du bruit de systeme (incertitude sur l'evolution)

### Exemple "Toy" du notebook (V5) -- Balle en chute libre

**Slide V5 (00:51) -- Formule cinematique :**
```
x_t = x_{t-1} + v_{t-1} * dt - (1/2) * g * dt^2
```

Le filtre traque la position malgre le bruit de la camera. Apres quelques iterations, il "s'accroche" a la trajectoire reelle meme avec des mesures bruitees et une mauvaise initialisation.

## 5.3 Cycle Recursif Predict-Update (PDF p.8-9, V5)

### Phase 1 - Prediction (a priori) :
```
X_t|t-1 = F * X_{t-1|t-1}                          (etat predit)
P_t|t-1 = F * P_{t-1|t-1} * F^T + Q                (covariance predite)
```

### Phase 2 - Mise a jour (a posteriori) :
```
y_t = Y_t - H * X_t|t-1                             (innovation = erreur de prevision)
K_t = P_t|t-1 * H^T / (H * P_t|t-1 * H^T + R)      (gain de Kalman)
X_t|t = X_t|t-1 + K_t * y_t                          (etat corrige)
P_t|t = (I - K_t * H) * P_t|t-1                      (covariance corrigee)
```

## 5.4 Le Gain de Kalman : L'Intelligence du Filtre (PDF p.9, V5)

### Intuition

Le gain de Kalman K_t est le "curseur de confiance" entre le modele et les donnees :

```
K_t -> 0  :  "Je fais confiance a mon modele, j'ignore la donnee"
             (quand R est grand, le bruit de mesure est fort)

K_t -> 1  :  "Je fais confiance aux donnees, j'ajuste mon modele"
             (quand Q est grand, l'incertitude sur l'etat est forte)
```

**V5 :** "The nice thing is that on every step the Kalman filter gives you an estimate but it also gives you a confidence interval around that estimate."

## 5.5 Application a la Regression Dynamique (Beta Dynamique) (V5)

### Le probleme du beta statique

**Slide V5 (09:40) -- Linear regression setup :**
```python
# Equation : y_i = alpha + beta * x_i
start = '2012-01-01'
end = '2015-01-01'
y = get_pricing('AMZN', fields='price', start_date=start, end_date=end)
x = get_pricing('SPY', fields='price', start_date=start, end_date=end)
```

**Slide V5 (07:40-07:59) -- Scatter plot AMZN vs SPY :**
Le slide montre un scatter plot spectaculaire avec des points colores par date (2012 en bleu -> 2014 en rouge). Axes : SPY (125-210) vs AMZN (150-410). De MULTIPLES lignes de regression sont superposees, chacune correspondant a un instant different. La pente CHANGE clairement au fil du temps.

**V5 :** "If you just drew one beta through all of this data and were like 'this works'... it's also better than choosing a lookback window because again, what lookback window do you choose?"

### Implementation avec pykalman (slides V5)

**Slide V5 (03:14/09:17) -- Code Kalman pour regression lineaire :**
```python
from pykalman import KalmanFilter

delta = 1e-1
trans_cov = delta / (1 - delta) * np.eye(2)  # Variance du random walk
obs_mat = np.expand_dims(np.vstack([[x], [np.ones(len(x))]]).T, axis=1)

kf = KalmanFilter(
    n_dim_obs=1,                         # y est 1-dimensionnel
    n_dim_state=2,                        # (beta, alpha) est 2-dimensionnel
    initial_state_mean=[0, 0],
    initial_state_covariance=np.ones((2, 2)),
    transition_matrices=np.eye(2),        # Random walk : etat = etat precedent + bruit
    observation_matrices=obs_mat,          # y = beta*x + alpha
    observation_covariance=2,
    transition_covariance=trans_cov
)

state_means, state_covs = kf.filter(y.values)
```

**Slide V5 (07:40) -- Graphe des estimations beta et alpha au fil du temps :**
Deux panneaux :
- **Slope (beta)** : varie de ~14 a ~24 entre 2012 et 2014, avec un pic vers jan 2014
- **Intercept (alpha)** : varie de ~1.34 a ~1.42, en miroir inverse du beta

### Application aux rendements (slides V5)

**Slide V5 (09:56/10:05) -- Code pour les rendements :**
```python
x_r = x.pct_change()[1:]
y_r = y.pct_change()[1:]

# Kalman filter sur les rendements
kf_r = KalmanFilter(n_dim_obs=1, n_dim_state=2,
                    initial_state_mean=[0, 0],
                    initial_state_covariance=np.ones((2, 2)),
                    transition_matrices=np.eye(2),
                    observation_matrices=obs_mat_r,
                    observation_covariance=1,
                    transition_covariance=trans_cov_r)

state_means_r, _ = kf_r.filter(y_r.values)
```

**Slide V5 (10:05) -- Scatter plot des rendements AMZN vs SPY :**
Le slide montre le scatter des rendements avec les lignes de regression Kalman colorees par date ET la ligne OLS statique en gris. Les lignes Kalman "tournent" au fil du temps, montrant l'evolution du beta.

### Generalisations (V5)

**Slide V5 (11:31) :**
> "We can use a Kalman filter to model non-linear transition and observation functions (extended/unscented Kalman filters). We can also specify non-Gaussian errors, useful for financial data with heavy-tailed distributions."
> "There are algorithms for inferring input parameters (covariance matrices, initial state) from data using pykalman.em()."

## 5.6 Calibration : Q et R (PDF p.10)

Les matrices Q et R sont critiques. Determinees par :
- **Maximum de vraisemblance (MLE)** sur les innovations du filtre
- Ou **algorithme EM** (Esperance-Maximisation) via `pykalman.em()`

---

# 6. ISOMORPHISME AR(1) <-> ORNSTEIN-UHLENBECK

## 6.1 Equivalence Mathematique (PDF p.14-15)

### Intuition

**Analogie :** L'AR(1) et l'OU sont le MEME phenomene observe a deux echelles differentes. C'est comme photographier une riviere : en photo (discret, AR(1)), vous voyez des images fixes a intervalle regulier. En video (continu, OU), vous voyez le flux en continu. Le "contenu" est le meme, seule la resolution temporelle change.

### Relation fondamentale

```
phi = e^{-theta * dt}
```

**Correspondance complete des parametres :**

| AR(1) | OU | Relation |
|-------|-----|---------|
| phi | theta | phi = e^{-theta*dt} |
| c/(1-phi) | mu | Meme moyenne d'equilibre |
| sigma_AR | sigma_OU | sigma_AR = sigma_OU * sqrt((1-e^{-2*theta*dt}) / (2*theta)) |

### Demi-vies

```
AR(1) : t_{1/2} = -ln(2) / ln(phi)    (en nombre de periodes)
OU    : t_{1/2} = ln(2) / theta        (en temps continu)
```

Equivalentes via phi = e^{-theta*dt}.

## 6.2 Consequence Pratique (PDF p.15)

Tout outil developpe pour l'un peut etre transfere a l'autre :
- Tests de rupture structurelle AR(1) -> applicables a OU
- Seuils optimaux de Bertram (temps continu) -> traduits en z-scores discrets

---

# 7. SYNERGIE HYBRIDE : KALMAN + OU

## 7.1 L'Approche de Pointe (PDF p.17)

### Intuition

**Analogie :** Imaginez que vous essayez d'ecouter une conversation dans un bar bruyant (le spread observe). Le "vrai" spread (le processus OU latent) est la conversation. Le bruit du bar (microstructure) la masque. Le filtre de Kalman est comme un casque a reduction de bruit active qui isole la voix de votre interlocuteur.

### Architecture

1. Le VRAI spread (latent, inobservable) suit un processus OU
2. Le spread OBSERVE est entache de bruits de microstructure
3. Le filtre de Kalman ESTIME le spread latent en filtrant le bruit

**Equation d'etat (discretisation de l'OU) :**
```
X_t = e^{-theta*dt} * X_{t-1} + mu * (1 - e^{-theta*dt}) + w_t
```

**Equation de mesure :**
```
Y_t = X_t + v_t   (observation bruitee)
```

### Avantages Operationnels

1. Beta dynamique (Kalman) + seuils optimaux (OU/Bertram)
2. Taux de faux signaux considerablement reduit
3. Exploitable a haute frequence
4. Robuste aux changements de regime (Gain de Kalman adaptatif)

---

# 8. CONSTRUCTION ET GESTION DU SPREAD

## 8.1 Positions Hedgees (V2)

### Intuition

**Analogie (V2) :** Vous pariez sur la METEO RELATIVE entre deux villes, pas sur la meteo absolue. Si vous pariez que Paris sera plus chaud que Lyon, peu importe si la temperature globale monte ou descend -- vous gagnez si l'ecart Paris-Lyon augmente.

**Slide V2 (01:52) -- Introduction du notebook :**
> "Pairs trading is a nice example of a strategy based on mathematical analysis. The principle is as follows: Let's say you have a pair of securities X and Y that have some underlying economic link."

### Mecanisme

**Long le spread :** Long actif A + Short actif B
- Profite si le spread AUGMENTE (A surperforme B)

**Short le spread :** Short actif A + Long actif B
- Profite si le spread DIMINUE (B surperforme A)

**Market-neutral :** La position Long + Short immunise contre les mouvements globaux du marche.

**V2 :** "If the market went up you would lose money on your shorts but make money on your longs... you'd be neutral."

## 8.2 Actif Synthetique (V2)

Le spread est un NOUVEL ACTIF synthetique. Il a sa propre dynamique, sa propre distribution.

**V2 :** "We've constructed a new synthetic asset... in finance this idea of synthetic assets that take value based on other assets is just super central."

## 8.3 Selection de Paires (V2, PDF)

### Le piege des comparaisons multiples

**V2 :** 20 actions => 190 paires a tester. Avec p = 0.05, ~10 paires "significatives" par HASARD.

**Slide V2 (30:23) :** La heatmap Seaborn illustre ce probleme -- sur 6 actifs (15 paires), seule ABGB-FSLR sort significative.

**Approche recommandee :**
1. Hypothese economique a priori (meme secteur, meme supply chain)
2. Test de cointegration
3. Verification out-of-sample
4. Surveillance continue de la stabilite

**V3 :** "One of the most important things done in finance is to make many independent bets. Here a quant would find many pairs they hypothesize are cointegrated, and evenly distribute their dollars between them."

## 8.4 Rolling Statistics et Look-Ahead Bias (V2)

**Slide V2 (43:40) -- Code complet :**
```python
# Rolling beta (fenetre de 30 jours)
rolling_beta = pd.ols(y=S1, x=S2, window_type='rolling', window=30)
spread = S2 - rolling_beta.beta['x'] * S1

# Moving averages du spread
spread_mavg1 = pd.rolling_mean(spread, window=1)     # 1 jour (= valeur courante)
spread_mavg30 = pd.rolling_mean(spread, window=30)    # 30 jours

# Rolling z-score = (spread_actuel - mavg_30j) / std_30j
```

**V2 :** "You can adjust these parameters... but in practice you shouldn't try to like adjust them to try to make your returns better... we discuss why in the overfitting lecture."

---

# 9. OVERFITTING ET BIAIS STATISTIQUES

## 9.1 Le Probleme Central (V4)

### Intuition

**Analogie (V4) :** C'est comme un etudiant qui memorise les REPONSES d'un examen passe au lieu de comprendre le COURS. Il aura 100% sur l'examen d'entrainement, mais 30% sur le vrai examen parce qu'il n'a rien appris -- il a juste memorise du bruit.

### Formalisation (visible sur les slides V4)

**Slide V4 (00:27-00:30) :**
```
D = D_T + epsilon
```

Ou :
- D : donnees observees
- D_T : signal vrai (true data generating process)
- epsilon : bruit aleatoire

**V4 :** "Overfitting is a huge problem in finance. I would actually say it's probably the biggest problem in quantitative finance because it sneaks in in so many different ways."

**Slide V4 (00:27) -- Deux causes d'overfitting :**
> 1. "Small sample size, so that noise and trend are not distinguishable"
> 2. "Choosing an overly complex model, so that it ends up contorting to fit the noise"

## 9.2 Manifestations en Finance

### a) Trop de regles / trop de parametres (V4)

**Slide V4 (00:30/02:29) -- Tableau illustratif :**

| TV Channel | Room Lighting | Enjoyment |
|------------|--------------|-----------|
| 1 | 2 | 1 |
| 2 | 3 | 2 |
| 3 | 2 | 3 |

Regles overfit :
1. Si TV=1 et Lighting=2 -> Enjoyment=1
2. Si TV=2 et Lighting=3 -> Enjoyment=2
3. Si TV=3 et Lighting=2 -> Enjoyment=3
4. Sinon -> Enjoyment=2 (moyenne)

**Probleme :** Le vrai modele est simplement Enjoyment = TV Channel (correlation 100%). La variable "Lighting" est du BRUIT. Mais le modele overfit inclut ce bruit.

**V4 :** "Just like physicists look for two equations that explain all of the universe, you want your model to be a very simple model that explains maybe 30% of the motion."

### b) Polynomial curve fitting (V4)

**Slide V4 (06:28) -- Graphe spectaculaire :**
Le slide montre un graphe avec des points suivant approximativement une parabole. Trois types de fit sont superposes :
- **Lineaire (sous-fit)** : ne capture pas la courbure
- **Quadratique (bon fit)** : capture la tendance sans le bruit
- **Polynome degre 9 (overfit)** : passe par CHAQUE point mais oscille sauvagement aux extremites (y descend jusqu'a -60)

**V4 :** "A ninth degree polynomial can go through any 10 points. This model predicts perfectly, and yet if we actually took this into practice, look at these tails -- we'd be making horribly wrong predictions."

### c) Parcimonie des parametres (V4)

**Slide V4 (06:28) :**
> "Model/Parameter Parsimony: It is better to explain 60% of the data with 2-3 parameters than 90% with 10."

> "Beware of the perfect fit: Because there is almost always noise present in real data, a perfect fit is almost always indicative of overfitting."

### d) Multiple Comparisons Bias (V2)

20 actions => 190 paires testees. Avec p = 0.05 : ~10 paires "significatives" par HASARD.
Solution : hypothese economique a priori + verification out-of-sample.

### e) Optimisation de la fenetre (V4)

**V4 (10:15-14:15) :** Tester toutes les fenetres (1-255 jours) et prendre la meilleure => OVERFITTING.
- Fenetre optimale de 11 jours en training
- Mais 10x MOINS profitable que la fenetre de 190 jours en walk-forward

**V4 :** "Pick a window length where I can move a bunch and I'm still going to be okay."

### f) Look-Ahead Bias (V2)

Calculer beta/z-score sur TOUTE la serie = utiliser info future.

**V2 :** "P values are binary. You have to treat them as binary. You can't treat them as more or less significant."

## 9.3 Solutions Anti-Overfitting

**Slide V4 (14:18-14:20) -- Quatre strategies :**

### 1. Parcimonie des parametres
Moins de parametres = moins de chances d'overfitter le bruit.

### 2. Out-of-sample testing
**Slide V4 (14:18) :**
> "The most important way to avoid overfitting: we need to test out of sample. Gather data we did not use in constructing the model, and test whether the model continues to work."

### 3. PIEGE : Abuser de l'out-of-sample
**Slide V4 (14:20) :**
> "A common mistake is to take your data, split it into in-sample and out-of-sample, and then repeatedly fit and compare. This defeats the purpose: the out-of-sample data is no longer clean."

**V4 :** "Whatever you have at the end of that process is likely going to be overfit to everything."

### 4. Information Criterion (AIC/BIC)
**Slide V4 (17:01) :** Le presentateur navigue vers la page Wikipedia de l'Akaike Information Criterion. L'AIC mesure le "bang-for-buck" de chaque parametre supplementaire.

### 5. Kalman Filter (V5)
Elimine le choix de fenetre => reduit l'overfitting sur ce parametre.

### 6. Paper trading / cross-validation
Generation de donnees en temps reel pour validation.

---

# 10. OPTIMISATION DES SEUILS : FRONTIERES DE BERTRAM

## 10.1 Le Probleme (PDF p.13)

### Intuition

**Analogie :** Les seuils z-score +/-2 sont comme un thermostat regle "au feeling" a 20°C. Ca marche, mais est-ce OPTIMAL ? Bertram repond a la question : "A quelle temperature exacte dois-je mettre le thermostat pour minimiser ma facture d'electricite tout en maintenant le confort ?"

## 10.2 Framework de Bertram (PDF p.13-14)

**Setup :**
- Seuils symetriques : [-a, +a]
- LONG quand le spread atteint -a (plancher)
- CLOTURE quand le spread revient a mu (equilibre)
- Cycle repete indefiniment

**Objectif :** Maximiser le profit MOYEN PAR UNITE DE TEMPS :
```
max_a  E[Profit] / E[Temps de cycle]
```

**Avantage :** Solution analytique fermee (pas besoin de Monte Carlo). Les seuils optimaux dependent DIRECTEMENT de theta et sigma estimes par MLE.

**Extensions (PDF p.14) :** Integration du controle de volatilite du profit pour les contraintes de risk management.

---

# 11. CONSIDERATIONS PRATIQUES

## 11.1 Couts de Transaction (PDF p.18)

Le modele de Bertram doit etre etendu en probleme multi-regime :
1. Position neutre (pas d'exposition)
2. Position long spread
3. Position short spread

Chaque transition a un cout (commission + slippage).

## 11.2 Microstructure (PDF p.17-18)

Bruits a filtrer (d'ou l'interet du Kalman) :
- Bid-ask bounce
- Latence asymetrique
- Chocs de liquidite institutionnels
- Slippage directionnel

## 11.3 Regime Changes

La cointegration n'est PAS permanente.

**V2 :** "If one of these companies gets completely new management... a pair that was previously cointegrated may become non-cointegrated."

**V3 :** "You should not naively assume that because a time series is stationary in the past it will continue to be stationary in the future."

Causes : M&A, changement de management, reglementation, choc macro.

## 11.4 Diversification (V2)

- JAMAIS trader une seule paire
- Portefeuille de multiples paires, idealement de secteurs differents
- Chaque paire a ~60% de chance de rester cointegree => loi des grands nombres

**V2 :** "You'd never want to trade just one pair. You'd want to trade a ton of different pairs from lots of different industries."

## 11.5 Machine Learning (PDF p.18-19)

Extensions modernes :
- Clustering non-lineaire pour la selection de paires
- Hidden Markov Models (HMM) pour anticiper les changements de Q et R
- Processus de Levy (sauts) au lieu du brownien standard
- Deep learning pour detecter les regimes en temps reel

---

# 12. SYNTHESE COMPARATIVE DES MODELES

## Tableau Recapitulatif

| Attribut | MCO + AR(1) Statique | Filtre de Kalman | Ornstein-Uhlenbeck |
|----------|---------------------|------------------|-------------------|
| **Domaine temporel** | Discret | Discret/recursif | Continu |
| **Hedge ratio** | Fixe (MCO) | Dynamique (Gain K) | Suppose fixe |
| **Bruit** | Homoscedasticite requise | Decomposition Q/R | Brownien integre |
| **Estimation** | MCO + ADF | MLE via EM | MLE exact (gaussien) |
| **Signal** | Z-score heuristique (+/-2) | Ecart etat-observation | Bertram (arret optimal) |
| **Forces** | Simple, rapide, interpretable | Adaptatif, sans fenetre | Rigoureux HF, seuils optimaux |
| **Faiblesses** | Inadapte aux regime changes | Initialisation Q/R complexe | Drift lineaire suppose, MLE couteux |

## Hierarchie d'Implementation Recommandee

### Niveau 1 (Debutant) : Engle-Granger + Z-score rolling
- Simple a implementer (V2 montre tout le code)
- Bon pour comprendre les concepts
- Inadapte au live trading serieux

### Niveau 2 (Intermediaire) : AR(1) + Half-life + Rolling beta
- Meilleure gestion de la dynamique
- Filtrage pre-trade via half-life
- Encore des seuils heuristiques

### Niveau 3 (Avance) : Kalman Filter pour beta dynamique + OU pour seuils
- Elimine le choix de fenetre (V5 : Kalman vs moving averages)
- Seuils mathematiquement optimaux (Bertram)
- Robuste aux changements de regime

### Niveau 4 (Institutionnel) : Kalman applique au processus OU latent + HMM
- Filtre le bruit de microstructure (PDF p.17)
- Detection de regime en temps reel
- Exploitation haute frequence
- Taux de faux signaux minimal

---

## BIBLIOTHEQUE PYTHON UTILISEE DANS LES VIDEOS

| Bibliotheque | Usage | Video |
|-------------|-------|-------|
| `numpy` | Calculs vectoriels, random | V1, V2, V3, V4, V5 |
| `pandas` | Series temporelles, DataFrames | V1, V2, V3 |
| `matplotlib.pyplot` | Graphes et visualisation | V1, V2, V3, V4, V5 |
| `statsmodels.api.OLS` | Regression lineaire | V1, V3 |
| `statsmodels.tsa.stattools.coint` | Test de cointegration | V2, V3 |
| `statsmodels.tsa.stattools.adfuller` | Test ADF | V3 |
| `scipy.optimize.minimize` | Optimisation (MLE) | V1 |
| `pykalman.KalmanFilter` | Filtre de Kalman | V5 |
| `seaborn` | Heatmap des p-values | V2 |

---

## INDEX DES CONCEPTS - REFERENCES CROISEES

| Concept | Sources | Section | Slides cles |
|---------|---------|---------|-------------|
| Stationnarite | V3, PDF | 1.1 | V3 00:28 (definition), V3 10:58 (graphe rendements) |
| ADF Test | V3, PDF | 1.3 | V3 19:20 (resultat test coint) |
| Hurst Exponent | PDF | 1.3 | -- |
| Cointegration vs Correlation | V2, PDF | 2.1 | V2 01:52 (notebook intro) |
| Combinaison lineaire formelle | V3 | 2.1 | V3 14:16 (definition + formule) |
| Engle-Granger 2 etapes | V3, PDF | 2.2 | V3 19:20 (test), V2 30:23 (heatmap) |
| Hedge ratio (beta) | V2, V3, PDF | 2.2 | V2 30:23 (beta=1.536) |
| AR(1) stationnarite | PDF | 3.1 | -- |
| Half-life | PDF, V1 | 3.2, 4.5 | -- |
| Z-score rolling | V2, PDF | 3.3 | V2 43:40 (code rolling) |
| EDS d'Ornstein-Uhlenbeck | V1, PDF | 4.1 | V1 00:00 (definition complete) |
| Resolution analytique OU | V1 | 4.2 | V1 00:00-06:24 (5 etapes) |
| Euler discretisation | V1 | 4.3 | V1 11:12 (formule + note) |
| Simulation OU | V1 | 4.3 | V1 12:00-19:12 (code + graphes multiples) |
| Densite conditionnelle MLE | V1, PDF | 4.6 | V1 09:36 (formule) |
| Methode des Moments | V1 | 4.6 | V1 23:12-27:12 (code + resultats) |
| MLE (Maximum Likelihood) | V1, PDF | 4.6 | V1 17:36-28:48 (code + resultats) |
| Kalman Filter concept | V5, PDF | 5.1 | V5 00:02 (definition), V5 09:39 (comparaison MA) |
| Kalman Gain | V5, PDF | 5.4 | -- |
| Beta dynamique | V5 | 5.5 | V5 07:40 (graphe slope/intercept), V5 07:59 (scatter plot) |
| Kalman sur rendements | V5 | 5.5 | V5 10:05 (scatter + OLS comparison) |
| pykalman code | V5 | 5.5 | V5 03:14/09:17 (KalmanFilter init) |
| Isomorphisme AR(1)-OU | PDF | 6.1 | -- |
| Hybride Kalman+OU | PDF | 7.1 | -- |
| Positions hedgees | V2 | 8.1 | V2 01:52 (concept) |
| Actif synthetique | V2 | 8.2 | -- |
| Multiple comparisons bias | V2 | 8.3 | V2 30:23 (heatmap) |
| Look-ahead bias | V2 | 8.4 | V2 43:40 (rolling fix) |
| D = D_T + epsilon | V4 | 9.1 | V4 00:27-00:30 (formule + causes) |
| Tableau TV/Lighting/Enjoyment | V4 | 9.2a | V4 00:30/02:29 (tableau 3 lignes) |
| Polynomial curve fitting | V4 | 9.2b | V4 06:28 (graphe multi-degres) |
| Parcimonie parametres | V4 | 9.2c | V4 06:28 (note) |
| Out-of-sample testing | V4 | 9.3 | V4 14:18 (section complete) |
| AIC (Information Criterion) | V4 | 9.3 | V4 17:01 (Wikipedia) |
| Bertram optimal stopping | PDF | 10.2 | -- |
| Couts de transaction | PDF | 11.1 | -- |
| Machine Learning extensions | PDF | 11.5 | -- |
