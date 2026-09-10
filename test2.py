"""Single-call makespan optimizer for the scheduler model.

Unlike test2Parallize.py, this module gives Z3 the application deadline as
the feasibility bound and asks Optimize to minimize the makespan in one call.
"""

import argparse
import json
import time
from pathlib import Path

import test2Parallize as base


def schedule_makespan(schedule):
    finish_times = [job["finish_time"] for job in schedule["jobs"]]
    arrival_times = [msg["arrive_timeframe"] for msg in schedule["messages"]]
    return max(finish_times + arrival_times + [0])


def run(input_path, output_file=None):
    started_at = time.perf_counter()
    base.configure_runtime(input_path)

    # build_and_solve creates Optimize when an objective is supplied. The
    # deadline is only a safe upper bound; Optimize finds the minimum inside it.
    feasible, model = base.build_and_solve(base.app_deadline, ["makespan"])
    if not feasible:
        return None

    # Reuse the existing schedule extraction code. It reads the model produced
    # by the single Optimize.check() call above when called through try_T, so
    # extract directly here to avoid a second scheduler invocation.
    job_info = {}
    dependencies = {
        job["id"]: sorted({
            msg["sender"] for msg in base.messages_data
            if msg["receiver"] == job["id"]
        })
        for job in base.jobs_data
    }
    from z3 import Int

    for index, job in enumerate(base.jobs_data):
        assigned_index = model[Int(f"job_{index}_endsystem")].as_long()
        node = base.endsystems[assigned_index]
        start = model[Int(f"job_{index}_start")].as_long()
        duration = base.job_duration_on_node(job, node)
        job_info[job["id"]] = {
            "job_id": job["id"],
            "assigned_node": node,
            "start_time": start,
            "finish_time": start + duration,
            "wcet": job["wcet_fullspeed"],
            "processing_time": duration,
            "dependencies": dependencies[job["id"]],
        }

    msg_details = []
    for msg in base.messages_data:
        mid = msg["id"]
        inject = model[Int(f"msg_{mid}_inject")].as_long()
        arrival = model[Int(f"msg_{mid}_arrival")].as_long()
        route_id = model[Int(f"msg_{mid}_path_choice")].as_long()
        options = base.build_routing_options(msg["sender"], msg["receiver"])
        path_nodes = next(path for rid, _, _, path in options if rid == route_id)
        hops = []
        hop_index = 0
        while True:
            value = model.eval(Int(f"msg_{mid}_hop_{route_id}_{hop_index}"), model_completion=False)
            if str(value) == f"msg_{mid}_hop_{route_id}_{hop_index}":
                break
            hops.append(value.as_long())
            hop_index += 1
        timeline = [{"node": base.idx_to_node[path_nodes[0]], "timeframe": inject}]
        timeline.extend({"node": base.idx_to_node[path_nodes[index + 1]], "timeframe": hop + 1}
                         for index, hop in enumerate(hops))
        msg_details.append({
            "msg_id": mid,
            "sender_job": msg["sender"],
            "receiver_job": msg["receiver"],
            "sender_node": job_info[msg["sender"]]["assigned_node"],
            "receiver_node": job_info[msg["receiver"]]["assigned_node"],
            "inject_timeframe": inject,
            "arrive_timeframe": arrival,
            "path_choice": route_id,
            "hop_times": timeline,
        })

    schedule = {"jobs": list(job_info.values()), "messages": msg_details}
    output = {
        "optimal_makespan": schedule_makespan(schedule),
        "schedule_calculation_seconds": round(time.perf_counter() - started_at, 6),
        "method": "z3_optimize_single_call",
        "optimizations": ["makespan"],
        "schedule": schedule,
    }
    output_path = Path(output_file) if output_file else Path("output") / f"{Path(input_path).stem}_smt_output.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=4), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the one-call Z3 makespan optimizer.")
    parser.add_argument("input_file")
    parser.add_argument("--output-file")
    parser.add_argument("--workers", type=int, default=1, help="Accepted for benchmark compatibility; unused.")
    args = parser.parse_args()
    output_path = run(args.input_file, args.output_file)
    if output_path is None:
        print("SAT found: No")
    else:
        result = json.loads(output_path.read_text(encoding="utf-8"))
        print(f"Total time: {result['schedule_calculation_seconds']:.2f} seconds")
        print(f"Optimal makespan: {result['optimal_makespan']}")
        print(f"Saved file location: {output_path}")