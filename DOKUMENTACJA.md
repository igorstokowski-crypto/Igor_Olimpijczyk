# 🏃 Igor Health Dashboard — Dokumentacja

> Ostatnia aktualizacja: 21.08.2026

---

## Co to jest?

Osobisty dashboard zdrowotny, który automatycznie pobiera dane z trzech źródeł:
- **Garmin Connect** — kroki, sen, kalorie, aktywności, trasy GPS
- **Fitatu** — kalorie spożyte, makroskładniki, lista produktów
- **Hevy** — treningi siłowe (serie, powtórzenia, ciężary)

Dane lądują w **Postgres** i lokalnym **Excel/CSV**, a dashboard jest dostępny online (login/hasło) i docelowo ma pokazywać też treningi znajomych z Garmin Connect.

---

## Architektura systemu

```
Zegarek Garmin
      ↓
Garmin Connect API
      ↓
sync.py ←── Fitatu API
      ↓    ←── Hevy API
      ↓
Postgres (db/schema.sql)  +  lokalny Excel/CSV
      ↓
dashboard.py (Streamlit, login przez app_users)
```

**Automatyzacja:** GitHub Actions odpala `sync.py` co 3 godziny (8:00–22:00 czasu polskiego).
Wymaga Postgresa dostępnego z internetu (adres w sekrecie `DATABASE_URL`) — patrz "Znane ograniczenia".

---

## Pliki projektu

| Plik | Opis |
|------|------|
| `sync.py` | Główny skrypt synchronizacji — pobiera dane i zapisuje do Postgres + Excel |
| `dashboard.py` | Dashboard Streamlit — login + wizualizacja danych z Postgres |
| `db/schema.sql` | Schemat Postgres (tabele, klucze) |
| `db.py` | Połączenie z Postgres + inicjalizacja schematu (`python db.py`) |
| `repository.py` | Warstwa dostępu do danych — cała logika zapisu/odczytu Postgres |
| `auth.py` | Konta użytkowników strony (Igor + znajomi) — dodawanie, weryfikacja hasła |
| `gmail_mfa.py` | Automatyczny odczyt kodu MFA Garmina z Gmaila (IMAP) |
| `migrate_sheets_to_postgres.py` | Jednorazowa migracja historii ze starego Google Sheets |
| `requirements.txt` | Zależności Python |
| `.env` | Zmienne środowiskowe (lokalne — nie wchodzi do git) |
| `SESJA_GARTH/` | Zapisana sesja logowania Garmin (`garmin_tokens.json`) |
| `.github/workflows/sync.yml` | GitHub Actions — automatyczny sync |
| `exports/` | Lokalny eksport: `sync_data.xlsx` + CSV |

---

## Postgres — tabele (`db/schema.sql`)

| Tabela | Zawartość | Klucz |
|--------|-----------|-------|
| `app_users` | Konta logowania na stronę (Igor + znajomi) | username/email |
| `garmin_people` | Osoby śledzone przez Garmina (właściciel + znajomi z newsfeedu) | garmin_profile_id |
| `daily_summary` | Kroki, sen, kalorie, HR, waga — każdy dzień (tylko właściciel) | person_id + date |
| `activities` | Treningi: dystans, czas, tempo, HR, GPS meta (własne + znajomych) | id (Garmin activity id) |
| `activity_laps` | Km-splity każdego biegu | activity_id + lap_number |
| `gps_tracks` | Trasy GPS jako JSON | activity_id |
| `fitatu_daily` | Dzienne makro: kcal, białko, tłuszcz, węgle | person_id + date |
| `fitatu_products` | Każdy produkt z każdego dnia | — (usuwa+wstawia per dzień) |
| `hevy_sets` | Serie siłowe: ćwiczenie, kg, reps | workout_id + exercise_order + set_number |
| `manual_metrics` | Waga wpisywana ręcznie (zastępuje dawne `General!E2`) | person_id + date |

`person_id` na razie wskazuje wyłącznie na Igora (`is_owner = TRUE`) — kolumna istnieje pod przyszłą
funkcję feedu znajomych z Garmin Connect (`source = 'connection_feed'` w `activities`).

---

## sync.py — jak działa

### Logika odświeżania
- **Dziś i wczoraj** — zawsze pobierane od nowa (nawet jeśli już są w Postgres)
- **Starsze dni** — pomijane jeśli już istnieją w Postgres
- **GitHub Actions** — pobiera ostatnie 7 dni; lokalnie — ostatnie 30 dni

### Garmin
```python
garmin_login()          # Garmin(return_on_mfa=True) + resume_login() z kodem z Gmaila
fetch_garmin_daily()    # kroki, sen, kalorie, HR, stres
fetch_garmin_activity() # szczegóły treningu (tempo, wznios, VO2max, itd.)
fetch_gps_track()       # trasa GPS jako lista {lat, lon, ele}
fetch_garmin_current_weight()  # waga z profilu (jeśli podpięta waga Garmin)
```

### Fitatu
```python
fitatu_login()          # email/hasło → JWT token
fetch_fitatu_day()      # kcal + makro dzienne + lista produktów
```

### Hevy
```python
fetch_hevy_workouts()   # paginacja /v1/workouts → serie z kg×reps
```

### Zapis do Postgres (`repository.py`)
```python
repo.upsert_daily()             # Dziennik — insert/update po (person_id, date)
repo.upsert_activities()        # Aktywności — insert/update po id
repo.upsert_laps()              # Okrążenia — insert/update po (activity_id, lap_number)
repo.upsert_gps_tracks()        # Trasy — insert/update po activity_id
repo.upsert_fitatu_daily()      # Fitatu
repo.replace_fitatu_products()  # FitatuProdukty — usuwa stare wiersze dnia i wstawia świeże
repo.upsert_hevy_sets()         # Hevy — insert, nigdy nie nadpisuje (ON CONFLICT DO NOTHING)
```

---

## dashboard.py — sekcje

### 1. Hero (górny baner)
- Zdjęcie (180px, kółko) + Imię
- Waga (ręcznie wpisywana — sekcja "⚖️ Zaktualizuj wagę" na dashboardzie) · Wzrost 181 cm
- Sen (z dziś — Garmin zapisuje sen nocy pod datą przebudzenia)
- Data

### 2. Podsumowanie miesięczne
- 👟 Kroki w miesiącu (suma z `Dziennik`)
- 💪 Siłownia — ile razy (unikalne `ID_treningu` z `Hevy`)
- 🏃 Bieganie — liczba sesji
- 🚴 Rower / 🏊 Basen — łącznie
- 🔥 Kardio łącznie

### 3. Kalorie
- Spalone (Garmin) vs Spożyte (Fitatu) → bilans

### 4. Ostatni trening siłowy (Hevy)
- Tabela: Ćwiczenie → Serie → Najlepsze podejście (kg×reps) → Wolumen

### 5. Ostatnia aktywność kardio (Garmin)
- Karta z tempem, HR, dynamiką biegu, efektami treningowymi
- Mapa GPS trasy (Plotly Scattermapbox, OpenStreetMap — bez tokena)

### 6. Historia
- 📊 Kroki — wykres słupkowy (ostatnie 30 dni)
- 🔥 Bilans kaloryczny — słupkowy (spalone vs spożyte)
- 🥗 Makro — stacked area (białko/tłuszcz/węgle)

### 7. Co jadłem
- Selektor daty + metryki makro
- Tabela produktów z Fitatu

### Priorytet danych (dziś vs wczoraj)
```python
# Kroki/kalorie: dziś jeśli kroki > 0, inaczej wczoraj
active_row = row_td if (row_td i kroki > 0) else row_yd

# Sen: zawsze z dziś (Garmin zapisuje sen nocy pod datą przebudzenia)
sleep_h = row_td["Sen_h"]

# Fitatu: dziś → wczoraj → ostatni dostępny
```

### Cache
`@st.cache_data(ttl=60)` — dane odświeżane co **60 sekund**

---

## Konta i logowanie

Dashboard wymaga zalogowania (formularz login/hasło) — jedno konto per osoba
(Igor + znajomi), tabela `app_users` w Postgres.

**Dodanie konta:**
```bash
python auth.py add <username> <email> "Wyświetlana nazwa"
# zapyta o hasło (nie jest przekazywane jako argument)
```

**Lista kont:**
```bash
python auth.py list
```

Hasła są hashowane (bcrypt) — nigdy nie są zapisywane ani logowane jawnie.

---

## GitHub Actions — sync.yml

```yaml
on:
  schedule:
    - cron: '0 6,9,12,15,18,20 * * *'  # 8:00, 11:00, 14:00, 17:00, 20:00, 22:00 PL
  workflow_dispatch:  # ręczne odpalenie z GitHub UI
```

### Sekrety (Settings → Secrets → Actions)

| Secret | Zawartość |
|--------|-----------|
| `GARTH_SESSION` | `tar.gz` sesji Garmin (`SESJA_GARTH/`) zakodowany base64 |
| `GARMIN_EMAIL` | Email konta Garmin (to samo konto Gmail co niżej) |
| `GARMIN_PASSWORD` | Hasło Garmin |
| `GMAIL_IMAP_APP_PASSWORD` | Hasło aplikacji Gmail — do automatycznego odczytu kodu MFA (patrz niżej) |
| `FITATU_EMAIL` | Email Fitatu |
| `FITATU_PASSWORD` | Hasło Fitatu |
| `HEVY_API_KEY` | Klucz API Hevy |
| `DATABASE_URL` | Connection string do Postgres — **musi być dostępny z internetu** (patrz "Znane ograniczenia") |

### Jak zakodować sesję Garmin do sekretu
```python
python -c "
import base64, tarfile, io
buf = io.BytesIO()
tar = tarfile.open(fileobj=buf, mode='w:gz')
tar.add('SESJA_GARTH', arcname='SESJA_GARTH')
tar.close()
print(base64.b64encode(buf.getvalue()).decode())
"
```
Wynik wklej jako wartość sekretu `GARTH_SESSION`.

---

## Automatyczne MFA przez Gmail

Konto Garmin ma jako adres logowania dedykowany Gmail. Gdy Garmin przy logowaniu
zażąda kodu weryfikacyjnego (MFA), `sync.py` **nie** pyta o niego interaktywnie —
zamiast tego (`gmail_mfa.py`) loguje się przez IMAP na to konto Gmail, znajduje
najnowszego maila od Garmina wysłanego po rozpoczęciu logowania i wyciąga z niego
6-cyfrowy kod, którym kończy logowanie (`garmin.resume_login(...)`).

Wymagane:
- konto Gmail ustawione jako email logowania w Garmin Connect
- hasło aplikacji Gmail (https://myaccount.google.com/apppasswords, wymaga
  włączonej weryfikacji dwuetapowej na koncie Gmail) w sekrecie/zmiennej
  `GMAIL_IMAP_APP_PASSWORD` — **nigdy nie w kodzie/git**

Sesja Garmin (`SESJA_GARTH`/`GARTH_SESSION`) jest zapisywana po udanym logowaniu,
więc MFA/Gmail jest potrzebne tylko gdy sesja wygaśnie lub jeszcze jej nie ma.

---

## Waga — jak wprowadzić ręcznie

Waga **nie** pobiera się z Garmina (brak podpiętej wagi Garmin Index).

**Gdzie wpisać:** na dashboardzie → rozwiń "⚖️ Zaktualizuj wagę" → wpisz i zapisz
(zapisuje się do tabeli `manual_metrics` w Postgres).

Sync nigdy nie nadpisuje tej wartości.

---

## Jak uruchomić lokalnie

```bash
# 1. Zainstaluj zależności
pip install -r requirements.txt

# 2. Skonfiguruj .env (skopiuj z .env.example)
cp .env.example .env
# uzupełnij dane: Garmin, Gmail, Fitatu, Hevy, DATABASE_URL

# 3. Zainicjalizuj schemat Postgres (jednorazowo / bezpiecznie powtarzalne)
python db.py

# 4. Dodaj sobie konto logowania do dashboardu
python auth.py add igor twoj@email.com "Igor"

# 5. Odpal sync — pierwsze uruchomienie samo się zaloguje i (jeśli trzeba)
#    pobierze kod MFA z Gmaila (GMAIL_IMAP_APP_PASSWORD w .env)
python sync.py

# 6. Uruchom dashboard lokalnie
streamlit run dashboard.py
```

### Migracja starych danych z Google Sheets (jednorazowo)

Jeśli masz historię w starym arkuszu Google Sheets, przenieś ją do Postgres:
```bash
# potrzebne: SPREADSHEET_ID, GOOGLE_CREDENTIALS (credentials.json),
# GARMIN_DISPLAY_NAME (profil z URL connect.garmin.com/app/profile/<TU>)
python migrate_sheets_to_postgres.py
```

---

## Znane ograniczenia

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Kroki z GitHub Actions mogą być stare | Zegarek nie zdążył zsync z Garmin Connect przed uruchomieniem workflow | Odpal sync lokalnie po powrocie do domu |
| Waga nie pobiera się z Garmina | Brak wagi Garmin Index | Wpisuj ręcznie na dashboardzie ("⚖️ Zaktualizuj wagę") |
| Sesja Garmin wygasa | Tokeny OAuth wygasają po pewnym czasie | Nic nie trzeba robić ręcznie — `sync.py` sam się przeloguje i pobierze kod MFA z Gmaila (patrz "Automatyczne MFA przez Gmail" wyżej) |
| **GitHub Actions nie zapisze danych bez dostępnego Postgresa** | `DATABASE_URL` musi być osiągalny z internetu (runnery GitHub Actions nie widzą `localhost` na Twoim komputerze) | Dopóki nie ma VPS-a: postaw Postgres na darmowym hostingu (np. Neon/Supabase/Railway) i wstaw jego connection string jako sekret `DATABASE_URL`; docelowo — Postgres na własnym VPS-ie |

---

## Dashboard online

Wymaga hostingu (patrz wyżej — obecnie w trakcie przenoszenia na własny VPS).

Repozytorium: **https://github.com/igorstokowski-crypto/Igor_Olimpijczyk**
