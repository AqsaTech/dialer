"""Pretends to be the Android gateway phone, so you can test everything without a real phone.

1. In the admin panel: add a gateway phone and copy its key, then assign a number to a tenant
   using that gateway and SIM slot 0.
2. Run:   python -m scripts.fake_phone --server http://127.0.0.1:8001 --key gw_YOURKEY
3. Type commands in this window:
       call +14155550123          a customer calls your SIM  (the popup appears in the tenant's browser)
       missed                     the last call was not answered
       sms +14155550123 hello     a customer texts your SIM
       quit
   Calls, texts, answer, reject and hang-up that the tenant starts in the browser are printed here and answered.
"""
import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

try:
    import websockets
except ImportError:
    sys.exit("Install it first:  pip install websockets")


def http_post(server: str, key: str, path: str, body: dict):
    req = urllib.request.Request(
        server + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Gateway-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:200]
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


async def post(args, path, body):
    status, data = await asyncio.to_thread(http_post, args.server, args.key, path, body)
    print(f"   server answered {status}: {data}")
    return status


async def run(args) -> None:
    server = args.server.rstrip("/")
    args.server = server
    scheme, rest = server.split("://", 1)
    url = ("wss" if scheme == "https" else "ws") + "://" + rest + "/ws/gateway"
    headers = {"X-Gateway-Key": args.key}
    major = int(websockets.__version__.split(".")[0]) #type: ignore
    kwargs = {"additional_headers": headers} if major >= 14 else {"extra_headers": headers}

    last_call = {"event": None, "slot": args.slot}
    answered_at: dict[str, float] = {}

    try:
        ws = await websockets.connect(url, **kwargs)#type:ignore
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Could not connect to {url}: {exc}\nCheck the server address and the gateway key.")
    print(f"Connected to {url}. The phone shows as ONLINE in the admin panel.")
    print("Type: call +NUMBER | missed | sms +NUMBER text | quit\n")

    async def send_result(log_id, status, **extra):
        await ws.send(json.dumps({"type": "result", "log_id": log_id, "status": status, **extra}))

    async def on_command(cmd: dict) -> None:
        kind, log_id = cmd.get("cmd"), cmd.get("log_id")
        print(f"<< server command: {cmd}")
        if kind == "dial":
            await send_result(log_id, "ringing")
            await asyncio.sleep(3)
            await send_result(log_id, "ended", duration_seconds=3)
        elif kind == "sms":
            await asyncio.sleep(1)
            await send_result(log_id, "sent")
        elif kind == "answer":
            event = cmd.get("event_id")
            answered_at[event] = time.time() #type: ignore
            await post(args, "/webhook/call-status", {"sim_slot": cmd.get("sim_slot", 0), "event_id": event, "status": "answered"})
        elif kind == "reject":
            await send_result(log_id, "rejected")
        elif kind == "hangup":
            event = cmd.get("event_id")
            if event:
                seconds = int(time.time() - answered_at.pop(event, time.time()))
                await post(args, "/webhook/call-status", {"sim_slot": cmd.get("sim_slot", 0), "event_id": event, "status": "ended", "duration_seconds": seconds})
            else:
                await send_result(log_id, "ended", duration_seconds=1)

    async def reader() -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "cmd" in msg:
                asyncio.create_task(on_command(msg))

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(25)
            await ws.send(json.dumps({"type": "ping"}))

    async def console() -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            words = line.strip().split()
            if not words:
                continue
            if words[0] == "quit":
                return
            if words[0] == "call" and len(words) >= 2:
                slot = int(words[2]) if len(words) > 2 else args.slot
                event = "fake-" + uuid.uuid4().hex[:12]
                last_call.update(event=event, slot=slot)
                await post(args, "/webhook/incoming-call", {"sim_slot": slot, "remote_number": words[1], "event_id": event})
            elif words[0] == "missed" and last_call["event"]:
                await post(args, "/webhook/call-status", {"sim_slot": last_call["slot"], "event_id": last_call["event"], "status": "missed"})
            elif words[0] == "sms" and len(words) >= 3:
                text = line.strip().split(maxsplit=2)[2]
                await post(args, "/webhook/incoming-sms", {"sim_slot": args.slot, "remote_number": words[1], "body": text, "event_id": "fake-" + uuid.uuid4().hex[:12]})
            else:
                print("Unknown command. Use: call +NUMBER | missed | sms +NUMBER text | quit")

    tasks = [asyncio.create_task(t) for t in (reader(), heartbeat(), console())]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()
    await ws.close()
    print("Disconnected.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fake Android gateway phone")
    ap.add_argument("--server", default="http://127.0.0.1:8001")
    ap.add_argument("--key", required=True, help="the gateway key from the admin panel")
    ap.add_argument("--slot", type=int, default=0, help="default SIM slot (0 or 1)")
    asyncio.run(run(ap.parse_args()))
