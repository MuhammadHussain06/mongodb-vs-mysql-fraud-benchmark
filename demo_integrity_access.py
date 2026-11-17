"""Show data integrity rules and read-only access control in MySQL and MongoDB."""
import sys

import pymysql
from pymongo import MongoClient
from pymongo.errors import OperationFailure, WriteError

from common import MONGO_DB, mongo_db, mysql_conn

ANALYST_USER = "analyst"
ANALYST_PASS = "analystpass"

BAD_TX = {"step": 1, "type": "REFUND", "amount": -50.0, "name_orig": "C1",
          "old_balance_orig": 0.0, "new_balance_orig": 0.0, "name_dest": "C2",
          "old_balance_dest": 0.0, "new_balance_dest": 0.0,
          "is_fraud": 0, "is_flagged_fraud": 0}

GOOD_TX = {**BAD_TX, "type": "TRANSFER", "amount": 50.0, "name_orig": "DEMO"}

failures = []


def report(label, fn, expect):
    """Run fn and check whether it was ALLOWED or BLOCKED as expected."""
    try:
        fn()
        outcome, detail = "ALLOWED", ""
    except (pymysql.err.MySQLError, WriteError, OperationFailure) as e:
        outcome, detail = "BLOCKED", f"\n            -> {str(e)[:150]}"
    print(f"  [{outcome}] {label}{detail}")
    if outcome != expect:
        failures.append(f"{label}: expected {expect}, got {outcome}")


def mysql_insert(cur, tx):
    cols = ", ".join(tx)
    cur.execute(f"INSERT INTO transactions ({cols}) VALUES ({', '.join(['%s'] * len(tx))})",
                tuple(tx.values()))


def integrity():
    print("\n== Data integrity: insert a transaction with negative amount and invalid type ==")
    cur = mysql_conn().cursor()
    db = mongo_db()
    report("MySQL CHECK constraints", lambda: mysql_insert(cur, BAD_TX), "BLOCKED")
    report("MongoDB (basic) schema validation",
           lambda: db.tx_basic.insert_one(dict(BAD_TX)), "BLOCKED")
    report("MongoDB (bucketed) schema validation", lambda: db.tx_bucket.insert_one(
        {"account": "C2", "day": 0, "count": 1, "total_amount": -50.0,
         "fraud_count": 0, "txs": []}), "BLOCKED")


def create_users():
    cur = mysql_conn().cursor()
    cur.execute(f"CREATE USER IF NOT EXISTS '{ANALYST_USER}'@'%' IDENTIFIED BY '{ANALYST_PASS}'")
    cur.execute(f"GRANT SELECT ON frauddb.* TO '{ANALYST_USER}'@'%'")

    db = mongo_db()
    if not db.command("usersInfo", ANALYST_USER)["users"]:
        db.command("createUser", ANALYST_USER, pwd=ANALYST_PASS,
                   roles=[{"role": "read", "db": MONGO_DB}])


def access_control():
    print("\n== Access control: read-only 'analyst' user ==")
    create_users()

    cur = mysql_conn(user=ANALYST_USER, password=ANALYST_PASS).cursor()
    report("MySQL analyst SELECT", lambda: cur.execute("SELECT COUNT(*) FROM transactions"), "ALLOWED")
    report("MySQL analyst INSERT", lambda: mysql_insert(cur, GOOD_TX), "BLOCKED")

    uri = f"mongodb://{ANALYST_USER}:{ANALYST_PASS}@127.0.0.1:27017/?authSource={MONGO_DB}"
    db = MongoClient(uri)[MONGO_DB]
    report("MongoDB analyst find", lambda: db.tx_basic.find_one(), "ALLOWED")
    report("MongoDB analyst insert", lambda: db.tx_basic.insert_one(dict(GOOD_TX)), "BLOCKED")


if __name__ == "__main__":
    integrity()
    access_control()
    if failures:
        print("\nUnexpected outcomes:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("\nAll integrity and access control checks behaved as expected.")
