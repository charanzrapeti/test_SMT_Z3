import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
import shutil
import time
from pathlib import Path
from z3 import *
from util.KPathFinding2 import compute_k_paths

# ── module-level setup (safe to run in workers too) ──
DEFAULT_INPUT_FILE = "./input/job_stress_test/57_8.json"


def load_input(input_path):
    with open(input_path, "r") as f:
        return json.load(f)


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

adj = []
undirected_links = set()
path_data = {}
num_jobs = 0
num_msgs = 0
node_speed_factors = {}





def configure_runtime(input_path):
    global input_file, data, jobs_data, messages_data, platform_nodes, app_deadline
    global endsystems, switches, all_nodes, num_endsystems, num_switches, num_nodes
    global node_to_idx, idx_to_node, es_real_to_esidx, adj, undirected_links
    global path_data, num_jobs, num_msgs, node_speed_factors

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



    path_data = compute_k_paths(input_file, k=1)
    num_jobs  = len(jobs_data)
    num_msgs  = len(messages_data)
    node_speed_factors = {
        node["id"]: node.get("speed_factor", 1)
        for node in platform_nodes
        if not node["is_router"]
    }


def normalized_processing_times(job):
    allowed_nodes = job["can_run_on"]
    processing_times = job.get("processing_times")

    if isinstance(processing_times, list) and len(processing_times) == len(allowed_nodes):
        return [math.ceil(value) for value in processing_times]
    

    # return [
    #     math.ceil(job["wcet_fullspeed"] * node_speed_factors.get(node_id, 1))
    #     for node_id in allowed_nodes
    # ]


def job_duration_options(job):
    return {
        es_real_to_esidx[node_id]: duration
        for node_id, duration in zip(job["can_run_on"], job["processing_times"])
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


def worker_try_T(T):
    return try_T(T)


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


def max_expr(expressions):
    if not expressions:
        return 0
    result = expressions[-1]
    for expr in reversed(expressions[:-1]):
        result = If(expr >= result, expr, result)
    return result


def compute_lmin(jobs_data, messages_data):
    job_wcet     = {job["id"]: min(normalized_processing_times(job)) for job in jobs_data}
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


def build_routing_options(sender_job, receiver_job):
    
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
                # an error has to be raised here
                raise ValueError(f"Path not found for nodes: {path_key}")
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
                
   
    return routing_options


def build_and_solve(T, optimization_options=None):
    optimization_options = optimization_options or []

    solver = Optimize() if optimization_options else Solver()
    # solver.set("timeout", 1800000)

    # ============================================================
    # JOB VARIABLES
    # ============================================================

    job_assigned_es = [Int(f"job_{i}_endsystem") for i in range(num_jobs)]
    job_start_time = [Int(f"job_{i}_start") for i in range(num_jobs)]

    # ============================================================
    # MESSAGE VARIABLES
    # ============================================================

    msg_inject_time = [Int(f"msg_{mid}_inject") for mid in range(num_msgs)]
    msg_arrival_time = [Int(f"msg_{mid}_arrival") for mid in range(num_msgs)]
    msg_path_choice = [Int(f"msg_{mid}_path_choice") for mid in range(num_msgs)]

    hop_times = {}

    # ============================================================
    # JOB DOMAIN CONSTRAINTS
    # ============================================================

    for i, job in enumerate(jobs_data):
        allowed = [es_real_to_esidx[rid] for rid in job["can_run_on"] if rid in es_real_to_esidx]
        if not allowed: return False, None
        solver.add(Or([job_assigned_es[i] == x for x in allowed]))
        duration = job_duration_expr(i, job_assigned_es[i])
        solver.add(job_start_time[i] >= 0)
        solver.add(job_start_time[i] + duration <= T)

    # ============================================================
    # CPU MUTUAL EXCLUSION
    # ============================================================

    for i in range(num_jobs):
        for j in range(i + 1, num_jobs):
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

    edge_usage = {}
    # ============================================================
    # MESSAGE ROUTING
    # ============================================================

    message_wait_terms = []
    for msg in messages_data:
        mid = msg["id"]
        sender_job = msg["sender"]  
        receiver_job = msg["receiver"]
        sender_duration = job_duration_expr(sender_job, job_assigned_es[sender_job])

        routing_options = build_routing_options(sender_job, receiver_job)
        if not routing_options: return False, None

        solver.add(Or([msg_path_choice[mid] == rid for (rid, _, _, _) in routing_options]))

        solver.add(msg_inject_time[mid] >= job_start_time[sender_job] + sender_duration)
        solver.add(msg_inject_time[mid] < T)
        solver.add(msg_arrival_time[mid] >= msg_inject_time[mid])
        solver.add(msg_arrival_time[mid] < T)

        routing_cases = []
        for (rid, src_es_idx, dst_es_idx, path_nodes) in routing_options:
            conds = [
                job_assigned_es[sender_job] == src_es_idx,
                job_assigned_es[receiver_job] == dst_es_idx,
                msg_path_choice[mid] == rid
            ]
            num_hops = len(path_nodes) - 1
            local_hop_times = []
            for hop in range(num_hops):
                hvar = Int(f"msg_{mid}_hop_{rid}_{hop}")
                local_hop_times.append(hvar)
                solver.add(hvar >= 0, hvar < T)
            hop_times[(mid, rid)] = local_hop_times

            if num_hops > 0: conds.append(local_hop_times[0] == msg_inject_time[mid])
            for h in range(num_hops - 1): conds.append(local_hop_times[h + 1] >= local_hop_times[h] + 1)
            
            route_wait = Sum([local_hop_times[h + 1] - local_hop_times[h] - 1 for h in range(num_hops - 1)]) if num_hops > 1 else 0
            message_wait_terms.append(If(msg_path_choice[mid] == rid, route_wait, 0))

            conds.append(msg_arrival_time[mid] == (local_hop_times[-1] + 1 if num_hops > 0 else msg_inject_time[mid]))
            conds.append(job_start_time[receiver_job] >= msg_arrival_time[mid])

            for h in range(num_hops):
                edge = (min(path_nodes[h], path_nodes[h+1]), max(path_nodes[h], path_nodes[h+1]))
                if edge not in edge_usage: edge_usage[edge] = []
                edge_usage[edge].append((mid, rid, local_hop_times[h]))
            routing_cases.append(And(conds))
        solver.add(Or(routing_cases))

    # ============================================================
    # WIRE CONTENTION
    # ============================================================

    for key, users in edge_usage.items():
        for i in range(len(users)):
            mid_i, rid_i, hop_time_i = users[i]
            for j in range(i + 1, len(users)):
                mid_j, rid_j, hop_time_j = users[j]   
                if mid_i == mid_j: continue
                solver.add(Implies(And(msg_path_choice[mid_i] == rid_i, msg_path_choice[mid_j] == rid_j), hop_time_i != hop_time_j))

    if optimization_options:
        job_finish_exprs = [job_start_time[i] + job_duration_expr(i, job_assigned_es[i]) for i in range(num_jobs)]
        message_latency_terms = [msg_arrival_time[mid] - msg_inject_time[mid] for mid in range(num_msgs)]
        for option in optimization_options:
            if option == "makespan":
                schedule_makespan = Int("optimized_schedule_makespan")
                solver.add(schedule_makespan >= 0, schedule_makespan <= T)
                for f in job_finish_exprs: solver.add(schedule_makespan >= f)
                for a in msg_arrival_time: solver.add(schedule_makespan >= a)
                solver.minimize(schedule_makespan)
            elif option == "resource-usage": solver.minimize(Sum([job_duration_expr(i, job_assigned_es[i]) for i in range(num_jobs)]))
            elif option == "message-wait": solver.minimize(Sum(message_wait_terms) if message_wait_terms else 0)
            elif option == "low-latency": solver.minimize(Sum(message_latency_terms) if message_latency_terms else 0)
            elif option == "job-start": solver.minimize(Sum(job_start_time) if job_start_time else 0)

    result = solver.check()
    if result != sat: return False, None
    return True, solver.model()


def try_T(T, optimization_options=None):

    feasible, model = build_and_solve(T, optimization_options)

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

        es_idx = model[
            Int(f"job_{i}_endsystem")
        ].as_long()

        real_node = endsystems[es_idx]

        start_time = model[
            Int(f"job_{i}_start")
        ].as_long()

        processing_time = job_duration_on_node(job, real_node)

        job_info[job["id"]] = {
            "job_id": job["id"],
            "assigned_node": real_node,
            "start_time": start_time,
            "finish_time": start_time + processing_time,
            "wcet": job["wcet_fullspeed"],
            "processing_time": processing_time,
            "dependencies": job_dependencies[job["id"]],
        }

    # ============================================================
    # MESSAGE INFO
    # ============================================================

    msg_details = []

    for msg in messages_data:

        mid = msg["id"]

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
        default=1,
        help="Number of parallel workers for makespan search."
    )
    args = parser.parse_args()
    optimization_options = normalize_optimization_options(args.optimize)
    scheduler_started_at = time.perf_counter()

    input_file = args.input_file
    configure_runtime(input_file)

    l_min = compute_lmin(jobs_data, messages_data)
    t_max = app_deadline

    SEARCH_LOWER_BOUND = l_min

    low = max(l_min, SEARCH_LOWER_BOUND)
    high = t_max
    best_schedule = None
    optimal_T     = None
    NUM_WORKERS   = args.workers

    with ProcessPoolExecutor(
        max_workers=NUM_WORKERS,
        initializer=configure_runtime,
        initargs=(input_file,),
    ) as executor:
        while low <= high:
            mid = (low + high) // 2

            # build a contiguous candidate block centered near mid
            half = NUM_WORKERS // 2
            a = max(low, mid - half)
            b = min(high, a + NUM_WORKERS - 1)

            candidates = list(range(a, b + 1))
            t_label = f"T = {candidates[0]}" if len(candidates) == 1 else f"T = {candidates}"
            print(f"Checking {t_label} for SAT...", flush=True)

            step_started_at = time.perf_counter()
            results = list(executor.map(worker_try_T, candidates))
            step_seconds = time.perf_counter() - step_started_at

            # collect SAT results
            sat_ts = [t for (t, feasible, sched) in results if feasible]

            if sat_ts:
                t_sat = min(sat_ts)
                print(f"SAT found at T = {t_sat} (took {step_seconds:.2f}s to finish)", flush=True)

                # store schedule for smallest SAT found
                for (t, feasible, sched) in results:
                    if t == t_sat and feasible:
                        optimal_T = t_sat
                        best_schedule = sched
                        break

                # narrow search to values < t_sat
                high = t_sat - 1
            else:
                print(f"UNSAT for {t_label} (took {step_seconds:.2f}s to finish)", flush=True)
                # all tested were UNSAT -> advance lower bound
                low = b + 1

    scheduler_seconds = time.perf_counter() - scheduler_started_at

    if best_schedule is not None:
        optimized_output_file = None
        if optimization_options:
            _, optimized, optimized_schedule = try_T(
                optimal_T,
                optimization_options=optimization_options,
            )
            if optimized:
                best_schedule = optimized_schedule
            scheduler_seconds = time.perf_counter() - scheduler_started_at

        output = {
            "optimal_makespan": optimal_T,
            "schedule_calculation_seconds": round(scheduler_seconds, 6),
            "optimizations": optimization_options,
            "schedule":         best_schedule,
        }
        base_name   = Path(input_file).stem
        output_dir = Path("output")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{base_name}_smt_output.json"
        with open(output_file, "w") as f:
            json.dump(output, f, indent=4)

        if optimization_options:
            optimized_suffix = "_".join(optimization_options).replace("-", "_")
            optimized_output_file = output_dir / f"{base_name}_smt_optimized_{optimized_suffix}.json"
            with open(optimized_output_file, "w") as f:
                json.dump(output, f, indent=4)

        scheduled_output_file = str(output_file)
        if args.output_file:
            out_path = Path(args.output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output_file, args.output_file)
            scheduled_output_file = str(args.output_file)

            if optimization_options:
                output_path = Path(args.output_file)
                copied_optimized_output = output_path.with_name(
                    f"{output_path.stem}_optimized_{optimized_suffix}{output_path.suffix}"
                )
                shutil.copyfile(optimized_output_file, copied_optimized_output)

        print(f"Total time: {scheduler_seconds:.2f} seconds")
        print("SAT found: Yes")
        print(f"Saved file location: {scheduled_output_file}")
    else:
        print(f"Total time: {scheduler_seconds:.2f} seconds")
        print("SAT found: No")

