#!/usr/bin/env python3
"""Single-pass Z3 Optimize makespan solver used by Evaluation 2."""
import argparse
import json
import time
from pathlib import Path

import solver as core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file")
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--log", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    core.configure_runtime(args.input_file, log_enabled=args.log)
    l_min = core.compute_lmin(core.jobs_data, core.messages_data)
    horizon, feasible, schedule, stats = core.try_T(
        core.app_deadline, ["makespan"], collect_stats=True
    )
    elapsed = time.perf_counter() - started
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "sat": bool(feasible and core.schedule_makespan(schedule) < core.app_deadline),
        "solver": "z3_optimize_makespan", "l_min": l_min,
        "deadline": core.app_deadline,
        "optimal_makespan": core.schedule_makespan(schedule) if feasible else None,
        "optimal_time_horizon": horizon if feasible else None,
        "scheduler_compute_time": elapsed, "smt_stats": stats,
        "schedule": schedule if feasible else None,
    }
    temp = output_path.with_name(output_path.name + ".tmp")
    temp.write_text(json.dumps(output, indent=2) + "\n")
    temp.replace(output_path)
    if args.log:
        print(f"[EVAL2] solver=z3_optimize_makespan l_min={l_min} deadline={core.app_deadline}", flush=True)
        print(f"[EVAL2] makespan={output['optimal_makespan']} scheduler_compute_time={elapsed:.6f}s", flush=True)
        print("[EVAL2] SMT stats: " + json.dumps(stats, sort_keys=True), flush=True)
        print(f"[EVAL2] output={output_path}", flush=True)


if __name__ == "__main__":
    main()
