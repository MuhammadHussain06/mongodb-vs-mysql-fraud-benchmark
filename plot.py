"""Build summary tables and figures from the CSVs in results/."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import RESULTS_DIR, SYSTEM_LABELS

FIG_DIR = os.path.join(RESULTS_DIR, "figures")
SYSTEMS = list(SYSTEM_LABELS)
QUERY_LABELS = {
    "history": "Account history",
    "window_sum": "7-day window sum",
    "fraud_by_type": "Fraud count by type",
    "single_insert": "Single insert",
}


def read(name):
    return pd.read_csv(os.path.join(RESULTS_DIR, name))


def grouped_bars(ax, df, groups, value, group_labels):
    """Bars per group, one bar per system."""
    width = 0.8 / len(SYSTEMS)
    for i, system in enumerate(SYSTEMS):
        vals = [df.loc[(df["group"] == g) & (df["system"] == system), value].mean() for g in groups]
        pos = [x + (i - (len(SYSTEMS) - 1) / 2) * width for x in range(len(groups))]
        ax.bar(pos, vals, width, label=SYSTEM_LABELS[system])
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(group_labels)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, name), dpi=200)
    plt.close(fig)
    print("Saved", os.path.join(FIG_DIR, name))


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    lat = read("latency.csv")
    loads = read("load_times.csv")
    storage = read("storage.csv")

    # Average across runs
    summary = (lat.groupby(["rows", "system", "query", "indexed"])[["mean_ms", "p50_ms", "p95_ms"]]
               .mean().round(3).reset_index())
    summary.to_csv(os.path.join(RESULTS_DIR, "summary_latency.csv"), index=False)
    print("Saved", os.path.join(RESULTS_DIR, "summary_latency.csv"))

    max_rows = summary["rows"].max()
    indexed = summary[summary["indexed"]]

    # Fig 1: latency vs data size, indexes on
    queries = ["history", "window_sum", "fraud_by_type"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, query in zip(axes, queries):
        for system in SYSTEMS:
            d = indexed[(indexed["query"] == query) & (indexed["system"] == system)].sort_values("rows")
            ax.plot(d["rows"], d["mean_ms"], marker="o", label=SYSTEM_LABELS[system])
        ax.set_title(QUERY_LABELS[query])
        ax.set_xlabel("Rows loaded")
        ax.set_ylabel("Mean latency (ms)")
        ax.grid(alpha=0.3)
    axes[0].legend()
    save(fig, "fig1_latency_vs_size.png")

    # Fig 2: index on vs off at the largest size
    d = summary[(summary["rows"] == max_rows) & summary["query"].isin(["history", "window_sum"])].copy()
    d["group"] = d["query"] + "_" + d["indexed"].map({True: "on", False: "off"})
    groups = ["history_off", "history_on", "window_sum_off", "window_sum_on"]
    labels = ["History\nno index", "History\nindexed", "Window sum\nno index", "Window sum\nindexed"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    grouped_bars(ax, d, groups, "mean_ms", labels)
    ax.set_yscale("log")
    ax.set_ylabel("Mean latency (ms, log scale)")
    ax.set_title(f"Effect of indexing ({max_rows:,} rows)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    save(fig, "fig2_index_effect.png")

    # Fig 3: bulk load time vs data size
    d = loads.groupby(["rows", "system"])["seconds"].mean().reset_index()
    d["group"] = d["rows"]
    sizes = sorted(d["rows"].unique())
    fig, ax = plt.subplots(figsize=(7, 4.5))
    grouped_bars(ax, d, sizes, "seconds", [f"{s:,}" for s in sizes])
    ax.set_xlabel("Rows loaded")
    ax.set_ylabel("Bulk load time (s)")
    ax.set_title("Bulk load time")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    save(fig, "fig3_load_time.png")

    # Fig 4: single insert latency at the largest size
    d = indexed[(indexed["rows"] == max_rows) & (indexed["query"] == "single_insert")]
    fig, ax = plt.subplots(figsize=(6, 4.5))
    x = range(len(SYSTEMS))
    ax.bar([i - 0.2 for i in x], [d.loc[d["system"] == s, "mean_ms"].mean() for s in SYSTEMS], 0.4, label="Mean")
    ax.bar([i + 0.2 for i in x], [d.loc[d["system"] == s, "p95_ms"].mean() for s in SYSTEMS], 0.4, label="p95")
    ax.set_xticks(list(x))
    ax.set_xticklabels([SYSTEM_LABELS[s] for s in SYSTEMS])
    ax.set_ylabel("Latency (ms)")
    ax.set_title(f"Single durable insert ({max_rows:,} rows)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    save(fig, "fig4_single_insert.png")

    # Fig 5: storage at the largest size
    d = storage[storage["rows"] == max_rows].groupby("system")[["data_mb", "index_mb"]].mean()
    d = d.reindex(SYSTEMS)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    labels = [SYSTEM_LABELS[s] for s in SYSTEMS]
    ax.bar(labels, d["data_mb"], label="Data")
    ax.bar(labels, d["index_mb"], bottom=d["data_mb"], label="Indexes")
    ax.set_ylabel("Size on disk (MB)")
    ax.set_title(f"Storage ({max_rows:,} rows)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    save(fig, "fig5_storage.png")

    print_headline(indexed, loads, storage, max_rows)


def print_headline(indexed, loads, storage, rows):
    """Print the key numbers for the largest size, averaged across runs."""
    print(f"\n===== Headline results ({rows:,} rows, indexes on) =====")
    table = indexed[indexed["rows"] == rows].pivot(index="query", columns="system", values="mean_ms")
    table = table[SYSTEMS].rename(columns=SYSTEM_LABELS, index=QUERY_LABELS)
    print("\nMean latency (ms)")
    print(table.to_string())

    print("\nBulk load time (s)")
    load = loads[loads["rows"] == rows].groupby("system")["seconds"].mean().reindex(SYSTEMS)
    print(load.rename(index=SYSTEM_LABELS).round(2).to_string())

    print("\nStorage, data + indexes (MB)")
    s = storage[storage["rows"] == rows].groupby("system")[["data_mb", "index_mb"]].mean().reindex(SYSTEMS)
    print((s["data_mb"] + s["index_mb"]).rename(index=SYSTEM_LABELS).round(1).to_string())


if __name__ == "__main__":
    main()
