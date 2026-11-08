"""Create the first administrator. Run once from the project root:

    python -m scripts.create_admin
"""
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy import select

from common import models  # noqa: F401
from common.database import SessionLocal
from common.models import Role, User
from common.security import hash_password
from tenant_core.schemas import UserCreate


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.role == Role.admin)):
            if input("An admin already exists. Create another? [y/N] ").strip().lower() != "y":
                return
        username = input("Admin username: ").strip()
        email = input("Admin email: ").strip()
        password = getpass.getpass("Password (min 10 chars, letters and digits): ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
        try:
            data = UserCreate(username=username, email=email, password=password, role=Role.admin)
        except ValidationError as exc:
            sys.exit("\n".join(e["msg"] for e in exc.errors()))
        db.add(User(
            username=data.username,
            email=data.email.lower(),
            password_hash=hash_password(data.password),
            role=Role.admin,
        ))
        db.commit()
        print("Admin created.")


if __name__ == "__main__":
    main()
