import os
import pathlib

pathlib.Path("test_auth.db").unlink(missing_ok=True)
os.environ.update(
    APP_ENV="development",
    DATABASE_URL="mysql+pymysql://root:ar4729189@127.0.0.1:3306/dialor",
    SECRET_KEY="a" * 40,
    REFRESH_SECRET_KEY="b" * 40,
    MAX_FAILED_LOGINS="3",
    MAX_CALLS_PER_MINUTE="3",
    BLOCKED_PREFIXES="+999",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from common import models  # noqa: E402,F401
from common.database import Base, SessionLocal, engine  # noqa: E402
from common.models import Role, User  # noqa: E402
from common.security import hash_password  # noqa: E402
from main import app  # noqa: E402

PASSWORD = "Str0ngPassw0rd"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def make_user():
    def _make(username="alice", email="alice@example.com", password=PASSWORD, role=Role.user):
        with SessionLocal() as db:
            user = User(username=username, email=email, password_hash=hash_password(password), role=role)
            db.add(user)
            db.commit()
            return user.id
    return _make


def login(client, ident="alice", password=PASSWORD):
    return client.post("/auth/login", data={"username": ident, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}
