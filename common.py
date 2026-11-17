"""Shared connection settings and helpers."""
import csv
import os

import pymysql
from pymongo import MongoClient

MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "rootpass",
    "database": "frauddb",
}
MONGO_URI = "mongodb://root:rootpass@127.0.0.1:27017/?authSource=admin"
MONGO_DB = "frauddb"

# Paths are relative to the project folder, wherever the scripts are run from
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(PROJECT_DIR, "data", "paysim.csv")
# RESULTS_DIR env var selects another output folder (e.g. results_quick)
RESULTS_DIR = os.path.join(PROJECT_DIR, os.environ.get("RESULTS_DIR", "results"))

# PaySim column -> column/field name used in both databases
COLUMNS = {
    "step": "step",
    "type": "type",
    "amount": "amount",
    "nameOrig": "name_orig",
    "oldbalanceOrg": "old_balance_orig",
    "newbalanceOrig": "new_balance_orig",
    "nameDest": "name_dest",
    "oldbalanceDest": "old_balance_dest",
    "newbalanceDest": "new_balance_dest",
    "isFraud": "is_fraud",
    "isFlaggedFraud": "is_flagged_fraud",
}
FIELDS = list(COLUMNS.values())
TX_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]

SYSTEM_LABELS = {
    "mysql": "MySQL",
    "mongo_basic": "MongoDB (basic)",
    "mongo_bucket": "MongoDB (bucketed)",
}


def mysql_conn(**overrides):
    return pymysql.connect(**{**MYSQL_CONFIG, **overrides}, autocommit=True)


def mongo_db(uri=MONGO_URI):
    return MongoClient(uri)[MONGO_DB]


def day_of(step):
    # PaySim steps are hours starting at 1
    return (step - 1) // 24


def append_csv(name, rows, header):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, name)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerows(rows)
