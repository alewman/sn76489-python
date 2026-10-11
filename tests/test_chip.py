"""The SN76489 against the wiki's rules, its published noise bit patterns, and the die.

The rules are Maxim's SN76489 page (sms-python's tests); the engine's own shape --
the rotation, power-on, the write pipeline -- is Nuked-PSG's (megadrive-python's).
The every-clock comparison with Nuked-PSG itself is tests/test_referee.py.
"""

from __future__ import annotations

import re
import zipfile
from itertools import pairwise
from pathlib import Path

import pytest

from sn76489_python import (
    CLOCKS_PER_SAMPLE,
    GAME_GEAR_PSG,
    IDEAL_LEVELS,
    SEGA_VDP_PSG,
    SN76489,
    SN76489AN,
    VARIANTS,
    YM7101_LEVELS,
    YM7101_PSG,
    PSGVariant,
)

ROOT = Path(__file__).resolve().parents[1]
ATTACH = ROOT / "reference" / "smspower-attach"
NUKED_PSG = ROOT / "reference" / "src" / "Nuked-PSG" / "ympsg.c"

#: The NTSC Master System's and Mega Drive's PSG clock, 315/88 MHz.
NTSC_CLOCK = 3_579_545


def written(psg: SN76489, *values: int) -> SN76489:
    """Write each byte and run past the clock that applies it."""
    for value in values:
        psg.write(value)
        psg.run(2)
    return psg


# -- the noise register ------------------------------------------------------------


def lfsr_period(variant: PSGVariant, white: bool) -> int:
    psg = written(SN76489(variant), 0xE4 if white else 0xE0)
    for _ in range(100):  # out of the all-zero reset state
        psg._shift()
    start, steps = psg.noise, 0
    while True:
        psg._shift()
        steps += 1
        if psg.noise == start:
            return steps


def test_white_noise_periods():
    # 2^15 - 1 for the discrete part; 57,337 for the Sega 16-bit $0009 register,
    # which is not maximal (sms-python's docs/undocumented-behavior.md, open item 6).
    assert lfsr_period(SN76489AN, white=True) == 32_767
    assert lfsr_period(SEGA_VDP_PSG, white=True) == 57_337
    assert lfsr_period(YM7101_PSG, white=True) == 57_337


def test_periodic_noise_is_the_register_width():
    # Periodic noise feeds back nothing: the zero-detect's single 1 circulates.
    assert lfsr_period(SN76489AN, white=False) == 15
    assert lfsr_period(SEGA_VDP_PSG, white=False) == 16


def test_the_taps_are_the_wikis_mirrored():
    # $0009 (bits 0 and 3, shifting right) is Nuked-PSG's bits 15 and 12 (shifting left).
    assert YM7101_PSG.left_taps() == (1 << 15) | (1 << 12)
    assert SN76489AN.left_taps() == (1 << 14) | (1 << 13)


def _pattern(name: str) -> bytes:
    archive = ATTACH / f"{name}.zip"
    if not archive.exists():
        pytest.skip(f"{archive} not fetched (scripts/fetch_references.py)")
    with zipfile.ZipFile(archive) as bundle:
        (member,) = bundle.namelist()
        return bundle.read(member)


def noise_bits(variant: PSGVariant, count: int) -> bytes:
    """The noise channel's output, one bit per shift, read off the chip's pins.

    Shift rate 3 with tone 3's period at 0 shifts the register once every two
    rotations (32 input clocks), so sampling the noise channel every 32 clocks reads
    each bit once.
    """
    psg = written(SN76489(variant), 0xC0, 0x00, 0xE7, 0xF0)  # tone 3 = 0; white, rate 3
    bits = bytearray()
    for _ in range(count):
        psg.run(32)
        bits.append(1 if psg.attenuations()[3] == 0 else 0)
    return bytes(bits)


def test_discrete_noise_matches_the_wikis_bit_pattern():
    # The wiki's download labelled "Sega VDP white noise" is, bit for bit, the 15-bit
    # $0003 sequence; its "SN76489 white noise" is the same sequence inverted and
    # rotated. Neither is the 16-bit $0009 sequence the page describes
    # (docs/claims.md; sms-python's docs/undocumented-behavior.md, open item 6).
    sega = _pattern("SegaVDPWhiteNoise")
    ti = _pattern("SN76489WhiteNoise")
    bits = noise_bits(SN76489AN, 2 * 32_767)
    assert sega in bits
    assert ti in bytes(1 - bit for bit in bits)


def test_a_noise_write_restarts_the_register():
    psg = written(SN76489(), 0xE4, 0xF0)
    psg.run(10_000)
    assert psg.noise != 0
    psg.write(0xE4)
    psg.run(8)  # the trigger reaches the register on the next first phase
    assert psg.noise in (0, 1)


# -- the port ------------------------------------------------------------------------


def test_tone_latch_then_data_byte():
    psg = written(SN76489(), 0x80 | 0x0E, 0x0F)  # tone 1: low 4 bits $E, high 6 $0F
    assert psg.freq[0] == 0x0FE
    written(psg, 0x80 | 0x20 | 0x05)  # tone 2, low bits only
    assert psg.freq[1] == 0x005
    assert psg.freq[0] == 0x0FE


def test_data_byte_after_a_volume_latch_sets_the_volume():
    psg = written(SN76489(), 0x90 | 0x3)
    assert psg.volume[0] == 3
    written(psg, 0x07)  # a data byte goes to the latched register
    assert psg.volume[0] == 7


def test_data_byte_after_a_noise_latch_is_not_ignored():
    # "The data byte is NOT ignored. If it is, some games (e.g. Micro Machines)
    # produce the wrong sound on their noise channel."
    psg = written(SN76489(), 0xE5)
    assert psg.noise_data == 0b101
    written(psg, 0x04)
    assert psg.noise_data == 0b100


def test_a_write_reaches_its_register_on_a_later_clock():
    psg = SN76489()
    psg.write(0x93)
    assert psg.volume[0] == 15
    psg.run(1)  # the clock that takes the byte in
    psg.run(1)  # by the head of the next clock it is in the register
    assert psg.volume[0] == 3


# -- power-on ----------------------------------------------------------------------


def test_power_up_is_silent_with_zeroed_registers():
    psg = SN76489()
    assert psg.freq == [0, 0, 0]
    assert psg.noise_data == 0
    assert psg.volume == [15, 15, 15, 15]
    assert psg.attenuations() == (15, 15, 15, 15)


def test_power_up_leaves_the_rotation_part_way_round():
    """/IC held for 16 clocks leaves the counters at 1 and the selector at bit 3, not
    everything at zero (``ympsg.c`` ``YMPSG_Init``)."""
    psg = SN76489()
    assert psg.counter == [1, 1, 1, 1]
    assert psg.chan_sel == 0x08
    assert psg.counter_of == 0x0F
    assert psg.clock == 0


# -- tone ------------------------------------------------------------------------------


def test_one_sample_every_sixteen_input_clocks():
    psg = SN76489()
    psg.run(CLOCKS_PER_SAMPLE * 100)
    assert len(psg.take_attenuations()) == 100


def test_tone_register_0x0fe_is_440_hz():
    # "0x0fe gives 440.4Hz" at 3,579,545 Hz: the sign flips once a period, a period
    # being 254 rotations of 16 clocks.
    psg = written(SN76489(), 0x8E, 0x0F, 0x90)
    psg.take_attenuations()
    psg.run(NTSC_CLOCK)
    levels = [sample[0] for sample in psg.take_attenuations()]
    flips = sum(a != b for a, b in pairwise(levels))
    assert flips / 2 == pytest.approx(440.4, abs=0.5)


@pytest.mark.parametrize("variant", [SEGA_VDP_PSG, GAME_GEAR_PSG, SN76489AN])
@pytest.mark.parametrize("period", [0, 1])
def test_low_periods_hold_the_output_high_on_the_master_system_parts(variant, period):
    # "If the register value is zero or one then the output is a constant value of +1"
    # (the wiki, "Tone channels"): used for sample playback.
    psg = written(SN76489(variant), 0x80 | period, 0x00, 0x90)
    psg.take_attenuations()
    psg.run(16 * 200)
    assert {sample[0] for sample in psg.take_attenuations()} == {0}


@pytest.mark.parametrize("period", [0, 1])
def test_low_periods_toggle_once_a_rotation_on_the_ym7101(period):
    # The die compares an up-counter with the period, so 0 and 1 both expire every
    # rotation (Nuked-PSG; the every-clock comparison covers it).
    psg = written(SN76489(YM7101_PSG), 0x80 | period, 0x00, 0x90)
    psg.take_attenuations()
    psg.run(16 * 200)
    levels = [sample[0] for sample in psg.take_attenuations()]
    assert set(levels) == {0, 15}
    assert all(a != b for a, b in pairwise(levels))


def test_noise_rate_three_follows_tone_three():
    psg = written(SN76489(), 0xC0 | 0x5, 0x00, 0xE7)  # tone 3 = $005; white, rate 3
    psg.run(1_000)
    shifts = 0
    for _ in range(16 * 100):
        before = psg.noise
        psg.run(1)
        shifts += psg.noise != before
    # Tone 3's sign flips every 5 rotations and the register shifts on its rising
    # edge: once every 10 rotations, 10 shifts in 100.
    assert shifts == 10


# -- levels and stereo -----------------------------------------------------------------


def test_ideal_levels_are_two_decibels_per_step_and_fifteen_is_silent():
    assert IDEAL_LEVELS[0] == 1.0
    for step in range(14):
        assert IDEAL_LEVELS[step + 1] / IDEAL_LEVELS[step] == pytest.approx(10**-0.1)
    assert IDEAL_LEVELS[15] == 0.0


@pytest.mark.skipif(not NUKED_PSG.exists(), reason="Nuked-PSG is not fetched")
def test_ym7101_levels_are_the_dies():
    """The YM7101's curve is Nuked-PSG's measured one, not 2 dB a step."""
    body = re.search(r"ympsg_vol\[17\] = \{(.*?)\};", NUKED_PSG.read_text(), re.S)
    assert body is not None
    values = [float(value) for value in body.group(1).replace("\n", "").split(",")]
    assert tuple(values[:16]) == YM7101_LEVELS


def test_the_variants_take_their_curves():
    assert YM7101_PSG.levels == YM7101_LEVELS
    assert SEGA_VDP_PSG.levels == IDEAL_LEVELS
    assert set(VARIANTS) == {"SN76489AN", "Sega VDP", "Game Gear", "YM7101"}


def test_without_stereo_both_sides_are_the_sum_of_the_channels():
    psg = written(SN76489(YM7101_PSG), 0x80 | 0x1, 0x00, 0x90)
    psg.write_stereo(0x10)  # ignored: no port $06 here
    assert psg.stereo == 0xFF
    psg.take_samples()
    psg.run(16 * 50)
    samples = psg.take_samples()
    assert all(left == right for left, right in samples)
    assert max(left for left, _ in samples) == pytest.approx(1.0)


def test_game_gear_stereo_routes_each_channel():
    gg = written(SN76489(GAME_GEAR_PSG), 0x80 | 0x1, 0x00, 0x90)  # tone 1 held high
    gg.write_stereo(0x10)  # tone 1 left only
    gg.run(CLOCKS_PER_SAMPLE * 400)
    left, right = gg.take_samples()[-1]
    assert left == pytest.approx(1.0)
    assert right == 0.0


def test_a_stereo_change_keeps_the_samples_already_made():
    gg = written(SN76489(GAME_GEAR_PSG), 0x80 | 0x1, 0x00, 0x90)
    gg.take_samples()
    gg.run(16 * 10)
    gg.write_stereo(0x01)  # tone 1 right only, from here on
    gg.run(16 * 10)
    samples = gg.take_samples()
    assert samples[:10] == [(1.0, 1.0)] * 10
    assert samples[10:] == [(0.0, 1.0)] * 10


def test_the_test_bit_drives_every_channel():
    psg = written(SN76489(YM7101_PSG), 0x92, 0xB4, 0xD6, 0xF8)
    assert psg.attenuations()[3] == 15  # the noise register is still all zero
    psg.write_test(1)
    assert psg.attenuations() == (2, 4, 6, 8)
