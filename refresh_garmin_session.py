"""
refresh_garmin_session.py
Loguje się do Garmin Connect i generuje nowy GARTH_SESSION secret.
Nie wymaga Google credentials ani .env — podaj email i hasło poniżej.
"""

import garth, base64, tarfile, io
from pathlib import Path

# ── UZUPEŁNIJ ────────────────────────────────────────
GARMIN_EMAIL    = "igorstokowski@gmail.com"
GARMIN_PASSWORD = ""   # <-- wpisz swoje hasło
# ─────────────────────────────────────────────────────

SESSION_DIR = Path("SESJA_GARTH")
SESSION_DIR.mkdir(exist_ok=True)
garth.home = str(SESSION_DIR)

print("⏳ Loguję się do Garmin Connect...")
print("   (może pojawić się prośba o kod MFA — wpisz go i zatwierdź Enterem)\n")

garth.login(GARMIN_EMAIL, GARMIN_PASSWORD)
garth.save(str(SESSION_DIR))
print("✅ Zalogowano! Sesja zapisana.\n")

# Generuj wartość secretu
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    tar.add(str(SESSION_DIR))
value = base64.b64encode(buf.getvalue()).decode()

out = Path("garth_session_new.txt")
out.write_text(value)

print(f"✅ Gotowe! Plik: {out.resolve()}")
print(f"   Długość: {len(value)} znaków\n")
print("Skopiuj zawartość pliku garth_session_new.txt i wklej do GitHub:")
print("  repo → Settings → Secrets and variables → Actions")
print("  → GARTH_SESSION → Update secret")
