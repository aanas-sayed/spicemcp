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


def _editor_for(netlist_path):
    """Return a SpiceEditor for an existing netlist file."""
    from spicelib.editor.spice_editor import SpiceEditor

    return SpiceEditor(str(netlist_path))


def _apply_change(editor, change: dict) -> tuple[dict | None, dict | None]:
    """Apply a single change. Returns (applied_dict, failed_dict). Exactly one is None."""
    ctype = change.get("type")
    ref = change.get("ref")
    value = change.get("value")
    action = change.get("action")

    if ctype == "component":
        try:
            old = editor.get_component_value(ref)
        except Exception:
            return None, {
                "type": "component",
                "ref": ref,
                "reason": f"Component {ref} not found in netlist",
            }
        try:
            editor.set_component_value(ref, value)
        except Exception as exc:
            return None, {
                "type": "component",
                "ref": ref,
                "reason": f"Failed to set value: {exc}",
            }
        return {
            "type": "component",
            "ref": ref,
            "old_value": old,
            "new_value": value,
        }, None

    if ctype == "parameter":
        try:
            old = editor.get_parameter(ref)
        except Exception:
            old = None
        try:
            editor.set_parameter(ref, value)
        except Exception as exc:
            return None, {
                "type": "parameter",
                "ref": ref,
                "reason": f"Failed to set parameter: {exc}",
            }
        return {
            "type": "parameter",
            "ref": ref,
            "old_value": old,
            "new_value": value,
        }, None

    if ctype == "model":
        try:
            old = editor.get_component_value(ref)
        except Exception:
            return None, {
                "type": "model",
                "ref": ref,
                "reason": f"Component {ref} not found in netlist",
            }
        try:
            editor.set_element_model(ref, value)
        except Exception as exc:
            return None, {
                "type": "model",
                "ref": ref,
                "reason": f"Failed to set model: {exc}",
            }
        return {
            "type": "model",
            "ref": ref,
            "old_value": old,
            "new_value": value,
        }, None

    if ctype == "instruction":
        if action == "add":
            try:
                editor.add_instruction(ref)
            except Exception as exc:
                return None, {
                    "type": "instruction",
                    "ref": ref,
                    "reason": f"Failed to add instruction: {exc}",
                }
            return {
                "type": "instruction",
                "ref": ref,
                "action": "add",
                "old_value": None,
            }, None
        if action == "remove":
            try:
                removed = editor.remove_instruction(ref)
            except Exception as exc:
                return None, {
                    "type": "instruction",
                    "ref": ref,
                    "reason": f"Failed to remove instruction: {exc}",
                }
            if not removed:
                return None, {
                    "type": "instruction",
                    "ref": ref,
                    "reason": f"Instruction '{ref}' not found in netlist",
                }
            return {
                "type": "instruction",
                "ref": ref,
                "action": "remove",
                "old_value": ref,
            }, None
        return None, {
            "type": "instruction",
            "ref": ref,
            "reason": f"Unknown action '{action}'. Use 'add' or 'remove'.",
        }

    return None, {
        "type": ctype,
        "ref": ref,
        "reason": (
            f"Unknown change type '{ctype}'. Valid types: component, parameter, model, instruction."
        ),
    }


def modify_netlist(session_id: str, changes: list[dict]) -> dict:
    """Apply a batch of netlist edits via spicelib's SpiceEditor.

    Each change is a dict with 'type', 'ref', and either 'value' (component/
    parameter/model) or 'action' (instruction). Successful changes go into
    'applied'; failures go into 'failed'. Sets simulation_required on the
    session so subsequent measure/plot calls return an error until simulate
    is called again.
    """
    from spicemcp import _globals

    manager = _globals.manager
    session = manager.get_session(session_id)
    if session is None:
        return {
            "applied": [],
            "failed": [],
            "netlist_preview": "",
            "warnings": [],
            "simulation_required": False,
            "error": (
                f"Session '{session_id}' not found or has expired."
                " Create a new session with simulate_netlist or create_session."
            ),
        }

    if session.netlist_path is None or not session.netlist_path.exists():
        return {
            "applied": [],
            "failed": [],
            "netlist_preview": "",
            "warnings": [],
            "simulation_required": False,
            "error": (
                f"Session '{session_id}' has no netlist. Call write_netlist before modify_netlist."
            ),
        }

    if not isinstance(changes, list) or not changes:
        return {
            "applied": [],
            "failed": [],
            "netlist_preview": "",
            "warnings": [],
            "simulation_required": False,
            "error": "'changes' must be a non-empty list",
        }

    try:
        editor = _editor_for(session.netlist_path)
    except Exception as exc:
        return {
            "applied": [],
            "failed": [],
            "netlist_preview": "",
            "warnings": [],
            "simulation_required": False,
            "error": f"Failed to load netlist for editing: {type(exc).__name__}: {exc}",
        }

    applied: list[dict] = []
    failed: list[dict] = []
    for change in changes:
        a, f = _apply_change(editor, change)
        if a is not None:
            applied.append(a)
        if f is not None:
            failed.append(f)

    try:
        editor.save_netlist(str(session.netlist_path))
    except Exception as exc:
        return {
            "applied": applied,
            "failed": failed,
            "netlist_preview": "",
            "warnings": [],
            "simulation_required": False,
            "error": f"Failed to save modified netlist: {type(exc).__name__}: {exc}",
        }

    session.simulation_required = True
    # Stale prior results
    session.raw_path = None
    session.raw_file_size_mb = 0.0
    session.meas_results = {}
    session.signals_available = []

    try:
        text = session.netlist_path.read_text(errors="replace")
        preview = "\n".join(text.splitlines()[:20])
    except OSError:
        preview = ""

    return {
        "applied": applied,
        "failed": failed,
        "netlist_preview": preview,
        "warnings": [],
        "simulation_required": True,
        "error": None,
    }
