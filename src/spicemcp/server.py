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
