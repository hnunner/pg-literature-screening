"""Minimal .env loader.

Deliberately not python-dotenv: this needs to read five keys from one file, and
avoiding the dependency keeps `pip install` to the two SDKs. Existing
environment variables always win, so a shell export can override the file.
"""

import os
from pathlib import Path


def load_env(path=".env"):
    env_path = Path(path)
    if not env_path.is_file():
        return {}
    loaded = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded
