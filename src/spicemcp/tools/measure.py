"""MCP tool handler for measure_signal (batch, domain-aware)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from spicelib import RawRead

from spicemcp.core.analysis_engine import (
    _ac_stats,
    _dc_stats,
    _power_stats,
    _slice,
    _tran_stats,
    detect_domain,
)


def _find_nth_crossing(
    x: np.ndarray,
    y: np.ndarray,
    threshold: float,
    edge: str,
    n: int,
    hysteresis: int,
) -> float | None:
    """Return the x-value of the n-th threshold crossing, or None.

    edge: 'rising' | 'falling' | 'either'
    hysteresis: minimum consecutive samples on the new side before a crossing counts.
    """
    if len(y) < 2:
        return None
    above = y >= threshold
    found = 0
    i = 1
    while i < len(y):
        prev_above = above[i - 1]
        cur_above = above[i]
        if edge == "rising":
            crossed = (not prev_above) and cur_above
        elif edge == "falling":
            crossed = prev_above and (not cur_above)
        else:  # either
            crossed = prev_above != cur_above
        if crossed:
            ok = True
            new_side_above = cur_above
            for j in range(1, max(1, hysteresis)):
                k = i + j
                if k >= len(y):
                    break
                if above[k] != new_side_above:
                    ok = False
                    break
            if ok:
                found += 1
                if found == n:
                    x0, x1 = float(x[i - 1]), float(x[i])
                    y0, y1 = float(y[i - 1]), float(y[i])
                    if y1 != y0:
                        return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                    return float(x[i])
        i += 1
    return None


def _stats_for(
    domain: str,
    raw: RawRead,
    signal: str,
    step: int,
    x_start: float | None,
    x_end: float | None,
) -> dict[str, Any]:
    wave = raw.get_wave(signal, step)
    if domain == "op":
        val = float(np.real(wave[0]) if np.iscomplexobj(wave) else wave[0])
        return {"value": val}

    axis_raw = raw.get_trace(0).get_wave(step)
    axis = np.real(axis_raw) if np.iscomplexobj(axis_raw) else axis_raw

    if domain == "ac":
        wave_complex = wave.astype(complex)
        axis_w, wave_w = _slice(axis, wave_complex, x_start, x_end)
        s = _ac_stats(axis_w, wave_w)
        gain_db = 20.0 * np.log10(np.abs(wave_w) + 1e-300)
        return {
            **s.__dict__,
            "gain_db_at_end": float(gain_db[-1]) if len(gain_db) else None,
        }

    wave_real = np.real(wave) if np.iscomplexobj(wave) else wave
    axis_w, wave_w = _slice(axis, wave_real, x_start, x_end)

    if domain == "dc":
        s = _dc_stats(axis_w, wave_w)
        return {**s.__dict__, "num_points": int(len(wave_w))}

    s = _tran_stats(axis_w, wave_w)
    return s.__dict__


def _crossing_for(
    domain: str,
    raw: RawRead,
    signal: str,
    step: int,
    x_start: float | None,
    x_end: float | None,
    threshold: float,
    edge: str,
    n: int,
    hysteresis: int,
) -> dict[str, Any]:
    wave = raw.get_wave(signal, step)
    axis_raw = raw.get_trace(0).get_wave(step)
    axis = np.real(axis_raw) if np.iscomplexobj(axis_raw) else axis_raw

    if domain == "ac":
        wave_complex = wave.astype(complex)
        axis_w, wave_w = _slice(axis, wave_complex, x_start, x_end)
        gain_db = 20.0 * np.log10(np.abs(wave_w) + 1e-300)
        x_found = _find_nth_crossing(axis_w, gain_db, threshold, edge, n, hysteresis)
    else:
        wave_real = np.real(wave) if np.iscomplexobj(wave) else wave
        axis_w, wave_w = _slice(axis, wave_real, x_start, x_end)
        x_found = _find_nth_crossing(axis_w, wave_w, threshold, edge, n, hysteresis)

    return {
        "found": x_found is not None,
        "x": x_found,
        "threshold": threshold,
        "edge": edge,
        "n": n,
    }


def _power_for(
    raw: RawRead,
    v_sig: str,
    i_sig: str,
    step: int,
    x_start: float | None,
    x_end: float | None,
) -> dict[str, Any]:
    v_wave = raw.get_wave(v_sig, step)
    i_wave = raw.get_wave(i_sig, step)
    axis_raw = raw.get_trace(0).get_wave(step)
    axis = np.real(axis_raw) if np.iscomplexobj(axis_raw) else axis_raw
    v_real = np.real(v_wave) if np.iscomplexobj(v_wave) else v_wave
    i_real = np.real(i_wave) if np.iscomplexobj(i_wave) else i_wave
    axis_w, v_w = _slice(axis, v_real, x_start, x_end)
    _, i_w = _slice(axis, i_real, x_start, x_end)
    s = _power_stats(axis_w, v_w, i_w)
    return s.__dict__


def _measure_one(raw_path: Path, domain: str, m: dict) -> dict[str, Any]:
    op = m.get("operation")
    step = int(m.get("step", 0))
    x_start = m.get("x_start")
    x_end = m.get("x_end")

    if op == "power":
        signals = m.get("signals")
        if not isinstance(signals, list) or len(signals) != 2:
            return {
                "operation": "power",
                "error": "'power' requires 'signals' as exactly 2 traces [V, I]",
            }
        v_sig, i_sig = signals[0], signals[1]
        raw = RawRead(raw_path, traces_to_read=[v_sig, i_sig], verbose=False)
        result = _power_for(raw, v_sig, i_sig, step, x_start, x_end)
        return {
            "operation": "power",
            "domain": domain,
            "v_signal": v_sig,
            "i_signal": i_sig,
            "step": step,
            **result,
        }

    signal = m.get("signal")
    if not signal:
        return {"operation": op, "error": "'signal' is required"}
    raw = RawRead(raw_path, traces_to_read=[signal], verbose=False)

    if op == "stats":
        result = _stats_for(domain, raw, signal, step, x_start, x_end)
        return {"operation": "stats", "domain": domain, "signal": signal, "step": step, **result}

    if op == "crossing":
        threshold = m.get("threshold")
        if threshold is None:
            return {"operation": "crossing", "error": "'crossing' requires 'threshold'"}
        edge = m.get("edge", "rising")
        n = int(m.get("n", 1))
        hysteresis = int(m.get("hysteresis", 0))
        result = _crossing_for(
            domain,
            raw,
            signal,
            step,
            x_start,
            x_end,
            float(threshold),
            edge,
            n,
            hysteresis,
        )
        return {
            "operation": "crossing",
            "domain": domain,
            "signal": signal,
            "step": step,
            **result,
        }

    return {
        "operation": op,
        "error": f"Unsupported operation '{op}'. Use 'stats', 'crossing', or 'power'.",
    }


def measure_signal(session_id: str, measurements: list[dict]) -> dict:
    """Run a batch of measurements against a session's raw file."""
    from spicemcp import _globals

    manager = _globals.manager
    session = manager.get_session(session_id)
    if session is None:
        return {
            "results": [],
            "error": (
                f"Session '{session_id}' not found or has expired."
                " Create a new session with simulate_netlist or create_session."
            ),
        }

    if session.simulation_required:
        return {
            "results": [],
            "error": (
                f"Session '{session_id}' has been modified since last simulation."
                " Call simulate before measuring."
            ),
        }

    if session.raw_path is None or not session.raw_path.exists():
        return {
            "results": [],
            "error": (
                f"Session '{session_id}' has no raw file. Run simulate_netlist or simulate first."
            ),
        }

    if not isinstance(measurements, list) or not measurements:
        return {"results": [], "error": "'measurements' must be a non-empty list"}

    domain = session.domain or detect_domain(session.raw_path)
    available = session.signals_available or []

    for m in measurements:
        if m.get("operation") == "power":
            for s in m.get("signals") or []:
                if available and s not in available:
                    return {
                        "results": [],
                        "error": (
                            f"Signal '{s}' not found in raw file."
                            f" Available signals: {', '.join(available)}"
                        ),
                    }
        else:
            s = m.get("signal")
            if s and available and s not in available:
                return {
                    "results": [],
                    "error": (
                        f"Signal '{s}' not found in raw file."
                        f" Available signals: {', '.join(available)}"
                    ),
                }

    results: list[dict] = []
    for m in measurements:
        try:
            results.append(_measure_one(session.raw_path, domain, m))
        except Exception as exc:
            results.append(
                {
                    "operation": m.get("operation"),
                    "signal": m.get("signal"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return {"results": results, "error": None}
