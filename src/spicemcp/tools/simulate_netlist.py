"""Core simulation runner and simulate_netlist compound tool."""

from __future__ import annotations

import time
from pathlib import Path

from spicelib import SimRunner

from spicemcp.backends.docker_ltspice import DockerLTspice
from spicemcp.backends.docker_ngspice import DockerNGspice
from spicemcp.core.analysis_engine import (
    detect_domain,
    list_signals,
    parse_log_summary,
    parse_meas_results,
    parse_operating_point,
    parse_step_info,
)
from spicemcp.core.diagnosis import diagnose
from spicemcp.core.session_manager import SimSession
from spicemcp.tools.netlist import _apply_path_rewrites, _ref_to_dict, _violation_to_dict


def _backend_class(simulator: str):
    if simulator == "ltspice":
        return DockerLTspice
    if simulator == "ngspice":
        return DockerNGspice
    raise ValueError(f"Unknown simulator: '{simulator}'. Valid values: 'ltspice', 'ngspice'.")


def _diagnosis_to_dict(d) -> dict | None:
    if d is None:
        return None
    return {
        "title": d.title,
        "suggestions": [
            {"action": s.action, "tradeoff": s.tradeoff, "severity": s.severity}
            for s in d.suggestions
        ],
    }


def run_simulation_on_session(session: SimSession, timeout_s: int) -> dict:
    """Run a simulation for the given session and return the partial response dict.

    The session must already have netlist_path set. Updates session state
    (raw_path, log_path, domain, signals_available, meas_results, step_info,
    raw_file_size_mb, status) in place.

    Returns a dict conforming to the 'simulate' tool output shape (no session_id).
    """
    backend = _backend_class(session.simulator)
    t0 = time.monotonic()
    session.status = "running"

    runner = SimRunner(
        simulator=backend,
        output_folder=session.work_dir,
        timeout=float(timeout_s),
        verbose=False,
    )
    task = runner.run(session.netlist_path, exe_log=True)

    # wait_completion timeout is a per-completion reset; add a safety margin
    completed = runner.wait_completion(
        timeout=float(timeout_s + 30),
        abort_all_on_timeout=True,
    )
    elapsed = round(time.monotonic() - t0, 2)

    # Determine raw/log paths from task results
    raw_path: Path | None = None
    log_path: Path | None = None
    result = task.get_results() if task is not None else None
    if result is not None:
        if result[0]:
            raw_path = Path(result[0])
        if len(result) > 1 and result[1]:
            log_path = Path(result[1])

    # Fall back: scan work_dir for log if SimRunner didn't report one
    if log_path is None or not log_path.exists():
        candidates = sorted(session.work_dir.glob("*.log"))
        if candidates:
            log_path = candidates[-1]

    log_summary = parse_log_summary(log_path) if log_path and log_path.exists() else ""

    sim_failed = not completed or raw_path is None or not raw_path.exists()
    if not completed and sim_failed:
        status = "timeout"
    elif sim_failed:
        status = "failed"
    else:
        status = "completed"

    if status != "completed":
        session.status = status
        diagnosis = _diagnosis_to_dict(diagnose(log_summary) if log_summary else None)
        return {
            "status": status,
            "domain": "unknown",
            "elapsed_s": elapsed,
            "meas_results": {},
            "operating_point": None,
            "step_info": [],
            "signals_available": [],
            "raw_file_size_mb": 0,
            "log_summary": log_summary,
            "warnings": [],
            "diagnosis": diagnosis,
            "error": None,
        }

    # Completed successfully - parse all results
    session.raw_path = raw_path
    session.log_path = log_path
    session.status = "completed"
    session.simulation_required = False

    domain = detect_domain(raw_path)
    session.domain = domain

    signals = list_signals(raw_path)
    session.signals_available = signals

    raw_mb = raw_path.stat().st_size / (1024 * 1024)
    session.raw_file_size_mb = raw_mb

    meas = parse_meas_results(log_path) if log_path and log_path.exists() else {}
    session.meas_results = meas

    step_info = parse_step_info(log_path) if log_path and log_path.exists() else []
    session.step_info = step_info

    op = parse_operating_point(raw_path) if domain == "op" else None

    warnings: list[str] = []
    if not meas:
        warnings.append(
            "No .MEAS statements found - consider adding measurements for structured results"
        )

    return {
        "status": "completed",
        "domain": domain,
        "elapsed_s": elapsed,
        "meas_results": meas,
        "operating_point": op,
        "step_info": step_info,
        "signals_available": signals,
        "raw_file_size_mb": round(raw_mb, 2),
        "log_summary": log_summary,
        "warnings": warnings,
        "diagnosis": None,
        "error": None,
    }


def simulate_netlist(
    simulator: str,
    netlist: str,
    filename: str = "circuit.net",
    timeout_s: int = 300,
) -> dict:
    """Create a session, sanitize the netlist, simulate, and return all results.

    This is the 90% path: one call returns .MEAS results, domain, signals,
    and model resolution status. The session_id is included for follow-up calls.
    """
    from spicemcp import _globals
    from spicemcp.core.sanitizer import sanitize

    if simulator not in ("ltspice", "ngspice"):
        return {
            "session_id": None,
            "status": "failed",
            "domain": "unknown",
            "elapsed_s": 0,
            "meas_results": {},
            "operating_point": None,
            "step_info": [],
            "signals_available": [],
            "raw_file_size_mb": 0,
            "log_summary": "",
            "model_references": [],
            "warnings": [],
            "violations": [],
            "diagnosis": None,
            "error": (
                f"Unknown simulator '{simulator}'."
                " Valid values: 'ltspice', 'ngspice'."
            ),
        }

    timeout_s = min(int(timeout_s), 600)

    manager = _globals.manager
    config = _globals.config

    # Create session
    try:
        session = manager.create_session(simulator)
    except RuntimeError as exc:
        return {
            "session_id": None,
            "status": "failed",
            "domain": "unknown",
            "elapsed_s": 0,
            "meas_results": {},
            "operating_point": None,
            "step_info": [],
            "signals_available": [],
            "raw_file_size_mb": 0,
            "log_summary": "",
            "model_references": [],
            "warnings": [],
            "violations": [],
            "diagnosis": None,
            "error": str(exc),
        }

    model_dirs = config.model_dirs if config else []
    san = sanitize(netlist, model_dirs=model_dirs)

    refs = [_ref_to_dict(r) for r in san.model_references]
    violations = [_violation_to_dict(v) for v in san.violations]
    warnings = list(san.warnings)

    for ref in san.model_references:
        if ref.status == "not_found":
            msg = (
                f"Model '{ref.directive}' not found in any configured model directory."
                " Simulation will likely fail with 'can't find model'."
            )
            if ref.similar:
                msg += f" Similar models found: {', '.join(ref.similar)}"
            warnings.append(msg)

    if not san.accepted:
        session.status = "failed"
        return {
            "session_id": session.session_id,
            "status": "failed",
            "domain": "unknown",
            "elapsed_s": 0,
            "meas_results": {},
            "operating_point": None,
            "step_info": [],
            "signals_available": [],
            "raw_file_size_mb": 0,
            "log_summary": "",
            "model_references": refs,
            "warnings": warnings,
            "violations": violations,
            "diagnosis": None,
            "error": None,
        }

    # Write netlist to work dir (with path rewrites applied)
    rewritten = _apply_path_rewrites(netlist, san.model_references)
    netlist_path = session.work_dir / filename
    netlist_path.write_text(rewritten)
    session.netlist_path = netlist_path

    # Run simulation
    sim_result = run_simulation_on_session(session, timeout_s)

    return {
        "session_id": session.session_id,
        **sim_result,
        "model_references": refs,
    }
