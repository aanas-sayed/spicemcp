"""Integration test fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def world_accessible_tmp_path(tmp_path):
    """Make tmp_path 0o777 so Docker containers can read/write the bind mount.

    pytest's tmp_path is created with mode=0o700 (owner-only). Our Docker
    backends run with --cap-drop=ALL which removes CAP_DAC_OVERRIDE, so the
    container process (root or uid 1000) cannot traverse a 0o700 directory
    owned by the test runner's uid. 0o777 lets any uid read/write the mount.
    """
    os.chmod(tmp_path, 0o777)
