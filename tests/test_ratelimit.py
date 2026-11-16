from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.ratelimit import RateLimitMiddleware

def test_limits_posts_only():
    a = FastAPI()
    a.add_middleware(RateLimitMiddleware, limit=2, window=60)
    @a.post("/x")
    def x(): return {"ok": True}
    @a.get("/y")
    def y(): return {"ok": True}
    c = TestClient(a)
    assert c.post("/x").status_code == 200
    assert c.post("/x").status_code == 200
    assert c.post("/x").status_code == 429
    assert c.get("/y").status_code == 200
