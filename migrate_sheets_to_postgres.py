#!/usr/bin/env python3
"""
migrate_sheets_to_postgres.py — jednorazowa migracja historycznych danych
z Google Sheets do Postgres (schemat: db/schema.sql).

Uruchomienie:
  python db.py                        # najpierw utwórz tabele
  python migrate_sheets_to_postgres.py

Wymaga tych samych zmiennych co dotychczas: SPREADSHEET_ID, GOOGLE_CREDENTIALS
(plik service account) oraz — żeby historia trafiła na TO SAMO konto, którego
używa sync.py — GARMIN_DISPLAY_NAME (profil Garmin, np. z URL
connect.garmin.com/app/profile/<TU>).
"""

import json
import os

import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

import repository as repo

load_dotenv()

SPREADSHEET_ID    = os.environ["SPREADSHEET_ID"]
CREDENTIALS_FILE  = os.environ.get("GOOGLE_CREDENTIALS", "credentials.json")
GARMIN_DISPLAY_NAME = os.environ.get("GARMIN_DISPLAY_NAME")


def get_sheets():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds).spreadsheets()


def read_full_sheet(sheets, tab: str) -> pd.DataFrame:
    try:
        res = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A:ZZ").execute()
        rows = res.get("values", [])
        if len(rows) < 2:
            return pd.DataFrame()
        n = len(rows[0])
        return pd.DataFrame([r + [""] * (n - len(r)) for r in rows[1:]], columns=rows[0])
    except Exception as e:
        print(f"  ⚠️ Nie udało się wczytać '{tab}': {e}")
        return pd.DataFrame()


def assign_exercise_order(rows: list[dict]) -> list[dict]:
    """Sheets nie zapisywały kolejności ćwiczenia w treningu — odtwarzamy ją
    z kolejności wierszy (każda zmiana Cwiczenie/Superset_ID = nowe ćwiczenie)."""
    state_by_workout = {}
    for r in rows:
        wid = r.get("ID_treningu")
        key = (r.get("Cwiczenie"), r.get("Superset_ID"))
        state = state_by_workout.setdefault(wid, {"last_key": None, "order": -1})
        if key != state["last_key"]:
            state["order"] += 1
            state["last_key"] = key
        r["Cwiczenie_kolejnosc"] = state["order"]
    return rows


def main():
    if not GARMIN_DISPLAY_NAME:
        print("❌ Ustaw GARMIN_DISPLAY_NAME (profil Garmin z URL connect.garmin.com/app/profile/<TU>)")
        print("   — to musi być TEN SAM identyfikator, którego użyje sync.py po zalogowaniu.")
        return

    person_id = repo.get_or_create_person(GARMIN_DISPLAY_NAME, "Igor", is_owner=True)
    print(f"✅ Osoba (właściciel): person_id={person_id}")

    sheets = get_sheets()

    print("\n📥 Dziennik...")
    df = read_full_sheet(sheets, "Dziennik")
    repo.upsert_daily(person_id, df.to_dict("records"))

    print("\n📥 Aktywności...")
    df = read_full_sheet(sheets, "Aktywności")
    repo.upsert_activities(person_id, df.to_dict("records"), source="own")

    print("\n📥 Okrążenia...")
    df = read_full_sheet(sheets, "Okrążenia")
    repo.upsert_laps(df.to_dict("records"))

    print("\n📥 Trasy...")
    df = read_full_sheet(sheets, "Trasy")
    repo.upsert_gps_tracks(df.to_dict("records"))

    print("\n📥 Fitatu...")
    df = read_full_sheet(sheets, "Fitatu")
    repo.upsert_fitatu_daily(person_id, df.to_dict("records"))

    print("\n📥 FitatuProdukty...")
    df = read_full_sheet(sheets, "FitatuProdukty")
    repo.replace_fitatu_products(person_id, df.to_dict("records"))

    print("\n📥 Hevy...")
    df = read_full_sheet(sheets, "Hevy")
    rows = assign_exercise_order(df.to_dict("records"))
    repo.upsert_hevy_sets(person_id, rows)

    print("\n📥 General (waga)...")
    df = read_full_sheet(sheets, "General")
    if not df.empty and len(df.columns) >= 5:
        try:
            weight = float(str(df.iloc[0, 4]).replace(",", "."))
            repo.set_manual_weight(person_id, weight)
            print(f"  ✓ Waga: {weight} kg")
        except (ValueError, TypeError):
            print("  ⚠️ Nie udało się odczytać wagi z General!E2")

    print("\n✅ Migracja zakończona.")


if __name__ == "__main__":
    main()
