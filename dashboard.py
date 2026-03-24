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

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
CREDS_FILE     = os.getenv("GOOGLE_CREDENTIALS", "credentials.json")
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
    width: 130px; height: 130px; border-radius: 50%;
    object-fit: cover; object-position: top;
    border: 4px solid rgba(255,255,255,.15);
    box-shadow: 0 8px 32px rgba(0,0,0,.4);
    flex-shrink: 0;
  }
  .hero-photo-placeholder {
    width: 130px; height: 130px; border-radius: 50%;
    background: rgba(255,255,255,.08); display: flex;
    align-items: center; justify-content: center;
    font-size: 3rem; flex-shrink: 0;
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

# Dziś jako priorytet, wczoraj jako fallback
def pick(col, today_row, yday_row):
    v = n(today_row.get(col)) if today_row is not None else None
    if v is None or v == 0.0:
        v = n(yday_row.get(col)) if yday_row is not None else None
    return v

def pick_row():
    """Zwraca (row, label) — dziś jeśli ma dane, inaczej wczoraj"""
    if row_td is not None and n(row_td.get("Kroki", 0) or 0):
        return row_td, "dziś"
    if row_yd is not None:
        return row_yd, "wczoraj"
    return None, "—"

active_row, active_label = pick_row()

# weight — z arkusza General, komórka E2 (Current Weight)
latest_weight = None
try:
    raw_w = _svc().values().get(
        spreadsheetId=SPREADSHEET_ID, range="General!E2"
    ).execute().get("values", [[]])[0][0]
    latest_weight = n(raw_w)
except Exception:
    pass

# Sen z dziś (Garmin zapisuje sen nocy pod datą przebudzenia = dziś rano)
# Kroki/kalorie z dziś jeśli są, inaczej wczoraj
sleep_h     = n(row_td.get("Sen_h"))     if row_td is not None else n(row_yd.get("Sen_h")     if row_yd is not None else None)
sleep_score = n(row_td.get("Jakos_snu")) if row_td is not None else n(row_yd.get("Jakos_snu") if row_yd is not None else None)
steps       = n(active_row.get("Kroki"))              if active_row is not None else None
kcal_burned = n(active_row.get("Kalorie_calkowite"))  if active_row is not None else None
dist_day    = n(active_row.get("Dystans_dzienny_km")) if active_row is not None else None

# Fitatu — A=Data, B=Kcal — priorytet: dziś → wczoraj → ostatni dostępny
fit_row, kcal_eaten, fit_date_used = None, None, today

if not df_fit.empty:
    df_fit2 = df_fit.copy()
    col_date = df_fit2.columns[0]
    col_kcal = df_fit2.columns[1] if len(df_fit2.columns) > 1 else None
    df_fit2["_dt"] = pd.to_datetime(df_fit2[col_date].astype(str).str.strip().str[:10], errors="coerce")
    df_fit2 = df_fit2.dropna(subset=["_dt"]).sort_values("_dt")
    if not df_fit2.empty:
        r = df_fit2[df_fit2["_dt"].dt.strftime("%Y-%m-%d") == today]   # dziś
        if r.empty:
            r = df_fit2[df_fit2["_dt"].dt.strftime("%Y-%m-%d") == yday]  # wczoraj
        if r.empty:
            r = df_fit2.iloc[[-1]]                                        # ostatni dostępny
        fit_row       = r.iloc[-1]
        fit_date_used = fit_row["_dt"].strftime("%Y-%m-%d")
        if col_kcal:
            kcal_eaten = n(fit_row[col_kcal])

# Products — A=Data, B=Produkt, reszta kolumn opcjonalnie
prods = pd.DataFrame()
if not df_prod.empty:
    col_pd = df_prod.columns[0]   # A — data
    prods = df_prod[df_prod[col_pd].astype(str).str.strip().str[:10] == fit_date_used].copy()

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
#  LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

def sleep_label(s):
    if s is None: return None
    q = "Świetny 🌟" if s >= 85 else "Dobry ✅" if s >= 70 else "Średni ⚠️" if s >= 50 else "Słaby ❌"
    return f"{int(s)}/100 · {q}"

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

# ── MAIN CONTENT wrapper ──────────────────────────────────────────────────────
st.markdown('<div class="main-pad">', unsafe_allow_html=True)

# ── Kalorie ───────────────────────────────────────────────────────────────────
fit_date_label    = datetime.strptime(fit_date_used, "%Y-%m-%d").strftime("%d.%m.%Y") if fit_date_used else "—"
garmin_date_label = datetime.strptime(active_row.get("Data","") if active_row is not None else yday, "%Y-%m-%d").strftime("%d.%m.%Y") if active_row is not None else "—"
garmin_lbl        = "dziś" if (active_row is not None and active_row.get("Data","")[:10] == today) else "wczoraj"
fitatu_lbl        = "dziś" if fit_date_used == today else "wczoraj"
st.markdown(f'<div class="sec">🔥 Kalorie — Garmin: {garmin_date_label} ({garmin_lbl}) · Fitatu: {fit_date_label} ({fitatu_lbl})</div>', unsafe_allow_html=True)
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


# ── Makra ─────────────────────────────────────────────────────────────────────
if fit_row is not None:
    col_b = df_fit.columns[1] if len(df_fit.columns) > 1 else "Kcal"
    col_p = df_fit.columns[2] if len(df_fit.columns) > 2 else "Bialko_g"
    col_t = df_fit.columns[3] if len(df_fit.columns) > 3 else "Tluszcze_g"
    col_w = df_fit.columns[4] if len(df_fit.columns) > 4 else "Wegle_g"
    st.markdown('<div class="sec">🥗 Makro</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("🥩 Białko",      fmt(n(fit_row.get(col_p)),  " g", 0))
    c2.metric("🧈 Tłuszcze",    fmt(n(fit_row.get(col_t)), " g", 0))
    c3.metric("🍞 Węglowodany", fmt(n(fit_row.get(col_w)),   " g", 0))


# ── Co jadłem ─────────────────────────────────────────────────────────────────
st.markdown('<div class="sec">🛒 Co jadłem wczoraj</div>', unsafe_allow_html=True)

if not prods.empty:
    # kolumny po pozycji: A=data(0), B=produkt(1), C+(2+) = opcjonalne (gramy, kcal itd.)
    pcols = list(prods.columns)
    col_name = pcols[1] if len(pcols) > 1 else pcols[0]
    col_gram = pcols[2] if len(pcols) > 2 else None
    col_kcal = pcols[3] if len(pcols) > 3 else None

    rows_html = ""
    total_kcal = 0
    for _, row in prods.iterrows():
        produkt = row[col_name]
        gramy   = row[col_gram] if col_gram else ""
        kcal_v  = row[col_kcal] if col_kcal else ""
        g_fmt   = f"{n(gramy):.0f} g" if n(gramy) else ""
        k_val   = n(kcal_v)
        if k_val: total_kcal += k_val
        k_fmt   = f"{k_val:.0f}" if k_val else ""
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

# ── SIŁOWY ────────────────────────────────────────────────────────────────────
with c_sila:
    d_sila = hevy_date.strftime("%d.%m.%Y") if hevy_date else "—"
    total_sets = sum(e["sets"] for e in hevy_ex_rows)
    total_vol  = sum(
        float(e["vol"].replace(" ","").replace("kg",""))
        for e in hevy_ex_rows if e["vol"]
    ) if hevy_ex_rows else 0

    if hevy_ex_rows:
        ex_rows_html = ""
        for e in hevy_ex_rows:
            ex_rows_html += f"""
            <tr>
              <td style="font-weight:600;color:#111">{e['name']}</td>
              <td style="color:#555;text-align:center">{e['sets']} serie</td>
              <td style="color:#4F46E5;font-weight:600">{e['best']}</td>
              <td style="color:#888">{e['vol']}</td>
            </tr>"""
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
            <thead>
              <tr style="font-size:.7rem;color:#aaa;text-transform:uppercase;letter-spacing:.05em">
                <th style="text-align:left;padding:4px 6px;border-bottom:1px solid #eee">Ćwiczenie</th>
                <th style="text-align:center;padding:4px 6px;border-bottom:1px solid #eee">Serie</th>
                <th style="text-align:left;padding:4px 6px;border-bottom:1px solid #eee">Najlepsza seria</th>
                <th style="text-align:left;padding:4px 6px;border-bottom:1px solid #eee">Objętość</th>
              </tr>
            </thead>
            <tbody style="font-size:.85rem">{ex_rows_html}</tbody>
          </table>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown('<div class="card"><div class="card-title">💪 Ostatni trening siłowy</div><div style="color:#bbb;margin-top:.5rem">Brak danych</div></div>', unsafe_allow_html=True)

# ── KARDIO ─────────────────────────────────────────────────────────────────────
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

        # Główne metryki
        main_pills = ""
        if kdist:   main_pills += pill("📍", f"{kdist:.2f}", " km")
        if kczas:   main_pills += pill("⏱", kczas)
        if kkal:    main_pills += pill("🔥", f"{kkal:.0f}", " kcal")

        # Tempo (tylko bieg/chód)
        tempo_pills = ""
        if is_run:
            if ktempo: tempo_pills += pill("🏃", ktempo, " /km")
            if ktgap:  tempo_pills += pill("⛰️ GAP", ktgap, " /km")
            if ktbest: tempo_pills += pill("⚡", ktbest, " /km best")

        # HR
        hr_pills = ""
        if khr:    hr_pills += pill("❤️ avg", f"{khr:.0f}", " bpm")
        if khrmax: hr_pills += pill("❤️ max", f"{khrmax:.0f}", " bpm")

        # Dynamika (bieg) / Moc (rower)
        dyn_pills = ""
        if kkad:   dyn_pills += pill("🦵 kadencja", f"{kkad:.0f}", " spm")
        if kmoc:   dyn_pills += pill("⚡ moc", f"{kmoc:.0f}", " W")

        # Teren
        ter_pills = ""
        if kwznios: ter_pills += pill("⬆️", f"{kwznios:.0f}", " m")
        if kspadek: ter_pills += pill("⬇️", f"{kspadek:.0f}", " m")
        if ktemp:   ter_pills += pill("🌡️", f"{ktemp:.0f}", "°C")

        # Efekty treningowe
        eff_pills = ""
        if keff_a:  eff_pills += pill("🫀 aerobowy", f"{keff_a:.1f}")
        if keff_b:  eff_pills += pill("💥 beztlenowy", f"{keff_b:.1f}")
        if kvo2:    eff_pills += pill("🫁 VO2max", f"{kvo2:.0f}")
        if kstam:   eff_pills += pill("🔋 stamina", f"{kstam:.0f}", "%")

        def row_section(label, html):
            return f'<div style="margin:.5rem 0 .2rem;font-size:.7rem;color:#aaa;text-transform:uppercase;letter-spacing:.06em">{label}</div><div class="card-stats">{html}</div>' if html.strip() else ""

        # Szukaj trasy GPS
        gps_points = None
        act_id_str = str(last_cardio.get("ID", ""))
        if act_id_str and not df_trasy.empty and "Aktywnosc_ID" in df_trasy.columns:
            match = df_trasy[df_trasy["Aktywnosc_ID"] == act_id_str]
            if not match.empty:
                raw = match.iloc[-1].get("Punkty_JSON", "")
                if raw:
                    try:
                        gps_points = json.loads(raw)
                    except Exception:
                        gps_points = None

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
        </div>
        """, unsafe_allow_html=True)

        # Mapa trasy
        if gps_points and len(gps_points) >= 2:
            lats = [p[0] for p in gps_points]
            lons = [p[1] for p in gps_points]
            clat = sum(lats) / len(lats)
            clon = sum(lons) / len(lons)
            fig_map = go.Figure()
            fig_map.add_trace(go.Scattermapbox(
                lat=lats, lon=lons, mode="lines",
                line=dict(width=3, color="#4F46E5"),
                name="Trasa", hoverinfo="skip",
            ))
            fig_map.add_trace(go.Scattermapbox(
                lat=[lats[0]], lon=[lons[0]], mode="markers",
                marker=dict(size=14, color="#10B981"),
                name="Start",
            ))
            fig_map.add_trace(go.Scattermapbox(
                lat=[lats[-1]], lon=[lons[-1]], mode="markers",
                marker=dict(size=14, color="#EF4444"),
                name="Meta",
            ))
            fig_map.update_layout(
                mapbox_style="open-street-map",
                mapbox=dict(center=dict(lat=clat, lon=clon), zoom=13),
                margin=dict(l=0, r=0, t=0, b=0),
                height=380,
                legend=dict(orientation="h", y=1.02, x=0),
            )
            st.plotly_chart(fig_map, use_container_width=True)
        elif gps_points is None and act_id_str:
            st.caption("🏟️ Brak trasy GPS — bieżnia lub indoor")
    else:
        st.markdown('<div class="card"><div class="card-title">🏃 Ostatni trening kardio</div><div style="color:#bbb;margin-top:.5rem">Brak danych</div></div>', unsafe_allow_html=True)




# ══════════════════════════════════════════════════════════════════════════════
#  HISTORIA
# ══════════════════════════════════════════════════════════════════════════════

CHART_H = 300
DAYS_DEFAULT = 30

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

# ── Przygotuj historyczne dane Dziennik ──────────────────────────────────────
hist_dz = pd.DataFrame()
if not dz.empty:
    hist_dz = dz.copy()
    for col in ["Kroki", "Kalorie_calkowite", "Kalorie_aktywne"]:
        if col in hist_dz.columns:
            hist_dz[col] = hist_dz[col].apply(n)
    hist_dz = hist_dz.sort_values("Data")

# ── Przygotuj historyczne dane Fitatu ────────────────────────────────────────
hist_fit = pd.DataFrame()
if not df_fit.empty:
    hf = df_fit.copy()
    hf.columns = [c.strip() for c in hf.columns]
    col_d = hf.columns[0]
    col_k = hf.columns[1] if len(hf.columns) > 1 else None
    col_b = hf.columns[2] if len(hf.columns) > 2 else None
    col_t = hf.columns[3] if len(hf.columns) > 3 else None
    col_w = hf.columns[4] if len(hf.columns) > 4 else None
    hf["_dt"] = pd.to_datetime(hf[col_d].astype(str).str.strip().str[:10], errors="coerce")
    hf = hf.dropna(subset=["_dt"]).sort_values("_dt")
    hist_fit = hf.rename(columns={
        col_d: "Data", col_k: "Kcal",
        **({"Bialko_g": col_b} if col_b else {}),
        **({"Tluszcze_g": col_t} if col_t else {}),
        **({"Wegle_g": col_w} if col_w else {}),
    })
    if col_k: hist_fit["Kcal"]      = hist_fit["Kcal"].apply(n)
    if col_b: hist_fit[col_b]       = hist_fit[col_b].apply(n)
    if col_t: hist_fit[col_t]       = hist_fit[col_t].apply(n)
    if col_w: hist_fit[col_w]       = hist_fit[col_w].apply(n)
    hist_fit["_dt"] = hf["_dt"]

# Połącz Dziennik + Fitatu po dacie → bilans kalorii
hist_bal = pd.DataFrame()
if not hist_dz.empty and not hist_fit.empty and "Kalorie_calkowite" in hist_dz.columns:
    left  = hist_dz[["Data", "Kalorie_calkowite"]].copy()
    left["_key"] = left["Data"].dt.strftime("%Y-%m-%d")
    right = hist_fit[["_dt", "Kcal"]].copy()
    right["_key"] = right["_dt"].dt.strftime("%Y-%m-%d")
    merged = left.merge(right[["_key","Kcal"]], on="_key", how="inner")
    merged["Bilans"] = merged["Kalorie_calkowite"] - merged["Kcal"]
    hist_bal = merged.sort_values("Data")

# ── Selektor zakresu ──────────────────────────────────────────────────────────
st.markdown('<div class="sec">📈 Historia</div>', unsafe_allow_html=True)
col_r1, col_r2 = st.columns([3, 1])
with col_r2:
    days_range = st.selectbox("Zakres", [7, 14, 30, 60, 90, 180, 365], index=2,
                               format_func=lambda x: f"Ostatnie {x} dni")
cutoff = pd.Timestamp.now() - timedelta(days=days_range)

# ── 1. Kroki ─────────────────────────────────────────────────────────────────
if not hist_dz.empty and "Kroki" in hist_dz.columns:
    df_k = hist_dz[hist_dz["Data"] >= cutoff][["Data","Kroki"]].dropna()
    if not df_k.empty:
        target = 10000
        fig = go.Figure()
        colors = ["#4F46E5" if v >= target else "#F59E0B" for v in df_k["Kroki"]]
        fig.add_trace(go.Bar(
            x=df_k["Data"], y=df_k["Kroki"],
            marker_color=colors, name="Kroki",
            hovertemplate="%{x|%d.%m}: <b>%{y:,.0f}</b> kroków<extra></extra>",
        ))
        fig.add_hline(y=target, line_dash="dot", line_color="#aaa",
                      annotation_text="10 000 cel", annotation_position="top right")
        sparkline_layout(fig, "👟 Historia kroków")
        st.plotly_chart(fig, use_container_width=True)

# ── 2. Bilans kalorii ────────────────────────────────────────────────────────
if not hist_bal.empty:
    df_b = hist_bal[hist_bal["Data"] >= cutoff].copy()
    if not df_b.empty:
        fig2 = go.Figure()
        bar_colors = ["#10B981" if v >= 0 else "#EF4444" for v in df_b["Bilans"]]
        fig2.add_trace(go.Bar(
            x=df_b["Data"], y=df_b["Bilans"],
            marker_color=bar_colors, name="Bilans",
            hovertemplate="%{x|%d.%m}: <b>%{y:+,.0f}</b> kcal<extra></extra>",
        ))
        fig2.add_hline(y=0, line_color="#888", line_width=1)
        sparkline_layout(fig2, "📊 Bilans kalorii (🟢 deficyt / 🔴 nadwyżka)")
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

# ── 3. Historia makro ─────────────────────────────────────────────────────────
if not hist_fit.empty:
    col_b2 = df_fit.columns[2] if len(df_fit.columns) > 2 else None
    col_t2 = df_fit.columns[3] if len(df_fit.columns) > 3 else None
    col_w2 = df_fit.columns[4] if len(df_fit.columns) > 4 else None
    if col_b2 and col_t2 and col_w2:
        df_m = hist_fit[hist_fit["_dt"] >= cutoff].copy()
        df_m = df_m.rename(columns={col_b2: "Bialko", col_t2: "Tluszcze", col_w2: "Wegle"})
        if not df_m.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_m["_dt"], y=df_m["Bialko"],
                name="🥩 Białko", mode="lines", stackgroup="one",
                line=dict(color="#6366F1"), fillcolor="rgba(99,102,241,.25)",
                hovertemplate="%{x|%d.%m}: <b>%{y:.0f} g</b><extra>Białko</extra>"))
            fig.add_trace(go.Scatter(x=df_m["_dt"], y=df_m["Tluszcze"],
                name="🧈 Tłuszcze", mode="lines", stackgroup="one",
                line=dict(color="#F59E0B"), fillcolor="rgba(245,158,11,.25)",
                hovertemplate="%{x|%d.%m}: <b>%{y:.0f} g</b><extra>Tłuszcze</extra>"))
            fig.add_trace(go.Scatter(x=df_m["_dt"], y=df_m["Wegle"],
                name="🍞 Węgle", mode="lines", stackgroup="one",
                line=dict(color="#10B981"), fillcolor="rgba(16,185,129,.25)",
                hovertemplate="%{x|%d.%m}: <b>%{y:.0f} g</b><extra>Węgle</extra>"))
            sparkline_layout(fig, "🥗 Makro dzienne (g)")
            st.plotly_chart(fig, use_container_width=True)

# ── 4. Przeglądarka produktów per dzień ──────────────────────────────────────
st.markdown('<div class="sec">🛒 Co jadłem — historia produktów</div>', unsafe_allow_html=True)

if not df_prod.empty:
    prod2 = df_prod.copy()
    col_pd2 = prod2.columns[0]
    prod2["_dt"] = pd.to_datetime(prod2[col_pd2].astype(str).str.strip().str[:10], errors="coerce")
    prod2 = prod2.dropna(subset=["_dt"]).sort_values("_dt", ascending=False)
    available_dates = sorted(prod2["_dt"].dt.date.unique(), reverse=True)

    if available_dates:
        sel_date = st.selectbox(
            "Wybierz dzień",
            available_dates,
            format_func=lambda d: d.strftime("%A, %d %B %Y"),
        )
        day_prods = prod2[prod2["_dt"].dt.date == sel_date].copy()
        pcols2 = list(day_prods.columns)
        col_pname = pcols2[1] if len(pcols2) > 1 else pcols2[0]
        col_pgram = pcols2[2] if len(pcols2) > 2 else None
        col_pkcal = pcols2[3] if len(pcols2) > 3 else None

        rows_h = ""
        tot = 0
        for _, row in day_prods.iterrows():
            nm = row[col_pname]
            gr = f"{n(row[col_pgram]):.0f} g" if col_pgram and n(row[col_pgram]) else ""
            kv = n(row[col_pkcal]) if col_pkcal else None
            if kv: tot += kv
            kf = f"{kv:.0f}" if kv else ""
            rows_h += f"<tr><td style='font-weight:500;color:#111'>{nm}</td><td style='color:#555'>{gr}</td><td style='color:#E05A2B;font-weight:600'>{kf}</td></tr>"

        # Makro dla wybranego dnia — native Streamlit
        if not hist_fit.empty:
            fd = hist_fit[hist_fit["_dt"].dt.date == sel_date]
            if not fd.empty:
                fit_day_row = fd.iloc[-1]
                cb2 = df_fit.columns[1] if len(df_fit.columns) > 1 else None
                cp2 = df_fit.columns[2] if len(df_fit.columns) > 2 else None
                ct2 = df_fit.columns[3] if len(df_fit.columns) > 3 else None
                cw2 = df_fit.columns[4] if len(df_fit.columns) > 4 else None
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("🔥 Kcal",      fmt(n(fit_day_row.get(cb2)), " kcal", 0))
                mc2.metric("🥩 Białko",     fmt(n(fit_day_row.get(cp2)), " g", 0))
                mc3.metric("🧈 Tłuszcze",   fmt(n(fit_day_row.get(ct2)), " g", 0))
                mc4.metric("🍞 Węglowodany",fmt(n(fit_day_row.get(cw2)), " g", 0))

        # Tabela produktów
        st.markdown(f"""
        <div class="card">
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="font-size:.7rem;color:#aaa;text-transform:uppercase;letter-spacing:.05em">
                <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #eee">Produkt</th>
                <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #eee">Gramy</th>
                <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #eee">Kcal</th>
              </tr>
            </thead>
            <tbody style="font-size:.88rem">{rows_h}</tbody>
          </table>
          <div style="margin-top:.7rem;font-size:.82rem;color:#aaa;text-align:right">
            Łącznie: <b style="color:#E05A2B">{int(tot)} kcal</b> &nbsp;·&nbsp; {len(day_prods)} produktów
          </div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#bbb;font-size:.9rem">Brak danych produktów</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# Footer
st.markdown(f"""
<div style="text-align:center;padding:1.5rem;font-size:.75rem;color:#94A3B8;border-top:1px solid #E2E8F0;margin-top:1rem">
  🔄 Odświeża się co 5 min &nbsp;·&nbsp; {datetime.now().strftime('%H:%M')} &nbsp;·&nbsp; Garmin · Fitatu · Hevy
</div>
""", unsafe_allow_html=True)
