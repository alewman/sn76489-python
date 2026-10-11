#!/usr/bin/env python
"""Seed faults into the chip, one at a time, and check the fast gate catches each.

    python scripts/mutation.py                    # examples and the rule tests
    python scripts/mutation.py --examples-only    # what a port's gate alone catches

A gate that cannot fail proves nothing. Each mutant changes one place in
``src/sn76489_python/chip.py`` -- a rule the chip is known to have, broken the way a
port might break it -- and the gate is the conformance examples
(``examples/conformance/``), which a port runs, plus this chip's own rule tests
(``tests/test_chip.py`` without the referee): what fails first when a rule is broken.
A mutant the gate misses is listed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHIP = ROOT / "src" / "sn76489_python" / "chip.py"

#: (what is broken, the exact text, its replacement)
MUTANTS = [
    ("down-counter style compare", "        if counter >= period:\n", "        if counter > period:\n"),
    ("counters wrap at 9 bits", "self.counter[rot] = (counter + 1) & 0x3FF", "self.counter[rot] = (counter + 1) & 0x1FF"),
    ("noise rates swapped", "NOISE_PERIODS = (0x10, 0x20, 0x40)", "NOISE_PERIODS = (0x20, 0x10, 0x40)"),
    ("rate 3 follows tone 2", "noise_of = (self.sign >> 1) & 1 if (noise_data & 3) == 3", "noise_of = (self.sign >> 2) & 1 if (noise_data & 3) == 3"),
    ("noise shifts on both edges", "elif noise_of and not self.noise_of:", "elif noise_of != self.noise_of:"),
    ("no zero-detect", "bit = 1 if feedback or (noise & self._lfsr_low) == 0 else 0", "bit = 1 if feedback else 0"),
    ("noise output bit one higher", "self._lfsr_out = variant.lfsr_bits - 2", "self._lfsr_out = variant.lfsr_bits - 1"),
    ("taps not mirrored", "return sum(\n            1 << (top - bit)", "return sum(\n            1 << bit"),
    ("a noise write keeps the register", "            self.noise_data = data & 0x07\n            self.noise_trig = 1", "            self.noise_data = data & 0x07"),
    ("data byte ignored after a volume latch", "        if latch & 1:  # 1, 3, 5, 7", "        if latch & 1 and low:  # 1, 3, 5, 7"),
    ("high tone bits shifted by 3", "((data << 4) & 0x3F0)", "((data << 3) & 0x3F0)"),
    ("bit 7 clear moves the latch", "                if self._data & 0x80:\n                    self.latch", "                if True:\n                    self.latch"),
    ("a write misses the data register", "        self._data = value & 0xFF\n        self._write_flag = True", "        self._write_flag = value & 0xFF or 0x100"),
    ("no update in the second phase", "        if self._write_flag_l:\n            self._update_registers()\n        self.rot", "        self.rot"),
    ("signs flip on another step", "        if chan_sel & 1:\n            self.sign ^= self.counter_of & 15", "        if chan_sel & 2:\n            self.sign ^= self.counter_of & 15"),
    ("rotation does not wait for the tones", "(0 if (ic_latch2 & 1) or self.chan_sel & 7 else 1)", "(0 if (ic_latch2 & 1) or self.chan_sel & 3 else 1)"),
    ("prescaler not reset by /IC", "            if self.ic_latch1 == 2:\n                p1 = 0", "            if False:\n                p1 = 0"),
    ("a sample every 15 clocks", "CLOCKS_PER_SAMPLE = 16", "CLOCKS_PER_SAMPLE = 15"),
    ("low periods never hold", "        if self.variant.low_periods_hold_high:", "        if False:"),
    ("hold applies to period 2", "            if freq[0] <= 1:", "            if freq[0] <= 2:"),
    ("test bit ignored", "        if self.test & 1:\n            sign |= 15", "        if False:\n            sign |= 15"),
    ("stereo sides swapped", "                if stereo & (0x10 << channel):\n                    left += level", "                if stereo & (0x01 << channel):\n                    left += level"),
    ("2.5 dB a step", "(*(10 ** (-0.1 * step)", "(*(10 ** (-0.125 * step)"),
]  # fmt: skip


def gate(src: Path, python: str, examples_only: bool = False) -> bool:
    """True when the gate passes (the mutant survives)."""
    rules = []
    if not examples_only:
        rules = ["tests/test_chip.py"]
    env = dict(os.environ, PYTHONPATH=str(src))
    result = subprocess.run(
        # -o pythonpath: pyproject puts the real src first; the mutated copy must win.
        [python, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-o", "pythonpath=tests scripts",
         "-m", "not referee",
         "tests/test_conformance.py::test_this_chip_still_writes_every_reference_trace",
         *rules],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )  # fmt: skip
    return result.returncode == 0


def main() -> int:
    examples_only = "--examples-only" in sys.argv[1:]
    python = sys.executable
    original = CHIP.read_text()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        shutil.copytree(ROOT / "src", src)
        target = src / "sn76489_python" / "chip.py"
        if not gate(src, python):
            print("the unmutated chip fails the gate")
            return 2
        survivors = []
        for name, old, new in MUTANTS:
            if original.count(old) != 1:
                print(f"{name}: the text to mutate is not found exactly once")
                return 2
            target.write_text(original.replace(old, new))
            survived = gate(src, python, examples_only)
            print(f"{'SURVIVED' if survived else 'caught  '}  {name}")
            if survived:
                survivors.append(name)
        print(f"\n{len(MUTANTS) - len(survivors)} of {len(MUTANTS)} mutants caught")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
