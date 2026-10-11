"""The SN76489 programmable sound generator, run the way the die runs it.

Three tone channels, one noise channel, one write-only port, a 4-bit attenuation
each. The engine is the Sega PSG inside the Mega Drive's YM7101 VDP as Nuked-PSG
transcribes it from the die (``reference/src/Nuked-PSG/ympsg.c``, pinned at
d15a168; GPL-2.0, read and cited, never copied). It equals Nuked-PSG at every input
clock (docs/validation.md). What differs between the parts in Sega's machines is
data on :class:`PSGVariant`, never a branch scattered through the logic.

The engine came from megadrive-python's ``psg.py``, which adapted sms-python's
``psg.py``; the variant table is sms-python's. What the die has and a
programmer's-model PSG does not:

* **The chip's own rotation.** An internal clock at a quarter of the input clock
  alternates two phases, one of the four counters is stepped per phase pair, and the
  *period* is taken from a one-hot selector that runs one place behind the counter
  index, so counter 0 is the noise channel's, counter 1 tone 1's, counter 2 tone
  2's, counter 3 tone 3's (``YMPSG_ClockInternal1`` lines 109-199 and
  ``YMPSG_ClockInternal2`` lines 201-214).
* **The counter is an up-counter compared with the period**, not a down-counter
  reloaded at zero: ``if counter >= period: counter = 0`` and then ``counter += 1``
  (lines 176-186). The two differ for a tick after a period is written, and for a
  period of 0 or 1.
* **The noise LFSR shifts left** with a zero-detect that feeds a 1 into an all-zero
  register, and its output is a bit latched a phase behind (lines 122-135, 213).
  Maxim's wiki describes the same machine shifting right; the variant's taps are in
  the wiki's notation and are mirrored here (:meth:`PSGVariant.left_taps`).
* **A write takes effect one input clock later** (``YMPSG_Clock`` lines 287-294: the
  channel latch is taken on the clock of the write, the register updated by the next
  clock's ``YMPSG_UpdateRegisters``).
* **Power-on is the /IC sequence**, not an assignment: the reset leaves the counters
  at 1, the rotation part way round and the overflow shift register full, which a
  plain zeroing does not (:meth:`SN76489.reset`).

One output sample is one full rotation, 16 input clocks: 223,722 Hz from the
3,579,545 Hz clock of an NTSC Master System or Mega Drive.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Input clocks per output sample: four channels, four input clocks a phase pair.
CLOCKS_PER_SAMPLE = 16

#: The ideal attenuation curve: 2 dB a step, 15 silent (the TI data manual,
#: "attenuator"; Maxim's wiki, "Volume/attenuation").
IDEAL_LEVELS: tuple[float, ...] = (*(10 ** (-0.1 * step) for step in range(15)), 0.0)

#: The YM7101's curve: Nuked-PSG's values (``ympsg.c`` line 7, ``ympsg_vol``), which
#: are not 2 dB a step.
YM7101_LEVELS: tuple[float, ...] = (
    1.0, 0.772, 0.622, 0.485, 0.382, 0.29, 0.229, 0.174,
    0.132, 0.096, 0.072, 0.051, 0.034, 0.019, 0.009, 0.0,
)  # fmt: skip

#: Counter reload values for noise shift rates 0-2; rate 3 follows tone channel 3
#: (ympsg.c lines 152-166, where the rate ORs 16, 32 or 64 into the period).
NOISE_PERIODS = (0x10, 0x20, 0x40)


@dataclass(frozen=True)
class PSGVariant:
    """What differs between the SN76489 parts in Sega's machines.

    ``lfsr_bits`` and ``white_noise_taps`` (in the wiki's right-shifting notation):
    16 bits tapped at bits 0 and 3 ($0009) on the Sega-integrated parts, 15 bits
    tapped at bits 0 and 1 ($0003) on the discrete TI part (Maxim's wiki, "The Linear
    Feedback Shift Register"; Nuked-PSG's 16-bit register taps bits 15 and 12, the
    same pair mirrored).

    ``stereo``: the Game Gear's port $06, per-channel left and right enables (Sega's
    Game Gear manual).

    ``levels``: the output level of each attenuation, 15 being silence. The analogue
    curve is the variant's: the die-measured one for the YM7101, the ideal 2 dB
    otherwise, since nothing in hand measures the Master System's.

    ``low_periods_hold_high``: tone periods 0 and 1 hold the channel's output high.
    Reported for the Sega Master System part, which games use for sample playback
    (Maxim's wiki, "Tone channels"); the YM7101's die instead toggles the output once
    a rotation, as Nuked-PSG does. Where the sources disagree each variant keeps the
    behaviour its own evidence gives (docs/claims.md).
    """

    name: str
    lfsr_bits: int = 16
    white_noise_taps: int = 0x0009
    stereo: bool = False
    levels: tuple[float, ...] = IDEAL_LEVELS
    low_periods_hold_high: bool = False

    def left_taps(self) -> int:
        """The white-noise taps mirrored for the left-shifting register."""
        top = self.lfsr_bits - 1
        return sum(
            1 << (top - bit) for bit in range(self.lfsr_bits) if self.white_noise_taps >> bit & 1
        )


#: The discrete TI SN76489AN of the SG-1000, SC-3000 and Othello Multivision.
SN76489AN = PSGVariant(
    "SN76489AN", lfsr_bits=15, white_noise_taps=0x0003, low_periods_hold_high=True
)
#: The PSG inside the Master System's 315-5124 and 315-5246 VDPs.
SEGA_VDP_PSG = PSGVariant("Sega VDP", low_periods_hold_high=True)
#: The Game Gear's PSG: the Sega one, with per-channel stereo enables.
GAME_GEAR_PSG = PSGVariant("Game Gear", stereo=True, low_periods_hold_high=True)
#: The PSG inside the Mega Drive's YM7101 VDP: Nuked-PSG's die.
YM7101_PSG = PSGVariant("YM7101", levels=YM7101_LEVELS)

VARIANTS = {
    variant.name: variant for variant in (SN76489AN, SEGA_VDP_PSG, GAME_GEAR_PSG, YM7101_PSG)
}


class SN76489:
    """The PSG as the die has it: registers, four counters, and the rotation.

    ``volume``: the four attenuations (tone 1-3, noise). ``freq``: the three 10-bit
    tone periods. ``noise_data``: the 3-bit noise register (bit 2 white, bits 1-0 the
    shift rate). ``stereo``: the Game Gear's port $06 value (bits 7-4 left enables
    for noise and tones 3-1, bits 3-0 right), $FF on the other variants.

    :meth:`attenuations` is the chip's digital output, what each channel is driving
    this instant, and is what the referee is compared against. :meth:`take_samples`
    turns the finished samples into levels.
    """

    def __init__(self, variant: PSGVariant = SEGA_VDP_PSG) -> None:
        self.variant = variant
        self._lfsr_mask = (1 << variant.lfsr_bits) - 1
        self._lfsr_low = self._lfsr_mask >> 1
        self._lfsr_taps = variant.left_taps()
        self._lfsr_out = variant.lfsr_bits - 2
        self.reset()

    def reset(self) -> None:
        """Power-on: /IC held for 16 input clocks, as a console's reset does.

        Nuked-PSG's ``YMPSG_Init`` (ympsg.c lines 256-266) holds /IC over 16 clocks
        and then releases it, which zeroes the registers through ``reg_reset``,
        silences the channels through ``data_mask``, and leaves the sequencer part
        way round: counters at 1, the overflow register full, the one-hot selector at
        bit 3. Running the same sequence here is shorter than asserting the resulting
        state and cannot drift from it.
        """
        self.volume = [0xF, 0xF, 0xF, 0xF]
        self.freq = [0, 0, 0]
        self.noise_data = 0
        self.stereo = 0xFF
        self.latch = 0
        self.test = 0
        self.counter = [0, 0, 0, 0]
        self.counter_of = 0
        #: Bit 3 tone 1, bit 2 tone 2, bit 1 tone 3, bit 0 noise (ympsg.c line 219).
        self.sign = 0
        self.noise = 0
        self.noise_of = 0
        self.noise_trig = 0
        self.noise_trig_l = 0
        self.noise_sign = 0
        #: The one-hot period selector and the counter index it runs ahead of.
        self.chan_sel = 0
        self.rot = 0
        #: The /4 prescaler and the two /IC shift registers.
        self.p1 = 0
        self.p2 = 0
        self.ic_latch1 = 0
        self.ic_latch2 = 0
        self.ic = 1
        #: The write pipeline (ympsg.c's ``data``, ``write_flag`` and ``write_flag_l``):
        #: the data register, which a write replaces at once; a write not yet taken
        #: in by a clock; a byte taken in and still to reach its register.
        self._data = 0
        self._write_flag = False
        self._write_flag_l = False
        self.clock = 0
        #: One entry per finished sample: the four attenuations being driven.
        self.levels: list[tuple[int, int, int, int]] = []
        #: Samples already turned into levels by a stereo change (:meth:`write_stereo`).
        self._mixed: list[tuple[float, float]] = []

        self.run(16)
        self.ic = 0
        # /IC drives reg_reset and data_mask, which zero the periods and the noise
        # register and force every attenuation to 15 (ympsg.c YMPSG_UpdateRegisters,
        # lines 24-107). Asserted here rather than run, because a write during /IC --
        # the only thing the loop would do differently -- cannot happen on a console:
        # the board holds the PSG in reset before the CPUs run.
        self.volume = [0xF, 0xF, 0xF, 0xF]
        self.freq = [0, 0, 0]
        self.noise_data = 0
        self.clock = 0
        self.levels.clear()

    # -- the ports -------------------------------------------------------------------

    def write(self, value: int) -> None:
        """The data port. Reading it locks up a Mega Drive (CMD ``gen-hw.txt`` 1) and
        is not wired on the Master System, so there is no read.

        The byte reaches its register on the next input clock: run the chip up to the
        moment of the write first. It replaces the data register at once, so a write on
        the clock straight after another hands the first one's register update its own
        byte, as the die does (``YMPSG_Write``, ympsg.c lines 238-242). No console can
        write that fast; the conformance kit's ``back-to-back`` example does.
        """
        self._data = value & 0xFF
        self._write_flag = True

    def write_stereo(self, value: int) -> None:
        """The Game Gear's port $06: per-channel left and right enables. Ignored on
        the other variants. Samples finished before the write keep the old routing."""
        if self.variant.stereo:
            self._mixed.extend(self._mix(self.levels))
            self.levels = []
            self.stereo = value & 0xFF

    def write_test(self, value: int) -> None:
        """The three test bits, which Nuked-PSG takes as ``YMPSG_Test`` (ympsg.c line
        336). Bit 0 forces every channel's sign high; the other two select one channel
        for an analogue test output, which this model has no counterpart for and
        ignores. On the Mega Drive they are the VDP debug register's bits 11-9."""
        self.test = value & 7

    # -- time ------------------------------------------------------------------------

    def run(self, clocks: int) -> None:
        """Advance ``clocks`` input clocks, appending finished samples.

        The body is ``YMPSG_Clock`` (ympsg.c lines 273-306): the /4 prescaler, the /IC
        shift register that resets it, then the registers, the channel latch and one
        of the two internal phases.

        The register update happens **twice**: once at the head of the clock after the
        write, and once inside the second internal phase, which the write's own clock
        may be (ympsg.c calls ``YMPSG_UpdateRegisters`` at line 287 and again at line
        209). So a write that lands on that phase reaches the register a clock earlier
        than one that does not -- worth 19 samples in 102,569 of the first stream this
        was compared on, and the reason it is modelled and not smoothed over.
        """
        clock = self.clock
        for _ in range(clocks):
            p2_latch = self.p2
            self.p2 = (self.p2 + self.p1) & 1
            p1 = self.p1 ^ 1
            if self.ic_latch1 == 2:
                p1 = 0
                self.p2 = 0
            self.p1 = p1
            self.ic_latch1 = ((self.ic_latch1 << 1) | self.ic) & 3
            if self._write_flag_l:
                self._update_registers()
                self._write_flag_l = False
            if self._write_flag:
                # The channel latch is taken on the clock of the write itself.
                if self._data & 0x80:
                    self.latch = (self._data >> 4) & 7
                self._write_flag = False
                self._write_flag_l = True
            if p1:
                if p2_latch:
                    self._phase2()
                else:
                    self._phase1()
            clock += 1
            if clock % CLOCKS_PER_SAMPLE == 0:
                self.levels.append(self.attenuations())
        self.clock = clock

    def _update_registers(self) -> None:
        """The latched byte into the register the channel latch names (ympsg.c
        ``YMPSG_UpdateRegisters``, lines 24-107).

        A byte with bit 7 set carries the low four data bits; one with bit 7 clear
        carries the high six bits of a tone register. Bit 7 does not select the
        register: the latch does, so a byte with bit 7 clear written while a volume or
        noise register is latched is written there whole ("The data byte is NOT
        ignored", Maxim's wiki: Micro Machines' noise is wrong otherwise).
        """
        data = self._data
        low = bool(data & 0x80)
        latch = self.latch
        if latch & 1:  # 1, 3, 5, 7: the attenuations of tone 1-3 and noise
            self.volume[latch >> 1] = data & 0x0F
        elif latch == 6:
            self.noise_data = data & 0x07
            self.noise_trig = 1
        elif low:
            channel = latch >> 1
            self.freq[channel] = (self.freq[channel] & 0x3F0) | (data & 0x0F)
        else:
            channel = latch >> 1
            self.freq[channel] = (self.freq[channel] & 0x00F) | ((data << 4) & 0x3F0)

    def _phase1(self) -> None:
        """The first internal phase: the noise register, then one counter's step.

        ``ympsg.c`` ``YMPSG_ClockInternal1``, lines 109-199. ``chan_sel`` is a one-hot
        shift register naming whose *period* this step compares against; ``rot``
        names the counter. The four expiries collected in ``counter_of`` flip the four
        signs together on the step that serves tone 1.
        """
        ic_latch2 = self.ic_latch2
        noise_data = self.noise_data
        # The noise generator follows tone 3's sign in shift rate 3, its own counter's
        # otherwise, and shifts on that signal's rising edge.
        noise_of = (self.sign >> 1) & 1 if (noise_data & 3) == 3 else self.sign & 1
        if self.noise_trig_l or ic_latch2 & 1:
            self.noise = 0
        elif noise_of and not self.noise_of:
            self._shift()
        self.noise_of = noise_of

        chan_sel = 0 if ic_latch2 & 2 else self.chan_sel
        period = 0
        if chan_sel & 1:
            period = self.freq[0]
        if chan_sel & 2:
            period |= self.freq[1]
        if chan_sel & 4:
            period |= self.freq[2]
        if chan_sel & 8:
            rate = noise_data & 3
            if rate != 3:
                period |= NOISE_PERIODS[rate]
        if chan_sel & 1:
            self.sign ^= self.counter_of & 15
        if ic_latch2 & 2:
            self.sign = 0
        self.counter_of = (self.counter_of << 1) & 0xFF
        rot = self.rot
        counter = self.counter[rot]
        if counter >= period:
            self.counter_of |= 1
            counter = 0
        if ic_latch2 & 2:
            counter = 0
        self.counter[rot] = (counter + 1) & 0x3FF
        # The one-hot rotation: a 1 is fed in when the three tone places are clear.
        self.chan_sel = (
            (self.chan_sel << 1) | (0 if (ic_latch2 & 1) or self.chan_sel & 7 else 1)
        ) & 0xFF
        self.ic_latch2 = ((ic_latch2 << 1) | self.ic) & 0xFF
        self.noise_trig_l = self.noise_trig

    def _shift(self) -> None:
        """One step of the noise register (ympsg.c lines 126-134): white noise feeds
        back the parity of the tapped bits, periodic noise nothing, and an all-zero
        register below the top bit takes a 1 either way, which is what makes periodic
        noise a single 1 circulating the register's width."""
        noise = self.noise
        feedback = (noise & self._lfsr_taps).bit_count() & 1 and (self.noise_data >> 2) & 1
        bit = 1 if feedback or (noise & self._lfsr_low) == 0 else 0
        self.noise = ((noise << 1) | bit) & self._lfsr_mask

    def _phase2(self) -> None:
        """The second internal phase: the counter index steps and the LFSR's output bit
        is latched (``ympsg.c`` ``YMPSG_ClockInternal2``, lines 201-214)."""
        if self.noise_trig_l:
            self.noise_trig = 0
        if self._write_flag_l:
            self._update_registers()
        self.rot = (self.rot + 1) & 3
        self.noise_sign = (self.noise >> self._lfsr_out) & 1

    # -- output ----------------------------------------------------------------------

    def attenuations(self) -> tuple[int, int, int, int]:
        """What each channel is driving now: its attenuation while its sign bit is
        high, silence (15) otherwise (ympsg.c ``YMPSG_UpdateSample``, lines 216-236).
        The noise channel uses the latched LFSR bit, the tone channels their signs."""
        sign = (self.sign & 14) | self.noise_sign
        if self.test & 1:
            sign |= 15
        volume = self.volume
        if self.variant.low_periods_hold_high:
            freq = self.freq
            if freq[0] <= 1:
                sign |= 8
            if freq[1] <= 1:
                sign |= 4
            if freq[2] <= 1:
                sign |= 2
        return (
            volume[0] if sign & 8 else 15,
            volume[1] if sign & 4 else 15,
            volume[2] if sign & 2 else 15,
            volume[3] if sign & 1 else 15,
        )

    def _mix(self, levels: list[tuple[int, int, int, int]]) -> list[tuple[float, float]]:
        table = self.variant.levels
        stereo = self.stereo
        if stereo == 0xFF:
            mono = [table[a] + table[b] + table[c] + table[d] for a, b, c, d in levels]
            return [(level, level) for level in mono]
        # Bits 7-4 left, 3-0 right; within each, bit 0 tone 1 ... bit 3 noise.
        mixed = []
        for attenuations in levels:
            left = right = 0.0
            for channel, attenuation in enumerate(attenuations):
                level = table[attenuation]
                if stereo & (0x10 << channel):
                    left += level
                if stereo & (0x01 << channel):
                    right += level
            mixed.append((left, right))
        return mixed

    def take_samples(self) -> list[tuple[float, float]]:
        """Return and clear the finished samples as ``(left, right)`` levels, each
        0.0-4.0 (four channels of 0.0-1.0) by the variant's curve. Without stereo the
        two sides are equal. Resampling and the analogue path belong to the board."""
        mixed = self._mixed
        mixed.extend(self._mix(self.levels))
        self._mixed, self.levels = [], []
        return mixed

    def take_attenuations(self) -> list[tuple[int, int, int, int]]:
        """Return and clear the finished samples as the chip's own digital state, the
        four attenuations, which is what the Nuked-PSG comparison is made on. Stereo
        is not applied."""
        levels, self.levels = self.levels, []
        self._mixed = []
        return levels
