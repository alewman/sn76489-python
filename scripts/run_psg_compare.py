#!/usr/bin/env python
"""The PSG acceptance: this chip against Nuked-PSG, at every input clock.

    python scripts/run_psg_compare.py              # the synthetic streams
    python scripts/run_psg_compare.py --streams    # and the exported board streams

Nuked-PSG (``reference/src/Nuked-PSG``, die-derived, GPL-2.0, pinned at d15a168) is
the judge here: no hardware capture of a Sega PSG's digital state exists, and the
family's tier rule makes a die-derived model the judge where nothing hardware covers
the question.

What is compared is the chip's **digital** output: the four attenuations its four
channels are driving, at **every input clock**, not only at the one clock in sixteen a
sample is taken on. That is the whole state a listener could hear, sampled 16 times
more finely than the chip's own output rate. Nuked's analogue level is not compared,
because :data:`~sn76489_python.YM7101_LEVELS` is Nuked's own curve and comparing it
would be circular; the curve is checked in the unit tests instead.

The chip is run as :data:`~sn76489_python.YM7101_PSG`, the variant the die is. The
other variants share the engine and differ only in data (docs/contract.md).

The streams
-----------

* **synthetic**: two seeded random walks over all eight registers, every tone period,
  every noise setting, every attenuation.
* **--streams**: every event file in ``validation/streams/`` -- the writes a board's
  PSG received while running a cartridge, exported by
  ``scripts/export_board_streams.py`` (local; derived from ROMs).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import referees

from sn76489_python import SN76489, YM7101_PSG

ROOT = Path(__file__).resolve().parent.parent
STREAMS = ROOT / "validation" / "streams"


def stream_random(seed: int, count: int) -> list[tuple[int, int]]:
    """Latch and data bytes at random, over all eight registers."""
    rng = random.Random(seed)
    events: list[tuple[int, int]] = []
    clock = 40
    for _ in range(count):
        events.append((clock, 0x80 | (rng.randrange(8) << 4) | rng.randrange(16)))
        clock += rng.randrange(20, 400)
        if rng.random() < 0.6:
            events.append((clock, rng.randrange(0x40)))
            clock += rng.randrange(20, 400)
    return events


def stream_tones() -> list[tuple[int, int]]:
    """Every tone period from 0 to 1023 in steps, at full volume: the periods 0 and 1
    behave differently from the rest (sms-python's note from Maxim's wiki), and the
    counter's compare-then-reload makes a rewrite mid-period visible."""
    events: list[tuple[int, int]] = []
    clock = 40
    for channel in range(3):
        events.append((clock, 0x90 | (channel << 5)))
        clock += 32
    for period in list(range(0, 8)) + list(range(8, 1024, 37)):
        for channel in range(3):
            events.append((clock, 0x80 | (channel << 5) | (period & 0x0F)))
            clock += 32
            events.append((clock, (period >> 4) & 0x3F))
            clock += 32
        clock += 4000
    return events


def stream_noise() -> list[tuple[int, int]]:
    """All eight noise settings, white and periodic, each with tone 3 as its clock at
    a few periods, and the LFSR reset a write brings."""
    events: list[tuple[int, int]] = []
    clock = 40
    events.append((clock, 0xF0))  # noise at full volume
    clock += 32
    for period in (0x010, 0x080, 0x200):
        events.append((clock, 0xC0 | (period & 0x0F)))
        clock += 32
        events.append((clock, (period >> 4) & 0x3F))
        clock += 32
        for setting in range(8):
            events.append((clock, 0xE0 | setting))
            clock += 20000
    return events


def stream_volumes() -> list[tuple[int, int]]:
    """Every attenuation on every channel, with a tone running."""
    events: list[tuple[int, int]] = []
    clock = 40
    for channel in range(3):
        events.append((clock, 0x80 | (channel << 5) | 0x0A))
        clock += 32
        events.append((clock, 0x08 + channel))
        clock += 32
    events.append((clock, 0xE4))
    clock += 32
    for level in range(16):
        for channel in range(4):
            events.append((clock, 0x90 | (channel << 5) | level))
            clock += 600
        clock += 3000
    return events


def compare(name: str, events: list[tuple[int, int]], clocks: int, tmp: Path) -> bool:
    started = time.perf_counter()
    reference = referees.run_psg(events, clocks, tmp)
    psg = SN76489(YM7101_PSG)
    index = 0
    count = len(events)
    differing = 0
    first = None
    for clock in range(clocks):
        while index < count and events[index][0] <= clock:
            psg.write(events[index][1])
            index += 1
        psg.run(1)
        mine = psg.attenuations()
        if mine != reference[clock]:
            differing += 1
            if first is None:
                first = (clock, reference[clock], mine)
    wall = time.perf_counter() - started
    if differing == 0:
        print(f"  {clocks:>12,} input clocks  IDENTICAL (four attenuations)  {wall:.1f} s")
        return True
    print(
        f"  {differing:,} of {clocks:,} input clocks differ, first at {first[0]:,} "
        f"(referee {first[1]}, core {first[2]})"
    )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--streams", action="store_true", help="also validation/streams/")
    parser.add_argument("--only", help="run only the streams whose name contains this")
    parser.add_argument("--tail", type=int, default=16 * 2000)
    args = parser.parse_args(argv)

    streams = [
        ("random (seed 1, 3000 latches)", stream_random(1, 3000)),
        ("random (seed 2, 3000 latches)", stream_random(2, 3000)),
        ("every tone period", stream_tones()),
        ("every noise setting", stream_noise()),
        ("every attenuation", stream_volumes()),
    ]
    if args.streams:
        for path in sorted(STREAMS.glob("*.bin")):
            meta = json.loads(path.with_suffix(".json").read_text())
            events = referees.read_events(path)
            label = f"{path.stem} ({meta['sha256'][:16]}, {meta['frames']} frames)"
            streams.append((label, events))
    if args.only:
        streams = [(name, events) for name, events in streams if args.only in name]

    failures = 0
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, events in streams:
            clocks = (events[-1][0] if events else 0) + args.tail
            total += clocks
            print(f"{name}: {len(events):,} writes, {clocks:,} input clocks")
            if not compare(name, events, clocks, Path(tmp)):
                failures += 1
    print(f"\n{len(streams)} streams, {total:,} input clocks, {failures} not identical")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
