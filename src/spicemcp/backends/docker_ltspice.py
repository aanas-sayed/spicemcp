"""DockerLTspice -- spicelib Simulator subclass that runs LTspice inside Docker."""

from __future__ import annotations

import subprocess
from pathlib import Path

from spicelib.sim.simulator import Simulator, SpiceSimulatorError, run_function


class DockerLTspice(Simulator):
    """Runs LTspice inside a Docker container with full security isolation.

    Security flags applied on every run: --network=none, --read-only,
    --cap-drop=ALL, --security-opt=no-new-privileges, --pids-limit=256.
    These are non-negotiable (D-03) and cannot be overridden via config.
    """

    IMAGE: str = "aanas-sayed/docker-ltspice:latest"
    spice_exe: list[str] = ["docker"]
    process_name: str = "docker"
    _model_mounts: list[dict] = []

    @classmethod
    def valid_switch(cls, switch: str, path: str = "") -> list:
        return []

    @classmethod
    def run(
        cls,
        netlist_file,
        cmd_line_switches=None,
        timeout=None,
        stdout=None,
        stderr=None,
        cwd=None,
        exe_log=False,
    ) -> int:
        if not cls.is_available():
            raise SpiceSimulatorError(
                f"Docker image '{cls.IMAGE}' not found."
                f" Pull it with: docker pull {cls.IMAGE}"
            )

        netlist_file = Path(netlist_file)
        work_dir = netlist_file.parent
        filename = netlist_file.name

        cmd = [
            "docker", "run", "--rm",
            "--read-only",
            "--tmpfs", "/tmp:size=512m",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=2g", "--cpus=2",
            "--pids-limit=256",
            "--user=1000:1000",
            "-v", f"{work_dir}:/sim:rw",
        ]

        for mount in cls._model_mounts:
            cmd.extend(["-v", f"{mount['host']}:{mount['container']}:ro"])

        cmd.extend([cls.IMAGE, "wine", "LTspice.exe", "-b", f"/sim/{filename}"])

        return run_function(cmd, timeout=timeout, stdout=stdout, stderr=stderr)

    @classmethod
    def is_available(cls) -> bool:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", cls.IMAGE],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
