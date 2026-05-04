"""Integration tests that require Docker images to be present.

These tests are skipped automatically if the required image is not available
locally. Pull images with:

    docker compose --profile simulators pull   (from the docker/ directory)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spicemcp.backends.docker_ltspice import DockerLTspice
from spicemcp.backends.docker_ngspice import DockerNGspice


def _image_present(image: str) -> bool:
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_ltspice = pytest.mark.skipif(
    not _image_present(DockerLTspice.IMAGE),
    reason=f"Docker image {DockerLTspice.IMAGE!r} not present",
)

needs_ngspice = pytest.mark.skipif(
    not _image_present(DockerNGspice.IMAGE),
    reason=f"Docker image {DockerNGspice.IMAGE!r} not present",
)


RC_NETLIST = """\
RC filter -- integration test
V1 in 0 AC 1 SIN(0 1 1k)
R1 in out 1k
C1 out 0 1n
.ac dec 10 1 10Meg
.end
"""

OP_NETLIST = """\
Simple op-point -- integration test
V1 in 0 DC 1
R1 in out 1k
R2 out 0 1k
.op
.end
"""


@needs_ltspice
def test_ltspice_ac_simulation_produces_raw_file(tmp_path):
    netlist = tmp_path / "rc.net"
    netlist.write_text(RC_NETLIST)
    rc = DockerLTspice.run(netlist, timeout=60)
    assert rc == 0
    raw_files = list(tmp_path.glob("*.raw"))
    assert raw_files, "LTspice did not produce a .raw file"


@needs_ngspice
def test_ngspice_ac_simulation_produces_raw_file(tmp_path):
    netlist = tmp_path / "rc.net"
    netlist.write_text(RC_NETLIST)
    rc = DockerNGspice.run(netlist, timeout=60)
    assert rc == 0
    raw_files = list(tmp_path.glob("*.raw"))
    assert raw_files, "ngspice did not produce a .raw file"


@needs_ngspice
def test_ngspice_produces_log_file(tmp_path):
    netlist = tmp_path / "rc.net"
    netlist.write_text(RC_NETLIST)
    DockerNGspice.run(netlist, timeout=60)
    log_files = list(tmp_path.glob("*.log"))
    assert log_files, "ngspice did not produce a .log file"
