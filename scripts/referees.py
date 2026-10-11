"""Running the PSG referee, and reading and writing write streams.

The referee is a C program built from the pinned die-derived source by
``sh validation/build_referees.sh`` into ``reference/build-referees/`` (ignored):

* ``psg_ref`` -- Nuked-PSG (the PSG of the YM7101 VDP, from its die)

It takes a binary event file of ``{u64 clock; u8 data; u8 pad}`` records, where
``clock`` counts input clocks after power-on and a write is applied before the clock
it names, and writes the four attenuations at every clock. The same event file is
how a board hands this repository a write stream (``scripts/export_board_streams.py``).
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFEREES = ROOT / "reference" / "build-referees"

EVENT = struct.Struct("<QBB")

#: Two of these running at once in the same directory -- two pytest workers, a run
#: beside a test -- must not write each other's event and output files, so every
#: name carries the process id.
_PID = os.getpid()


def referee(name: str) -> Path:
    path = REFEREES / name
    if not path.exists():
        raise SystemExit(
            f"{path} is missing: run `python scripts/fetch_references.py` and "
            "`sh validation/build_referees.sh` first"
        )
    return path


def write_events(path: Path, events: list[tuple[int, int]]) -> None:
    """``(clock, data)`` records, in order, into an event file."""
    with path.open("wb") as handle:
        for clock, data in events:
            handle.write(EVENT.pack(clock, data & 0xFF, 0))


def read_events(path: Path) -> list[tuple[int, int]]:
    """An event file's ``(clock, data)`` records, in file order."""
    raw = path.read_bytes()
    if len(raw) % EVENT.size:
        raise ValueError(f"{path}: not a whole number of {EVENT.size}-byte records")
    return [(clock, data) for clock, data, _pad in EVENT.iter_unpack(raw)]


def run_psg(
    events: list[tuple[int, int]], clocks: int, tmp: Path, *, every: int = 1
) -> list[tuple[int, int, int, int]]:
    """Nuked-PSG over ``clocks`` input clocks: the four attenuations (tone 1-3, noise)
    each channel drives, at every ``every``-th clock."""
    event_file, out_file = tmp / f"psg-events-{_PID}.bin", tmp / f"psg-out-{_PID}.bin"
    write_events(event_file, events)
    result = subprocess.run(
        [str(referee("psg_ref")), str(event_file), str(out_file), str(clocks), str(every)],
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode(errors="replace"))
        raise SystemExit(f"psg_ref failed ({result.returncode})")
    raw = out_file.read_bytes()
    event_file.unlink()
    out_file.unlink()
    # Each record is {u16 attenuations; i16 level}; the level is Nuked's analogue
    # output on its own curve and is not compared (docs/validation.md).
    return [
        ((word >> 12) & 15, (word >> 8) & 15, (word >> 4) & 15, word & 15)
        for word, _level in struct.iter_unpack("<Hh", raw)
    ]
