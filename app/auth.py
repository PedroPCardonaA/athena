import hmac
import os
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import db

ph = PasswordHasher()
COOKIE = "ideas_session"
SESSION_MAX_AGE = 7 * 24 * 3600
COOKIE_SECURE = os.environ.get("IDEAS_COOKIE_SECURE", "0") == "1"

_attempts: list[float] = []
MAX_ATTEMPTS, WINDOW = 10, 300


def _setting(con, key):
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def _set(con, key, value):
    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
    con.commit()


def bootstrap(con):
    """Create the session secret, and the password hash from env on first run."""
    if not _setting(con, "secret"):
        _set(con, "secret", secrets.token_urlsafe(48))
    if not _setting(con, "pw_hash"):
        pw = os.environ.get("IDEAS_ADMIN_PASSWORD", "")
        if len(pw) < 12:
            raise SystemExit("Set IDEAS_ADMIN_PASSWORD (min 12 chars) for first run")
        _set(con, "pw_hash", ph.hash(pw))


def rate_limited() -> bool:
    now = time.time()
    _attempts[:] = [t for t in _attempts if now - t < WINDOW]
    return len(_attempts) >= MAX_ATTEMPTS


def check_password(con, pw: str) -> bool:
    _attempts.append(time.time())
    try:
        ok = ph.verify(_setting(con, "pw_hash"), pw)
    except VerifyMismatchError:
        return False
    if ok:
        _attempts.clear()
    return ok


def _ser(con):
    return URLSafeTimedSerializer(_setting(con, "secret"), salt="session")


def new_session(con) -> str:
    return _ser(con).dumps({"csrf": secrets.token_urlsafe(24)})


def read_session(con, cookie: str | None):
    if not cookie:
        return None
    try:
        return _ser(con).loads(cookie, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def csrf_ok(session, token: str) -> bool:
    return bool(session) and hmac.compare_digest(session["csrf"], token or "")


def create_token(con, name: str, scope: str) -> str:
    tok = "ids_" + secrets.token_urlsafe(32)
    con.execute("INSERT INTO api_tokens(name,hash,scope) VALUES(?,?,?)", (name, db.hash_token(tok), scope))
    con.commit()
    return tok


def lookup_token(con, tok: str):
    row = con.execute("SELECT * FROM api_tokens WHERE hash=?", (db.hash_token(tok),)).fetchone()
    if row:
        con.execute("UPDATE api_tokens SET last_used=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        con.commit()
    return row
