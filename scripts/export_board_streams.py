#!/usr/bin/env python
"""Export the write streams a board's PSG receives, as event files.

    ../megadrive-python/.venv-pypy/bin/python scripts/export_board_streams.py \\
        --board ../megadrive-python
    ../sms-python/.venv-pypy/bin/python scripts/export_board_streams.py --board ../sms-python

Run it with the board's own interpreter, so the board's dependencies (its CPU cores)
import. The stream is the board's own: every byte written to the PSG's port, at the
input clock the board's PSG had reached when it arrived, so a replay into a fresh chip
sees each write on the clock the board's did (scripts/run_psg_compare.py
``--streams``). Only the data port is recorded: the Game Gear's stereo port is
outside the referee's chip.

This needs the board (``--board``: a checkout; its ``src`` goes on the path) and the
ROMs. The files land in ``validation/streams/`` (ignored), each with a ``.json``
beside it: the image's SHA-256, the machine, the frames run, the buttons. They are
derived from ROMs and are never committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import referees

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "validation" / "streams"
#: The ROMs sit beside the checkouts, as the boards do (``--roms`` to point elsewhere).
ROMS = ROOT.parent / "roms"

#: megadrive-python's five milestone cartridges: (file, frames Start is pressed at,
#: frames). Gunstar Heroes wants Start twice -- title, then mode select.
MEGA_DRIVE = [
    ("Sonic The Hedgehog (USA, Europe).zip", (120,), 720),
    ("Streets of Rage 2 (USA).zip", (240,), 720),
    ("Gunstar Heroes (USA).zip", (200, 400, 600), 1200),
    ("Castlevania - Bloodlines (USA).zip", (240,), 720),
    ("Phantasy Star IV (USA).zip", (240,), 720),
]

#: sms-python's: (machine, directory, file, frames button 1 / Start is pressed at,
#: frames). Micro Machines is the wiki's case for the noise data byte.
MASTER_SYSTEM = [
    ("sms2", "mastersystem", "Sonic The Hedgehog (USA, Europe, Brazil) (En).zip", (240,), 900),
    ("sms2", "mastersystem", "Alex Kidd in Miracle World (USA, Europe).zip", (240,), 900),
    ("sms2", "mastersystem", "After Burner (World).zip", (300,), 900),
    ("sms2", "mastersystem", "Micro Machines (Europe).zip", (300, 400), 900),
    ("sms2", "mastersystem", "Phantasy Star (USA, Europe) (Rev A).zip", (240,), 900),
    ("gamegear", "gamegear", "Shinobi II - The Silent Fury (World).zip", (240,), 900),
    ("gamegear", "gamegear", "Columns (USA, Europe, Brazil) (En).zip", (240,), 900),
    ("sg1000", "sg1000", "Flicky (Japan, New Zealand) (Ja).zip", (240,), 900),
]


def load_image(path: Path, suffixes: tuple[str, ...]) -> bytes:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if Path(name).suffix.lower() in suffixes:
                    return archive.read(name)
    return path.read_bytes()


def capture_mega_drive(image: bytes, frames: int, press_at: tuple[int, ...]):
    from megadrive_python.cartridge import Cartridge
    from megadrive_python.io import BUTTONS
    from megadrive_python.machine import MACHINES
    from megadrive_python.system import System

    system = System(MACHINES["genesis"], Cartridge(image))
    board = system.board
    psg = board.psg
    board.fm.enabled = False  # the PSG's stream does not depend on the FM's output
    writes: list[tuple[int, int]] = []
    psg_write = psg.write

    def spy(value: int) -> None:
        writes.append((psg.clock, value & 0xFF))
        psg_write(value)

    psg.write = spy  # type: ignore[method-assign]
    pad = board.io.ports[0].device
    for frame in range(frames):
        pad.pressed = BUTTONS["start"] if any(at <= frame < at + 8 for at in press_at) else 0
        system.run_frame()
        board.fm.take_samples()
        psg.take_samples()
    return writes


def capture_master_system(machine: str, image: bytes, frames: int, press_at: tuple[int, ...]):
    from sms_python.board import MACHINES
    from sms_python.cartridge import Cartridge
    from sms_python.io import BUTTON_1
    from sms_python.system import System

    # The PSG's clocks are the CPU's cycles; with audio off the board does not run its
    # generator, and the write stream does not depend on it.
    system = System(MACHINES[machine], Cartridge.from_file_image(image), audio=False)
    board = system.board
    psg = board.psg
    writes: list[tuple[int, int]] = []
    psg_write = psg.write

    def spy(value: int) -> None:
        writes.append((board.cycles, value & 0xFF))
        psg_write(value)

    psg.write = spy  # type: ignore[method-assign]
    for frame in range(frames):
        pressed = any(at <= frame < at + 8 for at in press_at)
        board.io.pad1.pressed = {BUTTON_1} if pressed else set()
        board.gg_ports.start_pressed = pressed
        system.run_frame()
    return writes


def save(name: str, machine: str, image: bytes, frames: int, press_at, writes) -> None:
    stem = f"{machine}-{Path(name).stem}"
    OUT.mkdir(parents=True, exist_ok=True)
    referees.write_events(OUT / f"{stem}.bin", writes)
    meta = {
        "name": name,
        "machine": machine,
        "sha256": hashlib.sha256(image).hexdigest(),
        "frames": frames,
        "press_at": list(press_at),
        "writes": len(writes),
        "last_clock": writes[-1][0] if writes else 0,
    }
    (OUT / f"{stem}.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{stem}: {len(writes):,} writes -> validation/streams/{stem}.bin")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--board", type=Path, required=True, help="a board checkout")
    parser.add_argument("--roms", type=Path, default=ROMS)
    args = parser.parse_args(argv)
    board = args.board.resolve()
    sys.path.insert(0, str(board / "src"))
    commit = subprocess.run(
        ["git", "-C", str(board), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if (board / "src" / "megadrive_python").exists():
        print(f"board: megadrive-python {commit}")
        for name, press_at, frames in MEGA_DRIVE:
            path = args.roms / "megadrive" / name
            if not path.exists():
                print(f"{name}: missing")
                continue
            image = load_image(path, (".md", ".gen", ".bin", ".smd"))
            save(
                name,
                "genesis",
                image,
                frames,
                press_at,
                capture_mega_drive(image, frames, press_at),
            )
    elif (board / "src" / "sms_python").exists():
        print(f"board: sms-python {commit}")
        for machine, folder, name, press_at, frames in MASTER_SYSTEM:
            path = args.roms / folder / name
            if not path.exists():
                print(f"{name}: missing")
                continue
            image = load_image(path, (".sms", ".gg", ".sg", ".bin"))
            writes = capture_master_system(machine, image, frames, press_at)
            save(name, machine, image, frames, press_at, writes)
    else:
        raise SystemExit(f"{board}: neither megadrive-python nor sms-python")
    return 0


if __name__ == "__main__":
    sys.exit(main())
