"""Evenly distributed, interruptible parallel makespan search.

Each round samples the current integer interval evenly. A SAT result closes
the interval above it; an UNSAT result closes the interval below it. Workers
are terminated before the next round so stale searches do not consume cores.
"""

import argparse
import json
import multiprocessing as mp
import shutil
import time
from queue import Empty
from pathlib import Path

import test2Parallize as base


def worker(input_path, candidate, result_queue):
    base.configure_runtime(input_path)
    result_queue.put(base.try_T(candidate))


def evenly_spaced(low, high, count):
    count = min(count, high - low + 1)
    if count <= 1:
        return [low]
    return sorted({low + index * (high - low) // (count - 1) for index in range(count)})


def terminate_all(processes):
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join()


def terminate_outside(processes, candidates, low, high):
    for process, candidate in zip(processes, candidates):
        if (candidate < low or candidate > high) and process.is_alive():
            process.terminate()


def collect_round(processes, candidates, result_queue, low, high):
    results = []
    pending = set(range(len(processes)))
    while pending:
        try:
            result = result_queue.get(timeout=0.1)
        except Empty:
            for index in list(pending):
                if not processes[index].is_alive():
                    pending.remove(index)
            continue

        candidate, feasible, schedule = result
        results.append((candidate, feasible, schedule))
        pending.discard(candidates.index(candidate))
        if feasible:
            high = min(high, candidate - 1)
        else:
            low = max(low, candidate + 1)
        # A result only invalidates candidates on the corresponding side.
        terminate_outside(processes, candidates, low, high)
    for process in processes:
        process.join()
    return results, low, high


def run(input_path, workers):
    base.configure_runtime(input_path)
    low, high = base.compute_lmin(base.jobs_data, base.messages_data), base.app_deadline
    best_schedule = None
    optimal = None
    checked = 0
    started_at = time.perf_counter()
    context = mp.get_context("spawn")

    while low <= high:
        candidates = evenly_spaced(low, high, workers)
        result_queue = context.Queue()
        processes = []
        for candidate in candidates:
            process = context.Process(target=worker, args=(str(input_path), candidate, result_queue))
            process.start()
            processes.append(process)

        try:
            results, low, high = collect_round(
                processes, candidates, result_queue, low, high
            )
        finally:
            result_queue.close()

        checked += len(results)
        sat_results = [result for result in results if result[1]]
        if sat_results:
            candidate, _, schedule = min(sat_results, key=lambda result: result[0])
            optimal = candidate
            best_schedule = schedule
        status = f"{len(sat_results)} SAT / {len(results) - len(sat_results)} UNSAT"
        print(f"{input_path}: {status}; next range [{low}, {high}]", flush=True)

    elapsed = time.perf_counter() - started_at
    return {
        "optimal_makespan": optimal,
        "schedule_calculation_seconds": round(elapsed, 6),
        "method": "evenly_spread_interruptible_parallel_search",
        "workers": workers,
        "candidates_checked": checked,
        "search_lower_bound": base.compute_lmin(base.jobs_data, base.messages_data),
        "schedule": best_schedule,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the interruptible evenly-spread parallel scheduler.")
    parser.add_argument("input_file")
    parser.add_argument("--output-file")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    result = run(args.input_file, args.workers)
    output_path = Path(args.output_file) if args.output_file else Path("output") / f"{Path(args.input_file).stem}_smt_output.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=4), encoding="utf-8")
    print(f"Total time: {result['schedule_calculation_seconds']:.2f} seconds")
    print(f"SAT found: {'Yes' if result['schedule'] is not None else 'No'}")
    print(f"Saved file location: {output_path}")