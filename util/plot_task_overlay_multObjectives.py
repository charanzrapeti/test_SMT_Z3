import json
import matplotlib.pyplot as plt

# --------------------------------------------------
# Count tasks per node
# --------------------------------------------------
def compute_tasks_per_node(json_file):
    with open(json_file, "r") as f:
        data = json.load(f)

    nodes = data["nodes"]
    schedule = data["schedule"]

    task_count = {node: 0 for node in nodes}

    for job in schedule:
        node = job["assigned_node"]
        task_count[node] += 1

    return nodes, task_count

# --------------------------------------------------
# MAIN
# --------------------------------------------------
def main():

    # ------------------------
    # Two-objective outputs
    # ------------------------
    two_obj_files = [
        ("schedule_Makespan_StartTime_30T.json", "Makespan + StartTime"),
        ("schedule_MaxLoad_StartTime_30T.json", "MaxLoad + StartTime"),
        ("schedule_Makespan_MaxLoad_30T.json", "Makespan + MaxLoad")
    ]

    plt.figure(figsize=(12,7))
    for file, label in two_obj_files:
        nodes, task_count = compute_tasks_per_node(file)
        y_values = [task_count[node] for node in nodes]
        plt.plot(nodes, y_values, marker='o', linewidth=2, label=label)

    plt.xlabel("Nodes")
    plt.ylabel("Number of Tasks")
    plt.title("Tasks per Node Comparison Across Two-Objective Optimizations")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # ------------------------
    # Three-objective output
    # ------------------------
    three_obj_file = ("schedule_allthree_30T.json", "Makespan + MaxLoad + StartTime")

    nodes, task_count = compute_tasks_per_node(three_obj_file[0])
    y_values = [task_count[node] for node in nodes]

    plt.figure(figsize=(12,7))
    plt.plot(nodes, y_values, marker='s', color='red', linewidth=2, label=three_obj_file[1])
    plt.xlabel("Nodes")
    plt.ylabel("Number of Tasks")
    plt.title("Tasks per Node for Three-Objective Optimization")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()