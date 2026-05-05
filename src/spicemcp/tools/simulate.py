"""MCP tool handler for simulate (existing session)."""

from __future__ import annotations


def simulate(
    session_id: str,
    timeout_s: int = 300,
) -> dict:
    """Run a simulation on an existing session that already has a netlist.

    The session must have been created with create_session and have a netlist
    written via write_netlist. Returns the same structure as simulate_netlist
    minus session_id and model_references.
    """
    from spicemcp import _globals
    from spicemcp.tools.simulate_netlist import run_simulation_on_session

    manager = _globals.manager

    session = manager.get_session(session_id)
    if session is None:
        return {
            "status": None,
            "domain": None,
            "elapsed_s": None,
            "meas_results": None,
            "operating_point": None,
            "step_info": None,
            "signals_available": None,
            "raw_file_size_mb": None,
            "log_summary": None,
            "warnings": None,
            "diagnosis": None,
            "error": (
                f"Session '{session_id}' not found or has expired."
                " Create a new session with simulate_netlist or create_session."
            ),
        }

    if session.netlist_path is None or not session.netlist_path.exists():
        return {
            "status": None,
            "domain": None,
            "elapsed_s": None,
            "meas_results": None,
            "operating_point": None,
            "step_info": None,
            "signals_available": None,
            "raw_file_size_mb": None,
            "log_summary": None,
            "warnings": None,
            "diagnosis": None,
            "error": (
                f"Session '{session_id}' has no netlist."
                " Call write_netlist before simulate."
            ),
        }

    timeout_s = min(int(timeout_s), 600)
    return run_simulation_on_session(session, timeout_s)
