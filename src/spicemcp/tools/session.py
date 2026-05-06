"""MCP tool handlers for session management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_session(simulator: str) -> dict:
    """Create a new simulation session.

    Returns session_id and TTL info, or an error if the simulator is
    unknown or the session limit has been reached.
    """
    from spicemcp import _globals

    if simulator not in ("ltspice", "ngspice"):
        return {
            "session_id": None,
            "simulator": simulator,
            "status": None,
            "expires_in_minutes": None,
            "error": (f"Unknown simulator '{simulator}'. Valid values: 'ltspice', 'ngspice'."),
        }

    manager = _globals.manager
    try:
        session = manager.create_session(simulator)
    except RuntimeError as exc:
        return {
            "session_id": None,
            "simulator": simulator,
            "status": None,
            "expires_in_minutes": None,
            "error": str(exc),
        }

    return {
        "session_id": session.session_id,
        "simulator": session.simulator,
        "status": session.status,
        "expires_in_minutes": manager.ttl_minutes,
        "error": None,
    }


def list_sessions() -> dict:
    """List all active sessions with TTL and file-size information."""
    from spicemcp import _globals

    manager = _globals.manager
    sessions = manager.list_sessions()

    rows = []
    total_raw_mb = 0.0
    for s in sessions:
        expires_delta = s.last_accessed + timedelta(minutes=manager.ttl_minutes) - _now()
        expires_in_seconds = max(0, int(expires_delta.total_seconds()))
        has_raw = s.raw_path is not None and s.raw_path.exists()
        rows.append(
            {
                "session_id": s.session_id,
                "simulator": s.simulator,
                "status": s.status,
                "domain": s.domain,
                "created_at": s.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_accessed_at": s.last_accessed.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "expires_in_seconds": expires_in_seconds,
                "has_raw_file": has_raw,
                "raw_file_size_mb": round(s.raw_file_size_mb, 3),
                "has_meas_results": bool(s.meas_results),
                "simulation_required": s.simulation_required,
            }
        )
        total_raw_mb += s.raw_file_size_mb

    return {
        "sessions": rows,
        "total_sessions": len(rows),
        "total_raw_mb": round(total_raw_mb, 3),
    }


def cleanup_session(
    session_id: str,
    keep_log: bool = True,
    delete_session: bool = False,
) -> dict:
    """Clean up raw files (and optionally the whole session) for a session.

    Returns freed_mb and the resulting session status. If the session does
    not exist, returns status 'not_found' - this is idempotent, not an error.
    """
    from spicemcp import _globals

    manager = _globals.manager
    session = manager.get_session(session_id)
    if session is None:
        return {
            "freed_mb": 0.0,
            "session_status": "not_found",
            "error": None,
        }

    freed_mb = manager.cleanup_session(
        session_id,
        keep_log=keep_log,
        delete_session=delete_session,
    )
    if delete_session:
        final_status = "deleted"
    else:
        # Re-fetch if not deleted (still in registry)
        remaining = manager.get_session(session_id)
        final_status = remaining.status if remaining else "deleted"

    return {
        "freed_mb": round(freed_mb, 3),
        "session_status": final_status,
        "error": None,
    }
