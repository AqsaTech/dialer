import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from common.database import SessionLocal
from common.models import (
    AssignedNumber,
    CallSMSLog,
    Direction,
    Gateway,
    LogStatus,
    LogType,
    Role,
)
from tests.conftest import bearer, login


@pytest.fixture()
def admin_h(client, make_user):
    make_user("boss", "boss@example.com", role=Role.admin)
    return bearer(login(client, "boss").json()["access_token"])


def new_gateway(client, h, name="phone-1"):
    r = client.post("/admin/gateways", json={"name": name}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def assign(client, h, user_id, gateway_id, phone="+923001234567", slot=0, **extra):
    body = {"user_id": user_id, "gateway_id": gateway_id, "phone_number": phone, "sim_slot": slot, **extra}
    return client.post("/admin/numbers", json=body, headers=h)


def user_headers(client, ident):
    return bearer(login(client, ident).json()["access_token"])


# ---- gateways --------------------------------------------------------------
def test_gateway_key_is_shown_once_and_stored_hashed(client, admin_h):
    gw = new_gateway(client, admin_h)
    key = gw["api_key"]
    assert key.startswith("gw_")
    listed = client.get("/admin/gateways", headers=admin_h).json()
    assert "api_key" not in listed[0] and "api_key_hash" not in listed[0]
    with SessionLocal() as db:
        stored = db.get(Gateway, gw["id"]).api_key_hash #type: ignore
    assert stored == hashlib.sha256(key.encode()).hexdigest()
    assert stored != key


def test_rotating_key_replaces_the_hash(client, admin_h):
    gw = new_gateway(client, admin_h)
    r = client.post(f"/admin/gateways/{gw['id']}/rotate-key", headers=admin_h)
    assert r.status_code == 200
    assert r.json()["api_key"] != gw["api_key"]
    with SessionLocal() as db:
        assert db.get(Gateway, gw["id"]).api_key_hash == hashlib.sha256(r.json()["api_key"].encode()).hexdigest() #type : ignore


def test_duplicate_gateway_name_is_rejected(client, admin_h):
    new_gateway(client, admin_h)
    assert client.post("/admin/gateways", json={"name": "phone-1"}, headers=admin_h).status_code == 409


def test_tenants_cannot_manage_gateways_or_numbers(client, make_user):
    uid = make_user()
    h = user_headers(client, "alice")
    assert client.post("/admin/gateways", json={"name": "mine"}, headers=h).status_code == 403
    assert client.get("/admin/numbers", headers=h).status_code == 403
    assert assign(client, h, uid, 1).status_code == 403


# ---- assigning numbers -----------------------------------------------------
def test_assign_number_normalizes_format(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    r = assign(client, admin_h, uid, gw["id"], phone="+92 300-123 4567")
    assert r.status_code == 201, r.text
    assert r.json()["phone_number"] == "+923001234567"


@pytest.mark.parametrize("bad", ["03001234567", "+0123456789", "abc", "+12", "+1234567890123456"])
def test_bad_phone_numbers_are_rejected(client, make_user, admin_h, bad):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    assert assign(client, admin_h, uid, gw["id"], phone=bad).status_code == 422


def test_duplicate_phone_and_duplicate_slot_are_rejected(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    assert assign(client, admin_h, uid, gw["id"], "+923001234567", 0).status_code == 201
    assert assign(client, admin_h, uid, gw["id"], "+923001234567", 1).status_code == 409
    assert assign(client, admin_h, uid, gw["id"], "+923009999999", 0).status_code == 409
    assert assign(client, admin_h, uid, gw["id"], "+923009999999", 1).status_code == 201


def test_unknown_user_gateway_and_disabled_user(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    assert assign(client, admin_h, 9999, gw["id"]).status_code == 404
    assert assign(client, admin_h, uid, 9999).status_code == 404
    client.patch(f"/admin/users/{uid}/active", json={"is_active": False}, headers=admin_h)
    assert assign(client, admin_h, uid, gw["id"]).status_code == 400


# ---- tenant isolation ------------------------------------------------------
def test_each_tenant_sees_only_their_own_numbers(client, make_user, admin_h):
    a = make_user("alice", "alice@example.com")
    b = make_user("bob", "bob@example.com")
    gw = new_gateway(client, admin_h)
    na = assign(client, admin_h, a, gw["id"], "+923001111111", 0).json()
    nb = assign(client, admin_h, b, gw["id"], "+923002222222", 1).json()

    ha, hb = user_headers(client, "alice"), user_headers(client, "bob")
    assert [n["phone_number"] for n in client.get("/numbers", headers=ha).json()] == ["+923001111111"]
    assert [n["phone_number"] for n in client.get("/numbers", headers=hb).json()] == ["+923002222222"]

    assert client.get(f"/numbers/{na['id']}", headers=ha).status_code == 200
    assert client.get(f"/numbers/{nb['id']}", headers=ha).status_code == 404  # not 403
    assert client.get(f"/numbers/{na['id']}", headers=hb).status_code == 404


def test_tenant_view_hides_gateway_details(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    assign(client, admin_h, uid, gw["id"], label="Sales line")
    item = client.get("/numbers", headers=user_headers(client, "alice")).json()[0]
    assert set(item) == {"id", "phone_number", "label"}


def test_deactivated_number_disappears_for_tenant(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    num = assign(client, admin_h, uid, gw["id"]).json()
    h = user_headers(client, "alice")
    client.patch(f"/admin/numbers/{num['id']}", json={"is_active": False}, headers=admin_h)
    assert client.get("/numbers", headers=h).json() == []
    assert client.get(f"/numbers/{num['id']}", headers=h).status_code == 404


def test_reassigning_a_number_moves_visibility(client, make_user, admin_h):
    a = make_user("alice", "alice@example.com")
    b = make_user("bob", "bob@example.com")
    gw = new_gateway(client, admin_h)
    num = assign(client, admin_h, a, gw["id"]).json()
    ha, hb = user_headers(client, "alice"), user_headers(client, "bob")
    r = client.patch(f"/admin/numbers/{num['id']}", json={"user_id": b}, headers=admin_h)
    assert r.status_code == 200
    assert client.get("/numbers", headers=ha).json() == []
    assert len(client.get("/numbers", headers=hb).json()) == 1


# ---- logs table ------------------------------------------------------------
def _log(uid, number_id, event_id):
    return CallSMSLog(
        user_id=uid,
        number_id=number_id,
        type=LogType.call,
        direction=Direction.inbound,
        status=LogStatus.ringing,
        remote_number="+14155550123",
        external_event_id=event_id,
    )


def test_duplicate_event_id_cannot_create_a_second_log(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    num = assign(client, admin_h, uid, gw["id"]).json()
    with SessionLocal() as db:
        db.add(_log(uid, num["id"], "evt-1"))
        db.commit()
    with SessionLocal() as db:
        db.add(_log(uid, num["id"], "evt-1"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_logs_without_event_id_are_allowed_and_relationships_load(client, make_user, admin_h):
    uid = make_user()
    gw = new_gateway(client, admin_h)
    num = assign(client, admin_h, uid, gw["id"]).json()
    with SessionLocal() as db:
        db.add(_log(uid, num["id"], None))
        db.add(_log(uid, num["id"], None))
        db.commit()
        row = db.scalars(select(CallSMSLog)).first()
        assert row.number.user.username == "alice" #type:ignore
        assert row.number.gateway.name == "phone-1"  #type:ignore
        assert db.scalar(select(AssignedNumber)).gateway.numbers[0].id == num["id"] #type:ignore
