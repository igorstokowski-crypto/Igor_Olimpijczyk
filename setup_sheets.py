#!/usr/bin/env python3
"""
setup_sheets.py — Jednorazowy skrypt do przygotowania arkusza Google Sheets.
Tworzy zakładki: Dziennik, Aktywności, Okrążenia (jeśli nie istnieją).
Istniejące zakładki są POMIJANE.
"""

import os
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

SPREADSHEET_ID   = os.environ["SPREADSHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS", "credentials.json")

# ── Nagłówki ──────────────────────────────────────────
SHEETS_CONFIG = {
    # Fitatu — już istnieją, nie ruszamy nagłówków (tylko pomijamy jeśli są)
    "Fitatu":         ["Data", "Kcal", "Bialko_g", "Tluszcze_g", "Wegle_g"],
    "FitatuProdukty": ["Data", "Produkt", "Gramy", "Kcal"],
    # Hevy — siłownia
    "Hevy": ["ID_treningu", "Data", "Trening", "Cwiczenie", "Seria", "KG", "Reps", "RPE", "Typ"],
    # Garmin — nowe
    "Dziennik": [
        "Data", "Kroki", "Dystans_dzienny_km",
        "Kalorie_aktywne", "Kalorie_calkowite",
        "Sen_h", "Jakos_snu",
        "HR_spoczynkowe", "Stres_sr", "Intensywne_min", "Waga_kg",
    ],
    "Aktywności": [
        "ID", "Data", "Nazwa", "Typ",
        "Dystans_km", "Czas", "Czas_ruchu",
        "Kalorie", "HR_sr", "HR_max",
        "Wznios_m", "Spadek_m", "Temperatura_sr",
        "Tempo_sr", "Tempo_GAP", "Tempo_najlepsze",
        "Moc_sr_W", "Moc_max_W", "W_kg",
        "Kadencja_sr_spm", "Kadencja_max_spm",
        "Dlugosc_kroku_m", "Kontakt_z_podlozem_ms", "Bilans_GCT_pct",
        "Odchyl_pionowe_cm", "Odchyl_do_dlugosci_pct",
        "Efekt_aerobowy", "Efekt_beztlenowy", "Obciazenie_wysilkiem",
        "Stamina_start_pct", "Stamina_koniec_pct",
        "VO2max", "BodyBattery_wplyw",
    ],
    "Okrążenia": [
        "Data_treningu", "Aktywnosc_ID", "Nr_okr",
        "Dystans_km", "Czas", "Tempo", "GAP",
        "HR_sr", "HR_max",
        "Moc_sr_W", "Moc_max_W", "W_kg",
        "Kadencja_sr_spm",
        "Kontakt_ms", "Bilans_GCT_pct",
        "Dlugosc_kroku_m", "Odchyl_pionowe_cm", "Odchyl_do_dlugosci_pct",
        "Wznios_m", "Spadek_m",
    ],
}

def main():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service    = build("sheets", "v4", credentials=creds)
    spreadsheet = service.spreadsheets()

    # Pobierz istniejące zakładki
    meta = spreadsheet.get(spreadsheetId=SPREADSHEET_ID).execute()
    existing = {s["properties"]["title"] for s in meta["sheets"]}
    print(f"Istniejące zakładki: {', '.join(existing)}\n")

    # Dodaj brakujące zakładki
    add_requests = []
    for title in SHEETS_CONFIG:
        if title in existing:
            print(f"  ⏭️  '{title}' — już istnieje, pomijam")
        else:
            add_requests.append({
                "addSheet": {"properties": {"title": title}}
            })
            print(f"  ➕ '{title}' — zostanie utworzona")

    if add_requests:
        spreadsheet.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": add_requests}
        ).execute()
        print("  ✅ Zakładki utworzone\n")
    else:
        print()

    # Dodaj nagłówki do nowych zakładek
    for title, headers in SHEETS_CONFIG.items():
        if title in existing:
            continue  # nie ruszaj istniejących
        range_name = f"'{title}'!A1"
        spreadsheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [headers]}
        ).execute()
        print(f"  📋 '{title}' — nagłówki ({len(headers)} kolumn) dodane")

    print("\n✅ Gotowe! Arkusz przygotowany.")
    print(f"   https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")

if __name__ == "__main__":
    main()
