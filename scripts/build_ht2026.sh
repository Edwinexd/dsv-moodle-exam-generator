#!/bin/sh
# Build all three IDSV HT2026 exam groups (2026-09-26) and validate them.
# Each group has its own seed, machine-language problem and CodeRunner question.
set -e
cd "$(dirname "$0")/.."
OUT="${1:-$HOME/Downloads/iexam-dsv-2026-09-26}"
DATE=2026-09-26

build() {   # group, start, end
    python3 build_idsv.py --config "courses/idsv_ht2026_g$1.json" \
        --date "$DATE" --start "$2" --end "$3" \
        -o "$OUT/idsv_ht2026_g$1_${DATE}_$2-$3.mbz"
}

build 1 08:00 11:00
build 2 12:00 15:00
build 3 16:00 19:00

python3 scripts/validate_mbz.py "$OUT"/idsv_ht2026_g*_"$DATE"_*.mbz
