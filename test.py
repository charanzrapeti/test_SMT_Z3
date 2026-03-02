import json
from z3 import *

# ------------------------
# Load tasks from JSON
# ------------------------
with open("tasks.json", "r") as f:
    data = json.load(f)

tasks = data["tasks"]
n = len(tasks)

# ------------------------
# Create Z3 solver
# ------------------------
solver = Solver()

# ------------------------
# Variables
# ------------------------

# Start times (decision variables)
start = [Int(f"start_{i}") for i in range(n)]

# Node assignment (0 or 1)
node = [Int(f"node_{i}") for i in range(n)]

# ------------------------
# Constraints
# ------------------------

for i, task in enumerate(tasks):

    wcet = task["wcet"]
    deadline = task["deadline"]
    release = task["start_time"]

    # Start after release time
    solver.add(start[i] >= release)

    # Finish before deadline
    solver.add(start[i] + wcet <= deadline)

    # Assign to node 0 or 1
    solver.add(Or(node[i] == 0, node[i] == 1))


# ------------------------
# Non-overlap constraints
# ------------------------

for i in range(n):
    for j in range(i + 1, n):

        wcet_i = tasks[i]["wcet"]
        wcet_j = tasks[j]["wcet"]

        # If tasks are on same node → enforce no overlap
        same_node = node[i] == node[j]

        no_overlap = Or(
            start[i] + wcet_i <= start[j],
            start[j] + wcet_j <= start[i]
        )

        solver.add(Implies(same_node, no_overlap))


# ------------------------
# Solve
# ------------------------

if solver.check() == sat:
    model = solver.model()
    print("Schedule found:\n")

    for i in range(n):
        print(f"Task {i}:")
        print("  Node:", model[node[i]])
        print("  Start:", model[start[i]])
        print("  Finish:", model[start[i]].as_long() + tasks[i]["wcet"])
        print()
else:
    print("No feasible schedule found.")