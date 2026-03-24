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

import sys, os, json, datetime, time, base64
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
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

def _n(v):
    """Bezpieczna konwersja do float."""
    try: return float(str(v).replace(",", ".").strip())
    except: return None

def _read_full_sheet(sheets, tab: str) -> pd.DataFrame:
    """Wczytuje cały arkusz Google Sheets jako DataFrame."""
    try:
        res = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A:ZZ"
        ).execute()
        rows = res.get("values", [])
        if len(rows) < 2:
            return pd.DataFrame()
        n = len(rows[0])
        return pd.DataFrame([r + [""] * (n - len(r)) for r in rows[1:]], columns=rows[0])
    except Exception:
        return pd.DataFrame()

def build_analytics(sheets) -> dict[str, pd.DataFrame]:
    """
    Czyta pełną historię z Google Sheets i oblicza arkusze analityczne.
    Zwraca słownik {nazwa_arkusza: DataFrame}.
    """
    import numpy as np

    # ── Wczytaj pełną historię ─────────────────────────
    df_dz   = _read_full_sheet(sheets, "Dziennik")
    df_akt  = _read_full_sheet(sheets, "Aktywności")
    df_fit  = _read_full_sheet(sheets, "Fitatu")
    df_hevy = _read_full_sheet(sheets, "Hevy")

    # Normalizuj Fitatu — stare nagłówki: 'Dzień','Białko (g)','Tłuszcze (G)','Węgle (g)'
    if not df_fit.empty:
        df_fit = df_fit.rename(columns={
            "Dzień":         "Data",
            "Białko (g)":    "Bialko_g",
            "Białko (G)":    "Bialko_g",
            "Tłuszcze (g)":  "Tluszcze_g",
            "Tłuszcze (G)":  "Tluszcze_g",
            "Węgle (g)":     "Wegle_g",
            "Węgle (G)":     "Wegle_g",
        })

    result = {}

    # ══════════════════════════════════════════════════
    # 1. STATYSTYKI — ogólne metryki i średnie
    # ══════════════════════════════════════════════════
    stats_rows = []

    if not df_dz.empty:
        for col in ["Kroki", "Kalorie_calkowite", "Kalorie_aktywne",
                    "Sen_h", "Jakos_snu", "HR_spoczynkowe", "Stres_sr",
                    "Intensywne_min", "Waga_kg"]:
            if col in df_dz.columns:
                df_dz[col] = df_dz[col].apply(_n)
        df_dz["Data"] = pd.to_datetime(df_dz["Data"], errors="coerce")
        df_dz = df_dz.dropna(subset=["Data"]).sort_values("Data")

        steps = df_dz["Kroki"].dropna()
        sleep = df_dz["Sen_h"].dropna()
        hr    = df_dz["HR_spoczynkowe"].dropna()
        stress= df_dz["Stres_sr"].dropna()
        waga  = df_dz["Waga_kg"].dropna()

        stats_rows += [
            ("KROKI", "", ""),
            ("Średnia dzienna",          f"{steps.mean():.0f}" if len(steps) else "—", "kroków"),
            ("Mediana dzienna",           f"{steps.median():.0f}" if len(steps) else "—", "kroków"),
            ("Maksimum (1 dzień)",        f"{steps.max():.0f}" if len(steps) else "—", "kroków"),
            ("Dni z celem 10 000+",       f"{(steps >= 10000).sum()}", f"/ {len(steps)} dni"),
            ("Łącznie wszystkich kroków", f"{steps.sum():.0f}", "kroków"),
            ("", "", ""),
            ("SEN", "", ""),
            ("Średni sen",               f"{sleep.mean():.2f}" if len(sleep) else "—", "h"),
            ("Najkrótszy sen",           f"{sleep.min():.2f}" if len(sleep) else "—", "h"),
            ("Najdłuższy sen",           f"{sleep.max():.2f}" if len(sleep) else "—", "h"),
            ("Dni < 7h snu",             f"{(sleep < 7).sum()}", f"/ {len(sleep)} dni"),
            ("", "", ""),
            ("TĘTNO SPOCZYNKOWE", "", ""),
            ("Średnie HR spoczynkowe",    f"{hr.mean():.1f}" if len(hr) else "—", "bpm"),
            ("Najniższe HR",             f"{hr.min():.0f}" if len(hr) else "—", "bpm"),
            ("Najwyższe HR",             f"{hr.max():.0f}" if len(hr) else "—", "bpm"),
            ("", "", ""),
            ("STRES", "", ""),
            ("Średni stres",             f"{stress.mean():.1f}" if len(stress) else "—", "/ 100"),
            ("Dni z niskim stresem (<25)", f"{(stress < 25).sum()}", f"/ {len(stress)} dni"),
            ("Dni z wysokim stresem (>50)", f"{(stress > 50).sum()}", f"/ {len(stress)} dni"),
        ]
        if len(waga) > 0:
            bmi = waga.iloc[-1] / (1.81 ** 2)
            stats_rows += [
                ("", "", ""),
                ("WAGA", "", ""),
                ("Ostatnia waga",         f"{waga.iloc[-1]:.1f}", "kg"),
                ("BMI (wzrost 181 cm)",   f"{bmi:.1f}", "kg/m²"),
                ("Najniższa waga",        f"{waga.min():.1f}", "kg"),
                ("Najwyższa waga",        f"{waga.max():.1f}", "kg"),
            ]

    if not df_fit.empty:
        for col in ["Kcal", "Bialko_g", "Tluszcze_g", "Wegle_g"]:
            if col in df_fit.columns:
                df_fit[col] = df_fit[col].apply(_n)
        df_fit["Data"] = pd.to_datetime(df_fit["Data"], errors="coerce")
        df_fit = df_fit.dropna(subset=["Data"]).sort_values("Data")

        kcal = df_fit["Kcal"].dropna()
        bial = df_fit["Bialko_g"].dropna()
        tlus = df_fit["Tluszcze_g"].dropna()
        wegl = df_fit["Wegle_g"].dropna()

        stats_rows += [
            ("", "", ""),
            ("ODŻYWIANIE (Fitatu)", "", ""),
            ("Średnie kcal / dzień",     f"{kcal.mean():.0f}" if len(kcal) else "—", "kcal"),
            ("Maks kcal w dzień",        f"{kcal.max():.0f}" if len(kcal) else "—", "kcal"),
            ("Min kcal w dzień",         f"{kcal.min():.0f}" if len(kcal) else "—", "kcal"),
            ("Średnie białko",           f"{bial.mean():.1f}" if len(bial) else "—", "g/dzień"),
            ("Średnie tłuszcze",         f"{tlus.mean():.1f}" if len(tlus) else "—", "g/dzień"),
            ("Średnie węgle",            f"{wegl.mean():.1f}" if len(wegl) else "—", "g/dzień"),
        ]

        if not df_dz.empty:
            merged = df_dz.merge(df_fit[["Data", "Kcal"]], on="Data", how="inner")
            if "Kalorie_calkowite" in merged.columns:
                merged["Bilans"] = merged["Kalorie_calkowite"] - merged["Kcal"]
                bilans = merged["Bilans"].dropna()
                deficyt = (bilans < 0).sum()
                nadwyzka = (bilans >= 0).sum()
                stats_rows += [
                    ("", "", ""),
                    ("BILANS KALORYCZNY", "", ""),
                    ("Średni bilans / dzień",  f"{bilans.mean():.0f}" if len(bilans) else "—", "kcal"),
                    ("Dni z deficytem",        f"{deficyt}", f"/ {len(bilans)} dni"),
                    ("Dni z nadwyżką",         f"{nadwyzka}", f"/ {len(bilans)} dni"),
                    ("Łączny bilans",          f"{bilans.sum():.0f}", "kcal"),
                ]

    if not df_akt.empty:
        for col in ["Dystans_km", "Kalorie", "HR_sr", "Wznios_m"]:
            if col in df_akt.columns:
                df_akt[col] = df_akt[col].apply(_n)
        df_akt["Data"] = pd.to_datetime(df_akt["Data"], errors="coerce")
        df_akt = df_akt.dropna(subset=["Data"]).sort_values("Data")

        if "Typ" in df_akt.columns:
            biegi = df_akt[df_akt["Typ"].str.lower().isin(RUNNING_TYPES)]
            rowery = df_akt[df_akt["Typ"].str.lower().isin(CYCLING_TYPES)]
            stats_rows += [
                ("", "", ""),
                ("AKTYWNOŚCI ŁĄCZNIE", "", ""),
                ("Wszystkich treningów",   f"{len(df_akt)}", ""),
                ("Łączny dystans",        f"{df_akt['Dystans_km'].sum():.1f}" if "Dystans_km" in df_akt.columns else "—", "km"),
                ("", "", ""),
                ("BIEGANIE", "", ""),
                ("Liczba biegów",          f"{len(biegi)}", ""),
                ("Łączny dystans",        f"{biegi['Dystans_km'].sum():.1f}" if len(biegi) else "—", "km"),
                ("Średni dystans",        f"{biegi['Dystans_km'].mean():.2f}" if len(biegi) else "—", "km"),
                ("Łączne wzniesienie",    f"{biegi['Wznios_m'].sum():.0f}" if len(biegi) else "—", "m"),
                ("", "", ""),
                ("ROWER / INNE KARDIO", "", ""),
                ("Liczba jazd",            f"{len(rowery)}", ""),
                ("Łączny dystans",        f"{rowery['Dystans_km'].sum():.1f}" if len(rowery) else "—", "km"),
            ]

    if not df_hevy.empty:
        df_hevy["Data_start"] = pd.to_datetime(df_hevy["Data_start"] if "Data_start" in df_hevy.columns else df_hevy.get("Data", ""), errors="coerce")
        sesje = df_hevy["ID_treningu"].nunique() if "ID_treningu" in df_hevy.columns else 0
        stats_rows += [
            ("", "", ""),
            ("SIŁOWNIA (Hevy)", "", ""),
            ("Łączna liczba sesji",  f"{sesje}", ""),
            ("Łączna liczba serii",  f"{len(df_hevy)}", ""),
        ]

    result["Statystyki"] = pd.DataFrame(stats_rows, columns=["Metryka", "Wartość", "Jednostka"])

    # ══════════════════════════════════════════════════
    # 2. MIESIĄCE — zestawienie per miesiąc
    # ══════════════════════════════════════════════════
    miesiace_rows = []

    if not df_dz.empty:
        df_dz["Miesiac"] = df_dz["Data"].dt.to_period("M")
        gr_dz = df_dz.groupby("Miesiac")

        miesiace_map = {}
        for m, grp in gr_dz:
            miesiace_map[str(m)] = {
                "Kroki_suma":   grp["Kroki"].sum() if "Kroki" in grp else 0,
                "Kroki_sr":     grp["Kroki"].mean() if "Kroki" in grp else 0,
                "Sen_sr":       grp["Sen_h"].mean() if "Sen_h" in grp else 0,
                "HR_sr":        grp["HR_spoczynkowe"].mean() if "HR_spoczynkowe" in grp else 0,
                "Intensywne_suma": grp["Intensywne_min"].sum() if "Intensywne_min" in grp else 0,
            }

        if not df_fit.empty:
            df_fit["Miesiac"] = df_fit["Data"].dt.to_period("M")
            gr_fit = df_fit.groupby("Miesiac")
            for m, grp in gr_fit:
                ms = str(m)
                if ms not in miesiace_map:
                    miesiace_map[ms] = {}
                miesiace_map[ms]["Kcal_sr"]   = grp["Kcal"].mean() if "Kcal" in grp else 0
                miesiace_map[ms]["Bialko_sr"]  = grp["Bialko_g"].mean() if "Bialko_g" in grp else 0
                miesiace_map[ms]["Tluszcze_sr"] = grp["Tluszcze_g"].mean() if "Tluszcze_g" in grp else 0
                miesiace_map[ms]["Wegle_sr"]   = grp["Wegle_g"].mean() if "Wegle_g" in grp else 0

        if not df_akt.empty:
            df_akt["Miesiac"] = df_akt["Data"].dt.to_period("M")
            gr_akt = df_akt.groupby("Miesiac")
            for m, grp in gr_akt:
                ms = str(m)
                if ms not in miesiace_map:
                    miesiace_map[ms] = {}
                typ = grp["Typ"].str.lower() if "Typ" in grp else pd.Series([], dtype=str)
                miesiace_map[ms]["Treningi_laczn"] = len(grp)
                miesiace_map[ms]["Km_laczn"]       = grp["Dystans_km"].sum() if "Dystans_km" in grp else 0
                miesiace_map[ms]["Biegi_ile"]       = int(typ.isin(RUNNING_TYPES).sum())
                miesiace_map[ms]["Biegi_km"]        = float(grp.loc[typ.isin(RUNNING_TYPES), "Dystans_km"].sum()) if "Dystans_km" in grp else 0
                miesiace_map[ms]["Wznios_m"]        = grp["Wznios_m"].sum() if "Wznios_m" in grp else 0

        if not df_hevy.empty:
            dc = "Data_start" if "Data_start" in df_hevy.columns else "Data"
            if dc in df_hevy.columns:
                df_hevy["_dt"] = pd.to_datetime(df_hevy[dc], errors="coerce")
                df_hevy["Miesiac"] = df_hevy["_dt"].dt.to_period("M")
                gr_h = df_hevy.groupby("Miesiac")
                for m, grp in gr_h:
                    ms = str(m)
                    if ms not in miesiace_map:
                        miesiace_map[ms] = {}
                    miesiace_map[ms]["Silownia_ile"] = grp["ID_treningu"].nunique() if "ID_treningu" in grp else 0

        for ms in sorted(miesiace_map.keys()):
            d = miesiace_map[ms]
            miesiace_rows.append({
                "Miesiąc":           ms,
                "Kroki suma":        round(d.get("Kroki_suma", 0)),
                "Kroki śr/dzień":    round(d.get("Kroki_sr", 0)),
                "Sen śr (h)":        round(d.get("Sen_sr", 0), 2),
                "HR spocz. śr":      round(d.get("HR_sr", 0), 1),
                "Intens. min suma":  round(d.get("Intensywne_suma", 0)),
                "Kcal śr/dzień":     round(d.get("Kcal_sr", 0)),
                "Białko śr (g)":     round(d.get("Bialko_sr", 0), 1),
                "Tłuszcze śr (g)":   round(d.get("Tluszcze_sr", 0), 1),
                "Węgle śr (g)":      round(d.get("Wegle_sr", 0), 1),
                "Treningi":          d.get("Treningi_laczn", 0),
                "Km łącznie":        round(d.get("Km_laczn", 0), 1),
                "Biegi (ile)":       d.get("Biegi_ile", 0),
                "Biegi km":          round(d.get("Biegi_km", 0), 1),
                "Wzniesienie m":     round(d.get("Wznios_m", 0)),
                "Siłownia (ile)":    d.get("Silownia_ile", 0),
            })

    result["Miesiące"] = pd.DataFrame(miesiace_rows) if miesiace_rows else pd.DataFrame()

    # ══════════════════════════════════════════════════
    # 3. REKORDY — personal bests
    # ══════════════════════════════════════════════════
    rekordy_rows = []

    if not df_akt.empty and "Typ" in df_akt.columns:
        biegi = df_akt[df_akt["Typ"].str.lower().isin(RUNNING_TYPES)].copy()

        if len(biegi) > 0:
            rekordy_rows.append(("BIEGANIE — REKORDY", "", "", ""))

            if "Dystans_km" in biegi.columns:
                idx = biegi["Dystans_km"].idxmax()
                r = biegi.loc[idx]
                rekordy_rows.append(("Najdłuższy bieg", f"{r['Dystans_km']:.2f} km",
                                     str(r["Data"])[:10], r.get("Nazwa", "")))

            if "Tempo_sr" in biegi.columns:
                biegi_z_tempem = biegi[biegi["Tempo_sr"].apply(lambda x: bool(str(x).strip() and str(x) != "0"))]
                if len(biegi_z_tempem) > 0:
                    idx = biegi_z_tempem["Tempo_sr"].astype(str).apply(
                        lambda t: sum(int(x) * (60 ** i) for i, x in enumerate(reversed(t.split(":")))) if ":" in t else 9999
                    ).idxmin()
                    r = biegi_z_tempem.loc[idx]
                    rekordy_rows.append(("Najszybsze tempo śr.", r["Tempo_sr"],
                                         str(r["Data"])[:10], f"{r['Dystans_km']:.2f} km"))

            if "Wznios_m" in biegi.columns:
                idx = biegi["Wznios_m"].idxmax()
                r = biegi.loc[idx]
                rekordy_rows.append(("Największe wzniesienie", f"{r['Wznios_m']:.0f} m",
                                     str(r["Data"])[:10], f"{r['Dystans_km']:.2f} km"))

            if "HR_sr" in biegi.columns:
                idx = biegi["HR_sr"].idxmin()
                r = biegi.loc[idx]
                rekordy_rows.append(("Najniższe HR podczas biegu", f"{r['HR_sr']:.0f} bpm",
                                     str(r["Data"])[:10], f"{r['Dystans_km']:.2f} km"))

            # Rekordy dystansowe
            for prog, label in [(5, "5 km"), (10, "10 km"), (21, "półmaraton"), (42, "maraton")]:
                kandydaci = biegi[biegi["Dystans_km"] >= prog] if "Dystans_km" in biegi.columns else pd.DataFrame()
                if len(kandydaci) > 0 and "Tempo_sr" in kandydaci.columns:
                    idx = kandydaci["Tempo_sr"].astype(str).apply(
                        lambda t: sum(int(x) * (60 ** i) for i, x in enumerate(reversed(t.split(":")))) if ":" in t else 9999
                    ).idxmin()
                    r = kandydaci.loc[idx]
                    rekordy_rows.append((f"Najszybszy bieg {label}+", r["Tempo_sr"],
                                         str(r["Data"])[:10], f"{r['Dystans_km']:.2f} km"))

    if not df_hevy.empty and "Cwiczenie" in df_hevy.columns:
        df_hevy["KG"] = df_hevy["KG"].apply(_n) if "KG" in df_hevy.columns else 0
        df_hevy["Reps"] = df_hevy["Reps"].apply(_n) if "Reps" in df_hevy.columns else 0
        df_hevy["Wolumen"] = df_hevy["KG"] * df_hevy["Reps"]

        rekordy_rows.append(("", "", "", ""))
        rekordy_rows.append(("SIŁOWNIA — REKORDY (max ciężar per ćwiczenie)", "", "", ""))

        top_cwiczenia = df_hevy.groupby("Cwiczenie")["KG"].max().sort_values(ascending=False).head(15)
        for cwicz, max_kg in top_cwiczenia.items():
            row_best = df_hevy[(df_hevy["Cwiczenie"] == cwicz) & (df_hevy["KG"] == max_kg)].iloc[0]
            dc = "Data_start" if "Data_start" in df_hevy.columns else "Data"
            rekordy_rows.append((
                cwicz,
                f"{max_kg:.1f} kg × {int(row_best['Reps'] or 0)} reps",
                str(row_best.get(dc, ""))[:10],
                f"wolumen: {row_best['Wolumen']:.0f} kg"
            ))

    result["Rekordy"] = pd.DataFrame(rekordy_rows, columns=["Ćwiczenie / Metryka", "Wynik", "Data", "Opis"]) if rekordy_rows else pd.DataFrame()

    # ══════════════════════════════════════════════════
    # 4. BILANS KCAL — dzień po dniu
    # ══════════════════════════════════════════════════
    if not df_dz.empty and not df_fit.empty and "Kalorie_calkowite" in df_dz.columns:
        merged = df_dz[["Data", "Kroki", "Kalorie_calkowite", "Kalorie_aktywne", "Sen_h", "HR_spoczynkowe"]].merge(
            df_fit[["Data", "Kcal", "Bialko_g", "Tluszcze_g", "Wegle_g"]], on="Data", how="outer"
        ).sort_values("Data")
        merged["Bilans_kcal"] = merged["Kalorie_calkowite"] - merged["Kcal"]
        merged["Data"] = merged["Data"].dt.strftime("%Y-%m-%d")
        for col in merged.select_dtypes(include="float64").columns:
            merged[col] = merged[col].round(2)
        result["Bilans kcal"] = merged.rename(columns={
            "Kalorie_calkowite": "Spalone kcal",
            "Kalorie_aktywne":   "Aktywne kcal",
            "Kcal":              "Spożyte kcal",
            "Bialko_g":          "Białko g",
            "Tluszcze_g":        "Tłuszcze g",
            "Wegle_g":           "Węgle g",
            "Bilans_kcal":       "Bilans kcal",
            "Sen_h":             "Sen h",
            "HR_spoczynkowe":    "HR spocz.",
        })
    else:
        result["Bilans kcal"] = pd.DataFrame()

    return result


def save_analytics_to_sheets(sheets, analytics: dict[str, pd.DataFrame]):
    """
    Zapisuje arkusze analityczne do Google Sheets.
    Każdy DataFrame → osobna zakładka (całkowity nadpis: usuń + wstaw nowe dane).
    """
    for tab_name, df in analytics.items():
        if df.empty:
            print(f"  {tab_name}: brak danych — pominięto")
            continue
        try:
            # Wypełnij NaN pustymi stringami, konwertuj wszystko na string
            df_clean = df.fillna("").astype(str)
            header = [list(df_clean.columns)]
            rows   = df_clean.values.tolist()
            values = header + rows

            # Sprawdź czy zakładka istnieje — jeśli nie, utwórz
            meta = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
            existing_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

            if tab_name not in existing_titles:
                sheets.batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
                ).execute()

            # Wyczyść zawartość i wstaw świeże dane
            sheets.values().clear(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{tab_name}'!A:ZZ"
            ).execute()
            sheets.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{tab_name}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()
            print(f"  ✓ {tab_name}: {len(rows)} wierszy → Google Sheets")
        except Exception as e:
            print(f"  ⚠️ {tab_name}: błąd zapisu do Sheets — {e}")


def save_local(datasets: list[tuple[str, list, list]], sheets=None):
    OUTPUT_DIR.mkdir(exist_ok=True)
    xlsx_path = OUTPUT_DIR / "sync_data.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for sheet_name, data, cols in datasets:
            df = pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)
            safe_name = sheet_name.replace("ę", "e").replace("ó", "o").replace("ą", "a")
            df.to_csv(OUTPUT_DIR / f"{safe_name}.csv", index=False, encoding="utf-8-sig")
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Arkusze analityczne — czytamy pełną historię z Google Sheets
        analytics = {}
        if sheets is not None:
            try:
                import traceback
                analytics = build_analytics(sheets)
                for aname, adf in analytics.items():
                    if not adf.empty:
                        adf.to_excel(writer, sheet_name=aname, index=False)
                print(f"  ✓ Analiza Excel: {', '.join(analytics.keys())}")
            except Exception as e:
                traceback.print_exc()
                print(f"  ⚠️ Błąd analizy: {e}")

    print(f"  📁 {xlsx_path.name}  +  {len(datasets)}x .csv  →  /{OUTPUT_DIR.name}/")
    return analytics  # zwróć żeby main mógł zapisać do Sheets

# ── GŁÓWNA LOGIKA ─────────────────────────────────────
def main():
    print("=" * 55)
    print("  UNIFIED SYNC — Garmin + Fitatu")
    print("=" * 55)

    # Daty — w GitHub Actions zawsze ostatnie 7 dni
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    if in_ci:
        last_sync = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        print(f"GitHub Actions — sync ostatnich 7 dni od: {last_sync}")
    elif LAST_SYNC_FILE.exists():
        saved = json.loads(LAST_SYNC_FILE.read_text())
        last_sync = saved.get("lastDate", START_DATE)
        print(f"Ostatnia sync: {last_sync}")
    else:
        last_sync = START_DATE
        print(f"Pierwsza sync od: {last_sync}")
    dates = get_dates(last_sync)
    print(f"Zakres: {dates[0]} - {dates[-1]}  ({len(dates)} dni)\n")

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
    analytics = save_local([
        ("Dziennik",       new["Dziennik"],       DZIENNIK_COLS),
        ("Aktywności",     new["Aktywności"],      AKTYWNOSCI_COLS),
        ("Okrążenia",      new["Okrążenia"],       OKRAZENIA_COLS),
        ("Fitatu",         new["Fitatu"],          FITATU_COLS),
        ("FitatuProdukty", new["FitatuProdukty"],  FITATU_PROD_COLS),
        ("Hevy",           new["Hevy"],            HEVY_COLS),
        ("Trasy",          new["Trasy"],           TRASY_COLS),
    ], sheets=sheets)

    # ── ANALITYKA → GOOGLE SHEETS ─────────────────────
    if analytics:
        print("\n─── ANALITYKA → GOOGLE SHEETS ────────────────────")
        save_analytics_to_sheets(sheets, analytics)

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
