"""Checks your setup before you start the server.

    python -m scripts.check_setup
"""
import importlib
import sys
from pathlib import Path

problems = 0


def ok(msg: str) -> None:
    print(f"  [ok]    {msg}")


def bad(msg: str) -> None:
    global problems
    problems += 1
    print(f"  [FIX]   {msg}")


def main() -> int:
    print("Python")
    if sys.version_info < (3, 10):
        bad(f"Python 3.10 or newer is needed, you have {sys.version.split()[0]}")
    else:
        ok(f"Python {sys.version.split()[0]}")

    print("Packages")
    packages = {
        "fastapi": "fastapi", "uvicorn": "uvicorn[standard]", "sqlalchemy": "sqlalchemy",
        "pymysql": "pymysql", "cryptography": "cryptography", "bcrypt": "bcrypt", "jwt": "PyJWT",
        "pydantic_settings": "pydantic-settings", "email_validator": "email-validator",
        "multipart": "python-multipart", "alembic": "alembic", "websockets": "websockets",
    }
    missing = [pip for mod, pip in packages.items() if importlib.util.find_spec(mod) is None] #type :ignore
    if missing:
        bad("missing packages. Run: pip install -r requirements.txt   (" + ", ".join(missing) + ")")
    else:
        ok("all packages installed")

    print("Settings (.env)")
    if not Path(".env").exists():
        bad("no .env file. Copy .env.example to .env and fill it in")
    try:
        from common.config import get_settings
        settings = get_settings()
        ok("settings are valid (keys are long enough and different)")
    except Exception as exc:  # noqa: BLE001
        bad(f"settings problem: {str(exc).splitlines()[0] if str(exc) else exc}")
        print("\nStopped: fix the settings first, then run this again.")
        return 1

    print("Database")
    try:
        from sqlalchemy import inspect, text

        from common.database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        ok(f"connected to the database ({engine.dialect.name})")
        tables = set(inspect(engine).get_table_names())
        needed = {"users", "revoked_tokens", "gateways", "assigned_numbers", "call_sms_logs"}
        if needed - tables:
            if not list(Path("alembic/versions").glob("*.py")):
                bad('no migration yet. Run: alembic revision --autogenerate -m "initial schema"   then   alembic upgrade head')
            else:
                bad("tables are missing. Run: alembic upgrade head")
        else:
            ok("all tables exist")
            from sqlalchemy import select

            from common.database import SessionLocal
            from common.models import Role, User

            with SessionLocal() as db:
                if db.scalar(select(User).where(User.role == Role.admin)) is None:
                    bad("no admin user yet. Run: python -m scripts.create_admin")
                else:
                    ok("an admin user exists")
    except Exception as exc:  # noqa: BLE001
        bad(f"cannot use the database: {str(exc).splitlines()[0]}")
        print("      Check DATABASE_URL, that MySQL is running, and that the database and user exist.")

    print("Mail (optional)")
    if settings.mail_server:
        ok(f"SMTP server set: {settings.mail_server}")
    else:
        ok("no SMTP server: reset links are printed in the server window; admins can set passwords instead")

    print()
    if problems:
        print(f"{problems} thing(s) to fix. Run this again after each fix.")
        return 1
    print("Everything looks good. Start the server with:")
    print("    uvicorn main:app --host 0.0.0.0 --port 8001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
