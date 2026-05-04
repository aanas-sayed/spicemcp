"""Simulation failure diagnosis with ranked recovery suggestions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Suggestion:
    action: str
    severity: str  # always_safe | safe_for_most | use_with_caution | fix_required
    tradeoff: str = ""


@dataclass
class DiagnosisResult:
    title: str
    suggestions: list[Suggestion] = field(default_factory=list)


_PATTERNS: list[tuple[str, DiagnosisResult]] = [
    (
        r"time step too small|timestep too small",
        DiagnosisResult(
            title="Convergence failure - timestep too small",
            suggestions=[
                Suggestion(
                    action="Add initial conditions: .ic V(out)=<expected_dc>",
                    severity="always_safe",
                    tradeoff="No accuracy impact. Requires knowing approximate DC values.",
                ),
                Suggestion(
                    action="Add .options trtol=3",
                    severity="safe_for_most",
                    tradeoff=(
                        "Slightly reduces switching transition accuracy. "
                        "Acceptable for power electronics. NOT recommended "
                        "for precision analog (ADC, PLL) where timing matters."
                    ),
                ),
                Suggestion(
                    action="Increase reltol: .options reltol=0.01",
                    severity="use_with_caution",
                    tradeoff=(
                        "Relaxes error tolerance 10x. May cause visible "
                        "artifacts in high-Q circuits."
                    ),
                ),
            ],
        ),
    ),
    (
        r"singular matrix|matrix.*singular|singular.*matrix",
        DiagnosisResult(
            title="Topology error - singular matrix",
            suggestions=[
                Suggestion(
                    action="Every node needs a DC path to ground",
                    severity="fix_required",
                ),
                Suggestion(
                    action=(
                        "Check for voltage source loops"
                        " (two voltage sources in series with no resistance)"
                    ),
                    severity="fix_required",
                ),
                Suggestion(
                    action="Add a large resistor (e.g. 1G) from floating nodes to ground",
                    severity="always_safe",
                    tradeoff="Negligible accuracy impact.",
                ),
            ],
        ),
    ),
    (
        r"can'?t find (model|definition|subcircuit)|undefined (model|subcircuit)|unknown component",
        DiagnosisResult(
            title="Missing model or subcircuit",
            suggestions=[
                Suggestion(
                    action="Use list_models to check available models and their paths",
                    severity="fix_required",
                ),
                Suggestion(
                    action="Verify .lib/.include path is correct relative to the netlist",
                    severity="fix_required",
                ),
            ],
        ),
    ),
    (
        r"node\s+\S+\s+is\s+floating|floating node",
        DiagnosisResult(
            title="Floating node",
            suggestions=[
                Suggestion(
                    action="Add a 1G resistor from the floating node to ground",
                    severity="always_safe",
                    tradeoff="Negligible accuracy impact on circuit behaviour.",
                ),
            ],
        ),
    ),
    (
        r"dc operating point not found|no convergence in dc",
        DiagnosisResult(
            title="DC operating point convergence failure",
            suggestions=[
                Suggestion(
                    action="Add .ic or .nodeset directives with approximate DC values",
                    severity="always_safe",
                    tradeoff="No accuracy impact.",
                ),
                Suggestion(
                    action="Add .options srcsteps=1 to ramp sources from zero",
                    severity="safe_for_most",
                    tradeoff="Slows initial convergence but often resolves startup failures.",
                ),
            ],
        ),
    ),
    (
        r"division by zero|divide by zero",
        DiagnosisResult(
            title="Division by zero in expression",
            suggestions=[
                Suggestion(
                    action="Check .param expressions for zero denominators",
                    severity="fix_required",
                ),
                Suggestion(
                    action="Add a small series resistance (e.g. 1m) to ideal sources or inductors",
                    severity="always_safe",
                    tradeoff="Negligible effect at normal operating currents.",
                ),
            ],
        ),
    ),
    (
        r"inductor.*current.*limit|current through.*inductor.*exceed",
        DiagnosisResult(
            title="Inductor current limit exceeded",
            suggestions=[
                Suggestion(
                    action="Reduce simulation timestep or add .ic for inductor current",
                    severity="always_safe",
                    tradeoff="No accuracy impact.",
                ),
            ],
        ),
    ),
]


def diagnose(log_text: str) -> DiagnosisResult | None:
    """Return the first matching DiagnosisResult for the given log text, or None."""
    lower = log_text.lower()
    for pattern, result in _PATTERNS:
        if re.search(pattern, lower):
            return result
    return None
