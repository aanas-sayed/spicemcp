"""Session-scoped raw file fixtures for analysis engine tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from spicelib import RawWrite, Trace


@pytest.fixture(scope="session")
def tran_raw(tmp_path_factory) -> Path:
    """TRAN raw file: 1kHz sine on V(out), R=1k so I(R1) = V/1000."""
    out = tmp_path_factory.mktemp("raw") / "tran.raw"
    t = np.linspace(0, 10e-3, 1001)  # 0-10ms, 1001 points
    v_out = np.sin(2 * np.pi * 1000 * t)  # 1V peak, 1kHz
    i_r1 = v_out / 1000.0  # 1k resistor

    rw = RawWrite(plot_name="Transient Analysis", fastacces=False)
    rw.add_trace(Trace("time", t, whattype="time"))
    rw.add_trace(Trace("V(out)", v_out, whattype="voltage"))
    rw.add_trace(Trace("I(R1)", i_r1, whattype="current"))
    rw.save(str(out))
    return out


@pytest.fixture(scope="session")
def ac_raw(tmp_path_factory) -> Path:
    """AC raw file: RC filter H(f) = 1/(1+j*2*pi*f*RC), R=1k C=1n -> fc~159kHz."""
    out = tmp_path_factory.mktemp("raw") / "ac.raw"
    freq = np.logspace(1, 7, 200)  # 10 Hz to 10 MHz
    rc = 1e3 * 1e-9  # 1us time constant
    h = 1.0 / (1.0 + 1j * 2 * np.pi * freq * rc)

    rw = RawWrite(plot_name="AC Analysis", fastacces=False)
    rw.add_trace(Trace("frequency", freq, whattype="frequency", numerical_type="complex"))
    rw.add_trace(Trace("V(out)", h, whattype="voltage", numerical_type="complex"))
    rw.save(str(out))
    return out
