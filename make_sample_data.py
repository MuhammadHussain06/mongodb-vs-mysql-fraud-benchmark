"""Generate a small synthetic CSV with the PaySim column layout (used by CI)."""
import argparse
import csv
import random

from common import TX_TYPES

HEADER = ["step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
          "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=20000)
    parser.add_argument("--accounts", type=int, default=3000, help="distinct destination accounts")
    parser.add_argument("--out", default="data/sample.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for i in range(args.rows):
            amount = round(rng.uniform(1, 100000), 2)
            old_balance = round(rng.uniform(0, 200000), 2)
            writer.writerow([
                1 + i * 743 // args.rows,  # steps spread over PaySim's 743 hours
                rng.choice(TX_TYPES),
                amount,
                f"C{1000000 + i}",
                old_balance,
                round(max(old_balance - amount, 0.0), 2),
                f"C{rng.randrange(args.accounts)}",
                0.0,
                amount,
                int(rng.random() < 0.01),
                0,
            ])
    print(f"Wrote {args.rows} rows to {args.out}")


if __name__ == "__main__":
    main()
