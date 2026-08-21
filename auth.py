"""
auth.py — konta użytkowników strony (Igor + znajomi).

CLI:
  python auth.py add <username> <email> <display_name>   # zapyta o hasło
  python auth.py list
"""

import getpass
import sys

import bcrypt

from db import cursor


def create_user(username: str, email: str, password: str, display_name: str, is_admin: bool = False) -> int:
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO app_users (username, email, password_hash, display_name, is_admin)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (username, email, password_hash, display_name, is_admin),
        )
        return cur.fetchone()["id"]


def verify_user(username: str, password: str) -> dict | None:
    """Zwraca dane użytkownika jeśli hasło poprawne, inaczej None."""
    with cursor() as cur:
        cur.execute(
            "SELECT id, username, email, password_hash, display_name, is_admin "
            "FROM app_users WHERE username = %s",
            (username,),
        )
        user = cur.fetchone()

    if not user:
        return None
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return None

    return {k: v for k, v in user.items() if k != "password_hash"}


def list_users() -> list[dict]:
    with cursor() as cur:
        cur.execute("SELECT id, username, email, display_name, is_admin, created_at FROM app_users ORDER BY id")
        return cur.fetchall()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python auth.py add <username> <email> <display_name>")
        print("        python auth.py list")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) != 5:
            print("Użycie: python auth.py add <username> <email> <display_name>")
            sys.exit(1)
        _, _, username, email, display_name = sys.argv
        password = getpass.getpass("Hasło: ")
        password2 = getpass.getpass("Powtórz hasło: ")
        if password != password2:
            print("❌ Hasła się nie zgadzają.")
            sys.exit(1)
        user_id = create_user(username, email, password, display_name)
        print(f"✅ Utworzono konto '{username}' (id={user_id})")

    elif cmd == "list":
        for u in list_users():
            admin = " [admin]" if u["is_admin"] else ""
            print(f"  #{u['id']} {u['username']} <{u['email']}> — {u['display_name']}{admin}")

    else:
        print(f"Nieznana komenda: {cmd}")
        sys.exit(1)
