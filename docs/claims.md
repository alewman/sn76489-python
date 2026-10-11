# Claims: what this core claims, how strongly, and where it stops

The SN76489 has a TI data manual for the discrete part and nothing from Sega for
theirs. One transcription of a real die exists: Nuked-PSG, the PSG block of the
Mega Drive's YM7101 VDP. No hardware capture of any Sega PSG's digital state is in
hand. So the strongest judge of the engine is **die-derived**, and only for the
YM7101; the other parts' differences rest on research documents and reports. Each
behaviour below carries a status set by the best evidence that reaches it. The
evidence itself is [validation.md](validation.md).

## The strands of evidence

| Lineage | Sources | Tier | Reach |
| --- | --- | --- | --- |
| **The YM7101's die** | Nuked-PSG @ d15a168, run as a referee | die-derived | the four attenuations at every input clock; the YM7101's analogue curve |
| **Maxim's SN76489 page** (SMS Power wiki, from Charles MacDonald's SMS1, GG, Genesis and SC-3000H samples, which are not in hand) | research document | the noise registers' widths and taps; the latch/data protocol; periods 0 and 1 on the Sega part; power-on |
| **The wiki's two noise bit patterns** | illustrations, not recordings | the 15-bit $0003 sequence |
| **TI** | the SN76489AN data manual | documentation | the ideal curve; the register map |
| **Sega** | the Game Gear hardware manual | documentation | port $06 |
| **The boards' writes** | sms-python and megadrive-python running cartridges, exported | not an oracle (inputs) | real sound drivers' write traffic for the referee comparison |
| **The suite itself** | the tests, the conformance examples, the seeded faults | not an oracle | shows a gate would notice a wrong value |

## Status levels

| Status | Meaning |
| --- | --- |
| **Verified** | Hardware-captured evidence covers it and the core matches. |
| **Strong** | A die-derived model agrees at every clock over broad streams, and nothing closer to silicon disagrees. |
| **Provisional** | One research document or one die lineage supports it, over a narrow domain, or the die is another part's. |
| **Contested** | Credible sources disagree; the core's choice is named. |
| **Undecidable here** | Nothing available tells the candidates apart. |
| **Outside the contract** | Not claimed, by decision. |

## The claims

### Verified

Nothing. No hardware capture of a PSG's digital output exists in the family's
references.

### Strong (the YM7101)

- **The four attenuations at every input clock**, over six synthetic streams and the
  writes of thirteen cartridges on three consoles, equal Nuked-PSG: the rotation,
  the up-counters, the noise register, the write pipeline (including two writes a
  clock apart) and power-on. The numbers are in [validation.md](validation.md).
- **The YM7101's curve** is Nuked-PSG's table, value for value.

### Provisional

- **The Master System, Game Gear and SG-1000 parts run the YM7101's engine.** The
  cartridge streams from sms-python agree with Nuked-PSG through the YM7101 variant,
  which shows the engine handles their drivers' traffic, not that their silicon is
  the YM7101's. The 315-5124 die photograph exists; no netlist does. Where the
  YM7101's sequencer timing differs from theirs, nothing here would notice.
- **The 16-bit $0009 noise register on the Sega parts.** The wiki, MAME and Genesis
  Plus GX agree; the die confirms it for the YM7101 only.
- **The 15-bit $0003 register on the SN76489AN.** It reproduces the wiki's bit
  pattern over all 32,767 bits, but the pattern is an illustration, not a recording.
- **Port $06's bit order.** Sega's manual.

### Contested

- **Tone periods 0 and 1.** The wiki reports that the Sega part holds the output
  high, and games use this for sample playback. The YM7101's die toggles the output
  once a rotation, at clock / 32 (111.9 kHz). An analogue path would smooth that to
  half the level, which may be what was observed. Each variant keeps the behaviour
  its own evidence gives: `low_periods_hold_high` is set on the Master System, Game
  Gear and SG-1000 variants (sms-python's behaviour until now) and clear on the
  YM7101 (megadrive-python's). A recording of `SN76489TestRom-SMS` playing a period
  of 1 on a real Master System would settle it for that part.
- **The Sega noise sequence's bit pattern.** The wiki's download labelled `Sega VDP
  white noise.dat` is the 15-bit $0003 sequence, not the 16-bit one the page
  describes. The core follows the page (sms-python's undocumented-behavior.md, open
  item 6).

### Undecidable here

- **Period 0 on the discrete SN76489AN**: held high, or a period of 1024? The TI
  manual does not say. The core holds it high, as the Sega parts are reported to.
- **The Master System's analogue curve**, and the SMS2's clipping. Nothing in hand
  measures them; the variants use the ideal 2 dB.

### Outside the contract

- **The SN76489AN's random power-on state**, and its READY wait states (about 32
  clocks per write, TI data manual). A board that wants them adds them.
- **The test bits' analogue output select** (bits 1-2).
- **The analogue path**: filters, mixing, resampling.
