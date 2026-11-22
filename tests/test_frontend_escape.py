"""User-supplied text must be HTML-escaped before it is put into innerHTML."""
import json, pathlib, re, shutil, subprocess, pytest
from fastapi.testclient import TestClient
from app import main
from tests.helpers import register, admin

HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
FIELD = r"(?:name|loc|location|notes|reason|farmer|buyer|farmer_name|variety|crop|buyer_type)"
REF = re.compile(r"(?<![\w.$])([A-Za-z_]\w*\." + FIELD + r")\b")
EXPR = re.compile(r"\$\{([^{}`]*)\}")
PAYLOAD = "<img src=x onerror=alert(1)>"


def test_no_unescaped_user_fields_in_templates():
    bad = [m.group(1) for m in EXPR.finditer(HTML)
           if not any(k in m.group(1) for k in ("escH(", "esc(", "encodeURIComponent", "=>")) and REF.search(m.group(1))]
    assert not bad, bad[:5]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_escape_helper_neutralises_payload():
    line = re.search(r"const escH = .*", HTML).group(0)
    out = subprocess.run(["node", "-e", line + "\nconsole.log(escH(" + json.dumps(PAYLOAD) + "))"], capture_output=True, text=True).stdout.strip()
    assert out == "&lt;img src=x onerror=alert(1)&gt;"


def test_hostile_name_is_stored_raw_and_served_raw():
    client = TestClient(main.app)
    uid, _ = register(client, "farmer", name=PAYLOAD)
    names = [u["name"] for u in client.get("/users", headers=admin(client)).json()]
    assert PAYLOAD in names  # stored and served raw; escaping happens only at render time
