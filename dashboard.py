#!/usr/bin/env python3
"""
dashboard.py — Personal health dashboard for Igor
"""

import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import date, datetime, timedelta
import os, json
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
CREDS_FILE     = os.getenv("GOOGLE_CREDENTIALS", "credentials.json")
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

st.set_page_config(page_title="Igor · Dashboard", page_icon="🏃", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
  .block-container { padding: 1.5rem 2.5rem 2rem; }

  [data-testid="stMetricValue"] { font-size: 2rem !important; font-weight: 800; }
  [data-testid="stMetricLabel"] { font-size: 0.75rem !important; color: #999 !important; text-transform: uppercase; letter-spacing: .07em; }
  [data-testid="stMetricDelta"] { font-size: 0.82rem !important; }

  .sec { font-size: 0.78rem; font-weight: 700; color: #aaa; text-transform: uppercase;
         letter-spacing: .1em; margin: 1.8rem 0 .6rem; border-bottom: 1px solid #f0f0f0; padding-bottom: .3rem; }

  .card { background: #fff; border: 1.5px solid #eee; border-radius: 16px; padding: 1.2rem 1.4rem; }
  .card-title { font-size: 0.75rem; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: .07em; margin-bottom: .4rem; }
  .card-name { font-size: 1.15rem; font-weight: 700; color: #111; margin-bottom: .3rem; }
  .card-date { font-size: 0.8rem; color: #bbb; margin-bottom: .8rem; }
  .card-stats { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .8rem; }
  .stat-pill { background: #f5f5f5; border-radius: 20px; padding: 4px 12px; font-size: 0.82rem; color: #333; }
  .ex-pill { background: #EEF2FF; color: #4F46E5; border-radius: 20px; padding: 3px 10px; font-size: 0.8rem; display: inline-block; margin: 2px; }

  .prod-table { width: 100%; border-collapse: collapse; margin-top: .4rem; }
  .prod-table th { font-size: 0.72rem; color: #aaa; text-transform: uppercase; letter-spacing: .05em;
                   border-bottom: 1px solid #f0f0f0; padding: 4px 8px; text-align: left; }
  .prod-table td { font-size: 0.88rem; padding: 5px 8px; border-bottom: 1px solid #fafafa; }
  .prod-table tr:last-child td { border-bottom: none; }
  .prod-kcal { color: #888; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ── Google Sheets ──────────────────────────────────────────────────────────────
@st.cache_resource
def _svc():
    try:
        info = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds).spreadsheets()

@st.cache_data(ttl=300, show_spinner=False)
def sheet(tab: str) -> pd.DataFrame:
    try:
        rows = _svc().values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A:ZZ"
        ).execute().get("values", [])
        if len(rows) < 2:
            return pd.DataFrame()
        n = len(rows[0])
        return pd.DataFrame([r + [""] * (n - len(r)) for r in rows[1:]], columns=rows[0])
    except Exception as e:
        st.warning(f"Błąd zakładki '{tab}': {e}")
        return pd.DataFrame()


# ── Helpers ────────────────────────────────────────────────────────────────────
def n(v, d=None):
    try: return float(str(v).replace(",", ".").strip())
    except: return d

def fmt(v, suf="", dec=0):
    if v is None: return "—"
    return f"{v:,.{dec}f}{suf}".replace(",", " ")

yday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Load ───────────────────────────────────────────────────────────────────────
with st.spinner(""):
    df_dz   = sheet("Dziennik")
    df_akt  = sheet("Aktywności")
    df_hevy = sheet("Hevy")
    df_fit  = sheet("Fitatu")
    df_prod = sheet("FitatuProdukty")
    df_gen  = sheet("General")


# ── Dziennik ───────────────────────────────────────────────────────────────────
dz, row_yd = pd.DataFrame(), None
if not df_dz.empty and "Data" in df_dz.columns:
    dz = df_dz.copy()
    dz["Data"] = pd.to_datetime(dz["Data"], errors="coerce")
    dz = dz.sort_values("Data").dropna(subset=["Data"])
    m = dz["Data"].dt.strftime("%Y-%m-%d") == yday
    row_yd = dz[m].iloc[-1] if m.any() else None

# weight — z arkusza General, komórka E2 (Current Weight)
latest_weight = None
try:
    raw_w = _svc().values().get(
        spreadsheetId=SPREADSHEET_ID, range="General!E2"
    ).execute().get("values", [[]])[0][0]
    latest_weight = n(raw_w)
except Exception:
    pass

steps       = n(row_yd.get("Kroki"))             if row_yd is not None else None
kcal_burned = n(row_yd.get("Kalorie_calkowite")) if row_yd is not None else None
sleep_h     = n(row_yd.get("Sen_h"))             if row_yd is not None else None
sleep_score = n(row_yd.get("Jakos_snu"))         if row_yd is not None else None
dist_day    = n(row_yd.get("Dystans_dzienny_km")) if row_yd is not None else None

# Fitatu — sprawdź wczoraj, a jeśli brak to ostatni dostępny dzień
fit_row, kcal_eaten, fit_date_used = None, None, yday

def match_date(df, col, date_str):
    """Dopasuj datę ignorując format (YYYY-MM-DD lub inne)."""
    mask = df[col].str.strip().str[:10] == date_str
    return df[mask]

if not df_fit.empty and "Data" in df_fit.columns:
    r = match_date(df_fit, "Data", yday)
    if r.empty:
        # weź ostatni dostępny dzień
        df_fit_sorted = df_fit.copy()
        df_fit_sorted["_dt"] = pd.to_datetime(df_fit_sorted["Data"].str.strip().str[:10], errors="coerce")
        df_fit_sorted = df_fit_sorted.dropna(subset=["_dt"]).sort_values("_dt")
        if not df_fit_sorted.empty:
            r = df_fit_sorted.iloc[[-1]]
            fit_date_used = df_fit_sorted["_dt"].iloc[-1].strftime("%Y-%m-%d")
    if not r.empty:
        fit_row    = r.iloc[-1]
        kcal_eaten = n(fit_row.get("Kcal"))

# Products — tak samo
prods = pd.DataFrame()
if not df_prod.empty and "Data" in df_prod.columns:
    prods = match_date(df_prod, "Data", fit_date_used).copy()
    if prods.empty and fit_date_used != yday:
        prods = match_date(df_prod, "Data", fit_date_used).copy()

# Balance
balance = None
if kcal_burned and kcal_eaten:
    balance = int(kcal_burned - kcal_eaten)

# Last cardio
last_cardio = None
CARDIO = {"running","cycling","swimming","walking","trail_running",
          "open_water_swimming","road_biking","indoor_cycling","treadmill_running"}
if not df_akt.empty and "Data" in df_akt.columns:
    akt = df_akt.copy()
    akt["_dt"] = pd.to_datetime(akt["Data"], errors="coerce")
    cardio_df = akt[akt["Typ"].str.lower().isin(CARDIO)] if "Typ" in akt.columns else akt
    if not cardio_df.empty:
        last_cardio = cardio_df.sort_values("_dt").iloc[-1]

# Last strength
hevy_name, hevy_exs, hevy_date, hevy_sets = None, [], None, 0
if not df_hevy.empty:
    h = df_hevy.copy()
    dc = "Data_start" if "Data_start" in h.columns else "Data"
    if dc in h.columns:
        h["_dt"] = pd.to_datetime(h[dc], errors="coerce")
        h = h.dropna(subset=["_dt"])
        if not h.empty:
            wid  = h.sort_values("_dt").iloc[-1].get("ID_treningu")
            wk   = h[h["ID_treningu"] == wid]
            hevy_name = wk.iloc[-1].get("Trening", "Trening siłowy")
            hevy_date = wk["_dt"].max()
            hevy_sets = len(wk)
            if "Cwiczenie" in wk.columns:
                hevy_exs = list(wk["Cwiczenie"].dropna().unique())


# ══════════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

# Header
c_img, c_name, c_date = st.columns([1, 4, 2])
with c_img:
    try:
        st.image("zdj.jpg", width=160, output_format="JPEG")
    except Exception:
        pass
with c_name:
    st.markdown("<div style='padding-top:.3rem'><span style='font-size:2rem;font-weight:800'>Igor</span><br><span style='color:#aaa;font-size:.9rem'>Personal Health Dashboard</span></div>", unsafe_allow_html=True)
with c_date:
    st.markdown(
        f"<div style='text-align:right;padding-top:.9rem;color:#aaa;font-size:.85rem;'>"
        f"📅 {date.today().strftime('%A, %d %B %Y')}</div>",
        unsafe_allow_html=True
    )
st.divider()


# ── Waga + Sen ────────────────────────────────────────────────────────────────
st.markdown('<div class="sec">📊 Sylwetka</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3)

c1.metric("⚖️ Waga", fmt(latest_weight, " kg", 1))
c2.metric("📏 Wzrost", "181 cm")

def sleep_label(s):
    if s is None: return None
    q = "Świetny" if s >= 85 else "Dobry" if s >= 70 else "Średni" if s >= 50 else "Słaby"
    return f"{int(s)}/100 · {q}"

c3.metric("😴 Sen", fmt(sleep_h, " h", 1), delta=sleep_label(sleep_score), delta_color="off")


# ── Kalorie ───────────────────────────────────────────────────────────────────
st.markdown(
    f'<div class="sec">🔥 Kalorie — {(date.today()-timedelta(days=1)).strftime("%d.%m.%Y")}</div>',
    unsafe_allow_html=True
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("👟 Kroki",        fmt(steps, "", 0)       if steps else "—")
c2.metric("🔥 Spalone",      fmt(kcal_burned, " kcal", 0))
c3.metric("🥗 Spożyte",      fmt(kcal_eaten,  " kcal", 0))

if balance is not None:
    lbl   = "📉 Deficyt" if balance > 0 else "📈 Nadwyżka"
    color = "normal"    if balance > 0 else "inverse"
    c4.metric(lbl, fmt(abs(balance), " kcal", 0), delta_color=color)
else:
    c4.metric("⚡ Bilans", "—")


# ── Makra ─────────────────────────────────────────────────────────────────────
if fit_row is not None:
    c1, c2, c3 = st.columns(3)
    c1.metric("🥩 Białko",      fmt(n(fit_row.get("Bialko_g")),  " g", 0))
    c2.metric("🧈 Tłuszcze",    fmt(n(fit_row.get("Tluszcze_g")), " g", 0))
    c3.metric("🍞 Węglowodany", fmt(n(fit_row.get("Wegle_g")),   " g", 0))


# ── Co jadłem ─────────────────────────────────────────────────────────────────
st.markdown('<div class="sec">🛒 Co jadłem wczoraj</div>', unsafe_allow_html=True)

if not prods.empty:
    cols_show = [c for c in ["Produkt", "Gramy", "Kcal"] if c in prods.columns]
    rows_html = ""
    total_kcal = 0
    for _, row in prods[cols_show].iterrows():
        produkt = row.get("Produkt", "")
        gramy   = row.get("Gramy", "")
        kcal_v  = row.get("Kcal", "")
        g_fmt   = f"{n(gramy):.0f} g" if n(gramy) else gramy
        k_val   = n(kcal_v)
        if k_val: total_kcal += k_val
        k_fmt   = f"{k_val:.0f}" if k_val else kcal_v
        rows_html += f"<tr><td>{produkt}</td><td style='color:#888'>{g_fmt}</td><td style='color:#888'>{k_fmt}</td></tr>"

    st.markdown(f"""
    <div class="card">
      <table class="prod-table">
        <thead><tr><th>Produkt</th><th>Gramy</th><th>Kcal</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
      <div style="margin-top:.6rem;font-size:.82rem;color:#aaa;text-align:right;">
        Łącznie: <b style="color:#333">{int(total_kcal)} kcal</b> · {len(prods)} produktów
      </div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#bbb;font-size:.9rem;padding:.5rem 0">Brak danych z Fitatu na ten dzień</div>', unsafe_allow_html=True)


# ── Treningi ──────────────────────────────────────────────────────────────────
st.markdown('<div class="sec">🏋️ Ostatnie treningi</div>', unsafe_allow_html=True)
c_sila, c_kardio = st.columns(2)

with c_sila:
    exs_html = "".join(f'<span class="ex-pill">{e}</span>' for e in hevy_exs) if hevy_exs else '<span style="color:#bbb">brak danych</span>'
    d_sila   = hevy_date.strftime("%d.%m.%Y") if hevy_date else "—"
    sets_str = f'<div style="margin-top:.7rem"><span class="stat-pill">📊 {hevy_sets} serii</span></div>' if hevy_sets else ""
    st.markdown(f"""
    <div class="card">
      <div class="card-title">💪 Ostatni trening siłowy</div>
      <div class="card-name">{hevy_name or '—'}</div>
      <div class="card-date">{d_sila}</div>
      <div>{exs_html}</div>
      {sets_str}
    </div>
    """, unsafe_allow_html=True)

with c_kardio:
    if last_cardio is not None:
        kname  = last_cardio.get("Nazwa", "Aktywność")
        kdist  = n(last_cardio.get("Dystans_km"))
        kczas  = last_cardio.get("Czas", "")
        khr    = n(last_cardio.get("HR_sr"))
        ktempo = last_cardio.get("Tempo_sr", "")
        kvo2   = n(last_cardio.get("VO2max"))
        try:
            kdate = pd.to_datetime(last_cardio.get("_dt") or last_cardio.get("Data")).strftime("%d.%m.%Y")
        except:
            kdate = "—"

        pills = []
        if kdist:  pills.append(f"📍 {kdist:.2f} km")
        if kczas:  pills.append(f"⏱ {kczas}")
        if ktempo: pills.append(f"🏃 {ktempo} /km")
        if khr:    pills.append(f"❤️ {khr:.0f} bpm")
        if kvo2:   pills.append(f"🫁 VO2max {kvo2:.0f}")
        pills_html = "".join(f'<span class="stat-pill">{p}</span>' for p in pills)

        st.markdown(f"""
        <div class="card">
          <div class="card-title">🏃 Ostatni trening kardio</div>
          <div class="card-name">{kname}</div>
          <div class="card-date">{kdate}</div>
          <div class="card-stats">{pills_html}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="card">
          <div class="card-title">🏃 Ostatni trening kardio</div>
          <div style="color:#bbb;margin-top:.5rem">Brak danych</div>
        </div>
        """, unsafe_allow_html=True)




# Footer
st.divider()
st.caption(f"🔄 Odświeża się co 5 min  ·  {datetime.now().strftime('%H:%M:%S')}  ·  Garmin · Fitatu · Hevy")
