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

    json_files = [
        ("schedule_OptimizeMakespan_30T.json", "Makespan"),
        ("schedule_OptimizeMaxLoad_30T.json", "MaxLoad"),
        ("schedule_OptimizeStartTime_30T.json", "StartTime")
    ]

    plt.figure(figsize=(10,6))

    for file, label in json_files:

        nodes, task_count = compute_tasks_per_node(file)

        y_values = [task_count[node] for node in nodes]

        plt.plot(nodes, y_values, marker='o', linewidth=2, label=label)

    plt.xlabel("Nodes")
    plt.ylabel("Number of Tasks")
    plt.title("Tasks per Node Comparison Across Objectives")

    plt.legend()
    plt.grid(True)

    plt.show()


if __name__ == "__main__":
    main()