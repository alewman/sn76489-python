# The contract: the chip's port, its time and its outputs

This is what a host can rely on and what a port must reproduce. Everything here is
checked by `tests/` or by the conformance kit ([conformance.md](conformance.md));
how strongly each behaviour is known is [claims.md](claims.md).

## One chip, four variants

```python
from sn76489_python import SN76489, SN76489AN, SEGA_VDP_PSG, GAME_GEAR_PSG, YM7101_PSG

chip = SN76489(YM7101_PSG)  # the Mega Drive's
```

The variant is a constructor argument, a `PSGVariant`. It is a value, not a
subclass, so a host can build its own. Every variant runs the same engine; the
fields are the only differences.

| Field | `SN76489AN` | `SEGA_VDP_PSG` | `GAME_GEAR_PSG` | `YM7101_PSG` | Evidence |
| --- | --- | --- | --- | --- | --- |
| machines | SG-1000, SC-3000, Othello Multivision | Mark III, Master System 1 and 2 | Game Gear | Mega Drive / Genesis | |
| `lfsr_bits`, `white_noise_taps` | 15, $0003 | 16, $0009 | 16, $0009 | 16, $0009 | Maxim's wiki (research document); Nuked-PSG for the YM7101 (die-derived) |
| `stereo` | no | no | port $06 | no | Sega's Game Gear manual |
| `levels` | 2 dB a step | 2 dB a step | 2 dB a step | Nuked-PSG's curve | TI data manual; Nuked-PSG |
| `low_periods_hold_high` | yes | yes | yes | no | the wiki (reported); Nuked-PSG |

`white_noise_taps` is written in the wiki's notation, a register shifting right. The
engine's register shifts left, as the die's does, and `PSGVariant.left_taps()`
mirrors the taps: $0009 becomes bits 15 and 12, Nuked-PSG's pair.

`VARIANTS` maps each variant's `name` to it.

## Time

The chip runs from one input clock: 3,579,545 Hz on an NTSC Master System or Mega
Drive, where it is the Z80's clock. The core counts **input clocks**.

- **`run(clocks)`** advances that many input clocks from where the chip stands.
  `clock` counts the clocks run since power-on.
- One output sample is one full rotation of the four channels: **16 clocks**
  (`CLOCKS_PER_SAMPLE`), 223,722 Hz at the NTSC clock.
- **The host owns the conversion.** It brings the chip up to the moment of each write
  with `run()` before calling `write()`. megadrive-python divides its master clock by
  15; sms-python's clocks are its CPU cycles.

## Power-on

`SN76489()` and `reset()` run the die's power-on: /IC held for 16 clocks, then
released (Nuked-PSG's `YMPSG_Init`). The registers come out zeroed and every channel
silent, with the rotation part way round: the counters at 1, the one-hot selector at
bit 3, the overflow shift register full. `clock` then reads 0. The SN76489AN's
power-on is random on a real part (the wiki); this core starts it like the Sega
parts.

## The ports

| Port | API | Behaviour |
| --- | --- | --- |
| data (write only) | `write(value)` | The latch/data byte protocol. A byte with bit 7 set latches a register (bits 6-4) and carries its low four bits; a byte with bit 7 clear carries the high six bits of a latched tone register, or the whole value of a latched volume or noise register. The byte reaches its register on the next input clock, a clock sooner if the clock it is taken on runs the second internal phase. A noise-register write restarts the noise register. |
| (the data register) | | A write replaces the data register at once. A write on the clock straight after another therefore hands the first write's register update the second byte, as the die does. No console writes that fast. |
| Game Gear port $06 | `write_stereo(value)` | Bits 7-4 enable noise, tone 3, tone 2 and tone 1 on the left; bits 3-0 the same on the right. Ignored by the other variants (`stereo` stays $FF). Samples already made keep their routing. |
| test | `write_test(bits)` | The three test bits. Bit 0 forces every channel's sign high. The other two select a channel for an analogue test output this core does not model. On the Mega Drive they are the VDP debug register's bits 11-9; the board shifts them. |

There is no read: reading the PSG locks up a Mega Drive (CMD `gen-hw.txt`), and the
Master System does not wire one.

## The outputs

| Output | API | What |
| --- | --- | --- |
| the digital state | `attenuations()` | The four attenuations being driven this instant (tone 1, 2, 3, noise): each channel's volume while its output is high, 15 otherwise. This is what the referee is compared on, at every clock. |
| per sample | `take_attenuations()` | One 4-tuple per 16 clocks, then cleared. Stereo is not applied. |
| levels | `take_samples()` | One `(left, right)` per 16 clocks, then cleared: the variant's `levels` of each channel summed, each side 0.0-4.0. Without stereo the two sides are equal. |

The two `take_` methods drain the same queue: a host uses one of them.

The analogue path (the output filter, the mix with other chips, resampling to the
host's rate, the SMS2's clipping) belongs to the board. megadrive-python mixes the
PSG into its FM path in `audio.py`; sms-python box-filters to the host's rate in its
`audio.py`.

## What a port must reproduce

The digital state at every input clock, over the conformance examples
([conformance.md](conformance.md)). The `levels` tables and the stereo routing are
data a port copies; `tests/test_chip.py` checks them in this core.
