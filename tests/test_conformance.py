"""The conformance kit: the examples still trace the same, and agree with Nuked-PSG."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from sn76489_python.conformance import (
    TRACE_HEADER,
    diff_traces,
    load_manifest,
    main,
    manifest_from_dict,
    trace_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "conformance"
MANIFESTS = sorted(EXAMPLES.glob("*.json"))
REFEREE = ROOT / "reference" / "build-referees" / "psg_ref"


def test_there_are_examples():
    assert len(MANIFESTS) == 10


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda path: path.stem)
def test_this_chip_still_writes_every_reference_trace(path):
    reference = path.with_suffix(".trace").read_text(encoding="utf-8").splitlines()
    assert diff_traces(reference, trace_manifest(load_manifest(path))) is None


def test_make_examples_is_reproducible():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_examples.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def per_clock(trace: list[str], clocks: int) -> list[tuple[int, int, int, int]]:
    """A trace's attenuations after each input clock, 1 to ``clocks``."""
    changes = {}
    for line in trace:
        if line.startswith("A "):
            fields = [int(field) for field in line.split()[1:]]
            changes[fields[0]] = tuple(fields[1:5])
    out, current = [], changes[0]
    for clock in range(1, clocks + 1):
        current = changes.get(clock, current)
        out.append(current)
    return out


#: The examples Nuked-PSG models: its variant, no stereo port, no test bits.
REFEREE_CHECKED = [
    path
    for path in MANIFESTS
    if json.loads(path.read_text())["variant"] == "ym7101"
    and all(event["kind"] == "write" for event in json.loads(path.read_text())["events"])
]


def test_most_ym7101_examples_are_referee_checked():
    assert len(REFEREE_CHECKED) == 4


@pytest.mark.referee
@pytest.mark.skipif(not REFEREE.exists(), reason="run `sh validation/build_referees.sh`")
@pytest.mark.parametrize("path", REFEREE_CHECKED, ids=lambda path: path.stem)
def test_the_example_agrees_with_nuked_psg_at_every_clock(path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import referees

    manifest = load_manifest(path)
    events = [(event.t, event.data) for event in manifest.events]
    with tempfile.TemporaryDirectory() as tmp:
        reference = referees.run_psg(events, manifest.clocks, Path(tmp))
    trace = path.with_suffix(".trace").read_text(encoding="utf-8").splitlines()
    assert per_clock(trace, manifest.clocks) == reference


# -- the format and the command line ---------------------------------------------------


def manifest(**overrides) -> dict:
    value = {
        "version": 1,
        "name": "tiny",
        "variant": "ym7101",
        "clocks": 400,
        "events": [
            {"t": 10, "kind": "write", "data": 0x90},
            {"t": 12, "kind": "write", "data": 0x81},
        ],
    }
    value.update(overrides)
    return value


def test_a_trace_starts_with_its_header_and_ends_with_the_count():
    lines = list(trace_manifest(manifest_from_dict(manifest())))
    assert lines[0] == TRACE_HEADER
    assert lines[1] == "# tiny ym7101"
    assert lines[2].startswith("A 0 ")
    assert lines[-1] == "# end 400 clocks 25 samples 2 writes"


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"variant": "ay-3-8910"},
        {"surprise": 1},
        {"events": [{"t": 5, "kind": "read"}]},
        {"events": [{"t": 5, "kind": "write", "data": 256}]},
        {"events": [{"t": 9, "kind": "write"}, {"t": 5, "kind": "write"}]},
        {"events": [{"t": 500, "kind": "write"}]},
    ],
)
def test_bad_manifests_are_refused(change):
    with pytest.raises((ValueError, TypeError)):
        manifest_from_dict(manifest(**change))


def test_diff_reports_identical_and_the_first_difference(tmp_path):
    path = tmp_path / "tiny.json"
    path.write_text(json.dumps(manifest()))
    good = tmp_path / "good.trace"
    assert main(["trace", str(path), "--out", str(good)]) == 0
    out = io.StringIO()
    assert main(["diff", str(path), str(good)], stdout=out) == 0
    assert "identical" in out.getvalue()

    lines = good.read_text().splitlines()
    lines[3] = lines[3].rsplit(" ", 1)[0] + " 0"  # a wrong stereo value
    bad = tmp_path / "bad.trace"
    bad.write_text("\n".join(lines) + "\n")
    out = io.StringIO()
    assert main(["diff", str(path), str(bad)], stdout=out) == 1
    assert "line 4" in out.getvalue()


def test_bad_input_exits_two(tmp_path):
    out = io.StringIO()
    assert main(["trace", str(tmp_path / "missing.json")], stdout=out) == 2
