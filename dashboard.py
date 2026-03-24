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
  .prod-table th { font-size: 0.72rem; color: #666; text-transform: uppercase; letter-spacing: .05em;
                   border-bottom: 2px solid #e8e8e8; padding: 6px 10px; text-align: left; font-weight: 700; }
  .prod-table td { font-size: 0.92rem; padding: 7px 10px; border-bottom: 1px solid #f0f0f0; color: #111; font-weight: 500; }
  .prod-table td:nth-child(2) { color: #555; font-weight: 400; }
  .prod-table td:nth-child(3) { color: #E05A2B; font-weight: 600; }
  .prod-table tr:hover td { background: #f7f7f7; }
  .prod-table tr:last-child td { border-bottom: none; }
  .prod-kcal { color: #E05A2B; font-size: 0.85rem; font-weight: 600; }
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

# Fitatu — A=Data, B=Kcal — czytaj po pozycji kolumny, nie po nazwie
fit_row, kcal_eaten, fit_date_used = None, None, yday
_fit_debug = ""

if not df_fit.empty:
    df_fit2 = df_fit.copy()
    # kolumna A to zawsze indeks 0 (data), kolumna B to indeks 1 (kcal)
    col_date = df_fit2.columns[0]
    col_kcal = df_fit2.columns[1] if len(df_fit2.columns) > 1 else None
    _fit_debug = f"cols={list(df_fit2.columns)}, rows={len(df_fit2)}, last={df_fit2[col_date].iloc[-1] if not df_fit2.empty else '?'}"
    df_fit2["_dt"] = pd.to_datetime(df_fit2[col_date].astype(str).str.strip().str[:10], errors="coerce")
    df_fit2 = df_fit2.dropna(subset=["_dt"]).sort_values("_dt")
    if not df_fit2.empty:
        r = df_fit2[df_fit2["_dt"].dt.strftime("%Y-%m-%d") == yday]
        if r.empty:
            r = df_fit2.iloc[[-1]]
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
fit_date_label = datetime.strptime(fit_date_used, "%Y-%m-%d").strftime("%d.%m.%Y") if fit_date_used else "—"
garmin_date_label = (date.today()-timedelta(days=1)).strftime("%d.%m.%Y")
st.markdown(
    f'<div class="sec">🔥 Kalorie — Garmin: {garmin_date_label} · Fitatu: {fit_date_label}</div>',
    unsafe_allow_html=True
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("👟 Kroki",        fmt(steps, "", 0) if steps else "—")
c2.metric("🔥 Spalone",      fmt(kcal_burned, " kcal", 0))
c3.metric("🥗 Spożyte",      fmt(kcal_eaten,  " kcal", 0) if kcal_eaten else "—")

if balance is not None:
    lbl   = "📉 Deficyt" if balance > 0 else "📈 Nadwyżka"
    color = "normal"    if balance > 0 else "inverse"
    c4.metric(lbl, fmt(abs(balance), " kcal", 0), delta_color=color)
else:
    c4.metric("⚡ Bilans", "—")

# debug Fitatu (tymczasowe — usuniemy jak zadziała)
with st.expander("🔍 Debug Fitatu", expanded=False):
    st.write(f"yday={yday}, fit_date_used={fit_date_used}, kcal_eaten={kcal_eaten}")
    st.write(f"df_fit info: {_fit_debug}")
    st.dataframe(df_fit.head(5))

# ── Makra ─────────────────────────────────────────────────────────────────────
if fit_row is not None:
    col_b = df_fit.columns[1] if len(df_fit.columns) > 1 else "Kcal"
    col_p = df_fit.columns[2] if len(df_fit.columns) > 2 else "Bialko_g"
    col_t = df_fit.columns[3] if len(df_fit.columns) > 3 else "Tluszcze_g"
    col_w = df_fit.columns[4] if len(df_fit.columns) > 4 else "Wegle_g"
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
    else:
        st.markdown('<div class="card"><div class="card-title">🏃 Ostatni trening kardio</div><div style="color:#bbb;margin-top:.5rem">Brak danych</div></div>', unsafe_allow_html=True)




# Footer
st.divider()
st.caption(f"🔄 Odświeża się co 5 min  ·  {datetime.now().strftime('%H:%M:%S')}  ·  Garmin · Fitatu · Hevy")
