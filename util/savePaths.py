import json
from pathlib import Path
import networkx as nx
from itertools import islice


def compute_k_paths(json_file, k=1):
    # -------------------------
    # Load JSON
    # -------------------------
    with open(json_file, "r") as f:
        json_data = json.load(f)

    nodes = json_data["platform"]["nodes"]
    links = json_data["platform"]["links"]

    # -------------------------
    # Build graph
    # -------------------------
    G = nx.Graph()

    for node in nodes:
        G.add_node(node["id"], is_router=node["is_router"])

    for link in links:
        G.add_edge(link["start"], link["end"])

    # -------------------------
    # Compute processor nodes only
    # -------------------------
    processors = [n["id"] for n in nodes if not n["is_router"]]

    # -------------------------
    # K shortest paths
    # -------------------------
    def k_shortest_paths(graph, source, target, k):
        return list(islice(nx.shortest_simple_paths(graph, source, target), k))

    # -------------------------
    # Compute paths
    # -------------------------
    output = []

    for src in processors:
        for dst in processors:

            if src == dst:
                paths = [[src]]
            else:
                try:
                    paths = k_shortest_paths(G, src, dst, k)
                except nx.NetworkXNoPath:
                    paths = []

            # Convert every node id to string
            paths_as_strings = [
                [str(node) for node in path]
                for path in paths
            ]

            output.append(
                {
                    "source": str(src),
                    "destination": str(dst),
                    "paths": paths_as_strings,
                }
            )

    # -------------------------
    # Save JSON
    # -------------------------
    input_path = Path(json_file)

    # Save to ../paths relative to util/
    output_dir = Path(__file__).resolve().parent.parent / "paths"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{input_path.stem}_paths.json"

    with open(output_file, "w") as f:
        json.dump(output, f, indent=4)

    print(f"K paths saved to: {output_file}")

    return output


if __name__ == "__main__":
    compute_k_paths("../input/graph_1 - input.json", k=3)