import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import shutil
import time
from pathlib import Path
from z3 import *
from util.KPathFinding2 import compute_k_paths

# ── module-level setup (safe to run in workers too) ──
DEFAULT_INPUT_FILE = "input/graph_0.json"


def load_input(input_path):
    with open(input_path, "r") as f:
        return json.load(f)


input_file = None
data = {}

jobs_data      = []
messages_data  = []
platform_nodes = []
app_deadline   = 0

endsystems = []
switches   = []
all_nodes  = []

num_endsystems = 0
num_switches   = 0
num_nodes      = 0

node_to_idx      = {}
idx_to_node      = {}
es_real_to_esidx = {}

adj = []
undirected_links = set()
path_data = {}
ROUTING_OPTIONS_CACHE = {}
num_jobs  = 0
num_msgs  = 0
node_speed_factors = {}


def configure_runtime(input_path):
    global input_file, data, jobs_data, messages_data, platform_nodes, app_deadline
    global endsystems, switches, all_nodes, num_endsystems, num_switches, num_nodes
    global node_to_idx, idx_to_node, es_real_to_esidx, adj, undirected_links
    global path_data, num_jobs, num_msgs, ROUTING_OPTIONS_CACHE, node_speed_factors

    input_file = str(input_path)
    data = load_input(input_file)

    jobs_data      = data["application"]["jobs"]
    messages_data  = data["application"]["messages"]
    platform_nodes = data["platform"]["nodes"]
    app_deadline   = data["application"]["deadline"]

    endsystems = sorted([n["id"] for n in platform_nodes if not n["is_router"]])
    switches   = sorted([n["id"] for n in platform_nodes if     n["is_router"]])
    all_nodes  = endsystems + switches

    num_endsystems = len(endsystems)
    num_switches   = len(switches)
    num_nodes      = len(all_nodes)

    node_to_idx      = {real_id: idx for idx, real_id in enumerate(all_nodes)}
    idx_to_node      = {idx: real_id for real_id, idx  in node_to_idx.items()}
    es_real_to_esidx = {real_id: i   for i, real_id    in enumerate(endsystems)}

    adj = [[False] * num_nodes for _ in range(num_nodes)]
    for link in data["platform"].get("links", []):
        i = node_to_idx[link["start"]]
        j = node_to_idx[link["end"]]
        adj[i][j] = True
        adj[j][i] = True

    undirected_links = set()
    for ni in range(num_nodes):
        for nj in range(num_nodes):
            if adj[ni][nj]:
                undirected_links.add((min(ni, nj), max(ni, nj)))

    path_data = compute_k_paths(input_file, k=1)
    ROUTING_OPTIONS_CACHE = {}
    num_jobs  = len(jobs_data)
    num_msgs  = len(messages_data)
    node_speed_factors = {
        node["id"]: node.get("speed_factor", 1)
        for node in platform_nodes
        if not node["is_router"]
    }

import math

def normalized_processing_times(job):
    allowed_nodes = job["can_run_on"]
    processing_times = job.get("processing_times")

    if isinstance(processing_times, list) and len(processing_times) == len(allowed_nodes):
        return [math.ceil(value) for value in processing_times]

    return [
        math.ceil(job["wcet_fullspeed"] * node_speed_factors.get(node_id, 1))
        for node_id in allowed_nodes
    ]


def job_duration_options(job):
    return {
        es_real_to_esidx[node_id]: duration
        for node_id, duration in zip(job["can_run_on"], normalized_processing_times(job))
        if node_id in es_real_to_esidx
    }


def job_duration_expr(job_index, assigned_es_expr):
    options = job_duration_options(jobs_data[job_index])
    duration = jobs_data[job_index]["wcet_fullspeed"]
    for es_idx, processing_time in reversed(list(options.items())):
        duration = If(assigned_es_expr == es_idx, processing_time, duration)
    return duration


def job_duration_on_node(job, real_node):
    options = dict(zip(job["can_run_on"], normalized_processing_times(job)))
    return options.get(real_node, job["wcet_fullspeed"])



class VerboseProgress:
    def __init__(self, enabled=False, log_file=None):
        self.enabled = enabled
        self.log_handle = None
        self.detailed = False
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_handle = open(log_path, "w")

    def close(self):
        if self.log_handle:
            self.log_handle.close()

    def emit(self, message):
        if not self.enabled and self.log_handle is None:
            return

        if self.enabled:
            print(message, flush=True)
        if self.log_handle:
            self.log_handle.write(f"{message}\n")
            self.log_handle.flush()

    def step(self, label, done=False, percent=None, detail=None):
        if not self.detailed:
            return

        mark = "[x]" if done else "[ ]"
        parts = [mark, label]
        if percent is not None:
            parts.append(f"{percent:6.2f}%")
        if detail:
            parts.append(str(detail))
        self.emit(" ".join(parts))

    def concise_step(self, percent, label, detail=None):
        line = f"[{percent:>3}%] {label}"
        if detail:
            line = f"{line} - {detail}"
        self.emit(line)

    def headline(self, input_file):
        self.emit(f"INPUT FILE: {input_file}")

    def completion(self, input_file, output_file, makespan, seconds):
        self.emit(
            f"INPUT FILE COMPLETED: {input_file} scheduled"
        )
        self.emit(
            f"OUTPUT FILE: {output_file} | MAKESPAN: {makespan} | TIME TAKEN: {seconds:.3f}s"
        )
        self.emit("-" * 72)
        self.emit("")


def pair_count(size):
    return size * (size - 1) // 2


def count_comparisons(users_by_resource):
    total = 0
    for users in users_by_resource.values():
        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                if users[i][0] != users[j][0]:
                    total += 1
    return total


def compute_lmin(jobs_data, messages_data):
    job_wcet     = {
        job["id"]: min(normalized_processing_times(job))
        for job in jobs_data
    }
    msg_receiver = {msg["id"]: msg["receiver"]       for msg in messages_data}
    msgs_sent_by = {}
    for msg in messages_data:
        msgs_sent_by.setdefault(msg["sender"], []).append(msg["id"])

    memo = {}
    def chain_min_time(job_id):
        if job_id in memo:
            return memo[job_id]
        outgoing_msgs = msgs_sent_by.get(job_id, [])
        if not outgoing_msgs:
            result = job_wcet[job_id]
        else:
            best_downstream = max(
                chain_min_time(msg_receiver[mid]) for mid in outgoing_msgs
            )
            result = job_wcet[job_id] + 1 + best_downstream
        memo[job_id] = result
        return result

    all_receivers = {msg["receiver"] for msg in messages_data}
    root_jobs     = [job["id"] for job in jobs_data if job["id"] not in all_receivers]
    if not root_jobs:
        root_jobs = [job["id"] for job in jobs_data]   

    return max(max(chain_min_time(jid) for jid in root_jobs),
               max(job_wcet[jid] for jid in job_wcet))


def compute_cpu_load_lower_bound(jobs_data, endsystems):
    """Lower bound from total CPU work over the available compute nodes."""
    if not jobs_data or not endsystems:
        return 0
    total_wcet = sum(
        min(normalized_processing_times(job))
        for job in jobs_data
    )
    return (total_wcet + len(endsystems) - 1) // len(endsystems)


def build_routing_options(sender_job, receiver_job):
    cache_key = (sender_job, receiver_job)
    if cache_key in ROUTING_OPTIONS_CACHE:
        return ROUTING_OPTIONS_CACHE[cache_key]
    
    routing_options = []
    option_counter = 0

    sender_allowed = [
        rid for rid in jobs_data[sender_job]["can_run_on"]
        if rid in es_real_to_esidx
    ]

    receiver_allowed = [
        rid for rid in jobs_data[receiver_job]["can_run_on"]
        if rid in es_real_to_esidx
    ]

    for src_real in sender_allowed:

        for dst_real in receiver_allowed:

            src_es_idx = es_real_to_esidx[src_real]
            dst_es_idx = es_real_to_esidx[dst_real]

            path_key = (src_real, dst_real)

            if path_key not in path_data:
                continue

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
                
    ROUTING_OPTIONS_CACHE[cache_key] = routing_options
    return routing_options


def build_and_solve(T, progress=None, optimization_options=None):
    if progress is None:
        progress = VerboseProgress()

    optimization_options = optimization_options or []

    candidate_started_at = time.perf_counter()
    if progress.detailed:
        progress.emit("")
        progress.emit(f"Candidate T={T}: building SMT model")

    solver = Optimize() if optimization_options else Solver()
    solver.set("timeout", 300000)  # 5 minutes per SMT check

    # ============================================================
    # JOB VARIABLES
    # ============================================================

    job_assigned_es = [
        Int(f"job_{i}_endsystem")
        for i in range(num_jobs)
    ]

    job_start_time = [
        Int(f"job_{i}_start")
        for i in range(num_jobs)
    ]

    # ============================================================
    # MESSAGE VARIABLES
    # ============================================================

    #
    # NEW MODEL:
    #
    # Instead of msg_position[mid][tf]
    #
    # We model:
    #
    # hop_time[mid][hop]
    #
    # meaning:
    #
    # timeframe when message starts traversing hop
    #
    # This massively reduces SMT complexity.
    #

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

    #
    # Per-message hop timing variables
    #
    # hop_times[mid] = [ tf0, tf1, tf2 ... ]
    #

    hop_times = {}
    progress.step(
        "Create solver variables",
        done=True,
        percent=10,
        detail=f"jobs={num_jobs}, messages={num_msgs}, nodes={num_nodes}",
    )

    # ============================================================
    # JOB DOMAIN CONSTRAINTS
    # ============================================================

    job_domain_constraints = 0
    for i, job in enumerate(jobs_data):

        allowed = [
            es_real_to_esidx[rid]
            for rid in job["can_run_on"]
            if rid in es_real_to_esidx
        ]

        if not allowed:
            progress.step(
                "Add job domain constraints",
                done=True,
                percent=20,
                detail=f"job {job['id']} has no allowed end systems",
            )
            return False, None

        solver.add(
            Or([
                job_assigned_es[i] == x
                for x in allowed
            ])
        )
        job_domain_constraints += 1

        solver.add(job_start_time[i] >= 0)
        solver.add(job_start_time[i] + job_duration_expr(i, job_assigned_es[i]) <= T)
        job_domain_constraints += 2

    progress.step(
        "Add job domain constraints",
        done=True,
        percent=20,
        detail=f"constraints={job_domain_constraints}",
    )

    # ============================================================
    # CPU MUTUAL EXCLUSION
    # ============================================================

    cpu_comparisons = 0
    cpu_total_comparisons = pair_count(num_jobs)
    for i in range(num_jobs):

        for j in range(i + 1, num_jobs):
            cpu_comparisons += 1

            duration_i = job_duration_expr(i, job_assigned_es[i])
            duration_j = job_duration_expr(j, job_assigned_es[j])

            solver.add(
                Implies(
                    job_assigned_es[i] == job_assigned_es[j],
                    Or(
                        job_start_time[i] + duration_i <= job_start_time[j],
                        job_start_time[j] + duration_j <= job_start_time[i]
                    )
                )
            )

    progress.step(
        "Add CPU mutual-exclusion comparisons",
        done=True,
        percent=35,
        detail=f"comparisons={cpu_comparisons}/{cpu_total_comparisons}",
    )

    # ============================================================
    # STORE CANDIDATE EDGE USAGES
    # ============================================================

    #
    # edge_usage[(ni, nj)] = [(mid, rid, hop_time), ...]
    #
    # Later we add pairwise constraints:
    # if two selected route hops use the same edge, their hop times differ.
    #
    # This avoids creating one Boolean expression per edge per timeframe.
    #

    edge_usage = {}
    node_usage = {}

    # ============================================================
    # MESSAGE ROUTING
    # ============================================================

    route_options_total = 0
    route_case_total = 0
    hop_var_total = 0
    message_wait_terms = []
    for msg in messages_data:

        mid = msg["id"]

        sender_job = msg["sender"]
        receiver_job = msg["receiver"]

        sender_duration = job_duration_expr(sender_job, job_assigned_es[sender_job])

        # --------------------------------------------------------
        # COLLECT VALID ROUTES
        # --------------------------------------------------------

        routing_options = build_routing_options(sender_job, receiver_job)
        route_options_total += len(routing_options)
        

        if not routing_options:
            progress.step(
                "Build message routing constraints",
                done=True,
                percent=55,
                detail=f"message {mid} has no valid routing options",
            )
            return False, None

        # --------------------------------------------------------
        # path choice domain
        # --------------------------------------------------------

        solver.add(
            Or([
                msg_path_choice[mid] == rid
                for (rid, _, _, _) in routing_options
            ])
        )

        # --------------------------------------------------------
        # injection constraints
        # --------------------------------------------------------

        solver.add(
            msg_inject_time[mid]
            >=
            job_start_time[sender_job] + sender_duration
        )

        solver.add(msg_inject_time[mid] >= 0)
        solver.add(msg_inject_time[mid] < T)

        solver.add(msg_arrival_time[mid] >= 0)
        solver.add(msg_arrival_time[mid] < T)

        # --------------------------------------------------------
        # ROUTING CASES
        # --------------------------------------------------------

        routing_cases = []

        for (
            rid,
            src_es_idx,
            dst_es_idx,
            path_nodes
        ) in routing_options:
            route_case_total += 1

            conds = []

            # ----------------------------------------------------
            # assignment consistency
            # ----------------------------------------------------

            conds.append(
                job_assigned_es[sender_job]
                ==
                src_es_idx
            )

            conds.append(
                job_assigned_es[receiver_job]
                ==
                dst_es_idx
            )

            conds.append(
                msg_path_choice[mid] == rid
            )

            # ----------------------------------------------------
            # PATH
            # ----------------------------------------------------

            num_hops = len(path_nodes) - 1

            #
            # create hop timing vars
            #

            local_hop_times = []

            for hop in range(num_hops):
                hop_var_total += 1

                hvar = Int(f"msg_{mid}_hop_{rid}_{hop}")

                local_hop_times.append(hvar)

                solver.add(hvar >= 0)
                solver.add(hvar < T)

            hop_times[(mid, rid)] = local_hop_times

            # ----------------------------------------------------
            # first hop starts at inject time
            # ----------------------------------------------------

            if num_hops > 0:

                conds.append(
                    local_hop_times[0]
                    ==
                    msg_inject_time[mid]
                )

            # ----------------------------------------------------
            # hops ordered
            # ----------------------------------------------------

            #
            # each hop takes 1 timeframe
            #
            # but may wait if wire busy
            #

            for h in range(num_hops - 1):

                conds.append(
                    local_hop_times[h + 1]
                    >=
                    local_hop_times[h] + 1
                )

            if num_hops > 1:
                route_wait = Sum([
                    local_hop_times[h + 1] - local_hop_times[h] - 1
                    for h in range(num_hops - 1)
                ])
            else:
                route_wait = 0
            message_wait_terms.append(
                If(msg_path_choice[mid] == rid, route_wait, 0)
            )

            # ----------------------------------------------------
            # arrival time
            # ----------------------------------------------------

            if num_hops > 0:

                conds.append(
                    msg_arrival_time[mid]
                    ==
                    local_hop_times[-1] + 1
                )

            else:

                conds.append(
                    msg_arrival_time[mid]
                    ==
                    msg_inject_time[mid]
                )

            # ----------------------------------------------------
            # receiver waits
            # ----------------------------------------------------

            conds.append(
                job_start_time[receiver_job]
                >=
                msg_arrival_time[mid]
            )

            # ----------------------------------------------------
            # REGISTER EDGE USAGE
            # ----------------------------------------------------

            for h in range(num_hops):

                ni = path_nodes[h]
                nj = path_nodes[h + 1]

                edge = (
                    min(ni, nj),
                    max(ni, nj)
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

            # ----------------------------------------------------
            # REGISTER NODE OCCUPANCY
            # ----------------------------------------------------

            #
            # A message occupies:
            # - the source node at inject time,
            # - each intermediate node from arrival until next departure,
            # - the destination node at arrival time.
            #
            # Intervals are inclusive over integer timeframes.
            #

            if num_hops == 0:

                node_intervals = [
                    (
                        path_nodes[0],
                        msg_inject_time[mid],
                        msg_inject_time[mid]
                    )
                ]

            else:

                node_intervals = [
                    (
                        path_nodes[0],
                        msg_inject_time[mid],
                        local_hop_times[0]
                    )
                ]

                for node_pos in range(1, len(path_nodes) - 1):

                    node_intervals.append(
                        (
                            path_nodes[node_pos],
                            local_hop_times[node_pos - 1] + 1,
                            local_hop_times[node_pos]
                        )
                    )

                node_intervals.append(
                    (
                        path_nodes[-1],
                        msg_arrival_time[mid],
                        msg_arrival_time[mid]
                    )
                )

            for node_idx, start_expr, end_expr in node_intervals:

                if node_idx not in node_usage:
                    node_usage[node_idx] = []

                node_usage[node_idx].append(
                    (
                        mid,
                        rid,
                        start_expr,
                        end_expr
                    )
                )

            routing_cases.append(
                And(conds)
            )

        solver.add(
            Or(routing_cases)
        )

    progress.step(
        "Build message routing constraints",
        done=True,
        percent=55,
        detail=(
            f"messages={num_msgs}, route_options={route_options_total}, "
            f"route_cases={route_case_total}, hop_vars={hop_var_total}"
        ),
    )

    # ============================================================
    # WIRE CONTENTION
    # ============================================================

    edge_total_comparisons = count_comparisons(edge_usage)
    edge_comparisons = 0
    for key, users in edge_usage.items():

        for i in range(len(users)):

            mid_i, rid_i, hop_time_i = users[i]

            for j in range(i + 1, len(users)):

                mid_j, rid_j, hop_time_j = users[j]

                if mid_i == mid_j:
                    continue

                edge_comparisons += 1

                solver.add(
                    Implies(
                        And(
                            msg_path_choice[mid_i] == rid_i,
                            msg_path_choice[mid_j] == rid_j
                        ),
                        hop_time_i != hop_time_j
                    )
                )

    progress.step(
        "Add wire-contention comparisons",
        done=True,
        percent=70,
        detail=f"comparisons={edge_comparisons}/{edge_total_comparisons}",
    )

    # ============================================================
    # NODE CONTENTION
    # ============================================================
    # Intentionally omitted. Multiple messages may wait/occupy the same
    # end-system or switch node; only wire/edge contention is modeled.

    # ============================================================
    # SECONDARY OPTIMIZATION
    # ============================================================
    if optimization_options:
        job_finish_exprs = [
            job_start_time[i] + job_duration_expr(i, job_assigned_es[i])
            for i in range(num_jobs)
        ]
        message_latency_terms = [
            msg_arrival_time[mid] - msg_inject_time[mid]
            for mid in range(num_msgs)
        ]

        objective_details = []
        for option in optimization_options:
            if option == "makespan":
                schedule_makespan = Int("optimized_schedule_makespan")
                solver.add(schedule_makespan >= 0)
                solver.add(schedule_makespan <= T)
                for finish_expr in job_finish_exprs:
                    solver.add(schedule_makespan >= finish_expr)
                for arrival_expr in msg_arrival_time:
                    solver.add(schedule_makespan >= arrival_expr)
                solver.minimize(schedule_makespan)
                objective_details.append("makespan")
            elif option == "resource-usage":
                solver.minimize(Sum([
                    job_duration_expr(i, job_assigned_es[i])
                    for i in range(num_jobs)
                ]))
                objective_details.append("resource-usage")
            elif option == "message-wait":
                solver.minimize(Sum(message_wait_terms) if message_wait_terms else 0)
                objective_details.append("message-wait")
            elif option == "low-latency":
                solver.minimize(Sum(message_latency_terms) if message_latency_terms else 0)
                objective_details.append("low-latency")
            elif option == "job-start":
                solver.minimize(Sum(job_start_time) if job_start_time else 0)
                objective_details.append("job-start")

        progress.step(
            "Add optimization objectives",
            done=True,
            percent=85,
            detail=", ".join(objective_details),
        )

    # ============================================================
    # SOLVE
    # ============================================================

    progress.step("Run Z3 solver check", done=False, percent=90)
    solve_started_at = time.perf_counter()
    result = solver.check()
    solve_seconds = time.perf_counter() - solve_started_at
    candidate_seconds = time.perf_counter() - candidate_started_at
    progress.step(
        "Run Z3 solver check",
        done=True,
        percent=100,
        detail=(
            f"result={result}, solve_seconds={solve_seconds:.3f}, "
            f"candidate_seconds={candidate_seconds:.3f}"
        ),
    )

    if result != sat:
        return False, None

    return True, solver.model()

def try_T(T, progress=None, optimization_options=None):

    feasible, model = build_and_solve(T, progress, optimization_options)

    if not feasible:
        return T, False, None

    # ============================================================
    # JOB INFO
    # ============================================================

    job_info = {}
    job_dependencies = {
        job["id"]: sorted({
            msg["sender"]
            for msg in messages_data
            if msg["receiver"] == job["id"]
        })
        for job in jobs_data
    }

    for i, job in enumerate(jobs_data):

        sender_job = msg["sender"]
        receiver_job = msg["receiver"]

        sender_node = job_info[sender_job]["assigned_node"]
        receiver_node = job_info[receiver_job]["assigned_node"]

        inject_tf = model[
            Int(f"msg_{mid}_inject")
        ].as_long()

        arrival_tf = model[
            Int(f"msg_{mid}_arrival")
        ].as_long()

        chosen_rid = model[
            Int(f"msg_{mid}_path_choice")
        ].as_long()

        routing_options = build_routing_options(sender_job, receiver_job)
        chosen_path_nodes = None

        for rid, _, _, path_nodes in routing_options:

            if rid == chosen_rid:
                chosen_path_nodes = path_nodes
                break

        if chosen_path_nodes is None:
            return T, False, None

        hop_schedule = []

        hop_idx = 0

        while True:

            var_name = f"msg_{mid}_hop_{chosen_rid}_{hop_idx}"

            var = Int(var_name)

            val = model.eval(var, model_completion=False)

            if val is None or str(val) == var_name:
                break

            hop_schedule.append(val.as_long())

            hop_idx += 1

        path_timeline = []

        if chosen_path_nodes:

            path_timeline.append(
                {
                    "node": idx_to_node[chosen_path_nodes[0]],
                    "timeframe": inject_tf


                }
            )

            for hop_idx, hop_tf in enumerate(hop_schedule):

                path_timeline.append(
                    {
                        "node": idx_to_node[chosen_path_nodes[hop_idx + 1]],
                        "timeframe": hop_tf + 1
                    }
                )

        msg_details.append({

            "msg_id": mid,

            "sender_job": sender_job,
            "receiver_job": receiver_job,

            "sender_node": sender_node,
            "receiver_node": receiver_node,

            "inject_timeframe": inject_tf,
            "arrive_timeframe": arrival_tf,

            "path_choice": chosen_rid,

            "hop_times": path_timeline
        })

    schedule = {
        "jobs": list(job_info.values()),
        "messages": msg_details,
    }

    return T, True, schedule

def worker_try_T(T):
    return try_T(T, VerboseProgress())

def normalize_optimization_options(raw_options):
    aliases = {
        "makespan": "makespan",
        "resource": "resource-usage",
        "resources": "resource-usage",
        "resource-usage": "resource-usage",
        "resource_usage": "resource-usage",
        "message-wait": "message-wait",
        "message_wait": "message-wait",
        "less-message-waiting": "message-wait",
        "low-latency": "low-latency",
        "low_latency": "low-latency",
        "latency": "low-latency",
        "job-start": "job-start",
        "job_start": "job-start",
        "job-start-time": "job-start",
        "job_start_time": "job-start",
    }
    normalized = []
    for option in raw_options or []:
        for item in option:
            key = item.strip().lower()
            if key not in aliases:
                raise ValueError(f"Unknown optimization option: {item}")
            value = aliases[key]
            if value not in normalized:
                normalized.append(value)
    return normalized

# ── CRITICAL: all execution must be inside this guard on Windows ──
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the SMT scheduler.")
    parser.add_argument(
        "input_file",
        nargs="?",
        default=DEFAULT_INPUT_FILE,
        help="Path to the scheduler input JSON file.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional path where the generated schedule JSON should be copied.",
    )
    parser.add_argument(
        "--verbose-progress",
        action="store_true",
        help="Print detailed scheduler progress, comparison counts, and timing.",
    )
    parser.add_argument(
        "--progress-log",
        help="Optional text file where verbose scheduler progress should be saved.",
    )
    parser.add_argument(
        "--optimize",
        nargs="+",
        action="append",
        metavar="OBJECTIVE",
        help=(
            "Optional final optimization pass after the best T is found. "
            "Choices: makespan, resource-usage, message-wait, low-latency, job-start."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of parallel workers for makespan search (default: 10).",
    )
    args = parser.parse_args()
    optimization_options = normalize_optimization_options(args.optimize)
    progress = VerboseProgress(
        enabled=args.verbose_progress,
        log_file=args.progress_log,
    )
    scheduler_started_at = time.perf_counter()
    input_file = args.input_file
    configure_runtime(input_file)

    l_min = compute_lmin(jobs_data, messages_data)
    cpu_load_min = compute_cpu_load_lower_bound(jobs_data, endsystems)
    t_max = app_deadline

    SEARCH_LOWER_BOUND = max(l_min, cpu_load_min)

    low = max(l_min, SEARCH_LOWER_BOUND)
    high = t_max
    search_total = max(1, high - low + 1)
    candidates_checked = 0
    best_schedule = None
    optimal_T     = None

    if args.verbose_progress:
        progress.headline(input_file)
        progress.concise_step(
            10,
            "Loaded input and routing paths",
            f"deadline={app_deadline}, jobs={num_jobs}, messages={num_msgs}, lower_bound={SEARCH_LOWER_BOUND}",
        )
        progress.concise_step(25, "Started makespan search", f"T={low}..{high}")
    else:
        print(f"Search range: T = {low} to {high}")
    NUM_WORKERS = args.workers
    next_progress_mark = 50

    with ProcessPoolExecutor(
        max_workers=NUM_WORKERS,
        initializer=configure_runtime,
        initargs=(input_file,),
    ) as executor:
        while low <= high:
            range_size = high - low + 1
            if range_size <= NUM_WORKERS:
                candidates = list(range(low, high + 1))
            else:
                step = range_size / (NUM_WORKERS + 1)
                candidates = sorted(list(set(
                    low + round(i * step) for i in range(1, NUM_WORKERS + 1)
                )))
                candidates = [c for c in candidates if low <= c <= high]

            a = min(candidates)
            b = max(candidates)

            if not args.verbose_progress:
                print(f"Trying T candidates: {candidates} ...")
            candidates_checked += len(candidates)

            results = list(executor.map(worker_try_T, candidates))

            # collect SAT results
            sat_ts = [t for (t, feasible, sched) in results if feasible]

            if sat_ts:
                t_sat = min(sat_ts)
                if not args.verbose_progress:
                    print(f"  SAT found at T = {t_sat}")

                # store schedule for smallest SAT found
                for (t, feasible, sched) in results:
                    if t == t_sat and feasible:
                        optimal_T = t_sat
                        best_schedule = sched
                        break

                # narrow search to values < t_sat
                high = t_sat - 1

                # Update the lower bound based on the largest UNSAT candidate below t_sat
                unsat_ts = [t for (t, feasible, sched) in results if not feasible and t < t_sat]
                if unsat_ts:
                    low = max(low, max(unsat_ts) + 1)
            else:
                if not args.verbose_progress:
                    print(f"  No SAT in range {low}..{b}")
                # all tested were UNSAT -> advance lower bound
                low = b + 1

            if args.verbose_progress:
                remaining = max(0, high - low + 1)
                search_percent = 25 + int(65 * (1 - (remaining / search_total)))
                while next_progress_mark <= min(90, search_percent):
                    progress.concise_step(
                        next_progress_mark,
                        "Searching candidate makespans",
                        f"checked={candidates_checked}, remaining~={remaining}",
                    )
                    next_progress_mark += 25

    scheduler_seconds = time.perf_counter() - scheduler_started_at

    if best_schedule is not None:
        optimized_output_file = None
        if optimization_options:
            if args.verbose_progress:
                progress.concise_step(90, "Optimizing final schedule", ", ".join(optimization_options))
            else:
                print(f"\nOptimizing final schedule: {', '.join(optimization_options)}")

            _, optimized, optimized_schedule = try_T(
                optimal_T, progress, optimization_options=optimization_options
            )
            if optimized:
                best_schedule = optimized_schedule
            elif not args.verbose_progress:
                print("Optimization pass did not find a schedule; keeping the feasible schedule.")
            scheduler_seconds = time.perf_counter() - scheduler_started_at

        if args.verbose_progress:
            progress.concise_step(90, "Writing schedule output")
        else:
            print(f"\nOptimal T = {optimal_T} -- stopping search.")

        output = {
            "optimal_makespan": optimal_T,
            "schedule_calculation_seconds": round(scheduler_seconds, 6),
            "workers": NUM_WORKERS,
            "candidates_checked": candidates_checked,
            "search_lower_bound": SEARCH_LOWER_BOUND,
            "optimizations": optimization_options,
            "schedule": best_schedule,
        }
        base_name   = Path(input_file).stem
        output_file = f"output/{base_name}_smt_output.json"
        with open(output_file, "w") as f:
            json.dump(output, f, indent=4)
        if not args.verbose_progress:
            print(f"Schedule written to {output_file}")

        if optimization_options:
            optimized_suffix = "_".join(optimization_options).replace("-", "_")
            optimized_output_file = f"output/{base_name}_smt_optimized_{optimized_suffix}.json"
            with open(optimized_output_file, "w") as f:
                json.dump(output, f, indent=4)
            if not args.verbose_progress:
                print(f"Optimized schedule written to {optimized_output_file}")

        scheduled_output_file = output_file
        if args.output_file:
            shutil.copyfile(output_file, args.output_file)
            scheduled_output_file = args.output_file
            if not args.verbose_progress:
                print(f"Schedule copied to {args.output_file}")

            if optimization_options and optimized_output_file:
                output_path = Path(args.output_file)
                copied_optimized_output = output_path.with_name(
                    f"{output_path.stem}_optimized_{optimized_suffix}{output_path.suffix}"
                )
                shutil.copyfile(optimized_output_file, copied_optimized_output)
                if not args.verbose_progress:
                    print(f"Optimized schedule copied to {copied_optimized_output}")

        # ── Pretty-print summary to console ──
        if args.verbose_progress:
            progress.completion(
                input_file,
                scheduled_output_file,
                optimal_T,
                scheduler_seconds,
            )
        else:
            print(f"\n{'='*60}")
            print(f"Optimal makespan T = {optimal_T}")
            print(f"{'='*60}")

            print("\nJOB SCHEDULE:")
            for job in best_schedule["jobs"]:
                print(f"  Job {job['job_id']:>2} | node {job['assigned_node']:>3} | "
                      f"start={job['start_time']:>3}  finish={job['finish_time']:>3}  wcet={job['wcet']}")

            print("\nMESSAGE DETAILS:")
            for msg in best_schedule["messages"]:
                print(f"  Msg {msg['msg_id']:>2} | {msg['sender_node']} -> {msg['receiver_node']} | "
                      f"inject@tf={msg['inject_timeframe']}  arrive@tf={msg['arrive_timeframe']}")

      

    else:
        print("No feasible schedule exists within the application deadline.")

    progress.close()
