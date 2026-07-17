# Auto Dispo CIC — scraper du catalogue de leasing

Scrape le catalogue de véhicules en LLD/LOA de
[auto-dispo.cic-leasing.fr](https://auto-dispo.cic-leasing.fr/leasing-voiture).

## Pourquoi c'est plus simple qu'Autosphere

Ce site est intégralement rendu côté serveur, avec une vraie pagination
par URL (`?page=N`, ~155 pages) et sans bandeau cookie bloquant le
contenu. Le scraper utilise donc `requests` + `BeautifulSoup` — pas de
Playwright, pas de navigateur, pas de clic à simuler.

## Installation

```bash
pip install -r requirements.txt --break-system-packages
```

## Utilisation

```bash
python scraper.py
```

Pour tester rapidement sur un sous-ensemble (2 pages au lieu de ~155) :

```bash
MAX_PAGES=2 python scraper.py
```

## Résultat

Un fichier `data/vehicules_autodispo.csv` avec une ligne par véhicule :
marque, modèle, finition, référence, titre, condition (neuf/occasion),
apport (avec/sans), énergie, transmission, kilométrage, prix mensuel, URL,
date du relevé.

Chaque exécution **ajoute** les nouvelles lignes (le fichier grandit dans
le temps si vous relancez régulièrement), avec une date de relevé pour
permettre un suivi dans le temps.

## Dashboard

```bash
streamlit run dashboard.py
```

Filtres (marque, énergie, état, prix), section "proportion électrique par
marque", répartition par marque, prix moyen par énergie, kilométrage vs
prix, et table détaillée avec lien vers chaque annonce.

## Automatisation (GitHub Actions)

Le workflow `.github/workflows/scrape.yml` relance le scraper tous les
jours à 9h15 UTC et committe les nouvelles lignes dans `data/`. Avant de
pousser sur GitHub, vérifiez que les workflows ont les droits d'écriture :
**Settings → Actions → General → Workflow permissions → "Read and write
permissions"**.

## Déploiement (Streamlit Community Cloud)

1. Créez un dépôt GitHub (public ou privé) et poussez ce dossier.
2. Sur [share.streamlit.io](https://share.streamlit.io), "Create app" →
   sélectionnez le dépôt, branche `main`, fichier principal `dashboard.py`.
3. Streamlit Cloud installe les dépendances depuis `requirements.txt`
   (streamlit, pandas, plotly — pas besoin de `requests`/`beautifulsoup4`
   pour l'app déployée, mais les avoir ne pose pas de souci).
