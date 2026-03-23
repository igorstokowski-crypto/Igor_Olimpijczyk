#!/usr/bin/env python3
"""
garmin_sync.py
Pobiera dane z Garmin Connect i zapisuje do:
  • Google Sheets — 3 zakładki: Dziennik, Aktywności, Okrążenia
  • exports/aktywnosci.csv + okrazenia.csv + dziennik.csv
  • exports/garmin_data.xlsx  (3 arkusze)

MFA fix: sesja garth jest persystentna — MFA tylko przy PIERWSZYM uruchomieniu.

Instalacja:
  pip install garth garminconnect google-api-python-client google-auth pandas openpyxl python-dotenv

Konfiguracja:
  Skopiuj .env.example → .env i uzupełnij dane.
  Wrzuć credentials.json (service account Google) do folderu ze skryptem.
"""

import os, json, datetime, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import garth
from garminconnect import Garmin
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ── KONFIGURACJA ──────────────────────────────────────
GARMIN_EMAIL     = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD  = os.environ["GARMIN_PASSWORD"]
SPREADSHEET_ID   = os.environ["SPREADSHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS", "credentials.json")

SESSION_DIR    = Path(__file__).parent / "SESJA_GARTH"   # NIE kasować — klucz do braku MFA!
LAST_SYNC_FILE = Path(__file__).parent / "last_sync.json"
START_DATE     = "2025-01-01"
OUTPUT_DIR     = Path(__file__).parent / "exports"

RUNNING_TYPES  = {"running", "treadmill_running", "trail_running"}
CYCLING_TYPES  = {"cycling", "road_cycling", "gravel_cycling", "virtual_ride", "indoor_cycling"}
SWIMMING_TYPES = {"swimming", "lap_swimming", "open_water_swimming"}
WALKING_TYPES  = {"walking", "hiking"}
ALL_TYPES      = RUNNING_TYPES | CYCLING_TYPES | SWIMMING_TYPES | WALKING_TYPES

# ── NAGŁÓWKI ZAKŁADEK ─────────────────────────────────
DZIENNIK_COLS = [
    "Data",
    "Kroki", "Dystans_dzienny_km",
    "Kalorie_aktywne", "Kalorie_calkowite",
    "Sen_h", "Jakos_snu",
    "HR_spoczynkowe",
    "Stres_sr",
    "Intensywne_min",
    "Waga_kg",
]

AKTYWNOSCI_COLS = [
    # Identyfikacja
    "ID", "Data", "Nazwa", "Typ",
    # Podstawowe (wszystkie sporty)
    "Dystans_km", "Czas", "Czas_ruchu",
    "Kalorie", "HR_sr", "HR_max",
    "Wznios_m", "Spadek_m", "Temperatura_sr",
    # Tempo (bieg + chód)
    "Tempo_sr", "Tempo_GAP", "Tempo_najlepsze",
    # Moc (bieg + rower)
    "Moc_sr_W", "Moc_max_W", "W_kg",
    # Dynamika biegu (tylko bieganie)
    "Kadencja_sr_spm", "Kadencja_max_spm",
    "Dlugosc_kroku_m",
    "Kontakt_z_podlozem_ms", "Bilans_GCT_pct",
    "Odchyl_pionowe_cm", "Odchyl_do_dlugosci_pct",
    # Trening
    "Efekt_aerobowy", "Efekt_beztlenowy",
    "Obciazenie_wysilkiem",
    "Stamina_start_pct", "Stamina_koniec_pct",
    "VO2max",
    # Wellness
    "BodyBattery_wplyw",
]

OKRAZENIA_COLS = [
    "Data_treningu", "Aktywnosc_ID", "Nr_okr",
    "Dystans_km", "Czas",
    "Tempo", "GAP",
    "HR_sr", "HR_max",
    "Moc_sr_W", "Moc_max_W", "W_kg",
    "Kadencja_sr_spm",
    "Kontakt_ms", "Bilans_GCT_pct",
    "Dlugosc_kroku_m",
    "Odchyl_pionowe_cm", "Odchyl_do_dlugosci_pct",
    "Wznios_m", "Spadek_m",
]

# ── GARMIN AUTH (MFA FIX) ─────────────────────────────
def garmin_login() -> Garmin:
    """
    Loguje z cache sesji garth.
    Sekret braku MFA: SESSION_DIR nigdy nie jest kasowany.
    Token OAuth wygasa, ale garth automatycznie go odświeża refresh tokenem.
    MFA pojawia się tylko gdy SESSION_DIR jest pusty (pierwsze uruchomienie).
    """
    SESSION_DIR.mkdir(exist_ok=True)
    garth.home = str(SESSION_DIR)

    try:
        garth.resume(str(SESSION_DIR))
        print("✅ Garmin: sesja z cache (bez MFA)")
    except Exception:
        print("⏳ Pierwsze logowanie — może pojawić się kod MFA...")
        delays = [0, 30, 60, 120]
        for attempt, delay in enumerate(delays, 1):
            if delay:
                print(f"  ⏳ Czekam {delay}s przed próbą {attempt}/{len(delays)}...")
                time.sleep(delay)
            try:
                garth.login(GARMIN_EMAIL, GARMIN_PASSWORD)
                garth.save(str(SESSION_DIR))  # <-- zapisz sesję na dysk
                print("✅ Zalogowano! Sesja zapisana → kolejne uruchomienia bez MFA")
                break
            except Exception as e:
                if "429" in str(e) and attempt < len(delays):
                    print(f"  ⚠️  Rate limit (429) — spróbuję za chwilę...")
                    continue
                raise

    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.garth = garth.client

    # Pobierz display_name — wymagane przez API (np. /usersummary-service/usersummary/daily/{display_name})
    # Pomijamy client.login() żeby nie wymuszać MFA, więc ustawiamy to ręcznie.
    try:
        profile = garth.client.connectapi("/userprofile-service/socialProfile")
        client.display_name = profile.get("displayName")
        print(f"  Profil: {client.display_name}")
    except Exception as e:
        print(f"  ⚠️ Nie mogłem pobrać profilu ({e}), próbuję z .env...")
        client.display_name = os.environ.get("GARMIN_DISPLAY_NAME") or None

    return client

# ── DATY DO POBRANIA ──────────────────────────────────
def get_dates_to_fetch() -> list[str]:
    from_date = START_DATE
    if LAST_SYNC_FILE.exists():
        saved = json.loads(LAST_SYNC_FILE.read_text())
        from_date = saved.get("lastDate", START_DATE)
        print(f"Ostatnia sync: {from_date}")
    else:
        print(f"Pierwsza sync od: {from_date}")

    # Cofnij 2 dni (na wypadek późnych synców zegarka)
    start = datetime.date.fromisoformat(from_date) - datetime.timedelta(days=2)
    today = datetime.date.today()
    dates, d = [], start
    while d <= today:
        dates.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return dates

# ── POMOCNICZE ────────────────────────────────────────
def secs_to_str(s) -> str:
    s = int(s or 0)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def pace(speed_ms) -> str:
    """m/s → min:ss /km"""
    if not speed_ms or speed_ms <= 0:
        return ""
    p = 1000 / speed_ms
    return f"{int(p // 60)}:{int(p % 60):02d}"

def v(val, default=""):
    return val if val is not None else default

# ── POBIERANIE DANYCH DZIENNYCH ───────────────────────
def fetch_daily(client: Garmin, date_str: str) -> dict:
    row = dict.fromkeys(DZIENNIK_COLS, "")
    row["Data"] = date_str

    try:
        s = client.get_user_summary(date_str)
        row.update({
            "Kroki":              v(s.get("totalSteps"), 0),
            "Dystans_dzienny_km": round((s.get("totalDistanceMeters") or 0) / 1000, 2),
            "Kalorie_aktywne":    round(s.get("activeKilocalories") or 0),
            "Kalorie_calkowite":  round(s.get("totalKilocalories") or 0),
            "Sen_h":              round((s.get("sleepingSeconds") or 0) / 3600, 2),
            "HR_spoczynkowe":     v(s.get("restingHeartRateValue")),
            "Stres_sr":           v(s.get("averageStressLevel")),
            "Intensywne_min":     v(s.get("vigorousIntensityMinutes"), 0),
        })
    except Exception as e:
        print(f"  ⚠️ Summary {date_str}: {e}")

    try:
        sleep = client.get_sleep_data(date_str)
        daily_sleep = (sleep or {}).get("dailySleepDTO") or {}
        row["Jakos_snu"] = v(daily_sleep.get("sleepScores", {}).get("overall", {}).get("value"))
    except Exception:
        pass

    try:
        w = client.get_weigh_ins(date_str, date_str)
        entries = (w or {}).get("dateWeightList") or []
        if entries:
            row["Waga_kg"] = round((entries[0].get("weight") or 0) / 1000, 1)
    except Exception:
        pass

    return row

# ── POBIERANIE AKTYWNOŚCI ─────────────────────────────
def fetch_activity(client: Garmin, act: dict) -> tuple[dict, list[dict]]:
    """Zwraca (wiersz aktywności, lista okrążeń)."""
    act_id   = act["activityId"]
    act_type = act.get("activityType", {}).get("typeKey", "")

    row = dict.fromkeys(AKTYWNOSCI_COLS, "")
    row.update({
        "ID":            str(act_id),
        "Data":          (act.get("startTimeLocal") or "")[:16],
        "Nazwa":         act.get("activityName", ""),
        "Typ":           act_type,
        "Dystans_km":    round((act.get("distance") or 0) / 1000, 2),
        "Czas":          secs_to_str(act.get("duration")),
        "Czas_ruchu":    secs_to_str(act.get("movingDuration")),
        "Kalorie":       v(act.get("calories"), 0),
        "HR_sr":         v(act.get("averageHR")),
        "HR_max":        v(act.get("maxHR")),
        "Wznios_m":      v(act.get("elevationGain"), 0),
        "Spadek_m":      v(act.get("elevationLoss"), 0),
        "Temperatura_sr":v(act.get("avgTemperature")),
        "Moc_sr_W":      v(act.get("avgPower")),
        "Moc_max_W":     v(act.get("maxPower")),
        "Efekt_aerobowy":   v(act.get("aerobicTrainingEffect")),
        "Efekt_beztlenowy": v(act.get("anaerobicTrainingEffect")),
        "Obciazenie_wysilkiem": v(act.get("activityTrainingLoad")),
        "VO2max":           v(act.get("vO2MaxValue")),
    })

    # Tempo tylko dla biegania/chodzenia
    if act_type in RUNNING_TYPES | WALKING_TYPES:
        row["Tempo_sr"]        = pace(act.get("averageSpeed"))
        row["Tempo_najlepsze"] = pace(act.get("maxSpeed"))
        row["Kadencja_sr_spm"] = v(act.get("averageRunningCadenceInStepsPerMinute"))

    # Szczegóły z dedykowanego endpointu (dynamika biegu, stamina, itp.)
    try:
        details = client.get_activity_details(act_id)
        dto = (details or {}).get("summaryDTO") or {}
        row.update({
            "Tempo_GAP":               pace(dto.get("avgGradeAdjustedSpeed")),
            "Kadencja_max_spm":        v(dto.get("maxRunCadence")),
            "Dlugosc_kroku_m":         round(dto.get("avgStrideLength") or 0, 2) or "",
            "Kontakt_z_podlozem_ms":   v(dto.get("avgGroundContactTime")),
            "Bilans_GCT_pct":          v(dto.get("avgGroundContactBalance")),
            "Odchyl_pionowe_cm":       round(dto.get("avgVerticalOscillation") or 0, 1) or "",
            "Odchyl_do_dlugosci_pct":  round(dto.get("avgVerticalRatio") or 0, 1) or "",
            "W_kg":                    round(dto.get("avgPowerPerKg") or 0, 2) or "",
            "Stamina_start_pct":       round(dto.get("startStamina") or 0, 1) or "",
            "Stamina_koniec_pct":      round(dto.get("endStamina") or 0, 1) or "",
            "BodyBattery_wplyw":       v(dto.get("bodyBatteryChange")),
        })
    except Exception as e:
        print(f"  ⚠️ Szczegóły {act_id}: {e}")

    # Okrążenia — tylko dla biegania
    laps = []
    if act_type in RUNNING_TYPES:
        try:
            splits   = client.get_activity_splits(act_id) or {}
            lap_list = splits.get("lapDTOs") or splits.get("laps") or []
            for i, lap in enumerate(lap_list, 1):
                lap_row = dict.fromkeys(OKRAZENIA_COLS, "")
                lap_row.update({
                    "Data_treningu":          row["Data"],
                    "Aktywnosc_ID":           str(act_id),
                    "Nr_okr":                 i,
                    "Dystans_km":             round((lap.get("distance") or 0) / 1000, 2),
                    "Czas":                   secs_to_str(lap.get("duration")),
                    "Tempo":                  pace(lap.get("averageSpeed")),
                    "GAP":                    pace(lap.get("avgGradeAdjustedSpeed")),
                    "HR_sr":                  v(lap.get("averageHR")),
                    "HR_max":                 v(lap.get("maxHR")),
                    "Moc_sr_W":               v(lap.get("avgPower")),
                    "Moc_max_W":              v(lap.get("maxPower")),
                    "W_kg":                   round(lap.get("avgPowerPerKg") or 0, 2) or "",
                    "Kadencja_sr_spm":        v(lap.get("averageRunningCadenceInStepsPerMinute")),
                    "Kontakt_ms":             v(lap.get("avgGroundContactTime")),
                    "Bilans_GCT_pct":         v(lap.get("avgGroundContactBalance")),
                    "Dlugosc_kroku_m":        round(lap.get("avgStrideLength") or 0, 2) or "",
                    "Odchyl_pionowe_cm":      round(lap.get("avgVerticalOscillation") or 0, 1) or "",
                    "Odchyl_do_dlugosci_pct": round(lap.get("avgVerticalRatio") or 0, 1) or "",
                    "Wznios_m":               v(lap.get("elevationGain"), 0),
                    "Spadek_m":               v(lap.get("elevationLoss"), 0),
                })
                laps.append(lap_row)
        except Exception as e:
            print(f"  ⚠️ Okrążenia {act_id}: {e}")

    return row, laps

# ── GOOGLE SHEETS ─────────────────────────────────────
def get_sheets():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds).spreadsheets()

def get_existing_ids(sheets, tab: str) -> set:
    """Czyta kolumnę A (klucze/daty) — używane do deduplikacji."""
    res = sheets.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A2:A"
    ).execute()
    return {r[0] for r in (res.get("values") or []) if r}

def append_to_sheet(sheets, tab: str, cols: list, rows: list[dict]):
    if not rows:
        print(f"  {tab}: brak nowych danych")
        return
    values = [[str(r.get(c, "")) for c in cols] for r in rows]
    sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A2",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    print(f"✓ {tab}: +{len(rows)} wierszy")

# ── EKSPORT LOKALNY ───────────────────────────────────
def save_local(aktywnosci: list, okrazenia: list, dziennik: list):
    OUTPUT_DIR.mkdir(exist_ok=True)
    datasets = [
        ("aktywnosci", aktywnosci, AKTYWNOSCI_COLS),
        ("okrazenia",  okrazenia,  OKRAZENIA_COLS),
        ("dziennik",   dziennik,   DZIENNIK_COLS),
    ]
    xlsx_path = OUTPUT_DIR / "garmin_data.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for name, data, cols in datasets:
            df = pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)
            df.to_csv(OUTPUT_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")
            df.to_excel(writer, sheet_name=name.capitalize(), index=False)
    print(f"  📁 {xlsx_path}  +  3x .csv  w  /{OUTPUT_DIR.name}/")

# ── GŁÓWNA LOGIKA ─────────────────────────────────────
def main():
    print("=" * 55)
    print("  GARMIN SYNC")
    print("=" * 55)

    client = garmin_login()
    dates  = get_dates_to_fetch()
    print(f"Zakres: {dates[0]} → {dates[-1]}  ({len(dates)} dni)\n")

    sheets = get_sheets()
    existing_dziennik   = get_existing_ids(sheets, "Dziennik")
    existing_aktywnosci = get_existing_ids(sheets, "Aktywności")  # kolumna A = activityId

    new_dziennik   = []
    new_aktywnosci = []
    new_okrazenia  = []

    # ── Dane dzienne ──────────────────────────────────
    print("📅 Dane dzienne...")
    for date_str in dates:
        if date_str in existing_dziennik:
            continue
        row = fetch_daily(client, date_str)
        new_dziennik.append(row)
        print(f"  {date_str}  {row.get('Kroki', 0):>6} kroków  "
              f"sen: {row.get('Sen_h', 0)}h  "
              f"waga: {row.get('Waga_kg', '-')} kg")
        time.sleep(0.5)

    # ── Aktywności ────────────────────────────────────
    print("\n🏃 Aktywności...")
    try:
        all_acts = client.get_activities_by_date(dates[0], dates[-1], "")
        acts = [a for a in all_acts
                if a.get("activityType", {}).get("typeKey") in ALL_TYPES]
        print(f"  Znaleziono {len(acts)} aktywności")

        for act in acts:
            act_id = str(act["activityId"])
            if act_id in existing_aktywnosci:
                continue  # już w Sheets

            act_row, laps = fetch_activity(client, act)
            new_aktywnosci.append(act_row)
            new_okrazenia.extend(laps)

            lap_info = f"  {len(laps)} okr." if laps else ""
            print(f"  {act_row['Data']}  [{act_row['Typ']}]  "
                  f"{act_row['Dystans_km']} km{lap_info}")
            time.sleep(1)

    except Exception as e:
        print(f"⚠️ Błąd pobierania aktywności: {e}")

    # ── Zapis do Google Sheets ────────────────────────
    print("\n📊 Google Sheets...")
    append_to_sheet(sheets, "Dziennik",    DZIENNIK_COLS,    new_dziennik)
    append_to_sheet(sheets, "Aktywności",  AKTYWNOSCI_COLS,  new_aktywnosci)
    append_to_sheet(sheets, "Okrążenia",   OKRAZENIA_COLS,   new_okrazenia)

    # ── Lokalne pliki ─────────────────────────────────
    print("\n💾 Lokalne pliki...")
    save_local(new_aktywnosci, new_okrazenia, new_dziennik)

    # ── Zapisz datę ostatniej sync ────────────────────
    today_str = datetime.date.today().isoformat()
    LAST_SYNC_FILE.write_text(json.dumps({
        "lastDate": today_str,
        "lastRun":  datetime.datetime.now().isoformat(),
    }, indent=2))
    print(f"\n✅ Gotowe!  Następna sync pobierze dane od: {today_str}")

if __name__ == "__main__":
    main()
