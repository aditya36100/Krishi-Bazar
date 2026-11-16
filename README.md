# Krishi Bazar

A marketplace that connects farmers directly with buyers. It runs fully on your own computer with Python, FastAPI and SQLite. No paid services are needed.

## What it does

- Farmers list crops through tickets with photos and a video. Photos are checked with simple image heuristics.
- Buyers browse listings, place orders and pay through an escrow flow. Payments are a demo and no real money moves.
- Every money movement is recorded in a tamper-evident ledger (Merkle hash chain). You can verify it at `/ledger/verify`.
- Price forecasts use a LightGBM model on historical Karnataka mandi prices.
- Disputes are handled as cases, and an admin view shows summaries and settings.

## Requirements

- Python 3 on Windows, macOS or Linux
- The packages in `requirements.txt`

## Setup (Windows PowerShell)

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

2. Install the packages:

```powershell
pip install -r requirements.txt
```

3. Get price data. `data/prices.csv` is not stored in git, so create it in one of two ways:

   - Download Karnataka prices from the CEDA API:

     ```powershell
     python ceda_fetch.py
     ```

     This needs a free CEDA API key in a file named `.env` in the project folder, on one line:
     `CEDA_API_KEY=your_key_here`
     Never share or commit this file.

   - Or convert your own CSV file:

     ```powershell
     python data/normalize_agmarknet.py raw.csv --state Karnataka
     ```

   For a quick dry run only, `python data/make_demo_csv.py` writes SYNTHETIC prices and the app shows a warning banner.

4. Create demo data. Skip this if `krishi.db` already exists. To start fresh, delete `krishi.db` first:

```powershell
python seed.py
```

You can name crops, for example `python seed.py Tomato Onion`. By default it uses the 4 crops with the most price history.

## Run the app

```powershell
python -m uvicorn app.main:app --reload --port 8080
```

Open http://127.0.0.1:8080 in your browser. Press `Ctrl+C` in the terminal to stop it.

## Run the tests

```powershell
pip install pytest httpx
python -m pytest -q tests
```

## Settings (optional environment variables)

All have defaults. Set them in PowerShell before starting the app, for example `$env:KS_MIN_KG = "50"`.

| Variable | Default | Meaning |
|---|---|---|
| KS_DB | krishi.db | Database file |
| KS_PRICES | data/prices.csv | Price data file |
| KS_MARGIN | 0.15 | Direct-sale premium over the mandi price |
| KS_MIN_KG | 100 | Minimum listing and order size in kg |
| KS_FARMER_COMMISSION | 0.01 | Share taken from the farmer |
| KS_BUYER_MARKUP | 0.05 | Markup added to the buyer price |
| KS_CANCEL_FEE | 0.10 | Cancellation fee after the free window |
| KS_RATE_LIMIT | 120 | Request rate limit |

## Evaluation scripts

The `eval` folder holds the scripts behind the numbers in `results/`. Price backtests take a data file and optional crop names:

```powershell
python -m eval.backtest data/prices.csv Tomato Onion
```

## Known limits

- Payments and subscriptions are demo only. Subscription prices, buyer minimum quantities, grade factors and image-check thresholds are placeholders.
- It runs locally only. There is no deployment setup yet.
- Do not commit `.env`, `krishi.db`, `uploads/` or `.venv/`. They are already listed in `.gitignore`.