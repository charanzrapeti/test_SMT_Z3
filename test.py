import json
from z3 import *

from KPathFinding import compute_min_path_costs

# -------------------------
# Load JSON
# -------------------------
with open("example_30T_fixed.json", "r") as f:
    data = json.load(f)

jobs = data["application"]["jobs"]
messages = data["application"]["messages"]
platform_nodes = data["platform"]["nodes"]

# -------------------------
# Extract compute nodes (non-routers only)
# -------------------------
compute_nodes = [n["id"] for n in platform_nodes if not n["is_router"]]
compute_nodes = sorted(compute_nodes)

num_nodes = len(compute_nodes)
n = len(jobs)

# Map real node IDs <-> solver indices
node_id_to_index = {nid: idx for idx, nid in enumerate(compute_nodes)}
index_to_node_id = {idx: nid for nid, idx in node_id_to_index.items()}

# Get Paths from KPathFinding
min_path_cost = compute_min_path_costs("example_30T_fixed.json", k=2)


# Build cost matrix aligned to solver node indices
cost_matrix = [[0 for _ in range(num_nodes)] for _ in range(num_nodes)]

for src_real in compute_nodes:
    for dst_real in compute_nodes:

        src_idx = node_id_to_index[src_real]
        dst_idx = node_id_to_index[dst_real]

        # Take shortest path only
        cost_matrix[src_idx][dst_idx] = min_path_cost[(src_real, dst_real)][0]




# ------ visualization purpose only
# -------------------------
# Build dependency map
# -------------------------
# job_id -> list of dependency job_ids
dependencies = {job["id"]: [] for job in jobs}

for msg in messages:
    sender = msg["sender"]
    receiver = msg["receiver"]

    if receiver in dependencies:
        dependencies[receiver].append(sender)

all_nodes_set = set()

for job in jobs:
        for nid in job["can_run_on"]:
            all_nodes_set.add(nid)

all_nodes_list = sorted(list(all_nodes_set))



#-------------------------------------------

# -------------------------
# Create solver
# -------------------------
solver = Solver()

start = [Int(f"start_{i}") for i in range(n)]
node = [Int(f"node_{i}") for i in range(n)]

# -------------------------
# Build Z3 CostArray to represent the cost matrix
# -------------------------
CostArray = Array('CostArray', IntSort(), ArraySort(IntSort(), IntSort()))

cost_array_expr = CostArray

for i in range(num_nodes):
    row_array = K(IntSort(), 0)
    for j in range(num_nodes):
        row_array = Store(row_array, j, cost_matrix[i][j])
    cost_array_expr = Store(cost_array_expr, i, row_array)

solver.add(CostArray == cost_array_expr)

# -------------------------
# Job constraints
# -------------------------
for i, job in enumerate(jobs):

    wcet = job["wcet_fullspeed"]
    deadline = job["deadline"]
    allowed_real_nodes = job["can_run_on"]

    allowed_indices = [
        node_id_to_index[nid]
        for nid in allowed_real_nodes
        if nid in node_id_to_index
    ]

    solver.add(start[i] >= 0)
    solver.add(start[i] + wcet <= deadline)

    solver.add(node[i] >= 0, node[i] < num_nodes)
    solver.add(Or([node[i] == k for k in allowed_indices]))

# -------------------------
# Non-overlap constraints
# -------------------------
for i in range(n):
    for j in range(i + 1, n):

        wcet_i = jobs[i]["wcet_fullspeed"]
        wcet_j = jobs[j]["wcet_fullspeed"]

        same_node = node[i] == node[j]

        no_overlap = Or(
            start[i] + wcet_i <= start[j],
            start[j] + wcet_j <= start[i]
        )

        solver.add(Implies(same_node, no_overlap))

# -------------------------
# Dependency constraints (NO mapping used)
# -------------------------
for msg in messages:

    sender = msg["sender"]
    receiver = msg["receiver"]
    sender_wcet = jobs[sender]["wcet_fullspeed"]
    comm_cost = Select(
    Select(CostArray, node[sender]),
    node[receiver]
)

    # Since job_id == index, we use directly
    solver.add(
        start[receiver] >= start[sender] + sender_wcet + comm_cost
    )

# -------------------------
# Solve
# -------------------------
if solver.check() == sat:
    model = solver.model()

    output_schedule = {
        "schedule": []
    }

    for i in range(n):

        assigned_index = model[node[i]].as_long()
        assigned_real_node = index_to_node_id[assigned_index]

        start_time = model[start[i]].as_long()
        wcet = jobs[i]["wcet_fullspeed"]
        finish_time = start_time + wcet

        output_schedule["schedule"].append({
            "job_id": i,
            "assigned_node":  f"p{assigned_real_node}",
            "start_time": start_time,
            "wcet_fullspeed": wcet,
            "finish_time": finish_time,
            "dependencies": dependencies[i]
        })

        output_schedule["nodes"] = [f"p{nid}" for nid in all_nodes_list]

    with open("schedule_output30T.json", "w") as f:
        json.dump(output_schedule, f, indent=4)

    print("Feasible schedule found. Output written to schedule_output.json")

else:
    print("No feasible schedule found.")