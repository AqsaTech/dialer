from datetime import timedelta

from common.database import SessionLocal
from common.models import Role, User
from common.security import create_token
from tests.conftest import PASSWORD, bearer, login


def _tokens(client, ident="alice", password=PASSWORD):
    r = login(client, ident, password)
    assert r.status_code == 200, r.text
    return r.json()


def _user(user_id):
    with SessionLocal() as db:
        return db.get(User, user_id)


def test_public_registration_is_closed(client):
    r = client.post("/Register", json={"username": "x", "email": "x@x.com", "Password": "abc", "role": "admin"})
    assert r.status_code == 404
    r = client.post("/auth/register", json={})
    assert r.status_code == 404


def test_login_and_me(client, make_user):
    make_user()
    t = _tokens(client)
    me = client.get("/auth/me", headers=bearer(t["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert "password_hash" not in me.json()


def test_login_by_email_is_case_insensitive(client, make_user):
    make_user()
    assert login(client, "ALICE@example.com").status_code == 200


def test_wrong_password_and_unknown_user_give_same_error(client, make_user):
    make_user()
    a = login(client, "alice", "wrong-password-1")
    b = login(client, "nobody", "wrong-password-1")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_account_locks_after_repeated_failures(client, make_user):
    make_user()
    for _ in range(3):
        assert login(client, "alice", "wrong-password-1").status_code == 401
    assert login(client, "alice", PASSWORD).status_code == 429


def test_token_types_are_not_interchangeable(client, make_user):
    uid = make_user()
    t = _tokens(client)
    assert client.get("/auth/me", headers=bearer(t["refresh_token"])).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": t["access_token"]}).status_code == 401
    reset, _, _ = create_token("reset", _user(uid), timedelta(minutes=5)) #type :ignore
    assert client.get("/auth/me", headers=bearer(reset)).status_code == 401


def test_refresh_rotates_and_old_refresh_dies(client, make_user):
    make_user()
    t = _tokens(client)
    r = client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    assert client.get("/auth/me", headers=bearer(r.json()["access_token"])).status_code == 200
    again = client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert again.status_code == 401


def test_logout_revokes_access_and_refresh(client, make_user):
    make_user()
    t = _tokens(client)
    r = client.post("/auth/logout", json={"refresh_token": t["refresh_token"]}, headers=bearer(t["access_token"]))
    assert r.status_code == 200
    assert client.get("/auth/me", headers=bearer(t["access_token"])).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_logout_all_kills_every_session(client, make_user):
    make_user()
    t1, t2 = _tokens(client), _tokens(client)
    assert client.post("/auth/logout-all", headers=bearer(t1["access_token"])).status_code == 200
    assert client.get("/auth/me", headers=bearer(t2["access_token"])).status_code == 401


def test_change_password_ends_old_sessions(client, make_user):
    make_user()
    t = _tokens(client)
    new_pw = "An0therStrongPw"
    r = client.post(
        "/auth/change-password",
        json={"old_password": PASSWORD, "new_password": new_pw},
        headers=bearer(t["access_token"]),
    )
    assert r.status_code == 200
    assert client.get("/auth/me", headers=bearer(t["access_token"])).status_code == 401
    assert login(client, "alice", PASSWORD).status_code == 401
    assert login(client, "alice", new_pw).status_code == 200


def test_weak_new_password_is_rejected(client, make_user):
    make_user()
    t = _tokens(client)
    r = client.post(
        "/auth/change-password",
        json={"old_password": PASSWORD, "new_password": "short1"},
        headers=bearer(t["access_token"]),
    )
    assert r.status_code == 422


def test_forgot_password_does_not_reveal_accounts(client, make_user):
    make_user()
    known = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_reset_link_works_once(client, make_user):
    uid = make_user()
    token, _, _ = create_token("reset", _user(uid), timedelta(minutes=5)) #type: ignore
    new_pw = "Reset0Password9"
    r = client.post("/auth/reset-password", json={"token": token, "new_password": new_pw})
    assert r.status_code == 200
    assert login(client, "alice", new_pw).status_code == 200
    assert login(client, "alice", PASSWORD).status_code == 401
    reuse = client.post("/auth/reset-password", json={"token": token, "new_password": "Third0Password"})
    assert reuse.status_code == 400


def test_access_token_cannot_reset_password(client, make_user):
    make_user()
    t = _tokens(client)
    r = client.post("/auth/reset-password", json={"token": t["access_token"], "new_password": "Whatever1234"})
    assert r.status_code == 400


def test_normal_user_cannot_use_admin_routes(client, make_user):
    make_user()
    t = _tokens(client)
    assert client.get("/admin/users", headers=bearer(t["access_token"])).status_code == 403
    r = client.post(
        "/admin/users",
        json={"username": "evil", "email": "e@e.com", "password": PASSWORD, "role": "admin"},
        headers=bearer(t["access_token"]),
    )
    assert r.status_code == 403


def test_admin_creates_users_and_duplicates_fail(client, make_user):
    make_user("boss", "boss@example.com", role=Role.admin)
    h = bearer(_tokens(client, "boss")["access_token"])
    body = {"username": "bob", "email": "Bob@Example.com", "password": PASSWORD}
    r = client.post("/admin/users", json=body, headers=h)
    assert r.status_code == 201
    assert r.json()["role"] == "user"
    assert r.json()["email"] == "bob@example.com"
    assert client.post("/admin/users", json=body, headers=h).status_code == 409
    assert login(client, "bob").status_code == 200


def test_disabling_user_kicks_them_out(client, make_user):
    make_user("boss", "boss@example.com", role=Role.admin)
    uid = make_user()
    admin_h = bearer(_tokens(client, "boss")["access_token"])
    user_tokens = _tokens(client, "alice")
    r = client.patch(f"/admin/users/{uid}/active", json={"is_active": False}, headers=admin_h)
    assert r.status_code == 200
    assert client.get("/auth/me", headers=bearer(user_tokens["access_token"])).status_code == 401
    assert login(client, "alice").status_code == 403


def test_admin_cannot_disable_self(client, make_user):
    admin_id = make_user("boss", "boss@example.com", role=Role.admin)
    h = bearer(_tokens(client, "boss")["access_token"])
    r = client.patch(f"/admin/users/{admin_id}/active", json={"is_active": False}, headers=h)
    assert r.status_code == 400


def test_admin_can_set_a_password_and_unlock_the_account(client, make_user):
    make_user("boss", "boss@example.com", role=Role.admin)
    uid = make_user()
    old = _tokens(client, "alice")
    for _ in range(3):
        login(client, "alice", "wrong-password-1")
    assert login(client, "alice", PASSWORD).status_code == 429  # locked

    # a normal user cannot do this
    assert client.post(
        f"/admin/users/{uid}/password", json={"new_password": "Brand0NewPass1"}, headers=bearer(old["access_token"])
    ).status_code == 403

    admin_h = bearer(_tokens(client, "boss")["access_token"])
    r = client.post(f"/admin/users/{uid}/password", json={"new_password": "Brand0NewPass1"}, headers=admin_h)
    assert r.status_code == 200
    assert client.get("/auth/me", headers=bearer(old["access_token"])).status_code == 401
    assert login(client, "alice", "Brand0NewPass1").status_code == 200
    weak = client.post(f"/admin/users/{uid}/password", json={"new_password": "short"}, headers=admin_h)
    assert weak.status_code == 422
