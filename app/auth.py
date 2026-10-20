"""Authentication, sessions and a central role/ownership policy (deny by default)."""
import contextvars, datetime, hashlib, hmac, os, re, secrets, sqlite3, time
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qsl, urlencode
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from .db import conn

DEV = os.getenv("KS_DEV", "1") == "1"  # set KS_DEV=0 before any public hosting
ADMIN_EMAIL = os.getenv("KS_ADMIN_EMAIL", "admin@demo.test").lower()
ADMIN_PW = os.getenv("KS_ADMIN_PASSWORD", "admin123" if DEV else "")
HOURS, ADMIN_HOURS, COOKIE = 12, 4, "kb_session"
BUYER_TYPES = ["Restaurant", "Hotel", "Supermarket", "Exporter", "Personal use", "Other"]
DOCS = {} if DEV else {"docs_url": None, "redoc_url": None, "openapi_url": None}
_cur = contextvars.ContextVar("user", default=None)
router = APIRouter(prefix="/auth")

def now(): return datetime.datetime.now(datetime.timezone.utc)
def cur(): return _cur.get()
def uid():
    u = _cur.get()
    if not u: raise HTTPException(401, "Please sign in")
    return u["id"]

def hash_pw(pw):
    s = secrets.token_bytes(16)
    return "pbkdf2$%s$%s" % (s.hex(), hashlib.pbkdf2_hmac("sha256", pw.encode(), s, 200_000).hex())
def check_pw(pw, stored):
    try:
        _, s, h = stored.split("$")
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(s), 200_000).hex(), h)
    except Exception:
        return False
DUMMY = hash_pw("dummy-password")

_hits, _otp = {}, {}
def _check(key, limit, window=600):
    t = time.time(); L = [x for x in _hits.get(key, []) if t - x < window]; _hits[key] = L
    if len(L) >= limit: raise HTTPException(429, "Too many attempts. Please try again later.")
def _hit(key): _hits.setdefault(key, []).append(time.time())
def _ip(r): return r.client.host if r.client else "?"
def _sha(t): return hashlib.sha256(t.encode()).hexdigest()
def _public(u): return {"id": u["id"], "name": u["name"], "role": u["role"], "loc": u.get("loc") or "", "buyer_type": u.get("buyer_type") or ""}
def _norm_phone(p):
    p = re.sub(r"[\s\-]", "", p or ""); p = re.sub(r"^(\+91|91|0)(?=\d{10}$)", "", p)
    return p if re.fullmatch(r"[6-9]\d{9}", p) else None

def init():
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INT, role TEXT, expires TEXT)")
        for ddl in ("ALTER TABLE users ADD COLUMN phone TEXT", "ALTER TABLE users ADD COLUMN email TEXT", "ALTER TABLE users ADD COLUMN pw_hash TEXT"):
            try: c.execute(ddl)
            except sqlite3.OperationalError: pass
        if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            if not ADMIN_PW: raise RuntimeError("Set KS_ADMIN_PASSWORD before starting with KS_DEV=0")
            c.execute("INSERT INTO users(name,role,loc,email,pw_hash) VALUES('Administrator','admin','',?,?)", (ADMIN_EMAIL, hash_pw(ADMIN_PW)))
        if DEV:
            for r in c.execute("SELECT id FROM users WHERE role='farmer' AND (phone IS NULL OR phone='')").fetchall():
                c.execute("UPDATE users SET phone=? WHERE id=?", ("9000000%03d" % r["id"], r["id"]))
            for r in c.execute("SELECT id FROM users WHERE role='buyer' AND (email IS NULL OR email='')").fetchall():
                c.execute("UPDATE users SET email=?, pw_hash=? WHERE id=?", ("buyer%d@demo.test" % r["id"], hash_pw("buyer1234"), r["id"]))
    if DEV:
        with conn() as c:
            print("[DEV] admin:", ADMIN_EMAIL, "/", ADMIN_PW)
            for r in c.execute("SELECT id, role, phone, email FROM users WHERE role IN ('farmer','buyer') AND (phone LIKE '9000000%' OR email LIKE '%@demo.test')"):
                print("[DEV]", r["role"], r["phone"] if r["role"] == "farmer" else r["email"] + " / buyer1234")

def _start(u):
    tok = secrets.token_urlsafe(32); hrs = ADMIN_HOURS if u["role"] == "admin" else HOURS
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (now().isoformat(),))
        c.execute("INSERT INTO sessions(token_hash,user_id,role,expires) VALUES(?,?,?,?)",
                  (_sha(tok), u["id"], u["role"], (now() + datetime.timedelta(hours=hrs)).isoformat()))
    r = JSONResponse(_public(u))
    r.set_cookie(COOKIE, tok, max_age=hrs * 3600, httponly=True, samesite="lax", secure=not DEV, path="/")
    return r

def _user(scope):
    for k, v in scope["headers"]:
        if k == b"cookie":
            try: m = SimpleCookie(v.decode("latin-1")).get(COOKIE)
            except CookieError: return None
            if not m: return None
            with conn() as c:
                r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?",
                              (_sha(m.value), now().isoformat())).fetchone()
            return dict(r) if r else None
    return None

class PhoneReq(BaseModel): phone: str
class Verify(BaseModel):
    phone: str; otp: str; name: str = ""; loc: str = ""
class BuyerReg(BaseModel):
    name: str; email: str; password: str; loc: str; buyer_type: str
class Login(BaseModel):
    email: str; password: str

@router.post("/farmer/otp")
def farmer_otp(b: PhoneReq, request: Request):
    ph = _norm_phone(b.phone)
    if not ph: raise HTTPException(400, "Enter a valid 10-digit mobile number")
    _check("otp:" + ph, 5); _check("otpip:" + _ip(request), 20)
    o = _otp.get(ph)
    if o and time.time() - o["sent"] < 30: raise HTTPException(429, "Wait 30 seconds before asking for another OTP")
    if not DEV: raise HTTPException(501, "SMS provider not configured yet")
    code = str(secrets.randbelow(900000) + 100000)
    _otp[ph] = {"code": code, "exp": time.time() + 300, "tries": 0, "sent": time.time()}
    _hit("otp:" + ph); _hit("otpip:" + _ip(request)); print("[DEV OTP]", ph, code)
    return {"sent": True, "dev_otp": code}

@router.post("/farmer/verify")
def farmer_verify(b: Verify, request: Request):
    ph = _norm_phone(b.phone)
    if not ph: raise HTTPException(400, "Enter a valid 10-digit mobile number")
    _check("vf:" + ph, 5)
    o = _otp.get(ph)
    if not o or o["exp"] < time.time(): raise HTTPException(400, "OTP expired. Request a new one.")
    o["tries"] += 1
    if o["tries"] > 5 or not hmac.compare_digest(o["code"], b.otp.strip()):
        _hit("vf:" + ph); raise HTTPException(400, "Wrong OTP")
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE role='farmer' AND phone=?", (ph,)).fetchone()
        if not u:
            if not b.name.strip() or not b.loc.strip():
                raise HTTPException(404, "This number is not registered. Enter your name and village to register.")
            i = c.execute("INSERT INTO users(name,role,loc,phone) VALUES(?,?,?,?)", (b.name.strip(), "farmer", b.loc.strip(), ph)).lastrowid
            u = c.execute("SELECT * FROM users WHERE id=?", (i,)).fetchone()
    _otp.pop(ph, None)
    return _start(dict(u))

@router.post("/buyer/register")
def buyer_register(b: BuyerReg, request: Request):
    em = b.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em): raise HTTPException(400, "Enter a valid email")
    if len(b.password) < 8: raise HTTPException(400, "Password must be at least 8 characters")
    if b.buyer_type not in BUYER_TYPES: raise HTTPException(400, "Choose what you will use the crop for")
    if not b.name.strip() or not b.loc.strip(): raise HTTPException(400, "Name and location are required")
    _check("reg:" + _ip(request), 10); _hit("reg:" + _ip(request))
    with conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (em,)).fetchone(): raise HTTPException(409, "This email is already registered")
        i = c.execute("INSERT INTO users(name,role,loc,buyer_type,email,pw_hash) VALUES(?,?,?,?,?,?)",
                      (b.name.strip(), "buyer", b.loc.strip(), b.buyer_type, em, hash_pw(b.password))).lastrowid
        u = c.execute("SELECT * FROM users WHERE id=?", (i,)).fetchone()
    return _start(dict(u))

def _login(b, role, request):
    em = b.email.strip().lower(); k, ik = "login:%s:%s" % (role, em), "loginip:" + _ip(request)
    _check(k, 5); _check(ik, 20)
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE role=? AND email=?", (role, em)).fetchone()
    ok = check_pw(b.password, u["pw_hash"] if u and u["pw_hash"] else DUMMY)
    if not (u and ok):
        _hit(k); _hit(ik); raise HTTPException(401, "Invalid email or password")
    return _start(dict(u))

@router.post("/buyer/login")
def buyer_login(b: Login, request: Request): return _login(b, "buyer", request)
@router.post("/admin/login")
def admin_login(b: Login, request: Request): return _login(b, "admin", request)

@router.get("/me")
def me():
    u = _cur.get()
    if not u: raise HTTPException(401, "Not signed in")
    return _public(u)

@router.post("/logout")
def logout(request: Request):
    t = request.cookies.get(COOKIE)
    if t:
        with conn() as c: c.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(t),))
    r = JSONResponse({"ok": True}); r.delete_cookie(COOKIE, path="/"); return r

# ---- central policy: (method, path regex, allowed roles, ownership check). Anything not listed is refused.
PUBLIC = [("GET", r"/"), ("GET", r"/meta"), ("GET", r"/auth/me"), ("POST", r"/auth/(farmer/otp|farmer/verify|buyer/register|buyer/login|admin/login|logout)")]
RULES = [
 ("GET", r"/varieties", {"farmer", "admin"}, None), ("GET", r"/users", {"admin"}, None),
 ("POST", r"/tickets", {"farmer"}, None), ("GET", r"/tickets", {"farmer", "admin"}, None),
 ("POST", r"/tickets/\d+/(media|submit|cancel)", {"farmer"}, "ticket"), ("DELETE", r"/tickets/\d+", {"farmer"}, "ticket"),
 ("POST", r"/tickets/\d+/(schedule|reject|approve)", {"admin"}, None), ("GET", r"/media/\d+", {"farmer", "admin"}, "media"),
 ("GET", r"/mandi/.+", {"admin"}, None), ("GET", r"/price/.+", {"admin"}, None),
 ("GET", r"/listings", {"farmer", "buyer", "admin"}, None), ("POST", r"/listings/\d+/unpublish", {"admin"}, None),
 ("GET", r"/orders", {"farmer", "buyer", "admin"}, None), ("POST", r"/orders", {"buyer"}, None),
 ("POST", r"/orders/\d+/fault/\d+", {"admin"}, None), ("GET", r"/orders/\d+/ledger", {"farmer", "buyer", "admin"}, "order"),
 ("POST", r"/orders/\d+/[a-z_]+", {"farmer", "buyer", "admin"}, "order"), ("GET", r"/ledger/verify", {"admin"}, None),
 ("GET", r"/subscription/\d+", {"buyer"}, "self"), ("POST", r"/subscribe/\d+/[a-z]+", {"buyer"}, "self"),
 ("GET", r"/reliability/\d+", {"admin"}, None), ("GET", r"/admin/summary", {"admin"}, None)]
PERM = {"farmer": {"harvest", "ship", "cancel", "refund", "dispute"}, "buyer": {"fund", "cancel", "deliver", "release", "dispute", "buyer_cancel"}}

def _can(role, action, state):
    if state == "DISPUTED": return role == "admin" and action in ("release", "refund")
    if role == "admin": return False
    if action == "undo": return (role == "farmer" and state in ("HARVESTED", "SHIPPED")) or (role == "buyer" and state == "DELIVERED")
    return action in PERM.get(role, ())

def _own(kind, path, method, u):
    n = int(re.findall(r"/(\d+)", path)[0]); role = u["role"]
    with conn() as c:
        if kind == "self": return None if n == u["id"] else (403, "Not your account")
        if kind == "ticket":
            r = c.execute("SELECT farmer_id FROM tickets WHERE id=?", (n,)).fetchone(); ok = bool(r) and r["farmer_id"] == u["id"]
        elif kind == "media":
            r = c.execute("SELECT t.farmer_id FROM ticket_media m JOIN tickets t ON t.id=m.ticket_id WHERE m.id=?", (n,)).fetchone()
            ok = role == "admin" or (bool(r) and r["farmer_id"] == u["id"])
        else:
            r = c.execute("SELECT o.buyer_id, o.state, l.farmer_id FROM orders o JOIN listings l ON l.id=o.listing_id WHERE o.id=?", (n,)).fetchone()
            if not r: return (404, "Order not found")
            ok = role == "admin" or (role == "farmer" and r["farmer_id"] == u["id"]) or (role == "buyer" and r["buyer_id"] == u["id"])
            if ok and method == "POST" and not _can(role, path.rsplit("/", 1)[1], r["state"]):
                return (403, "That action is not allowed for you in the order's current state")
    return None if ok else (403, "Not your record")

def _check_access(path, method, u):
    if DEV and (path in ("/docs", "/openapi.json", "/redoc") or path.startswith("/docs/")): return None
    for m, p in PUBLIC:
        if m == method and re.fullmatch(p, path): return None
    if not u: return (401, "Please sign in")
    for m, p, roles, own in RULES:
        if m == method and re.fullmatch(p, path):
            if u["role"] not in roles: return (403, "Not allowed for your role")
            return _own(own, path, method, u) if own else None
    return (403, "Not allowed")

def _rewrite(scope, path, method, u):  # the server, not the client, decides whose data a request sees
    if method == "GET" and (path in ("/listings", "/orders", "/tickets") or re.fullmatch(r"/orders/\d+/ledger", path)):
        q = [(k, v) for k, v in parse_qsl(scope["query_string"].decode(), keep_blank_values=True) if k not in ("view", "farmer_id", "buyer_id")]
        q.append(("view", u["role"]))
        if u["role"] == "farmer": q.append(("farmer_id", str(u["id"])))
        if u["role"] == "buyer": q.append(("buyer_id", str(u["id"])))
        scope["query_string"] = urlencode(q).encode()

class AuthMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        u = _user(scope); tok = _cur.set(u)
        try:
            deny = _check_access(scope["path"], scope["method"], u)
            if deny: return await JSONResponse({"detail": deny[1]}, status_code=deny[0])(scope, receive, send)
            if u: _rewrite(scope, scope["path"], scope["method"], u)
            await self.app(scope, receive, send)
        finally:
            _cur.reset(tok)
