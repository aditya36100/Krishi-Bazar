"""Photo quality and duplicate checks for ticket photos. Flags only, for the admin; it cannot judge produce quality.
Checks: blur (variance of Laplacian), brightness, low resolution, and near-duplicates (64-bit difference hash).
Thresholds are HEURISTICS (placeholders): see eval/image_eval.py for how they behave on synthetic images.
Pillow is imported lazily so the app still starts if Pillow is missing."""
import numpy as np

BLUR_MIN = 100.0   # variance of Laplacian below this = BLURRY
DARK_MAX = 40.0    # mean grey level below this = TOO_DARK
BRIGHT_MIN = 220.0 # mean grey level above this = TOO_BRIGHT
MIN_SIDE = 400     # pixels
DUP_BITS = 6       # Hamming distance <= this = near-duplicate

def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS media_flags(media_id INTEGER PRIMARY KEY, ticket_id INT, blur REAL, brightness REAL, w INT, h INT, phash TEXT, flags TEXT)")

def analyze(path):
    from PIL import Image
    im = Image.open(path)
    im.load()
    w, h = im.size
    g = im.convert("L")
    g.thumbnail((512, 512))
    a = np.asarray(g, dtype=float)
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    blur, bright = float(lap.var()), float(a.mean())
    s = np.asarray(g.resize((9, 8)), dtype=float)
    bits = (s[:, 1:] > s[:, :-1]).flatten()
    ph = 0
    for b in bits:
        ph = (ph << 1) | int(b)
    flags = []
    if blur < BLUR_MIN: flags.append("BLURRY")
    if bright < DARK_MAX: flags.append("TOO_DARK")
    if bright > BRIGHT_MIN: flags.append("TOO_BRIGHT")
    if min(w, h) < MIN_SIDE: flags.append("LOW_RESOLUTION")
    return {"blur": round(blur, 1), "brightness": round(bright, 1), "w": w, "h": h, "phash": format(ph, "016x"), "flags": flags}

def hamming(h1, h2):
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")

def analyze_and_store(c, media_id, ticket_id, path):
    r = analyze(path)
    for row in c.execute("SELECT media_id, ticket_id, phash FROM media_flags").fetchall():
        if hamming(r["phash"], row[2]) <= DUP_BITS:
            r["flags"].append("DUPLICATE_IN_TICKET" if row[1] == ticket_id else "DUPLICATE_OF_OTHER_TICKET")
            break
    c.execute("INSERT OR REPLACE INTO media_flags(media_id,ticket_id,blur,brightness,w,h,phash,flags) VALUES(?,?,?,?,?,?,?,?)",
              (media_id, ticket_id, r["blur"], r["brightness"], r["w"], r["h"], r["phash"], ",".join(r["flags"])))
    return r["flags"]

def flags_for_ticket(c, ticket_id):
    rows = c.execute("SELECT media_id, blur, brightness, w, h, flags FROM media_flags WHERE ticket_id=? ORDER BY media_id", (ticket_id,)).fetchall()
    return [{"media_id": r[0], "blur": r[1], "brightness": r[2], "size": f"{r[3]}x{r[4]}", "flags": [f for f in (r[5] or "").split(",") if f]} for r in rows]
