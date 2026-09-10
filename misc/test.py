import json
from z3 import *
import random
import math
from functools import reduce
from collections import defaultdict
from util.KPathFinding2 import compute_k_paths

# =========================================================
# LOAD DATA
# =========================================================
with open("input/example_30T_fixed.json", "r") as f:
    data = json.load(f)

jobs = data["application"]["jobs"]
messages = data["application"]["messages"]
platform_nodes = data["platform"]["nodes"]

compute_nodes = [n["id"] for n in platform_nodes if not n["is_router"]]

node_id_to_index = {n: i for i, n in enumerate(compute_nodes)}
index_to_node_id = {i: n for n, i in node_id_to_index.items()}

n = len(jobs)

# =========================================================
# PATHS
# =========================================================
k_paths = compute_k_paths("input/example_30T_fixed.json", k=2)

# =========================================================
# HYPERPERIOD (CASE B)
# =========================================================
periods = [msg.get("period", 10) for msg in messages]


def lcm(a, b):
    return abs(a*b) // math.gcd(a, b)


H = reduce(lcm, periods)
instances = {i: H // periods[i] for i in range(len(messages))}

# =========================================================
# APPLICATION DEADLINE
# =========================================================
successors = defaultdict(list)
for msg in messages:
    successors[msg["sender"]].append(msg["receiver"])

memo = {}


def critical_path(job_id):
    if job_id in memo:
        return memo[job_id]
    wcet = jobs[job_id]["wcet_fullspeed"]
    if not successors[job_id]:
        memo[job_id] = wcet
    else:
        memo[job_id] = wcet + max(critical_path(r) for r in successors[job_id])
    return memo[job_id]


CP = max(critical_path(i) for i in range(n))
WCET_SUM = sum(job["wcet_fullspeed"] for job in jobs)

ALPHA = 0
APP_DEADLINE = int(CP + ALPHA * (WCET_SUM - CP))

print(f"Critical path:  {CP}")
print(f"WCET sum:       {WCET_SUM}")
print(f"App deadline:   {APP_DEADLINE}  (alpha={ALPHA})")

# =========================================================
# SOLVER
# =========================================================
solver = Solver()

start = [Int(f"start_{i}") for i in range(n)]
node = [Int(f"node_{i}") for i in range(n)]

# =========================================================
# JOB CONSTRAINTS
# =========================================================
for i, job in enumerate(jobs):

    wcet = job["wcet_fullspeed"]

    allowed = [
        node_id_to_index[node_name]
        for node_name in job["can_run_on"]
        if node_name in node_id_to_index
    ]

    assert allowed, f"Job {i} has no valid compute nodes in can_run_on"

    solver.add(start[i] >= 0)
    solver.add(start[i] + wcet <= APP_DEADLINE)
    solver.add(Or([node[i] == a for a in allowed]))

# =========================================================
# CPU NON-OVERLAP
# =========================================================
for i in range(n):
    for j in range(i + 1, n):

        wi = jobs[i]["wcet_fullspeed"]
        wj = jobs[j]["wcet_fullspeed"]

        solver.add(Implies(
            node[i] == node[j],
            Or(
                start[i] + wi <= start[j],
                start[j] + wj <= start[i]
            )
        ))

# =========================================================
# COMMUNICATION MODEL (FIXED ROUTING)
# =========================================================
LINK_TIME = 1

offset = {}
link_usage = {}

for m, msg in enumerate(messages):

    s = msg["sender"]
    r = msg["receiver"]

    
    src = node[s]
    dst = node[r]
   
    entry = k_paths.get((src, dst), None)
    if not entry or not entry["paths"]:
        continue

    path = entry["paths"][0]
    print("print starts here")
    print(src, dst )
    print(path)

    offset[m] = {}

    for h in range(len(path) - 1):

        link = (path[h], path[h + 1])

        offset[m][link] = Int(f"o_{m}_{h}")

        if link not in link_usage:
            link_usage[link] = []

        link_usage[link].append(m)

# =========================================================
# JOB → MESSAGE DEPENDENCY
# =========================================================
for msg in messages:
    s = msg["sender"]
    r = msg["receiver"]

    solver.add(start[r] >= start[s] + jobs[s]["wcet_fullspeed"])

# =========================================================
# CONTENTION (CASE A + B)
# =========================================================
for link, msgs_on_link in link_usage.items():

    for i in range(len(msgs_on_link)):
        for j in range(i + 1, len(msgs_on_link)):

            m1 = msgs_on_link[i]
            m2 = msgs_on_link[j]

            o1 = offset[m1][link]
            o2 = offset[m2][link]

            L1 = LINK_TIME
            L2 = LINK_TIME

            # -------- CASE A --------
            solver.add(
                Or(
                    o1 + L1 <= o2,
                    o2 + L2 <= o1
                )
            )

            # -------- CASE B --------
            P1, P2 = periods[m1], periods[m2]
            I1, I2 = instances[m1], instances[m2]

            for a in range(I1):
                for b in range(I2):

                    solver.add(
                        Or(
                            (a * P1 + o1 + L1) <= (b * P2 + o2),
                            (b * P2 + o2 + L2) <= (a * P1 + o1)
                        )
                    )

# =========================================================
# BUILD DEPENDENCIES (FOR OUTPUT)
# =========================================================
dependencies = {i: [] for i in range(n)}

for msg in messages:
    dependencies[msg["receiver"]].append(msg["sender"])

# =========================================================
# SOLVE
# =========================================================
if solver.check() == sat:

    model = solver.model()

    schedule = []

    for i in range(n):

        ni = model[node[i]].as_long()
        st = model[start[i]].as_long()
        wc = jobs[i]["wcet_fullspeed"]

        schedule.append({
            "job_id": i,
            "assigned_node": f"p{index_to_node_id[ni]}",
            "start_time": st,
            "wcet_fullspeed": wc,
            "finish_time": st + wc,
            "dependencies": dependencies[i]
        })

        

    output = {
        "objective": "Scheduling the jobs",
        "alpha": ALPHA,
        "critical_path": CP,
        "wcet_sum": WCET_SUM,
        "app_deadline": APP_DEADLINE,
        "schedule": schedule,
        "nodes": [f"p{nid}" for nid in compute_nodes]
    }

    with open("schedule_output_paper_model.json", "w") as f:
        json.dump(output, f, indent=4)

    print("✔ FEASIBLE SCHEDULE FOUND (CORRECT FORMAT)")

else:
    print("❌ UNSAT - constraints too tight")
    print(f"  Try increasing ALPHA above {ALPHA}")