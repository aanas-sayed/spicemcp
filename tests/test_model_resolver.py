"""Model resolver tests -- 3-tier path resolution logic."""

import pytest
from pathlib import Path

from spicemcp.core.model_resolver import ModelResolver

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_MODELS = FIXTURES / "sample_models"


# ---------------------------------------------------------------------------
# Bare filenames (Tier 1)
# ---------------------------------------------------------------------------

def test_bare_filename_not_in_any_mount_is_passthrough():
    resolver = ModelResolver([])
    ref = resolver.resolve(".lib XBUCK360.lib", "XBUCK360.lib")
    assert ref.status == "passthrough"
    assert ref.resolved_path is None

def test_bare_filename_found_in_first_mount(tmp_path):
    (tmp_path / "MyModel.lib").write_text("* stub")
    resolver = ModelResolver([tmp_path])
    ref = resolver.resolve(".lib MyModel.lib", "MyModel.lib")
    assert ref.status == "found"
    assert ref.resolved_path == "/models/user_0/MyModel.lib"
    assert ref.host_path == str(tmp_path / "MyModel.lib")

def test_bare_filename_found_in_second_mount(tmp_path):
    dir0 = tmp_path / "dir0"
    dir0.mkdir()
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir1 / "MyModel.lib").write_text("* stub")
    resolver = ModelResolver([dir0, dir1])
    ref = resolver.resolve(".lib MyModel.lib", "MyModel.lib")
    assert ref.status == "found"
    assert ref.resolved_path == "/models/user_1/MyModel.lib"

def test_bare_filename_checks_mounts_in_order(tmp_path):
    """When the same filename is in both mounts, the first match wins."""
    dir0 = tmp_path / "dir0"
    dir0.mkdir()
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir0 / "MyModel.lib").write_text("* stub0")
    (dir1 / "MyModel.lib").write_text("* stub1")
    resolver = ModelResolver([dir0, dir1])
    ref = resolver.resolve(".lib MyModel.lib", "MyModel.lib")
    assert ref.resolved_path == "/models/user_0/MyModel.lib"

def test_bare_filename_against_sample_models():
    resolver = ModelResolver([SAMPLE_MODELS])
    ref = resolver.resolve(".lib XBUCK360.lib", "XBUCK360.lib")
    assert ref.status == "found"
    assert ref.resolved_path == "/models/user_0/XBUCK360.lib"

def test_bare_sub_file_found(tmp_path):
    (tmp_path / "XLDO312A.sub").write_text("* stub")
    resolver = ModelResolver([tmp_path])
    ref = resolver.resolve(".lib XLDO312A.sub", "XLDO312A.sub")
    assert ref.status == "found"
    assert ref.resolved_path == "/models/user_0/XLDO312A.sub"


# ---------------------------------------------------------------------------
# Relative paths with directory components (pass-through, work-dir resolved)
# ---------------------------------------------------------------------------

def test_relative_path_with_subdir_is_found():
    resolver = ModelResolver([])
    ref = resolver.resolve(".lib subdir/model.lib", "subdir/model.lib")
    assert ref.status == "found"
    assert ref.resolved_path == "subdir/model.lib"

def test_relative_path_deep_subdir():
    resolver = ModelResolver([])
    ref = resolver.resolve(".lib a/b/c/model.lib", "a/b/c/model.lib")
    assert ref.status == "found"
    assert ref.resolved_path == "a/b/c/model.lib"


# ---------------------------------------------------------------------------
# Absolute paths (Tier 3)
# ---------------------------------------------------------------------------

def test_absolute_path_in_mount_is_rewritten(tmp_path):
    model = tmp_path / "XBUCK360.lib"
    model.write_text("* stub")
    resolver = ModelResolver([tmp_path])
    ref = resolver.resolve(f".lib {model}", str(model))
    assert ref.status == "rewritten"
    assert ref.resolved_path == "/models/user_0/XBUCK360.lib"
    assert ref.host_path == str(model)

def test_absolute_path_subdirectory_in_mount_is_rewritten(tmp_path):
    subdir = tmp_path / "vendor" / "acme"
    subdir.mkdir(parents=True)
    model = subdir / "XBUCK360.lib"
    model.write_text("* stub")
    resolver = ModelResolver([tmp_path])
    ref = resolver.resolve(f".lib {model}", str(model))
    assert ref.status == "rewritten"
    assert ref.resolved_path == "/models/user_0/vendor/acme/XBUCK360.lib"

def test_absolute_path_in_second_mount_uses_correct_index(tmp_path):
    dir0 = tmp_path / "dir0"
    dir0.mkdir()
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    model = dir1 / "MyModel.lib"
    model.write_text("* stub")
    resolver = ModelResolver([dir0, dir1])
    ref = resolver.resolve(f".lib {model}", str(model))
    assert ref.status == "rewritten"
    assert ref.resolved_path == "/models/user_1/MyModel.lib"

def test_absolute_path_outside_all_mounts_is_rejected(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    outside = Path("/some/other/path/evil.lib")
    resolver = ModelResolver([mount])
    ref = resolver.resolve(f".lib {outside}", str(outside))
    assert ref.status == "rejected"
    assert ref.resolved_path is None

def test_absolute_path_no_mounts_is_rejected():
    resolver = ModelResolver([])
    ref = resolver.resolve(".lib /absolute/path/model.lib", "/absolute/path/model.lib")
    assert ref.status == "rejected"


# ---------------------------------------------------------------------------
# find_similar
# ---------------------------------------------------------------------------

def test_find_similar_returns_close_matches(tmp_path):
    for name in ["XBUCK360.lib", "XBUCK360_TRANS.lib", "TPS54361.lib", "XLDO312.lib"]:
        (tmp_path / name).write_text("* stub")
    resolver = ModelResolver([tmp_path])
    matches = resolver.find_similar("XBUCK360.lib")
    assert "XBUCK360.lib" in matches

def test_find_similar_no_mounts_returns_empty():
    resolver = ModelResolver([])
    assert resolver.find_similar("XBUCK360.lib") == []

def test_find_similar_unrelated_filename_returns_empty(tmp_path):
    (tmp_path / "completely_unrelated.lib").write_text("* stub")
    resolver = ModelResolver([tmp_path])
    matches = resolver.find_similar("XYZQRS999.lib")
    assert matches == []

def test_find_similar_returns_at_most_three(tmp_path):
    for i in range(10):
        (tmp_path / f"XBUCK360_{i}.lib").write_text("* stub")
    resolver = ModelResolver([tmp_path])
    matches = resolver.find_similar("XBUCK360_0.lib")
    assert len(matches) <= 3

def test_find_similar_scans_multiple_dirs(tmp_path):
    dir0 = tmp_path / "dir0"
    dir0.mkdir()
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir0 / "ModelA.lib").write_text("* stub")
    (dir1 / "ModelAlt.lib").write_text("* stub")
    resolver = ModelResolver([dir0, dir1])
    matches = resolver.find_similar("ModelA.lib")
    assert len(matches) >= 1


# ---------------------------------------------------------------------------
# ModelReference fields
# ---------------------------------------------------------------------------

def test_model_reference_directive_preserved(tmp_path):
    (tmp_path / "MyModel.lib").write_text("* stub")
    resolver = ModelResolver([tmp_path])
    directive = ".lib MyModel.lib"
    ref = resolver.resolve(directive, "MyModel.lib")
    assert ref.directive == directive

def test_rejected_reference_has_no_resolved_path():
    resolver = ModelResolver([])
    ref = resolver.resolve(".lib /abs/path.lib", "/abs/path.lib")
    assert ref.resolved_path is None
    assert ref.host_path is None
