"""Tiny in-memory rate limiter for POST requests (per client IP, sliding window). Free, no dependencies.
Limit via env KS_RATE_LIMIT (POSTs per window; 0 turns it off). It ignores X-Forwarded-For, so behind a proxy
every user would share one IP: revisit when deploying."""
import os, time
from collections import deque

class RateLimitMiddleware:
    def __init__(self, app, limit=None, window=60.0):
        self.app = app
        self.limit = int(os.getenv("KS_RATE_LIMIT", "120")) if limit is None else limit
        self.window = window
        self.hits = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and self.limit > 0:
            ip = scope["client"][0] if scope.get("client") else "?"
            now = time.monotonic()
            q = self.hits.setdefault(ip, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                await send({"type": "http.response.start", "status": 429,
                            "headers": [(b"content-type", b"application/json"), (b"retry-after", str(int(self.window)).encode())]})
                await send({"type": "http.response.body", "body": b'{"detail":"Too many requests, please slow down"}'})
                return
            q.append(now)
        await self.app(scope, receive, send)
