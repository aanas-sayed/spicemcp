"""Diagnosis engine tests."""

from spicemcp.core.diagnosis import DiagnosisResult, Suggestion, diagnose

# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


def test_diagnose_timestep_too_small():
    result = diagnose("Error: time step too small")
    assert result is not None
    assert "timestep too small" in result.title.lower() or "convergence" in result.title.lower()


def test_diagnose_timestep_case_insensitive():
    result = diagnose("ERROR: Timestep Too Small")
    assert result is not None


def test_diagnose_singular_matrix():
    result = diagnose("Matrix is singular at node 5")
    assert result is not None
    assert "singular" in result.title.lower()


def test_diagnose_missing_model():
    result = diagnose("Can't find model TPS54360")
    assert result is not None
    assert "model" in result.title.lower() or "missing" in result.title.lower()


def test_diagnose_missing_subcircuit():
    result = diagnose("Can't find subcircuit XBUCK360")
    assert result is not None


def test_diagnose_floating_node():
    result = diagnose("node N001 is floating")
    assert result is not None
    assert "floating" in result.title.lower()


def test_diagnose_dc_no_convergence():
    result = diagnose("DC operating point not found after 100 iterations")
    assert result is not None


def test_diagnose_no_match_returns_none():
    result = diagnose("Simulation complete. No errors.")
    assert result is None


def test_diagnose_empty_log():
    result = diagnose("")
    assert result is None


# ---------------------------------------------------------------------------
# Suggestion structure
# ---------------------------------------------------------------------------


def test_suggestions_are_list():
    result = diagnose("time step too small")
    assert isinstance(result.suggestions, list)
    assert len(result.suggestions) > 0


def test_suggestion_has_required_fields():
    result = diagnose("time step too small")
    for s in result.suggestions:
        assert isinstance(s, Suggestion)
        assert s.action
        assert s.severity in ("always_safe", "safe_for_most", "use_with_caution", "fix_required")


def test_timestep_suggestions_have_tradeoffs():
    result = diagnose("time step too small")
    cautious = [s for s in result.suggestions if s.severity == "use_with_caution"]
    for s in cautious:
        assert s.tradeoff, "use_with_caution suggestions must explain the tradeoff"


def test_fix_required_singular_matrix():
    result = diagnose("singular matrix detected")
    fix_required = [s for s in result.suggestions if s.severity == "fix_required"]
    assert len(fix_required) >= 1


def test_always_safe_suggestion_for_timestep():
    result = diagnose("time step too small")
    safe = [s for s in result.suggestions if s.severity == "always_safe"]
    assert len(safe) >= 1


# ---------------------------------------------------------------------------
# DiagnosisResult dataclass
# ---------------------------------------------------------------------------


def test_diagnosis_result_default_suggestions():
    d = DiagnosisResult(title="test")
    assert d.suggestions == []


def test_suggestion_default_tradeoff():
    s = Suggestion(action="do something", severity="always_safe")
    assert s.tradeoff == ""
