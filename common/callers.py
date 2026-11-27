"""
Registered callers — lets an inbound call be greeted by name.

Deliberately minimal, because this stores personal data on a demo box:
  - only a phone number and a display name, nothing else
  - every entry expires after REGISTRATION_TTL_HOURS and is purged on access
  - no verification, so treat a match as a convenience, never as identity;
    nothing sensitive may be gated on it

Backed by a JSON file under logs/ (a bind mount), so registrations survive a
container rebuild but are trivially wipeable with a single rm.
"""
import json
import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

REGISTRATION_TTL_HOURS = 24
STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "callers.json"
)

_lock = threading.Lock()


def normalize_phone(raw):
    """Best-effort E.164 for US-style input; returns None if implausible."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) < 11 or len(digits) > 15:
        return None
    return "+" + digits


def _load():
    try:
        with open(STORE_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, STORE_PATH)


def _purge_expired(data):
    """Drop entries past their TTL. Returns (kept, removed_count)."""
    cutoff = time.time() - REGISTRATION_TTL_HOURS * 3600
    kept = {k: v for k, v in data.items() if v.get("registered_at", 0) >= cutoff}
    return kept, len(data) - len(kept)


def register(phone, name):
    """Store a display name for a phone number. Returns (phone, error)."""
    normalized = normalize_phone(phone)
    if not normalized:
        return None, "That doesn't look like a phone number."
    clean_name = (name or "").strip()[:40]
    if not clean_name:
        return None, "A name is required."

    with _lock:
        data, expired = _purge_expired(_load())
        data[normalized] = {"name": clean_name, "registered_at": time.time()}
        _save(data)
    logger.info(
        f"Caller registered: {normalized[:-4]}**** as {clean_name!r} "
        f"(expires in {REGISTRATION_TTL_HOURS}h, purged {expired} stale)"
    )
    return normalized, None


def lookup(phone):
    """Return the display name for a caller, or None."""
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    with _lock:
        data, expired = _purge_expired(_load())
        if expired:
            _save(data)
        entry = data.get(normalized)
    return entry.get("name") if entry else None


def forget(phone):
    """Remove a registration on request."""
    normalized = normalize_phone(phone)
    if not normalized:
        return False
    with _lock:
        data, _ = _purge_expired(_load())
        existed = data.pop(normalized, None) is not None
        _save(data)
    return existed


def count():
    """How many live registrations exist (for the dashboard)."""
    with _lock:
        data, _ = _purge_expired(_load())
    return len(data)
