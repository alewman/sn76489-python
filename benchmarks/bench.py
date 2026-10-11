#!/usr/bin/env python
"""How fast this chip runs: input clocks per second, and the fraction of real time.

    python benchmarks/bench.py [--seconds 2] [--repeat 3]

Runs the first ``--seconds`` of emulated time of the seed-1 random walk
(scripts/run_psg_compare.py) through ``run()``, as a board drives the chip: run to
each write, write, and at the end take the samples. Real time is 3,579,545 input
clocks a second (an NTSC Master System's or Mega Drive's PSG). Reports the best of
``--repeat`` runs, since the machine is shared.
"""

from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_psg_compare

from sn76489_python import SN76489, VARIANTS

REAL_TIME = 3_579_545


def run(events, clocks: int, variant) -> float:
    chip = SN76489(variant)
    started = time.perf_counter()
    for clock, data in events:
        if clock >= clocks:
            break
        chip.run(clock - chip.clock)
        chip.write(data)
    chip.run(clocks - chip.clock)
    chip.take_samples()
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    clocks = int(REAL_TIME * args.seconds)
    events = run_psg_compare.stream_random(1, 40_000)
    print(f"{platform.python_implementation()} {platform.python_version()}, {clocks:,} clocks")
    for name in ("YM7101", "Game Gear"):
        best = min(run(events, clocks, VARIANTS[name]) for _ in range(args.repeat))
        rate = clocks / best
        print(
            f"  {name:10s} {rate:12,.0f} clocks/s  {rate / REAL_TIME:6.3f}x real time"
            f"  ({best:.2f} s)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
