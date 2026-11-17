"""Load the first N PaySim rows into MySQL, MongoDB (basic) and MongoDB (bucketed)."""
import argparse
import time

import pandas as pd

from common import (DEFAULT_CSV, FIELDS, COLUMNS, TX_TYPES, append_csv,
                    day_of, mongo_db, mysql_conn)

BATCH = 5000

MYSQL_DDL = """
CREATE TABLE transactions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    step INT NOT NULL,
    type VARCHAR(10) NOT NULL,
    amount DOUBLE NOT NULL,
    name_orig VARCHAR(20) NOT NULL,
    old_balance_orig DOUBLE NOT NULL,
    new_balance_orig DOUBLE NOT NULL,
    name_dest VARCHAR(20) NOT NULL,
    old_balance_dest DOUBLE NOT NULL,
    new_balance_dest DOUBLE NOT NULL,
    is_fraud TINYINT NOT NULL,
    is_flagged_fraud TINYINT NOT NULL,
    CONSTRAINT chk_amount CHECK (amount >= 0),
    CONSTRAINT chk_type CHECK (type IN ('CASH_IN','CASH_OUT','DEBIT','PAYMENT','TRANSFER')),
    CONSTRAINT chk_fraud CHECK (is_fraud IN (0, 1))
)
"""

BASIC_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": FIELDS,
        "properties": {
            "step": {"bsonType": "int", "minimum": 1},
            "type": {"enum": TX_TYPES},
            "amount": {"bsonType": "double", "minimum": 0},
            "name_orig": {"bsonType": "string"},
            "name_dest": {"bsonType": "string"},
            "is_fraud": {"enum": [0, 1]},
        },
    }
}

BUCKET_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["account", "day", "count", "total_amount", "fraud_count", "txs"],
        "properties": {
            "account": {"bsonType": "string"},
            "day": {"bsonType": "int", "minimum": 0},
            "count": {"bsonType": "int", "minimum": 0},
            "total_amount": {"bsonType": "double", "minimum": 0},
            "txs": {"bsonType": "array"},
        },
    }
}


def read_rows(path, rows):
    df = pd.read_csv(path, nrows=rows).rename(columns=COLUMNS)
    float_cols = ["amount", "old_balance_orig", "new_balance_orig",
                  "old_balance_dest", "new_balance_dest"]
    df[float_cols] = df[float_cols].astype(float)
    return df[FIELDS].to_dict("records")


def load_mysql(records):
    conn = mysql_conn()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS transactions")
    cur.execute(MYSQL_DDL)

    sql = (f"INSERT INTO transactions ({', '.join(FIELDS)}) "
           f"VALUES ({', '.join(['%s'] * len(FIELDS))})")
    rows = [tuple(r[f] for f in FIELDS) for r in records]

    start = time.perf_counter()
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, rows[i:i + BATCH])
    elapsed = time.perf_counter() - start
    conn.close()
    return elapsed


def load_mongo_basic(db, records):
    db.drop_collection("tx_basic")
    db.create_collection("tx_basic", validator=BASIC_VALIDATOR)
    docs = [dict(r) for r in records]

    start = time.perf_counter()
    for i in range(0, len(docs), BATCH):
        db.tx_basic.insert_many(docs[i:i + BATCH], ordered=False)
    return time.perf_counter() - start


def build_buckets(records):
    """One document per destination account per day, with running totals."""
    buckets = {}
    for r in records:
        key = (r["name_dest"], day_of(r["step"]))
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = {"account": key[0], "day": key[1], "count": 0,
                                "total_amount": 0.0, "fraud_count": 0, "txs": []}
        b["count"] += 1
        b["total_amount"] += r["amount"]
        b["fraud_count"] += r["is_fraud"]
        b["txs"].append({k: r[k] for k in FIELDS if k != "name_dest"})
    return list(buckets.values())


def load_mongo_bucket(db, records):
    db.drop_collection("tx_bucket")
    db.create_collection("tx_bucket", validator=BUCKET_VALIDATOR)

    # Grouping is part of the load cost for this design, so it is timed
    start = time.perf_counter()
    docs = build_buckets(records)
    for i in range(0, len(docs), BATCH):
        db.tx_bucket.insert_many(docs[i:i + BATCH], ordered=False)
    return time.perf_counter() - start, len(docs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args()

    records = read_rows(args.csv, args.rows)
    print(f"Read {len(records)} rows from {args.csv}")

    db = mongo_db()
    mysql_s = load_mysql(records)
    print(f"MySQL:              {mysql_s:.1f} s")
    basic_s = load_mongo_basic(db, records)
    print(f"MongoDB (basic):    {basic_s:.1f} s")
    bucket_s, n_buckets = load_mongo_bucket(db, records)
    print(f"MongoDB (bucketed): {bucket_s:.1f} s ({n_buckets} bucket documents)")

    append_csv("load_times.csv",
               [[args.run, len(records), "mysql", round(mysql_s, 3)],
                [args.run, len(records), "mongo_basic", round(basic_s, 3)],
                [args.run, len(records), "mongo_bucket", round(bucket_s, 3)]],
               ["run", "rows", "system", "seconds"])


if __name__ == "__main__":
    main()
