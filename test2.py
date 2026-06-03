import argparse
import json
from z3 import *
from util.KPathFinding2 import compute_k_paths

# =============================================================================
# LOAD INPUT DATA
# =============================================================================
parser = argparse.ArgumentParser(
    description="Find a feasible/optimal SMT schedule for one input JSON."
)
parser.add_argument(
    "input_file",
    nargs="?",
    default="input/graph_0.json",
    help="Input JSON file. Defaults to input/graph_0.json.",
)
args = parser.parse_args()

input_file = args.input_file
with open(input_file, "r") as f:
    data = json.load(f)

jobs_data       = data["application"]["jobs"]
messages_data   = data["application"]["messages"]
platform_nodes  = data["platform"]["nodes"]
app_deadline    = data["application"]["deadline"]

# =============================================================================
# CLASSIFY NODES
#
# Endsystems  = compute nodes where jobs run (not routers)
# Switches    = routers that forward messages (is_router = True)
#
# We keep them in one list: endsystems first, then switches.
# This matters because job_node variables index into endsystems only,
# while node_time variables index into ALL nodes (endsystems + switches).
#
# Example:
#   endsystems = [1, 2, 3, 7, 11, 15, 16, 17]   (real node IDs)
#   switches   = [4, 5, 6, 8, 9, 10, 12, 13, 14] (real node IDs)
#   all_nodes  = [1,2,3,7,11,15,16,17, 4,5,6,8,9,10,12,13,14]
#
# node_to_idx[real_id] → position in all_nodes list (used in arrays)
# idx_to_node[idx]     → real node ID
# =============================================================================
endsystems  = sorted([n["id"] for n in platform_nodes if not n["is_router"]])
switches    = sorted([n["id"] for n in platform_nodes if     n["is_router"]])
all_nodes   = endsystems + switches   # endsystems come first

num_endsystems = len(endsystems)
num_switches   = len(switches)
num_nodes      = len(all_nodes)

# Map real node ID <-> array index
node_to_idx = {real_id: idx for idx, real_id in enumerate(all_nodes)}
idx_to_node = {idx: real_id for real_id, idx  in node_to_idx.items()}

# Map real endsystem ID -> endsystem-only index (0..num_endsystems-1)
# This is what job_node[i] will range over.
# Example: endsystems=[1,2,3,7] → es_real_to_esidx={1:0, 2:1, 3:2, 7:3}
es_real_to_esidx = {real_id: i for i, real_id in enumerate(endsystems)}

# =============================================================================
# BUILD ADJACENCY MATRIX
#
# adj[i][j] = True means there is a direct physical link between
# node at index i and node at index j (undirected — both directions stored).
# =============================================================================
adj = [[False] * num_nodes for _ in range(num_nodes)]
for link in data["platform"].get("links", []):
    i = node_to_idx[link["start"]]
    j = node_to_idx[link["end"]]
    adj[i][j] = True
    adj[j][i] = True

# =============================================================================
# BUILD UNDIRECTED LINK SET
#
# For collision detection we model each physical wire ONCE.
# We store each link as (smaller_idx, larger_idx) to avoid duplicates.
# Example: link between node-idx 2 and node-idx 5 → stored as (2, 5)
# NOT stored as both (2,5) and (5,2).
# =============================================================================
undirected_links = set()
for ni in range(num_nodes):
    for nj in range(num_nodes):
        if adj[ni][nj]:
            undirected_links.add((min(ni, nj), max(ni, nj)))

def canonical_link(a, b):
    """Return the canonical (smaller, larger) form of a link."""
    return (min(a, b), max(a, b))

# =============================================================================
# LOAD PRECOMPUTED PATHS
#
# path_data[(src_real_id, dst_real_id)] = {
#     'paths': [[src, sw1, sw2, ..., dst], ...],  # list of paths
#     'costs': [2, 4, ...]                          # hops through switches
# }
#
# Each path is a list of REAL node IDs from source endsystem to
# destination endsystem, passing through switches in between.
# The LENGTH of the path - 1 = number of timeframes the message travels.
#
# Example path [1, 4, 5, 2] means:
#   tf+0: message at node 1 (source endsystem)
#   tf+1: message at node 4 (switch)
#   tf+2: message at node 5 (switch)
#   tf+3: message at node 2 (destination endsystem)
# =============================================================================
path_data = compute_k_paths(input_file, k=2)

# =============================================================================
# PROBLEM DIMENSIONS
# =============================================================================
num_jobs = len(jobs_data)
num_msgs = len(messages_data)

# =============================================================================
# COMPUTE LOWER BOUND FOR TIMEFRAMES (l_min)
#
# The minimum number of timeframes we need to try is determined by the
# longest chain of dependent messages in the application.
#
# A "dependency chain" looks like:
#   Job0 --[M0]--> Job1 --[M1]--> Job2 --[M2]--> Job3
#
# Job1 cannot start until M0 arrives.
# Job1 then sends M1. Job2 cannot start until M1 arrives.
# And so on...
#
# The longest such chain gives us l_min — the absolute minimum number
# of timeframes any valid schedule could possibly need.
# Trying T < l_min is pointless; it will always be UNSAT.
#
# How chain() works:
#   chain(mid) = 1 + longest chain starting from the job that receives mid
#
# Example:
#   Messages: M0(Job0→Job1), M1(Job1→Job2), M2(Job2→Job3)
#   chain(M2) = 1  (Job3 sends nothing)
#   chain(M1) = 1 + chain(M2) = 2
#   chain(M0) = 1 + chain(M1) = 3
#   l_min = 3
# =============================================================================
def compute_lmin(messages_data):
    # "Which job receives message mid?"
    msg_receiver = {msg["id"]: msg["receiver"] for msg in messages_data}

    # "Which messages does job j send?"
    msgs_sent_by_job = {}
    for msg in messages_data:
        msgs_sent_by_job.setdefault(msg["sender"], []).append(msg["id"])

    memo = {}
    def chain_length(mid):
        if mid in memo:
            return memo[mid]
        receiving_job = msg_receiver[mid]
        outgoing_msgs = msgs_sent_by_job.get(receiving_job, [])
        if not outgoing_msgs:
            memo[mid] = 1
        else:
            memo[mid] = 1 + max(chain_length(m) for m in outgoing_msgs)
        return memo[mid]

    return max(chain_length(msg["id"]) for msg in messages_data) if messages_data else 1

l_min = compute_lmin(messages_data)
t_max = app_deadline

print(f"Search range: T = {l_min} to {t_max}")

# =============================================================================
# MAIN SCHEDULER: build and solve SMT for exactly T timeframes
#
# The key idea:
#   We do NOT schedule jobs first and then route messages.
#   Everything is solved SIMULTANEOUSLY by the SMT solver.
#
#   The solver picks:
#     - which endsystem each job runs on
#     - when each job starts
#     - which path each message takes
#     - at which timeframe each message is injected
#
#   All of these choices are linked by constraints, so the solver
#   finds a consistent assignment for ALL variables at once.
# =============================================================================
def build_and_solve(T):
    """
    Build the SMT problem for T timeframes and attempt to solve it.
    Returns (True, model) if a valid schedule exists, (False, None) otherwise.
    Timeframes are numbered 0, 1, 2, ..., T-1.
    """
    solver = Solver()

    # =========================================================================
    # DECISION VARIABLES
    # =========================================================================

    # job_assigned_es[i] = endsystem index (0..num_endsystems-1) for job i
    # This is an INDEX into the `endsystems` list, NOT the real node ID.
    # The solver picks this — it represents "where does job i run?"
    job_assigned_es = [Int(f"job_{i}_endsystem") for i in range(num_jobs)]

    # job_start_time[i] = timeframe at which job i starts executing
    # The solver picks this — it represents "when does job i start?"
    job_start_time = [Int(f"job_{i}_start") for i in range(num_jobs)]

    # node_occupied_by[ni][tf] = which message is at node ni at timeframe tf
    # Value is 0 (node idle) or 1..num_msgs (message ID, 1-indexed)
    # We use 1-indexed message IDs so that 0 unambiguously means "idle".
    # Example: node_occupied_by[4][3] = 2 means message 2 is at node 4 at tf 3
    node_occupied_by = [
        [Int(f"node_{ni}_at_tf_{tf}") for tf in range(T)]
        for ni in range(num_nodes)
    ]

    # wire_in_use[tf][(ni,nj)] = True if the wire between ni and nj is
    # carrying a message at timeframe tf (undirected: stored as min,max)
    # This Boolean is shared for BOTH directions of the wire.
    # If wire_in_use[tf][(2,5)] = True, then BOTH 2→5 and 5→2 are blocked.
    wire_in_use = {}
    for tf in range(T):
        for (ni, nj) in undirected_links:
            wire_in_use[(tf, ni, nj)] = Bool(f"wire_{ni}_{nj}_at_tf_{tf}")

    # msg_has_arrived[mid][tf] = mid+1 if message mid has reached its
    # destination by timeframe tf, or 0 if it has not arrived yet.
    # We use mid+1 (not mid) so that message 0's arrival value (1) is
    # distinguishable from "not arrived" (0).
    msg_has_arrived = [
        [Int(f"msg_{mid}_arrived_by_tf_{tf}") for tf in range(T)]
        for mid in range(num_msgs)
    ]

    # =========================================================================
    # CONSTRAINT GROUP A: Variable Domains
    #
    # Restrict all variables to their valid ranges.
    # Without these, the solver might pick nonsensical values like
    # node_occupied_by = -5 or job_assigned_es = 999.
    # =========================================================================

    # A1: node_occupied_by is 0 (idle) or a valid 1-indexed message ID
    for ni in range(num_nodes):
        for tf in range(T):
            solver.add(node_occupied_by[ni][tf] >= 0)
            solver.add(node_occupied_by[ni][tf] <= num_msgs)
            # 0 = idle, 1..num_msgs = message IDs

    # A2: msg_has_arrived is either 0 (not arrived) or mid+1 (arrived)
    for mid in range(num_msgs):
        for tf in range(T):
            solver.add(Or(
                msg_has_arrived[mid][tf] == 0,        # not arrived yet
                msg_has_arrived[mid][tf] == mid + 1   # arrived
            ))

    # =========================================================================
    # CONSTRAINT GROUP B: Message Arrival Semantics
    #
    # B1: Nothing has arrived at timeframe 0 (before any transmission)
    # B2: Arrival is monotone — once a message arrives, it stays arrived.
    #     If msg M arrived by tf=5, then it's also "arrived" at tf=6,7,...
    #     This lets us write simple constraints like:
    #       "job can start if msg_has_arrived[mid][job_start_time] == mid+1"
    # =========================================================================
    for mid in range(num_msgs):
        # B1: Nothing arrived at start
        solver.add(msg_has_arrived[mid][0] == 0)

        # B2: Monotone — arrived stays arrived
        for tf in range(T - 1):
            solver.add(Implies(
                msg_has_arrived[mid][tf] == mid + 1,        # if arrived at tf
                msg_has_arrived[mid][tf + 1] == mid + 1     # still arrived at tf+1
            ))

    # =========================================================================
    # CONSTRAINT GROUP C: Job Placement
    #
    # C1: Each job must be placed on an endsystem it is allowed to run on.
    #     (Respects the "can_run_on" field from the input JSON)
    # C2: Job start time must be >= 0 and job must finish within T timeframes.
    # C3: Two jobs on the SAME endsystem must not overlap in execution time.
    #     (Two jobs on DIFFERENT endsystems can run at the same time — fine!)
    # =========================================================================

    # C1: Job must be placed on an allowed endsystem
    for i, job in enumerate(jobs_data):
        allowed_es_indices = [
            es_real_to_esidx[real_id]
            for real_id in job["can_run_on"]
            if real_id in es_real_to_esidx
        ]
        solver.add(Or([job_assigned_es[i] == k for k in allowed_es_indices]))

    # C2: Job timing within T timeframes
    for i, job in enumerate(jobs_data):
        wcet = job["wcet_fullspeed"]
        solver.add(job_start_time[i] >= 0)
        solver.add(job_start_time[i] + wcet <= T)

    # C3: Non-overlap for jobs sharing an endsystem
    # If job_i and job_j are on the same endsystem, one must finish
    # before the other starts. If they're on different endsystems,
    # no constraint needed — they can run in parallel.
    for i in range(num_jobs):
        for j in range(i + 1, num_jobs):
            wcet_i = jobs_data[i]["wcet_fullspeed"]
            wcet_j = jobs_data[j]["wcet_fullspeed"]
            solver.add(Implies(
                job_assigned_es[i] == job_assigned_es[j],  # same endsystem
                Or(
                    # i finishes before j starts
                    job_start_time[i] + wcet_i <= job_start_time[j],
                    # OR j finishes before i starts
                    job_start_time[j] + wcet_j <= job_start_time[i]
                )
            ))

    # =========================================================================
    # CONSTRAINT GROUP D: Bidirectional Wire Collision
    #
    # A physical wire between nodes A and B can carry at most one message
    # at any timeframe — in EITHER direction.
    #
    # wire_in_use[(tf, A, B)] is a SINGLE Boolean for the wire.
    # If it is True, the wire is busy — no other message can use it
    # in either direction at that timeframe.
    #
    # This is enforced implicitly: since node_occupied_by[ni][tf] is a single
    # integer, only one message can occupy a node at a time. Combined with
    # the path constraints (which set wire_in_use when a message uses a wire),
    # two messages cannot share a wire.
    #
    # BIDIRECTIONAL means: if message M1 uses wire A→B at tf,
    # then message M2 cannot use wire B→A at the same tf.
    # Since both would try to set wire_in_use[(tf,A,B)] = True, but
    # they would also both try to set node_occupied_by[A][tf] or
    # node_occupied_by[B][tf] — and those can only hold one value.
    # The collision is caught at the node level automatically.
    #
    # The explicit wire constraint below adds an extra layer of safety:
    # if wire A-B is in use, mark it in BOTH lookup directions.
    # =========================================================================
    # (No additional constraint needed beyond path constraints below,
    #  because node_occupied_by being a single integer already prevents
    #  two messages at the same node at the same time.)

    # =========================================================================
    # CONSTRAINT GROUP E: Path Routing (The Core Constraint)
    #
    # For each message M (sender job S → receiver job R):
    #
    # We enumerate ALL possible combinations of:
    #   - which endsystem job S is placed on  (src_es)
    #   - which endsystem job R is placed on  (dst_es)
    #   - which path through switches connects src_es to dst_es
    #   - at which timeframe the message is injected (inj_tf)
    #
    # For each combination, we build a "path option" — a conjunction saying:
    #   IF this combination is chosen THEN:
    #     - job S is on src_es
    #     - job R is on dst_es
    #     - sender finishes before injection
    #     - message occupies each node along the path at consecutive tfs
    #     - each wire along the path is marked as in-use
    #     - message is marked as arrived when it reaches dst_es
    #     - receiver job starts AFTER message arrives
    #
    # The solver must choose AT LEAST ONE path option for each message.
    # This is written as: solver.add(Or(all_path_options_for_this_message))
    #
    # IMPORTANT: The path options for DIFFERENT messages interact through
    # the shared node_occupied_by and wire_in_use variables. If message M1
    # wants node 4 at tf 3, and message M2 also wants node 4 at tf 3,
    # the solver will see that node_occupied_by[4][3] cannot equal both
    # M1's id and M2's id — so it will try different combinations.
    # =========================================================================
    for msg in messages_data:
        msg_id_0indexed = msg["id"]
        msg_id_1indexed = msg["id"] + 1  # 1-indexed so 0 means idle in node_occupied_by

        sender_job_idx   = msg["sender"]
        receiver_job_idx = msg["receiver"]
        sender_wcet      = jobs_data[sender_job_idx]["wcet_fullspeed"]

        # Collect all valid path options for this message
        all_options_for_this_msg = []

        # Try every possible (source endsystem, destination endsystem) pair
        for src_es_idx, src_es_real in enumerate(endsystems):
            for dst_es_idx, dst_es_real in enumerate(endsystems):

                if src_es_idx == dst_es_idx:
                    continue  # sender and receiver can't be on same endsystem

                # Get precomputed paths between these two endsystems
                path_key = (src_es_real, dst_es_real)
                if path_key not in path_data:
                    continue
                available_paths = path_data[path_key]["paths"]

                for path in available_paths:
                    # path = [src_es_real, sw1_real, sw2_real, ..., dst_es_real]
                    # len(path) = total nodes visited
                    # The message takes len(path) timeframes to traverse
                    # (one timeframe per node, including src and dst)
                    num_hops = len(path)

                    # Try every possible injection timeframe
                    for inj_tf in range(T):
                        arrival_tf = inj_tf + num_hops - 1

                        if arrival_tf >= T:
                            continue  # message doesn't fit within T timeframes

                        # Build the conjunction for this specific option
                        option_conditions = []

                        # CONDITION 1: Sender job must be on src_es
                        option_conditions.append(
                            job_assigned_es[sender_job_idx] == src_es_idx
                        )

                        # CONDITION 2: Receiver job must be on dst_es
                        option_conditions.append(
                            job_assigned_es[receiver_job_idx] == dst_es_idx
                        )

                        # CONDITION 3: Sender must finish before message is injected
                        # job_start + wcet <= inj_tf means job finishes at or before inj_tf
                        option_conditions.append(
                            job_start_time[sender_job_idx] + sender_wcet <= inj_tf
                        )

                        # CONDITION 4: Message occupies each node along the path
                        # at consecutive timeframes starting from inj_tf.
                        # path[0]=src_es at inj_tf, path[1]=sw1 at inj_tf+1, etc.
                        for step, real_node_id in enumerate(path):
                            ni  = node_to_idx[real_node_id]
                            tf  = inj_tf + step
                            option_conditions.append(
                                node_occupied_by[ni][tf] == msg_id_1indexed
                            )

                        # CONDITION 5: Each wire along the path is marked in-use
                        # path[step] → path[step+1] means wire between them is busy
                        for step in range(len(path) - 1):
                            ni  = node_to_idx[path[step]]
                            nj  = node_to_idx[path[step + 1]]
                            tf  = inj_tf + step
                            link_key = (tf, min(ni, nj), max(ni, nj))
                            if link_key in wire_in_use:
                                option_conditions.append(wire_in_use[link_key])

                        # CONDITION 6: Mark message as arrived at destination timeframe
                        option_conditions.append(
                            msg_has_arrived[msg_id_0indexed][arrival_tf] == msg_id_1indexed
                        )

                        # CONDITION 7: Receiver job starts AFTER message arrives
                        # This is the job dependency constraint:
                        # "Job R cannot start until message M arrives"
                        option_conditions.append(
                            job_start_time[receiver_job_idx] >= arrival_tf + 1
                        )

                        all_options_for_this_msg.append(And(option_conditions))

        # At least one path option must be chosen for this message
        if all_options_for_this_msg:
            solver.add(Or(all_options_for_this_msg))
        else:
            # No valid path exists for this message — immediately impossible
            solver.add(BoolVal(False))
            return False, None

    # =========================================================================
    # SOLVE
    # =========================================================================
    result = solver.check()

    if result == sat:
        return True, solver.model()
    else:
        return False, None


# =============================================================================
# INCREMENTAL SEARCH OVER T
#
# We try T = l_min, l_min+1, l_min+2, ... t_max
# The first T for which the solver returns SAT is the OPTIMAL makespan.
#
# Why is this optimal?
#   - We proved T-1 is UNSAT (no valid schedule exists in fewer timeframes)
#   - We found a valid schedule for T
#   - Therefore T is the minimum possible makespan
#
# Why start at l_min?
#   - Any T < l_min is guaranteed UNSAT due to message dependency chains
#   - Starting there saves time
# =============================================================================
best_model  = None
optimal_T   = None

for T in range(l_min, t_max + 1):
    print(f"Trying T = {T}...")
    feasible, model = build_and_solve(T)

    if feasible:
        print(f"SAT at T = {T} — optimal schedule found!")
        best_model = model
        optimal_T  = T
        break
    else:
        print(f"UNSAT at T = {T} — trying larger T")

# =============================================================================
# EXTRACT AND SAVE SCHEDULE
# =============================================================================
if best_model is not None:
    output = {
        "optimal_makespan": optimal_T,
        "schedule": []
    }

    for i, job in enumerate(jobs_data):
        es_idx      = best_model[Int(f"job_{i}_endsystem")].as_long()
        real_node   = endsystems[es_idx]
        start_time  = best_model[Int(f"job_{i}_start")].as_long()
        wcet        = job["wcet_fullspeed"]

        output["schedule"].append({
            "job_id":        job["id"],
            "assigned_node": real_node,
            "start_time":    start_time,
            "finish_time":   start_time + wcet,
            "wcet":          wcet,
        })

    base_name   = input_file.replace("input/", "").replace(".json", "")
    output_file = f"output/{base_name}_smt_output.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=4)
    print(f"Schedule written to {output_file}")

else:
    print("No feasible schedule exists within the application deadline.")
