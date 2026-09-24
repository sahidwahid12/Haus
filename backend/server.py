#!/usr/bin/env python3
"""
Haus Backend
=============
- REST API: register / login / me / forgot-password / reset-password
- One isolated Docker container per account (true per-user "room")
- Persistent 24/7 container; WebSocket bridges to a `docker exec bash` pty session
- 1 IP can create at most N accounts
- Forgot-password via emailed verification code (pluggable SMTP or dev-log fallback)

Run:  uvicorn server:app --host 0.0.0.0 --port 8080
"""

import asyncio
import hashlib
import json
import os
import pty
import secrets
import signal
import struct
import fcntl
import termios
import subprocess
import sqlite3
import time
import re
import smtplib
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from email.message import EmailMessage
from email.utils import formataddr

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path("/var/lib/webshell/webshell.db")
DB_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))
SECRET = os.environ.get("WEBSHELL_SECRET", secrets.token_hex(32))

# Docker / container settings
BASE_IMAGE = os.environ.get("WS_IMAGE", "ubuntu:22.04")
# 512m OOM-killed real workloads (npm install on a monorepo died with SIGKILL /
# exit 137). 2g is a cap rather than a reservation, so idle containers stay small.
MEM_LIMIT = os.environ.get("WS_MEM", "2g")
CPU_LIMIT = os.environ.get("WS_CPU", "1.0")
# Each account is shelled into a non-root user (no sudo) inside its own
# container, so a user is an ordinary account. Root access to the runtime is
# provided separately through the SSH bridge, never through this shell.
SHELL_USER = os.environ.get("WS_SHELL_USER", "haus")
SHELL_UID = os.environ.get("WS_SHELL_UID", "1000")
# Every user container is attached to this dedicated bridge network, which has
# inter-container communication (ICC) DISABLED. That way one account's sandbox
# can never open a TCP/ICMP connection to another account's sandbox, while the
# backend (on the host) and outbound internet (NAT) still work.
ISO_NETWORK = os.environ.get("WS_NETWORK", "haus_iso")
MAX_ACCOUNTS_PER_IP = int(os.environ.get("WS_MAX_ACCOUNTS_PER_IP", "3"))
RESET_CODE_TTL = int(os.environ.get("WS_RESET_TTL", "600"))  # seconds
# Anti-spam for password-reset emails.
RESET_COOLDOWN = int(os.environ.get("WS_RESET_COOLDOWN", "180"))   # sek per account
RESET_IP_LIMIT = int(os.environ.get("WS_RESET_IP_LIMIT", "5"))     # requests per IP
RESET_IP_WINDOW = int(os.environ.get("WS_RESET_IP_WINDOW", "900")) # 15 menit
ROUTER_PORT = 20128
ROUTER_GRANT_TTL = int(os.environ.get("WS_ROUTER_GRANT_TTL", "120"))
ROUTER_SESSION_TTL = int(os.environ.get("WS_ROUTER_SESSION_TTL", "28800"))
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "https://a0b25aa3ce76bd678.sg2.agentos-app.run").rstrip("/")
ROUTER_BODY_MAX = 8 * 1024 * 1024

# SMTP (optional). If unset, codes are logged to stdout (dev mode).
# Secrets are read from a 0600 file so they never live in the repo or in argv.
SMTP_ENV_FILE = Path(os.environ.get("SMTP_ENV_FILE", "/var/lib/webshell/smtp.env"))


def _load_smtp_env() -> dict:
    cfg = {}
    try:
        if SMTP_ENV_FILE.is_file():
            for line in SMTP_ENV_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return cfg


_SMTP_CFG = _load_smtp_env()


def _cfg(key: str, default: str = "") -> str:
    """Environment wins; otherwise fall back to the smtp.env file."""
    return os.environ.get(key) or _SMTP_CFG.get(key, default)


SMTP_HOST = _cfg("SMTP_HOST")
SMTP_PORT = int(_cfg("SMTP_PORT", "587"))
SMTP_USER = _cfg("SMTP_USER", "")
SMTP_PASS = _cfg("SMTP_PASS", "")
SMTP_FROM = _cfg("SMTP_FROM", SMTP_USER or "noreply@haus.app")


def harden_host():
    """Lock down host paths so the server source/DB cannot be read by container users."""
    try:
        os.chmod("/root", 0o700)
        for d in (BASE_DIR, BASE_DIR.parent):
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
        try:
            if SMTP_ENV_FILE.is_file():
                os.chmod(SMTP_ENV_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        pass


harden_host()


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            container_name TEXT UNIQUE NOT NULL,
            email TEXT,
            register_ip TEXT,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS router_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('grant', 'session')),
            expires_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_router_sessions_token ON router_sessions(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_router_sessions_user ON router_sessions(user_id)")
    conn.commit()
    conn.close()


init_db()


# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------
_USER_RE = re.compile(r"^[a-z0-9_]{3,20}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + ":" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"


# --- Anti-spam untuk permintaan kode reset (in-memory, per IP) ---------------
_RESET_IP_HITS: dict[str, list[float]] = {}


def reset_ip_allowed(ip: str) -> bool:
    """Batasi jumlah permintaan kode per IP dalam jendela waktu tertentu.

    Ini yang mencegah spam/penyalahgunaan secara umum. Batasannya seragam untuk
    semua IP, sehingga tidak membocorkan apakah sebuah akun ada atau tidak.
    """
    now = time.time()
    hits = [t for t in _RESET_IP_HITS.get(ip, []) if now - t < RESET_IP_WINDOW]
    if len(hits) >= RESET_IP_LIMIT:
        _RESET_IP_HITS[ip] = hits
        return False
    hits.append(now)
    _RESET_IP_HITS[ip] = hits
    # cegah map tumbuh tanpa batas
    if len(_RESET_IP_HITS) > 5000:
        for k in list(_RESET_IP_HITS):
            v = _RESET_IP_HITS.get(k) or []
            if not v or now - max(v) > RESET_IP_WINDOW:
                _RESET_IP_HITS.pop(k, None)
    return True


# ----------------------------------------------------------------------------
# Docker container provisioning (one container per account)
# ----------------------------------------------------------------------------
def container_is_running(name: str) -> bool:
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() == "true"
    except Exception:
        return False


def ensure_iso_network():
    """Create the isolated per-user bridge network (ICC disabled) if missing.

    Containers live here so they cannot talk to each other; the host (backend)
    and outbound internet (NAT) remain reachable.
    """
    try:
        out = subprocess.run(
            ["docker", "network", "ls", "--filter", f"name=^{ISO_NETWORK}$",
             "--format", "{{.Name}}"], capture_output=True, text=True, timeout=10)
        if ISO_NETWORK in out.stdout.split():
            return
        subprocess.run([
            "docker", "network", "create", "--driver", "bridge",
            "--opt", "com.docker.network.bridge.enable_icc=false",
            "--opt", "com.docker.network.bridge.enable_ip_masquerade=true",
            ISO_NETWORK],
            check=True, capture_output=True, timeout=30)
        print(f"[HAUS] created isolated network {ISO_NETWORK}", flush=True)
    except Exception as e:
        print(f"[HAUS] ensure_iso_network failed: {e}", flush=True)


def create_container(name: str):
    # Remove a stale container with the same name if it exists but is not running
    try:
        existing = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{name}$",
             "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10)
        if existing.stdout.strip() == name:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
    except Exception:
        pass
    ensure_iso_network()
    subprocess.run([
        "docker", "run", "-d", "--name", name, "--hostname", name,
        f"--memory={MEM_LIMIT}", f"--cpus={CPU_LIMIT}", "--restart", "unless-stopped",
        "--network", ISO_NETWORK,
        BASE_IMAGE, "sleep", "infinity"],
        check=True, capture_output=True, timeout=120)
    provision_container(name)


BANNER_SRC = BASE_DIR / "haus-banner.sh"
BANNER_HOOK = ('if [ -x /usr/local/bin/haus-banner ] && '
               '[ ! -f "$HOME/.haus_banner_off" ]; then haus-banner; fi\n')


def _ensure_shell_user(name: str):
    """Create a non-root shell user (no sudo, no extra groups) inside the container."""
    try:
        subprocess.run(["docker", "exec", name, "bash", "-c",
            f"id {SHELL_USER} >/dev/null 2>&1 || "
            f"useradd -m -s /bin/bash -u {SHELL_UID} {SHELL_USER}; "
            f"gpasswd -d {SHELL_USER} sudo >/dev/null 2>&1 || true; "
            f"usermod -G '' {SHELL_USER} 2>/dev/null || true; "
            f"mkdir -p /home/{SHELL_USER} && chown -R {SHELL_UID}:{SHELL_UID} /home/{SHELL_USER}; "
            f"chown -R {SHELL_UID}:{SHELL_UID} /usr/local/lib/hermes-agent 2>/dev/null || true"
        ], capture_output=True, timeout=60)
    except Exception as e:
        print(f"[HAUS] shell user provisioning failed: {e}", flush=True)


def provision_container(name: str):
    """Drop the Haus welcome banner into the container and run it on bash login.

    Best effort only: if this fails the container is still usable, the user just
    won't see the banner.
    """
    _ensure_shell_user(name)
    hook_tmp = "/tmp/.haus_banner_hook_%s" % name
    try:
        if BANNER_SRC.is_file():
            subprocess.run(
                ["docker", "cp", str(BANNER_SRC), f"{name}:/usr/local/bin/haus-banner"],
                capture_output=True, timeout=30)
            subprocess.run(
                ["docker", "exec", name, "chmod", "+x", "/usr/local/bin/haus-banner"],
                capture_output=True, timeout=30)
            with open(hook_tmp, "w") as fh:
                fh.write("\n" + BANNER_HOOK)
            subprocess.run(
                ["docker", "cp", hook_tmp, f"{name}:/tmp/.haus_banner_hook"],
                capture_output=True, timeout=30)
            subprocess.run(
                ["docker", "exec", name, "bash", "-c",
                 f"grep -q haus-banner /home/{SHELL_USER}/.bashrc 2>/dev/null || "
                 f"cat /tmp/.haus_banner_hook >> /home/{SHELL_USER}/.bashrc"],
                capture_output=True, timeout=30)
    except Exception as e:
        print(f"[HAUS] banner provisioning failed: {e}", flush=True)
    finally:
        try:
            os.unlink(hook_tmp)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Email (pluggable: real SMTP if configured, else dev-log)
# ----------------------------------------------------------------------------
def send_code_email(to_addr: str, code: str) -> bool:
    """Send the reset code. Returns True if the mail was actually handed to SMTP.

    Without SMTP configured this falls back to logging the code (dev mode),
    which means the user will never see it - the caller still reports success
    to avoid leaking which accounts exist.
    """
    if not SMTP_HOST:
        print(f"[HAUS] password reset code for {to_addr}: {code}", flush=True)
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = "Haus password reset code"
        msg["From"] = formataddr(("Haus", SMTP_FROM))
        msg["To"] = to_addr
        msg.set_content(
            f"Your Haus verification code is: {code}\n\n"
            f"This code expires in {RESET_CODE_TTL // 60} minutes.\n"
            "If you did not request this, you can safely ignore this email.\n"
        )
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.ehlo()
            if SMTP_PORT not in (25, 465):
                s.starttls()
                s.ehlo()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"[HAUS] reset code emailed to {to_addr}", flush=True)
        return True
    except Exception as e:
        print(f"[HAUS] email send failed: {e}", flush=True)
        return False


# ----------------------------------------------------------------------------
# Persistent per-user Docker-backed shell session
# ----------------------------------------------------------------------------
class UserSession:
    """A persistent Docker container per user, with a WebSocket-bridged bash pty.

    The container itself is the 24/7 "room" (filesystem/process/network isolated).
    The WebSocket bridge uses `docker exec -it bash` with a pty. The exec process
    is intentionally kept alive when the phone/app disconnects, so foreground and
    background processes in the shell survive logout/reconnect. It is only cleaned
    up when the shell itself exits or the backend explicitly tears it down.
    """

    RING_MAX = 64 * 1024

    def __init__(self, user: dict, loop: asyncio.AbstractEventLoop):
        self.user = user
        self.container = user["container_name"]
        self.loop = loop
        self.subscribers = set()
        self.ring = bytearray()
        self.cols = 80
        self.rows = 24
        self.master_fd = None
        self.proc = None
        self.exec_alive = False
        if not container_is_running(self.container):
            create_container(self.container)
        self._spawn_exec()

    def _spawn_exec(self):
        master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            ["docker", "exec", "-it", "-u", SHELL_USER, self.container, "bash", "-l"],
            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
        )
        os.close(slave)
        self.master_fd = master
        self.resize(self.rows, self.cols)
        self.loop.add_reader(master, self._on_read)
        self.exec_alive = True

    def _on_read(self):
        try:
            data = os.read(self.master_fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._cleanup_exec()
            return
        self.ring.extend(data)
        if len(self.ring) > self.RING_MAX:
            self.ring = self.ring[-self.RING_MAX:]
        for q in list(self.subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                pass

    def _cleanup_exec(self):
        if not self.exec_alive:
            return
        self.exec_alive = False
        try:
            self.loop.remove_reader(self.master_fd)
        except Exception:
            pass
        try:
            os.close(self.master_fd)
        except Exception:
            pass
        try:
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass
        for q in list(self.subscribers):
            try:
                q.put_nowait(b"\r\n\x1b[31m[session ended - reconnect to resume]\x1b[0m\r\n")
            except Exception:
                pass

    def write(self, data: bytes):
        if not self.exec_alive:
            return
        if os.environ.get("HAUS_DEBUG"):
            print(f"[DBG] write {len(data)}b: {data[:60]!r} fd={self.master_fd} alive={self.exec_alive}", flush=True)
        try:
            os.write(self.master_fd, data)
        except OSError as e:
            if os.environ.get("HAUS_DEBUG"):
                print(f"[DBG] write err {e}", flush=True)

    def resize(self, rows: int, cols: int):
        self.rows = max(1, min(400, rows))
        self.cols = max(1, min(800, cols))
        if not self.exec_alive:
            return
        try:
            subprocess.run(
                ["docker", "resize", "-s", f"{self.rows}x{self.cols}", self.container],
                timeout=5, capture_output=True)
        except Exception:
            pass

    def attach(self) -> asyncio.Queue:
        if not self.exec_alive:
            try:
                self._spawn_exec()
            except Exception:
                pass
        q = asyncio.Queue()
        if self.ring:
            q.put_nowait(bytes(self.ring))
        self.subscribers.add(q)
        return q

    def detach(self, q: asyncio.Queue):
        self.subscribers.discard(q)
        # Do NOT kill the docker exec when the last WebSocket disconnects.
        # The app may be backgrounded, the phone may be locked, or the user may
        # log out and back in. Keeping this PTY/bash alive is what preserves cwd,
        # env and foreground/background processes across that transition.
        # `_on_read` continues draining output into the ring buffer while detached.
        # Cleanup happens only when bash exits, the container stops, or the
        # backend process is explicitly shut down.


SESSIONS: dict[int, UserSession] = {}


async def get_session(user: dict) -> UserSession:
    loop = asyncio.get_event_loop()
    s = SESSIONS.get(user["id"])
    if s is None or not container_is_running(s.container):
        if s is None and not container_is_running(user["container_name"]):
            await loop.run_in_executor(
                None, lambda: create_container(user["container_name"]))
        s = UserSession(user, loop)
        SESSIONS[user["id"]] = s
    return s


# ----------------------------------------------------------------------------
# Auth logic
# ----------------------------------------------------------------------------
def authenticate_token(token: str):
    conn = get_db()
    row = conn.execute(
        "SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?",
        (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    conn = get_db()
    conn.execute("INSERT INTO tokens (token, user_id, created_at) VALUES (?,?,?)",
                 (token, user_id, time.time()))
    conn.commit()
    conn.close()
    return token


# ----------------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------------
app = FastAPI(title="Haus API")


# ----------------------------------------------------------------------------
# Per-user 9Router Dashboard proxy (fixed internal port 20128)
# ----------------------------------------------------------------------------
_ROUTER_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cookie_without_haus(cookie: str) -> str:
    """Forward only upstream app cookies; never leak Haus auth cookie upstream."""
    kept = []
    for item in cookie.split(";"):
        if "=" not in item:
            continue
        key, value = item.strip().split("=", 1)
        if key != "haus_router_session":
            kept.append(f"{key}={value}")
    return "; ".join(kept)


def _router_user_from_cookie(cookie: str):
    if not cookie:
        return None
    token = None
    for item in cookie.split(";"):
        if "=" in item:
            key, value = item.strip().split("=", 1)
            if key == "haus_router_session":
                token = value
                break
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT u.* FROM router_sessions r JOIN users u ON u.id=r.user_id "
        "WHERE r.token_hash=? AND r.kind='session' AND r.expires_at>?",
        (_token_hash(token), time.time())).fetchone()
    conn.close()
    return dict(row) if row else None


def _router_container_ip(container_name: str) -> str | None:
    """Resolve only a DB-owned container to its Docker bridge IP."""
    if not re.fullmatch(r"haus_[a-z0-9_]{3,20}", container_name or ""):
        return None
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
            capture_output=True, text=True, timeout=10)
        ip = result.stdout.strip()
        if ip and re.fullmatch(r"[0-9a-fA-F:.]+", ip):
            return ip
    except Exception:
        pass
    return None


def _proxy_headers(request: Request, cookie: str) -> dict[str, str]:
    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in _ROUTER_HOP_HEADERS and key.lower() != "authorization":
            headers[key] = value
    upstream_cookie = _cookie_without_haus(cookie)
    if upstream_cookie:
        headers["cookie"] = upstream_cookie
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-prefix"] = "/router"
    return headers


def _rewrite_router_location(value: str, upstream: str) -> str:
    if value.startswith(upstream):
        suffix = value[len(upstream):] or "/"
        return "/router" + (suffix if suffix.startswith("/") else "/" + suffix)
    if value.startswith("/") and not value.startswith("//"):
        return "/router" + value
    return value


def _rewrite_router_body(content: bytes, content_type: str) -> bytes:
    """Make root-relative app URLs work below the authenticated /router prefix."""
    kind = content_type.lower()
    if not any(part in kind for part in ("text/html", "javascript", "text/css", "application/json")):
        return content
    # 9Router is a Next.js app and emits paths such as /api, /_next and
    # /dashboard inside HTML/JS/CSS. Prefix quoted root paths without touching
    # absolute URLs or protocol-relative URLs.
    for quote in (b'"', b"'", b"`"):
        content = content.replace(quote + b"/", quote + b"/router/")
    return content


def _require_router_user(request: Request):
    user = _router_user_from_cookie(request.headers.get("cookie", ""))
    if not user:
        raise HTTPException(401, "Router session expired. Open the Dashboard again.")
    return user


@app.post("/api/router/session")
async def create_router_session(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    user = authenticate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Missing or invalid token")
    if not container_is_running(user["container_name"]):
        raise HTTPException(503, "Your container is not running")
    if not _router_container_ip(user["container_name"]):
        raise HTTPException(503, "Router gateway is unavailable")

    grant = secrets.token_urlsafe(48)
    conn = get_db()
    # Keep at most a few old grants/sessions per user.
    conn.execute("DELETE FROM router_sessions WHERE user_id=? OR expires_at<?", (user["id"], time.time()))
    conn.execute(
        "INSERT INTO router_sessions (user_id, token_hash, kind, expires_at, used, created_at) "
        "VALUES (?,?, 'grant', ?, 0, ?)",
        (user["id"], _token_hash(grant), time.time() + ROUTER_GRANT_TTL, time.time()))
    conn.commit()
    conn.close()
    return {
        "url": f"{PUBLIC_BASE_URL}/router/access/{quote(grant, safe='')}",
        "expires_at": int(time.time() + ROUTER_GRANT_TTL),
    }


@app.get("/router/access/{grant}")
async def exchange_router_grant(grant: str):
    conn = get_db()
    row = conn.execute(
        "SELECT user_id FROM router_sessions WHERE token_hash=? AND kind='grant' "
        "AND used=0 AND expires_at>?", (_token_hash(grant), time.time())).fetchone()
    if not row:
        conn.close()
        raise HTTPException(401, "Router link expired. Open the Dashboard again.")
    conn.execute("UPDATE router_sessions SET used=1 WHERE token_hash=?", (_token_hash(grant),))
    session = secrets.token_urlsafe(48)
    conn.execute(
        "INSERT INTO router_sessions (user_id, token_hash, kind, expires_at, used, created_at) "
        "VALUES (?,?,'session',?,?,?)",
        (row["user_id"], _token_hash(session), time.time() + ROUTER_SESSION_TTL, 1, time.time()))
    conn.commit()
    conn.close()
    response = RedirectResponse("/router/dashboard", status_code=303)
    response.set_cookie(
        "haus_router_session", session, max_age=ROUTER_SESSION_TTL,
        httponly=True, secure=True, samesite="strict", path="/router")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.api_route("/router", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.api_route("/router/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def router_http_proxy(request: Request, path: str = ""):
    user = _require_router_user(request)
    ip = _router_container_ip(user["container_name"])
    if not ip or not container_is_running(user["container_name"]):
        raise HTTPException(503, "9Router is not running in your container")
    body = await request.body()
    if len(body) > ROUTER_BODY_MAX:
        raise HTTPException(413, "Request body too large")
    suffix = "/" + path.lstrip("/")
    upstream = f"http://{ip}:{ROUTER_PORT}"
    url = upstream + suffix
    if request.url.query:
        url += "?" + request.url.query
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            upstream_response = await client.request(
                request.method, url, content=body, headers=_proxy_headers(
                    request, request.headers.get("cookie", "")))
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"9Router is unavailable: {type(exc).__name__}")
    headers = {}
    for key, value in upstream_response.headers.items():
        if key.lower() in _ROUTER_HOP_HEADERS or key.lower() == "set-cookie":
            continue
        headers[key] = value
    if "location" in headers:
        headers["location"] = _rewrite_router_location(headers["location"], upstream)
    ctype = upstream_response.headers.get("content-type", "")
    content = _rewrite_router_body(upstream_response.content, ctype)
    if content != upstream_response.content:
        headers.pop("content-length", None)
        headers.pop("content-encoding", None)
    return Response(content=content, status_code=upstream_response.status_code, headers=headers,
                    media_type=None)


@app.websocket("/router/{path:path}")
async def router_ws_proxy(websocket: WebSocket, path: str = ""):
    user = _router_user_from_cookie(websocket.headers.get("cookie", ""))
    if not user:
        await websocket.close(code=4401)
        return
    ip = _router_container_ip(user["container_name"])
    if not ip or not container_is_running(user["container_name"]):
        await websocket.close(code=4503)
        return
    upstream_url = f"ws://{ip}:{ROUTER_PORT}/" + path.lstrip("/")
    if websocket.query_params:
        upstream_url += "?" + str(websocket.query_params)
    cookie = _cookie_without_haus(websocket.headers.get("cookie", ""))
    extra = {"Cookie": cookie} if cookie else None
    try:
        async with websockets.connect(upstream_url, additional_headers=extra, open_timeout=8,
                                      ping_interval=20, max_size=8 * 1024 * 1024) as upstream_ws:
            await websocket.accept()
            async def client_to_upstream():
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    data = message.get("text") if message.get("text") is not None else message.get("bytes")
                    if data is not None:
                        await upstream_ws.send(data)
            async def upstream_to_client():
                async for data in upstream_ws:
                    if isinstance(data, bytes):
                        await websocket.send_bytes(data)
                    else:
                        await websocket.send_text(data)
            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup():
    # Make sure the isolated (ICC-disabled) network exists before anything
    # tries to attach a container to it.
    ensure_iso_network()

    # Best-effort: pre-pull the base image so first container creation is fast.
    # For a locally-built Haus image this simply fails harmlessly; the image is
    # already present in the Docker daemon.
    def _pull():
        try:
            subprocess.run(["docker", "pull", BASE_IMAGE], capture_output=True, timeout=300)
        except Exception:
            pass
    threading.Thread(target=_pull, name="haus-image-pull", daemon=True).start()

    # Existing accounts also receive the welcome banner. This is deliberately
    # best-effort so a single stopped container cannot block server startup.
    def _provision_existing():
        try:
            conn = get_db()
            rows = conn.execute("SELECT container_name FROM users").fetchall()
            conn.close()
            for row in rows:
                name = row["container_name"]
                if container_is_running(name):
                    provision_container(name)
        except Exception as e:
            print(f"[HAUS] existing-container provisioning skipped: {e}", flush=True)
    threading.Thread(target=_provision_existing, name="haus-banner-existing",
                     daemon=True).start()
    start_keepalive()


class RegisterReq(BaseModel):
    username: str
    password: str
    email: str = ""


class LoginReq(BaseModel):
    username: str
    password: str


class ForgotReq(BaseModel):
    username: str


class ResetReq(BaseModel):
    username: str
    code: str
    new_password: str


@app.get("/")
def root():
    return {"service": "Haus", "status": "ok", "sessions": len(SESSIONS)}


ROOT_SSH_KEY_PATH = os.environ.get("WS_ROOT_SSH_KEY", "/var/lib/webshell/root_ssh_key")
# Only these accounts may fetch the runtime root key (the SSH bridge). Everyone
# else gets 403, so an ordinary user cannot use the bridge to reach another
# user's container.
ROOT_SSH_USERS = {u.strip() for u in
                  os.environ.get("WS_ROOT_SSH_USERS", "broyaseele4").split(",") if u.strip()}


def _runtime_ip() -> str:
    # A sibling sandbox container reaches this runtime's sshd through the host.
    # Prefer the isolated network's gateway (the host itself) because that is
    # always reachable from inside any container attached to ISO_NETWORK.
    try:
        out = subprocess.run(
            ["docker", "network", "inspect", "-f",
             "{{range .IPAM.Config}}{{.Gateway}}{{end}}", ISO_NETWORK],
            capture_output=True, text=True, timeout=5).stdout.strip().split()
        if out:
            return out[0]
    except Exception:
        pass
    # Fall back to the docker0 gateway, then any host IP.
    try:
        out = subprocess.run(
            ["bash", "-c",
             "ip -4 addr show docker0 2>/dev/null | awk '/inet/{print $2}' | cut -d/ -f1"],
            capture_output=True, text=True, timeout=5).stdout.strip().split()
        if out:
            return out[0]
    except Exception:
        pass
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True,
                              text=True, timeout=5).stdout.split()
        return out[0] if out else ""
    except Exception:
        return ""


@app.get("/api/root-ssh")
async def root_ssh_badge(request: Request):
    """Dedicated root-access bridge badge for the runtime.

    This is intentionally separate from the per-user non-root app shell: it
    gives root control of the runtime (e.g. to reach any container via docker)
    without ever granting root inside a user's own sandbox shell.
    """
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    user = authenticate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Missing or invalid token")
    if user["username"] not in ROOT_SSH_USERS:
        raise HTTPException(403, "Your account is not allowed to use the root SSH bridge")
    key = ""
    try:
        key = Path(ROOT_SSH_KEY_PATH).read_text()
    except Exception:
        key = ""
    try:
        all_ips = subprocess.run(["hostname", "-I"], capture_output=True,
                                  text=True, timeout=5).stdout.split()
    except Exception:
        all_ips = []
    return {
        "host": _runtime_ip(),
        "hosts": all_ips,
        "port": 22,
        "user": "root",
        "private_key": key,
        "connect": "ssh -i haus_root_key root@<host>  (run from another sandbox container)",
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/register")
async def register(req: RegisterReq, request: Request):
    username = req.username.strip().lower()
    if not _USER_RE.match(username):
        raise HTTPException(400, "Username must be 3-20 chars: a-z 0-9 _")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    email = req.email.strip().lower()
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")

    ip = client_ip(request)
    conn = get_db()
    # 1 IP -> max N accounts
    ip_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE register_ip=?", (ip,)).fetchone()[0]
    if ip_count >= MAX_ACCOUNTS_PER_IP:
        conn.close()
        raise HTTPException(429,
            f"Maximum {MAX_ACCOUNTS_PER_IP} accounts per IP reached")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        conn.close()
        raise HTTPException(409, "Username already taken")

    container_name = "haus_" + username
    try:
        await asyncio.get_event_loop().run_in_executor(None, create_container, container_name)
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Failed to provision container: {e}")

    cur = conn.execute(
        "INSERT INTO users (username, password, container_name, email, register_ip, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (username, hash_password(req.password), container_name, email or None,
         ip, time.time()))
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    token = create_token(user_id)
    try:
        user = dict(get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        await get_session(user)  # eagerly start the 24/7 container + session
    except Exception:
        pass
    return {"token": token, "username": username, "container": container_name}


@app.post("/api/login")
async def login(req: LoginReq):
    username = req.username.strip().lower()
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not verify_password(req.password, row["password"]):
        conn.close()
        raise HTTPException(401, "Invalid username or password")
    token = create_token(row["id"])
    conn.close()
    return {"token": token, "username": username, "container": row["container_name"]}


@app.get("/api/me")
async def me(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "Missing token")
    user = authenticate_token(token)
    if not user:
        raise HTTPException(401, "Invalid token")
    return {"username": user["username"], "container": user["container_name"]}


@app.post("/api/forgot-password")
async def forgot_password(req: ForgotReq, request: Request):
    # Batas per IP. Seragam untuk semua IP -> tidak membocorkan eksistensi akun.
    if not reset_ip_allowed(client_ip(request)):
        raise HTTPException(429, "Too many reset requests. Please try again later.")

    username = req.username.strip().lower()
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    # Selalu kembalikan respons yang sama supaya tidak ada user enumeration.
    if row and row["email"]:
        # Cooldown per akun: kalau masih terlalu cepat, LEWATI pengiriman tapi
        # tetap balas "ok". Jadi inbox tidak di-spam tanpa membocorkan apa pun.
        last = conn.execute(
            "SELECT created_at FROM password_resets WHERE user_id=? "
            "ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
        waited = time.time() - last["created_at"] if last else None
        if waited is not None and waited < RESET_COOLDOWN:
            print(f"[HAUS] reset cooldown aktif untuk {username} "
                  f"({int(RESET_COOLDOWN - waited)}s lagi)", flush=True)
        else:
            code = f"{secrets.randbelow(1000000):06d}"
            conn.execute(
                "INSERT INTO password_resets (user_id, code, expires_at, used, created_at) "
                "VALUES (?,?,?,0,?)",
                (row["id"], code, time.time() + RESET_CODE_TTL, time.time()))
            conn.commit()
            send_code_email(row["email"], code)
    conn.close()
    return {"ok": True, "message": "If the account exists, a code was sent to its email."}


@app.post("/api/reset-password")
async def reset_password(req: ResetReq):
    username = req.username.strip().lower()
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Account not found")
    reset = conn.execute(
        "SELECT * FROM password_resets WHERE user_id=? AND code=? AND used=0 "
        "AND expires_at>? ORDER BY id DESC LIMIT 1",
        (row["id"], req.code, time.time())).fetchone()
    if not reset:
        conn.close()
        raise HTTPException(400, "Invalid or expired code")
    conn.execute("UPDATE password_resets SET used=1 WHERE id=?", (reset["id"],))
    conn.execute("UPDATE users SET password=? WHERE id=?",
                 (hash_password(req.new_password), row["id"]))
    # invalidate existing sessions/tokens for safety
    conn.execute("DELETE FROM tokens WHERE user_id=?", (row["id"],))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Password updated. Please login again."}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token") or ""
    user = authenticate_token(token)
    if not user:
        await websocket.send_text(json.dumps({"type": "error", "message": "unauthorized"}))
        await websocket.close()
        return

    session = await get_session(user)
    queue = session.attach()

    # IMPORTANT: Starlette/uvicorn permits only ONE pending receive() per
    # WebSocket - "cannot call recv while another coroutine is already waiting
    # for the next message". So we keep a single long-lived recv task and only
    # renew whichever task actually completed.
    recv_task = asyncio.ensure_future(websocket.receive_text())
    q_task = asyncio.ensure_future(queue.get())
    try:
        while True:
            done, _ = await asyncio.wait(
                {recv_task, q_task}, return_when=asyncio.FIRST_COMPLETED)

            if q_task in done:
                data = q_task.result()
                try:
                    await websocket.send_text(json.dumps(
                        {"type": "output", "data": data.decode("utf-8", "replace")}))
                except Exception:
                    break
                q_task = asyncio.ensure_future(queue.get())

            if recv_task in done:
                try:
                    raw = recv_task.result()
                except WebSocketDisconnect:
                    break
                try:
                    obj = json.loads(raw)
                except Exception:
                    obj = None
                if isinstance(obj, dict):
                    kind = obj.get("type")
                    if kind == "input":
                        session.write(str(obj.get("data", "")).encode("utf-8", "replace"))
                    elif kind == "resize":
                        try:
                            session.resize(int(obj.get("rows", 24)), int(obj.get("cols", 80)))
                        except (TypeError, ValueError):
                            pass
                recv_task = asyncio.ensure_future(websocket.receive_text())
    except WebSocketDisconnect:
        pass
    except Exception:
        if os.environ.get("HAUS_DEBUG"):
            import traceback
            print("[HAUS] ws error:", flush=True)
            traceback.print_exc()
    finally:
        for t in (recv_task, q_task):
            t.cancel()
        session.detach(queue)


# ----------------------------------------------------------------------------
# Keepalive (bonus): ping our own health endpoint so the sandbox stays awake.
# ----------------------------------------------------------------------------
def start_keepalive():
    url = os.environ.get("KEEPALIVE_URL") or \
        "https://a0b25aa3ce76bd678.sg2.agentos-app.run/health"
    try:
        interval = max(10, int(os.environ.get("KEEPALIVE_INTERVAL", "300")))
    except ValueError:
        interval = 300

    def _loop():
        while True:
            time.sleep(interval)
            try:
                req = urllib.request.Request(
                    url, method="GET",
                    headers={"User-Agent": "Haus-KeepAlive"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    r.read()
            except Exception:
                pass

    threading.Thread(target=_loop, name="haus-keepalive", daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    print(f"Haus backend on http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
