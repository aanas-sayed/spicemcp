"""DockerLTspice -- spicelib Simulator subclass that runs LTspice inside Docker."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from spicelib.sim.simulator import Simulator, SpiceSimulatorError, run_function


def _default_ltspice_image() -> str:
    # Wine 10+ aborts under QEMU on 16 KB page-size hosts (Apple Silicon, Asahi).
    # macos-latest is pinned to Wine 9.0 which does not have this bug.
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "aanas0sayed/docker-ltspice:macos-latest"
    return "aanas0sayed/docker-ltspice:latest"


def _host_user() -> str | None:
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return f"{os.getuid()}:{os.getgid()}"
    return None


class DockerLTspice(Simulator):
    """Runs LTspice inside a Docker container with full security isolation.

    Security flags applied on every run: --network=none, --cap-drop=ALL,
    --security-opt=no-new-privileges, --pids-limit=256, plus --user matching
    the host uid:gid so output files end up owned by the host user.

    Relies on the docker-ltspice image's prefix-template design: the image
    runs as wineuser by default but copies its Wine prefix to /tmp/wine-prefix
    on every container start under the running uid, so any --user value works
    without CAP_DAC_OVERRIDE or CAP_CHOWN.

    --read-only is not used: Wine writes to its prefix during every run.
    """

    IMAGE: str = _default_ltspice_image()
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
                f"Docker image '{cls.IMAGE}' not found. Pull it with: docker pull {cls.IMAGE}"
            )

        netlist_file = Path(netlist_file)
        work_dir = netlist_file.parent
        filename = netlist_file.name

        cmd = [
            "docker",
            "run",
            "--rm",
            "--platform=linux/amd64",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=2g",
            "--cpus=2",
            "--pids-limit=256",
            "-v",
            f"{work_dir}:/sim:rw",
        ]

        host_user = _host_user()
        if host_user is not None:
            cmd.extend([f"--user={host_user}"])

        for mount in cls._model_mounts:
            cmd.extend(["-v", f"{mount['host']}:{mount['container']}:ro"])

        netlist_win = f"Z:\\sim\\{filename}"
        # The image's entrypoint sets $WINEPREFIX to /tmp/wine-prefix and primes
        # Xvfb. Use $WINEPREFIX to locate LTspice.exe - the image symlinks the
        # 1.7 GB install from the prefix to /opt/ltspice to keep the template small.
        bash_cmd = (
            f'timeout 120 wine "$WINEPREFIX/drive_c/Program Files/ADI/LTspice/LTspice.exe" '
            f'-b -run "{netlist_win}" || true; '
            f"wineserver --wait 2>/dev/null || true"
        )
        cmd.extend([cls.IMAGE, "/bin/bash", "-c", bash_cmd])

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
