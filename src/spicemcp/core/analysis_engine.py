"""Domain-aware analysis engine wrapping spicelib RawRead and LTSpiceLogReader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from spicelib import RawRead
from spicelib.log.ltsteps import LTSpiceLogReader

# ---------------------------------------------------------------------------
# Domain detection
# ---------------------------------------------------------------------------


def detect_domain(raw_path: Path) -> str:
    """Return canonical domain string from raw file header.

    Uses get_plot_name() as the authoritative source (D-11).
    Returns one of: tran | ac | dc | op | noise | unknown
    """
    raw = RawRead(raw_path, traces_to_read=[], verbose=False)
    plot_name = raw.get_plot_name().lower()
    if "transient" in plot_name:
        return "tran"
    if "ac analysis" in plot_name or "frequency" in plot_name:
        return "ac"
    if "dc transfer" in plot_name or "dc sweep" in plot_name:
        return "dc"
    if "operating point" in plot_name:
        return "op"
    if "noise" in plot_name:
        return "noise"
    return "unknown"


def list_signals(raw_path: Path) -> list[str]:
    """Return all trace names in the raw file (header-only read)."""
    raw = RawRead(raw_path, traces_to_read=[], verbose=False)
    return raw.get_trace_names()


# ---------------------------------------------------------------------------
# Transient stats
# ---------------------------------------------------------------------------


@dataclass
class TranStats:
    min: float
    max: float
    mean_dc: float
    mean_arithmetic: float
    mean_rms: float
    integral: float
    peak_to_peak: float
    x_at_min: float
    x_at_max: float
    num_points: int


def _tran_stats(axis: np.ndarray, wave: np.ndarray) -> TranStats:
    dt = axis[-1] - axis[0]
    integral = float(np.trapezoid(wave, axis))
    mean_dc = integral / dt if dt != 0 else float(np.mean(wave))
    if dt != 0:
        mean_rms = float(np.sqrt(np.trapezoid(wave**2, axis) / dt))
    else:
        mean_rms = float(np.sqrt(np.mean(wave**2)))
    i_min = int(np.argmin(wave))
    i_max = int(np.argmax(wave))
    return TranStats(
        min=float(wave[i_min]),
        max=float(wave[i_max]),
        mean_dc=mean_dc,
        mean_arithmetic=float(np.mean(wave)),
        mean_rms=mean_rms,
        integral=integral,
        peak_to_peak=float(wave[i_max] - wave[i_min]),
        x_at_min=float(axis[i_min]),
        x_at_max=float(axis[i_max]),
        num_points=len(wave),
    )


# ---------------------------------------------------------------------------
# AC stats
# ---------------------------------------------------------------------------


@dataclass
class AcStats:
    gain_db_at_start: float
    peak_gain_db: float
    peak_gain_freq: float
    bandwidth_3db: float | None
    unity_gain_freq: float | None
    phase_margin_deg: float | None
    gain_margin_db: float | None


def _ac_stats(freq: np.ndarray, wave: np.ndarray) -> AcStats:
    gain_db = 20.0 * np.log10(np.abs(wave) + 1e-300)
    phase_deg = np.degrees(np.unwrap(np.angle(wave)))

    i_peak = int(np.argmax(gain_db))
    gain_db_start = float(gain_db[0])
    peak_gain_db = float(gain_db[i_peak])
    peak_gain_freq = float(freq[i_peak])

    # 3dB bandwidth from the start gain
    bw_ref = gain_db_start - 3.0
    bw_3db = _find_threshold_crossing(freq, gain_db, bw_ref, edge="falling")

    # Unity gain (0 dB) crossing
    unity_gain_freq = _find_threshold_crossing(freq, gain_db, 0.0, edge="falling")

    # Phase margin: phase at unity gain crossing
    phase_margin = None
    if unity_gain_freq is not None:
        idx = np.searchsorted(freq, unity_gain_freq)
        idx = min(idx, len(phase_deg) - 1)
        phase_at_ugf = float(phase_deg[idx])
        phase_margin = 180.0 + phase_at_ugf  # 0 deg reference = -180

    # Gain margin: gain at -180 degree phase crossing
    gain_margin = None
    minus180_freq = _find_threshold_crossing(freq, phase_deg, -180.0, edge="falling")
    if minus180_freq is not None:
        idx = np.searchsorted(freq, minus180_freq)
        idx = min(idx, len(gain_db) - 1)
        gain_margin = float(-gain_db[idx])

    return AcStats(
        gain_db_at_start=gain_db_start,
        peak_gain_db=peak_gain_db,
        peak_gain_freq=peak_gain_freq,
        bandwidth_3db=bw_3db,
        unity_gain_freq=unity_gain_freq,
        phase_margin_deg=phase_margin,
        gain_margin_db=gain_margin,
    )


# ---------------------------------------------------------------------------
# DC stats
# ---------------------------------------------------------------------------


@dataclass
class DcStats:
    min: float
    max: float
    x_at_min: float
    x_at_max: float
    value_at_start: float
    value_at_end: float


def _dc_stats(sweep: np.ndarray, wave: np.ndarray) -> DcStats:
    i_min = int(np.argmin(wave))
    i_max = int(np.argmax(wave))
    return DcStats(
        min=float(wave[i_min]),
        max=float(wave[i_max]),
        x_at_min=float(sweep[i_min]),
        x_at_max=float(sweep[i_max]),
        value_at_start=float(wave[0]),
        value_at_end=float(wave[-1]),
    )


# ---------------------------------------------------------------------------
# Noise stats
# ---------------------------------------------------------------------------


@dataclass
class NoiseStats:
    peak_spectral_density: float
    peak_freq: float


def _noise_stats(freq: np.ndarray, wave: np.ndarray) -> NoiseStats:
    mag = np.abs(wave)
    i_peak = int(np.argmax(mag))
    return NoiseStats(
        peak_spectral_density=float(mag[i_peak]),
        peak_freq=float(freq[i_peak]),
    )


# ---------------------------------------------------------------------------
# Threshold crossing helper
# ---------------------------------------------------------------------------


def _find_threshold_crossing(
    x: np.ndarray,
    y: np.ndarray,
    threshold: float,
    edge: str = "falling",
    hysteresis: int = 1,
) -> float | None:
    """Return interpolated x-value where y crosses threshold.

    edge='falling' finds the first downward crossing.
    edge='rising' finds the first upward crossing.
    hysteresis: minimum consecutive samples on new side before counting.
    """
    above = y >= threshold
    consecutive = 0
    for i in range(1, len(y)):
        if edge == "falling":
            crossed = above[i - 1] and not above[i]
        else:
            crossed = not above[i - 1] and above[i]
        if crossed:
            consecutive += 1
            if consecutive >= hysteresis:
                # Linear interpolation
                x0, x1 = float(x[i - 1]), float(x[i])
                y0, y1 = float(y[i - 1]), float(y[i])
                if y1 != y0:
                    return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                return float(x[i])
        else:
            consecutive = 0
    return None


# ---------------------------------------------------------------------------
# Power computation
# ---------------------------------------------------------------------------


@dataclass
class PowerStats:
    mean_power: float
    peak_power: float
    rms_power: float


def _power_stats(
    axis: np.ndarray,
    v_wave: np.ndarray,
    i_wave: np.ndarray,
) -> PowerStats:
    p = v_wave * i_wave
    dt = axis[-1] - axis[0]
    mean_p = float(np.trapezoid(p, axis) / dt) if dt != 0 else float(np.mean(p))
    if dt != 0:
        rms_p = float(np.sqrt(np.trapezoid(p**2, axis) / dt))
    else:
        rms_p = float(np.sqrt(np.mean(p**2)))
    return PowerStats(
        mean_power=mean_p,
        peak_power=float(np.max(np.abs(p))),
        rms_power=rms_p,
    )


# ---------------------------------------------------------------------------
# Window slicing
# ---------------------------------------------------------------------------


def _slice(axis: np.ndarray, wave: np.ndarray, x_start: float | None, x_end: float | None):
    """Return (axis_slice, wave_slice) restricted to [x_start, x_end]."""
    if x_start is None and x_end is None:
        return axis, wave
    mask = np.ones(len(axis), dtype=bool)
    if x_start is not None:
        mask &= axis >= x_start
    if x_end is not None:
        mask &= axis <= x_end
    return axis[mask], wave[mask]


# ---------------------------------------------------------------------------
# Public API: measure
# ---------------------------------------------------------------------------


def measure_signal(
    raw_path: Path,
    signal: str,
    operation: str,
    step: int = 0,
    x_start: float | None = None,
    x_end: float | None = None,
    *,
    threshold: float | None = None,
    edge: str = "falling",
    n: int = 1,
    hysteresis: int = 1,
    i_signal: str | None = None,
) -> dict[str, Any]:
    """Measure a signal from a raw file.

    operation: 'stats' | 'crossing' | 'power'

    For 'power', i_signal is required (current trace name).
    Returns a dict of domain-appropriate results.
    """
    domain = detect_domain(raw_path)

    traces = [signal]
    if operation == "power" and i_signal:
        traces.append(i_signal)

    raw = RawRead(raw_path, traces_to_read=traces, verbose=False)
    wave = raw.get_wave(signal, step)

    if domain == "op":
        val = float(np.real(wave[0]) if np.iscomplexobj(wave) else wave[0])
        return {"domain": domain, "signal": signal, "value": val}

    # get_axis() checks an internal flag that RawWrite-generated files do not set.
    # get_trace(0).get_wave() is always safe and is what get_axis() delegates to.
    axis_raw = raw.get_trace(0).get_wave(step)
    axis = np.real(axis_raw) if np.iscomplexobj(axis_raw) else axis_raw

    if domain == "ac":
        wave_complex = wave.astype(complex)
        axis_w, wave_w = _slice(axis, wave_complex, x_start, x_end)
        if operation == "stats":
            stats = _ac_stats(axis_w, wave_w)
            return {
                "domain": domain,
                "signal": signal,
                **stats.__dict__,
            }
        if operation == "crossing":
            gain_db = 20.0 * np.log10(np.abs(wave_w) + 1e-300)
            val = threshold if threshold is not None else 0.0
            found = _find_threshold_crossing(axis_w, gain_db, val, edge=edge, hysteresis=hysteresis)
            return {"domain": domain, "signal": signal, "crossing_freq": found}
        raise ValueError(f"Unsupported operation '{operation}' for AC domain")

    # TRAN / DC / NOISE
    wave_real = np.real(wave) if np.iscomplexobj(wave) else wave
    axis_w, wave_w = _slice(axis, wave_real, x_start, x_end)

    if domain == "noise":
        if operation == "stats":
            stats = _noise_stats(axis_w, wave_w)
            return {"domain": domain, "signal": signal, **stats.__dict__}

    if domain == "dc":
        if operation == "stats":
            stats = _dc_stats(axis_w, wave_w)
            return {"domain": domain, "signal": signal, **stats.__dict__}

    # TRAN (default for stats/crossing/power)
    if operation == "stats":
        stats = _tran_stats(axis_w, wave_w)
        return {"domain": domain, "signal": signal, **stats.__dict__}

    if operation == "crossing":
        val = threshold if threshold is not None else 0.0
        found = _find_threshold_crossing(axis_w, wave_w, val, edge=edge, hysteresis=hysteresis)
        return {"domain": domain, "signal": signal, "crossing_x": found}

    if operation == "power":
        if i_signal is None:
            raise ValueError("'power' operation requires i_signal")
        i_wave = raw.get_wave(i_signal, step)
        i_wave_real = np.real(i_wave) if np.iscomplexobj(i_wave) else i_wave
        _, i_wave_w = _slice(axis, i_wave_real, x_start, x_end)
        stats = _power_stats(axis_w, wave_w, i_wave_w)
        return {"domain": domain, "signal": signal, **stats.__dict__}

    raise ValueError(f"Unsupported operation '{operation}'")


# ---------------------------------------------------------------------------
# Public API: log parsing
# ---------------------------------------------------------------------------


def parse_meas_results(log_path: Path) -> dict[str, Any]:
    """Parse .MEAS results from an LTSpice log file.

    Returns a dict mapping measure name to value (or list of values for stepped sims).
    """
    reader = LTSpiceLogReader(str(log_path), read_measures=True)
    results: dict[str, Any] = {}
    try:
        meas_names = reader.get_measure_names()
    except Exception:
        return results
    for name in meas_names:
        try:
            values = reader[name]
            if isinstance(values, (list, tuple)):
                results[name] = [float(v) if v is not None else None for v in values]
                if len(results[name]) == 1:
                    results[name] = results[name][0]
            else:
                results[name] = float(values) if values is not None else None
        except Exception:
            results[name] = None
    return results


def parse_step_info(log_path: Path) -> list[dict[str, Any]]:
    """Parse .STEP parameter info from an LTSpice log file.

    Returns a list of dicts, one per step, each with the stepped parameter values.
    """
    try:
        reader = LTSpiceLogReader(str(log_path), read_measures=False)
        step_vars = reader.get_step_vars()
        if not step_vars:
            return []
        steps = []
        for i in range(reader.step_count):
            entry = {"index": i}
            for var in step_vars:
                try:
                    entry[var] = reader[var][i]
                except Exception:
                    entry[var] = None
            steps.append(entry)
        return steps
    except Exception:
        return []


def parse_log_summary(log_path: Path, max_chars: int = 500) -> str:
    """Return errors/warnings from the log, truncated to max_chars."""
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return ""
    lines = []
    for line in text.splitlines():
        lower = line.lower()
        if any(k in lower for k in ("error", "warning", "fatal", "abort", "failed")):
            lines.append(line.strip())
    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "..."
    return summary


def parse_operating_point(raw_path: Path) -> dict[str, float] | None:
    """Extract operating point values from a raw file.

    Returns None if the raw file is not an OP analysis.
    """
    domain = detect_domain(raw_path)
    if domain != "op":
        return None
    raw = RawRead(raw_path, verbose=False)
    names = raw.get_trace_names()
    result: dict[str, float] = {}
    for name in names:
        try:
            wave = raw.get_wave(name, 0)
            val = wave[0] if len(wave) > 0 else 0.0
            result[name] = float(np.real(val) if np.iscomplexobj(val) else val)
        except Exception:
            pass
    return result or None
