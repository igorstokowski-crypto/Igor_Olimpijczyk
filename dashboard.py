#!/usr/bin/env python3
"""
dashboard.py — Personal health dashboard for Igor
Reads live from Google Sheets (Dziennik, Aktywności, Hevy, Fitatu, FitatuProdukty)
Run locally:   streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import date, datetime, timedelta
import os, json
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
HEIGHT_CM      = 181
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
CREDS_FILE     = os.getenv("GOOGLE_CREDENTIALS", "credentials.json")
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

st.set_page_config(page_title="Igor · Dashboard", page_icon="🏃", layout="wide")

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
  .block-container { padding: 1.5rem 2.5rem 2rem; }
  [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: 700; }
  [data-testid="stMetricLabel"] { font-size: 0.8rem !important; color: #888 !important; text-transform: uppercase; letter-spacing: .05em; }
  [data-testid="stMetricDelta"] { font-size: 0.85rem !important; }
  div[data-testid="column"] > div { gap: 0.5rem; }
  .section-title { font-size: 1rem; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: .08em; margin: 1.5rem 0 .5rem; border-bottom: 1px solid #eee; padding-bottom: .4rem; }
  .workout-card { background: #fafafa; border: 1px solid #eee; border-radius: 12px; padding: 1rem 1.2rem; height: 100%; }
  .workout-card h4 { margin: 0 0 .3rem; font-size: 1rem; }
  .workout-card .date { color: #aaa; font-size: 0.8rem; margin-bottom: .6rem; }
  .workout-card .pill { display: inline-block; background: #f0f0f0; border-radius: 20px; padding: 2px 10px; font-size: 0.8rem; margin: 2px; }
  .workout-card .stat { font-size: 0.88rem; color: #444; margin-top: .5rem; }
  .product-row td { font-size: 0.88rem !important; }
</style>
""", unsafe_allow_html=True)


# ── Google Sheets ─────────────────────────────────────────────────────────────
@st.cache_resource
def _sheets_svc():
    try:
        raw = st.secrets["GOOGLE_CREDENTIALS_JSON"]
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds).spreadsheets()

@st.cache_data(ttl=300, show_spinner=False)
def read_sheet(tab: str) -> pd.DataFrame:
    try:
        result = _sheets_svc().values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A:ZZ"
        ).execute()
        rows = result.get("values", [])
        if len(rows) < 2:
            return pd.DataFrame()
        max_cols = len(rows[0])
        data = [r + [""] * (max_cols - len(r)) for r in rows[1:]]
        return pd.DataFrame(data, columns=rows[0])
    except Exception as e:
        st.warning(f"Nie udało się załadować zakładki '{tab}': {e}")
        return pd.DataFrame()


# ── Helpers ───────────────────────────────────────────────────────────────────
def num(val, default=None):
    try:
        return float(str(val).replace(",", ".").strip())
    except Exception:
        return default

def fmt_num(val, suffix="", decimals=0):
    if val is None:
        return "—"
    return f"{val:,.{decimals}f}{suffix}".replace(",", " ")

yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
today_str     = date.today().strftime("%Y-%m-%d")


# ── Load all sheets ───────────────────────────────────────────────────────────
with st.spinner("Ładowanie danych…"):
    df_dz   = read_sheet("Dziennik")
    df_akt  = read_sheet("Aktywności")
    df_hevy = read_sheet("Hevy")
    df_fit  = read_sheet("Fitatu")
    df_prod = read_sheet("FitatuProdukty")


# ── Dziennik processing ───────────────────────────────────────────────────────
dz = pd.DataFrame()
row_yday = None
if not df_dz.empty and "Data" in df_dz.columns:
    dz = df_dz.copy()
    dz["Data"] = pd.to_datetime(dz["Data"], errors="coerce")
    dz = dz.sort_values("Data").dropna(subset=["Data"])
    mask = dz["Data"].dt.strftime("%Y-%m-%d") == yesterday_str
    row_yday = dz[mask].iloc[-1] if mask.any() else None

# weight trend (90 days)
waga_df = pd.DataFrame()
latest_weight = None
weight_delta  = None
if not dz.empty and "Waga_kg" in dz.columns:
    waga_df = dz[["Data", "Waga_kg"]].copy()
    waga_df["Waga_kg"] = waga_df["Waga_kg"].apply(num)
    waga_df = waga_df.dropna(subset=["Waga_kg"]).sort_values("Data")
    if not waga_df.empty:
        latest_weight = waga_df["Waga_kg"].iloc[-1]
        cutoff = pd.Timestamp.now() - timedelta(days=7)
        past = waga_df[waga_df["Data"] <= cutoff]
        if not past.empty:
            weight_delta = latest_weight - past["Waga_kg"].iloc[-1]

bmi = round(latest_weight / ((HEIGHT_CM / 100) ** 2), 1) if latest_weight else None

steps        = num(row_yday.get("Kroki"))          if row_yday is not None else None
kcal_burned  = num(row_yday.get("Kalorie_calkowite")) if row_yday is not None else None
sleep_h      = num(row_yday.get("Sen_h"))             if row_yday is not None else None
sleep_qual   = num(row_yday.get("Jakos_snu"))         if row_yday is not None else None
hr_rest      = num(row_yday.get("HR_spoczynkowe"))    if row_yday is not None else None


# ── Fitatu ────────────────────────────────────────────────────────────────────
fit_row = None
kcal_consumed = None
if not df_fit.empty and "Data" in df_fit.columns:
    r = df_fit[df_fit["Data"] == yesterday_str]
    if not r.empty:
        fit_row = r.iloc[-1]
        kcal_consumed = num(fit_row.get("Kcal"))

products_yday = pd.DataFrame()
if not df_prod.empty and "Data" in df_prod.columns:
    products_yday = df_prod[df_prod["Data"] == yesterday_str].copy()

deficit = int(kcal_burned - kcal_consumed) if (kcal_burned and kcal_consumed) else None


# ── Last cardio ───────────────────────────────────────────────────────────────
last_cardio = None
CARDIO_TYPES = {
    "running", "cycling", "swimming", "walking", "trail_running",
    "open_water_swimming", "road_biking", "indoor_cycling", "treadmill_running"
}
if not df_akt.empty and "Data" in df_akt.columns:
    akt = df_akt.copy()
    akt["_dt"] = pd.to_datetime(akt["Data"], errors="coerce")
    if "Typ" in akt.columns:
        cardio_mask = akt["Typ"].str.lower().isin(CARDIO_TYPES)
        cardio_df = akt[cardio_mask] if cardio_mask.any() else akt
    else:
        cardio_df = akt
    if not cardio_df.empty:
        last_cardio = cardio_df.sort_values("_dt").iloc[-1]


# ── Last strength (Hevy) ──────────────────────────────────────────────────────
last_hevy_name  = None
last_hevy_exs   = []
last_hevy_date  = None
last_hevy_sets  = 0
if not df_hevy.empty:
    h = df_hevy.copy()
    date_col = "Data_start" if "Data_start" in h.columns else ("Data" if "Data" in h.columns else None)
    if date_col:
        h["_dt"] = pd.to_datetime(h[date_col], errors="coerce")
        h = h.dropna(subset=["_dt"])
        if not h.empty:
            latest_id = h.sort_values("_dt").iloc[-1].get("ID_treningu")
            wk = h[h["ID_treningu"] == latest_id]
            last_hevy_name  = wk.iloc[-1].get("Trening", "Trening siłowy")
            last_hevy_date  = wk["_dt"].max()
            last_hevy_sets  = len(wk)
            if "Cwiczenie" in wk.columns:
                last_hevy_exs = list(wk["Cwiczenie"].dropna().unique())


# ═════════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ═════════════════════════════════════════════════════════════════════════════

# ── Header ────────────────────────────────────────────────────────────────────
col_name, col_date = st.columns([2, 1])
with col_name:
    st.markdown("# 👋 Igor")
with col_date:
    st.markdown(
        f"<div style='text-align:right; padding-top:.8rem; color:#888; font-size:.9rem;'>"
        f"📅 {date.today().strftime('%A, %d %B %Y')}</div>",
        unsafe_allow_html=True
    )

st.divider()

# ── Sylwetka ──────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📊 Sylwetka</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)

delta_txt = f"{weight_delta:+.1f} kg (7 dni)" if weight_delta is not None else None
c1.metric("⚖️ Waga",    fmt_num(latest_weight, " kg", 1), delta=delta_txt, delta_color="inverse")
c2.metric("📏 Wzrost",  f"{HEIGHT_CM} cm")
c3.metric("🧮 BMI",     f"{bmi}" if bmi else "—")
c4.metric("❤️ HR spocz.", fmt_num(hr_rest, " bpm", 0))
def sleep_emoji(score):
    if score is None: return ""
    if score >= 85: return "😴 Świetny"
    if score >= 70: return "🙂 Dobry"
    if score >= 50: return "😐 Średni"
    return "😟 Słaby"

sleep_label = f"{int(sleep_qual)}/100 · {sleep_emoji(sleep_qual)}" if sleep_qual else None
c5.metric("😴 Sen", fmt_num(sleep_h, " h", 1), delta=sleep_label, delta_color="off")


# ── Wczoraj ───────────────────────────────────────────────────────────────────
st.markdown(
    f'<div class="section-title">📅 Wczoraj — {(date.today()-timedelta(days=1)).strftime("%d.%m.%Y")}</div>',
    unsafe_allow_html=True
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("👟 Kroki",        fmt_num(steps, "", 0) if steps else "—")
c2.metric("🔥 Kcal spalone", fmt_num(kcal_burned,   " kcal", 0))
c3.metric("🥗 Kcal spożyte", fmt_num(kcal_consumed, " kcal", 0))

if deficit is not None:
    label = "📉 Deficyt" if deficit > 0 else "📈 Nadwyżka"
    c4.metric(label, fmt_num(abs(deficit), " kcal", 0),
              delta="kalorii" if deficit > 0 else "kalorii",
              delta_color="normal" if deficit > 0 else "inverse")
else:
    c4.metric("⚡ Bilans",  "—")


# ── Makra ─────────────────────────────────────────────────────────────────────
if fit_row is not None:
    st.markdown('<div class="section-title">🥩 Makra wczoraj</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    bialko  = num(fit_row.get("Bialko_g"))
    tluszcz = num(fit_row.get("Tluszcze_g"))
    wegle   = num(fit_row.get("Wegle_g"))
    c1.metric("🥩 Białko",   fmt_num(bialko,  " g", 0))
    c2.metric("🧈 Tłuszcze", fmt_num(tluszcz, " g", 0))
    c3.metric("🍞 Węglowodany", fmt_num(wegle, " g", 0))


# ── Produkty ──────────────────────────────────────────────────────────────────
if not products_yday.empty:
    with st.expander(f"🛒 Co jadłem wczoraj ({len(products_yday)} produktów)", expanded=True):
        cols = [c for c in ["Produkt", "Gramy", "Kcal"] if c in products_yday.columns]
        display = products_yday[cols].copy().reset_index(drop=True)
        if "Gramy" in display.columns:
            display["Gramy"] = display["Gramy"].apply(
                lambda x: f"{num(x):.0f} g" if num(x) else x
            )
        if "Kcal" in display.columns:
            display["Kcal"] = display["Kcal"].apply(
                lambda x: f"{num(x):.0f}" if num(x) else x
            )
        st.dataframe(display, use_container_width=True, hide_index=True)


# ── Treningi ──────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">🏋️ Ostatnie treningi</div>', unsafe_allow_html=True)
col_sila, col_kardio = st.columns(2)

with col_sila:
    date_sila = last_hevy_date.strftime("%d.%m.%Y") if last_hevy_date else "—"
    exs_html = "".join(f'<span class="pill">{e}</span>' for e in last_hevy_exs) if last_hevy_exs else "Brak ćwiczeń"
    st.markdown(f"""
    <div class="workout-card">
      <h4>💪 Ostatni trening siłowy</h4>
      <div class="date">{date_sila}</div>
      <div style="font-weight:600; margin-bottom:.5rem;">{last_hevy_name or '—'}</div>
      <div>{exs_html}</div>
      {"<div class='stat'>📊 " + str(last_hevy_sets) + " serii łącznie</div>" if last_hevy_sets else ""}
    </div>
    """, unsafe_allow_html=True)

with col_kardio:
    if last_cardio is not None:
        name   = last_cardio.get("Nazwa", "Aktywność")
        typ    = last_cardio.get("Typ", "")
        dist   = num(last_cardio.get("Dystans_km"))
        czas   = last_cardio.get("Czas", "")
        hr_avg = num(last_cardio.get("HR_sr"))
        tempo  = last_cardio.get("Tempo_sr", "")
        vo2    = num(last_cardio.get("VO2max"))
        dt_k   = last_cardio.get("_dt") or last_cardio.get("Data", "")
        try:
            date_k = pd.to_datetime(dt_k).strftime("%d.%m.%Y")
        except Exception:
            date_k = str(dt_k)[:10]

        stats = []
        if dist:   stats.append(f"📍 {dist:.2f} km")
        if czas:   stats.append(f"⏱ {czas}")
        if tempo:  stats.append(f"🏃 {tempo} /km")
        if hr_avg: stats.append(f"❤️ {hr_avg:.0f} bpm")
        if vo2:    stats.append(f"🫁 VO2max {vo2:.0f}")
        stats_html = "  ·  ".join(stats) if stats else "Brak szczegółów"

        st.markdown(f"""
        <div class="workout-card">
          <h4>🏃 Ostatni trening kardio</h4>
          <div class="date">{date_k}</div>
          <div style="font-weight:600; margin-bottom:.5rem;">{name}</div>
          <div class="stat">{stats_html}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="workout-card">
          <h4>🏃 Ostatni trening kardio</h4>
          <div class="stat">Brak danych</div>
        </div>
        """, unsafe_allow_html=True)


# ── Trend wagowy ──────────────────────────────────────────────────────────────
if not waga_df.empty and len(waga_df) > 2:
    st.markdown('<div class="section-title">📈 Trend wagowy (90 dni)</div>', unsafe_allow_html=True)

    w90 = waga_df[waga_df["Data"] >= (pd.Timestamp.now() - timedelta(days=90))].copy()

    fig = go.Figure()

    # Raw weight
    fig.add_trace(go.Scatter(
        x=w90["Data"], y=w90["Waga_kg"],
        mode="lines+markers",
        line=dict(color="#FF6B6B", width=2),
        marker=dict(size=5, color="#FF6B6B"),
        name="Waga",
        hovertemplate="%{x|%d.%m.%Y}<br><b>%{y:.1f} kg</b><extra></extra>"
    ))

    # Linear trendline
    if len(w90) > 3:
        x_num = (w90["Data"] - w90["Data"].min()).dt.days.values
        z = np.polyfit(x_num, w90["Waga_kg"].values, 1)
        p = np.poly1d(z)
        fig.add_trace(go.Scatter(
            x=w90["Data"], y=p(x_num),
            mode="lines",
            line=dict(color="#4ECDC4", width=2, dash="dash"),
            name="Trend",
            hoverinfo="skip"
        ))

    # Target zone (optional: ±0.5 kg band around trend)
    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis_title="kg",
        xaxis_title=None,
        legend=dict(orientation="h", yanchor="bottom", y=1, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    f"🔄 Odświeżanie co 5 minut  ·  "
    f"Ostatni render: {datetime.now().strftime('%H:%M:%S')}  ·  "
    f"Dane: Garmin Connect · Fitatu · Hevy"
)
