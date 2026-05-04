"""Version-aware result cache. Excludes Monte Carlo simulations."""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_MC_PATTERN = re.compile(r"\bmc\s*\(", re.IGNORECASE)


def is_monte_carlo(netlist: str) -> bool:
    """Return True if the netlist contains Monte Carlo expressions."""
    return bool(_MC_PATTERN.search(netlist))


def cache_key(simulator: str, image_tag: str, netlist: str) -> str:
    """Stable SHA-256 cache key including simulator version."""
    canonical = netlist.strip()
    payload = f"{simulator}:{image_tag}:{canonical}"
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class _Entry:
    value: Any
    expires_at: datetime


class SimCache:
    """Thread-safe in-memory result cache with TTL and Monte Carlo exclusion.

    Monte Carlo netlists (those containing mc() expressions) are never cached.
    Cache keys incorporate the simulator type and Docker image tag so solver
    version changes between image updates do not serve stale results.
    """

    def __init__(self, ttl_minutes: float = 60, max_entries: int = 200) -> None:
        self.ttl_minutes = ttl_minutes
        self.max_entries = max_entries
        self._store: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return cached value or None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if datetime.now(tz=timezone.utc) >= entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any) -> None:
        """Store a value. Evicts oldest entry if at capacity."""
        with self._lock:
            if len(self._store) >= self.max_entries and key not in self._store:
                oldest = min(self._store, key=lambda k: self._store[k].expires_at)
                del self._store[oldest]
            expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=self.ttl_minutes)
            self._store[key] = _Entry(value=value, expires_at=expires_at)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
