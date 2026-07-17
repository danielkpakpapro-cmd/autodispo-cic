"""
scraper.py — Auto Dispo CIC (auto-dispo.cic-leasing.fr)
==========================================================
Contrairement à Autosphere, ce catalogue est intégralement rendu côté
serveur, avec une vraie pagination par URL (?page=N) et sans bandeau
cookie bloquant le contenu. Pas besoin de Playwright/navigateur : de
simples requêtes HTTP (requests) + parsing HTML (BeautifulSoup) suffisent
— beaucoup moins de points de défaillance que sur Autosphere.

LOGIQUE
-------
Chaque fiche véhicule de la page catalogue est un unique <a> cliquable
contenant tout le texte utile (titre, énergie, kilométrage, boîte, prix)
et pointant vers l'URL détail (ex: /leasing-voiture/renault/clio-v/
tce-100-ves00888888?apport=sans). On repère ces liens via le motif
"-ves<chiffres>" dans le href (ce qui exclut les liens de nav/pub), on en
extrait le texte brut, et on en tire les champs par regex. La marque et
le modèle viennent directement du chemin de l'URL (bien plus fiable que
de les extraire du texte, qui répète le titre deux fois collé à
l'énergie sans espace).

Le nombre total de pages est lu dynamiquement depuis la pagination de la
page 1 (~155 pages actuellement, 10 véhicules/page) — jamais codé en dur.

USAGE
-----
    pip install requests beautifulsoup4 --break-system-packages
    python scraper.py

    Variables d'environnement optionnelles :
      MAX_PAGES=5 python scraper.py   -> limite à 5 pages pour tester vite
"""

import csv
import os
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://auto-dispo.cic-leasing.fr/leasing-voiture"
# Le "+" doit être encodé en %2B : envoyé tel quel, un "+" dans une query
# string est conventionnellement décodé en espace côté serveur, ce qui
# casse ce paramètre (observé : erreur 500 avec "0+1000+without" brut).
QUERY = "monthly_rent=0%2B1000%2Bwithout"
CSV_PATH = "data/vehicules_autodispo.csv"
CSV_FIELDS = ["date_releve", "reference", "marque", "modele", "finition",
              "titre", "condition", "apport", "energie", "transmission",
              "km", "prix_mensuel", "url"]

DELAY_BETWEEN_PAGES = 0.4  # secondes, pour rester respectueux du serveur
MAX_PAGES = int(os.environ.get("MAX_PAGES", "0")) or None  # None = toutes

ENERGIES = ["Hybride rechargeable", "Micro-hybride essence", "Micro-hybride diesel",
            "Hybride", "Electrique", "Essence", "Diesel", "GPL"]
TRANSMISSIONS = ["Automatique", "Manuelle"]

APPORT_PATTERN = re.compile(r"^(SANS APPORT|AVEC APPORT)\s+Voiture\s+(occasion|neuve)\s+")
PRICE_PATTERN = re.compile(r"à partir de\s+([\d\s]+)\s*€/mois")
KM_PATTERN = re.compile(r"([\d\s]+)\s*km")
VEHICLE_LINK_PATTERN = re.compile(r"-ves\d+")
PAGE_NUM_PATTERN = re.compile(r"[?&]page=(\d+)")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def _get_with_retries(session, url, max_retries=3):
    """GET avec quelques tentatives en cas de souci réseau transitoire,
    pour éviter qu'un simple timeout ponctuel ne fasse planter tout le
    scraping sur 155 pages."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(1.5 * attempt)
    raise last_error


def _parse_card(text, url):
    """Extrait les champs d'une fiche véhicule à partir du texte brut de
    son <a> et de son URL de détail."""
    text = re.sub(r"\s+", " ", text).strip()

    m = APPORT_PATTERN.match(text)
    apport = m.group(1) if m else None
    condition = m.group(2) if m else None
    rest = text[m.end():] if m else text

    # Le titre est répété deux fois d'affilée, collé à l'énergie sans
    # espace (ex: "...MaxEssence"). On repère où l'énergie commence pour
    # couper le bloc titre, puis on vérifie la duplication.
    energie_found, energie_pos = None, None
    for e in ENERGIES:
        idx = rest.find(e)
        if idx != -1 and (energie_pos is None or idx < energie_pos):
            energie_pos, energie_found = idx, e

    title_area = rest[:energie_pos] if energie_pos is not None else rest
    half = len(title_area) // 2
    first_half, second_half = title_area[:half].strip(), title_area[half:].strip()
    titre = first_half if first_half == second_half else title_area.strip()

    km_match = KM_PATTERN.search(rest)
    km = int(re.sub(r"\D", "", km_match.group(1))) if km_match else None

    transmission = next((t for t in TRANSMISSIONS if t in rest), None)

    price_match = PRICE_PATTERN.search(rest)
    prix_mensuel = int(re.sub(r"\D", "", price_match.group(1))) if price_match else None

    # Marque / modèle / finition / référence : directement depuis l'URL,
    # bien plus fiable que le texte.
    path = url.split("cic-leasing.fr/leasing-voiture/", 1)[-1].split("?")[0]
    parts = path.split("/")
    marque = parts[0] if len(parts) > 0 else None
    modele = parts[1] if len(parts) > 1 else None
    finition_ref = parts[2] if len(parts) > 2 else None
    ref_match = re.search(r"(ves\d+)$", finition_ref) if finition_ref else None
    reference = ref_match.group(1) if ref_match else None
    finition = finition_ref.rsplit("-", 1)[0] if finition_ref and ref_match else finition_ref

    return {
        "reference": reference,
        "marque": marque,
        "modele": modele,
        "finition": finition,
        "titre": titre,
        "condition": condition,
        "apport": apport,
        "energie": energie_found,
        "transmission": transmission,
        "km": km,
        "prix_mensuel": prix_mensuel,
        "url": url,
    }


def _get_total_pages(session):
    """Lit dynamiquement le nombre total de pages depuis la pagination de
    la page 1 (jamais codé en dur, s'adapte si le catalogue grandit)."""
    resp = _get_with_retries(session, f"{BASE_URL}?{QUERY}")
    soup = BeautifulSoup(resp.text, "html.parser")
    max_page = 1
    for a in soup.find_all("a", href=True):
        m = PAGE_NUM_PATTERN.search(a["href"])
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page, resp.text


def _extract_cards_from_html(html, seen_refs):
    """Extrait toutes les fiches véhicule d'une page HTML, en dédoublonnant
    par référence (chaque fiche peut apparaître dans plusieurs blocs)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not VEHICLE_LINK_PATTERN.search(href):
            continue
        url = href if href.startswith("http") else f"https://auto-dispo.cic-leasing.fr{href}"
        text = a.get_text(separator=" ", strip=True)
        if not text:
            continue
        row = _parse_card(text, url)
        if row["reference"] and row["reference"] not in seen_refs:
            seen_refs.add(row["reference"])
            rows.append(row)
    return rows


def scrape():
    import datetime as dt
    now = dt.datetime.now().isoformat(timespec="seconds")

    session = requests.Session()
    total_pages, first_page_html = _get_total_pages(session)
    if MAX_PAGES:
        total_pages = min(total_pages, MAX_PAGES)
    print(f"{total_pages} pages à parcourir (10 véhicules/page environ).")

    seen_refs = set()
    all_rows = []

    # Page 1 déjà récupérée pour compter les pages, on la parse directement
    page1_rows = _extract_cards_from_html(first_page_html, seen_refs)
    all_rows.extend(page1_rows)
    print(f"  Page 1 : {len(page1_rows)} véhicules")

    for page in range(2, total_pages + 1):
        try:
            resp = _get_with_retries(session, f"{BASE_URL}?{QUERY}&page={page}")
            rows = _extract_cards_from_html(resp.text, seen_refs)
            all_rows.extend(rows)
            if page % 10 == 0 or page == total_pages:
                print(f"  Page {page}/{total_pages} : {len(rows)} véhicules "
                      f"(total cumulé : {len(all_rows)})")
        except Exception as e:
            print(f"  [ALERTE] Page {page} : erreur ignorée : {e}")
        time.sleep(DELAY_BETWEEN_PAGES)

    for row in all_rows:
        row["date_releve"] = now

    return all_rows


def save_to_csv(rows, csv_path=CSV_PATH):
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\n{len(rows)} lignes ajoutées à {csv_path}")


if __name__ == "__main__":
    rows = scrape()
    save_to_csv(rows)

    print(f"\nTerminé : {len(rows)} véhicules uniques scrapés.")
    marques = {}
    for r in rows:
        marques[r["marque"]] = marques.get(r["marque"], 0) + 1
    print("\nRépartition par marque (top 15) :")
    for marque, count in sorted(marques.items(), key=lambda x: -x[1])[:15]:
        print(f"  {marque:20s} {count}")
