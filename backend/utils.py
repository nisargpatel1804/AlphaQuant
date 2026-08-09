# backend/utils.py

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


# ----------------------------------------------------------------------
# TTL Cache (formerly backend/main/services/cache.py)
# ----------------------------------------------------------------------
class CacheEntry:
    def __init__(self, value: Any, expires_at: datetime):
        self.value = value
        self.expires_at = expires_at


class SimpleTTLCache:
    """Simple in-memory cache with time-to-live."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < datetime.utcnow():
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = CacheEntry(
            value=value,
            expires_at=datetime.utcnow() + timedelta(seconds=self.ttl_seconds),
        )

    def clear(self) -> None:
        self._store.clear()


# Global cache instance – shared across the application
cache = SimpleTTLCache(ttl_seconds=300)


# ----------------------------------------------------------------------
# Utility functions (formerly backend/main/utils.py)
# ----------------------------------------------------------------------
def normalize_ticker(ticker: str) -> str:
    """Strip and uppercase a ticker symbol."""
    return ticker.strip().upper()


def to_serializable(value: Any) -> Any:
    """
    Recursively convert a value to a JSON-serializable format.
    Handles dataclasses, dicts, lists, tuples, and numpy types.
    """
    if is_dataclass(value):
        return to_serializable(asdict(value))
    if isinstance(value, dict):
        return {key: to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_serializable(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except Exception:
            return value
    return value