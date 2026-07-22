import argparse
import json
import shutil
from pathlib import Path
from z3 import *
from util.KPathFinding2 import compute_k_paths

# ── module-level setup (safe to run in workers too) ──
DEFAULT_INPUT_FILE = "input/graph_0.json"


def load_input(input_path):
    with open(input_path, "r") as f:
        return json.load(f)


input_file = DEFAULT_INPUT_FILE
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
num_jobs  = len(jobs_data)
num_msgs  = len(messages_data)


def compute_lmin(jobs_data, messages_data):
    job_wcet     = {job["id"]: job["wcet_fullspeed"] for job in jobs_data}
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


def build_and_solve(T):

    solver = Solver()
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

    # ============================================================
    # JOB DOMAIN CONSTRAINTS
    # ============================================================

    for i, job in enumerate(jobs_data):

        allowed = [
            es_real_to_esidx[rid]
            for rid in job["can_run_on"]
            if rid in es_real_to_esidx
        ]

        solver.add(
            Or([
                job_assigned_es[i] == x
                for x in allowed
            ])
        )

        wcet = job["wcet_fullspeed"]

        solver.add(job_start_time[i] >= 0)
        solver.add(job_start_time[i] + wcet <= T)

    # ============================================================
    # CPU MUTUAL EXCLUSION
    # ============================================================

    for i in range(num_jobs):

        for j in range(i + 1, num_jobs):

            wcet_i = jobs_data[i]["wcet_fullspeed"]
            wcet_j = jobs_data[j]["wcet_fullspeed"]

            solver.add(
                Implies(
                    job_assigned_es[i] == job_assigned_es[j],
                    Or(
                        job_start_time[i] + wcet_i <= job_start_time[j],
                        job_start_time[j] + wcet_j <= job_start_time[i]
                    )
                )
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

    for msg in messages_data:

        mid = msg["id"]

        sender_job = msg["sender"]
        receiver_job = msg["receiver"]

        sender_wcet = jobs_data[sender_job]["wcet_fullspeed"]

        # --------------------------------------------------------
        # COLLECT VALID ROUTES
        # --------------------------------------------------------

        routing_options = build_routing_options(sender_job, receiver_job)
        

        if not routing_options:
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
            job_start_time[sender_job] + sender_wcet
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

    # ============================================================
    # WIRE CONTENTION
    # ============================================================

    for key, users in edge_usage.items():

        for i in range(len(users)):

            mid_i, rid_i, hop_time_i = users[i]

            for j in range(i + 1, len(users)):

                mid_j, rid_j, hop_time_j = users[j]

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

    # ============================================================
    # NODE CONTENTION
    # ============================================================

    for key, users in node_usage.items():

        for i in range(len(users)):

            mid_i, rid_i, start_i, end_i = users[i]

            for j in range(i + 1, len(users)):

                mid_j, rid_j, start_j, end_j = users[j]

                if mid_i == mid_j:
                    continue

                solver.add(
                    Implies(
                        And(
                            msg_path_choice[mid_i] == rid_i,
                            msg_path_choice[mid_j] == rid_j
                        ),
                        Or(
                            end_i < start_j,
                            end_j < start_i
                        )
                    )
                )

    # ============================================================
    # SOLVE
    # ============================================================

    result = solver.check()

    if result != sat:
        return False, None

    return True, solver.model()

def try_T(T):

    feasible, model = build_and_solve(T)

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

        wcet = job["wcet_fullspeed"]

        job_info[job["id"]] = {
            "job_id": job["id"],
            "assigned_node": real_node,
            "start_time": start_time,
            "finish_time": start_time + wcet,
            "wcet": wcet,
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
    args = parser.parse_args()

    input_file = args.input_file
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
    num_jobs  = len(jobs_data)
    num_msgs  = len(messages_data)

    l_min = compute_lmin(jobs_data, messages_data)
    t_max = app_deadline

    SEARCH_LOWER_BOUND = l_min

    low = max(l_min, SEARCH_LOWER_BOUND)
    high = t_max
    best_schedule = None
    optimal_T     = None

    print(f"Search range: T = {low} to {high}")
    NUM_WORKERS = 8

    while low <= high:
        mid = (low + high) // 2

        # build a contiguous candidate block centered near mid
        half = NUM_WORKERS // 2
        a = max(low, mid - half)
        b = min(high, a + NUM_WORKERS - 1)

        candidates = list(range(a, b + 1))
        print(f"Trying T candidates: {candidates} ...")

        results = [try_T(candidate) for candidate in candidates]

        # collect SAT results
        sat_ts = [t for (t, feasible, sched) in results if feasible]

        if sat_ts:
            t_sat = min(sat_ts)
            print(f"  SAT found at T = {t_sat}")

            # store schedule for smallest SAT found
            for (t, feasible, sched) in results:
                if t == t_sat and feasible:
                    optimal_T = t_sat
                    best_schedule = sched
                    break

            # narrow search to values < t_sat
            high = t_sat - 1
        else:
            print(f"  No SAT in range {a}..{b}")
            # all tested were UNSAT -> advance lower bound
            low = b + 1

    if best_schedule is not None:
        print(f"\nOptimal T = {optimal_T} -- stopping search.")

        output = {
            "optimal_makespan": optimal_T,
            "schedule":         best_schedule,
        }
        base_name   = Path(input_file).stem
        output_file = f"output/{base_name}_smt_output.json"
        with open(output_file, "w") as f:
            json.dump(output, f, indent=4)
        print(f"Schedule written to {output_file}")

        if args.output_file:
            shutil.copyfile(output_file, args.output_file)
            print(f"Schedule copied to {args.output_file}")

        # ── Pretty-print summary to console ──
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
