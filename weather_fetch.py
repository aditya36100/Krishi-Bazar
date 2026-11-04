"""Fetch daily weather for 4 Karnataka mandi regions from Open-Meteo (free, no key, non-commercial).
Averages them into data/weather.csv (date, temp_c, rain_mm). Usage: python weather_fetch.py"""
import json, ssl, time, urllib.request, urllib.parse
import pandas as pd
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

PLACES = {"Bengaluru": (12.97, 77.59), "Hubballi": (15.36, 75.12), "Belagavi": (15.85, 74.50), "Kolar": (13.14, 78.13)}
URL = "https://archive-api.open-meteo.com/v1/archive"

def get(lat, lon, start="2018-01-01", end="2025-10-30"):
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                                "daily": "temperature_2m_mean,precipitation_sum", "timezone": "Asia/Kolkata"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{URL}?{q}", context=CTX, timeout=60) as r:
                return json.load(r)["daily"]
        except Exception as e:
            print("retry", attempt + 1, e); time.sleep(20 * (attempt + 1))
    raise SystemExit("Open-Meteo failed 4 times")

def main(out="data/weather.csv"):
    frames = []
    for name, (lat, lon) in PLACES.items():
        d = get(lat, lon)
        frames.append(pd.DataFrame({"date": pd.to_datetime(d["time"]), "temp_c": d["temperature_2m_mean"],
                                    "rain_mm": d["precipitation_sum"]}).set_index("date"))
        print("got", name, len(d["time"])); time.sleep(2)
    m = sum(f.fillna(0) for f in frames) / len(frames)
    m.round(2).reset_index().to_csv(out, index=False)
    print("saved", out, len(m), "rows"); print(m.describe().round(1))

if __name__ == "__main__":
    main()
