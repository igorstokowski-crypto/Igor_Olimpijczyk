#!/usr/bin/env python3
"""
dashboard.py — Personal health dashboard for Igor
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import date, datetime, timedelta
import os, json
from dotenv import load_dotenv

load_dotenv()

try:
    SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", os.getenv("SPREADSHEET_ID", ""))
except Exception:
    SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS", "credentials.json")
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

st.set_page_config(page_title="Igor · Dashboard", page_icon="🏃", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: #F0F2F6; }
  .block-container { padding: 0 !important; max-width: 100% !important; }
  section[data-testid="stSidebar"] { display: none; }

  /* ── HERO ── */
  .hero {
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 60%, #1e3a5f 100%);
    padding: 2.5rem 3rem 2rem;
    display: flex; align-items: center; gap: 2rem;
    margin-bottom: 0;
  }
  .hero-photo {
    width: 180px; height: 180px; border-radius: 50%;
    object-fit: cover; object-position: top;
    border: 4px solid rgba(255,255,255,.2);
    box-shadow: 0 8px 40px rgba(0,0,0,.5);
    flex-shrink: 0;
  }
  .hero-photo-placeholder {
    width: 180px; height: 180px; border-radius: 50%;
    background: rgba(255,255,255,.08); display: flex;
    align-items: center; justify-content: center;
    font-size: 4rem; flex-shrink: 0;
  }
  .hero-name { font-size: 2.4rem; font-weight: 900; color: #fff; line-height: 1.1; }
  .hero-sub  { font-size: .9rem; color: rgba(255,255,255,.45); margin-top: .2rem; }
  .hero-date { font-size: .82rem; color: rgba(255,255,255,.4); margin-top: .5rem; }
  .hero-stats { display: flex; gap: 2rem; margin-top: 1.2rem; flex-wrap: wrap; }
  .hero-stat-val  { font-size: 1.6rem; font-weight: 800; color: #fff; }
  .hero-stat-lbl  { font-size: .7rem; color: rgba(255,255,255,.4); text-transform: uppercase; letter-spacing: .08em; }

  /* ── MAIN CONTENT ── */
  .main-pad { padding: 1.8rem 3rem; }

  /* ── SECTION HEADER ── */
  .sec {
    font-size: .72rem; font-weight: 700; color: #94A3B8;
    text-transform: uppercase; letter-spacing: .12em;
    margin: 2rem 0 .8rem; display: flex; align-items: center; gap: .5rem;
  }
  .sec::after { content:''; flex:1; height:1px; background:#E2E8F0; }

  /* ── METRIC CARDS ── */
  [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: 800; color: #0F172A; }
  [data-testid="stMetricLabel"] { font-size: .7rem !important; color: #94A3B8 !important; text-transform: uppercase; letter-spacing: .08em; }
  [data-testid="stMetricDelta"] { font-size: .78rem !important; }
  [data-testid="stMetric"] {
    background: #fff; border-radius: 16px;
    padding: 1.1rem 1.3rem !important;
    box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04);
    border: 1px solid #F1F5F9;
  }

  /* ── WORKOUT CARDS ── */
  .card {
    background: #fff; border-radius: 18px; padding: 1.4rem 1.6rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 4px 20px rgba(0,0,0,.05);
    border: 1px solid #F1F5F9; height: 100%;
  }
  .card-title { font-size: .7rem; font-weight: 700; color: #94A3B8; text-transform: uppercase; letter-spacing: .1em; margin-bottom: .5rem; }
  .card-name  { font-size: 1.2rem; font-weight: 800; color: #0F172A; margin-bottom: .2rem; line-height: 1.3; }
  .card-date  { font-size: .78rem; color: #CBD5E1; margin-bottom: 1rem; }
  .card-stats { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .6rem; }
  .stat-pill  { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 20px; padding: 4px 12px; font-size: .8rem; color: #334155; font-weight: 500; }
  .ex-pill    { background: #EEF2FF; color: #4F46E5; border-radius: 20px; padding: 3px 10px; font-size: .78rem; display: inline-block; margin: 2px; font-weight: 600; }

  /* ── PRODUCT TABLE ── */
  .prod-table { width: 100%; border-collapse: collapse; }
  .prod-table th { font-size: .68rem; color: #94A3B8; text-transform: uppercase; letter-spacing: .06em;
                   border-bottom: 2px solid #F1F5F9; padding: 6px 10px; text-align: left; font-weight: 700; }
  .prod-table td { font-size: .9rem; padding: 7px 10px; border-bottom: 1px solid #F8FAFC; color: #1E293B; font-weight: 500; }
  .prod-table td:nth-child(2) { color: #64748B; font-weight: 400; }
  .prod-table td:nth-child(3) { color: #E05A2B; font-weight: 700; }
  .prod-table tr:hover td { background: #F8FAFC; }
  .prod-table tr:last-child td { border-bottom: none; }
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

@st.cache_data(ttl=60, show_spinner=False)
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

today = date.today().strftime("%Y-%m-%d")
yday  = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Load ───────────────────────────────────────────────────────────────────────
with st.spinner(""):
    df_dz    = sheet("Dziennik")
    df_akt   = sheet("Aktywności")
    df_hevy  = sheet("Hevy")
    df_fit   = sheet("Fitatu")
    df_prod  = sheet("FitatuProdukty")
    df_gen   = sheet("General")
    df_trasy = sheet("Trasy")


# ── Dziennik ───────────────────────────────────────────────────────────────────
dz, row_td, row_yd = pd.DataFrame(), None, None
if not df_dz.empty and "Data" in df_dz.columns:
    dz = df_dz.copy()
    dz["Data"] = pd.to_datetime(dz["Data"], errors="coerce")
    dz = dz.sort_values("Data").dropna(subset=["Data"])
    m_td = dz["Data"].dt.strftime("%Y-%m-%d") == today
    m_yd = dz["Data"].dt.strftime("%Y-%m-%d") == yday
    row_td = dz[m_td].iloc[-1] if m_td.any() else None
    row_yd = dz[m_yd].iloc[-1] if m_yd.any() else None

# ── Ustal wspólną datę dla Garmin + Fitatu ─────────────────────────────────────
# Zasada: obie wartości (spalone i spożyte) MUSZĄ być z tego samego dnia.
# 1. Jeśli dziś ma i Garmin (kroki>0) i Fitatu → użyj dziś
# 2. Jeśli jedno źródło nie ma dziś danych → użyj wczoraj dla obu
# 3. Fallback: wczoraj Garmin + ostatni dostępny Fitatu (jeśli brak wczoraj)

garmin_has_today = (row_td is not None)

# Przygotuj Fitatu lookup
fit_row, kcal_eaten, fit_date_used = None, None, yday
df_fit2 = pd.DataFrame()
if not df_fit.empty:
    df_fit2 = df_fit.copy()
    col_date_f = df_fit2.columns[0]
    col_kcal_f = df_fit2.columns[1] if len(df_fit2.columns) > 1 else None
    df_fit2["_dt"] = pd.to_datetime(df_fit2[col_date_f].astype(str).str.strip().str[:10], errors="coerce")
    df_fit2 = df_fit2.dropna(subset=["_dt"]).sort_values("_dt")

fitatu_has_today = (not df_fit2.empty and
                    not df_fit2[df_fit2["_dt"].dt.strftime("%Y-%m-%d") == today].empty)

# Wybierz wspólną datę
if garmin_has_today and fitatu_has_today:
    shared_date = today
    active_row  = row_td
    active_label = "dziś"
elif row_yd is not None:
    shared_date  = yday
    active_row   = row_yd
    active_label = "wczoraj"
else:
    shared_date  = today
    active_row   = row_td
    active_label = "—"

# Fitatu dla wspólnej daty
if not df_fit2.empty:
    col_kcal_f = df_fit2.columns[1] if len(df_fit2.columns) > 1 else None
    r = df_fit2[df_fit2["_dt"].dt.strftime("%Y-%m-%d") == shared_date]
    if r.empty:
        r = df_fit2.iloc[[-1]]   # absolutny fallback — ostatni dostępny
    fit_row       = r.iloc[-1]
    fit_date_used = fit_row["_dt"].strftime("%Y-%m-%d")
    if col_kcal_f:
        kcal_eaten = n(fit_row[col_kcal_f])

# weight — z arkusza General, komórka E2 (Current Weight)
latest_weight = None
try:
    if not df_gen.empty and len(df_gen.columns) >= 5:
        latest_weight = n(df_gen.iloc[0, 4])
except Exception:
    pass

# Sen zawsze z dziś (Garmin zapisuje sen nocy pod datą przebudzenia)
sleep_h     = n(row_td.get("Sen_h"))     if row_td is not None else (n(row_yd.get("Sen_h"))     if row_yd is not None else None)
sleep_score = n(row_td.get("Jakos_snu")) if row_td is not None else (n(row_yd.get("Jakos_snu")) if row_yd is not None else None)

steps       = n(active_row.get("Kroki"))             if active_row is not None else None
kcal_burned = n(active_row.get("Kalorie_calkowite")) if active_row is not None else None
dist_day    = n(active_row.get("Dystans_dzienny_km"))if active_row is not None else None

# Products — z tej samej daty co Fitatu
prods = pd.DataFrame()
if not df_prod.empty:
    col_pd = df_prod.columns[0]
    prods = df_prod[df_prod[col_pd].astype(str).str.strip().str[:10] == fit_date_used].copy()

# Balance — tylko gdy oba z tej samej daty
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

# Last strength — grupuj po ćwiczeniu: serie, max kg, łączna objętość
hevy_name, hevy_date, hevy_duration = None, None, ""
hevy_ex_rows = []   # [{"name":..,"sets":..,"best":..,"vol":..}]

if not df_hevy.empty:
    h = df_hevy.copy()
    dc = "Data_start" if "Data_start" in h.columns else "Data"
    if dc in h.columns:
        h["_dt"] = pd.to_datetime(h[dc], dayfirst=True, errors="coerce")
        h = h.dropna(subset=["_dt"])
        if not h.empty:
            wid = h.sort_values("_dt").iloc[-1].get("ID_treningu")
            wk  = h[h["ID_treningu"] == wid].copy()
            hevy_name     = wk.iloc[-1].get("Trening", "Trening siłowy")
            hevy_date     = wk["_dt"].max()
            hevy_duration = str(wk.iloc[-1].get("Czas_trwania", ""))
            if "Cwiczenie" in wk.columns:
                for ex_name, grp in wk.groupby("Cwiczenie", sort=False):
                    sets  = len(grp)
                    kgs   = grp["KG"].apply(n).dropna()   if "KG"   in grp.columns else pd.Series(dtype=float)
                    reps  = grp["Reps"].apply(n).dropna() if "Reps" in grp.columns else pd.Series(dtype=float)
                    max_kg = kgs.max()  if not kgs.empty  else None
                    # najlepsza seria = max kg × reps dla tego kg
                    best_str = ""
                    if not kgs.empty and not reps.empty:
                        merged = pd.DataFrame({"kg": kgs, "reps": reps}).dropna()
                        if not merged.empty:
                            top = merged.loc[merged["kg"].idxmax()]
                            best_str = f"{top['kg']:.1f} kg × {int(top['reps'])} reps"
                    # objętość = Σ(kg × reps)
                    vol = None
                    if not kgs.empty and not reps.empty:
                        merged2 = pd.DataFrame({"kg":kgs,"reps":reps}).dropna()
                        if not merged2.empty:
                            vol = (merged2["kg"] * merged2["reps"]).sum()
                    hevy_ex_rows.append({
                        "name": ex_name, "sets": sets,
                        "best": best_str,
                        "vol":  f"{vol:,.0f} kg".replace(",", " ") if vol else ""
                    })


# ══════════════════════════════════════════════════════════════════════════════
#  LAYOUT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def sleep_label(s):
    if s is None: return None
    q = "Świetny 🌟" if s >= 85 else "Dobry ✅" if s >= 70 else "Średni ⚠️" if s >= 50 else "Słaby ❌"
    return f"{int(s)}/100 · {q}"

# ── Dodatkowe style dla zakładek ─────────────────────────────────────────────
st.markdown("""
<style>
  /* Tabs */
  [data-testid="stTabs"] { margin-top: 0; }
  [data-testid="stTabsTabList"] {
    background: #fff; border-bottom: 2px solid #E2E8F0;
    padding: 0 3rem; gap: .2rem;
  }
  [data-testid="stTabsTab"] {
    font-size: .82rem; font-weight: 600; color: #94A3B8;
    padding: .7rem 1.2rem; border-radius: 0;
    border-bottom: 2px solid transparent; margin-bottom: -2px;
  }
  [data-testid="stTabsTab"][aria-selected="true"] {
    color: #4F46E5; border-bottom-color: #4F46E5;
  }
  [data-testid="stTabsTabPanel"] { padding-top: 0 !important; }

  /* Record rows */
  .rec-row { display:flex; align-items:center; justify-content:space-between;
             padding:.6rem 0; border-bottom:1px solid #F1F5F9; }
  .rec-row:last-child { border-bottom: none; }
  .rec-name { font-size:.9rem; font-weight:600; color:#1E293B; }
  .rec-val  { font-size:1rem; font-weight:800; color:#4F46E5; }
  .rec-meta { font-size:.75rem; color:#94A3B8; }

  /* Month chart label */
  .month-kpi { background:#fff; border-radius:14px; padding:1rem 1.2rem;
               box-shadow:0 1px 3px rgba(0,0,0,.06); border:1px solid #F1F5F9;
               text-align:center; }
  .month-kpi-val { font-size:1.5rem; font-weight:800; color:#0F172A; }
  .month-kpi-lbl { font-size:.68rem; color:#94A3B8; text-transform:uppercase;
                   letter-spacing:.08em; margin-top:.2rem; }
</style>
""", unsafe_allow_html=True)

# ── HERO ──────────────────────────────────────────────────────────────────────
wt_str    = f"{latest_weight:.1f} kg" if latest_weight else "— kg"
sleep_str = f"{sleep_h:.1f} h" if sleep_h else "—"
sleep_q   = sleep_label(sleep_score) or ""
bal_str   = (("+" if balance > 0 else "") + fmt(balance, " kcal", 0)) if balance is not None else "—"
bal_lbl   = "Deficyt" if (balance or 0) > 0 else "Nadwyżka"

try:
    import base64
    with open("zdj.jpg", "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    photo_html = f'<img class="hero-photo" src="data:image/jpeg;base64,{img_b64}"/>'
except Exception:
    photo_html = '<div class="hero-photo-placeholder">🏃</div>'

st.markdown(f"""
<div class="hero">
  {photo_html}
  <div style="flex:1">
    <div class="hero-name">Igor Stokowski</div>
    <div class="hero-sub">Personal Health Dashboard</div>
    <div class="hero-date">📅 {date.today().strftime('%A, %d %B %Y')}</div>
    <div class="hero-stats">
      <div>
        <div class="hero-stat-val">{wt_str}</div>
        <div class="hero-stat-lbl">Waga · 181 cm</div>
      </div>
      <div style="width:1px;background:rgba(255,255,255,.1)"></div>
      <div>
        <div class="hero-stat-val">{sleep_str}</div>
        <div class="hero-stat-lbl">Sen · {sleep_q}</div>
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  WSPÓLNE DANE DLA WYKRESÓW (przygotowane raz, używane w kilku zakładkach)
# ══════════════════════════════════════════════════════════════════════════════

CHART_H = 300

def sparkline_layout(fig, title=""):
    fig.update_layout(
        height=CHART_H, margin=dict(l=0, r=0, t=28, b=0),
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=True, legend=dict(orientation="h", y=1.15, x=0),
        hovermode="x unified",
        title=dict(text=title, font=dict(size=12, color="#888"), x=0),
        xaxis=dict(showgrid=False, tickformat="%d.%m", tickfont=dict(size=10)),
        yaxis=dict(gridcolor="#f5f5f5", tickfont=dict(size=10)),
    )
    return fig

# Przygotuj historyczne dane Dziennik
hist_dz = pd.DataFrame()
if not dz.empty:
    hist_dz = dz.copy()
    for col in ["Kroki", "Kalorie_calkowite", "Kalorie_aktywne", "Sen_h", "HR_spoczynkowe", "Stres_sr"]:
        if col in hist_dz.columns:
            hist_dz[col] = hist_dz[col].apply(n)
    hist_dz = hist_dz.sort_values("Data")

# Przygotuj historyczne dane Fitatu — normalizuj stare nagłówki
hist_fit = pd.DataFrame()
if not df_fit.empty:
    hf = df_fit.copy()
    hf.columns = [c.strip() for c in hf.columns]
    hf = hf.rename(columns={
        "Dzień":        "Data",
        "Białko (g)":   "Bialko_g",
        "Białko (G)":   "Bialko_g",
        "Tłuszcze (g)": "Tluszcze_g",
        "Tłuszcze (G)": "Tluszcze_g",
        "Węgle (g)":    "Wegle_g",
        "Węgle (G)":    "Wegle_g",
    })
    hf["_dt"] = pd.to_datetime(hf["Data"].astype(str).str.strip().str[:10], errors="coerce")
    hf = hf.dropna(subset=["_dt"]).sort_values("_dt")
    for col in ["Kcal", "Bialko_g", "Tluszcze_g", "Wegle_g"]:
        if col in hf.columns:
            hf[col] = hf[col].apply(n)
    hist_fit = hf

# Bilans kalorii dzień po dniu
hist_bal = pd.DataFrame()
if not hist_dz.empty and not hist_fit.empty and "Kalorie_calkowite" in hist_dz.columns:
    left  = hist_dz[["Data", "Kalorie_calkowite"]].copy()
    left["_key"] = left["Data"].dt.strftime("%Y-%m-%d")
    right = hist_fit[["_dt", "Kcal"]].copy()
    right["_key"] = right["_dt"].dt.strftime("%Y-%m-%d")
    merged = left.merge(right[["_key","Kcal"]], on="_key", how="inner")
    merged["Bilans"] = merged["Kalorie_calkowite"] - merged["Kcal"]
    hist_bal = merged.sort_values("Data")

# ══════════════════════════════════════════════════════════════════════════════
#  TABS NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="main-pad">', unsafe_allow_html=True)
tab_dzis, tab_hist, tab_rekordy, tab_miesiace = st.tabs([
    "📊  Dziś", "📈  Historia", "🏆  Rekordy", "📅  Miesiące"
])

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — DZIŚ
# ══════════════════════════════════════════════════════════════════════════════
with tab_dzis:

    # ── Podsumowanie miesięczne ────────────────────────────────────────────────
    _avail_months = []
    if not dz.empty:
        _avail_months = sorted(dz["Data"].dt.to_period("M").dropna().unique().tolist(), reverse=True)
    if not _avail_months:
        _avail_months = [pd.Period(date.today(), "M")]
    _month_labels  = [str(p) for p in _avail_months]
    _month_display = [pd.Period(p, "M").strftime("%B %Y") for p in _month_labels]

    st.markdown('<div class="sec">📅 Podsumowanie miesięczne</div>', unsafe_allow_html=True)
    _sel_col, _ = st.columns([2, 5])
    with _sel_col:
        _chosen_display = st.selectbox("Miesiąc", _month_display, index=0, label_visibility="collapsed")
    _chosen_ym = _month_labels[_month_display.index(_chosen_display)]

    month_steps = 0
    if not dz.empty and "Kroki" in dz.columns:
        _mdf = dz[dz["Data"].dt.strftime("%Y-%m") == _chosen_ym].copy()
        month_steps = int(_mdf["Kroki"].apply(n).dropna().sum())

    month_km = 0.0
    month_gym = 0
    month_run = month_bike = month_swim = 0

    if not df_hevy.empty:
        _hdf = df_hevy.copy()
        _dc = "Data_start" if "Data_start" in _hdf.columns else "Data"
        if _dc in _hdf.columns:
            _hdf["_dt"] = pd.to_datetime(_hdf[_dc], dayfirst=True, errors="coerce")
            _hdf = _hdf[_hdf["_dt"].dt.strftime("%Y-%m") == _chosen_ym]
            month_gym = _hdf["ID_treningu"].nunique() if "ID_treningu" in _hdf.columns else 0

    if not df_akt.empty and "Data" in df_akt.columns and "Typ" in df_akt.columns:
        _adf = df_akt.copy()
        _adf["_dt"] = pd.to_datetime(_adf["Data"], errors="coerce")
        _adf = _adf[_adf["_dt"].dt.strftime("%Y-%m") == _chosen_ym]
        _typs = _adf["Typ"].str.lower()
        month_run  = int(_typs.isin({"running","trail_running","treadmill_running"}).sum())
        month_bike = int(_typs.isin({"cycling","road_biking","indoor_cycling"}).sum())
        month_swim = int(_typs.isin({"swimming","lap_swimming","open_water_swimming"}).sum())
        if "Dystans_km" in _adf.columns:
            month_km = float(_adf["Dystans_km"].apply(n).dropna().sum())

    month_kardio = month_run + month_bike + month_swim

    cm1, cm2, cm3, cm4, cm5, cm6 = st.columns(6)
    cm1.metric("👟 Kroki",           f"{month_steps:,}".replace(",", " ") if month_steps else "—")
    cm2.metric("🏃 Km aktywności",   f"{month_km:.1f} km" if month_km else "—")
    cm3.metric("💪 Siłownia",        f"{month_gym}×")
    cm4.metric("🏃 Bieganie",        f"{month_run}×")
    cm5.metric("🚴 Rower / 🏊 Basen",f"{month_bike + month_swim}×")
    cm6.metric("🔥 Kardio łącznie",  f"{month_kardio}×")

    # ── Kalorie & Kroki ────────────────────────────────────────────────────────
    shared_date_label = datetime.strptime(shared_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    shared_lbl        = "dziś" if shared_date == today else "wczoraj"
    fitatu_lbl        = shared_lbl  # zawsze ta sama data co Garmin

    st.markdown(f'<div class="sec">🔥 Kalorie — {shared_date_label} ({shared_lbl})</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔥 Spalone",  fmt(kcal_burned, " kcal", 0))
    c2.metric("🥗 Spożyte",  fmt(kcal_eaten,  " kcal", 0) if kcal_eaten else "—")
    if balance is not None:
        lbl   = "📉 Deficyt" if balance > 0 else "📈 Nadwyżka"
        color = "normal"    if balance > 0 else "inverse"
        c3.metric(lbl, fmt(abs(balance), " kcal", 0), delta_color=color)
    else:
        c3.metric("⚡ Bilans", "—")
    c4.metric("👟 Kroki", fmt(steps, "", 0) if steps else "—")

    # ── Makro ──────────────────────────────────────────────────────────────────
    if fit_row is not None and not hist_fit.empty:
        st.markdown('<div class="sec">🥗 Makro</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("🥩 Białko",      fmt(n(fit_row.get("Bialko_g") or fit_row.get("Białko (g)")),  " g", 0))
        c2.metric("🧈 Tłuszcze",    fmt(n(fit_row.get("Tluszcze_g") or fit_row.get("Tłuszcze (G)")), " g", 0))
        c3.metric("🍞 Węglowodany", fmt(n(fit_row.get("Wegle_g") or fit_row.get("Węgle (g)")),   " g", 0))

    # ── Co jadłem ─────────────────────────────────────────────────────────────
    st.markdown(f'<div class="sec">🛒 Co jadłem {fitatu_lbl}</div>', unsafe_allow_html=True)
    if not prods.empty:
        pcols = list(prods.columns)
        col_name = pcols[1] if len(pcols) > 1 else pcols[0]
        col_gram = pcols[2] if len(pcols) > 2 else None
        col_kcal = pcols[3] if len(pcols) > 3 else None
        rows_html = ""
        total_kcal = 0
        for _, row in prods.iterrows():
            produkt = row[col_name]
            g_fmt   = f"{n(row[col_gram]):.0f} g" if col_gram and n(row[col_gram]) else ""
            k_val   = n(row[col_kcal]) if col_kcal else None
            if k_val: total_kcal += k_val
            k_fmt   = f"{k_val:.0f}" if k_val else ""
            rows_html += f"<tr><td>{produkt}</td><td style='color:#888'>{g_fmt}</td><td style='color:#E05A2B;font-weight:600'>{k_fmt}</td></tr>"
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

    # ── Treningi ───────────────────────────────────────────────────────────────
    st.markdown('<div class="sec">🏋️ Ostatnie treningi</div>', unsafe_allow_html=True)
    c_sila, c_kardio = st.columns(2)

    # Siłowy
    with c_sila:
        d_sila    = hevy_date.strftime("%d.%m.%Y") if hevy_date else "—"
        total_sets = sum(e["sets"] for e in hevy_ex_rows)
        total_vol  = sum(float(e["vol"].replace(" ","").replace("kg","")) for e in hevy_ex_rows if e["vol"]) if hevy_ex_rows else 0
        if hevy_ex_rows:
            ex_rows_html = ""
            for e in hevy_ex_rows:
                ex_rows_html += f"""<tr>
                  <td style="font-weight:600;color:#111">{e['name']}</td>
                  <td style="color:#555;text-align:center">{e['sets']} serie</td>
                  <td style="color:#4F46E5;font-weight:600">{e['best']}</td>
                  <td style="color:#888">{e['vol']}</td></tr>"""
            dur_str = f"· ⏱ {hevy_duration}" if hevy_duration else ""
            vol_str = f"{total_vol:,.0f} kg".replace(",", " ") if total_vol else "—"
            st.markdown(f"""
            <div class="card">
              <div class="card-title">💪 Ostatni trening siłowy</div>
              <div class="card-name">{hevy_name or '—'}</div>
              <div class="card-date">{d_sila} {dur_str}</div>
              <div style="display:flex;gap:.5rem;margin:.5rem 0">
                <span class="stat-pill">📊 {total_sets} serii</span>
                <span class="stat-pill">🏋️ {vol_str} objętość</span>
              </div>
              <table style="width:100%;border-collapse:collapse;margin-top:.6rem">
                <thead><tr style="font-size:.7rem;color:#aaa;text-transform:uppercase;letter-spacing:.05em">
                  <th style="text-align:left;padding:4px 6px;border-bottom:1px solid #eee">Ćwiczenie</th>
                  <th style="text-align:center;padding:4px 6px;border-bottom:1px solid #eee">Serie</th>
                  <th style="text-align:left;padding:4px 6px;border-bottom:1px solid #eee">Najlepsza seria</th>
                  <th style="text-align:left;padding:4px 6px;border-bottom:1px solid #eee">Objętość</th>
                </tr></thead>
                <tbody style="font-size:.85rem">{ex_rows_html}</tbody>
              </table>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="card"><div class="card-title">💪 Ostatni trening siłowy</div><div style="color:#bbb;margin-top:.5rem">Brak danych</div></div>', unsafe_allow_html=True)

    # Kardio
    with c_kardio:
        if last_cardio is not None:
            kname   = last_cardio.get("Nazwa", "Aktywność")
            ktyp    = str(last_cardio.get("Typ", "")).lower()
            kdist   = n(last_cardio.get("Dystans_km"))
            kczas   = last_cardio.get("Czas", "")
            khr     = n(last_cardio.get("HR_sr"))
            khrmax  = n(last_cardio.get("HR_max"))
            ktempo  = last_cardio.get("Tempo_sr", "")
            ktgap   = last_cardio.get("Tempo_GAP", "")
            ktbest  = last_cardio.get("Tempo_najlepsze", "")
            kwznios = n(last_cardio.get("Wznios_m"))
            kspadek = n(last_cardio.get("Spadek_m"))
            kkal    = n(last_cardio.get("Kalorie"))
            kvo2    = n(last_cardio.get("VO2max"))
            kmoc    = n(last_cardio.get("Moc_sr_W"))
            kkad    = n(last_cardio.get("Kadencja_sr_spm"))
            keff_a  = n(last_cardio.get("Efekt_aerobowy"))
            keff_b  = n(last_cardio.get("Efekt_beztlenowy"))
            kstam   = n(last_cardio.get("Stamina_koniec_pct"))
            ktemp   = n(last_cardio.get("Temperatura_sr"))
            try:
                kdate = pd.to_datetime(last_cardio.get("_dt") or last_cardio.get("Data")).strftime("%d.%m.%Y")
            except:
                kdate = "—"
            is_run = ktyp in {"running","treadmill_running","trail_running"}

            def pill(icon, val, suf=""):
                return f'<span class="stat-pill">{icon} {val}{suf}</span>' if val else ""

            def row_section(label, html):
                return f'<div style="margin:.5rem 0 .2rem;font-size:.7rem;color:#aaa;text-transform:uppercase;letter-spacing:.06em">{label}</div><div class="card-stats">{html}</div>' if html.strip() else ""

            main_pills  = (pill("📍", f"{kdist:.2f}", " km") if kdist else "") + (pill("⏱", kczas) if kczas else "") + (pill("🔥", f"{kkal:.0f}", " kcal") if kkal else "")
            tempo_pills = (pill("🏃", ktempo, " /km") + pill("⛰️ GAP", ktgap, " /km") + pill("⚡", ktbest, " /km best")) if is_run else ""
            hr_pills    = (pill("❤️ avg", f"{khr:.0f}", " bpm") if khr else "") + (pill("❤️ max", f"{khrmax:.0f}", " bpm") if khrmax else "")
            dyn_pills   = (pill("🦵 kadencja", f"{kkad:.0f}", " spm") if kkad else "") + (pill("⚡ moc", f"{kmoc:.0f}", " W") if kmoc else "")
            ter_pills   = (pill("⬆️", f"{kwznios:.0f}", " m") if kwznios else "") + (pill("⬇️", f"{kspadek:.0f}", " m") if kspadek else "") + (pill("🌡️", f"{ktemp:.0f}", "°C") if ktemp else "")
            eff_pills   = (pill("🫀 aerobowy", f"{keff_a:.1f}") if keff_a else "") + (pill("💥 beztlenowy", f"{keff_b:.1f}") if keff_b else "") + (pill("🫁 VO2max", f"{kvo2:.0f}") if kvo2 else "") + (pill("🔋 stamina", f"{kstam:.0f}", "%") if kstam else "")

            # GPS
            gps_points = None
            act_id_str = str(last_cardio.get("ID", ""))
            if act_id_str and not df_trasy.empty and "Aktywnosc_ID" in df_trasy.columns:
                match = df_trasy[df_trasy["Aktywnosc_ID"] == act_id_str]
                if not match.empty:
                    raw = match.iloc[-1].get("Punkty_JSON", "")
                    if raw:
                        try: gps_points = json.loads(raw)
                        except: pass

            st.markdown(f"""
            <div class="card">
              <div class="card-title">🏃 Ostatni trening kardio</div>
              <div class="card-name">{kname}</div>
              <div class="card-date">{kdate}</div>
              <div class="card-stats">{main_pills}</div>
              {row_section("Tempo", tempo_pills)}
              {row_section("Tętno", hr_pills)}
              {row_section("Dynamika", dyn_pills)}
              {row_section("Teren", ter_pills)}
              {row_section("Efekty treningowe", eff_pills)}
            </div>""", unsafe_allow_html=True)

            if gps_points and len(gps_points) >= 2:
                lats = [p[0] for p in gps_points]
                lons = [p[1] for p in gps_points]
                clat, clon = sum(lats)/len(lats), sum(lons)/len(lons)
                fig_map = go.Figure()
                fig_map.add_trace(go.Scattermapbox(lat=lats, lon=lons, mode="lines", line=dict(width=3, color="#4F46E5"), name="Trasa", hoverinfo="skip"))
                fig_map.add_trace(go.Scattermapbox(lat=[lats[0]], lon=[lons[0]], mode="markers", marker=dict(size=14, color="#10B981"), name="Start"))
                fig_map.add_trace(go.Scattermapbox(lat=[lats[-1]], lon=[lons[-1]], mode="markers", marker=dict(size=14, color="#EF4444"), name="Meta"))
                fig_map.update_layout(mapbox_style="open-street-map", mapbox=dict(center=dict(lat=clat, lon=clon), zoom=13),
                                      margin=dict(l=0,r=0,t=0,b=0), height=380, legend=dict(orientation="h", y=1.02, x=0))
                st.plotly_chart(fig_map, use_container_width=True)
            elif gps_points is None and act_id_str:
                st.caption("🏟️ Brak trasy GPS — bieżnia lub indoor")
        else:
            st.markdown('<div class="card"><div class="card-title">🏃 Ostatni trening kardio</div><div style="color:#bbb;margin-top:.5rem">Brak danych</div></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — HISTORIA
# ══════════════════════════════════════════════════════════════════════════════
with tab_hist:
    col_r1, col_r2 = st.columns([4, 1])
    with col_r2:
        days_range = st.selectbox("Zakres", [7, 14, 30, 60, 90, 180, 365], index=2,
                                   format_func=lambda x: f"Ostatnie {x} dni", key="hist_range")
    cutoff = pd.Timestamp.now() - timedelta(days=days_range)

    # 1. Kroki
    if not hist_dz.empty and "Kroki" in hist_dz.columns:
        df_k = hist_dz[hist_dz["Data"] >= cutoff][["Data","Kroki"]].dropna()
        if not df_k.empty:
            target = 10000
            fig = go.Figure()
            colors = ["#4F46E5" if v >= target else "#F59E0B" for v in df_k["Kroki"]]
            fig.add_trace(go.Bar(x=df_k["Data"], y=df_k["Kroki"], marker_color=colors, name="Kroki",
                hovertemplate="%{x|%d.%m}: <b>%{y:,.0f}</b> kroków<extra></extra>"))
            fig.add_hline(y=target, line_dash="dot", line_color="#aaa",
                          annotation_text="10 000 cel", annotation_position="top right")
            sparkline_layout(fig, "👟 Historia kroków")
            st.plotly_chart(fig, use_container_width=True)

    # 2. Bilans kalorii
    if not hist_bal.empty:
        df_b = hist_bal[hist_bal["Data"] >= cutoff].copy()
        if not df_b.empty:
            fig2 = go.Figure()
            bar_colors = ["#10B981" if v >= 0 else "#EF4444" for v in df_b["Bilans"]]
            fig2.add_trace(go.Bar(x=df_b["Data"], y=df_b["Bilans"], marker_color=bar_colors, name="Bilans",
                hovertemplate="%{x|%d.%m}: <b>%{y:+,.0f}</b> kcal<extra></extra>"))
            fig2.add_hline(y=0, line_color="#888", line_width=1)
            sparkline_layout(fig2, "📊 Bilans kalorii (🟢 deficyt / 🔴 nadwyżka)")
            fig2.update_layout(showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

    # 3. Sen + HR w dwóch kolumnach
    ch1, ch2 = st.columns(2)
    with ch1:
        if not hist_dz.empty and "Sen_h" in hist_dz.columns:
            df_sen = hist_dz[hist_dz["Data"] >= cutoff][["Data","Sen_h"]].dropna()
            if not df_sen.empty:
                fig_s = go.Figure()
                fig_s.add_trace(go.Scatter(x=df_sen["Data"], y=df_sen["Sen_h"], mode="lines+markers",
                    line=dict(color="#6366F1", width=2), marker=dict(size=4),
                    hovertemplate="%{x|%d.%m}: <b>%{y:.1f} h</b><extra>Sen</extra>"))
                fig_s.add_hline(y=7, line_dash="dot", line_color="#10B981",
                                annotation_text="7h cel", annotation_position="top right")
                sparkline_layout(fig_s, "😴 Historia snu (h)")
                fig_s.update_layout(showlegend=False)
                st.plotly_chart(fig_s, use_container_width=True)
    with ch2:
        if not hist_dz.empty and "HR_spoczynkowe" in hist_dz.columns:
            df_hr = hist_dz[hist_dz["Data"] >= cutoff][["Data","HR_spoczynkowe"]].dropna()
            df_hr = df_hr[df_hr["HR_spoczynkowe"] > 0]
            if not df_hr.empty:
                fig_hr = go.Figure()
                fig_hr.add_trace(go.Scatter(x=df_hr["Data"], y=df_hr["HR_spoczynkowe"], mode="lines+markers",
                    line=dict(color="#EF4444", width=2), marker=dict(size=4),
                    hovertemplate="%{x|%d.%m}: <b>%{y:.0f} bpm</b><extra>HR spocz.</extra>"))
                sparkline_layout(fig_hr, "❤️ HR spoczynkowe (bpm)")
                fig_hr.update_layout(showlegend=False)
                st.plotly_chart(fig_hr, use_container_width=True)

    # 4. Historia makro
    if not hist_fit.empty and "Bialko_g" in hist_fit.columns:
        df_m = hist_fit[hist_fit["_dt"] >= cutoff].copy()
        if not df_m.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_m["_dt"], y=df_m["Bialko_g"],
                name="🥩 Białko", mode="lines", stackgroup="one",
                line=dict(color="#6366F1"), fillcolor="rgba(99,102,241,.25)",
                hovertemplate="%{x|%d.%m}: <b>%{y:.0f} g</b><extra>Białko</extra>"))
            if "Tluszcze_g" in df_m.columns:
                fig.add_trace(go.Scatter(x=df_m["_dt"], y=df_m["Tluszcze_g"],
                    name="🧈 Tłuszcze", mode="lines", stackgroup="one",
                    line=dict(color="#F59E0B"), fillcolor="rgba(245,158,11,.25)",
                    hovertemplate="%{x|%d.%m}: <b>%{y:.0f} g</b><extra>Tłuszcze</extra>"))
            if "Wegle_g" in df_m.columns:
                fig.add_trace(go.Scatter(x=df_m["_dt"], y=df_m["Wegle_g"],
                    name="🍞 Węgle", mode="lines", stackgroup="one",
                    line=dict(color="#10B981"), fillcolor="rgba(16,185,129,.25)",
                    hovertemplate="%{x|%d.%m}: <b>%{y:.0f} g</b><extra>Węgle</extra>"))
            sparkline_layout(fig, "🥗 Makro dzienne (g)")
            st.plotly_chart(fig, use_container_width=True)

    # 5. Historia produktów
    st.markdown('<div class="sec">🛒 Co jadłem — historia</div>', unsafe_allow_html=True)
    if not df_prod.empty:
        prod2 = df_prod.copy()
        col_pd2 = prod2.columns[0]
        prod2["_dt"] = pd.to_datetime(prod2[col_pd2].astype(str).str.strip().str[:10], errors="coerce")
        prod2 = prod2.dropna(subset=["_dt"]).sort_values("_dt", ascending=False)
        available_dates = sorted(prod2["_dt"].dt.date.unique(), reverse=True)
        if available_dates:
            sel_date = st.selectbox("Wybierz dzień", available_dates,
                format_func=lambda d: d.strftime("%A, %d %B %Y"), key="prod_date")
            day_prods = prod2[prod2["_dt"].dt.date == sel_date].copy()
            pcols2 = list(day_prods.columns)
            col_pname = pcols2[1] if len(pcols2) > 1 else pcols2[0]
            col_pgram = pcols2[2] if len(pcols2) > 2 else None
            col_pkcal = pcols2[3] if len(pcols2) > 3 else None
            # Makro tego dnia
            if not hist_fit.empty:
                fd = hist_fit[hist_fit["_dt"].dt.date == sel_date]
                if not fd.empty:
                    fdr = fd.iloc[-1]
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("🔥 Kcal",      fmt(n(fdr.get("Kcal")),       " kcal", 0))
                    mc2.metric("🥩 Białko",     fmt(n(fdr.get("Bialko_g")),   " g", 0))
                    mc3.metric("🧈 Tłuszcze",   fmt(n(fdr.get("Tluszcze_g")), " g", 0))
                    mc4.metric("🍞 Węglowodany",fmt(n(fdr.get("Wegle_g")),    " g", 0))
            rows_h, tot = "", 0
            for _, row in day_prods.iterrows():
                nm = row[col_pname]
                gr = f"{n(row[col_pgram]):.0f} g" if col_pgram and n(row[col_pgram]) else ""
                kv = n(row[col_pkcal]) if col_pkcal else None
                if kv: tot += kv
                kf = f"{kv:.0f}" if kv else ""
                rows_h += f"<tr><td style='font-weight:500;color:#111'>{nm}</td><td style='color:#555'>{gr}</td><td style='color:#E05A2B;font-weight:600'>{kf}</td></tr>"
            st.markdown(f"""
            <div class="card">
              <table style="width:100%;border-collapse:collapse">
                <thead><tr style="font-size:.7rem;color:#aaa;text-transform:uppercase;letter-spacing:.05em">
                  <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #eee">Produkt</th>
                  <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #eee">Gramy</th>
                  <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #eee">Kcal</th>
                </tr></thead>
                <tbody style="font-size:.88rem">{rows_h}</tbody>
              </table>
              <div style="margin-top:.7rem;font-size:.82rem;color:#aaa;text-align:right">
                Łącznie: <b style="color:#E05A2B">{int(tot)} kcal</b> &nbsp;·&nbsp; {len(day_prods)} produktów
              </div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — REKORDY
# ══════════════════════════════════════════════════════════════════════════════
with tab_rekordy:
    rec_l, rec_r = st.columns(2)

    # ── Rekordy biegowe ────────────────────────────────────────────────────────
    with rec_l:
        st.markdown('<div class="sec">🏃 Bieganie — rekordy</div>', unsafe_allow_html=True)
        RUNNING_T = {"running","treadmill_running","trail_running"}
        if not df_akt.empty and "Typ" in df_akt.columns:
            biegi = df_akt[df_akt["Typ"].str.lower().isin(RUNNING_T)].copy()
            for col in ["Dystans_km","HR_sr","Wznios_m"]:
                if col in biegi.columns: biegi[col] = biegi[col].apply(n)

            def rec_row_html(label, val, date_str="", detail=""):
                return f"""<div class="rec-row">
                  <div><div class="rec-name">{label}</div><div class="rec-meta">{date_str} {detail}</div></div>
                  <div class="rec-val">{val}</div></div>"""

            if len(biegi) > 0:
                html = ""
                if "Dystans_km" in biegi.columns:
                    idx = biegi["Dystans_km"].idxmax()
                    r = biegi.loc[idx]
                    html += rec_row_html("Najdłuższy bieg", f"{r['Dystans_km']:.2f} km",
                                         str(r.get("Data",""))[:10], str(r.get("Nazwa","")))
                if "Tempo_sr" in biegi.columns:
                    bt = biegi[biegi["Tempo_sr"].astype(str).str.contains(":")]
                    if len(bt):
                        bt["_s"] = bt["Tempo_sr"].astype(str).apply(
                            lambda t: sum(int(x)*(60**i) for i,x in enumerate(reversed(t.split(":")))))
                        idx = bt["_s"].idxmin()
                        r = bt.loc[idx]
                        html += rec_row_html("Najszybsze tempo", r["Tempo_sr"]+" /km",
                                             str(r.get("Data",""))[:10], f"{r.get('Dystans_km',0):.2f} km")
                if "Wznios_m" in biegi.columns:
                    idx = biegi["Wznios_m"].idxmax()
                    r = biegi.loc[idx]
                    html += rec_row_html("Największe wzniesienie", f"{r['Wznios_m']:.0f} m",
                                         str(r.get("Data",""))[:10], f"{r.get('Dystans_km',0):.2f} km")
                # PB per dystans
                for prog, label in [(5,"5 km+"),(10,"10 km+"),(21,"Półmaraton+"),(42,"Maraton+")]:
                    kand = biegi[biegi["Dystans_km"] >= prog] if "Dystans_km" in biegi.columns else pd.DataFrame()
                    if len(kand) and "Tempo_sr" in kand.columns:
                        kt = kand[kand["Tempo_sr"].astype(str).str.contains(":")]
                        if len(kt):
                            kt = kt.copy()
                            kt["_s"] = kt["Tempo_sr"].astype(str).apply(
                                lambda t: sum(int(x)*(60**i) for i,x in enumerate(reversed(t.split(":")))))
                            idx = kt["_s"].idxmin()
                            r = kt.loc[idx]
                            html += rec_row_html(f"Najszybsze {label}", r["Tempo_sr"]+" /km",
                                                 str(r.get("Data",""))[:10], f"{r.get('Dystans_km',0):.2f} km")
                st.markdown(f'<div class="card">{html}</div>', unsafe_allow_html=True)
                # Podsumowanie liczbowe
                st.markdown('<div style="height:.5rem"></div>', unsafe_allow_html=True)
                rb1, rb2, rb3 = st.columns(3)
                rb1.metric("Łącznie biegów",    f"{len(biegi)}")
                rb2.metric("Łączny dystans",    f"{biegi['Dystans_km'].sum():.1f} km" if "Dystans_km" in biegi.columns else "—")
                rb3.metric("Łączne wzniesienie",f"{biegi['Wznios_m'].sum():.0f} m" if "Wznios_m" in biegi.columns else "—")
        else:
            st.info("Brak danych biegowych")

    # ── Rekordy siłowe ─────────────────────────────────────────────────────────
    with rec_r:
        st.markdown('<div class="sec">💪 Siłownia — max ciężar</div>', unsafe_allow_html=True)
        if not df_hevy.empty and "Cwiczenie" in df_hevy.columns and "KG" in df_hevy.columns:
            hv = df_hevy.copy()
            hv["KG"]   = hv["KG"].apply(n)
            hv["Reps"] = hv["Reps"].apply(n) if "Reps" in hv.columns else 0
            hv = hv.dropna(subset=["KG"])
            hv = hv[hv["KG"] > 0]
            top = hv.groupby("Cwiczenie")["KG"].max().dropna()
            top = top[top > 0].sort_values(ascending=False)
            # Szukaj w polu tekstowym
            search = st.text_input("🔍 Szukaj ćwiczenia", placeholder="np. Bench Press...", key="rec_search")
            if search:
                top = top[top.index.str.lower().str.contains(search.lower())]
            html = ""
            for cwicz, max_kg in top.items():
                best = hv[(hv["Cwiczenie"] == cwicz) & (hv["KG"] == max_kg)].iloc[0]
                _rv = n(best.get("Reps"))
                reps_str = f"× {int(_rv)} reps" if _rv and _rv > 0 else ""
                dc = "Data_start" if "Data_start" in hv.columns else "Data"
                date_str = str(best.get(dc,""))[:10]
                html += f"""<div class="rec-row">
                  <div><div class="rec-name">{cwicz}</div><div class="rec-meta">{date_str}</div></div>
                  <div class="rec-val">{max_kg:.1f} kg {reps_str}</div></div>"""
            st.markdown(f'<div class="card" style="max-height:520px;overflow-y:auto">{html}</div>', unsafe_allow_html=True)
            # Podsumowanie
            st.markdown('<div style="height:.5rem"></div>', unsafe_allow_html=True)
            sh1, sh2 = st.columns(2)
            dc2 = "Data_start" if "Data_start" in hv.columns else "Data"
            unique_sess = df_hevy["ID_treningu"].nunique() if "ID_treningu" in df_hevy.columns else 0
            sh1.metric("Łącznie sesji", f"{unique_sess}")
            sh2.metric("Łącznie serii", f"{len(df_hevy)}")
        else:
            st.info("Brak danych siłowych")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — MIESIĄCE
# ══════════════════════════════════════════════════════════════════════════════
with tab_miesiace:
    # Oblicz miesięczne agregacje
    month_rows = []
    if not hist_dz.empty:
        dz_m = hist_dz.copy()
        dz_m["M"] = dz_m["Data"].dt.to_period("M")
        for m, grp in dz_m.groupby("M"):
            row = {"Miesiąc": str(m)}
            if "Kroki" in grp.columns:
                row["Kroki suma"]    = int(grp["Kroki"].dropna().sum())
                row["Kroki śr/dzień"]= round(grp["Kroki"].dropna().mean())
            if "Sen_h" in grp.columns:
                row["Sen śr (h)"]    = round(grp["Sen_h"].dropna().mean(), 2)
            if "HR_spoczynkowe" in grp.columns:
                hr_vals = grp["HR_spoczynkowe"].dropna()
                hr_vals = hr_vals[hr_vals > 0]
                row["HR spocz. śr"]  = round(hr_vals.mean(), 1) if len(hr_vals) else 0
            if "Intensywne_min" in grp.columns:
                row["Intens. min"]   = int(grp["Intensywne_min"].dropna().sum())
            month_rows.append(row)

    if not hist_fit.empty:
        fit_m = hist_fit.copy()
        fit_m["M"] = fit_m["_dt"].dt.to_period("M")
        for m, grp in fit_m.groupby("M"):
            ms = str(m)
            existing = next((r for r in month_rows if r["Miesiąc"] == ms), None)
            if not existing:
                existing = {"Miesiąc": ms}
                month_rows.append(existing)
            if "Kcal" in grp.columns:
                existing["Kcal śr/dzień"] = round(grp["Kcal"].dropna().mean())

    if not df_akt.empty and "Data" in df_akt.columns and "Typ" in df_akt.columns:
        akt_m = df_akt.copy()
        akt_m["_dt2"] = pd.to_datetime(akt_m["Data"], errors="coerce")
        akt_m["M"] = akt_m["_dt2"].dt.to_period("M")
        for m, grp in akt_m.groupby("M"):
            ms = str(m)
            existing = next((r for r in month_rows if r["Miesiąc"] == ms), None)
            if not existing:
                existing = {"Miesiąc": ms}
                month_rows.append(existing)
            typs = grp["Typ"].str.lower()
            existing["Biegi"]   = int(typs.isin({"running","trail_running","treadmill_running"}).sum())
            existing["Kardio"]  = int(typs.isin({"running","trail_running","treadmill_running","cycling","road_cycling","indoor_cycling","swimming","lap_swimming","open_water_swimming","walking","hiking"}).sum())
            if "Dystans_km" in grp.columns:
                existing["Km łącznie"] = round(float(grp["Dystans_km"].apply(n).dropna().sum()), 1)

    if not df_hevy.empty and "ID_treningu" in df_hevy.columns:
        hv_m = df_hevy.copy()
        dc = "Data_start" if "Data_start" in hv_m.columns else "Data"
        if dc in hv_m.columns:
            hv_m["_dt2"] = pd.to_datetime(hv_m[dc], errors="coerce")
            hv_m["M"] = hv_m["_dt2"].dt.to_period("M")
            for m, grp in hv_m.groupby("M"):
                ms = str(m)
                existing = next((r for r in month_rows if r["Miesiąc"] == ms), None)
                if not existing:
                    existing = {"Miesiąc": ms}
                    month_rows.append(existing)
                existing["Siłownia"] = grp["ID_treningu"].nunique()

    df_months = pd.DataFrame(sorted(month_rows, key=lambda x: x["Miesiąc"]))

    if not df_months.empty:
        # KPI ostatni pełny miesiąc
        last_full = df_months.iloc[-2] if len(df_months) > 1 else df_months.iloc[-1]
        curr = df_months.iloc[-1]
        lbl_curr = pd.Period(curr["Miesiąc"], "M").strftime("%B %Y")
        st.markdown(f'<div class="sec">📅 Bieżący miesiąc — {lbl_curr}</div>', unsafe_allow_html=True)
        mk1, mk2, mk3, mk4, mk5, mk6 = st.columns(6)
        mk1.metric("👟 Kroki",        f"{int(curr.get('Kroki suma',0)):,}".replace(",", " ") if curr.get("Kroki suma") else "—",
                   delta=f"{int(curr.get('Kroki suma',0)) - int(last_full.get('Kroki suma',0)):+,}".replace(",", " ") + " vs prev")
        mk2.metric("🏃 Km",           f"{curr.get('Km łącznie', 0):.1f} km" if curr.get("Km łącznie") else "—")
        mk3.metric("💪 Siłownia",     f"{int(curr.get('Siłownia',0))}×" if curr.get("Siłownia") else "—")
        mk4.metric("🏃 Biegi",        f"{int(curr.get('Biegi',0))}×" if curr.get("Biegi") else "—")
        mk5.metric("🔥 Kardio łącz.", f"{int(curr.get('Kardio',0))}×" if curr.get("Kardio") else "—")
        mk6.metric("🥗 Kcal śr",      f"{int(curr.get('Kcal śr/dzień',0))} kcal" if curr.get("Kcal śr/dzień") else "—")

        # Wykres kroków per miesiąc
        st.markdown('<div class="sec">📊 Porównanie miesięcy</div>', unsafe_allow_html=True)
        ch_a, ch_b = st.columns(2)
        with ch_a:
            if "Kroki suma" in df_months.columns:
                df_plot = df_months[df_months["Kroki suma"] > 0].tail(12)
                if not df_plot.empty:
                    fig_km = go.Figure(go.Bar(
                        x=df_plot["Miesiąc"], y=df_plot["Kroki suma"],
                        marker_color="#4F46E5",
                        hovertemplate="%{x}: <b>%{y:,.0f}</b> kroków<extra></extra>"))
                    sparkline_layout(fig_km, "👟 Kroki per miesiąc")
                    fig_km.update_layout(showlegend=False)
                    st.plotly_chart(fig_km, use_container_width=True)
        with ch_b:
            if "Km łącznie" in df_months.columns:
                df_plot2 = df_months[df_months["Km łącznie"] > 0].tail(12)
                if not df_plot2.empty:
                    fig_km2 = go.Figure(go.Bar(
                        x=df_plot2["Miesiąc"], y=df_plot2["Km łącznie"],
                        marker_color="#10B981",
                        hovertemplate="%{x}: <b>%{y:.1f} km</b><extra></extra>"))
                    sparkline_layout(fig_km2, "🏃 Km biegania per miesiąc")
                    fig_km2.update_layout(showlegend=False)
                    st.plotly_chart(fig_km2, use_container_width=True)

        ch_c, ch_d = st.columns(2)
        with ch_c:
            act_cols = [c for c in ["Siłownia", "Biegi", "Kardio"] if c in df_months.columns]
            if act_cols:
                df_plot3 = df_months.tail(12)
                fig_act = go.Figure()
                colors_act = {"Siłownia": "#4F46E5", "Biegi": "#F59E0B", "Kardio": "#EF4444"}
                for col in act_cols:
                    fig_act.add_trace(go.Bar(x=df_plot3["Miesiąc"], y=df_plot3[col],
                        name=col, marker_color=colors_act.get(col, "#888")))
                fig_act.update_layout(barmode="group")
                sparkline_layout(fig_act, "🏋️ Treningi per miesiąc")
                st.plotly_chart(fig_act, use_container_width=True)
        with ch_d:
            if "Sen śr (h)" in df_months.columns:
                df_plot4 = df_months[df_months["Sen śr (h)"] > 0].tail(12)
                if not df_plot4.empty:
                    fig_sen = go.Figure(go.Scatter(
                        x=df_plot4["Miesiąc"], y=df_plot4["Sen śr (h)"],
                        mode="lines+markers", line=dict(color="#6366F1", width=2),
                        marker=dict(size=6),
                        hovertemplate="%{x}: <b>%{y:.2f} h</b><extra>Sen śr</extra>"))
                    fig_sen.add_hline(y=7, line_dash="dot", line_color="#10B981",
                                     annotation_text="7h", annotation_position="top right")
                    sparkline_layout(fig_sen, "😴 Średni sen per miesiąc (h)")
                    fig_sen.update_layout(showlegend=False)
                    st.plotly_chart(fig_sen, use_container_width=True)

        # Tabela miesięcy
        st.markdown('<div class="sec">📋 Tabela miesięcy</div>', unsafe_allow_html=True)
        display_cols = [c for c in ["Miesiąc","Kroki suma","Kroki śr/dzień","Km łącznie",
                                     "Biegi","Siłownia","Kardio","Kcal śr/dzień",
                                     "Sen śr (h)","HR spocz. śr","Intens. min"] if c in df_months.columns]
        df_show = df_months[display_cols].iloc[::-1].reset_index(drop=True).copy()
        # Konwertuj wszystko na str — najsafe dla PyArrow (brak OverflowError z dużych int)
        df_show = df_show.astype(str).replace("nan", "—").replace("<NA>", "—").replace("None", "—")
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.info("Brak danych miesięcznych")

st.markdown('</div>', unsafe_allow_html=True)

# Footer
st.markdown(f"""
<div style="text-align:center;padding:1.5rem;font-size:.75rem;color:#94A3B8;border-top:1px solid #E2E8F0;margin-top:1rem">
  🔄 Odświeża się automatycznie &nbsp;·&nbsp; {datetime.now().strftime('%H:%M')} &nbsp;·&nbsp; Garmin · Fitatu · Hevy
</div>
""", unsafe_allow_html=True)
