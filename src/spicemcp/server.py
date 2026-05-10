"""SpiceMCP server entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from spicemcp.config import apply_config_to_backends, load_config
from spicemcp.core.session_manager import SessionManager


@asynccontextmanager
async def _lifespan(app: FastMCP):
    import spicemcp._globals as _globals

    _globals.config = load_config()
    apply_config_to_backends(_globals.config)
    _globals.manager = SessionManager(
        ttl_minutes=_globals.config.session_ttl_minutes,
        max_sessions=_globals.config.max_sessions,
    )
    try:
        yield
    finally:
        _globals.manager.stop()


mcp = FastMCP("SpiceMCP", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


@mcp.tool()
def simulate_netlist(
    simulator: str,
    netlist: str,
    filename: str = "circuit.net",
    timeout_s: int = 300,
) -> dict[str, Any]:
    """Create a session, sanitize and write the netlist, run the simulation,
    and return structured results. This is the one-call 90% path.

    simulator: 'ltspice' | 'ngspice'
    netlist: full SPICE netlist as a string
    filename: optional filename, default 'circuit.net'
    timeout_s: simulation timeout in seconds, max 600
    """
    from spicemcp.tools.simulate_netlist import simulate_netlist as _run

    return _run(simulator=simulator, netlist=netlist, filename=filename, timeout_s=timeout_s)


@mcp.tool()
def simulate(
    session_id: str,
    timeout_s: int = 300,
) -> dict[str, Any]:
    """Run a simulation on an existing session.

    The session must have a netlist written via write_netlist first.
    Returns the same structure as simulate_netlist minus session creation.

    session_id: session identifier from create_session or simulate_netlist
    timeout_s: simulation timeout in seconds, max 600
    """
    from spicemcp.tools.simulate import simulate as _run

    return _run(session_id=session_id, timeout_s=timeout_s)


@mcp.tool()
def write_netlist(
    session_id: str,
    netlist: str,
    filename: str = "circuit.net",
) -> dict[str, Any]:
    """Sanitize and write a netlist to a session's work directory.

    Returns accepted/rejected status, sanitizer violations, and model
    reference resolution results. Does not run the simulation.

    session_id: session identifier from create_session
    netlist: full SPICE netlist as a string
    filename: optional filename, default 'circuit.net'
    """
    from spicemcp.tools.netlist import write_netlist as _run

    return _run(session_id=session_id, netlist=netlist, filename=filename)


@mcp.tool()
def create_session(simulator: str) -> dict[str, Any]:
    """Create a new simulation session without running a simulation.

    Use this when you want to write and modify a netlist before simulating.
    For a one-shot simulation, use simulate_netlist instead.

    simulator: 'ltspice' | 'ngspice'
    """
    from spicemcp.tools.session import create_session as _run

    return _run(simulator=simulator)


@mcp.tool()
def list_sessions() -> dict[str, Any]:
    """List all active simulation sessions with their status, TTL, and file sizes."""
    from spicemcp.tools.session import list_sessions as _run

    return _run()


@mcp.tool()
def measure_signal(
    session_id: str,
    measurements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run a batch of measurements against a session's raw file.

    Each measurement is a dict:
      - operation: 'stats' | 'crossing' | 'power'
      - signal: trace name (for stats and crossing)
      - signals: [V_signal, I_signal] (for power)
      - x_start, x_end: optional window (time/freq/sweep depending on domain)
      - step: optional step index, default 0
      - threshold, edge ('rising'|'falling'|'either'), n, hysteresis: for crossing

    Returns {'results': [...], 'error': null/string}. Results are returned in
    the same order as input measurements; per-result errors are surfaced in
    that result's 'error' key.
    """
    from spicemcp.tools.measure import measure_signal as _run

    return _run(session_id=session_id, measurements=measurements)


@mcp.tool()
def plot_signals(
    session_id: str,
    signals: list[str],
    x_start: float | None = None,
    x_end: float | None = None,
    step: int = 0,
    overlay_steps: bool = False,
    title: str = "",
    format: str = "png",
) -> dict[str, Any]:
    """Plot signals from a session's raw file.

    AC simulations auto-render as Bode plots (gain + phase subplots, log x).
    Transient/DC plots put V signals on the left axis and I signals dashed
    on the right axis. format: 'png' | 'html' | 'both' (HTML needs plotly).
    """
    from spicemcp.tools.plot import plot_signals as _run

    return _run(
        session_id=session_id,
        signals=signals,
        x_start=x_start,
        x_end=x_end,
        step=step,
        overlay_steps=overlay_steps,
        title=title,
        format=format,
    )


@mcp.tool()
def modify_netlist(
    session_id: str,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply a batch of netlist edits via spicelib's SpiceEditor.

    Each change is a dict:
      - {type: 'component', ref: 'R1', value: '4.7k'}
      - {type: 'parameter', ref: 'Vdd', value: '5'}
      - {type: 'model', ref: 'D1', value: '1N4148'}
      - {type: 'instruction', ref: '.tran 10u', action: 'add' | 'remove'}

    Sets simulation_required on the session - measure_signal and plot_signals
    will return an error until simulate is called again.
    """
    from spicemcp.tools.netlist import modify_netlist as _run

    return _run(session_id=session_id, changes=changes)


@mcp.tool()
def list_models(search: str = "") -> dict[str, Any]:
    """List model files in configured model_dirs, optionally filtered by 'search'.

    Substring match (case-insensitive) on filename. Returns close-name
    suggestions when the search term has no direct matches.
    """
    from spicemcp.tools.models import list_models as _run

    return _run(search=search)


@mcp.tool()
def cleanup_session(
    session_id: str,
    keep_log: bool = True,
    delete_session: bool = False,
) -> dict[str, Any]:
    """Clean up raw files for a session, optionally deleting it entirely.

    session_id: session identifier
    keep_log: if True (default), preserve the log file for diagnostics
    delete_session: if True, remove the session and all files entirely
    """
    from spicemcp.tools.session import cleanup_session as _run

    return _run(session_id=session_id, keep_log=keep_log, delete_session=delete_session)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
