"""
dashboard.py — Auto Dispo CIC
===============================
Dashboard Streamlit pour explorer le catalogue de leasing scrapé par
scraper.py (data/vehicules_autodispo.csv) : prix mensuels, répartition
par marque/énergie, kilométrage, et table filtrable.

USAGE
-----
    streamlit run dashboard.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Auto Dispo CIC — catalogue leasing",
    page_icon="🚗",
    layout="wide",
)

CSV_PATH = "data/vehicules_autodispo.csv"


@st.cache_data(ttl=600)
def load_data(path=CSV_PATH):
    df = pd.read_csv(path, parse_dates=["date_releve"])
    return df


st.title("🚗 Auto Dispo CIC — catalogue de leasing")

try:
    df = load_data(CSV_PATH)
except FileNotFoundError:
    st.error(
        f"Fichier introuvable : `{CSV_PATH}`. "
        "Lancez d'abord `python scraper.py` pour générer les données."
    )
    st.stop()

if df.empty:
    st.warning("Le fichier de données est vide pour l'instant.")
    st.stop()

derniere_date = df["date_releve"].max()
st.caption(f"Dernier relevé : {derniere_date.strftime('%d/%m/%Y %H:%M')}")

# Snapshot le plus récent : si le scraper est relancé plusieurs fois, un
# même véhicule (référence) peut apparaître à plusieurs dates avec un prix
# ou un kilométrage mis à jour — on ne garde que la dernière occurrence de
# chaque référence pour éviter les doublons dans les stats globales.
snapshot = (
    df.sort_values("date_releve")
    .drop_duplicates(subset="reference", keep="last")
    .copy()
)

# --- Filtres (barre latérale) ---
st.sidebar.header("Filtres")

toutes_marques = sorted(snapshot["marque"].dropna().unique())
marques_choisies = st.sidebar.multiselect("Marque", toutes_marques)

toutes_energies = sorted(snapshot["energie"].dropna().unique())
energies_choisies = st.sidebar.multiselect("Énergie", toutes_energies)

conditions = sorted(snapshot["condition"].dropna().unique())
conditions_choisies = st.sidebar.multiselect("État", conditions)

prix_min = int(snapshot["prix_mensuel"].min())
prix_max = int(snapshot["prix_mensuel"].max())
prix_range = st.sidebar.slider(
    "Prix mensuel (€)", prix_min, prix_max, (prix_min, prix_max)
)

filtered = snapshot.copy()
if marques_choisies:
    filtered = filtered[filtered["marque"].isin(marques_choisies)]
if energies_choisies:
    filtered = filtered[filtered["energie"].isin(energies_choisies)]
if conditions_choisies:
    filtered = filtered[filtered["condition"].isin(conditions_choisies)]
filtered = filtered[
    filtered["prix_mensuel"].between(prix_range[0], prix_range[1])
]

# --- Section électrique (réagit aux filtres ci-dessus) ---
st.subheader("🔋 Proportion de véhicules électriques")

total_vehicules = len(filtered)
total_electriques = (filtered["energie"] == "Electrique").sum()
proportion_globale = total_electriques / total_vehicules if total_vehicules else 0

col_e1, col_e2, col_e3 = st.columns(3)
col_e1.metric("Véhicules (vue filtrée)", f"{total_vehicules:,}".replace(",", " "))
col_e2.metric("Dont électriques", f"{total_electriques:,}".replace(",", " "))
col_e3.metric("Proportion électrique", f"{proportion_globale:.1%}")

par_marque_electrique = (
    filtered.groupby("marque")
    .agg(total=("reference", "count"),
         electrique=("energie", lambda s: (s == "Electrique").sum()))
    .reset_index()
)
par_marque_electrique["proportion"] = (
    par_marque_electrique["electrique"] / par_marque_electrique["total"]
)
par_marque_electrique = par_marque_electrique.sort_values("total", ascending=False)

if len(par_marque_electrique):
    fig_elec_marque = px.bar(
        par_marque_electrique,
        x="marque", y="proportion",
        text="electrique",
        labels={"marque": "Marque", "proportion": "% électrique"},
    )
    fig_elec_marque.update_traces(texttemplate="%{text}", textposition="outside")
    fig_elec_marque.update_layout(yaxis_tickformat=".0%")
    st.plotly_chart(fig_elec_marque, width="stretch")
else:
    st.info("Aucun véhicule ne correspond aux filtres sélectionnés.")

st.divider()

# --- Métriques ---
col1, col2, col3 = st.columns(3)
col1.metric("Prix mensuel moyen", f"{filtered['prix_mensuel'].mean():.0f} €" if len(filtered) else "—")
col2.metric("Kilométrage médian", f"{filtered['km'].median():.0f} km" if len(filtered) else "—")
part_neuf = (filtered["condition"] == "neuve").mean() * 100 if len(filtered) else 0
col3.metric("Part de neuf", f"{part_neuf:.0f}%")

st.divider()

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Véhicules par marque")
    par_marque = (
        filtered["marque"].value_counts().reset_index()
        .rename(columns={"count": "nombre", "marque": "marque"})
        .head(20)
    )
    fig_marque = px.bar(par_marque, x="marque", y="nombre")
    st.plotly_chart(fig_marque, width="stretch")

with col_right:
    st.subheader("Prix mensuel moyen par énergie")
    par_energie = (
        filtered.groupby("energie")["prix_mensuel"]
        .mean()
        .reset_index()
        .sort_values("prix_mensuel", ascending=False)
    )
    fig_energie = px.bar(
        par_energie, x="energie", y="prix_mensuel",
        labels={"prix_mensuel": "Prix mensuel moyen (€)"},
    )
    st.plotly_chart(fig_energie, width="stretch")

st.divider()

st.subheader("Kilométrage vs prix mensuel")
fig_scatter = px.scatter(
    filtered, x="km", y="prix_mensuel", color="energie",
    hover_data=["marque", "modele", "titre"],
    labels={"km": "Kilométrage", "prix_mensuel": "Prix mensuel (€)"},
)
st.plotly_chart(fig_scatter, width="stretch")

st.divider()

st.subheader("Détail des véhicules")
table_display = filtered.rename(
    columns={
        "marque": "Marque",
        "modele": "Modèle",
        "finition": "Finition",
        "condition": "État",
        "apport": "Apport",
        "energie": "Énergie",
        "transmission": "Transmission",
        "km": "Km",
        "prix_mensuel": "Prix mensuel (€)",
    }
)[["Marque", "Modèle", "Finition", "État", "Apport", "Énergie",
   "Transmission", "Km", "Prix mensuel (€)", "url"]]

st.dataframe(
    table_display.sort_values("Prix mensuel (€)"),
    width="stretch",
    hide_index=True,
    column_config={
        "url": st.column_config.LinkColumn("Lien", display_text="Voir l'annonce"),
    },
)

st.caption(f"{len(filtered)} véhicule(s) affiché(s) sur {len(snapshot)} au total.")
