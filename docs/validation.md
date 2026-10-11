# Validation: the oracles, ranked, and what was run

## The tier rule

Oracles rank by where their expected values came from:

1. **hardware-captured**: measured on a real chip;
2. **hardware-corrected**: written against hardware and fixed until it agreed;
3. **die-derived**: a transcription of the chip's silicon from die photographs;
4. **emulator-derived**: another emulator's output;
5. **documentation**.

A lower tier is used as a judge only where nothing above it covers the question. For
the PSG's digital state nothing above die-derived exists: there is no capture of any
Sega PSG's channel outputs and no self-checking PSG test program. That is the case
the rule reserves for a die-derived judge. This is the family's rule, as
megadrive-python and ym2612-python state it.

## The oracles

| Oracle | Tier | Role | Pinned |
| --- | --- | --- | --- |
| **Nuked-PSG** (nukeykt), the PSG block of the YM7101 VDP transcribed from its die | die-derived | **the judge**: the four attenuations at every input clock; the YM7101's curve | `reference/src/Nuked-PSG` @ d15a168, GPL-2.0, built locally as `psg_ref` |
| **Maxim's SN76489 page** (SMS Power wiki) | research document | the variants' noise registers, the latch/data protocol, periods 0 and 1 on the Sega part | cited; sms-python `reference/smspower-wiki/SN76489.pmwiki` |
| **The wiki's noise bit patterns** (`SN76489WhiteNoise.zip`, `SegaVDPWhiteNoise.zip`) | illustration | the 15-bit $0003 sequence | `reference/smspower-attach/`, SHA-256 pinned |
| **TI SN76489AN data manual** | documentation | the ideal curve | sms-python `reference/manuals/` |

`scripts/fetch_references.py` fetches the referee and the two pattern files.
`sh validation/build_referees.sh` builds the referee. Neither is ever committed.
`validation/psg_ref.c` drives the referee and copies nothing. Nuked-PSG's source is
read and cited by file and line in `src/sn76489_python/chip.py`, never copied.

## Certification record

### The Nuked-PSG rung: every input clock, zero differences

`sn76489-python` at the commit that adds this page, PyPy 7.3.20 (Python 3.11.13),
gcc 15.2.0, run on 2026-10-11. The chip runs as `YM7101_PSG`, the variant the die
is. At every input clock, the four attenuations it drives equal Nuked-PSG's:

| Streams | Input clocks | Result |
| --- | --- | --- |
| 6 synthetic: two random walks (3,000 latches each), a dense walk (6,000 writes 1-4 clocks apart), every tone period, every noise setting, every attenuation | 2,990,093 | **identical** |
| 5 Mega Drive cartridges from megadrive-python 4871beb: Sonic, Streets of Rage 2, Gunstar Heroes, Castlevania Bloodlines, Phantasy Star IV | 200,443,323 | **identical** |
| 5 Master System cartridges from sms-python 5008061 (SMS2): Sonic, Alex Kidd in Miracle World, After Burner, Micro Machines, Phantasy Star | 268,619,797 | **identical** |
| 2 Game Gear cartridges: Shinobi II, Columns | 107,454,364 | **identical** |
| 1 SG-1000 cartridge: Flicky | 53,754,995 | **identical** |
| **total, 19 streams** | **633,262,572** | **0 different** |

```text
python scripts/fetch_references.py && sh validation/build_referees.sh
../sms-python/.venv-pypy/bin/python scripts/export_board_streams.py --board ../sms-python
../megadrive-python/.venv-pypy/bin/python scripts/export_board_streams.py --board ../megadrive-python
python scripts/run_psg_compare.py --streams
```

The cartridge streams are every byte the boards' PSGs received, at the input clock
each arrived, exported to `validation/streams/` (ignored: derived from ROMs). The
Master System, Game Gear and SG-1000 streams run through the YM7101 variant, so
they test the engine against those consoles' sound drivers, not those consoles'
silicon ([claims.md](claims.md), Provisional).

### What the conformance kit found

Before this core existed, megadrive-python's PSG matched Nuked-PSG on 121,279,139
input clocks of synthetic and game streams, whose writes were at least 20 clocks
apart. The kit's `back-to-back` and `random-walk` examples write one clock apart, and
there it differed. Nuked-PSG's `YMPSG_Write` replaces the data register at once, so
a write on the clock straight after another hands the first write's pending register
update the second byte. The board's model kept the first byte. The core now models
the single data register. No console writes the PSG that fast, so no board's
behaviour changes. The dense synthetic stream and four referee-checked examples now
cover it.

### The variants

| What | Result | Tier |
| --- | --- | --- |
| The SN76489AN's noise, read off its noise channel's output through `run()` | contains the wiki's "Sega VDP white noise" pattern, all 32,767 bits; the inverted sequence contains its "SN76489 white noise" | illustration |
| White-noise periods | 32,767 (15-bit $0003), 57,337 (16-bit $0009), as sms-python asserted | research document |
| Periodic-noise periods | 15 and 16, the register widths | research document |
| The YM7101's curve | equals `ympsg_vol` value for value | die-derived |
| The ideal curve | 2 dB a step, 15 silent | documentation |
| Periods 0 and 1 | held high on the SMS, GG and SG-1000 variants; toggle once a rotation on the YM7101 (contested, [claims.md](claims.md)) | research document / die-derived |

### Seeded faults

`python scripts/mutation.py`: 23 mutants, each breaking one rule the way a port
might: counter compare and width, noise rates, the rate-3 source, edge detection,
the zero-detect, the output bit, unmirrored taps, the noise restart, the latch/data
protocol, the data register, the second-phase update, the sign-flip step, the
rotation, the prescaler's /IC reset, the sample rate, the low-period hold, the test
bit, stereo routing and the curve. **23 caught.** With the conformance examples
alone as the gate (`--examples-only`), 21 are caught. The two survivors are the
stereo sides and the curve, which sit outside the digital trace by design and which
the rule tests catch.

### Coverage

`coverage run --source=src/sn76489_python -m pytest` with the referee built: `chip.py`
100% of 205 statements, `conformance.py` 94% (the command line's error paths),
97% overall.

## Speed

`python benchmarks/bench.py`: the seed-1 random walk, two seconds of emulated time,
run as a board drives the chip. Best of three on the shared i9-13900K, 2026-10-11.

| Interpreter | YM7101 | Game Gear | Real time |
| --- | --- | --- | --- |
| PyPy 7.3.20 | 29.97 M clocks/s | 32.54 M clocks/s | **8.4×** |
| CPython 3.14.4 | 3.05 M clocks/s | 3.30 M clocks/s | **0.85×** |

Real time is 3,579,545 clocks a second. The engine steps every input clock, as the
die does. sms-python's previous model stepped every 16 clocks and ran 26× real time
on PyPy and 4.9× on CPython; the cost of exactness is about three times on PyPy.
Speed is a job for a Rust transcription and its `-fast` fork.
