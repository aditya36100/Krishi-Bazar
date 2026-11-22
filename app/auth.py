"""Login for Krishi: scrypt password hashes, HMAC-signed session tokens, and FastAPI dependencies
that enforce roles (farmer / buyer / admin) and ownership. Standard library only."""
import base64, hashlib, hmac, json, os, secrets, time
from fastapi import Depends, Header, HTTPException, Query
from .db import conn

# Set KS_SECRET in .env so sessions survive a restart. Without it a random key is made per process.
SECRET = (os.getenv("KS_SECRET") or secrets.token_hex(32)).encode()
TTL = int(os.getenv("KS_TOKEN_HOURS", "12")) * 3600
_DUMMY = None


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def burn_time(pw: str):
    """Spend the same time as a real check, so an unknown phone number is not faster to reject."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not-a-real-password")
    check_password(pw, _DUMMY)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(uid: int, role: str) -> str:
    body = _b64(json.dumps({"id": uid, "role": role, "exp": int(time.time()) + TTL}).encode())
    return body + "." + _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())


def read_token(tok: str):
    try:
        body, sig = tok.split(".")
        good = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        d = json.loads(_unb64(body))
        return d if d["exp"] >= time.time() else None
    except Exception:
        return None


def ensure_admin():
    """Create or refresh the admin account from KS_ADMIN_USER (default 'admin') and KS_ADMIN_PASSWORD.
    Admin logs in with that username in the phone field. With no password set, there is no admin."""
    pw = os.getenv("KS_ADMIN_PASSWORD", "")
    if not pw:
        return False
    user = os.getenv("KS_ADMIN_USER", "admin")
    with conn() as c:
        r = c.execute("SELECT id, password_hash FROM users WHERE role='admin' AND phone=?", (user,)).fetchone()
        if r and r["password_hash"] and check_password(pw, r["password_hash"]):
            return True
        h = hash_password(pw)
        if r:
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (h, r["id"]))
        else:
            c.execute("INSERT INTO users(name,role,loc,phone,password_hash) VALUES('Admin','admin','',?,?)", (user, h))
    return True


def _user_from(tok: str):
    d = read_token(tok) if tok else None
    if not d:
        raise HTTPException(401, "Please log in")
    with conn() as c:
        r = c.execute("SELECT id, name, role FROM users WHERE id=?", (d["id"],)).fetchone()
    if not r or r["role"] != d["role"]:
        raise HTTPException(401, "Please log in")
    return {"id": r["id"], "name": r["name"], "role": r["role"]}


def _bearer(h: str) -> str:
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def current_user(authorization: str = Header(default="")):
    return _user_from(_bearer(authorization))


def current_user_q(authorization: str = Header(default=""), t: str = Query(default="")):
    """Same as current_user, but also accepts ?t=<token> because <img> and <video> tags cannot send headers."""
    return _user_from(_bearer(authorization) or t)


def admin_only(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user


def role(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Not allowed for your role")
        return user
    return dep


def _parties(oid: int):
    with conn() as c:
        r = c.execute("SELECT o.buyer_id, o.state, l.farmer_id FROM orders o JOIN listings l ON l.id=o.listing_id WHERE o.id=?", (oid,)).fetchone()
    if not r:
        raise HTTPException(404, "order not found")
    return r


def order_party(oid: int, user=Depends(current_user)):
    if user["role"] == "admin":
        return user
    r = _parties(oid)
    if user["id"] not in (r["buyer_id"], r["farmer_id"]):
        raise HTTPException(403, "Not your order")
    return user


# Who may trigger each order action (admin may do all). Mirrors PERM in frontend/index.html.
ORDER_ACTIONS = {"fund": {"buyer"}, "harvest": {"farmer"}, "ship": {"farmer"}, "deliver": {"buyer"},
                 "release": {"buyer"}, "dispute": {"buyer", "farmer"}, "refund": {"farmer"},
                 "cancel": {"buyer", "farmer"}, "undo": {"buyer", "farmer"}, "buyer_cancel": {"buyer"}}


def authorize_order(user, oid: int, action: str):
    if user["role"] == "admin":
        return
    r = _parties(oid)
    rel = "buyer" if user["id"] == r["buyer_id"] else ("farmer" if user["id"] == r["farmer_id"] else None)
    if rel is None or rel not in ORDER_ACTIONS[action]:
        raise HTTPException(403, "You cannot do this on this order")
    if r["state"] == "DISPUTED" and action in ("release", "refund"):
        raise HTTPException(403, "A disputed order can only be settled by the admin")


def ticket_owner(tid: int, user=Depends(current_user)):
    if user["role"] == "admin":
        return user
    with conn() as c:
        r = c.execute("SELECT farmer_id FROM tickets WHERE id=?", (tid,)).fetchone()
    if not r:
        raise HTTPException(404, "ticket not found")
    if r["farmer_id"] != user["id"]:
        raise HTTPException(403, "Not your ticket")
    return user


def media_access(mid: int, user=Depends(current_user_q)):
    if user["role"] == "admin":
        return user
    with conn() as c:
        r = c.execute("SELECT t.farmer_id FROM ticket_media m JOIN tickets t ON t.id=m.ticket_id WHERE m.id=?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    if r["farmer_id"] != user["id"]:
        raise HTTPException(403, "Not your file")
    return user


def self_buyer(buyer_id: int, user=Depends(current_user)):
    if user["role"] == "admin" or (user["role"] == "buyer" and user["id"] == buyer_id):
        return user
    raise HTTPException(403, "Not your account")
