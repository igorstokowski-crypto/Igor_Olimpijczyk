import garth
from garminconnect import Garmin
import datetime
import requests
import time
import os
import shutil

# --- KONFIGURACJA ---
GARMIN_EMAIL = "igorstokowski@gmail.com"
GARMIN_PASSWORD = "[Korek730)"
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzcY3bJvbcj6NHPcSJkN1ZpCiqNNNCpiGXwm8uzxG51bYFKI4nj8Cad-hCcSnzxU_PG/exec"

GARMIN_DISPLAY_NAME = "c4bde228-f91e-44db-bb5c-040abe70b731"

ALLOWED_ACTIVITIES = [
    'running', 'treadmill_running', 'trail_running',
    'cycling', 'road_cycling', 'gravel_cycling', 'virtual_ride', 'indoor_cycling',
    'swimming', 'lap_swimming', 'open_water_swimming'
]
# --------------------

def get_last_sync_date():
    """Sprawdza datę ostatniego zapisu w Google Sheets."""
    print("📞 Pytam Google o ostatni zapis...")
    try:
        response = requests.get(WEBHOOK_URL)
        if response.status_code == 200:
            date_str = response.text.strip()
            # Upewniamy się, że to data
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception as e:
        print(f"⚠️ Nie udało się pobrać daty ({e}).")
    
    # Jeśli błąd, startujemy od Lipca (bezpiecznik)
    return datetime.date(2025, 7, 1)

def sync_gap_filler():
    print("🚀 URUCHAMIAM UZUPEŁNIANIE BRAKÓW...")
    
    # 1. Logowanie (Metoda Garth - Przeszczep Mózgu - Twoja działająca wersja)
    clean_session_dir = os.path.join(os.getcwd(), "SESJA_GARTH")
    if os.path.exists(clean_session_dir): shutil.rmtree(clean_session_dir)
    os.makedirs(clean_session_dir, exist_ok=True)
    garth.home = clean_session_dir

    try:
        print("⏳ Logowanie do Garmina...")
        garth.login(GARMIN_EMAIL, GARMIN_PASSWORD)
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.garth = garth.client
        client.display_name = GARMIN_DISPLAY_NAME
        print("✅ Zalogowano!")
    except Exception as e:
        print(f"❌ Błąd logowania: {e}")
        return

    # 2. Logika Dat (Omiń ostatni, omiń dzisiaj)
    last_sync = get_last_sync_date()
    print(f"📅 Ostatni dzień w Excelu: {last_sync}")

    start_date = last_sync + datetime.timedelta(days=1) # Start = Ostatni + 1
    end_date = datetime.date.today() - datetime.timedelta(days=1) # Koniec = Wczoraj

    if start_date > end_date:
        print("😎 Wszystko aktualne! Nie ma pełnych dni do pobrania.")
        print(f"   (Następne pobieranie możliwe jutro dla dnia: {datetime.date.today()})")
        return

    days_to_sync = (end_date - start_date).days + 1
    print(f"📥 Pobieram {days_to_sync} dni (od {start_date} do {end_date})")
    print("------------------------------------------------")

    # 3. Pętla pobierania
    for i in range(days_to_sync):
        current_date = start_date + datetime.timedelta(days=i)
        date_str = current_date.isoformat()
        print(f"Checking {date_str}...", end=" ")

        try:
            # A. KROKI / SEN -> Do zakładki 'Dziennik'
            stats = client.get_user_summary(date_str)
            payload_daily = {
                "type": "daily",
                "date": date_str,
                "steps": stats.get('totalSteps') or 0,
                "calories": stats.get('totalKilocalories') or 0,
                "sleep": round((stats.get('sleepingSeconds') or 0) / 3600, 2)
            }
            requests.post(WEBHOOK_URL, json=payload_daily)

            # B. TRENINGI -> Do zakładki 'Aktywności'
            activities = client.get_activities_by_date(date_str, date_str, "")
            act_count = 0
            for act in activities:
                act_type = act.get('activityType', {}).get('typeKey')
                if act_type in ALLOWED_ACTIVITIES:
                    payload_act = {
                        "type": "activity",
                        "date": act.get('startTimeLocal'),
                        "sport": act_type,
                        "distance": round((act.get('distance') or 0) / 1000, 2),
                        "duration": round((act.get('duration') or 0) / 60, 0),
                        "hr": act.get('averageHR') or 0,
                        "calories": act.get('calories') or 0
                    }
                    requests.post(WEBHOOK_URL, json=payload_act)
                    act_count += 1
            
            if act_count > 0:
                print(f"✅ Dziennik + {act_count} aktywności")
            else:
                print("✅ Dziennik")

        except Exception as e:
            print(f"⚠️ Błąd: {e}")
        
        time.sleep(1) # Przerwa techniczna

    print(f"\n🏁 Sukces! Uzupełniono dane do {end_date}.")

if __name__ == "__main__":
    sync_gap_filler()