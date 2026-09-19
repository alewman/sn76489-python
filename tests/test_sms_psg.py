"""The SN76489 against the wiki's rules and its published noise bit patterns."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from sms_python.psg import (
    CYCLES_PER_TICK,
    GAME_GEAR_PSG,
    PSG,
    SEGA_VDP_PSG,
    SN76489AN,
    VOLUME_TABLE,
)

ATTACH = Path(__file__).resolve().parents[1] / "reference" / "smspower-attach"


def lfsr_period(variant, white: bool) -> int:
    psg = PSG(variant)
    psg.write(0xE4 if white else 0xE0)
    start, steps = psg.lfsr, 0
    while True:
        psg._shift()
        steps += 1
        if psg.lfsr == start:
            return steps


def test_white_noise_periods():
    # 2^15 - 1 for the discrete part; 57,337 for the Sega 16-bit $0009 register,
    # which is not maximal (docs/undocumented-behavior.md, open item 6).
    assert lfsr_period(SN76489AN, white=True) == 32_767
    assert lfsr_period(SEGA_VDP_PSG, white=True) == 57_337


def test_periodic_noise_is_the_register_width():
    # Periodic noise taps bit 0 only: a one-bit loop the width of the register.
    assert lfsr_period(SN76489AN, white=False) == 15
    assert lfsr_period(SEGA_VDP_PSG, white=False) == 16


def _pattern(name: str) -> bytes:
    archive = ATTACH / f"{name.replace(' ', '')}.zip"
    if not archive.exists():
        pytest.skip(f"{archive} not fetched (scripts/fetch_references.py)")
    with zipfile.ZipFile(archive) as bundle:
        (member,) = bundle.namelist()
        return bundle.read(member)


def test_discrete_noise_matches_the_wikis_bit_pattern():
    # The wiki's download labelled "Sega VDP white noise" is, bit for bit, the 15-bit
    # $0003 sequence from reset; its "SN76489 white noise" is the same sequence
    # inverted and rotated. Neither is the 16-bit $0009 sequence the page describes.
    # Recorded in docs/undocumented-behavior.md, open item 6.
    psg = PSG(SN76489AN)
    psg.write(0xE4)
    bits = bytearray()
    for _ in range(32_767):
        psg._shift()
        bits.append(psg.outputs[3])
    assert bytes(bits) == _pattern("SegaVDP WhiteNoise")
    ti = _pattern("SN76489 WhiteNoise")
    doubled = bytes(1 - bit for bit in bits) * 2
    assert ti in doubled


def test_tone_latch_then_data_byte():
    psg = PSG()
    psg.write(0x80 | 0x0E)  # latch channel 0 tone, low 4 bits = $E
    psg.write(0x0F)  # data: high 6 bits = $0F
    assert psg.tone[0] == 0x0FE
    psg.write(0x80 | 0x20 | 0x05)  # channel 1 tone low bits only
    assert psg.tone[1] == 0x005
    assert psg.tone[0] == 0x0FE


def test_data_byte_after_a_volume_latch_sets_the_volume():
    psg = PSG()
    psg.write(0x90 | 0x3)  # channel 0 volume 3
    assert psg.volume[0] == 3
    psg.write(0x07)  # data byte: low 4 bits update the latched volume
    assert psg.volume[0] == 7


def test_data_byte_after_a_noise_latch_is_not_ignored():
    # "The data byte is NOT ignored. If it is, some games (e.g. Micro Machines)
    # produce the wrong sound on their noise channel."
    psg = PSG()
    psg.write(0xE5)
    assert psg.noise == 0b101
    psg.lfsr = 0x1234
    psg.write(0x04)
    assert psg.noise == 0b100
    assert psg.lfsr == 0x8000  # every noise-register write resets the register


def test_power_up_is_silent_with_zeroed_registers():
    psg = PSG()
    assert psg.tone == [0, 0, 0]
    assert psg.noise == 0
    assert psg.volume == [15, 15, 15, 15]


def test_volume_table_is_two_decibels_per_step_and_fifteen_is_silent():
    assert VOLUME_TABLE[0] == 1.0
    for step in range(14):
        assert VOLUME_TABLE[step + 1] / VOLUME_TABLE[step] == pytest.approx(10**-0.1)
    assert VOLUME_TABLE[15] == 0.0


def count_flips(psg: PSG, channel: int, ticks: int) -> int:
    flips, last = 0, psg.outputs[channel]
    for _ in range(ticks):
        psg._tick()
        if psg.outputs[channel] != last:
            flips += 1
            last = psg.outputs[channel]
    return flips


def test_tone_register_0x0fe_is_440_hz():
    # "0x0fe gives 440.4Hz" at 3,579,545 Hz: one flip per 254 ticks, two per cycle.
    psg = PSG()
    psg.write(0x8E)
    psg.write(0x0F)
    ticks_per_second = 3_579_545 // CYCLES_PER_TICK
    flips = count_flips(psg, 0, ticks_per_second)
    assert flips / 2 == pytest.approx(440.4, abs=0.5)


@pytest.mark.parametrize("period", [0, 1])
def test_tone_register_zero_or_one_holds_the_output_high(period):
    psg = PSG()
    psg.write(0x80 | period)
    psg.write(0x00)
    for _ in range(100):
        psg._tick()
        assert psg.outputs[0] == 1


def test_noise_rate_three_follows_tone_two():
    psg = PSG()
    psg.write(0xC0 | 0x5)  # tone 2 = $005
    psg.write(0x00)
    psg.write(0xE7)  # white noise, rate 3
    shifts = 0
    for _ in range(100):
        before = psg.lfsr
        psg._tick()
        shifts += psg.lfsr != before  # a non-zero register always changes on a shift
    # The counter reloads every 5 ticks and the register shifts on every second
    # reload: 10 shifts in 100 ticks.
    assert shifts == 10


def test_stereo_register_only_exists_on_the_game_gear():
    sms = PSG(SEGA_VDP_PSG)
    sms.write_stereo(0x0F)
    assert sms.stereo == 0xFF
    gg = PSG(GAME_GEAR_PSG)
    gg.write_stereo(0x0F)
    assert gg.stereo == 0x0F


def test_game_gear_stereo_routes_each_channel():
    gg = PSG(GAME_GEAR_PSG, sample_rate=44_100)
    gg.write(0x80 | 0x1)  # tone 0 = 1: constant +1
    gg.write(0x00)
    gg.write(0x90)  # channel 0 full volume
    gg.write_stereo(0x10)  # channel 0 left only
    gg.run(CYCLES_PER_TICK * 400)
    left, right = gg.take_samples()[-1]
    assert left == pytest.approx(0.25)
    assert right == 0.0


def test_one_second_gives_the_sample_rate():
    psg = PSG(sample_rate=44_100)
    psg.run(3_579_545)
    assert abs(len(psg.take_samples()) - 44_100) <= 1
