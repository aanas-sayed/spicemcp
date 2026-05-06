"""Config loading tests."""

import json
import sys
from pathlib import Path

import pytest

from spicemcp.config import SpiceMCPConfig, load_config


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_default_config_returns_sensible_values(tmp_path):
    config = load_config(path=tmp_path / "nonexistent.json")
    assert config.session_ttl_minutes == 10
    assert config.max_raw_size_mb == 200
    assert config.max_sessions == 10
    assert config.model_dirs == []

def test_default_ltspice_backend_is_docker(tmp_path):
    config = load_config(path=tmp_path / "nonexistent.json")
    assert config.ltspice.backend == "docker"
    assert config.ltspice.image is not None
    assert "docker-ltspice" in config.ltspice.image

def test_default_ngspice_backend_is_docker(tmp_path):
    config = load_config(path=tmp_path / "nonexistent.json")
    assert config.ngspice.backend == "docker"
    assert config.ngspice.image == "aanas0sayed/docker-ngspice:latest"

def test_apple_silicon_ltspice_image(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    from spicemcp.backends.docker_ltspice import _default_ltspice_image
    assert "macos-latest" in _default_ltspice_image()

def test_non_apple_silicon_ltspice_image(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    from spicemcp.backends.docker_ltspice import _default_ltspice_image
    assert _default_ltspice_image() == "aanas0sayed/docker-ltspice:latest"


# ---------------------------------------------------------------------------
# JSON file loading
# ---------------------------------------------------------------------------

def test_config_from_json_file(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "simulators": {
            "ltspice": {
                "backend": "docker",
                "image": "my-custom/ltspice:v2",
                "timeout_s": 600,
            }
        },
        "session_ttl_minutes": 5,
        "max_raw_size_mb": 100,
        "max_sessions": 3,
        "model_dirs": [str(tmp_path)],
    }))
    config = load_config(path=cfg_file)
    assert config.ltspice.image == "my-custom/ltspice:v2"
    assert config.ltspice.timeout_s == 600
    assert config.session_ttl_minutes == 5
    assert config.max_raw_size_mb == 100
    assert config.max_sessions == 3
    assert config.model_dirs == [tmp_path]

def test_partial_config_uses_defaults_for_missing_fields(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"session_ttl_minutes": 3}))
    config = load_config(path=cfg_file)
    assert config.session_ttl_minutes == 3
    assert config.max_raw_size_mb == 200  # default unchanged

def test_ngspice_config_from_json(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "simulators": {
            "ngspice": {"image": "my-custom/ngspice:v1", "timeout_s": 120}
        }
    }))
    config = load_config(path=cfg_file)
    assert config.ngspice.image == "my-custom/ngspice:v1"
    assert config.ngspice.timeout_s == 120

def test_model_dirs_are_path_objects(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"model_dirs": [str(tmp_path)]}))
    config = load_config(path=cfg_file)
    assert all(isinstance(d, Path) for d in config.model_dirs)

def test_local_override_takes_precedence(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "simulators": {
            "ltspice": {"backend": "docker", "image": "docker-image:v1"}
        },
        "overrides": {
            "ltspice": {"backend": "local", "executable": "/usr/bin/ltspice"}
        },
    }))
    config = load_config(path=cfg_file)
    assert config.ltspice.backend == "local"
    assert config.ltspice.executable == "/usr/bin/ltspice"

def test_missing_file_returns_defaults(tmp_path):
    config = load_config(path=tmp_path / "does_not_exist.json")
    assert type(config).__name__ == "SpiceMCPConfig"
    assert config.session_ttl_minutes == 10


# ---------------------------------------------------------------------------
# Environment variable
# ---------------------------------------------------------------------------

def test_env_var_config_path(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"session_ttl_minutes": 7}))
    monkeypatch.setenv("SPICEMCP_CONFIG", str(cfg_file))
    config = load_config()
    assert config.session_ttl_minutes == 7

def test_explicit_path_takes_precedence_over_env_var(tmp_path, monkeypatch):
    env_file = tmp_path / "env.json"
    env_file.write_text(json.dumps({"session_ttl_minutes": 99}))
    monkeypatch.setenv("SPICEMCP_CONFIG", str(env_file))
    explicit_file = tmp_path / "explicit.json"
    explicit_file.write_text(json.dumps({"session_ttl_minutes": 5}))
    config = load_config(path=explicit_file)
    assert config.session_ttl_minutes == 5


# ---------------------------------------------------------------------------
# apply_config_to_backends
# ---------------------------------------------------------------------------

def test_apply_config_wires_image_to_backends(tmp_path):
    from spicemcp.backends.docker_ltspice import DockerLTspice
    from spicemcp.backends.docker_ngspice import DockerNGspice
    from spicemcp.config import apply_config_to_backends

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "simulators": {
            "ltspice": {"image": "custom/ltspice:test"},
            "ngspice": {"image": "custom/ngspice:test"},
        }
    }))
    config = load_config(path=cfg_file)
    apply_config_to_backends(config)
    assert DockerLTspice.IMAGE == "custom/ltspice:test"
    assert DockerNGspice.IMAGE == "custom/ngspice:test"

def test_apply_config_wires_model_mounts(tmp_path):
    from spicemcp.backends.docker_ltspice import DockerLTspice
    from spicemcp.config import apply_config_to_backends, SpiceMCPConfig

    dir0 = tmp_path / "models0"
    dir0.mkdir()
    config = SpiceMCPConfig(model_dirs=[dir0])
    apply_config_to_backends(config)
    assert len(DockerLTspice._model_mounts) == 1
    assert DockerLTspice._model_mounts[0]["host"] == str(dir0)
    assert DockerLTspice._model_mounts[0]["container"] == "/models/user_0"
