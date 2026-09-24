# Haus — Native Android Terminal as a Service

A **native Android app** (Kotlin) that connects to a **persistent, always-on Docker
container** in the cloud. Each account gets exactly **one isolated container**. Sessions
persist 24/7 across reconnects, even when the phone is off.

```
┌──────────────┐    HTTPS / WSS     ┌──────────────────────────────┐
│  Android App │ ─────────────────▶ │  Haus Backend (published)    │
│  "Haus"      │   register/login   │  FastAPI + WebSocket bridge  │
│  xterm view  │ ◀──── terminal ──── │  one Docker container/user   │
└──────────────┘                    │  bash pty via `docker exec`  │
                                     └──────────────────────────────┘
```

## API

| Endpoint | Body | Notes |
|---|---|---|
| `POST /api/register` | `{username, password, email}` | Creates a container; **max 3 accounts per IP** |
| `POST /api/login` | `{username, password}` | Returns a new token |
| `GET /api/me` | `Authorization: Bearer <token>` | Current user |
| `POST /api/forgot-password` | `{username}` | Emails a 6-digit code (always same response) |
| `POST /api/reset-password` | `{username, code, new_password}` | Code is single-use, 10 min TTL |
| `WS /ws?token=...` | `{"type":"input"/"resize"}` | Terminal bridge |

The URL lives in `android/app/src/main/java/com/haus/app/util/Constants.kt`. Change
`BASE_URL` to repoint the app (must be `https://`; `wss://` is derived automatically).

## Backend (`backend/`)

- `server.py` — FastAPI app.
  - **One Docker container per account** (`haus_<username>`, `ubuntu:22.04`,
    `--memory=2g --cpus=1.0 --restart unless-stopped`). True process, filesystem and
    network isolation between users. Containers sit on a dedicated bridge network
    with inter-container communication disabled, so one account can never reach
    another's sandbox.
  - The WebSocket bridges into a `docker exec -it <container> bash -l` pty. When the app is
    backgrounded, the phone is locked, or the user logs out, the server **keeps this PTY/bash
    alive**; cwd, environment, foreground jobs and background jobs survive reconnect. Output
    is buffered in a 64 KB ring so reconnect replays the last screen. The shell is cleaned up
    only if bash exits, the container stops, or the backend itself is explicitly shut down.
  - **1 IP ⇒ max 3 accounts** (`WS_MAX_ACCOUNTS_PER_IP`, default 3), read from `X-Forwarded-For`.
  - **Forgot-password** via emailed 6-digit code (`password_resets` table, single-use,
    `WS_RESET_TTL` seconds). Anti-spam: one code per account every 3 minutes,
    plus max 5 reset requests per IP per 15 minutes (`WS_RESET_COOLDOWN`,
    `WS_RESET_IP_LIMIT`, `WS_RESET_IP_WINDOW`). Cooldown requests return the same
    generic response but do not send another email.
    Credentials are read from env **or** from `/var/lib/webshell/smtp.env` (chmod 0600,
    `KEY=VALUE` lines) so secrets never live in the repo:

    ```ini
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASS=your-16-digit-app-password
    SMTP_FROM=you@gmail.com
    ```

    Without them the code is only logged to stdout (dev mode) — the user never receives it.
    `send_code_email()` returns `False` on failure and never raises, so a broken SMTP
    config can't turn into a 500.
  - Passwords: PBKDF2-HMAC-SHA256, 100k iterations. Tokens: random 32-byte hex in SQLite.
  - Built-in **self-ping keepalive** thread so the sandbox stays warm.
- `requirements.txt` — `fastapi`, `uvicorn[standard]`, `pyjwt`.
- Run: `cd backend && uvicorn server:app --host 0.0.0.0 --port 8080`

Env vars: `WS_IMAGE`, `WS_MEM`, `WS_CPU`, `WS_MAX_ACCOUNTS_PER_IP`, `WS_RESET_TTL`,
`SMTP_*`, `KEEPALIVE_URL`, `KEEPALIVE_INTERVAL`, `HAUS_DEBUG`.

## Android app (`android/`)

Native Kotlin (minSdk 24, targetSdk 34, AGP 8.5.2, Kotlin 1.9.24). Package `com.haus.app`,
version 1.5.

- **Termux-style launcher icon** — dark rounded square with a green `>_` prompt; adaptive
  icon for API 26+ plus PNG fallbacks for 24–25.
- **Theme** — dark slate surfaces (`#0A0C10`) with a Haus-green accent (`#00E676`), Material 3,
  matching green terminal palette inside xterm.js.
- **Login** — username/password, password visibility toggle, progress indicator,
  *Forgot password?* link, and server error messages surfaced verbatim.
- **Register** — username + **email** + password + confirm, with client-side validation
  (username `a-z0-9_`, 3–20 chars; password ≥ 6; valid email) before hitting the server.
- **Forgot password** — two-step flow: request code → enter code + new password.
- **Terminal** — xterm.js in a WebView for glyph rendering (the only web component; auth,
  networking, storage and UI are native Kotlin), an OkHttp WebSocket for I/O, a native
  **Termux-style extra-keys bar** (ESC, TAB, CTRL, ALT, arrows, ENTER, `/ | ~ . , * -`),
  status indicator, and **automatic reconnect** (5 attempts with backoff) instead of logging
  out on a transient network blip. The extra-keys bar can be hidden/shown with **Keys/Hide**;
  its preference is remembered. Only an invalid token (401/403) forces re-login.
  - **CTRL / ALT are sticky modifiers.** Tap **CTRL** (or **ALT**) to light it up, then type
    the next key — including letters on the soft keyboard — and the modifier is applied
    automatically: `CTRL`+`C` sends the real `Ctrl+C` interrupt, `CTRL`+`D` an EOF, `ALT`+`F`
    an `ESC f` style sequence, etc. The modifier clears after that one keystroke.
- **Welcome banner** — each container gets `/usr/local/bin/haus-banner` and a login hook.
  It explains the private container, 24/7 behavior and useful commands. Run `haus-banner off`
  to hide it on future terminal opens; run `haus-banner on` to show it again, or simply
  type `haus-banner` to display it once.
- **9Router Dashboard gateway** — the Android terminal header has **Open Web UI**. It creates
  a short-lived, single-use Haus grant, then proxies only the authenticated user’s internal
  port `20128` (9Router’s default Dashboard port) through `/router`. The long-lived Haus token
  is never put in the browser URL, no Docker host port is published, and arbitrary host/port
  proxying is rejected. Install/start 9Router inside your container on `0.0.0.0:20128`, then
  tap the button; the Dashboard opens in the restricted in-app WebView. If the service is not
  running, the app shows a clear notice instead of a blank page.

### 9Router quick start inside a container

The Haus base image includes Git, curl, and the `haus-fix-clone` helper. 9Router’s official
Docker/source instructions use port `20128`. After installing it, make sure its web service
binds to `0.0.0.0:20128` (not only `127.0.0.1`) so the Haus gateway can reach it:

```bash
# Check the service before opening the app button
curl -I http://127.0.0.1:20128/dashboard
# 9Router should be kept running in the container (for example via nohup/tmux/supervisor)
```

The gateway only supports 9Router’s fixed internal port; it is not a generic port forwarder.
See the [official 9Router docs](https://github.com/decolua/9router) for installation and provider setup.

### Build

```bash
cd android
export ANDROID_HOME=/root/android-sdk
./gradlew assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk
```

## Download

The latest Android app is published as a prebuilt **APK** on the
[Releases](https://github.com/sahidwahid12/Haus/releases/latest) page of this repository — no build tools needed.
Install it on any Android 7.0+ (API 24+) device, then open **Haus** and register an
account to get your own always-on container.

> Sideloading note: because the APK is distributed directly (not via Google Play),
> Android will ask you to allow "Install unknown apps" for your file manager the
> first time. The app only talks to your Haus backend over HTTPS/WSS.

## Security notes

- Each user lives in their own container, so they cannot read another user's files.
- Passwords are PBKDF2-HMAC-SHA256 hashed; reset codes are single-use and expire.
- Tokens are random 32-byte hex, stored server-side and in the device DataStore.
- Host paths (`/root`, app dir, DB) are chmod'd to `0700`/`0600` on startup.
- CORS is open for demo convenience; restrict `allow_origins` before public production use.
