from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from common.models import Role
from tests.conftest import bearer, login


def _hdr(client, ident):
    return bearer(login(client, ident).json()["access_token"])


@pytest.fixture()
def w(client, make_user):
    make_user("boss", "boss@example.com", role=Role.admin)
    admin = _hdr(client, "boss")
    a = make_user("alice", "alice@example.com")
    b = make_user("bob", "bob@example.com")
    gw = client.post("/admin/gateways", json={"name": "phone-1"}, headers=admin).json()

    def assign(uid, phone, slot):
        r = client.post(
            "/admin/numbers",
            json={"user_id": uid, "gateway_id": gw["id"], "phone_number": phone, "sim_slot": slot},
            headers=admin,
        )
        assert r.status_code == 201, r.text
        return r.json()

    return SimpleNamespace(
        admin=admin, a=a, b=b, gw=gw, key=gw["api_key"],
        na=assign(a, "+923001111111", 0), nb=assign(b, "+923002222222", 1),
        ha=_hdr(client, "alice"), hb=_hdr(client, "bob"),
        token_a=login(client, "alice").json()["access_token"],
    )


def hook(client, w, path, body, key=None):
    return client.post(f"/webhook/{path}", json=body, headers={"X-Gateway-Key": key or w.key})


def call(slot=0, event="evt-1", remote="+14155550123"):
    return {"sim_slot": slot, "remote_number": remote, "event_id": event}


def sms(slot=0, event="s-1", body="hello"):
    return {**call(slot, event, "+14155550123"), "body": body}


def phone_ws(client, key):
    return client.websocket_connect("/ws/gateway", headers={"x-gateway-key": key})


def sync(phone):
    """Messages are processed in order, so a pong proves everything sent earlier was handled."""
    phone.send_json({"type": "ping"})
    assert phone.receive_json() == {"type": "pong"}


# ---- webhook auth ----------------------------------------------------------
def test_webhook_requires_a_valid_gateway_key(client, w):
    assert client.post("/webhook/incoming-call", json=call()).status_code == 401
    assert hook(client, w, "incoming-call", call(), key="gw_wrong").status_code == 401
    client.patch(f"/admin/gateways/{w.gw['id']}/active", json={"is_active": False}, headers=w.admin)
    assert hook(client, w, "incoming-call", call()).status_code == 403


def test_tenant_jwt_cannot_call_webhooks(client, w):
    r = client.post("/webhook/incoming-call", json=call(), headers=w.ha)
    assert r.status_code == 401


# ---- incoming events -------------------------------------------------------
def test_incoming_call_goes_to_the_sim_owner_only(client, w):
    r = hook(client, w, "incoming-call", call(slot=0))
    assert r.status_code == 200 and r.json()["ok"] and not r.json()["duplicate"]
    mine = client.get("/logs", headers=w.ha).json()["items"]
    assert len(mine) == 1 and mine[0]["status"] == "ringing" and mine[0]["direction"] == "inbound"
    assert mine[0]["created_at"].endswith("Z")
    assert client.get("/logs", headers=w.hb).json()["items"] == []


def test_a_retry_with_the_same_event_id_is_not_a_second_log(client, w):
    first = hook(client, w, "incoming-call", call()).json()
    second = hook(client, w, "incoming-call", call()).json()
    assert second["duplicate"] is True and second["log_id"] == first["log_id"]
    assert len(client.get("/logs", headers=w.ha).json()["items"]) == 1


def test_unmapped_sim_is_ignored(client, w):
    client.patch(f"/admin/numbers/{w.na['id']}", json={"is_active": False}, headers=w.admin)
    assert hook(client, w, "incoming-call", call(slot=0)).json() == {"ok": True, "ignored": True}
    other = client.post("/admin/gateways", json={"name": "phone-2"}, headers=w.admin).json()
    r = hook(client, w, "incoming-call", call(slot=1), key=other["api_key"])
    assert r.json() == {"ok": True, "ignored": True}
    assert client.get("/logs", headers=w.hb).json()["items"] == []


def test_incoming_sms_is_stored_and_isolated(client, w):
    hook(client, w, "incoming-sms", sms(slot=1, body="for bob"))
    item = client.get("/logs", headers=w.hb).json()["items"][0]
    assert item["type"] == "sms" and item["body"] == "for bob" and item["status"] == "received"
    assert client.get("/logs", headers=w.ha).json()["items"] == []


def test_call_status_updates_and_final_status_sticks(client, w):
    hook(client, w, "incoming-call", call())
    r = hook(client, w, "call-status", {"sim_slot": 0, "event_id": "evt-1", "status": "missed"})
    assert r.status_code == 200
    assert client.get("/logs", headers=w.ha).json()["items"][0]["status"] == "missed"
    hook(client, w, "call-status", {"sim_slot": 0, "event_id": "evt-1", "status": "answered"})
    assert client.get("/logs", headers=w.ha).json()["items"][0]["status"] == "missed"


# ---- logs API --------------------------------------------------------------
def test_logs_pagination_and_filters(client, w):
    for i in range(5):
        hook(client, w, "incoming-sms", sms(event=f"s-{i}", body=f"m{i}"))
    p1 = client.get("/logs?limit=2", headers=w.ha).json()
    assert [x["body"] for x in p1["items"]] == ["m4", "m3"] and p1["next_before_id"]
    p2 = client.get(f"/logs?limit=2&before_id={p1['next_before_id']}", headers=w.ha).json()
    assert [x["body"] for x in p2["items"]] == ["m2", "m1"]
    p3 = client.get(f"/logs?limit=2&before_id={p2['next_before_id']}", headers=w.ha).json()
    assert [x["body"] for x in p3["items"]] == ["m0"] and p3["next_before_id"] is None
    assert client.get("/logs?type=call", headers=w.ha).json()["items"] == []
    assert len(client.get("/logs?type=sms&direction=inbound", headers=w.ha).json()["items"]) == 5


def test_another_tenants_log_is_a_404(client, w):
    log_id = hook(client, w, "incoming-call", call()).json()["log_id"]
    assert client.get(f"/logs/{log_id}", headers=w.ha).status_code == 200
    assert client.get(f"/logs/{log_id}", headers=w.hb).status_code == 404


# ---- real time -------------------------------------------------------------
def test_popup_event_reaches_only_the_owner(client, w):
    with client.websocket_connect("/ws/events") as ws:
        ws.send_json({"type": "auth", "token": w.token_a})
        assert ws.receive_json() == {"event": "ready"}
        hook(client, w, "incoming-call", call(slot=1, event="bobs"))  # bob's SIM
        hook(client, w, "incoming-call", call(slot=0, event="alices"))
        msg = ws.receive_json()
        assert msg["event"] == "incoming_call" and msg["log"]["remote_number"] == "+14155550123"
        ws.send_text("ping")
        assert ws.receive_text() == "pong"  # nothing of bob's was delivered in between


def test_browser_socket_rejects_a_bad_token(client, w):
    with client.websocket_connect("/ws/events") as ws:
        ws.send_json({"type": "auth", "token": "not-a-token"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_browser_socket_rejects_a_refresh_token(client, w):
    refresh = login(client, "alice").json()["refresh_token"]
    with client.websocket_connect("/ws/events") as ws:
        ws.send_json({"type": "auth", "token": refresh})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_phone_socket_rejects_a_bad_key(client, w):
    with pytest.raises(WebSocketDisconnect):
        with phone_ws(client, "gw_wrong"):
            pass


def test_admin_sees_which_gateways_are_online(client, w):
    assert client.get("/admin/gateways", headers=w.admin).json()[0]["online"] is False
    with phone_ws(client, w.key) as phone:
        sync(phone)
        assert client.get("/admin/gateways", headers=w.admin).json()[0]["online"] is True


# ---- outgoing --------------------------------------------------------------
def test_dial_with_an_offline_phone_fails_cleanly(client, w):
    r = client.post("/calls/dial", json={"number_id": w.na["id"], "to": "+14155550123"}, headers=w.ha)
    assert r.status_code == 503
    assert client.get("/logs", headers=w.ha).json()["items"] == []


def test_dial_reaches_the_phone_and_status_flows_back(client, w):
    with phone_ws(client, w.key) as phone:
        r = client.post("/calls/dial", json={"number_id": w.na["id"], "to": "+1 415 555 0123"}, headers=w.ha)
        assert r.status_code == 202
        log_id = r.json()["log_id"]
        assert phone.receive_json() == {"cmd": "dial", "log_id": log_id, "sim_slot": 0, "to": "+14155550123"}
        phone.send_json({"type": "result", "log_id": log_id, "status": "ringing"})
        sync(phone)
        assert client.get(f"/logs/{log_id}", headers=w.ha).json()["status"] == "ringing"
        phone.send_json({"type": "result", "log_id": log_id, "status": "ended", "duration_seconds": 42})
        sync(phone)
        done = client.get(f"/logs/{log_id}", headers=w.ha).json()
        assert done["status"] == "ended" and done["duration_seconds"] == 42


def test_cannot_dial_from_someone_elses_number(client, w):
    with phone_ws(client, w.key) as phone:
        sync(phone)
        r = client.post("/calls/dial", json={"number_id": w.nb["id"], "to": "+14155550123"}, headers=w.ha)
        assert r.status_code == 404


def test_blocked_prefix_and_rate_limit(client, w):
    with phone_ws(client, w.key) as phone:
        sync(phone)
        blocked = client.post("/calls/dial", json={"number_id": w.na["id"], "to": "+9991234567"}, headers=w.ha)
        assert blocked.status_code == 403
        for _ in range(3):  # MAX_CALLS_PER_MINUTE is 3 in tests
            ok = client.post("/calls/dial", json={"number_id": w.na["id"], "to": "+14155550123"}, headers=w.ha)
            assert ok.status_code == 202
        over = client.post("/calls/dial", json={"number_id": w.na["id"], "to": "+14155550123"}, headers=w.ha)
        assert over.status_code == 429
        # Bob has his own allowance.
        bob = client.post("/calls/dial", json={"number_id": w.nb["id"], "to": "+14155550123"}, headers=w.hb)
        assert bob.status_code == 202


def test_sms_send_reaches_the_phone(client, w):
    with phone_ws(client, w.key) as phone:
        r = client.post("/sms/send", json={"number_id": w.na["id"], "to": "+14155550123", "body": "hi there"}, headers=w.ha)
        assert r.status_code == 202
        cmd = phone.receive_json()
        assert cmd["cmd"] == "sms" and cmd["body"] == "hi there" and cmd["to"] == "+14155550123"
        phone.send_json({"type": "result", "log_id": cmd["log_id"], "status": "sent"})
        sync(phone)
        assert client.get(f"/logs/{cmd['log_id']}", headers=w.ha).json()["status"] == "sent"


def test_bad_destination_is_rejected(client, w):
    r = client.post("/calls/dial", json={"number_id": w.na["id"], "to": "03001234567"}, headers=w.ha)
    assert r.status_code == 422


# ---- answer / reject -------------------------------------------------------
def test_answer_sends_a_command_and_only_while_ringing(client, w):
    log_id = hook(client, w, "incoming-call", call(event="evt-9")).json()["log_id"]
    with phone_ws(client, w.key) as phone:
        sync(phone)
        assert client.post(f"/calls/{log_id}/answer", headers=w.hb).status_code == 404
        r = client.post(f"/calls/{log_id}/answer", headers=w.ha)
        assert r.status_code == 202
        cmd = phone.receive_json()
        assert cmd["cmd"] == "answer" and cmd["log_id"] == log_id and cmd["event_id"] == "evt-9"
        hook(client, w, "call-status", {"sim_slot": 0, "event_id": "evt-9", "status": "missed"})
        assert client.post(f"/calls/{log_id}/reject", headers=w.ha).status_code == 409


def test_a_phone_cannot_change_another_gateways_logs(client, w):
    log_id = hook(client, w, "incoming-call", call()).json()["log_id"]
    other = client.post("/admin/gateways", json={"name": "phone-2"}, headers=w.admin).json()
    with phone_ws(client, other["api_key"]) as intruder:
        intruder.send_json({"type": "result", "log_id": log_id, "status": "answered"})
        sync(intruder)
    assert client.get(f"/logs/{log_id}", headers=w.ha).json()["status"] == "ringing"
