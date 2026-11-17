"""Benchmark read queries, single inserts and storage for the three designs."""
import argparse
import math
import random
import time

import numpy as np
from pymongo import WriteConcern

from common import FIELDS, append_csv, day_of, mongo_db, mysql_conn

WARMUP = 5
WINDOW_DAYS = 7
BENCH_TAG = "BENCH"
LATENCY_HEADER = ["run", "rows", "system", "query", "indexed", "reps",
                  "mean_ms", "p50_ms", "p95_ms"]


# ---------- queries ----------
# Each query function takes one sampled account and returns a comparable result.

def mysql_queries(cur):
    def history(a):
        cur.execute("SELECT * FROM transactions WHERE name_dest = %s", (a["account"],))
        return len(cur.fetchall())

    def window_sum(a):
        cur.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions "
                    "WHERE name_dest = %s AND step BETWEEN %s AND %s",
                    (a["account"], a["lo_step"], a["hi_step"]))
        count, total = cur.fetchone()
        return int(count), float(total)

    def fraud_by_type(_):
        cur.execute("SELECT type, COUNT(*), SUM(is_fraud) FROM transactions GROUP BY type")
        return sorted((t, int(c), int(f)) for t, c, f in cur.fetchall())

    return {"history": history, "window_sum": window_sum, "fraud_by_type": fraud_by_type}


def basic_queries(coll):
    def history(a):
        return len(list(coll.find({"name_dest": a["account"]})))

    def window_sum(a):
        res = list(coll.aggregate([
            {"$match": {"name_dest": a["account"],
                        "step": {"$gte": a["lo_step"], "$lte": a["hi_step"]}}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "total": {"$sum": "$amount"}}},
        ]))
        return (res[0]["count"], float(res[0]["total"])) if res else (0, 0.0)

    def fraud_by_type(_):
        res = coll.aggregate([
            {"$group": {"_id": "$type", "count": {"$sum": 1}, "fraud": {"$sum": "$is_fraud"}}},
        ])
        return sorted((r["_id"], r["count"], r["fraud"]) for r in res)

    return {"history": history, "window_sum": window_sum, "fraud_by_type": fraud_by_type}


def bucket_queries(coll):
    def history(a):
        txs = [t for b in coll.find({"account": a["account"]}) for t in b["txs"]]
        return len(txs)

    def window_sum(a):
        # Uses the per-day totals instead of reading each transaction
        res = list(coll.aggregate([
            {"$match": {"account": a["account"],
                        "day": {"$gte": a["lo_day"], "$lte": a["hi_day"]}}},
            {"$group": {"_id": None, "count": {"$sum": "$count"},
                        "total": {"$sum": "$total_amount"}}},
        ]))
        return (res[0]["count"], float(res[0]["total"])) if res else (0, 0.0)

    def fraud_by_type(_):
        res = coll.aggregate([
            {"$unwind": "$txs"},
            {"$group": {"_id": "$txs.type", "count": {"$sum": 1},
                        "fraud": {"$sum": "$txs.is_fraud"}}},
        ])
        return sorted((r["_id"], r["count"], r["fraud"]) for r in res)

    return {"history": history, "window_sum": window_sum, "fraud_by_type": fraud_by_type}


# ---------- indexes ----------

def drop_indexes(cur, db):
    cur.execute("SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'transactions' "
                "AND index_name = 'idx_dest_step'")
    if cur.fetchone()[0]:
        cur.execute("DROP INDEX idx_dest_step ON transactions")
    db.tx_basic.drop_indexes()
    db.tx_bucket.drop_indexes()


def create_indexes(cur, db):
    cur.execute("CREATE INDEX idx_dest_step ON transactions (name_dest, step)")
    db.tx_basic.create_index([("name_dest", 1), ("step", 1)])
    db.tx_bucket.create_index([("account", 1), ("day", 1)])


# ---------- helpers ----------

def sample_accounts(cur, n, seed=42):
    """Destination accounts with at least 2 transactions, plus a 7-day window ending on their last day."""
    cur.execute("SELECT name_dest, MAX(step) FROM transactions "
                "GROUP BY name_dest HAVING COUNT(*) >= 2 ORDER BY name_dest")
    rows = cur.fetchall()
    picked = random.Random(seed).sample(rows, min(n, len(rows)))
    accounts = []
    for name, max_step in picked:
        hi_day = day_of(max_step)
        lo_day = max(hi_day - WINDOW_DAYS + 1, 0)
        accounts.append({"account": name, "lo_day": lo_day, "hi_day": hi_day,
                         "lo_step": lo_day * 24 + 1, "hi_step": (hi_day + 1) * 24})
    return accounts


def measure(fn, accounts, reps):
    for a in accounts[:WARMUP]:
        fn(a)
    times = []
    for i in range(reps):
        a = accounts[i % len(accounts)]
        start = time.perf_counter()
        fn(a)
        times.append((time.perf_counter() - start) * 1000)
    return times


def summarise(times):
    arr = np.array(times)
    return [len(arr), round(arr.mean(), 3), round(np.percentile(arr, 50), 3),
            round(np.percentile(arr, 95), 3)]


def same(a, b):
    if isinstance(a, tuple) and len(a) == 2 and isinstance(a[1], float):
        return a[0] == b[0] and math.isclose(a[1], b[1], rel_tol=1e-9, abs_tol=0.01)
    return a == b


def check_results(systems, accounts):
    """All three designs must return the same answer before timing them."""
    ok = True
    for query in ["history", "window_sum", "fraud_by_type"]:
        for a in accounts[:10]:
            results = {name: q[query](a) for name, q in systems.items()}
            ref = results["mysql"]
            if not all(same(ref, r) for r in results.values()):
                print(f"  MISMATCH {query} {a['account']}: {results}")
                ok = False
    print("  Result check:", "OK" if ok else "FAILED")
    return ok


# ---------- single inserts ----------

def bench_inserts(cur, db, accounts, reps):
    """Insert single transactions one at a time, each durably committed."""
    basic = db.tx_basic.with_options(write_concern=WriteConcern(w=1, j=True))
    bucket = db.tx_bucket.with_options(write_concern=WriteConcern(w=1, j=True))
    sql = (f"INSERT INTO transactions ({', '.join(FIELDS)}) "
           f"VALUES ({', '.join(['%s'] * len(FIELDS))})")

    def make_tx(i):
        a = accounts[i % len(accounts)]
        return {"step": a["hi_step"], "type": "TRANSFER", "amount": 100.0,
                "name_orig": f"{BENCH_TAG}{i}", "old_balance_orig": 0.0,
                "new_balance_orig": 0.0, "name_dest": a["account"],
                "old_balance_dest": 0.0, "new_balance_dest": 0.0,
                "is_fraud": 0, "is_flagged_fraud": 0}

    def ins_mysql(tx):
        cur.execute(sql, tuple(tx[f] for f in FIELDS))

    def ins_basic(tx):
        basic.insert_one(dict(tx))

    def ins_bucket(tx):
        # Appends to the account's existing day bucket and updates its totals
        bucket.update_one(
            {"account": tx["name_dest"], "day": day_of(tx["step"])},
            {"$inc": {"count": 1, "total_amount": tx["amount"], "fraud_count": tx["is_fraud"]},
             "$push": {"txs": {k: tx[k] for k in FIELDS if k != "name_dest"}}},
            upsert=True)

    results = {}
    for name, fn in [("mysql", ins_mysql), ("mongo_basic", ins_basic),
                     ("mongo_bucket", ins_bucket)]:
        times = []
        for i in range(reps):
            tx = make_tx(i)
            start = time.perf_counter()
            fn(tx)
            times.append((time.perf_counter() - start) * 1000)
        results[name] = times

    # Remove the benchmark rows so the dataset is unchanged
    cur.execute("DELETE FROM transactions WHERE name_orig LIKE %s", (f"{BENCH_TAG}%",))
    db.tx_basic.delete_many({"name_orig": {"$regex": f"^{BENCH_TAG}"}})
    per_bucket = {}
    for i in range(reps):
        tx = make_tx(i)
        key = (tx["name_dest"], day_of(tx["step"]))
        per_bucket[key] = per_bucket.get(key, 0) + 1
    for (account, day), k in per_bucket.items():
        db.tx_bucket.update_one(
            {"account": account, "day": day},
            {"$pull": {"txs": {"name_orig": {"$regex": f"^{BENCH_TAG}"}}},
             "$inc": {"count": -k, "total_amount": -100.0 * k}})
    return results


# ---------- storage ----------

def storage_stats(cur, db):
    cur.execute("ANALYZE TABLE transactions")
    cur.fetchall()
    cur.execute("SELECT data_length, index_length FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'transactions'")
    data, index = cur.fetchone()
    stats = {"mysql": (data, index)}
    for name, coll in [("mongo_basic", "tx_basic"), ("mongo_bucket", "tx_bucket")]:
        s = next(db[coll].aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
        stats[name] = (s["storageSize"], s["totalIndexSize"])
    return stats


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True, help="rows currently loaded (label for results)")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--accounts", type=int, default=100)
    parser.add_argument("--reps", type=int, default=100, help="reps for indexed lookups and inserts")
    parser.add_argument("--slow-reps", type=int, default=20, help="reps for unindexed lookups and full scans")
    args = parser.parse_args()

    conn = mysql_conn()
    cur = conn.cursor()
    db = mongo_db()

    cur.execute("SELECT COUNT(*) FROM transactions")
    loaded = cur.fetchone()[0]
    if loaded != args.rows:
        print(f"Warning: {loaded} rows loaded but --rows is {args.rows}")

    accounts = sample_accounts(cur, args.accounts)
    print(f"Sampled {len(accounts)} accounts")

    systems = {"mysql": mysql_queries(cur),
               "mongo_basic": basic_queries(db.tx_basic),
               "mongo_bucket": bucket_queries(db.tx_bucket)}

    rows = []
    for indexed in [False, True]:
        print(f"\nPhase: indexes {'ON' if indexed else 'OFF'}")
        drop_indexes(cur, db)
        if indexed:
            create_indexes(cur, db)
        if not check_results(systems, accounts):
            raise SystemExit("Designs returned different results; stopping.")

        for name, queries in systems.items():
            for query, fn in queries.items():
                slow = query == "fraud_by_type" or not indexed
                stats = summarise(measure(fn, accounts, args.slow_reps if slow else args.reps))
                rows.append([args.run, args.rows, name, query, indexed, *stats])
                print(f"  {name:<13} {query:<14} mean {stats[1]:>9.3f} ms  p95 {stats[3]:>9.3f} ms")

    print("\nSingle inserts (indexes ON)")
    for name, times in bench_inserts(cur, db, accounts, args.reps).items():
        stats = summarise(times)
        rows.append([args.run, args.rows, name, "single_insert", True, *stats])
        print(f"  {name:<13} mean {stats[1]:>9.3f} ms  p95 {stats[3]:>9.3f} ms")

    append_csv("latency.csv", rows, LATENCY_HEADER)

    storage = storage_stats(cur, db)
    append_csv("storage.csv",
               [[args.run, args.rows, name, round(d / 1e6, 2), round(i / 1e6, 2)]
                for name, (d, i) in storage.items()],
               ["run", "rows", "system", "data_mb", "index_mb"])
    print("\nStorage (MB data / index)")
    for name, (d, i) in storage.items():
        print(f"  {name:<13} {d / 1e6:>8.1f} / {i / 1e6:>8.1f}")

    conn.close()


if __name__ == "__main__":
    main()
