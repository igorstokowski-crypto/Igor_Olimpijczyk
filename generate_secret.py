"""
Uruchom po `python sync.py` (gdy sesja Garmin jest świeża).
Generuje nową wartość dla GitHub Secret GARTH_SESSION.
"""
import base64, tarfile, io
from pathlib import Path

SESSION_DIR = Path("SESJA_GARTH")

if not SESSION_DIR.exists() or not any(SESSION_DIR.iterdir()):
    print("❌ Folder SESJA_GARTH jest pusty lub nie istnieje.")
    print("   Najpierw uruchom: python sync.py")
else:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(SESSION_DIR))
    value = base64.b64encode(buf.getvalue()).decode()
    out = Path("garth_session_new.txt")
    out.write_text(value)
    print(f"✅ Gotowe! Plik: {out.resolve()}")
    print(f"   Długość: {len(value)} znaków")
    print()
    print("Następnie wklej zawartość pliku do GitHub:")
    print("  repo → Settings → Secrets → Actions → GARTH_SESSION → Update secret")
