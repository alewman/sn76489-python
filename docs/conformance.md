# Conformance: proving another core is the same chip

This page is for someone writing an SN76489 core in another language who wants to
use this one as the reference. It covers what "the same chip" means here, the
manifest and trace formats, and what a port may claim after each rung. The tooling is
`sn76489_python.conformance`. The shape is the family's, after z80-python's,
m68000-python's and ym2612-python's kits.

## What must match

At every input clock:

- the **four attenuations** being driven (tone 1, 2, 3, noise), exactly as
  `attenuations()` returns them, including the test bit's effect;
- the **stereo** register, on the Game Gear variant.

The output holds between clocks, so the trace records only the clocks where it
changes, which is the same as recording every clock.

Not in the trace: the `levels` curves and the stereo routing inside `take_samples()`.
A port copies them as data ([contract.md](contract.md)); the seeded faults show the
examples alone do not catch a wrong curve or swapped sides (validation.md).

## The manifest

```json
{
  "version": 1,
  "name": "back-to-back-ym7101",
  "variant": "ym7101",
  "clocks": 10645,
  "events": [
    {"t": 40, "kind": "write", "data": 144},
    {"t": 47, "kind": "stereo", "data": 240},
    {"t": 54, "kind": "test", "data": 1}
  ]
}
```

| Key | Meaning |
| --- | --- |
| `variant` | `sn76489an`, `sega-vdp`, `game-gear` or `ym7101`. |
| `clocks` | Run to this many input clocks after power-on. |
| `events` | In clock order. Before an event at `t` the chip is run to `t` clocks; events at the same `t` are applied in order. `write` is the data port, `stereo` the Game Gear's port $06, `test` the three test bits. |

## The trace

Plain text, one record per line:

```text
# sn76489-trace 1
# back-to-back-ym7101 ym7101
A 0 15 15 15 15 255          before the first clock: a1 a2 a3 noise stereo
A 41 0 15 15 15 255          after clock 41, which changed the output
# end 10645 clocks 665 samples 115 writes
```

The header line names the format version; a trace of another version is refused
rather than misread. Lines starting `#` other than the header are comments, but they
are compared too, so a port writes them exactly. A port writes its trace in this
form and runs:

```text
python -m sn76489_python.conformance diff manifest.json port.trace
```

which reports `traces are identical` (exit 0) or the first differing line with both
versions (exit 1). `python -m sn76489_python.conformance trace manifest.json` writes
the reference trace.

## The examples

`examples/conformance/` holds ten manifests with their reference traces, written by
`scripts/make_examples.py`. `tests/test_conformance.py` checks two things. First,
that this chip still writes every trace. Second, with the referee built, that the
four examples Nuked-PSG can model (the YM7101 variant, data-port writes only) agree
with it at every clock. Those examples are therefore referee-checked, not just this
chip's say-so.

| Manifest | Aimed at |
| --- | --- |
| `random-walk-ym7101`, `random-walk-sega-vdp`, `random-walk-sn76489an` | every register, writes 1 to 600 clocks apart, so writes land on every phase of the rotation |
| `back-to-back-ym7101` | the write pipeline: writes one clock apart at each of the 16 clocks of a rotation, then a write on every clock |
| `low-periods-ym7101`, `low-periods-sega-vdp` | tone periods 0, 1 and 2 with volume steps, the sample-playback idiom, where the variants differ |
| `noise-ym7101`, `noise-sn76489an` | all eight noise settings, tone 3 as the clock at three periods; the two register widths |
| `stereo-game-gear` | the Game Gear's enables over eleven patterns |
| `test-bits-ym7101` | the test bits |

## Certification ladder for a port

| Rung | What | Claim after it |
| --- | --- | --- |
| 1 | The `levels` tables equal [contract.md](contract.md)'s | the analogue data is the chip's |
| 2 | Every example in `examples/conformance/` diffs identical | the engine and the variants, on the examples |
| 3 | The six synthetic streams of `scripts/run_psg_compare.py` as manifests, identical | equivalent to this core over the synthetic streams, and therefore equal to Nuked-PSG on them |
| 4 | The exported board streams (scripts/export_board_streams.py) as manifests, identical | equivalent on real sound drivers' writes |

Rung 3 and up do not need a port to talk to the referee. Equivalence to this core
and this core's equality to Nuked-PSG ([validation.md](validation.md)) compose.

## What this does not cover

- The **analogue path**: filtering, mixing, resampling. Those are the board's.
- **Bus timing**: when a CPU's write reaches the chip is the host's.
