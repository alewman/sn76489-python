"""The every-clock comparison with Nuked-PSG (scripts/run_psg_compare.py).

Needs the referee: ``python scripts/fetch_references.py`` then
``sh validation/build_referees.sh``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFEREE = ROOT / "reference" / "build-referees" / "psg_ref"

pytestmark = [
    pytest.mark.referee,
    pytest.mark.skipif(not REFEREE.exists(), reason="run `sh validation/build_referees.sh`"),
]


def test_the_synthetic_streams_match_nuked_psg_at_every_clock():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_psg_compare.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "6 streams" in result.stdout
    assert ", 0 not identical" in result.stdout
