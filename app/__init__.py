import os


def _load_env(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")):
    """Tiny .env reader (KEY=VALUE lines). Real environment variables win. Values are never printed."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env()
