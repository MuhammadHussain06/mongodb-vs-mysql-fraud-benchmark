#!/usr/bin/env bash
# Short reproducibility check: one size, fewer repetitions, separate output folder.
# Usage: ./quick_check.sh
# Optional env vars: ROWS (default 100000), CSV (default data/paysim.csv)
set -euo pipefail
cd "$(dirname "$0")"

ROWS=${ROWS:-100000}
CSV=${CSV:-data/paysim.csv}
export RESULTS_DIR=results_quick

# Fresh output each time so results are not mixed with older checks
rm -rf "$RESULTS_DIR"

python load.py --rows "$ROWS" --csv "$CSV"
python bench.py --rows "$ROWS" --accounts 50 --reps 30 --slow-reps 5
python demo_integrity_access.py
python plot.py
