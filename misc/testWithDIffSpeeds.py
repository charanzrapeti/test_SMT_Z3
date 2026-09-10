import json
from z3 import *

from util.KPathFinding import compute_min_path_costs

# -------------------------
# Load JSON
# -------------------------
input_file = "input/example_30T_fixed_with_process_speeds.json"
with open(input_file, "r") as f:
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

# -------------------------
# Extract node speeds
# -------------------------
node_speed = {}

for nnode in platform_nodes:
    if not nnode["is_router"]:
        node_speed[nnode["id"]] = nnode["speed"]

# Map real node IDs <-> solver indices
node_id_to_index = {nid: idx for idx, nid in enumerate(compute_nodes)}
index_to_node_id = {idx: nid for nid, idx in node_id_to_index.items()}

# -------------------------
# Convert speeds to index order
# -------------------------
speed_array = [0]*num_nodes

for nid in compute_nodes:
    idx = node_id_to_index[nid]
    speed_array[idx] = node_speed[nid]

# -------------------------
# Get Paths from KPathFinding
# -------------------------
min_path_cost = compute_min_path_costs("input/example_30T_fixed.json", k=2)

# -------------------------
# Build cost matrix aligned to solver node indices
# -------------------------
cost_matrix = [[0 for _ in range(num_nodes)] for _ in range(num_nodes)]

for src_real in compute_nodes:
    for dst_real in compute_nodes:

        src_idx = node_id_to_index[src_real]
        dst_idx = node_id_to_index[dst_real]

        cost_matrix[src_idx][dst_idx] = min_path_cost[(src_real, dst_real)][0]

# -------------------------
# Build dependency map
# -------------------------
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

# -------------------------
# Create solver
# -------------------------
solver = Solver()

start = [Int(f"start_{i}") for i in range(n)]
node = [Int(f"node_{i}") for i in range(n)]
exec_time = [Int(f"exec_time_{i}") for i in range(n)]

# -------------------------
# Build CostArray
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
# Build SpeedArray
# -------------------------
SpeedArray = Array('SpeedArray', IntSort(), IntSort())

speed_expr = K(IntSort(), 0)

for i in range(num_nodes):
    speed_expr = Store(speed_expr, i, speed_array[i])

solver.add(SpeedArray == speed_expr)

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

    solver.add(node[i] >= 0, node[i] < num_nodes)
    solver.add(Or([node[i] == k for k in allowed_indices]))

    speed = Select(SpeedArray, node[i])

    solver.add(exec_time[i] == wcet / speed)

    solver.add(start[i] + exec_time[i] <= deadline)

# -------------------------
# Non-overlap constraints
# -------------------------
for i in range(n):
    for j in range(i + 1, n):

        exec_i = exec_time[i]
        exec_j = exec_time[j]

        same_node = node[i] == node[j]

        no_overlap = Or(
            start[i] + exec_i <= start[j],
            start[j] + exec_j <= start[i]
        )

        solver.add(Implies(same_node, no_overlap))

# -------------------------
# Dependency constraints
# -------------------------
for msg in messages:

    sender = msg["sender"]
    receiver = msg["receiver"]

    comm_cost = Select(
        Select(CostArray, node[sender]),
        node[receiver]
    )

    solver.add(
        start[receiver] >= start[sender] + exec_time[sender] + comm_cost
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
        speed = node_speed[assigned_real_node]

        exec_t = wcet // speed
        finish_time = start_time + exec_t

        output_schedule["schedule"].append({
            "job_id": i,
            "assigned_node": assigned_real_node,
            "start_time": start_time,
            "wcet_fullspeed": wcet,
            "speed": speed,
            "execution_time": exec_t,
            "finish_time": finish_time,
            "dependencies": dependencies[i]
        })

        output_schedule["nodes"] = all_nodes_list

    # Extract base name from input file
    base_name = input_file.replace("input/", "").replace(".json", "")
    output_file = f"output/{base_name}_output.json"

    with open(output_file, "w") as f:
        json.dump(output_schedule, f, indent=4)

    print("Feasible schedule found. Output written to schedule_output30T_with_Speeds_V2.json")

else:
    print("No feasible schedule found.")