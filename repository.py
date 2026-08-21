"""
repository.py — warstwa dostępu do danych (Postgres), zastępuje bezpośrednie
wywołania Google Sheets API w sync.py i dashboard.py.

Konwencja: funkcje zapisu przyjmują listy dict-ów z kluczami takimi jak w
oryginalnych kolumnach Sheets (np. "Kroki", "Dystans_km") — dzięki temu
kod budujący te dane w sync.py (fetch_garmin_daily, fetch_garmin_activity, …)
nie musiał się zmieniać, zmienia się tylko warstwa zapisu/odczytu.

`read_table_compat(tab)` odtwarza DataFrame z DOKŁADNIE takimi samymi
nagłówkami kolumn jak dawny arkusz Sheets — dashboard.py i analityka
w sync.py mogą więc czytać z Postgresa bez zmiany logiki renderowania.
"""

import json
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import psycopg2.extras

from db import cursor


# ── HELPERY KONWERSJI ─────────────────────────────────────────────────────
def _num(v):
    """"" / None / niekonwertowalne → None; inaczej float."""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _txt(v):
    if v is None or v == "":
        return None
    return str(v)


def _date(v):
    if v is None or v == "":
        return None
    if isinstance(v, (date, datetime)):
        return v
    return str(v)[:10]


# ── OSOBY (garmin_people) ─────────────────────────────────────────────────
def get_or_create_person(garmin_profile_id: str, full_name: str, is_owner: bool = False) -> int:
    with cursor(commit=True) as cur:
        cur.execute(
            "SELECT id FROM garmin_people WHERE garmin_profile_id = %s", (garmin_profile_id,)
        )
        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute(
            """
            INSERT INTO garmin_people (garmin_profile_id, full_name, is_owner)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (garmin_profile_id, full_name, is_owner),
        )
        return cur.fetchone()["id"]


def get_owner_person_id() -> int | None:
    with cursor() as cur:
        cur.execute("SELECT id FROM garmin_people WHERE is_owner = TRUE LIMIT 1")
        row = cur.fetchone()
        return row["id"] if row else None


# ── ISTNIEJĄCE KLUCZE (odpowiednik get_existing_keys) ─────────────────────
def existing_daily_dates(person_id: int) -> set[str]:
    with cursor() as cur:
        cur.execute("SELECT date FROM daily_summary WHERE person_id = %s", (person_id,))
        return {r["date"].isoformat() for r in cur.fetchall()}


def daily_has_steps(person_id: int) -> dict[str, bool]:
    with cursor() as cur:
        cur.execute(
            "SELECT date, steps FROM daily_summary WHERE person_id = %s", (person_id,)
        )
        return {r["date"].isoformat(): bool(r["steps"]) for r in cur.fetchall()}


def existing_activity_ids(person_id: int) -> set[str]:
    with cursor() as cur:
        cur.execute("SELECT id FROM activities WHERE person_id = %s", (person_id,))
        return {str(r["id"]) for r in cur.fetchall()}


def existing_track_ids(person_id: int) -> set[str]:
    with cursor() as cur:
        cur.execute(
            "SELECT gt.activity_id FROM gps_tracks gt "
            "JOIN activities a ON a.id = gt.activity_id WHERE a.person_id = %s",
            (person_id,),
        )
        return {str(r["activity_id"]) for r in cur.fetchall()}


def existing_fitatu_dates(person_id: int) -> set[str]:
    with cursor() as cur:
        cur.execute("SELECT date FROM fitatu_daily WHERE person_id = %s", (person_id,))
        return {r["date"].isoformat() for r in cur.fetchall()}


def existing_fitatu_product_dates(person_id: int) -> set[str]:
    with cursor() as cur:
        cur.execute(
            "SELECT DISTINCT date FROM fitatu_products WHERE person_id = %s", (person_id,)
        )
        return {r["date"].isoformat() for r in cur.fetchall()}


def existing_hevy_workout_ids(person_id: int) -> set[str]:
    with cursor() as cur:
        cur.execute(
            "SELECT DISTINCT workout_id FROM hevy_sets WHERE person_id = %s", (person_id,)
        )
        return {r["workout_id"] for r in cur.fetchall()}


# ── ZAPIS: DZIENNIK ────────────────────────────────────────────────────────
def upsert_daily(person_id: int, rows: list[dict]):
    if not rows:
        print("  Dziennik: brak danych")
        return
    with cursor(commit=True) as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO daily_summary
                    (person_id, date, steps, distance_km, calories_active, calories_total,
                     sleep_h, sleep_quality, resting_hr, avg_stress, vigorous_minutes, weight_kg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (person_id, date) DO UPDATE SET
                    steps = EXCLUDED.steps, distance_km = EXCLUDED.distance_km,
                    calories_active = EXCLUDED.calories_active, calories_total = EXCLUDED.calories_total,
                    sleep_h = EXCLUDED.sleep_h, sleep_quality = EXCLUDED.sleep_quality,
                    resting_hr = EXCLUDED.resting_hr, avg_stress = EXCLUDED.avg_stress,
                    vigorous_minutes = EXCLUDED.vigorous_minutes, weight_kg = EXCLUDED.weight_kg
                """,
                (
                    person_id, _date(r.get("Data")), _num(r.get("Kroki")), _num(r.get("Dystans_dzienny_km")),
                    _num(r.get("Kalorie_aktywne")), _num(r.get("Kalorie_calkowite")),
                    _num(r.get("Sen_h")), _num(r.get("Jakos_snu")), _num(r.get("HR_spoczynkowe")),
                    _num(r.get("Stres_sr")), _num(r.get("Intensywne_min")), _num(r.get("Waga_kg")),
                ),
            )
    print(f"  ✓ Dziennik: {len(rows)} wierszy")


# ── ZAPIS: AKTYWNOŚCI ──────────────────────────────────────────────────────
def upsert_activities(person_id: int, rows: list[dict], source: str = "own"):
    if not rows:
        print("  Aktywności: brak danych")
        return
    with cursor(commit=True) as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO activities (
                    id, person_id, source, started_at, name, sport, distance_km, duration,
                    moving_duration, calories, avg_hr, max_hr, elevation_gain_m, elevation_loss_m,
                    avg_temperature, avg_pace, gap_pace, best_pace, avg_power_w, max_power_w,
                    power_per_kg, avg_cadence_spm, max_cadence_spm, stride_length_m,
                    ground_contact_ms, gct_balance_pct, vertical_oscillation_cm, vertical_ratio_pct,
                    aerobic_effect, anaerobic_effect, training_load, stamina_start_pct,
                    stamina_end_pct, vo2max, body_battery_change
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    started_at = EXCLUDED.started_at, name = EXCLUDED.name, sport = EXCLUDED.sport,
                    distance_km = EXCLUDED.distance_km, duration = EXCLUDED.duration,
                    moving_duration = EXCLUDED.moving_duration, calories = EXCLUDED.calories,
                    avg_hr = EXCLUDED.avg_hr, max_hr = EXCLUDED.max_hr,
                    elevation_gain_m = EXCLUDED.elevation_gain_m, elevation_loss_m = EXCLUDED.elevation_loss_m,
                    avg_temperature = EXCLUDED.avg_temperature, avg_pace = EXCLUDED.avg_pace,
                    gap_pace = EXCLUDED.gap_pace, best_pace = EXCLUDED.best_pace,
                    avg_power_w = EXCLUDED.avg_power_w, max_power_w = EXCLUDED.max_power_w,
                    power_per_kg = EXCLUDED.power_per_kg, avg_cadence_spm = EXCLUDED.avg_cadence_spm,
                    max_cadence_spm = EXCLUDED.max_cadence_spm, stride_length_m = EXCLUDED.stride_length_m,
                    ground_contact_ms = EXCLUDED.ground_contact_ms, gct_balance_pct = EXCLUDED.gct_balance_pct,
                    vertical_oscillation_cm = EXCLUDED.vertical_oscillation_cm,
                    vertical_ratio_pct = EXCLUDED.vertical_ratio_pct,
                    aerobic_effect = EXCLUDED.aerobic_effect, anaerobic_effect = EXCLUDED.anaerobic_effect,
                    training_load = EXCLUDED.training_load, stamina_start_pct = EXCLUDED.stamina_start_pct,
                    stamina_end_pct = EXCLUDED.stamina_end_pct, vo2max = EXCLUDED.vo2max,
                    body_battery_change = EXCLUDED.body_battery_change
                """,
                (
                    int(r["ID"]), person_id, source, _txt(r.get("Data")), _txt(r.get("Nazwa")),
                    _txt(r.get("Typ")), _num(r.get("Dystans_km")), _txt(r.get("Czas")),
                    _txt(r.get("Czas_ruchu")), _num(r.get("Kalorie")), _num(r.get("HR_sr")),
                    _num(r.get("HR_max")), _num(r.get("Wznios_m")), _num(r.get("Spadek_m")),
                    _num(r.get("Temperatura_sr")), _txt(r.get("Tempo_sr")), _txt(r.get("Tempo_GAP")),
                    _txt(r.get("Tempo_najlepsze")), _num(r.get("Moc_sr_W")), _num(r.get("Moc_max_W")),
                    _num(r.get("W_kg")), _num(r.get("Kadencja_sr_spm")), _num(r.get("Kadencja_max_spm")),
                    _num(r.get("Dlugosc_kroku_m")), _num(r.get("Kontakt_z_podlozem_ms")),
                    _num(r.get("Bilans_GCT_pct")), _num(r.get("Odchyl_pionowe_cm")),
                    _num(r.get("Odchyl_do_dlugosci_pct")), _num(r.get("Efekt_aerobowy")),
                    _num(r.get("Efekt_beztlenowy")), _num(r.get("Obciazenie_wysilkiem")),
                    _num(r.get("Stamina_start_pct")), _num(r.get("Stamina_koniec_pct")),
                    _num(r.get("VO2max")), _num(r.get("BodyBattery_wplyw")),
                ),
            )
    print(f"  ✓ Aktywności: {len(rows)} wierszy")


# ── ZAPIS: OKRĄŻENIA ───────────────────────────────────────────────────────
def upsert_laps(rows: list[dict]):
    if not rows:
        return
    with cursor(commit=True) as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO activity_laps (
                    activity_id, lap_number, distance_km, duration, avg_pace, gap_pace,
                    avg_hr, max_hr, avg_power_w, max_power_w, power_per_kg, avg_cadence_spm,
                    ground_contact_ms, gct_balance_pct, stride_length_m, vertical_oscillation_cm,
                    vertical_ratio_pct, elevation_gain_m, elevation_loss_m
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (activity_id, lap_number) DO UPDATE SET
                    distance_km = EXCLUDED.distance_km, duration = EXCLUDED.duration,
                    avg_pace = EXCLUDED.avg_pace, gap_pace = EXCLUDED.gap_pace,
                    avg_hr = EXCLUDED.avg_hr, max_hr = EXCLUDED.max_hr,
                    avg_power_w = EXCLUDED.avg_power_w, max_power_w = EXCLUDED.max_power_w,
                    power_per_kg = EXCLUDED.power_per_kg, avg_cadence_spm = EXCLUDED.avg_cadence_spm,
                    ground_contact_ms = EXCLUDED.ground_contact_ms, gct_balance_pct = EXCLUDED.gct_balance_pct,
                    stride_length_m = EXCLUDED.stride_length_m,
                    vertical_oscillation_cm = EXCLUDED.vertical_oscillation_cm,
                    vertical_ratio_pct = EXCLUDED.vertical_ratio_pct,
                    elevation_gain_m = EXCLUDED.elevation_gain_m, elevation_loss_m = EXCLUDED.elevation_loss_m
                """,
                (
                    int(r["Aktywnosc_ID"]), int(r["Nr_okr"]), _num(r.get("Dystans_km")),
                    _txt(r.get("Czas")), _txt(r.get("Tempo")), _txt(r.get("GAP")),
                    _num(r.get("HR_sr")), _num(r.get("HR_max")), _num(r.get("Moc_sr_W")),
                    _num(r.get("Moc_max_W")), _num(r.get("W_kg")), _num(r.get("Kadencja_sr_spm")),
                    _num(r.get("Kontakt_ms")), _num(r.get("Bilans_GCT_pct")),
                    _num(r.get("Dlugosc_kroku_m")), _num(r.get("Odchyl_pionowe_cm")),
                    _num(r.get("Odchyl_do_dlugosci_pct")), _num(r.get("Wznios_m")), _num(r.get("Spadek_m")),
                ),
            )
    print(f"  ✓ Okrążenia: {len(rows)} wierszy")


# ── ZAPIS: TRASY GPS ───────────────────────────────────────────────────────
def upsert_gps_tracks(rows: list[dict]):
    if not rows:
        return
    with cursor(commit=True) as cur:
        for r in rows:
            points = json.loads(r["Punkty_JSON"]) if r.get("Punkty_JSON") else []
            cur.execute(
                """
                INSERT INTO gps_tracks (activity_id, sport, points)
                VALUES (%s, %s, %s)
                ON CONFLICT (activity_id) DO UPDATE SET sport = EXCLUDED.sport, points = EXCLUDED.points
                """,
                (int(r["Aktywnosc_ID"]), _txt(r.get("Typ")), psycopg2.extras.Json(points)),
            )
    print(f"  ✓ Trasy: {len(rows)} wierszy")


# ── ZAPIS: FITATU ──────────────────────────────────────────────────────────
def upsert_fitatu_daily(person_id: int, rows: list[dict]):
    if not rows:
        print("  Fitatu: brak danych")
        return
    with cursor(commit=True) as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO fitatu_daily (person_id, date, kcal, protein_g, fat_g, carbs_g)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (person_id, date) DO UPDATE SET
                    kcal = EXCLUDED.kcal, protein_g = EXCLUDED.protein_g,
                    fat_g = EXCLUDED.fat_g, carbs_g = EXCLUDED.carbs_g
                """,
                (
                    person_id, _date(r.get("Data")), _num(r.get("Kcal")),
                    _num(r.get("Bialko_g")), _num(r.get("Tluszcze_g")), _num(r.get("Wegle_g")),
                ),
            )
    print(f"  ✓ Fitatu: {len(rows)} wierszy")


def replace_fitatu_products(person_id: int, rows: list[dict]):
    """Jak upsert_multirow — usuwa wszystkie produkty danego dnia i wstawia świeże."""
    if not rows:
        return
    dates = {_date(r.get("Data")) for r in rows}
    with cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM fitatu_products WHERE person_id = %s AND date = ANY(%s::date[])",
            (person_id, list(dates)),
        )
        for r in rows:
            cur.execute(
                """
                INSERT INTO fitatu_products (person_id, date, product, grams, kcal)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (person_id, _date(r.get("Data")), _txt(r.get("Produkt")), _num(r.get("Gramy")), _num(r.get("Kcal"))),
            )
    print(f"  ✓ FitatuProdukty: {len(rows)} wierszy")


# ── ZAPIS: HEVY ────────────────────────────────────────────────────────────
def upsert_hevy_sets(person_id: int, rows: list[dict]):
    """rows muszą zawierać klucz 'Cwiczenie_kolejnosc' (0-indexed kolejność ćwiczenia w treningu)."""
    if not rows:
        print("  Hevy: brak nowych danych")
        return
    with cursor(commit=True) as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO hevy_sets (
                    person_id, workout_id, exercise_order, set_number, started_at, ended_at,
                    duration, workout_title, workout_notes, exercise_name, exercise_notes,
                    superset_id, set_type, weight_kg, reps, distance_m, duration_s, rpe
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workout_id, exercise_order, set_number) DO NOTHING
                """,
                (
                    person_id, str(r["ID_treningu"]), int(r["Cwiczenie_kolejnosc"]), int(r["Seria"]),
                    _txt(r.get("Data_start")), _txt(r.get("Data_koniec")), _txt(r.get("Czas_trwania")),
                    _txt(r.get("Trening")), _txt(r.get("Opis_treningu")), _txt(r.get("Cwiczenie")),
                    _txt(r.get("Notatki_cwiczenia")), _txt(r.get("Superset_ID")), _txt(r.get("Typ")),
                    _num(r.get("KG")), _num(r.get("Reps")), _num(r.get("Dystans_m")),
                    _num(r.get("Czas_s")), _num(r.get("RPE")),
                ),
            )
    unique_workouts = len({r["ID_treningu"] for r in rows})
    print(f"  ✓ Hevy: {unique_workouts} treningów ({len(rows)} serii)")


# ── DANE RĘCZNE (waga) ─────────────────────────────────────────────────────
def set_manual_weight(person_id: int, weight_kg: float, on_date: date | None = None):
    on_date = on_date or date.today()
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO manual_metrics (person_id, date, weight_kg)
            VALUES (%s, %s, %s)
            ON CONFLICT (person_id, date) DO UPDATE SET weight_kg = EXCLUDED.weight_kg
            """,
            (person_id, on_date, weight_kg),
        )


def get_latest_manual_weight(person_id: int) -> float | None:
    with cursor() as cur:
        cur.execute(
            "SELECT weight_kg FROM manual_metrics WHERE person_id = %s AND weight_kg IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (person_id,),
        )
        row = cur.fetchone()
        return float(row["weight_kg"]) if row else None


# ── ODCZYT — KOMPATYBILNY Z NAGŁÓWKAMI SHEETS (dla dashboard.py / analityki) ─
_TAB_QUERIES = {
    "Dziennik": (
        """SELECT date AS "Data", steps AS "Kroki", distance_km AS "Dystans_dzienny_km",
                  calories_active AS "Kalorie_aktywne", calories_total AS "Kalorie_calkowite",
                  sleep_h AS "Sen_h", sleep_quality AS "Jakos_snu", resting_hr AS "HR_spoczynkowe",
                  avg_stress AS "Stres_sr", vigorous_minutes AS "Intensywne_min", weight_kg AS "Waga_kg"
           FROM daily_summary WHERE person_id = %(person_id)s ORDER BY date""",
    ),
    "Aktywności": (
        """SELECT id AS "ID", started_at AS "Data", name AS "Nazwa", sport AS "Typ",
                  distance_km AS "Dystans_km", duration AS "Czas", moving_duration AS "Czas_ruchu",
                  calories AS "Kalorie", avg_hr AS "HR_sr", max_hr AS "HR_max",
                  elevation_gain_m AS "Wznios_m", elevation_loss_m AS "Spadek_m",
                  avg_temperature AS "Temperatura_sr", avg_pace AS "Tempo_sr", gap_pace AS "Tempo_GAP",
                  best_pace AS "Tempo_najlepsze", avg_power_w AS "Moc_sr_W", max_power_w AS "Moc_max_W",
                  power_per_kg AS "W_kg", avg_cadence_spm AS "Kadencja_sr_spm",
                  max_cadence_spm AS "Kadencja_max_spm", stride_length_m AS "Dlugosc_kroku_m",
                  ground_contact_ms AS "Kontakt_z_podlozem_ms", gct_balance_pct AS "Bilans_GCT_pct",
                  vertical_oscillation_cm AS "Odchyl_pionowe_cm", vertical_ratio_pct AS "Odchyl_do_dlugosci_pct",
                  aerobic_effect AS "Efekt_aerobowy", anaerobic_effect AS "Efekt_beztlenowy",
                  training_load AS "Obciazenie_wysilkiem", stamina_start_pct AS "Stamina_start_pct",
                  stamina_end_pct AS "Stamina_koniec_pct", vo2max AS "VO2max",
                  body_battery_change AS "BodyBattery_wplyw"
           FROM activities WHERE person_id = %(person_id)s ORDER BY started_at""",
    ),
    "Okrążenia": (
        """SELECT a.started_at AS "Data_treningu", al.activity_id AS "Aktywnosc_ID",
                  al.lap_number AS "Nr_okr", al.distance_km AS "Dystans_km", al.duration AS "Czas",
                  al.avg_pace AS "Tempo", al.gap_pace AS "GAP", al.avg_hr AS "HR_sr", al.max_hr AS "HR_max",
                  al.avg_power_w AS "Moc_sr_W", al.max_power_w AS "Moc_max_W", al.power_per_kg AS "W_kg",
                  al.avg_cadence_spm AS "Kadencja_sr_spm", al.ground_contact_ms AS "Kontakt_ms",
                  al.gct_balance_pct AS "Bilans_GCT_pct", al.stride_length_m AS "Dlugosc_kroku_m",
                  al.vertical_oscillation_cm AS "Odchyl_pionowe_cm",
                  al.vertical_ratio_pct AS "Odchyl_do_dlugosci_pct",
                  al.elevation_gain_m AS "Wznios_m", al.elevation_loss_m AS "Spadek_m"
           FROM activity_laps al JOIN activities a ON a.id = al.activity_id
           WHERE a.person_id = %(person_id)s ORDER BY a.started_at, al.lap_number""",
    ),
    "Fitatu": (
        """SELECT date AS "Data", kcal AS "Kcal", protein_g AS "Bialko_g",
                  fat_g AS "Tluszcze_g", carbs_g AS "Wegle_g"
           FROM fitatu_daily WHERE person_id = %(person_id)s ORDER BY date""",
    ),
    "FitatuProdukty": (
        """SELECT date AS "Data", product AS "Produkt", grams AS "Gramy", kcal AS "Kcal"
           FROM fitatu_products WHERE person_id = %(person_id)s ORDER BY date""",
    ),
    "Hevy": (
        """SELECT workout_id AS "ID_treningu", started_at AS "Data_start", ended_at AS "Data_koniec",
                  duration AS "Czas_trwania", workout_title AS "Trening", workout_notes AS "Opis_treningu",
                  exercise_name AS "Cwiczenie", exercise_notes AS "Notatki_cwiczenia",
                  superset_id AS "Superset_ID", set_number AS "Seria", set_type AS "Typ",
                  weight_kg AS "KG", reps AS "Reps", distance_m AS "Dystans_m",
                  duration_s AS "Czas_s", rpe AS "RPE"
           FROM hevy_sets WHERE person_id = %(person_id)s ORDER BY started_at, exercise_order, set_number""",
    ),
    "Trasy": (
        """SELECT gt.activity_id AS "Aktywnosc_ID", gt.sport AS "Typ", gt.points AS "Punkty_JSON"
           FROM gps_tracks gt JOIN activities a ON a.id = gt.activity_id
           WHERE a.person_id = %(person_id)s""",
    ),
}


def read_table_compat(tab: str, person_id: int) -> pd.DataFrame:
    """
    Zwraca DataFrame z nagłówkami identycznymi jak dawny arkusz Sheets,
    wartości jako stringi (tak jak zwracało Sheets API) — dla zgodności
    z dashboard.py / build_analytics bez zmiany logiki renderowania.
    """
    (query,) = _TAB_QUERIES[tab]
    with cursor() as cur:
        cur.execute(query, {"person_id": person_id})
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        if isinstance(v, Decimal):
            return str(int(v)) if v == v.to_integral_value() else str(v)
        return str(v)

    cols = list(rows[0].keys())
    return pd.DataFrame([[cell(r[c]) for c in cols] for r in rows], columns=cols)
