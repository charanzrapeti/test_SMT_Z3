import json
import re
from pathlib import Path

import matplotlib.pyplot as plt


# ============================================================
# Configuration
# ============================================================

INPUT_DIR = Path(
    r"D:\masters\project_work\test_code\output\job_stress_test"
)

OUTPUT_FILE = INPUT_DIR / "smt_performance_plot.png"


# ============================================================
# Extract data from JSON files
# ============================================================

results = []

for json_file in INPUT_DIR.glob("*.json"):

    # --------------------------------------------------------
    # Extract task count and message count from filename
    #
    # Examples:
    #   20_8_smt_output.json
    #   20_10_input_smt_output.json
    #   65_10_smt_output.json
    #
    # The first two numbers are task_count and message_count.
    # --------------------------------------------------------

    match = re.match(r"^(\d+)_(\d+)_", json_file.name)

    if not match:
        print(f"Skipping filename: {json_file.name}")
        continue

    task_count = int(match.group(1))
    message_count = int(match.group(2))

    # --------------------------------------------------------
    # Read JSON
    # --------------------------------------------------------

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

    except Exception as e:
        print(f"Error reading {json_file.name}: {e}")
        continue

    # --------------------------------------------------------
    # Extract values
    # --------------------------------------------------------

    makespan = data.get("optimal_makespan")
    runtime = data.get("schedule_calculation_seconds")

    if makespan is None or runtime is None:
        print(f"Missing values in: {json_file.name}")
        continue

    results.append({
        "task_count": task_count,
        "message_count": message_count,
        "makespan": makespan,
        "runtime": runtime,
        "filename": json_file.name,
    })


# ============================================================
# Sort results
# ============================================================

# Sort primarily by task count and secondarily by message count
results.sort(
    key=lambda x: (x["task_count"], x["message_count"])
)


# ============================================================
# Print extracted data
# ============================================================

print("\nExtracted results:")
print("-" * 75)

for r in results:
    print(
        f"{r['task_count']:>3}/{r['message_count']:<3} | "
        f"Makespan: {r['makespan']:>6} | "
        f"Runtime: {r['runtime']:>10.4f} s | "
        f"{r['filename']}"
    )

print("-" * 75)
print(f"Total files processed: {len(results)}")


# ============================================================
# Prepare plotting data
# ============================================================

x_labels = [
    f"{r['task_count']}/{r['message_count']}"
    for r in results
]

runtime_values = [
    r["runtime"]
    for r in results
]

makespan_values = [
    r["makespan"]
    for r in results
]

x = range(len(results))


# ============================================================
# Create figure
# ============================================================

fig, ax1 = plt.subplots(figsize=(16, 8))


# ============================================================
# LEFT Y-AXIS
# Schedule calculation runtime
# ============================================================

line1 = ax1.plot(
    x,
    runtime_values,
    marker="o",
    markersize=6,
    linewidth=2,
    label="Schedule Runtime",
    color="tab:green"
)

ax1.set_xlabel(
    "Task Count / Message Count",
    fontsize=12
)

ax1.set_ylabel(
    "Schedule Calculation Runtime (seconds)",
    fontsize=12
)

ax1.set_xticks(x)
ax1.set_xticklabels(
    x_labels,
    rotation=45,
    ha="right"
)

ax1.grid(
    True,
    axis="y",
    linestyle="--",
    alpha=0.4
)


# ============================================================
# RIGHT Y-AXIS
# Optimal makespan
# ============================================================

ax2 = ax1.twinx()

line2 = ax2.plot(
    x,
    makespan_values,
    marker="s",
    markersize=6,
    linewidth=2,
    label="Optimal Makespan",
    color="tab:blue"
)

ax2.set_ylabel(
    "Optimal Makespan",
    fontsize=12
)


# ============================================================
# Combined legend
# ============================================================

lines = line1 + line2

labels = [
    line.get_label()
    for line in lines
]

ax1.legend(
    lines,
    labels,
    loc="upper left",
    fontsize=11
)


# ============================================================
# Title
# ============================================================

plt.title(
    "SMT Scheduler Performance",
    fontsize=16,
    fontweight="bold",
    pad=15
)


# ============================================================
# Improve layout
# ============================================================

fig.tight_layout()


# ============================================================
# Save graph
# ============================================================

plt.savefig(
    OUTPUT_FILE,
    dpi=300,
    bbox_inches="tight"
)

print(f"\nGraph saved to:")
print(OUTPUT_FILE)


# ============================================================
# Show graph
# ============================================================

plt.show()