"""Spoilage / distance risk. risk = transit_hours / remaining_shelf_hours.
SHELF_H = assumed sellable hours at ambient temperature (ESTIMATES - verify/tune; admin can edit).
Far buyers are never blocked; they get a warning. Later: tune SHELF_H from real complaint outcomes."""
import math
from datetime import datetime

SHELF_H = {"Tomato": 48, "Strawberry": 48, "Lettuce": 36, "Broccoli": 72, "Zucchini": 96, "Cauliflower": 96,
           "Cabbage": 168, "Carrot": 240, "Beetroot": 240, "Onion": 720, "Potato": 720, "Sweet Potato": 480,
           "Banana": 120, "Mango": 96, "Papaya": 96, "Pomegranate": 336, "Grapes": 120, "Guava": 96,
           "Capsicum": 120, "Avocado": 120, "Dragon Fruit": 168}
DEFAULT_SHELF_H = 96
ROAD_FACTOR, SPEED_KMPH = 1.3, 35.0   # road distance vs straight line; avg truck speed incl. stops
COORDS = {"bengaluru": (12.97, 77.59), "mysuru": (12.30, 76.64), "hubballi": (15.36, 75.12),
          "belagavi": (15.85, 74.50), "kolar": (13.14, 78.13), "tumakuru": (13.34, 77.10),
          "mangaluru": (12.91, 74.86), "ballari": (15.14, 76.92), "davanagere": (14.47, 75.92),
          "shivamogga": (13.93, 75.57), "vijayapura": (16.83, 75.71), "kalaburagi": (17.33, 76.83),
          "hassan": (13.00, 76.10), "mandya": (12.52, 76.90), "chikkaballapur": (13.43, 77.73)}

def _xy(loc):
    k = str(loc).strip().lower()
    for name, c in COORDS.items():
        if name in k:
            return c
    return None

def distance_km(a, b):
    p, q = _xy(a), _xy(b)
    if not p or not q:
        return None
    la1, lo1, la2, lo2 = map(math.radians, (*p, *q))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h)) * ROAD_FACTOR

def hours_since(harvest_iso, now=None):
    return max(((now or datetime.now()) - datetime.fromisoformat(harvest_iso)).total_seconds() / 3600, 0.0)

def assess(crop, age_h, from_loc, to_loc):
    d = distance_km(from_loc, to_loc)
    if d is None:
        return {"distance_km": None, "level": "UNKNOWN", "warn": "Distance unknown; check delivery time with the seller."}
    shelf = SHELF_H.get(crop, DEFAULT_SHELF_H)
    transit = d / SPEED_KMPH
    remaining = max(shelf - age_h, 1.0)
    risk = round(min(transit / remaining, 1.0), 2)
    level = "OK" if risk < 0.25 else "CAUTION" if risk < 0.5 else "WARNING"
    msg = {"OK": "", "CAUTION": f"{crop} may lose some freshness on this {d:.0f} km trip.",
           "WARNING": f"High spoilage risk: ~{transit:.0f} h transit vs ~{remaining:.0f} h of shelf life left. You may buy, at your own risk."}[level]
    return {"distance_km": round(d), "transit_h": round(transit, 1), "remaining_h": round(remaining, 1),
            "risk": risk, "level": level, "warn": msg}
