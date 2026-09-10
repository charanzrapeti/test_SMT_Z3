
import argparse
import json
import math
import time
from pathlib import Path

from z3 import *
from util.KPathFinding2 import compute_k_paths


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_INPUT_FILE = "./input/job_stress_test/57_8.json"


# ============================================================
# MODULE-LEVEL DATA
# ============================================================

input_file = None
data = {}

jobs_data = []
messages_data = []
platform_nodes = []
app_deadline = 0

endsystems = []
switches = []
all_nodes = []

num_endsystems = 0
num_switches = 0
num_nodes = 0

node_to_idx = {}
idx_to_node = {}
es_real_to_esidx = {}

path_data = {}
num_jobs = 0
num_msgs = 0


# ============================================================
# INPUT
# ============================================================

def load_input(input_path):
    with open(input_path, "r") as f:
        return json.load(f)


def configure_runtime(input_path):
    global input_file
    global data
    global jobs_data
    global messages_data
    global platform_nodes
    global app_deadline
    global endsystems
    global switches
    global all_nodes
    global num_endsystems
    global num_switches
    global num_nodes
    global node_to_idx
    global idx_to_node
    global es_real_to_esidx
    global path_data
    global num_jobs
    global num_msgs

    input_file = str(input_path)
    data = load_input(input_file)

    jobs_data = data["application"]["jobs"]
    messages_data = data["application"]["messages"]
    platform_nodes = data["platform"]["nodes"]
    app_deadline = data["application"]["deadline"]

    endsystems = sorted(
        [n["id"] for n in platform_nodes if not n["is_router"]]
    )

    switches = sorted(
        [n["id"] for n in platform_nodes if n["is_router"]]
    )

    all_nodes = endsystems + switches

    num_endsystems = len(endsystems)
    num_switches = len(switches)
    num_nodes = len(all_nodes)

    node_to_idx = {
        real_id: idx
        for idx, real_id in enumerate(all_nodes)
    }

    idx_to_node = {
        idx: real_id
        for real_id, idx in node_to_idx.items()
    }

    es_real_to_esidx = {
        real_id: i
        for i, real_id in enumerate(endsystems)
    }

    path_data = compute_k_paths(input_file, k=1)

    num_jobs = len(jobs_data)
    num_msgs = len(messages_data)


# ============================================================
# JOB DURATION
# ============================================================

def normalized_processing_times(job):
    allowed_nodes = job["can_run_on"]
    processing_times = job.get("processing_times")

    if (
        isinstance(processing_times, list)
        and len(processing_times) == len(allowed_nodes)
    ):
        return [math.ceil(value) for value in processing_times]

    return None


def job_duration_options(job):
    return {
        es_real_to_esidx[node_id]: duration
        for node_id, duration in zip(
            job["can_run_on"],
            job["processing_times"]
        )
        if node_id in es_real_to_esidx
    }


def job_duration_expr(job_index, assigned_es_expr):
    options = job_duration_options(jobs_data[job_index])

    duration = jobs_data[job_index]["wcet_fullspeed"]

    for es_idx, processing_time in reversed(list(options.items())):
        duration = If(
            assigned_es_expr == es_idx,
            processing_time,
            duration
        )

    return duration


# ============================================================
# ROUTING
# ============================================================

def build_routing_options(sender_job, receiver_job):

    routing_options = []
    option_counter = 0

    sender_allowed = [
        rid
        for rid in jobs_data[sender_job]["can_run_on"]
        if rid in es_real_to_esidx
    ]

    receiver_allowed = [
        rid
        for rid in jobs_data[receiver_job]["can_run_on"]
        if rid in es_real_to_esidx
    ]

    for src_real in sender_allowed:

        for dst_real in receiver_allowed:

            src_es_idx = es_real_to_esidx[src_real]
            dst_es_idx = es_real_to_esidx[dst_real]

            path_key = (src_real, dst_real)

            if path_key not in path_data:
                raise ValueError(
                    f"Path not found for nodes: {path_key}"
                )

            for path in path_data[path_key]["paths"]:

                if not path:
                    continue

                path_nodes = [
                    node_to_idx[x]
                    for x in path
                ]

                routing_options.append(
                    (
                        option_counter,
                        src_es_idx,
                        dst_es_idx,
                        path_nodes
                    )
                )

                option_counter += 1

    return routing_options


# ============================================================
# SMT SOLVER
# ============================================================

def build_and_solve(T, optimization=None):

    # --------------------------------------------------------
    # Select solver
    # --------------------------------------------------------

    if optimization == "makespan":
        solver = Optimize()
    else:
        solver = Solver()

    # ========================================================
    # JOB VARIABLES
    # ========================================================

    job_assigned_es = [
        Int(f"job_{i}_endsystem")
        for i in range(num_jobs)
    ]

    job_start_time = [
        Int(f"job_{i}_start")
        for i in range(num_jobs)
    ]

    # ========================================================
    # MESSAGE VARIABLES
    # ========================================================

    msg_inject_time = [
        Int(f"msg_{mid}_inject")
        for mid in range(num_msgs)
    ]

    msg_arrival_time = [
        Int(f"msg_{mid}_arrival")
        for mid in range(num_msgs)
    ]

    msg_path_choice = [
        Int(f"msg_{mid}_path_choice")
        for mid in range(num_msgs)
    ]

    hop_times = {}

    # ========================================================
    # JOB DOMAIN CONSTRAINTS
    # ========================================================

    for i, job in enumerate(jobs_data):

        allowed = [
            es_real_to_esidx[rid]
            for rid in job["can_run_on"]
            if rid in es_real_to_esidx
        ]

        if not allowed:
            return False, None, None

        solver.add(
            Or([
                job_assigned_es[i] == x
                for x in allowed
            ])
        )

        duration = job_duration_expr(
            i,
            job_assigned_es[i]
        )

        solver.add(
            job_start_time[i] >= 0
        )

        solver.add(
            job_start_time[i] + duration <= T
        )

    # ========================================================
    # CPU MUTUAL EXCLUSION
    # ========================================================

    for i in range(num_jobs):

        for j in range(i + 1, num_jobs):

            duration_i = job_duration_expr(
                i,
                job_assigned_es[i]
            )

            duration_j = job_duration_expr(
                j,
                job_assigned_es[j]
            )

            solver.add(
                Implies(
                    job_assigned_es[i] == job_assigned_es[j],

                    Or(
                        job_start_time[i] + duration_i
                        <= job_start_time[j],

                        job_start_time[j] + duration_j
                        <= job_start_time[i]
                    )
                )
            )

    # ========================================================
    # MESSAGE ROUTING
    # ========================================================

    edge_usage = {}

    for msg in messages_data:

        mid = msg["id"]

        sender_job = msg["sender"]
        receiver_job = msg["receiver"]

        sender_duration = job_duration_expr(
            sender_job,
            job_assigned_es[sender_job]
        )

        routing_options = build_routing_options(
            sender_job,
            receiver_job
        )

        if not routing_options:
            return False, None, None

        # ----------------------------------------------------
        # Message must select one valid route
        # ----------------------------------------------------

        solver.add(
            Or([
                msg_path_choice[mid] == rid
                for rid, _, _, _ in routing_options
            ])
        )

        # ----------------------------------------------------
        # Injection / arrival constraints
        # ----------------------------------------------------

        solver.add(
            msg_inject_time[mid]
            >= job_start_time[sender_job] + sender_duration
        )

        solver.add(
            msg_inject_time[mid] < T
        )

        solver.add(
            msg_arrival_time[mid]
            >= msg_inject_time[mid]
        )

        solver.add(
            msg_arrival_time[mid] < T
        )

        routing_cases = []

        # ----------------------------------------------------
        # Each possible routing option
        # ----------------------------------------------------

        for (
            rid,
            src_es_idx,
            dst_es_idx,
            path_nodes
        ) in routing_options:

            conds = [

                job_assigned_es[sender_job]
                == src_es_idx,

                job_assigned_es[receiver_job]
                == dst_es_idx,

                msg_path_choice[mid]
                == rid
            ]

            num_hops = len(path_nodes) - 1

            local_hop_times = []

            # ------------------------------------------------
            # Create hop timing variables
            # ------------------------------------------------

            for hop in range(num_hops):

                hvar = Int(
                    f"msg_{mid}_hop_{rid}_{hop}"
                )

                local_hop_times.append(hvar)

                solver.add(
                    hvar >= 0,
                    hvar < T
                )

            hop_times[(mid, rid)] = local_hop_times

            # ------------------------------------------------
            # First hop starts when message is injected
            # ------------------------------------------------

            if num_hops > 0:

                conds.append(
                    local_hop_times[0]
                    == msg_inject_time[mid]
                )

            # ------------------------------------------------
            # Consecutive hops
            # ------------------------------------------------

            for h in range(num_hops - 1):

                conds.append(
                    local_hop_times[h + 1]
                    >= local_hop_times[h] + 1
                )

            # ------------------------------------------------
            # Message arrival
            # ------------------------------------------------

            if num_hops > 0:

                conds.append(
                    msg_arrival_time[mid]
                    == local_hop_times[-1] + 1
                )

            else:

                conds.append(
                    msg_arrival_time[mid]
                    == msg_inject_time[mid]
                )

            # Receiver job can only start after message arrives

            conds.append(
                job_start_time[receiver_job]
                >= msg_arrival_time[mid]
            )

            # ------------------------------------------------
            # Register physical link usage
            # ------------------------------------------------

            for h in range(num_hops):

                edge = (
                    min(
                        path_nodes[h],
                        path_nodes[h + 1]
                    ),
                    max(
                        path_nodes[h],
                        path_nodes[h + 1]
                    )
                )

                if edge not in edge_usage:
                    edge_usage[edge] = []

                edge_usage[edge].append(
                    (
                        mid,
                        rid,
                        local_hop_times[h]
                    )
                )

            routing_cases.append(
                And(conds)
            )

        # ----------------------------------------------------
        # One routing case must be active
        # ----------------------------------------------------

        solver.add(
            Or(routing_cases)
        )

    # ========================================================
    # WIRE CONTENTION
    # ========================================================

    for edge, users in edge_usage.items():

        for i in range(len(users)):

            mid_i, rid_i, hop_time_i = users[i]

            for j in range(i + 1, len(users)):

                mid_j, rid_j, hop_time_j = users[j]

                # Same message does not conflict with itself
                if mid_i == mid_j:
                    continue

                solver.add(
                    Implies(

                        And(
                            msg_path_choice[mid_i] == rid_i,
                            msg_path_choice[mid_j] == rid_j
                        ),

                        hop_time_i != hop_time_j
                    )
                )

    # ========================================================
    # MAKESPAN OPTIMIZATION
    # ========================================================

    makespan_expr = None

    if optimization == "makespan":

        schedule_makespan = Int(
            "optimized_schedule_makespan"
        )

        solver.add(
            schedule_makespan >= 0,
            schedule_makespan <= T
        )

        # Every job must finish before makespan

        for i in range(num_jobs):

            finish = (
                job_start_time[i]
                + job_duration_expr(
                    i,
                    job_assigned_es[i]
                )
            )

            solver.add(
                schedule_makespan >= finish
            )

        # Every message must arrive before makespan

        for arrival in msg_arrival_time:

            solver.add(
                schedule_makespan >= arrival
            )

        solver.minimize(schedule_makespan)

        makespan_expr = schedule_makespan

    # ========================================================
    # SOLVE
    # ========================================================

    result = solver.check()

    if result != sat:
        return False, None, None

    model = solver.model()

    # --------------------------------------------------------
    # Get makespan
    # --------------------------------------------------------

    if optimization == "makespan":

        makespan = model.eval(
            makespan_expr
        ).as_long()

    else:

        # Calculate actual makespan from the model

        job_finishes = []

        for i in range(num_jobs):

            start = model.eval(
                job_start_time[i]
            ).as_long()

            duration = model.eval(
                job_duration_expr(
                    i,
                    job_assigned_es[i]
                )
            ).as_long()

            job_finishes.append(
                start + duration
            )

        message_arrivals = [
            model.eval(arrival).as_long()
            for arrival in msg_arrival_time
        ]

        makespan = max(
            job_finishes + message_arrivals,
            default=0
        )

    return True, model, makespan


# ============================================================
# OUTPUT FILE
# ============================================================

def save_schedule_json(output_file, makespan, elapsed_time, model=None):
    schedule_payload = {
        "jobs": [],
        "messages": [],
    }

    if model is not None:
        for i, job in enumerate(jobs_data):
            try:
                assigned = model.eval(job_assigned_es[i])
                assigned_value = int(assigned.as_long())
            except Exception:
                assigned_value = None

            try:
                start = int(model.eval(job_start_time[i]).as_long())
            except Exception:
                start = None

            try:
                duration = int(model.eval(job_duration_expr(i, job_assigned_es[i])).as_long())
            except Exception:
                duration = None

            finish = start + duration if start is not None and duration is not None else None
            assigned_node = None
            if assigned_value is not None:
                if assigned_value < len(endsystems):
                    assigned_node = endsystems[assigned_value]
                else:
                    assigned_node = assigned_value

            schedule_payload["jobs"].append({
                "job_id": job.get("id"),
                "assigned_node": assigned_node,
                "start_time": start,
                "finish_time": finish,
                "wcet": job.get("wcet_fullspeed"),
                "processing_time": duration,
                "dependencies": [],
            })

        for mid, msg in enumerate(messages_data):
            inject_time = None
            arrival_time = None
            path_choice = None

            try:
                inject_time = int(model.eval(msg_inject_time[mid]).as_long())
            except Exception:
                pass

            try:
                arrival_time = int(model.eval(msg_arrival_time[mid]).as_long())
            except Exception:
                pass

            try:
                path_choice = int(model.eval(msg_path_choice[mid]).as_long())
            except Exception:
                pass

            route_details = None
            if path_choice is not None:
                for route_id, src_es_idx, dst_es_idx, path_nodes in build_routing_options(msg["sender"], msg["receiver"]):
                    if route_id == path_choice:
                        route_details = {
                            "route_id": route_id,
                            "source_node": src_es_idx,
                            "destination_node": dst_es_idx,
                            "path_nodes": path_nodes,
                        }
                        break

            schedule_payload["messages"].append({
                "message_id": msg.get("id"),
                "sender": msg.get("sender"),
                "receiver": msg.get("receiver"),
                "inject_time": inject_time,
                "arrive_time": arrival_time,
                "path_choice": path_choice,
                "route": route_details,
            })

    output = {
        "optimal_makespan": makespan,
        "schedule_calculation_seconds": round(elapsed_time, 6),
        "optimizations": ["makespan"],
        "schedule": schedule_payload,
    }

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{Path(output_file).stem}_smt_output.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4)

    return output_file


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Run the SMT scheduler.")
    parser.add_argument(
        "input_file",
        nargs="?",
        default=DEFAULT_INPUT_FILE,
        help="Path to the scheduler input JSON file.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_file)

    configure_runtime(input_path)

    print(
        f"Starting scheduler for file: {input_path}"
    )

    start_time = time.perf_counter()

    # --------------------------------------------------------
    # Choose:
    #
    # None          -> normal SAT solving
    # "makespan"    -> minimize makespan
    # --------------------------------------------------------

    optimization = "makespan"

    sat, model, makespan = build_and_solve(
        T=100000,
        optimization=optimization
    )

    elapsed_time = time.perf_counter() - start_time

    # ========================================================
    # OUTPUT
    # ========================================================

    output_path = save_schedule_json(
        input_path,
        makespan,
        elapsed_time,
        model=model if sat else None,
    )

    if sat:

        print("SAT")
        print(
            f"Scheduler time: {elapsed_time:.3f} seconds"
        )
        print(
            f"Makespan: {makespan}"
        )

    else:

        print("UNSAT")
        print(
            f"Scheduler time: {elapsed_time:.3f} seconds"
        )

    print(f"Saved file location: {output_path}")
