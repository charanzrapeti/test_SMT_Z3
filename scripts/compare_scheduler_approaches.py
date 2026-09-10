

import csv
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ============================================================
# PATHS
# ============================================================

# This script is inside:
#
#     project_root/scripts/
#
# Therefore:
PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_DIR = PROJECT_ROOT / "input" / "job_stress_test"
RESULTS_DIR = PROJECT_ROOT / "results" / "comparision"

TEST_DIR = RESULTS_DIR / "test"
TEST2_DIR = RESULTS_DIR / "test2parallize"

TEST_INPUT_DIR = TEST_DIR / "input"
TEST_OUTPUT_DIR = TEST_DIR / "output"

TEST2_INPUT_DIR = TEST2_DIR / "input"
TEST2_OUTPUT_DIR = TEST2_DIR / "output"

TEST_SCRIPT = PROJECT_ROOT / "test.py"
TEST2_SCRIPT = PROJECT_ROOT / "test2Parallize.py"


# ============================================================
# SETUP
# ============================================================

def create_directories():
    directories = [
        TEST_INPUT_DIR,
        TEST_OUTPUT_DIR,
        TEST2_INPUT_DIR,
        TEST2_OUTPUT_DIR,
        RESULTS_DIR,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


# ============================================================
# INPUT NAME PARSING
# ============================================================

def get_jobs_messages(input_file):
    """
    Extract the number of jobs and messages.

    Example:

        53_8.json

    becomes:

        jobs = 53
        messages = 8

    The graph label will be:

        53_8
    """

    match = re.match(r"^(\d+)_(\d+)", input_file.stem)

    if match:
        jobs = int(match.group(1))
        messages = int(match.group(2))
        return jobs, messages, f"{jobs}_{messages}"

    return None, None, input_file.stem


# ============================================================
# READ RESULT FROM SCHEDULER OUTPUT
# ============================================================

def extract_result(stdout, input_file):
    """
    Extract SAT/UNSAT, scheduler time and makespan
    from scheduler stdout.

    Expected output from test.py:

        Starting scheduler for file: ...
        SAT
        Scheduler time: 12.345 seconds
        Makespan: 123
    """

    result = {
        "status": "failed",
        "makespan": None,
        "scheduler_seconds": None,
        "stdout": stdout,
    }

    if "SAT" in stdout:
        result["status"] = "sat"
    elif "UNSAT" in stdout:
        result["status"] = "unsat"

    time_match = re.search(
        r"Scheduler time:\s*([0-9.eE+-]+)\s*seconds",
        stdout,
        re.IGNORECASE,
    )
    if not time_match:
        time_match = re.search(
            r"Total time:\s*([0-9.eE+-]+)\s*seconds",
            stdout,
            re.IGNORECASE,
        )

    if time_match:
        result["scheduler_seconds"] = float(time_match.group(1))

    makespan_match = re.search(
        r"Makespan:\s*([0-9.eE+-]+)",
        stdout,
        re.IGNORECASE,
    )
    if makespan_match:
        result["makespan"] = float(makespan_match.group(1))
        if result["makespan"].is_integer():
            result["makespan"] = int(result["makespan"])

    return result


# ============================================================
# RUN ONE SCHEDULER
# ============================================================

def run_scheduler(script, input_file, output_file):
    print()
    print("=" * 70)
    print(f"Running: {script.name}")
    print(f"Input:   {input_file.name}")
    print("=" * 70)

    print("Python:", sys.executable)
    print("Script:", script)
    print("Input:", input_file)
    print("CWD:", PROJECT_ROOT)

    started = time.perf_counter()

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                str(input_file),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        wall_time = time.perf_counter() - started
        print("RETURN CODE:", completed.returncode)

        print("----- STDOUT -----")
        print(completed.stdout)

        print("----- STDERR -----")
        print(completed.stderr)
    except Exception as error:
        wall_time = time.perf_counter() - started
        return {
            "status": "failed",
            "wall_seconds": wall_time,
            "scheduler_seconds": None,
            "makespan": None,
            "stdout": "",
            "stderr": str(error),
        }

    stdout = completed.stdout
    stderr = completed.stderr
    result = extract_result(stdout, input_file)

    if completed.returncode != 0:
        result["status"] = "failed"

    result["wall_seconds"] = wall_time
    result["stderr"] = stderr

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(stdout, encoding="utf-8")

    generated_json = PROJECT_ROOT / "output" / f"{input_file.stem}_smt_output.json"
    if generated_json.exists() and script.name == TEST2_SCRIPT.name:
        copied_json = output_file.with_name(f"{output_file.stem}_smt_output.json")
        shutil.copy2(generated_json, copied_json)

        try:
            with generated_json.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            if payload.get("optimal_makespan") is not None:
                result["makespan"] = payload["optimal_makespan"]
            if payload.get("schedule_calculation_seconds") is not None:
                result["scheduler_seconds"] = float(payload["schedule_calculation_seconds"])
        except Exception:
            pass

    if stderr.strip():
        stderr_file = output_file.with_suffix(".stderr.txt")
        stderr_file.write_text(stderr, encoding="utf-8")

    print(f"Status:          {result['status']}")
    if result["scheduler_seconds"] is not None:
        print(f"Scheduler time:  {result['scheduler_seconds']:.6f} s")
    if result["makespan"] is not None:
        print(f"Makespan:        {result['makespan']}")
    print(f"Process time:     {wall_time:.6f} s")

    return result


# ============================================================
# COPY INPUT FILE
# ============================================================

def copy_input(input_file, destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_file, destination / input_file.name)


# ============================================================
# SAVE JSON
# ============================================================

def save_json(rows, json_file):
    json_file.write_text(json.dumps(rows, indent=4), encoding="utf-8")
    print(f"JSON results: {json_file}")


def save_scheduler_json(rows, prefix, json_file):
    records = []
    for row in rows:
        records.append(
            {
                "input": row["input"],
                "jobs": row["jobs"],
                "messages": row["messages"],
                "status": row[f"{prefix}_status"],
                "makespan": row[f"{prefix}_makespan"],
                "scheduler_seconds": row[f"{prefix}_scheduler_seconds"],
            }
        )

    save_json(records, json_file)


# ============================================================
# CREATE COMPARISON GRAPH
# ============================================================

def plot_comparison(rows, output_file, title, y_label, value_key, second_value_key):
    valid_rows = [
        row
        for row in rows
        if row[value_key] is not None or row[second_value_key] is not None
    ]

    if not valid_rows:
        print(f"No data available for {title}. Skipping graph.")
        return

    labels = [row["input"] for row in valid_rows]
    test_values = [
        row[value_key] if row[value_key] is not None else float("nan")
        for row in valid_rows
    ]
    test2_values = [
        row[second_value_key] if row[second_value_key] is not None else float("nan")
        for row in valid_rows
    ]

    figure, axis = plt.subplots(figsize=(11, 6))
    axis.plot(labels, test_values, marker="o", linewidth=2, label="test.py", color="tab:blue")
    axis.plot(labels, test2_values, marker="o", linewidth=2, label="test2Parallize.py", color="tab:orange")

    axis.set_title(title)
    axis.set_xlabel("Jobs_Messages")
    axis.set_ylabel(y_label)
    axis.grid(axis="y", alpha=0.3)
    axis.legend()
    axis.tick_params(axis="x", rotation=35)
    figure.tight_layout()

    figure.savefig(output_file, format="svg", bbox_inches="tight")
    plt.close(figure)

    print(f"Graph saved: {output_file}")


# ============================================================
# CREATE MAKESPAN GRAPH
# ============================================================

def plot_makespan(rows, output_file):
    plot_comparison(
        rows,
        output_file,
        "Makespan Comparison",
        "Makespan (timeframes)",
        "test_makespan",
        "test2_makespan",
    )


# ============================================================
# CREATE SCHEDULER TIME GRAPH
# ============================================================

def plot_scheduler_time(rows, output_file):
    plot_comparison(
        rows,
        output_file,
        "Scheduler Time Comparison",
        "Scheduler Time (seconds)",
        "test_scheduler_seconds",
        "test2_scheduler_seconds",
    )


# ============================================================
# EXPORT ARTIFACTS
# ============================================================

def save_comparison_artifacts(rows, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_makespan(rows, output_dir / "makespan.svg")
    plot_scheduler_time(rows, output_dir / "scheduler_time.svg")

    save_scheduler_json(rows, "test", output_dir / "test_results.json")
    save_scheduler_json(rows, "test2", output_dir / "test2parallize_results.json")


# ============================================================
# MAIN BENCHMARK
# ============================================================

def main():
    print("=" * 70)
    print("SMT SCHEDULER COMPARISON")
    print("=" * 70)
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Input folder : {INPUT_DIR}")
    print(f"Results      : {RESULTS_DIR}")

    if not TEST_SCRIPT.exists():
        raise FileNotFoundError(f"Could not find: {TEST_SCRIPT}")

    if not TEST2_SCRIPT.exists():
        raise FileNotFoundError(f"Could not find: {TEST2_SCRIPT}")

    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Could not find input directory: {INPUT_DIR}")

    create_directories()

    input_files = sorted(
        INPUT_DIR.glob("*.json"),
        key=lambda path: (
            get_jobs_messages(path)[0]
            if get_jobs_messages(path)[0] is not None
            else float("inf")
        ),
    )

    if not input_files:
        print("No JSON files found.")
        return

    print(f"\nFound {len(input_files)} input files.")

    rows = []

    for input_file in input_files:
        jobs, messages, label = get_jobs_messages(input_file)

        print()
        print("#" * 70)
        print(f"INPUT: {input_file.name}")
        if jobs is not None:
            print(f"Jobs: {jobs} | Messages: {messages}")
        print("#" * 70)

        copy_input(input_file, TEST_INPUT_DIR)
        copy_input(input_file, TEST2_INPUT_DIR)

        test_output = TEST_OUTPUT_DIR / f"{input_file.stem}.txt"
        test2_output = TEST2_OUTPUT_DIR / f"{input_file.stem}.txt"

        test_result = run_scheduler(TEST_SCRIPT, input_file, test_output)
        test2_result = run_scheduler(TEST2_SCRIPT, input_file, test2_output)

        rows.append(
            {
                "input": input_file.stem,
                "jobs": jobs,
                "messages": messages,
                "test_status": test_result["status"],
                "test_makespan": test_result["makespan"],
                "test_scheduler_seconds": test_result["scheduler_seconds"],
                "test2_status": test2_result["status"],
                "test2_makespan": test2_result["makespan"],
                "test2_scheduler_seconds": test2_result["scheduler_seconds"],
            }
        )

    save_comparison_artifacts(rows, RESULTS_DIR)

    print()
    print("=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)
    print(f"Results are in: {RESULTS_DIR}")


if __name__ == "__main__":
    main()

