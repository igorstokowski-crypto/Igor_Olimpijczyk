#!/usr/bin/env python3
"""
sync.py — Unified sync: Garmin + Fitatu + Hevy → Google Sheets + Excel + CSV

Google Sheets (6 zakładek):
  Dziennik        — Garmin: codzienne kroki, sen, kalorie, HR, waga
  Aktywności      — Garmin: treningi (bieg pełne dane, rower/pływanie/chód podstawowe)
  Okrążenia       — Garmin: km-splits każdego biegu
  Fitatu          — Fitatu: dzienne makro (kcal, białko, tłuszcz, węgle)
  FitatuProdukty  — Fitatu: każdy produkt z każdego dnia
  Hevy            — Hevy: serie siłowe (1 wiersz = 1 seria)

Excel + CSV: exports/sync_data.xlsx  +  6x .csv w exports/

Uruchomienie:
  pip install -r requirements.txt
  python sync.py
"""

import os, json, datetime, time, base64
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import requests
import garth
from garminconnect import Garmin
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ── KONFIGURACJA ──────────────────────────────────────
GARMIN_EMAIL     = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD  = os.environ["GARMIN_PASSWORD"]
FITATU_EMAIL     = os.environ["FITATU_EMAIL"]
FITATU_PASSWORD  = os.environ["FITATU_PASSWORD"]
SPREADSHEET_ID   = os.environ["SPREADSHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS", "even-ally-480810-a1-b7b5e8ed226a.json")

SESSION_DIR    = Path(__file__).parent / "SESJA_GARTH"
LAST_SYNC_FILE = Path(__file__).parent / "last_sync.json"
START_DATE     = "2025-01-01"
OUTPUT_DIR     = Path(__file__).parent / "exports"

HEVY_API_KEY   = os.environ["HEVY_API_KEY"]
HEVY_BASE      = "https://api.hevyapp.com/v1"
HEVY_HEADERS   = {"api-key": HEVY_API_KEY}

FITATU_BASE    = "https://pl-pl.fitatu.com/api"
FITATU_HEADERS = {
    "api-key":      "FITATU-MOBILE-APP",
    "api-secret":   "PYRXtfs88UDJMuCCrNpLV",
    "Content-Type": "application/json",
}
FITATU_MEALS = [
    "breakfast", "secondBreakfast", "lunch", "afternoonSnack",
    "dinner", "supper", "snack",
    "meal1", "meal2", "meal3", "meal4", "meal5", "meal6",
]

RUNNING_TYPES  = {"running", "treadmill_running", "trail_running"}
CYCLING_TYPES  = {"cycling", "road_cycling", "gravel_cycling", "virtual_ride", "indoor_cycling"}
SWIMMING_TYPES = {"swimming", "lap_swimming", "open_water_swimming"}
WALKING_TYPES  = {"walking", "hiking"}
ALL_TYPES      = RUNNING_TYPES | CYCLING_TYPES | SWIMMING_TYPES | WALKING_TYPES

# ── NAGŁÓWKI ZAKŁADEK ─────────────────────────────────
DZIENNIK_COLS = [
    "Data", "Kroki", "Dystans_dzienny_km",
    "Kalorie_aktywne", "Kalorie_calkowite",
    "Sen_h", "Jakos_snu",
    "HR_spoczynkowe", "Stres_sr", "Intensywne_min", "Waga_kg",
]
AKTYWNOSCI_COLS = [
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
]
OKRAZENIA_COLS = [
    "Data_treningu", "Aktywnosc_ID", "Nr_okr",
    "Dystans_km", "Czas", "Tempo", "GAP",
    "HR_sr", "HR_max",
    "Moc_sr_W", "Moc_max_W", "W_kg",
    "Kadencja_sr_spm",
    "Kontakt_ms", "Bilans_GCT_pct",
    "Dlugosc_kroku_m", "Odchyl_pionowe_cm", "Odchyl_do_dlugosci_pct",
    "Wznios_m", "Spadek_m",
]
FITATU_COLS         = ["Data", "Kcal", "Bialko_g", "Tluszcze_g", "Wegle_g"]
FITATU_PROD_COLS    = ["Data", "Produkt", "Gramy", "Kcal"]
TRASY_COLS          = ["Aktywnosc_ID", "Typ", "Punkty_JSON"]

# Typy aktywności bez GPS (bieżnia, indoor)
INDOOR_TYPES = {"treadmill_running", "indoor_cycling", "virtual_ride", "indoor_rowing", "strength_training"}
HEVY_COLS           = [
    "ID_treningu", "Data_start", "Data_koniec", "Czas_trwania",
    "Trening", "Opis_treningu",
    "Cwiczenie", "Notatki_cwiczenia", "Superset_ID",
    "Seria", "Typ",
    "KG", "Reps", "Dystans_m", "Czas_s", "RPE",
]

# ── HELPERS ───────────────────────────────────────────
def fetch_gps_track(garmin, activity_id: int, activity_type: str, max_points: int = 300) -> str:
    """Pobierz trasę GPS aktywności. Zwraca JSON string lub '' gdy brak GPS."""
    if activity_type in INDOOR_TYPES:
        return ""
    try:
        details = garmin.get_activity_details(int(activity_id), maxpoly=max_points)
        geo = (details or {}).get("geoPolylineDTO") or {}
        pts = geo.get("polyline") or []
        if not pts:
            return ""
        step = max(1, len(pts) // max_points)
        track = [
            [round(p["lat"], 6), round(p["lon"], 6)]
            for p in pts[::step]
            if "lat" in p and "lon" in p
        ]
        return json.dumps(track) if track else ""
    except Exception as e:
        print(f"    ⚠️ GPS fetch {activity_id}: {e}")
        return ""

def secs_to_str(s) -> str:
    s = int(s or 0)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def pace(speed_ms) -> str:
    if not speed_ms or speed_ms <= 0:
        return ""
    p = 1000 / speed_ms
    return f"{int(p // 60)}:{int(p % 60):02d}"

def v(val, default=""):
    return val if val is not None else default

def get_dates(from_date: str) -> list[str]:
    start = datetime.date.fromisoformat(from_date) - datetime.timedelta(days=2)
    today = datetime.date.today()
    dates, d = [], start
    while d <= today:
        dates.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return dates

# ── GARMIN AUTH ───────────────────────────────────────
def garmin_login() -> Garmin:
    SESSION_DIR.mkdir(exist_ok=True)
    token_file = SESSION_DIR / "oauth2_token.json"

    print(f"  [debug] SESSION_DIR: {SESSION_DIR}")
    print(f"  [debug] token_file istnieje: {token_file.exists()}")

    if token_file.exists():
        try:
            garth.resume(str(SESSION_DIR))
            print("✅ Garmin: sesja z cache (bez MFA)")
        except Exception as e:
            print(f"  ⚠️ Sesja wygasła ({e}), loguję od nowa...")
            token_file.unlink(missing_ok=True)
            _garmin_fresh_login()
    else:
        _garmin_fresh_login()

    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.garth = garth.client

    try:
        profile = garth.client.connectapi("/userprofile-service/socialProfile")
        client.display_name = profile.get("displayName")
        print(f"  Profil: {client.display_name}")
    except Exception as e:
        client.display_name = os.environ.get("GARMIN_DISPLAY_NAME") or None

    return client

def _garmin_fresh_login():
    token_file = SESSION_DIR / "oauth2_token.json"
    print("⏳ Logowanie Garmin — może pojawić się kod MFA...")
    delays = [0, 30, 60, 120]
    for attempt, delay in enumerate(delays, 1):
        if delay:
            print(f"  ⏳ Rate limit — czekam {delay}s...")
            time.sleep(delay)
        try:
            garth.login(GARMIN_EMAIL, GARMIN_PASSWORD)

            # Próbuj wszystkich znanych metod zapisu sesji
            try:
                garth.save(str(SESSION_DIR))
            except Exception:
                try:
                    garth.client.dump(str(SESSION_DIR))
                except Exception:
                    garth.home = str(SESSION_DIR)

            print(f"  [debug] Pliki po logowaniu: {list(SESSION_DIR.glob('*'))}")

            if token_file.exists():
                print("✅ Zalogowano! Sesja zapisana — kolejne uruchomienia bez MFA")
            else:
                print("⚠️  Zalogowano, ale sesja NIE została zapisana na dysk!")
                print("   Sprawdź uprawnienia do folderu lub wersję garth.")
            break
        except Exception as e:
            if "429" in str(e) and attempt < len(delays):
                print("  ⚠️ Rate limit (429)...")
                continue
            raise

# ── GARMIN: POBIERZ WAGĘ Z PROFILU ───────────────────
def fetch_garmin_current_weight() -> float | None:
    """
    Pobiera wagę ustawioną ręcznie w Garmin > Ustawienia ogólne > Aktualna waga.
    Endpoint: /userprofile-service/userprofile/personal-information
    Zwraca wagę w kg lub None.
    """
    try:
        data = garth.client.connectapi(
            "/userprofile-service/userprofile/personal-information"
        )
        weight_g = data.get("weight")  # w gramach
        if weight_g:
            return round(weight_g / 1000, 1)
    except Exception as e:
        print(f"  ⚠️ Nie udało się pobrać wagi z profilu: {e}")
    return None


# ── GARMIN: DANE DZIENNE ──────────────────────────────
def fetch_garmin_daily(client: Garmin, date_str: str, current_weight_kg: float | None = None) -> dict:
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
        print(f"  ⚠️ Garmin summary {date_str}: {e}")

    try:
        sleep = client.get_sleep_data(date_str)
        score = (((sleep or {}).get("dailySleepDTO") or {})
                 .get("sleepScores", {}).get("overall", {}).get("value"))
        row["Jakos_snu"] = v(score)
    except Exception:
        pass

    # Próba 1: ważenia z Garmin (np. waga Garmin Index)
    try:
        w = client.get_weigh_ins(date_str, date_str)
        entries = (w or {}).get("dateWeightList") or []
        if entries:
            row["Waga_kg"] = round((entries[0].get("weight") or 0) / 1000, 1)
    except Exception:
        pass

    # Próba 2: jeśli brak ważenia z wagi, użyj wagi z General (podanej ręcznie)
    # — wstawiamy tylko gdy to dzisiaj lub przekazano wartość z zewnątrz
    if not row["Waga_kg"] and current_weight_kg:
        row["Waga_kg"] = current_weight_kg

    return row

# ── GARMIN: AKTYWNOŚĆ + OKRĄŻENIA ────────────────────
def fetch_garmin_activity(client: Garmin, act: dict) -> tuple[dict, list[dict]]:
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

    if act_type in RUNNING_TYPES | WALKING_TYPES:
        row["Tempo_sr"]        = pace(act.get("averageSpeed"))
        row["Tempo_najlepsze"] = pace(act.get("maxSpeed"))
        row["Kadencja_sr_spm"] = v(act.get("averageRunningCadenceInStepsPerMinute"))

    try:
        dto = (client.get_activity_details(act_id) or {}).get("summaryDTO") or {}
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

    laps = []
    if act_type in RUNNING_TYPES:
        try:
            splits   = client.get_activity_splits(act_id) or {}
            lap_list = splits.get("lapDTOs") or splits.get("laps") or []
            for i, lap in enumerate(lap_list, 1):
                lr = dict.fromkeys(OKRAZENIA_COLS, "")
                lr.update({
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
                laps.append(lr)
        except Exception as e:
            print(f"  ⚠️ Okrążenia {act_id}: {e}")

    return row, laps

# ── FITATU ────────────────────────────────────────────
def fitatu_login() -> tuple[str, str]:
    res = requests.post(
        f"{FITATU_BASE}/login",
        headers=FITATU_HEADERS,
        json={"_username": FITATU_EMAIL, "_password": FITATU_PASSWORD},
    )
    data = res.json()
    if not data.get("token"):
        raise RuntimeError(f"Fitatu login failed: {data}")
    payload = json.loads(base64.b64decode(data["token"].split(".")[1] + "==").decode())
    print(f"✅ Fitatu zalogowany, userId: {payload['id']}")
    return data["token"], str(payload["id"])

def fetch_fitatu_day(token: str, user_id: str, date_str: str) -> tuple[dict | None, list[dict]]:
    res = requests.get(
        f"{FITATU_BASE}/diet-and-activity-plan/{user_id}/day/{date_str}",
        headers={**FITATU_HEADERS, "authorization": f"Bearer {token}"},
    )
    data = res.json()
    diet = data.get("dietPlan") or {}

    items = []
    for key in FITATU_MEALS:
        for item in (diet.get(key) or {}).get("items") or []:
            items.append(item)

    if not items:
        return None, []

    kcal = bialko = tluszcze = wegle = 0.0
    products = []
    for item in items:
        kcal     += item.get("energy", 0) or 0
        bialko   += item.get("protein", 0) or 0
        tluszcze += item.get("fat", 0) or 0
        wegle    += item.get("carbohydrate", 0) or 0
        products.append({
            "Data":    date_str,
            "Produkt": item.get("name", "?"),
            "Gramy":   item.get("weight", 0) or 0,
            "Kcal":    round(item.get("energy", 0) or 0),
        })

    daily = {
        "Data":       date_str,
        "Kcal":       round(kcal),
        "Bialko_g":   round(bialko),
        "Tluszcze_g": round(tluszcze),
        "Wegle_g":    round(wegle),
    }
    return daily, products

# ── HEVY ─────────────────────────────────────────────
def _fmt_dt(iso: str) -> str:
    """ISO 8601 → dd.mm.yyyy HH:MM"""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso[:16] if iso else ""

def _duration(start_iso: str, end_iso: str) -> str:
    """Zwraca czas trwania w formacie H:MM lub MM:SS"""
    try:
        s = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        e = datetime.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return secs_to_str(int((e - s).total_seconds()))
    except Exception:
        return ""

def fetch_hevy_workouts(existing_ids: set) -> list[dict]:
    """
    Pobiera treningi z Hevy API (paginacja, max pageSize=10).
    Zatrzymuje się gdy natrafi na workout_id już istniejący w Sheets.
    Zwraca płaską listę wierszy (1 wiersz = 1 seria).
    """
    rows = []
    page = 1
    done = False

    while not done:
        res = requests.get(
            f"{HEVY_BASE}/workouts",
            headers=HEVY_HEADERS,
            params={"page": page, "pageSize": 10},  # API max = 10
        )
        if res.status_code != 200:
            print(f"  ⚠️ Hevy API błąd (strona {page}): {res.status_code} — {res.text[:200]}")
            break

        data     = res.json()
        workouts = data.get("workouts") or []
        if not workouts:
            break  # koniec danych

        print(f"  strona {page}/{data.get('page_count', '?')} — {len(workouts)} treningów", end="\r")

        for workout in workouts:
            wid = workout["id"]
            if wid in existing_ids:
                done = True
                break

            start    = workout.get("start_time", "")
            end      = workout.get("end_time", "")
            w_title  = workout.get("title", "")
            w_desc   = workout.get("description", "") or ""

            for ex in workout.get("exercises") or []:
                ex_title  = ex.get("title", "")
                ex_notes  = ex.get("notes", "") or ""
                superset  = ex.get("supersets_id")

                for s in ex.get("sets") or []:
                    rows.append({
                        "ID_treningu":       wid,
                        "Data_start":        _fmt_dt(start),
                        "Data_koniec":       _fmt_dt(end),
                        "Czas_trwania":      _duration(start, end),
                        "Trening":           w_title,
                        "Opis_treningu":     w_desc,
                        "Cwiczenie":         ex_title,
                        "Notatki_cwiczenia": ex_notes,
                        "Superset_ID":       superset if superset is not None else "",
                        "Seria":             (s.get("index") or 0) + 1,
                        "Typ":               s.get("type") or "",
                        "KG":                s.get("weight_kg") if s.get("weight_kg") is not None else "",
                        "Reps":              s.get("reps") if s.get("reps") is not None else "",
                        "Dystans_m":         s.get("distance_meters") if s.get("distance_meters") is not None else "",
                        "Czas_s":            s.get("duration_seconds") if s.get("duration_seconds") is not None else "",
                        "RPE":               s.get("rpe") if s.get("rpe") is not None else "",
                    })

        page += 1

    print()  # newline po \r
    return rows

# ── GOOGLE SHEETS ─────────────────────────────────────
def get_sheets():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds).spreadsheets()

def ensure_tabs(sheets, tabs_cols: dict[str, list]):
    """Tworzy brakujące zakładki i uzupełnia brakujące nagłówki."""
    meta     = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
    existing = {s["properties"]["title"] for s in meta["sheets"]}

    # Utwórz brakujące zakładki
    to_create = [t for t in tabs_cols if t not in existing]
    if to_create:
        sheets.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": t}}} for t in to_create]}
        ).execute()
        for tab in to_create:
            print(f"  ➕ Utworzono zakładkę: {tab}")

    # Zapisz nagłówki wszędzie gdzie wiersz 1 jest pusty
    for tab, headers in tabs_cols.items():
        res = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{tab}'!A1:Z1",
        ).execute()
        if not res.get("values"):  # wiersz 1 pusty — dodaj nagłówki
            sheets.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{tab}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
            print(f"  📋 Nagłówki dodane: {tab}")

def get_existing_keys(sheets, tab: str) -> dict:
    """Zwraca {klucz: numer_wiersza} (wiersz 2 = indeks 0)."""
    try:
        res = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{tab}'!A2:A",
        ).execute()
        return {r[0]: i + 2 for i, r in enumerate(res.get("values") or []) if r}
    except Exception:
        return {}

def upsert_to_sheet(sheets, tab: str, cols: list, rows: list[dict]):
    """Insert nowych wierszy, update istniejących (po kluczu w kolumnie A)."""
    if not rows:
        print(f"  {tab}: brak danych")
        return

    key_to_row = get_existing_keys(sheets, tab)
    to_insert, batch_data = [], []

    for r in rows:
        key    = str(r.get(cols[0], ""))
        values = [str(r.get(c, "")) for c in cols]
        if key in key_to_row:
            row_num = key_to_row[key]
            end_col = chr(ord("A") + len(cols) - 1)
            batch_data.append({
                "range":  f"'{tab}'!A{row_num}:{end_col}{row_num}",
                "values": [values],
            })
        else:
            to_insert.append(values)

    if batch_data:
        sheets.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": batch_data},
        ).execute()
        print(f"  ✓ {tab}: zaktualizowano {len(batch_data)} wierszy")

    if to_insert:
        sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{tab}'!A2",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": to_insert},
        ).execute()
        print(f"  ✓ {tab}: +{len(to_insert)} nowych wierszy")

def upsert_multirow(sheets, tab: str, cols: list, rows: list[dict], date_key: str):
    """
    Dla zakładek gdzie 1 dzień = wiele wierszy (FitatuProdukty, Okrążenia).
    Usuwa wszystkie wiersze dla danej daty i wstawia świeże.
    """
    if not rows:
        return

    dates_to_refresh = {str(r.get(date_key, "")) for r in rows}

    # Pobierz wszystkie wiersze żeby znaleźć numery do usunięcia
    try:
        res = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{tab}'!A2:A",
        ).execute()
        existing_col_a = res.get("values") or []
    except Exception:
        existing_col_a = []

    rows_to_delete = [
        i + 2  # numer wiersza w Sheets (1-indexed, +1 za nagłówek)
        for i, r in enumerate(existing_col_a)
        if r and r[0] in dates_to_refresh
    ]

    # Usuń od końca (żeby numery się nie przesuwały)
    if rows_to_delete:
        requests_list = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId":    _get_sheet_id(sheets, tab),
                        "dimension":  "ROWS",
                        "startIndex": rn - 1,  # 0-indexed
                        "endIndex":   rn,
                    }
                }
            }
            for rn in sorted(rows_to_delete, reverse=True)
        ]
        sheets.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests_list},
        ).execute()
        print(f"  {tab}: usunięto {len(rows_to_delete)} starych wierszy")

    # Wstaw świeże
    values = [[str(r.get(c, "")) for c in cols] for r in rows]
    sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A2",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    print(f"  ✓ {tab}: +{len(rows)} wierszy")

_sheet_id_cache = {}
def _get_sheet_id(sheets, tab_name: str) -> int:
    if tab_name not in _sheet_id_cache:
        meta = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
        for s in meta["sheets"]:
            _sheet_id_cache[s["properties"]["title"]] = s["properties"]["sheetId"]
    return _sheet_id_cache[tab_name]

def append_to_sheet(sheets, tab: str, cols: list, rows: list[dict]):
    """Zachowane dla Hevy — tylko nowe (nie nadpisujemy historii treningów)."""
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
    print(f"  ✓ {tab}: +{len(rows)} wierszy")

# ── EKSPORT LOKALNY ───────────────────────────────────
def save_local(datasets: list[tuple[str, list, list]]):
    OUTPUT_DIR.mkdir(exist_ok=True)
    xlsx_path = OUTPUT_DIR / "sync_data.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for sheet_name, data, cols in datasets:
            df = pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)
            safe_name = sheet_name.replace("ę", "e").replace("ó", "o").replace("ą", "a")
            df.to_csv(OUTPUT_DIR / f"{safe_name}.csv", index=False, encoding="utf-8-sig")
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"  📁 {xlsx_path.name}  +  {len(datasets)}x .csv  →  /{OUTPUT_DIR.name}/")

# ── GŁÓWNA LOGIKA ─────────────────────────────────────
def main():
    print("=" * 55)
    print("  UNIFIED SYNC — Garmin + Fitatu")
    print("=" * 55)

    # Daty
    last_sync = START_DATE
    if LAST_SYNC_FILE.exists():
        saved = json.loads(LAST_SYNC_FILE.read_text())
        last_sync = saved.get("lastDate", START_DATE)
        print(f"Ostatnia sync: {last_sync}")
    else:
        print(f"Pierwsza sync od: {last_sync}")
    dates = get_dates(last_sync)
    print(f"Zakres: {dates[0]} → {dates[-1]}  ({len(dates)} dni)\n")

    # Google Sheets — upewnij się że wszystkie zakładki istnieją
    sheets = get_sheets()
    ensure_tabs(sheets, {
        "Dziennik":       DZIENNIK_COLS,
        "Aktywności":     AKTYWNOSCI_COLS,
        "Okrążenia":      OKRAZENIA_COLS,
        "Fitatu":         FITATU_COLS,
        "FitatuProdukty": FITATU_PROD_COLS,
        "Hevy":           HEVY_COLS,
        "Trasy":          TRASY_COLS,
    })

    existing_hevy = get_existing_keys(sheets, "Hevy")
    existing_akt  = get_existing_keys(sheets, "Aktywności")

    today     = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    # Zawsze odświeżaj dziś i wczoraj; starsze dni — tylko jeśli brak
    def should_refresh(date_str: str, existing_keys: dict) -> bool:
        if date_str >= yesterday:   # dziś lub wczoraj — zawsze update
            return True
        return date_str not in existing_keys

    existing_trasy = get_existing_keys(sheets, "Trasy")

    new = {
        "Dziennik":       [],
        "Aktywności":     [],
        "Okrążenia":      [],
        "Fitatu":         [],
        "FitatuProdukty": [],
        "Hevy":           [],
        "Trasy":          [],
    }

    # ── GARMIN ────────────────────────────────────────
    print("─── GARMIN ───────────────────────────────────────")
    garmin = garmin_login()

    current_weight = fetch_garmin_current_weight()
    if current_weight:
        print(f"  ⚖️  Aktualna waga z profilu: {current_weight} kg")

    existing_dz = get_existing_keys(sheets, "Dziennik")
    print("\n📅 Dane dzienne...")
    for date_str in dates:
        if not should_refresh(date_str, existing_dz):
            continue
        weight_for_day = current_weight if date_str == today else None
        row = fetch_garmin_daily(garmin, date_str, weight_for_day)
        new["Dziennik"].append(row)
        print(f"  {date_str}  {row.get('Kroki', 0):>6} kroków  "
              f"sen: {row.get('Sen_h', 0)}h  "
              f"waga: {row.get('Waga_kg', '-')} kg")
        time.sleep(0.5)

    print("\n🏃 Aktywności...")
    try:
        all_acts = garmin.get_activities_by_date(dates[0], dates[-1], "")
        acts = [a for a in all_acts
                if a.get("activityType", {}).get("typeKey") in ALL_TYPES]
        print(f"  Znaleziono: {len(acts)}")
        for act in acts:
            act_id_str = str(act["activityId"])
            act_typ    = act.get("activityType", {}).get("typeKey", "")

            # GPS — pobierz dla każdej aktywności której jeszcze nie ma w Trasy
            if act_id_str not in existing_trasy:
                gps_json = fetch_gps_track(garmin, act["activityId"], act_typ)
                if gps_json:
                    new["Trasy"].append({
                        "Aktywnosc_ID": act_id_str,
                        "Typ":          act_typ,
                        "Punkty_JSON":  gps_json,
                    })
                    print(f"    🗺️  GPS {act_id_str}: {len(json.loads(gps_json))} punktów")
                else:
                    print(f"    🏟️  Brak GPS {act_id_str} (indoor/bieżnia)")
                time.sleep(0.5)

            # Szczegóły aktywności — tylko nowe
            if act_id_str in existing_akt:
                continue
            act_row, laps = fetch_garmin_activity(garmin, act)
            new["Aktywności"].append(act_row)
            new["Okrążenia"].extend(laps)
            lap_info = f"  {len(laps)} okr." if laps else ""
            print(f"  {act_row['Data']}  [{act_row['Typ']}]  "
                  f"{act_row['Dystans_km']} km{lap_info}")
            time.sleep(1)
    except Exception as e:
        print(f"  ⚠️ Błąd: {e}")

    # ── FITATU ────────────────────────────────────────
    print("\n─── FITATU ───────────────────────────────────────")
    token, user_id = fitatu_login()

    existing_fit  = get_existing_keys(sheets, "Fitatu")
    existing_prod = get_existing_keys(sheets, "FitatuProdukty")
    print("\n🥗 Dane żywieniowe...")
    for date_str in dates:
        if not should_refresh(date_str, existing_fit) and not should_refresh(date_str, existing_prod):
            continue
        daily, products = fetch_fitatu_day(token, user_id, date_str)
        if daily and should_refresh(date_str, existing_fit):
            new["Fitatu"].append(daily)
        if products and should_refresh(date_str, existing_prod):
            new["FitatuProdukty"].extend(products)
        if daily:
            print(f"  {date_str}  {daily['Kcal']} kcal  "
                  f"B:{daily['Bialko_g']}g  T:{daily['Tluszcze_g']}g  W:{daily['Wegle_g']}g  "
                  f"({len(products)} produktów)")

    # ── HEVY ──────────────────────────────────────────────
    print("\n─── HEVY ─────────────────────────────────────────")
    print("🏋️  Treningi siłowe...")
    new["Hevy"] = fetch_hevy_workouts(existing_hevy)
    if new["Hevy"]:
        unique_workouts = len({r["ID_treningu"] for r in new["Hevy"]})
        print(f"  Nowych treningów: {unique_workouts}  ({len(new['Hevy'])} serii)")
    else:
        print("  Brak nowych treningów")

    # ── ZAPIS DO SHEETS ───────────────────────────────
    print("\n─── GOOGLE SHEETS ────────────────────────────────")
    upsert_to_sheet(sheets, "Dziennik",       DZIENNIK_COLS,    new["Dziennik"])
    upsert_to_sheet(sheets, "Aktywności",     AKTYWNOSCI_COLS,  new["Aktywności"])
    upsert_to_sheet(sheets, "Okrążenia",      OKRAZENIA_COLS,   new["Okrążenia"])
    upsert_to_sheet(sheets, "Fitatu",         FITATU_COLS,      new["Fitatu"])
    upsert_multirow(sheets, "FitatuProdukty", FITATU_PROD_COLS, new["FitatuProdukty"], "Data")
    append_to_sheet(sheets, "Hevy",           HEVY_COLS,        new["Hevy"])
    append_to_sheet(sheets, "Trasy",          TRASY_COLS,       new["Trasy"])

    # ── EKSPORT LOKALNY ───────────────────────────────
    print("\n─── EKSPORT LOKALNY ──────────────────────────────")
    save_local([
        ("Dziennik",       new["Dziennik"],       DZIENNIK_COLS),
        ("Aktywności",     new["Aktywności"],      AKTYWNOSCI_COLS),
        ("Okrążenia",      new["Okrążenia"],       OKRAZENIA_COLS),
        ("Fitatu",         new["Fitatu"],          FITATU_COLS),
        ("FitatuProdukty", new["FitatuProdukty"],  FITATU_PROD_COLS),
        ("Hevy",           new["Hevy"],            HEVY_COLS),
        ("Trasy",          new["Trasy"],           TRASY_COLS),
    ])

    # ── ZAPISZ DATĘ SYNC ──────────────────────────────
    today_str = datetime.date.today().isoformat()
    LAST_SYNC_FILE.write_text(json.dumps({
        "lastDate": today_str,
        "lastRun":  datetime.datetime.now().isoformat(),
    }, indent=2))

    print(f"\n{'='*55}")
    print(f"  ✅ Gotowe!  Następna sync od: {today_str}")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
