"""The conformance kit: what a port of this chip must reproduce, clock by clock.

Two entry points, also ``python -m sn76489_python.conformance`` (or
``sn76489-conformance``):

* :func:`trace_manifest` runs a manifest on this chip and yields the reference trace:
  a line at every input clock on which the chip's output changes.
* :func:`diff_traces` compares an external trace with the reference and returns the
  first difference, or ``None``.

The manifest and trace formats are docs/conformance.md. The module depends only on the
standard library and :mod:`sn76489_python.chip`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TextIO

from sn76489_python.chip import (
    CLOCKS_PER_SAMPLE,
    GAME_GEAR_PSG,
    SEGA_VDP_PSG,
    SN76489,
    SN76489AN,
    YM7101_PSG,
    PSGVariant,
)

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "TRACE_HEADER",
    "VARIANTS",
    "Event",
    "Manifest",
    "TraceDifference",
    "diff_traces",
    "load_manifest",
    "main",
    "manifest_from_dict",
    "trace_manifest",
]

MANIFEST_SCHEMA_VERSION = 1
#: The first line of every trace, so a trace of another version is refused, not misread.
TRACE_HEADER = "# sn76489-trace 1"

VARIANTS: dict[str, PSGVariant] = {
    "sn76489an": SN76489AN,
    "sega-vdp": SEGA_VDP_PSG,
    "game-gear": GAME_GEAR_PSG,
    "ym7101": YM7101_PSG,
}
KINDS = ("write", "stereo", "test")


@dataclass(frozen=True)
class Event:
    """One thing the host does to the chip, before input clock ``t``.

    ``write``: ``write(data)``, the data port. ``stereo``: ``write_stereo(data)``, the
    Game Gear's port $06. ``test``: ``write_test(data)``, the three test bits. Before
    an event the chip is run to ``t`` clocks after power-on; the events at one ``t``
    are applied in order.
    """

    t: int
    kind: str
    data: int = 0

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}")
        if self.t < 0 or not 0 <= self.data <= 0xFF:
            raise ValueError(f"event out of range: {self}")


@dataclass(frozen=True)
class Manifest:
    """A run: the variant, the events in clock order, and how many clocks to run."""

    name: str
    variant: str
    events: tuple[Event, ...]
    clocks: int

    def __post_init__(self) -> None:
        if self.variant not in VARIANTS:
            raise ValueError(f"unknown variant {self.variant!r} ({', '.join(VARIANTS)})")
        if any(b.t < a.t for a, b in pairwise(self.events)):
            raise ValueError("events must be in clock order")
        if self.events and self.events[-1].t > self.clocks:
            raise ValueError("an event falls after the end of the run")


@dataclass(frozen=True)
class TraceDifference:
    """The first line where two traces differ (1-based), and both lines."""

    line: int
    reference: str
    external: str

    def __str__(self) -> str:
        return (
            f"traces differ at line {self.line}\n"
            f"  reference: {self.reference}\n  external:  {self.external}"
        )


def trace_manifest(manifest: Manifest) -> Iterator[str]:
    """Run ``manifest`` on this chip, yielding the trace's lines (without newlines).

    ``A clock a1 a2 a3 an stereo`` after input clock ``clock`` (counted from 1 after
    power-on) whenever the four attenuations being driven or the stereo enables differ
    from the previous line's, and once before the first clock (``clock`` 0). Since the
    output holds between lines, two traces with the same lines have the same output at
    every input clock; a sample is the output at every 16th.
    """
    chip = SN76489(VARIANTS[manifest.variant])
    yield TRACE_HEADER
    yield f"# {manifest.name} {manifest.variant}"
    last = (*chip.attenuations(), chip.stereo)
    yield "A 0 {} {} {} {} {}".format(*last)
    writes = 0

    def advance(t: int) -> Iterator[str]:
        nonlocal last
        while chip.clock < t:
            chip.run(1)
            now = (*chip.attenuations(), chip.stereo)
            if now != last:
                last = now
                yield "A {} {} {} {} {} {}".format(chip.clock, *now)

    for event in manifest.events:
        yield from advance(event.t)
        if event.kind == "write":
            chip.write(event.data)
            writes += 1
        elif event.kind == "stereo":
            chip.write_stereo(event.data)
        else:
            chip.write_test(event.data)
    yield from advance(manifest.clocks)
    samples = chip.clock // CLOCKS_PER_SAMPLE
    yield f"# end {chip.clock} clocks {samples} samples {writes} writes"


def diff_traces(reference: Iterable[str], external: Iterable[str]) -> TraceDifference | None:
    """The first line where ``external`` differs from ``reference``, or ``None``."""
    line = 0
    ref_iter, ext_iter = iter(reference), iter(external)
    while True:
        line += 1
        ref = next(ref_iter, None)
        ext = next(ext_iter, None)
        if ref is None and ext is None:
            return None
        ref = None if ref is None else ref.rstrip("\n")
        ext = None if ext is None else ext.rstrip("\n")
        if ref != ext:
            return TraceDifference(line, ref or "(end of trace)", ext or "(end of trace)")


def manifest_from_dict(value: object) -> Manifest:
    """A manifest from its JSON form (docs/conformance.md), strictly checked."""
    if not isinstance(value, dict):
        raise ValueError("a manifest is a JSON object")
    allowed = {"version", "name", "variant", "events", "clocks"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown manifest keys: {sorted(unknown)}")
    if value.get("version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest version {value.get('version')!r}")
    events = []
    for index, item in enumerate(value.get("events", [])):
        if not isinstance(item, dict):
            raise ValueError(f"event {index} is not an object")
        extra = set(item) - {"t", "kind", "data"}
        if extra:
            raise ValueError(f"event {index}: unknown keys {sorted(extra)}")
        events.append(Event(**item))
    return Manifest(
        name=str(value["name"]),
        variant=str(value["variant"]),
        events=tuple(events),
        clocks=int(value["clocks"]),
    )


def load_manifest(path: str | Path) -> Manifest:
    return manifest_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """``trace`` writes the reference trace; ``diff`` reports the first difference.

    Exit status: 0 on success or equal traces, 1 on a difference, 2 on bad input.
    """
    out = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="sn76489-conformance", description=main.__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    trace_cmd = commands.add_parser("trace", help="write the reference trace of a manifest")
    trace_cmd.add_argument("manifest")
    trace_cmd.add_argument("--out", help="file to write (default: stdout)")
    diff_cmd = commands.add_parser("diff", help="compare an external trace with the reference")
    diff_cmd.add_argument("manifest")
    diff_cmd.add_argument("trace", help="trace path, or '-' for stdin")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=out)
        return 2
    if args.command == "trace":
        lines = trace_manifest(manifest)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line + "\n")
        else:
            for line in lines:
                out.write(line + "\n")
        return 0
    try:
        handle = sys.stdin if args.trace == "-" else open(args.trace, encoding="utf-8")  # noqa: SIM115
    except OSError as exc:
        print(f"error: {exc}", file=out)
        return 2
    with handle:
        difference = diff_traces(trace_manifest(manifest), handle)
    if difference is None:
        print(f"{manifest.name}: traces are identical", file=out)
        return 0
    print(f"{manifest.name}: {difference}", file=out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
