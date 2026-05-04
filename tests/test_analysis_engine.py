"""Analysis engine tests using synthetic raw file fixtures."""

import math

import numpy as np
import pytest

from spicemcp.core.analysis_engine import (
    AcStats,
    DcStats,
    TranStats,
    _ac_stats,
    _dc_stats,
    _find_threshold_crossing,
    _power_stats,
    _tran_stats,
    detect_domain,
    list_signals,
    measure_signal,
    parse_log_summary,
)


# ---------------------------------------------------------------------------
# detect_domain
# ---------------------------------------------------------------------------

def test_detect_domain_tran(tran_raw):
    assert detect_domain(tran_raw) == "tran"


def test_detect_domain_ac(ac_raw):
    assert detect_domain(ac_raw) == "ac"


# ---------------------------------------------------------------------------
# list_signals
# ---------------------------------------------------------------------------

def test_list_signals_tran(tran_raw):
    names = list_signals(tran_raw)
    assert "V(out)" in names
    assert "I(R1)" in names


def test_list_signals_ac(ac_raw):
    names = list_signals(ac_raw)
    assert "V(out)" in names


# ---------------------------------------------------------------------------
# _tran_stats — pure numpy unit tests
# ---------------------------------------------------------------------------

def test_tran_stats_sine_mean_dc_near_zero():
    t = np.linspace(0, 10e-3, 10001)
    v = np.sin(2 * np.pi * 1000 * t)
    s = _tran_stats(t, v)
    assert abs(s.mean_dc) < 1e-6


def test_tran_stats_dc_level():
    t = np.linspace(0, 1e-3, 1001)
    v = np.full_like(t, 3.3)
    s = _tran_stats(t, v)
    assert abs(s.mean_dc - 3.3) < 1e-9
    assert abs(s.mean_arithmetic - 3.3) < 1e-9
    assert abs(s.mean_rms - 3.3) < 1e-9


def test_tran_stats_peak_to_peak():
    t = np.linspace(0, 1e-3, 1001)
    v = np.sin(2 * np.pi * 1000 * t)
    s = _tran_stats(t, v)
    assert abs(s.peak_to_peak - 2.0) < 0.01


def test_tran_stats_x_at_min_max():
    t = np.linspace(0, 2e-3, 2001)
    v = np.sin(2 * np.pi * 1000 * t)
    s = _tran_stats(t, v)
    assert abs(s.max - 1.0) < 0.01
    assert abs(s.min + 1.0) < 0.01


def test_tran_stats_num_points():
    t = np.linspace(0, 1e-3, 500)
    v = np.zeros(500)
    s = _tran_stats(t, v)
    assert s.num_points == 500


def test_tran_stats_rms_of_sine():
    t = np.linspace(0, 10e-3, 10001)
    v = np.sin(2 * np.pi * 1000 * t)
    s = _tran_stats(t, v)
    assert abs(s.mean_rms - 1.0 / math.sqrt(2)) < 0.001


def test_tran_stats_integral():
    t = np.linspace(0, 1.0, 10001)
    v = np.ones(10001)  # integral of 1 over [0,1] = 1
    s = _tran_stats(t, v)
    assert abs(s.integral - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# _ac_stats — pure numpy unit tests
# ---------------------------------------------------------------------------

def test_ac_stats_gain_at_dc_is_zero_db():
    freq = np.logspace(0, 6, 500)
    h = np.ones(len(freq), dtype=complex)
    s = _ac_stats(freq, h)
    assert abs(s.gain_db_at_start) < 0.01


def test_ac_stats_rc_filter_bandwidth():
    freq = np.logspace(1, 7, 1000)
    rc = 1e3 * 1e-9  # fc = 159kHz
    h = 1.0 / (1.0 + 1j * 2 * np.pi * freq * rc)
    s = _ac_stats(freq, h)
    assert s.bandwidth_3db is not None
    assert abs(s.bandwidth_3db - 159155.0) / 159155.0 < 0.02


def test_ac_stats_unity_gain_passthrough():
    freq = np.logspace(1, 7, 1000)
    h = np.ones(len(freq), dtype=complex)
    s = _ac_stats(freq, h)
    assert s.unity_gain_freq is None  # never crosses 0 dB falling


def test_ac_stats_peak_gain():
    freq = np.logspace(1, 6, 500)
    # Gain of 20dB at 1kHz
    h = np.ones(len(freq), dtype=complex) * 10.0
    s = _ac_stats(freq, h)
    assert abs(s.peak_gain_db - 20.0) < 0.01


def test_ac_stats_phase_margin_unity_gain():
    freq = np.logspace(1, 7, 1000)
    # Single-pole: phase at UGF should give positive phase margin
    rc = 1e3 * 1e-9
    h = 1.0 / (1.0 + 1j * 2 * np.pi * freq * rc)
    s = _ac_stats(freq, h)
    if s.unity_gain_freq is not None and s.phase_margin_deg is not None:
        assert s.phase_margin_deg > 0


# ---------------------------------------------------------------------------
# _dc_stats — pure numpy unit tests
# ---------------------------------------------------------------------------

def test_dc_stats_linear_sweep():
    sweep = np.linspace(0, 5, 101)
    v = sweep * 0.5  # voltage divider
    s = _dc_stats(sweep, v)
    assert abs(s.min) < 1e-10
    assert abs(s.max - 2.5) < 1e-10
    assert abs(s.value_at_start) < 1e-10
    assert abs(s.value_at_end - 2.5) < 1e-10


def test_dc_stats_x_at_extremes():
    sweep = np.linspace(0, 5, 101)
    v = sweep * 0.5
    s = _dc_stats(sweep, v)
    assert abs(s.x_at_min - 0.0) < 1e-10
    assert abs(s.x_at_max - 5.0) < 1e-10


# ---------------------------------------------------------------------------
# _find_threshold_crossing
# ---------------------------------------------------------------------------

def test_crossing_rising_edge():
    x = np.linspace(0, 1, 1001)
    y = np.sin(2 * np.pi * x)  # rises through 0 at x=0
    # First rising crossing of 0: at x~0
    c = _find_threshold_crossing(x, y, 0.0, edge="rising")
    # sin crosses 0 rising at 0 and 1.0, so first is 0 (degenerate: starts at 0)
    # Let's check at x=0.5: sin is 0 falling
    c2 = _find_threshold_crossing(x, y, 0.0, edge="falling")
    assert c2 is not None
    assert abs(c2 - 0.5) < 0.01


def test_crossing_falling_sine():
    x = np.linspace(0, 2e-3, 2001)
    y = np.sin(2 * np.pi * 1000 * x)
    c = _find_threshold_crossing(x, y, 0.5, edge="falling")
    assert c is not None
    assert 0 < c < 2e-3


def test_crossing_no_crossing_returns_none():
    x = np.linspace(0, 1, 100)
    y = np.ones(100) * 2.0  # never crosses 5.0
    assert _find_threshold_crossing(x, y, 5.0) is None


def test_crossing_interpolates():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([2.0, 0.0, -2.0])
    c = _find_threshold_crossing(x, y, 1.0, edge="falling")
    assert c is not None
    assert abs(c - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# _power_stats
# ---------------------------------------------------------------------------

def test_power_stats_dc():
    t = np.linspace(0, 1e-3, 1001)
    v = np.full_like(t, 5.0)
    i = np.full_like(t, 0.01)
    s = _power_stats(t, v, i)
    assert abs(s.mean_power - 0.05) < 1e-9
    assert abs(s.peak_power - 0.05) < 1e-9


def test_power_stats_sine_rms():
    t = np.linspace(0, 10e-3, 10001)
    v = np.sin(2 * np.pi * 1000 * t)
    i = v / 1000.0
    s = _power_stats(t, v, i)
    # Mean power of V*I = sin^2/1k -> mean = 1/(2k) = 0.0005
    assert abs(s.mean_power - 0.0005) < 1e-5


# ---------------------------------------------------------------------------
# measure_signal (end-to-end via raw files)
# ---------------------------------------------------------------------------

def test_measure_tran_stats(tran_raw):
    r = measure_signal(tran_raw, "V(out)", "stats")
    assert r["domain"] == "tran"
    assert abs(r["mean_dc"]) < 1e-5
    assert abs(r["peak_to_peak"] - 2.0) < 0.01
    assert r["num_points"] == 1001


def test_measure_tran_crossing(tran_raw):
    r = measure_signal(tran_raw, "V(out)", "crossing", threshold=0.0, edge="falling")
    assert r["domain"] == "tran"
    assert r["crossing_x"] is not None
    # sin crosses 0 falling at t = 0.5/1kHz = 0.5ms
    assert abs(r["crossing_x"] - 0.5e-3) < 0.1e-3


def test_measure_tran_power(tran_raw):
    r = measure_signal(tran_raw, "V(out)", "power", i_signal="I(R1)")
    assert r["domain"] == "tran"
    assert abs(r["mean_power"] - 0.0005) < 1e-4


def test_measure_tran_windowed(tran_raw):
    # Restrict to first half-cycle [0, 0.5ms] - should be positive half-sine
    r = measure_signal(tran_raw, "V(out)", "stats", x_start=0.0, x_end=0.5e-3)
    assert r["min"] >= -0.01  # near zero at start/end of window


def test_measure_ac_stats(ac_raw):
    r = measure_signal(ac_raw, "V(out)", "stats")
    assert r["domain"] == "ac"
    assert abs(r["gain_db_at_start"]) < 0.1  # passband ~0 dB
    assert r["bandwidth_3db"] is not None
    assert abs(r["bandwidth_3db"] - 159155.0) / 159155.0 < 0.05


def test_measure_ac_crossing(ac_raw):
    r = measure_signal(ac_raw, "V(out)", "crossing", threshold=-3.0)
    assert r["domain"] == "ac"
    assert r["crossing_freq"] is not None
    assert abs(r["crossing_freq"] - 159155.0) / 159155.0 < 0.05


def test_measure_unknown_operation_raises(tran_raw):
    with pytest.raises(ValueError, match="Unsupported operation"):
        measure_signal(tran_raw, "V(out)", "notanop")


# ---------------------------------------------------------------------------
# parse_log_summary
# ---------------------------------------------------------------------------

def test_parse_log_summary_extracts_errors(tmp_path):
    log = tmp_path / "sim.log"
    log.write_text("Starting simulation\nError: singular matrix\nDone\n")
    summary = parse_log_summary(log)
    assert "Error: singular matrix" in summary


def test_parse_log_summary_truncates(tmp_path):
    log = tmp_path / "sim.log"
    log.write_text("\n".join(f"Error: line {i}" for i in range(200)))
    summary = parse_log_summary(log, max_chars=100)
    assert len(summary) <= 103  # 100 + "..."


def test_parse_log_summary_missing_file(tmp_path):
    summary = parse_log_summary(tmp_path / "nosuchfile.log")
    assert summary == ""


def test_parse_log_summary_no_errors(tmp_path):
    log = tmp_path / "sim.log"
    log.write_text("Starting simulation\nSimulation complete\n")
    summary = parse_log_summary(log)
    assert summary == ""


# ---------------------------------------------------------------------------
# Cache module (tested here for proximity to analysis context)
# ---------------------------------------------------------------------------

from spicemcp.core.cache import SimCache, cache_key, is_monte_carlo


def test_is_monte_carlo_detects_mc():
    assert is_monte_carlo(".param R1 mc(1k, 0.1)")


def test_is_monte_carlo_case_insensitive():
    assert is_monte_carlo(".PARAM R1 MC(1k, 0.1)")


def test_is_monte_carlo_false_for_clean_netlist():
    assert not is_monte_carlo("R1 in out 1k\nC1 out 0 1n\n.tran 1m")


def test_cache_key_includes_simulator_and_tag():
    k1 = cache_key("ltspice", "tag1", "netlist")
    k2 = cache_key("ltspice", "tag2", "netlist")
    k3 = cache_key("ngspice", "tag1", "netlist")
    assert k1 != k2
    assert k1 != k3


def test_cache_key_stable():
    k1 = cache_key("ltspice", "latest", "R1 in out 1k")
    k2 = cache_key("ltspice", "latest", "R1 in out 1k")
    assert k1 == k2


def test_sim_cache_set_get():
    c = SimCache()
    c.set("k1", {"result": 42})
    assert c.get("k1") == {"result": 42}


def test_sim_cache_miss_returns_none():
    c = SimCache()
    assert c.get("nonexistent") is None


def test_sim_cache_expiry():
    import time
    c = SimCache(ttl_minutes=0.0001)  # ~6ms TTL
    c.set("k", "value")
    time.sleep(0.05)
    assert c.get("k") is None


def test_sim_cache_len():
    c = SimCache()
    c.set("a", 1)
    c.set("b", 2)
    assert len(c) == 2


def test_sim_cache_invalidate():
    c = SimCache()
    c.set("k", "v")
    c.invalidate("k")
    assert c.get("k") is None


def test_sim_cache_clear():
    c = SimCache()
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert len(c) == 0


def test_sim_cache_max_entries_evicts():
    c = SimCache(max_entries=3)
    for i in range(4):
        c.set(f"k{i}", i)
    assert len(c) == 3
