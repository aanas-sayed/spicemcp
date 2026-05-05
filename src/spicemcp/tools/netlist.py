"""MCP tool handler for write_netlist."""

from __future__ import annotations


def _violation_to_dict(v) -> dict:
    return {
        "line": v.line,
        "type": v.type,
        "content": v.content,
        "fix": v.fix,
    }


def _ref_to_dict(ref) -> dict:
    d = {
        "directive": ref.directive,
        "status": ref.status,
        "resolved_path": ref.resolved_path,
    }
    if ref.similar:
        d["similar"] = ref.similar
    return d


def _apply_path_rewrites(netlist: str, model_references: list) -> str:
    """Replace absolute host paths with container paths in the netlist text."""
    for ref in model_references:
        if ref.status == "rewritten" and ref.host_path and ref.resolved_path:
            netlist = netlist.replace(ref.host_path, ref.resolved_path)
    return netlist


def write_netlist(
    session_id: str,
    netlist: str,
    filename: str = "circuit.net",
) -> dict:
    """Sanitize and write a netlist to the session's work directory.

    Returns accepted/rejected status, violations, model reference resolution
    results, and sanitizer warnings.
    """
    from spicemcp import _globals
    from spicemcp.core.sanitizer import sanitize

    manager = _globals.manager
    config = _globals.config

    session = manager.get_session(session_id)
    if session is None:
        return {
            "accepted": False,
            "filename": filename,
            "violations": [],
            "warnings": [],
            "model_references": [],
            "estimated_raw_size_mb": None,
            "error": (
                f"Session '{session_id}' not found or has expired."
                " Create a new session with simulate_netlist or create_session."
            ),
        }

    model_dirs = config.model_dirs if config else []
    result = sanitize(netlist, model_dirs=model_dirs)

    violations = [_violation_to_dict(v) for v in result.violations]
    refs = [_ref_to_dict(r) for r in result.model_references]
    warnings = list(result.warnings)

    # Warn about model references that could not be resolved
    for ref in result.model_references:
        if ref.status == "not_found":
            msg = (
                f"Model '{ref.directive}' not found in any configured model directory."
                " Simulation will likely fail with 'can't find model'."
            )
            if ref.similar:
                msg += f" Similar models found: {', '.join(ref.similar)}"
            warnings.append(msg)

    if not result.accepted:
        return {
            "accepted": False,
            "filename": filename,
            "violations": violations,
            "warnings": warnings,
            "model_references": refs,
            "estimated_raw_size_mb": None,
            "error": None,
        }

    # Apply path rewrites and write to work directory
    rewritten = _apply_path_rewrites(netlist, result.model_references)
    netlist_path = session.work_dir / filename
    netlist_path.write_text(rewritten)
    session.netlist_path = netlist_path
    session.simulation_required = True

    return {
        "accepted": True,
        "filename": filename,
        "violations": [],
        "warnings": warnings,
        "model_references": refs,
        "estimated_raw_size_mb": None,
        "error": None,
    }
