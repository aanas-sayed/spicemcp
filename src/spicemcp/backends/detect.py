"""Docker-in-Docker detection."""

from __future__ import annotations

from pathlib import Path


class ConfigError(Exception):
    pass


def is_running_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(errors="ignore")
        return "docker" in cgroup or "containerd" in cgroup
    except OSError:
        return False


def check_docker_socket() -> None:
    """Raise ConfigError if we are inside a container but the Docker socket is missing."""
    if is_running_in_container():
        socket = Path("/var/run/docker.sock")
        if not socket.exists():
            raise ConfigError(
                "SpiceMCP is running inside a container but the Docker socket is not"
                " mounted. Run with: -v /var/run/docker.sock:/var/run/docker.sock"
            )
