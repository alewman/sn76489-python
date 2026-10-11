"""The README's minimal host: tone 1 at 440 Hz for a tenth of a second."""

from sn76489_python import SN76489, YM7101_PSG

CLOCK = 3_579_545  # the PSG's input clock on an NTSC Master System or Mega Drive

chip = SN76489(YM7101_PSG)
for byte in (0x8E, 0x0F, 0x90):  # tone 1 period $0FE (440 Hz), attenuation 0
    chip.write(byte)
    chip.run(32)  # a write reaches its register on the next clock; leave a few

chip.run(CLOCK // 10)  # a tenth of a second
samples = chip.take_samples()  # [(left, right), ...] at CLOCK / 16 = 223,722 Hz
print(f"{len(samples):,} samples, peak {max(left for left, _ in samples):.2f}")
