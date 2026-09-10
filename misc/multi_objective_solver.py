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
# Extract compute nodes
# -------------------------
compute_nodes = [n["id"] for n in platform_nodes if not n["is_router"]]
compute_nodes = sorted(compute_nodes)

num_nodes = len(compute_nodes)
n = len(jobs)

node_id_to_index = {nid: idx for idx, nid in enumerate(compute_nodes)}
index_to_node_id = {idx: nid for nid, idx in node_id_to_index.items()}

# -------------------------
# Path costs
# -------------------------
min_path_cost = compute_min_path_costs("example_30T_fixed.json", k=2)

cost_matrix = [[0 for _ in range(num_nodes)] for _ in range(num_nodes)]

for src_real in compute_nodes:
    for dst_real in compute_nodes:
        src_idx = node_id_to_index[src_real]
        dst_idx = node_id_to_index[dst_real]
        cost_matrix[src_idx][dst_idx] = min_path_cost[(src_real, dst_real)][0]

# -------------------------
# Dependency map
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

# ==============================
# TWO OBJECTIVES SOLVER
# ==============================
def solve_two_objectives(obj1, obj2):
    solver = Optimize()
    start = [Int(f"start_{i}") for i in range(n)]
    node = [Int(f"node_{i}") for i in range(n)]

    # Cost array
    CostArray = Array('CostArray', IntSort(), ArraySort(IntSort(), IntSort()))
    cost_array_expr = CostArray
    for i in range(num_nodes):
        row_array = K(IntSort(), 0)
        for j in range(num_nodes):
            row_array = Store(row_array, j, cost_matrix[i][j])
        cost_array_expr = Store(cost_array_expr, i, row_array)
    solver.add(CostArray == cost_array_expr)

    # Job constraints
    for i, job in enumerate(jobs):
        wcet = job["wcet_fullspeed"]
        deadline = job["deadline"]
        allowed_indices = [node_id_to_index[nid] for nid in job["can_run_on"] if nid in node_id_to_index]

        solver.add(start[i] >= 0)
        solver.add(start[i] + wcet <= deadline)
        solver.add(node[i] >= 0, node[i] < num_nodes)
        solver.add(Or([node[i] == k for k in allowed_indices]))

    # Non-overlap constraints
    for i in range(n):
        for j in range(i+1, n):
            same_node = node[i] == node[j]
            no_overlap = Or(
                start[i] + jobs[i]["wcet_fullspeed"] <= start[j],
                start[j] + jobs[j]["wcet_fullspeed"] <= start[i]
            )
            solver.add(Implies(same_node, no_overlap))

    # Dependency constraints
    for msg in messages:
        sender = msg["sender"]
        receiver = msg["receiver"]
        comm_cost = Select(Select(CostArray, node[sender]), node[receiver])
        solver.add(start[receiver] >= start[sender] + jobs[sender]["wcet_fullspeed"] + comm_cost)

    # Metrics
    makespan = Int("makespan")
    for i in range(n):
        solver.add(makespan >= start[i] + jobs[i]["wcet_fullspeed"])

    load = [Int(f"load_{k}") for k in range(num_nodes)]
    max_load = Int("max_load")
    for k in range(num_nodes):
        solver.add(load[k] == Sum([If(node[i] == k, jobs[i]["wcet_fullspeed"], 0) for i in range(n)]))
        solver.add(max_load >= load[k])

    sum_start = Sum(start)

    objectives = {"Makespan": makespan, "MaxLoad": max_load, "StartTime": sum_start}
    solver.minimize(objectives[obj1])
    solver.minimize(objectives[obj2])

    print(f"Solving two objectives: {obj1} + {obj2}")

    if solver.check() == sat:
        model = solver.model()
        output_schedule = {"objective": f"{obj1}_{obj2}", "schedule": []}
        for i in range(n):
            assigned_index = model[node[i]].as_long()
            start_time = model[start[i]].as_long()
            wcet = jobs[i]["wcet_fullspeed"]
            output_schedule["schedule"].append({
                "job_id": i,
                "assigned_node": f"p{index_to_node_id[assigned_index]}",
                "start_time": start_time,
                "wcet_fullspeed": wcet,
                "finish_time": start_time + wcet,
                "dependencies": dependencies[i]
            })
        output_schedule["nodes"] = [f"p{nid}" for nid in all_nodes_list]
        with open(f"schedule_{obj1}_{obj2}_30T.json", "w") as f:
            json.dump(output_schedule, f, indent=4)
        print(f"Output written to schedule_{obj1}_{obj2}_30T.json")
    else:
        print("No feasible schedule found")

# ==============================
# THREE OBJECTIVES SOLVER
# ==============================
def solve_three_objectives():
    solver = Optimize()
    start = [Int(f"start_{i}") for i in range(n)]
    node = [Int(f"node_{i}") for i in range(n)]

    CostArray = Array('CostArray', IntSort(), ArraySort(IntSort(), IntSort()))
    cost_array_expr = CostArray
    for i in range(num_nodes):
        row_array = K(IntSort(), 0)
        for j in range(num_nodes):
            row_array = Store(row_array, j, cost_matrix[i][j])
        cost_array_expr = Store(cost_array_expr, i, row_array)
    solver.add(CostArray == cost_array_expr)

    for i, job in enumerate(jobs):
        wcet = job["wcet_fullspeed"]
        allowed_indices = [node_id_to_index[nid] for nid in job["can_run_on"] if nid in node_id_to_index]
        solver.add(start[i] >= 0)
        solver.add(start[i] + wcet <= job["deadline"])
        solver.add(node[i] >= 0, node[i] < num_nodes)
        solver.add(Or([node[i] == k for k in allowed_indices]))

    for i in range(n):
        for j in range(i+1, n):
            same_node = node[i] == node[j]
            no_overlap = Or(
                start[i] + jobs[i]["wcet_fullspeed"] <= start[j],
                start[j] + jobs[j]["wcet_fullspeed"] <= start[i]
            )
            solver.add(Implies(same_node, no_overlap))

    for msg in messages:
        sender = msg["sender"]
        receiver = msg["receiver"]
        comm_cost = Select(Select(CostArray, node[sender]), node[receiver])
        solver.add(start[receiver] >= start[sender] + jobs[sender]["wcet_fullspeed"] + comm_cost)

    makespan = Int("makespan")
    for i in range(n):
        solver.add(makespan >= start[i] + jobs[i]["wcet_fullspeed"])

    load = [Int(f"load_{k}") for k in range(num_nodes)]
    max_load = Int("max_load")
    for k in range(num_nodes):
        solver.add(load[k] == Sum([If(node[i] == k, jobs[i]["wcet_fullspeed"], 0) for i in range(n)]))
        solver.add(max_load >= load[k])

    sum_start = Sum(start)

    solver.minimize(makespan)
    solver.minimize(max_load)
    solver.minimize(sum_start)

    print("Solving three objectives: Makespan + MaxLoad + StartTime")

    if solver.check() == sat:
        model = solver.model()
        output_schedule = {"objective": "Makespan_MaxLoad_StartTime", "schedule": []}
        for i in range(n):
            assigned_index = model[node[i]].as_long()
            start_time = model[start[i]].as_long()
            wcet = jobs[i]["wcet_fullspeed"]
            output_schedule["schedule"].append({
                "job_id": i,
                "assigned_node": f"p{index_to_node_id[assigned_index]}",
                "start_time": start_time,
                "wcet_fullspeed": wcet,
                "finish_time": start_time + wcet,
                "dependencies": dependencies[i]
            })
        output_schedule["nodes"] = [f"p{nid}" for nid in all_nodes_list]
        with open("schedule_allthree_30T.json", "w") as f:
            json.dump(output_schedule, f, indent=4)
        print("Output written to schedule_allthree_30T.json")
    else:
        print("No feasible schedule found")

# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    # two objectives experiments
    solve_two_objectives("Makespan", "StartTime")
    solve_two_objectives("MaxLoad", "StartTime")
    solve_two_objectives("Makespan", "MaxLoad")

    # three objectives experiment
    solve_three_objectives()