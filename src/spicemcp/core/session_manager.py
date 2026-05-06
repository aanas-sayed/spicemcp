"""Session lifecycle management with TTL-based auto-expiry."""

from __future__ import annotations

import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class SimSession:
    session_id: str
    simulator: str
    status: str  # created | running | completed | failed | cleaned | deleted
    work_dir: Path
    netlist_path: Path | None = None
    raw_path: Path | None = None
    log_path: Path | None = None
    domain: str | None = None
    created_at: datetime = field(default_factory=_now)
    last_accessed: datetime = field(default_factory=_now)
    meas_results: dict = field(default_factory=dict)
    signals_available: list[str] = field(default_factory=list)
    simulation_required: bool = False
    raw_file_size_mb: float = 0.0
    step_info: list = field(default_factory=list)


class SessionManager:
    """Manages simulation session lifecycle and background TTL cleanup.

    The reaper thread runs every `reaper_interval` seconds and deletes sessions
    whose last_accessed timestamp is older than `ttl_minutes`. Any tool call
    that references a session_id resets its TTL via get_session().
    """

    def __init__(
        self,
        ttl_minutes: float = 10,
        max_sessions: int = 10,
        reaper_interval: float = 30,
    ) -> None:
        self.ttl_minutes = ttl_minutes
        self.max_sessions = max_sessions
        self.reaper_interval = reaper_interval
        self._sessions: dict[str, SimSession] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reaper_loop, daemon=True)
        self._reaper.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_session(self, simulator: str) -> SimSession:
        with self._lock:
            active = [s for s in self._sessions.values() if s.status not in ("cleaned", "deleted")]
            if len(active) >= self.max_sessions:
                raise RuntimeError(
                    f"Maximum concurrent sessions ({self.max_sessions}) reached."
                    " Clean up existing sessions or wait for TTL expiry."
                    " Use list_sessions to see active sessions."
                )
            session_id = secrets.token_hex(6)
            work_dir = Path(tempfile.mkdtemp(prefix=f"spicemcp_{session_id}_"))
            session = SimSession(
                session_id=session_id,
                simulator=simulator,
                status="created",
                work_dir=work_dir,
            )
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> SimSession | None:
        """Return the session and reset its TTL. Returns None if not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_accessed = _now()
            return session

    def touch(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_accessed = _now()

    def list_sessions(self) -> list[SimSession]:
        with self._lock:
            return list(self._sessions.values())

    def cleanup_session(
        self,
        session_id: str,
        keep_log: bool = True,
        delete_session: bool = False,
    ) -> float:
        """Delete raw (and optionally log) files. Returns megabytes freed.

        If delete_session=True, removes the work directory entirely and
        removes the session from the registry.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return 0.0

            freed_mb = 0.0

            if session.raw_path and session.raw_path.exists():
                freed_mb += session.raw_path.stat().st_size / (1024 * 1024)
                session.raw_path.unlink()
                session.raw_path = None
                session.raw_file_size_mb = 0.0

            if not keep_log and session.log_path and session.log_path.exists():
                freed_mb += session.log_path.stat().st_size / (1024 * 1024)
                session.log_path.unlink()
                session.log_path = None

            session.status = "cleaned"

            if delete_session:
                if session.work_dir.exists():
                    for f in session.work_dir.rglob("*"):
                        if f.is_file():
                            freed_mb += f.stat().st_size / (1024 * 1024)
                    shutil.rmtree(session.work_dir, ignore_errors=True)
                session.status = "deleted"
                del self._sessions[session_id]

            return freed_mb

    # ------------------------------------------------------------------
    # TTL reaper (called by daemon thread and directly in tests)
    # ------------------------------------------------------------------

    def _is_expired(self, session: SimSession) -> bool:
        if session.status in ("cleaned", "deleted"):
            return False
        return _now() - session.last_accessed > timedelta(minutes=self.ttl_minutes)

    def _reap_expired(self) -> int:
        """Synchronously delete all expired sessions. Returns count reaped."""
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
        for sid in expired:
            self.cleanup_session(sid, keep_log=False, delete_session=True)
        return len(expired)

    def _reaper_loop(self) -> None:
        while not self._stop.wait(timeout=self.reaper_interval):
            self._reap_expired()

    def stop(self) -> None:
        """Stop the reaper thread. Useful in tests to avoid resource warnings."""
        self._stop.set()
