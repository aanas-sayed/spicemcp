"""Configuration loading for SpiceMCP."""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _default_ltspice_image() -> str:
    # Apple Silicon Macs need the macos-latest tag (pinned to Wine 9.0).
    # Wine 10+ aborts with an anon_mmap_fixed assertion failure under QEMU
    # user-mode emulation on 16 KB page-size hosts. See ARCHITECTURE.md.
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "aanas-sayed/docker-ltspice:macos-latest"
    return "aanas-sayed/docker-ltspice:latest"


@dataclass
class SimulatorConfig:
    backend: str = "docker"
    image: str | None = None
    executable: str | None = None
    timeout_s: int = 300
    memory_limit: str = "2g"
    cpu_limit: int = 2


@dataclass
class SpiceMCPConfig:
    ltspice: SimulatorConfig = field(
        default_factory=lambda: SimulatorConfig(image=_default_ltspice_image())
    )
    ngspice: SimulatorConfig = field(
        default_factory=lambda: SimulatorConfig(
            image="aanas-sayed/docker-ngspice:latest"
        )
    )
    model_dirs: list[Path] = field(default_factory=list)
    session_ttl_minutes: int = 10
    max_raw_size_mb: int = 200
    max_sessions: int = 10


def _parse_sim_config(data: dict[str, Any], base: SimulatorConfig) -> SimulatorConfig:
    return SimulatorConfig(
        backend=data.get("backend", base.backend),
        image=data.get("image", base.image),
        executable=data.get("executable", base.executable),
        timeout_s=int(data.get("timeout_s", base.timeout_s)),
        memory_limit=data.get("memory_limit", base.memory_limit),
        cpu_limit=int(data.get("cpu_limit", base.cpu_limit)),
    )


def load_config(path: Path | None = None) -> SpiceMCPConfig:
    """Load config from a JSON file.

    Search order when path is None:
      1. SPICEMCP_CONFIG environment variable
      2. ~/.config/spicemcp/config.json
      3. Built-in defaults (returns SpiceMCPConfig() unchanged)
    """
    defaults = SpiceMCPConfig()

    if path is None:
        env_path = os.environ.get("SPICEMCP_CONFIG")
        if env_path:
            path = Path(env_path)
        else:
            path = Path.home() / ".config" / "spicemcp" / "config.json"

    if not path.exists():
        return defaults

    with open(path) as f:
        data = json.load(f)

    sims = data.get("simulators", {})
    ltspice_cfg = _parse_sim_config(sims.get("ltspice", {}), defaults.ltspice)
    ngspice_cfg = _parse_sim_config(sims.get("ngspice", {}), defaults.ngspice)

    # Local overrides take precedence over simulators block
    for name, cfg_ref in (("ltspice", ltspice_cfg), ("ngspice", ngspice_cfg)):
        override = data.get("overrides", {}).get(name)
        if override:
            if name == "ltspice":
                ltspice_cfg = _parse_sim_config(override, cfg_ref)
            else:
                ngspice_cfg = _parse_sim_config(override, cfg_ref)

    return SpiceMCPConfig(
        ltspice=ltspice_cfg,
        ngspice=ngspice_cfg,
        model_dirs=[Path(d) for d in data.get("model_dirs", [])],
        session_ttl_minutes=int(
            data.get("session_ttl_minutes", defaults.session_ttl_minutes)
        ),
        max_raw_size_mb=int(data.get("max_raw_size_mb", defaults.max_raw_size_mb)),
        max_sessions=int(data.get("max_sessions", defaults.max_sessions)),
    )


def apply_config_to_backends(config: SpiceMCPConfig) -> None:
    """Wire image tags and model mount lists to the Docker backend classes."""
    from .backends.docker_ltspice import DockerLTspice
    from .backends.docker_ngspice import DockerNGspice

    mounts = [
        {"host": str(d), "container": f"/models/user_{i}"}
        for i, d in enumerate(config.model_dirs)
    ]

    if config.ltspice.image:
        DockerLTspice.IMAGE = config.ltspice.image
    DockerLTspice._model_mounts = mounts

    if config.ngspice.image:
        DockerNGspice.IMAGE = config.ngspice.image
    DockerNGspice._model_mounts = mounts
