"""
ShopFlow — User Service  (port 8083)
======================================
Owns: user accounts, auth tokens, session records.

Intentional bugs:
  BUG_JWT_NO_EXPIRY — issued JWTs have no exp claim
  BUG_WEAK_PASSWORD — accepts passwords < 4 chars without error

Exposes:
  POST /auth/login
  POST /auth/register
  GET  /auth/validate        — validates Bearer token (called by order-service)
  GET  /users/me
  GET  /health
  GET  /logs/events
"""

import os
import uuid
import base64
import json
import hmac
import hashlib
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Bug toggles ───────────────────────────────────────────────────────────────
BUG_JWT_NO_EXPIRY   = os.getenv("BUG_JWT_NO_EXPIRY",   "false").lower() == "true"
BUG_WEAK_PASSWORD   = os.getenv("BUG_WEAK_PASSWORD",   "false").lower() == "true"

JWT_SECRET = os.getenv("JWT_SECRET", "shopflow-demo-secret-not-for-production")

# ── Structured event log ──────────────────────────────────────────────────────
_EVENT_LOG: deque = deque(maxlen=200)

def _log_event(level: str, service: str, event: str, detail: str, correlation_id: str = None):
    entry = {
        "id":             str(uuid.uuid4()),
        "timestamp":      datetime.utcnow().isoformat(),
        "level":          level,
        "service":        service,
        "event":          event,
        "detail":         detail,
        "correlation_id": correlation_id,
    }
    _EVENT_LOG.append(entry)
    logging.getLogger("user").log(
        logging.ERROR if level == "ERROR" else logging.WARNING if level == "WARN" else logging.INFO,
        "[%s] %s — %s", service, event, detail,
    )
    return entry


# ── In-memory user store ──────────────────────────────────────────────────────
_USERS = {
    "test@example.com":  {"user_id": 1, "email": "test@example.com",
                          "password_hash": "5f4dcc3b5aa765d61d8327deb882cf99",  # "password" md5
                          "name": "Test User"},
    "admin@shopflow.io": {"user_id": 2, "email": "admin@shopflow.io",
                          "password_hash": "21232f297a57a5a743894a0e4a801fc3",  # "admin" md5
                          "name": "Shop Admin"},
}
_SESSIONS: dict = {}  # token → user_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_event("INFO", "user-service", "startup", "User service started", "system")
    yield


app = FastAPI(title="ShopFlow User Service", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class LoginRequest(BaseModel):
    email:    str
    password: str


class RegisterRequest(BaseModel):
    email:    str
    password: str
    name:     str


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _issue_jwt(user_id: int, email: str) -> str:
    header  = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = {"sub": str(user_id), "email": email, "iat": int(datetime.utcnow().timestamp())}
    if not BUG_JWT_NO_EXPIRY:
        payload["exp"] = int(datetime.utcnow().timestamp()) + 3600  # 1 hour
    else:
        _log_event("WARN", "user-service", "jwt_issued_without_expiry",
                   f"user_id={user_id} email={email}", f"user-{user_id}")
    body  = _b64url(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = _b64url(hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _decode_jwt(token: str) -> Optional[dict]:
    """Decode and verify JWT. Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        sig_input = f"{header}.{body}".encode()
        expected_sig = _b64url(hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest())
        if sig != expected_sig:
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        # Check expiry if present
        exp = payload.get("exp")
        if exp and int(datetime.utcnow().timestamp()) > exp:
            _log_event("WARN", "user-service", "jwt_expired",
                       f"user_id={payload.get('sub')}", None)
            return None
        return payload
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    bugs = {k: True for k, v in {
        "BUG_JWT_NO_EXPIRY": BUG_JWT_NO_EXPIRY,
        "BUG_WEAK_PASSWORD": BUG_WEAK_PASSWORD,
    }.items() if v}
    return {"status": "ok", "service": "user-service", "bugs_active": list(bugs.keys())}


@app.post("/auth/login")
def login(req: LoginRequest):
    correlation_id = str(uuid.uuid4())
    user = _USERS.get(req.email)

    # SQL-injection style probe — if email contains SQL chars, flag it
    if any(c in req.email for c in ["'", "--", "OR ", "1=1"]):
        _log_event("ERROR", "user-service", "sql_injection_probe_detected",
                   f"email={req.email}", correlation_id)
        raise HTTPException(status_code=400, detail="Invalid input")

    if not user or _md5(req.password) != user["password_hash"]:
        _log_event("WARN", "user-service", "login_failed",
                   f"email={req.email}", correlation_id)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _issue_jwt(user["user_id"], user["email"])
    _SESSIONS[token] = user["user_id"]

    _log_event("INFO", "user-service", "login_success",
               f"user_id={user['user_id']} email={user['email']}", correlation_id)

    return {"access_token": token, "token_type": "bearer", "user_id": user["user_id"]}


@app.post("/auth/register")
def register(req: RegisterRequest):
    correlation_id = str(uuid.uuid4())

    if not BUG_WEAK_PASSWORD and len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    elif BUG_WEAK_PASSWORD and len(req.password) < 1:
        pass  # accepts any non-empty password — intentional weakness
    
    if req.email in _USERS:
        raise HTTPException(status_code=409, detail="Email already registered")

    new_id = max(u["user_id"] for u in _USERS.values()) + 1
    _USERS[req.email] = {
        "user_id":       new_id,
        "email":         req.email,
        "password_hash": _md5(req.password),
        "name":          req.name,
    }
    _log_event("INFO", "user-service", "user_registered",
               f"user_id={new_id} email={req.email}", correlation_id)
    return {"user_id": new_id, "email": req.email}


@app.get("/auth/validate")
def validate_token(authorization: str = Header(default=None)):
    """Called by order-service to validate a bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    payload = _decode_jwt(token)
    if payload is None:
        _log_event("WARN", "user-service", "token_validation_failed",
                   "invalid or expired token", None)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload.get("sub", 0))
    return {"valid": True, "user_id": user_id, "email": payload.get("email")}


@app.get("/users/me")
def get_me(authorization: str = Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    payload = _decode_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = payload.get("email")
    user = _USERS.get(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user["user_id"], "email": user["email"], "name": user["name"]}


@app.get("/logs/events")
def get_events(limit: int = 50, level: Optional[str] = None):
    events = list(reversed(list(_EVENT_LOG)))
    if level:
        events = [e for e in events if e["level"] == level.upper()]
    return {"service": "user-service", "events": events[:limit], "total": len(events)}
