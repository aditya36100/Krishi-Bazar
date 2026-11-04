from app.spoilage import assess, distance_km, hours_since

def test_distance_sane():
    assert 250 < distance_km("Bengaluru", "Hubballi") < 600
    assert distance_km("Atlantis", "Kolar") is None

def test_tomato_near_ok_far_warn():
    assert assess("Tomato", 2, "Kolar", "Bengaluru")["level"] == "OK"
    assert assess("Tomato", 24, "Hubballi", "Bengaluru")["level"] == "WARNING"

def test_potato_far_ok_and_unknown():
    assert assess("Potato", 24, "Hubballi", "Bengaluru")["level"] == "OK"
    assert assess("Tomato", 2, "Kolar", "Nowhere")["level"] == "UNKNOWN"

def test_hours_since():
    from datetime import datetime
    assert hours_since("2026-11-01T00:00:00", datetime(2026, 11, 2)) == 24
