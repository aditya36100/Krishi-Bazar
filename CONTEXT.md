# Project Context

> Paste this file into the chat at the start of a new session instead of re-typing the brief.

## Identity
- Developer: Aditya, student, India, Windows + PowerShell + Antigravity IDE.
- Repo: github.com/aditya36100/Krishi-Bazar, working branch: **adiai**.
- Workspace: `c:\Users\adity\Desktop\ks2`

## Paper Title
"AI-Based Verifiable Farm-to-Buyer Marketplace with Conformal Price Forecasting and Tamper-Evident Escrow"

Old name in code/UI: **Krishi Bazar** (rename later, roadmap step 4). Goal: a working app + a research paper with real CS depth. Mentor called earlier version PU-level; depth and measured results matter more than extra features. Honest framing: algorithms are known; contribution is a carefully built, measured end-to-end system. Do not claim novelty.

## Tech Stack (free only, add nothing paid)
Python 3.12, venv `.venv`, FastAPI, SQLite (`app/db.py`), pandas, scikit-learn 1.9.1, statsmodels 0.15.0, lightgbm 4.7.0, pytest, single-file `frontend/index.html`.

Data: CEDA Agmarknet, Karnataka daily modal prices 2018-01-01 to 2025-10-30, 15 crops, Rs/kg, in `data/prices.csv`.
Credit: **"Centre for Economic Data & Analysis, Ashoka University"** (free for non-commercial use; never share anyone's key).
Weather data: parked.

## How It Works
- Farmer submits a **sell ticket**; admin visits, grades (A/B/C), sets or overrides price, approves → creates a listing.
- Buyers see the listing with a markup (whole lot only; min kg by buyer type).
- Subscribers get **early access only**, never a price discount.
- Order → escrow state machine (`app/escrow.py`) with deposit; every money event appended to a hash-chained ledger (BEGIN IMMEDIATE, `tx()` in `app/db.py`).
- `app/pricing.py`: ridge on 4 log-price lags, split-conformal intervals, cold_start proxy.
- `app/pricing_rules.py` `quote()`: G = price×qty×quality; farmer gets G×(1−1%); buyer pays G×1.05 capped at MRP; platform earns the difference.
- `app/reliability.py`: Beta-Bernoulli user scoring.
- `app/spoilage.py` `assess()`: distance, transit hours, risk OK/CAUTION/WARNING (shelf-life values are ESTIMATES; warn far buyers, never block).
- `app/cases.py`: TF-IDF case-based learning; auto-resolve only if admin allowed it, else escalate.
- `eval/compare.py`: compares 5 baselines (naive, seasonal-naive, ridge, ETS, ARIMA) on one rolling split, h=2 weeks, 40 test weeks, 26-point conformal calibration, alpha=0.1.

## Known Results (never invent others)
MAPE% naive/ridge: Tomato 15.3/14.8, Onion 9.4/8.0, Potato 7.9/7.9, Banana 11.0/12.5, Carrot 10.5/10.0, Mango 24.1/27.9.
Price history alone barely beats naive at 2 weeks. Intervals are very wide (44–100% of price). Seasonal-naive is much worse.
Count forecast horizon from last observed date (Oct 2025), not today.

## Done
- Ledger race fixed; subscriber discount removed; `quote()` wired into `/price/{crop}` (optional qty, quality); 16 tests pass.

## Known Issue (flag before changing)
`escrow.py` FEE defaults to 0.05 but the decision is **1% farmer fee and 5% buyer fee**. Need to align defaults, keep them admin-editable.

## Roadmap (strict order)
1. Wire `quote()` into `/orders` and ticket approve flow; spoilage warning in `/listings` for far buyers; connect `cases.py` to tickets/disputes.
2. LightGBM quantile model (lag + calendar features) with adaptive conformal intervals (ACI), compared with the 5 baselines on the same split. This is the paper's core result.
3. Isolation Forest for price/order anomalies; min-cost-flow farmer-buyer matching; Thompson sampling on reliability; Merkle-tree proofs on the ledger; idempotency keys, rate limiting, event replay. Each compared with a simple baseline.
4. Rename Krishi Bazar to a technical name in code and UI; add the CEDA credit; migrate to Supabase Postgres (BEGIN IMMEDIATE → SELECT ... FOR UPDATE); rebuild seed data on real crops.
5. Draft the paper.

## Caveats
- Karnataka APMC Act caps agent commission and recovers from buyer → farmer fee may not be a better deal. Treat the app as a demo/pilot until mentor confirms licensing.
- Do NOT run `seed.py` yet.
- Verify free-tier limits (Supabase etc.) by web search before telling Aditya.

## Anti-Hallucination Rules
- Before editing a file, read exact lines. Never guess function names, columns or file contents.
- If unsure, say "I don't know, checking" and check. Never invent numbers, results, library features or UI wording.
- Cite file and line numbers for every change.
- Report only what you actually ran and saw.

## Token Rules
- Never re-read or print whole large files. Use `Select-String` or line ranges.
- No recaps, no restating the message, no filler. 80–250 words per reply, except when code is needed.
- Make small patches, not full-file rewrites. Do not run long commands or print long output.

## Teaching Rules
- Work through a whole roadmap item autonomously, running tests after each change. Stop and ask Aditya only when: (a) a test fails and can't be fixed in two tries, (b) need to delete or rewrite a file, (c) a choice affects fee rules, licensing or the paper's claims, or (d) it is time to commit.
- At each stop, give a short summary of 5 lines or fewer: what changed (file and line numbers), test result, and what's next.
- Give paste-ready PowerShell. Patch files with a small temporary Python script that asserts each old string occurs exactly once, run it, then delete it.
- Recommend one option and say why in one line.

## Security
- Never ask Aditya to paste secrets. `.env` stays out of git.
- Before every commit: `git add .` then `git status --short`, confirm `.env`, `.venv` and `*.session` files are NOT listed.

