"""End-to-end workflow test: buck-relevant LC filter compensation.

Exercises the full toolchain (simulate_netlist -> measure_signal -> plot_signals
-> modify_netlist -> simulate -> measure_signal) on a buck converter power
stage. Skipped if the ngspice Docker image is not available locally.
"""

from __future__ import annotations

import subprocess

import pytest

import spicemcp._globals as _globals
from spicemcp.backends.docker_ngspice import DockerNGspice
from spicemcp.config import SpiceMCPConfig
from spicemcp.core.session_manager import SessionManager
from spicemcp.tools.measure import measure_signal
from spicemcp.tools.netlist import modify_netlist
from spicemcp.tools.plot import plot_signals
from spicemcp.tools.simulate import simulate
from spicemcp.tools.simulate_netlist import simulate_netlist


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


needs_ngspice = pytest.mark.skipif(
    not _image_present(DockerNGspice.IMAGE),
    reason=f"Docker image {DockerNGspice.IMAGE!r} not present",
)


@pytest.fixture(autouse=True)
def fresh_globals():
    _globals.config = SpiceMCPConfig()
    _globals.manager = SessionManager(ttl_minutes=10, max_sessions=5, reaper_interval=9999)
    yield
    _globals.manager.stop()
    _globals.config = None
    _globals.manager = None


# Buck power stage AC model: vin -> L -> Cout (with ESR) -> load.
# This is the control-to-output plant of a voltage-mode buck (averaged).
# AC swept from 100 Hz to 1 MHz; we expect an LC resonance around
# fr = 1/(2*pi*sqrt(L*C)) ~= 5.03 kHz with L=10u, C=100u.
BUCK_PLANT_AC = """\
* Buck averaged power stage - control-to-output AC sweep
.param L=10u Cout=100u Resr=1m Rload=1.65
Vac sw 0 AC 1
L1 sw n1 {L}
Resr n1 out {Resr}
Cout out 0 {Cout}
Rload n1 0 {Rload}
.ac dec 50 100 1Meg
.end
"""


@needs_ngspice
def test_full_buck_compensation_workflow(tmp_path):
    """End-to-end: simulate -> measure -> plot -> modify -> simulate -> measure.

    Demonstrates the buck compensation workflow: an under-damped LC filter
    has a sharp resonance peak (low ESR). Adding ESR damps it. We confirm
    peak_gain_db drops after the modification.
    """
    # ── Step 1: simulate the under-damped power stage ───────────────────────
    r1 = simulate_netlist(simulator="ngspice", netlist=BUCK_PLANT_AC, timeout_s=60)
    assert r1["error"] is None
    assert r1["status"] == "completed"
    assert r1["domain"] == "ac"
    sid = r1["session_id"]
    assert sid is not None
    # Check we have AC outputs - ngspice writes V(<node>) lowercase
    sigs_lower = [s.lower() for s in r1["signals_available"]]
    assert any("v(out)" in s for s in sigs_lower)

    # Resolve canonical signal name (ngspice may use lowercase)
    out_name = next(s for s in r1["signals_available"] if s.lower() in ("v(out)",))

    # ── Step 2: measure the AC response (get peak gain and bandwidth) ───────
    r2 = measure_signal(
        sid,
        [{"signal": out_name, "operation": "stats"}],
    )
    assert r2["error"] is None
    stats_low_esr = r2["results"][0]
    assert stats_low_esr["domain"] == "ac"
    peak_low = stats_low_esr["peak_gain_db"]
    # Underdamped LC with Resr=1m has a sharp resonance well above 0 dB.
    assert peak_low > 10.0, f"expected sharp resonance peak, got {peak_low} dB"

    # ── Step 3: plot the Bode plot to PNG ───────────────────────────────────
    r3 = plot_signals(sid, signals=[out_name], title="Buck plant - low ESR", format="png")
    assert r3["error"] is None
    assert r3["domain"] == "ac"
    assert r3["image_uri"] is not None
    assert r3["image_uri"].startswith("file://")

    # ── Step 4: modify the netlist to add ESR damping ───────────────────────
    r4 = modify_netlist(sid, [{"type": "parameter", "ref": "Resr", "value": "0.5"}])
    assert r4["error"] is None
    assert len(r4["applied"]) == 1
    assert r4["simulation_required"] is True

    # ── Step 5: re-simulate the damped circuit ──────────────────────────────
    r5 = simulate(sid, timeout_s=60)
    assert r5["error"] is None
    assert r5["status"] == "completed"

    # ── Step 6: measure the damped response ─────────────────────────────────
    r6 = measure_signal(
        sid,
        [{"signal": out_name, "operation": "stats"}],
    )
    assert r6["error"] is None
    stats_damped = r6["results"][0]
    peak_damped = stats_damped["peak_gain_db"]

    # Damping should reduce the resonance peak significantly
    assert peak_damped < peak_low - 5, (
        f"expected damping to reduce peak by >5 dB; "
        f"low ESR: {peak_low:.2f} dB, damped: {peak_damped:.2f} dB"
    )

    # ── Step 7: plot the damped Bode in HTML format if plotly is available ──
    r7 = plot_signals(sid, signals=[out_name], title="Buck plant - damped", format="png")
    assert r7["error"] is None
    assert r7["image_uri"] is not None
