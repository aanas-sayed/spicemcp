"""Session manager tests."""

import time

import pytest

from spicemcp.core.session_manager import SessionManager, SimSession


@pytest.fixture
def mgr():
    m = SessionManager(ttl_minutes=10, max_sessions=5, reaper_interval=9999)
    yield m
    m.stop()


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


def test_create_session_returns_sim_session(mgr):
    s = mgr.create_session("ltspice")
    assert isinstance(s, SimSession)


def test_session_id_is_twelve_hex_chars(mgr):
    s = mgr.create_session("ltspice")
    assert len(s.session_id) == 12
    assert all(c in "0123456789abcdef" for c in s.session_id)


def test_create_session_sets_simulator(mgr):
    s = mgr.create_session("ngspice")
    assert s.simulator == "ngspice"


def test_create_session_status_is_created(mgr):
    s = mgr.create_session("ltspice")
    assert s.status == "created"


def test_create_session_work_dir_exists(mgr):
    s = mgr.create_session("ltspice")
    assert s.work_dir.exists()
    assert s.work_dir.is_dir()


def test_create_session_work_dir_uses_session_id(mgr):
    s = mgr.create_session("ltspice")
    assert s.session_id in s.work_dir.name


def test_create_session_unique_ids(mgr):
    ids = {mgr.create_session("ltspice").session_id for _ in range(5)}
    assert len(ids) == 5


def test_create_session_enforces_max_sessions(mgr):
    for _ in range(5):
        mgr.create_session("ltspice")
    with pytest.raises(RuntimeError, match="Maximum concurrent sessions"):
        mgr.create_session("ltspice")


def test_cleaned_sessions_do_not_count_toward_limit(mgr):
    sessions = [mgr.create_session("ltspice") for _ in range(5)]
    mgr.cleanup_session(sessions[0].session_id, delete_session=True)
    new = mgr.create_session("ltspice")
    assert new is not None


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


def test_get_session_returns_session(mgr):
    s = mgr.create_session("ltspice")
    found = mgr.get_session(s.session_id)
    assert found is s


def test_get_session_returns_none_for_unknown(mgr):
    assert mgr.get_session("nonexistent") is None


def test_get_session_resets_last_accessed(mgr):
    s = mgr.create_session("ltspice")
    before = s.last_accessed
    time.sleep(0.05)
    mgr.get_session(s.session_id)
    assert s.last_accessed > before


# ---------------------------------------------------------------------------
# touch
# ---------------------------------------------------------------------------


def test_touch_updates_last_accessed(mgr):
    s = mgr.create_session("ltspice")
    before = s.last_accessed
    time.sleep(0.05)
    mgr.touch(s.session_id)
    assert s.last_accessed > before


def test_touch_unknown_session_is_noop(mgr):
    mgr.touch("doesnotexist")  # should not raise


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty(mgr):
    assert mgr.list_sessions() == []


def test_list_sessions_returns_all(mgr):
    s1 = mgr.create_session("ltspice")
    s2 = mgr.create_session("ngspice")
    listed = mgr.list_sessions()
    assert s1 in listed
    assert s2 in listed


# ---------------------------------------------------------------------------
# cleanup_session
# ---------------------------------------------------------------------------


def test_cleanup_session_removes_raw_file(mgr, tmp_path):
    s = mgr.create_session("ltspice")
    raw = s.work_dir / "sim.raw"
    raw.write_bytes(b"x" * 1024)
    s.raw_path = raw
    s.raw_file_size_mb = raw.stat().st_size / (1024 * 1024)

    freed = mgr.cleanup_session(s.session_id)
    assert not raw.exists()
    assert freed > 0


def test_cleanup_session_returns_mb_freed(mgr):
    s = mgr.create_session("ltspice")
    raw = s.work_dir / "sim.raw"
    raw.write_bytes(b"x" * (1024 * 1024))  # 1 MB
    s.raw_path = raw

    freed = mgr.cleanup_session(s.session_id)
    assert 0.9 < freed < 1.1


def test_cleanup_session_keeps_log_by_default(mgr):
    s = mgr.create_session("ltspice")
    log = s.work_dir / "sim.log"
    log.write_text("log content")
    s.log_path = log

    mgr.cleanup_session(s.session_id, keep_log=True)
    assert log.exists()


def test_cleanup_session_removes_log_when_requested(mgr):
    s = mgr.create_session("ltspice")
    log = s.work_dir / "sim.log"
    log.write_text("log content")
    s.log_path = log

    mgr.cleanup_session(s.session_id, keep_log=False)
    assert not log.exists()


def test_cleanup_session_sets_status_cleaned(mgr):
    s = mgr.create_session("ltspice")
    mgr.cleanup_session(s.session_id)
    assert s.status == "cleaned"


def test_delete_session_removes_work_dir(mgr):
    s = mgr.create_session("ltspice")
    work_dir = s.work_dir
    mgr.cleanup_session(s.session_id, delete_session=True)
    assert not work_dir.exists()


def test_delete_session_removes_from_registry(mgr):
    s = mgr.create_session("ltspice")
    sid = s.session_id
    mgr.cleanup_session(sid, delete_session=True)
    assert mgr.get_session(sid) is None


def test_cleanup_unknown_session_returns_zero(mgr):
    freed = mgr.cleanup_session("nosuchsession")
    assert freed == 0.0


# ---------------------------------------------------------------------------
# TTL / expiry
# ---------------------------------------------------------------------------


def test_is_expired_fresh_session(mgr):
    s = mgr.create_session("ltspice")
    assert not mgr._is_expired(s)


def test_is_expired_after_ttl(mgr):
    mgr.ttl_minutes = 0.0001  # ~6 ms
    s = mgr.create_session("ltspice")
    time.sleep(0.05)
    assert mgr._is_expired(s)


def test_is_expired_cleaned_session(mgr):
    mgr.ttl_minutes = 0.0001
    s = mgr.create_session("ltspice")
    s.status = "cleaned"
    time.sleep(0.05)
    assert not mgr._is_expired(s)


def test_reap_expired_removes_sessions(mgr):
    mgr.ttl_minutes = 0.0001
    s = mgr.create_session("ltspice")
    sid = s.session_id
    work_dir = s.work_dir
    time.sleep(0.05)
    reaped = mgr._reap_expired()
    assert reaped == 1
    assert mgr.get_session(sid) is None
    assert not work_dir.exists()


def test_reap_expired_does_not_remove_fresh(mgr):
    s = mgr.create_session("ltspice")
    sid = s.session_id
    reaped = mgr._reap_expired()
    assert reaped == 0
    assert mgr.get_session(sid) is not None


def test_reap_expired_only_removes_stale(mgr):
    from datetime import timedelta

    from spicemcp.core.session_manager import _now

    old = mgr.create_session("ltspice")
    old.last_accessed = _now() - timedelta(minutes=11)
    fresh = mgr.create_session("ngspice")
    mgr._reap_expired()
    assert mgr.get_session(old.session_id) is None
    assert mgr.get_session(fresh.session_id) is not None


# ---------------------------------------------------------------------------
# stop / reaper thread
# ---------------------------------------------------------------------------


def test_stop_terminates_reaper_thread():
    mgr = SessionManager(reaper_interval=9999)
    assert mgr._reaper.is_alive()
    mgr.stop()
    mgr._reaper.join(timeout=2)
    assert not mgr._reaper.is_alive()
