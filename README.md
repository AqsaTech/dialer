<<<<<<< HEAD
# Dialer.com
builder a dialer app which can call anywhere in the country....by using python fastapi 
=======
# Multi-tenant GSM Dialer

A web app where each customer (tenant) uses SIM numbers that sit in an Android "gateway" phone.
Tenants log in, see only their own calls and texts, get a live popup for incoming calls, and can
call, text, answer, reject and hang up from the browser. Voice stays on the phone.

## What is in this folder

    dialer/
      main.py            starts the whole server (both cores in one process)
      tenant_core/       Core A: logins, admin, numbers, logs, dial/SMS/answer/reject, browser WebSocket
      gateway_core/      Core B: webhooks and the WebSocket that the Android phone uses
      common/            shared: settings, database, models, security, live-connection hubs
      web/               the pages: login, dashboard, admin panel (HTML, Bootstrap 5, JavaScript)
      alembic/           database migrations (creates the tables)
      scripts/           check_setup, create_admin, fake_phone
      tests/             automatic tests (pytest)
      android_gateway/   the Android app for the phone with the SIMs (open in Android Studio)

You need: Python 3.10 or newer, and MySQL 8 (or use SQLite just to try it).

---------------------------------------------------------------------------------------------------

## 1. Install (one time)

Open a terminal in this folder.

Windows (PowerShell):

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    copy .env.example .env

Mac / Linux:

    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env

### Database
Option A, MySQL (recommended). In the MySQL console:

    CREATE DATABASE dialer CHARACTER SET utf8mb4;
    CREATE USER 'dialer_user'@'localhost' IDENTIFIED BY 'change_me';
    GRANT ALL ON dialer.* TO 'dialer_user'@'localhost';

Option B, just to try it: skip MySQL and use `DATABASE_URL=sqlite:///./dialer.db` in `.env`.

### Fill in `.env`
Open `.env` and set:
- `DATABASE_URL` (the line for your option)
- `SECRET_KEY` and `REFRESH_SECRET_KEY`: two DIFFERENT random values. Make each with:

      python -c "import secrets; print(secrets.token_urlsafe(48))"

### Create the tables and the admin

    alembic revision --autogenerate -m "initial schema"
    alembic upgrade head
    python -m scripts.create_admin

The first command is needed only once. Keep the file it creates in `alembic/versions/`.

---------------------------------------------------------------------------------------------------

## 2. Check that everything is ready

    python -m scripts.check_setup

It tells you exactly what to fix (missing packages, wrong password, tables not created, no admin).
Repeat until it says "Everything looks good".

Then run the automatic tests (they use their own temporary database, never yours):

    pytest -v

All tests should pass. If one fails, copy its message and send it to whoever maintains the project.

---------------------------------------------------------------------------------------------------

## 3. Start the server

    uvicorn main:app --host 0.0.0.0 --port 8001

Use exactly ONE worker (do not add `--workers`). The live connections are kept in memory.
During development add `--reload` if you want it to restart when you edit code.

Check that it works:
- Open http://127.0.0.1:8001/health, you should see `{"status":"ok"}`
- Open http://127.0.0.1:8001, you should see the sign-in page. Sign in as the admin.
- Open http://127.0.0.1:8001/docs for the interactive API list (turned off when `APP_ENV=production`)

To stop the server press Ctrl + C.

---------------------------------------------------------------------------------------------------

## 4. Try the whole system WITHOUT a phone

1. Sign in as admin, you land on the admin panel.
2. Users tab: create a tenant, for example `alice`.
3. Gateway phones tab: add a phone named `office-phone`. Copy the key shown (it is shown once).
4. Numbers tab: assign a number to alice, for example `+923001111111`, on `office-phone`, SIM 1.
5. In a second terminal (venv active) start the fake phone with your key:

       python -m scripts.fake_phone --server http://127.0.0.1:8001 --key gw_PASTE_THE_KEY

   The admin panel now shows the phone as Online.
6. In another browser window (or a private window) sign in as alice and open the dashboard.
7. In the fake phone terminal type:  `call +14155550123`
   Alice's browser shows the incoming call popup. Click Answer, the terminal prints the command.
   Click Hang up, the call shows as ended in the history.
8. Type `sms +14155550123 hello` in the terminal: the text appears in alice's history instantly.
9. In alice's dashboard, type a number and press Call or send a text: the terminal prints the
   command and answers it, and the history updates.

If all of that works, the server side is working. Next connect a real phone.

---------------------------------------------------------------------------------------------------

## 5. Use a real Android phone

1. Open the `android_gateway` folder in Android Studio and let it sync (use Gradle 8.7 or newer if
   it asks). Build and install it on the phone that holds the SIM cards (USB debugging on).
2. The phone and the server must reach each other. On the same Wi-Fi use the server PC's IP,
   for example `http://192.168.1.20:8001` (allow port 8001 in the Windows firewall).
   For the internet, put the server behind HTTPS (see section 7) and use `https://your-domain`.
3. In the app: enter the server address and the gateway key, then press the buttons in order:
   1. Allow permissions  2. Stop Android from sleeping this app  3. Save and start.
4. The admin panel shows the phone as Online. Call the SIM from another phone to test.

Notes about Android phones:
- Every phone brand behaves a little differently. The slot (SIM 1 or SIM 2) of an incoming call is
  not reported by every phone. The "default SIM slot" setting is used when the phone does not say.
- On some brands (Xiaomi, Huawei, Oppo, Samsung) also allow "autostart" and "run in background"
  for the app, otherwise the system may stop it.
- For outgoing calls Android cannot tell when the other person answers, so the status goes
  queued, ringing, ended. The duration counts from when dialling started.

---------------------------------------------------------------------------------------------------

## 6. If something does not work

| Problem | What to do |
|---|---|
| `ModuleNotFoundError` | The venv is not active, or run `pip install -r requirements.txt` |
| Error about SECRET_KEY at start | Fill both keys in `.env`, they must be 32+ characters and different |
| `Can't connect to MySQL` | Start MySQL, check `DATABASE_URL`, user and password (encode special characters) |
| `Table ... doesn't exist` | Run `alembic upgrade head` |
| Cannot sign in as admin | Run `python -m scripts.create_admin` |
| Page has no styling | The browser blocked Bootstrap from the internet. Check your connection and the browser console |
| Phone never shows Online | Wrong address or key; the phone cannot reach the PC (firewall, different network) |
| Popup does not appear | The tenant has no number on that gateway and SIM slot, or the phone reported another slot |
| Dial says "gateway phone is offline" | The phone app is stopped or disconnected. Open it and check the status |
| 429 Too many requests | The call or text limits in `.env` were reached. Wait a minute |
| Forgot a tenant password and no email set up | Admin panel, Users, "Set password" |

---------------------------------------------------------------------------------------------------

## 7. Before real use

- Put Caddy or nginx in front with HTTPS, and set `APP_ENV=production` in `.env`.
- In the Android manifest remove `android:usesCleartextTraffic="true"` once you use https.
- Back up the database every day.
- Set the SMTP lines in `.env` if you want "forgot password" emails; without them admins can set passwords.
- Limits that protect your SIM cards are in `.env`: `MAX_CALLS_PER_MINUTE`, `MAX_SMS_PER_MINUTE`,
  `MAX_OUTBOUND_PER_DAY`, `BLOCKED_PREFIXES`, `ALLOWED_PREFIXES`.
- To run the two cores as separate servers later, replace `common/hubs.py` with Redis pub/sub.

## Rules the code enforces
- The tenant id always comes from the verified login token, never from the request.
- Another tenant's data returns 404, so its existence is not revealed.
- Phones log in with their own key (stored hashed) and can only touch their own SIMs.
- A phone retry can never create a duplicate log (unique event id per number).
- Passwords: 10+ characters with letters and digits; 5 wrong tries locks the account for 15 minutes.
- Changing or resetting a password, or disabling a user, signs them out everywhere at once.
>>>>>>> 442f190 (built a dialer project)
#   d i a l e r  
 