#!/bin/sh
# Build the PSG referee from the pinned die-derived source in reference/src/
# (fetched by scripts/fetch_references.py, never committed here).
#
#   sh validation/build_referees.sh
#
# The binary lands in reference/build-referees/ (git-ignored). Nothing of the
# referee's source is copied into this repository: validation/psg_ref.c only drives it.
#
# Licence: Nuked-PSG GPL-2.0+. The binary is built locally and run as a referee; it is
# not distributed.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
src="$root/reference/src"
out="$root/reference/build-referees"
mkdir -p "$out"

CC=${CC:-gcc}
CFLAGS=${CFLAGS:--O2 -w}
$CC --version | head -n 1

echo "psg_ref   (Nuked-PSG @ d15a168)"
$CC $CFLAGS -I "$src/Nuked-PSG" -o "$out/psg_ref" \
    "$root/validation/psg_ref.c" "$src/Nuked-PSG/ympsg.c"

echo "built in $out"
