"""sn76489-python: a readable, pure-Python SN76489 PSG reference core.

The chip is :class:`SN76489`; its variants are :data:`SN76489AN` (the discrete TI
part), :data:`SEGA_VDP_PSG` (the Master System's), :data:`GAME_GEAR_PSG` and
:data:`YM7101_PSG` (the Mega Drive's). The contract -- the port, the time unit, the
outputs -- is docs/contract.md.
"""

from sn76489_python.chip import (
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

__all__ = [
    "CLOCKS_PER_SAMPLE",
    "GAME_GEAR_PSG",
    "IDEAL_LEVELS",
    "SEGA_VDP_PSG",
    "SN76489",
    "SN76489AN",
    "VARIANTS",
    "YM7101_LEVELS",
    "YM7101_PSG",
    "PSGVariant",
]
__version__ = "0.1.0.dev0"
