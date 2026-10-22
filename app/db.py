import sqlite3, os
DB = os.getenv("KS_DB", "krishi.db")

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, role TEXT, loc TEXT);
        CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY, farmer_id INT, crop TEXT, qty REAL,
            harvest_date TEXT, price REAL, loc TEXT, mandi_ref REAL);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, listing_id INT, buyer_id INT, qty REAL,
            amount REAL, state TEXT DEFAULT 'PLACED', deposit_pct REAL, created TEXT);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, order_id INT, event TEXT, detail TEXT,
            ts TEXT, prev_hash TEXT, hash TEXT);
        CREATE TABLE IF NOT EXISTS outcomes(id INTEGER PRIMARY KEY, order_id INT, party_id INT, kind TEXT, ok INT);
        """)
        try:
            c.execute("ALTER TABLE listings ADD COLUMN status TEXT DEFAULT 'ACTIVE'")
        except sqlite3.OperationalError:
            pass
        for ddl in ("ALTER TABLE listings ADD COLUMN variety TEXT DEFAULT ''",
                    "ALTER TABLE orders ADD COLUMN buyer_amount REAL"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY, buyer_id INT, plan TEXT, price REAL, starts TEXT, ends TEXT)")
        try:
            c.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        for ddl in ("ALTER TABLE users ADD COLUMN buyer_type TEXT DEFAULT ''",
                    "ALTER TABLE listings ADD COLUMN grade TEXT DEFAULT ''"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        for ddl in ("ALTER TABLE listings ADD COLUMN buyer_markup REAL",
                    "ALTER TABLE listings ADD COLUMN early_hours REAL DEFAULT 0",
                    "ALTER TABLE listings ADD COLUMN live_at TEXT"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, farmer_id INT, crop TEXT, variety TEXT, qty REAL, notes TEXT, status TEXT DEFAULT 'OPEN', visit_date TEXT, grade TEXT, final_qty REAL, price REAL, mandi_ref REAL, reason TEXT, listing_id INT, created TEXT)")
        for nm, bt in (("Green Leaf Restaurant", "Restaurant"), ("Taj Residency Hotels", "Hotel"),
                       ("FreshMart Supermarket", "Supermarket"), ("AgroExports Pvt Ltd", "Exporter")):
            c.execute("UPDATE users SET buyer_type=? WHERE name=? AND role='buyer' AND (buyer_type IS NULL OR buyer_type='')", (bt, nm))
        for ddl in ("ALTER TABLE tickets ADD COLUMN location TEXT DEFAULT ''",
                    "ALTER TABLE tickets ADD COLUMN phone TEXT DEFAULT ''",
                    "ALTER TABLE tickets ADD COLUMN alt_phone TEXT DEFAULT ''",
                    "ALTER TABLE tickets ADD COLUMN pref_date TEXT DEFAULT ''",
                    "ALTER TABLE tickets ADD COLUMN pref_slot TEXT DEFAULT ''"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE TABLE IF NOT EXISTS ticket_media(id INTEGER PRIMARY KEY, ticket_id INT, kind TEXT, path TEXT, filename TEXT, size INT)")
