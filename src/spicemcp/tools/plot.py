"""MCP tool handler for plot_signals (auto-Bode, dual y-axis, PNG/HTML)."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import numpy as np
from spicelib import RawRead

from spicemcp.core.analysis_engine import _slice, detect_domain


def _classify(name: str) -> str:
    n = name.strip().upper()
    if n.startswith("V("):
        return "V"
    if n.startswith("I("):
        return "I"
    return "X"


def _get_axis(raw: RawRead, step: int) -> np.ndarray:
    axis_raw = raw.get_trace(0).get_wave(step)
    return np.real(axis_raw) if np.iscomplexobj(axis_raw) else axis_raw


def _render_png(
    domain: str,
    axis: np.ndarray,
    waves: list[tuple[str, np.ndarray]],
    title: str,
    out_path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    if domain == "ac":
        fig, (ax_g, ax_p) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        for name, w in waves:
            mag_db = 20.0 * np.log10(np.abs(w) + 1e-300)
            phase_deg = np.degrees(np.unwrap(np.angle(w)))
            ax_g.semilogx(axis, mag_db, label=name)
            ax_p.semilogx(axis, phase_deg, label=name)
        ax_g.set_ylabel("Gain (dB)")
        ax_g.grid(True, which="both", alpha=0.3)
        ax_g.legend(loc="best", fontsize=8)
        ax_p.set_ylabel("Phase (deg)")
        ax_p.set_xlabel("Frequency (Hz)")
        ax_p.grid(True, which="both", alpha=0.3)
        if title:
            fig.suptitle(title)
        fig.tight_layout()
        fig.savefig(out_path, dpi=110)
        plt.close(fig)
        return

    fig, ax_v = plt.subplots(figsize=(9, 5))
    ax_i = None
    has_v = False
    for name, w in waves:
        kind = _classify(name)
        wreal = np.real(w) if np.iscomplexobj(w) else w
        if kind == "I":
            if ax_i is None:
                ax_i = ax_v.twinx()
                ax_i.set_ylabel("Current (A)")
            ax_i.plot(axis, wreal, label=name, linestyle="--")
        else:
            ax_v.plot(axis, wreal, label=name)
            has_v = True

    if domain == "tran":
        ax_v.set_xlabel("Time (s)")
    elif domain == "dc":
        ax_v.set_xlabel("Sweep")
    else:
        ax_v.set_xlabel("X")
    if has_v:
        ax_v.set_ylabel("Voltage (V)")
    ax_v.grid(True, alpha=0.3)

    handles, labels = ax_v.get_legend_handles_labels()
    if ax_i is not None:
        h2, l2 = ax_i.get_legend_handles_labels()
        handles += h2
        labels += l2
    if handles:
        ax_v.legend(handles, labels, loc="best", fontsize=8)
    if title:
        fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _render_html(
    domain: str,
    axis: np.ndarray,
    waves: list[tuple[str, np.ndarray]],
    title: str,
    out_path: Path,
) -> bool:
    """Render an interactive HTML plot via plotly. Returns True on success."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return False

    if domain == "ac":
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            subplot_titles=("Gain (dB)", "Phase (deg)"),
        )
        for name, w in waves:
            mag_db = 20.0 * np.log10(np.abs(w) + 1e-300)
            phase_deg = np.degrees(np.unwrap(np.angle(w)))
            fig.add_trace(
                go.Scatter(x=axis, y=mag_db, name=name, mode="lines"),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Scatter(x=axis, y=phase_deg, name=name, mode="lines", showlegend=False),
                row=2,
                col=1,
            )
        fig.update_xaxes(type="log", title_text="Frequency (Hz)", row=2, col=1)
        if title:
            fig.update_layout(title_text=title)
    else:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        for name, w in waves:
            kind = _classify(name)
            wreal = np.real(w) if np.iscomplexobj(w) else w
            secondary = kind == "I"
            line = {"dash": "dash"} if secondary else None
            fig.add_trace(
                go.Scatter(x=axis, y=wreal, name=name, mode="lines", line=line),
                secondary_y=secondary,
            )
        x_label = "Time (s)" if domain == "tran" else ("Sweep" if domain == "dc" else "X")
        fig.update_xaxes(title_text=x_label)
        fig.update_yaxes(title_text="Voltage (V)", secondary_y=False)
        fig.update_yaxes(title_text="Current (A)", secondary_y=True)
        if title:
            fig.update_layout(title_text=title)

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    return True


def _err(msg: str) -> dict[str, Any]:
    return {
        "domain": "unknown",
        "format": None,
        "image_uri": None,
        "image_size_kb": None,
        "html_uri": None,
        "error": msg,
    }


def plot_signals(
    session_id: str,
    signals: list[str],
    x_start: float | None = None,
    x_end: float | None = None,
    step: int = 0,
    overlay_steps: bool = False,
    title: str = "",
    format: str = "png",
) -> dict:
    """Plot signals from a session's raw file."""
    from spicemcp import _globals

    manager = _globals.manager
    session = manager.get_session(session_id)
    if session is None:
        return _err(f"Session '{session_id}' not found or has expired.")
    if session.simulation_required:
        return _err(
            f"Session '{session_id}' has been modified since last simulation."
            " Call simulate before plotting."
        )
    if session.raw_path is None or not session.raw_path.exists():
        return _err(
            f"Session '{session_id}' has no raw file. Run simulate_netlist or simulate first."
        )

    if not isinstance(signals, list) or not signals:
        return _err("'signals' must be a non-empty list")
    if len(signals) > 6:
        return _err(f"Too many signals ({len(signals)}). Maximum 6 per plot.")

    fmt = (format or "png").lower()
    if fmt not in ("png", "html", "both"):
        return _err(f"Invalid format '{format}'. Use 'png', 'html', or 'both'.")

    available = session.signals_available or []
    for s in signals:
        if available and s not in available:
            return _err(
                f"Signal '{s}' not found in raw file. Available signals: {', '.join(available)}"
            )

    domain = session.domain or detect_domain(session.raw_path)

    try:
        raw = RawRead(session.raw_path, traces_to_read=list(signals), verbose=False)
        axis = _get_axis(raw, step)
        waves: list[tuple[str, np.ndarray]] = []
        for s in signals:
            wave = raw.get_wave(s, step)
            axis_w, wave_w = _slice(axis, wave, x_start, x_end)
            axis = axis_w
            waves.append((s, wave_w))
    except Exception as exc:
        return _err(f"Failed to read raw file: {type(exc).__name__}: {exc}")

    plot_id = secrets.token_hex(4)
    png_path = session.work_dir / f"plot_{plot_id}.png"
    html_path = session.work_dir / f"plot_{plot_id}.html"

    image_uri: str | None = None
    image_size_kb: float | None = None
    html_uri: str | None = None

    try:
        if fmt in ("png", "both"):
            _render_png(domain, axis, waves, title, png_path)
            image_uri = png_path.as_uri()
            image_size_kb = round(png_path.stat().st_size / 1024.0, 2)
    except Exception as exc:
        return _err(f"PNG render failed: {type(exc).__name__}: {exc}")

    if fmt in ("html", "both"):
        ok = _render_html(domain, axis, waves, title, html_path)
        if ok:
            html_uri = html_path.as_uri()
        elif fmt == "html":
            return _err("HTML output requires plotly. Install with: uv sync --extra interactive")

    return {
        "domain": domain,
        "format": fmt,
        "image_uri": image_uri,
        "image_size_kb": image_size_kb,
        "html_uri": html_uri,
        "error": None,
    }
