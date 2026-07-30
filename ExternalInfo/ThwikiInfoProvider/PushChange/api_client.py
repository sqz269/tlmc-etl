"""Shared plumbing for the v6 backend push scripts.

Configuration comes from the environment:
  TLMC_API_BASE          backend base url (default http://localhost:30081,
                         the k3s NodePort)
  TLMC_INTERNAL_API_KEY  value for the X-Internal-Api-Key header; fetch with
    kubectl -n tlmc-player get secret backend-api-config \
      -o jsonpath='{.data.Internal__ApiKey}' | base64 -d

The wire is snake_case throughout (Newtonsoft SnakeCaseNamingStrategy on the
backend), including enum values ("arranger", "active").
"""

import os
import sys
import time
import uuid as uuid_lib

import requests

API_BASE = os.environ.get("TLMC_API_BASE", "http://localhost:30081").rstrip("/")
_API_KEY = os.environ.get("TLMC_INTERNAL_API_KEY")

_RETRYABLE = {429, 502, 503, 504}

# Crockford base32, lowercase — the TypeID spec alphabet.
_TYPEID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def typeid(prefix: str, uuid_str: str) -> str:
    """Encodes a bare uuid as a TypeID string ("trk_01h455..."), which is the
    only id format the backend routes bind. Mirrors Ids/TypeId.cs."""
    value = int.from_bytes(uuid_lib.UUID(uuid_str).bytes, "big")
    chars = []
    for _ in range(26):
        chars.append(_TYPEID_ALPHABET[value & 0x1F])
        value >>= 5
    suffix = "".join(reversed(chars))
    return f"{prefix}_{suffix}" if prefix else suffix


def track_typeid(uuid_str: str) -> str:
    return typeid("trk", uuid_str)


def release_typeid(uuid_str: str) -> str:
    return typeid("rel", uuid_str)


def require_api_key() -> str:
    if not _API_KEY:
        print(
            "TLMC_INTERNAL_API_KEY is not set. Fetch it with:\n"
            "  kubectl -n tlmc-player get secret backend-api-config "
            "-o jsonpath='{.data.Internal__ApiKey}' | base64 -d",
            file=sys.stderr,
        )
        sys.exit(1)
    return _API_KEY


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["X-Internal-Api-Key"] = require_api_key()
    session.headers["Content-Type"] = "application/json"
    return session


def send(session: requests.Session, method: str, path: str, payload, retries: int = 3):
    """One API call. Returns the Response; retries transient statuses.

    Raises nothing: callers inspect .status_code so one bad row never kills a
    100k-row push. Connection errors do raise after the retry budget — if the
    backend is down, stopping is correct.
    """
    url = f"{API_BASE}{path}"
    for attempt in range(retries + 1):
        try:
            resp = session.request(method, url, json=payload, timeout=120)
        except requests.ConnectionError:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in _RETRYABLE and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        return resp
    return resp
