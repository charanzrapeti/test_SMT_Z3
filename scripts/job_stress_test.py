import argparse
import csv
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt


COMPUTE_NODES = [1, 2, 3, 11, 17, 16, 15, 7]
WCET_PATTERN = [82, 60, 27, 64, 75, 24, 64, 69, 24, 47, 10, 90, 30, 72, 49, 82, 18, 94, 87, 49]
BASE_INPUT = Path("input/graph_1 - input.json")
INPUT_DIR = Path("input/job stress test")
OUTPUT_DIR = Path("output/job stress test")


def allowed_nodes_for_job(job_id):
    width_pattern = [1, 2, 3, 3, 2, 1, 3, 2]
    width = width_pattern[job_id % len(width_pattern)]
    start = (job_id * 3 + job_id // 2) % len(COMPUTE_NODES)
    return [COMPUTE_NODES[(start + offset) % len(COMPUTE_NODES)] for offset in range(width)]


def greedy_deadline(jobs, message_count=0):
    loads = {node: 0 for node in COMPUTE_NODES}
    for job in sorted(jobs, key=lambda item: item["wcet_fullspeed"], reverse=True):
        node = min(job["can_run_on"], key=lambda nid: loads[nid])
        loads[node] += job["wcet_fullspeed"]
    load_lower_bound = math.ceil(sum(job["wcet_fullspeed"] for job in jobs) / len(COMPUTE_NODES))
    chain_wcet = sum(job["wcet_fullspeed"] for job in jobs[: min(len(jobs), message_count + 1)])
    chain_lower_bound = chain_wcet + message_count
    return max(
        max(loads.values()) + 200,
        load_lower_bound + max(WCET_PATTERN) + 200,
        chain_lower_bound + 250,
    )


def make_jobs(count):
    jobs = []
    for job_id in range(count):
        wcet = WCET_PATTERN[job_id % len(WCET_PATTERN)]
        jobs.append(
            {
                "id": job_id,
                "wcet_fullspeed": wcet,
                "mcet": 0,
                "processing_times": 0,
                "can_run_on": allowed_nodes_for_job(job_id),
            }
        )
    return jobs


def make_messages(count, message_count):
    messages = []
    for msg_id in range(message_count):
        sender = msg_id % max(1, count - 1)
        receiver = sender + 1
        messages.append(
            {
                "id": msg_id,
                "sender": sender,
                "receiver": receiver,
                "size": 16 + (msg_id % 16),
                "timetriggered": True,
                "period": 50,
            }
        )
    return messages


def write_input(base_data, task_count, message_count):
    jobs = make_jobs(task_count)
    messages = make_messages(task_count, message_count)
    data = {
        "application": {
            "jobs": jobs,
            "messages": messages,
            "deadline": greedy_deadline(jobs, message_count) + (message_count * 4),
        },
        "platform": base_data["platform"],
        "frequencies": base_data.get("frequencies", []),
        "schemes": base_data.get("schemes", []),
    }
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = INPUT_DIR / f"{task_count}_{message_count}_input.json"
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    return path


def output_path_for(input_path):
    return OUTPUT_DIR / f"{input_path.stem}_smt_output.json"


def run_scheduler(scheduler, input_path, timeout_seconds):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_output = output_path_for(input_path)
    root_output = Path("output") / f"{input_path.stem}_smt_output.json"
    command = [
        sys.executable,
        str(scheduler),
        str(input_path),
        "--output-file",
        str(target_output),
    ]
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        elapsed = time.perf_counter() - started_at
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "elapsed_seconds": timeout_seconds,
            "makespan": None,
            "stdout_tail": (exc.stdout or "")[-1000:],
            "stderr_tail": (exc.stderr or "")[-1000:],
        }

    result = {
        "status": "ok" if completed.returncode == 0 and target_output.exists() else "failed",
        "elapsed_seconds": elapsed,
        "makespan": None,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }
    if target_output.exists():
        schedule = json.loads(target_output.read_text(encoding="utf-8"))
        result["makespan"] = schedule.get("optimal_makespan")
        result["scheduler_reported_seconds"] = schedule.get("schedule_calculation_seconds")
    if root_output.exists() and root_output.resolve() != target_output.resolve():
        root_output.unlink()
    return result


def save_results(results, label):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"stress_results_{label}.json"
    csv_path = OUTPUT_DIR / f"stress_results_{label}.csv"
    json_path.write_text(json.dumps(results, indent=4), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file",
                "tasks",
                "messages",
                "status",
                "elapsed_seconds",
                "scheduler_reported_seconds",
                "makespan",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return json_path, csv_path


def plot_results(results, label):
    successful = [row for row in results if row["status"] == "ok"]
    if not successful:
        return None
    labels = [f'{row["tasks"]}/{row["messages"]}' for row in successful]
    elapsed = [row["elapsed_seconds"] for row in successful]
    makespan = [row["makespan"] for row in successful]
    x_values = range(len(successful))

    fig, ax_time = plt.subplots(figsize=(12, 6))
    ax_span = ax_time.twinx()
    time_line = ax_time.plot(x_values, elapsed, marker="o", color="#1f77b4", label="scheduler time (s)")
    span_line = ax_span.plot(x_values, makespan, marker="s", color="#d62728", label="schedule makespan")
    ax_time.set_xticks(list(x_values))
    ax_time.set_xticklabels(labels, rotation=45, ha="right")
    ax_time.set_xlabel("Tasks/Messages")
    ax_time.set_ylabel("Scheduler time (seconds)")
    ax_span.set_ylabel("Schedule makespan")
    ax_time.grid(True, axis="y", alpha=0.25)
    lines = time_line + span_line
    ax_time.legend(lines, [line.get_label() for line in lines], loc="upper left")
    fig.tight_layout()
    path = OUTPUT_DIR / f"stress_plot_{label}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    parser = argparse.ArgumentParser(description="Generate and run scheduler job stress tests.")
    parser.add_argument("--scheduler", default="test2Parallize.py", help="Scheduler script to benchmark.")
    parser.add_argument("--label", default="baseline", help="Suffix for result files.")
    parser.add_argument("--start", type=int, default=20)
    parser.add_argument("--stop", type=int, default=80)
    parser.add_argument("--step", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--message-phase", action="store_true")
    args = parser.parse_args()

    base_data = json.loads(BASE_INPUT.read_text(encoding="utf-8"))
    scheduler = Path(args.scheduler)
    results = []

    for task_count in range(args.start, args.stop + 1, args.step):
        input_path = write_input(base_data, task_count, 0)
        run = run_scheduler(scheduler, input_path, args.timeout)
        run.update({"file": input_path.name, "tasks": task_count, "messages": 0})
        results.append(run)
        print(f'{input_path.name}: {run["status"]}, time={run["elapsed_seconds"]:.3f}s, makespan={run["makespan"]}', flush=True)
        if run["status"] != "ok":
            break

    if args.message_phase:
        ok_task_counts = [row["tasks"] for row in results if row["status"] == "ok" and row["messages"] == 0]
        if ok_task_counts:
            task_count = max(ok_task_counts)
            for message_count in range(3, min(30, task_count - 1) + 1, 3):
                input_path = write_input(base_data, task_count, message_count)
                run = run_scheduler(scheduler, input_path, args.timeout)
                run.update({"file": input_path.name, "tasks": task_count, "messages": message_count})
                results.append(run)
                print(f'{input_path.name}: {run["status"]}, time={run["elapsed_seconds"]:.3f}s, makespan={run["makespan"]}', flush=True)
                if run["status"] != "ok":
                    break

    json_path, csv_path = save_results(results, args.label)
    plot_path = plot_results(results, args.label)
    print(f"results_json={json_path}")
    print(f"results_csv={csv_path}")
    if plot_path:
        print(f"plot={plot_path}")


if __name__ == "__main__":
    main()
