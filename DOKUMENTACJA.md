# 🏃 Igor Health Dashboard — Dokumentacja

> Ostatnia aktualizacja: 24.03.2026

---

## Co to jest?

Osobisty dashboard zdrowotny, który automatycznie pobiera dane z trzech źródeł:
- **Garmin Connect** — kroki, sen, kalorie, aktywności, trasy GPS
- **Fitatu** — kalorie spożyte, makroskładniki, lista produktów
- **Hevy** — treningi siłowe (serie, powtórzenia, ciężary)

Dane lądują w **Google Sheets** i lokalnym **Excel/CSV**, a dashboard jest dostępny online przez **Streamlit Cloud**.

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
Google Sheets (7 zakładek)  +  lokalny Excel/CSV
      ↓
dashboard.py (Streamlit)
      ↓
https://igorolimpijczyk-kgyrhrrjpdjkhvaamlyrmt.streamlit.app
```

**Automatyzacja:** GitHub Actions odpala `sync.py` co 3 godziny (8:00–22:00 czasu polskiego).

---

## Pliki projektu

| Plik | Opis |
|------|------|
| `sync.py` | Główny skrypt synchronizacji — pobiera dane i zapisuje do Sheets + Excel |
| `dashboard.py` | Dashboard Streamlit — wizualizacja danych z Google Sheets |
| `requirements.txt` | Zależności Python |
| `.env` | Zmienne środowiskowe (lokalne — nie wchodzi do git) |
| `SESJA_GARTH/` | Tokeny OAuth Garmin (`oauth1_token.json` + `oauth2_token.json`) |
| `.github/workflows/sync.yml` | GitHub Actions — automatyczny sync |
| `exports/` | Lokalny eksport: `sync_data.xlsx` + CSV |

---

## Google Sheets — zakładki

| Zakładka | Zawartość | Klucz | Metoda zapisu |
|----------|-----------|-------|---------------|
| `Dziennik` | Kroki, sen, kalorie, HR, waga — każdy dzień | Data | upsert (nadpisuje) |
| `Aktywności` | Treningi: dystans, czas, tempo, HR, GPS meta | ID | upsert (nadpisuje) |
| `Okrążenia` | Km-splity każdego biegu | Data+Nr | upsert |
| `Fitatu` | Dzienne makro: kcal, białko, tłuszcz, węgle | Data | upsert (nadpisuje) |
| `FitatuProdukty` | Każdy produkt z każdego dnia | Data (multi) | delete+insert |
| `Hevy` | Serie siłowe: ćwiczenie, kg, reps | ID serii | append (tylko nowe) |
| `Trasy` | Trasy GPS jako JSON | ID aktywności | append (tylko nowe) |
| `General` | Dane statyczne: waga ręczna (E2), wzrost | — | NIE ruszane przez sync |

---

## sync.py — jak działa

### Logika odświeżania
- **Dziś i wczoraj** — zawsze pobierane od nowa (nawet jeśli już są w Sheets)
- **Starsze dni** — pomijane jeśli już istnieją w Sheets
- **GitHub Actions** — pobiera ostatnie 7 dni; lokalnie — ostatnie 30 dni

### Garmin
```python
garmin_login()          # loguje przez garth (OAuth2, bez MFA dzięki cache tokenów)
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

### Zapis do Sheets
```python
upsert_to_sheet()    # update istniejącego wiersza LUB append nowego (po kluczu z kol. A)
upsert_multirow()    # dla FitatuProdukty — usuwa stare wiersze dnia i wstawia świeże
append_to_sheet()    # tylko nowe wiersze (Hevy, Trasy)
```

---

## dashboard.py — sekcje

### 1. Hero (górny baner)
- Zdjęcie (180px, kółko) + Imię
- Waga (z `General!E2`) · Wzrost 181 cm
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
| `GARTH_SESSION` | `tar.gz` obu tokenów Garmin zakodowany base64 |
| `GARMIN_EMAIL` | Email konta Garmin |
| `GARMIN_PASSWORD` | Hasło Garmin |
| `FITATU_EMAIL` | Email Fitatu |
| `FITATU_PASSWORD` | Hasło Fitatu |
| `HEVY_API_KEY` | Klucz API Hevy |
| `SPREADSHEET_ID` | ID arkusza Google Sheets |
| `GOOGLE_CREDENTIALS_JSON` | JSON klucza service account Google |

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

## Waga — jak wprowadzić ręcznie

Waga **nie** pobiera się z Garmina (brak podpiętej wagi Garmin Index).

**Gdzie wpisać:** Google Sheets → zakładka `General` → komórka **E2**

Sync nigdy nie nadpisuje tej komórki. Dashboard odczytuje ją przy każdym odświeżeniu.

---

## Jak uruchomić lokalnie

```bash
# 1. Zainstaluj zależności
pip install -r requirements.txt

# 2. Skonfiguruj .env (skopiuj z .env.example)
cp .env.example .env
# uzupełnij dane: Garmin, Fitatu, Hevy, Google Sheets ID

# 3. Wstaw credentials Google
# Pobierz plik JSON z Google Cloud Console (Service Account)
# Zapisz jako credentials.json

# 4. Zaloguj Garmin (pierwsze uruchomienie — wymaga MFA)
python -c "import garth; garth.login('email', 'haslo'); garth.save('SESJA_GARTH')"

# 5. Odpal sync
python sync.py

# 6. Uruchom dashboard lokalnie
streamlit run dashboard.py
```

---

## Znane ograniczenia

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Kroki z GitHub Actions mogą być stare | Zegarek nie zdążył zsync z Garmin Connect przed uruchomieniem workflow | Odpal sync lokalnie po powrocie do domu |
| Waga nie pobiera się z Garmina | Brak wagi Garmin Index | Wpisuj ręcznie w Google Sheets → General → E2 |
| GitHub Actions wymaga aktualnej sesji Garmin | Tokeny OAuth wygasają | Co ~30 dni zaktualizuj sekret `GARTH_SESSION` |

---

## Dashboard online

🌐 **https://igorolimpijczyk-kgyrhrrjpdjkhvaamlyrmt.streamlit.app**

Repozytorium: **https://github.com/igorstokowski-crypto/Igor_Olimpijczyk**
