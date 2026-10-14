# Krishi Suraksha v3 - runs fully on your laptop
1. pip install -r requirements.txt
2. Put real prices in data/prices.csv:  python data/normalize_agmarknet.py raw.csv --state Karnataka
   (or for a dry run only: python data/make_demo_csv.py  -> SYNTHETIC, shows an orange warning banner)
3. Delete krishi.db if it exists, then:  python seed.py
4. uvicorn app.main:app --reload --port 8080   ->  open http://127.0.0.1:8080
5. Paper numbers: python -m eval.backtest data/prices.csv <Crop names>
