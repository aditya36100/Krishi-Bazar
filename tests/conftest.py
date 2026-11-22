"""Every test runs against its own temporary database. krishi.db is never touched."""
import os, tempfile
_TMP = tempfile.mkdtemp(prefix="ks_tests_")
os.environ["KS_DB"] = os.path.join(_TMP, "session.db")  # set before app.main is imported (it calls db.init() on import)
os.environ["KS_SECRET"] = "test-secret-not-for-production"
os.environ["KS_ADMIN_USER"] = "admin"
os.environ["KS_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["KS_RATE_LIMIT"] = "1000000"  # the many HTTP tests must not trip the rate limiter
os.environ.setdefault("KS_PRICES", os.path.join(os.path.dirname(__file__), "..", "data", "prices.csv"))

import pytest
from app import db, escrow, cases, idempotency, imagecheck, auth


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(escrow, "FEE", 0.01)
    monkeypatch.setattr(escrow, "BUYER_MARKUP", 0.05)
    monkeypatch.setattr(escrow, "CANCEL_FEE", 0.10)
    db.init()
    with db.conn() as c:
        cases.init(c); idempotency.init(c); imagecheck.init(c)
    auth.ensure_admin()
    yield
