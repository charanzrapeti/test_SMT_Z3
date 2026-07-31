import subprocess
import time
import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt

# ----------------------------------------
# Scheduler
# ----------------------------------------
SCHEDULER = "test2Parallize.py"

# ----------------------------------------
# Input files
# ----------------------------------------
input_files = [
    "input/input_20jobs.json",
    "input/input_22jobs.json",
    "input/input_24jobs.json",
    "input/input_26jobs.json",
    "input/input_28jobs.json",
]

tasks = []
makespans = []
execution_times = []

for input_file in input_files:

    print(f"\nRunning {input_file}")

    # ----------------------------
    # Run scheduler & measure time
    # ----------------------------
    start = time.perf_counter()

    subprocess.run(
        [sys.executable, SCHEDULER, input_file],
        check=True
    )

    runtime = time.perf_counter() - start

    # ----------------------------
    # Read input
    # ----------------------------
    with open(input_file, "r") as f:
        input_json = json.load(f)

    task_count = len(input_json["application"]["jobs"])

    # ----------------------------
    # Read output
    # ----------------------------
    output_file = (
        "output/"
        + Path(input_file).stem
        + "_smt_output.json"
    )

    with open(output_file, "r") as f:
        output_json = json.load(f)

    # Change this key if necessary
    makespan = output_json["optimal_makespan"]

    tasks.append(task_count)
    makespans.append(makespan)
    execution_times.append(runtime)

    print(
        f"Tasks={task_count}  "
        f"Makespan={makespan}  "
        f"Time={runtime:.3f}s"
    )

# ======================================================
# ONE GRAPH
# ======================================================

fig, ax1 = plt.subplots(figsize=(8,5))

# Makespan
ax1.plot(
    tasks,
    makespans,
    marker="o",
    linewidth=2,
    label="Makespan"
)

ax1.set_xlabel("Number of Tasks")
ax1.set_ylabel("Makespan")

# Execution Time
ax2 = ax1.twinx()

ax2.plot(
    tasks,
    execution_times,
    marker="s",
    linestyle="--",
    linewidth=2,
    label="Execution Time"
)

ax2.set_ylabel("Execution Time (seconds)")

# Combined legend
lines = ax1.get_lines() + ax2.get_lines()
labels = [line.get_label() for line in lines]

ax1.legend(lines, labels, loc="upper left")

plt.title("Scheduler Performance")
plt.grid(True)

plt.tight_layout()
plt.savefig("scheduler_performance.png", dpi=300)

plt.show()