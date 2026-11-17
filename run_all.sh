#!/usr/bin/env bash
# Load and benchmark each data size, then build figures.
# Usage: ./run_all.sh [run_number]
set -euo pipefail
cd "$(dirname "$0")"

RUN=${1:-1}
SIZES=(100000 500000 1000000)

for rows in "${SIZES[@]}"; do
  echo "=== Run $RUN, $rows rows ==="
  python load.py --rows "$rows" --run "$RUN"
  python bench.py --rows "$rows" --run "$RUN"
done

python plot.py
