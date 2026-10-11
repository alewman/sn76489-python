#!/usr/bin/env python
"""Write the conformance kit's example manifests and their reference traces.

    python scripts/make_examples.py           # write examples/conformance/
    python scripts/make_examples.py --check   # fail if any file would change

Each example aims at something a port could get wrong; docs/conformance.md lists
them. The seeds are fixed, so the files are reproducible byte for byte.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from sn76489_python.conformance import MANIFEST_SCHEMA_VERSION, load_manifest, trace_manifest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples" / "conformance"


def tone(channel: int, period: int) -> list[int]:
    """The latch byte and the data byte that set a tone period."""
    return [0x80 | (channel << 5) | (period & 0x0F), (period >> 4) & 0x3F]


def volume(channel: int, level: int) -> int:
    return 0x90 | (channel << 5) | level


def at(t: int, data: int, kind: str = "write") -> dict:
    return {"t": t, "kind": kind, "data": data}


def random_walk(seed: int, count: int) -> tuple[list[dict], int]:
    """Latch and data bytes at random over all eight registers, at random gaps
    including back-to-back clocks, so writes land on every phase of the rotation."""
    rng = random.Random(seed)
    events, t = [], 40
    for _ in range(count):
        events.append(at(t, 0x80 | (rng.randrange(8) << 4) | rng.randrange(16)))
        t += rng.choice((1, 2, 3, rng.randrange(4, 600)))
        if rng.random() < 0.6:
            events.append(at(t, rng.randrange(0x80)))
            t += rng.choice((1, 2, 3, rng.randrange(4, 600)))
    return events, t + 4000


def back_to_back() -> tuple[list[dict], int]:
    """The write pipeline: pairs of writes one clock apart, the second landing on each
    of the 16 clocks of a rotation in turn, and a write on every clock for a while."""
    events, t = [], 40
    for channel in range(3):
        events.append(at(t, volume(channel, 0)))
        t += 7
    for phase in range(16):
        start = t + phase
        events.append(at(start, tone(phase % 3, 0x20 + phase)[0]))
        events.append(at(start + 1, tone(phase % 3, 0x20 + phase)[1]))
        events.append(at(start + 2, volume(phase % 3, phase)))
        t = start + 400
    events.extend(at(t + k, 0x80 | ((k % 8) << 4) | (k % 16)) for k in range(64))
    return events, t + 64 + 4000


def low_periods() -> tuple[list[dict], int]:
    """Tone periods 0, 1 and 2 at full volume, the sample-playback idiom: the
    variants differ here (docs/contract.md)."""
    events, t = [], 40
    for channel in range(3):
        events.append(at(t, volume(channel, 0)))
        t += 5
    for period in (0, 1, 2, 1, 0):
        for channel in range(3):
            for byte in tone(channel, period):
                events.append(at(t, byte))
                t += 3
        for level in range(0, 16, 3):  # volume steps, as sample playback writes them
            events.append(at(t, volume(0, level)))
            t += 97
        t += 600
    return events, t + 2000


def noise_settings() -> tuple[list[dict], int]:
    """All eight noise settings with tone 3 as the clock at a few periods, long
    enough for periodic noise to come round."""
    events, t = [at(40, 0xF0)], 72
    for period in (0x000, 0x003, 0x040):
        for byte in tone(2, period):
            events.append(at(t, byte))
            t += 32
        for setting in range(8):
            events.append(at(t, 0xE0 | setting))
            t += 6000
    return events, t + 2000


def stereo_routing() -> tuple[list[dict], int]:
    """Every channel sounding, the Game Gear's enables swept over each bit pattern."""
    events, t = [], 40
    for channel, period in enumerate((0x011, 0x023, 0x035)):
        for byte in tone(channel, period):
            events.append(at(t, byte))
            t += 4
        events.append(at(t, volume(channel, channel * 2)))
        t += 4
    events.append(at(t, 0xE4))
    events.append(at(t, volume(3, 1)))
    t += 4
    for pattern in (0x00, 0xFF, 0x10, 0x01, 0x82, 0x28, 0xF0, 0x0F, 0x5A, 0xA5, 0xFF):
        events.append(at(t, pattern, "stereo"))
        t += 1500
    return events, t + 500


def test_bits() -> tuple[list[dict], int]:
    """The test bits: bit 0 forces every sign high, the others do nothing here."""
    events, t = [], 40
    for channel in range(4):
        events.append(at(t, volume(channel, 3 + channel)))
        t += 3
    for byte in tone(0, 0x100):
        events.append(at(t, byte))
        t += 3
    for bits in (1, 0, 2, 4, 6, 7, 0, 1, 0):
        events.append(at(t, bits, "test"))
        t += 777
    return events, t + 500


EXAMPLES = [
    ("random-walk-ym7101", "ym7101", lambda: random_walk(1, 600)),
    ("random-walk-sega-vdp", "sega-vdp", lambda: random_walk(2, 600)),
    ("random-walk-sn76489an", "sn76489an", lambda: random_walk(3, 600)),
    ("back-to-back-ym7101", "ym7101", back_to_back),
    ("low-periods-ym7101", "ym7101", low_periods),
    ("low-periods-sega-vdp", "sega-vdp", low_periods),
    ("noise-ym7101", "ym7101", noise_settings),
    ("noise-sn76489an", "sn76489an", noise_settings),
    ("stereo-game-gear", "game-gear", stereo_routing),
    ("test-bits-ym7101", "ym7101", test_bits),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if a file would change")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    changed = 0
    for name, variant, build in EXAMPLES:
        events, clocks = build()
        manifest = {
            "version": MANIFEST_SCHEMA_VERSION,
            "name": name,
            "variant": variant,
            "clocks": clocks,
            "events": events,
        }
        files = {OUT / f"{name}.json": json.dumps(manifest, indent=1) + "\n"}
        manifest_path = OUT / f"{name}.json"
        if not args.check:
            manifest_path.write_text(files[manifest_path], encoding="utf-8")
        trace = "\n".join(trace_manifest(load_manifest(manifest_path))) + "\n"
        files[OUT / f"{name}.trace"] = trace
        for path, text in files.items():
            old = path.read_text(encoding="utf-8") if path.exists() else None
            if old != text:
                changed += 1
                if args.check:
                    print(f"{path.relative_to(ROOT)}: would change")
                else:
                    path.write_text(text, encoding="utf-8")
        lines = trace.count("\n")
        print(f"{name}: {len(events)} events, {clocks:,} clocks, {lines:,} trace lines")
    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
