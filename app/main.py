import datetime, math, os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from . import db, escrow, pricing, reliability
from .db import conn

db.init()
app = FastAPI(title="Krishi Bazar API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # dev only

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.getenv("KS_PRICES", os.path.join(BASE, "data", "prices.csv"))
MARGIN = float(os.getenv("KS_MARGIN", "0.15"))  # direct-sale premium; calibrate from real transactions
MIN_KG = float(os.getenv("KS_MIN_KG", "100"))  # minimum listing and order size
ACTIONS = {"fund": "FUNDED", "harvest": "HARVESTED", "ship": "SHIPPED", "deliver": "DELIVERED",
           "release": "RELEASED", "dispute": "DISPUTED", "refund": "REFUNDED", "cancel": "CANCELLED"}

class User(BaseModel):
    name: str; role: str; loc: str = ""; buyer_type: str = ""; phone: str = ""
class Listing(BaseModel):
    farmer_id: int; crop: str; qty: float; price: float; variety: str = ""; harvest_date: str = ""; loc: str = ""
class Order(BaseModel):
    listing_id: int; buyer_id: int; qty: float; deposit_pct: float = 0.3

def _forecast(crop, harvest_date):
    days = (datetime.date.fromisoformat(harvest_date) - datetime.date.today()).days if harvest_date else 7
    f = pricing.forecast(pricing.weekly(pricing.load(CSV), crop), max(1, math.ceil(days / 7)))
    f["suggested"] = round(f["point"] * (1 + MARGIN), 2)
    return f

@app.post("/users")
def add_user(u: User):
    if u.role not in ("farmer", "buyer"):
        raise HTTPException(400, "role must be farmer or buyer")
    if not u.name.strip():
        raise HTTPException(400, "name is required")
    if u.role == "buyer" and u.buyer_type not in BUYER_MIN_KG:
        raise HTTPException(400, "Please choose what you will use the crop for: " + ", ".join(BUYER_MIN_KG))
    ph = ""
    if u.phone.strip():
        ph = _phone(u.phone)
        if not ph:
            raise HTTPException(400, "Enter a valid 10-digit mobile number")
    with conn() as c:
        return {"id": c.execute("INSERT INTO users(name,role,loc,buyer_type,phone) VALUES(?,?,?,?,?)",
                                (u.name.strip(), u.role, u.loc.strip(), u.buyer_type, ph)).lastrowid}

def add_listing(l: Listing):  # internal: listings are now created only when the admin approves a ticket
    if l.qty < MIN_KG:
        raise HTTPException(400, f"Minimum quantity is {MIN_KG:g} kg")
    if l.price <= 0 or not l.variety.strip():
        raise HTTPException(400, "Price and crop variety are required")
    try:
        ref = _forecast(l.crop, l.harvest_date)["point"]
    except Exception:
        ref = None
    with conn() as c:
        cur = c.execute("INSERT INTO listings(farmer_id,crop,variety,qty,harvest_date,price,loc,mandi_ref) VALUES(?,?,?,?,?,?,?,?)",
                        (l.farmer_id, l.crop, l.variety.strip(), l.qty, l.harvest_date, l.price, l.loc, ref))
        return {"id": cur.lastrowid, "mandi_ref": ref}

@app.get("/listings")
def listings(crop: str = "", loc: str = "", view: str = "farmer", buyer_id: int = 0, farmer_id: int = 0):
    subbed = _sub(buyer_id)["active"] if view == "buyer" else False
    with conn() as c:
        rows = c.execute("SELECT l.*, u.name farmer_name FROM listings l LEFT JOIN users u ON u.id=l.farmer_id "
                         "WHERE l.qty>0 AND l.status='ACTIVE' AND (?='' OR l.crop=?) AND (?='' OR l.loc=?) ORDER BY COALESCE(l.live_at, '') DESC, l.id DESC", (crop, crop, loc, loc)).fetchall()
        approved = None
        if view == "farmer" and farmer_id:  # a farmer sees only listings the admin approved from their tickets
            approved = {r[0] for r in c.execute("SELECT listing_id FROM tickets WHERE status='APPROVED' AND listing_id IS NOT NULL AND farmer_id=?", (farmer_id,))}
    out = []
    for r in rows:
        if approved is not None and r["id"] not in approved:
            continue
        d = dict(r); d["farmer_reliability"] = reliability.score(r["farmer_id"])
        if view == "buyer":
            d["price"] = round(d["price"] * (1 + _markup(r, subbed)), 2); d["early_access_until"] = _opens_at(r).isoformat(timespec="minutes"); d["locked_for_you"] = (not subbed) and _opens_at(r) > datetime.datetime.now(); d["subscriber_rate"] = subbed  # buyers only ever see the marked-up price
        out.append(d)
    return out

@app.post("/orders")
def place(o: Order):
    with conn() as c:
        l = c.execute("SELECT * FROM listings WHERE id=?", (o.listing_id,)).fetchone()
        if not l:
            raise HTTPException(404, "listing not found")
        o.qty = l["qty"]  # whole lot only: buyers cannot choose a quantity
        if o.qty <= 0:
            raise HTTPException(400, "This lot is no longer available")
        subbed = _sub(o.buyer_id)["active"]
        if not subbed and _opens_at(l) > datetime.datetime.now():
            raise HTTPException(403, "Early-access window: opens to all buyers at " + _opens_at(l).strftime("%d %b %H:%M"))
        mn = min(_buyer_min(o.buyer_id), l["qty"])
        if o.qty < mn:
            raise HTTPException(400, f"Minimum order is {mn:g} kg for your buyer type")
        oid = c.execute("INSERT INTO orders(listing_id,buyer_id,qty,amount,buyer_amount,deposit_pct,created) VALUES(?,?,?,?,?,?,?)",
                        (o.listing_id, o.buyer_id, o.qty, round(o.qty * l["price"], 2), round(o.qty * l["price"] * (1 + _markup(l, subbed)), 2), o.deposit_pct,
                         datetime.datetime.now().isoformat())).lastrowid
        c.execute("UPDATE listings SET qty=qty-? WHERE id=?", (o.qty, o.listing_id))
    escrow.start(oid)
    return {"id": oid, "state": "PLACED"}

@app.post("/orders/{oid}/{action}")
def act(oid: int, action: str):
    if action == "undo":
        try:
            escrow.undo(oid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": oid, "state": "undone"}
    if action == "buyer_cancel":
        try:
            escrow.buyer_cancel(oid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        with conn() as c:
            o = c.execute("SELECT qty, listing_id FROM orders WHERE id=?", (oid,)).fetchone()
            c.execute("UPDATE listings SET qty=qty+? WHERE id=?", (o["qty"], o["listing_id"]))
        return {"id": oid, "state": "cancelled"}
    if action not in ACTIONS:
        raise HTTPException(404, "unknown action")
    new = ACTIONS[action]
    try:
        escrow.move(oid, new)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with conn() as c:
        o = c.execute("SELECT o.*, l.farmer_id FROM orders o JOIN listings l ON l.id=o.listing_id WHERE o.id=?", (oid,)).fetchone()
        if new in ("REFUNDED", "CANCELLED"):
            c.execute("UPDATE listings SET qty=qty+? WHERE id=?", (o["qty"], o["listing_id"]))
        if new == "RELEASED":
            for pid, kind in ((o["farmer_id"], "farmer_fulfil"), (o["buyer_id"], "buyer_accept")):
                c.execute("INSERT INTO outcomes(order_id,party_id,kind,ok) VALUES(?,?,?,1)", (oid, pid, kind))
    return {"id": oid, "state": new}

@app.post("/orders/{oid}/fault/{party_id}")
def fault(oid: int, party_id: int):  # admin marks the party at fault after a dispute
    with conn() as c:
        c.execute("INSERT INTO outcomes(order_id,party_id,kind,ok) VALUES(?,?,?,0)", (oid, party_id, "fault"))
    return {"ok": True}

@app.get("/orders/{oid}/ledger")
def ledger(oid: int, view: str = "admin"):
    with conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM ledger WHERE order_id=? ORDER BY id", (oid,))]
    if view != "admin":
        for r in rows:
            r["detail"] = "(admin only)"
    return rows

@app.get("/ledger/verify")
def verify():
    ok, bad = escrow.verify_chain()
    return {"intact": ok, "first_bad_id": bad}

@app.get("/price/{crop}")
def price(crop: str, harvest_date: str = ""):
    try:
        return _forecast(crop, harvest_date)
    except FileNotFoundError:
        raise HTTPException(404, "prices.csv missing - run data/make_demo_csv.py")
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.get("/reliability/{user_id}")
def rel(user_id: int):
    return reliability.score(user_id)

@app.get("/admin/summary")
def summary():
    with conn() as c:
        g = lambda q: c.execute(q).fetchone()[0]
        gmv = g("SELECT COALESCE(SUM(amount),0) FROM orders WHERE state='RELEASED'")
        prem = g("SELECT AVG(l.price/l.mandi_ref-1)*100 FROM orders o JOIN listings l ON l.id=o.listing_id "
                 "WHERE o.state='RELEASED' AND l.mandi_ref>0")
        bp = g(f"SELECT COALESCE(SUM(COALESCE(buyer_amount, amount*{1 + escrow.BUYER_MARKUP})),0) FROM orders WHERE state='RELEASED'")
        subs = g("SELECT COALESCE(SUM(price),0) FROM subscriptions")
        out = {"users": g("SELECT COUNT(*) FROM users"), "orders": g("SELECT COUNT(*) FROM orders"),
               "gmv_released": gmv, "platform_fee": round(gmv * escrow.FEE, 2), "buyer_margin": round(bp - gmv, 2), "subscription_revenue": subs,
               "avg_farmer_premium_pct": None if prem is None else round(prem, 1)}
    out["ledger_intact"] = escrow.verify_chain()[0]
    return out


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(os.path.join(BASE, "frontend", "index.html"))

@app.get("/meta")
def meta():
    d = pricing.load(CSV)
    wk = d.groupby("commodity")["date"].apply(lambda x: x.dt.to_period("W").nunique())
    ok = wk[wk >= 60].sort_values(ascending=False)
    return {"synthetic": os.path.exists(os.path.join(BASE, "data", "SYNTHETIC")), "rows": int(len(d)),
            "from": str(d["date"].min().date()), "to": str(d["date"].max().date()), "crops": [str(c) for c in ok.index[:60]]}

@app.get("/price/{crop}/history")
def hist(crop: str, weeks: int = 52):
    s = pricing.weekly(pricing.load(CSV), crop).tail(weeks)
    return {"dates": [str(i.date()) for i in s.index], "values": [round(float(v), 2) for v in s.values]}

@app.get("/users")
def users():
    with conn() as c:
        rows = [dict(r) for r in c.execute("SELECT u.id, u.name, u.role, u.loc, u.buyer_type, u.phone, "
                                           "(SELECT MAX(s.ends) FROM subscriptions s WHERE s.buyer_id=u.id) plus_until FROM users u")]
        for u in rows:  # never send password hashes or emails to the browser; collect every phone number known for a person
            nums = []
            for r in c.execute("SELECT phone, alt_phone FROM tickets WHERE farmer_id=? ORDER BY id DESC", (u["id"],)):
                nums += [r["phone"], r["alt_phone"]]
            allp = []
            for x in [next((x for x in nums if x), ""), u["phone"]] + nums:
                if x and x not in allp:
                    allp.append(x)
            u["phone"] = allp[0] if allp else ""
            u["phones"] = allp
        return rows

@app.get("/orders")
def orders(view: str = "admin"):
    with conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT o.*, l.crop, l.variety, l.price, l.farmer_id, fu.name farmer, bu.name buyer FROM orders o "
            "JOIN listings l ON l.id=o.listing_id LEFT JOIN users fu ON fu.id=l.farmer_id "
            "LEFT JOIN users bu ON bu.id=o.buyer_id ORDER BY o.id DESC")]
    for d in rows:
        bp = d.get("buyer_amount") or round(d["amount"] * (1 + escrow.BUYER_MARKUP), 2)
        if view == "buyer":
            d["amount"] = bp; d.pop("buyer_amount", None); d.pop("price", None)
            if d["state"] in ("PLACED", "FUNDED"):
                d["cancel_charge"] = escrow.cancel_preview(d["id"])
        elif view == "farmer":
            d["payout"] = round(d["amount"] * (1 - escrow.FEE), 2); d.pop("buyer_amount", None)
        else:
            d["buyer_amount"] = bp
    return rows




RATE_CAP = 0.10  # admin-editable rates are fractions (0.03 = 3%), capped here
SUB_DISCOUNT = 0.005  # subscribers pay this much less markup (0.5 point)

def _load_rates():
    global SUB_DISCOUNT
    try:
        with conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
            rows = c.execute("SELECT k, v FROM settings").fetchall()
        for r in rows:
            k, v = r[0], float(r[1])
            if k == "farmer_fee":
                escrow.FEE = v
            elif k == "default_markup":
                escrow.BUYER_MARKUP = v
            elif k == "sub_discount":
                SUB_DISCOUNT = v
            elif k == "cancel_fee":
                escrow.CANCEL_FEE = v
    except Exception:
        pass

_load_rates()

def _markup(l, subbed):
    m = l["buyer_markup"] if l["buyer_markup"] is not None else escrow.BUYER_MARKUP
    return max(0.0, m - SUB_DISCOUNT) if subbed else m

def _opens_at(l):
    try:
        t0 = datetime.datetime.fromisoformat(l["live_at"])
        h = float(l["early_hours"] or 0)
    except Exception:
        return datetime.datetime.min
    return t0 + datetime.timedelta(hours=h)

def _check_terms(a):
    if a.buyer_markup != -1.0 and not (0 <= a.buyer_markup <= RATE_CAP):
        raise HTTPException(400, f"buyer markup must be between 0 and {RATE_CAP:g} (fraction, 0.03 = 3%)")
    if not (0 <= a.early_hours <= 720):
        raise HTTPException(400, "early-access hours must be between 0 and 720")

class RatesIn(BaseModel):
    farmer_fee: float = -1.0
    default_markup: float = -1.0
    sub_discount: float = -1.0
    cancel_fee: float = -1.0

@app.get("/admin/settings")
def admin_rates_get():
    return {"farmer_fee": escrow.FEE, "default_markup": escrow.BUYER_MARKUP, "sub_discount": SUB_DISCOUNT, "cancel_fee": escrow.CANCEL_FEE, "cap": RATE_CAP}

@app.post("/admin/settings")
def admin_rates_set(s: RatesIn):
    new = {}
    for k, v in (("farmer_fee", s.farmer_fee), ("default_markup", s.default_markup), ("sub_discount", s.sub_discount), ("cancel_fee", s.cancel_fee)):
        if v == -1.0:
            continue
        if not (0 <= v <= RATE_CAP):
            raise HTTPException(400, f"{k} must be between 0 and {RATE_CAP:g}")
        new[k] = v
    if not new:
        raise HTTPException(400, "nothing to change")
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
        for k, v in new.items():
            c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, str(v)))
    _load_rates()
    return admin_rates_get()

PLANS = {"monthly": ("Monthly", 999, 30), "yearly": ("Yearly", 9999, 365)}  # placeholder prices - decide with your mentor

def _sub(buyer_id):
    with conn() as c:
        r = c.execute("SELECT * FROM subscriptions WHERE buyer_id=? ORDER BY ends DESC LIMIT 1", (buyer_id,)).fetchone()
    if r and r["ends"] >= datetime.date.today().isoformat():
        return {"active": True, "plan": r["plan"], "ends": r["ends"]}
    return {"active": False, "plan": None, "ends": r["ends"] if r else None}

@app.get("/subscription/{buyer_id}")
def subscription(buyer_id: int):
    return {**_sub(buyer_id), "min_order": _buyer_min(buyer_id), "plans": {k: {"name": v[0], "price": v[1], "days": v[2]} for k, v in PLANS.items()}}

@app.post("/subscribe/{buyer_id}/{plan}")
def subscribe(buyer_id: int, plan: str):  # demo payment: no real money moves
    if plan not in PLANS:
        raise HTTPException(404, "unknown plan")
    name, price, days = PLANS[plan]
    cur = _sub(buyer_id)
    start = datetime.date.fromisoformat(cur["ends"]) if cur["active"] else datetime.date.today()
    with conn() as c:
        c.execute("INSERT INTO subscriptions(buyer_id,plan,price,starts,ends) VALUES(?,?,?,?,?)",
                  (buyer_id, name, price, start.isoformat(), (start + datetime.timedelta(days=days)).isoformat()))
    return _sub(buyer_id)


BUYER_MIN_KG = {"Restaurant": 50, "Hotel": 100, "Supermarket": 25, "Exporter": 500, "Personal use": 5, "Other": 50}  # placeholders
GRADE_FACTOR = {"A": 1.10, "B": 1.00, "C": 0.90}  # placeholders: grade -> multiple of the current mandi price

def _buyer_min(buyer_id):
    with conn() as c:
        r = c.execute("SELECT buyer_type FROM users WHERE id=?", (buyer_id,)).fetchone()
    return BUYER_MIN_KG.get((r["buyer_type"] if r else "") or "", MIN_KG)

def _latest_mandi(crop):
    try:
        d = pricing.load(CSV)
    except Exception:
        return None
    m = d[d["commodity"].str.lower() == crop.strip().lower()]
    if m.empty:
        return None
    s = m.set_index("date")["modal_price"].resample("W").mean().dropna()
    return (round(float(s.iloc[-1]), 2), str(s.index[-1].date())) if len(s) else None

@app.get("/mandi/{crop}")
def mandi(crop: str):
    r = _latest_mandi(crop)
    if not r:
        return {"latest": None}
    return {"latest": r[0], "as_of": r[1], "suggest": {g: round(r[0] * f, 2) for g, f in GRADE_FACTOR.items()}}

class Ticket(BaseModel):
    farmer_id: int; crop: str; qty: float; location: str; phone: str; pref_date: str; pref_slot: str
    variety: str = ""; alt_phone: str = ""; notes: str = ""

class Approve(BaseModel):
    buyer_markup: float = -1.0
    early_hours: float = 0.0
    grade: str; qty: float; price: float; agreed: bool = False; variety: str = ""

@app.post("/tickets")
def raise_ticket(t: Ticket):
    if t.qty < MIN_KG:
        raise HTTPException(400, f"Minimum quantity is {MIN_KG:g} kg")
    if not t.crop.strip():
        raise HTTPException(400, "Crop is required")
    if not t.location.strip():
        raise HTTPException(400, "Farm location is required")
    ph = _phone(t.phone)
    if not ph:
        raise HTTPException(400, "Enter a valid 10-digit mobile number")
    alt = _phone(t.alt_phone) if t.alt_phone.strip() else ""
    if t.alt_phone.strip() and not alt:
        raise HTTPException(400, "The alternate number is not valid")
    try:
        day = datetime.date.fromisoformat(t.pref_date)
    except ValueError:
        raise HTTPException(400, "Choose a valid visit date")
    if day < datetime.date.today():
        raise HTTPException(400, "The visit date cannot be in the past")
    if t.pref_slot not in VISIT_SLOTS:
        raise HTTPException(400, "Choose a visit time")
    with conn() as c:
        tid = c.execute("INSERT INTO tickets(farmer_id,crop,variety,qty,notes,location,phone,alt_phone,pref_date,pref_slot,status,created) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,'DRAFT',?)",
                        (t.farmer_id, t.crop.strip(), t.variety.strip() or "Not specified", t.qty, t.notes.strip(),
                         t.location.strip(), ph, alt, t.pref_date, t.pref_slot,
                         datetime.datetime.now().isoformat())).lastrowid
    return {"id": tid, "status": "DRAFT"}

@app.get("/tickets")
def tickets(view: str = "admin", farmer_id: int = 0):
    q, args = "SELECT t.*, u.name farmer, u.loc FROM tickets t LEFT JOIN users u ON u.id=t.farmer_id WHERE t.status!='DRAFT'", ()
    if view == "farmer":
        q, args = q + " AND t.farmer_id=?", (farmer_id,)
    with conn() as c:
        rows = [dict(r) for r in c.execute(q + " ORDER BY t.id DESC", args)]
        for r in rows:
            r["media"] = [dict(m) for m in c.execute("SELECT id, kind FROM ticket_media WHERE ticket_id=? ORDER BY id", (r["id"],))]
    return rows

def _tk_set(tid, new, **f):
    with conn() as c:
        t = c.execute("SELECT status FROM tickets WHERE id=?", (tid,)).fetchone()
        if not t:
            raise HTTPException(404, "ticket not found")
        if t["status"] not in ("OPEN", "SCHEDULED"):
            raise HTTPException(400, f"ticket is already {t['status']}")
        sets = "".join(f", {k}=?" for k in f)
        c.execute(f"UPDATE tickets SET status=?{sets} WHERE id=?", (new, *f.values(), tid))
    return {"id": tid, "status": new}

@app.post("/tickets/{tid}/schedule")
def schedule(tid: int, visit_date: str):
    try:
        datetime.date.fromisoformat(visit_date)
    except ValueError:
        raise HTTPException(400, "visit_date must be YYYY-MM-DD")
    return _tk_set(tid, "SCHEDULED", visit_date=visit_date)

@app.post("/tickets/{tid}/reject")
def reject(tid: int, reason: str = ""):
    return _tk_set(tid, "REJECTED", reason=reason.strip())

@app.post("/tickets/{tid}/cancel")
def cancel_ticket(tid: int):
    return _tk_set(tid, "CANCELLED")

@app.post("/tickets/{tid}/approve")
def approve(tid: int, a: Approve):
    with conn() as c:
        t = c.execute("SELECT t.*, u.loc FROM tickets t LEFT JOIN users u ON u.id=t.farmer_id WHERE t.id=?", (tid,)).fetchone()
    if not t:
        raise HTTPException(404, "ticket not found")
    if t["status"] not in ("OPEN", "SCHEDULED"):
        raise HTTPException(400, f"ticket is already {t['status']}")
    if a.grade not in GRADE_FACTOR:
        raise HTTPException(400, "grade must be A, B or C")
    if not a.agreed:
        raise HTTPException(400, "The farmer must agree to the price before the listing goes live")
    _check_terms(a)
    ref = _latest_mandi(t["crop"])
    r = add_listing(Listing(farmer_id=t["farmer_id"], crop=t["crop"], variety=(a.variety or t["variety"]),
                            qty=a.qty, price=a.price, loc=t["loc"] or ""))
    with conn() as c:
        c.execute("UPDATE listings SET buyer_markup=?, early_hours=?, live_at=? WHERE id=?", (None if a.buyer_markup == -1.0 else a.buyer_markup, a.early_hours, datetime.datetime.now().isoformat(), r["id"]))
        c.execute("UPDATE listings SET grade=?, mandi_ref=COALESCE(?, mandi_ref) WHERE id=?",
                  (a.grade, ref[0] if ref else None, r["id"]))
        c.execute("UPDATE tickets SET status='APPROVED', grade=?, final_qty=?, price=?, mandi_ref=?, listing_id=? WHERE id=?",
                  (a.grade, a.qty, a.price, ref[0] if ref else None, r["id"], tid))
    return {"ticket": tid, "listing": r["id"]}


import re, uuid, json

UPLOAD_DIR = os.path.join(BASE, "uploads")
PHOTO_EXT, VIDEO_EXT = {".jpg", ".jpeg", ".png", ".webp"}, {".mp4", ".mov", ".webm", ".m4v"}
MAX_PHOTOS, MAX_PHOTO_B, MAX_VIDEO_B = 7, 8 * 1024 * 1024, 150 * 1024 * 1024  # placeholders
VISIT_SLOTS = ["Morning (8-11 am)", "Midday (11 am-2 pm)", "Afternoon (2-5 pm)", "Evening (5-7 pm)"]

def _phone(p):
    p = re.sub(r"[\s\-]", "", p or "")
    p = re.sub(r"^(\+91|91|0)(?=\d{10}$)", "", p)
    return p if re.fullmatch(r"[6-9]\d{9}", p) else None

@app.get("/varieties")
def varieties():
    try:
        with open(os.path.join(BASE, "data", "varieties.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

@app.post("/tickets/{tid}/media")
async def upload_media(tid: int, request: Request, kind: str, filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if kind not in ("photo", "video") or ext not in (PHOTO_EXT if kind == "photo" else VIDEO_EXT):
        raise HTTPException(400, "Unsupported file type. Photos: jpg, png, webp. Video: mp4, mov, webm.")
    with conn() as c:
        t = c.execute("SELECT status FROM tickets WHERE id=?", (tid,)).fetchone()
        if not t or t["status"] != "DRAFT":
            raise HTTPException(400, "This ticket is not accepting uploads")
        n = c.execute("SELECT COUNT(*) FROM ticket_media WHERE ticket_id=? AND kind=?", (tid, kind)).fetchone()[0]
    if kind == "photo" and n >= MAX_PHOTOS:
        raise HTTPException(400, f"Maximum {MAX_PHOTOS} photos")
    if kind == "video" and n >= 1:
        raise HTTPException(400, "Only 1 video is allowed")
    limit = MAX_PHOTO_B if kind == "photo" else MAX_VIDEO_B
    folder = os.path.join(UPLOAD_DIR, str(tid))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, uuid.uuid4().hex + ext)
    size, too_big = 0, False
    with open(path, "wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                too_big = True
                break
            f.write(chunk)
    if too_big or size == 0:
        os.remove(path)
        raise HTTPException(413 if too_big else 400, f"File is too large (max {limit // (1024 * 1024)} MB)" if too_big else "Empty file")
    with conn() as c:
        c.execute("INSERT INTO ticket_media(ticket_id,kind,path,filename,size) VALUES(?,?,?,?,?)", (tid, kind, path, filename, size))
    return {"ok": True}

@app.post("/tickets/{tid}/submit")
def submit_ticket(tid: int):
    with conn() as c:
        t = c.execute("SELECT status FROM tickets WHERE id=?", (tid,)).fetchone()
        if not t or t["status"] != "DRAFT":
            raise HTTPException(400, "This ticket cannot be submitted")
        if c.execute("SELECT COUNT(*) FROM ticket_media WHERE ticket_id=? AND kind='video'", (tid,)).fetchone()[0] != 1:
            raise HTTPException(400, "1 video is required")
        c.execute("UPDATE tickets SET status='OPEN' WHERE id=?", (tid,))
    return {"id": tid, "status": "OPEN"}

@app.delete("/tickets/{tid}")
def discard_draft(tid: int):
    with conn() as c:
        t = c.execute("SELECT status FROM tickets WHERE id=?", (tid,)).fetchone()
        if not t or t["status"] != "DRAFT":
            raise HTTPException(400, "Only unfinished tickets can be discarded")
        paths = [r["path"] for r in c.execute("SELECT path FROM ticket_media WHERE ticket_id=?", (tid,))]
        c.execute("DELETE FROM ticket_media WHERE ticket_id=?", (tid,))
        c.execute("DELETE FROM tickets WHERE id=?", (tid,))
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return {"discarded": tid}

@app.get("/media/{mid}")
def media(mid: int):
    with conn() as c:
        m = c.execute("SELECT * FROM ticket_media WHERE id=?", (mid,)).fetchone()
    if not m or not os.path.exists(m["path"]):
        raise HTTPException(404, "not found")
    return FileResponse(m["path"])


@app.post("/listings/{lid}/unpublish")
def unpublish(lid: int, reason: str = ""):  # admin: take a live listing down; reopens its ticket if nothing was sold
    with conn() as c:
        l = c.execute("SELECT id FROM listings WHERE id=? AND status='ACTIVE'", (lid,)).fetchone()
        if not l:
            raise HTTPException(404, "No live listing with that id")
        n = c.execute("SELECT COUNT(*) FROM orders WHERE listing_id=? AND state NOT IN ('CANCELLED','REFUNDED','RELEASED')", (lid,)).fetchone()[0]
        if n:
            raise HTTPException(400, f"{n} active order(s) on this listing - cancel or refund them first")
        sold = c.execute("SELECT COUNT(*) FROM orders WHERE listing_id=? AND state='RELEASED'", (lid,)).fetchone()[0]
        c.execute("UPDATE listings SET status='WITHDRAWN' WHERE id=?", (lid,))
        t = c.execute("SELECT id FROM tickets WHERE listing_id=? AND status='APPROVED'", (lid,)).fetchone()
        status = "WITHDRAWN"
        if t and sold:
            c.execute("UPDATE tickets SET status='UNPUBLISHED', reason=? WHERE id=?", (reason.strip() or "Removed by admin after sales", t["id"]))
            status = "UNPUBLISHED"
        elif t:
            c.execute("UPDATE tickets SET status='OPEN', grade=NULL, final_qty=NULL, price=NULL, mandi_ref=NULL, listing_id=NULL, reason=NULL WHERE id=?", (t["id"],))
            status = "OPEN"
    return {"listing": lid, "status": status}
