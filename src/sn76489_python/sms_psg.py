"""The SN76489 programmable sound generator, in its discrete and Sega-integrated forms.

Every rule below is from Maxim's SN76489 page (``reference/smspower-wiki/SN76489.pmwiki``,
"the wiki" below) unless its comment names another source. The variant differences
(noise shift-register width and taps, stereo, power-up state) are data on
:class:`PSGVariant`, never branches in the logic.

The chip is clocked by the CPU clock and divides it by 16 internally (the wiki, "How
the SN76489 makes sound"), so one PSG *tick* is 16 CPU cycles. :meth:`PSG.run` takes
CPU cycles, advances the tone and noise generators tick by tick, and box-filters the
mixed output down to the host's sample rate.
"""

from __future__ import annotations

from dataclasses import dataclass

#: CPU cycles per PSG tick: the chip divides its input clock by 16 (the wiki).
CYCLES_PER_TICK = 16

#: Output amplitude for each 4-bit attenuation value: 2 dB per step, 15 is silence
#: (the wiki, "Volume/attenuation"; TI data manual, "attenuator").
VOLUME_TABLE: tuple[float, ...] = (*(10 ** (-0.1 * step) for step in range(15)), 0.0)

#: Noise counter reload values for noise-register shift rates 0-2; rate 3 uses tone 2
#: (the wiki, "Noise channel").
NOISE_RATE_PERIODS = (0x10, 0x20, 0x40)


@dataclass(frozen=True)
class PSGVariant:
    """What differs between the SN76489 parts in Sega's machines.

    ``lfsr_bits`` and ``white_noise_taps``: the wiki, "The Linear Feedback Shift
    Register": 16 bits tapped at bits 0 and 3 ($0009) for the SMS 1 and 2, Game Gear
    and Mega Drive; 15 bits tapped at bits 0 and 1 ($0003) for the SG-1000, SC-3000H
    and Othello Multivision. ``stereo``: the Game Gear's port $06 (the wiki,
    "Game Gear stereo"). ``powers_up_silent``: the Sega-integrated parts start with
    zeroed tone and noise registers and silent volumes; discrete parts start random
    (the wiki, "Registers"), which this model does not reproduce.
    """

    name: str
    lfsr_bits: int
    white_noise_taps: int
    stereo: bool = False
    powers_up_silent: bool = True


#: The discrete TI SN76489AN of the SG-1000 and SC-3000.
SN76489AN = PSGVariant("SN76489AN", lfsr_bits=15, white_noise_taps=0x0003)
#: The PSG inside the Master System's 315-5124 and 315-5246 VDPs.
SEGA_VDP_PSG = PSGVariant("Sega VDP", lfsr_bits=16, white_noise_taps=0x0009)
#: The Game Gear's PSG: the Sega one, with per-channel stereo enables.
GAME_GEAR_PSG = PSGVariant("Game Gear", lfsr_bits=16, white_noise_taps=0x0009, stereo=True)


def _parity(value: int) -> int:
    return value.bit_count() & 1


class PSG:
    """Three tone channels and one noise channel behind a single write-only port.

    ``tone``: the three 10-bit tone registers. ``noise``: the 3-bit noise register
    (bit 2 = white, bits 1-0 = shift rate). ``volume``: four 4-bit attenuations,
    channel 3 being noise. ``stereo``: the Game Gear's port $06 value (bits 7-4 left
    enables for channels 3-0, bits 3-0 right), $FF on the other machines.
    """

    def __init__(self, variant: PSGVariant = SEGA_VDP_PSG, sample_rate: int = 44_100,
                 clock: int = 3_579_545) -> None:  # fmt: skip
        self.variant = variant
        self.sample_rate = sample_rate
        self.clock = clock
        self.reset()

    # -- state ---------------------------------------------------------------

    def reset(self) -> None:
        """Power-up state of the Sega-integrated parts (see :class:`PSGVariant`)."""
        self.tone = [0, 0, 0]
        self.noise = 0
        self.volume = [0xF, 0xF, 0xF, 0xF]
        self.stereo = 0xFF
        self.latched_channel = 0
        self.latched_is_volume = False
        self.counters = [0, 0, 0, 0]
        self.outputs = [1, 1, 1, 1]
        self.noise_input = 0
        self.lfsr = self._lfsr_reset_value()
        self._cycle_remainder = 0
        self._sample_phase = 0
        self._sample_left = 0.0
        self._sample_right = 0.0
        self._sample_ticks = 0
        self.samples: list[tuple[float, float]] = []

    def _lfsr_reset_value(self) -> int:
        # "When the noise register is written to, the shift register is reset, such
        # that all bits are zero except for the highest bit" (the wiki, "Noise").
        return 1 << (self.variant.lfsr_bits - 1)

    # -- the port ------------------------------------------------------------

    def write(self, value: int) -> None:
        """Latch/data byte protocol (the wiki, "SN76489 register writes").

        A byte with bit 7 set latches a channel (bits 6-5) and a register type
        (bit 4: volume) and writes its low 4 bits to the low bits of that register.
        A byte with bit 7 clear writes to the latched register: the high 6 bits of a
        tone register, or the low bits of a volume or noise register ("The data byte
        is NOT ignored", or Micro Machines' noise is wrong).
        """
        value &= 0xFF
        if value & 0x80:
            self.latched_channel = (value >> 5) & 3
            self.latched_is_volume = bool(value & 0x10)
            data, high = value & 0x0F, False
        else:
            data, high = value & 0x3F, True
        channel = self.latched_channel
        if self.latched_is_volume:
            self.volume[channel] = data & 0x0F
        elif channel == 3:
            self.noise = data & 0x07
            self.lfsr = self._lfsr_reset_value()
        elif high:
            self.tone[channel] = (self.tone[channel] & 0x00F) | (data << 4)
        else:
            self.tone[channel] = (self.tone[channel] & 0x3F0) | data

    def write_stereo(self, value: int) -> None:
        """Game Gear port $06: per-channel left/right enables. Ignored elsewhere."""
        if self.variant.stereo:
            self.stereo = value & 0xFF

    # -- time ----------------------------------------------------------------

    def run(self, cycles: int) -> None:
        """Advance by ``cycles`` CPU cycles, appending finished samples to ``samples``."""
        total = self._cycle_remainder + cycles
        ticks, self._cycle_remainder = divmod(total, CYCLES_PER_TICK)
        for _ in range(ticks):
            self._tick()

    def _tick(self) -> None:
        for channel in range(3):
            self._tick_tone(channel)
        self._tick_noise()
        self._accumulate()

    def _tick_tone(self, channel: int) -> None:
        # "Each clock cycle, the counter is decremented (if it is non-zero). If,
        # after being decremented, it is zero, ... the counter is reset to the value
        # currently in the corresponding register ... The output bit is flipped."
        period = self.tone[channel]
        counter = self.counters[channel]
        if counter:
            counter -= 1
        if counter == 0:
            counter = period
            # "If the register value is zero or one then the output is a constant
            # value of +1" (the wiki, "Tone channels"; Sega part, see
            # docs/undocumented-behavior.md, PSG item 2).
            self.outputs[channel] = 1 if period <= 1 else self.outputs[channel] ^ 1
        self.counters[channel] = counter

    def _tick_noise(self) -> None:
        counter = self.counters[3]
        if counter:
            counter -= 1
        if counter == 0:
            rate = self.noise & 3
            counter = self.tone[2] if rate == 3 else NOISE_RATE_PERIODS[rate]
            # The noise generator's own input flips on each reload; the shift
            # register shifts only when it goes 0 -> 1, "only once for every two
            # times the related counter reaches zero" (the wiki, "The LFSR").
            self.noise_input ^= 1
            if self.noise_input:
                self._shift()
        self.counters[3] = counter

    def _shift(self) -> None:
        # "The bit that is shifted off the end ... is output to the mixer." White
        # noise feeds back the parity of the tapped bits; periodic noise feeds back
        # bit 0 alone (the wiki, "For white noise" / "For periodic noise").
        lfsr = self.lfsr
        self.outputs[3] = lfsr & 1
        taps = self.variant.white_noise_taps if self.noise & 4 else 0x0001
        feedback = _parity(lfsr & taps)
        self.lfsr = (lfsr >> 1) | (feedback << (self.variant.lfsr_bits - 1))

    # -- mixing --------------------------------------------------------------

    def channel_levels(self) -> tuple[float, float, float, float]:
        """Each channel's instantaneous output: its bit times its volume."""
        return tuple(  # type: ignore[return-value]
            VOLUME_TABLE[self.volume[channel]] if self.outputs[channel] else 0.0
            for channel in range(4)
        )

    def _accumulate(self) -> None:
        left = right = 0.0
        stereo = self.stereo
        for channel, level in enumerate(self.channel_levels()):
            if stereo & (0x10 << channel):
                left += level
            if stereo & (0x01 << channel):
                right += level
        self._sample_left += left
        self._sample_right += right
        self._sample_ticks += 1
        # Box filter: one output sample per clock/16/sample_rate ticks, tracked with
        # an integer phase so the long-run rate is exact.
        self._sample_phase += self.sample_rate * CYCLES_PER_TICK
        if self._sample_phase >= self.clock:
            self._sample_phase -= self.clock
            ticks = self._sample_ticks
            self.samples.append((self._sample_left / ticks / 4, self._sample_right / ticks / 4))
            self._sample_left = self._sample_right = 0.0
            self._sample_ticks = 0

    def take_samples(self) -> list[tuple[float, float]]:
        """Return and clear the finished stereo samples (each side in 0.0-1.0)."""
        samples, self.samples = self.samples, []
        return samples
