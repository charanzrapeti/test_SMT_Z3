
import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt


# ============================================================
# CONFIGURATION
# ============================================================

# This script is located in:
#     scripts/job_stress_test_fixed.py
#
# Input files:
#     input/job_stress_test/*.json
#
# Scheduler:
#     test2Parallize.py
#
# Scheduler output:
#     output/job_stress_test/
#
# Benchmark graph:
#     input/job_stress_test/stress_plot.svg

INPUT_DIR = Path("input/job_stress_test")
OUTPUT_DIR = Path("output/job_stress_test")

DEFAULT_SCHEDULER = "test2Parallize.py"


# ============================================================
# INPUT FILE INFORMATION
# ============================================================

def get_input_info(input_path):
    """
    Read the input JSON and determine the number of jobs/tasks
    and messages.
    """

    data = json.loads(input_path.read_text(encoding="utf-8"))

    application = data.get("application", {})

    jobs = application.get("jobs", [])
    messages = application.get("messages", [])

    return len(jobs), len(messages)


# ============================================================
# OUTPUT PATH
# ============================================================

def output_path_for(input_path):
    """
    Scheduler output corresponding to one input file.
    """

    return OUTPUT_DIR / f"{input_path.stem}_smt_output.json"


# ============================================================
# RUN SCHEDULER
# ============================================================

def run_scheduler(scheduler, input_path, timeout_seconds, workers):
    """
    Run the scheduler for one input JSON file.
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    target_output = output_path_for(input_path)

    command = [
        sys.executable,
        str(scheduler),
        str(input_path),
        "--output-file",
        str(target_output),
        "--workers",
        str(workers),
    ]

    print()
    print("=" * 70)
    print(f"Running scheduler:")
    print(f"  Input   : {input_path}")
    print(f"  Output  : {target_output}")
    print(f"  Workers : {workers}")
    print("=" * 70)

    start_time_epoch = time.time()
    start_time_str = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(start_time_epoch)
    )

    started_at = time.perf_counter()

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = process.communicate(
            timeout=timeout_seconds
        )

        elapsed = time.perf_counter() - started_at

    except subprocess.TimeoutExpired:

        end_time_epoch = time.time()
        end_time_str = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(end_time_epoch)
        )

        timeout_minutes = timeout_seconds / 60.0

        if timeout_minutes.is_integer():
            timeout_minutes_str = f"{int(timeout_minutes)}min"
        else:
            timeout_minutes_str = f"{timeout_minutes:.1f}min"

        print()
        print(
            f"scheduler timeout exceeded "
            f"{timeout_minutes_str}"
        )
        print(
            f"Start time of scheduler: {start_time_str}"
        )
        print(
            f"End time of scheduler:   {end_time_str}"
        )

        # Windows:
        # terminate the complete process tree
        try:
            subprocess.run(
                [
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(process.pid),
                ],
                capture_output=True,
            )
        except Exception:
            process.kill()

        return {
            "status": "timeout",
            "elapsed_seconds": timeout_seconds,
            "makespan": None,
            "stdout_tail": "",
            "stderr_tail": "Scheduler timeout exceeded.",
            "workers": workers,
        }

    result = {
        "status": (
            "ok"
            if process.returncode == 0
            and target_output.exists()
            else "failed"
        ),
        "elapsed_seconds": elapsed,
        "makespan": None,
        "stdout_tail": stdout[-1000:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else "",
        "workers": workers,
    }

    # --------------------------------------------------------
    # Read scheduler output
    # --------------------------------------------------------

    if target_output.exists():

        try:
            schedule = json.loads(
                target_output.read_text(
                    encoding="utf-8"
                )
            )

            result["makespan"] = schedule.get(
                "optimal_makespan"
            )

            result["scheduler_reported_seconds"] = (
                schedule.get(
                    "schedule_calculation_seconds"
                )
            )

            result["candidates_checked"] = (
                schedule.get(
                    "candidates_checked"
                )
            )

            result["search_lower_bound"] = (
                schedule.get(
                    "search_lower_bound"
                )
            )

        except Exception as exc:

            result["status"] = "failed"

            result["stderr_tail"] += (
                f"\nCould not read scheduler output: {exc}"
            )

    return result


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(results, output_dir):
    """
    Save benchmark results as JSON and CSV.
    """

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    json_path = (
        output_dir /
        "stress_results.json"
    )

    csv_path = (
        output_dir /
        "stress_results.csv"
    )

    json_path.write_text(
        json.dumps(
            results,
            indent=4
        ),
        encoding="utf-8"
    )

    fieldnames = [
        "file",
        "tasks",
        "messages",
        "status",
        "elapsed_seconds",
        "scheduler_reported_seconds",
        "makespan",
        "workers",
        "candidates_checked",
        "search_lower_bound",
    ]

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for row in results:

            writer.writerow(
                {
                    key: row.get(key)
                    for key in fieldnames
                }
            )

    return json_path, csv_path


# ============================================================
# SVG GRAPH
# ============================================================

def plot_results(results, input_dir):
    """
    Generate a single SVG graph containing all successful
    scheduler runs.

    The SVG is saved directly inside the input directory.
    """

    successful = [
        row
        for row in results
        if row["status"] == "ok"
        and row.get("makespan") is not None
    ]

    if not successful:
        print()
        print("No successful scheduler runs.")
        print("SVG graph was not generated.")
        return None

    # Sort by number of tasks, then messages
    successful.sort(
        key=lambda row: (
            row["tasks"],
            row["messages"]
        )
    )

    labels = [
        f'{row["tasks"]}/{row["messages"]}'
        for row in successful
    ]

    elapsed = [
        row["elapsed_seconds"]
        for row in successful
    ]

    makespan = [
        row["makespan"]
        for row in successful
    ]

    x_values = range(len(successful))

    # --------------------------------------------------------
    # Create graph
    # --------------------------------------------------------

    fig, ax_time = plt.subplots(
        figsize=(14, 7)
    )

    ax_span = ax_time.twinx()

    time_line = ax_time.plot(
        x_values,
        elapsed,
        marker="o",
        label="Scheduler time (s)"
    )

    span_line = ax_span.plot(
        x_values,
        makespan,
        marker="s",
        label="Schedule makespan"
    )

    ax_time.set_xticks(
        list(x_values)
    )

    ax_time.set_xticklabels(
        labels,
        rotation=45,
        ha="right"
    )

    ax_time.set_xlabel(
        "Tasks / Messages"
    )

    ax_time.set_ylabel(
        "Scheduler time (seconds)"
    )

    ax_span.set_ylabel(
        "Schedule makespan"
    )

    ax_time.grid(
        True,
        axis="y",
        alpha=0.25
    )

    lines = (
        time_line +
        span_line
    )

    ax_time.legend(
        lines,
        [
            line.get_label()
            for line in lines
        ],
        loc="upper left"
    )

    fig.suptitle(
        "Job Stress Test - Scheduler Performance"
    )

    fig.tight_layout()

    # --------------------------------------------------------
    # Save SVG in INPUT folder
    # --------------------------------------------------------

    svg_path = (
        input_dir /
        "stress_plot.svg"
    )

    fig.savefig(
        svg_path,
        format="svg"
    )

    plt.close(fig)

    return svg_path


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Run the scheduler on all existing "
            "JSON files in input/job_stress_test "
            "and generate an SVG benchmark graph."
        )
    )

    parser.add_argument(
        "--scheduler",
        default=DEFAULT_SCHEDULER,
        help=(
            "Scheduler script to execute. "
            "Default: test2Parallize.py"
        )
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help=(
            "Maximum scheduler runtime per input "
            "in seconds. Default: 1800."
        )
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of scheduler workers/cores. "
            "Default: 1."
        )
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Check input directory
    # --------------------------------------------------------

    if not INPUT_DIR.exists():

        print(
            f"ERROR: Input directory does not exist:"
        )

        print(
            f"  {INPUT_DIR.resolve()}"
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Find existing JSON files
    # --------------------------------------------------------

    input_files = sorted(
        INPUT_DIR.glob("*.json")
    )

    if not input_files:

        print(
            f"ERROR: No JSON files found in:"
        )

        print(
            f"  {INPUT_DIR.resolve()}"
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Resolve scheduler path
    # --------------------------------------------------------

    scheduler = Path(args.scheduler)

    if not scheduler.exists():

        # Try relative to this script
        script_relative = (
            Path(__file__).resolve().parent /
            scheduler
        )

        if script_relative.exists():
            scheduler = script_relative

        else:

            print(
                f"ERROR: Scheduler script not found:"
            )

            print(
                f"  {args.scheduler}"
            )

            print()
            print(
                "Current directory:"
            )

            print(
                f"  {Path.cwd()}"
            )

            sys.exit(1)

    # --------------------------------------------------------
    # Print benchmark information
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("JOB STRESS TEST")
    print("=" * 70)

    print(
        f"Input directory : "
        f"{INPUT_DIR.resolve()}"
    )

    print(
        f"Scheduler       : "
        f"{scheduler.resolve()}"
    )

    print(
        f"Output directory: "
        f"{OUTPUT_DIR.resolve()}"
    )

    print(
        f"Input files     : "
        f"{len(input_files)}"
    )

    print(
        f"Workers         : "
        f"{args.workers}"
    )

    print(
        f"Timeout         : "
        f"{args.timeout}s"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # Run every existing input file
    # --------------------------------------------------------

    results = []

    for index, input_path in enumerate(
        input_files,
        start=1
    ):

        print()
        print(
            f"[{index}/{len(input_files)}] "
            f"{input_path.name}"
        )

        # Read task/message counts
        try:

            task_count, message_count = (
                get_input_info(input_path)
            )

        except Exception as exc:

            print(
                f"ERROR reading "
                f"{input_path.name}: {exc}"
            )

            results.append(
                {
                    "file": input_path.name,
                    "tasks": None,
                    "messages": None,
                    "status": "invalid_input",
                    "elapsed_seconds": 0,
                    "makespan": None,
                    "workers": args.workers,
                    "stdout_tail": "",
                    "stderr_tail": str(exc),
                }
            )

            continue

        print(
            f"Tasks    : {task_count}"
        )

        print(
            f"Messages : {message_count}"
        )

        # ----------------------------------------------------
        # Run scheduler
        # ----------------------------------------------------

        run = run_scheduler(
            scheduler=scheduler,
            input_path=input_path,
            timeout_seconds=args.timeout,
            workers=args.workers,
        )

        run.update(
            {
                "file": input_path.name,
                "tasks": task_count,
                "messages": message_count,
            }
        )

        results.append(run)

        print()
        print(
            f"Result: {run['status']}"
        )

        print(
            f"Runtime: "
            f"{run['elapsed_seconds']:.3f}s"
        )

        print(
            f"Makespan: "
            f"{run['makespan']}"
        )

        # ----------------------------------------------------
        # Do NOT stop if one input fails.
        # Continue with the remaining files.
        # ----------------------------------------------------

        if run["status"] != "ok":

            print()
            print(
                f"--- SCHEDULER FAILED FOR "
                f"{input_path.name} ---"
            )

            print("STDOUT tail:")
            print(
                run.get(
                    "stdout_tail",
                    ""
                )
            )

            print("STDERR tail:")
            print(
                run.get(
                    "stderr_tail",
                    ""
                )
            )

            print("-" * 70)

    # --------------------------------------------------------
    # Save benchmark results
    # --------------------------------------------------------

    json_path, csv_path = save_results(
        results,
        OUTPUT_DIR
    )

    # --------------------------------------------------------
    # Generate SVG
    # --------------------------------------------------------

    svg_path = plot_results(
        results,
        INPUT_DIR
    )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    successful = sum(
        1
        for row in results
        if row["status"] == "ok"
    )

    failed = len(results) - successful

    print()
    print("=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)

    print(
        f"Total files : {len(results)}"
    )

    print(
        f"Successful   : {successful}"
    )

    print(
        f"Failed       : {failed}"
    )

    print()
    print(
        f"Results JSON : {json_path}"
    )

    print(
        f"Results CSV  : {csv_path}"
    )

    if svg_path:

        print(
            f"SVG graph    : {svg_path}"
        )

    print("=" * 70)


if __name__ == "__main__":
    main()
