# sn76489-python

A readable, pure-Python reference core of the **SN76489** programmable sound
generator, in the four forms Sega used: the discrete TI **SN76489AN** of the
SG-1000, the PSG inside the **Master System's** VDPs, the **Game Gear's** with its
stereo port, and the PSG block of the **Mega Drive's YM7101**. It covers three tone
channels, the noise channel with both register widths, the attenuators, the Game
Gear's stereo enables and the test bits.

It is not a programmer's-model PSG. It is the chip's **sequencer**: an internal clock
at a quarter of the input clock, two phases, one of four counters stepped per phase
pair, and a write that reaches its register a clock later. At **every input clock**
of the 19 streams below, the four attenuations it drives equal **Nuked-PSG**, a
transcription of the YM7101's die. What differs between the parts is data on a
`PSGVariant`, not branches.

It is a chip in the family's shape (chips are cores, boards compose cores), beside
[z80-python](https://github.com/alewman/z80-python),
[m68000-python](https://github.com/alewman/m68000-python) and
[ym2612-python](https://github.com/alewman/ym2612-python). It was extracted, with
both histories, from [megadrive-python](https://github.com/alewman/megadrive-python)
(the engine) and [sms-python](https://github.com/alewman/sms-python) (the variants),
whose two copies had diverged. Both boards now depend on it at a pinned commit.

## Validation

| What | Result | Tier |
| --- | --- | --- |
| The four attenuations at every input clock against Nuked-PSG @ d15a168: 6 synthetic streams, 5 Mega Drive, 5 Master System, 2 Game Gear and 1 SG-1000 cartridge | **633,262,572 input clocks, 0 different** | die-derived (the judge) |
| The YM7101's curve against the die's | all 16 values equal | die-derived |
| The SN76489AN's noise against the wiki's bit pattern | all 32,767 bits | illustration |
| 23 seeded faults | 23 caught (21 by the conformance examples alone) | not an oracle |

What each result supports, and how strongly, is [docs/claims.md](docs/claims.md).
The runs, with commands and commits, are [docs/validation.md](docs/validation.md).

## Install

```text
git clone https://github.com/alewman/sn76489-python
cd sn76489-python
python -m pip install -e ".[dev]"
```

Python 3.11 or newer (the newest PyPy supports). No dependencies.

## Minimal host

```python
from sn76489_python import SN76489, YM7101_PSG

CLOCK = 3_579_545  # the PSG's input clock on an NTSC Master System or Mega Drive

chip = SN76489(YM7101_PSG)
for byte in (0x8E, 0x0F, 0x90):  # tone 1 period $0FE (440 Hz), attenuation 0
    chip.write(byte)
    chip.run(32)  # a write reaches its register on the next clock; leave a few

chip.run(CLOCK // 10)  # a tenth of a second
samples = chip.take_samples()  # [(left, right), ...] at CLOCK / 16 = 223,722 Hz
```

The contract (the port, the time unit, the variants, the outputs, what belongs to
the board) is [docs/contract.md](docs/contract.md). In short:
- `run(clocks)` takes **input clocks**; a sample is 16 of them.
- `write(value)` is the data port, `write_stereo(value)` the Game Gear's port $06,
  `write_test(bits)` the three test bits.
- `attenuations()` is the digital output now, and `take_samples()` returns the
  finished samples as `(left, right)` levels.

## For a port: the conformance kit

```text
python -m sn76489_python.conformance trace examples/conformance/back-to-back-ym7101.json
python -m sn76489_python.conformance diff examples/conformance/back-to-back-ym7101.json port.trace
```

A manifest names the variant and the timed writes. The trace has a line at every
input clock where the output changes. Ten example manifests ship with reference
traces, four of them checked against Nuked-PSG by the tests. See
[docs/conformance.md](docs/conformance.md).

## Reproducing

```text
python -m pytest -q -m "not referee"            # rules, the kit (seconds)
python scripts/fetch_references.py              # Nuked-PSG, the wiki's patterns (never committed)
sh validation/build_referees.sh
python -m pytest -q                             # plus the referee comparisons
python scripts/run_psg_compare.py               # the synthetic streams, every clock
python scripts/export_board_streams.py --board ../megadrive-python   # with that board's Python
python scripts/run_psg_compare.py --streams     # the boards' streams (needs the export)
python scripts/mutation.py                      # the seeded faults
python benchmarks/bench.py                      # speed
```

The exported streams come from ROMs and stay local (`validation/streams/`,
ignored).

## Speed

This is a reference: correct first. Stepping every input clock as the die does,
PyPy 7.3.20 runs **8.4× real time** and CPython 3.14 0.85×. Making it fast is a job
for a Rust transcription and its `-fast` fork. See
[docs/validation.md](docs/validation.md), "Speed".

## Licence

MIT. Nuked-PSG (GPL-2.0) is read, cited by file and line, and run as a locally built
referee. None of its code is in this repository.
