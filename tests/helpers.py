"""Small helpers so tests can register people and call the API with a login token."""
import itertools
_n = itertools.count(1)
PW = "pass-12345"
ADMIN_PW = "test-admin-password"


def bearer(token):
    return {"Authorization": "Bearer " + token}


def register(client, role, name=None, loc="Bangalore", buyer_type="Other"):
    """Register a farmer or buyer; returns (user_id, auth_headers)."""
    ph = "98765%05d" % next(_n)
    body = {"name": name or f"{role}-{ph}", "role": role, "loc": loc, "phone": ph, "password": PW,
            "buyer_type": buyer_type if role == "buyer" else ""}
    r = client.post("/users", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    return j["id"], bearer(j["token"])


def admin(client):
    r = client.post("/login", json={"phone": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return bearer(r.json()["token"])
