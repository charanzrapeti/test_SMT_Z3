import argparse
import csv
import copy
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt


COMPUTE_NODES = [1, 2, 3, 11, 17, 16, 15, 7]
SPEED_FACTOR_PATTERN = [1, 2, 1.5, 1, 2, 1.5, 1, 2]
WCET_PATTERN = [82, 60, 27, 64, 75, 24, 64, 69, 24, 47, 10, 90, 30, 72, 49, 82, 18, 94, 87, 49]
BASE_INPUT = Path("input/graph_1 - input.json")
INPUT_DIR = Path("input/job_stress_test")
OUTPUT_DIR = Path("output/job_stress_test")


def allowed_nodes_for_job(job_id):
    width_pattern = [1, 2, 3, 3, 2, 1, 3, 2]
    width = width_pattern[job_id % len(width_pattern)]
    start = (job_id * 3 + job_id // 2) % len(COMPUTE_NODES)
    return [COMPUTE_NODES[(start + offset) % len(COMPUTE_NODES)] for offset in range(width)]


def speed_factors_by_node():
    return {
        node_id: SPEED_FACTOR_PATTERN[index % len(SPEED_FACTOR_PATTERN)]
        for index, node_id in enumerate(COMPUTE_NODES)
    }


def add_speed_factors(platform):
    platform = copy.deepcopy(platform)
    node_speed_factors = speed_factors_by_node()
    for node in platform.get("nodes", []):
        if not node.get("is_router", False):
            node["speed_factor"] = node_speed_factors.get(node["id"], 1)
    return platform


def processing_times_for_job(wcet, allowed_nodes):
    node_speed_factors = speed_factors_by_node()
    return [
        math.ceil(wcet * node_speed_factors.get(node_id, 1))
        for node_id in allowed_nodes
    ]


def message_count_for_task(task_count, min_messages, max_messages):
    span = max_messages - min_messages + 1
    return min_messages + ((task_count // 3) % span)


def greedy_deadline(jobs, message_count=0):
    loads = {node: 0 for node in COMPUTE_NODES}
    for job in sorted(jobs, key=lambda item: item["wcet_fullspeed"], reverse=True):
        node_times = dict(zip(job["can_run_on"], job["processing_times"]))
        node = min(job["can_run_on"], key=lambda nid: loads[nid] + node_times[nid])
        loads[node] += node_times[node]
    load_lower_bound = math.ceil(
        sum(min(job["processing_times"]) for job in jobs) / len(COMPUTE_NODES)
    )
    chain_wcet = sum(
        min(job["processing_times"])
        for job in jobs[: min(len(jobs), message_count + 1)]
    )
    chain_lower_bound = chain_wcet + message_count
    return max(
        max(loads.values()) + 200,
        load_lower_bound + math.ceil(max(WCET_PATTERN) * max(SPEED_FACTOR_PATTERN)) + 200,
        chain_lower_bound + 250,
    )


def make_jobs(count, pinned_pairs=0):
    jobs = []
    for job_id in range(count):
        wcet = WCET_PATTERN[job_id % len(WCET_PATTERN)]
        allowed_nodes = allowed_nodes_for_job(job_id)
        if job_id < pinned_pairs * 2:
            allowed_nodes = [1] if job_id % 2 == 0 else [17]
        jobs.append(
            {
                "id": job_id,
                "wcet_fullspeed": wcet,
                "mcet": 0,
                "processing_times": processing_times_for_job(wcet, allowed_nodes),
                "can_run_on": allowed_nodes,
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


def make_link_conflict_messages(count, message_count):
    messages = []
    pair_count = min(message_count, count // 2)
    for msg_id in range(pair_count):
        sender = msg_id * 2
        receiver = sender + 1
        messages.append(
            {
                "id": msg_id,
                "sender": sender,
                "receiver": receiver,
                "size": 24 + (msg_id % 8),
                "timetriggered": True,
                "period": 50,
            }
        )
    return messages


def write_input(base_data, task_count, message_count, filename=None, link_conflict=False):
    jobs = make_jobs(task_count, pinned_pairs=message_count if link_conflict else 0)
    if link_conflict:
        messages = make_link_conflict_messages(task_count, message_count)
    else:
        messages = make_messages(task_count, message_count)
    data = {
        "application": {
            "jobs": jobs,
            "messages": messages,
            "deadline": greedy_deadline(jobs, message_count) + (message_count * 4),
        },
        "platform": add_speed_factors(base_data["platform"]),
        "frequencies": base_data.get("frequencies", []),
        "schemes": base_data.get("schemes", []),
    }
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = INPUT_DIR / (filename or f"{task_count}_{message_count}_input.json")
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    return path


def prompt_int(name, current_value, default, min_value=None):
    if current_value is not None:
        return current_value
    if not sys.stdin.isatty():
        return default

    while True:
        raw_value = input(f"{name} [{default}]: ").strip()
        if not raw_value:
            value = default
        else:
            try:
                value = int(raw_value)
            except ValueError:
                print("Please enter an integer.")
                continue

        if min_value is not None and value < min_value:
            print(f"Please enter a value >= {min_value}.")
            continue
        return value


def resolve_run_config(args):
    start = prompt_int("Start number of tasks", args.start, 20, min_value=1)
    stop = prompt_int("Maximum number of tasks", args.stop, 80, min_value=start)
    min_messages = prompt_int("Minimum messages per file", args.min_messages, 8, min_value=0)
    max_messages = prompt_int("Maximum messages per file", args.max_messages, 12, min_value=min_messages)

    if stop < start:
        raise ValueError("--stop must be greater than or equal to --start.")
    if max_messages < min_messages:
        raise ValueError("--max-messages must be greater than or equal to --min-messages.")
    if min_messages > 0 and start < 2:
        raise ValueError("At least 2 tasks are required when messages are requested.")
    if max_messages >= start:
        raise ValueError("Maximum messages must be less than the starting task count.")

    return start, stop, min_messages, max_messages


def output_path_for(input_path):
    return OUTPUT_DIR / f"{input_path.stem}_smt_output.json"


def run_scheduler(scheduler, input_path, timeout_seconds, workers):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_output = output_path_for(input_path)
    root_output = Path("output") / f"{input_path.stem}_smt_output.json"
    command = [
        sys.executable,
        str(scheduler),
        str(input_path),
        "--output-file",
        str(target_output),
        "--workers",
        str(workers),
    ]
    
    start_time_epoch = time.time()
    start_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time_epoch))
    started_at = time.perf_counter()
    
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        elapsed = time.perf_counter() - started_at
    except subprocess.TimeoutExpired:
        end_time_epoch = time.time()
        end_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time_epoch))
        
        timeout_minutes = timeout_seconds / 60.0
        if timeout_minutes.is_integer():
            timeout_minutes_str = f"{int(timeout_minutes)}min"
        else:
            timeout_minutes_str = f"{timeout_minutes:.1f}min"
            
        print(f"\nscheduler timeout exceeded {timeout_minutes_str}", flush=True)
        print(f"Start time of scheduler: {start_time_str}", flush=True)
        print(f"End time of scheduler:   {end_time_str}", flush=True)
        
        # Cleanly terminate process tree on Windows using taskkill to avoid hanging
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        except Exception:
            process.kill()
            
        sys.exit(1)

    result = {
        "status": "ok" if process.returncode == 0 and target_output.exists() else "failed",
        "elapsed_seconds": elapsed,
        "makespan": None,
        "stdout_tail": stdout[-1000:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else "",
        "workers": workers,
    }
    if target_output.exists():
        schedule = json.loads(target_output.read_text(encoding="utf-8"))
        result["makespan"] = schedule.get("optimal_makespan")
        result["scheduler_reported_seconds"] = schedule.get("schedule_calculation_seconds")
        result["candidates_checked"] = schedule.get("candidates_checked")
        result["search_lower_bound"] = schedule.get("search_lower_bound")
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
                "workers",
                "candidates_checked",
                "search_lower_bound",
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
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--stop", type=int, default=None)
    parser.add_argument("--step", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--min-messages", type=int, default=None)
    parser.add_argument("--max-messages", type=int, default=None)
    parser.add_argument("--message-phase", action="store_true")
    parser.add_argument("--workers", type=int, default=None, help="Parallel scheduler workers/cores.")
    args = parser.parse_args()

    start, stop, min_messages, max_messages = resolve_run_config(args)
    workers = prompt_int("Number of workers/cores", args.workers, 3, min_value=1)
    base_data = json.loads(BASE_INPUT.read_text(encoding="utf-8"))
    scheduler = Path(args.scheduler)
    results = []
    # Avoid overwriting a previous 3/6/10-worker benchmark when the caller
    # leaves the default label unchanged.
    label = f"{args.label}_w{workers}"

    for task_count in range(start, stop + 1, args.step):
        message_count = message_count_for_task(task_count, min_messages, max_messages)
        input_path = write_input(base_data, task_count, message_count)
        run = run_scheduler(scheduler, input_path, args.timeout, workers)
        run.update({"file": input_path.name, "tasks": task_count, "messages": message_count})
        results.append(run)
        print(f'{input_path.name}: {run["status"]}, time={run["elapsed_seconds"]:.3f}s, makespan={run["makespan"]}', flush=True)
        if run["status"] != "ok":
            print(f"\n--- SUBPROCESS FAILED FOR {input_path.name} ---")
            print("STDOUT tail:")
            print(run.get("stdout_tail", "No stdout captured"))
            print("STDERR tail:")
            print(run.get("stderr_tail", "No stderr captured"))
            print("-" * 50, flush=True)
            break

    if args.message_phase:
        ok_task_counts = [row["tasks"] for row in results if row["status"] == "ok"]
        if ok_task_counts:
            task_count = max(ok_task_counts)
            for message_count in range(min_messages, min(max_messages, task_count - 1) + 1):
                input_path = write_input(base_data, task_count, message_count)
                run = run_scheduler(scheduler, input_path, args.timeout, workers)
                run.update({"file": input_path.name, "tasks": task_count, "messages": message_count})
                results.append(run)
                print(f'{input_path.name}: {run["status"]}, time={run["elapsed_seconds"]:.3f}s, makespan={run["makespan"]}', flush=True)
                if run["status"] != "ok":
                    break

    json_path, csv_path = save_results(results, label)
    plot_path = plot_results(results, label)
    print(f"results_json={json_path}")
    print(f"results_csv={csv_path}")
    if plot_path:
        print(f"plot={plot_path}")


if __name__ == "__main__":
    main()
