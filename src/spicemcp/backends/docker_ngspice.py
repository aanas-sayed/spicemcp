"""DockerNGspice -- spicelib Simulator subclass that runs ngspice inside Docker."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from spicelib.sim.simulator import Simulator, SpiceSimulatorError, run_function


def _host_user() -> str | None:
    """Return 'uid:gid' of the host process, or None on platforms without getuid."""
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return f"{os.getuid()}:{os.getgid()}"
    return None


class DockerNGspice(Simulator):
    """Runs ngspice inside a Docker container with full security isolation.

    Security flags and the .control block risk are both mitigated: the sanitizer
    blocks .control blocks in the netlist (D-01), and --network=none plus
    --cap-drop=ALL provide defence-in-depth at the container level (D-03).
    """

    IMAGE: str = "aanas0sayed/docker-ngspice:latest"
    spice_exe: list[str] = ["docker"]
    process_name: str = "docker"
    _model_mounts: list[dict] = []
    _compatibility_mode: str = "kiltpsa"

    @classmethod
    def valid_switch(cls, switch: str, parameter: str = "") -> list:
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
                f"Docker image '{cls.IMAGE}' not found. Pull it with: docker pull {cls.IMAGE}"
            )

        netlist_file = Path(netlist_file)
        work_dir = netlist_file.parent
        filename = netlist_file.name
        stem = netlist_file.stem

        cmd = [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--tmpfs",
            "/tmp:size=512m",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=2g",
            "--cpus=2",
            "--pids-limit=256",
            "-v",
            f"{work_dir}:/sim:rw",
        ]

        # Match container uid to host user so output files are owned correctly
        # and we can read/write the bind mount under --cap-drop=ALL.
        host_user = _host_user()
        if host_user is not None:
            cmd.extend([f"--user={host_user}"])

        for mount in cls._model_mounts:
            cmd.extend(["-v", f"{mount['host']}:{mount['container']}:ro"])

        ngspice_cmd = []
        if cls._compatibility_mode:
            ngspice_cmd.extend(["-D", f"ngbehavior={cls._compatibility_mode}"])
        ngspice_cmd.extend(
            [
                "-b",
                "-o",
                f"/sim/{stem}.log",
                "-r",
                f"/sim/{stem}.raw",
                f"/sim/{filename}",
            ]
        )

        cmd.extend([cls.IMAGE] + ngspice_cmd)

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
