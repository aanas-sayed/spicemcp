"""Netlist sanitizer -- the security core. Runs before every simulation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .model_resolver import ModelReference, ModelResolver


class ViolationType(StrEnum):
    CONTROL_BLOCK = "CONTROL_BLOCK"
    UNIXCOM = "UNIXCOM"
    CODEMODEL = "CODEMODEL"
    LIB_URL = "LIB_URL"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    PATH_REJECTED = "PATH_REJECTED"
    VERILOG_DLL = "VERILOG_DLL"


@dataclass
class SanitizerViolation:
    line: int
    type: str
    content: str
    fix: str


@dataclass
class SanitizeResult:
    accepted: bool
    violations: list[SanitizerViolation]
    warnings: list[str]
    model_references: list[ModelReference]


# Compiled patterns (case-insensitive matching done via re.IGNORECASE on use)
_RE_CONTROL_START = re.compile(r"^\.control\b", re.IGNORECASE)
_RE_CONTROL_END = re.compile(r"^\.endc\b", re.IGNORECASE)
_RE_UNIXCOM = re.compile(r"^set\s+unixcom\b", re.IGNORECASE)
_RE_CODEMODEL = re.compile(r"^\.(codemodel|pre_codemodel|load)\b", re.IGNORECASE)
_RE_PRAGMA = re.compile(r"^\.pragma\b", re.IGNORECASE)
_RE_DLL = re.compile(r"\.dll\b", re.IGNORECASE)
_RE_LIB_INCLUDE = re.compile(r"^\.(lib|include)\b", re.IGNORECASE)
_RE_URL = re.compile(r"^https?://", re.IGNORECASE)


def _extract_lib_path(line: str) -> str | None:
    """Extract the path argument from a .lib or .include directive.

    Handles quoted paths and strips optional section-name second tokens.
    Returns None if the directive has no path argument.
    """
    m = re.match(r"^\.(lib|include)\s+(.*)", line, re.IGNORECASE)
    if not m:
        return None
    rest = m.group(2).strip()
    if not rest:
        return None
    if rest[0] in ('"', "'"):
        quote = rest[0]
        end = rest.find(quote, 1)
        if end > 0:
            return rest[1:end]
        return rest[1:]  # unclosed quote -- take the rest
    # Unquoted: first whitespace-delimited token is the path
    return rest.split()[0]


def sanitize(
    netlist: str,
    model_dirs: list[Path | str] | None = None,
) -> SanitizeResult:
    """Sanitize a SPICE netlist string.

    Checks every line for security violations and classifies model references.
    Returns a SanitizeResult; accepted=True only if there are zero violations.

    Args:
        netlist: Raw netlist content as a string.
        model_dirs: Host paths to configured model mount directories. If None
            or empty, absolute paths always produce PATH_REJECTED violations and
            bare filenames always produce passthrough references.
    """
    if model_dirs is None:
        model_dirs = []

    resolver = ModelResolver(model_dirs)
    violations: list[SanitizerViolation] = []
    warnings: list[str] = []
    model_references: list[ModelReference] = []

    lines = netlist.splitlines()
    in_control = False

    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        # Line 1 is always the SPICE title -- ignored by all parsers
        if lineno == 1:
            continue
        if not stripped:
            continue

        # Comment lines
        if stripped.startswith("*"):
            continue

        # Continuation lines start with '+' -- carry context of prior directive.
        # Security-relevant directives don't span lines in practice; skip.
        if stripped.startswith("+"):
            continue

        # --- .control block tracking ---
        if _RE_CONTROL_START.match(stripped):
            in_control = True
            violations.append(
                SanitizerViolation(
                    line=lineno,
                    type=ViolationType.CONTROL_BLOCK,
                    content=stripped,
                    fix=(
                        "ngspice .control blocks can execute arbitrary shell commands and are"
                        " not permitted. Move measurement directives to .MEAS statements in the"
                        " netlist body. Example: .meas tran vout_max MAX V(out)"
                    ),
                )
            )
            continue

        if _RE_CONTROL_END.match(stripped):
            in_control = False
            continue

        if in_control:
            # Skip all content inside a .control block -- already rejected above
            continue

        # --- set unixcom (D-01: also blocks outside .control as a belt-and-suspenders) ---
        if _RE_UNIXCOM.match(stripped):
            violations.append(
                SanitizerViolation(
                    line=lineno,
                    type=ViolationType.UNIXCOM,
                    content=stripped,
                    fix=(
                        "'set unixcom' causes ngspice to treat unknown commands as shell"
                        " invocations. This directive is not permitted."
                    ),
                )
            )
            continue

        # --- XSPICE codemodel / load ---
        if _RE_CODEMODEL.match(stripped):
            violations.append(
                SanitizerViolation(
                    line=lineno,
                    type=ViolationType.CODEMODEL,
                    content=stripped,
                    fix=(
                        "XSPICE codemodel and .load directives load C shared libraries as"
                        " arbitrary code and are not permitted."
                    ),
                )
            )
            continue

        # --- QSPICE .pragma and DLL references ---
        if _RE_PRAGMA.match(stripped):
            violations.append(
                SanitizerViolation(
                    line=lineno,
                    type=ViolationType.VERILOG_DLL,
                    content=stripped,
                    fix=(
                        ".pragma directives are used by QSPICE for Verilog DLL loading and"
                        " are not permitted."
                    ),
                )
            )
            continue

        if _RE_DLL.search(stripped):
            violations.append(
                SanitizerViolation(
                    line=lineno,
                    type=ViolationType.VERILOG_DLL,
                    content=stripped,
                    fix="DLL file references are not permitted.",
                )
            )
            continue

        # --- .lib / .include path checks ---
        if _RE_LIB_INCLUDE.match(stripped):
            path_arg = _extract_lib_path(stripped)
            if path_arg is None:
                # Bare .lib with no argument -- unusual but not dangerous
                continue

            # URL-based .lib (LTspice supports this natively -- D-03)
            if _RE_URL.match(path_arg):
                violations.append(
                    SanitizerViolation(
                        line=lineno,
                        type=ViolationType.LIB_URL,
                        content=stripped,
                        fix=(
                            "URL-based .lib references are not permitted. Place the model file"
                            " in a configured model_dirs directory and use a relative or"
                            " absolute local path."
                        ),
                    )
                )
                continue

            # Path traversal (.. in any position)
            if ".." in path_arg:
                violations.append(
                    SanitizerViolation(
                        line=lineno,
                        type=ViolationType.PATH_TRAVERSAL,
                        content=stripped,
                        fix=(
                            "'..' is not allowed in .include/.lib paths. Use paths within"
                            " the work directory or add the model directory to model_dirs"
                            " in your config."
                        ),
                    )
                )
                continue

            # Delegate to model resolver for absolute and bare-filename paths.
            # Relative paths with directory components are allowed as-is and are
            # not added to model_references (they resolve in the work dir at runtime).
            ref = resolver.resolve(stripped, path_arg)

            if ref.status == "rejected":
                violations.append(
                    SanitizerViolation(
                        line=lineno,
                        type=ViolationType.PATH_REJECTED,
                        content=stripped,
                        fix=(
                            f"Absolute path '{path_arg}' is not within any configured model"
                            " directory. Add its parent directory to model_dirs in your config,"
                            " or use a relative path."
                        ),
                    )
                )
                # Still record the reference so callers can see the similar-files list
                model_references.append(ref)
                continue

            # For relative paths with directory components (status="found", no host_path,
            # resolved_path == path_arg) we skip adding to model_references -- they are
            # purely a work-dir concern and need no mount tracking.
            path_obj = Path(path_arg)
            if not path_obj.is_absolute() and path_obj.parent != Path("."):
                continue

            model_references.append(ref)

    return SanitizeResult(
        accepted=len(violations) == 0,
        violations=violations,
        warnings=warnings,
        model_references=model_references,
    )
