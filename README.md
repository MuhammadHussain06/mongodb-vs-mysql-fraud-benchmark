# MongoDB vs MySQL for Fraud Transaction Storage

SEG2102 Database Management Systems – Final Assessment
Muhammad Hussain (23115942), Sunway University

## Overview

This project compares three database designs for storing and querying financial transactions in a fraud-detection setting:

| System | Design |
|---|---|
| MySQL | One row per transaction in a `transactions` table |
| MongoDB (basic) | One document per transaction in `tx_basic` |
| MongoDB (bucketed) | One document per destination account per day in `tx_bucket`, holding that day's transactions plus pre-computed totals (`count`, `total_amount`, `fraud_count`) |

The bucketed design is the proposed solution. It targets per-account fraud lookups (e.g. "how much has this account received in the last 7 days?") by reading a few pre-aggregated documents instead of many individual transactions.

## Dataset

PaySim synthetic mobile-money transactions (6.3M rows, fraud-labelled):
https://www.kaggle.com/datasets/ealaxi/paysim1

Download the CSV and save it as `data/paysim.csv`. The first 100k, 500k and 1M rows are used.

## What is measured

| Test | Description |
|---|---|
| `history` | All transactions received by one account |
| `window_sum` | Count and total amount received by one account over a 7-day window |
| `fraud_by_type` | Count of transactions and fraud cases per transaction type (full scan) |
| `single_insert` | Inserting one new transaction, committed to disk (MySQL autocommit, MongoDB `w:1, j:true`) |
| Bulk load | Time to load N rows into each design |
| Storage | Data and index size on disk |

Read queries run with indexes off and then on (`(name_dest, step)` for MySQL and basic MongoDB, `(account, day)` for bucketed MongoDB). Each query runs against 100 randomly sampled accounts (fixed seed). Before timing, the script checks that all three designs return the same results.

`demo_integrity_access.py` demonstrates:
- **Data integrity:** MySQL `CHECK` constraints and MongoDB `$jsonSchema` validation rejecting an invalid transaction.
- **Access control:** a read-only `analyst` user in both databases that can read but not write.

## Repository layout

```
docker-compose.yml        MySQL and MongoDB containers (2 CPUs, 2 GB RAM, 512 MB cache each)
requirements.txt          Python dependencies
common.py                 Connection settings and shared helpers
load.py                   Loads N rows into all three designs, records bulk load time
bench.py                  Runs the query, insert and storage benchmarks
demo_integrity_access.py  Integrity and access control demo
plot.py                   Builds summary tables and figures, prints headline results
run_all.sh                Full run: load + bench for all sizes, then plot
quick_check.sh            Short reproducibility check at one size, output to results_quick/
make_sample_data.py       Generates a small synthetic PaySim-format CSV (used by CI)
.github/workflows/        GitHub Actions workflow running the quick check
data/                     Place paysim.csv here (not committed)
results/                  Full run output: CSV results, summary table, figures/
results_quick/            Quick check output (same layout as results/)
```

## Requirements

| Component | Version |
|---|---|
| OS | Linux, macOS, or Windows with WSL2 (Ubuntu) |
| Docker | Docker Engine 24+ or Docker Desktop with Compose v2 |
| MySQL | 8.0 (`mysql:8.0` image) |
| MongoDB | 7.0 (`mongo:7.0` image) |
| Python | 3.10+ |
| Python packages | pymongo 4.6+, PyMySQL 1.1+, cryptography 42+, pandas 2.0+, numpy 1.26+, matplotlib 3.8+ |

Hardware: at least 8 GB RAM and ~5 GB free disk.

## Setup

```bash
# 1. Clone and enter the project
git clone https://github.com/MuhammadHussain06/mongodb-vs-mysql-fraud-benchmark.git
cd mongodb-vs-mysql-fraud-benchmark

# 2. Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Dataset
#    Download from Kaggle and save as data/paysim.csv

# 4. Start the databases
docker compose up -d
docker compose ps        # wait until both show "healthy"
```

**WSL2 notes**
- Keep the project inside the Linux filesystem (e.g. `~/seg2102`), not under `/mnt/c`, as cross-filesystem reads are much slower.
- Give WSL at least 6 GB RAM in `C:\Users\<you>\.wslconfig`:
  ```
  [wsl2]
  memory=6GB
  ```

## Running

Full run (all sizes, then figures):

```bash
chmod +x run_all.sh
./run_all.sh 1           # run number 1
./run_all.sh 2           # optional repeat runs
./run_all.sh 3
```

Or step by step:

```bash
python load.py --rows 100000
python bench.py --rows 100000
python load.py --rows 500000
python bench.py --rows 500000
python load.py --rows 1000000
python bench.py --rows 1000000
python plot.py
```

Integrity and access control demo (run after any `load.py`; exits with an error if any check behaves unexpectedly):

```bash
python demo_integrity_access.py
```

Options:

| Script | Option | Default | Meaning |
|---|---|---|---|
| `load.py` | `--rows` | required | Number of CSV rows to load |
| | `--csv` | `data/paysim.csv` | Path to the dataset |
| | `--run` | 1 | Run number recorded in results |
| `bench.py` | `--rows` | required | Rows currently loaded (label) |
| | `--run` | 1 | Run number recorded in results |
| | `--accounts` | 100 | Accounts sampled for lookups |
| | `--reps` | 100 | Repetitions for indexed lookups and inserts |
| | `--slow-reps` | 20 | Repetitions for unindexed lookups and full scans |

A full run takes about 5 minutes on the test machine below; slower hardware will take longer.

## Quick reproducibility check

`quick_check.sh` runs the whole pipeline once at a single size with fewer repetitions, then prints the headline numbers. It takes a few minutes and writes to `results_quick/` (cleared on each run), so it never mixes with the full results in `results/`.

```bash
chmod +x quick_check.sh
./quick_check.sh                       # 100,000 rows from data/paysim.csv
ROWS=50000 ./quick_check.sh            # different size
```

It runs `load.py`, `bench.py`, `demo_integrity_access.py` and `plot.py`, and prints:
- mean latency per query and system (indexes on)
- bulk load time per system
- storage size per system

The script stops with an error if the three designs return different query results or if an integrity/access check does not behave as expected.

To compare with the reported results, check that the relative ordering of the systems matches `results/summary_latency.csv` at the same size. Absolute times will differ between machines.

## Continuous integration

`.github/workflows/quick-check.yml` runs on every push to `main`, on pull requests, and manually from the Actions tab (**Run workflow**). It:

1. Starts MySQL 8.0 and MongoDB 7.0 as service containers.
2. Installs the Python dependencies.
3. Generates a 20,000-row synthetic dataset with `make_sample_data.py` (PaySim requires a Kaggle login, so it is not downloaded in CI).
4. Runs `quick_check.sh` on it.
5. Adds the headline numbers to the run's summary page and uploads `results_quick/` as a downloadable artifact.

CI confirms the code runs end to end and the result and integrity checks pass. Its timings come from shared GitHub runners and are not used in the report.

## Output

All output is written to the project's own `results/` folder (or `results_quick/` for the quick check), regardless of where the scripts are run from.

The committed `results/` folder holds the results reported in the paper: three full runs on an Intel i9-14900HX laptop (16 GB RAM) running Ubuntu on WSL2 (8 GB, 16 CPUs). New runs are appended to these CSVs, so move or delete them first to start a fresh set.

| File | Contents |
|---|---|
| `results/load_times.csv` | Bulk load time per run, size and system |
| `results/latency.csv` | Mean, p50 and p95 latency per run, size, system, query and index setting |
| `results/storage.csv` | Data and index size (MB) per run, size and system |
| `results/summary_latency.csv` | Latency averaged across runs |
| `results/figures/fig1_latency_vs_size.png` | Query latency vs data size (unindexed lookups and full scan) |
| `results/figures/fig2_index_effect.png` | Indexed vs unindexed lookups at the largest size |
| `results/figures/fig3_load_time.png` | Bulk load time per size |
| `results/figures/fig4_single_insert.png` | Single insert latency |
| `results/figures/fig5_storage.png` | Storage size |

## Notes and limitations

- Single-machine, single-node setup; results reflect relative performance, not production throughput.
- Both databases get the same CPU, memory and cache limits so the comparison is fair.
- PaySim is synthetic; real transaction data may have different access patterns.
- Destination accounts (`nameDest`) are used as the lookup key because origin accounts in PaySim rarely repeat.
- The benchmark inserts are removed after each run, so repeated runs use the same data.

## Stopping and cleanup

```bash
docker compose down          # stop containers, keep data
docker compose down -v       # stop and delete database volumes
```

## License

MIT. See [LICENSE](LICENSE).
